"""
seed_ablation.py — what does 24 seeds/chunk actually buy over 12? A best-of-N curve on the noisy tier
(which already has all 24 seeds). For N in {6,12,18,24}: run the real funnel on the first N seeds and
report the ABSOLUTE quality of the picked take, averaged over the 20 GGS chunks:
  alpha  = mean vocal effort (spectral tilt) of the pick   — lower = softer
  peak   = mean PEAK effort (loudest moment)               — lower = fewer shouty spikes
  rate   = mean speech rate                                — lower = slower/calmer
  ecapa  = mean identity of the pick                       — higher = more him
  duds   = chunks with NO gate-passing take (fell back)    — fewer = better
  changed= chunks whose pick improved vs the previous N    — how often more seeds help

Seed count sets the noise/identity CHARACTER not at all (that's the tier); it only changes how good the
BEST take the funnel can find is. Best-of-N improves with diminishing returns.

Run: .venv/Scripts/python.exe scripts/seed_ablation.py
"""
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gate_takes as gt
import assemble_variants as av

sys.stdout.reconfigure(encoding="utf-8")
NOISY = ROOT / "data/out/lecture1/diary"
NARR = {1, 2, 3}
ORDER = [42, 123, 7, 2024, 99, 314, 777, 2025, 1, 11, 21, 55,
         88, 111, 222, 333, 444, 555, 666, 888, 999, 1234, 1976, 8848]
PAT = re.compile(r"(?P<ch>\d+)__s(?P<seed>\d+)\.wav")


def duds(rows):
    """# chunks where NO take passes duration+identity gate (funnel falls back to raw)."""
    ev = np.array([r["ecapa"] for r in rows])
    id_thr = max(0.55, float(ev.mean() - 1.4 * ev.std())) if ev.size else 0.55
    from collections import defaultdict
    by = defaultdict(list)
    for r in rows:
        by[r["ch"]].append(r)
    n = 0
    for ch, ts in by.items():
        med = float(np.median([t["dur"] for t in ts]))
        clean = [t for t in ts if 0.6 * med <= t["dur"] <= 1.35 * med and t["ecapa"] >= id_thr]
        n += (len(clean) == 0)
    return n


def main():
    print("[ecapa] centroid ...")
    embed, ref, ceil, cos = gt.ecapa_centroid()
    allr = [av.row(p, NOISY, False, embed, cos, ref) for p in sorted(NOISY.glob("*.wav"))
            if int(PAT.match(p.name)["ch"]) not in NARR]
    print(f"noisy GGS takes loaded: {len(allr)} (over {len({r['ch'] for r in allr})} chunks)\n")

    print(f"{'N':>3}  {'alpha↓':>7} {'peak↓':>7} {'rate↓':>7} {'ecapa↑':>7}  {'duds':>4}  {'changed':>7}")
    print("-" * 52)
    prev = None
    for N in (6, 12, 18, 24):
        seeds = set(ORDER[:N])
        rows = [dict(r) for r in allr if r["seed"] in seeds]   # fresh copies (funnel adds z_ keys)
        picks, _ = av.funnel(rows)
        ggs = [picks[ch] for ch in sorted(picks)]
        a = np.mean([t["alpha"] for t in ggs])
        pk = np.mean([t["peak"] for t in ggs])
        rt = np.mean([t["rate"] for t in ggs])
        ec = np.mean([t["ecapa"] for t in ggs])
        changed = sum(1 for ch in picks if prev and picks[ch]["wav"] != prev.get(ch, {}).get("wav", "")) if prev else 0
        print(f"{N:>3}  {a:7.2f} {pk:7.2f} {rt:7.2f} {ec:7.3f}  {duds(rows):>4}  {changed:>7}")
        prev = {ch: picks[ch] for ch in picks}
    print("\nRead: lower alpha/peak/rate = softer/calmer pick; higher ecapa = more him; fewer duds = safer.")
    print("The 6→12 step is the big win; 12→24 is a smaller polish (diminishing returns of best-of-N).")


if __name__ == "__main__":
    main()
