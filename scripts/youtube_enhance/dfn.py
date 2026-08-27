from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import soundfile as sf
from scipy.signal import correlate, correlation_lags

from .manifest import cache_key, write_json_atomic
from .source import sha256_file


class CacheMiss(RuntimeError):
    pass


class DfnAllocationError(RuntimeError):
    pass


class LatencyUnmeasurable(RuntimeError):
    """Raised when envelope correlation cannot establish one latency."""


REQUIRED_RENDER_VERSION_KEYS = frozenset(
    {"deepfilternet", "model", "python", "numpy", "soundfile", "ffmpeg"}
)
"""The complete, stable provenance version keys for a DFN render context."""


@dataclass(frozen=True)
class Processed:
    samples: np.ndarray
    latency_samples: int
    command: tuple[str, ...] = ()
    stdout: str = ""
    stderr: str = ""
    model_version: str | None = None


def build_dfn_command(
    executable: str,
    source: Path,
    output_directory: Path,
    attenuation_db: int | None,
    model_directory: Path | None = None,
) -> list[str]:
    command = [executable, "-o", str(output_directory), "--no-suffix"]
    if model_directory is not None:
        command.extend(["--model-base-dir", str(model_directory)])
    if attenuation_db is not None:
        command.extend(["--atten-lim", str(attenuation_db)])
    command.append(str(source))
    return command


def estimate_latency(
    reference: np.ndarray,
    processed: np.ndarray,
    max_lag_samples: int,
) -> int:
    if reference.ndim != 1 or processed.ndim != 1:
        raise ValueError("latency inputs must be mono arrays")
    if max_lag_samples < 0:
        raise ValueError("maximum lag must be non-negative")
    count = min(len(reference), len(processed))
    if count == 0:
        raise ValueError("latency inputs must not be empty")
    ref = np.abs(reference[:count]).astype(np.float64)
    out = np.abs(processed[:count]).astype(np.float64)
    ref -= ref.mean()
    out -= out.mean()
    if (
        not np.isfinite(ref).all()
        or not np.isfinite(out).all()
        or np.linalg.norm(ref) <= 1e-12
        or np.linalg.norm(out) <= 1e-12
    ):
        raise LatencyUnmeasurable("latency cannot be measured from silent or constant material")
    scores = correlate(out, ref, mode="full", method="fft")
    lags = correlation_lags(len(out), len(ref), mode="full")
    allowed = np.abs(lags) <= max_lag_samples
    allowed_scores = scores[allowed]
    peak = float(np.max(allowed_scores))
    if not np.isfinite(peak) or peak <= 1e-12:
        raise LatencyUnmeasurable("latency correlation has insufficient signal")
    peak_lags = lags[allowed][np.isclose(allowed_scores, peak, rtol=1e-8, atol=1e-12)]
    if len(peak_lags) != 1:
        raise LatencyUnmeasurable("latency correlation is ambiguous")
    return int(peak_lags[0])


def load_validated_cache(sidecar: Path, artifact: Path, expected_key: str) -> dict:
    if not sidecar.is_file() or not artifact.is_file():
        raise CacheMiss("cache files are absent")
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CacheMiss("cache sidecar is unreadable") from error
    if not isinstance(metadata, dict) or metadata.get("cache_key") != expected_key:
        raise CacheMiss("cache key changed")
    if metadata.get("artifact_sha256") != sha256_file(artifact):
        raise CacheMiss("cached artifact hash changed")
    return metadata


