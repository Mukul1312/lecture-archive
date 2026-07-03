"""
score_calibrate_noise.py — is the breathiness signal BREATH or recording HISS?

The calibration found HNR (a periodicity measure) as the top correlate of the "prayer" rating — but
HNR is dragged down by recording noise, so a noisy clip can look "breathy". This script controls for
recording noise (SNR + noise floor, via spectral_inspect) and re-checks:
  (1) partial correlation of each breathiness feature with rating, holding SNR constant,
  (2) whether S_breathy keeps its effect when SNR is added to the regression,
  (3) a NOISE-ROBUST breathy score (H1-H2 + CPPS, dropping the hiss-prone HNR), incremental over
      (arousal + SNR), with a permutation test.
If the robust breathiness survives noise-control -> it's phonation. If it collapses -> it was hiss.
Run after score_calibrate.py. Uses cached features.json + labels.json; noise cached to noise.json.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from spectral_inspect import analyze, load

D = ROOT / "data/out/lecture1/calibrate"
CLIPS = ROOT / "data/out/lecture1/final/clips"
FKEYS = ["f0", "spread", "loud", "rate", "cpps", "hnr", "alpha_std", "hammarberg", "h1h2"]


def zpool(rows):
    for k in FKEYS:
        v = np.array([r[k] for r in rows], float)
        m, s = np.nanmean(v), (np.nanstd(v) or 1.0)
        for r in rows:
            x = r[k]
            r["z_" + k] = 0.0 if (x is None or not np.isfinite(x)) else (x - m) / s
    return rows


def ols(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    p = A @ b
    return b, 1 - ((y - p) ** 2).sum() / (((y - y.mean()) ** 2).sum() + 1e-12)


def pcorr(x, y, z):
    x, y, z = map(np.asarray, (x, y, z))
    rxy, rxz, ryz = np.corrcoef(x, y)[0, 1], np.corrcoef(x, z)[0, 1], np.corrcoef(y, z)[0, 1]
    return (rxy - rxz * ryz) / np.sqrt(max(1e-9, (1 - rxz ** 2) * (1 - ryz ** 2)))


def main():
    rows = zpool(json.loads((D / "features.json").read_text(encoding="utf-8")))
    ncache = D / "noise.json"
    if ncache.exists():
        noise = json.loads(ncache.read_text())
    else:
        noise = {}
        for i, r in enumerate(rows, 1):
            a = analyze(load(CLIPS / f"{r['clip']}.wav"))
            noise[r["clip"]] = {"snr": a["snr"], "floor": a["floor"]}
            if i % 20 == 0:
                print(f"  noise {i}/{len(rows)}", file=sys.stderr)
        ncache.write_text(json.dumps(noise))
    for r in rows:
        r["snr"], r["floor"] = noise[r["clip"]]["snr"], noise[r["clip"]]["floor"]
    feat = {r["clip"]: r for r in rows}

    labels = json.loads((D / "labels.json").read_text(encoding="utf-8"))
    L = [(feat[c], float(l["rating"])) for c, l in labels.items() if c in feat and l.get("rating")]
    y = np.array([r[1] for r in L])
    col = lambda k: np.array([r[0][k] for r in L], float)
    snr = col("snr")

    print(f"\n{len(L)} clips | rating mean {y.mean():.2f}")
    rsy = np.corrcoef(snr, y)[0, 1]
    print(f"SNR x rating corr: {rsy:+.2f}  "
          f"({'noisier clips rate MORE prayer -> real confound risk' if rsy < -0.1 else 'clean clips not penalized -> low confound risk'})")

    print("\n=== breath vs hiss: partial corr with rating, CONTROLLING for SNR ===")
    for k in ["hnr", "cpps", "h1h2"]:
        raw = np.corrcoef(col(k), y)[0, 1]
        par = pcorr(col(k), y, snr)
        keep = abs(par) > 0.15 and np.sign(par) == np.sign(raw)
        print(f"  {k:6} raw r={raw:+.2f} -> partial(|SNR) r={par:+.2f}  ({'survives' if keep else 'collapses -> was noise'})")

    z = lambda k: col("z_" + k)
    Sa = -(z("f0") + z("rate") + z("loud")) / 3
    Sb = (z("h1h2") - z("cpps") - z("hnr")) / 3          # HNR-inclusive
    Sb_rob = (z("h1h2") - z("cpps")) / 2                  # noise-robust: drop HNR
    zsnr = (snr - snr.mean()) / (snr.std() or 1)

    _, r2a = ols(Sa[:, None], y)
    _, r2ab = ols(np.column_stack([Sa, Sb]), y)
    _, r2abn = ols(np.column_stack([Sa, Sb, zsnr]), y)
    _, r2arob = ols(np.column_stack([Sa, Sb_rob]), y)
    _, r2arobn = ols(np.column_stack([Sa, Sb_rob, zsnr]), y)
    print("\n=== does breathiness survive noise control? (R2) ===")
    print(f"  arousal                          {r2a:.3f}")
    print(f"  + breathy (HNR-incl)             {r2ab:.3f}   (dR2 {r2ab - r2a:+.3f})")
    print(f"  + breathy (HNR-incl) + SNR ctrl  {r2abn:.3f}")
    print(f"  + breathy_ROBUST (H1H2,CPPS)     {r2arob:.3f}   (dR2 {r2arob - r2a:+.3f})")
    print(f"  + breathy_ROBUST + SNR ctrl      {r2arobn:.3f}")

    _, r2base = ols(np.column_stack([Sa, zsnr]), y)
    _, r2full = ols(np.column_stack([Sa, zsnr, Sb_rob]), y)
    dR = r2full - r2base
    rng = np.random.default_rng(1337)
    null = [ols(np.column_stack([Sa, zsnr, rng.permutation(Sb_rob)]), y)[1] - r2base for _ in range(5000)]
    p = (1 + sum(x >= dR for x in null)) / (1 + len(null))
    print(f"\n  noise-robust breathy, incremental over (arousal + SNR): dR2={dR:+.3f}, perm p={p:.3f}")
    print("  -> " + ("BREATH, not hiss: robust breathiness (H1-H2 + CPPS) predicts your ear even after removing recording SNR."
                     if dR > 0.03 and p < 0.10 else
                     "collapses under noise control -> the earlier signal was largely recording noise, not phonation."))


if __name__ == "__main__":
    main()
