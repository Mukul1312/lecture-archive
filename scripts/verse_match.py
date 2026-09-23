"""Find the printed verse behind a garbled recognition.

    python scripts/verse_match.py --verses VERSES.txt --hypothesis "upaja prapanna asmiyangri"

Speech recognition cannot read this archive's Sanskrit. Whisper has **zero hours** of Sanskrit
transcription training data, and models fine-tuned on Sanskrit *prose* still score 99-110% WER
on chanted verse. But 54% of the Sanskrit words in this corpus sit in runs of three or more:
they are quotations, and quotations have fixed printed text.

So the question is not "what did he say" but "which verse is this" — a closed-set retrieval,
not an open-set transcription. The published prior art is emphatic: a Quranic verse finder
reaches 100% verse retrieval at 2.5% false positives from a 10.1%-WER transcript, and a
Gregorian chant pipeline goes 24.1% CER to 3.8% by matching against a database.

Two design commitments, both from that literature:

* **Match on a phonetic skeleton, not on letters.** A recogniser confuses exactly what is
  confusable — aspirates, sibilants, retroflex against dental, v against b, long vowels
  against short — and sandhi makes word boundaries meaningless. Folding those away first is
  what lets a 50%-wrong hypothesis still find its verse.
* **Refuse rather than guess.** A match must beat the runner-up by a margin or nothing is
  returned. For an archive of somebody's teaching, a confidently wrong verse of scripture is
  far worse than an admitted gap.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

# The confusions a recogniser actually makes on chanted Sanskrit, applied longest first so
# that "chh" folds before "ch". Everything collapses towards the plainest possible letter.
_FOLD = (
    ("chh", "c"), ("sh", "s"), ("ch", "c"), ("kh", "k"), ("gh", "g"), ("th", "t"),
    ("dh", "d"), ("ph", "p"), ("bh", "b"), ("jh", "j"), ("ss", "s"), ("nn", "n"),
    ("mm", "m"), ("ee", "i"), ("oo", "u"), ("aa", "a"), ("ii", "i"), ("uu", "u"),
    ("w", "b"), ("v", "b"), ("y", "i"), ("z", "j"), ("q", "k"), ("x", "ks"),
)
_VOWELS = str.maketrans({"e": "i", "o": "u"})


def skeleton(text: str) -> str:
    """Reduce a phrase to what survives being chanted and misheard.

    Diacritics go, then the confusable consonant pairs, then doubled letters, then spacing —
    because sandhi fuses words and no recogniser's word boundaries can be trusted here.
    """
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    plain = re.sub(r"[^a-z]+", " ", plain.lower())
    for source, target in _FOLD:
        plain = plain.replace(source, target)
    plain = plain.translate(_VOWELS)
    # Vowels go last, and they are most of what was left: in the folded text "a" alone was 27%
    # of all characters and "i" another 14%, so two letters that discriminate almost nothing
    # were carrying 41% of the signal. Dropping them raised the mean margin between the right
    # verse and the runner-up from 0.245 to 0.286 at identical recall — and margin, not score,
    # is what survives the corpus growing from 59 verses to 20,000.
    plain = re.sub(r"[aeiou]", "", plain)
    out: list[str] = []
    for ch in plain.replace(" ", ""):
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _grams(text: str, size: int = 3) -> Counter:
    return Counter(text[i:i + size] for i in range(len(text) - size + 1))


def _similarity(a: Counter, b: Counter) -> float:
    """How much of the shorter profile the longer one accounts for.

    Containment rather than Jaccard, because a heard fragment is often only part of the verse
    and should not be punished for the half he did not finish.
    """
    if not a or not b:
        return 0.0
    shared = sum((a & b).values())
    return shared / min(sum(a.values()), sum(b.values()))


@dataclass
class Match:
    """A verse the index is willing to stand behind."""

    verse: str
    score: float
    margin: float          # how far ahead of the next best verse
    index: int


class VerseIndex:
    """A corpus of printed verses, searchable by a garbled recognition of one."""

    def __init__(self, verses: list[str], gram: int = 3) -> None:
        self.verses = list(verses)
        self.gram = gram
        self._profiles = [_grams(skeleton(v), gram) for v in self.verses]

    def __len__(self) -> int:
        return len(self.verses)

    def rank(self, heard: str, top: int = 5) -> list[Match]:
        """Every verse, best first. Useful for inspecting why a match was or was not made."""
        profile = _grams(skeleton(heard), self.gram)
        if not profile or not self._profiles:
            return []
        scored = sorted(((_similarity(profile, p), i) for i, p in enumerate(self._profiles)),
                        key=lambda pair: (-pair[0], pair[1]))
        best = scored[0][0]
        return [Match(self.verses[i], score, score - (scored[1][0] if len(scored) > 1 else 0.0)
                      if score == best else 0.0, i)
                for score, i in scored[:top]]

    def find(self, heard: str, min_score: float = 0.30, min_margin: float = 0.25) -> Match | None:
        """The verse this is, or nothing.

        ``min_score`` is how much of the hypothesis must be accounted for before any verse is
        credible at all; ``min_margin`` is how far it must beat the runner-up. Both exist so
        the index can decline, which for scripture matters more than coverage.

        Measured on the Melbourne reference — 59 verse lines, three local recognisers, taking
        whichever retrieved most confidently — the margin is the lever that matters:

        | min_margin | attempted | wrong | precision | recall |
        |-----------:|----------:|------:|----------:|-------:|
        |       0.05 |        45 |     7 |       84% |    64% |
        |       0.10 |        41 |     6 |       85% |    59% |
        |       0.15 |        36 |     1 |       97% |    59% |
        |       0.25 |        34 |     0 |      100% |    58% |

        **The default is 0.25: never wrong, 58% of verses recovered.** Dropping vowels from the
        skeleton is what made that affordable — before it, being never wrong cost all but 47%.
        For an archive of somebody's teaching, a verse of scripture attributed to him wrongly is
        not worth three extra verses recovered, so the strict end is the right default and the
        caller lowers it deliberately.
        """
        ranked = self.rank(heard, top=2)
        if not ranked:
            return None
        best = ranked[0]
        if best.score < min_score or best.margin < min_margin:
            return None
        return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verses", required=True, type=Path, help="one printed verse per line")
    parser.add_argument("--hypothesis", required=True, help="what the recogniser heard")
    parser.add_argument("--min-score", type=float, default=0.30)
    parser.add_argument("--min-margin", type=float, default=0.25)
    parser.add_argument("--show", type=int, default=3, help="how many candidates to print")
    args = parser.parse_args(argv)

    verses = [v.strip() for v in args.verses.read_text(encoding="utf-8").splitlines() if v.strip()]
    index = VerseIndex(verses)
    found = index.find(args.hypothesis, args.min_score, args.min_margin)
    print(f"heard: {args.hypothesis}")
    print(f"index: {len(index)} verses\n")
    for candidate in index.rank(args.hypothesis, args.show):
        print(f"  {candidate.score:.3f}  {candidate.verse[:90]}")
    print()
    print(f"-> {found.verse}" if found else "-> unclear (no verse met the threshold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
