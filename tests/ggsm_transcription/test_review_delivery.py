"""Contracts for whole-timeline editorial review and Listening-draft delivery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

import scripts.ggsm_transcription.review as review_module
from scripts.ggsm_transcription.asr import ASRService
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
    def __init__(self, payload: bytes, duration: float) -> None:
        self.payload, self.duration = payload, duration

    def download(self, _url: str, staging_path: Path) -> SourceDownload:
        staging_path.write_bytes(self.payload)
        return SourceDownload("https://archive.example/final/lecture.mp3", "Sri Baladeva Tattva.mp3", {"downloader": "fake"})

    def probe(self, _path: Path) -> dict[str, object]:
        return {"duration_seconds": self.duration, "codec": "mp3",
                "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
                "tool_versions": {"downloader": "fake", "ffprobe": "fake"}}


class FakeModelAdapter:
    def __init__(self, segments: list[dict[str, object]]) -> None:
        self.segments = segments

    def transcribe(self, _path: Path, _configuration: dict[str, object]) -> list[dict[str, object]]:
        return self.segments

    def runtime_metadata(self) -> dict[str, str]:
        return {
            "execution_mode": "local",
            "model_snapshot": "/fake/small",
            "faster_whisper": "1.2.1",
            "python": "fake",
            "ffmpeg": "fake",
            "ffprobe": "fake",
        }


class ReviewDeliveryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(Path(self.tmp.name) / "data" / "transcribe")
        self.counter = 0

    def _inspected(self, duration: float = 620.0, segments: list[dict[str, object]] | None = None):
        self.counter += 1
        payload = f"source-{self.counter}".encode()
        if segments is None:
            segments = [
                {"id": 0, "start": 0.0, "end": 100.0, "text": " Opening words."},
                {"id": 1, "start": 200.0, "end": duration, "text": " Closing words."},
            ]
        job = IntakeService(self.store, FakeSourceAdapter(payload, duration)).intake(
            f"https://archive.example/lecture-{self.counter}.mp3"
        )
        asr = ASRService(self.store, FakeModelAdapter(segments))
        asr.transcribe(job["job_id"])
        return asr.inspect(job["job_id"])

    def _mark_reviewed(self, job_id: str, bodies: list[str]) -> list[Path]:
        manifest = json.loads((self.store.job_root(job_id) / "review" / "manifest.json").read_text(encoding="utf-8"))
        paths = []
        for entry, body in zip(manifest["chunks"], bodies, strict=True):
            path = self.store.job_root(job_id) / entry["path"]
            text = path.read_text(encoding="utf-8").replace("Review-State: pending", "Review-State: reviewed")
            before, _separator, _old = text.partition("## Editorial transcript\n")
            path.write_text(before + "## Editorial transcript\n\n" + body.strip() + "\n", encoding="utf-8", newline="\n")
            paths.append(path)
        return paths

    def _reviewed(self):
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        service.prepare_review(job["job_id"])
        self._mark_reviewed(job["job_id"], ["[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing."])
        service.record_review(job["job_id"])
        return job, service

    def _replace_with_directory_link(self, path: Path, target: Path) -> None:
        path.rmdir()
        try:
            path.symlink_to(target, target_is_directory=True)
            return
        except OSError:
            if os.name != "nt":
                self.skipTest("directory symlink creation is unavailable")
        completed = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(path), str(target)],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.skipTest("directory junction creation is unavailable")

    def test_prepare_review_uses_asr_boundaries_and_covers_short_and_gapped_timelines(self) -> None:
        long = self._inspected(3700.0, [
            {"id": 0, "start": 20.0, "end": 1790.0, "text": " First."},
            {"id": 1, "start": 1900.0, "end": 3585.0, "text": " Second."},
        ])
        service = ReviewDeliveryService(self.store)
        manifest = service.prepare_review(long["job_id"])
        spans = [(item["start_seconds"], item["end_seconds"]) for item in manifest["chunks"]]
        self.assertEqual(spans, [(0.0, 1790.0), (1790.0, 3585.0), (3585.0, 3700.0)])
        self.assertEqual(manifest["asr_gap_policy"], "ASR-uncovered intervals are not inferred silence")
        self.assertFalse(any(path.startswith("review/") for path in self.store.load_job(long["job_id"])["artifacts"]))
        for before, after in zip(manifest["chunks"], manifest["chunks"][1:]):
            self.assertEqual(before["end_seconds"], after["start_seconds"])

        short = self._inspected(90.0, [])
        short_manifest = service.prepare_review(short["job_id"])
        self.assertEqual([(c["start_seconds"], c["end_seconds"]) for c in short_manifest["chunks"]], [(0.0, 90.0)])
        chunk = self.store.job_root(short["job_id"]) / short_manifest["chunks"][0]["path"]
        chunk_text = chunk.read_text(encoding="utf-8")
        self.assertIn("listen to the complete assigned span", chunk_text.lower())
        self.assertIn("ASR-uncovered", chunk_text)
        self.assertIn("not inferred silence", chunk_text)

    def test_record_review_registers_only_complete_explicitly_reviewed_ordered_chunks(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        manifest = service.prepare_review(job["job_id"])
        self._mark_reviewed(job["job_id"], ["[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing."])
        result = service.record_review(job["job_id"])
        self.assertEqual(result["stage"], "reviewed")
        final_manifest = json.loads(self.store.validate_artifact(job["job_id"], "review/manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(all(chunk["reviewed"] for chunk in final_manifest["chunks"]))
        for chunk in manifest["chunks"]:
            self.store.validate_artifact(job["job_id"], chunk["path"])

    def test_record_review_refuses_missing_unreviewed_unordered_noncovering_or_rebound_chunks(self) -> None:
        service = ReviewDeliveryService(self.store)
        cases = ("missing", "unreviewed", "unordered", "noncovering", "rebound", "extra")
        for case in cases:
            with self.subTest(case=case):
                job = (self._inspected(3700.0, [
                    {"id": 0, "start": 0.0, "end": 1790.0, "text": " First."},
                    {"id": 1, "start": 1790.0, "end": 3585.0, "text": " Second."},
                    {"id": 2, "start": 3585.0, "end": 3700.0, "text": " Third."},
                ]) if case == "unordered" else self._inspected())
                manifest = service.prepare_review(job["job_id"])
                bodies = ([
                    "[00:00:00] First.\n\n[00:05:00] More.\n\n[00:10:00] More.\n\n[00:15:00] More.\n\n[00:20:00] More.\n\n[00:25:00] More.",
                    "[00:29:50] Second.\n\n[00:34:50] More.\n\n[00:39:50] More.\n\n[00:44:50] More.\n\n[00:49:50] More.\n\n[00:54:50] More.",
                    "[00:59:45] Third.\n\n[01:01:00] Closing.",
                ] if case == "unordered" else ["[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing."])
                paths = self._mark_reviewed(job["job_id"], bodies)
                manifest_path = self.store.job_root(job["job_id"]) / "review" / "manifest.json"
                if case == "missing":
                    paths[0].unlink()
                elif case == "unreviewed":
                    paths[0].write_text(paths[0].read_text(encoding="utf-8").replace("Review-State: reviewed", "Review-State: pending"), encoding="utf-8")
                elif case == "unordered":
                    manifest["chunks"] = list(reversed(manifest["chunks"]))
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                elif case == "noncovering":
                    manifest["chunks"][0]["start_seconds"] = 1.0
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                elif case == "rebound":
                    paths[0].write_text(paths[0].read_text(encoding="utf-8").replace(job["source_sha256"], "f" * 64), encoding="utf-8")
                else:
                    (self.store.job_root(job["job_id"]) / "review" / "chunk-extra.md").write_text("extra", encoding="utf-8")
                with self.assertRaises((ArtifactValidationError, JobValidationError)):
                    service.record_review(job["job_id"])
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "inspected")

    def test_reference_capture_is_nfc_secondary_evidence_and_never_changes_stage_or_review(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        manifest = service.prepare_review(job["job_id"])
        before_manifest = (self.store.job_root(job["job_id"]) / "review" / "manifest.json").read_bytes()
        source = Path(self.tmp.name) / "reference.md"
        source.write_text("Reference-only Cafe\u0301 sentence.", encoding="utf-8")
        result = service.register_reference(job["job_id"], "https://www.taptajivanam.com/example", source)
        self.assertEqual(result["stage"], "inspected")
        stored = self.store.validate_artifact(job["job_id"], "reference/taptajivanam.md")
        self.assertEqual(stored.read_text(encoding="utf-8"), "Reference-only Café sentence.")
        provenance = json.loads(self.store.validate_artifact(job["job_id"], "reference/provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["url"], "https://www.taptajivanam.com/example")
        self.assertEqual(provenance["input_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual((self.store.job_root(job["job_id"]) / "review" / "manifest.json").read_bytes(), before_manifest)
        self.assertFalse(any(chunk["reviewed"] for chunk in manifest["chunks"]))

    def test_reference_publication_resumes_without_changing_its_original_provenance(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        source = Path(self.tmp.name) / "recoverable-reference.md"
        source.write_text("Secondary evidence.", encoding="utf-8")
        with patch.object(self.store, "_write_manifest", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(JobValidationError):
                service.register_reference(job["job_id"], "https://www.taptajivanam.com/recover", source)
        provenance_path = self.store.job_root(job["job_id"]) / "reference" / "provenance.json"
        original = provenance_path.read_bytes()
        result = service.register_reference(job["job_id"], "https://www.taptajivanam.com/recover", source)
        self.assertEqual(result["stage"], "inspected")
        self.assertEqual(provenance_path.read_bytes(), original)
        self.store.validate_artifact(job["job_id"], "reference/taptajivanam.md")
        self.store.validate_artifact(job["job_id"], "reference/provenance.json")

    def test_prepare_review_recovers_each_interrupted_file_boundary_without_mislabeling_io(self) -> None:
        original = review_module._atomic_text
        for failure_index in range(1, 5):
            with self.subTest(failure_index=failure_index):
                job = self._inspected(3700.0, [
                    {"id": 0, "start": 0.0, "end": 1790.0, "text": " First."},
                    {"id": 1, "start": 1790.0, "end": 3585.0, "text": " Second."},
                    {"id": 2, "start": 3585.0, "end": 3700.0, "text": " Third."},
                ])
                calls = 0

                def interrupted(path: Path, text: str) -> None:
                    nonlocal calls
                    calls += 1
                    if calls == failure_index:
                        raise OSError("artifact write interrupted")
                    original(path, text)

                with patch.object(review_module, "_atomic_text", side_effect=interrupted):
                    with self.assertRaisesRegex(OSError, "artifact write interrupted"):
                        ReviewDeliveryService(self.store).prepare_review(job["job_id"])
                manifest = ReviewDeliveryService(self.store).prepare_review(job["job_id"])
                self.assertEqual(len(manifest["chunks"]), 3)

    def test_prepare_review_never_overwrites_an_edited_or_unknown_partial_retry(self) -> None:
        original = review_module._atomic_text
        job = self._inspected(3700.0, [
            {"id": 0, "start": 0.0, "end": 1790.0, "text": " First."},
            {"id": 1, "start": 1790.0, "end": 3585.0, "text": " Second."},
            {"id": 2, "start": 3585.0, "end": 3700.0, "text": " Third."},
        ])
        calls = 0

        def interrupted(path: Path, text: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("stop after first chunk")
            original(path, text)

        with patch.object(review_module, "_atomic_text", side_effect=interrupted):
            with self.assertRaises(OSError):
                ReviewDeliveryService(self.store).prepare_review(job["job_id"])
        first = self.store.job_root(job["job_id"]) / "review" / "chunk-001.md"
        first.write_text(first.read_text(encoding="utf-8") + "human edit\n", encoding="utf-8")
        edited = first.read_bytes()
        with self.assertRaises(ArtifactValidationError):
            ReviewDeliveryService(self.store).prepare_review(job["job_id"])
        self.assertEqual(first.read_bytes(), edited)

        unknown = self._inspected()
        unknown_path = self.store.job_root(unknown["job_id"]) / "review" / "unknown.md"
        unknown_path.write_text("unknown", encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            ReviewDeliveryService(self.store).prepare_review(unknown["job_id"])
        self.assertEqual(unknown_path.read_text(encoding="utf-8"), "unknown")

    def test_reference_recovers_target_only_and_provenance_only_interruptions_but_rejects_different_retry(self) -> None:
        original = review_module._atomic_text
        url = "https://www.taptajivanam.com/recovery-boundary"
        source = Path(self.tmp.name) / "boundary-reference.md"
        source.write_text("Original reference.", encoding="utf-8")

        for failure_index in (1, 2, 3):
            with self.subTest(failure_index=failure_index):
                job = self._inspected()
                calls = 0

                def interrupted(path: Path, text: str) -> None:
                    nonlocal calls
                    calls += 1
                    if calls == failure_index:
                        raise OSError("reference write interrupted")
                    original(path, text)

                with patch.object(review_module, "_atomic_text", side_effect=interrupted):
                    with self.assertRaisesRegex(OSError, "reference write interrupted"):
                        ReviewDeliveryService(self.store).register_reference(job["job_id"], url, source)
                ReviewDeliveryService(self.store).register_reference(job["job_id"], url, source)
                self.store.validate_artifact(job["job_id"], "reference/taptajivanam.md")
                self.store.validate_artifact(job["job_id"], "reference/provenance.json")

        provenance_only = self._inspected()

        def omit_target(path: Path, text: str) -> None:
            if path.name != "taptajivanam.md":
                original(path, text)

        with patch.object(review_module, "_atomic_text", side_effect=omit_target):
            with self.assertRaises(ArtifactValidationError):
                ReviewDeliveryService(self.store).register_reference(provenance_only["job_id"], url, source)
        ReviewDeliveryService(self.store).register_reference(provenance_only["job_id"], url, source)
        self.store.validate_artifact(provenance_only["job_id"], "reference/taptajivanam.md")

        different = self._inspected()
        calls = 0

        def target_only(path: Path, text: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("leave target only")
            original(path, text)

        with patch.object(review_module, "_atomic_text", side_effect=target_only):
            with self.assertRaises(OSError):
                ReviewDeliveryService(self.store).register_reference(different["job_id"], url, source)
        target = self.store.job_root(different["job_id"]) / "reference" / "taptajivanam.md"
        original_target = target.read_bytes()
        with self.assertRaises(ArtifactValidationError):
            ReviewDeliveryService(self.store).register_reference(
                different["job_id"], "https://www.taptajivanam.com/different-url", source
            )
        self.assertEqual(target.read_bytes(), original_target)
        changed = Path(self.tmp.name) / "different-reference.md"
        changed.write_text("Different reference.", encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            ReviewDeliveryService(self.store).register_reference(different["job_id"], url, changed)
        self.assertEqual(target.read_bytes(), original_target)

    def test_record_review_requires_audio_confirmation_for_recording_silence_not_an_asr_gap(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        service.prepare_review(job["job_id"])
        paths = self._mark_reviewed(job["job_id"], [
            "[00:00:00] Opening.\n\n[Recording silence, 00:01:40-00:03:20]\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing."
        ])
        with self.assertRaisesRegex(JobValidationError, "audible silence"):
            service.record_review(job["job_id"])
        paths[0].write_text(paths[0].read_text(encoding="utf-8").replace(
            "Audible-Silence-Confirmed: none", "Audible-Silence-Confirmed: 00:01:40-00:03:20"
        ), encoding="utf-8")
        self.assertEqual(service.record_review(job["job_id"])["stage"], "reviewed")

    def test_assembly_is_deterministic_nfc_and_keeps_only_exact_editorial_markers(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        service.prepare_review(job["job_id"])
        reference = Path(self.tmp.name) / "secondary.md"
        reference.write_text("Reference-only line must not enter delivery.", encoding="utf-8")
        service.register_reference(job["job_id"], "https://www.taptajivanam.com/secondary", reference)
        self._mark_reviewed(job["job_id"], [
            "[00:00:00] Speaker: Cafe\u0301 opening.\n\n"
            "[Non-English interpretation omitted, 00:01:40-00:03:20]\n\n"
            "[00:05:00] English lecture continues.\n\n"
            "[Indistinct English speech, 00:08:00-00:08:05]\n\n"
            "[00:10:00] Closing."
        ])
        service.record_review(job["job_id"])
        first = service.assemble(job["job_id"]).read_bytes()
        second = service.assemble(job["job_id"]).read_bytes()
        text = first.decode("utf-8")
        self.assertEqual(first, second)
        self.assertEqual(text, unicodedata.normalize("NFC", text))
        self.assertIn("Status: Listening draft", text)
        self.assertIn("Source URL: https://archive.example/lecture-", text)
        self.assertIn("Title: Sri Baladeva Tattva", text)
        self.assertIn("Duration: 00:10:20", text)
        self.assertIn("Manual OneNote copy/editing is outside this runner.", text)
        self.assertIn("[Non-English interpretation omitted, 00:01:40-00:03:20]", text)
        self.assertNotIn("Reference-only", text)
        self.assertNotIn("sha256", text.lower())

    def test_final_evidence_publication_resumes_after_manifest_replace_failure(self) -> None:
        # Break caught: a crash after a final evidence file was written could otherwise strand the job forever.
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        service.prepare_review(job["job_id"])
        self._mark_reviewed(job["job_id"], ["[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing."])
        with patch.object(self.store, "_write_manifest", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(JobValidationError):
                service.record_review(job["job_id"])
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "inspected")
        self.assertEqual(service.record_review(job["job_id"])["stage"], "reviewed")
        service.assemble(job["job_id"])
        with patch.object(self.store, "_write_manifest", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(JobValidationError):
                service.verify(job["job_id"])
        self.assertEqual(service.verify(job["job_id"])["stage"], "draft_ready")
        with patch.object(self.store, "_write_manifest", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(JobValidationError):
                service.handoff(job["job_id"])
        self.assertEqual(service.handoff(job["job_id"])["stage"], "handed_off")

    def test_assembly_refuses_unknown_markers_and_timestamps_more_than_five_minutes_apart(self) -> None:
        service = ReviewDeliveryService(self.store)
        for body, message in (
            ("[00:00:00] Opening.\n\n[Uncertain, 00:01:00-00:01:05]\n\n[00:05:00] Closing.", "marker"),
            ("[00:00:00] Opening.\n[Uncertain, 00:01:00-00:01:05]\n\n[00:05:00] Closing.", "marker"),
            ("[00:00:00] Prose says Recording silence, 00:01:00-00:01:05.\n\n[00:05:00] More.\n\n[00:05:20] Closing.", "marker"),
            ("[00:00:00] Opening.\n\n[00:05:01] Too late.", "five minutes"),
        ):
            with self.subTest(body=body):
                job = self._inspected()
                service.prepare_review(job["job_id"])
                self._mark_reviewed(job["job_id"], [body])
                with self.assertRaisesRegex(JobValidationError, message):
                    service.record_review(job["job_id"])

    def test_review_timestamp_coverage_includes_terminal_tail_and_exact_five_minutes(self) -> None:
        service = ReviewDeliveryService(self.store)
        too_long = self._inspected()
        service.prepare_review(too_long["job_id"])
        self._mark_reviewed(too_long["job_id"], [
            "[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:05:19] Last timestamp."
        ])
        with self.assertRaisesRegex(JobValidationError, "five minutes"):
            service.record_review(too_long["job_id"])

        exact = self._inspected()
        service.prepare_review(exact["job_id"])
        self._mark_reviewed(exact["job_id"], [
            "[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:05:20] Exactly five minutes remain."
        ])
        self.assertEqual(service.record_review(exact["job_id"])["stage"], "reviewed")

    def test_review_timestamp_coverage_is_global_across_chunk_boundaries(self) -> None:
        job = self._inspected(3600.5, [
            {"id": 0, "start": 0.0, "end": 1800.5, "text": " First half."},
            {"id": 1, "start": 1800.5, "end": 3600.5, "text": " Second half."},
        ])
        service = ReviewDeliveryService(self.store)
        manifest = service.prepare_review(job["job_id"])
        self.assertEqual(len(manifest["chunks"]), 2)
        self._mark_reviewed(job["job_id"], [
            "\n\n".join(f"[{hour}] First." for hour in (
                "00:00:00", "00:05:00", "00:10:00", "00:15:00", "00:20:00", "00:25:00"
            )),
            "\n\n".join(f"[{hour}] Second." for hour in (
                "00:30:01", "00:35:01", "00:40:01", "00:45:01", "00:50:01", "00:55:01", "01:00:00"
            )),
        ])
        with self.assertRaisesRegex(JobValidationError, "five minutes"):
            service.record_review(job["job_id"])

    def test_fractional_raw_boundaries_remain_exact_with_recordable_whole_second_markers(self) -> None:
        job = self._inspected(3700.5, [
            {"id": 0, "start": 0.0, "end": 1790.5, "text": " First."},
            {"id": 1, "start": 1790.5, "end": 3585.5, "text": " Second."},
            {"id": 2, "start": 3585.5, "end": 3700.5, "text": " Third."},
        ])
        service = ReviewDeliveryService(self.store)
        manifest = service.prepare_review(job["job_id"])
        self.assertEqual(
            [(chunk["start_seconds"], chunk["end_seconds"]) for chunk in manifest["chunks"]],
            [(0.0, 1790.5), (1790.5, 3585.5), (3585.5, 3700.5)],
        )
        self.assertEqual(manifest["clock_representation_tolerance_seconds"], 1.0)
        self.assertIn("raw source and chunk coverage remains exact", manifest["clock_representation_policy"])
        second_chunk = self.store.job_root(job["job_id"]) / "review" / "chunk-002.md"
        self.assertIn("[00:29:51] Second.", second_chunk.read_text(encoding="utf-8"))
        self._mark_reviewed(job["job_id"], [
            "[Indistinct English speech, 00:00:00-00:29:50]",
            "[Non-English interpretation omitted, 00:29:50-00:59:45]",
            "[Indistinct English speech, 00:59:45-01:01:41]",
        ])
        self.assertEqual(service.record_review(job["job_id"])["stage"], "reviewed")

        exact = self._inspected(3600.0, [
            {"id": 0, "start": 0.0, "end": 1800.0, "text": " First."},
            {"id": 1, "start": 1800.0, "end": 3600.0, "text": " Second."},
        ])
        service.prepare_review(exact["job_id"])
        self._mark_reviewed(exact["job_id"], [
            "[Indistinct English speech, 00:00:00-00:29:59]",
            "[Indistinct English speech, 00:29:59-01:00:00]",
        ])
        with self.assertRaisesRegex(JobValidationError, "outside"):
            service.record_review(exact["job_id"])

    def test_verify_fails_closed_on_changed_source_delivery_or_review_and_handoff_is_manual_only(self) -> None:
        service = ReviewDeliveryService(self.store)

        def assembled():
            job = self._inspected()
            service.prepare_review(job["job_id"])
            self._mark_reviewed(job["job_id"], ["[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing."])
            service.record_review(job["job_id"])
            service.assemble(job["job_id"])
            return job

        for evidence in ("source", "delivery", "review"):
            with self.subTest(evidence=evidence):
                job = assembled()
                root = self.store.job_root(job["job_id"])
                path = {"source": root / "source" / "source.bin",
                        "delivery": root / "delivery" / "onenote-transcript.md",
                        "review": root / "review" / "chunk-001.md"}[evidence]
                path.write_bytes(path.read_bytes() + b"changed")
                with self.assertRaises(ArtifactValidationError):
                    service.verify(job["job_id"])
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "reviewed")

        job = assembled()
        verified = service.verify(job["job_id"])
        self.assertEqual(verified["stage"], "draft_ready")
        handed = service.handoff(job["job_id"])
        self.assertEqual(handed["stage"], "handed_off")
        receipt = json.loads(self.store.validate_artifact(job["job_id"], "delivery/handoff.json").read_text(encoding="utf-8"))
        self.assertIn("ready for manual OneNote copy/editing", receipt["message"])
        self.assertFalse(receipt["copied_or_synced"])

    def test_handoff_revalidates_every_current_evidence_layer_after_verification(self) -> None:
        service = ReviewDeliveryService(self.store)
        for relative in (
            "asr/full.jsonl",
            "inspection/report.json",
            "review/manifest.json",
            "review/chunk-001.md",
        ):
            with self.subTest(relative=relative):
                job, _ = self._reviewed()
                service.assemble(job["job_id"])
                service.verify(job["job_id"])
                path = self.store.job_root(job["job_id"]) / relative
                path.write_bytes(path.read_bytes() + b"tampered")
                with self.assertRaises(ArtifactValidationError):
                    service.handoff(job["job_id"])
                self.assertEqual(self.store.load_job(job["job_id"])["stage"], "draft_ready")

    def test_commands_refuse_out_of_order_stages(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        with self.assertRaises(StageTransitionError):
            service.assemble(job["job_id"])
        with self.assertRaises(StageTransitionError):
            service.verify(job["job_id"])
        with self.assertRaises(StageTransitionError):
            service.handoff(job["job_id"])

    def test_output_directory_reparse_is_rejected_before_any_external_write(self) -> None:
        service = ReviewDeliveryService(self.store)
        cases: list[tuple[str, dict[str, object], object]] = []

        review_job = self._inspected()
        cases.append(("review", review_job, lambda: service.prepare_review(review_job["job_id"])))

        reference_job = self._inspected()
        reference_input = Path(self.tmp.name) / "safe-reference.md"
        reference_input.write_text("Reference.", encoding="utf-8")
        cases.append(("reference", reference_job, lambda: service.register_reference(
            reference_job["job_id"], "https://www.taptajivanam.com/safe", reference_input
        )))

        delivery_job, _ = self._reviewed()
        cases.append(("delivery", delivery_job, lambda: service.assemble(delivery_job["job_id"])))

        for name, job, operation in cases:
            with self.subTest(name=name):
                outside = Path(self.tmp.name) / f"outside-{name}"
                outside.mkdir()
                sentinel = outside / "sentinel.txt"
                sentinel.write_text("unchanged", encoding="utf-8")
                output = self.store.job_root(str(job["job_id"])) / name
                self._replace_with_directory_link(output, outside)
                with self.assertRaises((ArtifactValidationError, RepositoryHealthError)):
                    operation()  # type: ignore[operator]
                self.assertEqual({path.name for path in outside.iterdir()}, {"sentinel.txt"})
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_aggregate_refuses_forged_review_delivery_and_handoff_stages_without_evidence(self) -> None:
        def register_junk(job_id: str, paths: list[str]) -> None:
            root = self.store.job_root(job_id)
            for relative in paths:
                path = root / relative
                path.write_text("junk", encoding="utf-8")
                self.store.register_artifact(job_id, relative)

        inspected = self._inspected()
        register_junk(inspected["job_id"], ["review/manifest.json", "review/chunk-001.md"])
        with self.assertRaises(StageTransitionError):
            self.store.advance_stage(inspected["job_id"], "reviewed")

        direct = self._inspected()
        register_junk(direct["job_id"], ["review/manifest.json", "review/chunk-001.md"])
        with self.assertRaises(StageTransitionError):
            with self.store.transaction(direct["job_id"]) as transaction:
                transaction.advance_stage("reviewed")

        reviewed, service = self._reviewed()
        register_junk(reviewed["job_id"], ["delivery/onenote-transcript.md", "delivery/verification.json"])
        with self.assertRaises(StageTransitionError):
            self.store.advance_stage(reviewed["job_id"], "draft_ready")

        draft, service = self._reviewed()
        service.assemble(draft["job_id"])
        service.verify(draft["job_id"])
        register_junk(draft["job_id"], ["delivery/handoff.json"])
        with self.assertRaises(StageTransitionError):
            self.store.advance_stage(draft["job_id"], "handed_off")

    def test_remaining_low_level_and_typed_completion_paths_reject_junk_evidence(self) -> None:
        def register_junk(job_id: str, paths: list[str]) -> None:
            root = self.store.job_root(job_id)
            for relative in paths:
                path = root / relative
                path.write_text("junk", encoding="utf-8")
                self.store.register_artifact(job_id, relative)

        legacy_review = self._inspected()
        register_junk(legacy_review["job_id"], ["review/manifest.json", "review/chunk-001.md"])
        with self.assertRaises((AttributeError, StageTransitionError)):
            with self.store.transaction(legacy_review["job_id"]) as transaction:
                transaction._advance_stage("reviewed")

        legacy_draft, service = self._reviewed()
        register_junk(legacy_draft["job_id"], ["delivery/onenote-transcript.md", "delivery/verification.json"])
        with self.assertRaises((AttributeError, StageTransitionError)):
            with self.store.transaction(legacy_draft["job_id"]) as transaction:
                transaction._advance_stage("draft_ready")

        legacy_handoff, service = self._reviewed()
        service.assemble(legacy_handoff["job_id"])
        service.verify(legacy_handoff["job_id"])
        register_junk(legacy_handoff["job_id"], ["delivery/handoff.json"])
        with self.assertRaises((AttributeError, StageTransitionError)):
            with self.store.transaction(legacy_handoff["job_id"]) as transaction:
                transaction._advance_stage("handed_off")

        typed_review = self._inspected()
        register_junk(typed_review["job_id"], ["review/manifest.json", "review/chunk-001.md"])
        with self.assertRaises((ArtifactValidationError, JobValidationError)):
            with self.store.transaction(typed_review["job_id"]) as transaction:
                transaction.complete_review()

        typed_draft, _ = self._reviewed()
        register_junk(typed_draft["job_id"], ["delivery/onenote-transcript.md", "delivery/verification.json"])
        with self.assertRaises((ArtifactValidationError, JobValidationError)):
            with self.store.transaction(typed_draft["job_id"]) as transaction:
                transaction.complete_verification()

        typed_handoff, service = self._reviewed()
        service.assemble(typed_handoff["job_id"])
        service.verify(typed_handoff["job_id"])
        register_junk(typed_handoff["job_id"], ["delivery/handoff.json"])
        with self.assertRaises((ArtifactValidationError, JobValidationError)):
            with self.store.transaction(typed_handoff["job_id"]) as transaction:
                transaction.complete_handoff()

    def test_each_typed_completion_resumes_after_publication_commit_boundary_failure(self) -> None:
        original_writer = self.store._write_manifest

        def fail_second_manifest_write():
            calls = 0

            def writer(root: Path, state: dict[str, object]) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("completion manifest interrupted")
                original_writer(root, state)  # type: ignore[arg-type]

            return writer

        review = self._inspected()
        service = ReviewDeliveryService(self.store)
        service.prepare_review(review["job_id"])
        self._mark_reviewed(review["job_id"], ["[00:00:00] Opening.\n\n[00:05:00] More.\n\n[00:10:00] Closing."])
        with patch.object(self.store, "_write_manifest", side_effect=fail_second_manifest_write()):
            with self.assertRaisesRegex(JobValidationError, "manifest replacement"):
                service.record_review(review["job_id"])
        self.assertEqual(self.store.load_job(review["job_id"])["stage"], "inspected")
        self.store.validate_artifact(review["job_id"], "review/manifest.json")
        self.assertEqual(service.record_review(review["job_id"])["stage"], "reviewed")

        verification, service = self._reviewed()
        service.assemble(verification["job_id"])
        with patch.object(self.store, "_write_manifest", side_effect=fail_second_manifest_write()):
            with self.assertRaisesRegex(JobValidationError, "manifest replacement"):
                service.verify(verification["job_id"])
        self.assertEqual(self.store.load_job(verification["job_id"])["stage"], "reviewed")
        self.store.validate_artifact(verification["job_id"], "delivery/verification.json")
        self.assertEqual(service.verify(verification["job_id"])["stage"], "draft_ready")

        handoff, service = self._reviewed()
        service.assemble(handoff["job_id"])
        service.verify(handoff["job_id"])
        with patch.object(self.store, "_write_manifest", side_effect=fail_second_manifest_write()):
            with self.assertRaisesRegex(JobValidationError, "manifest replacement"):
                service.handoff(handoff["job_id"])
        self.assertEqual(self.store.load_job(handoff["job_id"])["stage"], "draft_ready")
        self.store.validate_artifact(handoff["job_id"], "delivery/handoff.json")
        self.assertEqual(service.handoff(handoff["job_id"])["stage"], "handed_off")

    def test_review_completion_rejects_extra_inventory_after_publication_boundary(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        service.prepare_review(job["job_id"])
        self._mark_reviewed(
            job["job_id"],
            ["[00:00:00] Opening.\n\n[00:05:00] More.\n\n[00:10:00] Closing."],
        )
        original_writer = self.store._write_manifest
        calls = 0

        def fail_completion_manifest(root: Path, state: dict[str, object]) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("completion manifest interrupted")
            original_writer(root, state)  # type: ignore[arg-type]

        with patch.object(self.store, "_write_manifest", side_effect=fail_completion_manifest):
            with self.assertRaisesRegex(JobValidationError, "manifest replacement"):
                service.record_review(job["job_id"])

        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "inspected")
        extra = self.store.job_root(job["job_id"]) / "review" / "chunk-999.md"
        extra.write_text("unregistered extra review evidence", encoding="utf-8")

        with self.assertRaisesRegex(ArtifactValidationError, "unexpected"):
            with self.store.transaction(job["job_id"]) as transaction:
                transaction.complete_review()
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "inspected")

        extra.unlink()
        self.assertEqual(service.record_review(job["job_id"])["stage"], "reviewed")

    def test_extra_review_inventory_is_rejected_by_assembly_verify_and_handoff(self) -> None:
        for operation in ("assemble", "verify", "handoff"):
            with self.subTest(operation=operation):
                job, service = self._reviewed()
                if operation in {"verify", "handoff"}:
                    service.assemble(job["job_id"])
                if operation == "handoff":
                    service.verify(job["job_id"])
                extra = self.store.job_root(job["job_id"]) / "review" / "chunk-999.md"
                extra.write_text("unregistered extra review evidence", encoding="utf-8")

                with self.assertRaisesRegex(ArtifactValidationError, "unexpected"):
                    getattr(service, operation)(job["job_id"])


if __name__ == "__main__":
    unittest.main()
