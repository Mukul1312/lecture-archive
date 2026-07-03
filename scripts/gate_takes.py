"""
gate_takes.py — the auto-reject stage of the voice-clone funnel (replaces hit-and-trial listening).

For every generated take it runs three automatic gates so the human ear only ever judges survivors:
  1. HALLUCINATION  — Whisper-transcribe (stable-ts); flag takes that are OUTLIERS in duration or
                      word-count vs the other seeds of the SAME sentence (laughs / repeats / extra
                      words make a take longer than its siblings). Robust to Sanskrit mis-ASR because
                      it compares within-sentence, not against an absolute transcript.
  2. IDENTITY       — ECAPA cosine to his real-voice centroid; flag takes well below the batch (the
                      "didn't sound like GGSM" ones).
  3. REGISTER (rank)— the graveness/calmness recipe (low pitch·narrow range·quiet·slow), centred
                      within sentence; ranks the SURVIVORS, gravest/calmest first.

Then it cross-checks its verdicts against the user's hand notes to prove the gates reproduce the
ear. Local, free, no pod.
  .venv/Scripts/python.exe scripts/gate_takes.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
import stable_whisper

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_graveness as bg                     # feats() = pitch/range/loud/rate

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/lecture1/pretest"
FINAL = ROOT / "data/out/lecture1/final"
sys.stdout.reconfigure(encoding="utf-8")

# the ACTUAL text fed to the model (from cloud/infer_pretest.py) — for the WER gate
EXPECT = {
    "date": "May eighth, nineteen seventy five, Thursday.",
    "vow": "This servant took a vow not to eat anything at night except a little maha water with Tulasi.",
    "iskcon": "To open an ISKCON centre in Odisha.",
    "prema": "For receiving complete and uninterrupted Krishna prema.",
    "prasadam": "He will not accept any Prasadam at night.",
    "lila": "But what an astonishing leela You are performing.",
    "sannyasi": "This servant did not desire to perform such type of severe austerity in front of a sannyasi present here.",
    "gopala": "Oh my Lord, Gopala! Please shower Your mercy.",
    "gauranga": "May this servant achieve success in the service of Sri Sri Guru and Gauranga. Hare Krishna.",
}


def wer(ref, hyp):
    """word-level edit distance / reference length (crude, dependency-free)."""
    r = re.findall(r"[a-z]+", ref.lower())
    h = re.findall(r"[a-z]+", hyp.lower())
    if not r:
        return 0.0
    d = np.zeros((len(r) + 1, len(h) + 1))
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r), len(h)] / len(r)


def trailing_artifact(wav_path):
    """Detect a short speech burst tacked on after a pause near the end (a laugh / extra word) —
    the 'extra thing at last' the ear catches but transcript length doesn't. Pure numpy RMS-VAD."""
    y, sr = sf.read(str(wav_path), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    frame, hop = int(0.025 * sr), int(0.010 * sr)
    if len(y) < frame * 2:
        return False
    n = 1 + (len(y) - frame) // hop
    rms = np.array([np.sqrt(np.mean(y[i * hop:i * hop + frame] ** 2) + 1e-9) for i in range(n)])
    db = 20 * np.log10(rms + 1e-9)
    thr = max(-38.0, float(np.percentile(db, 10)) + 3.0)
    sil = db < thr
    dur = len(y) / sr
    # silence intervals >= 0.18s -> speech = the complement
    sils, i = [], 0
    while i < n:
        if sil[i]:
            j = i
            while j < n and sil[j]:
                j += 1
            if (j - i) * hop / sr >= 0.18:
                sils.append((i * hop / sr, j * hop / sr))
            i = j
        else:
            i += 1
    speech, prev = [], 0.0
    for s, e in sils:
        if s - prev > 0.05:
            speech.append((prev, s))
        prev = e
    if dur - prev > 0.05:
        speech.append((prev, dur))
    if len(speech) < 2:
        return False
    last, before = speech[-1], speech[-2]
    gap = last[0] - before[1]
    return gap >= 0.30 and (last[1] - last[0]) <= 1.2 and last[0] >= 0.55 * dur
# the user's hand notes -> for validation (what their EAR flagged)
NOTES_HALLUC = {("date", 123), ("vow", 123), ("vow", 7), ("prasadam", 123)}   # laugh/repeat/extra words
NOTES_IDENTITY = {("gopala", 42)}                                             # "didn't sound like GGSM"


def ecapa_centroid():
    import torch, torch.nn.functional as F
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                         savedir=str(ROOT / ".venv/spkrec"), run_opts={"device": "cpu"},
                                         local_strategy=LocalStrategy.COPY)
    eng = set((ROOT / "data/english_words.txt").read_text(encoding="utf-8").split())
    tok = re.compile(r"[a-z']+")
    rows = [json.loads(l) for l in (FINAL / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def ef(t):
        w = tok.findall(t.lower())
        return (sum(1 for x in w if x in eng) / len(w)) if w else 0

    from math import gcd
    from scipy.signal import resample_poly

    def embed(p):
        y, sr = sf.read(str(p), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        if sr != 16000:                                  # ECAPA expects 16k; pretest takes are 48k
            g = gcd(sr, 16000)
            y = resample_poly(y, 16000 // g, sr // g).astype("float32")
        w = torch.from_numpy(np.ascontiguousarray(y)).unsqueeze(0)
        return F.normalize(clf.encode_batch(w).squeeze(0).squeeze(0), dim=0)

    sel = [FINAL / "clips" / Path(r["audio"]).name for r in rows
           if 5 <= r.get("duration", 0) <= 12 and ef(r["text"]) >= 0.85]
    ref = F.normalize(torch.stack([embed(p) for p in sel[:20]]).mean(0), dim=0)
    ceil = float(np.mean([float(torch.dot(embed(p), ref)) for p in sel[20:30]]))
    return embed, ref, ceil, (lambda a, b: float(torch.dot(a, b)))


def main():
    print("[1/3] building his ECAPA centroid ...")
    embed, ref, ceil, cos = ecapa_centroid()
    print(f"      his-own ceiling: {ceil:.3f}")

    pat = re.compile(r"(?P<label>\w+)__s(?P<seed>\d+)\.wav")
    cache_p = SRC / "_gate_cache.json"
    if cache_p.exists():
        print("[2/3] loading cached ASR + prosody ...")
        cache = json.loads(cache_p.read_text(encoding="utf-8"))
    else:
        print("[2/3] transcribing + measuring 45 takes (stable-ts tiny, CPU ~4 min) ...")
        model = stable_whisper.load_model("tiny")
        cache = {}
        for p in sorted(SRC.glob("*.wav")):
            if not pat.match(p.name):
                continue
            txt = model.transcribe(str(p), language="en", verbose=None).text.strip()
            cache[p.name] = dict(asr=txt, asr_words=len(txt.split()), **bg.feats(p))
        cache_p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    takes = []
    for p in sorted(SRC.glob("*.wav")):
        m = pat.match(p.name)
        if not m or p.name not in cache:
            continue
        takes.append(dict(label=m["label"], seed=int(m["seed"]),
                          ecapa=round(cos(embed(p), ref), 3), **cache[p.name]))

    # --- gate 1: hallucination = within-sentence duration / word-count outlier ---
    for key in ("dur", "asr_words"):
        med = {}
        by = defaultdict(list)
        for t in takes:
            by[t["label"]].append(t[key])
        med = {lab: float(np.median(v)) for lab, v in by.items()}
        for t in takes:
            t[f"{key}_ratio"] = t[key] / med[t["label"]] if med[t["label"]] else 1.0
    for t in takes:
        t["wer"] = round(wer(EXPECT[t["label"]], t["asr"]), 2)
    # --- gate 1 (HIGH-PRECISION hard reject): empty output, or a gross length outlier (stutter/repeat) ---
    for t in takes:
        t["halluc"] = (t["asr_words"] == 0 or t["dur_ratio"] >= 1.33)
    # --- gate 2: identity = ECAPA well below the batch ---
    surv = [t for t in takes if not t["halluc"]] or takes
    ev = np.array([t["ecapa"] for t in surv])
    id_thr = max(0.40, float(np.mean(ev) - 1.3 * np.std(ev)))
    for t in takes:
        t["identity_fail"] = t["ecapa"] < id_thr
    # --- advisory WARN (NOT a reject): garbled text or a possible tacked-on end — the ear confirms ---
    for t in takes:
        t["warn"] = (not t["halluc"] and not t["identity_fail"]
                     and (t["wer"] >= 0.80 or trailing_artifact(SRC / f"{t['label']}__s{t['seed']}.wav")))

    # --- gate 3: register rank among survivors (graveness, centred within sentence) ---
    for key in ("f0", "spread", "loud", "rate"):
        by = defaultdict(list)
        for t in takes:
            by[t["label"]].append(t[key])
        mean = {lab: float(np.mean(v)) for lab, v in by.items()}
        devs = [t[key] - mean[t["label"]] for t in takes]
        sd = float(np.std(devs)) or 1.0
        for t, d in zip(takes, devs):
            t[f"z_{key}"] = d / sd
    for t in takes:
        t["grave"] = round(-(t["z_f0"] + t["z_spread"] + t["z_loud"] + t["z_rate"]) / 4, 3)
        t["verdict"] = ("REJECT-halluc" if t["halluc"] else
                        "REJECT-identity" if t["identity_fail"] else "keep")

    # --- report ---
    print(f"\n[3/3] identity threshold {id_thr:.3f}  (his ceiling {ceil:.3f})\n")
    print("=== per-sentence: gates + register rank (survivors ranked calm-first) ===")
    for lab in EXPECT:
        grp = sorted([t for t in takes if t["label"] == lab], key=lambda t: (t["verdict"] != "keep", -t["grave"]))
        print(f"\n  ▶ {lab}")
        for t in grp:
            tag = {"keep": "  keep   ", "REJECT-halluc": "✗ gross  ", "REJECT-identity": "✗ ident  "}[t["verdict"]]
            wn = "⚠warn" if t.get("warn") else "     "
            print(f"    seed {t['seed']:<5} {tag} grave {t['grave']:+.2f}  dur {t['dur']:4.1f}s(x{t['dur_ratio']:.2f})  "
                  f"ecapa {t['ecapa']:.2f}  wer {t['wer']:.2f} {wn}  \"{t['asr'][:38]}\"")

    # --- validation vs the user's own ear ---
    hard = {(t["label"], t["seed"]) for t in takes if t["verdict"] != "keep"}
    warned = {(t["label"], t["seed"]) for t in takes if t.get("warn")}
    clean = [t for t in takes if t["verdict"] == "keep" and not t.get("warn")]
    print("\n=== VALIDATION vs your ear ===")
    print(f"  identity note {sorted(NOTES_IDENTITY)}  ->  hard-caught: {sorted(NOTES_IDENTITY & hard)}")
    print(f"  hallucination notes {sorted(NOTES_HALLUC)}:")
    print(f"    hard-rejected      : {sorted(NOTES_HALLUC & hard)}")
    print(f"    advisory-warned    : {sorted(NOTES_HALLUC & warned)}   (flagged for your ear, not auto-killed)")
    print(f"    slipped past both  : {sorted(NOTES_HALLUC - hard - warned)}   (subtle end-artifacts — ear-only)")
    print(f"\n  → hard-removed {len(hard)}/{len(takes)} (identity + gross failures) · warned {len(warned)} · "
          f"your ear now reviews {len(clean)} clean, register-ranked takes instead of {len(takes)}.")


if __name__ == "__main__":
    main()
