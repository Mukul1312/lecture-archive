"""Does the forced aligner put words where the recognisers heard them?

There are no hand-marked word onsets for this lecture yet, so the aligner cannot be scored
against truth. What exists is four systems that emitted word timestamps of their own -
Whisper, Deepgram, ElevenLabs and Sarvam - on the same audio. They are not truth either: they
disagree with each other, and Whisper's timings come from dynamic time warping over
cross-attention, which is known to drift. But they are four independent opinions, and a forced
aligner that agrees with all four is very unlikely to be wrong by much, while one that
disagrees with all four is very unlikely to be right.

So this measures agreement, and says agreement rather than accuracy. The claim it can support
is bounded: it can show the aligner is not broken, and it can show where it is least trusted.
It cannot establish the aligner is accurate to a given tolerance - that needs the hand-marked
onsets, which remain the honest next step.

One trap sits under all of it. The bake-off decoded a *cut* of the lecture, eleven pieces with
205.6 seconds removed, so every one of those timestamps is on a spliced clock. `CutMap` puts
them back. Getting that wrong would not look like a bug; it would look like the aligner
disagreeing with four independent systems.

    python scripts/timing_check.py WORD-TIMINGS.json
"""

from __future__ import annotations

import json
import statistics as st
import sys
from bisect import bisect_right
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from scripts.transcript_accuracy import fold, has_diacritics, indic_language

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BAKEOFF = REPO / "data/reference/bakeoff"

# Every system in the bake-off that emitted word-level times, on the cut audio.
TIMED_SYSTEMS = {
    "whisper medium": "whisper-medium-noskip.jsonl",
    "Deepgram nova-3": "deepgram-nova3-en-in.jsonl",
    "ElevenLabs scribe v2": "elevenlabs-scribe-v2-keyterms50.jsonl",
    "Sarvam saaras v4": "sarvam-saaras-v4-verbatim-keyterms50.jsonl",
}


class CutMap:
    """Cut-audio time back to recording time.

    The cut is a concatenation of kept pieces, so cut time advances continuously while
    recording time jumps at every splice. A time at a piece boundary belongs to the piece
    beginning there, and a time past the end is clamped rather than extrapolated - extrapolating
    would invent a moment that was removed from the cut and so was never decoded.
    """

    def __init__(self, keep: list[list[float]]) -> None:
        self.keep = [(float(a), float(b)) for a, b in keep]
        self.starts: list[float] = []   # where each piece begins in CUT time
        at = 0.0
        for start, end in self.keep:
            self.starts.append(at)
            at += end - start
        self.duration = at

    def to_original(self, when: float) -> float:
        if when <= 0:
            return self.keep[0][0]
        if when >= self.duration:
            return self.keep[-1][1]
        piece = bisect_right(self.starts, when) - 1
        return self.keep[piece][0] + (when - self.starts[piece])


@dataclass
class Agreement:
    system: str
    language: str
    deltas: list[float]


def onset_deltas(ours: list[tuple[str, float]], theirs: list[tuple[str, float]],
                 languages: list[str]) -> dict[str, list[float]]:
    """Signed onset differences for words two sources agree on, grouped by language.

    Matching is by text, not position: both sides misheard plenty, and a word only counts when
    the sequence aligner pairs it one to one. That keeps the measurement to words where "the
    same word" is a claim worth making.
    """
    matcher = SequenceMatcher(None, [w for w, _ in ours], [w for w, _ in theirs], autojunk=False)
    by_language: dict[str, list[float]] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for step in range(i2 - i1):
            by_language.setdefault(languages[i1 + step], []).append(
                ours[i1 + step][1] - theirs[j1 + step][1])
    return by_language


def language_of(word: str, line: str) -> str:
    """English, or which Indic language - the split AGENTS.md requires us to keep apart."""
    if not has_diacritics(word):
        return "english"
    return indic_language(line)


def load_words(path: Path, cut: CutMap) -> list[dict]:
    """A system's words, with times moved from the spliced clock to the recording's."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        word = json.loads(line)
        if word.get("s") is None:
            continue
        out.append({"w": word["w"], "s": cut.to_original(float(word["s"]))})
    return out


def compare(timings: dict, cut: CutMap) -> tuple[list[Agreement], list[Agreement]]:
    """How far the aligner sits from each system, and how far the systems sit from each other.

    The second half is the control, and it is what makes the first half readable. These four
    systems disagree with one another by some amount that has nothing to do with us; until that
    amount is known, a number for the aligner means nothing. If the systems agree among
    themselves to a twentieth of a second and the aligner is half a second out, the fault is
    ours. If they only agree to half a second, the aligner is in normal company.
    """
    ours, languages = [], []
    for cue in timings["cues"]:
        line = " ".join(w["word"] for w in cue["words"])
        for word in cue["words"]:
            folded = fold(word["word"])
            if len(folded) != 1:          # a token the scorer would not count either
                continue
            ours.append((folded[0], word["start"]))
            languages.append(language_of(word["word"], line))

    systems = {}
    for name, filename in TIMED_SYSTEMS.items():
        path = BAKEOFF / filename
        if path.exists():
            systems[name] = [(fold(w["w"])[0], w["s"]) for w in load_words(path, cut)
                             if len(fold(w["w"])) == 1]

    against_us = [Agreement(name, language, deltas)
                  for name, theirs in systems.items()
                  for language, deltas in onset_deltas(ours, theirs, languages).items()]

    # For the control the languages must be labelled on the first system's own words, since the
    # reference is not one of the two being compared.
    among_them = []
    names = list(systems)
    for first in range(len(names)):
        for second in range(first + 1, len(names)):
            a, b = systems[names[first]], systems[names[second]]
            labels = ["english"] * len(a)   # the control is about clock agreement, not language
            for language, deltas in onset_deltas(a, b, labels).items():
                among_them.append(Agreement(f"{names[first]} vs {names[second]}",
                                            language, deltas))
    return against_us, among_them


def summarise(deltas: list[float]) -> str:
    absolute = sorted(abs(d) for d in deltas)
    within = lambda t: sum(1 for d in absolute if d <= t) / len(absolute)
    return (f"{len(absolute):>7}{st.median(absolute):>9.2f}{st.median(deltas):>+9.2f}"
            f"{within(0.1):>9.0%}{within(0.2):>8.0%}{within(0.5):>8.0%}{within(1.0):>8.0%}")


HEADER = (f"{'':34}{'words':>7}{'|med|':>9}{'bias':>9}"
          f"{'<=0.1s':>9}{'<=0.2s':>8}{'<=0.5s':>8}{'<=1s':>8}")


def report(against_us: list[Agreement], among_them: list[Agreement]) -> None:
    print("THE ALIGNER against each system that emits its own word times\n")
    print(HEADER)
    for language in ("english", "sanskrit", "bengali"):
        for row in against_us:
            if row.language == language and row.deltas:
                print(f"{row.system:24}{row.language:10}{summarise(row.deltas)}")

    print("\nTHE CONTROL - the same systems against each other, all languages together")
    print("(how much they disagree among themselves, with no aligner involved)\n")
    print(HEADER)
    for row in among_them:
        if row.deltas:
            print(f"{row.system:34}{summarise(row.deltas)}")


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    timings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cut = CutMap(json.loads((REPO / "data/reference/melbourne-cut.json")
                            .read_text(encoding="utf-8"))["keep"])
    report(*compare(timings, cut))


if __name__ == "__main__":
    main()
