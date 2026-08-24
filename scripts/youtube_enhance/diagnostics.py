"""Read-only, conservative diagnostics and original-audio review material.

The labels in this module are proposals for human review, never authorization
to process a portion of the lecture.  ``write_original_review_material`` is
intended for the review stage: it only writes excerpts from the decoded stereo
source, using the sample coordinates recorded in the diagnostic report.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable

import numpy as np
import soundfile as sf

from scripts import enhance_diagnose as legacy_diagnostics

from .manifest import write_json_atomic
from .models import Segment, SegmentLabel
from .segments import segments_to_json, validate_segment_map
from .source import to_mid_side


SAMPLE_RATE = 48000
WINDOW_SAMPLES = 60 * SAMPLE_RATE
TIMELINE_FRAME_SAMPLES = 10 * SAMPLE_RATE
CONFIDENT_PROPOSAL = 0.90


@dataclass(frozen=True)
class WindowFeature:
    window_id: str
    start_sample: int
    label_hint: str
    floor_db: float
    active_db: float
    speech_confidence: float
    timeline_third: int
    role: str = ""


@dataclass(frozen=True)
class FrameProposal:
    start_sample: int
    end_sample: int
    label_hint: str
    confidence: float


def _db(value: float) -> float:
    return float(20 * np.log10(max(value, 1e-12)))


def scan_stereo_blocks(blocks: Iterable[np.ndarray], sample_rate: int) -> dict:
    """Measure decoded stereo without retaining more than one input block."""
    peak = 0.0
    samples = 0
    channel_sum = np.zeros(2, dtype=np.float64)
    channel_square = np.zeros(2, dtype=np.float64)
    lr_sum = 0.0
    mid_square = 0.0
    side_square = 0.0
    zero_run = longest_zero_run = dropout_runs = 0
    channel_zero_runs = np.zeros(2, dtype=np.int64)
    channel_zero_counts = np.zeros(2, dtype=np.int64)
    channel_longest_zero_runs = np.zeros(2, dtype=np.int64)
    channel_flat_runs = np.zeros(2, dtype=np.int64)
    channel_flat_counts = np.zeros(2, dtype=np.int64)
    channel_longest_flat_runs = np.zeros(2, dtype=np.int64)
    channel_pinned_samples = np.zeros(2, dtype=np.int64)

    for block in blocks:
        if block.ndim != 2 or block.shape[1] != 2:
            raise ValueError("diagnostic blocks must be stereo")
        if not len(block):
            continue
        current = block.astype(np.float64, copy=False)
        block_peak = float(np.max(np.abs(current)))
        peak = max(peak, block_peak)
        samples += len(current)
        channel_sum += current.sum(axis=0)
        channel_square += np.square(current).sum(axis=0)
        lr_sum += float(np.sum(current[:, 0] * current[:, 1]))
        mid, side = to_mid_side(current)
        mid_square += float(np.sum(np.square(mid)))
        side_square += float(np.sum(np.square(side)))

        both_zero = np.all(current == 0.0, axis=1)
        for is_zero in both_zero:
            if is_zero:
                zero_run += 1
                longest_zero_run = max(longest_zero_run, zero_run)
            else:
                dropout_runs += int(zero_run > 0)
                zero_run = 0

        # A flat top belongs to a channel.  Tracking each channel separately
        # prevents alternating pinned channels from becoming a fictitious run.
        for channel in range(2):
            for is_zero in current[:, channel] == 0.0:
                if is_zero:
                    channel_zero_runs[channel] += 1
                    channel_longest_zero_runs[channel] = max(
                        channel_longest_zero_runs[channel], channel_zero_runs[channel]
                    )
                else:
                    channel_zero_counts[channel] += int(channel_zero_runs[channel] > 0)
                    channel_zero_runs[channel] = 0
            for is_pinned in np.abs(current[:, channel]) >= 0.999:
                if is_pinned:
                    channel_flat_runs[channel] += 1
                    channel_longest_flat_runs[channel] = max(
                        channel_longest_flat_runs[channel], channel_flat_runs[channel]
                    )
                    channel_pinned_samples[channel] += 1
                else:
                    channel_flat_counts[channel] += int(channel_flat_runs[channel] >= 3)
                    channel_flat_runs[channel] = 0
    dropout_runs += int(zero_run > 0)
    channel_zero_counts += channel_zero_runs > 0
    channel_flat_counts += channel_flat_runs >= 3
    if samples == 0:
        raise ValueError("no samples supplied")

    means = channel_sum / samples
    variances = np.maximum(channel_square / samples - means * means, 1e-20)
    covariance = lr_sum / samples - means[0] * means[1]
    correlation = covariance / np.sqrt(variances[0] * variances[1])
    decoded_peak = _db(peak)
    return {
        "sample_rate": sample_rate,
        "samples": samples,
        "decoded_peak_dbfs": decoded_peak,
        # This lower bound is replaced with ffmpeg's oversampled measurement
        # in run_diagnostics.  Keeping the key makes streaming-only callers
        # explicit about the distinction rather than silently omitting it.
        "true_peak_dbfs": decoded_peak,
        "true_peak_method": "decoded-sample lower bound; loudnorm supplies oversampled value",
        "dc_offset": means.tolist(),
        "longest_zero_run_samples": longest_zero_run,
        "dropout_runs": int(dropout_runs),
        "per_channel_zero_run_counts": channel_zero_counts.tolist(),
        "per_channel_longest_zero_run_samples": channel_longest_zero_runs.tolist(),
        "flat_top_runs": int(channel_flat_counts.sum()),
        "longest_flat_top_run_samples": int(channel_longest_flat_runs.max()),
        "per_channel_flat_top_runs": channel_flat_counts.tolist(),
        "per_channel_longest_flat_top_run_samples": channel_longest_flat_runs.tolist(),
        "pct_pinned_full_scale": 100.0 * int(channel_pinned_samples.sum()) / (samples * 2),
        "per_channel_pct_pinned_full_scale": (100.0 * channel_pinned_samples / samples).tolist(),
        "left_right_correlation": float(correlation),
        "side_to_mid_db": float(
            10 * np.log10(max(side_square, 1e-20) / max(mid_square, 1e-20))
        ),
    }


def _min_by(rows: list[WindowFeature], key: str) -> WindowFeature:
    return min(rows, key=lambda item: (getattr(item, key), item.start_sample, item.window_id))


def _max_by(rows: list[WindowFeature], key: str) -> WindowFeature:
    return max(rows, key=lambda item: (getattr(item, key), -item.start_sample, item.window_id))


def select_representative_windows(rows: list[WindowFeature]) -> list[WindowFeature]:
    """Select review prompts while retaining the measurement-derived label."""
    speech = [item for item in rows if item.label_hint == "main_speech"]
    pauses = [item for item in rows if item.label_hint == "guarded_pause"]
    non_speech = [item for item in rows if item.label_hint != "main_speech" and item.label_hint != "guarded_pause"]
    choices: list[WindowFeature] = []
    if speech:
        choices.extend(
            [
                replace(_min_by(speech, "floor_db"), role="clean_speech"),
                replace(_max_by(speech, "floor_db"), role="noisy_speech"),
                replace(_min_by(speech, "active_db"), role="low_energy_speech"),
            ]
        )
    if pauses:
        choices.append(replace(_min_by(pauses, "start_sample"), role="guarded_pause"))
    if non_speech:
        choices.append(replace(_max_by(non_speech, "speech_confidence"), role="non_speech"))
    for third in (0, 1, 2):
        if not any(item.timeline_third == third for item in choices):
            pool = [item for item in rows if item.timeline_third == third]
            if pool:
                choices.append(replace(_max_by(pool, "speech_confidence"), role=f"third_{third}"))
    # One recording can legitimately be useful in several review roles.  Do
    # not deduplicate by window id, as that would hide measured role coverage.
    unique = {(item.window_id, item.role): item for item in choices}
    return sorted(unique.values(), key=lambda item: (item.start_sample, item.role, item.window_id))


def _loudness_measurement(ffmpeg: str, path: Path) -> dict:
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-i", str(path), "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', result.stderr, flags=re.S)
    if result.returncode != 0 or not matches:
        raise RuntimeError(f"loudness measurement failed: {result.stderr[-1200:]}")
    return json.loads(matches[-1])


def _read_window(audio: sf.SoundFile, start: int, count: int) -> np.ndarray:
    audio.seek(start)
    values = audio.read(count, dtype="float32", always_2d=False)
    if len(values) != count:
        raise RuntimeError("diagnostic window was truncated")
    return values


def _mid_window_report(values: np.ndarray, sample_rate: int) -> dict:
    integrity = legacy_diagnostics.integrity(values)
    level, frame_db, _ = legacy_diagnostics.level_and_floor(values, sample_rate)
    frequencies, noise_spectrum, speech_spectrum = legacy_diagnostics.spectra(
        values, sample_rate, frame_db
    )
    return {
        "integrity": integrity,
        "level": level,
        "tonal": legacy_diagnostics.tonal_peaks(values, sample_rate, frame_db),
        "reverb": legacy_diagnostics.blind_rt60(values, sample_rate),
        "bandwidth": legacy_diagnostics.bandwidth(frequencies, speech_spectrum),
        "snr_by_band": legacy_diagnostics.band_margins(
            frequencies, noise_spectrum, speech_spectrum
        ),
    }


def _feature_from_report(window_id: str, start: int, total_samples: int, measured: dict) -> WindowFeature:
    floor_db = float(measured["level"]["floor_db"])
    active_db = float(measured["level"]["speech_db"])
    margin = active_db - floor_db
    confidence = float(np.clip((margin - 8.0) / 20.0, 0.0, 1.0))
    hint = "guarded_pause" if floor_db <= -72.0 and active_db <= -62.0 else "uncertain"
    return WindowFeature(
        window_id=window_id,
        start_sample=start,
        label_hint=hint,
        floor_db=floor_db,
        active_db=active_db,
        speech_confidence=confidence,
        timeline_third=min(2, int(3 * start / max(total_samples, 1))),
    )


def _timeline_proposal(values: np.ndarray, start: int, end: int) -> FrameProposal:
    """Return a deliberately narrow classification for one bounded-memory frame."""
    level, _, _ = legacy_diagnostics.level_and_floor(values, SAMPLE_RATE)
    floor = float(level["floor_db"])
    active = float(level["speech_db"])
    margin = active - floor
    speech_confidence = float(np.clip((margin - 8.0) / 20.0, 0.0, 1.0))

    # Energy-only analysis cannot distinguish speech from music, chanting,
    # crowd noise, or overlap.  It therefore never calls active material
    # main_speech; only an exceptionally quiet frame gets a pause proposal.
    if floor <= -72.0 and active <= -62.0:
        return FrameProposal(start, end, "guarded_pause", 0.95)
    return FrameProposal(start, end, "uncertain", speech_confidence)


def _whole_timeline_proposals(mid_path: Path, total_samples: int) -> list[FrameProposal]:
    proposals: list[FrameProposal] = []
    with sf.SoundFile(mid_path) as mid:
        cursor = 0
        for values in mid.blocks(
            blocksize=TIMELINE_FRAME_SAMPLES, dtype="float32", always_2d=False
        ):
            end = cursor + len(values)
            proposals.append(_timeline_proposal(values, cursor, end))
            cursor = end
    if cursor != total_samples:
        raise RuntimeError("timeline scan changed decoded sample coordinates")
    return proposals


def _evidence_recommendations(reports: list[dict], stereo_report: dict) -> list[str]:
    """State measured evidence without selecting or enabling any treatment."""
    result = [
        "Evidence only: diagnostic measurements do not enable any processing stage.",
        f"Evidence: decoded peak {stereo_report['decoded_peak_dbfs']:.2f} dBFS; "
        f"flat-top runs {stereo_report['flat_top_runs']}; "
        f"longest zero run {stereo_report['longest_zero_run_samples']} samples.",
    ]
    for item in reports:
        level = item["level"]
        result.append(
            f"Evidence {item['window_id']}: floor {level['floor_db']:.1f} dBFS, "
            f"speech {level['speech_db']:.1f} dBFS, drift {level['floor_drift_db']:.1f} dB."
        )
    return result


def _noise_spectrum_evidence(reports: list[dict]) -> dict:
    """Return window-linked noise bands and their unweighted global mean."""
    per_window = []
    grouped: dict[tuple[int, int], list[float]] = {}
    for item in reports:
        bands = []
        for band in item["snr_by_band"]:
            lo, hi = int(band["lo"]), int(band["hi"])
            noise_db = float(band["noise_db"])
            bands.append({"lo": lo, "hi": hi, "noise_db": noise_db})
            grouped.setdefault((lo, hi), []).append(noise_db)
        per_window.append({
            "window_id": item["window_id"],
            "start_sample": item["start_sample"],
            "bands": bands,
        })
    return {
        "method": "quiet-frame spectra in nine 60-second windows",
        "per_window": per_window,
        "aggregate": {
            "method": "unweighted arithmetic mean of per-window band noise dB values",
            "bands": [
                {"lo": lo, "hi": hi, "mean_noise_db": float(np.mean(values))}
                for (lo, hi), values in sorted(grouped.items())
            ],
        },
    }


def run_diagnostics(
    stereo_path: Path,
    mid_path: Path,
    ffmpeg: str,
    output_path: Path,
) -> dict:
    """Create diagnostics plus complete, unreviewed conservative proposals."""
    with sf.SoundFile(stereo_path) as stereo:
        if stereo.samplerate != SAMPLE_RATE or stereo.channels != 2:
            raise ValueError("diagnostic source must be 48 kHz stereo")
        stereo_report = scan_stereo_blocks(
            stereo.blocks(blocksize=262144, dtype="float32", always_2d=True), SAMPLE_RATE
        )
        total_samples = stereo.frames
    if total_samples <= 0:
        raise ValueError("diagnostic source must contain samples")
    window_samples = min(WINDOW_SAMPLES, total_samples)
    starts = np.linspace(0, max(total_samples - window_samples, 0), 9, dtype=np.int64)
    reports: list[dict] = []
    features: list[WindowFeature] = []
    with sf.SoundFile(mid_path) as mid:
        if mid.samplerate != SAMPLE_RATE or mid.channels != 1 or mid.frames != total_samples:
            raise ValueError("mid diagnostic file does not match stereo decode")
        for index, start in enumerate(starts):
            measured = {
                **_mid_window_report(_read_window(mid, int(start), window_samples), SAMPLE_RATE),
                "window_id": f"w{index:02d}",
                "start_sample": int(start),
            }
            reports.append(measured)
            features.append(_feature_from_report(f"w{index:02d}", int(start), total_samples, measured))
    proposals = _whole_timeline_proposals(mid_path, total_samples)
    segments = propose_segments(proposals, total_samples)
    loudness = _loudness_measurement(ffmpeg, stereo_path)
    true_peak = float(loudness["input_tp"])
    stereo_report["true_peak_dbfs"] = true_peak
    stereo_report["true_peak_method"] = "ffmpeg loudnorm input_tp"
    floors = [float(item["level"]["floor_db"]) for item in reports]
    report = {
        "schema_version": 1,
        "integrity": {**stereo_report, "sampled_mid_windows": [item["integrity"] for item in reports]},
        "level": {"loudnorm": loudness, "sampled_windows": [item["level"] for item in reports]},
        "noise_floor": {"floor_db_by_window": floors, "drift_db": max(floors) - min(floors)},
        "noise_spectrum": _noise_spectrum_evidence(reports),
        "tonal": [item["tonal"] for item in reports],
        "reverb": [item["reverb"] for item in reports],
        "bandwidth": [item["bandwidth"] for item in reports],
        "snr_by_band": [item["snr_by_band"] for item in reports],
        "stereo": {
            "left_right_correlation": stereo_report["left_right_correlation"],
            "side_to_mid_db": stereo_report["side_to_mid_db"],
        },
        "window_features": [asdict(item) for item in features],
        "representative_windows": [asdict(item) for item in select_representative_windows(features)],
        "recommendations": _evidence_recommendations(reports, stereo_report),
    }
    write_json_atomic(output_path, report)
    write_json_atomic(output_path.parent / "segments-proposed.json", segments_to_json(segments))
    write_json_atomic(
        output_path.parent / "transitions.json",
        transition_windows(segments, total_samples, radius_samples=6 * SAMPLE_RATE),
    )
    return report


def propose_segments(proposals: list[FrameProposal], total_samples: int) -> list[Segment]:
    """Fill every uncovered coordinate with ``uncertain`` and validate coverage."""
    if total_samples <= 0:
        raise ValueError("total_samples must be positive")
    ordered = sorted(proposals, key=lambda item: (item.start_sample, item.end_sample))
    output: list[Segment] = []
    cursor = 0

    def append(start: int, end: int, label: SegmentLabel, notes: str) -> None:
        if end <= start:
            return
        if output and output[-1].end_sample == start and output[-1].label is label:
            previous = output.pop()
            output.append(Segment(previous.start_sample, end, label, False, previous.notes))
        else:
            output.append(Segment(start, end, label, False, notes))

    for proposal in ordered:
        start = max(cursor, min(total_samples, proposal.start_sample))
        end = max(start, min(total_samples, proposal.end_sample))
        if start > cursor:
            append(cursor, start, SegmentLabel.UNCERTAIN, "no confident proposal")
        try:
            label = SegmentLabel(proposal.label_hint)
        except ValueError:
            label = SegmentLabel.UNCERTAIN
        try:
            confidence = float(proposal.confidence)
        except (TypeError, ValueError):
            confidence = float("nan")
        if not np.isfinite(confidence) or confidence < CONFIDENT_PROPOSAL or label not in {
            SegmentLabel.MAIN_SPEECH,
            SegmentLabel.GUARDED_PAUSE,
        }:
            label = SegmentLabel.UNCERTAIN
        append(start, end, label, f"proposal confidence {confidence:.3f}")
        cursor = end
    if cursor < total_samples:
        append(cursor, total_samples, SegmentLabel.UNCERTAIN, "no confident proposal")
    validate_segment_map(output, total_samples, require_reviewed=False)
    return output


def transition_windows(
    segments: list[Segment], total_samples: int, radius_samples: int
) -> list[dict]:
    if radius_samples < 0:
        raise ValueError("radius_samples must be non-negative")
    return [
        {
            "boundary_sample": current.end_sample,
            "start_sample": max(0, current.end_sample - radius_samples),
            "end_sample": min(total_samples, current.end_sample + radius_samples),
            "from": current.label.value,
            "to": following.label.value,
        }
        for current, following in zip(segments, segments[1:])
    ]


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return name or "item"


def _write_or_verify_wav(path: Path, values: np.ndarray, sample_rate: int) -> None:
    if path.exists():
        try:
            existing, existing_rate = sf.read(path, dtype="float32", always_2d=True)
        except RuntimeError as error:
            raise FileExistsError(f"refusing to overwrite mismatched review artifact: {path}") from error
        if existing_rate != sample_rate or existing.shape != values.shape or not np.array_equal(existing, values):
            raise FileExistsError(f"refusing to overwrite mismatched review artifact: {path}")
        return
    sf.write(path, values, sample_rate, subtype="FLOAT")


def _write_or_verify_text(path: Path, value: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise FileExistsError(f"refusing to overwrite mismatched review artifact: {path}")
        return
    path.write_text(value, encoding="utf-8")


def write_original_review_material(
    stereo_path: Path,
    representative_windows: list[WindowFeature],
    transitions: list[dict],
    output_dir: Path,
    window_samples: int = 12 * SAMPLE_RATE,
) -> dict:
    """Write original-only stereo auditions and a safely escaped HTML index.

    Existing artifacts are reused only when their decoded samples (or index
    contents) exactly match the requested stable coordinates; otherwise this
    function refuses to overwrite them.
    """
    if window_samples <= 0:
        raise ValueError("window_samples must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with sf.SoundFile(stereo_path) as source:
        if source.samplerate != SAMPLE_RATE or source.channels != 2:
            raise ValueError("review source must be 48 kHz stereo")
        total_samples = source.frames
        requests = [
            (f"representative-{_safe_name(item.window_id)}", item.start_sample,
             min(total_samples, item.start_sample + window_samples), item.role or "representative")
            for item in representative_windows
        ]
        requests.extend(
            (f"transition-{int(item['boundary_sample'])}", int(item["start_sample"]),
             int(item["end_sample"]), f"transition {item['from']} to {item['to']}")
            for item in transitions
        )
        for identifier, start, end, role in requests:
            start = max(0, min(total_samples, start))
            end = max(start, min(total_samples, end))
            source.seek(start)
            values = source.read(end - start, dtype="float32", always_2d=True)
            filename = f"{identifier}.wav"
            _write_or_verify_wav(output_dir / filename, values, source.samplerate)
            rows.append({
                "file": filename,
                "start_sample": start,
                "end_sample": end,
                "role": role,
            })
    links = "\n".join(
        "<li><a href=\"{}\">{}</a> — {}–{} samples ({})</li>".format(
            html.escape(item["file"], quote=True), html.escape(item["file"]),
            item["start_sample"], item["end_sample"], html.escape(item["role"]),
        )
        for item in rows
    )
    index = "<!doctype html><meta charset=\"utf-8\"><title>Original review</title><ul>\n" + links + "\n</ul>\n"
    _write_or_verify_text(output_dir / "index.html", index)
    return {"directory": str(output_dir), "representatives": rows[:len(representative_windows)], "artifacts": rows}
