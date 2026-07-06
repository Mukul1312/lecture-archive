"""funnel_diary.py — per passage: gate seeds by duration sanity, pick highest-ECAPA survivor,
concatenate in order into the diary Short. Scores the whole clip. Local, CPU.
Usage: funnel_diary.py <takes_dir> <passages.json> <out.wav>"""
import sys, glob, json, re
from pathlib import Path
from math import gcd
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
import torch, torch.nn.functional as F
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"c:\Users\Mukul\code\personal-projects\voice-cloning")
TAKES = Path(sys.argv[1]); PASS = Path(sys.argv[2]); OUTWAV = Path(sys.argv[3])
DEV = "cpu"
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(ROOT/".venv/spkrec"), run_opts={"device": DEV}, local_strategy=LocalStrategy.COPY)
def rd(p, sr_t=16000):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    if sr != sr_t:
        g = gcd(sr, sr_t); y2 = resample_poly(y, sr_t//g, sr//g).astype("float32")
    else: y2 = y
    return y, sr, torch.from_numpy(np.ascontiguousarray(y2)).unsqueeze(0)
@torch.no_grad()
def emb(t): e = clf.encode_batch(t.to(DEV)).squeeze(0).squeeze(0); return F.normalize(e, dim=0)
def cos(a, b): return float(torch.dot(a, b))

raw = [emb(rd(p)[2]) for L in ["02","03","04"]
       for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]]
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
cen = F.normalize(torch.stack([e for e in raw if cos(e, c0) >= 0.55]).mean(0), dim=0)

passages = json.load(open(PASS, encoding="utf-8"))
sr_out = None; chosen = []
for p in passages:
    exp = len(p["hi"].split()) / 2.2                     # expected sec (~2.2 words/sec)
    cands = []
    for f in sorted(glob.glob(str(TAKES/f"{p['id']}__s*.wav"))):
        y, sr, t = rd(f); sr_out = sr; dur = len(y)/sr
        if dur < max(1.0, 0.5*exp) or dur > 2.2*exp:      # gate: truncation / loop
            continue
        cands.append((cos(emb(t), cen), dur, f, y))
    if not cands:                                          # fallback: take longest if all gated
        cands = [(cos(emb(rd(f)[2]), cen), len(rd(f)[0])/rd(f)[1], f, rd(f)[0])
                 for f in glob.glob(str(TAKES/f"{p['id']}__s*.wav"))]
    cands.sort(reverse=True)
    sc, dur, f, y = cands[0]
    chosen.append((p["id"], sc, dur, Path(f).name, y))
    print(f"{p['id']}: pick {Path(f).name}  ecapa {sc:.3f}  dur {dur:.1f}s  ({len(cands)} survived gate)")

# concat with 0.35s pauses
gap = np.zeros(int(0.35*sr_out), dtype=np.float32)
full = np.concatenate([seg for i, (_, _, _, _, seg) in enumerate(chosen)
                       for seg in ([chosen[i][4]] if i == 0 else [gap, chosen[i][4]])])
sf.write(str(OUTWAV), full, sr_out)
whole = cos(emb(rd(OUTWAV)[2]), cen)
print(f"\nDIARY SHORT: {OUTWAV.name}  total {len(full)/sr_out:.1f}s  |  whole-clip ECAPA {whole:.3f}")
print(f"(his-own ceiling ~0.767; per-passage mean {np.mean([c[1] for c in chosen]):.3f})")
