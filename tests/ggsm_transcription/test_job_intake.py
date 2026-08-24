"""Behavioral contracts for hash-bound transcription job intake."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ggsm_transcription.intake import HttpsFfprobeSourceAdapter, IntakeService, SourceDownload
from scripts.ggsm_transcription.store import (
    ArtifactValidationError,
    JobLockError,
    RepositoryHealthError,
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
        for title in ("Lecture con Swami", "aux lecture", "com1 discussion", "lpt1 notes"):
            generated = make_job_id(title, "b" * 64)
            self.assertEqual(validate_job_id(generated), generated)

    def test_only_the_declared_forward_stage_transition_is_legal(self) -> None:
        # Break caught: skipping an evidence-producing stage would make later output untrustworthy.
        job = IntakeService(self.store, FakeSourceAdapter()).intake("https://archive.example/stages")
        self.store.advance_stage(job["job_id"], "asr_ready")
        self.assertEqual(self.store.load_job(job["job_id"])["stage"], "asr_ready")
        with self.assertRaises(StageTransitionError):
            self.store.advance_stage(job["job_id"], "reviewed")

    def test_manifest_updates_are_atomic_and_increment_revision(self) -> None:
        # Break caught: a stale/non-atomic write could lose a job mutation or corrupt its manifest.
        job = IntakeService(self.store, FakeSourceAdapter()).intake("https://archive.example/atomic")
        original_revision = job["revision"]
        with self.store.transaction(job["job_id"]) as transaction:
            transaction.record_source_alias("https://archive.example/alias", "https://archive.example/final")
        updated = self.store.load_job(job["job_id"])
        self.assertEqual(updated["revision"], original_revision + 1)
        self.assertIn({"requested_url": "https://archive.example/alias", "resolved_url": "https://archive.example/final"}, updated["source_url_aliases"])
        self.assertFalse(any(path.name.startswith(".job.json.") for path in self.store.job_root(job["job_id"]).iterdir()))

    def test_job_lock_excludes_a_second_lock_attempt(self) -> None:
        # Break caught: concurrent writers could both mutate one job manifest.
        job = self._new_job()
        with self.store.lock_job(job["job_id"]):
            with self.assertRaises(JobLockError):
                with self.store.lock_job(job["job_id"]):
                    pass

    def test_os_lock_releases_after_a_lock_holder_process_exits(self) -> None:
        # Break caught: a stale sentinel file used to permanently block healthy resumption after a crash.
        job = self._new_job()
        code = "\n".join((
            "from scripts.ggsm_transcription.store import JobStore",
            "import sys, time",
            "store = JobStore(sys.argv[1])",
            "lock = store.lock_job(sys.argv[2])",
            "lock.__enter__()",
            "print('locked', flush=True)",
            "time.sleep(30)",
        ))
        holder = subprocess.Popen(
            [sys.executable, "-c", code, str(self.data_root), job["job_id"]],
            cwd=Path.cwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        self.assertEqual(holder.stdout.readline().strip(), "locked")
        with self.assertRaises(JobLockError):
            with self.store.lock_job(job["job_id"]):
                pass
        holder.terminate()
        holder.wait(timeout=10)
        holder.stdout.close()
        holder.stderr.close()
        with self.store.lock_job(job["job_id"]):
            pass

    def test_artifacts_reject_unsafe_paths_and_detect_changed_or_missing_files(self) -> None:
        # Break caught: artifact records could point outside the job or falsely attest altered evidence.
        job = IntakeService(self.store, FakeSourceAdapter(b"original source")).intake("https://archive.example/artifact")
        root = self.store.job_root(job["job_id"])
        source = root / "inspection" / "report.bin"
        source.write_bytes(b"original")
        for unsafe in ("../outside.bin", "C:/outside.bin", "/outside.bin"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(JobValidationError):
                    self.store.register_artifact(job["job_id"], unsafe)
        self.store.register_artifact(job["job_id"], "inspection/report.bin")
        with self.assertRaises(ArtifactValidationError):
            source.write_bytes(b"re-registered changed")
            self.store.register_artifact(job["job_id"], "inspection/report.bin")
        source.write_bytes(b"original")
        self.store.validate_artifact(job["job_id"], "inspection/report.bin")
        link = root / "inspection" / "linked.bin"
        try:
            link.symlink_to(source)
        except OSError as error:  # Windows may deny symlink creation without Developer Mode.
            self.assertIsNotNone(error)
        else:
            with self.assertRaises(ArtifactValidationError):
                self.store.register_artifact(job["job_id"], "inspection/linked.bin")
        source.write_bytes(b"changed")
        with self.assertRaises(ArtifactValidationError):
            self.store.validate_artifact(job["job_id"], "inspection/report.bin")
        source.unlink()
        with self.assertRaises(ArtifactValidationError):
            self.store.validate_artifact(job["job_id"], "inspection/report.bin")


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
        self.assertEqual(len([path for path in self.store.jobs_root.iterdir() if path.is_dir()]), 1)

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
        copied_manifest = self.store.job_root(copied_id) / "job.json"
        copied_state = self.store.load_job(copied_id)
        copied_state.update({
            "source": dict(first["source"]),
            "tool_versions": dict(first["tool_versions"]),
            "source_url_aliases": [{"requested_url": "https://archive.example/copied", "resolved_url": "https://archive.example/copied.mp3"}],
        })
        copied_state["artifacts"] = {"source/source.bin": {"sha256": first["source"]["sha256"], "byte_size": len(adapter.payload)}}
        copied_state["stage"] = "source_ready"
        copied_state["stage_history"].append({"stage": "source_ready", "at": copied_state["updated_at"]})
        copied_manifest.write_text(json.dumps(copied_state), encoding="utf-8")
        with self.assertRaisesRegex(JobValidationError, "more than one valid job matches the source hash"):
            self._service(FakeSourceAdapter(adapter.payload)).intake("https://archive.example/first")
        with self.assertRaisesRegex(JobValidationError, "more than one valid job matches the source hash"):
            self._service(FakeSourceAdapter(adapter.payload)).intake("https://archive.example/new")

    def test_hash_reuse_records_url_alias_and_later_resumes_without_download(self) -> None:
        # Break caught: losing alias provenance forces re-download and hides observed URLs.
        first_adapter = FakeSourceAdapter()
        first = self._service(first_adapter).intake("https://archive.example/first")
        second_adapter = FakeSourceAdapter(first_adapter.payload)
        reused = self._service(second_adapter).intake("https://archive.example/second")
        self.assertEqual(reused["job_id"], first["job_id"])
        aliases = self.store.load_job(first["job_id"])["source_url_aliases"]
        self.assertIn({"requested_url": "https://archive.example/second", "resolved_url": "https://archive.example/recording.mp3"}, aliases)
        self._service(second_adapter).intake("https://archive.example/second")
        self.assertEqual(second_adapter.download_calls, 1)

    def test_interrupted_created_job_resumes_same_hash_bound_identity(self) -> None:
        # Break caught: a crash after directory creation used to make intake permanently non-resumable.
        payload = b"interrupted source"
        digest = hashlib.sha256(payload).hexdigest()
        pending = self.store.create_job("lecture-recording", digest)
        result = self._service(FakeSourceAdapter(payload)).intake("https://archive.example/retry")
        self.assertEqual(result["job_id"], pending["job_id"])
        self.assertEqual(result["stage"], "source_ready")

    def test_hash_reuse_at_progressed_stages_records_alias_without_probing(self) -> None:
        # Break caught: an already-bound source must resume safely after ASR without fresh probe metadata.
        for target_stage in ("asr_ready", "inspected"):
            with self.subTest(target_stage=target_stage):
                isolated = JobStore(Path(self.tmp.name) / target_stage / "data" / "transcribe")
                first_adapter = FakeSourceAdapter()
                first = IntakeService(isolated, first_adapter).intake("https://archive.example/original")
                isolated.advance_stage(first["job_id"], "asr_ready")
                if target_stage == "inspected":
                    isolated.advance_stage(first["job_id"], "inspected")
                class NoProbeAdapter(FakeSourceAdapter):
                    def probe(self, source_path):
                        raise AssertionError("probe must not run for a bound hash identity")
                resumed = IntakeService(isolated, NoProbeAdapter(first_adapter.payload)).intake("https://archive.example/new-url")
                self.assertEqual(resumed["stage"], target_stage)
                self.assertIn({"requested_url": "https://archive.example/new-url", "resolved_url": "https://archive.example/recording.mp3"}, resumed["source_url_aliases"])
                self.assertEqual(list(isolated.incoming_root.iterdir()), [])

    def test_initial_manifest_failure_leaves_no_bad_jobs_entry(self) -> None:
        # Break caught: a crash before first job.json used to poison all later identity scans.
        digest = hashlib.sha256(b"failed create").hexdigest()
        with patch.object(JobStore, "_write_manifest", side_effect=OSError("injected first write failure")):
            with self.assertRaises(OSError):
                self.store.create_job("failed", digest)
        self.assertEqual([path for path in self.store.jobs_root.iterdir() if path.is_dir()], [])
        recovered = self._service(FakeSourceAdapter(b"other lecture")).intake("https://archive.example/other")
        self.assertEqual(recovered["stage"], "source_ready")

    def test_corrupt_job_directory_fails_closed_during_identity_scan(self) -> None:
        # Break caught: silently omitting corrupt evidence could create a duplicate source history.
        first = self._service(FakeSourceAdapter()).intake("https://archive.example/first")
        (self.store.job_root(first["job_id"]) / "job.json").write_text("[\"not-a-manifest\"]", encoding="utf-8")
        with self.assertRaises(RepositoryHealthError):
            self._service(FakeSourceAdapter()).intake("https://archive.example/second")

    def test_invalid_probe_values_fail_before_a_manifest_is_created(self) -> None:
        # Break caught: NaN, bool duration, malformed streams, or empty versions would poison timeline evidence.
        for key, value in (
            ("duration_seconds", math.nan),
            ("duration_seconds", True),
            ("duration_seconds", math.inf),
            ("streams", []),
            ("tool_versions", {"ffprobe": "", "downloader": "fake"}),
        ):
            with self.subTest(key=key, value=value):
                adapter = FakeSourceAdapter()
                original_probe = adapter.probe
                def malformed(path, key=key, value=value):
                    result = original_probe(path)
                    result[key] = value
                    return result
                adapter.probe = malformed  # type: ignore[method-assign]
                with self.assertRaises(JobValidationError):
                    self._service(adapter).intake("https://archive.example/malformed-" + key)
                self.assertEqual([path for path in self.store.jobs_root.iterdir() if path.is_dir()], [])


class AdapterAndTransactionRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(Path(self.tmp.name) / "data" / "transcribe")

    def test_unrestricted_mutation_is_rejected_and_compound_typed_mutation_is_one_revision(self) -> None:
        # Break caught: a generic mutator could forge a stage or re-legitimize changed evidence.
        job = IntakeService(self.store, FakeSourceAdapter()).intake("https://archive.example/compound")
        with self.assertRaises(JobValidationError):
            self.store.update_job(job["job_id"], lambda state: state.update({"stage": "handed_off"}))
        root = self.store.job_root(job["job_id"])
        (root / "inspection" / "report.json").write_text("{}", encoding="utf-8")
        before = self.store.load_job(job["job_id"])["revision"]
        with self.store.transaction(job["job_id"]) as transaction:
            transaction.register_artifact("inspection/report.json")
            transaction.advance_stage("asr_ready")
        after = self.store.load_job(job["job_id"])
        self.assertEqual(after["revision"], before + 1)
        self.assertEqual(after["stage"], "asr_ready")

    def test_ads_paths_are_rejected(self) -> None:
        # Break caught: NTFS alternate streams are not safe registered artifact files.
        job = self.store.create_job("safe", "c" * 64)
        with self.assertRaises(JobValidationError):
            self.store.register_artifact(job["job_id"], "source/source.bin:secret")

    def test_reparse_job_root_is_rejected_before_manifest_access(self) -> None:
        # Break caught: treating a job-root reparse target as trusted could mutate files outside jobs/.
        job = self.store.create_job("safe", "d" * 64)
        root = self.store.job_root(job["job_id"])
        import scripts.ggsm_transcription.store as store_module
        real_reparse = store_module._is_reparse
        with patch.object(store_module, "_is_reparse", side_effect=lambda path: path == root or real_reparse(path)):
            with self.assertRaises(RepositoryHealthError):
                self.store.load_job(job["job_id"])

    def test_atomic_failure_preserves_the_last_complete_manifest(self) -> None:
        # Break caught: replacement failure must not leave a torn or partially serialized job.json.
        job = IntakeService(self.store, FakeSourceAdapter()).intake("https://archive.example/replace")
        before = self.store.load_job(job["job_id"])
        with patch("scripts.ggsm_transcription.store.os.replace", side_effect=OSError("injected replace failure")):
            with self.assertRaises(JobValidationError):
                with self.store.transaction(job["job_id"]) as transaction:
                    transaction.record_source_alias("https://archive.example/new", "https://archive.example/final")
        self.assertEqual(self.store.load_job(job["job_id"]), before)

    def test_concrete_adapter_uses_injected_https_and_ffprobe_boundaries(self) -> None:
        # Break caught: a concrete adapter must supply final URL, copied bytes, stream metadata, and versions.
        class Response:
            def __init__(self): self.headers = {}
            def geturl(self): return "https://cdn.example/final.mp3"
            def read(self, _size=-1):
                if getattr(self, "done", False): return b""
                self.done = True
                return b"bytes"
            def __enter__(self): return self
            def __exit__(self, *_): return False
        def run(command, **_kwargs):
            if "-version" in command:
                return subprocess.CompletedProcess(command, 0, "ffprobe version 7.0\n", "")
            return subprocess.CompletedProcess(command, 0, json.dumps({"format": {"duration": "12.5"}, "streams": [{"index": 0, "codec_name": "mp3", "codec_type": "audio"}]}), "")
        adapter = HttpsFfprobeSourceAdapter(http_open=lambda _request: Response(), run_command=run)
        staging = self.store.incoming_root / "adapter.part"
        download = adapter.download("https://archive.example/request", staging)
        metadata = adapter.probe(staging)
        self.assertEqual(download.resolved_url, "https://cdn.example/final.mp3")
        self.assertEqual(staging.read_bytes(), b"bytes")
        self.assertEqual(metadata["codec"], "mp3")
        self.assertEqual(metadata["tool_versions"]["ffprobe"], "ffprobe version 7.0")
