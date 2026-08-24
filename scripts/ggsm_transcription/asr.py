"""Local, evidence-preserving ASR and ASR-uncovered inspection."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Protocol

from .store import ArtifactValidationError, JobStore, JobValidationError, StageTransitionError


DEFAULT_ASR_CONFIGURATION: dict[str, object] = {
    "model": "small", "device": "cpu", "compute_type": "int8", "language": "en",
    "beam_size": 5, "word_timestamps": True, "vad_filter": False,
    "condition_on_previous_text": False,
}
_REQUIRED_MEDIA_RUNTIME_KEYS = {"execution_mode", "ffmpeg", "ffprobe"}
_LOCAL_EXECUTION_MODE = "local"
_PINNED_FASTER_WHISPER_VERSION = "1.2.1"
_ASR_RUNTIME_KEYS = {
    "execution_mode", "model_snapshot", "faster_whisper", "python", "ffmpeg", "ffprobe",
}
_FULL_ASR_METADATA_KEYS = {"source_sha256", "configuration", "runtime"}
_RERUN_METADATA_KEYS = {
    "source_sha256", "start_seconds", "end_seconds", "configuration", "runtime", "media_runtime",
}


class _StrictJsonParseError(ValueError):
    """Serialized ASR evidence cannot be safely interpreted."""


@dataclass(frozen=True)
class _JsonNumber:
    """A finite JSON number with its original token retained for validation."""

    lexeme: str
    kind: str
    value: int | float


class ASRAdapter(Protocol):
    def transcribe(self, source_path: Path, configuration: dict[str, object]) -> list[dict[str, object]]: ...
    def runtime_metadata(self) -> dict[str, str]: ...


class MediaAdapter(Protocol):
    def extract_span(self, source: Path, target: Path, start: float, end: float) -> None: ...
    def runtime_metadata(self) -> dict[str, str]: ...


def _command_version(command: str) -> str:
    try:
        completed = subprocess.run([command, "-version"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise JobValidationError(f"{command} is required for local transcription") from error
    lines = completed.stdout.splitlines() or completed.stderr.splitlines()
    return lines[0].strip() if lines and lines[0].strip() else "unknown"


class LocalFasterWhisperAdapter:
    """Production adapter which resolves only a local cached small snapshot."""

    def __init__(self, snapshot_path: Path | None = None, module_importer: Callable[[str], Any] = importlib.import_module) -> None:
        self._configured_snapshot = snapshot_path
        self._import_module = module_importer
        self._selected_snapshot: Path | None = None

    def _snapshot(self) -> Path:
        if self._selected_snapshot is not None:
            return self._selected_snapshot
        if self._configured_snapshot is not None:
            candidates = [self._configured_snapshot]
        else:
            root = Path.home() / ".cache" / "huggingface" / "hub" / "models--Systran--faster-whisper-small" / "snapshots"
            candidates = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name) if root.is_dir() else []
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "config.json").is_file():
                self._selected_snapshot = candidate.resolve()
                return self._selected_snapshot
        raise JobValidationError("local small model snapshot is unavailable; cache Systran/faster-whisper-small before transcribing")

    def runtime_metadata(self) -> dict[str, str]:
        snapshot = self._snapshot()
        try:
            version = importlib.metadata.version("faster-whisper")
        except importlib.metadata.PackageNotFoundError:
            version = "unavailable"
        return {
            "execution_mode": _LOCAL_EXECUTION_MODE,
            "model_snapshot": str(snapshot),
            "faster_whisper": version,
            "python": sys.version.split()[0],
            "ffmpeg": _command_version("ffmpeg"),
            "ffprobe": _command_version("ffprobe"),
        }

    def transcribe(self, source_path: Path, configuration: dict[str, object]) -> list[dict[str, object]]:
        snapshot = self._snapshot()
        try:
            faster_whisper = self._import_module("faster_whisper")
        except ImportError as error:
            raise JobValidationError("faster-whisper is unavailable; activate .venv-transcribe before transcribing") from error
        try:
            model = faster_whisper.WhisperModel(str(snapshot), device="cpu", compute_type="int8")
            segments, _info = model.transcribe(str(source_path), language="en", beam_size=5, word_timestamps=True,
                                              vad_filter=False, condition_on_previous_text=False)
            return [_segment_to_record(index, segment) for index, segment in enumerate(segments)]
        except (OSError, RuntimeError) as error:
            raise JobValidationError("local faster-whisper backend failed during transcription") from error


class FfmpegMediaAdapter:
    def __init__(self, run_command: Callable[..., Any] = subprocess.run) -> None:
        self._run = run_command

    def extract_span(self, source: Path, target: Path, start: float, end: float) -> None:
        try:
            self._run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-i", str(source), "-t", str(end - start),
                       "-c", "copy", str(target)], capture_output=True, text=True, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise JobValidationError("ffmpeg failed to extract requested ASR span") from error

    def runtime_metadata(self) -> dict[str, str]:
        return {
            "execution_mode": _LOCAL_EXECUTION_MODE,
            "ffmpeg": _command_version("ffmpeg"),
            "ffprobe": _command_version("ffprobe"),
        }


def _segment_to_record(index: int, segment: Any) -> dict[str, object]:
    record: dict[str, object] = {"id": getattr(segment, "id", index), "start": getattr(segment, "start", None),
                                 "end": getattr(segment, "end", None), "text": getattr(segment, "text", None)}
    for name in ("avg_logprob", "compression_ratio", "no_speech_prob"):
        value = getattr(segment, name, None)
        if value is not None:
            record[name] = value
    words = getattr(segment, "words", None)
    if words is not None:
        record["words"] = [{key: getattr(word, key) for key in ("start", "end", "word", "probability") if getattr(word, key, None) is not None} for word in words]
    return record


def _atomic_text(path: Path, text: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _jsonl(records: list[dict[str, object]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for record in records)


def _strict_json_number(token: str, kind: str) -> _JsonNumber:
    try:
        value: int | float = int(token) if kind == "integer" else float(token)
    except (OverflowError, ValueError) as error:
        raise _StrictJsonParseError("JSON number is unreadable") from error
    if not math.isfinite(value):
        raise _StrictJsonParseError("JSON number must be finite")
    return _JsonNumber(token, kind, value)


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonParseError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise _StrictJsonParseError(f"non-finite JSON constant: {value}")


def _strict_json_loads(text: str) -> object:
    """Decode untrusted ASR evidence without losing duplicate keys or numeric spelling."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_int=lambda token: _strict_json_number(token, "integer"),
            parse_float=lambda token: _strict_json_number(token, "float"),
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, _StrictJsonParseError, OverflowError, ValueError) as error:
        raise _StrictJsonParseError("JSON evidence is unreadable") from error


