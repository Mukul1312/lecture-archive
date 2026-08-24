"""Fail-closed decoded-delivery QA and the pending human listening record."""

from __future__ import annotations

import math
import os
import json
import hashlib
import copy
from pathlib import Path
from typing import Any

from .source import sha256_file


SAMPLE_RATE = 48000
CHANNELS = 2
MAX_MP3_DELAY_PADDING = 1152
MAX_NEW_ZERO_RUN_SAMPLES = round(0.050 * SAMPLE_RATE)
CHECKLIST_SECTIONS = (
    "Candidate windows",
    "Segment transitions",
    "Chunk boundaries",
    "Quiet consonants",
    "Overlaps",
    "Music and chanting",
    "Applause and crowd",
    "Beginning",
    "Ending",
    "Naturalness veto",
    "Word-integrity veto",
)


class QaFailure(RuntimeError):
    pass


def _required(report: dict[str, Any], key: str) -> Any:
    try:
        return report[key]
    except KeyError as error:
        raise QaFailure(f"QA report is missing required field: {key}") from error


def _integer(report: dict[str, Any], key: str) -> int:
    value = _required(report, key)
    if isinstance(value, bool):
        raise QaFailure(f"QA field must be an integer: {key}")
    if type(value) is not int:
        raise QaFailure(f"QA field must be an integer: {key}")
    result = value
    if result < 0:
        raise QaFailure(f"QA count cannot be negative: {key}")
    return result


def _number(report: dict[str, Any], key: str) -> float:
    try:
        value = float(_required(report, key))
    except (TypeError, ValueError) as error:
        raise QaFailure(f"QA field must be numeric: {key}") from error
    if not math.isfinite(value):
        raise QaFailure(f"QA field must be finite: {key}")
    return value


def _required_hashes(report: dict[str, Any]) -> None:
    hashes = _required(report, "hashes")
    if not isinstance(hashes, dict):
        raise QaFailure("QA hashes must be an object")
    for key in (
        "source_sha256", "adaptive_sha256", "delivery_master_sha256",
        "flac_sha256", "mp3_sha256",
    ):
        value = hashes.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789ABCDEF" for char in value.upper()):
            raise QaFailure(f"QA report has invalid {key}")