def build_render_context_key(
    source_sha256: str,
    original_mid_pcm_sha256: str,
    attenuation_db: int | None,
    sample_rate: int,
    core_samples: int,
    halo_samples: int,
    blend_samples: int,
    segment_map_sha256: str,
    versions: Mapping[str, str],
) -> str:
    """Fingerprint a render with exactly the required provenance versions.

    ``versions`` must contain only DeepFilterNet, model, Python, NumPy,
    SoundFile, and ffmpeg under the stable lowercase keys in
    ``REQUIRED_RENDER_VERSION_KEYS``.
    """
    version_map = _validated_render_versions(versions)
    return cache_key(
        "dfn-render-context",
        {
            "source_sha256": source_sha256,
            "original_mid_pcm_sha256": original_mid_pcm_sha256,
        },
        {
            "attenuation_db": attenuation_db,
            "sample_rate": sample_rate,
            "core_samples": core_samples,
            "halo_samples": halo_samples,
            "blend_samples": blend_samples,
            "latency_policy": "envelope-xcorr-v1",
            "segment_map_sha256": segment_map_sha256,
        },
        version_map,
    )


def _validated_render_versions(versions: Mapping[str, str]) -> dict[str, str]:
    actual = set(versions)
    missing = sorted(REQUIRED_RENDER_VERSION_KEYS - actual)
    unexpected = sorted(actual - REQUIRED_RENDER_VERSION_KEYS)
    if missing or unexpected:
        pieces = []
        if missing:
            pieces.append(f"missing required versions: {', '.join(missing)}")
        if unexpected:
            pieces.append(f"unexpected version keys: {', '.join(unexpected)}")
        raise ValueError("; ".join(pieces))
    version_map = dict(versions)
    if any(not isinstance(value, str) or not value for value in version_map.values()):
        raise ValueError("render version values must be non-empty strings")
    return version_map


def _bounded_output(value: str, limit: int = 1200) -> str:
    return value[-limit:]


class DfnAdapter:
    def __init__(
        self,
        executable: str,
        model_version: str,
        max_latency_samples: int = 4800,
        model_directory: Path | None = None,
    ):
        if not isinstance(model_version, str) or not model_version:
            raise ValueError("model version must be a non-empty string")
        self.executable = executable
        self.model_version = model_version
        self.max_latency_samples = max_latency_samples
        self.model_directory = Path(model_directory) if model_directory is not None else None

    def enhance(
        self,
        samples: np.ndarray,
        sample_rate: int,
        attenuation_db: int | None,
        work_directory: Path,
    ) -> Processed:
        if samples.ndim != 1:
            raise ValueError("DeepFilterNet input must be mono")
        work_directory.mkdir(parents=True, exist_ok=True)
        attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=work_directory))
        input_directory = attempt / "input"
        output_directory = attempt / "output"
        input_directory.mkdir()
        output_directory.mkdir()
        source = input_directory / "chunk.wav"
        sf.write(source, samples.astype(np.float32), sample_rate, subtype="FLOAT")
        command = build_dfn_command(
            self.executable,
            source,
            output_directory,
            attenuation_db,
            self.model_directory,
        )
        result = subprocess.run(command, capture_output=True, text=True)
        output = output_directory / "chunk.wav"
        stderr = _bounded_output(result.stderr or "")
        stdout = _bounded_output(result.stdout or "")
        if result.returncode != 0 or not output.exists():
            message = (result.stderr or result.stdout or "").lower()
            if "allocate" in message or "out of memory" in message:
                raise DfnAllocationError(message[-1200:])
            raise RuntimeError(f"DeepFilterNet failed: {message[-1200:]}")
        enhanced, rate = sf.read(output, dtype="float32")
        if rate != sample_rate or enhanced.ndim != 1:
            raise RuntimeError("DeepFilterNet changed rate or channel count")
        if len(enhanced) != len(samples):
            raise RuntimeError("DeepFilterNet changed sample count")
        latency = estimate_latency(samples, enhanced, self.max_latency_samples)
        return Processed(enhanced, latency, tuple(command), stdout, stderr, self.model_version)


