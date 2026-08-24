from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .source import from_mid_side


_BLIND_CODES = ("A", "B", "C")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def blind_order(source_hash: str, candidate_ids: list[str]) -> dict[str, str]:
    """Assign stable blind labels without relying on the input ordering."""
    if not source_hash or len(candidate_ids) > len(_BLIND_CODES):
        raise ValueError("a source hash and at most three candidates are required")
    if len(candidate_ids) != len(set(candidate_ids)) or any(not item for item in candidate_ids):
        raise ValueError("candidate identifiers must be non-empty and unique")
    ordered = sorted(
        candidate_ids,
        key=lambda item: hashlib.sha256(f"{source_hash}:{item}".encode()).digest(),
    )
    return {code: candidate_id for code, candidate_id in zip(_BLIND_CODES, ordered)}


def blend_mid(
    original_mid: np.ndarray,
    enhanced_mid: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """Blend only the reviewed processing mask; zeros stay bit-identical to original."""
    if original_mid.shape != enhanced_mid.shape or original_mid.shape != mask.shape:
        raise ValueError("parallel candidate arrays and mask must align")
    if original_mid.ndim != 1:
        raise ValueError("candidate mid arrays and mask must be one-dimensional")
    if not np.all(np.isfinite(mask)) or np.any(mask < 0) or np.any(mask > 1):
        raise ValueError("processing mask must be finite and stay in [0, 1]")
    output = original_mid.astype(np.float32, copy=True)
    selected = mask != 0.0
    output[selected] = (
        original_mid[selected] * (1.0 - mask[selected])
        + enhanced_mid[selected] * mask[selected]
    ).astype(np.float32)
    return output


def match_active_rms(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    """Loudness-match a listening copy only; callers must retain the raw array."""
    if reference.shape != candidate.shape or reference.ndim != 1:
        raise ValueError("matched candidates must be equal-length mono arrays")
    if not np.all(np.isfinite(reference)) or not np.all(np.isfinite(candidate)):
        raise ValueError("loudness matching requires finite arrays")
    threshold = max(float(np.percentile(np.abs(reference), 35)), 1e-6)
    active = np.abs(reference) >= threshold
    if not np.any(active):
        return candidate.astype(np.float32, copy=True)
    ref_rms = math.sqrt(float(np.mean(np.square(reference[active]))) + 1e-20)
    cand_rms = math.sqrt(float(np.mean(np.square(candidate[active]))) + 1e-20)
    gain = min(ref_rms / cand_rms, 4.0)
    output = candidate * gain
    peak = float(np.max(np.abs(output))) if len(output) else 0.0
    if peak > 0.99:
        output *= 0.99 / peak
    return output.astype(np.float32)


def _match_stereo(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    _require_stereo(reference, "reference")
    _require_stereo(candidate, "candidate")
    if reference.shape != candidate.shape:
        raise ValueError("matched candidates must have equal sample counts")
    ref_mid = reference.mean(axis=1)
    cand_mid = candidate.mean(axis=1)
    matched_mid = match_active_rms(ref_mid, cand_mid)
    denominator = float(np.sqrt(np.mean(np.square(cand_mid))) + 1e-20)
    numerator = float(np.sqrt(np.mean(np.square(matched_mid))) + 1e-20)
    output = candidate * (numerator / denominator)
    peak = float(np.max(np.abs(output))) if len(output) else 0.0
    if peak > 0.99:
        output *= 0.99 / peak
    return output.astype(np.float32)


def build_candidate_arrays(
    source_hash: str,
    original_mid: np.ndarray,
    original_side: np.ndarray,
    speech_mask: np.ndarray,
    render_22: np.ndarray,
    render_24: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, str]]:
    """Build aligned raw candidates plus separately loudness-matched audition copies."""
    shapes = {
        original_mid.shape,
        original_side.shape,
        speech_mask.shape,
        render_22.shape,
        render_24.shape,
    }
    if len(shapes) != 1 or original_mid.ndim != 1:
        raise ValueError("candidate inputs are not sample aligned mono arrays")
    selected = {
        "original": original_mid.astype(np.float32, copy=True),
        "adaptive-22": blend_mid(original_mid, render_22, speech_mask),
        "adaptive-24": blend_mid(original_mid, render_24, speech_mask),
    }
    raw = {name: from_mid_side(mid, original_side) for name, mid in selected.items()}
    mapping = blind_order(source_hash, list(selected))
    audition = {
        code: _match_stereo(raw["original"], raw[candidate_id])
        for code, candidate_id in mapping.items()
    }
    return raw, audition, mapping


def write_candidate_window(
    directory: Path,
    audition: dict[str, np.ndarray],
    sample_rate: int,
    *,
    trusted_root: Path,
) -> None:
    """Atomically create, or byte-reuse, one blind listening window.

    Existing partial or different evidence is deliberately refused.  The candidate
    arrays passed here are audition files; raw arrays never pass through this API.
    """
    directory = Path(directory)
    root = _trusted_root(Path(trusted_root))
    directory = _safe_destination(root, directory)
    _validate_audition(audition, sample_rate)
    expected_names = {f"{code}.wav" for code in _BLIND_CODES}
    leaves = tuple(directory / name for name in expected_names)
    for leaf in leaves:
        _safe_destination(root, leaf)
    if any(path.is_symlink() for path in leaves):
        raise ValueError("refusing symlinked candidate evidence leaf")
    if directory.exists():
        if not directory.is_dir() or {path.name for path in directory.iterdir()} != expected_names:
            raise FileExistsError(f"refusing to replace partial candidate evidence: {directory}")
        with tempfile.TemporaryDirectory(dir=directory.parent, prefix=".candidate-compare-") as temp:
            temporary = Path(temp)
            _write_window_files(temporary, audition, sample_rate)
            for name in expected_names:
                if not _same_audio_content(directory / name, temporary / name):
                    raise FileExistsError(f"refusing to replace different candidate evidence: {directory}")
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=directory.parent, prefix=".candidate-window-"))
    try:
        _write_window_files(temporary, audition, sample_rate)
        # os.rename refuses an existing destination on Windows, unlike replace.
        os.rename(temporary, directory)
    except BaseException:
        if temporary.exists():
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()
        raise