def _finite_tree(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise QaFailure("QA report contains a non-finite persisted number")
    if isinstance(value, dict):
        for nested in value.values():
            _finite_tree(nested)
    elif isinstance(value, list):
        for nested in value:
            _finite_tree(nested)


def _check_checklist(report: dict[str, Any]) -> None:
    checklist = _required(report, "listening_checklist")
    required = [section.lower() for section in CHECKLIST_SECTIONS]
    if (not isinstance(checklist, dict) or checklist.get("status") != "pending"
            or checklist.get("required_sections") != required
            or not isinstance(checklist.get("path"), str)
            or not isinstance(checklist.get("veto_text"), str)
            or "word integrity" not in checklist["veto_text"].lower()
            or "naturalness" not in checklist["veto_text"].lower()):
        raise QaFailure("pending listening checklist metadata/evidence is incomplete")
    value = checklist.get("sha256")
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise QaFailure("pending listening checklist hash is invalid")


def _check_path_bindings(report: dict[str, Any], *, rehash: bool = False) -> None:
    paths = _required(report, "artifact_paths")
    hashes = _required(report, "hashes")
    if not isinstance(paths, dict):
        raise QaFailure("QA artifact paths must be an object")
    for name in ("source", "adaptive", "delivery_master", "flac", "mp3"):
        if not isinstance(paths.get(name), str) or not paths[name]:
            raise QaFailure(f"QA artifact path is missing: {name}")
    if rehash:
        for name, hash_name in (("source", "source_sha256"), ("adaptive", "adaptive_sha256"),
                                ("delivery_master", "delivery_master_sha256"), ("flac", "flac_sha256"), ("mp3", "mp3_sha256")):
            if sha256_file(Path(paths[name])) != hashes[hash_name]:
                raise QaFailure(f"QA artifact hash no longer binds to {name} path")


def validate_delivery(report: dict[str, Any]) -> None:
    """Enforce the delivery contract before a QA report may be published."""
    _finite_tree(report)
    try:
        json.dumps(report, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise QaFailure("QA report is not standard finite JSON") from error
    source_samples = _integer(report, "source_samples")
    adaptive_samples = _integer(report, "adaptive_samples")
    master_samples = _integer(report, "master_samples")
    flac_samples = _integer(report, "flac_samples")
    mp3_samples = _integer(report, "mp3_samples")
    if source_samples <= 0 or adaptive_samples != source_samples or master_samples != source_samples or flac_samples != source_samples:
        raise QaFailure("source, adaptive, master, and decoded FLAC must have exactly equal PCM frame counts")
    mp3_delta = mp3_samples - source_samples
    if mp3_delta < 0 or mp3_delta > MAX_MP3_DELAY_PADDING or _integer(report, "mp3_delay_padding_samples") != mp3_delta:
        raise QaFailure("decoded MP3 count lacks verified <=1152-sample codec delay/padding evidence")
    if _integer(report, "sample_rate") != SAMPLE_RATE or _integer(report, "channels") != CHANNELS:
        raise QaFailure("generic delivery format must be 48 kHz stereo")
    for key in ("flac_sample_rate", "mp3_sample_rate"):
        if _integer(report, key) != SAMPLE_RATE:
            raise QaFailure("deliverables must be 48 kHz")
    for key in ("flac_channels", "mp3_channels"):
        if _integer(report, key) != CHANNELS:
            raise QaFailure("deliverables must be stereo")
    if (_integer(report, "flac_bits_per_raw_sample") != 24
            or _required(report, "flac_codec_name") != "flac"
            or _required(report, "flac_container_name") != "flac"):
        raise QaFailure("FLAC is not genuine 24-bit")
    if (abs(_integer(report, "mp3_bitrate") - 192000) > 3000
            or _required(report, "mp3_codec_name") != "mp3"
            or _required(report, "mp3_container_name") != "mp3"):
        raise QaFailure("MP3 is not approximately 192 kbps")
    for key in ("flac_lufs", "mp3_lufs"):
        if not -16.5 <= _number(report, key) <= -15.5:
            raise QaFailure("decoded loudness is outside -16 LUFS +/-0.5")
    for key in ("flac_true_peak_dbtp", "mp3_true_peak_dbtp"):
        if _number(report, key) > -1.5:
            raise QaFailure("decoded true peak exceeds -1.5 dBTP")
    if _integer(report, "non_finite_samples"):
        raise QaFailure("output contains non-finite samples")
    if _integer(report, "unexpected_zero_run_samples") > MAX_NEW_ZERO_RUN_SAMPLES:
        raise QaFailure("output contains a new digital dropout longer than 50 ms")
    if _integer(report, "flat_top_runs") > _integer(report, "reference_flat_top_runs") or _integer(report, "pinned_samples") > _integer(report, "reference_pinned_samples"):
        raise QaFailure("delivery introduced flat-top clipping beyond the original reference")
    reference_by_block = _required(report, "reference_flat_top_runs_by_block")
    output_by_block = _required(report, "flat_top_runs_by_block")
    if not isinstance(reference_by_block, list) or not isinstance(output_by_block, list) or len(reference_by_block) != len(output_by_block):
        raise QaFailure("flat-top regression evidence must cover the same blocks")
    if any(_raw_integer(reference, "reference flat-top block") < _raw_integer(output, "flat-top block") for reference, output in zip(reference_by_block, output_by_block)):
        raise QaFailure("delivery introduced a flat-top run in a measured block")
    if _integer(report, "flat_top_boundary_runs") > _integer(report, "reference_flat_top_boundary_runs"):
        raise QaFailure("delivery introduced a flat-top run across a block boundary")
    if report.get("flac_decode_ok") is not True or report.get("mp3_decode_ok") is not True or report.get("decode_ok") is not True:
        raise QaFailure("one or more deliverables did not fully decode")
    expected_boundaries = _required(report, "expected_boundary_samples")
    boundary_scores = _required(report, "boundary_scores")
    if not isinstance(expected_boundaries, list) or not isinstance(boundary_scores, list):
        raise QaFailure("boundary QA coverage must be lists")
    if not all(isinstance(item, int) and not isinstance(item, bool) and 0 < item < source_samples for item in expected_boundaries):
        raise QaFailure("expected boundaries must be unique in-range integer sample coordinates")
    actual_boundaries = [_integer(row, "boundary_sample") for row in boundary_scores]
    if len(expected_boundaries) != len(set(expected_boundaries)) or len(actual_boundaries) != len(set(actual_boundaries)) or set(actual_boundaries) != set(expected_boundaries):
        raise QaFailure("boundary QA scores do not uniquely cover every expected boundary")
    for row in boundary_scores:
        jump = _number(row, "jump")
        relative = _number(row, "jump_over_local_median_db")
        if jump > 0.05 and relative > 20.0:
            raise QaFailure("a chunk or segment boundary contains a new impulse")
    expected_windows = _required(report, "expected_candidate_window_ids")
    candidate_window_scores = _required(report, "candidate_window_scores")
    if not isinstance(expected_windows, list) or not isinstance(candidate_window_scores, list):
        raise QaFailure("candidate-window QA coverage must be lists")
    if not all(isinstance(item, str) and item for item in expected_windows) or len(expected_windows) != len(set(expected_windows)):
        raise QaFailure("expected candidate windows must be unique non-empty IDs")
    actual_windows = [_required(row, "window_id") for row in candidate_window_scores]
    if len(actual_windows) != len(set(actual_windows)) or set(actual_windows) != set(expected_windows):
        raise QaFailure("candidate-window QA does not uniquely cover every expected window")
    for row in candidate_window_scores:
        start, end = _integer(row, "start_sample"), _integer(row, "end_sample")
        if not 0 <= start < end <= source_samples:
            raise QaFailure("candidate-window score has an invalid source span")
        if _integer(row, "non_finite_samples") or _number(row, "peak") > 1.0:
            raise QaFailure("a full-render candidate window failed integrity checks")
    _required_hashes(report)
    _check_path_bindings(report)
    _number(report, "crest_db")
    _number(report, "lra")
    _check_checklist(report)


def _render_listening_checklist(report: dict[str, Any]) -> bytes:
    lines = ["# Listening checklist", "", "Status: pending", ""]
    expected_windows = report.get("expected_candidate_window_ids", [])
    expected_boundaries = report.get("expected_boundary_samples", [])
    lines.extend((
        "Candidate window IDs: " + (", ".join(map(str, expected_windows)) or "none"),
        "Boundary samples: " + (", ".join(map(str, expected_boundaries)) or "none"),
        "",
    ))
    for section in CHECKLIST_SECTIONS:
        lines.extend((f"## {section}", "", "- [ ] Reviewed", "- Notes: pending", ""))
    return "\n".join(lines).encode("utf-8")


def _stage(path: Path) -> Path:
    return path.with_name(f".{path.stem}.{hashlib.sha256(os.urandom(16)).hexdigest()}.stage{path.suffix}")


def _publish_set(stages: dict[Path, Path]) -> None:
    for destination in stages:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"refusing to overwrite immutable output: {destination}")
    made: list[tuple[Path, Path]] = []
    try:
        for destination, stage in stages.items():
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
    finally:
        for stage in stages.values():
            if stage.exists() and not stage.is_symlink():
                stage.unlink()


def _raw_integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise QaFailure(f"requires non-negative raw integer: {name}")
    return value


def collect_qa_report(
    source_samples: int,
    adaptive_samples: int,
    master_probe: dict[str, Any],
    flac_probe: dict[str, Any],
    mp3_probe: dict[str, Any],
    flac_metrics: dict[str, Any],
    mp3_metrics: dict[str, Any],
    flac_path: Path,
    mp3_path: Path,
    integrity: dict[str, Any],
    boundary_scores: list[dict[str, Any]],
    candidate_window_scores: list[dict[str, Any]],
    *,
    expected_boundary_samples: list[int],
    expected_candidate_window_ids: list[str],
    source_path: Path,
    adaptive_path: Path,
    delivery_master_path: Path,
    listening_checklist_path: Path | None = None,
) -> dict[str, Any]:
    """Collect complete decoded-output evidence without accepting it."""
    source_samples = _raw_integer(source_samples, "source_samples")
    adaptive_samples = _raw_integer(adaptive_samples, "adaptive_samples")
    if not all(type(value) is int and value >= 0 for value in expected_boundary_samples):
        raise QaFailure("collector requires raw integer expected boundaries")
    if not all(type(value) is str and value for value in expected_candidate_window_ids):
        raise QaFailure("collector requires raw string expected window IDs")
    report: dict[str, Any] = {
        "source_samples": source_samples,
        "adaptive_samples": adaptive_samples,
        "master_samples": _raw_integer(master_probe["frames"], "master frames"),
        "flac_samples": _raw_integer(flac_probe["frames"], "flac frames"),
        "mp3_samples": _raw_integer(mp3_probe["decoded_frames"], "mp3 frames"),
        "mp3_delay_padding_samples": _raw_integer(mp3_probe["codec_delay_padding_samples"], "mp3 delay"),
        "sample_rate": _raw_integer(flac_probe["sample_rate"], "flac rate"),
        "channels": _raw_integer(flac_probe["channels"], "flac channels"),
        "flac_sample_rate": _raw_integer(flac_probe["sample_rate"], "flac rate"),
        "mp3_sample_rate": _raw_integer(mp3_probe["sample_rate"], "mp3 rate"),
        "flac_channels": _raw_integer(flac_probe["channels"], "flac channels"),
        "mp3_channels": _raw_integer(mp3_probe["channels"], "mp3 channels"),
        "flac_bits_per_raw_sample": _raw_integer(flac_probe["bits_per_raw_sample"], "flac bits"),
        "flac_codec_name": str(flac_probe["codec_name"]),
        "flac_container_name": str(flac_probe["container_name"]),
        "mp3_bitrate": _raw_integer(mp3_probe["bit_rate"], "mp3 bitrate"),
        "mp3_codec_name": str(mp3_probe["codec_name"]),
        "mp3_container_name": str(mp3_probe["container_name"]),
        "flac_lufs": float(flac_metrics["integrated_lufs"]),
        "mp3_lufs": float(mp3_metrics["integrated_lufs"]),
        "flac_true_peak_dbtp": float(flac_metrics["true_peak_dbtp"]),
        "mp3_true_peak_dbtp": float(mp3_metrics["true_peak_dbtp"]),
        "non_finite_samples": _raw_integer(integrity["non_finite_samples"], "non-finite count"),
        "unexpected_zero_run_samples": _raw_integer(integrity["unexpected_zero_run_samples"], "zero run count"),
        "reference_flat_top_runs": _raw_integer(integrity["reference_flat_top_runs"], "reference flat tops"),
        "flat_top_runs": _raw_integer(integrity["flat_top_runs"], "flat tops"),
        "reference_pinned_samples": _raw_integer(integrity["reference_pinned_samples"], "reference pinned"),
        "pinned_samples": _raw_integer(integrity["pinned_samples"], "pinned"),
        "reference_flat_top_runs_by_block": [_raw_integer(v, "reference flat-top block") for v in integrity["reference_flat_top_runs_by_block"]],
        "flat_top_runs_by_block": [_raw_integer(v, "flat-top block") for v in integrity["flat_top_runs_by_block"]],
        "reference_flat_top_boundary_runs": _raw_integer(integrity["reference_flat_top_boundary_runs"], "reference boundary flat tops"),
        "flat_top_boundary_runs": _raw_integer(integrity["flat_top_boundary_runs"], "boundary flat tops"),
        "crest_db": float(integrity["crest_db"]),
        "lra": float(flac_metrics["lra"]),
        "flac_decode_ok": flac_metrics["decode_ok"] is True,
        "mp3_decode_ok": mp3_metrics["decode_ok"] is True,
        "decode_ok": flac_metrics["decode_ok"] is True and mp3_metrics["decode_ok"] is True,
        "boundary_scores": boundary_scores,
        "expected_boundary_samples": list(expected_boundary_samples),
        "candidate_window_scores": candidate_window_scores,
        "expected_candidate_window_ids": list(expected_candidate_window_ids),
        "hashes": {
            "source_sha256": sha256_file(source_path),
            "adaptive_sha256": sha256_file(adaptive_path),
            "delivery_master_sha256": sha256_file(delivery_master_path),
            "flac_sha256": sha256_file(flac_path),
            "mp3_sha256": sha256_file(mp3_path),
        },
        "artifact_paths": {
            "source": str(source_path), "adaptive": str(adaptive_path),
            "delivery_master": str(delivery_master_path), "flac": str(flac_path), "mp3": str(mp3_path),
        },
        "listening_checklist": {
            "status": "pending",
            "required_sections": [section.lower() for section in CHECKLIST_SECTIONS],
            "path": str(listening_checklist_path) if listening_checklist_path else "listening-checklist.md",
            "sha256": "0" * 64,
            "veto_text": "Naturalness and word integrity veto delivery.",
        },
    }
    payload = _render_listening_checklist(report)
    report["listening_checklist"]["sha256"] = hashlib.sha256(payload).hexdigest().upper()
    return report


def publish_qa_pair(report: dict[str, Any], qa_path: Path, checklist_path: Path) -> None:
    """Validate, stage, and publish canonical QA JSON plus checklist together."""
    if (qa_path == checklist_path or qa_path.is_symlink() or checklist_path.is_symlink()
            or qa_path.resolve() == checklist_path.resolve()):
        raise QaFailure("QA JSON and checklist paths must be distinct non-symlink leaves")
    if qa_path.parent.resolve() != checklist_path.parent.resolve():
        raise QaFailure("QA JSON and checklist must share a publication parent")
    qa_stage, checklist_stage = _stage(qa_path), _stage(checklist_path)
    all_paths = (qa_path, checklist_path, qa_stage, checklist_stage)
    if len({path.resolve() for path in all_paths}) != 4 or any(path.exists() or path.is_symlink() for path in all_paths):
        raise QaFailure("QA publication paths and private stages must be fresh and distinct")
    if qa_stage.parent.resolve() != qa_path.parent.resolve() or checklist_stage.parent.resolve() != checklist_path.parent.resolve():
        raise QaFailure("QA private stages must share their final parent")
    snapshot = copy.deepcopy(report)
    payload = _render_listening_checklist(snapshot)
    checklist = dict(snapshot.get("listening_checklist", {}))
    checklist.update({"status": "pending", "path": str(checklist_path),
                      "sha256": hashlib.sha256(payload).hexdigest().upper(),
                      "required_sections": [section.lower() for section in CHECKLIST_SECTIONS],
                      "veto_text": "Naturalness and word integrity veto delivery."})
    snapshot["listening_checklist"] = checklist
    validate_delivery(snapshot)
    _check_path_bindings(snapshot, rehash=True)
    validate_delivery(snapshot)
    qa_payload = (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    try:
        with qa_stage.open("xb") as handle:
            handle.write(qa_payload)
        with checklist_stage.open("xb") as handle:
            handle.write(_render_listening_checklist(snapshot))
        _publish_set({qa_path: qa_stage, checklist_path: checklist_stage})
    except BaseException:
        for path in (qa_stage, checklist_stage):
            if path.exists() and not path.is_symlink():
                path.unlink()
        raise
