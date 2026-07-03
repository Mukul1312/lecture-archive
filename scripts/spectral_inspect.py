"""
spectral_inspect.py — make the v5 background noise VISIBLE and MEASURABLE, and localize its SOURCE.

Renders mel-spectrograms stacked for a set of clips and prints a noise-floor table, so we can see the
noise and answer: is it inherited from the calm REFERENCE (room tone transferred by conditioning),
the BASE model (narrator path, no reference), the LoRA+ref path, or a model noise floor common to all?

Method (all loudness-independent where it matters):
  - noise floor  = 10th-percentile frame level (dBFS): the quietest frames = noise-only bed
  - speech level = 90th-percentile frame level; SNR ≈ speech - floor
  - noise SHAPE  = mean magnitude spectrum of the quietest 15% of frames, split into bands
                   (rumble <120 Hz / low / mid / hiss 3-8k / air >8k) — tells hum vs hiss vs broadband

Usage:  .venv/Scripts/python.exe scripts/spectral_inspect.py [label=path ...]
Default set: v5 full, the calm reference, a narrator take (base), a GGS take (LoRA+ref).
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa
import librosa.display
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
SR = 22050
NFFT, HOP = 1024, 256
OUT = ROOT / "voice_lab" / "spectral"
OUT.mkdir(parents=True, exist_ok=True)


def first(glob):
    hits = sorted((ROOT).glob(glob))
    return hits[0] if hits else None


def load(path):
    y, s = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    if s != SR:
        y = librosa.resample(y, orig_sr=s, target_sr=SR)
    return y


def frame_db(y):
    rms = librosa.feature.rms(y=y, frame_length=NFFT, hop_length=HOP)[0]
    return 20 * np.log10(rms + 1e-9)


def analyze(y):
    db = frame_db(y)
    S = np.abs(librosa.stft(y, n_fft=NFFT, hop_length=HOP))
    quiet = S[:, db <= np.percentile(db, 15)]            # noise-only frames
    prof = quiet.mean(1) if quiet.shape[1] else S.mean(1)
    freqs = librosa.fft_frequencies(sr=SR, n_fft=NFFT)
    e = prof ** 2
    bands = {"rumble<120": (0, 120), "low.12-.5k": (120, 500), "mid.5-3k": (500, 3000),
             "hiss3-8k": (3000, 8000), "air>8k": (8000, SR / 2)}
    frac = {k: float(e[(freqs >= lo) & (freqs < hi)].sum() / (e.sum() + 1e-12)) for k, (lo, hi) in bands.items()}
    return dict(floor=float(np.percentile(db, 10)), speech=float(np.percentile(db, 90)),
                snr=float(np.percentile(db, 90) - np.percentile(db, 10)), frac=frac, prof=prof, freqs=freqs)


def main():
    argv = sys.argv[1:]
    if argv:
        clips = []
        for a in argv:
            lab, _, p = a.partition("=")
            clips.append((lab, Path(p)))
    else:
        clips = [(c, p) for c, p in [
            ("v5 full (stitched)", ROOT / "voice_lab/diary_full/full.wav"),
            ("calm REFERENCE 0001", ROOT / "data/out/lecture1/final/clips/ggs_l1_0001.wav"),
            ("narrator take (base, no ref)", first("voice_lab/diary_full/audio/01__s*.wav")),
            ("GGS take (LoRA+ref)", first("voice_lab/diary_full/audio/10__s*.wav")),
        ] if p is not None]

    data = []
    for lab, p in clips:
        if not p or not Path(p).exists():
            print(f"  skip (missing): {lab} {p}")
            continue
        y = load(p)
        data.append((lab, p, y, analyze(y)))

    # ---- table ----
    print(f"\n{'clip':30s} {'floor':>7s} {'speech':>7s} {'SNR':>6s}   noise-shape (fraction of noise energy)")
    print("-" * 96)
    for lab, p, y, a in data:
        fr = a["frac"]
        shape = " ".join(f"{k}={v:.0%}" for k, v in fr.items())
        print(f"{lab:30s} {a['floor']:7.1f} {a['speech']:7.1f} {a['snr']:6.1f}   {shape}")
    print("\n(floor/speech in dBFS; SNR = speech-floor. Higher SNR = cleaner. "
          "Shape: where the noise BED sits — hiss3-8k/air = hiss, rumble/low = hum.)")

    # ---- mel-spectrogram stack ----
    n = len(data)
    fig, axes = plt.subplots(n, 1, figsize=(11, 2.3 * n + 0.6), constrained_layout=True)
    if n == 1:
        axes = [axes]
    im = None
    for ax, (lab, p, y, a) in zip(axes, data):
        M = librosa.power_to_db(librosa.feature.melspectrogram(
            y=y, sr=SR, n_fft=NFFT, hop_length=HOP, n_mels=128, fmax=SR // 2), ref=np.max)
        im = librosa.display.specshow(M, sr=SR, hop_length=HOP, x_axis="time", y_axis="mel",
                                      fmax=SR // 2, ax=ax, vmin=-80, vmax=0, cmap="magma")
        ax.set_title(f"{lab}   ·   floor {a['floor']:.0f} dB · SNR {a['snr']:.0f} dB", fontsize=10, loc="left")
        ax.set_ylabel("")
    fig.colorbar(im, ax=axes, format="%+d dB", location="right", shrink=0.6, label="dB (rel. max)")
    fig.suptitle("Mel-spectrograms — background-noise inspection", fontsize=12, x=0.01, ha="left")
    mel_png = OUT / "mels.png"
    fig.savefig(mel_png, dpi=120)
    plt.close(fig)

    # ---- noise-profile overlay (where each clip's noise bed sits, log-freq) ----
    fig2, ax2 = plt.subplots(figsize=(10, 4.2), constrained_layout=True)
    for lab, p, y, a in data:
        prof_db = 20 * np.log10(a["prof"] / (a["prof"].max() + 1e-12) + 1e-9)
        ax2.semilogx(a["freqs"][1:], prof_db[1:], label=lab, lw=1.6)
    ax2.set_xlim(40, SR // 2); ax2.set_ylim(-80, 2)
    ax2.set_xlabel("frequency (Hz, log)"); ax2.set_ylabel("noise-bed level (dB, norm.)")
    ax2.set_title("Noise-bed spectral shape (quietest 15% of frames) — overlay to compare source")
    ax2.grid(True, which="both", alpha=0.2); ax2.legend(fontsize=9)
    prof_png = OUT / "noise_profile.png"
    fig2.savefig(prof_png, dpi=120)
    plt.close(fig2)

    print(f"\nwrote {mel_png.relative_to(ROOT)}  and  {prof_png.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
