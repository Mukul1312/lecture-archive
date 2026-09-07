"""Contract tests for immutable Narrator Voice aggregate revision repositories."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ValidationError
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AuthorizationRecordId,
    AuthorityChangeId,
    DiaryEpisodeId,
    NarrationJobId,
    PassageId,
)
from heritage_archive.contexts.narrator_voice.domain.narration_job import (
    PassageDraft,
    prepare_lane_b_diary_job,
)
from heritage_archive.contexts.narrator_voice.domain.values import Lane, PassageText
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import (
    FilesystemAuthorizationRecordRepository,
    FilesystemDiaryEpisodeRepository,
    FilesystemNarrationJobRepository,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from tests.heritage_archive.narrator_voice.fixtures import (
    NOW,
    digest,
    make_contract,
    make_defaults,
    make_master_snapshot,
    make_scope,
    uuid,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FilesystemRepositoryContracts(unittest.TestCase):
    def test_storage_failures_are_typed_separately_from_caller_validation_and_cas(self):
        from heritage_archive.contexts.narrator_voice.infrastructure import filesystem_repositories as fs
        self.assertTrue(hasattr(fs, "FilesystemRepositoryFailure"))
        failure = fs.FilesystemRepositoryFailure
        self.assertTrue(issubclass(failure, ValidationError))
        with self._storage_root() as root:
            repository = FilesystemDiaryEpisodeRepository(root)
            episode = DiaryEpisode.prepare(DiaryEpisodeId(uuid(1280)), NOW)
            with self.assertRaises(ValidationError) as caught:
                repository.save(episode, True)
            self.assertNotIsInstance(caught.exception, failure)
            for target, error in (("publish_bytes_no_clobber", OSError("private storage")),
                                  ("encode_schema_v1", ValueError("private encoding"))):
                with patch.object(fs, target, side_effect=error), self.assertRaises(failure):
                    repository.save(episode, None)
            self.assertTrue(repository.save(episode, None))
            self.assertFalse(repository.save(episode, None))
            path = root.aggregates / "diary-episodes" / episode.episode_id.value / "revisions" / "00000000000000000001.json"
            path.write_bytes(b"corrupt")
            with self.assertRaises(failure):
                repository.load(episode.episode_id)
            with self.assertRaises(failure):
                repository.list_ids()

    def test_rehydration_invariant_and_lock_storage_faults_are_typed(self):
        from heritage_archive.contexts.narrator_voice.infrastructure import filesystem_repositories as fs
        from heritage_archive.contexts.narrator_voice.domain.errors import DomainInvariantError
        with self._storage_root() as root:
            repository = FilesystemDiaryEpisodeRepository(root)
            episode = DiaryEpisode.prepare(DiaryEpisodeId(uuid(1281)), NOW)
            with patch.object(fs.SingleWriterFileLock, "__enter__", side_effect=OSError("private lock path")):
                with self.assertRaises(Exception) as caught:
                    repository.save(episode, None)
                self.assertIsInstance(caught.exception, fs.FilesystemRepositoryFailure)
            repository.save(episode, None)
            with patch.object(DiaryEpisode, "from_snapshot", side_effect=DomainInvariantError("private invalid evidence")):
                with self.assertRaises(fs.FilesystemRepositoryFailure):
                    repository.load(episode.episode_id)
                with self.assertRaises(fs.FilesystemRepositoryFailure):
                    repository.list_ids()

    def test_discovery_is_empty_ordered_and_survives_reopening(self) -> None:
        for repository_type, kind, make, id_type in self._discoverable_types():
            with self.subTest(kind=kind), self._storage_root() as root:
                repository = repository_type(root)
                self.assertEqual(repository.list_ids(), ())
                for index in (1252, 1251):
                    self.assertTrue(repository.save(make(index), None))
                reopened = LocalNarrationRoot.open(root.path, (PROJECT_ROOT,))
                self.assertEqual(repository_type(reopened).list_ids(), (id_type(uuid(1251)), id_type(uuid(1252))))

    def test_discovery_rejects_corrupt_directory_and_revision_histories(self) -> None:
        for repository_type, kind, make, id_type in self._discoverable_types():
            for defect in ("invalid-id", "file-entry", "kind-file", "empty", "first", "later", "gap", "identity", "revision-file-directory"):
                with self.subTest(kind=kind, defect=defect), self._storage_root() as root:
                    repository = repository_type(root)
                    aggregate = make(1260)
                    repository.save(aggregate, None)
                    directory = root.aggregates / kind
                    aggregate_dir = directory / uuid(1260)
                    revisions = aggregate_dir / "revisions"
                    first = revisions / "00000000000000000001.json"
                    if defect == "invalid-id":
                        (directory / "not-an-id").mkdir()
                    elif defect == "file-entry":
                        (directory / uuid(1261)).write_bytes(b"unexpected file")
                    elif defect == "kind-file":
                        directory.rename(root.path / "saved-kind")
                        directory.write_bytes(b"unexpected file")
                    elif defect == "empty":
                        (directory / uuid(1261)).mkdir()
                    elif defect == "first":
                        first.write_bytes(b"invalid snapshot")
                    elif defect == "later":
                        (revisions / "00000000000000000002.json").write_bytes(b"invalid snapshot")
                    elif defect == "gap":
                        (revisions / "00000000000000000003.json").write_bytes(first.read_bytes())
                    elif defect == "identity":
                        aggregate_dir.rename(directory / uuid(1261))
                    else:
                        first.unlink()
                        first.mkdir()
                    with self.assertRaises(ValidationError):
                        repository.list_ids()

    def test_discovery_rejects_reparse_entries_without_following_them(self) -> None:
        import os
        import subprocess

        for location in ("kind", "aggregate", "revisions"):
            with self.subTest(location=location), self._storage_root() as root:
                repository = FilesystemDiaryEpisodeRepository(root)
                repository.save(DiaryEpisode.prepare(DiaryEpisodeId(uuid(1270)), NOW), None)
                kind = root.aggregates / "diary-episodes"
                target = root.path / "junction-target"
                link = {"kind": kind, "aggregate": kind / uuid(1270), "revisions": kind / uuid(1270) / "revisions"}[location]
                link.rename(target)
                if os.name == "nt":
                    completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                else:
                    link.symlink_to(target, target_is_directory=True)
                try:
                    with self.assertRaises(ValidationError):
                        repository.list_ids()
                finally:
                    if os.name == "nt":
                        link.rmdir()
                    else:
                        link.unlink()

    @staticmethod
    def _discoverable_types():
        return (
            (FilesystemDiaryEpisodeRepository, "diary-episodes", lambda index: DiaryEpisode.prepare(DiaryEpisodeId(uuid(index)), NOW), DiaryEpisodeId),
            (FilesystemNarrationJobRepository, "narration-jobs", lambda index: prepare_lane_b_diary_job(
                NarrationJobId(uuid(index)), make_contract(lane=Lane.B), make_defaults(),
                (PassageDraft(PassageId(uuid(index + 100)), 0, PassageText("discovery fixture")),), NOW,
            ), NarrationJobId),
        )

    def test_authorization_revisions_round_trip_and_refuse_stale_compare_and_swap(self) -> None:
        """A stale authorization write could overwrite immutable authority history."""
        record = AuthorizationRecord.register(
            AuthorizationRecordId(uuid(1200)), ActorId(uuid(1201)), make_scope(), digest("filesystem authority"), NOW
        )

        def mutate(value: AuthorizationRecord) -> None:
            value.withdraw(AuthorityChangeId(uuid(1202)), value.steward_actor_id, "fake withdrawal", NOW, expected_revision=value.revision)

        self._assert_revision_contract(FilesystemAuthorizationRecordRepository, record.record_id, record, mutate, "authorization-records")

    def test_narration_job_revisions_round_trip_and_refuse_stale_compare_and_swap(self) -> None:
        """A stale narration write could replace a later passage-text revision."""
        passage_id = PassageId(uuid(1211))
        job = prepare_lane_b_diary_job(
            NarrationJobId(uuid(1210)), make_contract(lane=Lane.B), make_defaults(),
            (PassageDraft(passage_id, 0, PassageText("fake stored narration text")),), NOW,
        )

        def mutate(value) -> None:
            value.revise_passage_text(passage_id, PassageText("fake revised narration text"), NOW, expected_revision=value.revision)

        self._assert_revision_contract(FilesystemNarrationJobRepository, job.job_id, job, mutate, "narration-jobs")

    def test_diary_episode_revisions_round_trip_and_refuse_stale_compare_and_swap(self) -> None:
        """A stale episode write could discard an attached immutable source snapshot."""
        episode = DiaryEpisode.prepare(DiaryEpisodeId(uuid(1220)), NOW)
        intro = make_master_snapshot(lane=Lane.C, episode_id=episode.episode_id, index=1221, samples=100)

        def mutate(value: DiaryEpisode) -> None:
            value.attach_intro(intro, NOW, expected_revision=value.revision)

        self._assert_revision_contract(FilesystemDiaryEpisodeRepository, episode.episode_id, episode, mutate, "diary-episodes")

    def test_load_stops_at_a_missing_or_invalid_revision_and_absent_id_is_none(self) -> None:
        """Selecting the highest filename would accept a revision after a corrupt gap."""
        record = AuthorizationRecord.register(
            AuthorizationRecordId(uuid(1230)), ActorId(uuid(1231)), make_scope(), digest("gap authority"), NOW
        )
        with self._storage_root() as root:
            repository = FilesystemAuthorizationRecordRepository(root)
            self.assertTrue(repository.save(record, None))
            revisions = root.aggregates / "authorization-records" / record.record_id.value / "revisions"
            revision_one = revisions / "00000000000000000001.json"
            (revisions / "00000000000000000002.json").write_bytes(b"not canonical JSON")
            (revisions / "00000000000000000003.json").write_bytes(revision_one.read_bytes())

            loaded = FilesystemAuthorizationRecordRepository(root).load(record.record_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.to_snapshot(), record.to_snapshot())
            self.assertIsNone(repository.load(AuthorizationRecordId(uuid(1232))))

    def test_interrupted_repository_publication_preserves_json_staging_and_raises_validation_error(self) -> None:
        """Leaking a storage error would let callers mistake interrupted persistence for a CAS refusal."""
        record = AuthorizationRecord.register(
            AuthorizationRecordId(uuid(1240)), ActorId(uuid(1241)), make_scope(), digest("interrupted authority"), NOW
        )
        with self._storage_root() as root:
            repository = FilesystemAuthorizationRecordRepository(root)

            with patch.object(Path, "rename", side_effect=OSError("interrupted publication")):
                with self.assertRaises(ValidationError):
                    repository.save(record, None)

            self.assertEqual(tuple(path.suffix for path in root.staging.iterdir()), (".json",))
            destination = root.aggregates / "authorization-records" / record.record_id.value / "revisions" / "00000000000000000001.json"
            self.assertFalse(destination.exists())

    def _assert_revision_contract(self, repository_type, aggregate_id, aggregate, mutate, aggregate_kind: str) -> None:
        with self._storage_root() as root:
            repository = repository_type(root)
            self.assertTrue(repository.save(aggregate, None))
            revisions = root.aggregates / aggregate_kind / aggregate_id.value / "revisions"
            self.assertEqual(
                (revisions / "00000000000000000001.json").read_bytes()[-1:],
                b"}",
            )

            reloaded = repository_type(root).load(aggregate_id)
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.to_snapshot(), aggregate.to_snapshot())
            mutate(reloaded)
            self.assertTrue(repository.save(reloaded, 1))

            self.assertFalse(repository.save(reloaded, 1))
            self.assertFalse((revisions / "00000000000000000003.json").exists())
            current = repository_type(root).load(aggregate_id)
            self.assertIsNotNone(current)
            self.assertEqual(current.to_snapshot(), reloaded.to_snapshot())

    def _storage_root(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = LocalNarrationRoot.open(Path(temporary_directory.name), (PROJECT_ROOT,))
        root.initialize_layout()
        return _StorageRootContext(root)


class _StorageRootContext:
    def __init__(self, root: LocalNarrationRoot) -> None:
        self._root = root

    def __enter__(self) -> LocalNarrationRoot:
        return self._root

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
