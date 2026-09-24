"""Does how loud a recording is change what a recogniser hears?

The archive's lectures span ten decibels of loudness, from -27.1 to -17.1 dB RMS, and some peak
within half a decibel of clipping. Whether that matters is the kind of question it is tempting to
answer from what one knows about models - they normalise internally, so it should not - and that
is exactly the reasoning this project has been wrong with five times.

So it is measured instead. One span of known text, recognised at four loudnesses, scored against
the same reference each time. If the error rate moves, normalising is a stage. If it does not,
the ten decibels are not worth a line of code.

The four conditions are chosen to bracket what a pipeline might actually do:

  -10 dB   quieter than anything in the archive
    0 dB   as published
  +10 dB   louder, and on a file peaking near zero this CLIPS - which is the real risk of
           normalising upward, and worth seeing rather than avoiding
  RMS      normalised to -23 dB, the archive's median, with peak headroom - what a sane
           normalisation stage would do

    .venv-transcribe/Scripts/python.exe scripts/gain_experiment.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
OUT = REPO / "data/reference/analysis/gain-experiment.json"

TARGET_RMS_DB = -23.0
SECONDS = 45.0


ALIGNED = REPO / "data/reference/analysis/archive-alignment"


def pick_span() -> tuple[dict, dict, list[dict]]:
    """A long span from a solo lecture, with the reference words that fall in the clip.

    The words must be chosen BY TIME, not by taking a share of the span's word list. A first
    attempt did the latter and every condition scored an identical 85.9% - the error was
    dominated by comparing the clip against the wrong words, and the audio made no difference to
    a number that was not measuring the audio. `spans_detail` keeps word strings but not their
    times, so the times come from the alignment the spans were built from.
    """
    manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    solo = [l for l in manifest["detail"]
            if l["transcript_records_other_speakers"] is False and not l["duplicate_of"]]
    best, span = None, None
    for lecture in solo:
        for candidate in lecture["spans_detail"]:
            if candidate["end"] - candidate["start"] >= SECONDS and (
                    span is None or len(candidate["words"]) > len(span["words"])):
                best, span = lecture, candidate
    if span is None:
        raise SystemExit("no span long enough; align more lectures first")

    timed = json.loads((ALIGNED / f"{best['slug']}.json").read_text(encoding="utf-8"))["words"]
    inside = [w for w in timed
              if span["start"] <= (w["start"] + w["end"]) / 2 < span["start"] + SECONDS]
    return best, span, inside


def cut(source: Path, start: float, seconds: float, filters: str, out: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-err_detect",
                    "ignore_err", "-ss", str(start), "-t", str(seconds), "-i", str(source),
                    "-af", filters, "-ac", "1", "-ar", "16000", str(out)],
                   check=True, capture_output=True)


def main() -> None:
    sys.path.insert(0, str(REPO))
    from faster_whisper import WhisperModel
    from scripts.span_score import rates, score_span

    lecture, span, in_clip = pick_span()
    source = REPO / lecture["audio"]
    print(f"{lecture['slug'][:56]}")
    print(f"span {span['start']/60:.1f}-{span['end']/60:.1f} min, using the first "
          f"{SECONDS:.0f}s = {len(in_clip)} reference words\n", flush=True)

    conditions = {
        "-10 dB": "volume=-10dB",
        "as published": "anull",
        "+10 dB (clips)": "volume=+10dB",
        f"RMS to {TARGET_RMS_DB:.0f} dB": f"loudnorm=I=-23:TP=-1.5:LRA=11",
    }
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    results = []
    with tempfile.TemporaryDirectory() as workspace:
        for name, filters in conditions.items():
            clip = Path(workspace) / f"{abs(hash(name))}.wav"
            cut(source, span["start"], SECONDS, filters, clip)
            segments, _ = model.transcribe(str(clip), beam_size=1, vad_filter=False,
                                           condition_on_previous_text=False)
            heard = " ".join(s.text.strip() for s in segments).split()
            summary = rates(score_span([w["word"] for w in in_clip], heard))
            results.append({"condition": name, "heard_words": len(heard), **summary})
            english = summary["english_error_rate"]
            print(f"  {name:18} heard {len(heard):>4} words   "
                  f"English {english:>7.1%}" if english is not None else f"  {name}", flush=True)

    OUT.write_text(json.dumps({
        "what_this_is": "Whether loudness changes what a recogniser hears.",
        "lecture": lecture["slug"], "span": span["start"], "seconds": SECONDS,
        "results": results,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    spread = [r["english_error_rate"] for r in results if r["english_error_rate"] is not None]
    if spread:
        print(f"\nEnglish error rate across ten decibels and a clip: "
              f"{min(spread):.1%} to {max(spread):.1%} "
              f"(spread {max(spread)-min(spread):.1%})")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