class CachedDfnAdapter:
    def __init__(self, inner: DfnAdapter, base_params: Mapping[str, Any], versions: Mapping[str, str]):
        self.inner = inner
        self.base_params = dict(base_params)
        self.versions = _validated_render_versions(versions)
        self.inner_model_version = getattr(inner, "model_version", None)
        if self.inner_model_version is not None and self.versions["model"] != self.inner_model_version:
            raise ValueError("model version does not match the DfnAdapter model")
        context_key = self.base_params.pop("render_context_key", None)
        if not isinstance(context_key, str) or not context_key:
            raise ValueError("base_params must include a render_context_key")
        self.render_context_key = context_key

    def enhance(
        self,
        samples: np.ndarray,
        sample_rate: int,
        attenuation_db: int | None,
        work_directory: Path,
    ) -> Processed:
        if samples.ndim != 1:
            raise ValueError("cached DeepFilterNet input must be mono")
        work_directory.mkdir(parents=True, exist_ok=True)
        pcm = np.ascontiguousarray(samples, dtype="<f4")
        pcm_hash = hashlib.sha256(pcm.tobytes()).hexdigest()
        params = {
            **self.base_params,
            "render_context_key": self.render_context_key,
            "sample_rate": sample_rate,
            "attenuation_db": attenuation_db,
            "input_samples": len(pcm),
        }
        expected_key = cache_key(
            "dfn-chunk",
            {"render_context_key": self.render_context_key, "pcm_sha256": pcm_hash},
            params,
            self.versions,
        )
        cache_directory = work_directory / expected_key
        cache_directory.mkdir(parents=True, exist_ok=True)
        artifact = cache_directory / "enhanced.wav"
        sidecar = cache_directory / "enhanced.json"
        try:
            metadata = load_validated_cache(sidecar, artifact, expected_key)
            artifact_info = sf.info(artifact)
            cached, rate = sf.read(artifact, dtype="float32")
            if (
                metadata.get("sample_rate") != sample_rate
                or metadata.get("channels") != 1
                or int(metadata.get("input_samples", -1)) != len(pcm)
                or int(metadata.get("output_samples", -1)) != len(pcm)
                or artifact_info.samplerate != sample_rate
                or artifact_info.channels != 1
                or artifact_info.frames != len(pcm)
                or rate != sample_rate
                or cached.ndim != 1
                or len(cached) != len(pcm)
                or not isinstance(metadata.get("latency_samples"), int)
                or (
                    self.inner_model_version is not None
                    and metadata.get("model_version") != self.inner_model_version
                )
            ):
                raise CacheMiss("cached PCM metadata changed")
            return Processed(cached, metadata["latency_samples"])
        except (CacheMiss, OSError, RuntimeError, ValueError):
            processed = self.inner.enhance(
                pcm, sample_rate, attenuation_db, cache_directory / "attempts"
            )
            if processed.samples.ndim != 1:
                raise RuntimeError("DeepFilterNet returned non-mono cached output")
            if len(processed.samples) != len(pcm):
                raise RuntimeError("DeepFilterNet changed sample count")
            if (
                self.inner_model_version is not None
                and processed.model_version != self.inner_model_version
            ):
                raise RuntimeError("DeepFilterNet returned a mismatched model version")
            sf.write(artifact, processed.samples, sample_rate, subtype="FLOAT")
            artifact_info = sf.info(artifact)
            if (
                artifact_info.samplerate != sample_rate
                or artifact_info.channels != 1
                or artifact_info.frames != len(pcm)
            ):
                raise RuntimeError("cached artifact format changed during write")
            write_json_atomic(
                sidecar,
                {
                    "cache_key": expected_key,
                    "artifact_sha256": sha256_file(artifact),
                    "input_samples": len(pcm),
                    "output_samples": len(processed.samples),
                    "sample_rate": sample_rate,
                    "channels": 1,
                    "latency_samples": processed.latency_samples,
                    "params": params,
                    "versions": self.versions,
                    "command": list(processed.command),
                    "stdout": _bounded_output(processed.stdout),
                    "stderr": _bounded_output(processed.stderr),
                    "model_version": processed.model_version,
                },
            )
            return processed
