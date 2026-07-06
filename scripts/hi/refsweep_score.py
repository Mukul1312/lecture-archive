"""refsweep_score.py — score refsweep OUTPUTS by ECAPA, grouped by reference -> rank references by
mean output-identity (stage-2 confirm). Same clean cross-lecture centroid as ref_shortlist.py. Local, CPU."""
import sys, glob, re, json
from pathlib import Path
from math import gcd
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
import torch, torch.nn.functional as F
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"c:\Users\Mukul\code\personal-projects\voice-cloning")
TAKES = ROOT/"data/hi/out_refsweep"        # pull pod:/workspace/out_refsweep here first
DEV = "cpu"
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(ROOT/".venv/spkrec"), run_opts={"device": DEV}, local_strategy=LocalStrategy.COPY)

def load_wav(path, sr_t=16000):
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    if sr != sr_t:
        g = gcd(sr, sr_t); y = resample_poly(y, sr_t//g, sr//g).astype("float32")
    return torch.from_numpy(np.ascontiguousarray(y)).unsqueeze(0)
@torch.no_grad()
def embed(p):
    e = clf.encode_batch(load_wav(p).to(DEV)).squeeze(0).squeeze(0)
    return F.normalize(e, dim=0)
def cos(a, b): return float(torch.dot(a, b))

# clean cross-lecture centroid (identical recipe to ref_shortlist.py)
raw = []
for L in ["02", "03", "04"]:
    for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]:
        raw.append(embed(p))
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
cen = F.normalize(torch.stack([e for e in raw if cos(e, c0) >= 0.55]).mean(0), dim=0)

# representativeness of each ref (from shortlist) for the AGREEMENT check
shortlist = {json.loads(l)["audio"].split("/")[-1].replace(".wav", ""): json.loads(l)["repr"]
             for l in (ROOT/"data/hi/ref_shortlist.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}

by_ref = {}
for p in sorted(glob.glob(str(TAKES/"*.wav"))):
    m = re.match(r"r(.+?)__(\w+)__s(\d+)\.wav", Path(p).name)
    if not m: continue
    ref = m.group(1)
    by_ref.setdefault(ref, []).append(cos(embed(p), cen))

print(f"scored {sum(len(v) for v in by_ref.values())} takes over {len(by_ref)} references\n")
print("=== references ranked by MEAN OUTPUT identity (ECAPA to his Hindi voice) ===")
rows = [(np.mean(v), np.min(v), np.max(v), len(v), ref) for ref, v in by_ref.items()]
rows.sort(reverse=True)
for mean, lo, hi, n, ref in rows:
    rep = shortlist.get(ref, float("nan"))
    print(f"  out {mean:.3f}  (min {lo:.3f} max {hi:.3f}, n={n})   repr {rep:.3f}   {ref}")
print(f"\nBEST reference by output-identity: {rows[0][4]}  (out {rows[0][0]:.3f})")
print("(compare vs current 0074 and vs the representativeness ranking — do they agree?)")
