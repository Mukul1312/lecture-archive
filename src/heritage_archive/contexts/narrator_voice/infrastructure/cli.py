"""Offline command adapter for local Narrator Voice operations.

This module owns only protocol parsing, exact nominal-ID conversion, redacted
serialization, and exit-code mapping.  The composition root supplies every
filesystem and application dependency lazily after parsing succeeds.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
from pathlib import Path
import sys
from typing import Protocol, TextIO

from heritage_archive.kernel import ContentDigest, ValidationError

from ..domain.errors import NarratorVoiceError
from ..domain.ids import (
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    GenerationAttemptId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
)


class CliConfigurationError(Exception):
    """A redacted configuration failure suitable for exit code two."""


class _ParserExit(Exception):
    def __init__(self, status: int) -> None:
        super().__init__()
        self.status = status


class _RedactingArgumentParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message and status == 0:
            self._print_message(message, sys.stdout)
        raise _ParserExit(status)

    def error(self, message: str) -> None:
        raise _ParserExit(2)


class CliOperations(Protocol):
    """Driver-facing facade implemented only by the composition root."""

    def initialize(self, config_file: Path) -> object: ...
    def doctor(self) -> object: ...
    def backup(self, destination: Path) -> object: ...
    def verify_backup(self, source: Path) -> object: ...
    def restore(self, source: Path) -> object: ...
    def reconcile_generation(
        self, job_id: NarrationJobId, attempt_id: GenerationAttemptId, expected_revision: int
    ) -> object: ...
    def reconcile_narration_assembly(
        self,
        job_id: NarrationJobId,
        attempt_id: NarrationAssemblyAttemptId,
        expected_revision: int,
    ) -> object: ...
    def reconcile_episode_assembly(
        self,
        episode_id: DiaryEpisodeId,
        attempt_id: EpisodeAssemblyAttemptId,
        expected_revision: int,
    ) -> object: ...


FacadeFactory = Callable[[bool], CliOperations]


def _positive_revision(raw: str) -> int:
    try:
        value = int(raw, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected revision must be a positive integer") from error
    if value < 1 or str(value) != raw:
        raise argparse.ArgumentTypeError("expected revision must be a canonical positive integer")
    return value


def _nominal_id(kind: type[object]) -> Callable[[str], object]:
    def parse(raw: str) -> object:
        try:
            return kind(raw)
        except (TypeError, ValueError) as error:
            raise argparse.ArgumentTypeError("identity must be lowercase RFC 4122 UUIDv4 text") from error

    return parse


def _absolute_path(raw: str) -> Path:
    value = Path(raw)
    if not value.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = _RedactingArgumentParser(
        prog="python -m heritage_archive.composition_root.narrator_voice_cli",
        description="Offline local operations for the Narrator Voice studio.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="initialize the explicit live root")
    initialize.add_argument("--config-file", required=True, type=_absolute_path, metavar="ABS_PATH")

    commands.add_parser("doctor", help="inspect local durable evidence without mutation")

    reconcile = commands.add_parser("reconcile", help="reconcile one explicit persisted attempt")
    variants = reconcile.add_subparsers(dest="kind", required=True)

    generation = variants.add_parser("generation")
    generation.add_argument("--job-id", required=True, type=_nominal_id(NarrationJobId), metavar="UUID")
    generation.add_argument(
        "--attempt-id", required=True, type=_nominal_id(GenerationAttemptId), metavar="UUID"
    )
    generation.add_argument("--expected-revision", required=True, type=_positive_revision, metavar="N")

    narration = variants.add_parser("narration-assembly")
    narration.add_argument("--job-id", required=True, type=_nominal_id(NarrationJobId), metavar="UUID")
    narration.add_argument(
        "--attempt-id", required=True, type=_nominal_id(NarrationAssemblyAttemptId), metavar="UUID"
    )
    narration.add_argument("--expected-revision", required=True, type=_positive_revision, metavar="N")

    episode = variants.add_parser("episode-assembly")
    episode.add_argument(
        "--episode-id", required=True, type=_nominal_id(DiaryEpisodeId), metavar="UUID"
    )
    episode.add_argument(
        "--attempt-id", required=True, type=_nominal_id(EpisodeAssemblyAttemptId), metavar="UUID"
    )
    episode.add_argument("--expected-revision", required=True, type=_positive_revision, metavar="N")

    backup = commands.add_parser("backup", help="copy the complete live root into an empty destination")
    backup.add_argument("--destination", required=True, type=_absolute_path, metavar="ABS_PATH")

    verify = commands.add_parser("verify-backup", help="verify an explicit backup without a live root")
    verify.add_argument("--source", required=True, type=_absolute_path, metavar="ABS_PATH")

    restore = commands.add_parser("restore", help="restore a verified backup into the live root")
    restore.add_argument("--source", required=True, type=_absolute_path, metavar="ABS_PATH")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    facade_factory: FacadeFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    parser = build_parser()
    try:
        arguments = parser.parse_args(None if argv is None else list(argv))
    except _ParserExit as exit_request:
        if exit_request.status != 0:
            _emit(errors, {"error": "usage_error"})
            return 2
        return 0

    if facade_factory is None:
        _emit(errors, {"error": "configuration_error"})
        return 2

    try:
        facade = facade_factory(arguments.command != "verify-backup")
        payload = _dispatch(arguments, facade)
    except CliConfigurationError:
        _emit(errors, {"error": "configuration_error"})
        return 2
    except (NarratorVoiceError, ValidationError, OSError, ValueError):
        _emit(errors, {"error": "operational_failure"})
        return 1
    except Exception:
        _emit(errors, {"error": "internal_failure"})
        return 1
    _emit(out, payload)
    return 0


def _dispatch(arguments: argparse.Namespace, facade: CliOperations) -> dict[str, object]:
    if arguments.command == "init":
        result = facade.initialize(arguments.config_file)
        return {
            "command": "init",
            "configuration_digest": _digest(result, "configuration_digest"),
            "initialized": _boolean(result, "initialized"),
        }
    if arguments.command == "doctor":
        result = facade.doctor()
        return {
            "checked_file_count": _count(result, "checked_file_count"),
            "command": "doctor",
            "healthy": _boolean(result, "healthy"),
            "issue_codes": list(_issue_codes(result)),
        }
    if arguments.command == "backup":
        result = facade.backup(arguments.destination)
        return _copy_result("backup", result)
    if arguments.command == "verify-backup":
        result = facade.verify_backup(arguments.source)
        digest = getattr(result, "manifest_digest", None)
        if digest is not None and type(digest) is not ContentDigest:
            raise ValidationError("backup verification digest is invalid")
        return {
            "byte_count": _count(result, "byte_count"),
            "command": "verify-backup",
            "file_count": _count(result, "file_count"),
            "issue_codes": list(_issue_codes(result)),
            "manifest_digest": None if digest is None else digest.hex_digest,
            "valid": _boolean(result, "valid"),
        }
    if arguments.command == "restore":
        result = facade.restore(arguments.source)
        return _copy_result("restore", result)
    if arguments.command == "reconcile":
        return _dispatch_reconcile(arguments, facade)
    raise ValidationError("unsupported parsed command")


def _dispatch_reconcile(arguments: argparse.Namespace, facade: CliOperations) -> dict[str, object]:
    if arguments.kind == "generation":
        result = facade.reconcile_generation(
            arguments.job_id, arguments.attempt_id, arguments.expected_revision
        )
        aggregate_key, aggregate_id = "job_id", arguments.job_id
    elif arguments.kind == "narration-assembly":
        result = facade.reconcile_narration_assembly(
            arguments.job_id, arguments.attempt_id, arguments.expected_revision
        )
        aggregate_key, aggregate_id = "job_id", arguments.job_id
    elif arguments.kind == "episode-assembly":
        result = facade.reconcile_episode_assembly(
            arguments.episode_id, arguments.attempt_id, arguments.expected_revision
        )
        aggregate_key, aggregate_id = "episode_id", arguments.episode_id
    else:
        raise ValidationError("unsupported reconcile kind")
    revision = _count(result, "revision", positive=True)
    result_identity = getattr(result, aggregate_key, None)
    if result_identity != aggregate_id:
        raise ValidationError("reconciliation result identity does not match the request")
    return {
        "attempt_id": arguments.attempt_id.value,
        "command": "reconcile",
        aggregate_key: aggregate_id.value,
        "kind": arguments.kind,
        "revision": revision,
    }


def _copy_result(command: str, result: object) -> dict[str, object]:
    return {
        "byte_count": _count(result, "byte_count"),
        "command": command,
        "file_count": _count(result, "file_count"),
        "manifest_digest": _digest(result, "manifest_digest"),
    }


def _boolean(result: object, field: str) -> bool:
    value = getattr(result, field, None)
    if type(value) is not bool:
        raise ValidationError("public result boolean is invalid")
    return value


def _count(result: object, field: str, *, positive: bool = False) -> int:
    value = getattr(result, field, None)
    minimum = 1 if positive else 0
    if type(value) is not int or value < minimum:
        raise ValidationError("public result count is invalid")
    return value


def _digest(result: object, field: str) -> str:
    value = getattr(result, field, None)
    if type(value) is not ContentDigest:
        raise ValidationError("public result digest is invalid")
    return value.hex_digest


def _issue_codes(result: object) -> tuple[str, ...]:
    values = getattr(result, "issue_codes", None)
    if type(values) is not tuple or any(type(value) is not str or not value for value in values):
        raise ValidationError("public issue codes are invalid")
    return values


def _emit(stream: TextIO, payload: dict[str, object]) -> None:
    stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    stream.write("\n")
