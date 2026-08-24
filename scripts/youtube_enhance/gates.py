from __future__ import annotations

import tempfile
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from resemblyzer import VoiceEncoder, preprocess_wav

from scripts.voice_quality import vq_feats


class CandidateRejected(RuntimeError):
    pass


_CANDIDATE_IDS = ("original", "adaptive-22", "adaptive-24")


def identity_verdict(natural_anchor_mean: float, candidate_mean: float) -> bool:
    return candidate_mean >= natural_anchor_mean - 0.03


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0:
        raise ValueError("cannot compare an empty speaker embedding")
    return float(np.dot(left, right) / denominator)


def embed_chunks(encoder, chunks: list[np.ndarray], sample_rate: int) -> np.ndarray:
    return np.stack([
        encoder.embed_utterance(preprocess_wav(chunk, source_sr=sample_rate))
        for chunk in chunks
    ])


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    changes = np.flatnonzero(np.diff(np.pad(mask.astype(np.int8), (1, 1))))
    return [(int(a), int(b)) for a, b in changes.reshape(-1, 2)]


def longest_new_zero_run(original: np.ndarray, candidate: np.ndarray) -> int:
    if original.shape != candidate.shape:
        raise ValueError("zero-run comparison requires aligned arrays")
    candidate_zero = candidate == 0.0
    return max(
        (end - start for start, end in _runs(candidate_zero) if not np.all(original[start:end] == 0.0)),
        default=0,
    )


