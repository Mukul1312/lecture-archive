"""ref_shortlist.py — clean the Hindi ECAPA yardstick + representativeness-shortlist reference candidates.
Stage 1 of the plan's two-stage reference selection (representativeness-shortlist -> refsweep-confirm).
Centroid: TRIMMED cross-lecture (L2-4) core (drop non-him/noisy outliers). Then rank the 106 vetted
L1 train_final clips by cosine-to-centroid; shortlist the most-representative, well-sized, clean ones.
Local, CPU."""
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

def load_wav(path, sr_t=16000):
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    rms = float(np.sqrt(np.mean(y**2))) if len(y) else 0.0
    if sr != sr_t:
        g = gcd(sr, sr_t); y = resample_poly(y, sr_t//g, sr//g).astype("float32")
    return torch.from_numpy(np.ascontiguousarray(y)).unsqueeze(0), rms

@torch.no_grad()
def embed(p):
    w, rms = load_wav(p)
    e = clf.encode_batch(w.to(DEV)).squeeze(0).squeeze(0)
    return F.normalize(e, dim=0), rms
def cos(a, b): return float(torch.dot(a, b))

# --- clean cross-lecture centroid: embed L2-4 sample, drop outliers, rebuild ---
raw = []
for L in ["02", "03", "04"]:
    for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]:
        e, _ = embed(p); raw.append(e)
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
keep = [e for e in raw if cos(e, c0) >= 0.55]          # self-consistent core (drop non-him/noisy)
cen = F.normalize(torch.stack(keep).mean(0), dim=0)
ceil = sorted(cos(e, cen) for e in keep)
print(f"clean centroid: kept {len(keep)}/{len(raw)} L2-4 clips (dropped {len(raw)-len(keep)} outliers)")
print(f"CEILING band (core vs centroid): p50 {np.median(ceil):.3f}  p10 {ceil[len(ceil)//10]:.3f}  max {ceil[-1]:.3f}")

# --- score the 106 vetted L1 candidates by representativeness ---
rows = [json.loads(l) for l in (ROOT/"data/hi/train_final/train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
cand = []
for r in rows:
    p = ROOT/"data/hi/train_final"/r["audio"]
    if not p.exists(): continue
    e, rms = embed(p)
    cand.append({"audio": r["audio"], "text": r["text"], "dur": r["duration"],
                 "repr": cos(e, cen), "rms": rms})
cand.sort(key=lambda x: -x["repr"])
print(f"\nrepresentativeness over {len(cand)} L1 clips: top {cand[0]['repr']:.3f}  median {np.median([c['repr'] for c in cand]):.3f}  low {cand[-1]['repr']:.3f}")

# shortlist: well-sized (6-11s), decent level, most representative, top 12
short = [c for c in cand if 6 <= c["dur"] <= 11 and c["rms"] > 0.02][:12]
print(f"\n=== SHORTLIST (top {len(short)} reference candidates) ===")
for c in short:
    print(f"  repr {c['repr']:.3f}  dur {c['dur']:.1f}s  {Path(c['audio']).name}  | {c['text'][:45]}")
(ROOT/"data/hi/ref_shortlist.jsonl").write_text(
    "\n".join(json.dumps({"audio": c["audio"], "text": c["text"], "dur": c["dur"], "repr": c["repr"]},
                         ensure_ascii=False) for c in short), encoding="utf-8")
print(f"\nwrote data/hi/ref_shortlist.jsonl  ({len(short)} candidates for the refsweep)")
