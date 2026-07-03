"""
ref_denoise_ab.py — decide whether to swap the diary's reference clip to its denoised copy.

The diary conditions on the NOISY clips/ggs_l1_0001.wav; a denoised copy clips_dn/ggs_l1_0001.wav
already exists. The survey's warning: reference-denoise is CLIP-DEPENDENT (helped 0081 +0.033, hurt
0112 -0.063), so we MEASURE both axes for THIS clip before switching:
  - NOISE:    spectral floor + band-shape (how much cleaner is the denoised reference?)
  - IDENTITY: ECAPA cosine of each ref to his centroid, and cos(noisy, denoised) directly.

librosa (spectral) and speechbrain (ECAPA) crash if imported together — librosa's warning stack-walk
pokes speechbrain's broken lazy modules. So each half runs in its OWN subprocess; the runner combines.

Run: .venv/Scripts/python.exe scripts/ref_denoise_ab.py
"""
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
REFS = {
    "noisy": ROOT / "data/out/lecture1/final/clips/ggs_l1_0001.wav",
    "denoised": ROOT / "data/out/lecture1/final/clips_dn/ggs_l1_0001.wav",
}
TAG = "RESULT_JSON:"


def _spectral():
    sys.path.insert(0, str(ROOT / "scripts"))
    from spectral_inspect import analyze, load
    out = {k: {kk: vv for kk, vv in analyze(load(p)).items() if kk in ("floor", "snr", "frac")}
           for k, p in REFS.items()}
    print(TAG + json.dumps(out))


def _ecapa():
    sys.path.insert(0, str(ROOT / "scripts"))
    import gate_takes as gt
    embed, centroid, ceil, cos = gt.ecapa_centroid()
    e = {k: embed(p) for k, p in REFS.items()}
    out = dict(ceil=float(ceil),
               noisy_id=float(cos(e["noisy"], centroid)),
               denoised_id=float(cos(e["denoised"], centroid)),
               cross=float(cos(e["noisy"], e["denoised"])))
    print(TAG + json.dumps(out))


