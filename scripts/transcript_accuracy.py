"""Score a machine transcript against a human-verified reference.

    python scripts/transcript_accuracy.py --review REVIEW.json --words WORDS.jsonl \
        --retime-report RETIME.json [--json OUT.json]

The reference is a finished reference-editor review (the words a listener confirmed).
The hypothesis is recognised words, restricted to the reference's span and with the
stretches the subtitles never covered removed, so speech nobody transcribed is not
counted as invented words.

Two tracks are reported because they measure different things:

* English words are strict: a different word is an error.
* Sanskrit and names — written with diacritics in the reference and in rough
  romanisation by the recogniser — are scored by closeness. "śrī" heard as "shri"
  is recognition, not an error; only a word a reader could not recognise counts.

``expand_contractions``, ``join_orphan_clitics`` and ``strip_speaker_label`` repair
differences of *writing* that were being counted as differences of *hearing*. They are
offered here but not applied by this command line, because the runs it has already scored
(the Whisper matrix) were measured without them; the Melbourne bake-off applies all three
through ``data/reference/melbourne_bakeoff.normalise``. Figures from the two are therefore
not directly comparable — see ``docs/error-text-analysis-2026-09-23.md``.
"""

from __future__ import annotations

import argparse
import bisect
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys
import unicodedata


FILLERS = {"um", "uh", "er", "erm", "mm", "hmm", "mhm", "ah", "eh"}
NEAR_MATCH_RATIO = 0.8
# Romanisation differences that carry no meaning: aspirates, sibilants, v/w/b, doubled letters.
_SKELETON = ((("sh", "s"), ("ch", "c"), ("kh", "k"), ("gh", "g"), ("th", "t"), ("dh", "d"),
              ("ph", "p"), ("bh", "b"), ("jh", "j"), ("ee", "i"), ("oo", "u"), ("w", "b"), ("v", "b")))


# Contractions carry no difference of hearing: a corrector does not stop at "he's" for
# "he is". Both sides are expanded the same way, so the ambiguous ones ("'s" as a
# possessive, "'d" as had or would) turn into the same odd text on both sides and
# never score as an error.
_CONTRACTIONS = ((r"n[’']t\b", " not"), (r"[’']ll\b", " will"), (r"[’']ve\b", " have"),
                 (r"[’']re\b", " are"), (r"[’']m\b", " am"), (r"[’']s\b", " is"),
                 (r"[’']d\b", " would"))
# Words that begin a line and end in a colon without anyone being named: he reads these aloud.
_NOT_SPEAKERS = {"translation", "purport", "synonyms", "note", "text", "verse", "chapter"}
_SPEAKER = re.compile(r"^\s*([A-Z][\w.]*(?: [A-Z][\w.]*){0,3})\s*:\s*")


def expand_contractions(text: str) -> str:
    """Write contractions out in full, the same way in the reference and in the transcript."""
    for pattern, replacement in _CONTRACTIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def strip_speaker_label(text: str) -> str:
    """Remove a leading "Name:" from a subtitle cue - a note about who speaks, not speech."""
    match = _SPEAKER.match(text)
    if match and match.group(1).lower() not in _NOT_SPEAKERS:
        return text[match.end():]
    return text


# Some recognisers write the clitic as a word of its own ("isn t", "he ll"). That is a
# defect one regular expression repairs, not a word misheard, so it is normalised in the
# same spirit as digits and bracketed annotations. The reference has already been
# expanded above and contains none of these, so the rule only reaches the transcript.
def join_orphan_clitics(text: str) -> str:
    """Repair contractions a recogniser split into two words."""
    text = re.sub(r"\b(\w+)n t\b", r"\1 not", text, flags=re.IGNORECASE)
    for short, long in (("ll", "will"), ("ve", "have"), ("re", "are"),
                        ("m", "am"), ("s", "is"), ("d", "would")):
        text = re.sub(r"(?<=\w )" + short + r"\b", long, text, flags=re.IGNORECASE)
    return text


def fold(text: str) -> list[str]:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return [t for t in re.sub(r"[^a-z0-9' ]+", " ", plain.lower()).split() if t not in FILLERS]


def has_diacritics(word: str) -> bool:
    """True when the verified text wrote this word in IAST — a Sanskrit word or a name."""
    return any(unicodedata.combining(c) for c in unicodedata.normalize("NFKD", word))


def skeleton(token: str) -> str:
    text = token
    for source, target in _SKELETON:
        text = text.replace(source, target)
    out = []
    for ch in text:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def recognisable(reference_token: str, heard_token: str) -> bool:
    """Would a reader recognise the heard word as the reference word?"""
    if reference_token == heard_token:
        return True
    if SequenceMatcher(None, reference_token, heard_token).ratio() >= NEAR_MATCH_RATIO:
        return True
    a, b = skeleton(reference_token), skeleton(heard_token)
    return a == b or SequenceMatcher(None, a, b).ratio() >= NEAR_MATCH_RATIO


