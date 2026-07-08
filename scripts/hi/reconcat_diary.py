"""reconcat_diary.py — fix the choppy joins: trim leading/trailing silence per chosen passage take,
then concatenate with a short natural gap. Same best-take selection as funnel_diary. -> diary_entry2_v2.wav."""
import sys, glob, json
from pathlib import Path
from math import gcd
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
import torch, torch.nn.functional as F
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"c:\Users\Mukul\code\personal-projects\voice-cloning")
TAKES = ROOT/"data/hi/out_diary"
DEV = "cpu"
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(ROOT/".venv/spkrec"), run_opts={"device": DEV}, local_strategy=LocalStrategy.COPY)
def rd(p, sr_t=16000):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    y16 = y if sr == sr_t else resample_poly(y, sr_t//gcd(sr, sr_t), sr//gcd(sr, sr_t)).astype("float32")
    return y, sr, torch.from_numpy(np.ascontiguousarray(y16)).unsqueeze(0)
@torch.no_grad()
def emb(t): e = clf.encode_batch(t.to(DEV)).squeeze(0).squeeze(0); return F.normalize(e, dim=0)
def cos(a, b): return float(torch.dot(a, b))
def trim_sil(y, sr, drop=42.0, pad=0.06):
    win = int(0.025*sr); hop = int(0.01*sr)
    db = np.array([20*np.log10(np.sqrt(np.mean(y[i:i+win]**2))+1e-9) for i in range(0, max(1, len(y)-win), hop)])
    v = np.where(db > db.max()-drop)[0]
    if len(v) == 0: return y
    a = max(0, v[0]*hop - int(pad*sr)); b = min(len(y), (v[-1]+1)*hop + int(pad*sr))
    return y[a:b]

raw = [emb(rd(p)[2]) for L in ["02","03","04"]
       for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]]
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
cen = F.normalize(torch.stack([e for e in raw if cos(e, c0) >= 0.55]).mean(0), dim=0)

passages = json.load(open(ROOT/"data/hi/diary_passages.json", encoding="utf-8"))
segs = []; sr_out = None
for p in passages:
    exp = len(p["hi"].split())/2.2
    cands = []
    for f in sorted(glob.glob(str(TAKES/f"{p['id']}__s*.wav"))):
        y, sr, t = rd(f); sr_out = sr; dur = len(y)/sr
        if dur < max(1.0, 0.5*exp) or dur > 2.2*exp: continue
        cands.append((cos(emb(t), cen), f, y))
    if not cands: continue
    cands.sort(key=lambda x: -x[0])
    y = trim_sil(cands[0][2], sr_out)
    segs.append(y)
    print(f"{p['id']}: {Path(cands[0][1]).name}  trimmed -> {len(y)/sr_out:.1f}s")

gap = np.zeros(int(0.18*sr_out), dtype=np.float32)
full = segs[0]
for s in segs[1:]:
    full = np.concatenate([full, gap, s])
out = ROOT/"data/hi/diary_entry2_v2.wav"
sf.write(str(out), full, sr_out)
whole = cos(emb(rd(out)[2]), cen)
print(f"\n{out.name}: {len(full)/sr_out:.0f}s (was 166s)  |  whole-clip ECAPA {whole:.3f}")
