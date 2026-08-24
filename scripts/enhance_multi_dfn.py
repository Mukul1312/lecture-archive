"""Blend parallel DeepFilterNet renders without stacking enhancement passes.

The accepted DFN24 render remains untouched through speech and uncertain audio.
A stronger render is used only inside long, low-energy regions detected from the
original recording.  Every switch is guarded and smoothly crossfaded.

Example (the existing five-minute evaluation ladder):

    .venv/Scripts/python.exe scripts/enhance_multi_dfn.py \
        --original data/enhance/poc/v2/00_original.wav \
        --speech data/enhance/poc/v2/13_dfn_atten24.wav \
        --pause data/enhance/poc/v2/14_dfn_full.wav \
        --output data/enhance/poc/v2/16_multi_dfn24_full_pauses.wav

All DFN inputs must be parallel renders of the same original—not outputs fed
serially through DFN—and must have identical sample counts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import binary_closing, uniform_filter1d


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(str(path), dtype="float32")
    if audio.ndim != 1:
        raise ValueError(f"Expected mono audio: {path}")
    return audio, sample_rate


def frame_rms(audio: np.ndarray, frame: int, hop: int) -> np.ndarray:
    if len(audio) < frame:
        return np.array([np.sqrt(np.mean(audio * audio) + 1e-20)])
    count = 1 + (len(audio) - frame) // hop
    shape = (count, frame)
    strides = (audio.strides[0] * hop, audio.strides[0])
    windows = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)
    return np.sqrt(np.mean(windows * windows, axis=1) + 1e-20)


def guarded_pause_mask(
    original: np.ndarray,
    sample_rate: int,
    percentile: float,
    min_pause_ms: float,
    guard_ms: float,
    fade_ms: float,
) -> tuple[np.ndarray, float, list[tuple[float, float]]]:
    hop = max(1, round(sample_rate * 0.010))
    frame = max(hop, round(sample_rate * 0.020))
    levels = frame_rms(original, frame, hop)
    threshold = float(np.percentile(levels, percentile))
    low = levels <= threshold

    # Bridge only very short holes in an otherwise quiet interval.
    low = binary_closing(low, iterations=max(1, round(0.050 * sample_rate / hop)))
    # ``min_pause_ms`` is the minimum usable strong-render interior. The raw
    # low-energy run must additionally contain a guard on both sides.
    min_frames = max(1, round(min_pause_ms / 1000 * sample_rate / hop))
    guard_frames = max(0, round(guard_ms / 1000 * sample_rate / hop))
    selected = np.zeros_like(low, dtype=bool)
    regions: list[tuple[float, float]] = []

    padded = np.pad(low.astype(np.int8), (1, 1))
    changes = np.flatnonzero(np.diff(padded))
    for start, stop in changes.reshape(-1, 2):
        if stop - start < min_frames + 2 * guard_frames:
            continue
        inner_start = start + guard_frames
        inner_stop = stop - guard_frames
        if inner_stop <= inner_start:
            continue
        selected[inner_start:inner_stop] = True
        regions.append((inner_start * hop / sample_rate, inner_stop * hop / sample_rate))

    frame_times = np.arange(len(selected), dtype=np.float64) * hop
    sample_mask = np.interp(
        np.arange(len(original), dtype=np.float64),
        frame_times,
        selected.astype(np.float32),
        left=0.0,
        right=0.0,
    )
    # A moving average turns each hard boundary into a linear crossfade in
    # O(number_of_samples); a wide Gaussian is needlessly expensive here.
    fade_samples = max(1, round(fade_ms / 1000 * sample_rate))
    sample_mask = uniform_filter1d(sample_mask, size=fade_samples, mode="constant")
    return np.clip(sample_mask, 0.0, 1.0), threshold, regions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--speech", type=Path, required=True,
                        help="accepted render used through all speech, currently DFN24")
    parser.add_argument("--pause", type=Path, required=True,
                        help="strong parallel render used only inside guarded pauses")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--silence-percentile", type=float, default=20.0)
    parser.add_argument("--min-pause-ms", type=float, default=500.0)
    parser.add_argument("--guard-ms", type=float, default=250.0)
    parser.add_argument("--fade-ms", type=float, default=120.0)
    args = parser.parse_args()

    original, sr = read_mono(args.original)
    speech, speech_sr = read_mono(args.speech)
    pause, pause_sr = read_mono(args.pause)
    if speech_sr != sr or pause_sr != sr:
        raise ValueError(f"Sample-rate mismatch: original={sr}, speech={speech_sr}, pause={pause_sr}")
    if len(speech) != len(original) or len(pause) != len(original):
        raise ValueError(
            "Inputs must have identical sample counts: "
            f"original={len(original)}, speech={len(speech)}, pause={len(pause)}"
        )

    mask, threshold, regions = guarded_pause_mask(
        original,
        sr,
        args.silence_percentile,
        args.min_pause_ms,
        args.guard_ms,
        args.fade_ms,
    )
    output = speech * (1.0 - mask) + pause * mask
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.output), output.astype("float32"), sr, subtype="FLOAT")

    threshold_db = 20 * np.log10(max(threshold, 1e-12))
    print(f"wrote: {args.output}")
    print(f"duration: {len(output) / sr:.3f} s (exactly preserved)")
    print(f"pause threshold: {threshold_db:.2f} dBFS (p{args.silence_percentile:g})")
    print(f"guarded regions: {len(regions)}")
    print(f"strong-render occupancy: {100 * np.mean(mask > 0.5):.2f}%")
    for start, stop in regions:
        print(f"  {start:9.3f} - {stop:9.3f} s")


if __name__ == "__main__":
    main()
