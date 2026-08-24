from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts.youtube_enhance import workflow_state
from scripts.youtube_enhance.workflow_state import (
    JobBusy,
    JobPaths,
    InvalidJobState,
    InvalidTransition,
    RepositoryIdentity,
    StaleJobState,
    discover_canonical_repository,
    existing_job_paths,
    job_lock,
    job_paths,
    safe_output_path,
    validate_existing_artifact,
)
from tests.youtube_enhance.workflow_fixtures import (
    artifact_record,
    create_directory_reparse,
    create_seeded_repository,
    remove_directory_reparse,
)


class WorkflowRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.primary = self.workspace / "canonical"
        common = self.primary / ".git"
        common.mkdir(parents=True)
        status = common.stat(follow_symlinks=False)
        self.repository = RepositoryIdentity(
            canonical_root=self.primary,
            git_common_dir=common,
            git_common_file_id=(status.st_dev, status.st_ino),
            identity_sha256="A" * 64,
        )

    def test_public_task_three_exceptions_are_runtime_errors(self):
        for exception_type in (JobBusy, InvalidJobState, InvalidTransition, StaleJobState):
            with self.subTest(exception_type=exception_type):
                self.assertTrue(issubclass(exception_type, RuntimeError))

    def test_primary_and_linked_worktree_discovery_return_the_primary_root(self):
        primary, linked = create_seeded_repository(self.workspace / "repositories")
        (linked / "nested").mkdir()

        primary_identity = discover_canonical_repository(primary)
        linked_identity = discover_canonical_repository(linked / "nested")

        self.assertEqual(primary_identity.canonical_root, primary.resolve())
        self.assertEqual(linked_identity.canonical_root, primary.resolve())
        self.assertEqual(primary_identity.git_common_dir, (primary / ".git").resolve())
        self.assertEqual(primary_identity, linked_identity)
        self.assertRegex(primary_identity.identity_sha256, r"^[0-9A-F]{64}$")

    def test_discovery_rejects_malformed_or_ambiguous_git_output(self):
        cases = ("", "relative/.git\n", "C:\\one\\.git\nC:\\two\\.git\n", "  \n")
        for output in cases:
            with self.subTest(output=output), patch.object(
                workflow_state.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, output, ""),
            ), self.assertRaises(ValueError):
                discover_canonical_repository(self.primary)

    def test_discovery_rejects_missing_installed_skill(self):
        primary, _ = create_seeded_repository(self.workspace / "missing-skill")
        (primary / ".agents" / "skills" / "enhancing-lecture-audio" / "SKILL.md").unlink()

        with self.assertRaises(ValueError):
            discover_canonical_repository(primary)

    def test_discovery_rejects_non_regular_installed_skill(self):
        primary, _ = create_seeded_repository(self.workspace / "unsafe-skill")
        skill = primary / ".agents" / "skills" / "enhancing-lecture-audio" / "SKILL.md"
        skill.unlink()
        skill.mkdir()

        with self.assertRaises(ValueError):
            discover_canonical_repository(primary)

    def test_discovery_rejects_non_dot_git_common_directory(self):
        common = self.primary / "common"
        common.mkdir()
        output = f"{common.resolve()}\n"

        with patch.object(
            workflow_state.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, output, ""),
        ), self.assertRaises(ValueError):
            discover_canonical_repository(self.primary)

    def test_discovery_rejects_reparse_common_directory(self):
        shutil.rmtree(self.primary / ".git")
        target = self.workspace / "actual-git"
        target.mkdir()
        link = self.primary / ".git"
        try:
            create_directory_reparse(target, link)
        except OSError as error:
            self.skipTest(f"directory reparse points unavailable: {error}")
        self.addCleanup(remove_directory_reparse, link)
        output = f"{link.absolute()}\n"

        with patch.object(
            workflow_state.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, output, ""),
        ), self.assertRaises(ValueError):
            discover_canonical_repository(self.primary)

    def test_discovery_rejects_reparse_common_directory_ancestor(self):
        physical_parent = self.workspace / "physical-parent"
        common = physical_parent / "primary" / ".git"
        common.mkdir(parents=True)
        linked_parent = self.workspace / "linked-parent"
        create_directory_reparse(physical_parent, linked_parent)
        self.addCleanup(remove_directory_reparse, linked_parent)
        output = f"{linked_parent / 'primary' / '.git'}\n"

        with patch.object(
            workflow_state.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, output, ""),
        ), self.assertRaises(ValueError):
            discover_canonical_repository(self.primary)

    def test_discovery_rejects_installed_skill_reparse(self):
        skill = self.primary / ".agents" / "skills" / "enhancing-lecture-audio" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        reparse_target = self.workspace / "skill-reparse-target"
        reparse_target.mkdir()
        create_directory_reparse(reparse_target, skill)
        self.addCleanup(remove_directory_reparse, skill)
        output = f"{self.primary / '.git'}\n"

        with patch.object(
            workflow_state.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, output, ""),
        ), self.assertRaises(ValueError):
            discover_canonical_repository(self.primary)

    def test_job_id_rejects_traversal_and_windows_devices(self):
        for value in ("../escape", "two/levels", ".locks", "CON", "nul", "name.", "UPPER"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                job_paths(self.repository, value)

    def test_job_root_is_always_under_primary_jobs_root(self):
        paths = job_paths(self.repository, "sample-job")
        self.assertEqual(
            paths.job_root,
            self.primary / "data" / "enhance" / "jobs" / "sample-job",
        )
        self.assertNotIn("youtube", paths.job_root.parts)

    def test_job_lock_is_under_jobs_locks_and_bound_to_normalized_job_root(self):
        paths = job_paths(self.repository, "sample-job")
        normalized_job_root = os.path.normcase(os.path.abspath(os.path.normpath(paths.job_root)))
        expected_name = hashlib.sha256(normalized_job_root.encode("utf-8")).hexdigest().upper()

        self.assertEqual(
            paths.lock_file,
            self.primary / "data" / "enhance" / "jobs" / ".locks" / f"{expected_name}.lock",
        )

    def test_nonblocking_job_lock_rejects_a_second_process_immediately(self):
        primary, _linked = create_seeded_repository(self.workspace / "lock-repository")
        paths = job_paths(discover_canonical_repository(primary), "sample-job")
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys\n"
                    "from pathlib import Path\n"
                    "from scripts.youtube_enhance.workflow_state import "
                    "discover_canonical_repository, job_lock, job_paths\n"
                    "paths = job_paths(discover_canonical_repository(Path(sys.argv[1])), sys.argv[2])\n"
                    "with job_lock(paths, blocking=False):\n"
                    "    print('locked', flush=True)\n"
                    "    sys.stdin.readline()\n"
                ),
                str(primary),
                "sample-job",
            ],
            cwd=Path.cwd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        self.assertIsNotNone(holder.stdout)
        ready = holder.stdout.readline().strip()
        if ready != "locked":
            _stdout, stderr = holder.communicate(timeout=5)
            self.fail(f"lock holder failed before acquiring the lock: {stderr}")

        started = time.monotonic()
        with self.assertRaisesRegex(JobBusy, "already running"):
            with job_lock(paths, blocking=False):
                self.fail("a second process acquired the same job lock")
        self.assertLess(time.monotonic() - started, 1.0)

        self.assertIsNotNone(holder.stdin)
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.communicate(timeout=5)
        self.assertEqual(holder.returncode, 0)

    def test_job_lock_rejects_a_noncanonical_lock_file(self):
        paths = job_paths(self.repository, "sample-job")
        tampered = replace(paths, lock_file=self.workspace / "outside.lock")

        with self.assertRaisesRegex(ValueError, "lock path is not canonical"):
            with job_lock(tampered, blocking=False):
                self.fail("a noncanonical lock path was accepted")
        self.assertFalse(tampered.lock_file.exists())

    def test_protected_legacy_path_is_never_runner_owned(self):
        with self.assertRaises(ValueError):
            safe_output_path(
                job_paths(self.repository, "sample-job"),
                PurePosixPath("../../youtube/synthetic-recording"),
            )

    def test_arbitrary_legacy_youtube_child_is_never_bound_as_a_runner_job(self):
        primary, _linked = create_seeded_repository(self.workspace / "legacy-repository")
        legacy_job = primary / "data" / "enhance" / "youtube" / "synthetic-recording" / "job.json"
        legacy_job.parent.mkdir(parents=True)
        original = b'{"legacy": true}\n'
        legacy_job.write_bytes(original)

        with self.assertRaisesRegex(ValueError, "protected legacy"):
            existing_job_paths(legacy_job)
        self.assertEqual(legacy_job.read_bytes(), original)

    def test_safe_output_accepts_an_absent_nested_destination_without_resolving_it(self):
        paths = job_paths(self.repository, "sample-job")

        result = safe_output_path(paths, PurePosixPath("work/chunks/0001.wav"))

        self.assertEqual(result, paths.job_root / "work" / "chunks" / "0001.wav")
        self.assertFalse(result.exists())

    def test_safe_output_rejects_absolute_dot_traversal_and_windows_components(self):
        paths = job_paths(self.repository, "sample-job")
        cases = (
            PurePosixPath("/absolute.wav"),
            PurePosixPath("."),
            PurePosixPath("../escape.wav"),
            PurePosixPath("CON.wav"),
            PurePosixPath("nested/nul.txt"),
            PurePosixPath("name."),
            PurePosixPath("bad\\name.wav"),
            PurePosixPath("C:/outside.wav"),
        )
        for relative_path in cases:
            with self.subTest(relative_path=relative_path), self.assertRaises(ValueError):
                safe_output_path(paths, relative_path)

    def test_safe_output_rejects_reparse_job_ancestor(self):
        paths = job_paths(self.repository, "sample-job")
        paths.data_root.mkdir(parents=True)
        target = self.workspace / "swapped-job"
        target.mkdir()
        try:
            create_directory_reparse(target, paths.job_root)
        except OSError as error:
            self.skipTest(f"directory reparse points unavailable: {error}")
        self.addCleanup(remove_directory_reparse, paths.job_root)

        with self.assertRaises(ValueError):
            safe_output_path(paths, PurePosixPath("work/output.wav"))

    def test_validate_existing_artifact_accepts_an_unchanged_regular_file(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")

        self.assertEqual(validate_existing_artifact(paths, record), artifact)

    def test_validate_existing_artifact_rejects_reparse_file_substitution(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")
        target = self.workspace / "replacement-directory"
        target.mkdir()
        artifact.unlink()
        try:
            create_directory_reparse(target, artifact)
        except OSError as error:
            self.skipTest(f"artifact reparse points unavailable: {error}")
        self.addCleanup(remove_directory_reparse, artifact)

        with self.assertRaises(ValueError):
            validate_existing_artifact(paths, record)

    def test_validate_existing_artifact_rejects_size_mismatch_independently(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")

        with self.assertRaises(ValueError):
            validate_existing_artifact(paths, replace(record, size_bytes=record.size_bytes + 1))

    def test_validate_existing_artifact_rejects_file_id_mismatch_independently(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")

        with self.assertRaises(ValueError):
            validate_existing_artifact(paths, replace(record, file_id=(0, 0)))

    def test_validate_existing_artifact_rejects_hash_mismatch_independently(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")

        with self.assertRaises(ValueError):
            validate_existing_artifact(paths, replace(record, sha256="B" * 64))

    def test_validate_existing_artifact_requires_uppercase_sha256(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")

        with self.assertRaises(ValueError):
            validate_existing_artifact(paths, replace(record, sha256=record.sha256.lower()))

    def test_validate_existing_artifact_rejects_identity_substitution_during_hashing(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")
        real_open = workflow_state._open_artifact_handle

        @contextmanager
        def substitute_after_close(path: Path):
            with real_open(path) as handle:
                yield handle
            replacement = path.with_name("same-bytes.bin")
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)

        with patch.object(
            workflow_state,
            "_open_artifact_handle",
            side_effect=substitute_after_close,
        ), self.assertRaises(ValueError):
            validate_existing_artifact(paths, record)

    def test_validate_existing_artifact_rejects_metadata_change_during_hashing(self):
        paths, artifact = self._write_artifact(b"validated artifact")
        record = artifact_record(artifact, "work/artifact.bin")
        before = artifact.stat(follow_symlinks=False)
        real_hash = workflow_state._sha256_file

        def touch(handle) -> str:
            digest = real_hash(handle)
            changed_mtime = before.st_mtime_ns + 2_000_000_000
            os.utime(artifact, ns=(before.st_atime_ns, changed_mtime))
            return digest

        with patch.object(workflow_state, "_sha256_file", side_effect=touch), self.assertRaises(
            ValueError
        ):
            validate_existing_artifact(paths, record)

    def test_validate_existing_artifact_binds_hashing_to_the_prevalidated_inode(self):
        paths, artifact = self._write_artifact(b"recorded-original")
        record = artifact_record(artifact, "work/artifact.bin")
        impostor = artifact.with_name("same-size-impostor.bin")
        impostor.write_bytes(b"substitute-bytes!")
        self.assertEqual(record.size_bytes, impostor.stat().st_size)
        impostor_sha256 = hashlib.sha256(impostor.read_bytes()).hexdigest().upper()
        inconsistent_record = replace(record, sha256=impostor_sha256)
        recorded_inode = artifact.with_name("recorded-inode.bin")
        real_hash = workflow_state._sha256_file

        def exploit_pathname_reopen(value) -> str:
            if not isinstance(value, Path):
                return real_hash(value)
            os.replace(value, recorded_inode)
            os.replace(impostor, value)
            try:
                return real_hash(value)
            finally:
                os.replace(value, impostor)
                os.replace(recorded_inode, value)

        with open(impostor, "rb") as impostor_handle, patch.object(
            workflow_state,
            "_open_artifact_handle",
            return_value=impostor_handle,
            create=True,
        ), patch.object(
            workflow_state,
            "_sha256_file",
            side_effect=exploit_pathname_reopen,
        ), self.assertRaises(ValueError):
            validate_existing_artifact(paths, inconsistent_record)

    def _write_artifact(self, content: bytes) -> tuple[JobPaths, Path]:
        paths = job_paths(self.repository, "sample-job")
        artifact = paths.job_root / "work" / "artifact.bin"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(content)
        return paths, artifact


if __name__ == "__main__":
    unittest.main()
