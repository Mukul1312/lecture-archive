"""score_expr.py — track B: does an EXPRESSIVE reference transfer more pitch-swing than the calm 0008?
For each expressive ref's outputs: ECAPA identity + output F0-std (swing). Baseline = out_diary (ref 0008).
F0 is a SECONDARY signal (ear is primary), but higher output F0-std suggests more pitch movement. Local, CPU."""
import sys, glob, json, re
from pathlib import Path
from math import gcd
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
import torch, torch.nn.functional as F
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from repo_paths import repository_root

sys.stdout.reconfigure(encoding="utf-8")
ROOT = repository_root(__file__)
EXPR, DIARY = ROOT/"data/hi/out_expr", ROOT/"data/hi/out_diary"
DEV = "cpu"
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(ROOT/".venv/spkrec"), run_opts={"device": DEV}, local_strategy=LocalStrategy.COPY)
def rd(p, sr_t=16000):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    y16 = y if sr == sr_t else resample_poly(y, sr_t//gcd(sr, sr_t), sr//gcd(sr, sr_t)).astype("float32")
    return y16
@torch.no_grad()
def emb(y): e = clf.encode_batch(torch.from_numpy(np.ascontiguousarray(y)).unsqueeze(0).to(DEV)).squeeze(0).squeeze(0); return F.normalize(e, dim=0)
def cos(a, b): return float(torch.dot(a, b))
def f0std(y, sr=16000, fmin=70, fmax=350):
    win = int(0.04*sr); hop = int(0.02*sr); f0 = []
    for i in range(0, max(1, len(y)-win), hop):
        x = y[i:i+win] - y[i:i+win].mean()
        if np.sqrt(np.mean(x**2)) < 1e-3: continue
        c = np.correlate(x, x, mode="full")[len(x)-1:]
        if c[0] <= 0: continue
        lo, hi = int(sr/fmax), min(int(sr/fmin), len(c)-1)
        if hi <= lo: continue
        k = np.argmax(c[lo:hi]) + lo
        if c[k]/c[0] > 0.35: f0.append(sr/k)
    return float(np.std(f0)) if len(f0) > 5 else 0.0

raw = [emb(rd(p)) for L in ["02","03","04"]
       for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]]
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
cen = F.normalize(torch.stack([e for e in raw if cos(e, c0) >= 0.55]).mean(0), dim=0)
refmeta = {json.loads(l)["audio"].split("/")[-1].replace(".wav",""): json.loads(l)
           for l in (ROOT/"data/hi/expressive_refs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}

def stats(files):
    ids = [cos(emb(rd(f)), cen) for f in files]
    sw = [f0std(rd(f)) for f in files]
    return np.mean(ids), np.mean(sw), len(files)

# baseline: ref 0008 (the diary), from out_diary
b_id, b_sw, b_n = stats(glob.glob(str(DIARY/"*.wav")))
print(f"BASELINE  ref 0008 (calm, ref-F0std ~52):  out-identity {b_id:.3f}   out-swing(F0std) {b_sw:.0f}   (n={b_n})\n")
print("=== EXPRESSIVE references — output identity & swing ===")
print(f"  {'ref':10} {'refF0std':>8} {'out-ident':>9} {'out-swing':>9}")
rows = []
for stem, meta in refmeta.items():
    fs = glob.glob(str(EXPR/f"r{stem}__*.wav"))
    if not fs: continue
    oid, osw, n = stats(fs)
    rows.append((osw, oid, stem, meta.get("f0std", 0)))
rows.sort(reverse=True)
for osw, oid, stem, rf0 in rows:
    flag = "  <- more swing than 0008" if osw > b_sw else ""
    print(f"  {stem.replace('ggm-hindi-lecture-01_',''):10} {rf0:8.0f} {oid:9.3f} {osw:9.0f}{flag}")
print(f"\n(0008 baseline out-swing {b_sw:.0f}; higher out-swing = more pitch movement — but JUDGE BY EAR, F0 is secondary)")
