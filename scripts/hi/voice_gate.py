"""
voice_gate.py — the DISSIMILARITY gate for the voice pivot (2026-07-10).

Same machinery as verify_identity.py, sign flipped. There we asked "is the clone close enough to
him?"; here we must prove a candidate narration voice is FAR ENOUGH from him. A candidate is
eligible only if BOTH independent encoders place it clearly below his cross-lecture ceiling.

Two anchors make the number mean something:
  HIS CEILING  — his lecture-03/04 clips vs a centroid built from lectures 01+02. This is "him on a
                 different day/recording": the score a true match produces. Building centroid and
                 ceiling from DIFFERENT lectures also kills caveat C3 (single-lecture circularity)
                 in research/docs/voice-cloning/identity-verification.md.
  CHANCE FLOOR — random unit vectors (~0). Documented as OPTIMISTIC (caveat C2): a real different
                 Indian male speaker scores well above chance, so % -of-span against this floor
                 flatters any candidate. Read the RAW cosine vs the ceiling, not the percentage.

Hindi centroid (not the English lecture-1 one in ecapa_score.py) so candidates are scored in the
same language they'll be judged in — cross-language embedding drift would confound the gate.

The two libraries conflict in one process, so each encoder runs in its OWN:
  .venv/Scripts/python.exe scripts/hi/voice_gate.py --enc ecapa
  .venv/Scripts/python.exe scripts/hi/voice_gate.py --enc dvector
  .venv/Scripts/python.exe scripts/hi/voice_gate.py --enc report
Add candidates with --cand LABEL=path/to.wav (repeatable); defaults to the VoxCPM2 base voices.
"""
import argparse, json, sys, types
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent.parent.parent
LECTURES = ROOT / "data/hi/lectures"               # per-lecture clips_hi/ + train_hi.jsonl
OUTD = ROOT / "data/hi/voice_gate"
# train_final/ is lecture-01 ONLY, so the cross-lecture split reads the per-lecture manifests.
CENTROID_LECTURES = ("ggm-hindi-lecture-01", "ggm-hindi-lecture-02")   # his reference from these ...
CEILING_LECTURES = ("ggm-hindi-lecture-03", "ggm-hindi-lecture-04")    # ... "him on another day" from these
DEFAULT_CANDS = {
    "VoxCPM2 base (hi)": ROOT / "data/hi/base_samples/base_hi.wav",
    "VoxCPM2 base (en)": ROOT / "data/hi/base_samples/base_en.wav",
}
sys.stdout.reconfigure(encoding="utf-8")


def load16k(p):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    if sr != 16000:
        g = gcd(sr, 16000)
        y = resample_poly(y, 16000 // g, sr // g).astype("float32")
    return y


def build_ecapa():
    import torch
    import torch.nn.functional as F
    sys.modules.setdefault("k2", types.ModuleType("k2"))
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                         savedir=str(ROOT / ".venv/spkrec"), run_opts={"device": "cpu"},
                                         local_strategy=LocalStrategy.COPY)

    @torch.no_grad()
    def embed(p):
        w = torch.from_numpy(np.ascontiguousarray(load16k(p))).unsqueeze(0)
        return F.normalize(clf.encode_batch(w).squeeze(0).squeeze(0), dim=0).cpu().numpy()
    return embed


def build_dvector():
    from resemblyzer import VoiceEncoder, preprocess_wav
    enc = VoiceEncoder(verbose=False)

    def embed(p):
        v = enc.embed_utterance(preprocess_wav(str(p)))
        return v / (np.linalg.norm(v) + 1e-9)
    return embed


def his_clips(lectures, lo=4.0, hi=12.0):
    """His real Hindi clips from the given lectures, long enough to embed reliably.

    Per-lecture manifests carry no duration field, so length comes from the wav header.
    """
    out = []
    for lec in lectures:
        man = LECTURES / lec / "train_hi.jsonl"
        if not man.exists():
            continue
        for line in man.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            p = LECTURES / lec / json.loads(line)["audio"]
            if p.exists() and lo <= sf.info(str(p)).duration <= hi:
                out.append(p)
    return sorted(out)


