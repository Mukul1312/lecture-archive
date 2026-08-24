"""Resumable, fail-closed orchestration for the YouTube lecture workflow.

Each command owns one immutable artifact transaction.  A manifest update is
the final state commit; complete evidence can be verified and adopted after a
crash, while partial, mismatched, extra, aliased, or symlinked evidence is
refused.  Candidate creation and full rendering remain separate commands so a
human blind-listening decision cannot be bypassed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import stat
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import soundfile as sf

from .candidates import build_candidate_arrays, write_candidate_artifacts
from .dfn import CachedDfnAdapter, DfnAdapter, build_render_context_key
from .diagnostics import (
    WindowFeature,
    run_diagnostics,
    transition_windows,
    write_original_review_material,
)
from .gates import (
    approve_candidate,
    canonical_evidence_hash,
    gate_evidence_hash,
    gate_report,
    score_candidate_windows,
)
from .loudness import export_matched_pair, normalize_two_pass, parse_loudnorm_json
from .manifest import (
    RenderNotApproved,
    candidate_context_fingerprint,
    read_json,
    render_approval_fingerprint,
    require_current_approval,
    write_json_atomic,
)
from .models import Segment, SegmentLabel
from .qa import collect_qa_report, publish_qa_pair, validate_delivery
from .render import crop_compensated, render_file
from .segments import (
    build_guarded_pause_mask,
    build_speech_mask,
    segments_from_json,
    validate_segment_map,
    write_mask_memmap,
)
from .source import (
    decode_float_stereo,
    from_mid_side,
    probe_audio,
    resolve_tool,
    sha256_file,
    stream_headroom_mid_side,
)


SAMPLE_RATE = 48_000
AUTHORITATIVE_SAMPLES = 131_864_451
REVIEW_WINDOW_SAMPLES = 30 * SAMPLE_RATE
GIB = 1024**3
DISK_SPACE_REQUIREMENTS = {
    "diagnose": 12 * GIB,
    "candidates": 8 * GIB,
    "render": 20 * GIB,
    "export": 8 * GIB,
    "qa": 1 * GIB,
}
# Three retained raw stereo candidates plus three retained audition stereo
# candidates: 6 arrays * 2 channels * float32 = 48 bytes per request sample.
CANDIDATE_MEMORY_BUDGET_BYTES = 1 * GIB
CANDIDATE_RETAINED_BYTES_PER_SAMPLE = 48

_FINAL_RUN_FILE_NAMES = {
    "adaptive.wav", "speech-mask.f32", "speech-render.wav", "pause-mask.f32",
    "pause-render.wav", "render-completion.json", "normalized-master.wav",
    "normalized-master-tp-corrected.wav", "Haladhara-lecture-enhanced.flac",
    "Haladhara-lecture-enhanced.mp3", "export-completion.json", "qa-report.json",
    "listening-checklist.md",
}

DEFAULT_PROCESSING = {
    "attenuation_db": None,
    "pause_treatment": "original",
    "candidate_attenuations_db": [22, 24],
    "sample_rate": SAMPLE_RATE,
    "core_samples": 11_520_000,
    "halo_samples": 96_000,
    "blend_samples": 5_760,
    "segment_fade_samples": 5_760,
    "pause_guard_samples": 12_000,
    "loudness_lufs": -16.0,
    "true_peak_dbtp": -1.5,
    "flac_bits": 24,
    "mp3_bitrate": 192_000,
}

_MANIFEST_BASE_KEYS = {
    "schema_version", "source", "versions", "processing", "working", "reports",
    "reference", "approval", "active_run_id", "preflight_space",
}
_MANIFEST_LATER_KEYS = {
    "candidate_context", "candidate_context_fingerprint", "candidate_evidence",
    "candidate_report_sha256", "selection", "segment_map_sha256", "render", "outputs", "qa",
}
_WORKSPACE_THREAD_LOCKS: dict[str, threading.Lock] = {}
_WORKSPACE_THREAD_LOCKS_GUARD = threading.Lock()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="enhance_youtube_lecture")
    subcommands = parser.add_subparsers(dest="command", required=True)
    diagnose = subcommands.add_parser("diagnose")
    diagnose.add_argument("--source", type=Path, required=True)
    diagnose.add_argument("--workspace", type=Path, required=True)
    diagnose.add_argument("--expected-sha256", required=True)
    candidates = subcommands.add_parser("candidates")
    candidates.add_argument("--workspace", type=Path, required=True)
    approve = subcommands.add_parser("approve")
    approve.add_argument("--workspace", type=Path, required=True)
    approve.add_argument("--blind-code", choices=("A", "B", "C"), required=True)
    approve.add_argument("--segments", type=Path, required=True)
    approve.add_argument("--pause", choices=("original", "approved-strong"), required=True)
    approve.add_argument("--reviewer", required=True)
    for name in ("render", "export", "qa"):
        command = subcommands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
    return parser


def _is_reparse_point(path: Path) -> bool:
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        return False
    attributes = getattr(value, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _assert_no_reparse_components(path: Path) -> None:
    absolute = Path(path).absolute()
    parts = absolute.parts
    cursor = Path(parts[0])
    for component in parts[1:]:
        if component == os.pardir:
            cursor = cursor.parent
            continue
        cursor = cursor / component
        if not os.path.lexists(cursor):
            continue
        if _is_reparse_point(cursor):
            raise RuntimeError(f"path contains a reparse point: {cursor}")


def _assert_lexically_within(workspace: Path, path: Path) -> None:
    root = os.path.normcase(os.path.abspath(workspace))
    candidate = os.path.normcase(os.path.abspath(path))
    try:
        common = os.path.commonpath((root, candidate))
    except ValueError as error:
        raise RuntimeError("path is on a different workspace volume") from error
    if common != root:
        raise RuntimeError("path escapes the workspace")


def _canonical_workspace(workspace: Path) -> Path:
    """Return one lexical absolute spelling after rejecting every existing reparse component."""
    spelling = Path(workspace).absolute()
    _assert_no_reparse_components(spelling)
    absolute = Path(os.path.abspath(os.fspath(spelling)))
    _assert_no_reparse_components(absolute)
    if os.path.lexists(absolute) and not absolute.is_dir():
        raise RuntimeError("workspace must be a real non-reparse directory")
    return absolute


def _safe_lock_path(workspace: Path) -> tuple[str, Path]:
    canonical = _canonical_workspace(workspace)
    key = os.path.normcase(os.fspath(canonical))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return key, Path(key).parent / f".youtube-enhance-{digest}.lock"


@contextmanager
def _workspace_lock(workspace: Path):
    workspace = _canonical_workspace(Path(workspace))
    key, lock_path = _safe_lock_path(workspace)
    _assert_no_reparse_components(lock_path.parent)
    with _WORKSPACE_THREAD_LOCKS_GUARD:
        thread_lock = _WORKSPACE_THREAD_LOCKS.setdefault(key, threading.Lock())
    with thread_lock:
        if os.path.lexists(lock_path) and _is_reparse_point(lock_path):
            raise RuntimeError("workspace lock must be a regular non-reparse file")
        with lock_path.open("a+b") as handle:
            opened = os.fstat(handle.fileno())
            named = os.lstat(lock_path)
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(opened, named):
                raise RuntimeError("workspace lock path changed while opening")
            if opened.st_size == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            try:
                _assert_no_reparse_components(workspace)
                yield workspace
            finally:
                handle.seek(0)
                unlock()


def _assert_safe_final_parent(workspace: Path, destination: Path) -> None:
    workspace = Path(workspace)
    destination = Path(destination)
    _assert_lexically_within(workspace, destination)
    _assert_no_reparse_components(workspace)
    _assert_no_reparse_components(destination.parent)
    root = workspace.resolve(strict=True)
    parent = destination.parent.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as error:
        raise RuntimeError("final publication parent resolves outside the workspace") from error
    if os.path.lexists(destination):
        raise FileExistsError(f"immutable final destination already exists: {destination}")


def _existing_volume_path(path: Path) -> Path:
    candidate = Path(path).resolve(strict=False)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise FileNotFoundError(f"cannot resolve volume for {path}")
        candidate = parent
    return candidate


def _check_free_space(workspace: Path, stage: str) -> dict[str, int]:
    required = DISK_SPACE_REQUIREMENTS[stage]
    observed = int(shutil.disk_usage(_existing_volume_path(workspace)).free)
    evidence = {"observed_free_bytes": observed, "required_free_bytes": required}
    if observed < required:
        raise RuntimeError(
            f"insufficient target-volume space for {stage}: "
            f"observed_free_bytes={observed}, required_free_bytes={required}"
        )
    return evidence


def _validated_space_evidence(value: Any, stage: str) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) != {"observed_free_bytes", "required_free_bytes"}
        or any(type(item) is not int or item < 0 for item in value.values())
        or value["required_free_bytes"] != DISK_SPACE_REQUIREMENTS[stage]
        or value["observed_free_bytes"] < value["required_free_bytes"]
    ):
        raise RuntimeError(f"{stage} completion has invalid disk-space provenance")
    return dict(value)


def _candidate_memory_evidence(requests: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    observed_samples = 0
    for request in requests:
        start, end = request.get("start_sample"), request.get("end_sample")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise RuntimeError("candidate memory request coordinates are malformed")
        observed_samples += end - start
    required = observed_samples * CANDIDATE_RETAINED_BYTES_PER_SAMPLE
    evidence = {
        "observed_request_samples": observed_samples,
        "retained_bytes_per_sample": CANDIDATE_RETAINED_BYTES_PER_SAMPLE,
        "required_retained_bytes": required,
        "budget_bytes": CANDIDATE_MEMORY_BUDGET_BYTES,
    }
    if required > CANDIDATE_MEMORY_BUDGET_BYTES:
        raise RuntimeError(
            "candidate retained-memory budget exceeded: "
            f"observed_request_samples={observed_samples}, "
            f"required_retained_bytes={required}, "
            f"budget_bytes={CANDIDATE_MEMORY_BUDGET_BYTES}"
        )
    return evidence


def _validated_candidate_memory_evidence(value: Any) -> dict[str, int]:
    keys = {
        "observed_request_samples", "retained_bytes_per_sample",
        "required_retained_bytes", "budget_bytes",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or any(type(item) is not int or item < 0 for item in value.values())
        or value["retained_bytes_per_sample"] != CANDIDATE_RETAINED_BYTES_PER_SAMPLE
        or value["budget_bytes"] != CANDIDATE_MEMORY_BUDGET_BYTES
        or value["required_retained_bytes"]
        != value["observed_request_samples"] * value["retained_bytes_per_sample"]
        or value["required_retained_bytes"] > value["budget_bytes"]
    ):
        raise RuntimeError("candidate completion has invalid retained-memory provenance")
    return dict(value)


def _first_version_line(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    lines = (result.stdout or result.stderr).splitlines()
    if not lines:
        raise RuntimeError(f"version command returned no text: {command[0]}")
    return lines[0].strip()


def _manifest_path(workspace: Path) -> Path:
    path = Path(workspace) / "manifest.json"
    if _is_reparse_point(path):
        raise RuntimeError("manifest must not be a reparse point")
    return path


def _exact_mapping(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RuntimeError(f"{label} schema is incomplete or extra")
    return value


def _canonical_sha(value: Any, *, lowercase: bool, label: str) -> str:
    pattern = r"[0-9a-f]{64}" if lowercase else r"[0-9A-F]{64}"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise RuntimeError(f"{label} must be canonical {'lowercase' if lowercase else 'uppercase'} SHA-256")
    return value


def _validate_manifest_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("manifest must be a JSON object")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise RuntimeError("manifest schema_version must be raw integer 1")
    keys = set(value)
    if not _MANIFEST_BASE_KEYS.issubset(keys) or not keys.issubset(
        _MANIFEST_BASE_KEYS | _MANIFEST_LATER_KEYS
    ):
        raise RuntimeError("manifest top-level schema is incomplete or extra")
    if not isinstance(value.get("preflight_space"), Mapping):
        raise RuntimeError("manifest preflight_space must be an object")

    candidate_keys = {
        "candidate_context", "candidate_context_fingerprint", "candidate_evidence",
        "candidate_report_sha256",
    }
    candidate_present = keys & candidate_keys
    if candidate_present and candidate_present != candidate_keys:
        raise RuntimeError("candidate manifest state is partial")
    approval = value.get("approval")
    approval_keys = {"selection", "segment_map_sha256"}
    if approval is None:
        if keys & approval_keys:
            raise RuntimeError("unapproved manifest contains stale selection state")
    elif not isinstance(approval, Mapping) or not approval_keys.issubset(keys) or not candidate_keys.issubset(keys):
        raise RuntimeError("approved manifest state is partial")
    return value


def _validate_manifest_stage_structure(manifest: Mapping[str, Any]) -> None:
    keys = set(manifest)
    candidate_keys = {
        "candidate_context", "candidate_context_fingerprint", "candidate_evidence",
        "candidate_report_sha256",
    }
    if candidate_keys.issubset(keys):
        _exact_mapping(manifest["candidate_context"], {
            "segment_map_sha256", "windows_reviewed_sha256", "transitions_sha256",
            "reviewed_transitions_sha256", "segments_proposed_sha256",
            "candidate_attenuations_db", "halo_policy",
        }, "candidate context")
        _exact_mapping(manifest["candidate_evidence"], {
            "root", "preflight_space", "report_evidence_sha256", "public_report_sha256",
            "completion_sha256", "private_map_sha256", "blind_map_sha256", "memory_budget",
        }, "candidate evidence")
        _canonical_sha(
            manifest["candidate_context_fingerprint"], lowercase=True,
            label="candidate context fingerprint",
        )
        _canonical_sha(
            manifest["candidate_report_sha256"], lowercase=False,
            label="candidate report physical hash",
        )
    if manifest.get("approval") is not None:
        if not candidate_keys.issubset(keys):
            raise RuntimeError("approval exists without candidate evidence")
        _exact_mapping(manifest["approval"], {
            "blind_code", "candidate_id", "pause_treatment", "reviewer", "approved_at",
            "fingerprint", "evidence_sha256",
        }, "approval")
        _exact_mapping(manifest.get("selection"), {
            "blind_code", "candidate_id", "pause_treatment",
        }, "selection")
        _canonical_sha(
            manifest.get("segment_map_sha256"), lowercase=False,
            label="reviewed segment physical hash",
        )
    if "render" in keys:
        _exact_mapping(manifest["render"], {
            "run_id", "adaptive_path", "adaptive_sha256", "samples", "chunk_boundaries",
            "completion_path", "completion_sha256", "reference_gain",
        }, "render manifest")
        if manifest.get("approval") is None or not isinstance(manifest.get("active_run_id"), str):
            raise RuntimeError("render exists without an approved active run")
    elif manifest.get("active_run_id") is not None:
        raise RuntimeError("active run exists without render state")
    if "outputs" in keys:
        _exact_mapping(manifest["outputs"], {
            "normalized_master", "delivery_master", "flac", "mp3",
            "normalized_master_sha256", "delivery_master_sha256", "flac_sha256",
            "mp3_sha256", "flac_metrics", "mp3_metrics", "completion_sha256",
        }, "export manifest")
        if "render" not in keys:
            raise RuntimeError("export exists without render state")
    if "qa" in keys:
        _exact_mapping(manifest["qa"], {
            "report_path", "checklist_path", "report_sha256", "checklist_sha256",
            "listening_status",
        }, "QA manifest")
        if "outputs" not in keys:
            raise RuntimeError("QA exists without export state")


def _load_manifest(workspace: Path) -> dict[str, Any]:
    value = read_json(_manifest_path(workspace))
    return _validate_manifest_schema(value)


def _workspace_leaf(workspace: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("workspace artifact path must be relative and traversal-safe")
    root = _canonical_workspace(workspace)
    logical = root / path
    cursor = root
    for component in path.parts:
        cursor = cursor / component
        if _is_reparse_point(cursor):
            raise RuntimeError(f"artifact path must not contain a reparse point: {cursor}")
    _assert_lexically_within(root, logical)
    return logical


def _relative(workspace: Path, path: Path) -> str:
    root = _canonical_workspace(workspace)
    candidate = Path(os.path.abspath(os.fspath(path)))
    _assert_lexically_within(root, candidate)
    _assert_no_reparse_components(candidate)
    return candidate.relative_to(root).as_posix()


def _artifact_record(workspace: Path, path: Path, *, channels: int | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"path": _relative(workspace, path), "sha256": sha256_file(path)}
    if channels is not None:
        info = sf.info(path)
        record.update(
            channels=channels,
            sample_rate=int(info.samplerate),
            frames=int(info.frames),
            subtype=info.subtype,
        )
    return record


def _verify_record(
    workspace: Path,
    record: Mapping[str, Any],
    *,
    frames: int | None = None,
    channels: int | None = None,
    subtype: str | None = None,
) -> Path:
    expected_keys = (
        {"path", "sha256"}
        if channels is None
        else {"path", "sha256", "channels", "sample_rate", "frames", "subtype"}
    )
    if (
        not isinstance(record, Mapping)
        or set(record) != expected_keys
        or not isinstance(record.get("path"), str)
        or not record["path"]
        or not isinstance(record.get("sha256"), str)
        or re.fullmatch(r"[0-9A-F]{64}", record["sha256"]) is None
    ):
        raise RuntimeError("artifact record is malformed")
    if channels is not None and (
        any(type(record.get(name)) is not int for name in ("channels", "sample_rate", "frames"))
        or record["channels"] <= 0
        or record["sample_rate"] <= 0
        or record["frames"] < 0
        or not isinstance(record.get("subtype"), str)
        or not record["subtype"]
    ):
        raise RuntimeError("audio artifact record metadata is malformed")
    path = _workspace_leaf(workspace, record["path"])
    if (
        not path.is_file()
        or _is_reparse_point(path)
        or sha256_file(path) != record["sha256"]
    ):
        raise RuntimeError(f"artifact hash validation failed: {path}")
    if channels is not None:
        info = sf.info(path)
        if (
            info.samplerate != SAMPLE_RATE
            or info.channels != channels
            or (frames is not None and info.frames != frames)
            or (subtype is not None and info.subtype != subtype)
            or record.get("channels") != channels
            or record.get("sample_rate") != SAMPLE_RATE
            or record.get("frames") != info.frames
            or record.get("subtype") != info.subtype
        ):
            raise RuntimeError(f"audio artifact format validation failed: {path}")
    return path


def _strict_segment_rows(path: Path) -> tuple[list[dict], list[Segment]]:
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError("segment map must be a JSON list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("segment rows must be JSON objects")
        if type(row.get("start_sample")) is not int or type(row.get("end_sample")) is not int:
            raise ValueError("segment coordinates must be raw JSON integers")
        if type(row.get("reviewed")) is not bool:
            raise ValueError("segment reviewed state must be a JSON boolean")
    return rows, segments_from_json(rows)


def _verify_diagnose_state(
    workspace: Path,
    manifest: Mapping[str, Any],
    *,
    expected_source: Path | None = None,
    expected_hash: str | None = None,
) -> None:
    _validate_manifest_schema(dict(manifest))
    _validate_manifest_stage_structure(manifest)
    source = manifest.get("source")
    source = _exact_mapping(source, {
        "path", "sha256", "bytes", "probe", "decoded_samples", "headroom_gain",
        "decoded_peak",
    }, "manifest source")
    if not isinstance(source["path"], str) or not source["path"]:
        raise RuntimeError("manifest source path is invalid")
    _canonical_sha(source["sha256"], lowercase=False, label="source physical hash")
    if type(source["bytes"]) is not int or source["bytes"] < 0 or not isinstance(source["probe"], dict):
        raise RuntimeError("manifest source byte/probe evidence is invalid")
    for name in ("headroom_gain", "decoded_peak"):
        item = source[name]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise RuntimeError(f"manifest source {name} is not a finite raw number")
    versions = _exact_mapping(manifest.get("versions"), {
        "deepfilternet", "model", "python", "numpy", "soundfile", "ffmpeg", "ffprobe",
    }, "version provenance")
    if any(not isinstance(item, str) or not item for item in versions.values()):
        raise RuntimeError("version provenance values must be non-empty strings")
    processing = _exact_mapping(manifest.get("processing"), set(DEFAULT_PROCESSING), "processing")
    integer_fields = {
        "sample_rate", "core_samples", "halo_samples", "blend_samples",
        "segment_fade_samples", "pause_guard_samples", "flac_bits", "mp3_bitrate",
    }
    if any(type(processing[name]) is not int for name in integer_fields):
        raise RuntimeError("processing integer values must be raw JSON integers")
    if processing["candidate_attenuations_db"] != [22, 24]:
        raise RuntimeError("candidate attenuation contract changed")
    attenuation = processing["attenuation_db"]
    if attenuation is not None and type(attenuation) is not int:
        raise RuntimeError("attenuation must be a raw integer or null")
    if processing["pause_treatment"] not in {"original", "approved-strong"}:
        raise RuntimeError("pause treatment is invalid")
    for name in ("loudness_lufs", "true_peak_dbtp"):
        item = processing[name]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise RuntimeError(f"processing {name} must be finite")
    source_path = Path(str(source.get("path", "")))
    if expected_source is not None and source_path.resolve() != expected_source.resolve():
        raise RuntimeError("workspace belongs to a different source path")
    if not source_path.is_file() or _is_reparse_point(source_path):
        raise RuntimeError("immutable source is missing or reparse-linked")
    current_hash = sha256_file(source_path)
    if current_hash != source.get("sha256") or (
        expected_hash is not None and current_hash != expected_hash.upper()
    ):
        raise RuntimeError("immutable source hash no longer matches manifest")
    if source_path.stat().st_size != source.get("bytes"):
        raise RuntimeError("immutable source byte count no longer matches manifest")
    total = source.get("decoded_samples")
    if type(total) is not int or total <= 0:
        raise RuntimeError("decoded sample count is invalid")

    preflight_space = manifest.get("preflight_space")
    if (
        not isinstance(preflight_space, Mapping)
        or "diagnose" not in preflight_space
        or not set(preflight_space).issubset(DISK_SPACE_REQUIREMENTS)
    ):
        raise RuntimeError("diagnose disk-space provenance is missing or contains an unknown stage")
    _validated_space_evidence(preflight_space["diagnose"], "diagnose")
    for stage in set(preflight_space) - {"diagnose"}:
        _validated_space_evidence(preflight_space[stage], stage)

    working = manifest.get("working")
    if not isinstance(working, Mapping) or set(working) != {
        "raw_stereo", "reference_stereo", "original_mid", "original_side"
    }:
        raise RuntimeError("working artifact set is incomplete or extra")
    raw = _verify_record(workspace, working["raw_stereo"], frames=total, channels=2, subtype="FLOAT")
    reference_stereo = _verify_record(
        workspace, working["reference_stereo"], frames=total, channels=2, subtype="FLOAT"
    )
    mid = _verify_record(workspace, working["original_mid"], frames=total, channels=1, subtype="FLOAT")
    side = _verify_record(workspace, working["original_side"], frames=total, channels=1, subtype="FLOAT")
    _assert_distinct_files([raw, reference_stereo, mid, side], "working")
    reference = manifest.get("reference")
    if not isinstance(reference, Mapping) or reference != {
        "representation": "headroom-adjusted-mid-side-v1",
        "source_sha256": source["sha256"],
        "headroom_gain": source["headroom_gain"],
        "reference_stereo_sha256": working["reference_stereo"]["sha256"],
        "original_mid_sha256": working["original_mid"]["sha256"],
        "original_side_sha256": working["original_side"]["sha256"],
    }:
        raise RuntimeError("headroom-adjusted reference binding is stale")

    reports = manifest.get("reports")
    if not isinstance(reports, Mapping) or set(reports) != {
        "diagnostics", "segments_proposed", "transitions", "original_review"
    }:
        raise RuntimeError("diagnostic report set is incomplete or extra")
    diagnostics_path = _verify_record(workspace, reports["diagnostics"])
    proposed_path = _verify_record(workspace, reports["segments_proposed"])
    transitions_path = _verify_record(workspace, reports["transitions"])
    diagnostics = read_json(diagnostics_path)
    expected_keys = {
        "schema_version", "integrity", "level", "noise_floor", "noise_spectrum",
        "tonal", "reverb", "bandwidth", "snr_by_band", "stereo",
        "window_features", "representative_windows", "recommendations",
    }
    if (
        not isinstance(diagnostics, dict)
        or set(diagnostics) != expected_keys
        or type(diagnostics.get("schema_version")) is not int
        or diagnostics["schema_version"] != 1
    ):
        raise RuntimeError("diagnostics schema is incomplete or extra")
    _, proposed = _strict_segment_rows(proposed_path)
    validate_segment_map(proposed, total, require_reviewed=False)
    if any(item.label not in {SegmentLabel.UNCERTAIN, SegmentLabel.GUARDED_PAUSE} for item in proposed):
        raise RuntimeError("automatic proposals authorized non-conservative processing")
    transitions = read_json(transitions_path)
    expected_transitions = transition_windows(proposed, total, radius_samples=6 * SAMPLE_RATE)
    if transitions != expected_transitions:
        raise RuntimeError("transition review coordinates are stale")
    review = reports["original_review"]
    if not isinstance(review, Mapping) or set(review) != {"index", "artifacts"}:
        raise RuntimeError("original review evidence is incomplete")
    index = _verify_record(workspace, review["index"])
    artifacts = review["artifacts"]
    if not isinstance(artifacts, list):
        raise RuntimeError("original review artifact index is malformed")
    verified = [index.resolve()]
    for record in artifacts:
        verified.append(_verify_record(workspace, record, channels=2).resolve())
    review_root = index.parent
    observed = {path.resolve() for path in review_root.iterdir() if path.is_file()}
    if observed != set(verified):
        raise RuntimeError("original review directory is partial or contains extra evidence")
    _assert_distinct_files(verified, "original review")


def _write_reference_stereo(mid_path: Path, side_path: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to overwrite working reference: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(mid_path) as mid, sf.SoundFile(side_path) as side:
        if (
            mid.samplerate != SAMPLE_RATE
            or side.samplerate != SAMPLE_RATE
            or mid.channels != 1
            or side.channels != 1
            or mid.frames != side.frames
        ):
            raise RuntimeError("headroom mid/side artifacts are not aligned")
        with sf.SoundFile(
            destination, "w", samplerate=SAMPLE_RATE, channels=2, subtype="FLOAT"
        ) as output:
            while True:
                mid_values = mid.read(262_144, dtype="float32")
                side_values = side.read(262_144, dtype="float32")
                if len(mid_values) != len(side_values):
                    raise RuntimeError("headroom mid/side reconstruction lost alignment")
                if not len(mid_values):
                    break
                output.write(from_mid_side(mid_values, side_values))
    info = sf.info(destination)
    if info.frames != sf.info(mid_path).frames or info.channels != 2 or info.samplerate != SAMPLE_RATE or info.subtype != "FLOAT":
        raise RuntimeError("headroom stereo reconstruction changed format or sample count")


def run_diagnose(args: argparse.Namespace) -> None:
    with _workspace_lock(Path(args.workspace)) as workspace:
        locked_args = argparse.Namespace(**vars(args))
        locked_args.workspace = workspace
        _run_diagnose_locked(locked_args)


def _run_diagnose_locked(args: argparse.Namespace) -> None:
    if _is_reparse_point(args.source) or not args.source.is_file():
        raise RuntimeError("immutable source must be a regular non-reparse file")
    source_hash = sha256_file(args.source)
    if source_hash != args.expected_sha256.upper():
        raise RuntimeError(
            f"source hash mismatch: expected {args.expected_sha256.upper()}, got {source_hash}"
        )
    workspace = Path(args.workspace)
    if _is_reparse_point(workspace):
        raise RuntimeError("workspace root must not be a reparse point")
    manifest_path = _manifest_path(workspace)
    if manifest_path.exists():
        manifest = _load_manifest(workspace)
        _verify_diagnose_state(
            workspace,
            manifest,
            expected_source=args.source,
            expected_hash=args.expected_sha256,
        )
        return
    if workspace.exists() and any(workspace.iterdir()):
        raise RuntimeError("diagnose workspace is partial or contains extra files")
    space = _check_free_space(workspace, "diagnose")
    ffmpeg = resolve_tool("ffmpeg")
    ffprobe = resolve_tool("ffprobe")
    deepfilter = Path(".venv/Scripts/deepFilter.exe").resolve()
    if not deepfilter.is_file():
        raise FileNotFoundError(deepfilter)
    probe = probe_audio(args.source, ffprobe)
    streams = probe.get("streams", [])
    if len(streams) != 1:
        raise RuntimeError("expected exactly one selected audio stream")
    stream = streams[0]
    if (
        stream.get("codec_name") != "opus"
        or stream.get("sample_rate") != "48000"
        or type(stream.get("channels")) is not int
        or stream["channels"] != 2
    ):
        raise RuntimeError("expected the verified 48 kHz stereo Opus stream")
    work = workspace / "work"
    raw_stereo = work / "decoded-raw.wav"
    reference_stereo = work / "reference-stereo.wav"
    original_mid = work / "original-mid.wav"
    original_side = work / "original-side.wav"
    decode_float_stereo(args.source, raw_stereo, ffmpeg)
    decode = stream_headroom_mid_side(raw_stereo, original_mid, original_side)
    if type(decode.get("samples")) is not int or decode["samples"] != AUTHORITATIVE_SAMPLES:
        raise RuntimeError(
            f"decoded sample count changed: {decode.get('samples')} != {AUTHORITATIVE_SAMPLES}"
        )
    diagnostics_path = workspace / "analysis" / "diagnostics.json"
    _write_reference_stereo(original_mid, original_side, reference_stereo)
    diagnostics = run_diagnostics(reference_stereo, original_mid, ffmpeg, diagnostics_path)
    proposed_path = workspace / "analysis" / "segments-proposed.json"
    transitions_path = workspace / "analysis" / "transitions.json"
    _, proposed = _strict_segment_rows(proposed_path)
    validate_segment_map(proposed, AUTHORITATIVE_SAMPLES, require_reviewed=False)
    transitions = read_json(transitions_path)
    if transitions != transition_windows(
        proposed, AUTHORITATIVE_SAMPLES, radius_samples=6 * SAMPLE_RATE
    ):
        raise RuntimeError("Task 6 transition evidence is incomplete")
    representatives = [WindowFeature(**row) for row in diagnostics["representative_windows"]]
    review_root = workspace / "analysis" / "review-original"
    review = write_original_review_material(
        reference_stereo, representatives, transitions, review_root
    )
    versions = {
        "python": _first_version_line([str(Path(".venv/Scripts/python.exe")), "--version"]),
        "ffmpeg": _first_version_line([ffmpeg, "-version"]),
        "ffprobe": _first_version_line([ffprobe, "-version"]),
        "deepfilternet": importlib.metadata.version("DeepFilterNet"),
        "model": _first_version_line([str(deepfilter), "--version"]),
        "numpy": importlib.metadata.version("numpy"),
        "soundfile": importlib.metadata.version("soundfile"),
    }
    artifact_paths = sorted({review_root / row["file"] for row in review["artifacts"]})
    manifest = {
        "schema_version": 1,
        "source": {
            "path": str(args.source.resolve()),
            "sha256": source_hash,
            "bytes": args.source.stat().st_size,
            "probe": probe,
            "decoded_samples": decode["samples"],
            "headroom_gain": float(decode["headroom_gain"]),
            "decoded_peak": float(decode["decoded_peak"]),
        },
        "versions": versions,
        "processing": dict(DEFAULT_PROCESSING),
        "working": {
            "raw_stereo": _artifact_record(workspace, raw_stereo, channels=2),
            "reference_stereo": _artifact_record(workspace, reference_stereo, channels=2),
            "original_mid": _artifact_record(workspace, original_mid, channels=1),
            "original_side": _artifact_record(workspace, original_side, channels=1),
        },
        "reports": {
            "diagnostics": _artifact_record(workspace, diagnostics_path),
            "segments_proposed": _artifact_record(workspace, proposed_path),
            "transitions": _artifact_record(workspace, transitions_path),
            "original_review": {
                "index": _artifact_record(workspace, review_root / "index.html"),
                "artifacts": [
                    _artifact_record(workspace, path, channels=2) for path in artifact_paths
                ],
            },
        },
        "reference": {
            "representation": "headroom-adjusted-mid-side-v1",
            "source_sha256": source_hash,
            "headroom_gain": float(decode["headroom_gain"]),
            "reference_stereo_sha256": sha256_file(reference_stereo),
            "original_mid_sha256": sha256_file(original_mid),
            "original_side_sha256": sha256_file(original_side),
        },
        "approval": None,
        "active_run_id": None,
        "preflight_space": {"diagnose": space},
    }
    write_json_atomic(manifest_path, manifest)


def _validate_reviewed_windows(
    rows: Any, total_samples: int, diagnostic_windows: Any
) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("reviewed candidate windows are required")
    if not isinstance(diagnostic_windows, list) or not diagnostic_windows:
        raise ValueError("diagnostic representative windows are required")
    expected: dict[tuple[str, str], tuple[int, int]] = {}
    for diagnostic in diagnostic_windows:
        if (
            not isinstance(diagnostic, dict)
            or type(diagnostic.get("start_sample")) is not int
            or not isinstance(diagnostic.get("window_id"), str)
            or not isinstance(diagnostic.get("role"), str)
        ):
            raise ValueError("diagnostic representative window schema is malformed")
        window_id = diagnostic["window_id"]
        role = diagnostic["role"]
        start = diagnostic["start_sample"]
        identity = (window_id, role)
        if identity in expected or start < 0 or start >= total_samples:
            raise ValueError("diagnostic representative window identity is invalid")
        expected[identity] = (start, min(total_samples, start + REVIEW_WINDOW_SAMPLES))
    output = _validated_reviewed_window_rows(rows, total_samples)
    identities = {(row["window_id"], row["role"]) for row in output}
    for row in output:
        identity = (row["window_id"], row["role"])
        if identity not in expected or (row["start_sample"], row["end_sample"]) != expected[identity]:
            raise ValueError("reviewed windows must exactly match diagnostic representatives")
    if identities != set(expected):
        raise ValueError("reviewed windows must cover every diagnostic representative exactly once")
    return output


def _validated_reviewed_window_rows(rows: Any, total_samples: int) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("reviewed candidate windows are required")
    output = []
    identities = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {
                "window_id", "start_sample", "end_sample", "reviewed_label", "role", "reviewed"
            }
            or type(row.get("reviewed")) is not bool
            or not row["reviewed"]
        ):
            raise ValueError("candidate windows must be explicitly reviewed")
        if type(row.get("start_sample")) is not int or type(row.get("end_sample")) is not int:
            raise ValueError("candidate window coordinates must be raw integers")
        start, end = row["start_sample"], row["end_sample"]
        if start < 0 or end <= start or end > total_samples:
            raise ValueError("candidate window coordinates are out of range")
        window_id = row.get("window_id")
        if not isinstance(window_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", window_id):
            raise ValueError("candidate window ID is unsafe")
        role = row.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError("candidate window role is missing")
        identity = (window_id, role)
        if identity in identities:
            raise ValueError("candidate window composite identities must be unique")
        identities.add(identity)
        SegmentLabel(row.get("reviewed_label"))
        output.append({**row, "artifact_id": _candidate_artifact_id(window_id, role)})
    ordered = sorted(output, key=lambda row: (row["start_sample"], row["end_sample"]))
    for left, right in zip(ordered, ordered[1:]):
        if right["start_sample"] < left["end_sample"] and not (
            right["window_id"] == left["window_id"]
            and right["start_sample"] == left["start_sample"]
            and right["end_sample"] == left["end_sample"]
        ):
            raise ValueError("distinct candidate source windows must not overlap")
    return output


def _candidate_artifact_id(window_id: str, role: str) -> str:
    if (
        not isinstance(window_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", window_id) is None
        or not isinstance(role, str)
        or not role
    ):
        raise ValueError("candidate artifact identity requires a safe window ID and role")
    safe_role = re.sub(r"[^A-Za-z0-9._-]+", "-", role).strip(".-") or "role"
    digest = hashlib.sha256(
        json.dumps([window_id, role], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"{window_id}--{safe_role[:48]}--{digest}"


def _valid_candidate_evidence_map(value: Any, artifact_ids: set[str]) -> bool:
    if not isinstance(value, dict) or set(value) != artifact_ids:
        return False
    for artifact_id, identity in value.items():
        if (
            not isinstance(identity, dict)
            or set(identity) != {"window_id", "role", "kind"}
            or any(not isinstance(item, str) or not item for item in identity.values())
            or identity["kind"] not in {"window", "transition"}
        ):
            return False
        try:
            if artifact_id != _candidate_artifact_id(identity["window_id"], identity["role"]):
                return False
        except ValueError:
            return False
    return True


def _candidate_requests(
    windows: Sequence[Mapping[str, Any]], segments: list[Segment], total_samples: int
) -> list[dict[str, Any]]:
    requests = [
        {
            "window_id": row["artifact_id"],
            "source_window_id": row["window_id"],
            "role": row["role"],
            "start_sample": row["start_sample"],
            "end_sample": row["end_sample"],
            "kind": "window",
            "reviewed_label": row["reviewed_label"],
        }
        for row in windows
    ]
    requests.extend(
        {
            "window_id": _candidate_artifact_id(
                f"transition-{row['boundary_sample']}",
                f"transition_{row['from']}_to_{row['to']}",
            ),
            "source_window_id": f"transition-{row['boundary_sample']}",
            "role": f"transition_{row['from']}_to_{row['to']}",
            "start_sample": row["start_sample"],
            "end_sample": row["end_sample"],
            "kind": "transition",
            "boundary_sample": row["boundary_sample"],
        }
        for row in transition_windows(
            segments, total_samples, radius_samples=6 * SAMPLE_RATE
        )
    )
    if len({row["window_id"] for row in requests}) != len(requests):
        raise RuntimeError("candidate and transition review IDs collide")
    return requests


def _current_candidate_requests(
    workspace: Path, manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    context = manifest.get("candidate_context")
    if not isinstance(context, Mapping):
        raise RuntimeError("candidate request ledger lacks its hash-bound context")
    segment_path = _workspace_leaf(workspace, "analysis/segments-reviewed.json")
    windows_path = _workspace_leaf(workspace, "analysis/windows-reviewed.json")
    if (
        _is_reparse_point(segment_path)
        or _is_reparse_point(windows_path)
        or not segment_path.is_file()
        or not windows_path.is_file()
        or sha256_file(segment_path) != context.get("segment_map_sha256")
        or sha256_file(windows_path) != context.get("windows_reviewed_sha256")
    ):
        raise RuntimeError("candidate request ledger is missing, reparse-linked, or stale")
    _, segments = _strict_segment_rows(segment_path)
    total_samples = manifest["source"]["decoded_samples"]
    validate_segment_map(segments, total_samples, require_reviewed=True)
    windows = _validated_reviewed_window_rows(read_json(windows_path), total_samples)
    requests = _candidate_requests(windows, segments, total_samples)
    reviewed_transitions = transition_windows(
        segments, total_samples, radius_samples=6 * SAMPLE_RATE
    )
    if context.get("reviewed_transitions_sha256") != canonical_evidence_hash(
        {"transitions": reviewed_transitions}
    ):
        raise RuntimeError("candidate request transition ledger is stale")
    return requests


def _slice_segments(segments: list[Segment], start: int, end: int) -> list[Segment]:
    output = []
    for item in segments:
        left, right = max(start, item.start_sample), min(end, item.end_sample)
        if right > left:
            output.append(
                Segment(left - start, right - start, item.label, item.reviewed, item.notes)
            )
    validate_segment_map(output, end - start, require_reviewed=True)
    return output


def _read_mono(path: Path, start: int, count: int) -> np.ndarray:
    with sf.SoundFile(path) as audio:
        if audio.samplerate != SAMPLE_RATE or audio.channels != 1:
            raise RuntimeError("candidate source must be 48 kHz mono")
        audio.seek(start)
        values = audio.read(count, dtype="float32", always_2d=False)
    if values.ndim != 1 or len(values) != count:
        raise RuntimeError(f"candidate read was truncated: {path}")
    return values


def _read_real_context(path: Path, start: int, end: int, total: int, halo: int) -> np.ndarray:
    read_start, read_end = max(0, start - halo), min(total, end + halo)
    values = _read_mono(path, read_start, read_end - read_start)
    left_pad, right_pad = max(0, halo - start), max(0, end + halo - total)
    if left_pad or right_pad:
        values = np.pad(values, (left_pad, right_pad), mode="reflect" if len(values) > 1 else "edge")
    if len(values) != (end - start) + 2 * halo:
        raise RuntimeError("candidate contextual halo changed requested coordinates")
    return values.astype(np.float32, copy=False)


def _render_versions(manifest: Mapping[str, Any]) -> dict[str, str]:
    versions = manifest["versions"]
    return {
        key: versions[key]
        for key in ("deepfilternet", "model", "python", "numpy", "soundfile", "ffmpeg")
    }


def _candidate_enhancers(manifest: Mapping[str, Any]) -> dict[int, CachedDfnAdapter]:
    executable = Path(".venv/Scripts/deepFilter.exe").resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    context = manifest["candidate_context"]
    processing = manifest["processing"]
    versions = _render_versions(manifest)
    result = {}
    for attenuation in (22, 24):
        key = build_render_context_key(
            manifest["source"]["sha256"],
            manifest["working"]["original_mid"]["sha256"],
            attenuation,
            SAMPLE_RATE,
            int(processing["core_samples"]),
            int(processing["halo_samples"]),
            int(processing["blend_samples"]),
            context["segment_map_sha256"],
            versions,
        )
        result[attenuation] = CachedDfnAdapter(
            DfnAdapter(str(executable), versions["model"]),
            {"render_context_key": key, "stage": "candidate"},
            versions,
        )
    return result


def _candidate_run_root(workspace: Path, manifest: Mapping[str, Any]) -> Path:
    fingerprint = manifest.get("candidate_context_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise RuntimeError("candidate context fingerprint must be canonical lowercase SHA-256")
    return _workspace_leaf(workspace, f"candidate-runs/{fingerprint}")


def _candidate_paths_present(run_root: Path) -> bool:
    return run_root.exists() or run_root.is_symlink()


def _reject_legacy_candidate_paths(workspace: Path) -> None:
    legacy = (workspace / "candidate-map.private.json", workspace / "candidates")
    if any(path.exists() or path.is_symlink() for path in legacy):
        raise RuntimeError("unversioned candidate evidence is stale and must not be reused")


def _assert_distinct_files(paths: Sequence[Path], stage: str) -> None:
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise RuntimeError(f"{stage} artifact paths alias")
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            if os.path.samefile(left, right):
                raise RuntimeError(f"{stage} artifact files alias")


def _reject_unknown_final_entries(run_directory: Path) -> None:
    if _is_reparse_point(run_directory) or not run_directory.is_dir():
        raise RuntimeError("final run must be a real non-reparse directory")
    for path in run_directory.iterdir():
        if path.name not in _FINAL_RUN_FILE_NAMES or _is_reparse_point(path) or not path.is_file():
            raise RuntimeError(f"unexpected final-run artifact: {path}")


def _verify_single_final_run(workspace: Path, run_id: str) -> Path:
    final_root = Path(workspace) / "final"
    if _is_reparse_point(final_root) or not final_root.is_dir():
        raise RuntimeError("final root must be a real non-reparse directory")
    _assert_no_reparse_components(final_root)
    entries = list(final_root.iterdir())
    if len(entries) != 1 or entries[0].name != run_id:
        raise RuntimeError("final root contains an extra, missing, or unrelated run")
    run_directory = entries[0]
    if _is_reparse_point(run_directory) or not run_directory.is_dir():
        raise RuntimeError("active final run must be a real non-reparse directory")
    return run_directory


def _derive_candidate_evidence(
    workspace: Path, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    run_root = _candidate_run_root(workspace, manifest)
    private_path = run_root / "candidate-map.private.json"
    report_path = run_root / "candidates" / "candidate-report.json"
    completion_path = run_root / "candidates" / "completion.json"
    for path in (private_path, report_path, completion_path):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("candidate evidence is partial or symlinked")
    completion = read_json(completion_path)
    completion = _exact_mapping(completion, {
        "schema_version", "blind_map_sha256", "artifacts", "provenance",
    }, "candidate completion")
    artifacts = completion["artifacts"]
    provenance = completion["provenance"]
    expected_provenance = {
        "candidate_context_fingerprint": manifest["candidate_context_fingerprint"],
        "preflight_space": provenance.get("preflight_space") if isinstance(provenance, dict) else None,
        "memory_budget": provenance.get("memory_budget") if isinstance(provenance, dict) else None,
    }
    if (
        type(completion["schema_version"]) is not int
        or completion["schema_version"] != 1
        or not isinstance(artifacts, dict)
        or provenance != expected_provenance
    ):
        raise RuntimeError("candidate completion marker is malformed")
    candidate_space = _validated_space_evidence(provenance["preflight_space"], "candidates")
    memory_budget = _validated_candidate_memory_evidence(provenance["memory_budget"])
    expected_memory_budget = _candidate_memory_evidence(
        _current_candidate_requests(workspace, manifest)
    )
    if memory_budget != expected_memory_budget:
        raise RuntimeError(
            "candidate completion retained-memory provenance does not match "
            "the current request ledger"
        )
    expected_files = {_workspace_leaf(run_root, relative).resolve() for relative in artifacts}
    expected_files.add(completion_path.resolve())
    observed_files = {
        path.resolve()
        for path in run_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed_files != expected_files:
        raise RuntimeError("candidate evidence is partial, extra, or aliased")
    _assert_distinct_files(sorted(observed_files), "candidate")
    for relative, expected_hash in artifacts.items():
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise RuntimeError("candidate completion hashes must be canonical lowercase SHA-256")
        path = _workspace_leaf(run_root, relative)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("candidate artifact is missing or symlinked")
        if sha256_file(path).casefold() != str(expected_hash).casefold():
            raise RuntimeError(f"candidate artifact hash changed: {path}")
    private_wrapper = read_json(private_path)
    public = read_json(report_path)
    private_evidence = (
        private_wrapper.get("evidence_map") if isinstance(private_wrapper, dict) else None
    )
    artifact_ids = {
        Path(relative).parts[1]
        for relative in artifacts
        if len(Path(relative).parts) == 3
        and Path(relative).parts[0] == "candidates"
        and Path(relative).name in {"A.wav", "B.wav", "C.wav"}
    }
    if (
        not isinstance(private_wrapper, dict)
        or set(private_wrapper) != {"source_hash", "blind_map", "evidence_map"}
        or not isinstance(public, dict)
        or private_wrapper.get("source_hash") != manifest["source"]["sha256"]
        or not isinstance(private_wrapper.get("blind_map"), dict)
        or not _valid_candidate_evidence_map(private_evidence, artifact_ids)
        or not isinstance(public.get("evidence_ids"), list)
        or any(not isinstance(item, str) or not item for item in public["evidence_ids"])
        or len(public["evidence_ids"]) != len(set(public["evidence_ids"]))
        or set(public["evidence_ids"]) != set(private_evidence)
        or public.get("processing_fingerprint") != manifest["candidate_context_fingerprint"]
        or gate_evidence_hash(public) != public.get("report_sha256")
        or canonical_evidence_hash(private_wrapper["blind_map"]) != public.get("blind_map_sha256")
        or completion.get("blind_map_sha256") != public.get("blind_map_sha256")
        or not re.fullmatch(r"[0-9a-f]{64}", str(public.get("report_sha256", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(public.get("blind_map_sha256", "")))
    ):
        raise RuntimeError("candidate report/map commitment is stale")
    return {
        "root": _relative(workspace, run_root),
        "preflight_space": candidate_space,
        "memory_budget": memory_budget,
        "report_evidence_sha256": public["report_sha256"],
        "public_report_sha256": sha256_file(report_path),
        "completion_sha256": sha256_file(completion_path),
        "private_map_sha256": sha256_file(private_path),
        "blind_map_sha256": public["blind_map_sha256"],
    }


def _candidate_context(
    workspace: Path,
    manifest: Mapping[str, Any],
    segment_path: Path,
    windows_path: Path,
    reviewed_segments: list[Segment],
    total_samples: int,
) -> dict[str, Any]:
    transitions_path = workspace / "analysis" / "transitions.json"
    if transitions_path.is_symlink() or not transitions_path.is_file():
        raise RuntimeError("Task 6 transitions are missing or symlinked")
    proposed_record = manifest.get("reports", {}).get("segments_proposed")
    proposed_hash = proposed_record.get("sha256") if isinstance(proposed_record, Mapping) else ""
    reviewed_transitions = transition_windows(
        reviewed_segments, total_samples, radius_samples=6 * SAMPLE_RATE
    )
    return {
        "segment_map_sha256": sha256_file(segment_path),
        "windows_reviewed_sha256": sha256_file(windows_path),
        "transitions_sha256": sha256_file(transitions_path),
        "reviewed_transitions_sha256": canonical_evidence_hash(
            {"transitions": reviewed_transitions}
        ),
        "segments_proposed_sha256": proposed_hash,
        "candidate_attenuations_db": [22, 24],
        "halo_policy": "real-source-neighbors-reflect-only-recording-boundaries-v1",
    }


def _invalidate_candidate_approval(manifest: dict[str, Any]) -> None:
    manifest["approval"] = None
    manifest.pop("selection", None)
    manifest.pop("segment_map_sha256", None)


def run_candidates(workspace: Path) -> None:
    with _workspace_lock(Path(workspace)) as workspace:
        _run_candidates_locked(workspace)


def _run_candidates_locked(workspace: Path) -> None:
    workspace = Path(workspace)
    manifest = _load_manifest(workspace)
    _verify_diagnose_state(workspace, manifest)
    total = manifest["source"]["decoded_samples"]
    segment_path = workspace / "analysis" / "segments-reviewed.json"
    windows_path = workspace / "analysis" / "windows-reviewed.json"
    if segment_path.is_symlink() or windows_path.is_symlink():
        raise RuntimeError("reviewed evidence must not be symlinked")
    _, segments = _strict_segment_rows(segment_path)
    validate_segment_map(segments, total, require_reviewed=True)
    diagnostics_record = manifest.get("reports", {}).get("diagnostics")
    diagnostics_path = _verify_record(workspace, diagnostics_record)
    diagnostics = read_json(diagnostics_path)
    if not isinstance(diagnostics, dict):
        raise RuntimeError("diagnostics report must be an object")
    windows = _validate_reviewed_windows(
        read_json(windows_path), total, diagnostics.get("representative_windows")
    )
    context = _candidate_context(
        workspace, manifest, segment_path, windows_path, segments, total
    )
    previous_context = manifest.get("candidate_context_fingerprint")
    manifest["candidate_context"] = context
    manifest["candidate_context_fingerprint"] = candidate_context_fingerprint(manifest)
    run_root = _candidate_run_root(workspace, manifest)
    _reject_legacy_candidate_paths(workspace)
    changed_context = previous_context != manifest["candidate_context_fingerprint"]

    downstream_present = any(key in manifest for key in ("render", "outputs", "qa")) or (
        manifest.get("active_run_id") is not None
    )
    if changed_context and downstream_present:
        raise RuntimeError("boundary changes after a full render require a new workflow workspace")

    if _candidate_paths_present(run_root):
        manifest["candidate_evidence"] = _derive_candidate_evidence(workspace, manifest)
        manifest["candidate_report_sha256"] = manifest["candidate_evidence"]["public_report_sha256"]
        if changed_context:
            _invalidate_candidate_approval(manifest)
        manifest.setdefault("preflight_space", {})["candidates"] = dict(
            manifest["candidate_evidence"]["preflight_space"]
        )
        if read_json(_manifest_path(workspace)) != manifest:
            write_json_atomic(_manifest_path(workspace), manifest)
        return

    space = _check_free_space(workspace, "candidates")
    halo = manifest["processing"]["halo_samples"]
    # Task 6 proposal transitions remain fingerprinted above, while blind
    # evidence follows the authoritative human-finalized processing map.
    requests = _candidate_requests(windows, segments, total)
    memory_budget = _candidate_memory_evidence(requests)
    enhancers = _candidate_enhancers(manifest)
    mid_path = _verify_record(
        workspace, manifest["working"]["original_mid"], frames=total, channels=1, subtype="FLOAT"
    )
    side_path = _verify_record(
        workspace, manifest["working"]["original_side"], frames=total, channels=1, subtype="FLOAT"
    )
    raw_by_window: dict[str, dict[str, np.ndarray]] = {}
    audition_by_window: dict[str, dict[str, np.ndarray]] = {}
    blind_map = None
    speech_ids = []
    speech_intervals = {}
    identity_anchor_intervals = set()
    transition_boundaries = {}
    for row in requests:
        start, end = row["start_sample"], row["end_sample"]
        count = end - start
        local_segments = _slice_segments(segments, start, end)
        mask = build_speech_mask(local_segments, count, manifest["processing"]["segment_fade_samples"])
        original_mid = _read_mono(mid_path, start, count)
        original_side = _read_mono(side_path, start, count)
        if np.any(mask):
            contextual = _read_real_context(mid_path, start, end, total, halo)
            rendered = {}
            for attenuation in (22, 24):
                processed = enhancers[attenuation].enhance(
                    contextual.copy(),
                    SAMPLE_RATE,
                    attenuation,
                    workspace / "work" / "candidates" / manifest["candidate_context_fingerprint"]
                    / row["window_id"] / f"atten{attenuation}",
                )
                rendered[attenuation] = crop_compensated(
                    processed.samples, halo, count, processed.latency_samples
                )
        else:
            rendered = {22: original_mid.copy(), 24: original_mid.copy()}
        raw, audition, current_map = build_candidate_arrays(
            manifest["source"]["sha256"],
            original_mid,
            original_side,
            mask,
            rendered[22],
            rendered[24],
        )
        if blind_map is not None and current_map != blind_map:
            raise RuntimeError("blind mapping changed between windows")
        blind_map = current_map
        raw_by_window[row["window_id"]] = raw
        audition_by_window[row["window_id"]] = audition
        if row["kind"] == "window" and row["reviewed_label"] == "main_speech":
            if not np.all(mask == 1.0):
                raise ValueError("main-speech identity windows must lie wholly inside finalized main speech")
            interval = (start, end)
            if interval not in identity_anchor_intervals:
                identity_anchor_intervals.add(interval)
                speech_ids.append(row["window_id"])
                speech_intervals[row["window_id"]] = interval
        if row["kind"] == "transition":
            transition_boundaries[row["window_id"]] = (row["boundary_sample"] - start,)
    metrics = score_candidate_windows(
        raw_by_window,
        speech_ids,
        SAMPLE_RATE,
        speech_intervals=speech_intervals,
        transition_windows=transition_boundaries,
    )
    report = gate_report(
        blind_map,
        metrics,
        SAMPLE_RATE,
        processing_fingerprint=manifest["candidate_context_fingerprint"],
        evidence_ids=[row["window_id"] for row in requests],
    )
    window_ids = [row["window_id"] for row in requests if row["kind"] == "window"]
    transition_ids = [row["window_id"] for row in requests if row["kind"] == "transition"]
    write_candidate_artifacts(
        run_root,
        manifest["source"]["sha256"],
        blind_map,
        report,
        window_ids,
        transition_window_ids=transition_ids,
        audition_by_window=audition_by_window,
        evidence_map={
            row["window_id"]: {
                "window_id": row["source_window_id"],
                "role": row["role"],
                "kind": row["kind"],
            }
            for row in requests
        },
        sample_rate=SAMPLE_RATE,
        completion_provenance={
            "candidate_context_fingerprint": manifest["candidate_context_fingerprint"],
            "preflight_space": space,
            "memory_budget": memory_budget,
        },
    )
    manifest["candidate_evidence"] = _derive_candidate_evidence(workspace, manifest)
    manifest["candidate_report_sha256"] = manifest["candidate_evidence"]["public_report_sha256"]
    if changed_context:
        _invalidate_candidate_approval(manifest)
    manifest.setdefault("preflight_space", {})["candidates"] = space
    write_json_atomic(_manifest_path(workspace), manifest)


def _verify_candidate_state(workspace: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("candidate_context_fingerprint") != candidate_context_fingerprint(manifest):
        raise RuntimeError("candidate context fingerprint is stale")
    evidence = _derive_candidate_evidence(workspace, manifest)
    if evidence != manifest.get("candidate_evidence"):
        raise RuntimeError("candidate artifact evidence no longer matches manifest")
    if manifest.get("candidate_report_sha256") != evidence["public_report_sha256"]:
        raise RuntimeError("candidate public report hash no longer matches manifest")
    return evidence


def run_approve(args: argparse.Namespace) -> None:
    with _workspace_lock(Path(args.workspace)) as workspace:
        locked_args = argparse.Namespace(**vars(args))
        locked_args.workspace = workspace
        _run_approve_locked(locked_args)


def _run_approve_locked(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace)
    manifest = _load_manifest(workspace)
    _verify_diagnose_state(workspace, manifest)
    evidence = _verify_candidate_state(workspace, manifest)
    canonical_segments = workspace / "analysis" / "segments-reviewed.json"
    if args.segments.is_symlink() or canonical_segments.is_symlink():
        raise RuntimeError("reviewed segment map must not be symlinked")
    _, canonical = _strict_segment_rows(canonical_segments)
    validate_segment_map(canonical, manifest["source"]["decoded_samples"], require_reviewed=True)
    _, segments = _strict_segment_rows(args.segments)
    validate_segment_map(segments, manifest["source"]["decoded_samples"], require_reviewed=True)
    if sha256_file(args.segments) != sha256_file(canonical_segments):
        raise RuntimeError("segment changes require a new candidate evidence run")
    segment_hash = sha256_file(canonical_segments)
    if segment_hash != manifest["candidate_context"]["segment_map_sha256"]:
        raise RuntimeError("segment changes require a new candidate evidence run")
    run_root = _candidate_run_root(workspace, manifest)
    private_wrapper = read_json(run_root / "candidate-map.private.json")
    private_map = private_wrapper["blind_map"]
    public = read_json(run_root / "candidates" / "candidate-report.json")
    internal_report = {**public, "blind_map": private_map}
    candidate_id = private_map[args.blind_code]
    attenuation = {"original": None, "adaptive-22": 22, "adaptive-24": 24}[candidate_id]
    selection = {
        "blind_code": args.blind_code,
        "candidate_id": candidate_id,
        "pause_treatment": args.pause,
    }
    if manifest.get("approval"):
        if manifest.get("selection") != selection:
            raise RuntimeError("immutable approval already records a different selection")
        if manifest["approval"].get("reviewer") != args.reviewer:
            raise RuntimeError("immutable approval already records a different reviewer")
        _verify_approved_state(workspace, manifest)
        return
    manifest["processing"]["attenuation_db"] = attenuation
    manifest["processing"]["pause_treatment"] = args.pause
    manifest["segment_map_sha256"] = segment_hash
    manifest["selection"] = selection
    fingerprint = render_approval_fingerprint(manifest)
    manifest["approval"] = approve_candidate(
        internal_report,
        args.blind_code,
        args.pause,
        args.reviewer,
        fingerprint,
        private_blind_map=private_map,
        candidate_context_fingerprint=manifest["candidate_context_fingerprint"],
    )
    if manifest["approval"]["evidence_sha256"] != evidence["report_evidence_sha256"]:
        raise RuntimeError("approval did not bind canonical candidate evidence")
    write_json_atomic(_manifest_path(workspace), manifest)


def _verify_approved_state(workspace: Path, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    _verify_diagnose_state(workspace, manifest)
    evidence = _verify_candidate_state(workspace, manifest)
    segment_path = workspace / "analysis" / "segments-reviewed.json"
    _, segments = _strict_segment_rows(segment_path)
    validate_segment_map(segments, manifest["source"]["decoded_samples"], require_reviewed=True)
    if sha256_file(segment_path) != manifest.get("segment_map_sha256"):
        raise RenderNotApproved("reviewed segment map bytes changed after approval")
    approval = require_current_approval(manifest)
    approval = _exact_mapping(approval, {
        "blind_code", "candidate_id", "pause_treatment", "reviewer", "approved_at",
        "fingerprint", "evidence_sha256",
    }, "approval")
    selection = _exact_mapping(manifest.get("selection"), {
        "blind_code", "candidate_id", "pause_treatment",
    }, "selection")
    _canonical_sha(approval["fingerprint"], lowercase=True, label="approval fingerprint")
    _canonical_sha(approval["evidence_sha256"], lowercase=True, label="approval evidence hash")
    if any(not isinstance(approval[name], str) or not approval[name] for name in (
        "blind_code", "candidate_id", "pause_treatment", "reviewer", "approved_at"
    )):
        raise RenderNotApproved("approval string provenance is malformed")
    if (
        approval.get("blind_code") != selection.get("blind_code")
        or approval.get("candidate_id") != selection.get("candidate_id")
        or approval.get("pause_treatment") != selection.get("pause_treatment")
        or approval.get("evidence_sha256") != evidence["report_evidence_sha256"]
    ):
        raise RenderNotApproved("approval selection/evidence binding is stale")
    expected_attenuation = {
        "original": None,
        "adaptive-22": 22,
        "adaptive-24": 24,
    }.get(selection.get("candidate_id"))
    if (
        selection.get("candidate_id") not in {"original", "adaptive-22", "adaptive-24"}
        or manifest["processing"].get("attenuation_db") != expected_attenuation
        or manifest["processing"].get("pause_treatment") != selection.get("pause_treatment")
    ):
        raise RenderNotApproved("approved candidate and effective processing settings diverge")
    if selection.get("candidate_id") == "original" and selection.get("pause_treatment") != "original":
        raise RenderNotApproved("Original safety winner cannot invoke a separate DFN pause treatment")
    return approval


def _cached_enhancer(
    manifest: Mapping[str, Any], stage: str, attenuation_db: int | None
) -> CachedDfnAdapter:
    executable = Path(".venv/Scripts/deepFilter.exe").resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    versions = _render_versions(manifest)
    processing = manifest["processing"]
    context_key = build_render_context_key(
        manifest["source"]["sha256"],
        manifest["working"]["original_mid"]["sha256"],
        attenuation_db,
        SAMPLE_RATE,
        processing["core_samples"],
        processing["halo_samples"],
        processing["blend_samples"],
        manifest["segment_map_sha256"],
        versions,
    )
    return CachedDfnAdapter(
        DfnAdapter(str(executable), versions["model"]),
        {"render_context_key": context_key, "stage": stage},
        versions,
    )


def _render_completion(
    workspace: Path, run_directory: Path, manifest: Mapping[str, Any]
) -> tuple[dict[str, Any], Path]:
    completion_path = run_directory / "render-completion.json"
    if completion_path.is_symlink() or not completion_path.is_file():
        raise RuntimeError("render completion marker is missing or symlinked")
    completion = read_json(completion_path)
    completion = _exact_mapping(completion, {
        "schema_version", "approval_fingerprint", "source_sha256", "reference_gain",
        "run_id", "adaptive_path", "authoritative_samples", "chunk_boundaries",
        "preflight_space", "artifacts",
    }, "render completion")
    if type(completion["schema_version"]) is not int or completion["schema_version"] != 1:
        raise RuntimeError("render completion schema version is invalid")
    artifacts = completion["artifacts"]
    if not isinstance(artifacts, dict):
        raise RuntimeError("render completion artifacts must be an object")
    _canonical_sha(
        completion["approval_fingerprint"], lowercase=True,
        label="render approval fingerprint",
    )
    _canonical_sha(completion["source_sha256"], lowercase=False, label="render source hash")
    if (
        isinstance(completion["reference_gain"], bool)
        or not isinstance(completion["reference_gain"], (int, float))
        or not math.isfinite(completion["reference_gain"])
    ):
        raise RuntimeError("render completion reference gain is invalid")
    _validated_space_evidence(completion.get("preflight_space"), "render")
    run_id = run_directory.name
    canonical_adaptive = _relative(workspace, run_directory / "adaptive.wav")
    if (
        completion.get("run_id") != run_id
        or completion.get("adaptive_path") != canonical_adaptive
        or type(completion.get("authoritative_samples")) is not int
        or completion.get("authoritative_samples") != manifest["source"]["decoded_samples"]
    ):
        raise RuntimeError("render completion identity mapping is stale")
    expected_names = {"adaptive.wav", "speech-mask.f32"}
    if manifest["processing"]["attenuation_db"] is not None:
        expected_names.add("speech-render.wav")
    if manifest["processing"]["pause_treatment"] == "approved-strong":
        expected_names.update({"pause-mask.f32", "pause-render.wav"})
    if {Path(relative).name for relative in artifacts} != expected_names:
        raise RuntimeError("render completion does not contain the exact approved artifact set")
    if canonical_adaptive not in artifacts:
        raise RuntimeError("render completion does not bind the canonical adaptive artifact")
    boundaries = completion.get("chunk_boundaries")
    total = manifest["source"]["decoded_samples"]
    if (
        not isinstance(boundaries, list)
        or any(type(value) is not int or not 0 < value < total for value in boundaries)
        or boundaries != sorted(set(boundaries))
    ):
        raise RuntimeError("render chunk-boundary provenance is malformed")
    _reject_unknown_final_entries(run_directory)
    expected = {completion_path.resolve()}
    for relative, digest in artifacts.items():
        path = _workspace_leaf(workspace, relative)
        if (
            path.parent.resolve() != run_directory.resolve()
            or path.name not in {
                "adaptive.wav", "speech-mask.f32", "speech-render.wav",
                "pause-mask.f32", "pause-render.wav",
            }
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9A-F]{64}", digest)
        ):
            raise RuntimeError("render artifact manifest is malformed")
        expected.add(path.resolve())
        if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError("render artifact hash changed")
    observed_render_names = {
        "adaptive.wav", "speech-mask.f32", "speech-render.wav", "pause-mask.f32",
        "pause-render.wav", "render-completion.json",
    }
    observed = {
        path.resolve()
        for path in run_directory.iterdir()
        if path.name in observed_render_names and (path.is_file() or path.is_symlink())
    }
    if observed != expected:
        raise RuntimeError("render artifact set is partial or extra")
    _assert_distinct_files(sorted(expected), "render")
    return completion, completion_path


def _verify_render_state(workspace: Path, manifest: Mapping[str, Any]) -> None:
    render = manifest.get("render")
    run_id = manifest.get("active_run_id")
    run_id_path = Path(run_id) if isinstance(run_id, str) else None
    if (
        not isinstance(render, Mapping)
        or set(render) != {
            "run_id", "adaptive_path", "adaptive_sha256", "samples", "chunk_boundaries",
            "completion_path", "completion_sha256", "reference_gain",
        }
        or run_id_path is None
        or run_id_path.is_absolute()
        or len(run_id_path.parts) != 1
        or run_id_path.name != run_id
    ):
        raise RuntimeError("render state is missing")
    run_directory = _verify_single_final_run(workspace, run_id)
    completion, completion_path = _render_completion(workspace, run_directory, manifest)
    completion_space = _validated_space_evidence(completion.get("preflight_space"), "render")
    completion_hash = sha256_file(completion_path)
    if (
        completion.get("approval_fingerprint") != render_approval_fingerprint(manifest)
        or completion.get("source_sha256") != manifest["source"]["sha256"]
        or completion.get("reference_gain") != manifest["source"]["headroom_gain"]
        or manifest.get("preflight_space", {}).get("render") != completion_space
    ):
        raise RuntimeError("render completion provenance is stale")
    expected_render = {
        "run_id": completion["run_id"],
        "adaptive_path": completion["adaptive_path"],
        "adaptive_sha256": completion["artifacts"][completion["adaptive_path"]],
        "samples": completion["authoritative_samples"],
        "chunk_boundaries": completion["chunk_boundaries"],
        "completion_path": _relative(workspace, completion_path),
        "completion_sha256": completion_hash,
        "reference_gain": completion["reference_gain"],
    }
    if dict(render) != expected_render:
        raise RuntimeError("render manifest does not equal its immutable completion mapping")
    adaptive = _workspace_leaf(workspace, completion["adaptive_path"])
    info = sf.info(adaptive)
    if info.frames != manifest["source"]["decoded_samples"] or info.samplerate != SAMPLE_RATE or info.channels != 2 or info.subtype != "FLOAT":
        raise RuntimeError("adaptive render format changed")


def _recover_render(workspace: Path, manifest: dict[str, Any]) -> bool:
    if manifest.get("render") or manifest.get("active_run_id"):
        _verify_render_state(workspace, manifest)
        return True
    final_root = workspace / "final"
    if not final_root.exists():
        return False
    if _is_reparse_point(final_root) or not final_root.is_dir():
        raise RuntimeError("final render root must be a real non-reparse directory")
    _assert_no_reparse_components(final_root)
    fingerprint = render_approval_fingerprint(manifest)
    matches = []
    directories = list(final_root.iterdir())
    if len(directories) > 1:
        raise RuntimeError("final render root contains extra sibling state")
    for directory in directories:
        if _is_reparse_point(directory) or not directory.is_dir():
            raise RuntimeError("final render root contains an unexpected entry")
        marker = directory / "render-completion.json"
        marker_value = read_json(marker) if marker.is_file() and not _is_reparse_point(marker) else None
        if isinstance(marker_value, dict) and marker_value.get("approval_fingerprint") == fingerprint:
            matches.append(directory)
    if not matches:
        if any(final_root.iterdir()):
            raise RuntimeError("final render state is partial or belongs to different approval")
        return False
    if len(matches) != 1:
        raise RuntimeError("multiple render sets claim the same approval")
    completion, marker = _render_completion(workspace, matches[0], manifest)
    candidate_render = {
        "run_id": completion["run_id"],
        "adaptive_path": completion["adaptive_path"],
        "adaptive_sha256": completion["artifacts"][completion["adaptive_path"]],
        "samples": completion["authoritative_samples"],
        "chunk_boundaries": completion["chunk_boundaries"],
        "completion_path": _relative(workspace, marker),
        "completion_sha256": sha256_file(marker),
        "reference_gain": completion["reference_gain"],
    }
    proposed = dict(manifest)
    proposed["active_run_id"] = matches[0].name
    proposed["render"] = candidate_render
    proposed["preflight_space"] = dict(manifest.get("preflight_space", {}))
    proposed["preflight_space"]["render"] = dict(completion["preflight_space"])
    _verify_render_state(workspace, proposed)
    manifest["active_run_id"] = matches[0].name
    manifest["render"] = candidate_render
    manifest.setdefault("preflight_space", {})["render"] = dict(completion["preflight_space"])
    write_json_atomic(_manifest_path(workspace), manifest)
    return True


def run_full_render(workspace: Path, manifest: dict) -> None:
    with _workspace_lock(Path(workspace)) as workspace:
        _run_full_render_locked(workspace, _load_manifest(workspace))


def _run_full_render_locked(workspace: Path, manifest: dict) -> None:
    workspace = Path(workspace)
    _verify_approved_state(workspace, manifest)
    final_root = workspace / "final"
    if _is_reparse_point(final_root):
        raise RuntimeError("final root must not be a reparse point")
    _assert_no_reparse_components(final_root)
    if _recover_render(workspace, manifest):
        return
    work_root = workspace / "work"
    if any(work_root.glob("render-stage-*")):
        raise RuntimeError("partial private render stage requires explicit cleanup")
    space = _check_free_space(workspace, "render")
    fingerprint = render_approval_fingerprint(manifest)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + fingerprint[:12]
    stage = work_root / f"render-stage-{run_id}"
    final_directory = workspace / "final" / run_id
    if stage.exists() or stage.is_symlink() or final_directory.exists() or final_directory.is_symlink():
        raise FileExistsError("immutable render destination already exists")
    stage.mkdir(parents=True)
    total = manifest["source"]["decoded_samples"]
    _, segments = _strict_segment_rows(workspace / "analysis" / "segments-reviewed.json")
    validate_segment_map(segments, total, require_reviewed=True)
    processing = manifest["processing"]
    mid_path = _verify_record(workspace, manifest["working"]["original_mid"], frames=total, channels=1, subtype="FLOAT")
    side_path = _verify_record(workspace, manifest["working"]["original_side"], frames=total, channels=1, subtype="FLOAT")
    speech_mask_path = write_mask_memmap(
        build_speech_mask(segments, total, processing["segment_fade_samples"]),
        stage / "speech-mask.f32",
    )
    attenuation = processing["attenuation_db"]
    speech_result = {"boundaries": []}
    if attenuation is None:
        speech_render = mid_path
    else:
        speech_render = stage / "speech-render.wav"
        speech_result = render_file(
            mid_path, speech_render, _cached_enhancer(manifest, "full-speech", attenuation),
            SAMPLE_RATE, attenuation, processing["core_samples"], processing["halo_samples"],
            processing["blend_samples"], workspace / "work" / "full-speech" / fingerprint,
        )
    pause_render = None
    pause_mask_path = None
    pause_result = {"boundaries": []}
    if processing["pause_treatment"] == "approved-strong":
        pause_render = stage / "pause-render.wav"
        pause_result = render_file(
            mid_path, pause_render, _cached_enhancer(manifest, "full-pause", None),
            SAMPLE_RATE, None, processing["core_samples"], processing["halo_samples"],
            processing["blend_samples"], workspace / "work" / "full-pause" / fingerprint,
        )
        pause_mask_path = write_mask_memmap(
            build_guarded_pause_mask(
                segments, total, processing["pause_guard_samples"], processing["segment_fade_samples"]
            ),
            stage / "pause-mask.f32",
        )
    adaptive = stage / "adaptive.wav"
    speech_weights = np.memmap(speech_mask_path, dtype=np.float32, mode="r", shape=(total,))
    pause_weights = (
        np.memmap(pause_mask_path, dtype=np.float32, mode="r", shape=(total,))
        if pause_mask_path is not None else None
    )
    with sf.SoundFile(mid_path) as original_mid, sf.SoundFile(side_path) as original_side, sf.SoundFile(speech_render) as processed_mid, sf.SoundFile(
        adaptive, "w", samplerate=SAMPLE_RATE, channels=2, subtype="FLOAT"
    ) as output:
        pause_file = sf.SoundFile(pause_render) if pause_render is not None else None
        try:
            cursor = 0
            while cursor < total:
                count = min(262_144, total - cursor)
                original = original_mid.read(count, dtype="float32")
                side = original_side.read(count, dtype="float32")
                processed = processed_mid.read(count, dtype="float32")
                if len(original) != count or len(side) != count or len(processed) != count:
                    raise RuntimeError("full render input was truncated")
                weight = speech_weights[cursor:cursor + count]
                selected = (
                    original.copy()
                    if manifest["selection"]["candidate_id"] == "original"
                    else original * (1.0 - weight) + processed * weight
                )
                if pause_file is not None:
                    pause = pause_file.read(count, dtype="float32")
                    if len(pause) != count:
                        raise RuntimeError("pause render was truncated")
                    pause_weight = pause_weights[cursor:cursor + count]
                    selected = selected * (1.0 - pause_weight) + pause * pause_weight
                output.write(from_mid_side(selected, side))
                cursor += count
        finally:
            if pause_file is not None:
                pause_file.close()
    # NumPy keeps the underlying Windows file mappings alive through the last
    # sliced view.  Release both the views and their roots before the stage
    # directory is renamed into its immutable final location.
    del weight
    del speech_weights
    if pause_weights is not None:
        del pause_weight
        del pause_weights
    info = sf.info(adaptive)
    if info.frames != total or info.samplerate != SAMPLE_RATE or info.channels != 2 or info.subtype != "FLOAT":
        raise RuntimeError("adaptive stereo reconstruction changed format or sample count")
    artifact_files = [path for path in stage.iterdir() if path.is_file()]
    artifacts = {
        f"final/{run_id}/{path.name}": sha256_file(path) for path in artifact_files
    }
    completion = {
        "schema_version": 1,
        "approval_fingerprint": fingerprint,
        "source_sha256": manifest["source"]["sha256"],
        "reference_gain": manifest["source"]["headroom_gain"],
        "run_id": run_id,
        "adaptive_path": f"final/{run_id}/adaptive.wav",
        "authoritative_samples": total,
        "chunk_boundaries": sorted(set(speech_result["boundaries"]) | set(pause_result["boundaries"])),
        "preflight_space": space,
        "artifacts": artifacts,
    }
    write_json_atomic(stage / "render-completion.json", completion)
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(stage) or not stage.is_dir():
        raise RuntimeError("render private stage changed before publication")
    _assert_no_reparse_components(stage)
    _assert_safe_final_parent(workspace, final_directory)
    os.rename(stage, final_directory)
    manifest["active_run_id"] = run_id
    manifest["render"] = {
        "run_id": run_id,
        "adaptive_path": completion["adaptive_path"],
        "adaptive_sha256": artifacts[completion["adaptive_path"]],
        "samples": completion["authoritative_samples"],
        "chunk_boundaries": completion["chunk_boundaries"],
        "completion_path": f"final/{run_id}/render-completion.json",
        "completion_sha256": sha256_file(final_directory / "render-completion.json"),
        "reference_gain": completion["reference_gain"],
    }
    manifest.setdefault("preflight_space", {})["render"] = space
    _verify_render_state(workspace, manifest)
    write_json_atomic(_manifest_path(workspace), manifest)


def _measure_loudness(ffmpeg: str, path: Path) -> dict[str, Any]:
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-i", str(path), "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:])
    values = parse_loudnorm_json(result.stderr)
    return {
        "integrated_lufs": float(values["input_i"]),
        "true_peak_dbtp": float(values["input_tp"]),
        "lra": float(values["input_lra"]),
        "decode_ok": True,
    }


def _stream_probe(ffprobe: str, path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    command = [
        ffprobe, "-v", "error", "-select_streams", "a:0", "-show_streams",
        "-show_format", "-of", "json", str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("streams"), list)
        or len(payload["streams"]) != 1
        or not isinstance(payload["streams"][0], dict)
        or not isinstance(payload.get("format"), dict)
    ):
        raise RuntimeError("delivery probe did not return one audio stream and format")
    return payload["streams"][0], payload["format"]


def _decoded_frames(ffmpeg: str, path: Path) -> int:
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-i", str(path),
        "-af", "astats=metadata=0:reset=0", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    matches = re.findall(r"Number of samples:\s*(\d+)", result.stderr)
    if result.returncode != 0 or not matches:
        raise RuntimeError(f"could not count decoded samples in {path}")
    return int(matches[-1])


def _measure_delivery(ffmpeg: str, ffprobe: str, path: Path, expected: int) -> dict[str, Any]:
    stream, container = _stream_probe(ffprobe, path)
    metrics = _measure_loudness(ffmpeg, path)
    suffix = path.suffix.lower()
    if suffix == ".flac":
        info = sf.info(path)
        metrics.update(
            sample_rate=int(info.samplerate), channels=int(info.channels), frames=int(info.frames),
            bits_per_raw_sample=_probe_decimal(stream.get("bits_per_raw_sample"), "bits_per_raw_sample"),
            codec_name=_probe_string(stream.get("codec_name"), "codec_name"),
            container_name=_probe_string(container.get("format_name"), "format_name"),
            bit_rate=0, codec_delay_padding_samples=0,
        )
    elif suffix == ".mp3":
        frames = _decoded_frames(ffmpeg, path)
        channels = stream.get("channels")
        if type(channels) is not int or channels < 0:
            raise RuntimeError("ffprobe channels must be a non-negative raw integer")
        metrics.update(
            sample_rate=_probe_decimal(stream.get("sample_rate"), "sample_rate"),
            channels=channels, frames=frames, bits_per_raw_sample=0,
            codec_name=_probe_string(stream.get("codec_name"), "codec_name"),
            container_name=_probe_string(container.get("format_name"), "format_name"),
            bit_rate=_probe_decimal(stream.get("bit_rate"), "bit_rate"),
            codec_delay_padding_samples=frames - expected,
        )
    else:
        raise RuntimeError("delivery measurement requires FLAC or MP3")
    return metrics


def _probe_decimal(value: Any, name: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is None:
        raise RuntimeError(f"ffprobe {name} must be an unsigned canonical decimal string")
    return int(value)


def _probe_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"ffprobe {name} must be a non-empty string")
    return value


def _publish_files(workspace: Path, stages: Mapping[Path, Path]) -> None:
    for destination in stages:
        _assert_safe_final_parent(workspace, destination)
        if os.path.lexists(destination):
            raise FileExistsError(f"refusing immutable stage overwrite: {destination}")
    made = []
    try:
        for destination, stage in stages.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            _assert_safe_final_parent(workspace, destination)
            if _is_reparse_point(stage) or not stage.is_file():
                raise RuntimeError("export private stage changed before publication")
            _assert_no_reparse_components(stage)
            os.link(stage, destination)
            made.append((destination, stage))
    except BaseException:
        for destination, stage in reversed(made):
            try:
                if os.path.samestat(os.stat(destination), os.stat(stage)):
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise


def _validate_persisted_delivery_metrics(
    metrics: Any, kind: str, expected_frames: int
) -> None:
    metrics = _exact_mapping(metrics, {
        "integrated_lufs", "true_peak_dbtp", "lra", "decode_ok", "sample_rate",
        "channels", "frames", "bits_per_raw_sample", "codec_name", "container_name",
        "bit_rate", "codec_delay_padding_samples",
    }, f"{kind} metrics")
    integer_names = {
        "sample_rate", "channels", "frames", "bits_per_raw_sample", "bit_rate",
        "codec_delay_padding_samples",
    }
    if any(type(metrics[name]) is not int or metrics[name] < 0 for name in integer_names):
        raise RuntimeError(f"{kind} metrics require non-negative raw integers")
    for name in ("integrated_lufs", "true_peak_dbtp", "lra"):
        item = metrics[name]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise RuntimeError(f"{kind} metrics require finite raw numbers")
    if (
        metrics["decode_ok"] is not True
        or metrics["sample_rate"] != SAMPLE_RATE
        or metrics["channels"] != 2
        or not -16.5 <= metrics["integrated_lufs"] <= -15.5
        or metrics["true_peak_dbtp"] > -1.5
    ):
        raise RuntimeError(f"{kind} decoded delivery contract failed")
    if kind == "FLAC":
        if (
            metrics["frames"] != expected_frames
            or metrics["bits_per_raw_sample"] != 24
            or metrics["codec_name"] != "flac"
            or metrics["container_name"] != "flac"
            or metrics["bit_rate"] != 0
            or metrics["codec_delay_padding_samples"] != 0
        ):
            raise RuntimeError("FLAC persisted format contract failed")
    elif (
        metrics["frames"] - expected_frames != metrics["codec_delay_padding_samples"]
        or not 0 <= metrics["codec_delay_padding_samples"] <= 1152
        or metrics["bits_per_raw_sample"] != 0
        or metrics["codec_name"] != "mp3"
        or metrics["container_name"] != "mp3"
        or abs(metrics["bit_rate"] - 192_000) > 3_000
    ):
        raise RuntimeError("MP3 persisted format contract failed")


def _verify_export_state(workspace: Path, manifest: Mapping[str, Any]) -> None:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        raise RuntimeError("export state is missing")
    run_directory = workspace / "final" / manifest["active_run_id"]
    _reject_unknown_final_entries(run_directory)
    marker = run_directory / "export-completion.json"
    if marker.is_symlink() or not marker.is_file() or sha256_file(marker) != outputs.get("completion_sha256"):
        raise RuntimeError("export completion marker changed")
    completion = read_json(marker)
    expected_completion_keys = {
        "schema_version", "render_completion_sha256", "preflight_space",
        "artifacts", "manifest_outputs",
    }
    completion = _exact_mapping(completion, expected_completion_keys, "export completion")
    if type(completion["schema_version"]) is not int or completion["schema_version"] != 1:
        raise RuntimeError("export completion marker is malformed")
    export_space = _validated_space_evidence(completion.get("preflight_space"), "export")
    if (
        completion.get("render_completion_sha256") != manifest["render"]["completion_sha256"]
        or manifest.get("preflight_space", {}).get("export") != export_space
    ):
        raise RuntimeError("export no longer binds the immutable render")
    expected_output_keys = {
        "normalized_master", "delivery_master", "flac", "mp3",
        "normalized_master_sha256", "delivery_master_sha256", "flac_sha256", "mp3_sha256",
        "flac_metrics", "mp3_metrics", "completion_sha256",
    }
    if set(outputs) != expected_output_keys:
        raise RuntimeError("export manifest output set is incomplete or extra")
    _validate_persisted_delivery_metrics(
        outputs["flac_metrics"], "FLAC", manifest["source"]["decoded_samples"]
    )
    _validate_persisted_delivery_metrics(
        outputs["mp3_metrics"], "MP3", manifest["source"]["decoded_samples"]
    )
    outputs_without_marker = {key: value for key, value in outputs.items() if key != "completion_sha256"}
    if completion.get("manifest_outputs") != outputs_without_marker:
        raise RuntimeError("export completion and manifest outputs diverge")
    expected_relatives = {
        outputs["normalized_master"], outputs["delivery_master"], outputs["flac"], outputs["mp3"]
    }
    artifacts = completion.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != expected_relatives:
        raise RuntimeError("export artifact set is incomplete or extra")
    expected_paths = [marker]
    for relative, digest in artifacts.items():
        path = _workspace_leaf(workspace, relative)
        if (
            path.parent.resolve() != run_directory.resolve()
            or path.name not in {
                "normalized-master.wav", "normalized-master-tp-corrected.wav",
                "Haladhara-lecture-enhanced.flac", "Haladhara-lecture-enhanced.mp3",
            }
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9A-F]{64}", digest)
            or path.is_symlink()
            or not path.is_file()
            or sha256_file(path) != digest
        ):
            raise RuntimeError("export artifact hash changed")
        expected_paths.append(path)
    observed_owned = {
        path.resolve()
        for path in run_directory.iterdir()
        if path.name in {
            "normalized-master.wav", "normalized-master-tp-corrected.wav",
            "Haladhara-lecture-enhanced.flac", "Haladhara-lecture-enhanced.mp3",
            "export-completion.json",
        }
        and (path.is_file() or path.is_symlink())
    }
    if observed_owned != {path.resolve() for path in expected_paths}:
        raise RuntimeError("export artifact set is incomplete or extra")
    _assert_distinct_files(expected_paths, "export")
    for key in ("normalized_master", "delivery_master", "flac", "mp3"):
        path = _workspace_leaf(workspace, outputs[key])
        if sha256_file(path) != outputs[f"{key}_sha256"]:
            raise RuntimeError(f"export state hash changed: {key}")


def _recover_export(workspace: Path, manifest: dict[str, Any]) -> bool:
    if manifest.get("outputs"):
        _verify_export_state(workspace, manifest)
        return True
    run_directory = workspace / "final" / manifest["active_run_id"]
    marker = run_directory / "export-completion.json"
    known = [
        run_directory / "normalized-master.wav",
        run_directory / "normalized-master-tp-corrected.wav",
        run_directory / "Haladhara-lecture-enhanced.flac",
        run_directory / "Haladhara-lecture-enhanced.mp3",
        marker,
    ]
    if not any(path.exists() or path.is_symlink() for path in known):
        return False
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("partial export set lacks a completion marker")
    completion = read_json(marker)
    completion = _exact_mapping(completion, {
        "schema_version", "render_completion_sha256", "preflight_space", "artifacts",
        "manifest_outputs",
    }, "export completion")
    if type(completion["schema_version"]) is not int or completion["schema_version"] != 1:
        raise RuntimeError("export completion marker is malformed")
    manifest_outputs = completion["manifest_outputs"]
    if not isinstance(manifest_outputs, dict):
        raise RuntimeError("export completion outputs must be an object")
    candidate_outputs = dict(manifest_outputs)
    candidate_outputs["completion_sha256"] = sha256_file(marker)
    export_space = _validated_space_evidence(completion.get("preflight_space"), "export")
    proposed = dict(manifest)
    proposed["outputs"] = candidate_outputs
    proposed["preflight_space"] = dict(manifest.get("preflight_space", {}))
    proposed["preflight_space"]["export"] = export_space
    _verify_export_state(workspace, proposed)
    manifest["outputs"] = candidate_outputs
    manifest.setdefault("preflight_space", {})["export"] = export_space
    write_json_atomic(_manifest_path(workspace), manifest)
    return True


def run_export(workspace: Path, manifest: dict) -> None:
    with _workspace_lock(Path(workspace)) as workspace:
        _run_export_locked(workspace, _load_manifest(workspace))


def _run_export_locked(workspace: Path, manifest: dict) -> None:
    workspace = Path(workspace)
    _verify_approved_state(workspace, manifest)
    _verify_render_state(workspace, manifest)
    if _recover_export(workspace, manifest):
        return
    space = _check_free_space(workspace, "export")
    run_id = manifest["active_run_id"]
    run_directory = workspace / "final" / run_id
    stage = workspace / "work" / f"export-stage-{run_id}"
    if stage.exists() or stage.is_symlink():
        raise RuntimeError("partial private export stage requires explicit cleanup")
    stage.mkdir(parents=True)
    adaptive = _workspace_leaf(workspace, manifest["render"]["adaptive_path"])
    expected = manifest["source"]["decoded_samples"]
    ffmpeg, ffprobe = resolve_tool("ffmpeg"), resolve_tool("ffprobe")
    normalized = stage / "normalized-master.wav"
    normalize_two_pass(ffmpeg, adaptive, normalized, expected)
    flac_stage = stage / "Haladhara-lecture-enhanced.flac"
    mp3_stage = stage / "Haladhara-lecture-enhanced.mp3"
    delivery = export_matched_pair(
        ffmpeg,
        normalized,
        flac_stage,
        mp3_stage,
        lambda path: _measure_delivery(ffmpeg, ffprobe, path, expected),
    )
    delivery_stage = Path(delivery["delivery_master"])
    destinations = {
        run_directory / "normalized-master.wav": normalized,
        run_directory / "Haladhara-lecture-enhanced.flac": flac_stage,
        run_directory / "Haladhara-lecture-enhanced.mp3": mp3_stage,
    }
    if delivery_stage != normalized:
        destinations[run_directory / "normalized-master-tp-corrected.wav"] = delivery_stage
    artifacts = {
        _relative(workspace, destination): sha256_file(stage_path)
        for destination, stage_path in destinations.items()
    }
    delivery_destination = (
        run_directory / "normalized-master.wav"
        if delivery_stage == normalized
        else run_directory / "normalized-master-tp-corrected.wav"
    )
    outputs = {
        "normalized_master": _relative(workspace, run_directory / "normalized-master.wav"),
        "delivery_master": _relative(workspace, delivery_destination),
        "flac": _relative(workspace, run_directory / "Haladhara-lecture-enhanced.flac"),
        "mp3": _relative(workspace, run_directory / "Haladhara-lecture-enhanced.mp3"),
        "normalized_master_sha256": artifacts[_relative(workspace, run_directory / "normalized-master.wav")],
        "delivery_master_sha256": artifacts[_relative(workspace, delivery_destination)],
        "flac_sha256": artifacts[_relative(workspace, run_directory / "Haladhara-lecture-enhanced.flac")],
        "mp3_sha256": artifacts[_relative(workspace, run_directory / "Haladhara-lecture-enhanced.mp3")],
        "flac_metrics": delivery["flac"],
        "mp3_metrics": delivery["mp3"],
    }
    completion = {
        "schema_version": 1,
        "render_completion_sha256": manifest["render"]["completion_sha256"],
        "preflight_space": space,
        "artifacts": artifacts,
        "manifest_outputs": outputs,
    }
    completion_stage = stage / "export-completion.json"
    write_json_atomic(completion_stage, completion)
    destinations[run_directory / "export-completion.json"] = completion_stage
    _publish_files(workspace, destinations)
    outputs["completion_sha256"] = sha256_file(run_directory / "export-completion.json")
    manifest["outputs"] = outputs
    manifest.setdefault("preflight_space", {})["export"] = space
    write_json_atomic(_manifest_path(workspace), manifest)
    shutil.rmtree(stage)


def _flat_run_stats(mask: np.ndarray) -> tuple[int, int, bool, bool]:
    changes = np.flatnonzero(np.diff(np.pad(mask.astype(np.int8), (1, 1))))
    runs = [(int(a), int(b)) for a, b in changes.reshape(-1, 2)]
    return (
        sum(1 for start, end in runs if end - start >= 3),
        int(np.count_nonzero(mask)),
        bool(mask[0]) if len(mask) else False,
        bool(mask[-1]) if len(mask) else False,
    )


def _output_integrity(mid_path: Path, side_path: Path, candidate: Path) -> dict[str, Any]:
    longest_new_zero = current_new_zero = non_finite = 0
    peak = sum_square = 0.0
    sample_values = 0
    reference_by_block, output_by_block = [], []
    reference_pinned = output_pinned = 0
    reference_total_runs = output_total_runs = 0
    reference_boundary_runs = output_boundary_runs = 0
    previous_reference_end = previous_output_end = False
    with sf.SoundFile(mid_path) as mid, sf.SoundFile(side_path) as side, sf.SoundFile(candidate) as test:
        while True:
            mid_values = mid.read(262_144, dtype="float32")
            side_values = side.read(262_144, dtype="float32")
            output = test.read(262_144, dtype="float32", always_2d=True)
            if len(mid_values) != len(side_values) or len(mid_values) != len(output):
                raise RuntimeError("integrity comparison lost alignment")
            if not len(output):
                break
            reference = from_mid_side(mid_values, side_values)
            finite = np.isfinite(output)
            non_finite += int(output.size - np.count_nonzero(finite))
            absolute = np.abs(np.nan_to_num(output))
            peak = max(peak, float(np.max(absolute)))
            sum_square += float(np.sum(np.square(np.nan_to_num(output))))
            sample_values += output.size
            new_zero = np.all(output == 0.0, axis=1) & np.any(reference != 0.0, axis=1)
            for value in new_zero:
                current_new_zero = current_new_zero + 1 if value else 0
                longest_new_zero = max(longest_new_zero, current_new_zero)
            reference_mask = np.any(np.abs(reference) >= 0.999999, axis=1)
            output_mask = np.any(absolute >= 0.999999, axis=1)
            ref_runs, ref_pinned, ref_start, ref_end = _flat_run_stats(reference_mask)
            out_runs, out_pinned, out_start, out_end = _flat_run_stats(output_mask)
            reference_by_block.append(ref_runs)
            output_by_block.append(out_runs)
            reference_total_runs += ref_runs
            output_total_runs += out_runs
            reference_pinned += ref_pinned
            output_pinned += out_pinned
            reference_boundary_runs += int(previous_reference_end and ref_start)
            output_boundary_runs += int(previous_output_end and out_start)
            previous_reference_end, previous_output_end = ref_end, out_end
    rms = np.sqrt(sum_square / max(sample_values, 1))
    return {
        "non_finite_samples": non_finite,
        "unexpected_zero_run_samples": longest_new_zero,
        "reference_flat_top_runs": reference_total_runs,
        "flat_top_runs": output_total_runs,
        "reference_pinned_samples": reference_pinned,
        "pinned_samples": output_pinned,
        "reference_flat_top_runs_by_block": reference_by_block,
        "flat_top_runs_by_block": output_by_block,
        "reference_flat_top_boundary_runs": reference_boundary_runs,
        "flat_top_boundary_runs": output_boundary_runs,
        "crest_db": float(20 * np.log10(max(peak, 1e-12) / max(rms, 1e-12))),
    }


def _boundary_scores(path: Path, boundaries: list[int]) -> list[dict[str, Any]]:
    scores = []
    with sf.SoundFile(path) as audio:
        for boundary in boundaries:
            start, end = max(0, boundary - 4_800), min(audio.frames, boundary + 4_800)
            audio.seek(start)
            values = audio.read(end - start, dtype="float32", always_2d=True)
            derivative = np.max(np.abs(np.diff(values, axis=0)), axis=1)
            if not len(derivative):
                raise RuntimeError("boundary excerpt is too short")
            index = min(len(derivative) - 1, max(0, boundary - start - 1))
            jump = float(derivative[index])
            neighborhood = float(np.median(derivative) + 1e-12)
            scores.append(
                {
                    "boundary_sample": boundary,
                    "jump": jump,
                    "jump_over_local_median_db": float(
                        20 * np.log10(max(jump, 1e-12) / neighborhood)
                    ),
                }
            )
    return scores


def _candidate_window_scores(
    workspace: Path, adaptive: Path, manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    diagnostics_path = _verify_record(workspace, manifest["reports"]["diagnostics"])
    diagnostics = read_json(diagnostics_path)
    if not isinstance(diagnostics, dict):
        raise RuntimeError("diagnostics report must be an object")
    rows = _validate_reviewed_windows(
        read_json(workspace / "analysis" / "windows-reviewed.json"),
        sf.info(adaptive).frames,
        diagnostics.get("representative_windows"),
    )
    mid_path = workspace / "work" / "original-mid.wav"
    side_path = workspace / "work" / "original-side.wav"
    result = []
    with sf.SoundFile(adaptive) as rendered:
        for row in rows:
            start, end = row["start_sample"], row["end_sample"]
            count = end - start
            original = from_mid_side(_read_mono(mid_path, start, count), _read_mono(side_path, start, count))
            rendered.seek(start)
            candidate = rendered.read(count, dtype="float32", always_2d=True)
            if len(candidate) != count:
                raise RuntimeError("full-render candidate window was truncated")
            result.append(
                {
                    "window_id": row["artifact_id"],
                    "start_sample": start,
                    "end_sample": end,
                    "reviewed_label": row["reviewed_label"],
                    "rms_delta_db": float(
                        20 * np.log10(
                            (np.sqrt(np.mean(np.square(candidate))) + 1e-20)
                            / (np.sqrt(np.mean(np.square(original))) + 1e-20)
                        )
                    ),
                    "peak": float(np.max(np.abs(candidate))),
                    "non_finite_samples": int(candidate.size - np.count_nonzero(np.isfinite(candidate))),
                }
            )
    return result


def _build_qa_report(workspace: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    run_directory = workspace / "final" / manifest["active_run_id"]
    source = Path(manifest["source"]["path"])
    adaptive = _workspace_leaf(workspace, manifest["render"]["adaptive_path"])
    master = _workspace_leaf(workspace, manifest["outputs"]["delivery_master"])
    flac = _workspace_leaf(workspace, manifest["outputs"]["flac"])
    mp3 = _workspace_leaf(workspace, manifest["outputs"]["mp3"])
    expected = manifest["source"]["decoded_samples"]
    ffmpeg, ffprobe = resolve_tool("ffmpeg"), resolve_tool("ffprobe")
    flac_metrics = _measure_delivery(ffmpeg, ffprobe, flac, expected)
    mp3_metrics = _measure_delivery(ffmpeg, ffprobe, mp3, expected)
    _, reviewed = _strict_segment_rows(workspace / "analysis" / "segments-reviewed.json")
    boundaries = sorted(
        set(manifest["render"]["chunk_boundaries"])
        | {item.end_sample for item in reviewed[:-1]}
    )
    window_scores = _candidate_window_scores(workspace, adaptive, manifest)
    return collect_qa_report(
        source_samples=expected,
        adaptive_samples=int(sf.info(adaptive).frames),
        master_probe={"frames": int(sf.info(master).frames)},
        flac_probe={
            "frames": flac_metrics["frames"], "sample_rate": flac_metrics["sample_rate"],
            "channels": flac_metrics["channels"], "bits_per_raw_sample": flac_metrics["bits_per_raw_sample"],
            "codec_name": flac_metrics["codec_name"], "container_name": flac_metrics["container_name"],
        },
        mp3_probe={
            "decoded_frames": mp3_metrics["frames"], "sample_rate": mp3_metrics["sample_rate"],
            "channels": mp3_metrics["channels"], "bit_rate": mp3_metrics["bit_rate"],
            "codec_delay_padding_samples": mp3_metrics["codec_delay_padding_samples"],
            "codec_name": mp3_metrics["codec_name"], "container_name": mp3_metrics["container_name"],
        },
        flac_metrics=flac_metrics,
        mp3_metrics=mp3_metrics,
        flac_path=flac,
        mp3_path=mp3,
        integrity=_output_integrity(
            workspace / "work" / "original-mid.wav",
            workspace / "work" / "original-side.wav",
            flac,
        ),
        boundary_scores=_boundary_scores(adaptive, boundaries),
        candidate_window_scores=window_scores,
        expected_boundary_samples=boundaries,
        expected_candidate_window_ids=[row["window_id"] for row in window_scores],
        source_path=source,
        adaptive_path=adaptive,
        delivery_master_path=master,
        listening_checklist_path=run_directory / "listening-checklist.md",
    )


def _verify_qa_state(workspace: Path, manifest: Mapping[str, Any]) -> None:
    state = _exact_mapping(manifest.get("qa"), {
        "report_path", "checklist_path", "report_sha256", "checklist_sha256",
        "listening_status",
    }, "QA state")
    if state["listening_status"] != "pending":
        raise RuntimeError("QA listening state must remain pending")
    run_directory = workspace / "final" / manifest["active_run_id"]
    _reject_unknown_final_entries(run_directory)
    qa_path = _workspace_leaf(workspace, state["report_path"])
    checklist_path = _workspace_leaf(workspace, state["checklist_path"])
    canonical_qa = run_directory / "qa-report.json"
    canonical_checklist = run_directory / "listening-checklist.md"
    if (
        qa_path != canonical_qa or checklist_path != canonical_checklist
        or qa_path.parent != checklist_path.parent or qa_path == checklist_path
        or _is_reparse_point(qa_path) or _is_reparse_point(checklist_path)
        or not qa_path.is_file() or not checklist_path.is_file()
        or not re.fullmatch(r"[0-9A-F]{64}", str(state["report_sha256"]))
        or not re.fullmatch(r"[0-9A-F]{64}", str(state["checklist_sha256"]))
        or sha256_file(qa_path) != state.get("report_sha256")
        or sha256_file(checklist_path) != state.get("checklist_sha256")
    ):
        raise RuntimeError("QA pair hash changed")
    _assert_distinct_files([qa_path, checklist_path], "QA")
    report = read_json(qa_path)
    expected_report_keys = {
        "source_samples", "adaptive_samples", "master_samples", "flac_samples",
        "mp3_samples", "mp3_delay_padding_samples", "sample_rate", "channels",
        "flac_sample_rate", "mp3_sample_rate", "flac_channels", "mp3_channels",
        "flac_bits_per_raw_sample", "flac_codec_name", "flac_container_name",
        "mp3_bitrate", "mp3_codec_name", "mp3_container_name", "flac_lufs",
        "mp3_lufs", "flac_true_peak_dbtp", "mp3_true_peak_dbtp",
        "non_finite_samples", "unexpected_zero_run_samples", "reference_flat_top_runs",
        "flat_top_runs", "reference_pinned_samples", "pinned_samples",
        "reference_flat_top_runs_by_block", "flat_top_runs_by_block",
        "reference_flat_top_boundary_runs", "flat_top_boundary_runs", "crest_db", "lra",
        "flac_decode_ok", "mp3_decode_ok", "decode_ok", "boundary_scores",
        "expected_boundary_samples", "candidate_window_scores",
        "expected_candidate_window_ids", "hashes", "artifact_paths",
        "listening_checklist", "orchestration",
    }
    report = _exact_mapping(report, expected_report_keys, "QA report")
    validate_delivery(report)
    orchestration = report.get("orchestration")
    if not isinstance(orchestration, dict):
        raise RuntimeError("QA orchestration provenance is missing")
    qa_space = _validated_space_evidence(orchestration.get("preflight_space"), "qa")
    if (
        orchestration != _qa_orchestration(manifest, qa_space)
        or manifest.get("preflight_space", {}).get("qa") != qa_space
    ):
        raise RuntimeError("QA orchestration provenance is stale")
    checklist = _exact_mapping(report.get("listening_checklist"), {
        "status", "required_sections", "path", "sha256", "veto_text",
    }, "QA listening checklist")
    if (
        checklist["status"] != "pending"
        or checklist["path"] != str(canonical_checklist)
        or checklist["sha256"] != state["checklist_sha256"]
        or checklist["sha256"] != sha256_file(checklist_path)
    ):
        raise RuntimeError("QA listening checkpoint is stale")
    for name, digest_name in (
        ("source", "source_sha256"), ("adaptive", "adaptive_sha256"),
        ("delivery_master", "delivery_master_sha256"), ("flac", "flac_sha256"),
        ("mp3", "mp3_sha256"),
    ):
        if sha256_file(Path(report["artifact_paths"][name])) != report["hashes"][digest_name]:
            raise RuntimeError("QA artifact binding changed")


def _qa_orchestration(manifest: Mapping[str, Any], space: Mapping[str, int]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": "qa",
        "preflight_space": dict(space),
        "source_sha256": manifest["source"]["sha256"],
        "reference": manifest["reference"],
        "versions": manifest["versions"],
        "processing": manifest["processing"],
        "selection": manifest["selection"],
        "approval_fingerprint": manifest["approval"]["fingerprint"],
        "render_completion_sha256": manifest["render"]["completion_sha256"],
        "export_completion_sha256": manifest["outputs"]["completion_sha256"],
    }


def run_qa(workspace: Path, manifest: dict) -> None:
    with _workspace_lock(Path(workspace)) as workspace:
        _run_qa_locked(workspace, _load_manifest(workspace))


def _run_qa_locked(workspace: Path, manifest: dict) -> None:
    workspace = Path(workspace)
    _verify_approved_state(workspace, manifest)
    _verify_render_state(workspace, manifest)
    _verify_export_state(workspace, manifest)
    run_directory = workspace / "final" / manifest["active_run_id"]
    qa_path = run_directory / "qa-report.json"
    checklist_path = run_directory / "listening-checklist.md"
    if manifest.get("qa"):
        _verify_qa_state(workspace, manifest)
        return
    if qa_path.exists() or qa_path.is_symlink() or checklist_path.exists() or checklist_path.is_symlink():
        if not qa_path.is_file() or not checklist_path.is_file() or qa_path.is_symlink() or checklist_path.is_symlink():
            raise RuntimeError("QA pair is partial or symlinked")
        candidate_state = {
            "report_path": _relative(workspace, qa_path),
            "checklist_path": _relative(workspace, checklist_path),
            "report_sha256": sha256_file(qa_path),
            "checklist_sha256": sha256_file(checklist_path),
            "listening_status": "pending",
        }
        recovered_report = read_json(qa_path)
        if not isinstance(recovered_report, dict) or not isinstance(
            recovered_report.get("orchestration"), dict
        ):
            raise RuntimeError("QA recovery report orchestration is malformed")
        recovered_space = _validated_space_evidence(
            recovered_report["orchestration"].get("preflight_space"), "qa"
        )
        proposed = dict(manifest)
        proposed["qa"] = candidate_state
        proposed["preflight_space"] = dict(manifest.get("preflight_space", {}))
        proposed["preflight_space"]["qa"] = recovered_space
        _verify_qa_state(workspace, proposed)
        manifest["qa"] = candidate_state
        manifest.setdefault("preflight_space", {})["qa"] = recovered_space
        write_json_atomic(_manifest_path(workspace), manifest)
        return
    space = _check_free_space(workspace, "qa")
    report = _build_qa_report(workspace, manifest)
    report = dict(report)
    report["orchestration"] = _qa_orchestration(manifest, space)
    _assert_safe_final_parent(workspace, qa_path)
    _assert_safe_final_parent(workspace, checklist_path)
    publish_qa_pair(report, qa_path, checklist_path)
    manifest["qa"] = {
        "report_path": _relative(workspace, qa_path),
        "checklist_path": _relative(workspace, checklist_path),
        "report_sha256": sha256_file(qa_path),
        "checklist_sha256": sha256_file(checklist_path),
        "listening_status": "pending",
    }
    manifest.setdefault("preflight_space", {})["qa"] = space
    _verify_qa_state(workspace, manifest)
    write_json_atomic(_manifest_path(workspace), manifest)


def _approved_manifest(parser: argparse.ArgumentParser, workspace: Path) -> dict[str, Any]:
    manifest = _load_manifest(workspace)
    try:
        # Check the logical approval before doing any potentially expensive hash reads.
        require_current_approval(manifest)
        _verify_approved_state(workspace, manifest)
    except (
        RenderNotApproved, RuntimeError, ValueError, OSError, subprocess.SubprocessError,
        KeyError, TypeError, AttributeError,
    ) as error:
        parser.error(str(error))
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "diagnose":
            run_diagnose(args)
        elif args.command == "candidates":
            run_candidates(args.workspace)
        elif args.command == "approve":
            run_approve(args)
        elif args.command == "render":
            with _workspace_lock(args.workspace) as workspace:
                manifest = _approved_manifest(parser, workspace)
                _run_full_render_locked(workspace, manifest)
        elif args.command == "export":
            with _workspace_lock(args.workspace) as workspace:
                manifest = _approved_manifest(parser, workspace)
                _run_export_locked(workspace, manifest)
        elif args.command == "qa":
            with _workspace_lock(args.workspace) as workspace:
                manifest = _approved_manifest(parser, workspace)
                _run_qa_locked(workspace, manifest)
    except (
        RenderNotApproved, RuntimeError, ValueError, OSError, subprocess.SubprocessError,
        KeyError, TypeError, AttributeError,
    ) as error:
        parser.error(str(error))
    return 0
