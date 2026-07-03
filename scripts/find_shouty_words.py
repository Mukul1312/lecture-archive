"""
find_shouty_words.py — WHERE is the residual shouting? Name the words.

For each chunk's picked take: force-align the text to the audio (stable-ts) -> word timestamps,
compute a vocal-effort (alpha ratio / spectral tilt) contour, average it per word, and flag the
highest-effort ("shouty") words. Prints per-chunk + an overall shoutiest-words list.

  .venv/Scripts/python.exe scripts/find_shouty_words.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
import stable_whisper

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/lecture1/diary"
CHUNKS = ROOT / "data/narration/diary_chunks_calm.txt"
CACHE = SRC / "_assemble_cache.json"
sys.stdout.reconfigure(encoding="utf-8")


def picks_from_cache():
    """re-derive the funnel's picked take per chunk (same softness logic as assemble_diary)."""
    rows = json.loads(CACHE.read_text(encoding="utf-8"))["rows"]
    by = defaultdict(list)
    for r in rows:
        by[r["ch"]].append(r)
    picks = {}
    for ch, takes in by.items():
        med = np.median([t["dur"] for t in takes])
        pool = [t for t in takes if 0.6 * med <= t["dur"] <= 1.35 * med and t["ecapa"] >= 0.65] or takes
        for k in ("f0", "spread", "rate", "alpha"):
            v = np.array([t[k] for t in pool], float); mu, sd = v.mean(), (v.std() or 1)
            for t in pool:
                t[f"z{k}"] = (t[k] - mu) / sd
        for t in pool:
            t["s"] = -(t["zf0"] + t["zspread"] + 2 * t["zrate"] + 2.5 * t["zalpha"]) / 6.5
        picks[ch] = max(pool, key=lambda t: t["s"])["wav"]
    return picks


def alpha_contour(y, sr, frame=1024, hop=256):
    win = np.hanning(frame)
    freqs = np.fft.rfftfreq(frame, 1 / sr)
    lo, hi = (freqs >= 50) & (freqs < 1000), (freqs >= 1000) & (freqs < 5000)
    rms_all = np.sqrt(np.mean(y ** 2)) + 1e-9
    t, a = [], []
    for i in range(0, max(0, len(y) - frame), hop):
        seg = y[i:i + frame]
        if np.sqrt(np.mean(seg ** 2)) < 0.35 * rms_all:      # voiced frames only
            continue
        mag = np.abs(np.fft.rfft(seg * win))
        a.append(10 * np.log10((mag[hi].sum() + 1e-9) / (mag[lo].sum() + 1e-9)))
        t.append((i + frame / 2) / sr)
    return np.array(t), np.array(a)


def main():
    texts = [l.strip() for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()]
    picks = picks_from_cache()
    print("[align] loading stable-ts (tiny) ...")
    model = stable_whisper.load_model("tiny")

    allwords = []
    print("\n=== per-chunk vocal effort by word (⚑ = shouty: >0.6 std above this line's mean) ===")
    for ch in sorted(picks):
        wav = SRC / picks[ch]
        y, sr = sf.read(str(wav), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        ct, ca = alpha_contour(y, sr)
        if not len(ca):
            continue
        res = model.align(str(wav), texts[ch - 1], language="en")
        words = []
        for w in res.all_words():
            m = (ct >= w.start) & (ct <= w.end)
            if m.sum() >= 2:
                words.append((w.word.strip(), float(np.mean(ca[m]))))
        if not words:
            continue
        vals = np.array([v for _, v in words])
        thr = vals.mean() + 0.6 * vals.std()
        line = " ".join((f"[{w}⚑{v:+.1f}]" if v >= thr else w) for w, v in words)
        print(f"\n  #{ch}: {line}")
        for w, v in words:
            allwords.append((v, w.strip(".,!?;:").lower(), ch))

    print("\n=== the shoutiest words across the whole diary (highest vocal effort) ===")
    allwords.sort(reverse=True)
    seen = set()
    for v, w, ch in allwords[:18]:
        print(f"  {v:+5.1f} dB  '{w}'  (chunk {ch})")


if __name__ == "__main__":
    main()