def _rescue_near_matches(reference: list[str], is_indic: list[bool], hypothesis: list[str],
                         i1: int, i2: int, j1: int, j2: int) -> set[int]:
    """Within one mismatching block, find Sanskrit/name positions that were recognisably heard.

    Only the Sanskrit track is forgiven: English stays strict, so a homophone such as
    "soles" heard as "souls" remains an error.
    """
    rescued, taken = set(), set()
    for i in range(i1, i2):
        if not is_indic[i]:
            continue
        for j in range(j1, j2):
            if j not in taken and recognisable(reference[i], hypothesis[j]):
                rescued.add(i)
                taken.add(j)
                break
    return rescued


def score(reference: list[str], is_indic: list[bool], hypothesis: list[str]) -> dict:
    matcher = SequenceMatcher(None, reference, hypothesis, autojunk=False)
    tally = {
        "reference_words": len(reference), "hypothesis_words": len(hypothesis),
        "exact": 0, "near": 0, "wrong": 0, "missing": 0, "inserted": 0,
        "english": {"words": 0, "exact": 0, "near": 0, "errors": 0},
        "indic": {"words": 0, "exact": 0, "near": 0, "errors": 0},
        "examples_wrong": [], "examples_near": [],
    }
    def note(index: int, kind: str) -> None:
        track = tally["indic" if is_indic[index] else "english"]
        track["words"] += 1
        track[kind] = track.get(kind, 0) + 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            tally["exact"] += i2 - i1
            for i in range(i1, i2):
                note(i, "exact")
            continue
        if tag == "insert":
            tally["inserted"] += j2 - j1
            continue
        rescued = _rescue_near_matches(reference, is_indic, hypothesis, i1, i2, j1, j2) if tag == "replace" else set()
        for i in rescued:
            tally["near"] += 1
            note(i, "near")
            if len(tally["examples_near"]) < 10:
                tally["examples_near"].append(reference[i])
        # What is left of the block after recognisable romanisations: substitutions first,
        # then whichever side has words to spare becomes missing or invented words.
        remaining_reference = (i2 - i1) - len(rescued)
        remaining_heard = (j2 - j1) - len(rescued)
        tally["wrong"] += min(remaining_reference, remaining_heard)
        tally["missing"] += max(0, remaining_reference - remaining_heard)
        tally["inserted"] += max(0, remaining_heard - remaining_reference)
        for i in range(i1, i2):
            if i not in rescued:
                note(i, "errors")
        if tag == "replace" and remaining_reference and len(tally["examples_wrong"]) < 12 and i2 - i1 <= 4:
            unrescued = [reference[i] for i in range(i1, i2) if i not in rescued]
            tally["examples_wrong"].append((" ".join(unrescued), " ".join(hypothesis[j1:j2])))
    return tally


@dataclass
class EditSite:
    """One place a corrector must stop and type: a contiguous stretch got wrong.

    This, not the error-word count, is what tracks correction time: five words lost in
    one breath is one stop, five words lost apart is five. The surrounding reference
    words travel with the site so a reader can judge it without opening the audio.
    """

    index: int                  # where in the reference the stop begins
    kind: str                   # "wrong" | "dropped" | "invented"
    reference: list[str]        # what he said, minus romanisations a reader would accept
    heard: list[str]            # what the recogniser wrote here
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    sanskrit_distance: int = 999   # words to the nearest Sanskrit word or name
    wrong: int = 0
    dropped: int = 0
    invented: int = 0


def _sanskrit_distance(positions: list[int], i1: int, i2: int) -> int:
    if not positions:
        return 999
    best = 999
    for i in range(i1, max(i2, i1 + 1)):
        k = bisect.bisect_left(positions, i)
        for j in (k - 1, k):
            if 0 <= j < len(positions):
                best = min(best, abs(i - positions[j]))
    return best


