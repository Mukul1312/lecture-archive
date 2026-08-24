"""Immutable two-pass loudness normalization and matched delivery exports."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

import soundfile as sf


SAMPLE_RATE = 48000
CHANNELS = 2
TARGET_LUFS = -16.0
TARGET_TRUE_PEAK = -1.5
LOUDNESS_TOLERANCE = 0.5
MAX_MP3_DELAY_PADDING = 1152


def _fresh_destination(path: Path) -> None:
    """Refuse all pre-existing destinations, including dangling symlinks."""
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable output: {path}")


def _distinct(source: Path, *destinations: Path) -> None:
    source_resolved = source.resolve()
    resolved = tuple(destination.resolve() for destination in destinations)
    if source_resolved in resolved or len(set(resolved)) != len(resolved):
        raise ValueError("source and output paths must be distinct")


def _stage_for(destination: Path) -> Path:
    """Create a same-parent private stage whose final suffix selects a muxer."""
    return destination.with_name(
        f".{destination.stem}.{uuid.uuid4().hex}.stage{destination.suffix}"
    )


def _discard_stage(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        path.unlink()


def _publish_set(stages: dict[Path, Path]) -> None:
    """Hard-link a complete staged set, rolling back only our own links."""
    for destination in stages:
        _fresh_destination(destination)
    published: list[tuple[Path, Path]] = []
    try:
        for destination, stage in stages.items():
            os.link(stage, destination)
            published.append((destination, stage))
    except BaseException:
        for destination, stage in reversed(published):
            try:
                if os.path.samestat(os.stat(destination), os.stat(stage)):
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        for stage in stages.values():
            _discard_stage(stage)


def _require_measured(measured: dict[str, str]) -> None:
    required = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    missing = required.difference(measured)
    if missing:
        raise RuntimeError(f"ffmpeg loudnorm measurements missing: {', '.join(sorted(missing))}")
    try:
        for key in required:
            if not math.isfinite(float(measured[key])):
                raise ValueError(key)
    except (TypeError, ValueError) as error:
        raise RuntimeError("ffmpeg loudnorm measurements must be finite numbers") from error


def parse_loudnorm_json(stderr: str) -> dict[str, str]:
    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', stderr, flags=re.S)
    if not matches:
        raise RuntimeError("ffmpeg loudnorm did not return measured JSON")
    try:
        measured = json.loads(matches[-1])
    except json.JSONDecodeError as error:
        raise RuntimeError("ffmpeg loudnorm returned invalid measured JSON") from error
    if not isinstance(measured, dict):
        raise RuntimeError("ffmpeg loudnorm measured JSON must be an object")
    _require_measured(measured)
    return {key: str(value) for key, value in measured.items()}


def build_second_pass_filter(
    measured: dict[str, str], target_i: float, target_tp: float
) -> str:
    _require_measured(measured)
    return (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA=11"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        ":linear=true:print_format=json"
    )


def build_export_commands(
    ffmpeg: str, master: Path, flac: Path, mp3: Path
) -> tuple[list[str], list[str]]:
    common = [
        ffmpeg, "-nostdin", "-n", "-v", "error", "-i", str(master),
        "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
    ]
    flac_command = common + [
        "-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24", str(flac),
    ]
    mp3_command = common + ["-c:a", "libmp3lame", "-b:a", "192k", str(mp3)]
    return flac_command, mp3_command


def _run_checked(runner: Callable[..., Any], command: list[str], **kwargs: Any) -> Any:
    result = runner(command, **kwargs)
    if getattr(result, "returncode", 0) != 0:
        raise RuntimeError(f"ffmpeg failed: {getattr(result, 'stderr', '')[-1200:]}")
    return result


def _valid_master(info: Any, expected_frames: int, *, require_float: bool = True) -> None:
    if (
        info.samplerate != SAMPLE_RATE
        or info.channels != CHANNELS
        or info.frames != expected_frames
        or (require_float and info.subtype != "FLOAT")
    ):
        raise RuntimeError("master must be exact-length 48 kHz stereo PCM")


def normalize_two_pass(
    ffmpeg: str,
    source: Path,
    destination: Path,
    expected_frames: int,
    *,
    runner: Callable[..., Any] = subprocess.run,
    audio_info: Callable[[Path], Any] = sf.info,
) -> dict[str, str]:
    """Normalize exactly once, retaining the adaptive WAV's exact timeline."""
    if isinstance(expected_frames, bool) or expected_frames <= 0:
        raise ValueError("expected_frames must be a positive integer")
    _distinct(source, destination)
    _fresh_destination(destination)
    _valid_master(audio_info(source), expected_frames, require_float=True)
    first = [
        ffmpeg, "-nostdin", "-hide_banner", "-i", str(source), "-af",
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK}:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    measured_run = _run_checked(runner, first, capture_output=True, text=True)
    measured = parse_loudnorm_json(measured_run.stderr)
    stage = _stage_for(destination)
    second = [
        ffmpeg, "-nostdin", "-n", "-v", "error", "-i", str(source), "-af",
        build_second_pass_filter(measured, TARGET_LUFS, TARGET_TRUE_PEAK),
        "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-c:a", "pcm_f32le", str(stage),
    ]
    try:
        _run_checked(runner, second, check=True)
        _valid_master(audio_info(stage), expected_frames, require_float=True)
        _publish_set({destination: stage})
    except BaseException:
        _discard_stage(stage)
        raise
    return measured


