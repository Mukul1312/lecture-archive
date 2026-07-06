"""analyze_diary.py — full objective analysis of the diary Short, per passage + whole, vs his REAL voice.
Measures: ECAPA identity, F0/pitch (median, spread=naturalness, range), speaking rate, pause fraction, level.
Re-selects the same best-take per passage the funnel used (ECAPA-max among duration-gated). Local, CPU."""
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
def _f0_frame(x, sr, fmin=70, fmax=350):
    x = x - x.mean()
    if np.sqrt(np.mean(x**2)) < 1e-3: return 0.0        # silence
    c = np.correlate(x, x, mode="full")[len(x)-1:]
    if c[0] <= 0: return 0.0
    lo, hi = int(sr/fmax), min(int(sr/fmin), len(c)-1)
    if hi <= lo: return 0.0
    k = np.argmax(c[lo:hi]) + lo
    return sr/k if c[k]/c[0] > 0.35 else 0.0            # voicing gate
def prosody(y, sr):
    win = int(0.04*sr); hop = int(0.02*sr)
    f0s = np.array([_f0_frame(y[i:i+win], sr) for i in range(0, max(1, len(y)-win), hop)])
    v = f0s[f0s > 0]
    wdb = int(0.025*sr); hdb = int(0.01*sr)
    db = np.array([20*np.log10(np.sqrt(np.mean(y[i:i+wdb]**2))+1e-9) for i in range(0, max(1, len(y)-wdb), hdb)])
    pause = float(np.mean(db < db.max()-40))
    if len(v) == 0: return dict(f0=0, f0std=0, lo=0, hi=0, pause=pause, voiced=0)
    return dict(f0=float(np.median(v)), f0std=float(np.std(v)), lo=float(np.percentile(v, 10)),
                hi=float(np.percentile(v, 90)), pause=pause, voiced=float(len(v)/len(f0s)))

# centroid + his-real prosody baseline (L2-4)
realp = []; raw = []
for L in ["02", "03", "04"]:
    for p in sorted(glob.glob(str(ROOT/f"data/hi/lectures/ggm-hindi-lecture-{L}/clips_hi/*.wav")))[:40]:
        y, sr, t = rd(p); raw.append(emb(t))
        if len(realp) < 24: realp.append(prosody(y, sr))
c0 = F.normalize(torch.stack(raw).mean(0), dim=0)
cen = F.normalize(torch.stack([e for e in raw if cos(e, c0) >= 0.55]).mean(0), dim=0)
RF0 = np.array([r["f0"] for r in realp]); RSTD = np.array([r["f0std"] for r in realp]); RPAU = np.array([r["pause"] for r in realp])
print("=== HIS REAL VOICE baseline (24 clips, L2-4) ===")
print(f"  pitch median {np.mean(RF0):.0f} Hz (range {np.percentile(RF0,10):.0f}-{np.percentile(RF0,90):.0f}) | "
      f"pitch spread(std) {np.mean(RSTD):.0f} Hz | pause {np.mean(RPAU)*100:.0f}%\n")

passages = {p["id"]: p["hi"] for p in json.load(open(ROOT/"data/hi/diary_passages.json", encoding="utf-8"))}
print("=== PER-PASSAGE (chosen take) ===")
print(f"  {'id':4} {'ecapa':>6} {'pitchHz':>7} {'spread':>6} {'wps':>4} {'pause':>5}  flags")
allsc = []
for pid, hi in passages.items():
    exp = len(hi.split())/2.2
    cands = []
    for f in sorted(glob.glob(str(TAKES/f"{pid}__s*.wav"))):
        y, sr, t = rd(f); dur = len(y)/sr
        if dur < max(1.0, 0.5*exp) or dur > 2.2*exp: continue
        cands.append((cos(emb(t), cen), f, y, sr))
    if not cands: continue
    cands.sort(key=lambda x: -x[0])
    sc, f, y, sr = cands[0]
    pr = prosody(y, sr); wps = len(hi.split())/(len(y)/sr)
    flags = []
    if pr["f0std"] < np.percentile(RSTD, 15): flags.append("FLAT?")     # monotone vs his range
    if wps > 3.2: flags.append("fast")
    if wps < 1.5: flags.append("slow")
    if sc < 0.75: flags.append("id-low")
    if pr["f0"] < np.percentile(RF0,5) or pr["f0"] > np.percentile(RF0,95): flags.append("pitch-off")
    allsc.append(sc)
    print(f"  {pid:4} {sc:6.3f} {pr['f0']:7.0f} {pr['f0std']:6.0f} {wps:4.1f} {pr['pause']*100:4.0f}%  {' '.join(flags)}")

# whole clip
y, sr, t = rd(ROOT/"data/hi/diary_entry2.wav")
pr = prosody(y, sr)
print(f"\n=== WHOLE DIARY ({len(y)/sr:.0f}s) ===")
print(f"  ECAPA {cos(emb(t), cen):.3f}  | pitch {pr['f0']:.0f} Hz spread {pr['f0std']:.0f} | pause {pr['pause']*100:.0f}%")
print(f"  per-passage ECAPA mean {np.mean(allsc):.3f} (min {min(allsc):.3f} max {max(allsc):.3f})")
print(f"  interpretation: pitch-spread near his ~{np.mean(RSTD):.0f}Hz = natural intonation; far below = monotone")
