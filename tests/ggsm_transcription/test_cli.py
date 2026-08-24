"""Command-level contracts for the local GGSM transcription runner."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.error import URLError

from scripts.ggsm_transcription import cli
from scripts.ggsm_transcription.asr import LocalFasterWhisperAdapter
from scripts.ggsm_transcription.intake import HttpsFfprobeSourceAdapter, IntakeService, SourceDownload
from scripts.ggsm_transcription.store import JobStore, JobValidationError


class FakeSourceAdapter:
    def download(self, _url: str, staging_path: Path) -> SourceDownload:
        staging_path.write_bytes(b"fake lecture audio")
        return SourceDownload(
            "https://archive.example/final/lecture.mp3",
            "lecture.mp3",
            {"downloader": "fake downloader"},
        )

    def probe(self, _source_path: Path) -> dict[str, object]:
        return {
            "duration_seconds": 620.0,
            "codec": "mp3",
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
            "tool_versions": {"ffprobe": "fake ffprobe"},
        }


class FakeModelAdapter:
    def transcribe(self, source_path: Path, _configuration: dict[str, object]) -> list[dict[str, object]]:
        if source_path.suffix == ".mka":
            return [{"id": 0, "start": 0.0, "end": 1.0, "text": " Span words."}]
        return [
            {"id": 0, "start": 0.0, "end": 100.0, "text": " Opening words."},
            {"id": 1, "start": 200.0, "end": 620.0, "text": " Closing words."},
        ]

    def runtime_metadata(self) -> dict[str, str]:
        return {
            "model_snapshot": "/fake/small",
            "faster_whisper": "1.2.1",
            "python": "fake",
            "ffmpeg": "fake",
            "ffprobe": "fake",
        }


class FakeMediaAdapter:
    def extract_span(self, _source: Path, target: Path, _start: float, _end: float) -> None:
        target.write_bytes(b"fake span")

    def runtime_metadata(self) -> dict[str, str]:
        return {"ffmpeg": "fake", "ffprobe": "fake"}


class FakeHttpResponse(BytesIO):
    def __init__(self, payload: bytes, resolved_url: str) -> None:
        super().__init__(payload)
        self._resolved_url = resolved_url

    def geturl(self) -> str:
        return self._resolved_url


class RecordingCommands:
    """A parser-bound fake whose return values mirror command service boundaries."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.state = {"job_id": "lecture-12345678", "stage": "source_ready"}

    def _state(self, name: str, *arguments: object) -> dict[str, str]:
        self.calls.append((name, arguments))
        return dict(self.state)

    def intake(self, url: str) -> dict[str, str]:
        return self._state("intake", url)

    def status(self, job_id: str) -> dict[str, str]:
        return self._state("status", job_id)

    def transcribe(self, job_id: str) -> dict[str, str]:
        return self._state("transcribe", job_id)

    def inspect(self, job_id: str) -> dict[str, str]:
        return self._state("inspect", job_id)

    def rerun_span(self, job_id: str, start: float, end: float) -> dict[str, Path]:
        self.calls.append(("rerun-span", (job_id, start, end)))
        return {"jsonl_path": Path("asr/reruns/span.jsonl"), "metadata_path": Path("asr/reruns/span.metadata.json")}

    def prepare_review(self, job_id: str) -> dict[str, object]:
        self.calls.append(("prepare-review", (job_id,)))
        return {"chunks": [{"id": "chunk-001"}]}

    def register_reference(self, job_id: str, url: str, markdown_file: Path) -> dict[str, str]:
        return self._state("register-reference", job_id, url, markdown_file)

    def record_review(self, job_id: str) -> dict[str, str]:
        return self._state("record-review", job_id)

    def assemble(self, job_id: str) -> Path:
        self.calls.append(("assemble", (job_id,)))
        return Path("delivery/onenote-transcript.md")

    def verify(self, job_id: str) -> dict[str, str]:
        return self._state("verify", job_id)

    def handoff(self, job_id: str) -> dict[str, str]:
        return self._state("handoff", job_id)


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name) / "data" / "transcribe"

    def _run(self, arguments: list[str], builder=None) -> tuple[int, str, str]:
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(arguments, command_builder=builder)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_is_available_without_constructing_workflow_adapters(self) -> None:
        def forbidden_builder(_data_root: Path):
            raise AssertionError("help must not construct a workflow")

        code, stdout, stderr = self._run(["--help"], forbidden_builder)

        self.assertEqual(code, 0)
        self.assertIn("transcribe", stdout)
        self.assertIn("--data-root", stdout)
        self.assertEqual(stderr, "")

    def test_status_does_not_create_a_missing_data_root(self) -> None:
        absent_root = Path(self.tmp.name) / "status-must-not-write"

        code, stdout, stderr = self._run(
            ["--data-root", str(absent_root), "status", "--job", "lecture-12345678"]
        )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("data root", stderr)
        self.assertFalse(absent_root.exists())

    def test_every_command_requires_its_declared_arguments_and_unknown_commands_fail_closed(self) -> None:
        commands = [
            "intake", "status", "transcribe", "inspect", "rerun-span", "prepare-review",
            "register-reference", "record-review", "assemble", "verify", "handoff",
        ]
        for command in commands:
            with self.subTest(command=command):
                code, stdout, stderr = self._run([command])
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("required", stderr)

        code, stdout, stderr = self._run(["not-a-command"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("invalid choice", stderr)

    def test_parser_dispatches_every_declared_command_and_serializes_concise_results(self) -> None:
        commands = RecordingCommands()
        builder_roots: list[Path] = []

        def builder(data_root: Path) -> RecordingCommands:
            builder_roots.append(data_root)
            return commands

        reference = Path(self.tmp.name) / "reference.md"
        reference.write_text("secondary evidence", encoding="utf-8")
        cases = [
            (["--data-root", str(self.data_root), "intake", "--url", "https://archive.example/lecture.mp3"], "intake"),
            (["--data-root", str(self.data_root), "status", "--job", "lecture-12345678"], "status"),
            (["--data-root", str(self.data_root), "transcribe", "--job", "lecture-12345678"], "transcribe"),
            (["--data-root", str(self.data_root), "inspect", "--job", "lecture-12345678"], "inspect"),
            (["--data-root", str(self.data_root), "rerun-span", "--job", "lecture-12345678", "--start", "1.5", "--end", "3.5"], "rerun-span"),
            (["--data-root", str(self.data_root), "prepare-review", "--job", "lecture-12345678"], "prepare-review"),
            (["--data-root", str(self.data_root), "register-reference", "--job", "lecture-12345678", "--url", "https://www.taptajivanam.com/lecture", "--file", str(reference)], "register-reference"),
            (["--data-root", str(self.data_root), "record-review", "--job", "lecture-12345678"], "record-review"),
            (["--data-root", str(self.data_root), "assemble", "--job", "lecture-12345678"], "assemble"),
            (["--data-root", str(self.data_root), "verify", "--job", "lecture-12345678"], "verify"),
            (["--data-root", str(self.data_root), "handoff", "--job", "lecture-12345678"], "handoff"),
        ]

        for arguments, command in cases:
            with self.subTest(command=command):
                code, stdout, stderr = self._run(arguments, builder)
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                result = json.loads(stdout)
                self.assertEqual(result["command"], command)
                self.assertEqual(result["job_id"], "lecture-12345678")
                self.assertIn("next_action", result)

        self.assertEqual(builder_roots, [self.data_root] * len(cases))
        self.assertEqual([name for name, _arguments in commands.calls], [
            "intake", "status", "transcribe", "inspect", "rerun-span", "status",
            "prepare-review", "status", "register-reference", "record-review", "assemble",
            "status", "verify", "handoff",
        ])

    def test_real_services_preserve_stage_gates_and_status_does_not_mutate_the_manifest(self) -> None:
        store = JobStore(self.data_root)
        source, model, media = FakeSourceAdapter(), FakeModelAdapter(), FakeMediaAdapter()

        def builder(_data_root: Path) -> cli.WorkflowCommands:
            return cli.WorkflowCommands(
                store,
                source_adapter_factory=lambda: source,
                model_adapter_factory=lambda: model,
                media_adapter_factory=lambda: media,
            )

        intake_arguments = ["intake", "--url", "https://archive.example/lecture.mp3"]
        code, stdout, stderr = self._run(intake_arguments, builder)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        job_id = json.loads(stdout)["job_id"]

        manifest_path = store.job_root(job_id) / "job.json"
        before_status = manifest_path.read_bytes()
        code, stdout, stderr = self._run(["status", "--job", job_id], builder)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["stage"], "source_ready")
        self.assertEqual(manifest_path.read_bytes(), before_status)

        code, _stdout, stderr = self._run(["assemble", "--job", job_id], builder)
        self.assertEqual(code, 1)
        self.assertIn("assemble requires a reviewed job", stderr)
        self.assertEqual(store.load_job(job_id)["stage"], "source_ready")

        code, _stdout, stderr = self._run(["handoff", "--job", job_id], builder)
        self.assertEqual(code, 1)
        self.assertIn("handoff requires a draft_ready job", stderr)
        self.assertEqual(store.load_job(job_id)["stage"], "source_ready")

        code, _stdout, stderr = self._run(["transcribe", "--job", job_id], builder)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(store.load_job(job_id)["stage"], "asr_ready")

        code, _stdout, stderr = self._run(["assemble", "--job", job_id], builder)
        self.assertEqual(code, 1)
        self.assertIn("assemble requires a reviewed job", stderr)
        code, _stdout, stderr = self._run(["handoff", "--job", job_id], builder)
        self.assertEqual(code, 1)
        self.assertIn("handoff requires a draft_ready job", stderr)
        self.assertEqual(store.load_job(job_id)["stage"], "asr_ready")

        code, _stdout, stderr = self._run(["rerun-span", "--job", job_id, "--start", "0", "--end", "10"], builder)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        code, _stdout, stderr = self._run(["inspect", "--job", job_id], builder)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        code, _stdout, stderr = self._run(["prepare-review", "--job", job_id], builder)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

        review_root = store.job_root(job_id) / "review"
        for chunk in json.loads((review_root / "manifest.json").read_text(encoding="utf-8"))["chunks"]:
            path = store.job_root(job_id) / chunk["path"]
            text = path.read_text(encoding="utf-8").replace("Review-State: pending", "Review-State: reviewed")
            before, _separator, _body = text.partition("## Editorial transcript\n")
            path.write_text(
                before + "## Editorial transcript\n\n[00:00:00] Opening.\n\n[00:05:00] Continuing.\n\n[00:10:00] Closing.\n",
                encoding="utf-8",
                newline="\n",
            )

        reference = Path(self.tmp.name) / "reference.md"
        reference.write_text("secondary reference", encoding="utf-8")
        commands = [
            (["register-reference", "--job", job_id, "--url", "https://www.taptajivanam.com/lecture", "--file", str(reference)], "inspected"),
            (["record-review", "--job", job_id], "reviewed"),
            (["assemble", "--job", job_id], "reviewed"),
            (["verify", "--job", job_id], "draft_ready"),
            (["handoff", "--job", job_id], "handed_off"),
        ]
        for arguments, expected_stage in commands:
            with self.subTest(command=arguments[0]):
                code, stdout, stderr = self._run(arguments, builder)
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                self.assertEqual(json.loads(stdout)["stage"], expected_stage)

        self.assertEqual(store.load_job(job_id)["stage"], "handed_off")
        self.assertTrue((store.job_root(job_id) / "delivery" / "onenote-transcript.md").is_file())

    def test_cli_rejects_non_finite_span_arguments_before_workflow_execution(self) -> None:
        commands = RecordingCommands()

        code, stdout, stderr = self._run(
            ["rerun-span", "--job", "lecture-12345678", "--start", "nan", "--end", "3"],
            lambda _data_root: commands,
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("finite number", stderr)
        self.assertEqual(commands.calls, [])


class CliExternalFailureContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name) / "data" / "transcribe"

    def _run(self, arguments: list[str], builder) -> tuple[int, str, str]:
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(arguments, command_builder=builder)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_https_adapter_normalizes_a_download_operational_error(self) -> None:
        def offline(_request: object) -> object:
            raise URLError("offline")

        adapter = HttpsFfprobeSourceAdapter(http_open=offline)

        with self.assertRaisesRegex(JobValidationError, "HTTPS source download failed"):
            adapter.download("https://archive.example/lecture.mp3", Path(self.tmp.name) / "source.part")

    def test_cli_normalizes_the_production_ffprobe_nonzero_boundary_without_creating_a_job(self) -> None:
        def failing_ffprobe(command: list[str], **_kwargs: object) -> object:
            raise subprocess.CalledProcessError(1, command, stderr="ffprobe failed")

        adapter = HttpsFfprobeSourceAdapter(
            http_open=lambda _request: FakeHttpResponse(b"source bytes", "https://archive.example/final/lecture.mp3"),
            run_command=failing_ffprobe,
        )
        store = JobStore(self.data_root)

        code, stdout, stderr = self._run(
            ["intake", "--url", "https://archive.example/lecture.mp3"],
            lambda _data_root: cli.WorkflowCommands(store, source_adapter_factory=lambda: adapter),
        )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("ffprobe failed to inspect the downloaded source", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(store.list_jobs(), [])

    def test_cli_normalizes_local_backend_runtime_failure_without_advancing_the_job(self) -> None:
        class FailingBackend:
            @staticmethod
            def WhisperModel(*_args: object, **_kwargs: object) -> object:
                raise RuntimeError("backend initialization failed")

        store = JobStore(self.data_root)
        job = IntakeService(store, FakeSourceAdapter()).intake("https://archive.example/lecture.mp3")
        snapshot = Path(self.tmp.name) / "small-snapshot"
        snapshot.mkdir()
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
        adapter = LocalFasterWhisperAdapter(
            snapshot_path=snapshot,
            module_importer=lambda _name: FailingBackend,
        )

        code, stdout, stderr = self._run(
            ["transcribe", "--job", job["job_id"]],
            lambda _data_root: cli.WorkflowCommands(store, model_adapter_factory=lambda: adapter),
        )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("local faster-whisper backend failed during transcription", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(store.load_job(job["job_id"])["stage"], "source_ready")
        self.assertFalse((store.job_root(job["job_id"]) / "asr" / "full.jsonl").exists())

    def test_local_adapter_does_not_hide_an_unexpected_programmer_type_error(self) -> None:
        class ProgrammerFailure:
            @staticmethod
            def WhisperModel(*_args: object, **_kwargs: object) -> object:
                raise TypeError("unexpected adapter contract")

        snapshot = Path(self.tmp.name) / "type-error-snapshot"
        snapshot.mkdir()
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
        adapter = LocalFasterWhisperAdapter(snapshot_path=snapshot, module_importer=lambda _name: ProgrammerFailure)

        with self.assertRaisesRegex(TypeError, "unexpected adapter contract"):
            adapter.transcribe(Path(self.tmp.name) / "source.bin", {})
