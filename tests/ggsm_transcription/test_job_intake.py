"""Behavioral contracts for hash-bound transcription job intake."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.ggsm_transcription.intake import IntakeService, SourceDownload
from scripts.ggsm_transcription.store import (
    ArtifactValidationError,
    JobLockError,
    JobStore,
    JobValidationError,
    StageTransitionError,
    make_job_id,
    validate_job_id,
)


class FakeSourceAdapter:
    """A deterministic local replacement for HTTP download and ffprobe."""

    def __init__(self, payload: bytes = b"recording bytes") -> None:
        self.payload = payload
        self.download_calls = 0

    def download(self, requested_url: str, staging_path: Path) -> SourceDownload:
        self.download_calls += 1
        staging_path.write_bytes(self.payload)
        return SourceDownload(
            resolved_url="https://archive.example/recording.mp3",
            filename="Lecture Recording.mp3",
        )

    def probe(self, source_path: Path) -> dict[str, object]:
        self.asserted_path = source_path
        return {
            "duration_seconds": 123.5,
            "codec": "mp3",
            "streams": [{"index": 0, "codec_name": "mp3", "codec_type": "audio"}],
            "tool_versions": {"ffprobe": "fake-1.0", "downloader": "fake-2.0"},
        }


class JobStoreContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name) / "data" / "transcribe"
        self.store = JobStore(self.data_root)

    def _new_job(self):
        return self.store.create_job("lecture-recording", "a" * 64)

    def test_job_ids_are_deterministic_and_reject_unsafe_names(self) -> None:
        # Break caught: accepting a path/device name could escape or invalidate job storage.
        self.assertEqual(make_job_id("Lecture Recording", "a" * 64), "lecture-recording-aaaaaaaa")
        self.assertEqual(validate_job_id("lecture-recording-aaaaaaaa"), "lecture-recording-aaaaaaaa")
        for invalid in ("../escape-aaaaaaaa", "con-aaaaaaaa", "nul-aaaaaaaa", "bad/name-aaaaaaaa", "x-123"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(JobValidationError):
                    validate_job_id(invalid)

    def test_only_the_declared_forward_stage_transition_is_legal(self) -> None:
        # Break caught: skipping an evidence-producing stage would make later output untrustworthy.
        job = self._new_job()
        self.store.advance_stage(job["job_id"], "source_ready")
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "source_ready")
        with self.assertRaises(StageTransitionError):
            self.store.advance_stage(job["job_id"], "reviewed")

    def test_manifest_updates_are_atomic_and_increment_revision(self) -> None:
        # Break caught: a stale/non-atomic write could lose a job mutation or corrupt its manifest.
        job = self._new_job()
        original_revision = job["revision"]
        updated = self.store.update_job(job["job_id"], lambda state: state.update({"note": "kept"}))
        self.assertEqual(updated["revision"], original_revision + 1)
        self.assertEqual(self.store.load_job(job["job_id"])["note"], "kept")
        self.assertFalse(any(path.name.startswith(".job.json.") for path in self.store.job_root(job["job_id"]).iterdir()))

    def test_job_lock_excludes_a_second_lock_attempt(self) -> None:
        # Break caught: concurrent writers could both mutate one job manifest.
        job = self._new_job()
        with self.store.lock_job(job["job_id"]):
            with self.assertRaises(JobLockError):
                with self.store.lock_job(job["job_id"]):
                    pass

    def test_artifacts_reject_unsafe_paths_and_detect_changed_or_missing_files(self) -> None:
        # Break caught: artifact records could point outside the job or falsely attest altered evidence.
        job = self._new_job()
        root = self.store.job_root(job["job_id"])
        source = root / "source" / "source.bin"
        source.write_bytes(b"original")
        for unsafe in ("../outside.bin", "C:/outside.bin", "/outside.bin"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(JobValidationError):
                    self.store.register_artifact(job["job_id"], unsafe)
        self.store.register_artifact(job["job_id"], "source/source.bin")
        self.store.validate_artifact(job["job_id"], "source/source.bin")
        link = root / "source" / "linked.bin"
        try:
            link.symlink_to(source)
        except OSError as error:  # Windows may deny symlink creation without Developer Mode.
            self.assertIsNotNone(error)
        else:
            with self.assertRaises(ArtifactValidationError):
                self.store.register_artifact(job["job_id"], "source/linked.bin")
        source.write_bytes(b"changed")
        with self.assertRaises(ArtifactValidationError):
            self.store.validate_artifact(job["job_id"], "source/source.bin")
        source.unlink()
        with self.assertRaises(ArtifactValidationError):
            self.store.validate_artifact(job["job_id"], "source/source.bin")


class IntakeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(Path(self.tmp.name) / "data" / "transcribe")

    def _service(self, adapter: FakeSourceAdapter) -> IntakeService:
        return IntakeService(self.store, adapter)

    def test_intake_requires_https_and_records_fake_probe_metadata(self) -> None:
        # Break caught: accepting an untrusted URL scheme or dropping source provenance loses intake safety.
        adapter = FakeSourceAdapter()
        with self.assertRaises(JobValidationError):
            self._service(adapter).intake("http://archive.example/recording.mp3")
        job = self._service(adapter).intake("https://archive.example/requested")
        source = job["source"]
        self.assertEqual(source["requested_url"], "https://archive.example/requested")
        self.assertEqual(source["resolved_url"], "https://archive.example/recording.mp3")
        self.assertEqual(source["sha256"], hashlib.sha256(adapter.payload).hexdigest())
        self.assertEqual(source["byte_size"], len(adapter.payload))
        self.assertEqual(source["duration_seconds"], 123.5)
        self.assertEqual(source["codec"], "mp3")
        self.assertEqual(job["tool_versions"]["ffprobe"], "fake-1.0")
        self.assertEqual(job["stage"], "source_ready")
        self.assertEqual(self.store.incoming_root.name, ".incoming")
        self.assertEqual(list(self.store.incoming_root.iterdir()), [])

    def test_valid_url_match_resumes_only_after_its_source_hash_validates(self) -> None:
        # Break caught: URL-only resume could attach later work to a changed local source.
        adapter = FakeSourceAdapter()
        first = self._service(adapter).intake("https://archive.example/requested")
        resumed = self._service(adapter).intake("https://archive.example/requested")
        self.assertEqual(resumed["job_id"], first["job_id"])
        self.assertEqual(adapter.download_calls, 1)
        source_path = self.store.job_root(first["job_id"]) / "source" / "source.bin"
        source_path.write_bytes(b"changed")
        with self.assertRaises(ArtifactValidationError):
            self._service(adapter).intake("https://archive.example/requested")

    def test_matching_url_and_duration_without_a_valid_source_does_not_resume(self) -> None:
        # Break caught: URL/duration matching could resume a job whose actual audio evidence vanished.
        adapter = FakeSourceAdapter()
        job = self._service(adapter).intake("https://archive.example/requested")
        (self.store.job_root(job["job_id"]) / "source" / "source.bin").unlink()
        with self.assertRaises(ArtifactValidationError):
            self._service(adapter).intake("https://archive.example/requested")

    def test_same_incoming_hash_reuses_existing_job_instead_of_creating_a_duplicate(self) -> None:
        # Break caught: the same downloaded audio could create two independent evidence histories.
        adapter = FakeSourceAdapter()
        first = self._service(adapter).intake("https://archive.example/first")
        adapter_second_url = FakeSourceAdapter(adapter.payload)
        duplicate = self._service(adapter_second_url).intake("https://archive.example/second")
        self.assertEqual(duplicate["job_id"], first["job_id"])
        self.assertEqual(len(list((self.store.jobs_root).iterdir())), 1)

    def test_invalid_existing_hash_record_blocks_a_new_duplicate_job(self) -> None:
        # Break caught: ignoring a damaged same-hash job could fork one source into two histories.
        adapter = FakeSourceAdapter()
        first = self._service(adapter).intake("https://archive.example/first")
        (self.store.job_root(first["job_id"]) / "source" / "source.bin").write_bytes(b"damaged")
        with self.assertRaises(ArtifactValidationError):
            self._service(FakeSourceAdapter(adapter.payload)).intake("https://archive.example/second")

    def test_multiple_valid_hash_matches_are_an_explicit_error(self) -> None:
        # Break caught: choosing an arbitrary duplicate job would attach work to the wrong history.
        adapter = FakeSourceAdapter()
        first = self._service(adapter).intake("https://archive.example/first")
        copied_id = make_job_id("copy", first["source"]["sha256"])
        copied = self.store.create_job("copy", first["source"]["sha256"])
        copied_path = self.store.job_root(copied_id) / "source" / "source.bin"
        copied_path.write_bytes(adapter.payload)
        self.store.register_artifact(copied_id, "source/source.bin")
        self.store.update_job(copied_id, lambda state: state.update({"source": dict(first["source"]), "tool_versions": dict(first["tool_versions"])}))
        self.store.advance_stage(copied_id, "source_ready")
        with self.assertRaises(JobValidationError):
            self._service(FakeSourceAdapter(adapter.payload)).intake("https://archive.example/new")
