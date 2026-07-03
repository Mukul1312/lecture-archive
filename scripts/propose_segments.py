"""
propose_segments.py - pause-driven clip proposer for the resegment.html confirm-pass.

Replaces the discredited ".?!"-punctuation cutter (align_cut.py / pod_dataprep.py) with
boundaries placed at REAL acoustic pauses, plus auto-attached transcript text and a
pre-filled keep/cut suggestion. Output drops straight into resegment.html (which now reads
`text`/`decision`) so a new lecture is a fast CONFIRM pass, not a from-scratch draw.

Signal stack (each an ablation lever):
  V0  gap-only     - cut at the largest INTER-WORD gap in each window (reconstructs the
                     old pause seed that scored ~90% vs the human).
  V1  +RMS-VAD     - measured silence (librosa RMS energy) selects AND snaps the cut to the
                     centre of the real silence, not the ASR gap midpoint.
  V1s +Silero-VAD  - same, neural VAD silences (only if silero-vad importable).
  V2  +prosody     - adds a pitch-reset / final-lowering term (parselmouth F0) so the chosen
                     boundary is a genuine IDEA boundary, not just any silence.

Ablation (default): score every variant's boundaries against a hand-reviewed export
(resegment_export.json) -> boundary-recall @0.2s/@0.3s + independent clip VALIDITY.

Run (ablation on lecture 1):
  .venv/Scripts/python.exe scripts/propose_segments.py --ablate \
      --audio  data/out/lecture1/lecture_full.wav \
      --words  data/lectures/i-and-mine-and-namabhasa-stage/words.json \
      --export data/out/lecture1/resegment_export.json

Emit a proposal for a NEW lecture (best variant -> resegment_proposed.json):
  .venv/Scripts/python.exe scripts/propose_segments.py \
      --audio  data/lectures/<slug>/audio.wav \
      --words  data/lectures/<slug>/words.json \
      --emit   data/out/<slug>/resegment_proposed.json --variant v2
"""
import argparse, json, sys
from pathlib import Path

import numpy as np
import librosa

ROOT = Path(__file__).resolve().parent.parent
EPS = 1e-8

# ---- clip-shape targets (from docs/clip-segmentation-policy.md + the human export) ----
MIN_SEC, MAX_SEC, TARGET_SEC = 5.0, 15.0, 10.5
MAX_INTRA_GAP = 2.2        # a clip may hold a pause up to this; bigger = hard break (verse/skip/alignment loss)
SNAP_WIN = 0.50            # search radius when snapping a cut to measured silence
LEAD, TAIL = 0.15, 0.15    # pad around each clip's speech (clips are TRIMMED, not chained)
EDGE_PAD = 0.10            # extra pad kept when trimming to a VAD speech edge


# --------------------------------------------------------------------------- I/O
def load_words(p):
    w = json.loads(Path(p).read_text(encoding="utf-8"))
    return [x for x in w if x.get("text", "").strip()]


# ----------------------------------------------------------------- silence (VAD)
def rms_silences(y, sr, thr_db=-35.0, min_sil=0.12, frame=400, hop=160):
    """librosa RMS-energy VAD -> list of (start,end) silence intervals + the threshold used."""
    rms = librosa.feature.rms(y=y, frame_length=frame, hop_length=hop)[0]
    db = 20.0 * np.log10(np.maximum(rms, EPS))
    thr = max(thr_db, float(np.percentile(db, 10)) + 3.0)   # never dip below the noise floor
    sil = db < thr
    t = librosa.frames_to_time(np.arange(len(db)), sr=sr, hop_length=hop)
    ints, i, n = [], 0, len(sil)
    while i < n:
        if sil[i]:
            j = i
            while j < n and sil[j]:
                j += 1
            t0, t1 = float(t[i]), float(t[j - 1] + hop / sr)
            if t1 - t0 >= min_sil:
                ints.append((t0, t1))
            i = j
        else:
            i += 1
    return ints, thr


def silero_silences(y, sr=16000, min_sil=0.12):
    """Neural VAD -> silence intervals = complements of speech. None if silero unavailable.
    Takes the already-loaded array (avoids torchaudio/torchcodec I/O)."""
    try:
        import torch
        from silero_vad import load_silero_vad, get_speech_timestamps
    except Exception:
        return None
    try:
        model = load_silero_vad()
        wav = torch.from_numpy(np.ascontiguousarray(y, dtype=np.float32))
        speech = get_speech_timestamps(wav, model, sampling_rate=sr, return_seconds=True)
    except Exception as e:
        print(f"[vad ] silero skipped: {e}")
        return None
    sil, prev = [], 0.0
    for sp in speech:
        if sp["start"] - prev >= min_sil:
            sil.append((prev, sp["start"]))
        prev = sp["end"]
    dur = len(y) / sr
    if dur - prev >= min_sil:
        sil.append((prev, dur))
    return sil