def write_gallery(
    path: Path,
    window_ids: list[str],
    *,
    transition_window_ids: list[str] | None = None,
) -> None:
    """Write an immutable public gallery containing codes, never candidate identities."""
    speech = _validate_window_ids(window_ids)
    transitions = _validate_window_ids(transition_window_ids or [])
    document = _gallery_document(speech, transitions)
    _write_immutable_text(Path(path), document)


def write_candidate_artifacts(
    work_root: Path,
    source_hash: str,
    blind_map: dict[str, str],
    report: dict[str, Any],
    speech_window_ids: list[str],
    *,
    transition_window_ids: list[str] | None = None,
    audition_by_window: dict[str, dict[str, np.ndarray]],
    evidence_map: dict[str, dict[str, str]] | None = None,
    sample_rate: int,
    completion_provenance: dict[str, Any] | None = None,
) -> str:
    """Persist the private mapping and public blind-only evidence without overwriting it."""
    if set(blind_map) != set(_BLIND_CODES) or set(blind_map.values()) != {
        "original", "adaptive-22", "adaptive-24"
    }:
        raise ValueError("blind map must contain the three independent candidate identities")
    root = _trusted_root(Path(work_root))
    speech = _validate_window_ids(speech_window_ids)
    transitions = _validate_window_ids(transition_window_ids or [])
    public_report = _public_report(report)
    report_sha256 = public_report["report_sha256"]
    blind_map_sha256 = _canonical_hash(blind_map)
    if report.get("blind_map_sha256") != blind_map_sha256:
        raise ValueError("private blind map does not match report commitment")
    window_ids = speech + transitions
    if set(speech) & set(transitions) or set(audition_by_window) != set(window_ids):
        raise ValueError("speech/transition IDs must be disjoint and match audition evidence")
    _validate_audition_windows(audition_by_window, sample_rate)
    private_wrapper: dict[str, Any] = {"source_hash": source_hash, "blind_map": blind_map}
    if evidence_map is not None:
        if set(evidence_map) != set(window_ids) or report.get("evidence_ids") != window_ids:
            raise ValueError("private evidence identities must match the public report and audio")
        for artifact_id, identity in evidence_map.items():
            if (
                not _SAFE_ID.fullmatch(artifact_id)
                or not isinstance(identity, dict)
                or set(identity) != {"window_id", "role", "kind"}
                or any(not isinstance(value, str) or not value for value in identity.values())
                or identity["kind"] not in {"window", "transition"}
            ):
                raise ValueError("private candidate evidence map is malformed")
        private_wrapper["evidence_map"] = evidence_map
    desired = {
        root / "candidate-map.private.json": _canonical_json(private_wrapper),
        root / "candidates" / "candidate-report.json": _canonical_json(public_report),
        root / "candidates" / "index.html": _gallery_document(speech, transitions),
    }
    with tempfile.TemporaryDirectory() as folder:
        stage = Path(folder)
        for window_id in window_ids:
            for code in _BLIND_CODES:
                path = stage / window_id / f"{code}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(path, audition_by_window[window_id][code], sample_rate, subtype="FLOAT")
                desired[root / "candidates" / window_id / f"{code}.wav"] = path.read_bytes()
    completion = {
        "schema_version": 1,
        "blind_map_sha256": blind_map_sha256,
        "artifacts": {
            str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(_as_bytes(content)).hexdigest()
            for path, content in desired.items()
        },
    }
    if completion_provenance is not None:
        completion["provenance"] = json.loads(_canonical_json(completion_provenance))
    marker = root / "candidates" / "completion.json"
    desired[marker] = _canonical_json(completion)
    paths = tuple(desired)
    for path in paths:
        _safe_destination(root, path)
        if path.is_symlink():
            raise ValueError("refusing symlinked candidate artifact leaf")
    candidate_root = root / "candidates"
    if candidate_root.exists():
        observed = {path.resolve() for path in candidate_root.rglob("*") if path.is_file()}
        expected = {path.resolve() for path in paths if path.is_relative_to(candidate_root)}
        if observed and observed != expected:
            raise FileExistsError("refusing candidate evidence with stale or missing artifact files")
    existing = [path.exists() for path in paths]
    if any(existing):
        if not all(existing):
            raise FileExistsError("refusing to complete a partial candidate artifact set")
        if any(not _artifact_matches(path, _as_bytes(desired[path])) for path in paths[:-1]):
            raise FileExistsError("refusing to replace mismatched candidate artifacts")
        if not _completion_matches_existing(marker, completion, root):
            raise FileExistsError("refusing to replace mismatched candidate artifacts")
        return report_sha256
    # All content is calculated and path-checked before any evidence is published;
    # the completion marker is deliberately the final published artifact.
    for path in paths[:-1]:
        _write_immutable_bytes(path, _as_bytes(desired[path]))
    _write_immutable_bytes(marker, _as_bytes(desired[marker]))
    return report_sha256


