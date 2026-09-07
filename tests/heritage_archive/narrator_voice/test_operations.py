"""Focused contracts for the minimum offline local-studio operations."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ValidationError, canonical_json, parse_strict_json
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.operations import (
    BackupResult,
    BackupVerificationResult,
    DoctorResult,
    InitResult,
    RestoreResult,
    backup,
    doctor,
    initialize_local_studio,
    load_local_studio_configuration,
    load_local_studio_initialization,
    restore,
    verify_backup,
)
from heritage_archive.platform.storage.local_files import (
    SingleWriterFileLock,
    WriterLockUnavailable,
)
from tests.heritage_archive.narrator_voice.fixtures import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SECRET_VALUES = (
    "Private Operator",
    "private-speaker-b",
    "private-speaker-c",
    "private-voice-b",
    "private-voice-c",
    "private-dictionary-b",
    "private-project",
    "private-cycle",
)


class LocalStudioOperationsTests(unittest.TestCase):
    def test_canonical_initialization_is_stable_private_and_conflicts_fail_closed(self) -> None:
        """A retry must preserve the generated operator identity while changed private input is refused."""
        with self._directories(2) as (input_directory, root_directory):
            request = self._load_request(input_directory)
            root = LocalNarrationRoot.open(root_directory, (PROJECT_ROOT,))
            identifiers = _Identifiers(ActorId(uuid(1501)))

            first = initialize_local_studio(root, request, identifiers)
            config_path = root.operations / "studio-config.json"
            first_bytes = config_path.read_bytes()
            configuration = load_local_studio_configuration(root)

            self.assertTrue(first.initialized)
            self.assertEqual(first.configuration_digest.hex_digest, hashlib.sha256(first_bytes).hexdigest())
            self.assertEqual(configuration.actor_id, ActorId(uuid(1501)))
            self.assertEqual(configuration.lane_b.opaque_provider_voice_reference, "private-voice-b")
            self.assertEqual(configuration.lane_b.voice_binding, "fixture-binding-b")
            self.assertEqual(configuration.lane_b.authorization_record_id.value, uuid(3))
            self.assertEqual(configuration.lane_c.initial_speed.value, "1.10")
            self.assertIsNone(configuration.lane_c.initial_emotion)
            self.assertEqual(parse_strict_json(first_bytes)["schema_version"], 2)
            self.assertNotIn(b"CARTESIA_API_KEY", first_bytes)
            self.assertNotIn(b"api_key", first_bytes)
            self.assertEqual(identifiers.calls, 1)

            repeated = initialize_local_studio(root, request, identifiers)
            self.assertFalse(repeated.initialized)
            self.assertEqual(config_path.read_bytes(), first_bytes)
            self.assertEqual(identifiers.calls, 1)

            with self.assertRaises(ValidationError):
                initialize_local_studio(
                    root,
                    replace(request, operator_display_label="Changed Operator"),
                    identifiers,
                )
            self.assertEqual(config_path.read_bytes(), first_bytes)

    def test_initialization_and_configuration_loaders_are_strict_and_canonical(self) -> None:
        """Unknown fields, noncanonical bytes, and configuration edits must not be accepted as authority."""
        with self._directories(2) as (input_directory, root_directory):
            path = input_directory / "initialization.json"
            document = self._initialization_document()
            document["api_key"] = "must-not-enter-configuration"
            path.write_bytes(canonical_json(document))
            with self.assertRaises(ValidationError):
                load_local_studio_initialization(path, (PROJECT_ROOT,))

            path.write_bytes(b'{ "schema": "narrator_voice.local_studio_initialization" }')
            with self.assertRaises(ValidationError):
                load_local_studio_initialization(path, (PROJECT_ROOT,))

            document = self._initialization_document()
            document["schema_version"] = 1
            path.write_bytes(canonical_json(document))
            with self.assertRaises(ValidationError):
                load_local_studio_initialization(path, (PROJECT_ROOT,))

            document = self._initialization_document()
            document["schema_version"] = True
            path.write_bytes(canonical_json(document))
            with self.assertRaises(ValidationError):
                load_local_studio_initialization(path, (PROJECT_ROOT,))

            request = self._load_request(input_directory)
            root = LocalNarrationRoot.open(root_directory, (PROJECT_ROOT,))
            initialize_local_studio(root, request, _Identifiers(ActorId(uuid(1502))))
            config_path = root.operations / "studio-config.json"
            configuration_document = parse_strict_json(config_path.read_bytes())
            configuration_document["schema_version"] = True
            config_path.write_bytes(canonical_json(configuration_document))
            with self.assertRaises(ValidationError):
                load_local_studio_configuration(root)

            configuration_document["schema_version"] = 1
            config_path.write_bytes(canonical_json(configuration_document))
            with self.assertRaises(ValidationError):
                load_local_studio_configuration(root)

    def test_doctor_reports_corrupt_json_and_staging_without_mutating_evidence(self) -> None:
        """Diagnostics must expose stable codes while preserving every byte of questionable evidence."""
        with self._initialized_root(1503) as root:
            corrupt = root.attempts / "generation" / f"{uuid(1504)}.json"
            corrupt.parent.mkdir()
            corrupt.write_bytes(b'{"broken":')
            orphan = root.staging / "unfinished.stage"
            orphan.write_bytes(b"unfinished")
            before = self._regular_files(root.path)

            result = doctor(root)

            self.assertFalse(result.healthy)
            self.assertIn("staging_nonempty", result.issue_codes)
            self.assertIn("json_invalid", result.issue_codes)
            self.assertEqual(self._regular_files(root.path), before)

    def test_backup_holds_the_writer_lock_and_copies_the_complete_regular_tree(self) -> None:
        """Skipping the source lock or staging files would produce a torn operational backup."""
        with self._initialized_root(1505) as root, self._directories(1) as (destination,):
            (root.staging / "unfinished.stage").write_bytes(b"unfinished")
            artifact = root.artifacts / "takes" / "one.wav"
            artifact.parent.mkdir()
            artifact.write_bytes(b"fake-wave")
            attempt = root.attempts / "generation" / f"{uuid(1506)}.json"
            attempt.parent.mkdir()
            attempt.write_bytes(b"corrupt but preserved")

            with SingleWriterFileLock(root.writer_lock):
                with self.assertRaises(WriterLockUnavailable):
                    backup(root, destination, (PROJECT_ROOT,))

            result = backup(root, destination, (PROJECT_ROOT,))
            manifest_path = destination / "backup-manifest.json"
            manifest = parse_strict_json(manifest_path.read_bytes())
            self.assertEqual(manifest["schema_version"], 1)
            copied_paths = {entry["path"] for entry in manifest["files"]}

            self.assertEqual(result.manifest_digest.hex_digest, hashlib.sha256(manifest_path.read_bytes()).hexdigest())
            self.assertIn("staging/unfinished.stage", copied_paths)
            self.assertIn("artifacts/takes/one.wav", copied_paths)
            self.assertIn(f"attempts/generation/{uuid(1506)}.json", copied_paths)
            self.assertNotIn(".writer.lock", copied_paths)
            self.assertEqual((destination / "staging" / "unfinished.stage").read_bytes(), b"unfinished")

    def test_backup_verification_detects_changed_missing_and_extra_files(self) -> None:
        """Verification must compare the exact file set rather than trusting the manifest alone."""
        cases = (
            ("changed", "backup_file_digest_mismatch"),
            ("missing", "backup_file_missing"),
            ("extra", "backup_file_extra"),
            ("boolean-schema", "backup_manifest_invalid"),
        )
        for index, (mutation, issue) in enumerate(cases, 1510):
            with self.subTest(mutation=mutation), self._initialized_root(index) as root, self._directories(1) as (destination,):
                backup(root, destination, (PROJECT_ROOT,))
                config = destination / "operations" / "studio-config.json"
                if mutation == "changed":
                    config.write_bytes(b"changed")
                elif mutation == "missing":
                    config.unlink()
                elif mutation == "extra":
                    (destination / "unexpected.bin").write_bytes(b"extra")
                else:
                    manifest_path = destination / "backup-manifest.json"
                    manifest = parse_strict_json(manifest_path.read_bytes())
                    manifest["schema_version"] = True
                    manifest_path.write_bytes(canonical_json(manifest))

                result = verify_backup(destination, (PROJECT_ROOT,))

                self.assertFalse(result.valid)
                self.assertIn(issue, result.issue_codes)

    def test_verified_restore_round_trip_recreates_private_state_without_manifest(self) -> None:
        """A verified cold restore must reproduce every source file but not backup-only metadata."""
        with self._initialized_root(1520) as root, self._directories(2) as (backup_directory, destination):
            (root.artifacts / "sample.bin").write_bytes(b"sample")
            backup(root, backup_directory, (PROJECT_ROOT,))

            restored = restore(backup_directory, destination, (PROJECT_ROOT,))
            reopened = LocalNarrationRoot.open(destination, (PROJECT_ROOT,))

            self.assertEqual(restored.file_count, len(self._regular_files(root.path)) - 1)
            self.assertEqual(
                load_local_studio_configuration(reopened),
                load_local_studio_configuration(root),
            )
            self.assertEqual((destination / "artifacts" / "sample.bin").read_bytes(), b"sample")
            self.assertFalse((destination / "backup-manifest.json").exists())

    def test_restore_refuses_nonempty_destination_without_changing_it(self) -> None:
        """Restoring over an existing studio could mix two unrelated histories."""
        with self._initialized_root(1530) as root, self._directories(2) as (backup_directory, destination):
            backup(root, backup_directory, (PROJECT_ROOT,))
            marker = destination / "keep.txt"
            marker.write_bytes(b"keep")

            with self.assertRaises(ValidationError):
                restore(backup_directory, destination, (PROJECT_ROOT,))

            self.assertEqual(self._regular_files(destination), {"keep.txt": b"keep"})

    def test_tampered_backup_leaves_empty_restore_destination_untouched(self) -> None:
        """Restore must verify all source evidence before it creates even the standard layout."""
        with self._initialized_root(1540) as root, self._directories(2) as (backup_directory, destination):
            backup(root, backup_directory, (PROJECT_ROOT,))
            (backup_directory / "operations" / "studio-config.json").write_bytes(b"tampered")

            with self.assertRaises(ValidationError):
                restore(backup_directory, destination, (PROJECT_ROOT,))

            self.assertEqual(tuple(destination.iterdir()), ())

    def test_public_results_are_frozen_and_do_not_echo_private_values(self) -> None:
        """Operational output must remain safe for a future CLI or browser boundary."""
        with self._directories(4) as (input_directory, root_directory, backup_directory, restore_directory):
            request = self._load_request(input_directory)
            root = LocalNarrationRoot.open(root_directory, (PROJECT_ROOT,))
            init_result = initialize_local_studio(root, request, _Identifiers(ActorId(uuid(1550))))
            doctor_result = doctor(root)
            backup_result = backup(root, backup_directory, (PROJECT_ROOT,))
            verification_result = verify_backup(backup_directory, (PROJECT_ROOT,))
            restore_result = restore(backup_directory, restore_directory, (PROJECT_ROOT,))
            results = (init_result, doctor_result, backup_result, verification_result, restore_result)

            self.assertEqual(
                tuple(type(item) for item in results),
                (InitResult, DoctorResult, BackupResult, BackupVerificationResult, RestoreResult),
            )
            for result in results:
                rendered = repr(asdict(result))
                self.assertFalse(any(secret in rendered for secret in SECRET_VALUES))
                with self.assertRaises(FrozenInstanceError):
                    result.__setattr__(next(iter(asdict(result))), None)

    def _load_request(self, directory: Path):
        path = directory / "initialization.json"
        path.write_bytes(canonical_json(self._initialization_document()))
        return load_local_studio_initialization(path, (PROJECT_ROOT,))

    @staticmethod
    def _initialization_document():
        dictionary_digest = hashlib.sha256(b"fake private dictionary").hexdigest()
        return {
            "schema": "narrator_voice.local_studio_initialization",
            "schema_version": 2,
            "operator_display_label": "Private Operator",
            "lane_b": {
                "display_label": "SSGGSM Odia diary",
                "speaker_identity": "private-speaker-b",
                "voice_binding": "fixture-binding-b",
                "authorization_record_id": uuid(3),
                "initial_speed": "0.90",
                "initial_volume": "1.00",
                "initial_emotion": "calm",
                "opaque_provider_voice_reference": "private-voice-b",
                "dictionary_binding": {
                    "opaque_reference": "private-dictionary-b",
                    "content_sha256": dictionary_digest,
                    "revision": "private-dictionary-revision",
                    "capability_identity": "private-dictionary-capability",
                },
            },
            "lane_c": {
                "display_label": "Odia diary introduction",
                "speaker_identity": "private-speaker-c",
                "voice_binding": "fixture-binding-c",
                "authorization_record_id": uuid(4),
                "initial_speed": "1.10",
                "initial_volume": "1.00",
                "initial_emotion": None,
                "opaque_provider_voice_reference": "private-voice-c",
                "dictionary_binding": None,
            },
            "budget": {
                "project_id": "private-project",
                "billing_cycle_id": "private-cycle",
                "usage_unit": "characters",
                "per_take_cap": "8000",
                "per_run_cap": "32000",
                "project_cap": "100000",
                "billing_cycle_cap": "200000",
            },
            "default_passage_gap_samples": 22050,
            "default_intro_to_diary_gap_samples": 44100,
        }

    def _initialized_root(self, actor_index: int):
        directories = self._directories(2)
        input_directory, root_directory = directories.__enter__()
        self.addCleanup(directories.__exit__, None, None, None)
        request = self._load_request(input_directory)
        root = LocalNarrationRoot.open(root_directory, (PROJECT_ROOT,))
        initialize_local_studio(root, request, _Identifiers(ActorId(uuid(actor_index))))
        return _RootContext(root)

    def _directories(self, count: int):
        handles = [tempfile.TemporaryDirectory() for _ in range(count)]
        return _DirectoriesContext(handles)

    @staticmethod
    def _regular_files(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }


class _Identifiers:
    def __init__(self, actor_id: ActorId) -> None:
        self._actor_id = actor_id
        self.calls = 0

    def new_id(self, kind: type):
        if kind is not ActorId:
            raise AssertionError("initialization may generate only one ActorId")
        self.calls += 1
        return self._actor_id


class _DirectoriesContext:
    def __init__(self, handles: list[tempfile.TemporaryDirectory]) -> None:
        self._handles = handles

    def __enter__(self) -> tuple[Path, ...]:
        return tuple(Path(handle.name) for handle in self._handles)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        for handle in reversed(self._handles):
            handle.cleanup()


class _RootContext:
    def __init__(self, root: LocalNarrationRoot) -> None:
        self._root = root

    def __enter__(self) -> LocalNarrationRoot:
        return self._root

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