def _normalise_json_value(value: object) -> object:
    """Drop private parser annotations only after lexical validation succeeds."""
    if isinstance(value, _JsonNumber):
        return value.value
    if isinstance(value, dict):
        return {key: _normalise_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_json_value(item) for item in value]
    return value


def _json_integer(value: object, label: str) -> int:
    if isinstance(value, _JsonNumber):
        if value.kind != "integer" or type(value.value) is not int:
            raise JobValidationError(f"ASR {label} must be an integer")
        return value.value
    if type(value) is not int:
        raise JobValidationError(f"ASR {label} must be an integer")
    return value


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, _JsonNumber):
        if value.kind not in {"integer", "float"} or type(value.value) not in {int, float}:
            raise JobValidationError(f"ASR {label} must be a finite number")
        candidate = value.value
    else:
        candidate = value
    if isinstance(candidate, bool) or type(candidate) not in {int, float} or not math.isfinite(candidate):
        raise JobValidationError(f"ASR {label} must be a finite number")
    return float(candidate)


def _validate_runtime(runtime: object, required_keys: set[str], label: str) -> dict[str, str]:
    if not isinstance(runtime, dict) or not required_keys.issubset(runtime):
        raise JobValidationError(f"{label} runtime metadata is incomplete")
    if any(not isinstance(key, str) or not isinstance(value, str) or not value.strip() for key, value in runtime.items()):
        raise JobValidationError(f"{label} runtime metadata must have non-empty strings")
    return dict(runtime)


def _validate_media_provenance(runtime: object) -> dict[str, str]:
    if not isinstance(runtime, dict) or set(runtime) != _REQUIRED_MEDIA_RUNTIME_KEYS:
        raise JobValidationError("media runtime metadata must use exactly the fixed local fields")
    validated = _validate_runtime(runtime, _REQUIRED_MEDIA_RUNTIME_KEYS, "media")
    if validated["execution_mode"] != _LOCAL_EXECUTION_MODE:
        raise JobValidationError("media runtime provenance must record local execution")
    return validated


