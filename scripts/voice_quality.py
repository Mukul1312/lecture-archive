"""
voice_quality.py — the MISSING breathiness / voice-quality features (the intimacy lever the graveness
meter is blind to). See ML-Journey "'Calm' Is Only the Floor — the Target Register Decomposes".

Garellek's two-feature rule: identifying BREATHY phonation needs a spectral-TILT measure AND a
NOISE/periodicity measure together — tilt alone can't tell modal from breathy.
  NOISE / periodicity (Praat, validated):
    - cpps : smoothed cepstral peak prominence (dB). LOWER = breathier / more aperiodic. Pitch-tracking-free.
    - hnr  : harmonics-to-noise ratio (dB), voiced frames. LOWER = breathier (more aspiration noise).
  TILT (FFT):
    - alpha_std : eGeMAPS-style alpha ratio = 10log10( E[50-1000Hz] / E[1-5kHz] ). HIGHER = softer/steeper tilt.
    - hammarberg: max energy 0-2kHz minus max energy 2-5kHz (dB). HIGHER = more low-band dominance = softer.
    - h1h2      : amplitude of 1st harmonic minus 2nd (dB), voiced frames. HIGHER = breathier (open glottis).
                  (UNCORRECTED for formants — a rough source-tilt proxy; treat as advisory.)

Breathy  = HIGH tilt (alpha/hammarberg/h1h2 up) WITH LOW periodicity (cpps/hnr down).
Modal    = HIGH periodicity (cpps/hnr up) regardless of tilt.

Reusable: `from voice_quality import vq_feats`. Run directly for a self-test on a spread of his clips.
Deps: parselmouth (Praat), numpy, soundfile, librosa.
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import parselmouth
from parselmouth.praat import call

ROOT = Path(__file__).resolve().parent.parent


def _load(path, sr_t=16000):
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    if sr != sr_t:
        import librosa
        y = librosa.resample(y, orig_sr=sr, target_sr=sr_t)
        sr = sr_t
    return y, sr


def hnr_mean(snd, f0min=75):
    """Praat harmonicity (cc) -> mean HNR (dB) over voiced frames. Higher = more periodic (modal)."""
    try:
        h = call(snd, "To Harmonicity (cc)", 0.01, f0min, 0.1, 1.0)
        n = int(call(h, "Get number of frames"))
        vals = np.array([call(h, "Get value in frame", i) for i in range(1, n + 1)], dtype=float)
        vals = vals[np.isfinite(vals) & (vals > -100)]   # drop undefined (-200) unvoiced frames
        return float(np.mean(vals)) if len(vals) else float("nan")
    except Exception as e:
        print(f"  [hnr] {e}", file=sys.stderr)
        return float("nan")


def cpps_mean(snd, f0min=60.0, f0max=330.0):
    """Praat PowerCepstrogram -> smoothed CPPS (dB). Lower = breathier / more aperiodic."""
    try:
        pc = call(snd, "To PowerCepstrogram", f0min, 0.002, 5000.0, 50.0)
        return float(call(pc, "Get CPPS", False, 0.02, 0.0005, f0min, f0max,
                          0.05, "Parabolic", 0.001, 0.05, "Straight", "Robust"))
    except Exception as e:
        print(f"  [cpps] {e}", file=sys.stderr)
        return float("nan")


def _tilt_feats(y, sr):
    """FFT tilt measures over voiced-ish frames (frame RMS >= 0.35 * global RMS)."""
    frame, hop = 1024, 256
    win = np.hanning(frame)
    f = np.fft.rfftfreq(frame, 1.0 / sr)
    lo, hi = (f >= 50) & (f < 1000), (f >= 1000) & (f < 5000)
    hlo, hhi = (f >= 0) & (f < 2000), (f >= 2000) & (f < 5000)
    rms = np.sqrt((y ** 2).mean()) + 1e-9
    alphas, hams = [], []
    for i in range(0, len(y) - frame, hop):
        seg = y[i:i + frame]
        if np.sqrt((seg ** 2).mean()) < 0.35 * rms:
            continue
        mag = np.abs(np.fft.rfft(seg * win)) + 1e-9
        e = mag ** 2
        alphas.append(10 * np.log10(e[lo].sum() / e[hi].sum()))          # higher = softer
        hams.append(20 * np.log10(mag[hlo].max() / mag[hhi].max()))       # higher = softer
    return (float(np.mean(alphas)) if alphas else float("nan"),
            float(np.mean(hams)) if hams else float("nan"))


def h1_h2(snd, f0min=75, f0max=300):
    """Uncorrected H1-H2 (dB) over voiced frames. Higher = breathier. Formant-confounded (advisory)."""
    try:
        pitch = snd.to_pitch(time_step=0.01, pitch_floor=f0min, pitch_ceiling=f0max)
        f0arr = pitch.selected_array["frequency"]
        ts = pitch.xs()
        y = snd.values[0]
        sr = snd.sampling_frequency
        frame = int(0.04 * sr)
        win = np.hanning(frame)
        freqs = np.fft.rfftfreq(frame, 1.0 / sr)
        vals = []
        for t, f0 in zip(ts, f0arr):
            if f0 <= 0:
                continue
            c = int(t * sr)
            a, b = c - frame // 2, c - frame // 2 + frame
            if a < 0 or b > len(y):
                continue
            mag = np.abs(np.fft.rfft(y[a:b] * win)) + 1e-9

            def amp_near(fq):
                band = (freqs > fq * 0.85) & (freqs < fq * 1.15)
                return mag[band].max() if band.any() else 1e-9
            vals.append(20 * np.log10(amp_near(f0) / amp_near(2 * f0)))
        return float(np.mean(vals)) if vals else float("nan")
    except Exception as e:
        print(f"  [h1h2] {e}", file=sys.stderr)
        return float("nan")


def vq_feats(path):
    """The voice-quality feature vector for one clip. Reusable across the Stage-0 probe + funnel."""
    snd = parselmouth.Sound(str(path))
    y, sr = _load(path)
    alpha_std, hammarberg = _tilt_feats(y, sr)
    return dict(cpps=cpps_mean(snd), hnr=hnr_mean(snd),
                alpha_std=alpha_std, hammarberg=hammarberg, h1h2=h1_h2(snd))


# ---- self-test: does breathiness VARY meaningfully across his real clips? --------------------------
def _selftest():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_graveness import feats  # HAVE features, for context
    CLIPS = ROOT / "data/out/lecture1/final/clips"
    names = ["ggs_l1_0001", "ggs_l1_0005", "ggs_l1_0032", "ggs_l1_0058", "ggs_l1_0072",
             "ggs_l1_0081", "ggs_l1_0086", "ggs_l1_0094", "ggs_l1_0112", "ggs_l1_0114"]
    print(f"{'clip':13}{'f0':>6}{'loud':>7}{'rate':>6} | {'cpps':>7}{'hnr':>7}{'alpha':>7}{'hamm':>7}{'h1h2':>7}")
    print("-" * 76)
    rows = []
    for n in names:
        p = CLIPS / f"{n}.wav"
        if not p.exists():
            continue
        g = feats(p)
        vq = vq_feats(p)
        rows.append((n, g, vq))
        print(f"{n:13}{g['f0']:6.0f}{g['loud']:7.1f}{g['rate']:6.1f} | "
              f"{vq['cpps']:7.2f}{vq['hnr']:7.2f}{vq['alpha_std']:7.2f}{vq['hammarberg']:7.2f}{vq['h1h2']:7.2f}")
    if len(rows) >= 3:
        def spread(k, sel):
            v = np.array([sel(r) for r in rows], dtype=float)
            v = v[np.isfinite(v)]
            return f"{v.min():.2f}..{v.max():.2f}  (range {v.max()-v.min():.2f}, std {v.std():.2f})"
        print("\n=== does the breathiness signal VARY across his lecture clips? (scarcity probe) ===")
        print(f"  cpps  {spread('cpps', lambda r: r[2]['cpps'])}   (lower = breathier)")
        print(f"  hnr   {spread('hnr', lambda r: r[2]['hnr'])}   (lower = breathier)")
        print(f"  alpha {spread('alpha', lambda r: r[2]['alpha_std'])}   (higher = softer)")
        print(f"  h1h2  {spread('h1h2', lambda r: r[2]['h1h2'])}   (higher = breathier)")
        print("  -> narrow ranges here = he is uniformly MODAL/projected in lectures (breathy audio is scarce).")


if __name__ == "__main__":
    _selftest()
