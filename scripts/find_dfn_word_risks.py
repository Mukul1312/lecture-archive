"""Find moments where aggressive DFN may have weakened speech evidence.

This is a triage tool, not an Odia intelligibility judge. It compares each
original/enhanced work chunk before loudness normalisation, ranks unusually
large broadband or consonant-band losses inside speech-like context, and adds
every stitch boundary as a mandatory audit item. The resulting JSON is meant
to drive synchronized human-listening clips.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import binary_closing, binary_dilation, uniform_filter1d
from scipy.signal import butter, sosfilt


SR = 48_000
HOP_MS = 10
FRAME_MS = 30


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(path), dtype="float32")
    if audio.ndim != 1:
        raise ValueError(f"expected mono audio: {path}")
    return audio, sr


def frame_rms(audio: np.ndarray, frame: int, hop: int) -> np.ndarray:
    if len(audio) < frame:
        return np.array([np.sqrt(np.mean(audio * audio) + 1e-20)], dtype=np.float32)
    count = 1 + (len(audio) - frame) // hop
    shape = (count, frame)
    strides = (audio.strides[0] * hop, audio.strides[0])
    windows = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)
    return np.sqrt(np.mean(windows * windows, axis=1) + 1e-20)


def band_levels(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    frame = round(sr * FRAME_MS / 1000)
    hop = round(sr * HOP_MS / 1000)
    broad = sosfilt(butter(4, [100, 7900], btype="bandpass", fs=sr, output="sos"), audio)
    consonant = sosfilt(butter(4, [2500, 7900], btype="bandpass", fs=sr, output="sos"), audio)
    return frame_rms(broad, frame, hop), frame_rms(consonant, frame, hop)


def db(value: np.ndarray) -> np.ndarray:
    return 20 * np.log10(np.maximum(value, 1e-10))


def time_match(values: np.ndarray, count: int) -> np.ndarray:
    """Map a shorter crossfaded render onto the original chunk's relative time."""
    if len(values) == count:
        return values
    source = np.linspace(0.0, 1.0, len(values), dtype=np.float64)
    target = np.linspace(0.0, 1.0, count, dtype=np.float64)
    return np.interp(target, source, values).astype(np.float32)


def align_to_reference(reference: np.ndarray, candidate: np.ndarray,
                       max_lag_frames: int = 100) -> tuple[np.ndarray, int, float]:
    """Compensate DFN/filter latency by maximizing smoothed-envelope correlation."""
    candidate = time_match(candidate, len(reference))
    ref = uniform_filter1d(db(reference), size=21, mode="nearest")
    cand = uniform_filter1d(db(candidate), size=21, mode="nearest")
    margin = max_lag_frames + 1
    core = ref[margin:-margin]
    core = core - np.mean(core)
    core_norm = np.linalg.norm(core) + 1e-12
    best_lag, best_corr = 0, -1.0
    for lag in range(-max_lag_frames, max_lag_frames + 1):
        other = cand[margin + lag:len(cand) - margin + lag]
        other = other - np.mean(other)
        corr = float(np.dot(core, other) / (core_norm * (np.linalg.norm(other) + 1e-12)))
        if corr > best_corr:
            best_lag, best_corr = lag, corr
    indices = np.arange(len(candidate), dtype=np.float64) + best_lag
    aligned = np.interp(indices, np.arange(len(candidate)), candidate,
                        left=candidate[0], right=candidate[-1]).astype(np.float32)
    return aligned, best_lag, best_corr


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.pad(mask.astype(np.int8), (1, 1))))
    return [(int(a), int(b)) for a, b in edges.reshape(-1, 2)]


def likely_internal_joins(original: np.ndarray, join_count: int, sr: int) -> list[float]:
    """Conservatively cover recursive midpoint splits whose exact logs were not saved."""
    if join_count <= 0:
        return []
    # One split is near 1/2. Two means 1/2 plus either 1/4 or 3/4, so audit
    # both possibilities. Three means all three. This recording has at most 3.
    fractions = [0.5] if join_count == 1 else [0.25, 0.5, 0.75]
    frame = 2048
    count = len(original) // frame
    levels = frame_rms(original[:count * frame], frame, frame)
    radius = round(20 * sr / frame)
    found = []
    for fraction in fractions:
        center = round(fraction * len(levels))
        lo, hi = max(0, center - radius), min(len(levels), center + radius)
        quiet = lo + int(np.argmin(levels[lo:hi]))
        found.append(quiet * frame / sr)
    return found


