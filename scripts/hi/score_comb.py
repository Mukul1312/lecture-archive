"""score_v1.py — ECAPA-score the v1 clips (winning ref 0008) vs the clean cross-lecture centroid,
with the OLD 0074 clone as the before/after baseline."""
import sys, glob
from pathlib import Path
from math import gcd
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
import torch, torch.nn.functional as F
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"c:\Users\Mukul\code\personal-projects\voice-cloning")
DEV = "cpu"
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(ROOT/".venv/spkrec"), run_opts={"device": DEV}, local_strategy=LocalStrategy.COPY)
def load_wav(p, sr_t=16000):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    if sr != sr_t:
        g = gcd(sr, sr_t); y = resample_poly(y, sr_t//g, sr//g).astype("float32")
    return torch.from_numpy(np.ascontiguousarray(y)).unsqueeze(0)
@torch.no_grad()
def embed(p):
    e = clf.encode_batch(load_wav(p).to(DEV)).squeeze(0).squeeze(0); return F.normalize(e, dim=0)
def cos(a, b): return float(torch.dot(a, b))

raw = [embed(p) for L in ["02","03","04"]
       for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]]
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
cen = F.normalize(torch.stack([e for e in raw if cos(e, c0) >= 0.55]).mean(0), dim=0)
ceil = sorted(cos(e, cen) for e in raw if cos(e, c0) >= 0.55)
print(f"his-own ceiling (median): {np.median(ceil):.3f}\n")

print("=== BEFORE (old ref 0074) ===")
for p in [ROOT/"data/hi/clone_samples/1_CLONE_hare_krishna.wav",
          ROOT/"data/hi/clone_samples/2_CLONE_jeevan.wav"]:
    if p.exists(): print(f"  {cos(embed(p), cen):.3f}  {p.name}")

print("\n=== v1 (winning ref 0008, lead-in + trimmed) ===")
for p in sorted(glob.glob(str(ROOT/"data/hi/v1/v1_combined_*.wav"))):
    tag = "trimmed" if p.endswith("_trim.wav") else "lead-in"
    print(f"  {cos(embed(p), cen):.3f}  [{tag}]  {Path(p).name}")
