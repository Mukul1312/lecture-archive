"""
odia_check.py — MEASURE how much of GGS's speech is actually ODIA (vs Hindi/English/...).

The content triage used Whisper LID, which has NO Odia label, so its Hindi/Odia split is untrustworthy
(see research/docs/hindi/hindi-extraction-pipeline-research.md). facebook/mms-lid-256 DOES have an `ory` (Odia) label,
so we run it over GGS-only speech windows to get a trustworthy language breakdown — specifically to
TEST the hypothesis "spoken Odia is rare" with a real number.

Reuses content_triage.json's `ggs_intervals` (GGS-only speech, from speaker-diarization — reliable, it's
a speaker not a language decision). Runs on the pod (venv_asr: torch + transformers).
  python cloud/odia_check.py
Outputs per lecture: content_triage_mms.json ; prints an overall Hindi/Odia/other breakdown.
Also exports the highest-confidence "MMS says Odia" clips to data/hi/odia_samples/ so you can EAR-CHECK
whether they're really Odia or just accented Hindi mislabelled.
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent.parent
HI = ROOT / "data" / "hi" / "lectures"


def to_wav_16k(src, dst):
    """mp3 -> cached 16k mono wav via ffmpeg. Standalone so we don't drag in pod_dataprep's librosa dep."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-ac", "1", "-ar", "16000", str(dst)], check=True)
    return dst
MID = "facebook/mms-lid-256"
NAMES = {"hin": "Hindi", "ory": "Odia", "ben": "Bengali", "asm": "Assamese", "npi": "Nepali",
         "urd": "Urdu", "eng": "English", "san": "Sanskrit", "mar": "Marathi", "guj": "Gujarati"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="one lecture (default: all)")
    ap.add_argument("--win", type=float, default=5.0, help="LID window seconds")
    ap.add_argument("--min-win", type=float, default=3.0, help="skip windows shorter than this")
    ap.add_argument("--samples", type=int, default=15, help="'MMS=Odia' clips to export for ear-check")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    from transformers import AutoFeatureExtractor, Wav2Vec2ForSequenceClassification
    print(f"loading {MID} on {dev} ...", file=sys.stderr)
    proc = AutoFeatureExtractor.from_pretrained(MID)
    model = Wav2Vec2ForSequenceClassification.from_pretrained(MID).to(dev).eval()
    id2label = model.config.id2label

    slugs = [a.slug] if a.slug else [p.name for p in sorted(HI.iterdir()) if p.is_dir()]
    grand = defaultdict(float)
    odia_clips = []                              # (slug, s, e, prob, wavpath)
    for slug in slugs:
        d = HI / slug
        tj = d / "content_triage.json"
        if not tj.exists():
            print(f"  skip {slug}: no content_triage.json")
            continue
        intervals = json.loads(tj.read_text(encoding="utf-8")).get("ggs_intervals", [])
        wav16 = to_wav_16k(d / "audio.mp3", ROOT / "_work" / f"hi_{slug}.wav")
        y, sr = torchaudio.load(str(wav16))
        if y.shape[0] > 1:
            y = y.mean(0, keepdim=True)
        y = y.squeeze(0)                         # mono 1-D
        per = defaultdict(float)
        wins = []
        for (s, e) in intervals:
            t = s
            while t < e - 0.5:
                w0, w1 = t, min(t + a.win, e)
                t = w1
                if w1 - w0 < a.min_win:
                    continue
                chunk = y[int(w0 * sr):int(w1 * sr)].numpy()
                inp = proc(chunk, sampling_rate=sr, return_tensors="pt")
                inp = {k: v.to(dev) for k, v in inp.items()}
                with torch.no_grad():
                    probs = model(**inp).logits.softmax(-1)[0]
                top = int(probs.argmax())
                lang, p = id2label[top], float(probs[top])
                per[lang] += (w1 - w0)
                grand[lang] += (w1 - w0)
                wins.append({"start": round(w0, 2), "end": round(w1, 2), "lang": lang, "prob": round(p, 3)})
                if lang == "ory":
                    odia_clips.append((slug, w0, w1, p, str(wav16)))
        tot = sum(per.values()) or 1.0
        hi = per.get("hin", 0) + per.get("urd", 0)
        od = per.get("ory", 0)
        (d / "content_triage_mms.json").write_text(json.dumps(
            {"slug": slug, "mms_min_by_lang": {k: round(v / 60, 2) for k, v in sorted(per.items(), key=lambda kv: -kv[1])},
             "mms_windows": wins}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {slug}: {tot/60:.1f}min | Hindi {hi/60:.1f}m ({100*hi/tot:.0f}%) | Odia {od/60:.1f}m "
              f"({100*od/tot:.0f}%) | " + " ".join(
                  f"{NAMES.get(k,k)}={v/60:.1f}" for k, v in sorted(per.items(), key=lambda kv: -kv[1])[:6]))

    gtot = sum(grand.values()) or 1.0
    ghi = grand.get("hin", 0) + grand.get("urd", 0)
    god = grand.get("ory", 0)
    print(f"\n==== MMS-LID over ALL GGS speech ==== {gtot/60:.0f}min analysed")
    print(f"  Hindi (hin+urd): {ghi/60:.0f}min ({100*ghi/gtot:.0f}%)")
    print(f"  Odia  (ory)    : {god/60:.0f}min ({100*god/gtot:.0f}%)   <-- the 'is Odia rare?' number")
    print("  full breakdown : " + ", ".join(
        f"{NAMES.get(k,k)} {v/60:.1f}m({100*v/gtot:.0f}%)" for k, v in sorted(grand.items(), key=lambda kv: -kv[1])))

    outdir = ROOT / "data" / "hi" / "odia_samples"
    outdir.mkdir(parents=True, exist_ok=True)
    for f in outdir.glob("*.wav"):
        f.unlink()
    odia_clips.sort(key=lambda c: -c[3])         # highest-confidence Odia first
    for i, (slug, s, e, p, wav) in enumerate(odia_clips[:a.samples], 1):
        dst = outdir / f"odia_{i:02d}_{slug[-2:]}_{int(s)}s_p{int(p*100)}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-ss", str(s), "-to", str(e), str(dst)])
    print(f"\nexported {min(len(odia_clips), a.samples)} highest-confidence 'MMS=Odia' clips -> {outdir}")
    print("NEXT: ear-check those samples — really Odia, or accented Hindi mislabelled? That confirms the plan.")


if __name__ == "__main__":
    main()
