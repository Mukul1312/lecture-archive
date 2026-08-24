"""
enhance_voice_impact.py — does the enhancement change HIM? A numeric stand-in for P.835 "SIG".

Our whole problem is voice damage, not leftover noise. DNSMOS/NISQA would measure that, but this repo
already owns better-suited machinery, locally and offline:

  d-vector cosine  (Resemblyzer GE2E)  -> speaker identity shift          [verify_identity.py pattern]
  MCD              (mel-cepstral dist) -> timbre distortion, PARALLEL     [eval_metrics.py]
  voice quality    (Praat via vq_feats)-> phonation + spectral tilt       [voice_quality.py]

The critical borrowing is not a metric, it is the ANCHOR DISCIPLINE from voice_gate.py /
verify_identity.py: a raw cosine means nothing on its own, so we establish the scale first.

  FLOOR (natural variation)  cos between DIFFERENT 15 s chunks of the SAME untouched recording.
                             This is how much "him at 30:15" already differs from "him at 32:45".
  MEASURED (processing)      cos between the SAME chunk before vs after enhancement. Same words,
                             same moment -> any drop is caused purely by the processing.

The read: enhancement is TRANSPARENT only if it moves the voice far LESS than a different moment of
his own speech does. If processing-distance approaches natural-variation distance, the tool has
changed him about as much as changing the sentence would — which is disqualifying.

We also score MANY chunks rather than one number for the whole file, because per-clip quality
prediction is unreliable (DNSMOS SIG clip-level SRCC 0.72) — distributions, not point estimates.

Note: ECAPA is UNAVAILABLE in this venv — the torch 2.0.1 downgrade needed by DeepFilterNet breaks
speechbrain 1.1.0 (`torch.amp.custom_fwd`). Resemblyzer's d-vector is a genuinely independent
encoder lineage (LSTM/GE2E vs ECAPA's TDNN), so it stands alone here, but this is ONE encoder where
the repo convention is two. Treat identity results as strong-but-single-source.

RUN: .venv/Scripts/python.exe scripts/enhance_voice_impact.py
"""
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import soundfile as sf
# resolve librosa's lazy submodules BEFORE torch-based encoders (repo convention, see eval_metrics.py)
import librosa
import librosa.feature  # noqa
_ = librosa.feature.mfcc
from resemblyzer import VoiceEncoder, preprocess_wav

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
POC = ROOT / "data/enhance/poc"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

VERSIONS = {
    "original":   POC / "segment_30min_5min_original.wav",
    "DFN light":  POC / "segment_30min_5min_no_pf.wav",
    "DFN aggr":   POC / "segment_30min_5min_with_pf.wav",
}
SR = 16000          # d-vector and MCD both work at 16 kHz
CHUNK_S = 15.0
VQ_WINDOWS = 8      # Praat features are slow; sample this many 30 s windows


def load16k(path):
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    return y


def chunks(y, n_s=CHUNK_S):
    n = int(n_s * SR)
    return [y[i:i + n] for i in range(0, len(y) - n + 1, n)]


# ------------------------------------------------------------------ identity

def embed_all(enc, chs):
    out = []
    for c in chs:
        out.append(enc.embed_utterance(preprocess_wav(c, source_sr=SR)))
    return np.stack(out)


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ---------------------------------------------------------------------- MCD

def mcd(ref, test, n_mfcc=25):
    """MCD-style spectral distance. Lower = timbre better preserved. RELATIVE USE ONLY.

    Original and enhanced are the SAME recording sample-for-sample, so no DTW alignment is needed —
    this is the clean parallel case MCD was designed for. c0 (overall energy) is excluded so the
    result reflects spectral SHAPE, not loudness.

    SCALE CAVEAT (verified, do not report these as textbook MCD): librosa MFCCs are dB-scaled DCT
    coefficients, not true mel-cepstra, so values land far above the usual 0-15 dB MCD range.
    Sanity-checked: identical signal -> 0.00, gain-changed -> 0.00, vs white noise -> ~434.
    Only comparisons BETWEEN candidates on this same scale are meaningful.

    There is deliberately no "natural variation" anchor for this metric: chunks with different words
    are unaligned frame-to-frame and score ~470, i.e. indistinguishable from the white-noise case.
    An anchor that cannot separate 'different sentence' from 'pure noise' cannot calibrate anything.
    """
    n = min(len(ref), len(test))
    a = librosa.feature.mfcc(y=ref[:n], sr=SR, n_mfcc=n_mfcc)[1:]
    b = librosa.feature.mfcc(y=test[:n], sr=SR, n_mfcc=n_mfcc)[1:]
    m = min(a.shape[1], b.shape[1])
    d = a[:, :m] - b[:, :m]
    return float((10.0 / np.log(10)) * np.sqrt(2.0) * np.mean(np.sqrt(np.sum(d ** 2, axis=0))))


# ------------------------------------------------------------- voice quality

