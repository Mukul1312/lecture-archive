"""
make_ref_candidates.py — build gentler reference-clean candidates and measure their noise, so the
downstream pod A/B tests the RIGHT set. The v5 noise is ~62% sub-120 Hz rumble; a high-pass filter
removes it with near-zero identity cost (his F0 ~140 Hz, formants above are untouched), unlike the
full Resemble-Enhance denoise (clips_dn) which cost -0.057 clip-level identity.

Candidates written to data/out/lecture1/final/clips_cand/ggs_l1_0001__<tag>.wav:
  hpf90 / hpf120  — Butterworth high-pass (order 4) at 90 / 120 Hz
  hpf120_dn       — hpf120 then a light spectral-gate (very mild), if noisereduce is available (optional)

Run: .venv/Scripts/python.exe scripts/make_ref_candidates.py
Then compare noise with: scripts/spectral_inspect.py "noisy=...clips/ggs_l1_0001.wav" "hpf120=..." ...
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/lecture1/final/clips/ggs_l1_0001.wav"
OUTDIR = ROOT / "data/out/lecture1/final/clips_cand"
OUTDIR.mkdir(parents=True, exist_ok=True)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def hpf(y, sr, fc, order=4):
    sos = butter(order, fc / (sr / 2), btype="highpass", output="sos")
    return sosfiltfilt(sos, y).astype("float32")


def main():
    y, sr = sf.read(str(SRC), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    print(f"source {SRC.name}: {len(y)/sr:.2f}s @ {sr} Hz")

    made = []
    for fc in (90, 120):
        yz = hpf(y, sr, fc)
        p = OUTDIR / f"ggs_l1_0001__hpf{fc}.wav"
        sf.write(str(p), yz, sr)
        made.append(p)
        print(f"  wrote {p.name}  (high-pass {fc} Hz)")

    dn = ROOT / "data/out/lecture1/final/clips_dn/ggs_l1_0001.wav"
    args = [f'"noisy={SRC}"', f'"denoised={dn}"'] + [f'"{p.stem.split("__")[1]}={p}"' for p in made]
    print("\ncompare noise with:")
    print("  .venv/Scripts/python.exe scripts/spectral_inspect.py " + " ".join(args))


if __name__ == "__main__":
    main()
