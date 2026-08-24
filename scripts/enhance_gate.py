"""
enhance_gate.py — score every candidate on BOTH axes and shortlist who gets auditioned.

The P.835 structure we cannot measure directly, approximated with what runs locally:

  SIG (did the voice survive?)   d-vector cosine to the original, ANCHORED against how much the
                                 untouched recording already varies against itself.
  BAK (was noise removed?)       noise-floor drop in the silences + how much of it is now digital
                                 zero (the gating artefact that caused the original rejection).

The anchor is the whole point. A cosine of 0.81 means nothing until you know that two different
15 s chunks of the SAME untouched recording score 0.936 — at which point 0.81 means the processing
moved him further than changing the sentence does.

Per Hu & Loizou (P.835, 32 listeners): listeners weight SIG far above BAK, so SIG is a VETO here,
not a term to average. A candidate that scrubs more noise while dropping below the anchor loses.

This picks who gets AUDITIONED. It does not pick the winner — ears do that, blind.

RUN: .venv/Scripts/python.exe scripts/enhance_gate.py [dir]        (default data/enhance/poc/v2)
"""
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import soundfile as sf
import librosa
import librosa.feature  # noqa
_ = librosa.feature.mfcc
from resemblyzer import VoiceEncoder, preprocess_wav

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SR = 16000
CHUNK_S = 15.0
VQ_WINDOWS = 6


def load16k(p):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    return librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y


def chunks(y):
    n = int(CHUNK_S * SR)
    return [y[i:i + n] for i in range(0, len(y) - n + 1, n)]


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def noise_stats(path):
    """BAK side: floor level in the quiet frames, and how much is hard digital zero."""
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    r = librosa.feature.rms(y=y, frame_length=4096, hop_length=1024)[0]
    rdb = 20 * np.log10(np.maximum(r, 1e-12))
    return dict(floor=float(np.percentile(rdb, 5)),
                speech=float(np.percentile(rdb, 90)),
                zero_pct=100 * float(np.mean(y == 0.0)))


def vq_mean(path):
    from voice_quality import vq_feats
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    n = int(30.0 * sr)
    starts = np.linspace(0, max(len(y) - n, 0), VQ_WINDOWS).astype(int)
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for k, s in enumerate(starts):
            p = Path(td) / f"w{k}.wav"
            sf.write(str(p), y[s:s + n], sr)
            try:
                rows.append(vq_feats(p))
            except Exception:
                pass
    return {k: float(np.mean([r[k] for r in rows])) for k in rows[0]} if rows else {}


def main():
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/enhance/poc/v2"
    files = sorted(d.glob("*.wav"))
    orig = next((f for f in files if "original" in f.name), None)
    if orig is None:
        sys.exit(f"no *original*.wav in {d}")
    cands = [f for f in files if f != orig]

    print(f"Scoring {len(cands)} candidates against {orig.name}\n")
    enc = VoiceEncoder("cpu")

    yo = load16k(orig)
    co = chunks(yo)
    eo = np.stack([enc.embed_utterance(preprocess_wav(c, source_sr=SR)) for c in co])
    n = len(co)

    nat = [cos(eo[i], eo[j]) for i in range(n) for j in range(i + 1, n)]
    anchor, anchor_min = float(np.mean(nat)), float(np.min(nat))
    print("=" * 92)
    print(f"ANCHOR  natural variation inside the untouched recording")
    print(f"        mean {anchor:.4f}   min {anchor_min:.4f}   ({len(nat)} pairs of {CHUNK_S:.0f}s chunks)")
    print(f"        A candidate must stay ABOVE this to claim it preserved him.")
    print("=" * 92)

    o_ns, o_vq = noise_stats(orig), vq_mean(orig)

    rows = []
    for f in cands:
        y = load16k(f)
        ch = chunks(y)[:n]
        e = np.stack([enc.embed_utterance(preprocess_wav(c, source_sr=SR)) for c in ch])
        cs = [cos(eo[i], e[i]) for i in range(len(ch))]
        ns, vq = noise_stats(f), vq_mean(f)
        rows.append(dict(name=f.stem, cos=float(np.mean(cs)), cos_min=float(np.min(cs)),
                         floor_drop=o_ns["floor"] - ns["floor"], zero=ns["zero_pct"],
                         d_cpps=vq.get("cpps", np.nan) - o_vq.get("cpps", np.nan),
                         d_hnr=vq.get("hnr", np.nan) - o_vq.get("hnr", np.nan),
                         d_hamm=vq.get("hammarberg", np.nan) - o_vq.get("hammarberg", np.nan)))

    rows.sort(key=lambda r: -r["cos"])
    print(f"\n{'candidate':<20}{'cos':>8}{'vs anchor':>11}{'noise cut':>11}{'zero%':>8}"
          f"{'dCPPS':>8}{'dHNR':>8}{'dHamm':>8}   verdict")
    print("-" * 108)
    for r in rows:
        gap = r["cos"] - anchor
        if gap >= 0:
            v = "PASS — within natural variation"
        elif gap > -0.03:
            v = "BORDERLINE"
        else:
            v = "FAIL — moved him more than a different sentence"
        print(f"{r['name']:<20}{r['cos']:>8.4f}{gap:>+11.4f}{r['floor_drop']:>10.1f}dB"
              f"{r['zero']:>8.2f}{r['d_cpps']:>+8.2f}{r['d_hnr']:>+8.2f}{r['d_hamm']:>+8.2f}   {v}")

    keep = [r for r in rows if r["cos"] - anchor > -0.03]
    print("\n" + "=" * 92)
    if keep:
        print("SHORTLIST for blind listening (SIG held; ranked by noise removed):")
        for r in sorted(keep, key=lambda r: -r["floor_drop"]):
            print(f"   {r['name']:<20} cut {r['floor_drop']:>5.1f} dB of noise, cos {r['cos']:.4f}")
    else:
        print("NOTHING PASSED. Every candidate moved the voice more than natural variation.")
        print("Least-damaging option:", rows[0]["name"], f"(cos {rows[0]['cos']:.4f})")
    print("=" * 92)


if __name__ == "__main__":
    main()
