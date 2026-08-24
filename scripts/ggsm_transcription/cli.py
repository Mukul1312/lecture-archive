"""Thin, local-only command adapter for GGSM transcription jobs.

The optional ``--data-root`` argument is deliberately a test seam.  Normal use
relies on the repository-relative default ``data/transcribe``; tests can point it
at a temporary directory without importing or installing faster-whisper.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, Protocol, Sequence, TextIO

from .asr import ASRService, FfmpegMediaAdapter, LocalFasterWhisperAdapter
from .intake import HttpsFfprobeSourceAdapter, IntakeService, SourceAdapter
from .review import ReviewDeliveryService
from .store import JobStore, JobValidationError


DEFAULT_DATA_ROOT = Path("data") / "transcribe"


class CommandHandlers(Protocol):
    """Command-facing use cases; fakes exercise this boundary in unit tests."""

    def intake(self, url: str) -> dict[str, Any]: ...
    def status(self, job_id: str) -> dict[str, Any]: ...
    def transcribe(self, job_id: str) -> dict[str, Any]: ...
    def inspect(self, job_id: str) -> dict[str, Any]: ...
    def rerun_span(self, job_id: str, start: float, end: float) -> dict[str, Path]: ...
    def prepare_review(self, job_id: str) -> dict[str, object]: ...
    def register_reference(self, job_id: str, url: str, markdown_file: Path) -> dict[str, Any]: ...
    def record_review(self, job_id: str) -> dict[str, Any]: ...
    def assemble(self, job_id: str) -> Path: ...
    def verify(self, job_id: str) -> dict[str, Any]: ...
    def handoff(self, job_id: str) -> dict[str, Any]: ...


class WorkflowCommands:
    """Construct only the production adapter needed by each command invocation."""

    def __init__(
        self,
        store: JobStore,
        source_adapter_factory: Callable[[], SourceAdapter] = HttpsFfprobeSourceAdapter,
        model_adapter_factory: Callable[[], LocalFasterWhisperAdapter] = LocalFasterWhisperAdapter,
        media_adapter_factory: Callable[[], FfmpegMediaAdapter] = FfmpegMediaAdapter,
    ) -> None:
        self.store = store
        self._source_adapter_factory = source_adapter_factory
        self._model_adapter_factory = model_adapter_factory
        self._media_adapter_factory = media_adapter_factory

    def intake(self, url: str) -> dict[str, Any]:
        return IntakeService(self.store, self._source_adapter_factory()).intake(url)

    def status(self, job_id: str) -> dict[str, Any]:
        return self.store.load_job(job_id)

    def transcribe(self, job_id: str) -> dict[str, Any]:
        return ASRService(self.store, self._model_adapter_factory()).transcribe(job_id)

    def inspect(self, job_id: str) -> dict[str, Any]:
        return ASRService(self.store, self._model_adapter_factory()).inspect(job_id)

    def rerun_span(self, job_id: str, start: float, end: float) -> dict[str, Path]:
        return ASRService(
            self.store,
            self._model_adapter_factory(),
            self._media_adapter_factory(),
        ).rerun_span(job_id, start, end)

    def prepare_review(self, job_id: str) -> dict[str, object]:
        return ReviewDeliveryService(self.store).prepare_review(job_id)

    def register_reference(self, job_id: str, url: str, markdown_file: Path) -> dict[str, Any]:
        return ReviewDeliveryService(self.store).register_reference(job_id, url, markdown_file)

    def record_review(self, job_id: str) -> dict[str, Any]:
        return ReviewDeliveryService(self.store).record_review(job_id)

    def assemble(self, job_id: str) -> Path:
        return ReviewDeliveryService(self.store).assemble(job_id)

    def verify(self, job_id: str) -> dict[str, Any]:
        return ReviewDeliveryService(self.store).verify(job_id)

    def handoff(self, job_id: str) -> dict[str, Any]:
        return ReviewDeliveryService(self.store).handoff(job_id)


CommandBuilder = Callable[[Path], CommandHandlers]


def build_production_commands(data_root: Path, *, read_only: bool = False) -> WorkflowCommands:
    """Create the local production command facade after CLI argument parsing."""
    return WorkflowCommands(JobStore(data_root, create=not read_only))


def _finite_seconds(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("seconds must be a finite number") from error
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("seconds must be a finite number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ggsm_transcription",
        description="Prepare a local, reviewed GGSM English lecture Listening draft.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        metavar="PATH",
        help="Test seam for a job root (default: data/transcribe).",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    intake = commands.add_parser("intake", help="Download and bind an HTTPS source by SHA-256.")
    intake.add_argument("--url", required=True, metavar="HTTPS-URL")

    for name, help_text in (
        ("status", "Read the current job state without changing it."),
        ("transcribe", "Create immutable full local ASR evidence."),
        ("inspect", "Inspect full ASR evidence and identify ASR-uncovered spans."),
        ("prepare-review", "Create editable whole-timeline review chunks."),
        ("record-review", "Validate and record every completed review chunk."),
        ("assemble", "Create a deterministic Listening draft from completed review."),
        ("verify", "Verify current source, review, and Listening draft evidence."),
        ("handoff", "Write a manual-only local handoff receipt."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--job", required=True, metavar="JOB-ID")

    rerun = commands.add_parser("rerun-span", help="Add supplemental local ASR evidence for a span.")
    rerun.add_argument("--job", required=True, metavar="JOB-ID")
    rerun.add_argument("--start", required=True, type=_finite_seconds, metavar="SECONDS")
    rerun.add_argument("--end", required=True, type=_finite_seconds, metavar="SECONDS")

    reference = commands.add_parser("register-reference", help="Register a local secondary Markdown reference.")
    reference.add_argument("--job", required=True, metavar="JOB-ID")
    reference.add_argument("--url", required=True, metavar="HTTPS-URL")
    reference.add_argument("--file", required=True, type=Path, metavar="MARKDOWN")
    return parser


_NEXT_ACTIONS = {
    "created": "Resume intake only after source identity is established.",
    "source_ready": "Next: transcribe the bound source locally.",
    "asr_ready": "Next: inspect full ASR evidence before review.",
    "inspected": "Next: prepare and complete whole-timeline listening review.",
    "reviewed": "Next: assemble the Listening draft, then verify it.",
    "draft_ready": "Next: create the local manual-only handoff receipt.",
    "handed_off": "Listening draft has a local manual-only handoff receipt.",
}


def _state_payload(command: str, state: object) -> dict[str, object]:
    if not isinstance(state, dict) or not isinstance(state.get("job_id"), str) or not isinstance(state.get("stage"), str):
        raise JobValidationError("workflow command did not return a valid job state")
    stage = state["stage"]
    return {
        "command": command,
        "job_id": state["job_id"],
        "stage": stage,
        "next_action": _NEXT_ACTIONS.get(stage, "Read status before taking another action."),
    }


def _execute(arguments: argparse.Namespace, commands: CommandHandlers) -> dict[str, object]:
    command = arguments.command
    if command == "intake":
        return _state_payload(command, commands.intake(arguments.url))
    if command == "status":
        return _state_payload(command, commands.status(arguments.job))
    if command == "transcribe":
        return _state_payload(command, commands.transcribe(arguments.job))
    if command == "inspect":
        return _state_payload(command, commands.inspect(arguments.job))
    if command == "rerun-span":
        commands.rerun_span(arguments.job, arguments.start, arguments.end)
        payload = _state_payload(command, commands.status(arguments.job))
        payload["supplemental_evidence"] = "rerun span recorded"
        return payload
    if command == "prepare-review":
        plan = commands.prepare_review(arguments.job)
        payload = _state_payload(command, commands.status(arguments.job))
        chunks = plan.get("chunks") if isinstance(plan, dict) else None
        if not isinstance(chunks, list):
            raise JobValidationError("review preparation did not return a valid chunk plan")
        payload["review_chunks"] = len(chunks)
        return payload
    if command == "register-reference":
        return _state_payload(command, commands.register_reference(arguments.job, arguments.url, arguments.file))
    if command == "record-review":
        return _state_payload(command, commands.record_review(arguments.job))
    if command == "assemble":
        commands.assemble(arguments.job)
        payload = _state_payload(command, commands.status(arguments.job))
        payload["delivery"] = "delivery/onenote-transcript.md"
        return payload
    if command == "verify":
        return _state_payload(command, commands.verify(arguments.job))
    if command == "handoff":
        return _state_payload(command, commands.handoff(arguments.job))
    raise JobValidationError("unknown GGSM transcription command")


def main(
    argv: Sequence[str] | None = None,
    *,
    command_builder: CommandBuilder | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run one command, returning a process-style exit status without stack traces."""
    output, errors = stdout or sys.stdout, stderr or sys.stderr
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exit_signal:
        return int(exit_signal.code)
    try:
        if command_builder is not None:
            commands = command_builder(arguments.data_root)
        else:
            commands = build_production_commands(arguments.data_root, read_only=arguments.command == "status")
        result = _execute(arguments, commands)
    except (JobValidationError, OSError, ValueError) as error:
        print(f"error: {error}", file=errors)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=output)
    return 0