def edit_sites(reference: list[str], is_indic: list[bool], hypothesis: list[str],
               context: int = 6) -> list[EditSite]:
    """Every place the transcript departs from the reference, as a corrector meets it.

    The counts inside each site match ``score``: the same rescue rule, so the totals
    add up to the same wrong, missing and inserted words.
    """
    positions = [i for i, x in enumerate(is_indic) if x]
    sites = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, reference, hypothesis, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        rescued = _rescue_near_matches(reference, is_indic, hypothesis, i1, i2, j1, j2) if tag == "replace" else set()
        remaining_reference = (i2 - i1) - len(rescued)
        remaining_heard = (j2 - j1) - len(rescued)
        if not remaining_reference and not remaining_heard:
            continue     # only romanisations a reader would accept: nothing to type
        wrong = min(remaining_reference, remaining_heard)
        dropped = max(0, remaining_reference - remaining_heard)
        invented = max(0, remaining_heard - remaining_reference)
        sites.append(EditSite(
            index=i1,
            kind="wrong" if wrong else "dropped" if dropped else "invented",
            reference=[reference[i] for i in range(i1, i2) if i not in rescued],
            heard=list(hypothesis[j1:j2]),
            before=reference[max(0, i1 - context):i1],
            after=reference[i2:i2 + context],
            sanskrit_distance=_sanskrit_distance(positions, i1, i2),
            wrong=wrong, dropped=dropped, invented=invented))
    return sites


def load_reference(review_path: Path) -> tuple[list[str], list[bool], dict]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    reference, is_indic = [], []
    for cue in review["cues"]:
        for raw in cue["text"].split():
            for token in fold(raw):
                reference.append(token)
                is_indic.append(has_diacritics(raw))
    return reference, is_indic, review


def load_hypothesis(words_path: Path, span: tuple[float, float], excluded: list[list[float]],
                    covered: list[tuple[float, float]] = ()) -> list[str]:
    """Heard words inside the span, without speech the subtitles never covered.

    ``excluded`` comes from the re-timing, which could only mark speech that no *matched*
    cue covered. A cue it could not match keeps an interpolated time that can fall inside
    such a stretch, and its reference words are still scored, so heard words inside any
    ``covered`` cue interval are always kept. Dropping them counted every one of that
    cue's words as missing: 16 cues on the Melbourne reference, the Bengali song among them.
    """
    start, end = span
    words = []
    for line in words_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        at = item["s"]
        if not start <= at <= end:
            continue
        in_cue = any(a <= at <= b for a, b in covered)
        if in_cue or not any(a <= at <= b for a, b in excluded):
            words += fold(item["w"])
    return words


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--review", required=True, type=Path, help="finished reference-editor review JSON")
    parser.add_argument("--words", required=True, type=Path, help="recognised words as JSON lines {w, s, e}")
    parser.add_argument("--retime-report", type=Path, help="retime report, for its spoken_but_not_subtitled spans")
    parser.add_argument("--label", default="", help="name for this run in the output")
    parser.add_argument("--json", type=Path, help="also write the result as JSON")
    args = parser.parse_args(argv)

    reference, is_indic, review = load_reference(args.review)
    excluded = json.loads(args.retime_report.read_text(encoding="utf-8"))["spoken_but_not_subtitled"] if args.retime_report else []
    span = (review["cues"][0]["start_ms"] / 1000, review["cues"][-1]["end_ms"] / 1000)
    covered = [(cue["start_ms"] / 1000, cue["end_ms"] / 1000) for cue in review["cues"]]
    hypothesis = load_hypothesis(args.words, span, excluded, covered)
    tally = score(reference, is_indic, hypothesis)

    n = tally["reference_words"]
    errors = tally["wrong"] + tally["missing"] + tally["inserted"]
    english, indic = tally["english"], tally["indic"]
    result = {
        "label": args.label or args.words.name,
        "reference_words": n, "hypothesis_words": tally["hypothesis_words"],
        "wer_strict": round((tally["wrong"] + tally["missing"] + tally["inserted"] + tally["near"]) / n, 4),
        "wer": round(errors / n, 4),
        "english_error_rate": round(english["errors"] / english["words"], 4) if english["words"] else None,
        "indic_error_rate": round(indic["errors"] / indic["words"], 4) if indic["words"] else None,
        "indic_recognised_by_closeness": indic["near"],
        "counts": {k: tally[k] for k in ("exact", "near", "wrong", "missing", "inserted")},
        "english_words": english["words"], "indic_words": indic["words"],
    }
    print(f"{result['label']}")
    print(f"  reference {n} words, heard {tally['hypothesis_words']}")
    print(f"  WER {result['wer']:.1%}   (strict, counting different spellings as errors: {result['wer_strict']:.1%})")
    print(f"  English {english['words']:>5} words: {result['english_error_rate']:.1%} wrong or missing")
    print(f"  Sanskrit/names {indic['words']:>4} words: {result['indic_error_rate']:.1%} unrecognisable "
          f"({indic['exact']} exact, {indic['near']} recognisable romanisations)")
    print(f"  counts: {result['counts']}")
    print("  example errors (reference -> heard):")
    for a, b in tally["examples_wrong"][:8]:
        print(f"    {a!r} -> {b!r}")
    if args.json:
        args.json.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