def canonical_evidence_hash(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def gate_report(
    blind_map: dict[str, str],
    metrics_by_candidate: dict[str, dict],
    sample_rate: int,
    *,
    processing_fingerprint: str,
    evidence_ids: list[str] | None = None,
) -> dict:
    """Apply objective vetoes only; the resulting shortlist is not a ranking."""
    if sample_rate <= 0 or not processing_fingerprint:
        raise ValueError("a positive sample rate and processing fingerprint are required")
    evidence_ids = list(evidence_ids or [])
    if len(evidence_ids) != len(set(evidence_ids)) or any(
        not isinstance(item, str) or not item for item in evidence_ids
    ):
        raise ValueError("candidate evidence IDs must be unique non-empty strings")
    if set(blind_map) != {"A", "B", "C"} or set(blind_map.values()) != set(_CANDIDATE_IDS):
        raise ValueError("blind map must contain exactly the independent three candidates")
    shortlist = []
    decisions = {}
    for code, candidate_id in blind_map.items():
        if candidate_id not in metrics_by_candidate:
            raise ValueError(f"missing metrics for {candidate_id}")
        metrics = metrics_by_candidate[candidate_id]
        required = {
            "natural_anchor_mean", "identity_mean", "longest_new_zero_run_samples",
            "sample_count_equal", "non_finite_samples", "peak",
        }
        missing = required - set(metrics)
        if missing:
            raise ValueError(f"missing veto metrics for {candidate_id}: {sorted(missing)}")
        reasons = []
        if candidate_id != "original" and (
            metrics["identity_mean"] is None or not identity_verdict(
                metrics["natural_anchor_mean"], metrics["identity_mean"]
            )
        ):
            reasons.append("identity")
        if metrics["longest_new_zero_run_samples"] > round(0.050 * sample_rate):
            reasons.append("new-zero-run")
        if not metrics["sample_count_equal"]:
            reasons.append("sample-count")
        if metrics["non_finite_samples"] != 0:
            reasons.append("non-finite")
        if metrics["peak"] > 1.0:
            reasons.append("clipping")
        decisions[code] = {"pass": not reasons, "reasons": reasons}
        if not reasons:
            shortlist.append(code)
    report = {
        "schema_version": 1,
        "blind_map": dict(blind_map),
        "metrics": {code: metrics_by_candidate[candidate_id] for code, candidate_id in blind_map.items()},
        "decisions": decisions,
        "shortlist": shortlist,
        "processing_fingerprint": processing_fingerprint,
        "evidence_ids": evidence_ids,
        "strong_pause_evidence": None,
        "blind_map_sha256": canonical_evidence_hash(dict(blind_map)),
    }
    report["report_sha256"] = _report_evidence_hash(report)
    return report


def approve_candidate(
    report: dict,
    blind_code: str,
    pause_treatment: str,
    reviewer: str,
    fingerprint: str,
    *,
    private_blind_map: dict[str, str] | None = None,
    candidate_context_fingerprint: str | None = None,
) -> dict:
    """Record a current human decision; this function never initiates a render."""
    evidence_context = (
        fingerprint
        if candidate_context_fingerprint is None
        else candidate_context_fingerprint
    )
    if evidence_context != report.get("processing_fingerprint"):
        raise CandidateRejected("approval fingerprint does not match current gate evidence")
    if not report.get("report_sha256") or report["report_sha256"] != _report_evidence_hash(report):
        raise CandidateRejected("candidate gate evidence hash is missing or stale")
    if private_blind_map is None or canonical_evidence_hash(private_blind_map) != report.get("blind_map_sha256"):
        raise CandidateRejected("private blind map does not match committed gate evidence")
    if report.get("blind_map") != private_blind_map:
        raise CandidateRejected("mutable report map does not match committed private map")
    if blind_code not in report.get("shortlist", []):
        raise CandidateRejected(f"{blind_code} did not pass objective vetoes")
    if blind_code not in report.get("blind_map", {}):
        raise CandidateRejected(f"{blind_code} has no private candidate mapping")
    if pause_treatment not in {"original", "approved-strong"}:
        raise ValueError("unknown pause treatment")
    if not reviewer.strip() or not fingerprint:
        raise ValueError("reviewer and current fingerprint are required")
    if pause_treatment == "approved-strong":
        evidence = report.get("strong_pause_evidence")
        if not isinstance(evidence, dict):
            raise CandidateRejected("approved strong pause requires separate blind evidence")
        supplied_hash = evidence.get("evidence_sha256")
        expected_hash = canonical_evidence_hash({
            key: value for key, value in evidence.items() if key != "evidence_sha256"
        })
        if (
            supplied_hash != expected_hash
            or evidence.get("blind_code") != blind_code
            or evidence.get("passed") is not True
            or evidence.get("processing_fingerprint") != evidence_context
            or evidence.get("report_sha256") != report["report_sha256"]
        ):
            raise CandidateRejected("strong-pause evidence does not bind this blind candidate and report")
    return {
        "blind_code": blind_code,
        "candidate_id": private_blind_map[blind_code],
        "pause_treatment": pause_treatment,
        "reviewer": reviewer,
        "approved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fingerprint": fingerprint,
        "evidence_sha256": report["report_sha256"],
    }


def _report_evidence_hash(report: dict) -> str:
    return canonical_evidence_hash({
        key: report[key]
        for key in (
            "schema_version", "processing_fingerprint", "blind_map_sha256", "metrics",
            "decisions", "shortlist", "evidence_ids",
        )
    })


def gate_evidence_hash(report: dict) -> str:
    return _report_evidence_hash(report)


def _mono16(stereo: np.ndarray, sample_rate: int) -> np.ndarray:
    _require_stereo(stereo)
    mono = stereo.mean(axis=1).astype(np.float32)
    return (
        librosa.resample(mono, orig_sr=sample_rate, target_sr=16000)
        if sample_rate != 16000
        else mono
    )


def _chunks15(values: np.ndarray) -> list[np.ndarray]:
    size = 15 * 16000
    return [values[start:start + size] for start in range(0, len(values) - size + 1, size)]


def _floor_db(stereo: np.ndarray) -> float:
    _require_stereo(stereo)
    mono = stereo.mean(axis=1)
    usable = len(mono) // 2048 * 2048
    if usable == 0:
        raise ValueError("noise floor requires at least one 2048-sample frame")
    frames = mono[:usable].reshape(-1, 2048)
    rms = np.sqrt(np.mean(np.square(frames), axis=1) + 1e-20)
    return float(np.percentile(20 * np.log10(rms), 5))


def _mfcc_distance(reference: np.ndarray, candidate: np.ndarray) -> float:
    first = librosa.feature.mfcc(y=reference, sr=16000, n_mfcc=25)[1:]
    second = librosa.feature.mfcc(y=candidate, sr=16000, n_mfcc=25)[1:]
    frames = min(first.shape[1], second.shape[1])
    if frames == 0:
        raise ValueError("parallel MFCC requires at least one frame")
    delta = first[:, :frames] - second[:, :frames]
    return float(np.mean(np.sqrt(np.sum(np.square(delta), axis=0))))


def _pumping_index(stereo: np.ndarray) -> float:
    _require_stereo(stereo)
    mono = stereo.mean(axis=1)
    usable = len(mono) // 960 * 960
    if usable < 1920:
        raise ValueError("pumping index requires at least two 960-sample frames")
    frames = mono[:usable].reshape(-1, 960)
    envelope = 20 * np.log10(np.sqrt(np.mean(np.square(frames), axis=1) + 1e-20))
    return float(np.std(np.diff(envelope)))


def _derivative_p999(stereo: np.ndarray) -> float:
    _require_stereo(stereo)
    if len(stereo) < 2:
        raise ValueError("transition derivative requires at least two samples")
    return float(np.percentile(np.abs(np.diff(stereo, axis=0)), 99.9))


def _voice_quality(stereo: np.ndarray, sample_rate: int, directory: Path, name: str) -> dict:
    path = directory / f"{name}.wav"
    sf.write(path, stereo[:30 * sample_rate].mean(axis=1), sample_rate)
    return {key: float(value) for key, value in vq_feats(path).items()}


def score_candidate_windows(
    raw_by_window: dict[str, dict[str, np.ndarray]],
    speech_window_ids: list[str],
    sample_rate: int,
    *,
    speech_intervals: dict[str, tuple[int, int]] | None = None,
    transition_windows: dict[str, tuple[int, ...]] | None = None,
    scoring_seams: dict[str, object] | None = None,
) -> dict[str, dict]:
    """Score raw evidence only after structural/audio validation has passed.

    The optional seams exist solely for hermetic tests; production defaults retain
    the real scoring libraries after the fail-closed preflight.
    """
    _validate_anchor_provenance(raw_by_window, speech_window_ids, speech_intervals)
    invalid = _preflight_raw_windows(raw_by_window, sample_rate)
    active_ids = tuple(candidate_id for candidate_id in _CANDIDATE_IDS if candidate_id not in invalid)
    seams = scoring_seams or {}
    speech16 = {
        candidate_id: [
            chunk for window_id in speech_window_ids
            for chunk in _chunks15(_mono16(raw_by_window[window_id][candidate_id], sample_rate))
        ]
        for candidate_id in active_ids
    }
    if len(speech16["original"]) < 2:
        if invalid:
            return _invalid_preflight_metrics(raw_by_window, invalid)
        raise ValueError("identity anchor requires at least two 15-second speech chunks")
    encoder_factory = seams.get("encoder_factory", lambda: VoiceEncoder("cpu"))
    encode = seams.get("embed_chunks", embed_chunks)
    encoder = encoder_factory()
    embeddings = {candidate_id: encode(encoder, chunks, 16000) for candidate_id, chunks in speech16.items()}
    original_embeddings = embeddings["original"]
    natural_anchor_mean = float(np.mean([
        cosine(original_embeddings[i], original_embeddings[j])
        for i in range(len(original_embeddings)) for j in range(i + 1, len(original_embeddings))
    ]))
    joined = {candidate_id: np.concatenate([raw_by_window[window_id][candidate_id] for window_id in speech_window_ids]) for candidate_id in active_ids}
    voice_quality = seams.get("voice_quality", _voice_quality)
    mfcc_distance = seams.get("mfcc_distance", _mfcc_distance)
    pumping_index = seams.get("pumping_index", _pumping_index)
    transition_metrics = _transition_metrics(raw_by_window, transition_windows or {}, active_ids)
    metrics = _invalid_preflight_metrics(raw_by_window, invalid)
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        original_vq = voice_quality(joined["original"], sample_rate, temp, "original")
        reference16 = np.concatenate(speech16["original"])
        for candidate_id in active_ids:
            candidate_vq = voice_quality(joined[candidate_id], sample_rate, temp, candidate_id)
            candidate16 = np.concatenate(speech16[candidate_id])
            transition = transition_metrics[candidate_id]
            metrics[candidate_id] = {
                "natural_anchor_mean": natural_anchor_mean,
                "identity_mean": float(np.mean([cosine(original_embeddings[index], embeddings[candidate_id][index]) for index in range(len(original_embeddings))])),
                "longest_new_zero_run_samples": max(longest_new_zero_run(raw_by_window[window_id]["original"].mean(axis=1), raw_by_window[window_id][candidate_id].mean(axis=1)) for window_id in raw_by_window),
                "sample_count_equal": True,
                "non_finite_samples": 0,
                "peak": _peak(joined[candidate_id]),
                "noise_floor_drop_db": float(np.mean([_floor_db(raw_by_window[window_id]["original"]) - _floor_db(raw_by_window[window_id][candidate_id]) for window_id in speech_window_ids])),
                "parallel_mfcc_distance": mfcc_distance(reference16, candidate16),
                "cpps_delta": candidate_vq["cpps"] - original_vq["cpps"],
                "hnr_delta": candidate_vq["hnr"] - original_vq["hnr"],
                "hammarberg_delta": candidate_vq["hammarberg"] - original_vq["hammarberg"],
                "spectral_tilt_delta": candidate_vq["alpha_std"] - original_vq["alpha_std"],
                "pumping_index_delta": pumping_index(joined[candidate_id]) - pumping_index(joined["original"]),
                "transition_peak_discontinuity": transition["aggregate"],
                "transition_evidence": transition["per_transition"],
                "status": "scored",
            }
    return metrics


def _validate_anchor_provenance(raw_by_window, speech_window_ids, speech_intervals) -> None:
    if not speech_window_ids or len(speech_window_ids) != len(set(speech_window_ids)):
        raise ValueError("unique reviewed speech windows are required")
    if speech_intervals is None or any(window_id not in raw_by_window or window_id not in speech_intervals for window_id in speech_window_ids):
        raise ValueError("speech anchor requires source interval provenance")
    intervals = []
    for window_id in speech_window_ids:
        start, end = speech_intervals[window_id]
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise ValueError("speech interval provenance must use increasing sample coordinates")
        intervals.append((start, end))
    ordered = sorted(intervals)
    for (_, left_end), (right_start, _) in zip(ordered, ordered[1:]):
        if right_start < left_end:
            raise ValueError("speech anchor intervals must not overlap")
    if len(set(intervals)) < 2:
        raise ValueError("identity anchor requires at least two unique source intervals")


def _preflight_raw_windows(raw_by_window, sample_rate: int) -> dict[str, dict]:
    if not raw_by_window:
        raise ValueError("raw candidate windows are required")
    invalid = {candidate_id: {"count": False, "non_finite": 0, "peak": 0.0, "zero_run": 0} for candidate_id in _CANDIDATE_IDS}
    for window in raw_by_window.values():
        if set(window) != set(_CANDIDATE_IDS):
            raise ValueError("every scoring window must contain exactly the internal candidate IDs")
        original = window["original"]
        _require_stereo(original)
        original_non_finite = int(np.size(original) - np.count_nonzero(np.isfinite(original)))
        if original_non_finite or _peak(original) > 1.0:
            raise ValueError("original evidence is invalid")
        for candidate_id in _CANDIDATE_IDS:
            values = window[candidate_id]
            try:
                _require_stereo(values)
                count_mismatch = values.shape != original.shape
            except ValueError:
                count_mismatch = True
            non_finite = int(np.size(values) - np.count_nonzero(np.isfinite(values)))
            peak = _peak(values)
            invalid[candidate_id]["count"] |= count_mismatch
            invalid[candidate_id]["non_finite"] += non_finite
            invalid[candidate_id]["peak"] = max(invalid[candidate_id]["peak"], peak)
            if not count_mismatch and candidate_id != "original":
                invalid[candidate_id]["zero_run"] = max(invalid[candidate_id]["zero_run"], longest_new_zero_run(original.mean(axis=1), values.mean(axis=1)))
    return {candidate_id: value for candidate_id, value in invalid.items() if value["count"] or value["non_finite"] or value["peak"] > 1.0 or value["zero_run"] > round(.050 * sample_rate)}


def _invalid_preflight_metrics(raw_by_window, invalid) -> dict[str, dict]:
    metrics = {}
    for candidate_id, state in invalid.items():
        metrics[candidate_id] = {
            "natural_anchor_mean": None, "identity_mean": None,
            "longest_new_zero_run_samples": state["zero_run"], "sample_count_equal": not state["count"],
            "non_finite_samples": state["non_finite"], "peak": state["peak"],
            "noise_floor_drop_db": None, "parallel_mfcc_distance": None,
            "cpps_delta": None, "hnr_delta": None, "hammarberg_delta": None,
            "spectral_tilt_delta": None, "pumping_index_delta": None,
            "transition_peak_discontinuity": None, "transition_evidence": {}, "status": "invalid-preflight",
        }
    return metrics


def _peak(values: np.ndarray) -> float:
    finite = np.abs(values[np.isfinite(values)])
    return float(np.max(finite)) if finite.size else 0.0


def _transition_metrics(raw_by_window, transition_windows, candidate_ids) -> dict[str, dict]:
    result = {candidate_id: {"aggregate": 0.0, "per_transition": {}} for candidate_id in candidate_ids}
    for window_id, boundaries in transition_windows.items():
        if window_id not in raw_by_window or not boundaries:
            raise ValueError("transition boundaries must reference a known excerpt")
        for boundary in boundaries:
            if not isinstance(boundary, int) or boundary <= 0 or boundary >= len(raw_by_window[window_id]["original"]):
                raise ValueError("transition boundary must lie inside its excerpt")
        for candidate_id in candidate_ids:
            stereo = raw_by_window[window_id][candidate_id]
            values = [float(np.max(np.abs(stereo[boundary] - stereo[boundary - 1]))) for boundary in boundaries]
            peak = max(values)
            result[candidate_id]["per_transition"][window_id] = {"boundaries": list(boundaries), "peak_discontinuity": peak}
            result[candidate_id]["aggregate"] = max(result[candidate_id]["aggregate"], peak)
    return result


def _require_stereo(stereo: np.ndarray) -> None:
    if stereo.ndim != 2 or stereo.shape[1] != 2:
        raise ValueError("metrics require stereo shaped (samples, 2) arrays")