def _write_window_files(directory: Path, audition: dict[str, np.ndarray], sample_rate: int) -> None:
    for code in _BLIND_CODES:
        sf.write(directory / f"{code}.wav", audition[code], sample_rate, subtype="FLOAT")


def _same_audio_content(existing: Path, expected: Path) -> bool:
    existing_info = sf.info(existing)
    expected_info = sf.info(expected)
    if (
        existing_info.samplerate != expected_info.samplerate
        or existing_info.channels != expected_info.channels
        or existing_info.frames != expected_info.frames
        or existing_info.subtype != expected_info.subtype
    ):
        return False
    existing_values, _ = sf.read(existing, dtype="float32", always_2d=True)
    expected_values, _ = sf.read(expected, dtype="float32", always_2d=True)
    return np.array_equal(existing_values, expected_values)


def _validate_audition(audition: dict[str, np.ndarray], sample_rate: int) -> None:
    if set(audition) != set(_BLIND_CODES) or sample_rate <= 0:
        raise ValueError("A/B/C stereo audition files and a positive sample rate are required")
    lengths = set()
    for code in _BLIND_CODES:
        stereo = audition[code]
        _require_stereo(stereo, code)
        if not np.all(np.isfinite(stereo)):
            raise ValueError("audition arrays must be finite")
        lengths.add(len(stereo))
    if len(lengths) != 1:
        raise ValueError("blind audition candidates must have equal sample counts")


def _require_stereo(values: np.ndarray, name: str) -> None:
    if values.ndim != 2 or values.shape[1] != 2:
        raise ValueError(f"{name} must be stereo shaped (samples, 2)")


def _validate_window_ids(window_ids: list[str]) -> list[str]:
    if len(window_ids) != len(set(window_ids)):
        raise ValueError("window identifiers must be unique")
    if any(not _SAFE_ID.fullmatch(window_id) for window_id in window_ids):
        raise ValueError("window identifiers must be traversal-safe")
    return list(window_ids)


