"""
verify_identity.py — is the identity claim ROBUST, or one lucky metric?

A single metric (ECAPA) saying "near his ceiling" is not proof. This re-tests the clone's speaker
identity with TWO independent encoders of DIFFERENT architecture:
    ECAPA-TDNN   (speechbrain/spkrec-ecapa-voxceleb)   — attention + channel aggregation
    d-vector     (Resemblyzer GE2E, LSTM)              — a totally separate lineage
For each encoder it establishes the scale — FLOOR (architecture chance level), his-own CEILING
(held-out real clips vs a centroid built from OTHER real clips), and places the CLONE (champion c150,
seen vs UNSEEN sentences) between them, mean±std. If BOTH encoders agree the clone sits near the
ceiling, identity is robustly solved; if they diverge, it isn't.

The two libraries conflict in one process, so each encoder runs in its OWN process:
  .venv/Scripts/python.exe scripts/verify_identity.py --enc ecapa
  .venv/Scripts/python.exe scripts/verify_identity.py --enc dvector
  .venv/Scripts/python.exe scripts/verify_identity.py --enc report
"""
import argparse, json, re, sys, types
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data/out/lecture1/final"
CLIPS = FINAL / "clips"
EVAL = ROOT / "data/out/lecture1/eval"
OUTD = ROOT / "data/out/lecture1"
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


def real_clip_names():
    eng = set((ROOT / "data/english_words.txt").read_text(encoding="utf-8").split())
    tok = re.compile(r"[a-z']+")
    rows = [json.loads(l) for l in (FINAL / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def ef(t):
        w = tok.findall(t.lower())
        return (sum(1 for x in w if x in eng) / len(w)) if w else 0
    return [Path(r["audio"]).name for r in rows if 5 <= r.get("duration", 0) <= 12 and ef(r["text"]) >= 0.85]


def compute(enc):
    reals = real_clip_names()
    cen_names, ceil_names = reals[:20], reals[20:40]
    champ_unseen = sorted(EVAL.glob("c150__nv*.wav"))
    champ_seen = sorted(EVAL.glob("c150__nm*.wav"))
    embed = build_ecapa() if enc == "ecapa" else build_dvector()
    print(f"[{enc}] embedding {len(cen_names)}+{len(ceil_names)} real, "
          f"{len(champ_unseen)}+{len(champ_seen)} clone ...")
    E = np.stack([embed(CLIPS / n) for n in cen_names])
    cen = E.mean(0); cen /= (np.linalg.norm(cen) + 1e-9)
    dot = lambda p: float(np.dot(embed(p), cen))
    ceil = [dot(CLIPS / n) for n in ceil_names]
    rng = np.random.default_rng(0).standard_normal((200, cen.shape[0]))
    rng /= np.linalg.norm(rng, axis=1, keepdims=True)
    floor = float(np.mean(rng @ cen))
    unseen = [dot(p) for p in champ_unseen]
    seen = [dot(p) for p in champ_seen]
    res = dict(enc=enc, floor=floor, ceil=ceil, unseen=unseen, seen=seen)
    (OUTD / f"idcheck_{enc}.json").write_text(json.dumps(res), encoding="utf-8")
    print(f"[{enc}] floor {floor:.3f} · clone-unseen {np.mean(unseen):.3f} · ceiling {np.mean(ceil):.3f}  -> saved")


def report():
    import numpy as np
    got = {}
    for enc in ("ecapa", "dvector"):
        f = OUTD / f"idcheck_{enc}.json"
        if f.exists():
            got[enc] = json.loads(f.read_text(encoding="utf-8"))
    if not got:
        sys.exit("no idcheck_*.json yet — run --enc ecapa and --enc dvector first")
    name = {"ecapa": "ECAPA-TDNN", "dvector": "d-vector GE2E"}
    print("\n" + "=" * 78)
    print("IDENTITY ROBUSTNESS — two independent encoders (clone = champion c150, UNSEEN)")
    print("=" * 78)
    print(f"{'encoder':<15} {'floor':>7} {'clone UNSEEN':>16} {'clone seen':>14} {'his CEILING':>15}")
    for enc, r in got.items():
        u, s, c = np.array(r["unseen"]), np.array(r["seen"]), np.array(r["ceil"])
        us = f"{u.mean():.3f}±{u.std():.3f}" if u.size else "n/a"
        ss = f"{s.mean():.3f}±{s.std():.3f}" if s.size else "n/a"
        cs = f"{c.mean():.3f}±{c.std():.3f}"
        print(f"{name[enc]:<15} {r['floor']:>7.3f} {us:>16} {ss:>14} {cs:>15}")
    print("\n=== clone vs his own ceiling (UNSEEN — the honest, overfitting-clean number) ===")
    verdicts = []
    for enc, r in got.items():
        u, c, fl = np.array(r["unseen"]), np.array(r["ceil"]), r["floor"]
        gap = c.mean() - u.mean()
        span = c.mean() - fl
        pct = 100 * (u.mean() - fl) / span if span else 0
        verdicts.append(pct)
        print(f"  {name[enc]:<15} clone {u.mean():.3f} vs ceiling {c.mean():.3f}  "
              f"gap {gap:+.3f}  ->  {pct:.0f}% of the way floor→ceiling")
    if len(verdicts) == 2:
        agree = "AGREE" if abs(verdicts[0] - verdicts[1]) < 20 else "DISAGREE"
        print(f"\n  Two independent encoders {agree} on where the clone sits "
              f"({verdicts[0]:.0f}% vs {verdicts[1]:.0f}% of span).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enc", required=True, choices=["ecapa", "dvector", "report"])
    args = ap.parse_args()
    if args.enc == "report":
        report()
    else:
        compute(args.enc)


if __name__ == "__main__":
    main()
