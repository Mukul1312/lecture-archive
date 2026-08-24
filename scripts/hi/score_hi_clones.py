"""score_hi_clones.py — Hindi ECAPA identity yardstick (CROSS-LECTURE, avoids circularity).
Centroid + ceiling from his lectures 2-4; the clones were made from a LECTURE-1 reference, so scoring
vs 2-4 is a fair generalization test. Objective 'how much is this him'. Local, CPU. Reuses ecapa_score pattern."""
import sys, glob
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
def centroid(ps): return F.normalize(torch.stack([embed(p) for p in ps]).mean(0), dim=0)
def clips(lec, a, b):
    return sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{lec}/clips_hi/*.wav")))[a:b]

cen_paths, ceil_paths = [], []
for L in ["02", "03", "04"]:
    cen_paths += clips(L, 0, 15); ceil_paths += clips(L, 15, 23)
cen = centroid(cen_paths)
ceil = [cos(embed(p), cen) for p in ceil_paths]
l1 = [cos(embed(p), cen) for p in clips("01", 0, 12)]
print(f"centroid: {len(cen_paths)} clips (lectures 2-4)")
print(f"CEILING  (his held-out L2-4 vs centroid): mean {np.mean(ceil):.3f}  min {min(ceil):.3f}  max {max(ceil):.3f}")
print(f"ANCHOR   (his LECTURE-1 clips vs L2-4 centroid, cross-lecture): mean {np.mean(l1):.3f}")

CS = ROOT/"data/hi/clone_samples"
labels = {
 "0_REFERENCE_real_him.wav": "REAL him (ref clip 0074, L1)",
 "1_CLONE_hare_krishna.wav": "clone harekrishna  hifi ts10",
 "2_CLONE_jeevan.wav": "clone jeevan       hifi ts10",
 "mode_harekrishna_hifi.wav": "clone harekrishna  hifi ts10 (rerun)",
 "mode_jeevan_hifi.wav": "clone jeevan       hifi ts10 (rerun)",
 "imp_harekrishna_A_norm30.wav": "clone harekrishna  A norm30",
 "imp_harekrishna_B_leadin.wav": "clone harekrishna  B leadin",
 "imp_harekrishna_C_cfg15.wav": "clone harekrishna  C cfg1.5",
 "imp_jeevan_A_norm30.wav": "clone jeevan       A norm30",
 "imp_jeevan_B_leadin.wav": "clone jeevan       B leadin",
 "imp_jeevan_C_cfg15.wav": "clone jeevan       C cfg1.5",
}
print("\n=== ECAPA cosine to his Hindi voice (L2-4 centroid) — higher = more him ===")
scored = []
for fn, lab in labels.items():
    p = CS/fn
    if not p.exists(): print(f"  (missing {fn})"); continue
    scored.append((cos(embed(p), cen), lab))
scored.sort(reverse=True)
for c, lab in scored:
    print(f"  {c:.3f}   {lab}")
print(f"\nscale: ceiling(his own)~{np.mean(ceil):.3f}  |  cross-lecture anchor~{np.mean(l1):.3f}")
