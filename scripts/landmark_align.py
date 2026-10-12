"""Time a published transcript by landmarks: fixed points where it and a recogniser agree.

The walking aligner (`scripts/align_archive.py`) moves through a recording seven minutes at a
time, handing each window a fixed share of the text. Measured against ElevenLabs word times on
eight lectures, that design fails in two ways, and neither can be fixed inside it:

- **Overflow.** When the speaker says something the edited transcript leaves out - a chanted
  verse, a repeated sentence - the window's text no longer fits its audio. Forced alignment
  cannot leave a word out, so the last words are crammed onto whatever audio is there: in "A True
  Attitude…" English was laid up to 3.5 minutes early, over a verse.
- **Drift.** Each window starts where the last one's final word ended, and a walk that only moves
  forward cannot take time back. Text that was never said pushes every later word late, window
  after window: a darshan drifted from 16 to 221 seconds behind the voice.

Landmarks remove the walk. A recogniser's words are compared with the transcript, and every run
of `MIN_RUN` or more tokens the two agree on becomes a landmark: a place in the text whose time
is known. The recording is cut in the pause before each landmark, and each piece is aligned on
its own - its words, its audio, a skip symbol at each end for speech the transcript lacks. A
mistake can no longer cross a landmark, and nothing carries from one piece to the next.

The recogniser only says WHERE. The times on the page still come from the same acoustic model
and the same alignment as before, within each piece, so a landmark from a rougher recogniser
than ElevenLabs costs nothing in precision as long as it lands in the right pause.

    .venv-indic/Scripts/python.exe -m scripts.landmark_align --slug SLUG
    .venv-indic/Scripts/python.exe -m scripts.landmark_align --evaluate   # held-out check, every
                                                                          # lecture with words
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

from scripts.forced_align import STAR, align, problems, spoken_words, to_seconds
from scripts.transcript_accuracy import fold

REPO = Path(__file__).resolve().parents[1]
LECTURES = REPO / "data/lectures"
HEARD = REPO / "data/reference/analysis/hosted/elevenlabs"
WALKED = REPO / "data/reference/analysis/archive-alignment"
OUT = REPO / "data/reference/analysis/landmark-alignment"

# Tokens in a row that both sides must share before a run is believed. Fewer is not evidence:
# a single common word, matched alone, was once paired with another occurrence 25 s away.
MIN_RUN = 4


@dataclass(frozen=True)
class Landmark:
    """A run of transcript words a recogniser also heard, and when it heard them."""

    first: int    # first transcript word of the run
    last: int     # last transcript word of the run, inclusive
    start: float  # when the recogniser heard the first word begin
    end: float    # when it heard the last word end
    cut: float    # where the recording is cut before this run: mid-pause before `start`


@dataclass(frozen=True)
class Segment:
    """A stretch of transcript and the stretch of audio it is aligned within, alone."""

    first: int    # first transcript word
    stop: int     # one past the last transcript word
    start: float  # seconds
    end: float    # seconds


def landmarks(words: list[str], heard: list[dict], min_run: int = MIN_RUN) -> list[Landmark]:
    """Runs of words the transcript and a recogniser agree on, with when they were heard.

    `heard` is the recogniser's words, `{"w", "s", "e"}`, in time order. A run is trimmed to
    whole words on both sides, so a landmark never dates a word by half of it.
    """
    heard = [h for h in heard if h.get("s") is not None and h.get("e") is not None]
    ours = [(token, index) for index, word in enumerate(words) for token in fold(word)]
    theirs = [(token, index) for index, h in enumerate(heard) for token in fold(h["w"])]
    matcher = SequenceMatcher(None, [t for t, _ in ours], [t for t, _ in theirs], autojunk=False)

    def opens(a: int, b: int) -> bool:
        return ((a == 0 or ours[a - 1][1] != ours[a][1])
                and (b == 0 or theirs[b - 1][1] != theirs[b][1]))

    def closes(a: int, b: int) -> bool:
        return ((a == len(ours) - 1 or ours[a + 1][1] != ours[a][1])
                and (b == len(theirs) - 1 or theirs[b + 1][1] != theirs[b][1]))

    marks: list[Landmark] = []
    for block in matcher.get_matching_blocks():
        lo, hi = 0, block.size - 1
        while lo <= hi and not opens(block.a + lo, block.b + lo):
            lo += 1
        while hi >= lo and not closes(block.a + hi, block.b + hi):
            hi -= 1
        if hi - lo + 1 < min_run:
            continue
        first, last = ours[block.a + lo][1], ours[block.a + hi][1]
        h0, h1 = theirs[block.b + lo][1], theirs[block.b + hi][1]
        start, end = heard[h0]["s"], heard[h1]["e"]
        before = heard[h0 - 1]["e"] if h0 > 0 else 0.0
        cut = (before + start) / 2 if before <= start else start
        # A recogniser's times can overlap; a landmark that would cut back into the previous
        # one is dropped rather than allowed to fold time over itself.
        if marks and (cut < marks[-1].end or first <= marks[-1].last):
            continue
        marks.append(Landmark(first, last, start, end, round(cut, 3)))
    return marks


def segments(marks: list[Landmark], n_words: int, duration: float) -> list[Segment]:
    """Cut the transcript and the recording at the landmarks. Every word lands in exactly one
    segment, and the segments run end to end from zero to `duration`."""
    if not marks:
        return [Segment(0, n_words, 0.0, duration)]
    out: list[Segment] = []
    if marks[0].first > 0:
        out.append(Segment(0, marks[0].first, 0.0, marks[0].cut))
    for k, mark in enumerate(marks):
        following = marks[k + 1] if k + 1 < len(marks) else None
        out.append(Segment(mark.first, following.first if following else n_words,
                           mark.cut if out else 0.0,
                           following.cut if following else duration))
    return out


def align_segments(log_probs, seconds_per_frame: float, words: list[str],
                   pieces: list[Segment]) -> tuple[list, list[dict]]:
    """Align each segment on its own and join the results.

    Each segment is aligned as [skip] + its words + [skip]: the skips are free to absorb speech
    the transcript lacks at either end, and between them the words fall where their letters fit
    best. A segment whose words cannot fit its audio - text that was never said, usually - is
    left untimed and reported, never squeezed into someone else's audio.
    """
    scores = log_probs[0] if log_probs.dim() == 3 else log_probs
    frames = scores.size(0)
    placed, steps = [], []
    for piece in pieces:
        chunk = words[piece.first:piece.stop]
        if not chunk:
            continue
        f0 = max(0, round(piece.start / seconds_per_frame))
        f1 = min(frames, round(piece.end / seconds_per_frame))
        step = {"first": piece.first, "stop": piece.stop,
                "start": round(piece.start, 3), "end": round(piece.end, 3)}
        try:
            spans = align(scores[f0:f1], [STAR] + chunk + [STAR])
        except (ValueError, RuntimeError) as exc:
            steps.append({**step, "why": f"{type(exc).__name__}: {str(exc)[:160]}"})
            continue
        real = [s for s in spans if s.word != STAR]
        for span in real:
            span.index = piece.first + (span.index - 1)   # the leading skip is index 0
        placed.extend(to_seconds(real, seconds_per_frame, offset=f0 * seconds_per_frame))
        steps.append({**step, "placed": len(real)})
    return placed, steps


def heard_words(slug: str) -> list[dict]:
    record = json.loads((HEARD / f"{slug}.json").read_text(encoding="utf-8"))
    if record.get("unit", "word") != "word":
        raise ValueError(f"{slug}: the recogniser reported {record['unit']}s, not words")
    return [h for h in record["words"] if h.get("s") is not None]


def scored_audio(slug: str):
    """The acoustic model's view of a recording, read exactly as the walking aligner reads it,
    so both share one clock."""
    import torchaudio
    from scripts.align_archive import read_audio
    from scripts.forced_align import SAMPLE_RATE, emissions_long
    waveform, rate = read_audio(LECTURES / slug / "audio.mp3")
    if rate != SAMPLE_RATE:
        waveform = torchaudio.functional.resample(waveform, rate, SAMPLE_RATE)
    log_probs, seconds_per_frame = emissions_long(waveform)
    return log_probs, seconds_per_frame, waveform.size(0) / SAMPLE_RATE


def align_lecture(slug: str, scored=None, keep=lambda marks: marks) -> dict:
    """One lecture timed by landmarks. `keep` chooses which landmarks to use - all of them,
    except when holding some out to check the result against."""
    started = time.time()
    words = spoken_words((LECTURES / slug / "transcript.txt").read_text(encoding="utf-8"))
    marks = keep(landmarks(words, heard_words(slug)))
    log_probs, seconds_per_frame, duration = scored or scored_audio(slug)
    placed, steps = align_segments(log_probs, seconds_per_frame, words,
                                   segments(marks, len(words), duration))
    return {
        "slug": slug,
        "method": "landmark",
        "audio_seconds": round(duration, 1),
        "transcript_words": len(words),
        "words_placed": len(placed),
        "coverage": round(len(placed) / len(words), 4) if words else 0.0,
        "mean_score": round(sum(s.score for s in placed) / len(placed), 4) if placed else 0.0,
        "landmarks": len(marks),
        "segments_untimed": [s for s in steps if "why" in s],
        "wall_seconds": round(time.time() - started, 1),
        "invariants_violated": problems(placed, duration=duration),
        "words": [asdict(s) for s in placed],
    }


def held_out_check(slug: str) -> dict:
    """Is landmark timing better than the walk, judged on words neither was given?

    Every other landmark is withheld from the landmark aligner, and the words in the withheld
    runs are then compared with where the recogniser heard them - for this alignment and for the
    walking aligner's, on exactly the same words. Judging on landmarks it was given would be
    circular: they agree with the recogniser by construction.
    """
    from scripts.read_along import paragraphs, renumber, word_check
    words = spoken_words((LECTURES / slug / "transcript.txt").read_text(encoding="utf-8"))
    heard = heard_words(slug)
    withheld = landmarks(words, heard)[1::2]
    judged = {i for m in withheld for i in range(m.first, m.last + 1)}

    result = align_lecture(slug, keep=lambda marks: marks[0::2])
    walked = json.loads((WALKED / f"{slug}.json").read_text(encoding="utf-8"))["words"]
    try:
        walked, _ = renumber(paragraphs((LECTURES / slug / "transcript.txt")
                                        .read_text(encoding="utf-8")), walked)
    except ValueError:
        pass

    def judge(timed: list[dict]) -> dict:
        offsets = [abs(o) for i, o in word_check(timed, heard).items() if i in judged]
        if not offsets:
            return {"words": 0}
        return {"words": len(offsets), "median_s": round(statistics.median(offsets), 3),
                "over_1s": round(sum(o > 1.0 for o in offsets) / len(offsets), 4),
                "over_5s": round(sum(o > 5.0 for o in offsets) / len(offsets), 4)}

    return {"slug": slug, "withheld_landmarks": len(withheld), "judged_words": len(judged),
            "landmark": judge(result["words"]), "walk": judge(walked),
            "invariants_violated": result["invariants_violated"],
            "untimed_segments": len(result["segments_untimed"])}


def write_atomically(destination: Path, result: dict) -> None:
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", action="append", default=None)
    parser.add_argument("--evaluate", action="store_true",
                        help="held-out comparison with the walking aligner; writes nothing")
    args = parser.parse_args()

    slugs = args.slug or sorted(p.stem for p in HEARD.glob("*.json")
                                if (WALKED / p.name).exists())
    if args.evaluate:
        rows = []
        for slug in slugs:
            print(f"checking {slug[:60]}", flush=True)
            row = held_out_check(slug)
            rows.append(row)
            for name in ("walk", "landmark"):
                r = row[name]
                print(f"   {name:9} {r.get('words', 0):5} withheld words, median "
                      f"{r.get('median_s', float('nan')):6.3f}s, >1s {r.get('over_1s', 0):6.1%}, "
                      f">5s {r.get('over_5s', 0):6.1%}", flush=True)
        (OUT).mkdir(parents=True, exist_ok=True)
        (OUT / "EVALUATION.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    for slug in slugs:
        print(f"timing {slug[:60]}", flush=True)
        result = align_lecture(slug)
        write_atomically(OUT / f"{slug}.json", result)
        print(f"   {result['words_placed']:,}/{result['transcript_words']:,} words, "
              f"{result['landmarks']} landmarks, {len(result['segments_untimed'])} segments "
              f"untimed, {result['wall_seconds'] / 60:.1f} min"
              + ("  WRONG: " + "; ".join(result["invariants_violated"])
                 if result["invariants_violated"] else ""), flush=True)


if __name__ == "__main__":
    main()