def sil_overlap(g0, g1, sils):
    return sum(max(0.0, min(g1, e) - max(g0, s)) for s, e in sils)


def snap(t, sils, win=SNAP_WIN):
    """Snap a cut time to the centre of the silence that contains it (or the nearest within win)."""
    best, bd = None, win
    for s, e in sils:
        if s <= t <= e:
            return (s + e) / 2.0, True
        d = min(abs(t - s), abs(t - e))
        if d < bd:
            bd, best = d, (s + e) / 2.0
    return (best if best is not None else t), (best is not None)


def speech_onset(t, sils, win=0.6):
    """VAD speech onset near a word start = end of the silence just before t (or None)."""
    best = None
    for s, e in sils:
        if t - win <= e <= t + 0.15 and (best is None or e > best):
            best = e
    return best


def speech_offset(t, sils, win=0.6):
    """VAD speech offset near a word end = start of the silence just after t (or None)."""
    best = None
    for s, e in sils:
        if t - 0.15 <= s <= t + win and (best is None or s < best):
            best = s
    return best


# ------------------------------------------------------------------- prosody (F0)
def f0_lookup(wav_path, sr=16000):
    """Return meanF0(t0,t1) closure over a parselmouth pitch track. Falls back to zeros."""
    try:
        import parselmouth
        snd = parselmouth.Sound(str(wav_path))
        pitch = snd.to_pitch(time_step=0.01)
        f0 = pitch.selected_array["frequency"]          # 0 where unvoiced
        times = pitch.xs()
        gmean = float(np.mean(f0[f0 > 0])) if np.any(f0 > 0) else 0.0
    except Exception:
        return (lambda a, b: 0.0), 0.0

    def mean_f0(t0, t1):
        m = (times >= t0) & (times <= t1)
        v = f0[m]
        v = v[v > 0]
        return float(np.mean(v)) if v.size else 0.0
    return mean_f0, gmean


def pitch_reset(words, k, mean_f0, gmean):
    """Higher = the pause after word k looks like a real phrase boundary (F0 reset + final lowering)."""
    if gmean <= 0 or k + 1 >= len(words):
        return 0.0
    before = mean_f0(words[k]["end"] - 0.30, words[k]["end"])
    after = mean_f0(words[k + 1]["start"], words[k + 1]["start"] + 0.30)
    reset = max(0.0, after - before) / gmean          # pitch jumps back up after the pause
    lower = max(0.0, gmean - before) / gmean          # speaker dropped below their mean before pausing
    return min(1.0, 0.6 * reset + 0.4 * lower)


# --------------------------------------------------------------- grouping engine
def choose_split(words, s, sils, variant, mean_f0, gmean):
    """From segment start s, pick the end-word k: a real pause closest to TARGET_SEC.
    v0 uses ASR gaps; v1/v1s use measured silence; v2 prefers a pitch-reset boundary."""
    N = len(words)
    cands, k = [], s
    while k < N:
        dur = words[k]["end"] - words[s]["start"]
        if k + 1 < N:
            g0, g1 = words[k]["end"], words[k + 1]["start"]
            gap, sil = g1 - g0, sil_overlap(g0, g1, sils)
        else:
            gap = sil = 9.0
        if dur >= MIN_SEC:
            cands.append({"k": k, "dur": dur, "gap": gap, "sil": sil})
        if dur >= MIN_SEC and (gap > MAX_INTRA_GAP or dur > MAX_SEC):   # hard break / over-length
            break
        k += 1
    if not cands:
        return min(k, N - 1)

    def strength(c):
        return c["gap"] if variant == "v0" else c["sil"]   # strongest pause per window (old heuristic)
    strong = [c for c in cands if strength(c) >= 0.16]
    pool = strong or cands
    if variant == "v2" and gmean > 0:                 # prosody: bias toward a pitch-reset boundary
        return max(pool, key=lambda c: 0.7 * pitch_reset(words, c["k"], mean_f0, gmean)
                   + strength(c) - 0.03 * abs(c["dur"] - TARGET_SEC))["k"]
    return max(pool, key=lambda c: strength(c) - 0.03 * abs(c["dur"] - TARGET_SEC))["k"]


