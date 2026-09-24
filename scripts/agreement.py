"""Do two runs of the same alignment agree?

Before trusting fifty lectures aligned on rented hardware, align two of them on both and check
the answers match. The risk is specific, and this project has already been bitten by its cousin:
batched Whisper decoding was faster and destroyed the chanted verse, 88% wrong. A GPU brings its
own version - float16 rather than float32, different kernels, cuDNN non-determinism.

The reason to insist on the check is not that a GPU is likely to be wrong. It is that **a faster
number that differs from the laptop's number is worse than no number**, because every figure in
this project is quoted against a Melbourne baseline measured on the laptop, and a run that
silently diverges makes the two incomparable without anyone noticing.

The same check guards any change that could move a timing - a library upgrade, a refactor of the
walk, a different decoder - so it is really a regression test whose fixture is a previous run.

    python scripts/agreement.py RUN-A.json RUN-B.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

# MMS_FA emits one frame per 320 samples at 16 kHz. A difference smaller than that is not a
# disagreement about where the word is - it is the same frame, reported with different floating
# point. Nothing finer than this is meaningful, whatever the arithmetic says.
FRAME = 0.02

# Beyond this the two runs are not describing the same audio any more. A fifth of a second is
# already twice the median gap between the aligner and three commercial systems, so a run
# differing by more has stopped being a faster way of getting the same answer.
DIVERGED = 0.2


def compare_alignments(first: list[dict], second: list[dict]) -> dict:
    """Two alignments of one lecture, compared word by word.

    Both the median and the maximum are reported, because they catch different failures. A
    systematic offset - every word late by the same amount, say from a decoder disagreeing about
    where the audio begins - moves the median. A single catastrophically misplaced word leaves
    the median untouched and shows only in the maximum.
    """
    if len(first) != len(second):
        return {"verdict": "different text", "words": len(first),
                "why": f"{len(first)} words in the first run, {len(second)} in the second"}
    if not first:
        return {"verdict": "identical", "words": 0, "median_shift": 0.0, "max_shift": 0.0,
                "within_one_frame": 1.0, "why": "nothing to compare"}

    for a, b in zip(first, second):
        if a["word"] != b["word"]:
            return {"verdict": "different text", "words": len(first),
                    "why": f"the runs disagree about the words themselves: "
                           f"{a['word']!r} against {b['word']!r}"}

    shifts = [abs(a["start"] - b["start"]) for a, b in zip(first, second)]
    median, largest = st.median(shifts), max(shifts)
    within = sum(1 for s in shifts if s <= FRAME) / len(shifts)

    if largest <= FRAME:
        verdict, why = "identical", "every word within one frame"
    elif largest > DIVERGED or median > FRAME * 2:
        verdict, why = "diverged", f"worst word moves {largest:.3f}s, median {median:.3f}s"
    else:
        verdict, why = "close", (f"{within:.0%} of words within one frame, "
                                 f"worst moves {largest:.3f}s")

    return {"verdict": verdict, "words": len(first), "median_shift": round(median, 4),
            "max_shift": round(largest, 4), "within_one_frame": round(within, 4), "why": why}


def load(path: Path) -> list[dict]:
    """Word list from an align_archive record, or from a bare list of words."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "words" in data:
        return data["words"]
    if isinstance(data, dict) and "cues" in data:
        return [w for cue in data["cues"] for w in cue["words"]]
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first")
    parser.add_argument("second")
    args = parser.parse_args()

    result = compare_alignments(load(Path(args.first)), load(Path(args.second)))
    print(f"verdict: {result['verdict'].upper()}  ({result['why']})")
    if "median_shift" in result:
        print(f"  {result['words']:,} words")
        print(f"  median shift {result['median_shift']:.4f}s, worst {result['max_shift']:.4f}s")
        print(f"  within one frame ({FRAME}s): {result['within_one_frame']:.1%}")
    # A non-zero exit so this can gate a pipeline rather than merely inform one.
    raise SystemExit(0 if result["verdict"] in ("identical", "close") else 1)


if __name__ == "__main__":
    main()
