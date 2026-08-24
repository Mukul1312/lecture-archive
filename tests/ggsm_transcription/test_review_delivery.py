"""Contracts for whole-timeline editorial review and Listening-draft delivery."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

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
        return {"model_snapshot": "/fake/small", "faster_whisper": "1.2.1", "python": "fake",
                "ffmpeg": "fake", "ffprobe": "fake"}


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
            ("[00:00:00] Opening.\n\n[00:05:01] Too late.", "five minutes"),
        ):
            with self.subTest(body=body):
                job = self._inspected()
                service.prepare_review(job["job_id"])
                self._mark_reviewed(job["job_id"], [body])
                with self.assertRaisesRegex(JobValidationError, message):
                    service.record_review(job["job_id"])

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

    def test_commands_refuse_out_of_order_stages(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        with self.assertRaises(StageTransitionError):
            service.assemble(job["job_id"])
        with self.assertRaises(StageTransitionError):
            service.verify(job["job_id"])
        with self.assertRaises(StageTransitionError):
            service.handoff(job["job_id"])

    def test_aggregate_refuses_forged_review_delivery_and_handoff_stages_without_evidence(self) -> None:
        job = self._inspected()
        service = ReviewDeliveryService(self.store)
        with self.assertRaises(RepositoryHealthError):
            self.store.advance_stage(job["job_id"], "reviewed")
        service.prepare_review(job["job_id"])
        self._mark_reviewed(job["job_id"], ["[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing."])
        service.record_review(job["job_id"])
        with self.assertRaises(RepositoryHealthError):
            self.store.advance_stage(job["job_id"], "draft_ready")
        service.assemble(job["job_id"])
        service.verify(job["job_id"])
        with self.assertRaises(RepositoryHealthError):
            self.store.advance_stage(job["job_id"], "handed_off")


if __name__ == "__main__":
    unittest.main()