def analyse_chunk(original: np.ndarray, enhanced: np.ndarray, sr: int) -> tuple[list[dict], dict]:
    ob, oh = band_levels(original, sr)
    eb, eh = band_levels(enhanced, sr)
    eb, lag, envelope_corr = align_to_reference(ob, eb)
    eh = time_match(eh, len(oh))
    indices = np.arange(len(eh), dtype=np.float64) + lag
    eh = np.interp(indices, np.arange(len(eh)), eh, left=eh[0], right=eh[-1]).astype(np.float32)
    ob_db, oh_db, eb_db, eh_db = map(db, (ob, oh, eb, eh))

    # Estimate ordinary DFN level change from strong speech, then flag only
    # unusually larger local losses. This avoids calling normal denoising a cut.
    strong = ob_db >= np.percentile(ob_db, 70)
    ordinary_broad = float(np.median((ob_db - eb_db)[strong]))
    ordinary_high = float(np.median((oh_db - eh_db)[strong]))
    broad_excess = ob_db - eb_db - ordinary_broad
    high_excess = oh_db - eh_db - ordinary_high

    # Recall-biased speech context: energy above p30, supported by activity in
    # a +/-250 ms neighborhood. Weak consonants between vowels remain eligible.
    active = ob_db >= np.percentile(ob_db, 30)
    context = uniform_filter1d(active.astype(np.float32), size=51, mode="constant") >= 0.22
    original_high_present = oh_db >= np.percentile(oh_db, 35)

    score = np.maximum(broad_excess - 4.0, 0.0)
    score += 0.65 * np.maximum(high_excess - 6.0, 0.0) * original_high_present
    suspicious = context & (score >= 3.0)
    suspicious = binary_closing(suspicious, iterations=8)
    suspicious = binary_dilation(suspicious, iterations=12)

    events = []
    for start, stop in runs(suspicious):
        local = score[start:stop]
        if not len(local):
            continue
        peak = start + int(np.argmax(local))
        events.append({
            "local_start_s": start * HOP_MS / 1000,
            "local_end_s": stop * HOP_MS / 1000,
            "local_peak_s": peak * HOP_MS / 1000,
            "risk_score": float(score[peak]),
            "broadband_excess_loss_db": float(broad_excess[peak]),
            "consonant_excess_loss_db": float(high_excess[peak]),
        })
    stats = {
        "alignment_lag_ms": lag * HOP_MS,
        "alignment_envelope_correlation": envelope_corr,
        "ordinary_broad_loss_db": ordinary_broad,
        "ordinary_consonant_loss_db": ordinary_high,
        "suspicious_regions": len(events),
    }
    return events, stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=Path("data/enhance/out/part-01/_work"))
    parser.add_argument("--output", type=Path,
                        default=Path("data/enhance/out/part-01/word-risk-audit.json"))
    args = parser.parse_args()

    originals = sorted(args.work.glob("10_chunk*.wav"))
    enhanced = sorted(args.work.glob("20_enh*.wav"))
    if not originals or len(originals) != len(enhanced):
        raise SystemExit(f"chunk mismatch: {len(originals)} original, {len(enhanced)} enhanced")

    all_events: list[dict] = []
    chunk_rows: list[dict] = []
    original_cursor = 0.0
    enhanced_cursor = 0.0
    for index, (op, ep) in enumerate(zip(originals, enhanced)):
        original, osr = read_mono(op)
        candidate, esr = read_mono(ep)
        if osr != SR or esr != SR:
            raise ValueError(f"unexpected sample rate in chunk {index}: {osr}, {esr}")
        events, stats = analyse_chunk(original, candidate, SR)
        odur, edur = len(original) / SR, len(candidate) / SR
        for event in events:
            relative = event["local_peak_s"] / odur
            event.update({
                "kind": "acoustic-risk",
                "chunk": index,
                "original_time_s": original_cursor + event["local_peak_s"],
                "enhanced_time_s": enhanced_cursor + relative * edur,
            })
            all_events.append(event)
        chunk_rows.append({
            "chunk": index,
            "original": str(op),
            "enhanced": str(ep),
            "original_start_s": original_cursor,
            "enhanced_start_s": enhanced_cursor,
            "original_duration_s": odur,
            "enhanced_duration_s": edur,
            "crossfade_removed_ms": 1000 * (odur - edur),
            **stats,
        })
        internal_count = round((odur - edur) / 0.030)
        for local_time in likely_internal_joins(original, internal_count, SR):
            all_events.append({
                "kind": "mandatory-internal-join-candidate",
                "chunk": index,
                "risk_score": None,
                "original_time_s": original_cursor + local_time,
                "enhanced_time_s": enhanced_cursor + (local_time / odur) * edur,
            })
        original_cursor += odur
        enhanced_cursor += edur
        if index < len(originals) - 1:
            all_events.append({
                "kind": "mandatory-outer-join",
                "chunk": index,
                "risk_score": None,
                "original_time_s": original_cursor,
                "enhanced_time_s": enhanced_cursor - 0.030,
            })
            enhanced_cursor -= 0.030  # outer stitch overlaps 30 ms
        print(f"chunk {index:02d}: {len(events):3d} acoustic risks, "
              f"internal shortening {1000 * (odur-edur):.0f} ms")

    acoustic = sorted(
        (e for e in all_events if e["kind"] == "acoustic-risk"),
        key=lambda e: e["risk_score"], reverse=True,
    )
    for rank, event in enumerate(acoustic, 1):
        event["rank"] = rank
    payload = {
        "warning": "Candidates only. An Odia-speaking listener must decide whether a word is cut.",
        "analysis": {
            "sample_rate": SR,
            "frame_ms": FRAME_MS,
            "hop_ms": HOP_MS,
            "original_duration_s": original_cursor,
            "enhanced_stitched_duration_s": enhanced_cursor,
            "acoustic_risk_count": len(acoustic),
            "mandatory_join_count": sum(
                e["kind"].startswith("mandatory-") for e in all_events
            ),
        },
        "chunks": chunk_rows,
        "events": all_events,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")
    mandatory = sum(e["kind"].startswith("mandatory-") for e in all_events)
    print(f"{len(acoustic)} ranked acoustic risks + {mandatory} mandatory join audits")


if __name__ == "__main__":
    main()
