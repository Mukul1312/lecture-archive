"""expressive_refs.py — track B: rank his 106 clips by PITCH EXPRESSIVENESS (F0 std) among identity-decent
ones, to find an ANIMATED reference that might transfer more pitch-swing. (F0 std is a valid RELATIVE
measure across his own same-condition clips.) Writes expressive_refs.jsonl (top candidates). Local, CPU."""
import sys, glob, json
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
DEV = "cpu"
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(ROOT/".venv/spkrec"), run_opts={"device": DEV}, local_strategy=LocalStrategy.COPY)
def rd(p, sr_t=16000):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    y16 = y if sr == sr_t else resample_poly(y, sr_t//gcd(sr, sr_t), sr//gcd(sr, sr_t)).astype("float32")
    return y16, torch.from_numpy(np.ascontiguousarray(y16)).unsqueeze(0)
@torch.no_grad()
def emb(t): e = clf.encode_batch(t.to(DEV)).squeeze(0).squeeze(0); return F.normalize(e, dim=0)
def cos(a, b): return float(torch.dot(a, b))
def f0_std(y, sr=16000, fmin=70, fmax=350):
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
    return (float(np.std(f0)), float(np.median(f0))) if len(f0) > 5 else (0.0, 0.0)

raw = [emb(rd(p)[1]) for L in ["02","03","04"]
       for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]]
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
cen = F.normalize(torch.stack([e for e in raw if cos(e, c0) >= 0.55]).mean(0), dim=0)

rows = [json.loads(l) for l in (ROOT/"data/hi/train_final/train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
cand = []
for r in rows:
    p = ROOT/"data/hi/train_final"/r["audio"]
    if not p.exists() or not (6 <= r["duration"] <= 12): continue
    y, t = rd(p); sd, med = f0_std(y)
    cand.append({"audio": r["audio"], "text": r["text"], "dur": r["duration"],
                 "ident": cos(emb(t), cen), "f0std": sd, "f0med": med})
# keep identity-decent, rank by expressiveness
ok = [c for c in cand if c["ident"] >= 0.80]
ok.sort(key=lambda x: -x["f0std"])
print(f"scored {len(cand)} clips; {len(ok)} with identity>=0.80")
print(f"{'clip':34} {'f0std':>6} {'ident':>6} {'dur':>4}")
for c in ok[:8]:
    print(f"  {Path(c['audio']).name:32} {c['f0std']:6.0f} {c['ident']:6.3f} {c['dur']:4.1f}   {c['text'][:32]}")
print(f"\n(current diary ref 0008 for comparison:)")
for c in cand:
    if "0008" in c["audio"]: print(f"  0008  f0std {c['f0std']:.0f}  ident {c['ident']:.3f}")
top = ok[:5]
(ROOT/"data/hi/expressive_refs.jsonl").write_text(
    "\n".join(json.dumps({"audio": c["audio"], "text": c["text"], "f0std": c["f0std"], "ident": c["ident"]},
                         ensure_ascii=False) for c in top), encoding="utf-8")
print(f"\nwrote data/hi/expressive_refs.jsonl ({len(top)} animated candidates)")