def group(words, sils, variant, mean_f0, gmean):
    """Cut at pause-centres, CONTIGUOUS with a 0.16s overlap pad each side — the structure the
    hand-reviewed export uses (start_{i+1} - end_i == -0.16)."""
    N = len(words)
    splits, i = [], 0
    while i < N:
        k = choose_split(words, i, sils, variant, mean_f0, gmean)
        splits.append(k)
        i = k + 1

    do_snap, HALF = variant != "v0", 0.06
    segs, prev_end_idx = [], -1
    for k in splits:
        s_idx = prev_end_idx + 1
        prev_end_idx = k
        if s_idx > k or s_idx >= N:
            continue
        if s_idx == 0:
            start = max(0.0, words[0]["start"] - LEAD)
        else:                                          # boundary = centre of the pause before this clip
            c = (words[s_idx - 1]["end"] + words[s_idx]["start"]) / 2.0
            if do_snap:
                c = snap(c, sils)[0]
            start = max(0.0, c - HALF)
        if k + 1 < N:                                  # boundary = centre of the pause after this clip
            c = (words[k]["end"] + words[k + 1]["start"]) / 2.0
            if do_snap:
                c = snap(c, sils)[0]
            end = c + HALF
        else:
            end = words[k]["end"] + TAIL
        if end - start >= 1.0:
            segs.append({"s_idx": s_idx, "k_idx": k, "start": round(start, 3), "end": round(end, 3)})
    return segs


# ------------------------------------------------------------- text + keep/cut QA
def load_english():
    p = ROOT / "data" / "english_words.txt"
    return set(p.read_text(encoding="utf-8").split()) if p.exists() else set()


def seg_text(words, seg):
    return " ".join(words[i]["text"] for i in range(seg["s_idx"], seg["k_idx"] + 1)).strip()


def qa_decision(words, seg, sils, eng):
    """Conservative prefill -> ('keep'|'cut', reason). Only HIGH-confidence STRUCTURAL cuts are
    suggested (length / alignment-loss / verse-dense); everything else defaults to keep so the
    human confirms. Content judgments (unclear pronunciation, audio-text mismatch) stay the
    human's call — an ASR round-trip CER gate is the pod-side upgrade for those."""
    dur = seg["end"] - seg["start"]
    toks = [t.strip(".,?!;:\"'").lower() for t in seg_text(words, seg).split()]
    toks = [t for t in toks if t]
    wps = len(toks) / dur if dur > 0 else 0.0
    non_eng = sum(1 for t in toks if t not in eng) / max(1, len(toks))
    if dur < 3.5:
        return "cut", f"short({dur:.1f}s)"
    if dur > 18.0:
        return "cut", f"long({dur:.1f}s)"
    if wps < 0.40:
        return "cut", f"low_wps({wps:.2f})"        # severe text-audio mismatch / alignment loss
    if non_eng > 0.70 and len(toks) >= 4:
        return "cut", f"verse_dense({non_eng:.0%})"
    reason = "ok"
    if non_eng > 0.45:
        reason = f"review_sanskrit({non_eng:.0%})"  # kept, but flagged for the human's ear
    elif wps < 0.6:
        reason = f"review_wps({wps:.2f})"
    return "keep", reason


# ------------------------------------------------------------------- ablation
def boundaries_of(segs):
    b = []
    for s in segs:
        b += [s["start"], s["end"]]
    return sorted(set(round(x, 3) for x in b))


def recall(human_b, prop_b, tol):
    if not human_b:
        return 0.0, 0.0
    errs = []
    hit = 0
    for h in human_b:
        d = min(abs(h - p) for p in prop_b) if prop_b else 999
        if d <= tol:
            hit += 1
            errs.append(d)
    med = float(np.median(errs)) if errs else 0.0
    return hit / len(human_b), med


