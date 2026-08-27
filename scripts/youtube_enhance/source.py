from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


SAMPLE_RATE = 48000
PEAK_TARGET = 0.95


def _reject_clobber(source: Path, outputs: tuple[Path, ...]) -> None:
    source_resolved = source.resolve()
    output_resolved = tuple(path.resolve() for path in outputs)
    if source_resolved in output_resolved:
        raise ValueError("source and output paths must not alias")
    if len(set(output_resolved)) != len(output_resolved):
        raise ValueError("output paths must be distinct")
    for path in outputs:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing output: {path}")


def sha256_file(path: Path, block_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_bytes):
            digest.update(block)
    return digest.hexdigest()


def calculate_headroom_gain(peak: float) -> float:
    if peak < 0:
        raise ValueError("peak must be non-negative")
    return 1.0 if peak <= PEAK_TARGET else PEAK_TARGET / peak


def to_mid_side(stereo: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if stereo.ndim != 2 or stereo.shape[1] != 2:
        raise ValueError("expected shape (samples, 2)")
    left = stereo[:, 0]
    right = stereo[:, 1]
    return (left + right) * 0.5, (left - right) * 0.5


def from_mid_side(mid: np.ndarray, side: np.ndarray) -> np.ndarray:
    if mid.shape != side.shape:
        raise ValueError("mid and side must have equal shapes")
    return np.column_stack((mid + side, mid - side)).astype(np.float32)


def scan_peak(path: Path, blocksize: int = 1_048_576) -> tuple[float, int]:
    peak = 0.0
    samples = 0
    with sf.SoundFile(path) as audio:
        if audio.channels != 2 or audio.samplerate != SAMPLE_RATE:
            raise ValueError("working decode must be 48 kHz stereo")
        for block in audio.blocks(blocksize=blocksize, dtype="float32", always_2d=True):
            peak = max(peak, float(np.max(np.abs(block))))
            samples += len(block)
    return peak, samples


def stream_headroom_mid_side(
    source: Path,
    mid_path: Path,
    side_path: Path,
    blocksize: int = 262_144,
) -> dict[str, float | int]:
    _reject_clobber(source, (mid_path, side_path))
    peak, samples = scan_peak(source)
    gain = calculate_headroom_gain(peak)
    mid_path.parent.mkdir(parents=True, exist_ok=True)
    side_path.parent.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(source) as src, sf.SoundFile(
        mid_path, "w", samplerate=SAMPLE_RATE, channels=1, subtype="FLOAT"
    ) as mid_out, sf.SoundFile(
        side_path, "w", samplerate=SAMPLE_RATE, channels=1, subtype="FLOAT"
    ) as side_out:
        for block in src.blocks(blocksize=blocksize, dtype="float32", always_2d=True):
            mid, side = to_mid_side(block * gain)
            mid_out.write(mid)
            side_out.write(side)
    if sf.info(mid_path).frames != samples or sf.info(side_path).frames != samples:
        raise RuntimeError("mid/side split changed the decoded sample count")
    return {"decoded_peak": peak, "headroom_gain": gain, "samples": samples}


def resolve_tool(name: str) -> str:
    if found := shutil.which(name):
        return found
    base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    matches = sorted(base.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe")) if base.exists() else []
    if matches:
        return str(matches[0])
    raise FileNotFoundError(f"Cannot resolve required tool: {name}")


def probe_audio(source: Path, ffprobe: str) -> dict:
    command = [
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_streams", "-show_format", "-of", "json", str(source),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def decode_float_stereo(source: Path, destination: Path, ffmpeg: str) -> None:
    _reject_clobber(source, (destination,))
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-nostdin", "-n", "-v", "error", "-i", str(source),
        "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_f32le", str(destination),
    ]
    subprocess.run(command, check=True)
