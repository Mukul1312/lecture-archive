"""Local, evidence-preserving ASR and ASR-uncovered inspection."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
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
_REQUIRED_RUNTIME_KEYS = {"model_snapshot", "faster_whisper", "python", "ffmpeg", "ffprobe"}
_REQUIRED_MEDIA_RUNTIME_KEYS = {"ffmpeg", "ffprobe"}


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
        return {"model_snapshot": str(snapshot), "faster_whisper": version, "python": sys.version.split()[0],
                "ffmpeg": _command_version("ffmpeg"), "ffprobe": _command_version("ffprobe")}

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
        return {"ffmpeg": _command_version("ffmpeg"), "ffprobe": _command_version("ffprobe")}


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


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise JobValidationError(f"ASR {label} must be a finite number")
    return float(value)


def _validate_runtime(runtime: object, required_keys: set[str], label: str) -> dict[str, str]:
    if not isinstance(runtime, dict) or not required_keys.issubset(runtime):
        raise JobValidationError(f"{label} runtime metadata is incomplete")
    if any(not isinstance(key, str) or not isinstance(value, str) or not value.strip() for key, value in runtime.items()):
        raise JobValidationError(f"{label} runtime metadata must have non-empty strings")
    return dict(runtime)


def _validate_record(record: object, previous_start: float | None = None) -> dict[str, object]:
    if not isinstance(record, dict) or not isinstance(record.get("id"), int) or isinstance(record["id"], bool) or not isinstance(record.get("text"), str):
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
    return dict(record)


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


def _read_metadata(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactValidationError("full ASR metadata is unreadable") from error
    if not isinstance(value, dict):
        raise ArtifactValidationError("full ASR metadata must be an object")
    return value


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
        if asr.get("source_sha256") != state["source_sha256"]:
            raise ArtifactValidationError("full ASR provenance is not source-bound")
        if asr.get("configuration") != DEFAULT_ASR_CONFIGURATION:
            raise ArtifactValidationError("full ASR provenance does not use the fixed local configuration")
        _validate_runtime(asr.get("runtime"), _REQUIRED_RUNTIME_KEYS, "ASR")
        metadata = _read_metadata(metadata_path)
        if metadata != asr:
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
        "schema_version": 1,
        "kind": kind,
        "source_sha256": source_sha256,
        "context": context,
        "outputs": {
            relative: {"sha256": _sha256_bytes(value), "byte_size": len(value)}
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
) -> dict[str, dict[str, object]] | None:
    path = store.validate_output_path(job_id, relative_path)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactValidationError("publication recovery intent is unreadable") from error
    if not isinstance(value, dict) or set(value) != {"schema_version", "kind", "source_sha256", "context", "outputs"}:
        raise ArtifactValidationError("publication recovery intent is malformed")
    if value.get("schema_version") != 1 or value.get("kind") != kind or value.get("source_sha256") != source_sha256:
        raise ArtifactValidationError("publication recovery intent is not source-bound to this operation")
    if value.get("context") != context or not isinstance(value.get("outputs"), dict):
        raise ArtifactValidationError("publication recovery intent does not match this operation")
    outputs = value["outputs"]
    if set(outputs) != set(output_paths):
        raise ArtifactValidationError("publication recovery intent has unexpected output paths")
    records: dict[str, dict[str, object]] = {}
    for relative, record in outputs.items():
        if (not isinstance(record, dict) or set(record) != {"sha256", "byte_size"}
                or not isinstance(record.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
                or not isinstance(record.get("byte_size"), int) or isinstance(record["byte_size"], bool)
                or record["byte_size"] < 0):
            raise ArtifactValidationError("publication recovery intent has invalid output records")
        records[relative] = {"sha256": record["sha256"], "byte_size": record["byte_size"]}
    return records


def _existing_outputs_match_intent(output_paths: dict[str, Path], records: dict[str, dict[str, object]]) -> bool:
    complete = True
    for relative, path in output_paths.items():
        if not path.exists():
            complete = False
            continue
        try:
            value = path.read_bytes()
        except OSError as error:
            raise ArtifactValidationError("recoverable publication output is unreadable") from error
        expected = records[relative]
        if _sha256_bytes(value) != expected["sha256"] or len(value) != expected["byte_size"]:
            raise ArtifactValidationError("recoverable publication output differs from its source-bound intent")
    return complete


def _publish_recoverable_outputs(
    store: JobStore,
    job_id: str,
    intent_relative: str,
    kind: str,
    source_sha256: str,
    output_paths: dict[str, Path],
    output_bytes: dict[str, bytes],
    context: dict[str, object],
) -> None:
    """Publish only deterministic output bytes bound by a durable recovery intent."""
    intent = _publication_intent(kind, source_sha256, output_bytes, context)
    records = _load_publication_intent(
        store, job_id, intent_relative, kind, source_sha256, output_paths, context
    )
    if records is None:
        if any(path.exists() for path in output_paths.values()):
            raise ArtifactValidationError("publication output exists without a recoverable source-bound intent")
        store.validate_output_path(job_id, intent_relative)
        _atomic_text(store.job_root(job_id) / intent_relative, _publication_intent_text(intent))
        records = intent["outputs"]  # type: ignore[assignment]
    elif records != intent["outputs"]:
        raise ArtifactValidationError("publication retry does not reproduce its source-bound intent")
    _existing_outputs_match_intent(output_paths, records)
    for relative, path in output_paths.items():
        if path.exists():
            continue
        store.validate_output_path(job_id, relative)
        _atomic_text(path, output_bytes[relative].decode("utf-8"))


def _clear_publication_intent(store: JobStore, job_id: str, relative_path: str) -> None:
    path = store.validate_output_path(job_id, relative_path)
    if path.exists():
        path.unlink()


def _validate_full_candidate_payloads(
    state: dict[str, Any], output_paths: dict[str, Path]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        metadata = _read_metadata(output_paths["asr/metadata.json"])
        if metadata.get("source_sha256") != state["source_sha256"]:
            raise ArtifactValidationError("recoverable full ASR metadata is not source-bound")
        if metadata.get("configuration") != DEFAULT_ASR_CONFIGURATION:
            raise ArtifactValidationError("recoverable full ASR metadata does not use the fixed local configuration")
        _validate_runtime(metadata.get("runtime"), _REQUIRED_RUNTIME_KEYS, "ASR")
        duration = _finite_number(state["source"]["duration_seconds"], "source duration")
        records = _validate_sequence(_read_raw_segments(output_paths["asr/full.jsonl"]), duration)
        return metadata, records
    except ArtifactValidationError:
        raise
    except JobValidationError as error:
        raise ArtifactValidationError("recoverable full ASR output is semantically invalid") from error


def _validate_rerun_candidate_payloads(
    state: dict[str, Any],
    output_paths: dict[str, Path],
    start: float,
    end: float,
) -> None:
    metadata_path = next(path for relative, path in output_paths.items() if relative.endswith(".metadata.json"))
    jsonl_path = next(path for relative, path in output_paths.items() if relative.endswith(".jsonl") and not relative.endswith(".metadata.json"))
    try:
        metadata = _read_metadata(metadata_path)
        if (metadata.get("source_sha256") != state["source_sha256"]
                or metadata.get("start_seconds") != start or metadata.get("end_seconds") != end
                or metadata.get("configuration") != DEFAULT_ASR_CONFIGURATION):
            raise ArtifactValidationError("recoverable rerun metadata is not bound to this source and span")
        _validate_runtime(metadata.get("runtime"), _REQUIRED_RUNTIME_KEYS, "ASR")
        _validate_runtime(metadata.get("media_runtime"), _REQUIRED_MEDIA_RUNTIME_KEYS, "media")
        _validate_sequence(_read_raw_segments(jsonl_path), end - start)
    except ArtifactValidationError:
        raise
    except JobValidationError as error:
        raise ArtifactValidationError("recoverable rerun output is semantically invalid") from error


def _validate_inspection_candidate_payloads(
    store: JobStore,
    job_id: str,
    state: dict[str, Any],
    output_paths: dict[str, Path],
) -> None:
    try:
        records = validate_primary_asr_evidence(store, job_id)
        duration = _finite_number(state["source"]["duration_seconds"], "source duration")
        report = _inspection_report(records, duration)
        expected_json = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        expected_markdown = _inspection_markdown(report).encode("utf-8")
        if output_paths["inspection/report.json"].read_bytes() != expected_json:
            raise ArtifactValidationError("recoverable inspection JSON is not deterministic current evidence")
        if output_paths["inspection/report.md"].read_bytes() != expected_markdown:
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
                if intent_records is not None and not _existing_outputs_match_intent(output_paths, intent_records):
                    raise ArtifactValidationError("published full ASR candidate is incomplete")
            else:
                if registered:
                    raise ArtifactValidationError("partial registered full ASR evidence is not recoverable")
                complete_intent = intent_records is not None and _existing_outputs_match_intent(output_paths, intent_records)
                if complete_intent:
                    metadata, _records = _validate_full_candidate_payloads(state, output_paths)
                else:
                    if intent_records is None and any(path.exists() for path in output_paths.values()):
                        raise ArtifactValidationError("full ASR evidence exists without a recoverable source-bound intent")
                    records = _validate_sequence(
                        self.model_adapter.transcribe(source, dict(DEFAULT_ASR_CONFIGURATION)), duration
                    )
                    self.store.validate_source(job_id)
                    runtime = _validate_runtime(self.model_adapter.runtime_metadata(), _REQUIRED_RUNTIME_KEYS, "ASR")
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
                    _publish_recoverable_outputs(
                        self.store, job_id, intent_relative, "full_asr", state["source_sha256"], output_paths,
                        output_bytes, {},
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
            complete_intent = intent_records is not None and _existing_outputs_match_intent(output_paths, intent_records)
            if complete_intent:
                _validate_rerun_candidate_payloads(state, output_paths, start_value, end_value)
            else:
                if intent_records is None and any(path.exists() for path in output_paths.values()):
                    raise ArtifactValidationError("rerun evidence exists without a recoverable source-bound intent")
                temporary_relative = f"asr/reruns/.{stem}.media.mka"
                temporary = self.store.validate_output_path(job_id, temporary_relative)
                if temporary.exists():
                    raise ArtifactValidationError("deterministic rerun media staging already exists")
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
                runtime = _validate_runtime(self.model_adapter.runtime_metadata(), _REQUIRED_RUNTIME_KEYS, "ASR")
                media_runtime = _validate_runtime(self.media_adapter.runtime_metadata(), _REQUIRED_MEDIA_RUNTIME_KEYS, "media")
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
                if intent_records is not None and not _existing_outputs_match_intent(output_paths, intent_records):
                    raise ArtifactValidationError("published inspection candidate is incomplete")
            else:
                if registered:
                    raise ArtifactValidationError("partial registered inspection evidence is not recoverable")
                complete_intent = intent_records is not None and _existing_outputs_match_intent(output_paths, intent_records)
                if complete_intent:
                    _validate_inspection_candidate_payloads(self.store, job_id, state, output_paths)
                else:
                    if intent_records is None and any(path.exists() for path in output_paths.values()):
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


def _read_raw_segments(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    previous_start: float | None = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise JobValidationError(f"raw ASR JSONL has a blank line at {line_number}")
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            raise JobValidationError(f"raw ASR JSONL is malformed at line {line_number}") from error
        record = _validate_record(parsed, previous_start)
        previous_start = float(record["start"])
        records.append(record)
    return records


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