def _gallery_document(speech: list[str], transitions: list[str]) -> str:
    sections = [_gallery_section(window_id, "Speech window") for window_id in speech]
    sections.extend(_gallery_section(window_id, "Transition excerpt") for window_id in transitions)
    return (
        "<!doctype html><meta charset=\"utf-8\"><title>Blind lecture candidates</title>"
        "<h1>Blind candidates</h1><p>Judge words and naturalness before noise.</p>"
        + "".join(sections)
    )


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "processing_fingerprint", "report_sha256", "blind_map_sha256", "metrics", "decisions", "shortlist",
        "evidence_ids",
    }
    if required - set(report):
        raise ValueError("gate report lacks immutable public evidence fields")
    public = {key: report[key] for key in required}
    if set(public["metrics"]) != set(_BLIND_CODES) or set(public["decisions"]) != set(_BLIND_CODES):
        raise ValueError("public metrics and decisions must use exactly A/B/C")
    if any(code not in _BLIND_CODES for code in public["shortlist"]):
        raise ValueError("public shortlist must use blind codes")
    _reject_identity_leaks(public)
    return public


def _reject_identity_leaks(value: Any, path: str = "report") -> None:
    identities = {"original", "adaptive-22", "adaptive-24"}
    forbidden_keys = {"candidate_id", "candidate_ids", "candidate_map", "blind_map", "identity_map"}
    if isinstance(value, str):
        if any(identity in value.casefold() for identity in identities):
            raise ValueError(f"candidate identity leaked in {path}")
    elif isinstance(value, dict):
        for key, item in value.items():
            if any(identity in str(key).casefold() for identity in identities) or str(key).lower() in forbidden_keys:
                raise ValueError(f"candidate identity field leaked in {path}")
            _reject_identity_leaks(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_identity_leaks(item, f"{path}[{index}]")


def _trusted_root(root: Path) -> Path:
    if ".." in root.parts:
        raise ValueError("trusted candidate root must be traversal-safe")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve(strict=True)


def _safe_destination(root: Path, path: Path) -> Path:
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("candidate evidence destination must be traversal-safe")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("candidate evidence destination escapes its trusted root") from error
    return resolved


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _as_bytes(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content


def _write_immutable_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError(f"refusing to replace existing evidence: {path}")
        return
    temporary = path.with_name(f".{path.name}.{hashlib.sha256(content).hexdigest()[:12]}.new")
    with temporary.open("xb") as handle:
        handle.write(content)
    try:
        os.link(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _artifact_matches(path: Path, expected: bytes) -> bool:
    if path.suffix.lower() != ".wav":
        return path.read_bytes() == expected
    with tempfile.TemporaryDirectory() as folder:
        candidate = Path(folder) / "expected.wav"
        candidate.write_bytes(expected)
        return _same_audio_content(path, candidate)


def _completion_matches_existing(marker: Path, expected: dict[str, Any], root: Path) -> bool:
    try:
        existing = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(existing, dict)
        or set(existing) != set(expected)
        or existing.get("schema_version") != expected.get("schema_version")
        or existing.get("blind_map_sha256") != expected.get("blind_map_sha256")
        or existing.get("provenance") != expected.get("provenance")
        or not isinstance(existing.get("artifacts"), dict)
        or set(existing["artifacts"]) != set(expected["artifacts"])
    ):
        return False
    for relative, digest in existing["artifacts"].items():
        path = root / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            return False
    return True


def _validate_audition_windows(windows: dict[str, dict[str, np.ndarray]], sample_rate: int) -> None:
    for audition in windows.values():
        _validate_audition(audition, sample_rate)


def _gallery_section(window_id: str, role: str) -> str:
    escaped_id = html.escape(window_id)
    players = "".join(
        f'<label>{code}<audio controls preload="metadata" src="{escaped_id}/{code}.wav"></audio></label>'
        for code in _BLIND_CODES
    )
    return f"<section data-role=\"{role}\"><h2>{escaped_id}</h2>{players}</section>"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def _write_immutable_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"refusing to replace existing evidence: {path}")
        return
    temporary = path.with_name(f".{path.name}.{hashlib.sha256(encoded).hexdigest()[:12]}.new")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
        # A hard link is an atomic create: a concurrently-created artifact wins
        # without this writer replacing it.
        os.link(temporary, path)
        temporary.unlink()
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise
