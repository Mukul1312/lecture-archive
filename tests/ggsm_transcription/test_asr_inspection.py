"""Contracts for local GGSM ASR evidence and ASR-uncovered inspection."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.ggsm_transcription.asr as asr_module
from scripts.ggsm_transcription.asr import ASRService, DEFAULT_ASR_CONFIGURATION, FfmpegMediaAdapter, LocalFasterWhisperAdapter
from scripts.ggsm_transcription.intake import IntakeService, SourceDownload
from scripts.ggsm_transcription.review import ReviewDeliveryService
from scripts.ggsm_transcription.store import (
    ArtifactValidationError,
    JobStore,
    JobValidationError,
    RepositoryHealthError,
    StageTransitionError,
)


def local_runtime_metadata(
    *,
    snapshot: str = "C:/fake/snapshot",
    faster_whisper: str = "1.2.1",
    execution_mode: str = "local",
    python: str = "fake-python",
    ffmpeg: str = "fake-ffmpeg",
    ffprobe: str = "fake-ffprobe",
) -> dict[str, str]:
    return {
        "execution_mode": execution_mode,
        "model_snapshot": snapshot,
        "faster_whisper": faster_whisper,
        "python": python,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
    }


class FakeSourceAdapter:
    def __init__(self, payload: bytes = b"source audio") -> None:
        self.payload = payload

    def download(self, requested_url: str, staging_path: Path) -> SourceDownload:
        staging_path.write_bytes(self.payload)
        return SourceDownload("https://archive.example/source.mp3", "source.mp3", {"downloader": "fake-download"})

    def probe(self, _source_path: Path) -> dict[str, object]:
        return {
            "duration_seconds": 30.0,
            "codec": "mp3",
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
            "tool_versions": {"downloader": "fake-download", "ffprobe": "fake-ffprobe"},
        }


class FakeModelAdapter:
    def __init__(self, segments: list[dict[str, object]] | None = None) -> None:
        self.segments = segments or [
            {"id": 0, "start": 5.0, "end": 10.0, "text": " First sentence.", "avg_logprob": -0.2,
             "words": [{"start": 5.0, "end": 5.5, "word": " First", "probability": 0.9}]},
            {"id": 1, "start": 12.0, "end": 20.0, "text": " Second sentence.", "avg_logprob": -1.6,
             "compression_ratio": 2.8, "no_speech_prob": 0.8},
        ]
        self.calls: list[tuple[Path, dict[str, object]]] = []

    def transcribe(self, source_path: Path, configuration: dict[str, object]) -> list[dict[str, object]]:
        self.calls.append((source_path, dict(configuration)))
        if source_path.suffix == ".mka":
            return [{"id": 0, "start": 0.0, "end": 0.5, "text": " Span rerun."}]
        return self.segments

    def runtime_metadata(self) -> dict[str, str]:
        return local_runtime_metadata()


class FakeMediaAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, float, float]] = []

    def extract_span(self, source: Path, target: Path, start: float, end: float) -> None:
        self.calls.append((source, target, start, end))
        target.write_bytes(source.read_bytes() + f"{start}:{end}".encode())

    def runtime_metadata(self) -> dict[str, str]:
        return {"execution_mode": "local", "ffmpeg": "fake-ffmpeg", "ffprobe": "fake-ffprobe"}


class ASRContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(Path(self.tmp.name) / "data" / "transcribe")
        self.job = IntakeService(self.store, FakeSourceAdapter()).intake("https://archive.example/lecture")
        self.model = FakeModelAdapter()
        self.media = FakeMediaAdapter()
        self.service = ASRService(self.store, self.model, self.media)

    def _register_direct_full_asr_candidate(
        self,
        job_id: str,
        runtime: dict[str, str],
        metadata_extra: dict[str, object] | None = None,
        configuration: dict[str, object] | None = None,
        raw_metadata: str | None = None,
        raw_jsonl: str | None = None,
    ) -> None:
        state = self.store.load_job(job_id)
        root = self.store.job_root(job_id)
        metadata = {
            "source_sha256": state["source_sha256"],
            "configuration": dict(DEFAULT_ASR_CONFIGURATION) if configuration is None else dict(configuration),
            "runtime": runtime,
        }
        if metadata_extra is not None:
            metadata.update(metadata_extra)
        (root / "asr" / "full.jsonl").write_text(
            raw_jsonl or '{"end": 1.0, "id": 0, "start": 0.0, "text": "direct candidate"}\n',
            encoding="utf-8",
        )
        (root / "asr" / "metadata.json").write_text(
            raw_metadata if raw_metadata is not None else json.dumps(metadata, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.store.transaction(job_id) as transaction:
            transaction.register_artifact("asr/full.jsonl")
            transaction.register_artifact("asr/metadata.json")
            transaction.record_asr_metadata(metadata)

    @staticmethod
    def _replace_retained_intent_payload(intent_path: Path, relative: str, payload: bytes) -> None:
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        intent["outputs"][relative] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "byte_size": len(payload),
            "payload_base64": base64.b64encode(payload).decode("ascii"),
        }
        intent_path.write_text(json.dumps(intent, sort_keys=True) + "\n", encoding="utf-8")

    def _interrupt_full_after_first_final(self, job_id: str) -> tuple[Path, Path, Path]:
        original_atomic = asr_module._atomic_text

        def fail_after_jsonl(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.name == "full.jsonl":
                raise OSError("full JSONL interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
            with self.assertRaises(OSError):
                ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter()).transcribe(job_id)
        root = self.store.job_root(job_id)
        return root, root / "asr" / "full.jsonl", root / "asr" / "metadata.json"

    def _interrupt_rerun_after_first_final(
        self, job_id: str, start: float = 0.0, end: float = 1.0
    ) -> tuple[Path, Path, Path, Path]:
        original_atomic = asr_module._atomic_text

        def fail_after_jsonl(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.parent.name == "reruns" and path.name.endswith(".jsonl"):
                raise OSError("rerun JSONL interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
            with self.assertRaises(OSError):
                ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter()).rerun_span(job_id, start, end)
        root = self.store.job_root(job_id)
        intent_path = next((root / "asr" / "reruns").glob(".*.publication.json"))
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        jsonl_relative = next(relative for relative in intent["outputs"] if relative.endswith(".jsonl"))
        metadata_relative = next(relative for relative in intent["outputs"] if relative.endswith(".metadata.json"))
        return root, root / Path(jsonl_relative), root / Path(metadata_relative), intent_path

    def _redirect_directory(self, path: Path, target: Path) -> None:
        """Install a temporary directory redirect for the callback-ordering regression."""
        try:
            path.symlink_to(target, target_is_directory=True)
            return
        except OSError:
            if os.name != "nt":
                self.skipTest("directory redirects are unavailable")
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            self.skipTest("directory junction creation is unavailable")

    @staticmethod
    def _remove_directory_redirect(path: Path) -> None:
        if not os.path.lexists(path):
            return
        if path.is_symlink():
            path.unlink()
        else:
            os.rmdir(path)

    def test_full_run_uses_the_fixed_configuration_and_records_runtime_metadata(self) -> None:
        # Break caught: a quiet model/configuration change makes a future draft irreproducible.
        result = self.service.transcribe(self.job["job_id"])
        self.assertEqual(self.model.calls[0][1], DEFAULT_ASR_CONFIGURATION)
        self.assertEqual(result["stage"], "asr_ready")
        metadata = json.loads((self.store.job_root(result["job_id"]) / "asr" / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["configuration"], DEFAULT_ASR_CONFIGURATION)
        self.assertEqual(metadata["runtime"]["model_snapshot"], "C:/fake/snapshot")
        self.assertEqual(metadata["source_sha256"], hashlib.sha256(b"source audio").hexdigest())
        self.store.validate_artifact(result["job_id"], "asr/full.jsonl")
        self.store.validate_artifact(result["job_id"], "asr/metadata.json")

    LECTURE_PROMPT = "Śrīmad-Bhāgavatam 6.2.36–37, Śrīla Gour Govinda Swami Mahārāja, Ajāmila, Viṣṇudūtas"

    def _bind_prompt(self, job_id: str, prompt: str) -> None:
        with self.store.transaction(job_id) as transaction:
            transaction.set_initial_prompt(prompt)

    def test_full_run_uses_the_prompt_the_job_declares(self) -> None:
        # Break caught: the fixed configuration could not express an initial_prompt
        # at all, yet both real 1985 transcripts used one -- a per-lecture list of
        # the verse, persons and terms whose spellings ASR would otherwise mangle.
        # A prompt is lecture content, so it belongs to the job, not to a module
        # constant shared by every lecture.
        job_id = self.job["job_id"]
        self._bind_prompt(job_id, self.LECTURE_PROMPT)

        result = self.service.transcribe(job_id)

        self.assertEqual(self.model.calls[0][1]["initial_prompt"], self.LECTURE_PROMPT)
        metadata = json.loads((self.store.job_root(result["job_id"]) / "asr" / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["configuration"]["initial_prompt"], self.LECTURE_PROMPT)
        self.assertEqual(self.store.load_job(job_id)["initial_prompt"], self.LECTURE_PROMPT)

    def test_a_span_rerun_drops_the_prompt_the_full_run_used(self) -> None:
        # Break caught: both real gap-filling passes recorded initial_prompt None
        # while the full pass carried one. A prompt biases a short clip heavily
        # toward its own vocabulary, which is exactly wrong when re-running the
        # seconds ASR already failed to hear. The rule is fixed, not a free choice.
        job_id = self.job["job_id"]
        self._bind_prompt(job_id, self.LECTURE_PROMPT)
        ready = self.service.transcribe(job_id)

        self.service.rerun_span(ready["job_id"], 6, 9)

        self.assertEqual(self.model.calls[0][1]["initial_prompt"], self.LECTURE_PROMPT)
        self.assertIsNone(self.model.calls[-1][1]["initial_prompt"])

    def test_a_prompt_cannot_be_bound_once_asr_evidence_exists(self) -> None:
        # Break caught: rebinding after the run would leave recorded provenance
        # describing a prompt the transcript was not produced with.
        job_id = self.job["job_id"]
        self.service.transcribe(job_id)

        with self.assertRaises((StageTransitionError, JobValidationError)):
            self._bind_prompt(job_id, self.LECTURE_PROMPT)

    def test_recorded_metadata_must_carry_the_prompt_the_job_declares(self) -> None:
        # Break caught: a candidate could otherwise attest any prompt, or none,
        # regardless of what the job was bound to.
        job_id = self.job["job_id"]
        self._bind_prompt(job_id, self.LECTURE_PROMPT)

        self._register_direct_full_asr_candidate(
            job_id,
            local_runtime_metadata(),
            configuration={**DEFAULT_ASR_CONFIGURATION, "initial_prompt": "a different prompt"},
        )

        with self.assertRaises(ArtifactValidationError):
            with self.store.transaction(job_id) as transaction:
                transaction.complete_asr()
        self.assertEqual(self.store.load_job(job_id)["stage"], "source_ready")

    def test_typed_asr_completion_rejects_explicitly_remote_or_unpinned_provenance(self) -> None:
        # Break caught: fixed decoder settings let a public typed transaction attest an explicitly remote or unpinned ASR run.
        cases = (
            ("https snapshot", local_runtime_metadata(snapshot="https://runpod.example/small")),
            ("wrong library version", local_runtime_metadata(faster_whisper="1.2.0")),
            ("remote execution mode", local_runtime_metadata(execution_mode="remote")),
            ("extra remote backend claim", {**local_runtime_metadata(), "backend": "runpod"}),
        )
        for name, runtime in cases:
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/provenance-{name.replace(' ', '-')}"
                )
                self._register_direct_full_asr_candidate(job["job_id"], runtime)
                with self.assertRaises(ArtifactValidationError):
                    with self.store.transaction(job["job_id"]) as transaction:
                        transaction.complete_asr()
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_typed_asr_completion_rejects_top_level_remote_provenance_claims(self) -> None:
        # Break caught: a local-looking nested runtime let an explicit remote backend claim escape the public typed completion boundary.
        cases = (
            {"backend": "runpod"},
            {"remote_endpoint": "https://runpod.example/asr"},
        )
        for metadata_extra in cases:
            with self.subTest(metadata_extra=metadata_extra):
                job = IntakeService(self.store, FakeSourceAdapter(repr(metadata_extra).encode())).intake(
                    f"https://archive.example/top-level-{next(iter(metadata_extra))}"
                )
                self._register_direct_full_asr_candidate(
                    job["job_id"], local_runtime_metadata(), metadata_extra
                )
                with self.assertRaises(ArtifactValidationError):
                    with self.store.transaction(job["job_id"]) as transaction:
                        transaction.complete_asr()
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_typed_asr_completion_rejects_duplicate_metadata_provenance_keys(self) -> None:
        # Break caught: default JSON parsing discarded an earlier explicit remote runtime claim before typed provenance validation.
        configuration_text = json.dumps(DEFAULT_ASR_CONFIGURATION, sort_keys=True)
        local_runtime = local_runtime_metadata()
        local_runtime_text = json.dumps(local_runtime, sort_keys=True)
        remote_runtime_text = json.dumps(
            local_runtime_metadata(execution_mode="remote", snapshot="https://runpod.example/small"),
            sort_keys=True,
        )
        nested_duplicate_runtime = (
            '{"execution_mode":"remote","execution_mode":"local",'
            f'"faster_whisper":{json.dumps(local_runtime["faster_whisper"])},'
            f'"ffmpeg":{json.dumps(local_runtime["ffmpeg"])},'
            f'"ffprobe":{json.dumps(local_runtime["ffprobe"])},'
            f'"model_snapshot":{json.dumps(local_runtime["model_snapshot"])},'
            f'"python":{json.dumps(local_runtime["python"])}'
            '}'
        )
        cases = (
            ("top-level runtime", lambda source: (
                f'{{"source_sha256":{json.dumps(source)},"configuration":{configuration_text},'
                f'"runtime":{remote_runtime_text},"runtime":{local_runtime_text}}}\n'
            )),
            ("nested execution mode", lambda source: (
                f'{{"source_sha256":{json.dumps(source)},"configuration":{configuration_text},'
                f'"runtime":{nested_duplicate_runtime}}}\n'
            )),
        )
        for name, metadata_text in cases:
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/duplicate-{name.replace(' ', '-')}"
                )
                self._register_direct_full_asr_candidate(
                    job["job_id"], local_runtime, raw_metadata=metadata_text(job["source_sha256"])
                )
                with self.assertRaises(ArtifactValidationError):
                    with self.store.transaction(job["job_id"]) as transaction:
                        transaction.complete_asr()
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_typed_asr_completion_rejects_type_confused_fixed_configuration(self) -> None:
        # Break caught: Python dictionary equality accepted JSON numeric substitutes for fixed Boolean/integer configuration fields.
        cases = (
            ("word timestamps integer", {"word_timestamps": 1}),
            ("vad integer", {"vad_filter": 0}),
            ("previous text float", {"condition_on_previous_text": 0.0}),
            ("beam float", {"beam_size": 5.0}),
        )
        for name, replacement in cases:
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/type-confused-{name.replace(' ', '-')}"
                )
                configuration = {**DEFAULT_ASR_CONFIGURATION, **replacement}
                self._register_direct_full_asr_candidate(
                    job["job_id"], local_runtime_metadata(), configuration=configuration
                )
                with self.assertRaises(ArtifactValidationError):
                    with self.store.transaction(job["job_id"]) as transaction:
                        transaction.complete_asr()
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_typed_asr_completion_rejects_duplicate_raw_jsonl_fields(self) -> None:
        # Break caught: a hidden timestamp was discarded by permissive JSON parsing before raw-ASR validation.
        cases = (
            (
                "segment field",
                '{"end": 1.0, "id": 0, "start": 31.0, "start": 0.0, "text": "direct candidate"}\n',
            ),
            (
                "nested word field",
                '{"end": 1.0, "id": 0, "start": 0.0, "text": "direct candidate", '
                '"words": [{"end": 0.5, "start": 0.25, "start": 0.0, "word": " word"}]}\n',
            ),
        )
        for name, raw_jsonl in cases:
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/duplicate-jsonl-{name.replace(' ', '-')}"
                )
                self._register_direct_full_asr_candidate(
                    job["job_id"], local_runtime_metadata(), raw_jsonl=raw_jsonl
                )
                with self.assertRaises(ArtifactValidationError):
                    with self.store.transaction(job["job_id"]) as transaction:
                        transaction.complete_asr()
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_strict_evidence_parser_rejects_nonfinite_constants_but_keeps_raw_timestamp_spelling_flexible(self) -> None:
        # Break caught: strict workflow identity must not accidentally impose canonical spelling on ordinary ASR timestamps.
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                with self.assertRaises(asr_module._StrictJsonParseError):
                    asr_module._strict_json_loads(f'{{"value": {constant}}}')
        records = asr_module._parse_raw_segments_text(
            '{"end": 1E0, "id": 0, "start": 0e0, "text": "ordinary ASR timestamps"}\n'
        )
        self.assertEqual(records, [{"end": 1.0, "id": 0, "start": 0.0, "text": "ordinary ASR timestamps"}])

    def test_typed_asr_completion_accepts_historical_missing_local_snapshot(self) -> None:
        # Break caught: review of an old local job would fail merely because its historical cache directory was later removed.
        job = IntakeService(self.store, FakeSourceAdapter(b"historical-local")).intake(
            "https://archive.example/historical-local"
        )
        missing_snapshot = str((Path(self.tmp.name) / "historical-cache" / "small-snapshot").resolve())
        self.assertFalse(Path(missing_snapshot).exists())
        self._register_direct_full_asr_candidate(
            job["job_id"], local_runtime_metadata(snapshot=missing_snapshot)
        )
        with self.store.transaction(job["job_id"]) as transaction:
            transaction.complete_asr()
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "asr_ready")

    def test_local_adapter_imports_faster_whisper_only_when_transcribing(self) -> None:
        # Break caught: ordinary workflow/tests would require the dedicated ASR environment just to import modules.
        imports: list[str] = []

        def importer(name: str):
            imports.append(name)
            raise ModuleNotFoundError(name)

        adapter = LocalFasterWhisperAdapter(snapshot_path=Path(self.tmp.name) / "missing", module_importer=importer)
        self.assertEqual(imports, [])
        with self.assertRaisesRegex(JobValidationError, "local small model snapshot"):
            adapter.transcribe(Path("source.bin"), DEFAULT_ASR_CONFIGURATION)
        self.assertEqual(imports, [])

    def test_local_adapter_constructs_and_calls_faster_whisper_with_the_fixed_defaults(self) -> None:
        # Break caught: a future adapter change could quietly enable VAD or a different language/model mode.
        snapshot = Path(self.tmp.name) / "snapshot"
        snapshot.mkdir()
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
        calls: dict[str, object] = {}

        class Segment:
            id, start, end, text = 7, 1.0, 2.0, " A line."
            avg_logprob = -0.1
            words = []

        class Model:
            def __init__(self, path: str, **kwargs: object) -> None:
                calls["construction"] = (path, kwargs)

            def transcribe(self, path: str, **kwargs: object):
                calls["transcription"] = (path, kwargs)
                return iter([Segment()]), object()

        class Module:
            WhisperModel = Model

        adapter = LocalFasterWhisperAdapter(snapshot_path=snapshot, module_importer=lambda name: Module())
        records = adapter.transcribe(Path("source.bin"), DEFAULT_ASR_CONFIGURATION)
        self.assertEqual(calls["construction"], (str(snapshot.resolve()), {"device": "cpu", "compute_type": "int8"}))
        self.assertEqual(calls["transcription"], ("source.bin", {"language": "en", "beam_size": 5, "word_timestamps": True, "vad_filter": False, "condition_on_previous_text": False, "initial_prompt": None}))
        self.assertEqual(records[0]["id"], 7)

    def _recording_adapter(self, calls: dict[str, object]) -> LocalFasterWhisperAdapter:
        snapshot = Path(self.tmp.name) / "recording-snapshot"
        snapshot.mkdir(exist_ok=True)
        (snapshot / "config.json").write_text("{}", encoding="utf-8")

        class Segment:
            id, start, end, text = 7, 1.0, 2.0, " A line."
            avg_logprob = -0.1
            words = []

        class Model:
            def __init__(self, path: str, **kwargs: object) -> None:
                calls["construction"] = (path, kwargs)

            def transcribe(self, path: str, **kwargs: object):
                calls["transcription"] = (path, kwargs)
                return iter([Segment()]), object()

        class Module:
            WhisperModel = Model

        return LocalFasterWhisperAdapter(snapshot_path=snapshot, module_importer=lambda name: Module())

    def test_local_adapter_executes_the_configuration_it_is_given(self) -> None:
        # Break caught: the adapter hardcoded every argument and ignored the
        # configuration entirely, so recorded provenance described values it did
        # not control. Metadata that cannot lie is the whole point of recording it.
        calls: dict[str, object] = {}
        adapter = self._recording_adapter(calls)

        adapter.transcribe(Path("source.bin"), {
            **DEFAULT_ASR_CONFIGURATION,
            "language": "fr", "beam_size": 1, "vad_filter": True, "compute_type": "float16",
        })

        self.assertEqual(calls["construction"][1], {"device": "cpu", "compute_type": "float16"})
        self.assertEqual(calls["transcription"][1], {
            "language": "fr", "beam_size": 1, "word_timestamps": True,
            "vad_filter": True, "condition_on_previous_text": False,
            "initial_prompt": None,
        })

    def test_local_adapter_refuses_a_configuration_key_it_cannot_route(self) -> None:
        # Break caught: a key named here but not routed would be written into
        # metadata and silently dropped from the call -- a recorded claim about a
        # parameter that was never applied. This is exactly how initial_prompt
        # would have been added had the routing not been made total first; the
        # example below is a real faster-whisper parameter this adapter does not
        # pass, so naming it must fail rather than become a lie that validates.
        calls: dict[str, object] = {}
        adapter = self._recording_adapter(calls)

        with self.assertRaises(JobValidationError):
            adapter.transcribe(Path("source.bin"), {**DEFAULT_ASR_CONFIGURATION, "temperature": 0.4})
        self.assertNotIn("transcription", calls)

    def test_local_adapter_requires_every_configuration_key(self) -> None:
        # Break caught: a missing key would otherwise fall back to faster-whisper's
        # own default, which the metadata would not record at all.
        calls: dict[str, object] = {}
        adapter = self._recording_adapter(calls)
        incomplete = dict(DEFAULT_ASR_CONFIGURATION)
        del incomplete["beam_size"]

        with self.assertRaises(JobValidationError):
            adapter.transcribe(Path("source.bin"), incomplete)
        self.assertNotIn("transcription", calls)

    def test_changed_source_is_rejected_before_full_asr_evidence_is_written(self) -> None:
        # Break caught: ASR evidence could otherwise attest a file other than the hash-bound recording.
        source = self.store.job_root(self.job["job_id"]) / "source" / "source.bin"
        source.write_bytes(b"changed")
        with self.assertRaises(ArtifactValidationError):
            self.service.transcribe(self.job["job_id"])
        self.assertFalse((self.store.job_root(self.job["job_id"]) / "asr" / "full.jsonl").exists())

    def test_rerun_is_supplemental_and_does_not_change_raw_full_evidence_or_stage(self) -> None:
        # Break caught: a convenient targeted rerun could silently rewrite the evidence reviewed later.
        ready = self.service.transcribe(self.job["job_id"])
        raw = self.store.validate_artifact(ready["job_id"], "asr/full.jsonl").read_bytes()
        span = self.service.rerun_span(ready["job_id"], 6, 9)
        self.assertEqual(self.store.load_job(ready["job_id"])["stage"], "asr_ready")
        self.assertEqual(self.store.validate_artifact(ready["job_id"], "asr/full.jsonl").read_bytes(), raw)
        self.assertTrue(span["jsonl_path"].is_file())
        self.assertTrue(span["metadata_path"].is_file())
        self.assertEqual(self.media.calls[0][1].suffix, ".mka")
        self.assertEqual(self.media.calls[0][2:], (6.0, 9.0))
        with self.assertRaises(JobValidationError):
            self.service.rerun_span(ready["job_id"], -1, 2)
        with self.assertRaises(JobValidationError):
            self.service.rerun_span(ready["job_id"], 9, 9)
        with self.assertRaises(JobValidationError):
            self.service.rerun_span(ready["job_id"], 0, 31)

    def test_ffmpeg_rerun_boundary_uses_a_known_output_format_and_duration_not_ambiguous_to(self) -> None:
        # Break caught: a `.tmp` stream-copy target made every production rerun fail before ASR started.
        commands: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        target = Path(self.tmp.name) / "span.mka"
        FfmpegMediaAdapter(run_command=runner).extract_span(Path("source.mp3"), target, 2.25, 5.5)
        command = commands[0]
        self.assertEqual(command[command.index("-t") + 1], "3.25")
        self.assertNotIn("-to", command)
        self.assertEqual(command[-1], str(target))
        self.assertEqual(target.suffix, ".mka")

    def test_rerun_refuses_changed_full_evidence_before_creating_any_supplemental_file(self) -> None:
        # Break caught: supplemental evidence could be added to a job whose immutable primary evidence was damaged.
        ready = self.service.transcribe(self.job["job_id"])
        raw = self.store.job_root(ready["job_id"]) / "asr" / "full.jsonl"
        raw.write_text("changed", encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            self.service.rerun_span(ready["job_id"], 1, 2)
        self.assertEqual(list((self.store.job_root(ready["job_id"]) / "asr" / "reruns").iterdir()), [])

    def test_distinct_submillisecond_spans_have_distinct_deterministic_evidence_paths(self) -> None:
        # Break caught: millisecond rounding caused different valid spans to collide under one evidence identifier.
        ready = self.service.transcribe(self.job["job_id"])
        first = self.service.rerun_span(ready["job_id"], 0.0001, 1.0001)
        second = self.service.rerun_span(ready["job_id"], 0.0002, 1.0002)
        self.assertNotEqual(first["jsonl_path"], second["jsonl_path"])

    def test_invalid_full_model_output_leaves_source_ready_without_immutable_asr_files(self) -> None:
        # Break caught: invalid decoder output used to become a permanent full-evidence artifact before inspection rejected it.
        for segments in (
            [{"id": 1, "start": 10.0, "end": 11.0, "text": "later"}, {"id": 0, "start": 2.0, "end": 3.0, "text": "earlier"}],
            [{"id": 0, "start": 29.0, "end": 31.0, "text": "outside duration"}],
        ):
            with self.subTest(segments=segments):
                job = IntakeService(self.store, FakeSourceAdapter(repr(segments).encode())).intake(f"https://archive.example/{len(segments)}-{segments[0]['id']}")
                service = ASRService(self.store, FakeModelAdapter(segments), FakeMediaAdapter())
                with self.assertRaises(JobValidationError):
                    service.transcribe(job["job_id"])
                root = self.store.job_root(job["job_id"])
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")
                self.assertFalse((root / "asr" / "full.jsonl").exists())
                self.assertFalse((root / "asr" / "metadata.json").exists())

    def test_source_change_during_asr_is_rejected_before_publication(self) -> None:
        # Break caught: a long model run could produce a transcript for bytes different from the job's source hash.
        source = self.store.job_root(self.job["job_id"]) / "source" / "source.bin"

        class MutatingModel(FakeModelAdapter):
            def transcribe(self, source_path: Path, configuration: dict[str, object]) -> list[dict[str, object]]:
                result = super().transcribe(source_path, configuration)
                source.write_bytes(b"changed during asr")
                return result

        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, MutatingModel(), self.media).transcribe(self.job["job_id"])
        self.assertFalse((self.store.job_root(self.job["job_id"]) / "asr" / "full.jsonl").exists())

    def test_missing_runtime_provenance_cannot_advance_to_asr_ready(self) -> None:
        # Break caught: a nominally complete run could omit the model/tool identity needed to reproduce it.
        class IncompleteRuntimeModel(FakeModelAdapter):
            def runtime_metadata(self) -> dict[str, str]:
                return {"model_snapshot": "/fake/snapshot", "python": "fake-python"}

        with self.assertRaisesRegex(JobValidationError, "runtime metadata"):
            ASRService(self.store, IncompleteRuntimeModel(), self.media).transcribe(self.job["job_id"])
        self.assertEqual(self.store.load_job(self.job["job_id"])["stage"], "source_ready")

    def test_incomplete_media_provenance_refuses_a_rerun_before_evidence_is_published(self) -> None:
        # Break caught: a span result without FFmpeg identity cannot be reproduced or audited later.
        ready = self.service.transcribe(self.job["job_id"])

        class IncompleteMedia(FakeMediaAdapter):
            def runtime_metadata(self) -> dict[str, str]:
                return {"ffmpeg": "fake-ffmpeg"}

        with self.assertRaisesRegex(JobValidationError, "media runtime metadata"):
            ASRService(self.store, self.model, IncompleteMedia()).rerun_span(ready["job_id"], 1, 2)
        self.assertEqual(list((self.store.job_root(ready["job_id"]) / "asr" / "reruns").iterdir()), [])

    def test_nonlocal_or_extra_media_provenance_refuses_rerun_before_output_publication(self) -> None:
        # Break caught: supplemental local-only evidence accepted an explicit remote mode/backend as arbitrary descriptive metadata.
        cases = (
            ("remote execution", {"execution_mode": "remote", "ffmpeg": "fake-ffmpeg", "ffprobe": "fake-ffprobe"}),
            ("extra backend", {"execution_mode": "local", "ffmpeg": "fake-ffmpeg", "ffprobe": "fake-ffprobe", "backend": "runpod"}),
        )
        for name, runtime in cases:
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/untrusted-media-{name.replace(' ', '-')}"
                )
                ready = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter()).transcribe(job["job_id"])

                class UntrustedMedia(FakeMediaAdapter):
                    def runtime_metadata(self) -> dict[str, str]:
                        return dict(runtime)

                model, media = FakeModelAdapter(), UntrustedMedia()
                with self.assertRaises(JobValidationError):
                    ASRService(self.store, model, media).rerun_span(ready["job_id"], 1, 2)
                self.assertEqual(model.calls, [])
                self.assertEqual(media.calls, [])
                self.assertEqual(list((self.store.job_root(ready["job_id"]) / "asr" / "reruns").iterdir()), [])

    def test_ffmpeg_media_adapter_records_explicit_local_provenance(self) -> None:
        # Break caught: the production FFmpeg adapter omitted the local execution attestation required for supplemental evidence.
        with patch.object(asr_module, "_command_version", side_effect=lambda command: f"{command}-version"):
            self.assertEqual(
                FfmpegMediaAdapter().runtime_metadata(),
                {"execution_mode": "local", "ffmpeg": "ffmpeg-version", "ffprobe": "ffprobe-version"},
            )

    def test_rerun_revalidates_a_temporary_target_after_media_runtime_callback(self) -> None:
        # Break caught: runtime metadata could redirect the already-validated staging parent before an external writer opened it.
        ready = self.service.transcribe(self.job["job_id"])
        normal_media = FakeMediaAdapter()
        normal = ASRService(self.store, FakeModelAdapter(), normal_media).rerun_span(ready["job_id"], 1.0, 2.0)
        self.assertTrue(normal["jsonl_path"].is_file())
        self.assertTrue(normal["metadata_path"].is_file())
        self.assertEqual(len(normal_media.calls), 1)

        root = self.store.job_root(ready["job_id"])
        reruns, backup = root / "asr" / "reruns", root / "asr" / "reruns-before-runtime-callback"
        outside = Path(self.tmp.name) / "outside-rerun-target"
        outside.mkdir()

        def restore_rerun_parent() -> None:
            self._remove_directory_redirect(reruns)
            if backup.exists():
                backup.replace(reruns)

        self.addCleanup(restore_rerun_parent)

        class RedirectingMedia(FakeMediaAdapter):
            def runtime_metadata(inner_self) -> dict[str, str]:
                reruns.rename(backup)
                self._redirect_directory(reruns, outside)
                return super().runtime_metadata()

        model, media = FakeModelAdapter(), RedirectingMedia()
        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, model, media).rerun_span(ready["job_id"], 3.0, 4.0)
        self.assertEqual(media.calls, [])
        self.assertEqual(model.calls, [])
        self.assertEqual(list(outside.iterdir()), [])

    def test_runtime_metadata_with_a_non_json_extra_is_rejected_before_any_full_asr_file(self) -> None:
        # Break caught: a later metadata serialization failure stranded raw full evidence at a source_ready job.
        class UnsafeExtraRuntimeModel(FakeModelAdapter):
            def runtime_metadata(self) -> dict[str, object]:
                return {**super().runtime_metadata(), "unsafe": float("nan")}

        with self.assertRaisesRegex(JobValidationError, "runtime metadata"):
            ASRService(self.store, UnsafeExtraRuntimeModel(), self.media).transcribe(self.job["job_id"])
        root = self.store.job_root(self.job["job_id"])
        self.assertEqual(self.store.load_job(self.job["job_id"])["stage"], "source_ready")
        self.assertFalse((root / "asr" / "full.jsonl").exists())
        self.assertFalse((root / "asr" / "metadata.json").exists())

    def test_negative_zero_and_zero_share_one_rerun_identity(self) -> None:
        # Break caught: numerically identical span bounds could create duplicate supplemental evidence histories.
        ready = self.service.transcribe(self.job["job_id"])
        self.service.rerun_span(ready["job_id"], 0.0, 1.0)
        with self.assertRaises(ArtifactValidationError):
            self.service.rerun_span(ready["job_id"], -0.0, 1.0)

    def test_signed_zero_interrupted_rerun_recovers_across_spellings_without_recalling_adapters(self) -> None:
        # Break caught: canonical rerun filenames still stranded a partial intent because signed zero leaked into metadata/context.
        original_atomic = asr_module._atomic_text
        for first_start, retry_start in ((-0.0, 0.0), (0.0, -0.0)):
            with self.subTest(first_start=repr(first_start), retry_start=repr(retry_start)):
                isolated = JobStore(Path(self.tmp.name) / f"zero-{repr(first_start)}" / "data" / "transcribe")
                job = IntakeService(isolated, FakeSourceAdapter(repr(first_start).encode())).intake(
                    f"https://archive.example/zero-{repr(first_start).replace('-', 'neg')}"
                )
                ASRService(isolated, FakeModelAdapter(), FakeMediaAdapter()).transcribe(job["job_id"])
                model, media = FakeModelAdapter(), FakeMediaAdapter()
                rerun = ASRService(isolated, model, media)

                def fail_after_jsonl(path: Path, text: str) -> None:
                    original_atomic(path, text)
                    if path.parent.name == "reruns" and path.name.endswith(".jsonl"):
                        raise OSError("signed-zero rerun JSONL interrupted")

                with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
                    with self.assertRaises(OSError):
                        rerun.rerun_span(job["job_id"], first_start, 1.0)
                recovered = rerun.rerun_span(job["job_id"], retry_start, 1.0)
                metadata = json.loads(recovered["metadata_path"].read_text(encoding="utf-8"))
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(len(media.calls), 1)
                self.assertEqual(metadata["start_seconds"], 0.0)
                self.assertEqual(math.copysign(1.0, metadata["start_seconds"]), 1.0)
                self.assertNotIn("-0.0", recovered["metadata_path"].read_text(encoding="utf-8"))

    def test_asr_reparse_output_parents_are_rejected_before_model_or_media_writes(self) -> None:
        # Break caught: output validation after external ASR/media work could write through a replaced job directory.
        import scripts.ggsm_transcription.store as store_module

        real_reparse = store_module._is_reparse
        root = self.store.job_root(self.job["job_id"])
        with patch.object(
            store_module,
            "_is_reparse",
            side_effect=lambda path: Path(path) == root / "asr" or real_reparse(path),
        ):
            with self.assertRaises(ArtifactValidationError):
                self.service.transcribe(self.job["job_id"])
        self.assertEqual(self.model.calls, [])

        ready = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter()).transcribe(self.job["job_id"])
        model, media = FakeModelAdapter(), FakeMediaAdapter()
        rerun = ASRService(self.store, model, media)
        with patch.object(
            store_module,
            "_is_reparse",
            side_effect=lambda path: Path(path) == root / "asr" / "reruns" or real_reparse(path),
        ):
            with self.assertRaises(ArtifactValidationError):
                rerun.rerun_span(ready["job_id"], 1, 2)
        self.assertEqual(media.calls, [])
        self.assertEqual(model.calls, [])

        with patch.object(
            store_module,
            "_is_reparse",
            side_effect=lambda path: Path(path) == root / "inspection" or real_reparse(path),
        ):
            with self.assertRaises(ArtifactValidationError):
                ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter()).inspect(ready["job_id"])
        self.assertFalse((root / "inspection" / "report.json").exists())

    def test_reparse_asr_output_leaf_is_rejected_before_model_or_atomic_write(self) -> None:
        # Break caught: a dangling/replaced final evidence leaf could bypass an exists()-guard until after ASR work.
        import scripts.ggsm_transcription.store as store_module

        root = self.store.job_root(self.job["job_id"])
        real_reparse = store_module._is_reparse
        with patch.object(
            store_module,
            "_is_reparse",
            side_effect=lambda path: Path(path) == root / "asr" / "full.jsonl" or real_reparse(path),
        ):
            with self.assertRaises(ArtifactValidationError):
                self.service.transcribe(self.job["job_id"])
        self.assertEqual(self.model.calls, [])

    def test_typed_asr_completion_rejects_fabricated_configuration_metadata_and_jsonl(self) -> None:
        # Break caught: a public typed transaction could attest fabricated remote/non-English or malformed raw ASR evidence.
        cases = (
            (
                "non-default configuration",
                {"model": "remote", "device": "cuda", "compute_type": "float16", "language": "xx"},
                '{"end": 1.0, "id": 0, "start": 0.0, "text": "fabricated"}\n',
                False,
            ),
            (
                "metadata mismatch",
                dict(DEFAULT_ASR_CONFIGURATION),
                '{"end": 1.0, "id": 0, "start": 0.0, "text": "fabricated"}\n',
                True,
            ),
            (
                "out of range JSONL",
                dict(DEFAULT_ASR_CONFIGURATION),
                '{"end": 31.0, "id": 0, "start": 0.0, "text": "fabricated"}\n',
                False,
            ),
            (
                "malformed JSONL",
                dict(DEFAULT_ASR_CONFIGURATION),
                "not valid JSONL\n",
                False,
            ),
        )
        for name, configuration, raw_jsonl, mismatch_metadata in cases:
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/{name.replace(' ', '-')}"
                )
                state = self.store.load_job(job["job_id"])
                root = self.store.job_root(job["job_id"])
                metadata = {
                    "source_sha256": state["source_sha256"],
                    "configuration": configuration,
                    "runtime": FakeModelAdapter().runtime_metadata(),
                }
                (root / "asr" / "full.jsonl").write_text(raw_jsonl, encoding="utf-8")
                metadata_file = {**metadata, "source_sha256": "0" * 64} if mismatch_metadata else metadata
                (root / "asr" / "metadata.json").write_text(
                    json.dumps(metadata_file, sort_keys=True) + "\n", encoding="utf-8"
                )
                with self.store.transaction(job["job_id"]) as transaction:
                    transaction.register_artifact("asr/full.jsonl")
                    transaction.register_artifact("asr/metadata.json")
                    transaction.record_asr_metadata(metadata)
                with self.assertRaises(ArtifactValidationError):
                    with self.store.transaction(job["job_id"]) as transaction:
                        transaction.complete_asr()
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_typed_asr_completion_rejects_a_changed_bound_source(self) -> None:
        # Break caught: self-registered ASR evidence could advance even after the hash-bound source changed.
        state = self.store.load_job(self.job["job_id"])
        root = self.store.job_root(self.job["job_id"])
        metadata = {
            "source_sha256": state["source_sha256"],
            "configuration": dict(DEFAULT_ASR_CONFIGURATION),
            "runtime": FakeModelAdapter().runtime_metadata(),
        }
        (root / "asr" / "full.jsonl").write_text(
            '{"end": 1.0, "id": 0, "start": 0.0, "text": "valid before source mutation"}\n',
            encoding="utf-8",
        )
        (root / "asr" / "metadata.json").write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
        with self.store.transaction(self.job["job_id"]) as transaction:
            transaction.register_artifact("asr/full.jsonl")
            transaction.register_artifact("asr/metadata.json")
            transaction.record_asr_metadata(metadata)
        (root / "source" / "source.bin").write_bytes(b"changed bound source")
        with self.assertRaises(ArtifactValidationError):
            with self.store.transaction(self.job["job_id"]) as transaction:
                transaction.complete_asr()
        self.assertEqual(self.store.load_job(self.job["job_id"])["stage"], "source_ready")

    def test_typed_inspection_completion_rejects_fabricated_reports_and_cannot_reach_review(self) -> None:
        # Break caught: registered junk reports let a public typed transaction forge inspected and bypass review's upstream evidence checks.
        ready = self.service.transcribe(self.job["job_id"])
        root = self.store.job_root(ready["job_id"])
        (root / "inspection" / "report.json").write_text("{}\n", encoding="utf-8")
        (root / "inspection" / "report.md").write_text("# fabricated\n", encoding="utf-8")
        with self.store.transaction(ready["job_id"]) as transaction:
            transaction.register_artifact("inspection/report.json")
            transaction.register_artifact("inspection/report.md")
        with self.assertRaises(ArtifactValidationError):
            with self.store.transaction(ready["job_id"]) as transaction:
                transaction.complete_inspection()
        self.assertEqual(self.store.load_job(ready["job_id"])["stage"], "asr_ready")
        with self.assertRaises(StageTransitionError):
            ReviewDeliveryService(self.store).prepare_review(ready["job_id"])

    def test_prepare_review_revalidates_semantically_forged_inspected_evidence(self) -> None:
        # Break caught: an inspected-looking manifest with rebounded junk reports could bypass review's upstream check.
        inspected = self.service.inspect(self.service.transcribe(self.job["job_id"])["job_id"])
        root = self.store.job_root(inspected["job_id"])
        report = root / "inspection" / "report.json"
        report.write_text("{}\n", encoding="utf-8")
        manifest = root / "job.json"
        state = json.loads(manifest.read_text(encoding="utf-8"))
        state["artifacts"]["inspection/report.json"] = {
            "sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
            "byte_size": report.stat().st_size,
        }
        manifest.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            ReviewDeliveryService(self.store).prepare_review(inspected["job_id"])


    def test_full_asr_publication_recovers_exact_partial_evidence_at_each_boundary(self) -> None:
        # Break caught: a crash after either full-ASR file or its manifest commit stranded an otherwise exact local run.
        original_atomic = asr_module._atomic_text
        for boundary in ("full.jsonl", "metadata.json", "manifest"):
            with self.subTest(boundary=boundary):
                job = IntakeService(self.store, FakeSourceAdapter(boundary.encode())).intake(
                    f"https://archive.example/full-recovery-{boundary}"
                )
                service = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter())
                if boundary == "manifest":
                    failure = patch.object(self.store, "_write_manifest", side_effect=OSError("manifest interrupted"))
                else:
                    def fail_after_target(path: Path, text: str, boundary=boundary) -> None:
                        original_atomic(path, text)
                        if path.name == boundary:
                            raise OSError(f"{boundary} interrupted")
                    failure = patch.object(asr_module, "_atomic_text", side_effect=fail_after_target)
                with failure:
                    with self.assertRaises((OSError, JobValidationError)):
                        service.transcribe(job["job_id"])
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")
                self.assertEqual(service.transcribe(job["job_id"])["stage"], "asr_ready")

    def test_full_asr_first_output_recovery_reuses_retained_candidate_without_a_second_model_call(self) -> None:
        # Break caught: retrying an interrupted JSONL/metadata pair regenerated changing ASR output instead of publishing the original candidate.
        class ChangingModel(FakeModelAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.runtime_calls = 0

            def transcribe(self, source_path: Path, configuration: dict[str, object]) -> list[dict[str, object]]:
                self.calls.append((source_path, dict(configuration)))
                return [{"id": 0, "start": 0.0, "end": 1.0, "text": f"full-run-{len(self.calls)}"}]

            def runtime_metadata(self) -> dict[str, str]:
                self.runtime_calls += 1
                return local_runtime_metadata(
                    snapshot=f"C:/fake/snapshot-{self.runtime_calls}",
                    python=f"fake-python-{self.runtime_calls}",
                )

        job = IntakeService(self.store, FakeSourceAdapter(b"changing-full")).intake(
            "https://archive.example/changing-full"
        )
        model = ChangingModel()
        service = ASRService(self.store, model, FakeMediaAdapter())
        original_atomic = asr_module._atomic_text

        def fail_after_jsonl(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.name == "full.jsonl":
                raise OSError("full JSONL interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
            with self.assertRaises(OSError):
                service.transcribe(job["job_id"])
        recovered = service.transcribe(job["job_id"])
        root = self.store.job_root(job["job_id"])
        self.assertEqual(recovered["stage"], "asr_ready")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.runtime_calls, 1)
        self.assertIn("full-run-1", (root / "asr" / "full.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads((root / "asr" / "metadata.json").read_text(encoding="utf-8"))["runtime"]["model_snapshot"],
            "C:/fake/snapshot-1",
        )

    def test_full_asr_recovery_rejects_semantically_poisoned_retained_metadata_before_missing_final_write(self) -> None:
        # Break caught: a hash-consistent but semantically invalid retained metadata payload was written to the missing immutable final before validation.
        original_atomic = asr_module._atomic_text
        job = IntakeService(self.store, FakeSourceAdapter(b"poisoned-full")).intake(
            "https://archive.example/poisoned-full"
        )
        first = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter())

        def fail_after_jsonl(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.name == "full.jsonl":
                raise OSError("full JSONL interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
            with self.assertRaises(OSError):
                first.transcribe(job["job_id"])

        root = self.store.job_root(job["job_id"])
        full_path = root / "asr" / "full.jsonl"
        metadata_path = root / "asr" / "metadata.json"
        original_full = full_path.read_bytes()
        self.assertFalse(metadata_path.exists())
        self._replace_retained_intent_payload(root / "asr" / ".full-publication.json", "asr/metadata.json", b"{}\n")

        class PoisonRetryModel:
            def transcribe(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("full recovery called a model adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("full recovery called a runtime adapter")

        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, PoisonRetryModel(), FakeMediaAdapter()).transcribe(job["job_id"])
        self.assertEqual(full_path.read_bytes(), original_full)
        self.assertFalse(metadata_path.exists())
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_full_asr_recovery_rejects_duplicate_retained_metadata_before_missing_final_write(self) -> None:
        # Break caught: duplicate provenance names let a remote claim disappear during recovery parsing and become immutable evidence.
        job = IntakeService(self.store, FakeSourceAdapter(b"duplicate-recovery")).intake(
            "https://archive.example/duplicate-recovery"
        )
        root, full_path, metadata_path = self._interrupt_full_after_first_final(job["job_id"])
        intent_path = root / "asr" / ".full-publication.json"
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        original_metadata = json.loads(
            base64.b64decode(intent["outputs"]["asr/metadata.json"]["payload_base64"].encode("ascii"))
        )
        remote_runtime = {
            **original_metadata["runtime"],
            "execution_mode": "remote",
            "model_snapshot": "https://runpod.example/small",
        }
        poisoned_metadata = (
            f'{{"source_sha256":{json.dumps(original_metadata["source_sha256"])},'
            f'"configuration":{json.dumps(original_metadata["configuration"], sort_keys=True)},'
            f'"runtime":{json.dumps(remote_runtime, sort_keys=True)},'
            f'"runtime":{json.dumps(original_metadata["runtime"], sort_keys=True)}}}\n'
        ).encode("utf-8")
        self._replace_retained_intent_payload(intent_path, "asr/metadata.json", poisoned_metadata)

        class PoisonRetryModel:
            def transcribe(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("duplicate recovery called a model adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("duplicate recovery called a runtime adapter")

        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, PoisonRetryModel(), FakeMediaAdapter()).transcribe(job["job_id"])
        self.assertTrue(full_path.is_file())
        self.assertFalse(metadata_path.exists())
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_full_asr_recovery_rejects_nested_duplicate_runtime_before_missing_final_write(self) -> None:
        # Break caught: a duplicate nested execution mode could conceal a remote provenance claim within otherwise valid metadata.
        job = IntakeService(self.store, FakeSourceAdapter(b"nested-duplicate-recovery")).intake(
            "https://archive.example/nested-duplicate-recovery"
        )
        root, full_path, metadata_path = self._interrupt_full_after_first_final(job["job_id"])
        intent_path = root / "asr" / ".full-publication.json"
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        metadata = json.loads(
            base64.b64decode(intent["outputs"]["asr/metadata.json"]["payload_base64"].encode("ascii"))
        )
        runtime = metadata["runtime"]
        nested_runtime = (
            '{"execution_mode":"remote",'
            f'"execution_mode":{json.dumps(runtime["execution_mode"])},'
            f'"faster_whisper":{json.dumps(runtime["faster_whisper"])},'
            f'"ffmpeg":{json.dumps(runtime["ffmpeg"])},'
            f'"ffprobe":{json.dumps(runtime["ffprobe"])},'
            f'"model_snapshot":{json.dumps(runtime["model_snapshot"])},'
            f'"python":{json.dumps(runtime["python"])}'
            '}'
        )
        poisoned_metadata = (
            f'{{"source_sha256":{json.dumps(metadata["source_sha256"])},'
            f'"configuration":{json.dumps(metadata["configuration"], sort_keys=True)},'
            f'"runtime":{nested_runtime}}}\n'
        ).encode("utf-8")
        self._replace_retained_intent_payload(intent_path, "asr/metadata.json", poisoned_metadata)

        class PoisonRetryModel:
            def transcribe(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("nested duplicate recovery called a model adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("nested duplicate recovery called a runtime adapter")

        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, PoisonRetryModel(), FakeMediaAdapter()).transcribe(job["job_id"])
        self.assertTrue(full_path.is_file())
        self.assertFalse(metadata_path.exists())
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_full_asr_recovery_rejects_type_confused_retained_configuration_before_missing_final_write(self) -> None:
        # Break caught: type-confused JSON configuration values passed the same coercive equality used by recovery and typed completion.
        job = IntakeService(self.store, FakeSourceAdapter(b"configuration-recovery")).intake(
            "https://archive.example/configuration-recovery"
        )
        root, full_path, metadata_path = self._interrupt_full_after_first_final(job["job_id"])
        intent_path = root / "asr" / ".full-publication.json"
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        metadata = json.loads(
            base64.b64decode(intent["outputs"]["asr/metadata.json"]["payload_base64"].encode("ascii"))
        )
        metadata["configuration"].update(
            {"word_timestamps": 1, "vad_filter": 0, "condition_on_previous_text": 0.0, "beam_size": 5.0}
        )
        self._replace_retained_intent_payload(
            intent_path,
            "asr/metadata.json",
            (json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
        )

        class PoisonRetryModel:
            def transcribe(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("configuration recovery called a model adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("configuration recovery called a runtime adapter")

        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, PoisonRetryModel(), FakeMediaAdapter()).transcribe(job["job_id"])
        self.assertTrue(full_path.is_file())
        self.assertFalse(metadata_path.exists())
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_full_asr_recovery_rejects_duplicate_publication_intent_before_missing_final_write(self) -> None:
        # Break caught: duplicate v2 envelope/output names made a private recovery intent ambiguous while permissive parsing kept only one.
        def add_duplicate_envelope(path: Path) -> None:
            text = path.read_text(encoding="utf-8")
            needle = '"kind": "full_asr",'
            self.assertIn(needle, text)
            path.write_text(text.replace(needle, f'{needle}\n  {needle}', 1), encoding="utf-8", newline="\n")

        def add_duplicate_output_record(path: Path) -> None:
            intent = json.loads(path.read_text(encoding="utf-8"))
            digest = intent["outputs"]["asr/metadata.json"]["sha256"]
            text = path.read_text(encoding="utf-8")
            needle = f'"sha256": "{digest}"'
            self.assertIn(needle, text)
            path.write_text(text.replace(needle, f'{needle},\n      {needle}', 1), encoding="utf-8", newline="\n")

        for name, mutate_intent in (("envelope", add_duplicate_envelope), ("output record", add_duplicate_output_record)):
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/duplicate-intent-{name.replace(' ', '-')}"
                )
                root, full_path, metadata_path = self._interrupt_full_after_first_final(job["job_id"])
                mutate_intent(root / "asr" / ".full-publication.json")

                class PoisonRetryModel:
                    def transcribe(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                        raise AssertionError("duplicate intent recovery called a model adapter")

                    def runtime_metadata(self) -> dict[str, str]:
                        raise AssertionError("duplicate intent recovery called a runtime adapter")

                with self.assertRaises(ArtifactValidationError):
                    ASRService(self.store, PoisonRetryModel(), FakeMediaAdapter()).transcribe(job["job_id"])
                self.assertTrue(full_path.is_file())
                self.assertFalse(metadata_path.exists())
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_full_asr_recovery_refuses_stale_malformed_legacy_or_partially_registered_intents_without_retrying(self) -> None:
        # Break caught: a compromised or insufficient interrupted-publication state could silently rerun ASR or overwrite immutable evidence.
        original_atomic = asr_module._atomic_text
        for condition in ("stale source", "changed final", "malformed payload", "legacy intent", "partial registration"):
            with self.subTest(condition=condition):
                job = IntakeService(self.store, FakeSourceAdapter(condition.encode())).intake(
                    f"https://archive.example/closed-recovery-{condition.replace(' ', '-')}"
                )
                model = FakeModelAdapter()
                service = ASRService(self.store, model, FakeMediaAdapter())

                def fail_after_jsonl(path: Path, text: str) -> None:
                    original_atomic(path, text)
                    if path.name == "full.jsonl":
                        raise OSError("full JSONL interrupted")

                with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
                    with self.assertRaises(OSError):
                        service.transcribe(job["job_id"])

                root = self.store.job_root(job["job_id"])
                full = root / "asr" / "full.jsonl"
                before_retry = full.read_bytes()
                intent_path = root / "asr" / ".full-publication.json"
                if condition == "stale source":
                    (root / "source" / "source.bin").write_bytes(b"changed after candidate publication")
                elif condition == "changed final":
                    full.write_text("changed immutable final\n", encoding="utf-8")
                    before_retry = full.read_bytes()
                elif condition in {"malformed payload", "legacy intent"}:
                    intent = json.loads(intent_path.read_text(encoding="utf-8"))
                    if condition == "malformed payload":
                        intent["outputs"]["asr/metadata.json"]["payload_base64"] = "not base64!"
                    else:
                        intent["schema_version"] = 1
                        for output in intent["outputs"].values():
                            output.pop("payload_base64")
                    intent_path.write_text(json.dumps(intent, sort_keys=True) + "\n", encoding="utf-8")
                else:
                    with self.store.transaction(job["job_id"]) as transaction:
                        transaction.register_artifact("asr/full.jsonl")

                with self.assertRaises(ArtifactValidationError):
                    service.transcribe(job["job_id"])
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(full.read_bytes(), before_retry)
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_inspection_rejects_legacy_private_publication_intent_explicitly(self) -> None:
        # Break caught: old hash-only inspection recovery state could be treated as a regenerable candidate without an explicit safety decision.
        ready = self.service.transcribe(self.job["job_id"])
        root = self.store.job_root(ready["job_id"])
        (root / "inspection" / ".publication.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "inspection",
                    "source_sha256": ready["source_sha256"],
                    "context": {"full_asr_sha256": ready["artifacts"]["asr/full.jsonl"]["sha256"]},
                    "outputs": {},
                },
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ArtifactValidationError, "legacy publication recovery intent"):
            self.service.inspect(ready["job_id"])
        self.assertEqual(self.store.load_job(ready["job_id"])["stage"], "asr_ready")

    def test_rerun_first_output_recovery_reuses_retained_candidate_without_a_second_adapter_call(self) -> None:
        # Break caught: retrying an interrupted span JSONL/metadata pair reran both media extraction and changing ASR output.
        ready = self.service.transcribe(self.job["job_id"])

        class ChangingRerunModel(FakeModelAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.runtime_calls = 0

            def transcribe(self, source_path: Path, configuration: dict[str, object]) -> list[dict[str, object]]:
                self.calls.append((source_path, dict(configuration)))
                return [{"id": 0, "start": 0.0, "end": 0.5, "text": f"rerun-{len(self.calls)}"}]

            def runtime_metadata(self) -> dict[str, str]:
                self.runtime_calls += 1
                return local_runtime_metadata(
                    snapshot=f"C:/fake/rerun-{self.runtime_calls}",
                    python=f"fake-rerun-python-{self.runtime_calls}",
                )

        model, media = ChangingRerunModel(), FakeMediaAdapter()
        service = ASRService(self.store, model, media)
        original_atomic = asr_module._atomic_text

        def fail_after_jsonl(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.parent.name == "reruns" and path.name.endswith(".jsonl"):
                raise OSError("rerun JSONL interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
            with self.assertRaises(OSError):
                service.rerun_span(ready["job_id"], 1.0, 2.0)
        recovered = service.rerun_span(ready["job_id"], 1.0, 2.0)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.runtime_calls, 1)
        self.assertEqual(len(media.calls), 1)
        self.assertIn("rerun-1", recovered["jsonl_path"].read_text(encoding="utf-8"))

    def test_rerun_recovery_rejects_semantically_poisoned_retained_metadata_before_missing_final_write(self) -> None:
        # Break caught: rerun recovery wrote a hash-consistent but invalid retained metadata payload before semantic validation.
        ready = self.service.transcribe(self.job["job_id"])
        first = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter())
        original_atomic = asr_module._atomic_text

        def fail_after_jsonl(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.parent.name == "reruns" and path.name.endswith(".jsonl"):
                raise OSError("rerun JSONL interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
            with self.assertRaises(OSError):
                first.rerun_span(ready["job_id"], 1.0, 2.0)

        root = self.store.job_root(ready["job_id"])
        intent_path = next((root / "asr" / "reruns").glob(".*.publication.json"))
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        jsonl_relative = next(relative for relative in intent["outputs"] if relative.endswith(".jsonl"))
        metadata_relative = next(relative for relative in intent["outputs"] if relative.endswith(".metadata.json"))
        jsonl_path = root / Path(jsonl_relative)
        metadata_path = root / Path(metadata_relative)
        original_jsonl = jsonl_path.read_bytes()
        self.assertFalse(metadata_path.exists())
        self._replace_retained_intent_payload(intent_path, metadata_relative, b"{}\n")

        class PoisonRetryModel:
            def transcribe(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("rerun recovery called a model adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("rerun recovery called a model runtime adapter")

        class PoisonRetryMedia:
            def extract_span(self, *_args: object, **_kwargs: object) -> None:
                raise AssertionError("rerun recovery called a media adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("rerun recovery called a media runtime adapter")

        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, PoisonRetryModel(), PoisonRetryMedia()).rerun_span(ready["job_id"], 1.0, 2.0)
        self.assertEqual(jsonl_path.read_bytes(), original_jsonl)
        self.assertFalse(metadata_path.exists())
        self.assertEqual(self.store.load_job(ready["job_id"])["stage"], "asr_ready")

    def test_rerun_recovery_rejects_boolean_span_bound_before_missing_final_write(self) -> None:
        # Break caught: Python equality let True stand in for 1.0 in retained rerun metadata.
        ready = self.service.transcribe(self.job["job_id"])
        original_atomic = asr_module._atomic_text

        def fail_after_jsonl(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.parent.name == "reruns" and path.name.endswith(".jsonl"):
                raise OSError("rerun JSONL interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_jsonl):
            with self.assertRaises(OSError):
                ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter()).rerun_span(
                    ready["job_id"], 1.0, 2.0
                )

        root = self.store.job_root(ready["job_id"])
        intent_path = next((root / "asr" / "reruns").glob(".*.publication.json"))
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        metadata_relative = next(relative for relative in intent["outputs"] if relative.endswith(".metadata.json"))
        retained = json.loads(
            base64.b64decode(intent["outputs"][metadata_relative]["payload_base64"].encode("ascii"))
        )
        retained["start_seconds"] = True
        self._replace_retained_intent_payload(
            intent_path,
            metadata_relative,
            (json.dumps(retained, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        metadata_path = root / Path(metadata_relative)
        self.assertFalse(metadata_path.exists())

        retry_model, retry_media = FakeModelAdapter(), FakeMediaAdapter()
        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, retry_model, retry_media).rerun_span(ready["job_id"], 1.0, 2.0)
        self.assertEqual(retry_model.calls, [])
        self.assertEqual(retry_media.calls, [])
        self.assertFalse(metadata_path.exists())

    def test_rerun_recovery_rejects_noncanonical_or_untrusted_metadata_and_context_before_missing_final_write(self) -> None:
        # Break caught: parsing before canonicality/provenance checks accepted textual aliases and remote supplemental evidence.
        def poison_metadata_start(path: Path, replacement: str) -> None:
            intent = json.loads(path.read_text(encoding="utf-8"))
            metadata_relative = next(relative for relative in intent["outputs"] if relative.endswith(".metadata.json"))
            payload = base64.b64decode(intent["outputs"][metadata_relative]["payload_base64"].encode("ascii"))
            text = payload.decode("utf-8")
            self.assertIn('"start_seconds": 0.0', text)
            self._replace_retained_intent_payload(
                path, metadata_relative, text.replace('"start_seconds": 0.0', f'"start_seconds": {replacement}', 1).encode("utf-8")
            )

        def poison_context(path: Path, replacement: str) -> None:
            text = path.read_text(encoding="utf-8")
            self.assertIn('"start_seconds": 0.0', text)
            path.write_text(
                text.replace('"start_seconds": 0.0', f'"start_seconds": {replacement}', 1),
                encoding="utf-8",
                newline="\n",
            )

        def poison_media_runtime(path: Path, media_runtime: dict[str, str]) -> None:
            intent = json.loads(path.read_text(encoding="utf-8"))
            metadata_relative = next(relative for relative in intent["outputs"] if relative.endswith(".metadata.json"))
            payload = base64.b64decode(intent["outputs"][metadata_relative]["payload_base64"].encode("ascii"))
            metadata = json.loads(payload)
            metadata["media_runtime"] = media_runtime
            self._replace_retained_intent_payload(
                path,
                metadata_relative,
                (json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
            )

        cases = (
            ("metadata negative zero", lambda path: poison_metadata_start(path, "-0")),
            ("metadata exponential zero", lambda path: poison_metadata_start(path, "0e0")),
            ("context false", lambda path: poison_context(path, "false")),
            ("context negative zero", lambda path: poison_context(path, "-0.0")),
            ("context integer zero", lambda path: poison_context(path, "0")),
            ("context exponential zero", lambda path: poison_context(path, "0e0")),
            (
                "metadata remote media",
                lambda path: poison_media_runtime(
                    path, {"execution_mode": "remote", "ffmpeg": "fake-ffmpeg", "ffprobe": "fake-ffprobe"}
                ),
            ),
            (
                "metadata extra media backend",
                lambda path: poison_media_runtime(
                    path,
                    {
                        "execution_mode": "local",
                        "ffmpeg": "fake-ffmpeg",
                        "ffprobe": "fake-ffprobe",
                        "backend": "runpod",
                    },
                ),
            ),
        )

        class PoisonRetryModel:
            def transcribe(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("noncanonical recovery called a model adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("noncanonical recovery called a model runtime adapter")

        class PoisonRetryMedia:
            def extract_span(self, *_args: object, **_kwargs: object) -> None:
                raise AssertionError("noncanonical recovery called a media adapter")

            def runtime_metadata(self) -> dict[str, str]:
                raise AssertionError("noncanonical recovery called a media runtime adapter")

        for name, poison in cases:
            with self.subTest(name=name):
                job = IntakeService(self.store, FakeSourceAdapter(name.encode())).intake(
                    f"https://archive.example/noncanonical-{name.replace(' ', '-')}"
                )
                ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter()).transcribe(job["job_id"])
                _root, jsonl_path, metadata_path, intent_path = self._interrupt_rerun_after_first_final(job["job_id"])
                original_jsonl = jsonl_path.read_bytes()
                self.assertFalse(metadata_path.exists())
                poison(intent_path)
                with self.assertRaises(ArtifactValidationError):
                    ASRService(self.store, PoisonRetryModel(), PoisonRetryMedia()).rerun_span(
                        job["job_id"], 0.0, 1.0
                    )
                self.assertEqual(jsonl_path.read_bytes(), original_jsonl)
                self.assertFalse(metadata_path.exists())
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "asr_ready")

    def test_inspection_recovery_rejects_semantically_poisoned_retained_markdown_before_missing_final_write(self) -> None:
        # Break caught: inspection recovery wrote retained non-deterministic Markdown before semantic validation.
        ready = self.service.transcribe(self.job["job_id"])
        original_atomic = asr_module._atomic_text

        def fail_after_report_json(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.name == "report.json":
                raise OSError("inspection JSON interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_report_json):
            with self.assertRaises(OSError):
                self.service.inspect(ready["job_id"])

        root = self.store.job_root(ready["job_id"])
        report_json = root / "inspection" / "report.json"
        report_markdown = root / "inspection" / "report.md"
        original_json = report_json.read_bytes()
        self.assertFalse(report_markdown.exists())
        self._replace_retained_intent_payload(
            root / "inspection" / ".publication.json", "inspection/report.md", b"# poisoned inspection\n"
        )

        retry_model, retry_media = FakeModelAdapter(), FakeMediaAdapter()
        with self.assertRaises(ArtifactValidationError):
            ASRService(self.store, retry_model, retry_media).inspect(ready["job_id"])
        self.assertEqual(retry_model.calls, [])
        self.assertEqual(retry_media.calls, [])
        self.assertEqual(report_json.read_bytes(), original_json)
        self.assertFalse(report_markdown.exists())
        self.assertEqual(self.store.load_job(ready["job_id"])["stage"], "asr_ready")

    def test_rerun_and_inspection_publication_recover_exact_partial_evidence_at_each_boundary(self) -> None:
        # Break caught: supplemental and inspection evidence became permanently non-retryable after a two-file interruption.
        original_atomic = asr_module._atomic_text
        for operation, first_name, second_name in (
            ("rerun", ".jsonl", ".metadata.json"),
            ("inspection", "report.json", "report.md"),
        ):
            for boundary in (first_name, second_name, "manifest"):
                with self.subTest(operation=operation, boundary=boundary):
                    job = IntakeService(self.store, FakeSourceAdapter(f"{operation}-{boundary}".encode())).intake(
                        f"https://archive.example/{operation}-recovery-{boundary.replace('.', 'x')}"
                    )
                    service = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter())
                    ready = service.transcribe(job["job_id"])
                    if boundary == "manifest":
                        failure = patch.object(self.store, "_write_manifest", side_effect=OSError("manifest interrupted"))
                    else:
                        def fail_after_target(path: Path, text: str, boundary=boundary, operation=operation) -> None:
                            original_atomic(path, text)
                            matches = path.name.endswith(boundary) if operation == "rerun" else path.name == boundary
                            if matches:
                                raise OSError(f"{boundary} interrupted")
                        failure = patch.object(asr_module, "_atomic_text", side_effect=fail_after_target)
                    with failure:
                        with self.assertRaises((OSError, JobValidationError)):
                            if operation == "rerun":
                                service.rerun_span(ready["job_id"], 1, 2)
                            else:
                                service.inspect(ready["job_id"])
                    if operation == "rerun":
                        recovered = service.rerun_span(ready["job_id"], 1, 2)
                        self.assertTrue(recovered["jsonl_path"].is_file())
                        self.assertEqual(self.store.load_job(ready["job_id"])["stage"], "asr_ready")
                    else:
                        self.assertEqual(self.store.load_job(ready["job_id"])["stage"], "asr_ready")
                        self.assertEqual(service.inspect(ready["job_id"])["stage"], "inspected")

    def test_full_asr_and_inspection_recover_after_typed_completion_manifest_failure(self) -> None:
        # Break caught: durable phase-one evidence was not usable after the second semantic stage-commit failed.
        for operation in ("full_asr", "inspection"):
            with self.subTest(operation=operation):
                isolated = JobStore(Path(self.tmp.name) / operation / "data" / "transcribe")
                job = IntakeService(isolated, FakeSourceAdapter(operation.encode())).intake(
                    f"https://archive.example/{operation}-stage-commit"
                )
                service = ASRService(isolated, FakeModelAdapter(), FakeMediaAdapter())
                if operation == "inspection":
                    service.transcribe(job["job_id"])
                original_write = isolated._write_manifest
                writes = 0

                def fail_typed_completion(root: Path, state: dict[str, object]) -> None:
                    nonlocal writes
                    writes += 1
                    if writes == 2:
                        raise OSError("typed completion manifest interrupted")
                    original_write(root, state)

                with patch.object(isolated, "_write_manifest", side_effect=fail_typed_completion):
                    with self.assertRaises(JobValidationError):
                        if operation == "full_asr":
                            service.transcribe(job["job_id"])
                        else:
                            service.inspect(job["job_id"])
                expected_before_retry = "source_ready" if operation == "full_asr" else "asr_ready"
                self.assertEqual(isolated.load_job(job["job_id"])["stage"], expected_before_retry)
                if operation == "full_asr":
                    self.assertEqual(service.transcribe(job["job_id"])["stage"], "asr_ready")
                else:
                    self.assertEqual(service.inspect(job["job_id"])["stage"], "inspected")

    def test_recovery_refuses_a_differing_partial_full_asr_file(self) -> None:
        # Break caught: a retry must not overwrite a partial immutable file whose bytes differ from the source-bound publication intent.
        original_atomic = asr_module._atomic_text
        job = IntakeService(self.store, FakeSourceAdapter(b"different partial")).intake(
            "https://archive.example/different-partial"
        )
        service = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter())

        def fail_after_full(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.name == "full.jsonl":
                raise OSError("full interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_full):
            with self.assertRaises(OSError):
                service.transcribe(job["job_id"])
        (self.store.job_root(job["job_id"]) / "asr" / "full.jsonl").write_text("different\n", encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            service.transcribe(job["job_id"])
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")

    def test_recovery_refuses_an_unsafe_partial_full_asr_output_path(self) -> None:
        # Break caught: an exact retry must fail before touching a reparse-replaced missing sibling output.
        import scripts.ggsm_transcription.store as store_module

        original_atomic = asr_module._atomic_text
        job = IntakeService(self.store, FakeSourceAdapter(b"unsafe partial")).intake(
            "https://archive.example/unsafe-partial"
        )
        model = FakeModelAdapter()
        service = ASRService(self.store, model, FakeMediaAdapter())

        def fail_after_full(path: Path, text: str) -> None:
            original_atomic(path, text)
            if path.name == "full.jsonl":
                raise OSError("full interrupted")

        with patch.object(asr_module, "_atomic_text", side_effect=fail_after_full):
            with self.assertRaises(OSError):
                service.transcribe(job["job_id"])
        metadata = self.store.job_root(job["job_id"]) / "asr" / "metadata.json"
        real_reparse = store_module._is_reparse
        with patch.object(
            store_module,
            "_is_reparse",
            side_effect=lambda path: Path(path) == metadata or real_reparse(path),
        ):
            with self.assertRaises(ArtifactValidationError):
                service.transcribe(job["job_id"])
        self.assertFalse(metadata.exists())
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")


class InspectionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(Path(self.tmp.name) / "data" / "transcribe")
        self.job = IntakeService(self.store, FakeSourceAdapter()).intake("https://archive.example/lecture")
        self.service = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter())
        self.service.transcribe(self.job["job_id"])

    def test_inspection_reports_beginning_middle_and_end_asr_uncovered_intervals_not_silence(self) -> None:
        # Break caught: a decoder gap was previously easy to misrepresent as audible recording silence.
        result = self.service.inspect(self.job["job_id"])
        report = json.loads((self.store.job_root(result["job_id"]) / "inspection" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["asr_uncovered_intervals"], [
            {"start": 0.0, "end": 5.0}, {"start": 10.0, "end": 12.0}, {"start": 20.0, "end": 30.0},
        ])
        markdown = (self.store.job_root(result["job_id"]) / "inspection" / "report.md").read_text(encoding="utf-8").lower()
        self.assertIn("asr-uncovered", markdown)
        self.assertIn("not inferred silence", markdown)
        self.assertNotIn("recording silence", markdown)
        self.assertEqual(result["stage"], "inspected")

    def test_inspection_revalidates_the_bound_source(self) -> None:
        # Break caught: inspection could advance even after the source no longer matched the hash-bound job.
        source = self.store.job_root(self.job["job_id"]) / "source" / "source.bin"
        source.write_bytes(b"changed before inspect")
        with self.assertRaises(ArtifactValidationError):
            self.service.inspect(self.job["job_id"])
        self.assertEqual(self.store.load_job(self.job["job_id"])["stage"], "asr_ready")

    def test_asr_ready_manifest_without_primary_evidence_or_provenance_is_invalid(self) -> None:
        # Break caught: a structurally incomplete primary evidence record could still accept later reruns.
        manifest = self.store.job_root(self.job["job_id"]) / "job.json"
        state = json.loads(manifest.read_text(encoding="utf-8"))
        state.pop("asr")
        manifest.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(RepositoryHealthError):
            self.store.load_job(self.job["job_id"])

    def test_bare_asr_ready_to_inspected_transition_cannot_commit_without_both_reports(self) -> None:
        # Break caught: an inspected state could be forged without the inspection evidence the stage represents.
        with self.assertRaises(StageTransitionError):
            self.store.advance_stage(self.job["job_id"], "inspected")
        self.assertEqual(self.store.load_job(self.job["job_id"])["stage"], "asr_ready")

    def test_inspection_rejects_out_of_order_raw_evidence_and_reports_confidence_and_repetition(self) -> None:
        # Break caught: corrupted raw JSONL could make coverage/diagnostics look trustworthy.
        invalid_job = IntakeService(self.store, FakeSourceAdapter(b"second source")).intake("https://archive.example/second")
        invalid = ASRService(self.store, FakeModelAdapter([
            {"id": 1, "start": 10.0, "end": 12.0, "text": " Later."},
            {"id": 0, "start": 5.0, "end": 9.0, "text": " Earlier.", "avg_logprob": -2.0},
        ]), FakeMediaAdapter())
        with self.assertRaisesRegex(JobValidationError, "out of order"):
            invalid.transcribe(invalid_job["job_id"])

        diagnostic_job = IntakeService(self.store, FakeSourceAdapter(b"third source")).intake("https://archive.example/third")
        diagnostic = ASRService(self.store, FakeModelAdapter([
            {"id": 0, "start": 0.0, "end": 5.0, "text": " Repeat.", "avg_logprob": -2.0},
            {"id": 1, "start": 5.0, "end": 8.0, "text": "repeat", "compression_ratio": 2.8},
        ]), FakeMediaAdapter())
        diagnostic.transcribe(diagnostic_job["job_id"])
        diagnostic.inspect(diagnostic_job["job_id"])
        report = json.loads((self.store.job_root(diagnostic_job["job_id"]) / "inspection" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["normalized_repeated_segments"], [{"normalized_text": "repeat", "segment_ids": [0, 1]}])
        self.assertEqual(report["confidence_outliers"], [{"id": 0, "reason": "low_avg_logprob", "value": -2.0}])
        self.assertEqual(report["suspicious_decoder_patterns"], [{"id": 1, "reason": "high_compression_ratio", "value": 2.8}])
