"""
strip_kirtana.py — detect SUNG kirtana/bhajan vs SPOKEN lecture (LANGUAGE-AGNOSTIC).

The ear-check proved no language-ID can find the non-Hindi content, but the non-Hindi (Bengali/Odia
devotional) is SUNG — and singing detectors fire on the acoustics of music, not words. inaSpeechSegmenter
tags "singing voice as music", so its `music` segments ≈ the sung kirtana we remove, with zero Hindi/Odia
LID. See docs/hindi-extraction-pipeline-research.md.

Runs on a pod with inaSpeechSegmenter (TensorFlow) + ffmpeg. For each lecture it writes a speech/music map
to content_triage_music.json, prints the speech-vs-sung breakdown, and exports the longest `music` clips to
data/hi/kirtana_samples/ so you can EAR-CHECK whether they're really kirtana.
  python cloud/strip_kirtana.py
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HI = ROOT / "data" / "hi" / "lectures"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="one lecture (default: all)")
    ap.add_argument("--samples", type=int, default=12, help="longest 'music' clips to export for ear-check")
    ap.add_argument("--min-music", type=float, default=3.0, help="min music-segment seconds to count/export")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    from inaSpeechSegmenter import Segmenter
    print("loading inaSpeechSegmenter (smn) ...", file=sys.stderr)
    seg = Segmenter(vad_engine="smn", detect_gender=False)

    slugs = [a.slug] if a.slug else [p.name for p in sorted(HI.iterdir()) if p.is_dir()]
    music_clips = []                             # (slug, s, e, mp3)
    grand = defaultdict(float)
    for slug in slugs:
        d = HI / slug
        mp3 = d / "audio.mp3"
        if not mp3.exists():
            print(f"  skip {slug}: no audio.mp3")
            continue
        segmentation = seg(str(mp3))             # [(label, start, end), ...]  label in speech/music/noEnergy/noise
        per = defaultdict(float)
        music_segs = []
        for label, s, e in segmentation:
            per[label] += (e - s)
            grand[label] += (e - s)
            if label == "music" and (e - s) >= a.min_music:
                music_segs.append((s, e))
                music_clips.append((slug, s, e, str(mp3)))
        (d / "content_triage_music.json").write_text(json.dumps(
            {"slug": slug, "min_by_label": {k: round(v / 60, 2) for k, v in per.items()},
             "music_segments": [[round(s, 2), round(e, 2)] for s, e in music_segs]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        tot = sum(per.values()) or 1.0
        print(f"  {slug}: speech {per['speech']/60:.1f}m ({100*per['speech']/tot:.0f}%) | "
              f"MUSIC {per['music']/60:.1f}m ({100*per['music']/tot:.0f}%) | "
              f"noise {per.get('noise',0)/60:.1f}m | silence {per.get('noEnergy',0)/60:.1f}m")

    gtot = sum(grand.values()) or 1.0
    print(f"\n==== inaSpeechSegmenter over all lectures ==== {gtot/60:.0f}min")
    print(f"  Speech           : {grand['speech']/60:.0f}min ({100*grand['speech']/gtot:.0f}%)")
    print(f"  MUSIC (~kirtana) : {grand['music']/60:.0f}min ({100*grand['music']/gtot:.0f}%)   <-- the kirtana number")
    print(f"  noise {grand.get('noise',0)/60:.0f}min | silence {grand.get('noEnergy',0)/60:.0f}min")

    outdir = ROOT / "data" / "hi" / "kirtana_samples"
    outdir.mkdir(parents=True, exist_ok=True)
    for f in outdir.glob("*.wav"):
        f.unlink()
    music_clips.sort(key=lambda c: -(c[2] - c[1]))   # longest music segments first
    for i, (slug, s, e, mp3) in enumerate(music_clips[:a.samples], 1):
        dur = min(e - s, 15)                         # cap the sample at 15s
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ss", str(s), "-t", str(dur),
                        "-ac", "1", "-ar", "16000", str(outdir / f"music_{i:02d}_{slug[-2:]}_{int(s)}s_{int(e-s)}dur.wav")])
    print(f"\nexported {min(len(music_clips), a.samples)} longest 'music' clips -> {outdir}  (ear-check: is it kirtana?)")


if __name__ == "__main__":
    main()
