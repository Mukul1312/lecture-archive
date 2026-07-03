"""
build_calibrate_clone.py — the CLEAN re-run of the register calibration, on CLONE audio instead of
noisy source clips.

Why cleaner: clone takes are synthesized (no recording hiss) AND all first-person prayer text
(valence held constant), so any 'prayer' rating variation is pure DELIVERY. This removes the SNR
confound that contaminated the source-clip calibration (noisier clips there rated as more prayer).

Computes prosody + voice-quality + SNR on the GGS diary takes (chunks 04-23, clean LoRA voice; up to
SEEDS_PER_CHUNK seeds each), CONFIRMS the confound is broken (SNR uniform + decorrelated from
breathiness), then builds the same blind 3x3-decorrelated rating gallery -> voice_lab/calibrate_clone/.
Run: .venv/Scripts/python.exe scripts/build_calibrate_clone.py   (--recompute to refresh the cache)
"""
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graveness import feats as prosody_feats
from voice_quality import vq_feats
from spectral_inspect import analyze, load
from build_calibrate import zscore, stratified_sample, TEMPLATE

SRC = ROOT / "data/out/lecture1/diary"
OUTD = ROOT / "data/out/lecture1/calibrate"
FEAT = OUTD / "features_clone.json"
GAL = ROOT / "voice_lab" / "calibrate_clone"
AUD = GAL / "audio"
N_LABEL = 36
SEEDS_PER_CHUNK = 10          # subsample seeds/chunk to keep compute reasonable while spanning delivery


def compute(recompute=False):
    if FEAT.exists() and not recompute:
        return json.loads(FEAT.read_text(encoding="utf-8"))
    OUTD.mkdir(parents=True, exist_ok=True)
    by_chunk = defaultdict(list)
    for p in sorted(SRC.glob("*.wav")):
        if p.stem[:2].isdigit() and 4 <= int(p.stem[:2]) <= 23:   # chunks 04-23 = GGS first-person prayer
            by_chunk[p.stem[:2]].append(p)
    takes = [p for ch in sorted(by_chunk) for p in by_chunk[ch][:SEEDS_PER_CHUNK]]
    rows = []
    for i, p in enumerate(takes, 1):
        g = prosody_feats(p)
        vq = vq_feats(p)
        a = analyze(load(p))
        rows.append(dict(clip=p.stem, f0=g["f0"], spread=g["spread"], loud=g["loud"], rate=g["rate"],
                         cpps=vq["cpps"], hnr=vq["hnr"], alpha_std=vq["alpha_std"],
                         hammarberg=vq["hammarberg"], h1h2=vq["h1h2"], snr=a["snr"], floor=a["floor"]))
        if i % 40 == 0:
            print(f"  features {i}/{len(takes)}", file=sys.stderr)
    FEAT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"cached {len(rows)} clone-take features -> {FEAT}")
    return rows


def main():
    rows = zscore(compute(recompute="--recompute" in sys.argv))
    snr = np.array([r["snr"] for r in rows])
    Sb = np.array([r["S_breathy"] for r in rows])
    Sa = np.array([r["S_arousal"] for r in rows])
    print("\n=== CONFOUND CHECK: is the clone audio clean + decorrelated from breathiness? ===")
    print(f"  SNR: mean {snr.mean():.1f} dB, range {snr.min():.1f}..{snr.max():.1f} dB   (source clips were noisier + more variable)")
    print(f"  corr(SNR, S_breathy) = {np.corrcoef(snr, Sb)[0, 1]:+.2f}   "
          f"({'near 0 -> confound FIXED, breath is separable from noise here' if abs(np.corrcoef(snr, Sb)[0, 1]) < 0.3 else 'WARN still correlated'})")
    print(f"  corr(SNR, S_arousal) = {np.corrcoef(snr, Sa)[0, 1]:+.2f}")

    sample = stratified_sample(rows, n=N_LABEL)
    a = np.array([r["S_arousal"] for r in sample]); b = np.array([r["S_breathy"] for r in sample])
    corr = float(np.corrcoef(a, b)[0, 1]); vif = 1.0 / max(1e-6, 1 - corr ** 2)
    print(f"\nsample: {len(sample)} clone takes | S_arousal x S_breathy corr {corr:+.2f} (VIF {vif:.1f}) "
          f"{'-> separable' if vif < 2.5 else '-> collinear'}")

    if GAL.exists():
        shutil.rmtree(GAL)
    AUD.mkdir(parents=True, exist_ok=True)
    items = []
    for i, r in enumerate(sample, 1):
        shutil.copyfile(SRC / f"{r['clip']}.wav", AUD / f"c{i:02d}.wav")
        items.append(dict(n=i, clip=r["clip"], url=f"audio/c{i:02d}.wav"))
    (GAL / "index.html").write_text(
        TEMPLATE.replace("/*__DATA__*/", json.dumps(items, ensure_ascii=False)), encoding="utf-8")
    print(f"wrote {GAL/'index.html'}  ({len(items)} clone takes to label)")
    print("\nNEXT: open http://localhost:8000/calibrate_clone/ , rate all, Export -> save as")
    print("      data/out/lecture1/calibrate/labels_clone.json , then I run the clean analysis")


if __name__ == "__main__":
    main()
