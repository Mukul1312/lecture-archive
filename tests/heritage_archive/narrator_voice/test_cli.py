"""Focused contract tests for the offline Narrator Voice command adapter."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from heritage_archive.kernel import ContentDigest, canonical_json
from heritage_archive.contexts.narrator_voice.domain.ids import (
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    GenerationAttemptId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
)
from heritage_archive.contexts.narrator_voice.infrastructure import cli


JOB_ID = "11111111-1111-4111-8111-111111111111"
GENERATION_ID = "22222222-2222-4222-8222-222222222222"
NARRATION_ASSEMBLY_ID = "33333333-3333-4333-8333-333333333333"
EPISODE_ID = "44444444-4444-4444-8444-444444444444"
EPISODE_ASSEMBLY_ID = "55555555-5555-4555-8555-555555555555"
DIGEST = ContentDigest("sha256", "a" * 64)


@dataclass(frozen=True, slots=True)
class _InitResult:
    initialized: bool = True
    configuration_digest: ContentDigest = DIGEST


@dataclass(frozen=True, slots=True)
class _DoctorResult:
    healthy: bool = True
    checked_file_count: int = 7
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _BackupResult:
    file_count: int = 5
    byte_count: int = 321
    manifest_digest: ContentDigest = DIGEST


@dataclass(frozen=True, slots=True)
class _VerificationResult:
    valid: bool = True
    file_count: int = 5
    byte_count: int = 321
    manifest_digest: ContentDigest | None = DIGEST
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RestoreResult:
    file_count: int = 5
    byte_count: int = 321
    manifest_digest: ContentDigest = DIGEST


@dataclass(frozen=True, slots=True)
class _JobResult:
    job_id: NarrationJobId
    revision: int


@dataclass(frozen=True, slots=True)
class _EpisodeResult:
    episode_id: DiaryEpisodeId
    revision: int


class _RecordingFacade:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.failure: Exception | None = None

    def _return(self, name: str, result: object, *arguments: object) -> object:
        self.calls.append((name, arguments))
        if self.failure is not None:
            raise self.failure
        return result

    def initialize(self, config_file: Path) -> _InitResult:
        return self._return("init", _InitResult(), config_file)  # type: ignore[return-value]

    def doctor(self) -> _DoctorResult:
        return self._return("doctor", _DoctorResult())  # type: ignore[return-value]

    def backup(self, destination: Path) -> _BackupResult:
        return self._return("backup", _BackupResult(), destination)  # type: ignore[return-value]

    def verify_backup(self, source: Path) -> _VerificationResult:
        return self._return("verify-backup", _VerificationResult(), source)  # type: ignore[return-value]

    def restore(self, source: Path) -> _RestoreResult:
        return self._return("restore", _RestoreResult(), source)  # type: ignore[return-value]

    def reconcile_generation(
        self,
        job_id: NarrationJobId,
        attempt_id: GenerationAttemptId,
        expected_revision: int,
    ) -> _JobResult:
        return self._return(
            "reconcile-generation", _JobResult(job_id, expected_revision + 1),
            job_id, attempt_id, expected_revision,
        )  # type: ignore[return-value]

    def reconcile_narration_assembly(
        self,
        job_id: NarrationJobId,
        attempt_id: NarrationAssemblyAttemptId,
        expected_revision: int,
    ) -> _JobResult:
        return self._return(
            "reconcile-narration-assembly", _JobResult(job_id, expected_revision + 1),
            job_id, attempt_id, expected_revision,
        )  # type: ignore[return-value]

    def reconcile_episode_assembly(
        self,
        episode_id: DiaryEpisodeId,
        attempt_id: EpisodeAssemblyAttemptId,
        expected_revision: int,
    ) -> _EpisodeResult:
        return self._return(
            "reconcile-episode-assembly", _EpisodeResult(episode_id, expected_revision + 1),
            episode_id, attempt_id, expected_revision,
        )  # type: ignore[return-value]


class NarratorVoiceCliTests(unittest.TestCase):
    def test_serve_dispatches_once_without_stdout_and_has_no_configuration_flags(self):
        facade = _RecordingFacade()
        facade.serve = lambda: facade.calls.append(("serve", ()))
        code, stdout, stderr, builds = self._run(["serve"], facade)
        self.assertEqual((code, stdout, stderr, builds), (0, "", "", [True]))
        self.assertEqual(facade.calls, [("serve", ())])
        for flag in ("--host", "--port", "--workers", "--proxy-headers", "--cors", "--reload"):
            with self.subTest(flag=flag):
                code, stdout, stderr, builds = self._run(["serve", flag, "SENTINEL"])
                self.assertEqual((code, stdout, builds), (2, "", []))
                self.assertEqual(json.loads(stderr), {"error": "usage_error"})
        self.assertEqual(self._run(["serve", "--help"])[0], 0)
        facade.serve = lambda: (_ for _ in ()).throw(RuntimeError("SENTINEL"))
        code, stdout, stderr, builds = self._run(["serve"], facade)
        self.assertEqual((code, stdout, json.loads(stderr)), (1, "", {"error": "internal_failure"}))

    def test_help_and_offline_imports_do_not_load_optional_web_or_live_composition(self):
        repository = Path(__file__).resolve().parents[3]
        script = '''
import importlib.abc
import sys
class NoWeb(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'starlette', 'uvicorn', 'httpx'} or fullname.endswith(('narrator_voice_web', 'narrator_voice_live')):
            raise AssertionError('optional web/live import')
sys.meta_path.insert(0, NoWeb())
from heritage_archive.composition_root import narrator_voice_cli
from heritage_archive.contexts.narrator_voice.infrastructure.operations import DoctorResult
assert narrator_voice_cli.main(['--help']) == 0
assert narrator_voice_cli.main(['serve', '--help']) == 0
from heritage_archive.contexts.narrator_voice.infrastructure import cli
class Offline:
    def doctor(self):
        return DoctorResult(True, 0, ())
assert cli.main(['doctor'], facade_factory=lambda require_root: Offline()) == 0
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=repository,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_serve_composition_uses_only_the_explicit_root(self):
        from heritage_archive.composition_root import narrator_voice_cli, narrator_voice_web
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"CARTESIA_NARRATION_ROOT": folder}, clear=True), patch.object(narrator_voice_web, "serve_narration") as serve:
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = narrator_voice_cli.main(["serve"])
            self.assertEqual((code, stdout.getvalue(), stderr.getvalue()), (0, "", ""))
            self.assertEqual(serve.call_count, 1)
            self.assertEqual(serve.call_args.args[0].path, Path(folder).resolve())

    def _run(
        self,
        arguments: list[str],
        facade: _RecordingFacade | None = None,
    ) -> tuple[int, str, str, list[bool]]:
        actual = facade or _RecordingFacade()
        builder_calls: list[bool] = []

        def build(require_live_root: bool) -> _RecordingFacade:
            builder_calls.append(require_live_root)
            return actual

        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(arguments, facade_factory=build)
        return code, stdout.getvalue(), stderr.getvalue(), builder_calls

    def test_help_and_parse_errors_are_lazy_and_redacted(self) -> None:
        code, stdout, stderr, builds = self._run(["--help"])
        self.assertEqual((code, stderr, builds), (0, "", []))
        self.assertIn("reconcile", stdout)
        self.assertIn("verify-backup", stdout)

        sentinel = "C:/private/SENTINEL-VOICE-ID"
        for arguments in (["--root", sentinel, "doctor"], ["serve", "--host", sentinel], ["init", "--config-file", sentinel, "extra"]):
            with self.subTest(arguments=arguments):
                code, stdout, stderr, builds = self._run(list(arguments))
                self.assertEqual((code, stdout, builds), (2, "", []))
                self.assertEqual(json.loads(stderr), {"error": "usage_error"})
                self.assertNotIn(sentinel, stderr)

    def test_operational_commands_preserve_explicit_path_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            cases = (
                (["init", "--config-file", str(base / "seed.json")], "init", (base / "seed.json",), True),
                (["doctor"], "doctor", (), True),
                (["backup", "--destination", str(base / "backup")], "backup", (base / "backup",), True),
                (["verify-backup", "--source", str(base / "backup")], "verify-backup", (base / "backup",), False),
                (["restore", "--source", str(base / "backup")], "restore", (base / "backup",), True),
            )
            for arguments, call_name, call_arguments, requires_root in cases:
                with self.subTest(command=arguments[0]):
                    facade = _RecordingFacade()
                    code, stdout, stderr, builds = self._run(arguments, facade)
                    self.assertEqual((code, stderr, builds), (0, "", [requires_root]))
                    self.assertEqual(facade.calls, [(call_name, call_arguments)])
                    payload = json.loads(stdout)
                    self.assertEqual(payload["command"], arguments[0])
                    self.assertNotIn(str(base), stdout)

    def test_all_reconcile_variants_dispatch_one_typed_attempt(self) -> None:
        cases = (
            (
                ["reconcile", "generation", "--job-id", JOB_ID, "--attempt-id", GENERATION_ID, "--expected-revision", "9"],
                "reconcile-generation",
                (NarrationJobId(JOB_ID), GenerationAttemptId(GENERATION_ID), 9),
                "generation",
            ),
            (
                ["reconcile", "narration-assembly", "--job-id", JOB_ID, "--attempt-id", NARRATION_ASSEMBLY_ID, "--expected-revision", "10"],
                "reconcile-narration-assembly",
                (NarrationJobId(JOB_ID), NarrationAssemblyAttemptId(NARRATION_ASSEMBLY_ID), 10),
                "narration-assembly",
            ),
            (
                ["reconcile", "episode-assembly", "--episode-id", EPISODE_ID, "--attempt-id", EPISODE_ASSEMBLY_ID, "--expected-revision", "11"],
                "reconcile-episode-assembly",
                (DiaryEpisodeId(EPISODE_ID), EpisodeAssemblyAttemptId(EPISODE_ASSEMBLY_ID), 11),
                "episode-assembly",
            ),
        )
        for arguments, call_name, expected, kind in cases:
            with self.subTest(kind=kind):
                facade = _RecordingFacade()
                code, stdout, stderr, builds = self._run(arguments, facade)
                self.assertEqual((code, stderr, builds), (0, "", [True]))
                self.assertEqual(facade.calls, [(call_name, expected)])
                payload = json.loads(stdout)
                self.assertEqual(payload["kind"], kind)
                self.assertEqual(payload["attempt_id"], expected[1].value)
                self.assertEqual(payload["revision"], expected[2] + 1)

    def test_invalid_uuid_revision_and_relative_paths_are_usage_errors_before_dispatch(self) -> None:
        cases = (
            ["reconcile", "generation", "--job-id", "private-invalid", "--attempt-id", GENERATION_ID, "--expected-revision", "1"],
            ["reconcile", "generation", "--job-id", JOB_ID, "--attempt-id", GENERATION_ID, "--expected-revision", "0"],
            ["init", "--config-file", "private/seed.json"],
            ["backup", "--destination", "private/backup"],
            ["verify-backup", "--source", "private/backup"],
            ["restore", "--source", "private/backup"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                code, stdout, stderr, builds = self._run(arguments)
                self.assertEqual((code, stdout, builds), (2, "", []))
                self.assertEqual(json.loads(stderr), {"error": "usage_error"})
                self.assertNotIn("private-invalid", stderr)

    def test_configuration_and_operational_failures_use_stable_redacted_errors(self) -> None:
        sentinel = "SENTINEL-API-KEY-and-private-root"

        def bad_configuration(_requires_live_root: bool) -> _RecordingFacade:
            raise cli.CliConfigurationError(sentinel)

        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["doctor"], facade_factory=bad_configuration)
        self.assertEqual((code, stdout.getvalue()), (2, ""))
        self.assertEqual(json.loads(stderr.getvalue()), {"error": "configuration_error"})
        self.assertNotIn(sentinel, stderr.getvalue())

        facade = _RecordingFacade()
        facade.failure = OSError(sentinel)
        code, stdout_value, stderr_value, _builds = self._run(["doctor"], facade)
        self.assertEqual((code, stdout_value), (1, ""))
        self.assertEqual(json.loads(stderr_value), {"error": "operational_failure"})
        self.assertNotIn(sentinel, stderr_value)

    def test_outputs_are_curated_and_do_not_serialize_extra_private_fields(self) -> None:
        class ResultWithSecret:
            healthy = False
            checked_file_count = 3
            issue_codes = ("corrupt_json",)
            actor_id = "SENTINEL-ACTOR"
            root = "C:/SENTINEL-ROOT"
            provider_voice_id = "SENTINEL-VOICE"

        facade = _RecordingFacade()
        facade.doctor = lambda: ResultWithSecret()  # type: ignore[method-assign]
        code, stdout, stderr, _builds = self._run(["doctor"], facade)
        self.assertEqual((code, stderr), (1, ""))
        self.assertEqual(
            json.loads(stdout),
            {
                "checked_file_count": 3,
                "command": "doctor",
                "healthy": False,
                "issue_codes": ["corrupt_json"],
            },
        )
        self.assertNotIn("SENTINEL", stdout)

    def test_invalid_backup_emits_its_curated_report_and_exits_nonzero(self) -> None:
        facade = _RecordingFacade()
        facade.verify_backup = lambda _source: _VerificationResult(  # type: ignore[method-assign]
            valid=False,
            issue_codes=("backup_file_digest_mismatch",),
        )
        source = Path(tempfile.gettempdir()).resolve() / "explicit-backup"

        code, stdout, stderr, builds = self._run(
            ["verify-backup", "--source", str(source)], facade
        )

        self.assertEqual((code, stderr, builds), (1, "", [False]))
        self.assertEqual(
            json.loads(stdout),
            {
                "byte_count": 321,
                "command": "verify-backup",
                "file_count": 5,
                "issue_codes": ["backup_file_digest_mismatch"],
                "manifest_digest": "a" * 64,
                "valid": False,
            },
        )

    def test_module_help_subprocess_exits_zero_when_package_is_importable(self) -> None:
        repository = Path(__file__).resolve().parents[3]
        environment = dict(os.environ)
        environment.pop("CARTESIA_NARRATION_ROOT", None)
        # Tests run directly from a src-layout checkout.  This explicit import
        # path models the package visibility supplied by the documented editable
        # install; it is not claimed as zero-setup checkout behavior.
        environment["PYTHONPATH"] = str(repository / "src")
        result = subprocess.run(
            [sys.executable, "-m", "heritage_archive.composition_root.narrator_voice_cli", "--help"],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reconcile", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_composition_root_rejects_missing_blank_and_relative_environment_without_writing(self) -> None:
        from heritage_archive.composition_root import narrator_voice_cli

        with tempfile.TemporaryDirectory() as folder:
            working = Path(folder)
            relative = "must-not-be-created"
            for value in (None, "", "   ", relative):
                with self.subTest(value=value):
                    environment = {} if value is None else {"CARTESIA_NARRATION_ROOT": value}
                    stdout, stderr = StringIO(), StringIO()
                    previous = Path.cwd()
                    os.chdir(working)
                    try:
                        with patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
                            code = narrator_voice_cli.main(["doctor"])
                    finally:
                        os.chdir(previous)
                    self.assertEqual((code, stdout.getvalue()), (2, ""))
                    self.assertEqual(json.loads(stderr.getvalue()), {"error": "configuration_error"})
                    self.assertFalse((working / relative).exists())

    def test_real_composition_init_doctor_and_missing_attempt_failure_are_offline_and_redacted(self) -> None:
        from heritage_archive.composition_root import narrator_voice_cli

        with tempfile.TemporaryDirectory() as input_folder, tempfile.TemporaryDirectory() as root_folder:
            seed = Path(input_folder) / "private-seed.json"
            seed.write_bytes(canonical_json({"schema": "invalid-private-seed"}))
            stdout, stderr = StringIO(), StringIO()
            with (
                patch.dict(os.environ, {"CARTESIA_NARRATION_ROOT": root_folder}, clear=True),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                invalid_code = narrator_voice_cli.main(["init", "--config-file", str(seed)])
            self.assertEqual((invalid_code, stdout.getvalue()), (2, ""))
            self.assertEqual(json.loads(stderr.getvalue()), {"error": "configuration_error"})
            self.assertEqual(tuple(Path(root_folder).iterdir()), ())

            seed.write_bytes(canonical_json(_private_initialization_document()))
            environment = {"CARTESIA_NARRATION_ROOT": root_folder}

            outputs: list[str] = []
            with patch.dict(os.environ, environment, clear=True):
                for arguments in (
                    ["init", "--config-file", str(seed)],
                    ["doctor"],
                ):
                    stdout, stderr = StringIO(), StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = narrator_voice_cli.main(arguments)
                    self.assertEqual((code, stderr.getvalue()), (0, ""))
                    outputs.append(stdout.getvalue())

                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = narrator_voice_cli.main([
                        "reconcile", "generation", "--job-id", JOB_ID,
                        "--attempt-id", GENERATION_ID, "--expected-revision", "1",
                    ])

            self.assertTrue(seed.is_file())
            self.assertTrue(json.loads(outputs[0])["initialized"])
            self.assertTrue(json.loads(outputs[1])["healthy"])
            self.assertEqual((code, stdout.getvalue()), (1, ""))
            self.assertEqual(json.loads(stderr.getvalue()), {"error": "operational_failure"})
            rendered = "".join(outputs) + stderr.getvalue()
            for sentinel in ("Private Operator", "private-voice-b", root_folder, input_folder):
                self.assertNotIn(sentinel, rendered)

    def test_real_composition_backup_verification_without_env_and_restore_use_explicit_sides(self) -> None:
        from heritage_archive.composition_root import narrator_voice_cli

        with (
            tempfile.TemporaryDirectory() as input_folder,
            tempfile.TemporaryDirectory() as root_folder,
            tempfile.TemporaryDirectory() as backup_folder,
            tempfile.TemporaryDirectory() as restore_folder,
        ):
            seed = Path(input_folder) / "private-seed.json"
            seed.write_bytes(canonical_json(_private_initialization_document()))
            live_environment = {"CARTESIA_NARRATION_ROOT": root_folder}
            setup_stdout, setup_stderr = StringIO(), StringIO()
            with (
                patch.dict(os.environ, live_environment, clear=True),
                redirect_stdout(setup_stdout),
                redirect_stderr(setup_stderr),
            ):
                self.assertEqual(narrator_voice_cli.main(["init", "--config-file", str(seed)]), 0)
                self.assertEqual(narrator_voice_cli.main(["backup", "--destination", backup_folder]), 0)
            self.assertEqual(setup_stderr.getvalue(), "")
            self.assertNotIn(root_folder, setup_stdout.getvalue())
            self.assertNotIn(backup_folder, setup_stdout.getvalue())

            stdout, stderr = StringIO(), StringIO()
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
                verification_code = narrator_voice_cli.main(["verify-backup", "--source", backup_folder])
            self.assertEqual((verification_code, stderr.getvalue()), (0, ""))
            self.assertTrue(json.loads(stdout.getvalue())["valid"])

            stdout, stderr = StringIO(), StringIO()
            with patch.dict(
                os.environ,
                {"CARTESIA_NARRATION_ROOT": restore_folder},
                clear=True,
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                restore_code = narrator_voice_cli.main(["restore", "--source", backup_folder])
            self.assertEqual((restore_code, stderr.getvalue()), (0, ""))
            self.assertEqual(json.loads(stdout.getvalue())["command"], "restore")
            self.assertTrue((Path(restore_folder) / "operations" / "studio-config.json").is_file())


def _private_initialization_document() -> dict[str, object]:
    return {
        "schema": "narrator_voice.local_studio_initialization",
        "schema_version": 2,
        "operator_display_label": "Private Operator",
        "lane_b": {
            "display_label": "SSGGSM Odia diary",
            "speaker_identity": "private-speaker-b",
            "voice_binding": "fixture-binding-b",
            "authorization_record_id": "123e4567-e89b-42d3-a456-426614190003",
            "initial_speed": "0.90",
            "initial_volume": "1.00",
            "initial_emotion": "calm",
            "opaque_provider_voice_reference": "private-voice-b",
            "dictionary_binding": None,
        },
        "lane_c": {
            "display_label": "Odia diary introduction",
            "speaker_identity": "private-speaker-c",
            "voice_binding": "fixture-binding-c",
            "authorization_record_id": "123e4567-e89b-42d3-a456-426614190004",
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


if __name__ == "__main__":
    unittest.main()
