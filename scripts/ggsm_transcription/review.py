"""Whole-timeline editorial review and deterministic Listening-draft delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any
from urllib.parse import unquote, urlsplit

from .asr import _read_raw_segments
from .store import ArtifactValidationError, JobStore, JobValidationError, StageTransitionError


_TARGET_CHUNK_SECONDS = 30 * 60.0
_BOUNDARY_TOLERANCE_SECONDS = 10 * 60.0
_CLOCK_REPRESENTATION_TOLERANCE_SECONDS = 1.0
_MARKER_NAMES = (
    "Non-English interpretation omitted",
    "Recording silence",
    "Indistinct English speech",
)
_TIMESTAMP = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+\S")
_MARKER = re.compile(
    r"^\[(Non-English interpretation omitted|Recording silence|Indistinct English speech), "
    r"(\d{2}:\d{2}:\d{2})-(\d{2}:\d{2}:\d{2})\]$"
)
_HEADER_KEYS = {
    "Chunk-ID", "Start-Seconds", "End-Seconds", "Source-SHA256",
    "Full-ASR-SHA256", "Review-State", "Audible-Silence-Confirmed",
}
_VERIFICATION_CHECKS = [
    "source", "ASR", "inspection", "full ordered review", "Unicode NFC",
    "Listening draft label", "exact markers", "five-minute timestamps", "deterministic assembly",
]
_HANDOFF_FIELDS = {
    "status": "Listening draft",
    "message": "The draft is ready for manual OneNote copy/editing.",
    "copied_or_synced": False,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return _hash_bytes(data), len(data)


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


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise JobValidationError(f"{label} must be a finite number")
    return float(value)


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


def _event_clock(seconds: float) -> str:
    """Render an ASR start inside its raw span, rounding fractional starts up."""
    return _clock(float(math.ceil(seconds)))


def _parse_clock(value: str) -> float:
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (TypeError, ValueError) as error:
        raise JobValidationError("editorial timestamp is malformed") from error
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise JobValidationError("editorial timestamp is malformed")
    return float(hours * 3600 + minutes * 60 + seconds)


def _chunk_plan(records: list[dict[str, object]], duration: float, source_sha256: str,
                full_asr_sha256: str) -> dict[str, object]:
    if duration <= 0:
        raise JobValidationError("review requires a positive measured source duration")
    segment_boundaries = sorted({float(record["end"]) for record in records if 0 < float(record["end"]) < duration})
    boundaries = [0.0]
    cursor = 0.0
    while duration - cursor > _TARGET_CHUNK_SECONDS:
        target = cursor + _TARGET_CHUNK_SECONDS
        feasible = [boundary for boundary in segment_boundaries
                    if cursor < boundary < duration and abs(boundary - target) <= _BOUNDARY_TOLERANCE_SECONDS]
        boundary = min(feasible, key=lambda candidate: (abs(candidate - target), candidate)) if feasible else target
        if boundary <= cursor:
            raise JobValidationError("review chunk planning did not make forward progress")
        boundaries.append(boundary)
        cursor = boundary
    boundaries.append(duration)
    chunks = [
        {"id": f"chunk-{index:03d}", "start_seconds": start, "end_seconds": end,
         "path": f"review/chunk-{index:03d}.md", "reviewed": False}
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
    ]
    return {
        "schema_version": 1,
        "source_sha256": source_sha256,
        "full_asr_sha256": full_asr_sha256,
        "source_duration_seconds": duration,
        "asr_gap_policy": "ASR-uncovered intervals are not inferred silence",
        "clock_representation_tolerance_seconds": _CLOCK_REPRESENTATION_TOLERANCE_SECONDS,
        "clock_representation_policy": (
            "whole-second editorial clocks may extend only to floor(raw start) or ceil(raw end); "
            "raw source and chunk coverage remains exact"
        ),
        "chunks": chunks,
    }


def _chunk_markdown(chunk: dict[str, object], plan: dict[str, object],
                    records: list[dict[str, object]]) -> str:
    start, end = float(chunk["start_seconds"]), float(chunk["end_seconds"])
    draft_lines: list[str] = []
    for record in records:
        segment_start = float(record["start"])
        if start <= segment_start < end:
            text = str(record["text"]).strip()
            if text:
                draft_lines.extend([f"[{_event_clock(segment_start)}] {text}", ""])
    if not draft_lines:
        draft_lines = ["<!-- ASR-uncovered draft span: listen before adding text or an audio-supported marker. -->", ""]
    lines = [
        "---",
        f"Chunk-ID: {chunk['id']}",
        f"Start-Seconds: {start}",
        f"End-Seconds: {end}",
        f"Source-SHA256: {plan['source_sha256']}",
        f"Full-ASR-SHA256: {plan['full_asr_sha256']}",
        "Review-State: pending",
        "Audible-Silence-Confirmed: none",
        "---",
        "",
        f"# Listening review {chunk['id']}",
        "",
        f"Assigned span: {_clock(start)}-{_clock(end)}",
        "",
        "Listen to the complete assigned span. Edit the ASR text from the audio, then set",
        "`Review-State: reviewed`. ASR-uncovered intervals are not inferred silence.",
        "Use only the exact time-bounded editorial markers described by the workflow.",
        "Whole-second clocks may overlap a fractional raw chunk edge by less than one second;",
        "the manifest's raw floating-point coverage remains exact.",
        "For every Recording silence marker, add its exact range to",
        "`Audible-Silence-Confirmed` (semicolon-separated); this is an explicit listening attestation.",
        "",
        "## Editorial transcript",
        "",
        *draft_lines,
    ]
    return unicodedata.normalize("NFC", "\n".join(lines).rstrip() + "\n")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactValidationError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{label} must be a JSON object")
    return value


def _parse_chunk(path: Path) -> tuple[dict[str, str], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ArtifactValidationError(f"review chunk is unreadable: {path.name}") from error
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise JobValidationError(f"review chunk metadata is malformed: {path.name}")
    header_text, remainder = text[4:].split("\n---\n", 1)
    header: dict[str, str] = {}
    for line in header_text.splitlines():
        key, separator, value = line.partition(": ")
        if not separator or key in header:
            raise JobValidationError(f"review chunk metadata is malformed: {path.name}")
        header[key] = value
    if set(header) != _HEADER_KEYS:
        raise JobValidationError(f"review chunk metadata fields are invalid: {path.name}")
    separator = "## Editorial transcript\n"
    if remainder.count(separator) != 1:
        raise JobValidationError(f"review chunk editorial section is malformed: {path.name}")
    body = remainder.split(separator, 1)[1].strip()
    return header, body


def _parse_confirmations(value: str) -> set[str]:
    if value == "none":
        return set()
    values = {item.strip() for item in value.split(";")}
    if not values or any(not re.fullmatch(r"\d{2}:\d{2}:\d{2}-\d{2}:\d{2}:\d{2}", item) for item in values):
        raise JobValidationError("audible silence confirmation is malformed")
    return values


def _validate_editorial_body(body: str, start: float, end: float,
                              confirmations: set[str]) -> list[tuple[float, float]]:
    if not body:
        raise JobValidationError("reviewed chunk has no editorial transcript")
    events: list[tuple[float, float]] = []
    silence_ranges: set[str] = set()
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()]
    for paragraph in paragraphs:
        marker = _MARKER.fullmatch(paragraph)
        if marker:
            marker_start, marker_end = _parse_clock(marker.group(2)), _parse_clock(marker.group(3))
            if marker_end <= marker_start:
                raise JobValidationError("editorial marker range must be ordered")
            if marker.group(1) == "Recording silence":
                silence_ranges.add(f"{marker.group(2)}-{marker.group(3)}")
            event = (marker_start, marker_end)
        else:
            if any(name.lower() in paragraph.lower() for name in _MARKER_NAMES):
                raise JobValidationError("unknown or malformed editorial marker")
            timestamp = _TIMESTAMP.match(paragraph)
            if timestamp is None:
                if paragraph.startswith("["):
                    raise JobValidationError("unknown or malformed editorial marker")
                raise JobValidationError("every editorial paragraph needs a natural timestamp")
            timestamp_close = paragraph.find("]")
            if "[" in paragraph[timestamp_close + 1:]:
                raise JobValidationError("unknown or malformed editorial marker")
            point = _parse_clock(timestamp.group(1))
            event = (point, point)
        if event[0] < math.floor(start) or event[1] > math.ceil(end):
            raise JobValidationError("editorial timestamp is outside its assigned review chunk")
        events.append(event)
    if confirmations != silence_ranges:
        raise JobValidationError("Recording silence requires an exact audible silence confirmation from listening")
    anchor = start
    for event_start, event_end in events:
        if event_start < anchor - _CLOCK_REPRESENTATION_TOLERANCE_SECONDS:
            raise JobValidationError("editorial timestamps or markers are out of order")
        if event_start - anchor > 300:
            raise JobValidationError("editorial timestamps are more than five minutes apart")
        anchor = max(event_start, event_end)
    return events


def _validate_event_stream(events: list[tuple[float, float]], duration: float) -> None:
    anchor = 0.0
    for event_start, event_end in events:
        if event_start < anchor:
            raise JobValidationError("editorial timestamps or markers are out of order")
        if event_start - anchor > 300:
            raise JobValidationError("editorial timestamps are more than five minutes apart")
        anchor = max(event_start, event_end)
    if math.ceil(duration) - anchor > 300:
        raise JobValidationError("editorial terminal tail is more than five minutes")


class ReviewDeliveryService:
    """Use cases for review evidence and a local, manual-only Listening draft."""

    def __init__(self, store: JobStore) -> None:
        self.store = store

    def _validate_upstream(self, job_id: str, state: dict[str, Any]) -> tuple[Path, list[dict[str, object]]]:
        self.store.validate_source(job_id)
        raw = self.store.validate_artifact(job_id, "asr/full.jsonl")
        self.store.validate_artifact(job_id, "asr/metadata.json")
        self.store.validate_artifact(job_id, "inspection/report.json")
        self.store.validate_artifact(job_id, "inspection/report.md")
        records = _read_raw_segments(raw)
        duration = _finite(state["source"]["duration_seconds"], "source duration")
        if any(float(record["end"]) > duration for record in records):
            raise ArtifactValidationError("raw ASR extends beyond its source")
        return raw, records

    def _expected_plan(self, state: dict[str, Any], records: list[dict[str, object]]) -> dict[str, object]:
        duration = _finite(state["source"]["duration_seconds"], "source duration")
        full_hash = state["artifacts"]["asr/full.jsonl"]["sha256"]
        return _chunk_plan(records, duration, state["source_sha256"], full_hash)

    def prepare_review(self, job_id: str) -> dict[str, object]:
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] != "inspected":
                raise StageTransitionError("prepare-review requires an inspected job")
            _raw, records = self._validate_upstream(job_id, state)
            root = self.store.job_root(job_id)
            review_root = root / "review"
            plan = self._expected_plan(state, records)
            expected_outputs: dict[Path, str] = {
                root / str(chunk["path"]): _chunk_markdown(chunk, plan, records)
                for chunk in plan["chunks"]  # type: ignore[union-attr]
            }
            expected_outputs[review_root / "manifest.json"] = _json_text(plan)
            self.store.validate_output_path(job_id, "review/manifest.json")
            actual = list(review_root.iterdir())
            expected_names = {path.name for path in expected_outputs}
            if any(path.name not in expected_names or not path.is_file() or path.is_symlink() for path in actual):
                raise ArtifactValidationError("review preparation contains unknown or unsafe partial evidence")
            for path, expected_text in expected_outputs.items():
                relative = path.relative_to(root).as_posix()
                self.store.validate_output_path(job_id, relative)
                if path.exists():
                    try:
                        existing = path.read_text(encoding="utf-8")
                    except (OSError, UnicodeError) as error:
                        raise ArtifactValidationError("partial review preparation is unreadable") from error
                    if existing != expected_text:
                        raise ArtifactValidationError("partial review preparation differs from the source-bound default")
                    continue
                _atomic_text(path, expected_text)
        return plan

    def _load_prepared(self, job_id: str, state: dict[str, Any], records: list[dict[str, object]]) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Path, dict[str, str], str]]]:
        root, review_root = self.store.job_root(job_id), self.store.job_root(job_id) / "review"
        manifest_path = review_root / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ArtifactValidationError("prepared review manifest is missing or unsafe")
        manifest = _read_json(manifest_path, "prepared review manifest")
        expected = self._expected_plan(state, records)
        recovering_final = False
        if manifest != expected:
            expected_chunks = expected["chunks"]
            actual_chunks = manifest.get("chunks")
            same_binding = all(manifest.get(key) == expected.get(key) for key in (
                "schema_version", "source_sha256", "full_asr_sha256",
                "source_duration_seconds", "asr_gap_policy", "clock_representation_tolerance_seconds",
                "clock_representation_policy",
            ))
            if not same_binding or not isinstance(actual_chunks, list) or len(actual_chunks) != len(expected_chunks):  # type: ignore[arg-type]
                raise ArtifactValidationError("prepared review manifest is altered, unordered, or non-covering")
            for expected_chunk, actual_chunk in zip(expected_chunks, actual_chunks, strict=True):  # type: ignore[arg-type]
                if (not isinstance(actual_chunk, dict)
                        or {key: actual_chunk.get(key) for key in expected_chunk} != {**expected_chunk, "reviewed": True}
                        or not isinstance(actual_chunk.get("sha256"), str)
                        or not isinstance(actual_chunk.get("byte_size"), int)):
                    raise ArtifactValidationError("prepared review manifest is altered, unordered, or non-covering")
            recovering_final = True
        expected_names = {"manifest.json", *(Path(str(chunk["path"])).name for chunk in expected["chunks"])}  # type: ignore[union-attr]
        actual_names = {path.name for path in review_root.iterdir() if path.is_file()}
        if actual_names != expected_names:
            raise ArtifactValidationError("review chunks are missing, unregistered in the manifest, or unexpected")
        parsed: list[tuple[dict[str, Any], Path, dict[str, str], str]] = []
        global_events: list[tuple[float, float]] = []
        for chunk in expected["chunks"]:  # type: ignore[union-attr]
            path = root / str(chunk["path"])
            if not path.is_file() or path.is_symlink():
                raise ArtifactValidationError(f"review chunk is missing or unsafe: {chunk['id']}")
            header, body = _parse_chunk(path)
            expected_header = {
                "Chunk-ID": str(chunk["id"]),
                "Start-Seconds": str(float(chunk["start_seconds"])),
                "End-Seconds": str(float(chunk["end_seconds"])),
                "Source-SHA256": str(expected["source_sha256"]),
                "Full-ASR-SHA256": str(expected["full_asr_sha256"]),
            }
            if any(header[key] != value for key, value in expected_header.items()):
                raise ArtifactValidationError(f"review chunk binding is altered: {chunk['id']}")
            if header["Review-State"] != "reviewed":
                raise JobValidationError(f"review chunk is not explicitly reviewed: {chunk['id']}")
            confirmations = _parse_confirmations(header["Audible-Silence-Confirmed"])
            global_events.extend(_validate_editorial_body(
                body, float(chunk["start_seconds"]), float(chunk["end_seconds"]), confirmations
            ))
            if recovering_final:
                final_chunk = manifest["chunks"][len(parsed)]
                digest, size = _hash_file(path)
                if final_chunk.get("sha256") != digest or final_chunk.get("byte_size") != size:
                    raise ArtifactValidationError("recoverable final review manifest does not match its chunks")
            parsed.append((chunk, path, header, body))
        _validate_event_stream(global_events, _finite(expected["source_duration_seconds"], "source duration"))
        return expected, parsed

    def record_review(self, job_id: str) -> dict[str, Any]:
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] != "inspected":
                raise StageTransitionError("record-review requires an inspected job")
            _raw, records = self._validate_upstream(job_id, state)
            plan, parsed = self._load_prepared(job_id, state, records)
            finalized = dict(plan)
            finalized["chunks"] = []
            for chunk, path, _header, _body in parsed:
                digest, size = _hash_file(path)
                finalized["chunks"].append({**chunk, "reviewed": True, "sha256": digest, "byte_size": size})
            manifest_path = self.store.job_root(job_id) / "review" / "manifest.json"
            self.store.validate_output_path(job_id, "review/manifest.json")
            _atomic_text(manifest_path, _json_text(finalized))
            for chunk, _path, _header, _body in parsed:
                transaction.register_artifact(str(chunk["path"]))
            transaction.register_artifact("review/manifest.json")
        with self.store.transaction(job_id) as transaction:
            transaction.complete_review()
        return self.store.load_job(job_id)

    def register_reference(self, job_id: str, reference_url: str, markdown_file: str | Path) -> dict[str, Any]:
        self.store._validate_https_url(reference_url)
        source = Path(markdown_file)
        if source.suffix.lower() != ".md" or not source.is_file() or source.is_symlink():
            raise JobValidationError("reference input must be a safe existing Markdown file")
        try:
            input_bytes = source.read_bytes()
            content = unicodedata.normalize("NFC", input_bytes.decode("utf-8"))
        except (OSError, UnicodeError) as error:
            raise JobValidationError("reference input must be readable UTF-8 Markdown") from error
        stored_bytes = content.encode("utf-8")
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] == "created":
                raise StageTransitionError("reference registration requires a source-ready or later job")
            self.store.validate_source(job_id)
            root = self.store.job_root(job_id)
            target = root / "reference" / "taptajivanam.md"
            provenance_path = root / "reference" / "provenance.json"
            intent_path = root / "reference" / ".capture.json"
            self.store.validate_output_path(job_id, "reference/taptajivanam.md")
            self.store.validate_output_path(job_id, "reference/provenance.json")
            self.store.validate_output_path(job_id, "reference/.capture.json")
            provenance = {
                "url": reference_url,
                "input_sha256": _hash_bytes(input_bytes),
                "stored_sha256": _hash_bytes(stored_bytes),
                "byte_size": len(stored_bytes),
                "captured_at": _utcnow(),
                "authority": "secondary evidence only; audio remains authoritative",
            }
            intent = {**provenance, "source_sha256": state["source_sha256"]}
            if intent_path.exists():
                existing_intent = _read_json(intent_path, "existing reference capture intent")
                if ({key: existing_intent.get(key) for key in intent if key != "captured_at"}
                        != {key: intent[key] for key in intent if key != "captured_at"}
                        or not isinstance(existing_intent.get("captured_at"), str)
                        or not existing_intent["captured_at"]):
                    raise ArtifactValidationError("existing reference capture intent differs from this retry")
                provenance["captured_at"] = existing_intent["captured_at"]
            elif target.exists() and not provenance_path.exists():
                raise ArtifactValidationError("target-only reference evidence lacks a recoverable capture intent")
            elif provenance_path.exists():
                existing_provenance = _read_json(provenance_path, "existing reference provenance")
                if ({key: existing_provenance.get(key) for key in provenance if key != "captured_at"}
                        != {key: provenance[key] for key in provenance if key != "captured_at"}
                        or not isinstance(existing_provenance.get("captured_at"), str)
                        or not existing_provenance["captured_at"]):
                    raise ArtifactValidationError("existing reference provenance differs from this retry")
                provenance["captured_at"] = existing_provenance["captured_at"]
                intent["captured_at"] = existing_provenance["captured_at"]
                _atomic_text(intent_path, _json_text(intent))
            else:
                _atomic_text(intent_path, _json_text(intent))
            if target.exists():
                if not target.is_file() or target.is_symlink() or target.read_bytes() != stored_bytes:
                    raise ArtifactValidationError("existing reference Markdown is unsafe or differs from this capture")
            if provenance_path.exists():
                if not provenance_path.is_file() or provenance_path.is_symlink():
                    raise ArtifactValidationError("existing reference provenance is unsafe")
                existing = _read_json(provenance_path, "existing reference provenance")
                if ({key: existing.get(key) for key in provenance if key != "captured_at"}
                        != {key: provenance[key] for key in provenance if key != "captured_at"}
                        or not isinstance(existing.get("captured_at"), str) or not existing["captured_at"]):
                    raise ArtifactValidationError("existing reference evidence is not a recoverable identical capture")
            if not target.exists():
                _atomic_text(target, content)
            if not provenance_path.exists():
                _atomic_text(provenance_path, _json_text(provenance))
            transaction.register_artifact("reference/taptajivanam.md")
            transaction.register_artifact("reference/provenance.json")
            try:
                intent_path.unlink()
            except FileNotFoundError:
                pass
        return self.store.load_job(job_id)

    def _validated_review(self, job_id: str, state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        manifest_path = self.store.validate_artifact(job_id, "review/manifest.json")
        manifest = _read_json(manifest_path, "final review manifest")
        _raw, records = self._validate_upstream(job_id, state)
        expected = self._expected_plan(state, records)
        chunks = manifest.get("chunks")
        if not isinstance(chunks, list) or len(chunks) != len(expected["chunks"]):  # type: ignore[arg-type]
            raise ArtifactValidationError("final review coverage is incomplete")
        expected_paths = {
            "review/manifest.json",
            *(str(chunk["path"]) for chunk in expected["chunks"]),  # type: ignore[union-attr]
        }
        registered_paths = {path for path in state["artifacts"] if path.startswith("review/")}
        review_root = self.store.job_root(job_id) / "review"
        try:
            entries = list(review_root.iterdir())
        except OSError as error:
            raise ArtifactValidationError("final review inventory is unreadable") from error
        actual_paths = {f"review/{entry.name}" for entry in entries}
        if registered_paths != expected_paths or actual_paths != expected_paths:
            raise ArtifactValidationError("final review inventory contains missing or unexpected evidence")
        for relative_path in expected_paths:
            self.store.validate_output_path(job_id, relative_path)
        bodies: list[str] = []
        global_events: list[tuple[float, float]] = []
        for expected_chunk, final_chunk in zip(expected["chunks"], chunks, strict=True):  # type: ignore[union-attr]
            if not isinstance(final_chunk, dict):
                raise ArtifactValidationError("final review chunk record is malformed")
            base = {key: final_chunk.get(key) for key in expected_chunk}
            if base != {**expected_chunk, "reviewed": True} or not final_chunk.get("reviewed"):
                raise ArtifactValidationError("final review is altered, unordered, or non-covering")
            path = self.store.validate_artifact(job_id, str(expected_chunk["path"]))
            digest, size = _hash_file(path)
            if final_chunk.get("sha256") != digest or final_chunk.get("byte_size") != size:
                raise ArtifactValidationError("final review chunk hash does not match its manifest")
            header, body = _parse_chunk(path)
            expected_header = {
                "Chunk-ID": str(expected_chunk["id"]),
                "Start-Seconds": str(float(expected_chunk["start_seconds"])),
                "End-Seconds": str(float(expected_chunk["end_seconds"])),
                "Source-SHA256": str(expected["source_sha256"]),
                "Full-ASR-SHA256": str(expected["full_asr_sha256"]),
                "Review-State": "reviewed",
            }
            if any(header[key] != value for key, value in expected_header.items()):
                raise ArtifactValidationError("final review chunk binding changed")
            global_events.extend(_validate_editorial_body(
                body, float(expected_chunk["start_seconds"]), float(expected_chunk["end_seconds"]),
                _parse_confirmations(header["Audible-Silence-Confirmed"])
            ))
            bodies.append(body)
        for key in ("schema_version", "source_sha256", "full_asr_sha256", "source_duration_seconds",
                    "asr_gap_policy", "clock_representation_tolerance_seconds", "clock_representation_policy"):
            if manifest.get(key) != expected.get(key):
                raise ArtifactValidationError("final review manifest binding changed")
        _validate_event_stream(global_events, _finite(expected["source_duration_seconds"], "source duration"))
        return manifest, bodies

    @staticmethod
    def _title(state: dict[str, Any]) -> str:
        slug = state["job_id"].rsplit("-", 1)[0]
        title = " ".join(part.capitalize() for part in slug.split("-") if part)
        if title:
            return title
        path_title = Path(unquote(urlsplit(state["source"]["resolved_url"]).path)).stem
        return path_title or "GGSM lecture"

    def _delivery_text(self, state: dict[str, Any], bodies: list[str]) -> str:
        title = self._title(state)
        duration = _clock(_finite(state["source"]["duration_seconds"], "source duration"))
        source_url = state["source"]["requested_url"]
        transcript = "\n\n".join(body.strip() for body in bodies)
        text = (
            f"# {title}\n\n"
            "Status: Listening draft\n\n"
            f"Source URL: {source_url}\n\n"
            f"Title: {title}\n\n"
            f"Duration: {duration}\n\n"
            "Manual OneNote copy/editing is outside this runner.\n\n"
            "## Transcript\n\n"
            f"{transcript}\n"
        )
        return unicodedata.normalize("NFC", text)

    def assemble(self, job_id: str) -> Path:
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] != "reviewed":
                raise StageTransitionError("assemble requires a reviewed job")
            _manifest, bodies = self._validated_review(job_id, state)
            delivery = self._delivery_text(state, bodies)
            path = self.store.job_root(job_id) / "delivery" / "onenote-transcript.md"
            self.store.validate_output_path(job_id, "delivery/onenote-transcript.md")
            if path.exists():
                if path.read_bytes() != delivery.encode("utf-8"):
                    raise ArtifactValidationError("existing delivery differs from deterministic reviewed assembly")
            else:
                _atomic_text(path, delivery)
            transaction.register_artifact("delivery/onenote-transcript.md")
        return path

    def _validate_delivery(self, job_id: str, state: dict[str, Any]) -> tuple[Path, bytes]:
        _manifest, bodies = self._validated_review(job_id, state)
        delivery_path = self.store.validate_artifact(job_id, "delivery/onenote-transcript.md")
        try:
            delivery_bytes = delivery_path.read_bytes()
            delivery_text = delivery_bytes.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise ArtifactValidationError("delivery is not readable UTF-8") from error
        if delivery_text != unicodedata.normalize("NFC", delivery_text):
            raise ArtifactValidationError("delivery is not Unicode NFC")
        expected = self._delivery_text(state, bodies).encode("utf-8")
        if delivery_bytes != expected:
            raise ArtifactValidationError("delivery does not match deterministic reviewed assembly")
        return delivery_path, delivery_bytes

    def validate_review_completion(self, job_id: str) -> None:
        state = self.store.load_job(job_id)
        if state["stage"] != "inspected":
            raise StageTransitionError("review completion requires an inspected job")
        self._validated_review(job_id, state)

    def _validate_verification_evidence(self, job_id: str, state: dict[str, Any]) -> bytes:
        self.store.validate_source(job_id)
        _delivery_path, delivery_bytes = self._validate_delivery(job_id, state)
        verification_path = self.store.validate_artifact(job_id, "delivery/verification.json")
        verification = _read_json(verification_path, "delivery verification")
        expected = {
            "success": True,
            "source_sha256": state["source_sha256"],
            "delivery_sha256": _hash_bytes(delivery_bytes),
            "checks": _VERIFICATION_CHECKS,
        }
        if ({key: verification.get(key) for key in expected} != expected
                or set(verification) != {*expected, "verified_at"}
                or not isinstance(verification.get("verified_at"), str)
                or not verification["verified_at"]):
            raise ArtifactValidationError("successful current-evidence verification is required")
        return delivery_bytes

    def validate_verification_completion(self, job_id: str) -> None:
        state = self.store.load_job(job_id)
        if state["stage"] != "reviewed":
            raise StageTransitionError("verification completion requires a reviewed job")
        self._validate_verification_evidence(job_id, state)

    def validate_handoff_completion(self, job_id: str) -> None:
        state = self.store.load_job(job_id)
        if state["stage"] != "draft_ready":
            raise StageTransitionError("handoff completion requires a draft_ready job")
        self._validate_verification_evidence(job_id, state)
        receipt_path = self.store.validate_artifact(job_id, "delivery/handoff.json")
        receipt = _read_json(receipt_path, "handoff receipt")
        if ({key: receipt.get(key) for key in _HANDOFF_FIELDS} != _HANDOFF_FIELDS
                or set(receipt) != {*_HANDOFF_FIELDS, "created_at"}
                or not isinstance(receipt.get("created_at"), str)
                or not receipt["created_at"]):
            raise ArtifactValidationError("manual-only matching handoff receipt is required")

    def verify(self, job_id: str) -> dict[str, Any]:
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] != "reviewed":
                raise StageTransitionError("verify requires a reviewed job")
            self.store.validate_source(job_id)
            _delivery_path, delivery_bytes = self._validate_delivery(job_id, state)
            verification = {
                "success": True,
                "verified_at": _utcnow(),
                "source_sha256": state["source_sha256"],
                "delivery_sha256": _hash_bytes(delivery_bytes),
                "checks": _VERIFICATION_CHECKS,
            }
            verification_path = self.store.job_root(job_id) / "delivery" / "verification.json"
            self.store.validate_output_path(job_id, "delivery/verification.json")
            if verification_path.exists():
                existing = _read_json(verification_path, "existing verification evidence")
                if ({key: existing.get(key) for key in verification if key != "verified_at"}
                        != {key: verification[key] for key in verification if key != "verified_at"}
                        or not isinstance(existing.get("verified_at"), str) or not existing["verified_at"]):
                    raise ArtifactValidationError("existing verification evidence is not a recoverable successful verification")
            else:
                _atomic_text(verification_path, _json_text(verification))
            transaction.register_artifact("delivery/verification.json")
        with self.store.transaction(job_id) as transaction:
            transaction.complete_verification()
        return self.store.load_job(job_id)

    def handoff(self, job_id: str) -> dict[str, Any]:
        with self.store.transaction(job_id) as transaction:
            state = transaction.state
            if state["stage"] != "draft_ready":
                raise StageTransitionError("handoff requires a draft_ready job")
            self._validate_verification_evidence(job_id, state)
            receipt = {"created_at": _utcnow(), **_HANDOFF_FIELDS}
            path = self.store.job_root(job_id) / "delivery" / "handoff.json"
            self.store.validate_output_path(job_id, "delivery/handoff.json")
            if path.exists():
                existing = _read_json(path, "existing handoff receipt")
                if ({key: existing.get(key) for key in receipt if key != "created_at"}
                        != {key: receipt[key] for key in receipt if key != "created_at"}
                        or not isinstance(existing.get("created_at"), str) or not existing["created_at"]):
                    raise ArtifactValidationError("existing handoff receipt is not recoverable manual-only evidence")
            else:
                _atomic_text(path, _json_text(receipt))
            transaction.register_artifact("delivery/handoff.json")
        with self.store.transaction(job_id) as transaction:
            transaction.complete_handoff()
        return self.store.load_job(job_id)
