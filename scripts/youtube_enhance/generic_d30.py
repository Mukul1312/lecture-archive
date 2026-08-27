"""Source-generic, job-bound DeepFilterNet3 D30 delivery runner."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import soundfile as sf

from .cli import _boundary_scores, _measure_delivery, _output_integrity
from .dfn import CachedDfnAdapter, DfnAdapter, build_render_context_key
from .loudness import export_matched_pair, normalize_two_pass
from .manifest import canonical_json, write_json_atomic
from .qa import collect_qa_report, publish_qa_pair
from .render import render_file
from .source import (
    SAMPLE_RATE,
    decode_float_stereo,
    from_mid_side,
    resolve_tool,
    sha256_file,
    stream_headroom_mid_side,
)
from .workflow_state import JobBusy, existing_job_paths, job_lock


ATTENUATION_DB = 30
CORE_SAMPLES = 240 * SAMPLE_RATE
HALO_SAMPLES = 2 * SAMPLE_RATE
BLEND_SAMPLES = 120 * SAMPLE_RATE // 1000
DELIVERY_BASENAME_LIMIT = 24
PROVENANCE_SUFFIX = ".provenance.json"


class _ScratchDfnAdapter:
    """Keep mutable DFN attempts short while CachedDfnAdapter owns the cache path."""

    def __init__(self, inner: DfnAdapter, scratch_root: Path):
        self.inner = inner
        self.scratch_root = Path(scratch_root)
        self.model_version = inner.model_version

    def enhance(
        self, samples: np.ndarray, sample_rate: int, attenuation_db: int | None, _cache_work: Path
    ):
        return self.inner.enhance(samples, sample_rate, attenuation_db, self.scratch_root)


class _CacheRootDfnAdapter:
    """Keep content-addressed cache leaves below one short, job-local root."""

    def __init__(self, inner: CachedDfnAdapter, cache_root: Path):
        self.inner = inner
        self.cache_root = Path(cache_root)

    def enhance(
        self, samples: np.ndarray, sample_rate: int, attenuation_db: int | None, _render_group: Path
    ):
        return self.inner.enhance(samples, sample_rate, attenuation_db, self.cache_root)


def _delivery_stage(work: Path, token: str) -> Path:
    return work / f".d-{token}"


def _delivery_names(source_path: Path) -> tuple[str, str]:
    """Derive short, deterministic, Windows-safe names from the approved source."""
    source_path = Path(source_path)
    stem = re.sub(r"[^\w.-]+", "-", source_path.stem, flags=re.UNICODE).strip(" .-_")
    stem = re.sub(r"-{2,}", "-", stem)
    if not stem:
        stem = f"lecture-{hashlib.sha256(source_path.name.encode('utf-8')).hexdigest()[:8]}"
    if stem.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        stem = f"lecture-{stem}"
    if len(stem) > DELIVERY_BASENAME_LIMIT:
        digest = hashlib.sha256(source_path.name.encode("utf-8")).hexdigest()[:8]
        stem = f"{stem[:DELIVERY_BASENAME_LIMIT - 9].rstrip(' .-_')}-{digest}"
    return f"{stem}-D30.flac", f"{stem}-D30.mp3"


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be an object")
    return value


def _require_approved_job(job_path: Path) -> tuple[dict[str, Any], Path, str]:
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("job JSON is unreadable") from error
    job = _require_mapping(job, "job")
    if job.get("stage") != "full_render_approved":
        raise RuntimeError("job is not approved for a full render")
    source = _require_mapping(job.get("source"), "job source")
    source_text, source_hash = source.get("path"), source.get("sha256")
    if not isinstance(source_text, str) or not source_text:
        raise RuntimeError("job source path is missing")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise RuntimeError("job source SHA-256 is missing")
    source_path = Path(source_text)
    if not source_path.is_file():
        raise FileNotFoundError(f"job source is missing: {source_path}")
    if sha256_file(source_path) != source_hash.lower():
        raise RuntimeError("job source SHA-256 no longer matches its approved bytes")

    treatment = _require_mapping(job.get("treatment"), "job treatment")
    choice = _require_mapping(_require_mapping(job.get("audition"), "job audition").get("choice"), "audition choice")
    if (
        treatment.get("mode") != "dfn30_parallel"
        or treatment.get("model") != "DeepFilterNet3"
        or treatment.get("attenuation_limit_db") != ATTENUATION_DB
        or treatment.get("preserve_complete_timeline") is not True
        or choice.get("selected_candidate") != "dfn30_parallel"
        or choice.get("result") != "unanimous"
    ):
        raise RuntimeError("job approval is not unanimous DeepFilterNet3 D30")
    delivery = _require_mapping(job.get("delivery"), "job delivery")
    if delivery.get("status") != "approved_pending_render":
        raise RuntimeError("job delivery is not pending an approved render")
    formats = delivery.get("formats")
    if not isinstance(formats, list) or not {"flac_24bit", "mp3_192kbps"}.issubset(formats):
        raise RuntimeError("job delivery formats do not require 24-bit FLAC and 192 kbps MP3")
    return job, source_path, source_hash.lower()


def _model_hashes(model_directory: Path) -> dict[str, str]:
    files = {
        "config.ini": model_directory / "config.ini",
        "checkpoints/model_120.ckpt.best": model_directory / "checkpoints" / "model_120.ckpt.best",
    }
    if any(not path.is_file() or path.is_symlink() for path in files.values()):
        raise FileNotFoundError("job-bound DeepFilterNet3 config/checkpoint is incomplete")
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


def _render_versions(actual: dict[str, str], model_hashes: dict[str, str]) -> dict[str, str]:
    return {
        "deepfilternet": actual["deepfilternet"],
        "model": "DeepFilterNet3:" + canonical_json(model_hashes) + ";binary=" + actual["deepfilter"],
        "python": actual["python"],
        "numpy": actual["numpy"],
        "soundfile": actual["soundfile"],
        "ffmpeg": actual["ffmpeg"],
    }


def _require_stereo_float(path: Path, frames: int | None = None) -> int:
    info = sf.info(path)
    if info.samplerate != SAMPLE_RATE or info.channels != 2 or info.subtype != "FLOAT" or info.frames <= 0:
        raise RuntimeError("decoded PCM must be non-empty 48 kHz floating-point stereo")
    if frames is not None and info.frames != frames:
        raise RuntimeError("decoded PCM frame count changed")
    return int(info.frames)


def _require_mono_float(path: Path, frames: int) -> None:
    info = sf.info(path)
    if info.samplerate != SAMPLE_RATE or info.channels != 1 or info.subtype != "FLOAT" or info.frames != frames:
        raise RuntimeError("mid/side PCM changed format or frame count")


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
                raise RuntimeError("mid/side reconstruction input was truncated")
            output.write(from_mid_side(mid_values, side_values))
            written += count
    _require_stereo_float(destination, frames)


def _provenance_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + PROVENANCE_SUFFIX)


def _discard_work_artifact(path: Path) -> None:
    for candidate in (path, _provenance_path(path)):
        if os.path.lexists(candidate):
            if candidate.is_symlink() or not candidate.is_file():
                raise RuntimeError(f"working artifact is not a regular file: {candidate}")
            candidate.unlink()


def _publish_provenance(path: Path, context: dict[str, Any], **extra: Any) -> None:
    write_json_atomic(_provenance_path(path), {
        "schema_version": 1,
        "artifact_sha256": sha256_file(path),
        "context": context,
        **extra,
    })


def _reusable(path: Path, validator, context: dict[str, Any]) -> dict[str, Any] | None:
    sidecar = _provenance_path(path)
    if not (path.exists() or path.is_symlink() or sidecar.exists() or sidecar.is_symlink()):
        return None
    if path.is_symlink() or sidecar.is_symlink() or not path.is_file() or not sidecar.is_file():
        return None
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        validator(path)
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError):
        return None
    if (
        not isinstance(metadata, dict)
        or metadata.get("artifact_sha256") != sha256_file(path)
        or metadata.get("context") != context
    ):
        return None
    return metadata


def _completed_delivery(
    delivery: Path,
    work: Path,
    *,
    source_hash: str,
    raw_hash: str,
    mid_hash: str,
    model_directory: Path,
    model_hashes: dict[str, str],
    context_key: str,
    actual_versions: dict[str, str],
    frames: int,
    flac_name: str,
    mp3_name: str,
) -> dict[str, Any] | None:
    completion_path = delivery / "completion.json"
    try:
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    expected = {
        "schema_version": 1,
        "mode": "dfn30_parallel",
        "source_sha256": source_hash,
        "source_pcm_sha256": raw_hash,
        "original_mid_sha256": mid_hash,
        "model_directory": str(model_directory.resolve()),
        "model_hashes": model_hashes,
        "attenuation_db": ATTENUATION_DB,
        "chunk_policy": {"core_samples": CORE_SAMPLES, "halo_samples": HALO_SAMPLES, "blend_samples": BLEND_SAMPLES},
        "cache_context_key": context_key,
        "tool_versions": actual_versions,
        "frames": frames,
        "listening_status": "pending",
    }
    if not isinstance(completion, dict) or any(completion.get(key) != value for key, value in expected.items()):
        return None
    artifacts = completion.get("artifacts")
    paths = {
        "adaptive.wav": work / "adaptive.wav",
        flac_name: delivery / flac_name,
        mp3_name: delivery / mp3_name,
        "qa-report.json": delivery / "qa-report.json",
        "listening-checklist.md": delivery / "listening-checklist.md",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != set(paths):
        return None
    master_record = completion.get("delivery_master")
    allowed_masters = {
        str(work / "normalized-master.wav"): work / "normalized-master.wav",
        str(delivery / "D30-delivery-master.wav"): delivery / "D30-delivery-master.wav",
    }
    if (
        not isinstance(master_record, dict)
        or set(master_record) != {"path", "sha256"}
        or not isinstance(master_record.get("path"), str)
        or master_record["path"] not in allowed_masters
    ):
        return None
    master_path = allowed_masters[master_record["path"]]
    try:
        for name, path in paths.items():
            if path.is_symlink() or not path.is_file() or artifacts.get(name) != sha256_file(path):
                return None
        if master_path.is_symlink() or not master_path.is_file() or master_record.get("sha256") != sha256_file(master_path):
            return None
        qa_report = json.loads(paths["qa-report.json"].read_text(encoding="utf-8"))
        if (
            not isinstance(qa_report, dict)
            or completion.get("chunk_boundaries") != qa_report.get("expected_boundary_samples")
        ):
            return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return completion


def _recover_incomplete_delivery(
    delivery: Path, work: Path, **completion_context: Any
) -> dict[str, Any] | None:
    if not (delivery.exists() or delivery.is_symlink()):
        return None
    completion = delivery / "completion.json"
    if delivery.is_symlink() or not delivery.is_dir():
        raise RuntimeError("delivery leaf is not a real directory")
    if completion.is_file() and not completion.is_symlink():
        if completed := _completed_delivery(delivery, work, **completion_context):
            return completed
    quarantine = work / f"interrupted-delivery-{uuid.uuid4().hex}"
    os.replace(delivery, quarantine)
    return None


def _publish_awaiting_listening(
    job: dict[str, Any], job_path: Path, delivery: Path, flac_name: str, mp3_name: str
) -> None:
    updated_job = dict(job)
    updated_delivery = dict(_require_mapping(updated_job["delivery"], "job delivery"))
    updated_delivery.update({
        "status": "awaiting_final_listening", "flac_path": str(delivery / flac_name),
        "mp3_path": str(delivery / mp3_name), "completion_path": str(delivery / "completion.json"),
        "qa_report_path": str(delivery / "qa-report.json"),
        "listening_checklist_path": str(delivery / "listening-checklist.md"),
    })
    updated_job["delivery"] = updated_delivery
    updated_job["stage"] = "awaiting_final_listening"
    write_json_atomic(job_path, updated_job)


def _run_generic_d30_locked(job_path: Path) -> dict[str, Any]:
    """Render one approved job with one, cacheable DeepFilterNet3 D30 pass."""
    job_path = Path(job_path)
    job, source_path, source_hash = _require_approved_job(job_path)
    flac_name, mp3_name = _delivery_names(source_path)
    job_root = job_path.parent.resolve()
    work = job_root / "work"
    delivery = job_root / "delivery"
    work.mkdir(parents=True, exist_ok=True)

    model_directory = job_root / "model" / "DeepFilterNet3"
    model_hashes = _model_hashes(model_directory)
    executable = Path(sys.executable).with_name("deepFilter.exe")
    if not executable.is_file():
        raise FileNotFoundError(executable)
    ffmpeg, ffprobe = resolve_tool("ffmpeg"), resolve_tool("ffprobe")
    actual_versions = _current_tool_versions(str(executable), ffmpeg, ffprobe)
    versions = _render_versions(actual_versions, model_hashes)

    raw, mid, side = work / "decoded-raw.wav", work / "original-mid.wav", work / "original-side.wav"
    raw_context = {"kind": "decoded-raw-v1", "source_sha256": source_hash, "ffmpeg": actual_versions["ffmpeg"]}
    if _reusable(raw, _require_stereo_float, raw_context) is None:
        _discard_work_artifact(raw)
        decode_float_stereo(source_path, raw, ffmpeg)
        _require_stereo_float(raw)
        _publish_provenance(raw, raw_context)
    frames = _require_stereo_float(raw)
    raw_hash = sha256_file(raw)
    mid_context = {"kind": "original-mid-v1", "raw_sha256": raw_hash}
    side_context = {"kind": "original-side-v1", "raw_sha256": raw_hash}
    if (
        _reusable(mid, lambda path: _require_mono_float(path, frames), mid_context) is None
        or _reusable(side, lambda path: _require_mono_float(path, frames), side_context) is None
    ):
        _discard_work_artifact(mid)
        _discard_work_artifact(side)
        stream_headroom_mid_side(raw, mid, side)
        _require_mono_float(mid, frames)
        _require_mono_float(side, frames)
        _publish_provenance(mid, mid_context)
        _publish_provenance(side, side_context)

    mid_hash, side_hash = sha256_file(mid), sha256_file(side)
    context_key = build_render_context_key(
        raw_hash, mid_hash, ATTENUATION_DB, SAMPLE_RATE, CORE_SAMPLES, HALO_SAMPLES,
        BLEND_SAMPLES, "generic-d30-full-timeline-v1", versions,
    )
    if completed := _recover_incomplete_delivery(
        delivery, work, source_hash=source_hash, raw_hash=raw_hash, mid_hash=mid_hash,
        model_directory=model_directory, model_hashes=model_hashes, context_key=context_key,
        actual_versions=actual_versions, frames=frames, flac_name=flac_name, mp3_name=mp3_name,
    ):
        _publish_awaiting_listening(job, job_path, delivery, flac_name, mp3_name)
        return completed
    enhancer = _CacheRootDfnAdapter(
        CachedDfnAdapter(
            _ScratchDfnAdapter(
                DfnAdapter(str(executable), versions["model"], model_directory=model_directory),
                work / "dfn-scratch",
            ),
            {
                "render_context_key": context_key,
                "stage": "generic-d30",
                "chunk_policy": {"core_samples": CORE_SAMPLES, "halo_samples": HALO_SAMPLES, "blend_samples": BLEND_SAMPLES},
                "model_hashes": model_hashes,
            },
            versions,
        ),
        work / "c",
    )
    rendered_mid, adaptive = work / "rendered-mid.wav", work / "adaptive.wav"
    rendered_context = {
        "kind": "rendered-mid-v1", "render_context_key": context_key,
        "original_mid_sha256": mid_hash,
    }
    rendered_metadata = _reusable(rendered_mid, lambda path: _require_mono_float(path, frames), rendered_context)
    if rendered_metadata is None:
        _discard_work_artifact(rendered_mid)
        render = render_file(mid, rendered_mid, enhancer, SAMPLE_RATE, ATTENUATION_DB, CORE_SAMPLES, HALO_SAMPLES, BLEND_SAMPLES, work / "cache")
        _require_mono_float(rendered_mid, frames)
        _publish_provenance(rendered_mid, rendered_context, render=render)
    else:
        render = rendered_metadata.get("render")
        if not isinstance(render, dict) or render.get("samples") != frames or render.get("sample_rate") != SAMPLE_RATE or not isinstance(render.get("boundaries"), list):
            _discard_work_artifact(rendered_mid)
            render = render_file(mid, rendered_mid, enhancer, SAMPLE_RATE, ATTENUATION_DB, CORE_SAMPLES, HALO_SAMPLES, BLEND_SAMPLES, work / "cache")
            _require_mono_float(rendered_mid, frames)
            _publish_provenance(rendered_mid, rendered_context, render=render)
    rendered_hash = sha256_file(rendered_mid)
    adaptive_context = {
        "kind": "adaptive-v1", "render_context_key": context_key,
        "rendered_mid_sha256": rendered_hash, "original_side_sha256": side_hash,
    }
    if _reusable(adaptive, lambda path: _require_stereo_float(path, frames), adaptive_context) is None:
        _discard_work_artifact(adaptive)
        _reconstruct_stereo(rendered_mid, side, adaptive, frames)
        _publish_provenance(adaptive, adaptive_context)

    normalized = work / "normalized-master.wav"
    adaptive_hash = sha256_file(adaptive)
    normalized_context = {
        "kind": "normalized-master-v1", "adaptive_sha256": adaptive_hash,
        "ffmpeg": actual_versions["ffmpeg"],
    }
    if _reusable(normalized, lambda path: _require_stereo_float(path, frames), normalized_context) is None:
        _discard_work_artifact(normalized)
        normalize_two_pass(ffmpeg, adaptive, normalized, frames)
        _require_stereo_float(normalized, frames)
        _publish_provenance(normalized, normalized_context)

    stage = _delivery_stage(work, uuid.uuid4().hex)
    stage.mkdir()
    staged_flac, staged_mp3 = stage / flac_name, stage / mp3_name
    stage_master_input = stage / "normalized-master.wav"
    delivery_created = False
    try:
        os.link(normalized, stage_master_input)
        exported = export_matched_pair(
            ffmpeg, stage_master_input, staged_flac, staged_mp3,
            lambda path: _measure_delivery(ffmpeg, ffprobe, path, frames),
        )
        stage_master = Path(exported["delivery_master"])
        delivery.mkdir()
        delivery_created = True
        flac, mp3 = delivery / flac_name, delivery / mp3_name
        master = normalized
        os.link(staged_flac, flac)
        os.link(staged_mp3, mp3)
        if stage_master.resolve() != stage_master_input.resolve():
            master = delivery / "D30-delivery-master.wav"
            os.link(stage_master, master)
        report = collect_qa_report(
            source_samples=frames,
            adaptive_samples=int(sf.info(adaptive).frames),
            master_probe={"frames": int(sf.info(master).frames)},
            flac_probe={key: exported["flac"][key] for key in ("frames", "sample_rate", "channels", "bits_per_raw_sample", "codec_name", "container_name")},
            mp3_probe={"decoded_frames": exported["mp3"]["frames"], **{key: exported["mp3"][key] for key in ("sample_rate", "channels", "bit_rate", "codec_delay_padding_samples", "codec_name", "container_name")}},
            flac_metrics=exported["flac"], mp3_metrics=exported["mp3"], flac_path=flac, mp3_path=mp3,
            integrity=_output_integrity(mid, side, flac), boundary_scores=_boundary_scores(adaptive, render["boundaries"]),
            candidate_window_scores=[], expected_boundary_samples=render["boundaries"],
            expected_candidate_window_ids=[], source_path=source_path, adaptive_path=adaptive,
            delivery_master_path=master, listening_checklist_path=delivery / "listening-checklist.md",
        )
        publish_qa_pair(report, delivery / "qa-report.json", delivery / "listening-checklist.md")
    except BaseException:
        if delivery_created:
            shutil.rmtree(delivery)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    completion = {
        "schema_version": 1, "mode": "dfn30_parallel", "source_sha256": source_hash,
        "source_pcm_sha256": raw_hash, "original_mid_sha256": mid_hash,
        "model_directory": str(model_directory.resolve()), "model_hashes": model_hashes,
        "attenuation_db": ATTENUATION_DB,
        "chunk_policy": {"core_samples": CORE_SAMPLES, "halo_samples": HALO_SAMPLES, "blend_samples": BLEND_SAMPLES},
        "cache_context_key": context_key, "tool_versions": actual_versions, "frames": frames,
        "chunk_boundaries": render["boundaries"], "listening_status": "pending",
        "delivery_master": {"path": str(master), "sha256": sha256_file(master)},
        "artifacts": {
            "adaptive.wav": sha256_file(adaptive), flac_name: sha256_file(flac), mp3_name: sha256_file(mp3),
            "qa-report.json": sha256_file(delivery / "qa-report.json"),
            "listening-checklist.md": sha256_file(delivery / "listening-checklist.md"),
        },
    }
    write_json_atomic(delivery / "completion.json", completion)
    _publish_awaiting_listening(job, job_path, delivery, flac_name, mp3_name)
    return completion


def run_generic_d30(job_path: Path) -> dict[str, Any]:
    """Validate and exclusively render one canonical approved job."""
    paths = existing_job_paths(Path(job_path))
    with job_lock(paths, blocking=False):
        return _run_generic_d30_locked(paths.job_file)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="generic_d30")
    parser.add_argument("--job", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_generic_d30(args.job)
    except JobBusy as error:
        print(f"generic_d30: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
