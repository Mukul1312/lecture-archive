from __future__ import annotations

from collections.abc import Sequence
from numbers import Integral
from pathlib import Path

import numpy as np

from .models import Segment, SegmentLabel


def _require_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _require_nonnegative_integer(value: object, name: str) -> int:
    integer = _require_integer(value, name)
    if integer < 0:
        raise ValueError(f"{name} must be non-negative")
    return integer


def validate_segment_map(
    segments: Sequence[Segment],
    total_samples: int,
    require_reviewed: bool,
) -> None:
    total_samples = _require_integer(total_samples, "total_samples")
    if total_samples <= 0 or not segments:
        raise ValueError("segment map and positive total_samples are required")
    cursor = 0
    for segment in segments:
        start_sample = _require_integer(segment.start_sample, "start_sample")
        end_sample = _require_integer(segment.end_sample, "end_sample")
        if start_sample != cursor:
            raise ValueError(f"segment map gap or overlap at sample {cursor}")
        if end_sample <= start_sample or end_sample > total_samples:
            raise ValueError("segment boundary is empty or out of range")
        if require_reviewed and not segment.reviewed:
            raise ValueError("full rendering requires every segment to be reviewed")
        cursor = end_sample
    if cursor != total_samples:
        raise ValueError("segment map does not cover the complete source")


def _raised_fade(length: int) -> np.ndarray:
    if length <= 0:
        return np.empty(0, dtype=np.float32)
    phase = np.linspace(0.0, np.pi, length, endpoint=False, dtype=np.float64)
    return (0.5 - 0.5 * np.cos(phase)).astype(np.float32)


def build_speech_mask(
    segments: Sequence[Segment],
    total_samples: int,
    fade_samples: int,
) -> np.ndarray:
    fade_samples = _require_nonnegative_integer(fade_samples, "fade_samples")
    validate_segment_map(segments, total_samples, require_reviewed=True)
    mask = np.zeros(total_samples, dtype=np.float32)
    for index, segment in enumerate(segments):
        if segment.label is not SegmentLabel.MAIN_SPEECH:
            continue
        start, end = segment.start_sample, segment.end_sample
        mask[start:end] = 1.0
        fade = min(fade_samples, (end - start) // 2)
        if fade and (index > 0 and segments[index - 1].label is not SegmentLabel.MAIN_SPEECH):
            mask[start : start + fade] = _raised_fade(fade)
        if fade and (
            index + 1 < len(segments)
            and segments[index + 1].label is not SegmentLabel.MAIN_SPEECH
        ):
            mask[end - fade : end] = _raised_fade(fade)[::-1]
    return mask


def build_guarded_pause_mask(
    segments: Sequence[Segment],
    total_samples: int,
    guard_samples: int,
    fade_samples: int,
) -> np.ndarray:
    guard_samples = _require_nonnegative_integer(guard_samples, "guard_samples")
    fade_samples = _require_nonnegative_integer(fade_samples, "fade_samples")
    validate_segment_map(segments, total_samples, require_reviewed=True)
    mask = np.zeros(total_samples, dtype=np.float32)
    for segment in segments:
        if segment.label is not SegmentLabel.GUARDED_PAUSE:
            continue
        start = segment.start_sample + guard_samples
        end = segment.end_sample - guard_samples
        if end <= start:
            continue
        mask[start:end] = 1.0
        fade = min(fade_samples, (end - start) // 2)
        if fade:
            curve = _raised_fade(fade)
            mask[start : start + fade] = curve
            mask[end - fade : end] = curve[::-1]
    return mask


def write_mask_memmap(mask: np.ndarray, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mapped = np.memmap(path, dtype=np.float32, mode="w+", shape=mask.shape)
    for start in range(0, len(mask), 1_048_576):
        end = min(start + 1_048_576, len(mask))
        mapped[start:end] = mask[start:end]
    mapped.flush()
    del mapped
    return path


def segments_from_json(rows: list[dict]) -> list[Segment]:
    return [
        Segment(
            start_sample=int(row["start_sample"]),
            end_sample=int(row["end_sample"]),
            label=SegmentLabel(row["label"]),
            reviewed=_reviewed_from_json(row["reviewed"]),
            notes=str(row.get("notes", "")),
        )
        for row in rows
    ]


def _reviewed_from_json(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("reviewed must be a JSON boolean")
    return value


def segments_to_json(segments: Sequence[Segment]) -> list[dict]:
    return [
        {
            "start_sample": item.start_sample,
            "end_sample": item.end_sample,
            "label": item.label.value,
            "reviewed": item.reviewed,
            "notes": item.notes,
        }
        for item in segments
    ]
