"""
cut_hi_final.py — apply the human review's trims and produce the clean Hindi training set.

Reads train_hi_final.jsonl (downloaded from the review tool: one row per KEPT clip with
{audio, lecture, start, end, trimStart, trimEnd, text}) and, for each clip:
  - resolves the local wav at data/hi/lectures/<lecture>/clips_hi/<name>
  - ffmpeg-trims [trimStart, clipdur - trimEnd] (the syllables you shaved on the waveform)
  - writes a normalized 16 kHz mono wav to data/hi/train_final/wavs/<name>
and emits data/hi/train_final/train.jsonl {audio, text, duration} + a metadata.csv (path|text).

Trim semantics (from the WaveSurfer region): trimStart = seconds cut off the FRONT,
trimEnd = seconds cut off the END. clipdur comes from ffprobe (authoritative), not end-start.

Local, CPU-only (ffmpeg). No GPU / pod needed for this step.
  python scripts/cut_hi_final.py data/hi/train_hi_final.jsonl
"""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
try:
    from scripts.repo_paths import data_root
except ModuleNotFoundError:
    from repo_paths import data_root

FF = "ffmpeg"
FP = "ffprobe"
DATA = data_root(__file__)
LECT = DATA / "hi" / "lectures"
OUT = DATA / "hi" / "train_final"
WAVS = OUT / "wavs"


def default_review_manifest() -> Path:
    return DATA / "hi" / "train_hi_final.jsonl"


def clean_text(t: str) -> str:
    """Brackets in the drafts mark real filler VOCALIZATIONS he makes (per the reviewer):
    [Aan]=nasal 'aan', [हाँ]='haan', etc. They are genuine audio, so we keep the sound but
    strip the brackets — else the TTS model would read the literal '[Aan]'. Latin [Aan] is
    transliterated to its Devanagari nasal vowel; Devanagari fillers just lose the brackets."""
    t = t or ""
    t = re.sub(r"\[\s*[Aa]+n\s*\]", "आँ", t)     # [Aan] -> nasal aa
    t = re.sub(r"\[\s*([^\]]*?)\s*\]", r"\1", t)  # [हाँ] -> हाँ (keep inner, drop brackets)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def probe_dur(p: Path) -> float:
    r = subprocess.run(
        [FP, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(p)],
        capture_output=True, text=True)
    return float(r.stdout.strip())


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else
               default_review_manifest())
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    WAVS.mkdir(parents=True, exist_ok=True)

    manifest, meta_rows = [], []
    skipped, total_dur = [], 0.0
    for r in rows:
        name = Path(r["audio"]).name
        clip = LECT / r["lecture"] / "clips_hi" / name
        text = clean_text(r.get("text"))
        if not clip.exists():
            skipped.append((name, "missing wav"))
            continue
        if not text:
            skipped.append((name, "empty text"))
            continue

        dur = probe_dur(clip)
        ss = max(0.0, float(r.get("trimStart") or 0))
        te = max(0.0, float(r.get("trimEnd") or 0))
        to = dur - te
        # guard: never invert or produce a sliver
        if to - ss < 0.4:
            ss, to = 0.0, dur  # trims implausible for this file -> keep whole clip
        out = WAVS / name
        cmd = [FF, "-y", "-v", "error", "-i", str(clip),
               "-ss", f"{ss:.3f}", "-to", f"{to:.3f}",
               "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)]
        subprocess.run(cmd, check=True)
        d = to - ss
        total_dur += d
        manifest.append({"audio": f"wavs/{name}", "text": text, "duration": round(d, 3)})
        meta_rows.append((f"wavs/{name}", text))

    (OUT / "train.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in manifest) + "\n",
        encoding="utf-8")
    with (OUT / "metadata.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="|")
        w.writerows(meta_rows)

    print(f"wrote {len(manifest)} clips -> {WAVS}")
    print(f"total clean audio: {total_dur:.1f}s = {total_dur/60:.2f} min")
    print(f"manifest: {OUT/'train.jsonl'}")
    if skipped:
        print(f"SKIPPED {len(skipped)}:")
        for n, why in skipped:
            print(f"  {n}: {why}")


if __name__ == "__main__":
    main()
