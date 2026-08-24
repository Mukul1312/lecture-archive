"""Contracts for local GGSM ASR evidence and ASR-uncovered inspection."""

from __future__ import annotations

import hashlib
import json
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
        return {"model_snapshot": "/fake/snapshot", "faster_whisper": "fake-1.2.1", "python": "fake-python", "ffmpeg": "fake-ffmpeg", "ffprobe": "fake-ffprobe"}


class FakeMediaAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, float, float]] = []

    def extract_span(self, source: Path, target: Path, start: float, end: float) -> None:
        self.calls.append((source, target, start, end))
        target.write_bytes(source.read_bytes() + f"{start}:{end}".encode())

    def runtime_metadata(self) -> dict[str, str]:
        return {"ffmpeg": "fake-ffmpeg", "ffprobe": "fake-ffprobe"}


class ASRContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(Path(self.tmp.name) / "data" / "transcribe")
        self.job = IntakeService(self.store, FakeSourceAdapter()).intake("https://archive.example/lecture")
        self.model = FakeModelAdapter()
        self.media = FakeMediaAdapter()
        self.service = ASRService(self.store, self.model, self.media)

    def test_full_run_uses_the_fixed_configuration_and_records_runtime_metadata(self) -> None:
        # Break caught: a quiet model/configuration change makes a future draft irreproducible.
        result = self.service.transcribe(self.job["job_id"])
        self.assertEqual(self.model.calls[0][1], DEFAULT_ASR_CONFIGURATION)
        self.assertEqual(result["stage"], "asr_ready")
        metadata = json.loads((self.store.job_root(result["job_id"]) / "asr" / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["configuration"], DEFAULT_ASR_CONFIGURATION)
        self.assertEqual(metadata["runtime"]["model_snapshot"], "/fake/snapshot")
        self.assertEqual(metadata["source_sha256"], hashlib.sha256(b"source audio").hexdigest())
        self.store.validate_artifact(result["job_id"], "asr/full.jsonl")
        self.store.validate_artifact(result["job_id"], "asr/metadata.json")

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
        self.assertEqual(calls["transcription"], ("source.bin", {"language": "en", "beam_size": 5, "word_timestamps": True, "vad_filter": False, "condition_on_previous_text": False}))
        self.assertEqual(records[0]["id"], 7)

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
        service = ASRService(self.store, FakeModelAdapter(), FakeMediaAdapter())

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
