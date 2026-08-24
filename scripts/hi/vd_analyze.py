"""
vd_analyze.py — screen the Voice Design sweep on the two things that gate usability.

1. SAFETY  — cosine vs GGSM's centroid. A description that lands near his ceiling is disqualified
              no matter how good it sounds. (Same centroid construction as voice_gate.py: built
              from lectures 01+02, so the 0.694 / 0.811 ceilings there are directly comparable.)
2. CONSISTENCY — mean pairwise cosine BETWEEN SEEDS of the same description. Voice Design invents a
              speaker from text, so nothing guarantees seed 42 and seed 7 are the same person. A
              multi-episode series needs one recognisable narrator, so a description that drifts
              across seeds is unusable even if every individual take sounds good.

Run each encoder in its own process (the two libraries conflict):
  .venv/Scripts/python.exe scripts/hi/vd_analyze.py --enc ecapa
  .venv/Scripts/python.exe scripts/hi/vd_analyze.py --enc dvector
"""
import argparse
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts/hi"))
from voice_gate import build_ecapa, build_dvector, his_clips, CENTROID_LECTURES, CEILING_LECTURES  # noqa: E402

VD = ROOT / "data/hi/out_vd"
sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enc", required=True, choices=["ecapa", "dvector"])
    args = ap.parse_args()

    wavs = sorted(VD.glob("*.wav"))
    if not wavs:
        sys.exit(f"no wavs in {VD}")
    embed = build_ecapa() if args.enc == "ecapa" else build_dvector()

    cen_paths, ceil_paths = his_clips(CENTROID_LECTURES), his_clips(CEILING_LECTURES)
    print(f"[{args.enc}] centroid {len(cen_paths)} · ceiling {len(ceil_paths)} · candidates {len(wavs)} ...")
    E = np.stack([embed(p) for p in cen_paths])
    cen = E.mean(0); cen /= (np.linalg.norm(cen) + 1e-9)
    ceiling = float(np.mean([np.dot(embed(p), cen) for p in ceil_paths]))

    # one embedding per clip, reused for both questions
    emb = {p.stem: embed(p) for p in wavs}
    by_desc = defaultdict(list)
    for stem, v in emb.items():
        by_desc[stem.split("__")[0]].append((stem, v))

    print(f"\nHIS cross-lecture ceiling: {ceiling:.3f}   (a candidate near this reads as HIM)\n")
    print(f"{'description':<12} {'vs GGSM (mean)':>15} {'worst':>8} {'seed-to-seed consistency':>26}")
    rows = []
    for desc in sorted(by_desc):
        items = by_desc[desc]
        sims = [float(np.dot(v, cen)) for _, v in items]
        pairs = [float(np.dot(a, b)) for (_, a), (_, b) in combinations(items, 2)]
        consist = float(np.mean(pairs)) if pairs else float("nan")
        rows.append((desc, np.mean(sims), max(sims), consist))
        print(f"{desc:<12} {np.mean(sims):>15.3f} {max(sims):>8.3f} "
              f"{consist:>20.3f} {'(n=%d pairs)' % len(pairs)}")

    print("\nReading it:")
    print(f"  · vs GGSM — compare against his ceiling {ceiling:.3f}. Lower = safer.")
    print("  · consistency — 1.0 would be identical takes. HIGHER is better here: it means the")
    print("    description reliably summons the same person. Low = the narrator changes per episode.")
    print("  · Note the tension: consistency and safety are different axes. A description can be")
    print("    perfectly consistent AND too close to him, or safe but a different man every seed.")


if __name__ == "__main__":
    main()