def validity(words, segs, sils):
    """% of clips that are training-valid, plus a breakdown of WHY the rest fail."""
    def midword(t):
        for w in words:
            if w["start"] + 0.03 < t < w["end"] - 0.03:
                return True
        return False

    def in_sil(t):
        return any(s - 0.08 <= t <= e + 0.08 for s, e in sils)

    ok = 0
    why = {"len": 0, "midword": 0, "not_silence": 0}
    for s in segs:
        dur = s["end"] - s["start"]
        bad = False
        if not (5.0 <= dur <= 18.0):
            why["len"] += 1; bad = True
        if midword(s["start"]) or midword(s["end"]):
            why["midword"] += 1; bad = True
        if not (in_sil(s["start"]) and in_sil(s["end"])):
            why["not_silence"] += 1; bad = True
        if not bad:
            ok += 1
    return (ok / len(segs) if segs else 0.0), why


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--export", help="hand-reviewed resegment_export.json (enables --ablate)")
    ap.add_argument("--ablate", action="store_true")
    ap.add_argument("--emit", help="write the chosen variant's proposal here")
    ap.add_argument("--variant", default="v1", choices=["v0", "v1", "v1s", "v2"])
    ap.add_argument("--thr-db", type=float, default=-35.0)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    words = load_words(args.words)
    print(f"[load] {len(words)} words · audio {args.audio}")
    y, sr = librosa.load(args.audio, sr=16000, mono=True)
    rms_sil, thr = rms_silences(y, sr, thr_db=args.thr_db)
    print(f"[vad ] RMS silences: {len(rms_sil)} intervals (thr {thr:.1f} dBFS, "
          f"{100*sum(e-s for s,e in rms_sil)/(len(y)/sr):.1f}% of audio)")
    sil_sil = silero_silences(y, sr) if (args.ablate or args.variant == "v1s") else None
    if sil_sil is not None:
        print(f"[vad ] Silero silences: {len(sil_sil)} intervals")
    mean_f0, gmean = f0_lookup(args.audio, sr)
    print(f"[f0  ] parselmouth mean F0: {gmean:.0f} Hz" if gmean else "[f0  ] F0 unavailable (prosody off)")

    eng = load_english()

    def build(variant):
        s = sil_sil if (variant == "v1s" and sil_sil is not None) else rms_sil
        segs = group(words, s, variant, mean_f0, gmean)
        for seg in segs:
            seg["text"] = seg_text(words, seg)
            seg["decision"], seg["reason"] = qa_decision(words, seg, s, eng)
        return segs, s

    if args.ablate:
        if not args.export:
            sys.exit("--ablate needs --export")
        exp = json.loads(Path(args.export).read_text(encoding="utf-8"))
        human_b = boundaries_of([{"start": e["start"], "end": e["end"]} for e in exp])
        keeps = [e for e in exp if e.get("decision") == "keep"]
        human_bk = boundaries_of([{"start": e["start"], "end": e["end"]} for e in keeps])
        print(f"\n[gt  ] human: {len(exp)} regions ({len(keeps)} keep) · "
              f"{len(human_b)} boundaries ({len(human_bk)} keep-boundaries)")

        variants = ["v0", "v1"] + (["v1s"] if sil_sil is not None else []) + ["v2"]
        names = {"v0": "gap-only (old)", "v1": "+RMS-VAD snap", "v1s": "+Silero-VAD snap", "v2": "+prosody"}
        # anchor: the existing (old) proposal on disk, if present
        old = Path(args.export).with_name("resegment_proposed.json")
        rows = []
        if old.exists():
            op = json.loads(old.read_text(encoding="utf-8"))
            osegs = [{"start": o["start"], "end": o["end"]} for o in op]
            ob = boundaries_of(osegs)
            r2, _ = recall(human_b, ob, 0.2); r3, _ = recall(human_b, ob, 0.3)
            rows.append(("existing_proposed", len(osegs), r2, r3, float("nan"), float("nan"), 0, float("nan")))

        why_v2 = None
        for v in variants:
            segs, s = build(v)
            b = boundaries_of(segs)
            r2, e2 = recall(human_b, b, 0.2)
            r3, _ = recall(human_b, b, 0.3)
            val, why = validity(words, segs, s)
            keeps_v = [x for x in segs if x["decision"] == "keep"]
            kval, _ = validity(words, keeps_v, s)
            if v == "v2":
                why_v2 = why
            rows.append((f"{v}:{names[v]}", len(segs), r2, r3, val, kval, len(keeps_v), e2))

        print("\n=== ABLATION — vs your hand-reviewed export ===")
        print(f"{'variant':22s} {'#seg':>5s} {'rec@.2':>7s} {'rec@.3':>7s} {'valid(all)':>10s} "
              f"{'valid(KEEP)':>12s} {'medErr':>7s}")
        for name, n, r2, r3, val, kval, nk, err in rows:
            es = "  -  " if err != err else f"{err*1000:4.0f}ms"
            vs = "  -  " if val != val else f"{val*100:4.0f}%"
            ks = "  -  " if val != val else f"{kval*100:4.0f}% (n={nk})"
            print(f"{name:22s} {n:5d} {r2*100:6.0f}% {r3*100:6.0f}% {vs:>10s} {ks:>12s} {es:>7s}")
        if why_v2:
            print(f"\nv2 validity failures (all clips): {why_v2}  <- these are mostly the ones auto-suggested CUT")
        print("\nrecall  = % of YOUR boundaries the proposer also placed within tol "
              "(BIASED HIGH for existing_proposed: your export was refined FROM it).")
        print("validity = % of proposed clips that are 5-18s, both edges in real silence, no mid-word "
              "(the non-circular quality metric).")

    if args.emit:
        segs, _ = build(args.variant)
        out = [{"id": i + 1, "start": s["start"], "end": s["end"],
                "dur": round(s["end"] - s["start"], 2), "text": s["text"],
                "decision": s["decision"], "reason": s["reason"]}
               for i, s in enumerate(segs)]
        Path(args.emit).parent.mkdir(parents=True, exist_ok=True)
        Path(args.emit).write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
        keep = sum(1 for s in segs if s["decision"] == "keep")
        print(f"\n[emit] {len(out)} segments ({keep} keep / {len(out)-keep} cut suggested) "
              f"[{args.variant}] -> {args.emit}")


if __name__ == "__main__":
    main()
