"""Grade a recogniser only where the transcript can be trusted.

The bake-off compared whole transcripts against each other, which is fair when the reference
covers the whole recording. The archive's references do not. Six of them stop while the lecture
continues, and every one of them omits something, so a model graded end to end is charged for
words it heard perfectly well in stretches nobody wrote down.

So grading happens span by span, over the manifest `scripts/scoreable.py` produces. Anything a
model says outside those spans is neither credited nor charged - it is simply not evidence.

This needs each model's words placed in time, which is why `flex_timed.py` exists: flex emits no
timestamps, and without them it cannot be graded this way at all.

    .venv-indic/Scripts/python.exe -m scripts.span_score SYSTEM-WORDS.jsonl --system whisper
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.transcript_accuracy import (fold, has_diacritics, indic_language, normalise, score)

REPO = Path(__file__).resolve().parents[1]
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"


def heard_within(start: float, end: float, words: list[dict]) -> list[str]:
    """The model's words that belong to this span, by where the middle of each word falls.

    The midpoint decides, rather than the start or the end. A word straddling the edge belongs
    to whichever side holds most of it, and - more important - every word lands in exactly one
    span, so nothing is counted twice or lost between two of them.
    """
    inside = [w for w in sorted(words, key=lambda w: w["s"])
              if start <= (w["s"] + w["e"]) / 2 < end]
    return [w["w"] for w in inside]


def score_span(reference_words: list[str], heard_words: list[str]) -> dict:
    """One span, scored the way the bake-off scores a transcript.

    Both sides go through the same normalisation - editorial asides, contractions, spelled
    numbers - so what remains is a difference of hearing rather than of house style.
    """
    reference = fold(normalise(" ".join(reference_words)))
    hypothesis = fold(normalise(" ".join(heard_words)))
    if not reference:
        return {"reference_words": 0, "heard_words": len(hypothesis),
                "english": {"words": 0, "exact": 0, "near": 0, "errors": 0},
                "indic": {"words": 0, "exact": 0, "near": 0, "errors": 0}}

    # `fold` drops fillers and punctuation, so diacritics must be read off the original words.
    original = normalise(" ".join(reference_words)).split()
    line = " ".join(original)
    marks = [has_diacritics(w) for w in original]
    if len(marks) != len(reference):                 # folding changed the count; fall back
        marks = [False] * len(reference)

    result = score(reference, marks, hypothesis)
    return {"reference_words": result["reference_words"],
            "heard_words": result["hypothesis_words"],
            "english": result["english"], "indic": result["indic"],
            "language": indic_language(line) if any(marks) else "english"}


def combine(results: list[dict]) -> dict:
    """Add spans together. Error rates are computed from the totals, never averaged."""
    total = {"reference_words": 0, "heard_words": 0,
             "english": {"words": 0, "exact": 0, "near": 0, "errors": 0},
             "indic": {"words": 0, "exact": 0, "near": 0, "errors": 0}}
    for one in results:
        total["reference_words"] += one["reference_words"]
        total["heard_words"] += one["heard_words"]
        for track in ("english", "indic"):
            for key in ("words", "exact", "near", "errors"):
                total[track][key] += one[track].get(key, 0)
    return total


def rates(totals: dict) -> dict:
    """The numbers a decision is made on."""
    def share(track):
        return round(totals[track]["errors"] / totals[track]["words"], 4) \
            if totals[track]["words"] else None
    return {"reference_words": totals["reference_words"],
            "english_error_rate": share("english"),
            "indic_error_rate": share("indic"),
            "english_words": totals["english"]["words"],
            "indic_words": totals["indic"]["words"]}


def score_lecture(spans: list[dict], words: list[dict]) -> dict:
    return combine([score_span(s["words"], heard_within(s["start"], s["end"], words))
                    for s in spans])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("words", help="JSONL of the system's words: {w, s, e}")
    parser.add_argument("--slug", required=True, help="which lecture these words are for")
    parser.add_argument("--system", required=True)
    args = parser.parse_args()

    manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    lecture = next((l for l in manifest["detail"] if l["slug"] == args.slug), None)
    if lecture is None:
        raise SystemExit(f"{args.slug} is not in {SPANS.name}")

    words = [json.loads(line) for line in Path(args.words).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    words = [w for w in words if w.get("s") is not None]
    totals = score_lecture(lecture["spans_detail"], words)
    summary = rates(totals)
    print(f"{args.system} on {args.slug[:44]}")
    print(f"  graded on {summary['reference_words']:,} reference words "
          f"in {lecture['spans']} span(s)")
    for track in ("english", "indic"):
        rate = summary[f"{track}_error_rate"]
        if rate is not None:
            print(f"  {track:8} {rate:>7.1%}  of {summary[f'{track}_words']:,} words")


if __name__ == "__main__":
    main()
