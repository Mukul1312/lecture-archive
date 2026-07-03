"""
score_calibrate.py — regress your blind ear-labels on the decomposed sub-scores and answer the
go/no-go: does S_breathy explain your "sounds like private prayer" judgment BEYOND S_arousal?

Reads:
  data/out/lecture1/calibrate/features.json   (from build_calibrate.py — has S_arousal/S_breathy/S_gravity)
  data/out/lecture1/calibrate/labels.json     (exported from the gallery: {clip: {rating, tags}})

Reports (all honest about small n):
  - OLS adjusted-R2 for  rating ~ S_arousal ; + S_breathy ; + S_gravity
  - incremental R2 from adding S_breathy, with a PERMUTATION test (assumption-light significance)
  - which RAW features correlate with your rating
  - the "subdued but hollow" test: are 'tender' clips breathier than 'flat/bored' clips?
  - the learned (calibrated) weights
Run: .venv/Scripts/python.exe scripts/score_calibrate.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data/out/lecture1/calibrate"


def ols(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ beta
    ss_res = ((y - pred) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum() + 1e-12
    return beta, 1 - ss_res / ss_tot


def adj_r2(r2, n, k):
    return 1 - (1 - r2) * (n - 1) / max(1, (n - k - 1))


def main():
    rows_all = json.loads((D / "features.json").read_text(encoding="utf-8"))
    FKEYS = ["f0", "spread", "loud", "rate", "cpps", "hnr", "alpha_std", "hammarberg", "h1h2"]
    for k in FKEYS:                                  # z-score across the FULL 140-clip pool, then sub-scores
        v = np.array([r[k] for r in rows_all], dtype=float)
        m = np.nanmean(v); s = np.nanstd(v) or 1.0
        for r in rows_all:
            x = r[k]
            r[f"z_{k}"] = 0.0 if (x is None or not np.isfinite(x)) else (x - m) / s
    for r in rows_all:
        r["S_arousal"] = -(r["z_f0"] + r["z_rate"] + r["z_loud"]) / 3      # higher = calmer
        r["S_breathy"] = (r["z_h1h2"] - r["z_cpps"] - r["z_hnr"]) / 3       # higher = breathier
        r["S_gravity"] = -(r["z_f0"] + r["z_spread"]) / 2                    # higher = graver
    feat = {r["clip"]: r for r in rows_all}
    lp = D / "labels.json"
    if not lp.exists():
        sys.exit(f"no labels yet — rate clips in the gallery, Export, and save to {lp}")
    labels = json.loads(lp.read_text(encoding="utf-8"))
    rows = [(feat[c], float(l["rating"]), l.get("tags", []))
            for c, l in labels.items() if c in feat and l.get("rating")]
    n = len(rows)
    if n < 10:
        sys.exit(f"only {n} labeled — need more for a meaningful fit")

    y = np.array([r[1] for r in rows])
    Sa = np.array([r[0]["S_arousal"] for r in rows])
    Sb = np.array([r[0]["S_breathy"] for r in rows])
    Sg = np.array([r[0]["S_gravity"] for r in rows])
    print(f"\n{n} labeled clips | rating {y.min():.0f}-{y.max():.0f} mean {y.mean():.2f} | "
          f"S_arousal x S_breathy corr {np.corrcoef(Sa, Sb)[0, 1]:+.2f}")

    _, r2a = ols(Sa[:, None], y)
    _, r2ab = ols(np.column_stack([Sa, Sb]), y)
    _, r2abg = ols(np.column_stack([Sa, Sb, Sg]), y)
    print("\n=== does your ear need more than arousal? (adjusted R2) ===")
    print(f"  rating ~ S_arousal              R2={r2a:.3f}  adj={adj_r2(r2a, n, 1):.3f}")
    print(f"  rating ~ S_arousal + S_breathy  R2={r2ab:.3f}  adj={adj_r2(r2ab, n, 2):.3f}")
    print(f"  rating ~ + S_gravity            R2={r2abg:.3f} adj={adj_r2(r2abg, n, 3):.3f}")

    dR2 = r2ab - r2a
    rng = np.random.default_rng(1337)
    null = [ols(np.column_stack([Sa, rng.permutation(Sb)]), y)[1] - r2a for _ in range(5000)]
    p = (1 + sum(x >= dR2 for x in null)) / (1 + len(null))
    print(f"\n  incremental R2 from S_breathy: {dR2:+.3f}  (permutation p={p:.3f})")
    print("  -> " + ("S_breathy MATTERS — it explains your ear beyond arousal. Worth engineering."
                     if (dR2 > 0.03 and p < 0.10) else
                     "S_breathy does NOT clearly help here — calm-alone may suffice, or need more labels."))

    print("\n=== which RAW features track your 'prayer' rating? (Pearson r) ===")
    for k in ["f0", "loud", "rate", "spread", "cpps", "hnr", "alpha_std", "hammarberg", "h1h2"]:
        v = np.array([r[0][k] for r in rows], dtype=float)
        m = np.isfinite(v)
        r = float(np.corrcoef(v[m], y[m])[0, 1]) if m.sum() > 2 else float("nan")
        print(f"  {k:11} r={r:+.2f}")

    tend = [r[0]["S_breathy"] for r in rows if "tender" in r[2]]
    flat = [r[0]["S_breathy"] for r in rows if "flat/bored" in r[2]]
    print("\n=== the 'subdued but hollow' test: S_breathy of tender vs flat/bored clips ===")
    if tend and flat:
        print(f"  tender ({len(tend)}):     S_breathy mean {np.mean(tend):+.2f}")
        print(f"  flat/bored ({len(flat)}): S_breathy mean {np.mean(flat):+.2f}")
        print("  -> " + ("tender IS breathier than flat/bored -> S_breathy separates the failure mode the meter was blind to."
                         if np.mean(tend) > np.mean(flat) else
                         "no separation on S_breathy -> breathiness isn't the discriminator your ear uses."))
    else:
        print(f"  (need both tags used: tender={len(tend)}, flat/bored={len(flat)})")

    beta, _ = ols(np.column_stack([Sa, Sb, Sg]), y)
    print("\n=== calibrated composite (learned weights) ===")
    print(f"  rating ~= {beta[0]:+.2f} + {beta[1]:+.2f}*S_arousal + {beta[2]:+.2f}*S_breathy + {beta[3]:+.2f}*S_gravity")


if __name__ == "__main__":
    main()