def vq_windows(path, n_win=VQ_WINDOWS, win_s=30.0):
    """Praat CPPS / HNR / tilt over several windows -> mean +/- std per file."""
    from voice_quality import vq_feats
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    n = int(win_s * sr)
    starts = np.linspace(0, max(len(y) - n, 0), n_win).astype(int)
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for k, s in enumerate(starts):
            p = Path(td) / f"w{k}.wav"
            sf.write(str(p), y[s:s + n], sr)
            try:
                rows.append(vq_feats(p))
            except Exception:
                pass
    if not rows:
        return {}
    keys = rows[0].keys()
    return {k: (float(np.mean([r[k] for r in rows])), float(np.std([r[k] for r in rows]))) for k in keys}


def main():
    missing = [k for k, v in VERSIONS.items() if not v.exists()]
    if missing:
        sys.exit(f"missing: {missing}")

    print("Loading + chunking...")
    audio = {k: load16k(v) for k, v in VERSIONS.items()}
    ch = {k: chunks(v) for k, v in audio.items()}
    n = min(len(v) for v in ch.values())
    ch = {k: v[:n] for k, v in ch.items()}
    print(f"  {n} chunks of {CHUNK_S:.0f}s each\n")

    enc = VoiceEncoder("cpu")
    emb = {k: embed_all(enc, v) for k, v in ch.items()}

    # ---- the anchor: how much does he vary against HIMSELF, untouched? ----
    E = emb["original"]
    nat = [cos(E[i], E[j]) for i in range(n) for j in range(i + 1, n)]
    nat_mean, nat_p05 = float(np.mean(nat)), float(np.percentile(nat, 5))

    print("=" * 78)
    print("ANCHOR — natural variation within the UNTOUCHED recording")
    print("=" * 78)
    print(f"  cos between different 15s chunks of the original:")
    print(f"    mean {nat_mean:.4f}   p05 {nat_p05:.4f}   min {min(nat):.4f}   ({len(nat)} pairs)")
    print(f"  -> this is the scale. Two different moments of his own speech sit this far apart.")

    print("\n" + "=" * 78)
    print("IDENTITY SHIFT — same chunk, before vs after processing")
    print("=" * 78)
    print(f"  {'version':<12}{'mean cos':>10}{'min':>9}{'p05':>9}   read")
    ident = {}
    for k in VERSIONS:
        if k == "original":
            continue
        cs = [cos(emb["original"][i], emb[k][i]) for i in range(n)]
        ident[k] = cs
        gap = float(np.mean(cs)) - nat_mean
        read = ("TRANSPARENT (moves him far less than natural variation)" if gap > 0.05
                else "MARGINAL — processing shift approaches natural variation"
                if gap > 0 else "FAILS — processing moved him MORE than a different moment does")
        print(f"  {k:<12}{np.mean(cs):>10.4f}{min(cs):>9.4f}{np.percentile(cs,5):>9.4f}   {read}")

    print("\n" + "=" * 78)
    print("MCD-style spectral distance vs the original (parallel, same words)")
    print("=" * 78)
    print("  Arbitrary scale (see docstring) — compare candidates to EACH OTHER, not to a threshold.\n")
    print(f"  {'version':<12}{'distance':>10}{'std':>8}")
    base = None
    for k in VERSIONS:
        if k == "original":
            continue
        ms = [mcd(ch["original"][i], ch[k][i]) for i in range(n)]
        rel = "" if base is None else f"   {100*(np.mean(ms)/base - 1):+.0f}% vs DFN light"
        base = np.mean(ms) if base is None else base
        print(f"  {k:<12}{np.mean(ms):>10.1f}{np.std(ms):>8.1f}{rel}")

    print("\n" + "=" * 78)
    print("VOICE QUALITY — phonation & spectral tilt (Praat), mean +/- std over windows")
    print("=" * 78)
    print("  cpps/hnr = periodicity (LOWER = breathier//more aperiodic)")
    print("  alpha_std/hammarberg/h1h2 = spectral tilt (HIGHER = softer/more low-band)\n")
    vq = {k: vq_windows(v) for k, v in VERSIONS.items()}
    keys = [k for k in ("cpps", "hnr", "alpha_std", "hammarberg", "h1h2") if k in vq["original"]]
    print(f"  {'version':<12}" + "".join(f"{k:>16}" for k in keys))
    for k in VERSIONS:
        if not vq[k]:
            continue
        print(f"  {k:<12}" + "".join(f"{vq[k][m][0]:>10.2f}±{vq[k][m][1]:<5.2f}" for m in keys))
    print(f"\n  {'DELTA vs orig':<12}" + "".join(f"{k:>16}" for k in keys))
    for k in VERSIONS:
        if k == "original" or not vq[k]:
            continue
        cells = ""
        for m in keys:
            d = vq[k][m][0] - vq["original"][m][0]
            sd = vq["original"][m][1]
            flag = "!" if sd > 0 and abs(d) > 2 * sd else " "
            cells += f"{d:>+14.2f}{flag} "
        print(f"  {k:<12}" + cells)
    print("\n  '!' = shifted more than 2x the natural window-to-window spread of the original")


if __name__ == "__main__":
    main()
