"""Contracts for local GGSM ASR evidence and ASR-uncovered inspection."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ggsm_transcription.asr import ASRService, DEFAULT_ASR_CONFIGURATION, FfmpegMediaAdapter, LocalFasterWhisperAdapter
from scripts.ggsm_transcription.intake import IntakeService, SourceDownload
from scripts.ggsm_transcription.store import ArtifactValidationError, JobStore, JobValidationError, RepositoryHealthError


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
