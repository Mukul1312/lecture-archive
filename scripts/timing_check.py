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


def compare(timings: dict, cut: CutMap) -> list[Agreement]:
    """Onset differences between the aligner and each system, for words both agree on.

    Matching is by text, not by position: the systems misheard plenty, and a word only counts
    when the sequence aligner pairs it one-to-one with the reference word. That keeps the
    measurement to words where "the same word" is a meaningful claim.
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

    results = []
    for name, filename in TIMED_SYSTEMS.items():
        path = BAKEOFF / filename
        if not path.exists():
            continue
        theirs = []
        for word in load_words(path, cut):
            folded = fold(word["w"])
            if len(folded) == 1:
                theirs.append((folded[0], word["s"]))

        matcher = SequenceMatcher(None, [w for w, _ in ours], [w for w, _ in theirs],
                                  autojunk=False)
        by_language: dict[str, list[float]] = {}
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                continue
            for step in range(i2 - i1):
                delta = ours[i1 + step][1] - theirs[j1 + step][1]
                by_language.setdefault(languages[i1 + step], []).append(delta)
        for language, deltas in by_language.items():
            results.append(Agreement(name, language, deltas))
    return results


def report(results: list[Agreement]) -> None:
    def summarise(deltas: list[float]) -> str:
        absolute = sorted(abs(d) for d in deltas)
        within = lambda t: sum(1 for d in absolute if d <= t) / len(absolute)
        return (f"{len(absolute):>7}{st.median(absolute):>9.2f}{st.median(deltas):>+9.2f}"
                f"{within(0.1):>9.0%}{within(0.2):>8.0%}{within(0.5):>8.0%}{within(1.0):>8.0%}")

    print(f"{'system':24}{'language':10}{'words':>7}{'|med|':>9}{'bias':>9}"
          f"{'<=0.1s':>9}{'<=0.2s':>8}{'<=0.5s':>8}{'<=1s':>8}")
    for language in ("english", "sanskrit", "bengali"):
        for row in results:
            if row.language == language and row.deltas:
                print(f"{row.system:24}{row.language:10}{summarise(row.deltas)}")


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    timings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cut = CutMap(json.loads((REPO / "data/reference/melbourne-cut.json")
                            .read_text(encoding="utf-8"))["keep"])
    report(compare(timings, cut))


if __name__ == "__main__":
    main()
