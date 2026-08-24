"""
enhance_make_candidates.py — build the candidate set for the enhancement bake-off.

Two fixes over the first attempt:

 1. HEADROOM ON EXTRACTION. The 64 kbps MP3 decodes to peaks ABOVE full scale (1.22 in this window,
    up to 1.86 elsewhere in the part) — normal decoder overshoot. Our first WAV cut clamped those to
    +/-1.0, destroying real peaks and manufacturing flat tops that we then mistook for source
    clipping. Here we decode to float and scale to 0.95 peak, so nothing is lost.

 2. THE UNTESTED DIAL. Our first two runs differed only in `--pf` — both ran DeepFilterNet at FULL
    attenuation. `--atten-lim` is the actual strength control ("attenuation limit in dB by mixing the
    enhanced signal with the noisy signal"), i.e. DFN's own built-in dry/wet. Sweeping it is the
    honest test of whether the tool can work here before concluding it can't.

Also generates the classical alternative (noisereduce spectral gating), which is the method suited to
STATIONARY noise — which is what enhance_diagnose.py measured this source to be.

RUN: .venv/Scripts/python.exe scripts/enhance_make_candidates.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/enhance/jiva_goswami/part-01.mp3"
OUT = ROOT / "data/enhance/poc/v2"
TMP = OUT / "_tmp"
START_S, DUR_S, SR = 1800, 300, 48000
PEAK_TARGET = 0.95
DFN = str(ROOT / ".venv/Scripts/deepFilter.exe")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def extract_with_headroom(dst):
    """Decode to float32 (no clamping), then scale so the true peak fits — losing nothing."""
    cmd = ["ffmpeg", "-v", "quiet", "-ss", str(START_S), "-t", str(DUR_S), "-i", str(SRC),
           "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    y = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, dtype=np.float32).copy()
    pk = float(np.max(np.abs(y)))
    n_over = int(np.sum(np.abs(y) > 1.0))
    y *= PEAK_TARGET / pk
    sf.write(str(dst), y, SR)
    print(f"  decoded peak {pk:.4f} ({20*np.log10(pk):+.2f} dBFS), {n_over} samples over full scale")
    print(f"  scaled by {PEAK_TARGET/pk:.4f} -> peak {PEAK_TARGET}; nothing clipped")
    return y


def run_dfn(src, dst, atten=None, pf=False):
    if dst.exists():
        print(f"  {dst.name:<22} exists, skip"); return
    d = TMP / dst.stem
    d.mkdir(parents=True, exist_ok=True)
    cmd = [DFN, "-o", str(d), "--no-suffix"]
    if atten is not None:
        cmd += ["--atten-lim", str(atten)]
    if pf:
        cmd += ["--pf"]
    cmd += [str(src)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    hits = list(d.glob("*.wav"))
    if not hits:
        print(f"  {dst.name:<22} FAILED: {r.stderr.strip()[:160]}"); return
    shutil.move(str(hits[0]), str(dst))
    print(f"  {dst.name:<22} ok")


def run_nr(src, dst, prop_decrease, stationary=True):
    if dst.exists():
        print(f"  {dst.name:<22} exists, skip"); return
    import noisereduce as nr
    y, sr = sf.read(str(src), dtype="float32")
    out = nr.reduce_noise(y=y, sr=sr, stationary=stationary, prop_decrease=prop_decrease)
    pk = float(np.max(np.abs(out)))
    if pk > 0.99:
        out = out * (0.99 / pk)
    sf.write(str(dst), out.astype("float32"), sr)
    print(f"  {dst.name:<22} ok (prop_decrease={prop_decrease}, stationary={stationary})")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)

    print("EXTRACT (headroom-preserving)")
    orig = OUT / "00_original.wav"
    extract_with_headroom(orig)

    print("\nDEEPFILTERNET — attenuation-limit sweep (the dial we never turned)")
    for a in (6, 12, 18, 24):
        run_dfn(orig, OUT / f"1{(a//6)-1}_dfn_atten{a:02d}.wav", atten=a)
    print("\nDEEPFILTERNET — full strength (what we ran before, on the fixed extract)")
    run_dfn(orig, OUT / "14_dfn_full.wav")
    run_dfn(orig, OUT / "15_dfn_full_pf.wav", pf=True)

    print("\nNOISEREDUCE — classical spectral gating (suits STATIONARY noise)")
    run_nr(orig, OUT / "20_nr_gentle.wav", 0.50)
    run_nr(orig, OUT / "21_nr_mild.wav", 0.75)

    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\ncandidates in {OUT}:")
    for p in sorted(OUT.glob("*.wav")):
        print(f"  {p.name:<24} {p.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