def _metric_number(metrics: dict[str, Any], key: str) -> float:
    try:
        value = float(metrics[key])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f"decoded delivery metric is missing or invalid: {key}") from error
    if value != value or value in (float("inf"), float("-inf")):
        raise RuntimeError(f"decoded delivery metric is non-finite: {key}")
    return value


def _metric_integer(metrics: dict[str, Any], key: str) -> int:
    value = metrics.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"decoded delivery metric must be a raw integer: {key}")
    if value < 0:
        raise RuntimeError(f"decoded delivery metric cannot be negative: {key}")
    return value


def _validate_decoded_delivery(
    metrics: dict[str, Any], kind: str, expected_frames: int
) -> None:
    if metrics.get("decode_ok") is not True:
        raise RuntimeError(f"decoded {kind} did not complete successfully")
    if _metric_integer(metrics, "sample_rate") != SAMPLE_RATE or _metric_integer(metrics, "channels") != CHANNELS:
        raise RuntimeError(f"decoded {kind} is not 48 kHz stereo")
    if not (TARGET_LUFS - LOUDNESS_TOLERANCE <= _metric_number(metrics, "integrated_lufs") <= TARGET_LUFS + LOUDNESS_TOLERANCE):
        raise RuntimeError(f"decoded {kind} loudness is outside -16 LUFS +/-0.5")
    if _metric_number(metrics, "true_peak_dbtp") > TARGET_TRUE_PEAK:
        raise RuntimeError(f"decoded {kind} true peak exceeds -1.5 dBTP")
    frames = _metric_integer(metrics, "frames")
    if kind == "FLAC":
        if (frames != expected_frames or _metric_integer(metrics, "bits_per_raw_sample") != 24
                or metrics.get("codec_name") != "flac" or metrics.get("container_name") != "flac"):
            raise RuntimeError("decoded FLAC changed PCM count or is not genuine 24-bit")
    else:
        delta = frames - expected_frames
        delay_padding = _metric_integer(metrics, "codec_delay_padding_samples")
        if delta < 0 or delta > MAX_MP3_DELAY_PADDING or delay_padding != delta:
            raise RuntimeError("decoded MP3 delay/padding is not verified within one MPEG frame")
        if (abs(_metric_integer(metrics, "bit_rate") - 192000) > 3000
                or metrics.get("codec_name") != "mp3" or metrics.get("container_name") != "mp3"):
            raise RuntimeError("decoded MP3 is not 192 kbps")


def export_matched_pair(
    ffmpeg: str,
    master: Path,
    flac: Path,
    mp3: Path,
    measure: Callable[[Path], dict[str, Any]],
    *,
    runner: Callable[..., Any] = subprocess.run,
    audio_info: Callable[[Path], Any] = sf.info,
) -> dict[str, Any]:
    """Encode a FLAC/MP3 pair from one master, publishing only after QA.

    Existing final artifacts are deliberately refused rather than guessed to
    match: explicit reuse needs the later run-manifest hash contract.
    """
    _distinct(master, flac, mp3)
    _fresh_destination(flac)
    _fresh_destination(mp3)
    corrected = master.with_name(f"{master.stem}-tp-corrected.wav")
    _distinct(master, corrected, flac, mp3)
    _fresh_destination(corrected)
    master_info = audio_info(master)
    _valid_master(master_info, master_info.frames, require_float=True)
    expected_frames = master_info.frames
    delivery_master = master
    created_stages: list[Path] = []
    corrected_stage: Path | None = None

    def encode(current_master: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
        flac_stage, mp3_stage = _stage_for(flac), _stage_for(mp3)
        created_stages.extend((flac_stage, mp3_stage))
        flac_command, mp3_command = build_export_commands(ffmpeg, current_master, flac_stage, mp3_stage)
        _run_checked(runner, flac_command, check=True)
        _run_checked(runner, mp3_command, check=True)
        return measure(flac_stage), measure(mp3_stage), flac_stage, mp3_stage

    try:
        flac_metrics, mp3_metrics, flac_stage, mp3_stage = encode(delivery_master)
        worst_peak = max(
            _metric_number(flac_metrics, "true_peak_dbtp"),
            _metric_number(mp3_metrics, "true_peak_dbtp"),
        )
        if worst_peak > TARGET_TRUE_PEAK:
            corrected_stage = _stage_for(corrected)
            created_stages.append(corrected_stage)
            correction = [
                ffmpeg, "-nostdin", "-n", "-v", "error", "-i", str(master), "-af",
                f"volume={TARGET_TRUE_PEAK - 0.05 - worst_peak:.6f}dB",
                "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-c:a", "pcm_f32le", str(corrected_stage),
            ]
            _run_checked(runner, correction, check=True)
            _valid_master(audio_info(corrected_stage), expected_frames, require_float=True)
            delivery_master = corrected_stage
            _discard_stage(flac_stage)
            _discard_stage(mp3_stage)
            flac_metrics, mp3_metrics, flac_stage, mp3_stage = encode(delivery_master)
        _validate_decoded_delivery(flac_metrics, "FLAC", expected_frames)
        _validate_decoded_delivery(mp3_metrics, "MP3", expected_frames)
        publication = {flac: flac_stage, mp3: mp3_stage}
        if corrected_stage is not None:
            publication[corrected] = corrected_stage
        _publish_set(publication)
    except BaseException:
        for stage in created_stages:
            _discard_stage(stage)
        raise
    return {"delivery_master": str(corrected if corrected_stage is not None else delivery_master), "flac": flac_metrics, "mp3": mp3_metrics}
