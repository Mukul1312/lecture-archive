from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .dfn import DfnAllocationError
from .models import Core


@dataclass(frozen=True)
class Support:
    start_sample: int
    values: np.ndarray
    weights: np.ndarray


def partition_cores(total_samples: int, target_samples: int) -> list[Core]:
    if total_samples <= 0 or target_samples <= 0:
        raise ValueError("positive sizes are required")
    return [
        Core(start, min(start + target_samples, total_samples))
        for start in range(0, total_samples, target_samples)
    ]


def crop_compensated(
    processed_halo: np.ndarray,
    core_offset: int,
    core_length: int,
    latency_samples: int,
) -> np.ndarray:
    if processed_halo.ndim != 1:
        raise ValueError("processed halo must be a one-dimensional mono array")
    if core_offset < 0 or core_length < 0 or latency_samples < 0:
        raise ValueError("crop coordinates and latency must be non-negative")
    start = core_offset + latency_samples
    end = start + core_length
    if start < 0 or end > len(processed_halo):
        raise ValueError("halo is too short for measured model latency")
    cropped = processed_halo[start:end]
    if len(cropped) != core_length:
        raise ValueError("latency compensation changed the core length")
    return cropped.astype(np.float32, copy=False)


def _taper(length: int, rising: bool) -> np.ndarray:
    phase = np.linspace(0.0, np.pi, length, endpoint=False, dtype=np.float64)
    values = 0.5 - 0.5 * np.cos(phase)
    return (values if rising else values[::-1]).astype(np.float32)


def support_weights(
    total_samples: int,
    core: Core,
    blend_samples: int,
) -> tuple[int, np.ndarray]:
    start = max(0, core.start_sample - blend_samples)
    end = min(total_samples, core.end_sample + blend_samples)
    weights = np.ones(end - start, dtype=np.float32)
    left = core.start_sample - start
    right = end - core.end_sample
    if left:
        weights[:left] = _taper(left, rising=True)
    if right:
        weights[-right:] = _taper(right, rising=False)
    return start, weights


def support_for_core(source: np.ndarray, core: Core, blend_samples: int) -> Support:
    start, weights = support_weights(len(source), core, blend_samples)
    end = start + len(weights)
    values = source[start:end].astype(np.float32, copy=True)
    return Support(start, values, weights)


def compose_supports(
    total_samples: int,
    supports: list[Support],
) -> tuple[np.ndarray, np.ndarray]:
    weighted = np.zeros(total_samples, dtype=np.float64)
    total_weight = np.zeros(total_samples, dtype=np.float64)
    for support in supports:
        end = support.start_sample + len(support.values)
        if (
            support.start_sample < 0
            or end > total_samples
            or support.values.shape != support.weights.shape
        ):
            raise ValueError("invalid support coordinates")
        sl = slice(support.start_sample, end)
        weighted[sl] += support.values * support.weights
        total_weight[sl] += support.weights
    if np.any(total_weight <= 0):
        raise ValueError("render supports do not cover the complete timeline")
    return (weighted / total_weight).astype(np.float32), total_weight.astype(np.float32)


def bisect_core(core: Core, source: np.ndarray, search_samples: int) -> tuple[Core, Core]:
    if source.ndim != 1:
        raise ValueError("bisection source must be mono")
    if core.start_sample < 0 or core.end_sample > len(source):
        raise ValueError("core must lie within the supplied source")
    if search_samples < 0:
        raise ValueError("search distance must be non-negative")
    midpoint = (core.start_sample + core.end_sample) // 2
    lo = max(core.start_sample + 1, midpoint - search_samples)
    hi = min(core.end_sample - 1, midpoint + search_samples)
    if hi <= lo:
        raise ValueError("core is too short to bisect")
    split = lo + int(np.argmin(np.abs(source[lo:hi])))
    return Core(core.start_sample, split), Core(split, core.end_sample)


def _reflect_context(values: np.ndarray, left_pad: int, right_pad: int) -> np.ndarray:
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("render source must be a non-empty mono array")
    mode = "reflect" if len(values) > 1 else "edge"
    return np.pad(values, (left_pad, right_pad), mode=mode)


