"""Choose between several recognisers, word by word.

    python scripts/transcript_select.py OUT.txt IN1.txt IN2.txt IN3.txt [--weights 1,1,1]

No single system is best on this corpus: one is strongest on English, another on Sanskrit,
and each is alone in getting some words right. Measured on the Melbourne reference, picking
the best of three per word would reach 92.4% on plain English where the best single system
reaches 83% — but only if something does the picking.

The method is ROVER: align every transcript onto the first one to build a confusion network,
then vote in each slot. It is deterministic and it cannot invent a word no recogniser
produced, which is the property that lets an archive of someone's teaching use it.

Two things it deliberately does not do:

* It does not help with Sanskrit. Agreement between systems that share an encoder lineage and
  the same near-zero hours of Sanskrit manufactures confidence rather than accuracy; the
  measured ceiling for selection there is 67%. Quoted verse is a retrieval problem.
* It does not break ties by guessing. With no majority the first transcript stands, so the
  caller decides the fallback by choosing the order.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
import sys


@dataclass
class Slot:
    """One place in the network, holding what each system put there.

    A candidate of ``None`` means that system had nothing here — either it never wrote the
    word, or another system wrote one it lacks. Both are votes for the word not existing.
    """

    candidates: list[str | None] = field(default_factory=list)


def _pair(pivot_run: list[str], other_run: list[str]) -> list[str | None]:
    """Line up two unequal runs of words inside one mismatching block.

    Equal lengths pair off. Otherwise the whole of the other system's run is put against the
    first pivot word and the rest are left empty: crude, but it keeps the network aligned and
    never silently drops a word.
    """
    if len(pivot_run) == len(other_run):
        return list(other_run)
    joined = " ".join(other_run) or None
    return [joined] + [None] * (len(pivot_run) - 1)


def confusion_network(transcripts: list[list[str]]) -> list[Slot]:
    """Align every transcript onto the first, one slot per word of the result."""
    if not transcripts:
        return []
    pivot = transcripts[0]
    # Slots for the pivot's own words, plus a bucket before each one for words only other
    # systems heard. Insertions live in their own slots so they can be voted on too.
    at: list[list[str | None]] = [[w] for w in pivot]
    before: list[dict[int, str]] = [{} for _ in range(len(pivot) + 1)]

    for number, other in enumerate(transcripts[1:], start=1):
        seen: list[str | None] = [None] * len(pivot)
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, pivot, other, autojunk=False).get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    seen[i1 + k] = other[j1 + k]
            elif tag == "replace":
                for k, word in enumerate(_pair(pivot[i1:i2], other[j1:j2])):
                    seen[i1 + k] = word
            elif tag == "insert":
                before[i1][number] = " ".join(other[j1:j2])
            # "delete" leaves None, which is this system voting the word away.
        for i, word in enumerate(seen):
            at[i].append(word)

    count = len(transcripts)
    slots: list[Slot] = []
    for i in range(len(pivot) + 1):
        if before[i]:
            row: list[str | None] = [None] * count
            for number, words in before[i].items():
                row[number] = words
            slots.append(Slot(candidates=row))
        if i < len(pivot):
            slots.append(Slot(candidates=at[i]))
    return slots


def select(transcripts: list[list[str]], weights: list[float] | None = None) -> list[str]:
    """Vote in every slot and return the chosen words.

    A tie is settled by weight, and then by the order the transcripts were given, so the
    first transcript is the fallback everywhere the others do not outvote it.
    """
    if len(transcripts) == 1:
        return list(transcripts[0])
    weights = weights or [1.0] * len(transcripts)
    if len(weights) != len(transcripts):
        raise ValueError("one weight per transcript")

    chosen: list[str] = []
    for slot in confusion_network(transcripts):
        tally: dict[str | None, float] = {}
        first: dict[str | None, int] = {}
        for number, word in enumerate(slot.candidates):
            tally[word] = tally.get(word, 0.0) + weights[number]
            first.setdefault(word, number)
        winner = min(tally, key=lambda w: (-tally[w], first[w]))
        if winner:
            chosen += winner.split()
    return chosen


def overrule_where_confident(base: list[str], other: list[str], confidence: list[float],
                             threshold: float) -> list[str]:
    """Keep the base transcript, except where a challenger is confident it heard differently.

    Plain voting could not improve on the best single system, because it has no way to tell
    two systems agreeing on the right answer from two agreeing on the wrong one. A per-word
    confidence is that missing signal. On the Melbourne reference Whisper's own probability
    separates 49.6% correct in its lowest quarter from 98.5% in its highest, and using it
    here took English error from 17.8% to 15.1% — the best local result measured.

    ``confidence`` is one value per token of ``other``. A stretch the challenger simply lacks
    is never taken: silence is not evidence, so the base is never shortened on confidence
    alone.
    """
    if len(confidence) != len(other):
        raise ValueError("one confidence per word of the challenger")
    chosen: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
        if tag == "equal" or tag == "delete":
            chosen += base[i1:i2]
            continue
        window = confidence[j1:j2]
        sure = bool(window) and sum(window) / len(window) >= threshold
        chosen += other[j1:j2] if sure else base[i1:i2]
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="where to write the chosen transcript")
    parser.add_argument("transcripts", nargs="+", type=Path,
                        help="two or more transcripts; the first is the fallback")
    parser.add_argument("--weights", help="comma-separated, one per transcript")
    args = parser.parse_args(argv)

    texts = [p.read_text(encoding="utf-8").split() for p in args.transcripts]
    weights = [float(w) for w in args.weights.split(",")] if args.weights else None
    chosen = select(texts, weights)
    args.out.write_text(" ".join(chosen), encoding="utf-8")
    sizes = ", ".join(f"{p.stem}={len(t)}" for p, t in zip(args.transcripts, texts))
    print(f"{len(chosen)} words chosen from {len(texts)} transcripts ({sizes}) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
