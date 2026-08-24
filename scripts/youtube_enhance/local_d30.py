"""Isolated, full-timeline local DeepFilterNet3 D30 review delivery."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import soundfile as sf

from .cli import _boundary_scores, _measure_delivery, _output_integrity
from .dfn import CachedDfnAdapter, DfnAdapter, build_render_context_key
from .loudness import export_matched_pair, normalize_two_pass
from .manifest import canonical_json, read_json, write_json_atomic
from .qa import collect_qa_report, publish_qa_pair
from .render import render_file
from .source import from_mid_side, resolve_tool, sha256_file


SAMPLE_RATE = 48_000
AUTHORITATIVE_FRAMES = 131_864_451
AUTHORITATIVE_SOURCE_SHA256 = "262630088DCC07E4507C004A3E46FA4CAF430EEFC2D047509A0618AFAE43BF68"
AUTHORITATIVE_ORIGINAL_MID_SHA256 = "A9EE0FC30C250DD0E636A89CF0B5C2474665866D0DA26CBA0A2945E444ACB697"
ATTENUATION_DB = 30
DELIVERY_NAME = "local-d30-review"


def _is_reparse_point(path: Path) -> bool:
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & reparse_flag)


def _assert_no_reparse_components(path: Path) -> None:
    absolute = Path(path).absolute()
    parts = absolute.parts
    cursor = Path(parts[0])
    for component in parts[1:]:
        cursor = cursor.parent if component == os.pardir else cursor / component
        if os.path.lexists(cursor) and _is_reparse_point(cursor):
            raise RuntimeError(f"local D30 delivery path contains a reparse point: {cursor}")


def _safe_delivery_directory(workspace: Path) -> tuple[Path, Path]:
    workspace = Path(os.path.abspath(os.fspath(Path(workspace).absolute())))
    _assert_no_reparse_components(workspace)
    if os.path.lexists(workspace) and not workspace.is_dir():
        raise RuntimeError("local D30 workspace must be a real directory")
    delivery = workspace / "deliveries" / DELIVERY_NAME
    try:
        if os.path.commonpath((os.path.normcase(os.fspath(workspace)), os.path.normcase(os.fspath(delivery)))) != os.path.normcase(os.fspath(workspace)):
            raise RuntimeError("local D30 delivery path escapes the workspace")
    except ValueError as error:
        raise RuntimeError("local D30 delivery path is on another volume") from error
    _assert_no_reparse_components(delivery.parent)
    if _is_reparse_point(delivery):
        raise RuntimeError("local D30 delivery leaf must not be a reparse point")
    return workspace, delivery


def _workspace_file(workspace: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError("workspace artifact path must be relative and traversal-safe")
    return workspace / candidate


def _model_hashes(model_directory: Path) -> dict[str, str]:
    model_directory = Path(model_directory)
    files = {
        "config.ini": model_directory / "config.ini",
        "checkpoints/model_120.ckpt.best": model_directory / "checkpoints" / "model_120.ckpt.best",
    }
    if any(not path.is_file() or path.is_symlink() for path in files.values()):
        raise FileNotFoundError("explicit DeepFilterNet3 config/checkpoint is incomplete")
    return {name: sha256_file(path) for name, path in files.items()}


def _first_version_line(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    lines = (result.stdout or result.stderr).splitlines()
    if not lines:
        raise RuntimeError(f"version command returned no text: {command[0]}")
    return lines[0].strip()


def _current_tool_versions(deepfilter: str, ffmpeg: str, ffprobe: str) -> dict[str, str]:
    return {
        "deepfilternet": importlib.metadata.version("DeepFilterNet"),
        "deepfilter": _first_version_line([deepfilter, "--version"]),
        "python": _first_version_line([sys.executable, "--version"]),
        "numpy": importlib.metadata.version("numpy"),
        "soundfile": importlib.metadata.version("soundfile"),
        "ffmpeg": _first_version_line([ffmpeg, "-version"]),
        "ffprobe": _first_version_line([ffprobe, "-version"]),
    }


def _require_workspace_tool_compatibility(manifest: dict[str, Any], actual: dict[str, str]) -> None:
    recorded = manifest.get("versions")
    if not isinstance(recorded, dict):
        raise RuntimeError("workspace manifest has no tool-version provenance")
    expected = {
        "deepfilternet": actual["deepfilternet"], "model": actual["deepfilter"],
        "python": actual["python"], "numpy": actual["numpy"],
        "soundfile": actual["soundfile"], "ffmpeg": actual["ffmpeg"],
        "ffprobe": actual["ffprobe"],
    }
    if any(recorded.get(key) != value for key, value in expected.items()):
        raise RuntimeError("workspace tool-version provenance is stale or incompatible")


def _render_versions(actual: dict[str, str], model_hashes: dict[str, str]) -> dict[str, str]:
    values = {
        "deepfilternet": actual["deepfilternet"],
        "model": "DeepFilterNet3:" + canonical_json(model_hashes) + ";binary=" + actual["deepfilter"],
        "python": actual["python"],
        "numpy": actual["numpy"],
        "soundfile": actual["soundfile"],
        "ffmpeg": actual["ffmpeg"],
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise RuntimeError("workspace manifest has incomplete tool-version provenance")
    return values


def _completion_tool_versions(render_versions: dict[str, str], actual: dict[str, str]) -> dict[str, str]:
    return {**render_versions, "deepfilter": actual["deepfilter"], "ffprobe": actual["ffprobe"]}


def _require_bound_inputs(workspace: Path) -> tuple[dict[str, Any], Path, Path, Path, Path, int]:
    manifest = read_json(workspace / "manifest.json")
    if not isinstance(manifest, dict):
        raise RuntimeError("workspace manifest must be an object")
    source = manifest.get("source")
    working = manifest.get("working")
    reference = manifest.get("reference")
    if not isinstance(source, dict) or not isinstance(working, dict) or not isinstance(reference, dict):
        raise RuntimeError("workspace manifest is missing source or working provenance")
    source_path = Path(source.get("path", ""))
    mid_record, side_record, raw_record = (
        working.get("original_mid"), working.get("original_side"), working.get("raw_stereo")
    )
    if (
        not source_path.is_file()
        or not isinstance(mid_record, dict)
        or not isinstance(side_record, dict)
        or not isinstance(raw_record, dict)
    ):
        raise RuntimeError("workspace source PCM/mid/side evidence is missing")
    mid_path = _workspace_file(workspace, mid_record.get("path", ""))
    side_path = _workspace_file(workspace, side_record.get("path", ""))
    raw_path = _workspace_file(workspace, raw_record.get("path", ""))
    if not mid_path.is_file() or not side_path.is_file() or not raw_path.is_file():
        raise RuntimeError("workspace original source PCM/mid/side files are missing")
    source_hash = sha256_file(source_path)
    raw_hash = sha256_file(raw_path)
    mid_hash = sha256_file(mid_path)
    side_hash = sha256_file(side_path)
    if (
        source.get("sha256") != AUTHORITATIVE_SOURCE_SHA256
        or source_hash != AUTHORITATIVE_SOURCE_SHA256
        or reference.get("original_mid_sha256") != AUTHORITATIVE_ORIGINAL_MID_SHA256
        or mid_hash != AUTHORITATIVE_ORIGINAL_MID_SHA256
        or mid_record.get("sha256") != mid_hash
        or side_record.get("sha256") != side_hash
        or reference.get("original_side_sha256") != side_hash
        or raw_record.get("sha256") != raw_hash
    ):
        raise RuntimeError("local D30 review inputs do not match required immutable hashes")
    frames = source.get("decoded_samples")
    if type(frames) is not int or frames != AUTHORITATIVE_FRAMES:
        raise RuntimeError("local D30 review does not have the required authoritative frame count")
    for path, channels in ((mid_path, 1), (side_path, 1)):
        info = sf.info(path)
        if info.frames != frames or info.samplerate != SAMPLE_RATE or info.channels != channels or info.subtype != "FLOAT":
            raise RuntimeError("local D30 review mid/side inputs changed format or frame count")
    raw_info = sf.info(raw_path)
    if (
        raw_info.frames != frames
        or raw_info.samplerate != SAMPLE_RATE
        or raw_info.channels != 2
        or raw_info.subtype != "FLOAT"
    ):
        raise RuntimeError("local D30 review source PCM changed format or frame count")
    return manifest, source_path, raw_path, mid_path, side_path, frames


def _reconstruct_stereo(mid_path: Path, side_path: Path, destination: Path, frames: int) -> None:
    with sf.SoundFile(mid_path) as mid, sf.SoundFile(side_path) as side, sf.SoundFile(
        destination, "w", samplerate=SAMPLE_RATE, channels=2, subtype="FLOAT"
    ) as output:
        written = 0
        while written < frames:
            count = min(262_144, frames - written)
            mid_values = mid.read(count, dtype="float32")
            side_values = side.read(count, dtype="float32")
            if len(mid_values) != count or len(side_values) != count:
                raise RuntimeError("local D30 reconstruction input was truncated")
            output.write(from_mid_side(mid_values, side_values))
            written += count
    info = sf.info(destination)
    if info.frames != frames or info.samplerate != SAMPLE_RATE or info.channels != 2 or info.subtype != "FLOAT":
        raise RuntimeError("local D30 reconstruction changed the timeline or format")


def run_local_d30(workspace: Path, model_directory: Path) -> dict[str, Any]:
    """Render one local-model DFN3 D30 delivery without touching official state."""
    workspace, delivery = _safe_delivery_directory(Path(workspace))
    if delivery.exists() or delivery.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable local review delivery: {delivery}")
    manifest, source_path, raw_path, mid_path, side_path, frames = _require_bound_inputs(workspace)
    model_directory = Path(model_directory)
    model_hashes = _model_hashes(model_directory)
    processing = manifest.get("processing")
    if not isinstance(processing, dict):
        raise RuntimeError("workspace manifest is missing chunk policy")
    try:
        core, halo, blend = (processing[name] for name in ("core_samples", "halo_samples", "blend_samples"))
    except KeyError as error:
        raise RuntimeError("workspace manifest is missing chunk policy") from error
    if any(type(value) is not int or value <= 0 for value in (core, halo, blend)):
        raise RuntimeError("workspace chunk policy is invalid")
    executable = Path(".venv/Scripts/deepFilter.exe").resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    ffmpeg, ffprobe = resolve_tool("ffmpeg"), resolve_tool("ffprobe")
    actual_versions = _current_tool_versions(str(executable), ffmpeg, ffprobe)
    _require_workspace_tool_compatibility(manifest, actual_versions)
    versions = _render_versions(actual_versions, model_hashes)
    completion_versions = _completion_tool_versions(versions, actual_versions)
    source_hash, source_pcm_hash, mid_hash = (
        sha256_file(source_path), sha256_file(raw_path), sha256_file(mid_path)
    )
    context_key = build_render_context_key(
        source_pcm_hash, mid_hash, ATTENUATION_DB, SAMPLE_RATE, core, halo, blend,
        "local-d30-full-timeline-v1", versions,
    )
    enhancer = CachedDfnAdapter(
        DfnAdapter(str(executable), versions["model"], model_directory=model_directory),
        {
            "render_context_key": context_key,
            "stage": "local-d30-review",
            "chunk_policy": {"core_samples": core, "halo_samples": halo, "blend_samples": blend},
            "model_hashes": model_hashes,
        },
        versions,
    )
    cache_root = workspace / "d30"
    delivery.mkdir(parents=True)
    adaptive = delivery / "adaptive.wav"
    rendered_mid = delivery / "rendered-mid.wav"
    try:
        render = render_file(
            mid_path, rendered_mid, enhancer, SAMPLE_RATE, ATTENUATION_DB,
            core, halo, blend, cache_root,
        )
        _reconstruct_stereo(rendered_mid, side_path, adaptive, frames)
        rendered_mid.unlink()
        normalized = delivery / "normalized-master.wav"
        normalize_two_pass(ffmpeg, adaptive, normalized, frames)
        flac = delivery / "Haladhara-lecture-D30-review.flac"
        mp3 = delivery / "Haladhara-lecture-D30-review.mp3"
        exported = export_matched_pair(
            ffmpeg, normalized, flac, mp3,
            lambda path: _measure_delivery(ffmpeg, ffprobe, path, frames),
        )
        master = Path(exported["delivery_master"])
        report = collect_qa_report(
            source_samples=frames,
            adaptive_samples=int(sf.info(adaptive).frames),
            master_probe={"frames": int(sf.info(master).frames)},
            flac_probe={key: exported["flac"][key] for key in ("frames", "sample_rate", "channels", "bits_per_raw_sample", "codec_name", "container_name")},
            mp3_probe={"decoded_frames": exported["mp3"]["frames"], **{key: exported["mp3"][key] for key in ("sample_rate", "channels", "bit_rate", "codec_delay_padding_samples", "codec_name", "container_name")}},
            flac_metrics=exported["flac"], mp3_metrics=exported["mp3"], flac_path=flac, mp3_path=mp3,
            integrity=_output_integrity(mid_path, side_path, flac),
            boundary_scores=_boundary_scores(adaptive, render["boundaries"]),
            candidate_window_scores=[], expected_boundary_samples=render["boundaries"],
            expected_candidate_window_ids=[], source_path=source_path, adaptive_path=adaptive,
            delivery_master_path=master, listening_checklist_path=delivery / "listening-checklist.md",
        )
        publish_qa_pair(report, delivery / "qa-report.json", delivery / "listening-checklist.md")
        completion = {
            "schema_version": 1,
            "mode": "dfn30_parallel",
            "source_sha256": source_hash,
            "source_pcm_sha256": source_pcm_hash,
            "original_mid_sha256": mid_hash,
            "model_directory": str(model_directory.resolve()),
            "model_hashes": model_hashes,
            "attenuation_db": ATTENUATION_DB,
            "chunk_policy": {"core_samples": core, "halo_samples": halo, "blend_samples": blend},
            "cache_context_key": context_key,
            "tool_versions": completion_versions,
            "frames": frames,
            "chunk_boundaries": render["boundaries"],
            "artifacts": {
                "adaptive.wav": sha256_file(adaptive),
                str(master.name): sha256_file(master),
                flac.name: sha256_file(flac), mp3.name: sha256_file(mp3),
                "qa-report.json": sha256_file(delivery / "qa-report.json"),
                "listening-checklist.md": sha256_file(delivery / "listening-checklist.md"),
            },
            "listening_status": "pending",
        }
        write_json_atomic(delivery / "completion.json", completion)
        return completion
    except BaseException:
        # Keep cache_root intact: CachedDfnAdapter makes completed chunks reusable.
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local_d30_review")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_local_d30(args.workspace, args.model_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
