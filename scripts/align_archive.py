"""Place a published prose transcript against its recording, with nothing to start from.

The Melbourne reference came pre-cut into cues a human had already timed, so every alignment
had a few seconds of audio and the words that belonged to them. The official archive gives
paragraphs. No timings, no diarisation, and questioner turns largely left out - so the audio
contains speech the text never mentions.

Two walls stand in the way of simply aligning the whole thing. The Viterbi backtrack matrix is
frames by letters, which for a 47-minute lecture wants about 6 GB; and even with memory to
spare, cutting the audio means deciding which words belong to which piece, which is the very
thing being computed.

The way through is to walk forward and let the text run out on purpose. Take a window of audio,
give it **fewer words than could possibly fit** - a slow-speech floor well under the 91 words a
minute actually measured - and close the list with a star. The words land where they were said,
the star absorbs whatever audio is left over, and the last word's end becomes the start of the
next window. Nothing is ever guessed: each step is anchored by the step before it, and a step
that goes wrong shows up as a collapsed score rather than as silent drift.

The star earns its place twice here. It absorbs the overflow that makes the walk work, and where
the transcript has simply omitted speech - a question from the floor - it leaves a span that can
be counted, instead of a silence indistinguishable from success.

    .venv-indic/Scripts/python.exe -m scripts.align_archive            # every fetched lecture
    .venv-indic/Scripts/python.exe -m scripts.align_archive --limit 3
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import torch

from scripts.forced_align import (SAMPLE_RATE, STAR, align, emissions_long, problems,
                                  spoken_words, to_seconds)

REPO = Path(__file__).resolve().parents[1]
LECTURES = REPO / "data/lectures"
OUT = REPO / "data/reference/analysis/archive-alignment"

# A window short enough that frames x letters stays far inside memory, and long enough that a
# lecture takes a handful of steps rather than hundreds.
WINDOW_SECONDS = 420.0

# Words per minute assumed when deciding how much text to offer a window. The one lecture with
# both text and audio measures 91; this is deliberately well below it, so the text always runs
# out before the audio does and the star has something to absorb. Too high and the last words
# of a window get compressed into audio that was never theirs.
WORDS_PER_MINUTE_FLOOR = 55


def align_prose(waveform: torch.Tensor, words: list[str],
                window: float = WINDOW_SECONDS) -> tuple[list, list[dict]]:
    """Walk forward through the recording, placing words as the audio allows.

    Returns the placed words and one record per step, so a lecture that went wrong can be read
    afterwards rather than merely distrusted.
    """
    placed, steps = [], []
    at_sample, at_word = 0, 0

    while at_word < len(words) and at_sample < waveform.size(0):
        span_samples = min(int(window * SAMPLE_RATE), waveform.size(0) - at_sample)
        if span_samples < SAMPLE_RATE:                       # under a second of audio left
            break
        budget = max(1, int(span_samples / SAMPLE_RATE / 60 * WORDS_PER_MINUTE_FLOOR))
        offered = words[at_word:at_word + budget]
        # A star at each end: one for audio before the first word of this window, one for
        # whatever is left after the text runs out.
        targets = [STAR] + offered + [STAR]

        piece = waveform[at_sample:at_sample + span_samples]
        try:
            # emissions_long, not emissions: wav2vec2's attention is quadratic in frames, and
            # a seven-minute window is 21,000 of them. It scores the window in overlapping
            # half-minute pieces and joins what each one was best placed to judge.
            log_probs, seconds_per_frame = emissions_long(piece)
            spans = to_seconds(align(log_probs, targets), seconds_per_frame,
                               offset=at_sample / SAMPLE_RATE)
        except Exception as exc:
            steps.append({"at_word": at_word, "why": f"{type(exc).__name__}: {str(exc)[:120]}"})
            break

        real = [s for s in spans if s.word != STAR]
        if not real:
            steps.append({"at_word": at_word, "why": "no word could be placed"})
            break

        # Renumber onto the whole transcript: `align` counted from zero within this window, and
        # the leading star occupies index 0.
        for span in real:
            span.index = at_word + (span.index - 1)
        placed.extend(real)

        gap = next((s for s in spans if s.word == STAR and s.start >= real[-1].end), None)
        steps.append({
            "at_word": at_word, "offered": len(offered), "placed": len(real),
            "from_s": round(at_sample / SAMPLE_RATE, 1), "to_s": round(real[-1].end, 1),
            "mean_score": round(sum(s.score for s in real) / len(real), 4),
            "trailing_star_s": round(gap.end - gap.start, 1) if gap else 0.0,
        })

        at_word += len(offered)
        advanced = int(real[-1].end * SAMPLE_RATE) - at_sample
        if advanced <= 0:                                    # no progress; stop rather than spin
            steps.append({"at_word": at_word, "why": "the window made no progress"})
            break
        at_sample += advanced
    return placed, steps


def read_audio(path: Path) -> tuple[torch.Tensor, int]:
    """One recording as mono samples, even when the file is damaged.

    At least one lecture on the archive has a broken MPEG frame partway through - the same bytes
    arrive on a fresh download, so the damage is in the published file, not the transfer.
    libsndfile refuses it outright. ffmpeg skips the bad frame and carries on, which for a
    lecture recording is the right trade: a fraction of a second lost against the whole thing.
    """
    import soundfile as sf
    try:
        data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.mean(axis=1)), rate
    except Exception:
        pass

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"{path.name} is damaged and ffmpeg is not on PATH to rescue it")
    with tempfile.TemporaryDirectory() as workspace:
        repaired = Path(workspace) / "repaired.wav"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-err_detect", "ignore_err",
                        "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), str(repaired)],
                       check=True, capture_output=True)
        data, rate = sf.read(str(repaired), dtype="float32", always_2d=True)
        return torch.from_numpy(data.mean(axis=1)), rate


def align_lecture(folder: Path) -> dict | None:
    """One lecture: its published transcript, timed."""
    audio = folder / "audio.mp3"
    transcript = folder / "transcript.txt"
    if not (audio.exists() and transcript.exists()):
        return None

    import torchaudio
    waveform, rate = read_audio(audio)
    if rate != SAMPLE_RATE:
        waveform = torchaudio.functional.resample(waveform, rate, SAMPLE_RATE)

    words = spoken_words(transcript.read_text(encoding="utf-8"))
    started = time.time()
    placed, steps = align_prose(waveform, words)
    duration = waveform.size(0) / SAMPLE_RATE

    return {
        "slug": folder.name,
        "audio_seconds": round(duration, 1),
        "transcript_words": len(words),
        "words_placed": len(placed),
        "coverage": round(len(placed) / len(words), 4) if words else 0.0,
        "mean_score": round(sum(s.score for s in placed) / len(placed), 4) if placed else 0.0,
        "wall_seconds": round(time.time() - started, 1),
        "invariants_violated": problems(placed, duration=duration),
        "steps": steps,
        "words": [asdict(s) for s in placed],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", action="store_true",
                        help="summarise what has been aligned so far and stop")
    args = parser.parse_args()

    if args.report:
        summary = report()
        (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
        print(json.dumps(summary, indent=1, ensure_ascii=False))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    folders = sorted(f for f in LECTURES.iterdir()
                     if f.is_dir() and (f / "audio.mp3").exists())
    todo = [f for f in folders if not (OUT / f"{f.name}.json").exists()][:args.limit]
    print(f"{len(folders)} lectures on disk, {len(todo)} still to align", flush=True)

    for index, folder in enumerate(todo, 1):
        print(f"[{index}/{len(todo)}] {folder.name[:52]}", flush=True)
        try:
            result = align_lecture(folder)
        except Exception as exc:
            print(f"    FAILED {type(exc).__name__}: {str(exc)[:90]}", flush=True)
            continue
        if result is None:
            continue
        (OUT / f"{folder.name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    {result['words_placed']:,}/{result['transcript_words']:,} words "
              f"({result['coverage']:.0%}), score {result['mean_score']:.3f}, "
              f"{result['audio_seconds'] / 60:.0f} min in {result['wall_seconds'] / 60:.1f} min"
              + ("  WRONG: " + "; ".join(result["invariants_violated"])
                 if result["invariants_violated"] else ""), flush=True)




# A pause longer than this is not breathing: it is audio the transcript has no words for.
SILENT_GAP = 2.0

# Audio left after the last transcribed word, beyond which the transcript is not merely trailing
# off but has stopped while the recording continued.
UNTRANSCRIBED_TAIL = 300.0


def audio_accounted_for(words: list[dict], duration: float) -> float:
    """The share of the recording the transcript has any words for.

    Useful, but do NOT read it as a completeness score against some ideal. The obvious control -
    run the same measure on the verified Melbourne reference - gives 64%, because that reference
    deliberately skips 11 minutes of kirtan at the head and 12 at the tail. A transcript can be
    perfectly faithful to the class it covers and still score low here, because recordings
    contain things nobody set out to transcribe.

    `stops_early` is the measure that means something on its own.
    """
    if not words or duration <= 0:
        return 0.0
    silent = sum(b["start"] - a["end"] for a, b in zip(words, words[1:])
                 if b["start"] - a["end"] > SILENT_GAP)
    silent += words[0]["start"] + max(0.0, duration - words[-1]["end"])
    return round(1 - silent / duration, 4)


def stops_early(words: list[dict], duration: float) -> float:
    """Seconds of recording left after the last word the transcript had.

    This is the failure that ruins a reference, and it is visible without any baseline: the
    aligner places every word it was given, runs out, and the recording carries on. On
    `cc-adi-lila 4.256-258` the text ends at 23.7 minutes of 47.2, and the remaining audio is at
    the same loudness as the rest - he is still speaking and nobody wrote it down.

    A recogniser scored against such a transcript is charged for every word it correctly hears
    after that point, which would make the pipeline look far worse than it is.
    """
    if not words or duration <= 0:
        return 0.0
    return round(max(0.0, duration - words[-1]["end"]), 1)


def report() -> dict:
    """What the corpus looks like once the walk has been over it.

    Coverage is the honest headline: the share of published words that could be placed in the
    audio at all. A lecture well under the rest is not necessarily a failed alignment - it is
    just as likely a transcript that omits more than the others, which is the thing this corpus
    was always going to have to tell us.
    """
    done = sorted(OUT.glob("*.json"))
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in done
            if p.name != "SUMMARY.json"]
    if not rows:
        return {"lectures": 0}

    for r in rows:
        r["audio_accounted_for"] = audio_accounted_for(r["words"], r["audio_seconds"])
        r["seconds_after_transcript_ends"] = stops_early(r["words"], r["audio_seconds"])
    thin = sorted((r for r in rows if r["seconds_after_transcript_ends"] > UNTRANSCRIBED_TAIL),
                  key=lambda r: -r["seconds_after_transcript_ends"])

    words = sum(r["transcript_words"] for r in rows)
    placed = sum(r["words_placed"] for r in rows)
    audio = sum(r["audio_seconds"] for r in rows)
    wall = sum(r["wall_seconds"] for r in rows)
    scored = [r["mean_score"] for r in rows if r["words_placed"]]
    broken = [r["slug"] for r in rows if r["invariants_violated"]]
    by_coverage = sorted(rows, key=lambda r: r["coverage"])

    return {
        "what_this_is": "Published prose transcripts placed against their recordings.",
        "lectures": len(rows),
        "audio_hours": round(audio / 3600, 2),
        "transcript_words": words,
        "words_placed": placed,
        "coverage": round(placed / words, 4) if words else 0.0,
        "mean_score": round(sum(scored) / len(scored), 4) if scored else 0.0,
        "speed_vs_realtime": round(audio / wall, 2) if wall else 0.0,
        "lectures_with_broken_invariants": broken,
        "audio_accounted_for_median": round(
            sorted(r["audio_accounted_for"] for r in rows)[len(rows) // 2], 4),
        "audio_accounted_for_on_the_melbourne_reference": 0.64,
        "transcripts_that_stop_before_the_recording_does": [
            {"slug": r["slug"],
             "minutes_left_untranscribed": round(r["seconds_after_transcript_ends"] / 60, 1),
             "audio_minutes": round(r["audio_seconds"] / 60, 1),
             "coverage": r["coverage"]}
            for r in thin],
        "worst_coverage": [{"slug": r["slug"], "coverage": r["coverage"],
                            "score": r["mean_score"], "words": r["transcript_words"]}
                           for r in by_coverage[:5]],
        "best_coverage": [{"slug": r["slug"], "coverage": r["coverage"],
                           "score": r["mean_score"], "words": r["transcript_words"]}
                          for r in by_coverage[-5:]],
    }

if __name__ == "__main__":
    main()
