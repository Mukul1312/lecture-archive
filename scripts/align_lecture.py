"""Give a verified transcript word-level timings, so the archive can be read along with.

The reviewed transcript arrives as cues - caption-sized lines, each with a start and end a
human checked against the audio. That is enough to read along at the line level and not enough
to highlight a word, which is what the archive is for: a listener who cannot follow chanted
Sanskrit needs to see which word is being sung now, not which line.

Cues make this tractable. Aligning seventy minutes in one pass is not possible - the Viterbi
backtrack matrix is frames x letters and runs to tens of gigabytes - but a cue is a few seconds
of audio whose words are already known, so each one aligns on its own in a fraction of a second
and no chunk boundary ever has to be guessed. Long-form audio with no cues is a harder problem
and a later one.

    python scripts/align_lecture.py REVIEW.json AUDIO.mp3 OUT.json
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict

from scripts.forced_align import align_window, spoken_words

# Cue boundaries mark where one caption should give way to the next, which is close to but not
# the same as where a word begins. A little air on each side lets the aligner find a word that
# starts fractionally early without having to invent audio for it.
PAD = 0.5


def align_cues(review_path: str, audio_path: str) -> dict:
    review = json.loads(open(review_path, encoding="utf-8").read())
    cues = review["cues"]
    offset = review.get("offset_ms", 0) / 1000

    out, failures = [], []
    started = time.time()
    for done, cue in enumerate(cues, 1):
        words = spoken_words(cue["text"])
        start, end = cue["start_ms"] / 1000 + offset, cue["end_ms"] / 1000 + offset
        if not words:
            out.append({"n": cue["n"], "start": start, "end": end, "words": []})
            continue
        try:
            spans = align_window(audio_path, start, end, words, pad=PAD)
        except Exception as exc:  # a cue too short for its words, or unreadable audio
            failures.append({"n": cue["n"], "why": str(exc)[:200]})
            spans = []
        out.append({"n": cue["n"], "start": start, "end": end,
                    "words": [asdict(s) for s in spans]})
        if done % 50 == 0:
            rate = (time.time() - started) / done
            print(f"  {done}/{len(cues)} cues, {rate:.2f}s each, "
                  f"{rate * (len(cues) - done) / 60:.1f} min left", flush=True)

    aligned = sum(len(c["words"]) for c in out)
    return {
        "what_this_is": "Word-level timings for a verified transcript, by CTC forced alignment.",
        "model": "torchaudio MMS_FA (wav2vec2, 1100+ languages, romanised alphabet)",
        "audio": audio_path,
        "review": review_path,
        "pad_s": PAD,
        "cues": out,
        "words_aligned": aligned,
        "cues_that_failed": failures,
        "wall_seconds": round(time.time() - started, 1),
    }


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    review_path, audio_path, out_path = sys.argv[1:4]
    result = align_cues(review_path, audio_path)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    print(f"{result['words_aligned']:,} words timed across {len(result['cues'])} cues "
          f"in {result['wall_seconds'] / 60:.1f} min -> {out_path}")
    if result["cues_that_failed"]:
        print(f"{len(result['cues_that_failed'])} cues failed: "
              f"{result['cues_that_failed'][:3]}")


if __name__ == "__main__":
    main()