def compute(enc, cands, floor_dir=None):
    cen_paths, ceil_paths = his_clips(CENTROID_LECTURES), his_clips(CEILING_LECTURES)
    if not cen_paths or not ceil_paths:
        sys.exit(f"need clips in both {CENTROID_LECTURES} and {CEILING_LECTURES}; "
                 f"got {len(cen_paths)} and {len(ceil_paths)}")
    embed = build_ecapa() if enc == "ecapa" else build_dvector()
    print(f"[{enc}] centroid {len(cen_paths)} clips ({'+'.join(CENTROID_LECTURES)}) · "
          f"ceiling {len(ceil_paths)} clips ({'+'.join(CEILING_LECTURES)}) · {len(cands)} candidates ...")

    E = np.stack([embed(p) for p in cen_paths])
    cen = E.mean(0); cen /= (np.linalg.norm(cen) + 1e-9)
    dot = lambda p: float(np.dot(embed(p), cen))

    ceil = [dot(p) for p in ceil_paths]
    rnd = np.random.default_rng(0).standard_normal((200, cen.shape[0]))
    rnd /= np.linalg.norm(rnd, axis=1, keepdims=True)
    floor = float(np.mean(rnd @ cen))

    scored = {}
    for label, p in cands.items():
        if not Path(p).exists():
            print(f"  (missing {p})")
            continue
        scored[label] = dot(Path(p))

    # REAL-speaker floor: other male Hindi speakers vs his centroid. This is the calibration that
    # turns the gate from relative evidence into a decision band (caveat C2 in identity-verification.md).
    real_floor = {}
    if floor_dir:
        wavs = sorted(Path(floor_dir).glob("*.wav"))
        if not wavs:
            print(f"  (no .wav under {floor_dir})")
        for w in wavs:
            real_floor[w.stem] = dot(w)   # one clip per DISTINCT speaker — dedupe upstream
        if real_floor:
            v = np.array(list(real_floor.values()))
            print(f"  real-speaker floor: n={len(v)} mean {v.mean():.3f} sd {v.std():.3f} "
                  f"min {v.min():.3f} max {v.max():.3f}")

    OUTD.mkdir(parents=True, exist_ok=True)
    res = dict(enc=enc, floor=floor, ceil=ceil, cands=scored, real_floor=real_floor,
               n_centroid=len(cen_paths), n_ceiling=len(ceil_paths))
    (OUTD / f"gate_{enc}.json").write_text(json.dumps(res), encoding="utf-8")
    print(f"[{enc}] floor {floor:.3f} · his cross-lecture ceiling {np.mean(ceil):.3f}±{np.std(ceil):.3f} -> saved")
    for label, c in sorted(scored.items(), key=lambda kv: kv[1]):
        print(f"        {c:.3f}  {label}")


def report():
    got = {}
    for enc in ("ecapa", "dvector"):
        f = OUTD / f"gate_{enc}.json"
        if f.exists():
            got[enc] = json.loads(f.read_text(encoding="utf-8"))
    if not got:
        sys.exit("no gate_*.json yet — run --enc ecapa and --enc dvector first")
    name = {"ecapa": "ECAPA-TDNN", "dvector": "d-vector GE2E"}

    print("\n" + "=" * 78)
    print("VOICE DISSIMILARITY GATE — candidate must sit FAR BELOW his ceiling, on BOTH encoders")
    print("=" * 78)
    print(f"{'encoder':<15} {'chance':>8} {'REAL-speaker floor':>22} {'HIS ceiling (x-lect)':>22}")
    for enc, r in got.items():
        c = np.array(r["ceil"])
        rf = np.array(list(r.get("real_floor", {}).values()))
        rfs = f"{rf.mean():.3f}±{rf.std():.3f} (n={rf.size})" if rf.size else "NOT MEASURED"
        print(f"{name[enc]:<15} {r['floor']:>8.3f} {rfs:>22} {f'{c.mean():.3f}±{c.std():.3f}':>22}")

    labels = sorted({l for r in got.values() for l in r["cands"]})
    if not labels:
        print("\n(no candidates scored)")
        return
    print(f"\n{'candidate':<26} " + " ".join(f"{name[e]:>15}" for e in got) + "   verdict")
    calibrated = all(r.get("real_floor") for r in got.values())
    for label in labels:
        cells, zs = [], []
        for enc, r in got.items():
            v = r["cands"].get(label)
            cells.append(f"{v:>15.3f}" if v is not None else f"{'n/a':>15}")
            rf = np.array(list(r.get("real_floor", {}).values()))
            if v is not None and rf.size >= 5 and rf.std() > 1e-6:
                zs.append((v - rf.mean()) / rf.std())
        # z = how far ABOVE a typical different-speaker this candidate sits, in floor SDs.
        # Small/negative -> indistinguishable from any other non-GGSM speaker -> safe.
        verdict = f"  z={max(zs):+.1f} (worst)" if zs else "  UNCALIBRATED"
        print(f"{label:<26} " + " ".join(cells) + verdict)

    print("\nHow to read this:")
    print("  · z = (candidate − real-speaker mean) / real-speaker SD, on the WORST encoder.")
    print("    z <= +1  -> scores like any other different speaker  -> PASS")
    print("    z >= +2  -> drifting toward him, an outlier among strangers -> INVESTIGATE")
    print("  · A candidate near/above HIS ceiling reads as HIM -> disqualified outright.")
    if not calibrated:
        print("  · ⚠ REAL-SPEAKER FLOOR NOT MEASURED (caveat C2). Without it the chance floor (~0)")
        print("    flatters every candidate and no z-score exists. Results are RELATIVE evidence")
        print("    only — not a certified pass. Re-run with --floor DIR_OF_OTHER_SPEAKERS.")
    print("  · Metric != perception. A blind human check remains the final authority (caveat C6).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enc", required=True, choices=["ecapa", "dvector", "report"])
    ap.add_argument("--cand", action="append", default=[], metavar="LABEL=PATH",
                    help="extra candidate wav (repeatable); omit to use the VoxCPM2 base voices")
    ap.add_argument("--floor", metavar="DIR",
                    help="dir of *.wav from OTHER male Hindi speakers, ONE clip per distinct "
                         "speaker — builds the real-speaker floor that calibrates the gate")
    args = ap.parse_args()
    if args.enc == "report":
        report()
        return
    cands = dict(DEFAULT_CANDS)
    for spec in args.cand:
        label, _, path = spec.partition("=")
        if not path:
            sys.exit(f"--cand needs LABEL=PATH, got {spec!r}")
        cands[label] = ROOT / path if not Path(path).is_absolute() else Path(path)
    compute(args.enc, cands, args.floor)


if __name__ == "__main__":
    main()