def _dual():
    """Confound-free identity: score 0001 (noisy+denoised) against BOTH a noisy and a denoised centroid.
    If denoised-0001 vs denoised-centroid ~ ceiling, the -0.177 vs the noisy centroid was a NOISE confound."""
    import json as _json
    import re
    from math import gcd

    import numpy as np
    import torch
    import torch.nn.functional as F
    import soundfile as sf
    from scipy.signal import resample_poly
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    FINAL = ROOT / "data/out/lecture1/final"
    clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                         savedir=str(ROOT / ".venv/spkrec"), run_opts={"device": "cpu"},
                                         local_strategy=LocalStrategy.COPY)

    def embed(p):
        y, sr = sf.read(str(p), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        if sr != 16000:
            g = gcd(sr, 16000)
            y = resample_poly(y, 16000 // g, sr // g).astype("float32")
        import numpy as _np
        w = torch.from_numpy(_np.ascontiguousarray(y)).unsqueeze(0)
        return F.normalize(clf.encode_batch(w).squeeze(0).squeeze(0), dim=0)

    eng = set((ROOT / "data/english_words.txt").read_text(encoding="utf-8").split())
    tok = re.compile(r"[a-z']+")

    def ef(t):
        w = tok.findall(t.lower())
        return (sum(1 for x in w if x in eng) / len(w)) if w else 0

    rows = [_json.loads(l) for l in (FINAL / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    names = [Path(r["audio"]).name for r in rows if 5 <= r.get("duration", 0) <= 12 and ef(r["text"]) >= 0.85]
    cen, cei = names[:20], names[20:30]

    def centroid(sub):
        return F.normalize(torch.stack([embed(FINAL / sub / n) for n in cen]).mean(0), dim=0)

    cN, cD = centroid("clips"), centroid("clips_dn")
    ceilN = float(np.mean([float(torch.dot(embed(FINAL / "clips" / n), cN)) for n in cei]))
    ceilD = float(np.mean([float(torch.dot(embed(FINAL / "clips_dn" / n), cD)) for n in cei]))
    n0, d0 = embed(REFS["noisy"]), embed(REFS["denoised"])
    out = dict(ceilN=ceilN, ceilD=ceilD,
               n0_cN=float(torch.dot(n0, cN)), n0_cD=float(torch.dot(n0, cD)),
               d0_cN=float(torch.dot(d0, cN)), d0_cD=float(torch.dot(d0, cD)))
    print(TAG + json.dumps(out))


def _run(mode):
    r = subprocess.run([sys.executable, __file__, mode], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith(TAG):
            return json.loads(line[len(TAG):])
    sys.exit(f"[{mode}] failed:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")


def main():
    for k, p in REFS.items():
        if not p.exists():
            sys.exit(f"missing {k}: {p}")
    print("[spectral] measuring noise (subprocess) ...")
    sp = _run("spectral")
    print("[ecapa] measuring identity (subprocess) ...")
    ec = _run("ecapa")

    print(f"\n{'reference':22s} {'floor':>7s} {'SNR':>6s} {'ECAPA→centroid':>15s}   noise-shape")
    print("-" * 90)
    for k, idk in (("noisy", "noisy_id"), ("denoised", "denoised_id")):
        s = sp[k]
        shape = " ".join(f"{kk}={vv:.0%}" for kk, vv in s["frac"].items())
        print(f"{k:22s} {s['floor']:7.1f} {s['snr']:6.1f} {ec[idk]:15.3f}   {shape}")

    dfloor = sp["denoised"]["floor"] - sp["noisy"]["floor"]
    did = ec["denoised_id"] - ec["noisy_id"]
    print(f"\nceiling (his clip-to-clip ECAPA): {ec['ceil']:.3f}")
    print(f"noise floor change (denoised - noisy): {dfloor:+.1f} dB   (negative = quieter = better)")
    print(f"identity change to centroid (denoised - noisy): {did:+.3f}   (bar: -0.03)")
    print(f"cos(noisy, denoised) for this clip: {ec['cross']:.3f}   (1.0 = denoise didn't move identity)")

    verdict = "IDENTITY SAFE" if did >= -0.03 else "IDENTITY RISK"
    noise = "cleaner" if dfloor < -2 else ("≈ same" if abs(dfloor) <= 2 else "NOISIER")
    print(f"\nVERDICT (naive, vs NOISY centroid): {verdict} · noise {noise}")

    print("\n[dual-centroid] disentangling the noise confound (subprocess) ...")
    dl = _run("dual")
    print(f"\n{'':22s} {'vs NOISY-centroid':>18s} {'vs DENOISED-centroid':>21s}")
    print("-" * 64)
    print(f"{'noisy 0001':22s} {dl['n0_cN']:18.3f} {dl['n0_cD']:21.3f}")
    print(f"{'denoised 0001':22s} {dl['d0_cN']:18.3f} {dl['d0_cD']:21.3f}")
    print(f"{'(ceiling)':22s} {dl['ceilN']:18.3f} {dl['ceilD']:21.3f}")
    # apples-to-apples: each ref vs ITS OWN-domain centroid, relative to that domain's ceiling
    fair = dl["d0_cD"] - dl["n0_cN"]
    print(f"\nCONFOUND-FREE identity (denoised-0001 vs denoised-centroid): {dl['d0_cD']:.3f} "
          f"(that domain's ceiling {dl['ceilD']:.3f})")
    print(f"apples-to-apples Δ (each ref vs its own-domain centroid): {fair:+.3f}   (bar: -0.03)")
    if dl["d0_cD"] >= dl["ceilD"] - 0.03:
        print("=> The -0.177 was a NOISE CONFOUND. Denoised ref keeps SPEAKER identity in-domain "
              "→ downstream is likely clean AND identity-safe. Proceed to the decisive pod A/B.")
    else:
        print("=> Real identity movement survives the confound fix → prefer a GENTLER clean "
              "(high-pass the rumble) over the aggressive denoise. Test both downstream.")
    print("\nDECISIVE next: generate GGS takes with each ref (same seeds), compare OUTPUT noise + identity.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "spectral":
        _spectral()
    elif mode == "ecapa":
        _ecapa()
    elif mode == "dual":
        _dual()
    else:
        main()