def _validate_local_snapshot_identity(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JobValidationError("ASR model snapshot identity is missing")
    snapshot = value.strip()
    windows = PureWindowsPath(snapshot)
    posix = PurePosixPath(snapshot)
    is_windows_drive_path = bool(re.match(r"^[A-Za-z]:[\\/]", snapshot))
    has_uri_scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", snapshot) is not None
    if (snapshot.startswith(("//", "\\\\")) or "//" in snapshot[:8]
            or (has_uri_scheme and not is_windows_drive_path)
            or not (windows.is_absolute() or posix.is_absolute())):
        raise JobValidationError("ASR model snapshot identity must be an absolute local non-URI path")
    return snapshot


def _validate_asr_provenance(runtime: object) -> dict[str, str]:
    if not isinstance(runtime, dict) or set(runtime) != _ASR_RUNTIME_KEYS:
        raise JobValidationError("ASR runtime metadata must use exactly the fixed local fields")
    validated = _validate_runtime(runtime, _ASR_RUNTIME_KEYS, "ASR")
    if validated["execution_mode"] != _LOCAL_EXECUTION_MODE:
        raise JobValidationError("ASR runtime provenance must record local execution")
    if validated["faster_whisper"] != _PINNED_FASTER_WHISPER_VERSION:
        raise JobValidationError("ASR runtime provenance must record faster-whisper 1.2.1")
    validated["model_snapshot"] = _validate_local_snapshot_identity(validated["model_snapshot"])
    return validated


def _validate_record(record: object, previous_start: float | None = None) -> dict[str, object]:
    if not isinstance(record, dict) or not isinstance(record.get("text"), str):
        raise JobValidationError("raw ASR JSONL segment is malformed")
    identifier = _json_integer(record.get("id"), "segment ID")
    if identifier < 0:
        raise JobValidationError("raw ASR JSONL segment is malformed")
    start, end = _finite_number(record.get("start"), "segment start"), _finite_number(record.get("end"), "segment end")
    if start < 0 or end < start:
        raise JobValidationError("raw ASR JSONL segment bounds are invalid")
    if previous_start is not None and start < previous_start:
        raise JobValidationError("raw ASR JSONL segments are out of order")
    for name in ("avg_logprob", "compression_ratio", "no_speech_prob"):
        if name in record:
            _finite_number(record[name], name)
    if "words" in record:
        if not isinstance(record["words"], list):
            raise JobValidationError("raw ASR words must be a list")
        for word in record["words"]:
            if not isinstance(word, dict) or not isinstance(word.get("word"), str):
                raise JobValidationError("raw ASR word timestamp is malformed")
            word_start, word_end = _finite_number(word.get("start"), "word start"), _finite_number(word.get("end"), "word end")
            if word_start < start or word_end < word_start or word_end > end:
                raise JobValidationError("raw ASR word timestamp is outside its segment")
            if "probability" in word:
                _finite_number(word["probability"], "word probability")
    normalised = _normalise_json_value(record)
    if not isinstance(normalised, dict):  # Defensive: record was already checked as an object above.
        raise JobValidationError("raw ASR JSONL segment is malformed")
    normalised["id"] = identifier
    return normalised


def _validate_sequence(records: list[dict[str, object]], duration: float) -> list[dict[str, object]]:
    validated: list[dict[str, object]] = []
    previous_start: float | None = None
    for record in records:
        candidate = _validate_record(record, previous_start)
        if float(candidate["end"]) > duration:
            raise JobValidationError("raw ASR segment extends beyond measured source duration")
        previous_start = float(candidate["start"])
        validated.append(candidate)
    return validated


def _metadata_text(metadata: dict[str, object]) -> str:
    return json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _metadata_from_text(text: str, label: str) -> dict[str, object]:
    try:
        value = _strict_json_loads(text)
    except _StrictJsonParseError as error:
        raise ArtifactValidationError(f"{label} metadata is unreadable") from error
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{label} metadata must be an object")
    return value


def _read_metadata(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ArtifactValidationError("full ASR metadata is unreadable") from error
    return _metadata_from_text(text, "full ASR")


def _matches_fixed_json_value(value: object, expected: object) -> bool:
    """Compare the JSON kind and value, without Python's bool/number aliases."""
    if type(expected) is bool:
        return type(value) is bool and value == expected
    if type(expected) is int:
        return ((type(value) is int or (isinstance(value, _JsonNumber) and value.kind == "integer"))
                and _json_integer(value, "fixed configuration value") == expected)
    if type(expected) is float:
        if isinstance(value, _JsonNumber):
            return value.kind == "float" and type(value.value) is float and value.value == expected
        return type(value) is float and value == expected
    if type(expected) is str:
        return type(value) is str and value == expected
    if expected is None:
        return value is None
    if type(expected) is list:
        return (isinstance(value, list) and len(value) == len(expected)
                and all(_matches_fixed_json_value(item, reference) for item, reference in zip(value, expected)))
    if type(expected) is dict:
        return (isinstance(value, dict) and set(value) == set(expected)
                and all(_matches_fixed_json_value(value[key], reference) for key, reference in expected.items()))
    return False


def _validate_fixed_configuration(configuration: object, label: str) -> None:
    if not _matches_fixed_json_value(configuration, DEFAULT_ASR_CONFIGURATION):
        raise JobValidationError(f"{label} metadata does not use the fixed local configuration")


def _canonical_span_lexeme(value: float) -> str:
    return json.dumps(value, allow_nan=False)


def _validate_canonical_span_value(value: object, expected: float, label: str) -> float:
    if not isinstance(value, _JsonNumber) or value.kind != "float" or type(value.value) is not float:
        raise JobValidationError(f"{label} must use a canonical decimal span bound")
    if not math.isfinite(value.value) or value.lexeme != _canonical_span_lexeme(expected):
        raise JobValidationError(f"{label} must use a canonical decimal span bound")
    return value.value


def _validate_exact_context(value: object, expected: dict[str, object], kind: str) -> None:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ArtifactValidationError("publication recovery intent does not match this operation")
    if kind == "rerun":
        for key in ("start_seconds", "end_seconds"):
            try:
                _validate_canonical_span_value(value.get(key), float(expected[key]), f"publication {key}")
            except (KeyError, JobValidationError) as error:
                raise ArtifactValidationError("publication recovery intent does not match this operation") from error
        return
    if not _matches_fixed_json_value(value, expected):
        raise ArtifactValidationError("publication recovery intent does not match this operation")


def _validate_full_metadata(metadata: dict[str, object], state: dict[str, Any], label: str) -> None:
    if set(metadata) != _FULL_ASR_METADATA_KEYS:
        raise ArtifactValidationError(f"{label} metadata must use exactly the fixed local fields")
    if metadata.get("source_sha256") != state["source_sha256"]:
        raise ArtifactValidationError(f"{label} metadata is not source-bound")
    try:
        _validate_fixed_configuration(metadata.get("configuration"), label)
        _validate_asr_provenance(metadata.get("runtime"))
    except JobValidationError as error:
        raise ArtifactValidationError(str(error)) from error


def _validate_rerun_metadata(
    metadata: dict[str, object], state: dict[str, Any], start: float, end: float, label: str
) -> None:
    if set(metadata) != _RERUN_METADATA_KEYS:
        raise ArtifactValidationError(f"{label} metadata must use exactly the fixed rerun fields")
    try:
        metadata_start = _validate_canonical_span_value(metadata.get("start_seconds"), start, f"{label} metadata start")
        metadata_end = _validate_canonical_span_value(metadata.get("end_seconds"), end, f"{label} metadata end")
        _validate_fixed_configuration(metadata.get("configuration"), label)
    except JobValidationError as error:
        raise ArtifactValidationError(f"{label} metadata has invalid rerun bounds") from error
    if (metadata.get("source_sha256") != state["source_sha256"]
            or metadata_start != start or metadata_end != end):
        raise ArtifactValidationError(f"{label} metadata is not bound to this source and span")
    try:
        _validate_asr_provenance(metadata.get("runtime"))
        _validate_media_provenance(metadata.get("media_runtime"))
    except JobValidationError as error:
        raise ArtifactValidationError(str(error)) from error


def validate_primary_asr_evidence(store: JobStore, job_id: str) -> list[dict[str, object]]:
    """Validate current, persisted primary ASR evidence without advancing a stage."""
    state = store.load_job(job_id)
    try:
        store.validate_source(job_id)
        raw_path = store.validate_artifact(job_id, "asr/full.jsonl")
        metadata_path = store.validate_artifact(job_id, "asr/metadata.json")
        asr = state.get("asr")
        if not isinstance(asr, dict):
            raise ArtifactValidationError("job has no bound full ASR provenance")
        _validate_full_metadata(asr, state, "full ASR provenance")
        metadata = _read_metadata(metadata_path)
        _validate_full_metadata(metadata, state, "full ASR")
        normalised_metadata = _normalise_json_value(metadata)
        if not isinstance(normalised_metadata, dict) or normalised_metadata != asr:
            raise ArtifactValidationError("full ASR metadata does not match bound provenance")
        duration = _finite_number(state["source"]["duration_seconds"], "source duration")
        return _validate_sequence(_read_raw_segments(raw_path), duration)
    except ArtifactValidationError:
        raise
    except JobValidationError as error:
        raise ArtifactValidationError("full ASR evidence is semantically invalid") from error


def validate_asr_completion(store: JobStore, job_id: str) -> None:
    state = store.load_job(job_id)
    if state["stage"] != "source_ready":
        raise StageTransitionError("ASR completion requires a source_ready job")
    validate_primary_asr_evidence(store, job_id)


def validate_inspection_evidence(store: JobStore, job_id: str) -> None:
    state = store.load_job(job_id)
    records = validate_primary_asr_evidence(store, job_id)
    try:
        report_json = store.validate_artifact(job_id, "inspection/report.json")
        report_markdown = store.validate_artifact(job_id, "inspection/report.md")
        duration = _finite_number(state["source"]["duration_seconds"], "source duration")
        report = _inspection_report(records, duration)
        expected_json = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
        expected_markdown = _inspection_markdown(report)
        if report_json.read_bytes() != expected_json.encode("utf-8"):
            raise ArtifactValidationError("inspection JSON is not the current deterministic ASR inspection")
        if report_markdown.read_bytes() != expected_markdown.encode("utf-8"):
            raise ArtifactValidationError("inspection Markdown is not the current deterministic ASR inspection")
    except ArtifactValidationError:
        raise
    except (OSError, JobValidationError) as error:
        raise ArtifactValidationError("inspection evidence is semantically invalid") from error


def validate_inspection_completion(store: JobStore, job_id: str) -> None:
    state = store.load_job(job_id)
    if state["stage"] != "asr_ready":
        raise StageTransitionError("inspection completion requires an asr_ready job")
    validate_inspection_evidence(store, job_id)


def _sha256_bytes(value: bytes) -> str:
    import hashlib
    return hashlib.sha256(value).hexdigest()


def _publication_intent(
    kind: str,
    source_sha256: str,
    output_bytes: dict[str, bytes],
    context: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": kind,
        "source_sha256": source_sha256,
        "context": context,
        "outputs": {
            relative: {
                "sha256": _sha256_bytes(value),
                "byte_size": len(value),
                "payload_base64": base64.b64encode(value).decode("ascii"),
            }
            for relative, value in sorted(output_bytes.items())
        },
    }


def _publication_intent_text(intent: dict[str, object]) -> str:
    return json.dumps(intent, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _load_publication_intent(
    store: JobStore,
    job_id: str,
    relative_path: str,
    kind: str,
    source_sha256: str,
    output_paths: dict[str, Path],
    context: dict[str, object],
) -> dict[str, bytes] | None:
    path = store.validate_output_path(job_id, relative_path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ArtifactValidationError("publication recovery intent is unreadable") from error
    try:
        value = _strict_json_loads(text)
    except _StrictJsonParseError as error:
        raise ArtifactValidationError("publication recovery intent is unreadable") from error
    if not isinstance(value, dict) or set(value) != {"schema_version", "kind", "source_sha256", "context", "outputs"}:
        raise ArtifactValidationError("publication recovery intent is malformed")
    schema_version = value.get("schema_version")
    if isinstance(schema_version, _JsonNumber) and schema_version.kind == "integer" and schema_version.value == 1:
        raise ArtifactValidationError("legacy publication recovery intent lacks retained candidate payloads")
    try:
        valid_schema_version = _json_integer(schema_version, "publication schema version") == 2
    except JobValidationError as error:
        raise ArtifactValidationError("publication recovery intent is not source-bound to this operation") from error
    if (not valid_schema_version or type(value.get("kind")) is not str or value["kind"] != kind
            or type(value.get("source_sha256")) is not str or value["source_sha256"] != source_sha256):
        raise ArtifactValidationError("publication recovery intent is not source-bound to this operation")
    _validate_exact_context(value.get("context"), context, kind)
    if not isinstance(value.get("outputs"), dict):
        raise ArtifactValidationError("publication recovery intent does not match this operation")
    outputs = value["outputs"]
    if set(outputs) != set(output_paths):
        raise ArtifactValidationError("publication recovery intent has unexpected output paths")
    payloads: dict[str, bytes] = {}
    for relative, record in outputs.items():
        if (not isinstance(record, dict) or set(record) != {"sha256", "byte_size", "payload_base64"}
                or not isinstance(record.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
                or not isinstance(record.get("payload_base64"), str)):
            raise ArtifactValidationError("publication recovery intent has invalid output records")
        try:
            byte_size = _json_integer(record.get("byte_size"), "publication output byte size")
        except JobValidationError as error:
            raise ArtifactValidationError("publication recovery intent has invalid output records") from error
        if byte_size < 0:
            raise ArtifactValidationError("publication recovery intent has invalid output records")
        try:
            payload = base64.b64decode(record["payload_base64"].encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as error:
            raise ArtifactValidationError("publication recovery intent has malformed retained candidate payloads") from error
        if _sha256_bytes(payload) != record["sha256"] or len(payload) != byte_size:
            raise ArtifactValidationError("publication recovery intent retained candidate payload does not match its binding")
        payloads[relative] = payload
    return payloads


def _existing_outputs_match_intent(
    store: JobStore,
    job_id: str,
    output_paths: dict[str, Path],
    payloads: dict[str, bytes],
) -> bool:
    complete = True
    for relative in output_paths:
        path = store.validate_output_path(job_id, relative)
        if not path.exists():
            complete = False
            continue
        try:
            value = path.read_bytes()
        except OSError as error:
            raise ArtifactValidationError("recoverable publication output is unreadable") from error
        if value != payloads[relative]:
            raise ArtifactValidationError("recoverable publication output differs from its source-bound intent")
    return complete


def _candidate_text(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ArtifactValidationError("publication recovery candidate payload is not valid UTF-8 evidence") from error


def _has_existing_output(store: JobStore, job_id: str, output_paths: dict[str, Path]) -> bool:
    return any(store.validate_output_path(job_id, relative).exists() for relative in output_paths)


def _publish_recoverable_outputs(
    store: JobStore,
    job_id: str,
    intent_relative: str,
    kind: str,
    source_sha256: str,
    output_paths: dict[str, Path],
    output_bytes: dict[str, bytes] | None,
    context: dict[str, object],
    preflight: Callable[[dict[str, bytes]], Any],
) -> Any:
    """Publish missing outputs from a durable exact candidate, never a regenerated retry."""
    store.validate_source(job_id)
    payloads = _load_publication_intent(
        store, job_id, intent_relative, kind, source_sha256, output_paths, context
    )
    if payloads is None:
        if output_bytes is None:
            raise ArtifactValidationError("publication recovery intent is missing its retained candidate payloads")
        if set(output_bytes) != set(output_paths):
            raise ArtifactValidationError("publication candidate does not define exactly the requested outputs")
        for relative in output_paths:
            if store.validate_output_path(job_id, relative).exists():
                raise ArtifactValidationError("publication output exists without a recoverable source-bound intent")
        intent_path = store.validate_output_path(job_id, intent_relative)
        _atomic_text(intent_path, _publication_intent_text(
            _publication_intent(kind, source_sha256, output_bytes, context)
        ))
        payloads = dict(output_bytes)
    elif output_bytes is not None:
        raise ArtifactValidationError("publication retry must use its retained candidate payloads")

    # Candidate bytes must be semantically valid before any immutable final is created.
    semantic_evidence = preflight(payloads)
    store.validate_source(job_id)
    _existing_outputs_match_intent(store, job_id, output_paths, payloads)
    for relative in output_paths:
        store.validate_source(job_id)
        path = store.validate_output_path(job_id, relative)
        if path.exists():
            continue
        _atomic_text(path, _candidate_text(payloads[relative]))
    return semantic_evidence


def _clear_publication_intent(store: JobStore, job_id: str, relative_path: str) -> None:
    path = store.validate_output_path(job_id, relative_path)
    if path.exists():
        path.unlink()


def _validate_full_candidate_payloads(
    state: dict[str, Any],
    payloads: dict[str, bytes],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        metadata = _metadata_from_text(
            _candidate_text(payloads["asr/metadata.json"]), "recoverable full ASR"
        )
        _validate_full_metadata(metadata, state, "recoverable full ASR")
        duration = _finite_number(state["source"]["duration_seconds"], "source duration")
        records = _validate_sequence(
            _parse_raw_segments_text(_candidate_text(payloads["asr/full.jsonl"])), duration
        )
        normalised_metadata = _normalise_json_value(metadata)
        if not isinstance(normalised_metadata, dict):
            raise ArtifactValidationError("recoverable full ASR metadata is malformed")
        return normalised_metadata, records
    except KeyError as error:
        raise ArtifactValidationError("recoverable full ASR candidate is missing a required payload") from error
    except ArtifactValidationError:
        raise
    except JobValidationError as error:
        raise ArtifactValidationError("recoverable full ASR output is semantically invalid") from error


def _validate_rerun_candidate_payloads(
    state: dict[str, Any],
    output_relatives: tuple[str, str],
    payloads: dict[str, bytes],
    start: float,
    end: float,
) -> None:
    metadata_relative = next(relative for relative in output_relatives if relative.endswith(".metadata.json"))
    jsonl_relative = next(
        relative for relative in output_relatives if relative.endswith(".jsonl") and not relative.endswith(".metadata.json")
    )
    try:
        metadata = _metadata_from_text(
            _candidate_text(payloads[metadata_relative]), "recoverable rerun"
        )
        _validate_rerun_metadata(metadata, state, start, end, "recoverable rerun")
        _validate_sequence(_parse_raw_segments_text(_candidate_text(payloads[jsonl_relative])), end - start)
    except KeyError as error:
        raise ArtifactValidationError("recoverable rerun candidate is missing a required payload") from error
    except ArtifactValidationError:
        raise
    except JobValidationError as error:
        raise ArtifactValidationError("recoverable rerun output is semantically invalid") from error


def _validate_inspection_candidate_payloads(
    store: JobStore,
    job_id: str,
    state: dict[str, Any],
    payloads: dict[str, bytes],
) -> None:
    try:
        records = validate_primary_asr_evidence(store, job_id)
        duration = _finite_number(state["source"]["duration_seconds"], "source duration")
        report = _inspection_report(records, duration)
        expected_json = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        expected_markdown = _inspection_markdown(report).encode("utf-8")
        if payloads.get("inspection/report.json") != expected_json:
            raise ArtifactValidationError("recoverable inspection JSON is not deterministic current evidence")
        if payloads.get("inspection/report.md") != expected_markdown:
            raise ArtifactValidationError("recoverable inspection Markdown is not deterministic current evidence")
    except ArtifactValidationError:
        raise
    except (OSError, JobValidationError) as error:
        raise ArtifactValidationError("recoverable inspection output is semantically invalid") from error


def _span_component(value: float) -> str:
    """A valid finite float has one lossless canonical hexadecimal representation."""
    if value == 0:
        value = 0.0
    return value.hex().replace("-", "neg").replace("+", "plus")


class ASRService:
    def __init__(self, store: JobStore, model_adapter: ASRAdapter, media_adapter: MediaAdapter | None = None) -> None:
        self.store, self.model_adapter, self.media_adapter = store, model_adapter, media_adapter

    def transcribe(self, job_id: str) -> dict[str, Any]:
        output_relatives = ("asr/full.jsonl", "asr/metadata.json")
        intent_relative = "asr/.full-publication.json"
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] != "source_ready":
                raise StageTransitionError("full ASR requires a source_ready job")
            source = self.store.validate_source(job_id)
            duration = _finite_number(state["source"]["duration_seconds"], "source duration")
            output_paths = {relative: self.store.validate_output_path(job_id, relative) for relative in output_relatives}
            intent_records = _load_publication_intent(
                self.store, job_id, intent_relative, "full_asr", state["source_sha256"], output_paths, {}
            )
            registered = {relative for relative in output_relatives if relative in state["artifacts"]}
            candidate_is_published = registered == set(output_relatives) and isinstance(state.get("asr"), dict)
            if candidate_is_published:
                if intent_records is not None and not _existing_outputs_match_intent(
                    self.store, job_id, output_paths, intent_records
                ):
                    raise ArtifactValidationError("published full ASR candidate is incomplete")
            else:
                if registered:
                    raise ArtifactValidationError("partial registered full ASR evidence is not recoverable")
                if intent_records is not None:
                    metadata, _records = _publish_recoverable_outputs(
                        self.store, job_id, intent_relative, "full_asr", state["source_sha256"], output_paths,
                        None, {}, lambda payloads: _validate_full_candidate_payloads(state, payloads),
                    )
                else:
                    if _has_existing_output(self.store, job_id, output_paths):
                        raise ArtifactValidationError("full ASR evidence exists without a recoverable source-bound intent")
                    records = _validate_sequence(
                        self.model_adapter.transcribe(source, dict(DEFAULT_ASR_CONFIGURATION)), duration
                    )
                    self.store.validate_source(job_id)
                    runtime = _validate_asr_provenance(self.model_adapter.runtime_metadata())
                    self.store.validate_source(job_id)
                    metadata = {
                        "source_sha256": state["source_sha256"],
                        "configuration": dict(DEFAULT_ASR_CONFIGURATION),
                        "runtime": dict(runtime),
                    }
                    output_bytes = {
                        "asr/full.jsonl": _jsonl(records).encode("utf-8"),
                        "asr/metadata.json": _metadata_text(metadata).encode("utf-8"),
                    }
                    metadata, _records = _publish_recoverable_outputs(
                        self.store, job_id, intent_relative, "full_asr", state["source_sha256"], output_paths,
                        output_bytes, {}, lambda payloads: _validate_full_candidate_payloads(state, payloads),
                    )
                for relative in output_relatives:
                    transaction.register_artifact(relative)
                transaction.record_asr_metadata(metadata)
        with self.store.transaction(job_id) as transaction:
            transaction.complete_asr()
        _clear_publication_intent(self.store, job_id, intent_relative)
        return self.store.load_job(job_id)

    def rerun_span(self, job_id: str, start: float, end: float) -> dict[str, Path]:
        if self.media_adapter is None:
            raise JobValidationError("a media adapter is required for a targeted ASR rerun")
        start_value, end_value = _finite_number(start, "rerun start"), _finite_number(end, "rerun end")
        start_value = 0.0 if start_value == 0 else start_value
        end_value = 0.0 if end_value == 0 else end_value
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] not in {"asr_ready", "inspected", "reviewed", "draft_ready", "handed_off"}:
                raise StageTransitionError("targeted ASR rerun requires an asr_ready or later job")
            duration = _finite_number(state["source"]["duration_seconds"], "source duration")
            if start_value < 0 or end_value <= start_value or end_value > duration:
                raise JobValidationError("rerun span must be ordered and inside measured source duration")
            source, root = self.store.validate_source(job_id), self.store.job_root(job_id)
            self._validate_primary_asr_evidence(job_id, state)
            stem = f"span-{_span_component(start_value)}-{_span_component(end_value)}"
            jsonl_path, metadata_path = root / "asr" / "reruns" / f"{stem}.jsonl", root / "asr" / "reruns" / f"{stem}.metadata.json"
            output_relatives = (f"asr/reruns/{jsonl_path.name}", f"asr/reruns/{metadata_path.name}")
            intent_relative = f"asr/reruns/.{stem}.publication.json"
            output_paths = {relative: self.store.validate_output_path(job_id, relative) for relative in output_relatives}
            context = {"start_seconds": start_value, "end_seconds": end_value}
            intent_records = _load_publication_intent(
                self.store, job_id, intent_relative, "rerun", state["source_sha256"], output_paths, context
            )
            registered = {relative for relative in output_relatives if relative in state["artifacts"]}
            if registered == set(output_relatives):
                raise ArtifactValidationError("deterministic rerun evidence already exists and is immutable")
            if registered:
                raise ArtifactValidationError("partial registered rerun evidence is not recoverable")
            if intent_records is not None:
                _publish_recoverable_outputs(
                    self.store, job_id, intent_relative, "rerun", state["source_sha256"], output_paths,
                    None, context,
                    lambda payloads: _validate_rerun_candidate_payloads(
                        state, output_relatives, payloads, start_value, end_value
                    ),
                )
            else:
                if _has_existing_output(self.store, job_id, output_paths):
                    raise ArtifactValidationError("rerun evidence exists without a recoverable source-bound intent")
                temporary_relative = f"asr/reruns/.{stem}.media.mka"
                temporary = self.store.validate_output_path(job_id, temporary_relative)
                if temporary.exists():
                    raise ArtifactValidationError("deterministic rerun media staging already exists")
                media_runtime = _validate_media_provenance(self.media_adapter.runtime_metadata())
                try:
                    self.media_adapter.extract_span(source, temporary, start_value, end_value)
                    temporary = self.store.validate_output_path(job_id, temporary_relative)
                    if not temporary.is_file():
                        raise ArtifactValidationError("media adapter did not produce a requested span")
                    records = _validate_sequence(
                        self.model_adapter.transcribe(temporary, dict(DEFAULT_ASR_CONFIGURATION)), end_value - start_value
                    )
                finally:
                    try:
                        safe_temporary = self.store.validate_output_path(job_id, temporary_relative)
                        if safe_temporary.exists():
                            safe_temporary.unlink()
                    except FileNotFoundError:
                        pass
                runtime = _validate_asr_provenance(self.model_adapter.runtime_metadata())
                self.store.validate_source(job_id)
                self._validate_primary_asr_evidence(job_id, state)
                metadata = {
                    "source_sha256": state["source_sha256"], "start_seconds": start_value, "end_seconds": end_value,
                    "configuration": dict(DEFAULT_ASR_CONFIGURATION), "runtime": runtime, "media_runtime": media_runtime,
                }
                output_bytes = {
                    output_relatives[0]: _jsonl(records).encode("utf-8"),
                    output_relatives[1]: _metadata_text(metadata).encode("utf-8"),
                }
                _publish_recoverable_outputs(
                    self.store, job_id, intent_relative, "rerun", state["source_sha256"], output_paths,
                    output_bytes, context,
                    lambda payloads: _validate_rerun_candidate_payloads(
                        state, output_relatives, payloads, start_value, end_value
                    ),
                )
            for relative in output_relatives:
                transaction.register_artifact(relative)
        _clear_publication_intent(self.store, job_id, intent_relative)
        return {"jsonl_path": jsonl_path, "metadata_path": metadata_path}

    def inspect(self, job_id: str) -> dict[str, Any]:
        output_relatives = ("inspection/report.json", "inspection/report.md")
        intent_relative = "inspection/.publication.json"
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] != "asr_ready":
                raise StageTransitionError("inspection requires an asr_ready job")
            self.store.validate_source(job_id)
            self._validate_primary_asr_evidence(job_id, state)
            raw_path = self.store.validate_artifact(job_id, "asr/full.jsonl")
            self.store.validate_artifact(job_id, "asr/metadata.json")
            records = _read_raw_segments(raw_path)
            report = _inspection_report(records, _finite_number(state["source"]["duration_seconds"], "source duration"))
            output_paths = {relative: self.store.validate_output_path(job_id, relative) for relative in output_relatives}
            intent_records = _load_publication_intent(
                self.store, job_id, intent_relative, "inspection", state["source_sha256"], output_paths,
                {"full_asr_sha256": state["artifacts"]["asr/full.jsonl"]["sha256"]},
            )
            registered = {relative for relative in output_relatives if relative in state["artifacts"]}
            candidate_is_published = registered == set(output_relatives)
            if candidate_is_published:
                if intent_records is not None and not _existing_outputs_match_intent(
                    self.store, job_id, output_paths, intent_records
                ):
                    raise ArtifactValidationError("published inspection candidate is incomplete")
            else:
                if registered:
                    raise ArtifactValidationError("partial registered inspection evidence is not recoverable")
                if intent_records is not None:
                    _publish_recoverable_outputs(
                        self.store, job_id, intent_relative, "inspection", state["source_sha256"], output_paths,
                        None, {"full_asr_sha256": state["artifacts"]["asr/full.jsonl"]["sha256"]},
                        lambda payloads: _validate_inspection_candidate_payloads(
                            self.store, job_id, state, payloads
                        ),
                    )
                else:
                    if _has_existing_output(self.store, job_id, output_paths):
                        raise ArtifactValidationError("inspection evidence exists without a recoverable source-bound intent")
                    self.store.validate_source(job_id)
                    self._validate_primary_asr_evidence(job_id, state)
                    output_bytes = {
                        "inspection/report.json": (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
                        "inspection/report.md": _inspection_markdown(report).encode("utf-8"),
                    }
                    _publish_recoverable_outputs(
                        self.store, job_id, intent_relative, "inspection", state["source_sha256"], output_paths,
                        output_bytes, {"full_asr_sha256": state["artifacts"]["asr/full.jsonl"]["sha256"]},
                        lambda payloads: _validate_inspection_candidate_payloads(
                            self.store, job_id, state, payloads
                        ),
                    )
                for relative in output_relatives:
                    transaction.register_artifact(relative)
        with self.store.transaction(job_id) as transaction:
            transaction.complete_inspection()
        _clear_publication_intent(self.store, job_id, intent_relative)
        return self.store.load_job(job_id)

    def _validate_primary_asr_evidence(self, job_id: str, state: dict[str, Any]) -> None:
        del state
        validate_primary_asr_evidence(self.store, job_id)


def _parse_raw_segments_text(text: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    previous_start: float | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise JobValidationError(f"raw ASR JSONL has a blank line at {line_number}")
        try:
            parsed = _strict_json_loads(line)
        except _StrictJsonParseError as error:
            raise JobValidationError(f"raw ASR JSONL is malformed at line {line_number}") from error
        record = _validate_record(parsed, previous_start)
        previous_start = float(record["start"])
        records.append(record)
    return records


def _read_raw_segments(path: Path) -> list[dict[str, object]]:
    return _parse_raw_segments_text(path.read_text(encoding="utf-8"))


def _inspection_report(records: list[dict[str, object]], duration: float) -> dict[str, object]:
    intervals: list[tuple[float, float]] = []
    confidence: list[dict[str, object]] = []
    patterns: list[dict[str, object]] = []
    repeats: dict[str, list[int]] = {}
    for record in records:
        start, end = float(record["start"]), float(record["end"])
        if end > duration:
            raise JobValidationError("raw ASR segment extends beyond measured source duration")
        intervals.append((start, end))
        identifier = record["id"]
        if "avg_logprob" in record and float(record["avg_logprob"]) < -1.0:
            confidence.append({"id": identifier, "reason": "low_avg_logprob", "value": record["avg_logprob"]})
        if "no_speech_prob" in record and float(record["no_speech_prob"]) > 0.6:
            patterns.append({"id": identifier, "reason": "high_no_speech_prob", "value": record["no_speech_prob"]})
        if "compression_ratio" in record and float(record["compression_ratio"]) > 2.4:
            patterns.append({"id": identifier, "reason": "high_compression_ratio", "value": record["compression_ratio"]})
        normalized = re.sub(r"[^\w]+", " ", record["text"].lower()).strip()
        if normalized:
            repeats.setdefault(normalized, []).append(identifier)
    return {"segment_count": len(records), "source_duration_seconds": duration,
            "segment_duration_seconds": sum(end - start for start, end in intervals),
            "confidence_outliers": confidence, "suspicious_decoder_patterns": patterns,
            "normalized_repeated_segments": [{"normalized_text": text, "segment_ids": identifiers} for text, identifiers in repeats.items() if len(identifiers) > 1],
            "asr_uncovered_intervals": [{"start": start, "end": end} for start, end in _uncovered_intervals(intervals, duration)]}


def _uncovered_intervals(intervals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    cursor, gaps = 0.0, []
    for start, end in intervals:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        gaps.append((cursor, duration))
    return gaps


def _inspection_markdown(report: dict[str, object]) -> str:
    gaps = report["asr_uncovered_intervals"]
    lines = ["# ASR inspection", "", f"Segments: {report['segment_count']}", "", "## ASR-uncovered intervals", "",
             "These intervals are ASR-uncovered; they are not inferred silence and require listening review.", ""]
    lines.extend(f"- {gap['start']:.3f}s to {gap['end']:.3f}s" for gap in gaps) if gaps else lines.append("- None")  # type: ignore[index]
    lines.extend(["", "Reference text is not used to fill ASR-uncovered intervals.", ""])
    return "\n".join(lines)