def render_array(
    source: np.ndarray,
    enhancer,
    sample_rate: int,
    attenuation_db: int | None,
    core_samples: int,
    halo_samples: int,
    blend_samples: int,
    work_root: Path | None = None,
) -> np.ndarray:
    if source.ndim != 1:
        raise ValueError("render source must be mono")
    work_root = Path("work") if work_root is None else Path(work_root)
    supports: list[Support] = []

    def render_one(core: Core) -> None:
        support_start = max(0, core.start_sample - blend_samples)
        support_end = min(len(source), core.end_sample + blend_samples)
        read_start = max(0, support_start - halo_samples)
        read_end = min(len(source), support_end + halo_samples)
        left_pad = halo_samples - (support_start - read_start)
        right_pad = halo_samples - (read_end - support_end)
        contextual = _reflect_context(source[read_start:read_end], left_pad, right_pad)
        support_offset = left_pad + support_start - read_start
        try:
            processed = enhancer.enhance(
                contextual,
                sample_rate,
                attenuation_db,
                work_root / f"{core.start_sample}-{core.end_sample}",
            )
        except DfnAllocationError:
            left, right = bisect_core(core, source, search_samples=20 * sample_rate)
            render_one(left)
            render_one(right)
            return
        values = crop_compensated(
            processed.samples,
            support_offset,
            support_end - support_start,
            processed.latency_samples,
        )
        template = support_for_core(source, core, blend_samples)
        supports.append(Support(support_start, values, template.weights))

    for item in partition_cores(len(source), core_samples):
        render_one(item)
    output, _ = compose_supports(len(source), supports)
    return output


def render_file(
    source_path: Path,
    output_path: Path,
    enhancer,
    sample_rate: int,
    attenuation_db: int | None,
    core_samples: int,
    halo_samples: int,
    blend_samples: int,
    work_root: Path,
) -> dict:
    info = sf.info(source_path)
    if sample_rate != 48_000 or info.samplerate != 48_000 or info.channels != 1:
        raise ValueError("render source must be mono at 48 kHz")
    total_samples = info.frames
    if total_samples <= 0:
        raise ValueError("render source must not be empty")
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    weighted_path = work_root / "weighted.f64"
    weights_path = work_root / "weights.f64"
    weighted = np.memmap(weighted_path, dtype=np.float64, mode="w+", shape=(total_samples,))
    weights = np.memmap(weights_path, dtype=np.float64, mode="w+", shape=(total_samples,))
    weighted[:] = 0
    weights[:] = 0
    rendered_cores: list[Core] = []

    with sf.SoundFile(source_path) as source_file:
        def read_samples(start: int, end: int) -> np.ndarray:
            source_file.seek(start)
            values = source_file.read(end - start, dtype="float32", always_2d=False)
            if values.ndim != 1 or len(values) != end - start:
                raise RuntimeError("context read was truncated")
            return values

        def render_one(core: Core) -> None:
            support_start = max(0, core.start_sample - blend_samples)
            support_end = min(total_samples, core.end_sample + blend_samples)
            read_start = max(0, support_start - halo_samples)
            read_end = min(total_samples, support_end + halo_samples)
            left_pad = halo_samples - (support_start - read_start)
            right_pad = halo_samples - (read_end - support_end)
            contextual = _reflect_context(
                read_samples(read_start, read_end), left_pad, right_pad
            )
            support_offset = left_pad + support_start - read_start
            try:
                processed = enhancer.enhance(
                    contextual,
                    sample_rate,
                    attenuation_db,
                    work_root / "chunks" / f"{core.start_sample}-{core.end_sample}",
                )
            except DfnAllocationError:
                parent = read_samples(core.start_sample, core.end_sample)
                local_left, _ = bisect_core(
                    Core(0, len(parent)),
                    parent,
                    min(20 * sample_rate, max(1, len(parent) // 3)),
                )
                split = core.start_sample + local_left.end_sample
                render_one(Core(core.start_sample, split))
                render_one(Core(split, core.end_sample))
                return
            values = crop_compensated(
                processed.samples,
                support_offset,
                support_end - support_start,
                processed.latency_samples,
            )
            weight_start, support_weight = support_weights(total_samples, core, blend_samples)
            if weight_start != support_start or len(support_weight) != len(values):
                raise RuntimeError("support coordinates changed during rendering")
            sl = slice(support_start, support_end)
            weighted[sl] += values * support_weight
            weights[sl] += support_weight
            rendered_cores.append(core)

        for core in partition_cores(total_samples, core_samples):
            render_one(core)

    for start in range(0, total_samples, 1_048_576):
        if np.any(weights[start:start + 1_048_576] <= 0):
            raise RuntimeError("chunk supports left uncovered samples")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(output_path, "w", samplerate=sample_rate, channels=1, subtype="FLOAT") as output:
        for start in range(0, total_samples, 1_048_576):
            end = min(start + 1_048_576, total_samples)
            output.write((weighted[start:end] / weights[start:end]).astype(np.float32))
    weighted.flush()
    weights.flush()
    del weighted, weights
    output_info = sf.info(output_path)
    if (
        output_info.frames != total_samples
        or output_info.samplerate != 48_000
        or output_info.channels != 1
        or output_info.subtype != "FLOAT"
    ):
        raise RuntimeError("disk-backed compositor changed output format")
    boundaries = sorted({core.end_sample for core in rendered_cores if core.end_sample < total_samples})
    return {"samples": total_samples, "sample_rate": sample_rate, "boundaries": boundaries}
