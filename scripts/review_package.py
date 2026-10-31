"""Build one lecture's review package: everything a devotee reviewer sees, worked out here.

    .venv/Scripts/python.exe -m scripts.review_package bg-3-37-the-duty-of-a-human-being-brisbane

The listening copies are read from a copy of the bucket's `manifests/media-v2.json` kept at
`data/reference/review/manifests/` (Mukul, 30 October 2026); `--media-manifest` names another.

The review app does no language processing (agreed 29 October 2026). Which words differ, what
language each stop is in, where a verse was matched, how long the clip runs - all of it is
decided here, with this repository's own tested code, and written into a package in the format
of `contracts/review/`. The package is checked against the schema and rules P1-P10 before it is
written, and a package that fails is not written at all.

It is written locally, under the gitignored `data/reference/review/packages/`. Uploading it to
`packages/<lecture>/<version>.json` is a separate step that needs the steward's go-ahead.

**Four kinds of stop**, each a question the two sources cannot settle between themselves:

- *word-disagreement* - inside a trustworthy span, the published transcript and ElevenLabs say
  different things. Compared after the scorer's own `normalise`, so a contraction or a number
  written as digits is not a stop: a corrector would not stop there either.
- *verse-check* - a run of the transcript matched a printed verse in `verse-runs.json`. The
  differences inside it are not asked separately; the printed text is the better question.
- *single-version* - outside every trustworthy span, only ElevenLabs has words.
- *agreement-sample* - a few places where both sources wrote exactly the same words, unmarked,
  because agreement is not proof. With `--every-agreed-piece`, every such place instead, cut
  into pieces of up to six words.

**Where the published words cannot be trusted, nothing is compared.** The lecture-level
placement check (`scripts/compare_hosted`) can pass while a stretch of words sits seconds away
from where they were spoken: on BG 3.37 Brisbane it passes at 1.05 against a limit of 1.5 and
still has seventeen such stretches, one with words placed 22 s early. A stop built there plays
the wrong audio. `read_along`'s word check finds them, and they are cut out of the trustworthy
spans, so ElevenLabs's words - which are in the right place - become the single version there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from scripts.compare_hosted import (CONTEXT, MISPLACED_RATIO, overall_error,
                                    score_lecture_by_language, whole_file_error, words_for)
from scripts.forced_align import problems, spoken_words
from scripts.read_along import (AGREE_SECONDS, check_alignment, disagreements, paragraphs,
                                renumber, untranscribed, word_check)
from scripts.review_contract import package_rules, schema_errors
from scripts.scoreable import scoreable_spans
from scripts.transcript_accuracy import (fold, folded_with_marks, has_diacritics, indic_language,
                                          normalise)
from scripts.verse_match import skeleton
from scripts.verse_runs import MAX_BRIDGE_SECONDS, bridgeable

REPO = Path(__file__).resolve().parents[1]
LECTURES = REPO / "data/lectures"
ALIGNED = REPO / "data/reference/analysis/archive-alignment"
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
HOSTED = REPO / "data/reference/analysis/hosted"
VERSES = REPO / "data/reference/analysis/verse-runs.json"
COPIES = REPO / "data/reference/read-along/audio"
OUT = REPO / "data/reference/review/packages"
MEDIA_MANIFEST = REPO / "data/reference/review/manifests/media-v2.json"

FORMAT = "lecture-review-package/1.0"

# The code a package depends on. A package built while any of it has uncommitted changes names a
# commit that does not contain the code that built it, so it is marked a draft in its notes.
PRODUCER_FILES = ("scripts/review_package.py", "scripts/review_contract.py", "contracts/review",
                  "scripts/compare_hosted.py", "scripts/forced_align.py", "scripts/read_along.py",
                  "scripts/scoreable.py", "scripts/transcript_accuracy.py", "scripts/verse_match.py",
                  "scripts/verse_runs.py", "scripts/span_score.py")

# Seconds of audio either side of a stop. Three is about a breath and a half-sentence, enough to
# hear the word arrive; the app's "wider context" plays more.
CONTEXT_SECONDS = 3.0
# Words of text either side, from the same source.
CONTEXT_WORDS = 6
# Differing phrases closer than this are heard in one breath and asked as one stop.
JOIN_SECONDS = 1.0
# The most words a version of one stop may hold, so a stop stays about ten seconds of work.
MAX_STOP_WORDS = 12
# A pause longer than this ends a single-version stop.
SINGLE_PAUSE = 1.0
# A recogniser's word lasting longer than this has not been timed: ElevenLabs stretched
# `Kama.` across 55 s of chanting on BG 3.37 Brisbane. It cannot be placed in a clip, so no
# stop holds it. Five of that lecture's 6,465 words exceed 3 s and only that one exceeds 5.
MAX_WORD_SECONDS = 5.0
# An agreement sample is this many words, and there is one for every AGREEMENT_EVERY word
# disagreements, with at least MIN_AGREEMENT. Proposed, not agreed: the steward decides.
AGREEMENT_WORDS = 6
AGREEMENT_EVERY = 20
MIN_AGREEMENT = 3
# The verse gate `verse_runs` applies by default. A match below it means `verse-runs.json` was
# written with a lower gate, which has admitted a wrong attribution before (see verse_runs.main).
VERSE_MARGIN = 0.25
# A lecture's length, decoded, may differ from the aligner's own figure by its rounding (0.1 s).
ALIGNER_TOLERANCE = 0.1
# Stops that start and end together are ordered by kind.
STOP_ORDER = {"word-disagreement": 0, "verse-check": 1, "agreement-sample": 2, "single-version": 3}


@dataclass
class Word:
    text: str
    start: float | None
    end: float | None

    def __post_init__(self):
        # The format requires NFC (P9), and some transcripts store ṛ as r plus a combining dot.
        # The two are the same text; the scorer folds both to the same tokens.
        self.text = unicodedata.normalize("NFC", self.text)

    @property
    def middle(self) -> float | None:
        return None if self.start is None else (self.start + self.end) / 2


@dataclass
class TrustedSpan:
    start: float
    end: float
    first: int   # published word positions, inclusive
    last: int


@dataclass
class DiffStop:
    """One question about a stretch where the two sources disagree, before it has an id."""

    language: str
    p_lo: int
    p_hi: int
    h_lo: int
    h_hi: int
    published: list[Word] = field(default_factory=list)
    heard: list[Word] = field(default_factory=list)
    differs_published: list[int] = field(default_factory=list)
    differs_heard: list[int] = field(default_factory=list)
    start: float | None = None
    end: float | None = None


def _pieces(word: str):
    """The scorer's tokens for one spoken word, each with whether the word carried diacritics.

    `normalise` is written for a whole transcript, and two of its rules fire only at the start of
    a line: a speaker label and the editor's "not in this audio". Handed one word, the word IS a
    line, so `Prabhupāda:` - the end of "Translation by Śrīla Prabhupāda:" - was dropped as a
    label. These words are already `spoken_words`, so those rules have done their work; a
    leading mark that folds to nothing keeps them from firing a second time.
    """
    for piece in normalise("· " + word).split():
        for token in fold(piece):
            yield token, has_diacritics(piece)


def comparable_tokens(words: list[str]) -> tuple[list[str], list[int], list[bool]]:
    """The scorer's tokens for these words joined, which word each came from, and its mark.

    The tokens are the scorer's own - `folded_with_marks(normalise(text))`, as compare_hosted
    reads a span - because anything else would put a stop where the scorer sees no difference
    or hide one it would charge. Only the way back to the words is worked out here, from the
    words tokenised one at a time. The two agree almost everywhere; where the scorer reads
    across a word boundary they do not - ElevenLabs's stutter `s-` after a word becomes `is` by
    the orphan-clitic repair - and those tokens go to the word they sit in.
    """
    single, single_owner = [], []
    for index, word in enumerate(words):
        for token, _ in _pieces(word):
            single.append(token)
            single_owner.append(index)
    tokens, marks = folded_with_marks(normalise(" ".join(words)))
    if tokens == single:
        return tokens, single_owner, marks
    owners = []
    for _, i1, i2, j1, j2 in SequenceMatcher(None, single, tokens, autojunk=False).get_opcodes():
        for k in range(j2 - j1):
            source = i1 + min(k * (i2 - i1) // (j2 - j1), i2 - i1 - 1) if i2 > i1 else i1 - 1
            owners.append(single_owner[max(0, min(source, len(single_owner) - 1))])
    return tokens, owners, marks


def check_against_scorer(words: list[str]) -> None:
    """Refuse unless these words give exactly the scorer's tokens, and each knows its word."""
    tokens, owners, _ = comparable_tokens(words)
    expected, _ = folded_with_marks(normalise(" ".join(words)))
    if tokens != expected or len(owners) != len(tokens) or owners != sorted(owners):
        raise ValueError("the comparison tokens are not the scorer's for this stretch")


def indic_mask(tokens: list[str], marks: list[bool], context: int = CONTEXT) -> list[str | None]:
    """Sanskrit or Bengali for each Indic token, read from the Indic tokens around it.

    `compare_hosted.language_mask` with one change: only words the editor marked as Indic vote.
    There every word in the window votes, and English `more` is also the Bengali pronoun `more`
    that `indic_language` counts, so on BG 3.37 Brisbane two of the three words it called
    Bengali were Sanskrit - `śreya` and `pūrṇa-vikacita-cetana`, each a few words from "more".
    """
    out: list[str | None] = []
    for index, mark in enumerate(marks):
        if not mark:
            out.append(None)
            continue
        window = [tokens[k] for k in range(max(0, index - context), index + context + 1)
                  if k < len(tokens) and marks[k]]
        out.append(indic_language(" ".join(window)))
    return out


def word_languages(words: list[Word]) -> list[str]:
    """English, Sanskrit or Bengali for each published word.

    The scorer's rule first: a word the editor wrote with diacritics is Indic, and
    `indic_language` reads Sanskrit or Bengali from the Indic words around it. Then one
    repair, `verse_runs`'s own: an unmarked word between two Indic words of one language, close
    in time and not an English function word, belongs to them. Without it `ceha` is English and
    SB 1.2.10 is cut into three stops at `nārtho yaś | ceha | karmabhiḥ`.
    """
    tokens, owners, marks = comparable_tokens([w.text for w in words])
    mask = indic_mask(tokens, marks)
    labels: list[str | None] = [None] * len(words)
    for at, owner in enumerate(owners):
        label = mask[at] if marks[at] else "english"
        if labels[owner] is None or (marks[at] and labels[owner] == "english"):
            labels[owner] = label
    # A word with nothing to compare - a dash - belongs to no language; it takes its neighbour's
    # so that it cannot split a stop.
    for i in range(len(labels)):
        if labels[i] is None:
            labels[i] = labels[i - 1] if i else next((l for l in labels if l), "english")
    bridged = list(labels)
    for i in range(1, len(words) - 1):
        before, after = labels[i - 1], labels[i + 1]
        if (labels[i] == "english" and before == after and before != "english"
                and bridgeable(words[i].text) and words[i - 1].end is not None
                and words[i + 1].start is not None
                and words[i + 1].start - words[i - 1].end <= MAX_BRIDGE_SECONDS):
            bridged[i] = before
    return bridged


def _word_range(owners: list[int], a: int, b: int, count: int) -> tuple[int, int]:
    """Token range [a, b) as a word range [lo, hi); an empty token range keeps its place."""
    if b > a:
        return owners[a], owners[b - 1] + 1
    at = owners[a] if a < len(owners) else count
    return at, at


def differing(published: list[Word], heard: list[Word]) -> tuple[list[int], list[int]]:
    """Positions in each version whose tokens the other version does not share."""
    pt, po, _ = comparable_tokens([w.text for w in published])
    ht, ho, _ = comparable_tokens([w.text for w in heard])
    return _differing(pt, po, ht, ho)


def _differing(pt: list[str], po: list[int], ht: list[str], ho: list[int]) -> tuple[list[int], list[int]]:
    mine, theirs = set(), set()
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, pt, ht, autojunk=False).get_opcodes():
        if tag != "equal":
            mine.update(po[i1:i2])
            theirs.update(ho[j1:j2])
    return sorted(mine), sorted(theirs)


def _times(words: list[Word]) -> tuple[float | None, float | None]:
    timed = [w for w in words if w.start is not None]
    if not timed:
        return None, None
    return min(w.start for w in timed), max(w.end for w in timed)


def _split_by_language(site: DiffStop, languages: list[str], published: list[Word],
                       heard: list[Word]) -> list[DiffStop]:
    """One site per language, the recogniser's words divided where the published ones change.

    The division is in time: halfway across the silence between the last published word of one
    language and the first of the next. Where only the recogniser has words, nothing marks their
    language, so the site is `unknown` rather than guessed from its neighbours.
    """
    if site.p_lo == site.p_hi:
        return [DiffStop("unknown", site.p_lo, site.p_hi, site.h_lo, site.h_hi)]
    groups: list[list[int]] = []
    for at in range(site.p_lo, site.p_hi):
        if groups and languages[groups[-1][-1]] == languages[at]:
            groups[-1].append(at)
        else:
            groups.append([at])
    parts, at = [], site.h_lo
    for g, group in enumerate(groups):
        end = site.h_hi
        if g < len(groups) - 1:
            _, left_end = _times([published[i] for i in group])
            right_start, _ = _times([published[i] for i in groups[g + 1]])
            end = at
            if left_end is not None and right_start is not None:
                boundary = (left_end + right_start) / 2
                while end < site.h_hi and heard[end].middle < boundary:
                    end += 1
        parts.append(DiffStop(languages[group[0]], group[0], group[-1] + 1, at, end))
        at = end
    return parts


def difference_stops(published: list[Word], heard: list[Word], languages: list[str],
                     runs: list[tuple[int, int, float, float]] = ()) -> list[DiffStop]:
    """Every place in one trustworthy span where the two sources disagree, one stop each.

    `languages` labels each published word. `runs` are verse runs, as (first published
    position, one past the last, start, end): their differences belong to a verse check.
    """
    pt, po, _ = comparable_tokens([w.text for w in published])
    ht, ho, _ = comparable_tokens([w.text for w in heard])
    sites: list[DiffStop] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, pt, ht, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        p_lo, p_hi = _word_range(po, i1, i2, len(published))
        h_lo, h_hi = _word_range(ho, j1, j2, len(heard))
        # A word of several tokens can sit in two blocks; it is one place, so one site.
        if sites and p_lo < sites[-1].p_hi:
            sites[-1].p_hi, sites[-1].h_hi = max(sites[-1].p_hi, p_hi), max(sites[-1].h_hi, h_hi)
            continue
        sites.append(DiffStop("", p_lo, p_hi, h_lo, h_hi))

    for r_lo, r_hi, r_start, r_end in runs:
        kept = []
        for site in sites:
            middles = [heard[j].middle for j in range(site.h_lo, site.h_hi)]
            touches = (site.p_lo < r_hi and r_lo < site.p_hi) or (
                site.p_lo == site.p_hi and r_lo <= site.p_lo <= r_hi) or any(
                r_start <= m <= r_end for m in middles)
            if not touches:
                kept.append(site)
                continue
            # What lies before the run and what lies after it stay questions of their own.
            last_before = site.h_lo + sum(1 for m in middles if m < r_start)
            first_after = site.h_lo + sum(1 for m in middles if m <= r_end)
            cut_before = max(site.p_lo, min(site.p_hi, r_lo))
            cut_after = min(site.p_hi, max(site.p_lo, r_hi))
            before = DiffStop("", site.p_lo, cut_before, site.h_lo, last_before)
            after = DiffStop("", cut_after, site.p_hi, first_after, site.h_hi)
            kept += [part for part in (before, after)
                     if part.p_hi > part.p_lo or part.h_hi > part.h_lo]
        sites = kept

    split = [part for site in sites
             for part in _split_by_language(site, languages, published, heard)]

    def fill(site: DiffStop) -> None:
        # The stop's own words, compared on the span's tokens: a fragment re-read on its own
        # would not be what the scorer read (`s-` is `is` only after the word before it).
        site.published = published[site.p_lo:site.p_hi]
        site.heard = heard[site.h_lo:site.h_hi]
        mine = [k for k, o in enumerate(po) if site.p_lo <= o < site.p_hi]
        theirs = [k for k, o in enumerate(ho) if site.h_lo <= o < site.h_hi]
        site.differs_published, site.differs_heard = _differing(
            [pt[k] for k in mine], [po[k] - site.p_lo for k in mine],
            [ht[k] for k in theirs], [ho[k] - site.h_lo for k in theirs])
        site.start, site.end = _times(site.published + site.heard)

    stops: list[DiffStop] = []
    for site in split:
        fill(site)
        if not (site.differs_published or site.differs_heard):
            continue
        previous = stops[-1] if stops else None
        if previous is not None and _joinable(previous, site, published, languages):
            merged = DiffStop(site.language, previous.p_lo, max(previous.p_hi, site.p_hi),
                              previous.h_lo, max(previous.h_hi, site.h_hi))
            fill(merged)
            stops[-1] = merged
            continue
        stops.append(site)
    for stop in stops:
        if stop.start is None:
            stop.start, stop.end = _neighbour_times(published, stop.p_lo, stop.p_hi)
    return stops


def _joinable(a: DiffStop, b: DiffStop, published: list[Word], languages: list[str]) -> bool:
    """Heard in one breath, the same language throughout, and still a short question."""
    if a.language != b.language or a.end is None or b.start is None:
        return False
    if b.start - a.end >= JOIN_SECONDS:
        return False
    between = languages[a.p_lo:max(a.p_hi, b.p_hi)]
    if a.language == "unknown" and between:
        return False
    if any(label != a.language for label in between):
        return False
    return (max(a.p_hi, b.p_hi) - a.p_lo <= MAX_STOP_WORDS
            and max(a.h_hi, b.h_hi) - a.h_lo <= MAX_STOP_WORDS)


def _neighbour_times(published: list[Word], lo: int, hi: int) -> tuple[float | None, float | None]:
    """For a stop with no timed word: from the end of the word before to the start of the next."""
    before = next((w.end for w in reversed(published[:lo]) if w.end is not None), None)
    after = next((w.start for w in published[hi:] if w.start is not None), None)
    if before is None or after is None or not before < after:
        return None, None
    return before, after


def trusted_spans(timed: list[dict], misplaced: list[list]) -> list[TrustedSpan]:
    """The scoreable spans, with every stretch of misplaced words taken out.

    A span is still built by `scoreable.scoreable_spans` - word to word, breaking at a silence
    longer than any real pause - but over the words that were not found away from where the
    recogniser heard them. A misplaced word ends a run as a long silence would.
    """
    runs: list[list[dict]] = [[]]
    for word in sorted(timed, key=lambda w: w["index"]):
        if any(word["start"] < b and a < word["end"] for a, b, _ in misplaced):
            runs.append([])
        else:
            runs[-1].append(word)
    spans = []
    for run in runs:
        at = 0
        for span in scoreable_spans(run):
            while run[at]["start"] != span.start:
                at += 1
            spans.append(TrustedSpan(span.start, span.end, run[at]["index"],
                                     run[at + len(span.words) - 1]["index"]))
            at += len(span.words)
    return spans


def clip(start: float, end: float, duration: float) -> tuple[float, float]:
    """The audio a reviewer hears for a stop: a few seconds either side, inside the recording."""
    return round(max(0.0, start - CONTEXT_SECONDS), 3), round(min(duration, end + CONTEXT_SECONDS), 3)


def span_manifest_is_current(stored: list[dict], entry: dict) -> bool:
    """Does the span manifest describe this alignment, or is every span in it someone else's?

    Checked against the alignment as stored, which is what `scripts.scoreable` reads. Spans
    recomputed after `renumber` drops editorial notes can split where the notes were, and differ
    from a manifest that is current.
    """
    fresh = scoreable_spans(stored)
    return len(fresh) == len(entry["spans_detail"]) and all(
        abs(a.start - b["start"]) <= 0.01 and abs(a.end - b["end"]) <= 0.01
        for a, b in zip(fresh, entry["spans_detail"]))


def out_of_earshot(start: float, end: float, taken: list[tuple[float, float]]) -> bool:
    """Is a stretch far enough from every stop that neither one's clip plays the other's words?

    An agreement sample is shown as one text. One heard inside a disagreement's clip, or with that
    disagreement among its context words, is no longer one text and gives itself away.
    """
    return not any(start - CONTEXT_SECONDS < t_end and t_start < end + CONTEXT_SECONDS
                   for t_start, t_end in taken)


def recited(printed: list[str], heard: list[str]) -> list[int]:
    """Which printed words appear to have been recited, as a suggestion only.

    Compared on `verse_match.skeleton`, the matcher's own folding, letter by letter: sandhi
    joins and splits words differently in print and in a transcript (`yaśceha`, `yaś ceha`), so
    words cannot be paired one to one. A printed word counts when most of its skeleton was heard
    in order. The app neither shows this nor pre-ticks it; reviewers tick what they hear.
    """
    letters, owner = [], []
    for index, word in enumerate(printed):
        for letter in skeleton(word):
            letters.append(letter)
            owner.append(index)
    matcher = SequenceMatcher(None, "".join(letters), skeleton(" ".join(heard)), autojunk=False)
    hits = Counter()
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            hits[owner[block.a + k]] += 1
    sizes = Counter(owner)
    return [i for i in range(len(printed)) if sizes[i] and hits[i] / sizes[i] >= 0.5]


def agreement_windows(published: list[Word], heard: list[Word], languages: list[str],
                      size: int = AGREEMENT_WORDS) -> list[tuple[int, int, int]]:
    """Places where both sources wrote exactly the same words, as (p_lo, p_hi, h_lo).

    Exactly, punctuation and spelling included: the app shows an agreement sample as one text,
    and two versions that differ would have one of them hidden.
    """
    matcher = SequenceMatcher(None, [w.text for w in published], [w.text for w in heard],
                              autojunk=False)
    found = []
    for block in matcher.get_matching_blocks():
        for k in range(0, block.size - size + 1, size):
            a, h = block.a + k, block.b + k
            if (all(w.start is not None for w in published[a:a + size])
                    and len(set(languages[a:a + size])) == 1 and languages[a] != "unknown"):
                found.append((a, a + size, h))
    return found


def identical_pairs(published: list[Word], heard: list[Word],
                    spans: list[TrustedSpan]) -> dict[int, int]:
    """Each published word in a span, paired with the ElevenLabs word written exactly like it.

    Compared span by span, as `agreement_windows` compares, so a pair never crosses a span.
    """
    pairs = {}
    for span in spans:
        near = [j for j, w in enumerate(heard) if span.start <= w.middle < span.end]
        if not near:
            continue
        p_lo, h_lo = span.first, near[0]
        matcher = SequenceMatcher(None, [w.text for w in published[p_lo:span.last + 1]],
                                  [w.text for w in heard[h_lo:near[-1] + 1]], autojunk=False)
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                pairs[p_lo + block.a + k] = h_lo + block.b + k
    return pairs


def agreed_pieces(published: list[Word], heard: list[Word], languages: list[str],
                  spans: list[TrustedSpan], taken_p: set[int], taken_h: set[int],
                  size: int = AGREEMENT_WORDS) -> list[tuple[int, int, int, int]]:
    """Every agreed word both sources wrote exactly alike, cut into pieces, as (p_lo, p_hi, h_lo, h_hi).

    A piece is at most `size` words in one language, inside one span, timed, and holds no word
    of another stop on either side (`taken_p`, `taken_h`); the last piece of a run may be
    shorter. A pair heard more than `AGREE_SECONDS` apart is not asked: matching text alone once
    paired `ei` with another occurrence 25 s away, and a piece is one clip. Nor is a recogniser
    word lasting longer than any word does, since it cannot be placed in a clip.
    """
    pairs = identical_pairs(published, heard, spans)

    def askable(i: int) -> bool:
        j = pairs.get(i)
        return (j is not None and i not in taken_p and j not in taken_h
                and published[i].start is not None and languages[i] != "unknown"
                and heard[j].end - heard[j].start <= MAX_WORD_SECONDS
                and abs(published[i].middle - heard[j].middle) <= AGREE_SECONDS)

    pieces, piece = [], []

    def close() -> None:
        if piece:
            pieces.append((piece[0], piece[-1] + 1, pairs[piece[0]], pairs[piece[-1]] + 1))
            piece.clear()

    for span in spans:
        for i in range(span.first, span.last + 1):
            if not askable(i):
                close()
                continue
            if piece and (pairs[i] != pairs[piece[-1]] + 1 or languages[i] != languages[piece[-1]]
                          or len(piece) == size):
                close()
            piece.append(i)
        close()
    return pieces


def unasked_agreed(published: list[Word], languages: list[str], spans: list[TrustedSpan],
                   owned_p: set[int], too_long_p: set[int], pairs: dict[int, int],
                   taken_h: set[int]) -> Counter:
    """Why each published word in a span belongs to no stop, counted by (reason, language).

    These words are unchecked, never correct: the import must not count them as either.
    """
    found = Counter()
    for span in spans:
        for i in range(span.first, span.last + 1):
            if i in owned_p:
                continue
            if published[i].start is None:
                reason = "untimed"
            elif i in too_long_p:
                reason = "inside a disagreement too long to ask"
            elif i not in pairs:
                reason = "written differently (agreed only after folding)"
            elif pairs[i] in taken_h:
                reason = "its ElevenLabs word is in another stop or an unasked disagreement"
            else:
                reason = f"heard over {AGREE_SECONDS:g} s apart, or a recogniser word with no real time"
            found[(reason, languages[i])] += 1
    return found


def context_words(words: list[Word], lo: int, hi: int,
                  blocked: set[int] = frozenset()) -> tuple[list[str], list[str]]:
    """Up to `CONTEXT_WORDS` either side of [lo, hi), stopping short of the first blocked word."""
    before = []
    for i in range(lo - 1, max(0, lo - CONTEXT_WORDS) - 1, -1):
        if i in blocked:
            break
        before.insert(0, words[i].text)
    after = []
    for i in range(hi, min(len(words), hi + CONTEXT_WORDS)):
        if i in blocked:
            break
        after.append(words[i].text)
    return before, after


def write_package(package: dict, target: Path) -> None:
    """Write `package`, but only if it passes its schema and every package rule.

    Bytes are written with LF line endings: the file's SHA-256 is how every answer names it.
    """
    errors = schema_errors("lecture-review-package", package)
    broken = package_rules(package)
    if errors or broken:
        lines = errors[:10] + [f"{b.rule}: {b.message}" for b in broken[:10]]
        raise ValueError(f"refused - the package fails {len(errors)} schema check(s) and "
                         f"{len(broken)} rule check(s):\n  " + "\n  ".join(lines))
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes((json.dumps(package, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    partial.replace(target)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def decoded_seconds(path: Path) -> float:
    """A recording's length by decoding every sample, never the MP3 header's figure.

    Some originals' headers are wrong - two list 3,164 frames that do not exist - so the header
    is not a measurement. ffmpeg decodes to 16-bit mono at the file's own rate and the samples
    are counted.
    """
    rate = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                               "stream=sample_rate", "-of", "csv=p=0", str(path)],
                              capture_output=True, text=True, check=True).stdout.strip())
    process = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                                "-ac", "1", "-f", "s16le", "-"], stdout=subprocess.PIPE)
    count = 0
    for block in iter(lambda: process.stdout.read(1 << 20), b""):
        count += len(block)
    if process.wait() != 0:
        raise RuntimeError(f"ffmpeg could not decode {path}")
    return count / 2 / rate


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout.strip()


def audio_entry(slug: str, manifest: dict, original_sha: str) -> tuple[dict, dict | None, dict | None]:
    """The original and its listening copy as the package names them, measured, not assumed."""
    entry = next((e for e in manifest["lectures"] if e["lecture"] == slug), None)
    if entry is None:
        raise ValueError(f"{slug} is not in the media manifest")
    if entry["original"]["sha256"] != original_sha:
        raise ValueError(f"the local audio's SHA-256 {original_sha} is not the manifest's "
                         f"{entry['original']['sha256']}")
    original = {"sha256": original_sha, "object": entry["original"]["object"]}
    copy = entry.get("listening_copy")
    if not copy:
        return original, None, {"reason": "not-made-yet"}
    if not copy.get("length_matches_original"):
        return original, None, {"reason": "failed-length-check",
                                "detail": "the media manifest records that the copy's length "
                                          "does not match the original's"}
    local = COPIES / f"{slug}.mp3"
    if local.exists() and sha256(local) == copy["sha256"]:
        seconds = decoded_seconds(local)
    elif "length_check" in copy:
        seconds = copy["length_check"]["copy_decoded_seconds"]
    else:
        raise ValueError(f"the listening copy's decoded length cannot be measured: no local copy "
                         f"with SHA-256 {copy['sha256']} and none recorded in the manifest")
    return original, {"object": copy["object"], "sha256": copy["sha256"],
                      "seconds": round(seconds, 3)}, None


def _apart(stop: DiffStop) -> bool:
    """Were the two versions paired across more silence than a timing error could explain?

    The same one-second tolerance `read_along` allows a placed word, measured between the two
    versions' stretches rather than word by word.
    """
    p_start, p_end = _times(stop.published)
    h_start, h_end = _times(stop.heard)
    if p_start is None or h_start is None:
        return False
    return max(p_start, h_start) - min(p_end, h_end) > AGREE_SECONDS


def verse_questions(matches: list[dict], published: list[Word], heard: list[Word],
                    spans: list[TrustedSpan]) -> tuple[list[dict], list[tuple], list[tuple]]:
    """A verse check for each matched verse run inside a trustworthy span.

    Returns the verse stops, their runs as (first, one past last, start, end) published
    positions and times, and the matches not asked with the reason. A match is refused rather
    than adjusted when the transcript at its times is not the text it matched, or when the
    reference is not an address a reviewer could look up.
    """
    stops, runs, skipped = [], [], []
    for match in matches:
        inside = [i for i, w in enumerate(published) if w.start is not None
                  and round(match["start"], 3) <= w.start and w.end <= round(match["end"], 3)]
        if not inside:
            skipped.append((match["start"], "no published words at its times"))
            continue
        lo, hi = inside[0], inside[-1] + 1
        if " ".join(w.text for w in published[lo:hi]) != unicodedata.normalize("NFC", match["text"]):
            skipped.append((match["start"], "the run's text is not the transcript's"))
            continue
        if not any(s.first <= lo and hi - 1 <= s.last for s in spans):
            skipped.append((match["start"], "not inside a trustworthy span"))
            continue
        if match["song"].startswith("cached "):
            skipped.append((match["start"], "the cached verse has no reference"))
            continue
        start, end = published[lo].start, published[hi - 1].end
        near = [j for j, w in enumerate(heard) if start <= w.middle <= end]
        runs.append((lo, hi, start, end))
        verse = unicodedata.normalize("NFC", match["verse"])
        printed = verse.split()
        stops.append({
            "kind": "verse-check", "language": indic_language(verse),
            "p": (lo, hi), "h": (near[0], near[-1] + 1) if near else None,
            "start": start, "end": end,
            "verse": {"reference": unicodedata.normalize("NFC", match["song"]),
                      "printed_text": verse,
                      "printed_words": printed,
                      "recited": recited(printed, [w.text for w in published[lo:hi]])}})
    return stops, runs, skipped


def span_differences(span: TrustedSpan, published: list[Word], heard: list[Word],
                     languages: list[str], runs: list[tuple]) -> list[DiffStop]:
    """The word disagreements in one trustworthy span, in whole-lecture positions."""
    p_lo, p_hi = span.first, span.last + 1
    near = [j for j, w in enumerate(heard) if span.start <= w.middle < span.end]
    if not near:
        return []
    h_lo, h_hi = near[0], near[-1] + 1
    check_against_scorer([w.text for w in published[p_lo:p_hi]])
    check_against_scorer([w.text for w in heard[h_lo:h_hi]])
    local = [(lo - p_lo, hi - p_lo, s, e) for lo, hi, s, e in runs if p_lo <= lo and hi <= p_hi]
    stops = difference_stops(published[p_lo:p_hi], heard[h_lo:h_hi], languages[p_lo:p_hi], local)
    for stop in stops:
        stop.p_lo, stop.p_hi = stop.p_lo + p_lo, stop.p_hi + p_lo
        stop.h_lo, stop.h_hi = stop.h_lo + h_lo, stop.h_hi + h_lo
    return stops


def lecture_words(text: str, record: dict,
                  eleven: dict) -> tuple[list[Word], list[Word], list[dict], int]:
    """The published words with their times, ElevenLabs's words, the timed alignment, and how
    many timed words were dropped as editorial notes.

    The published words are numbered as the aligner numbered them. An alignment made under an
    older cleanup rule is carried over the way the read-along page carries it, or refused.
    """
    spoken = spoken_words(text)
    paras = paragraphs(text)
    timed = record["words"]
    try:
        check_alignment(paras, timed)
        dropped = 0
    except ValueError:
        timed, dropped = renumber(paras, timed)
        check_alignment(paras, timed)
    timed = sorted(timed, key=lambda w: w["index"])
    duration_aligner = record["audio_seconds"]
    if problems([Word(w["word"], w["start"], w["end"]) for w in timed], duration_aligner):
        raise ValueError(f"the alignment breaks its timing invariants: "
                         f"{problems([Word(w['word'], w['start'], w['end']) for w in timed], duration_aligner)}")
    by_index = {w["index"]: w for w in timed}
    published = [Word(word, round(by_index[i]["start"], 3) if i in by_index else None,
                      round(by_index[i]["end"], 3) if i in by_index else None)
                 for i, word in enumerate(spoken)]
    heard = [Word(w["w"], round(w["s"], 3), round(w["e"], 3))
             for w in sorted(eleven["words"], key=lambda w: w["s"]) if w.get("s") is not None]
    return published, heard, timed, dropped


def make_version(source: str, words: list[Word], all_words: list[Word], lo: int, hi: int,
                 differs: list[int], blocked: set[int] = frozenset()) -> dict:
    """One source's version of a stop: its words, and the words around them for context."""
    before, after = context_words(all_words, lo, hi, blocked)
    return {"source": source, "before": before,
            "words": [{"text": w.text, "start": w.start, "end": w.end} for w in words],
            "after": after, "differs": differs}


def disagreement_draft(s: DiffStop, published: list[Word], heard: list[Word]) -> dict:
    return {"kind": "word-disagreement", "language": s.language, "start": s.start, "end": s.end,
            "p": (s.p_lo, s.p_hi), "h": (s.h_lo, s.h_hi),
            "versions": [make_version("published", s.published, published, s.p_lo, s.p_hi,
                                      s.differs_published),
                         make_version("elevenlabs", s.heard, heard, s.h_lo, s.h_hi,
                                      s.differs_heard)]}


def piece_draft(piece: tuple[int, int, int, int], published: list[Word], heard: list[Word],
                languages: list[str], blocked_p: set[int], blocked_h: set[int]) -> dict:
    """An agreement stop for one agreed piece, its context stopping at the blocked words.

    With no 3-second rule, a piece can sit beside a disagreement. Its context words stop short
    of that disagreement's words in both versions, or the one text shown would show which of
    the disagreement's versions is the published one.
    """
    a, b, h, h_end = piece
    mine, theirs = published[a:b], heard[h:h_end]
    start, end = _times(mine + theirs)
    return {"kind": "agreement-sample", "language": languages[a], "start": start, "end": end,
            "p": (a, b), "h": (h, h_end),
            "versions": [make_version("published", mine, published, a, b, [], blocked_p),
                         make_version("elevenlabs", theirs, heard, h, h_end, [], blocked_h)]}


def stop_from_draft(draft: dict, stop_id: str, duration: float) -> dict:
    context = clip(draft["start"], draft["end"], duration)
    stop = {"id": stop_id, "kind": draft["kind"], "language": draft["language"],
            "start": draft["start"], "end": draft["end"],
            "context": {"start": context[0], "end": context[1]},
            "versions": draft["versions"]}
    if "verse" in draft:
        stop["verse"] = draft["verse"]
    return stop


def assemble(slug: str, drafts: list[dict], duration: float, published: list[Word],
             languages: list[str], spans: list[TrustedSpan], heard: list[Word],
             outside: list[int]) -> tuple[list[dict], list[dict]]:
    """Every stop in timeline order with its id, and the timed transcript naming each word's stop."""
    drafts = sorted(drafts, key=lambda d: (d["start"], d["end"], STOP_ORDER[d["kind"]]))
    stops, owner_p, owner_h = [], {}, {}
    for serial, draft in enumerate(drafts, start=1):
        stop_id = f"{slug}#{serial:04d}"
        stops.append(stop_from_draft(draft, stop_id, duration))
        if draft["kind"] == "single-version":
            for j in range(*draft["h"]):
                owner_h[j] = stop_id
        elif draft["p"]:
            for i in range(*draft["p"]):
                if i in owner_p:
                    raise ValueError(f"published word {i} would belong to two stops")
                owner_p[i] = stop_id

    # The timed transcript for listening through: published words where they can be trusted,
    # ElevenLabs's words everywhere else. An unplaced published word sits where its neighbours do.
    lines, key = [], 0.0
    for span in spans:
        for i in range(span.first, span.last + 1):
            word = published[i]
            key = word.start if word.start is not None else key
            lines.append((key, 0, {"text": word.text, "start": word.start, "end": word.end,
                                   "language": languages[i], "source": "published",
                                   "stop": owner_p.get(i)}))
    for j in outside:
        word = heard[j]
        lines.append((word.start, 1, {"text": word.text, "start": word.start, "end": word.end,
                                      "language": "unknown", "source": "elevenlabs",
                                      "stop": owner_h.get(j)}))
    lines.sort(key=lambda line: (line[0], line[1]))
    return stops, [line[2] for line in lines]


def build(slug: str, manifest_path: Path, version: int = 1,
          every_agreed_piece: bool = False) -> tuple[dict, dict]:
    """The package for one lecture, and a summary of how it was made, for the report.

    By default a few agreement samples are drawn at random, out of earshot of every other stop.
    With `every_agreed_piece`, every piece both sources wrote exactly alike is asked instead.
    """
    folder = LECTURES / slug
    paths = {
        "published-transcript": folder / "transcript.txt",
        "alignment": ALIGNED / f"{slug}.json",
        "scoreable-spans": SPANS,
        "elevenlabs": HOSTED / "elevenlabs" / f"{slug}.json",
        "verse-matches": VERSES,
    }
    for role, path in paths.items():
        if not path.exists():
            raise ValueError(f"missing {role}: {path}")
    text = paths["published-transcript"].read_text(encoding="utf-8")
    record = json.loads(paths["alignment"].read_text(encoding="utf-8"))
    spans_manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    entry = next((d for d in spans_manifest["detail"] if d["slug"] == slug), None)
    if entry is None:
        raise ValueError(f"{slug} is not in the span manifest; run scripts.scoreable")
    if entry.get("duplicate_of"):
        raise ValueError(f"{slug} is the same recording as {entry['duplicate_of']}")
    eleven = json.loads(paths["elevenlabs"].read_text(encoding="utf-8"))
    if eleven.get("unit", "word") != "word":
        raise ValueError("ElevenLabs output is not word-timed")
    summary: dict = {"notes": []}

    published, heard_all, timed, dropped = lecture_words(text, record, eleven)
    if dropped:
        summary["notes"].append(f"{dropped} timed words are editorial notes under the current "
                                f"cleanup rule and were dropped with their timings.")
    duration_aligner = record["audio_seconds"]

    if not span_manifest_is_current(record["words"], entry):
        raise ValueError("the span manifest does not match this alignment; run scripts.scoreable")

    # The lecture-level placement check, exactly as compare_hosted computes it.
    services = {"elevenlabs": eleven}
    sarvam_path = HOSTED / "sarvam" / f"{slug}.json"
    if sarvam_path.exists():
        services["sarvam"] = json.loads(sarvam_path.read_text(encoding="utf-8"))
    ratios = {}
    for name, hosted in services.items():
        words = words_for(hosted)
        whole = whole_file_error(entry, words)
        ratios[name] = (overall_error(score_lecture_by_language(entry["spans_detail"], words))
                        / whole if whole else 1.0)
    if any(r > MISPLACED_RATIO for r in ratios.values()):
        raise ValueError(f"the alignment fails the placement check ({ratios}): its words are in "
                         f"the wrong places, so every stop would play the wrong audio")

    languages = word_languages(published)
    verse_file = json.loads(VERSES.read_text(encoding="utf-8"))
    matches = [m for m in verse_file["matched"] if m["slug"] == slug]
    low = [m for m in matches if m["margin"] < VERSE_MARGIN]
    if low:
        raise ValueError(f"verse-runs.json holds {len(low)} match(es) below the {VERSE_MARGIN} "
                         f"gate, so it was written with a lower one; run scripts.verse_runs")

    # The word-level check finds misplaced words only where both sources agree on the words,
    # since that is what it can measure. Where they disagree it is blind, and a pairing the
    # comparison makes there between words seconds apart is the same fault seen from the other
    # side. Those stretches are cut out too, and the comparison is run again.
    misplaced = [list(region) for region in disagreements(timed, word_check(timed, eleven["words"]))]
    summary["misplaced_checked"] = len(misplaced)
    for _ in range(4):
        spans = trusted_spans(timed, misplaced)
        verse_stops, runs, skipped_verses = verse_questions(matches, published, heard_all, spans)
        differences = []
        for span in spans:
            differences += span_differences(span, published, heard_all, languages, runs)
        apart = [stop for stop in differences if _apart(stop)]
        if not apart:
            break
        misplaced = sorted(misplaced + [[*_times(stop.published), len(stop.published)]
                                        for stop in apart])
    else:
        raise ValueError("misplaced pairings are still being found after four passes")
    summary["misplaced"] = misplaced
    summary["skipped_verses"] = skipped_verses
    in_span = lambda t: any(s.start <= t < s.end for s in spans)

    # Too big to be a ten-second question, or holding a word whose time cannot be believed.
    oversized = [s for s in differences if max(len(s.published), len(s.heard)) > MAX_STOP_WORDS
                 or any(w.end - w.start > MAX_WORD_SECONDS for w in s.heard)]
    untimed_stops = [s for s in differences if s.start is None or not s.start < s.end]
    summary["oversized"] = [(round(s.start, 1), len(s.published), len(s.heard)) for s in oversized
                            if s.start is not None]
    summary["untimed_differences"] = len(untimed_stops)
    differences = [s for s in differences if s not in oversized and s not in untimed_stops]

    # Single versions: ElevenLabs's words where no published word can be trusted. A word
    # ElevenLabs stretched across far longer than a word lasts ends a stop and is not asked.
    outside = [j for j, w in enumerate(heard_all) if not in_span(w.middle)]
    singles: list[list[int]] = []
    for j in outside:
        if heard_all[j].end - heard_all[j].start > MAX_WORD_SECONDS:
            singles.append([])
            continue
        if (singles and singles[-1] and singles[-1][-1] == j - 1
                and len(singles[-1]) < MAX_STOP_WORDS
                and heard_all[j].start - heard_all[j - 1].end <= SINGLE_PAUSE):
            singles[-1].append(j)
        else:
            singles.append([j])
    singles = [g for g in singles if g and any(fold(heard_all[j].text) for j in g)
               and heard_all[g[0]].start < heard_all[g[-1]].end]
    summary["long_words"] = [(w.text, round(w.start, 1), round(w.end - w.start, 1))
                             for j in outside for w in [heard_all[j]]
                             if w.end - w.start > MAX_WORD_SECONDS]

    # Agreement samples, away from every other stop.
    taken = [(s.start, s.end) for s in differences] + [(v["start"], v["end"]) for v in verse_stops] \
        + [(heard_all[g[0]].start, heard_all[g[-1]].end) for g in singles]
    candidates = []
    for span in spans:
        p_lo, p_hi = span.first, span.last + 1
        h_positions = [j for j, w in enumerate(heard_all) if span.start <= w.middle < span.end]
        if not h_positions:
            continue
        h_lo = h_positions[0]
        for a, b, h in agreement_windows(published[p_lo:p_hi], heard_all[h_lo:h_positions[-1] + 1],
                                         languages[p_lo:p_hi]):
            start, end = published[p_lo + a].start, published[p_lo + b - 1].end
            middle_end = heard_all[h_lo + h + b - a - 1].end
            end = max(end, middle_end)
            start = min(start, heard_all[h_lo + h].start)
            if out_of_earshot(start, end, taken):
                candidates.append((p_lo + a, p_lo + b, h_lo + h, h_lo + h + b - a, start, end))
    wanted = max(MIN_AGREEMENT, -(-len(differences) // AGREEMENT_EVERY))
    seed = int(hashlib.sha256(f"{slug} agreement-sample".encode()).hexdigest(), 16)
    chosen = sorted(random.Random(seed).sample(candidates, min(wanted, len(candidates))))
    summary["agreement_candidates"] = len(candidates)

    # Or every agreed piece, with no 3-second rule (plan of 31 October 2026): each word both
    # sources wrote exactly alike is asked once. Pieces stay clear of every stop's words and of
    # disagreements too long to ask; their context words stop at disagreements and verse checks.
    pieces, blocked_p, blocked_h = [], set(), set()
    if every_agreed_piece:
        chosen = []
        too_long = oversized + untimed_stops
        blocked_p = {i for s in differences for i in range(s.p_lo, s.p_hi)} | {
            i for v in verse_stops for i in range(*v["p"])}
        blocked_h = {j for s in differences for j in range(s.h_lo, s.h_hi)} | {
            j for v in verse_stops if v["h"] for j in range(*v["h"])}
        too_long_p = {i for s in too_long for i in range(s.p_lo, s.p_hi)}
        too_long_h = {j for s in too_long for j in range(s.h_lo, s.h_hi)}
        pieces = agreed_pieces(published, heard_all, languages, spans, blocked_p | too_long_p,
                               blocked_h | too_long_h)
        owned = blocked_p | {i for a, b, _, _ in pieces for i in range(a, b)}
        summary["unasked"] = unasked_agreed(published, languages, spans, owned, too_long_p,
                                            identical_pairs(published, heard_all, spans),
                                            blocked_h | too_long_h)
        summary["piece_words"] = Counter()
        for a, b, _, _ in pieces:
            summary["piece_words"][languages[a]] += b - a

    # Every stop, in timeline order, then given its id.
    original_sha = sha256(folder / "audio.mp3")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    duration = round(decoded_seconds(folder / "audio.mp3"), 3)
    if abs(duration - duration_aligner) > ALIGNER_TOLERANCE:
        raise ValueError(f"decoded length {duration} s disagrees with the aligner's "
                         f"{duration_aligner} s, so the two do not share a clock")
    original, copy, missing = audio_entry(slug, manifest, original_sha)

    drafts = [disagreement_draft(s, published, heard_all) for s in differences]
    for v in verse_stops:
        lo, hi = v["p"]
        mine = published[lo:hi]
        versions = []
        if v["h"]:
            theirs = heard_all[v["h"][0]:v["h"][1]]
            d_mine, d_theirs = differing(mine, theirs)
            versions = [make_version("published", mine, published, lo, hi, d_mine),
                        make_version("elevenlabs", theirs, heard_all, *v["h"], d_theirs)]
        else:
            versions = [make_version("published", mine, published, lo, hi, [])]
        start, end = _times(mine + (heard_all[v["h"][0]:v["h"][1]] if v["h"] else []))
        drafts.append({**v, "start": start, "end": end, "versions": versions})
    for g in singles:
        words = heard_all[g[0]:g[-1] + 1]
        drafts.append({"kind": "single-version", "language": "unknown", "start": words[0].start,
                       "end": words[-1].end, "p": None, "h": (g[0], g[-1] + 1),
                       "versions": [make_version("elevenlabs", words, heard_all, g[0], g[-1] + 1, [])]})
    for a, b, h, h_end, start, end in chosen:
        drafts.append({"kind": "agreement-sample", "language": languages[a], "start": start,
                       "end": end, "p": (a, b), "h": (h, h_end),
                       "versions": [make_version("published", published[a:b], published, a, b, []),
                                    make_version("elevenlabs", heard_all[h:h_end], heard_all, h,
                                            h_end, [])]})
    drafts += [piece_draft(piece, published, heard_all, languages, blocked_p, blocked_h)
               for piece in pieces]

    stops, transcript = assemble(slug, drafts, duration, published, languages, spans, heard_all,
                                 outside)

    revision = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--", *PRODUCER_FILES)
    inputs = [{"role": role, "path": path.relative_to(REPO).as_posix(), "sha256": sha256(path)}
              for role, path in paths.items()]
    if "sarvam" in services:
        inputs.append({"role": "sarvam", "path": sarvam_path.relative_to(REPO).as_posix(),
                       "sha256": sha256(sarvam_path)})
    inputs.append({"role": "media-manifest", "path": f"manifests/{manifest_path.name}",
                   "sha256": sha256(manifest_path)})
    notes = []
    if dirty:
        notes.append("DRAFT, not for publishing: built from producer code with uncommitted "
                     "changes, so the revision does not contain the code that built it.")
    notes += summary["notes"]
    cut = f"{len(misplaced)} stretches, {sum(b - a for a, b, _ in misplaced):.1f} s"
    notes.append(f"Cut out of the trustworthy spans as misplaced: {cut} - "
                 f"{summary['misplaced_checked']} found by read_along.word_check, the rest paired "
                 f"with ElevenLabs words over {AGREE_SECONDS} s away.")
    if oversized:
        notes.append(f"{len(oversized)} disagreement(s) over {MAX_STOP_WORDS} words or holding an "
                     f"untimed recogniser word were not asked.")
    notes.append("Single-version words are labelled unknown: ElevenLabs's spelling carries no "
                 "editorial diacritics to read a language from.")
    if skipped_verses:
        notes.append(f"{len(skipped_verses)} verse match(es) not asked: "
                     + "; ".join(f"{s:.1f} s {why}" for s, why in skipped_verses))
    if every_agreed_piece:
        notes.append(pieces_note(len(pieces), summary["piece_words"], summary["unasked"]))
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    ratio_text = ", ".join(f"{name} {r:.2f}" for name, r in ratios.items())
    package = {
        "schema": FORMAT,
        "package": {"id": f"{slug}/v{version}", "version": version,
                    "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "producer": {"name": "lecture-archive",
                     "command": f"python -m scripts.review_package {slug} --media-manifest "
                                f"manifests/{manifest_path.name}"
                                + (" --every-agreed-piece" if every_agreed_piece else ""),
                     "revision": revision, "inputs": inputs, "notes": " ".join(notes)[:4000]},
        "lecture": {"id": slug, "title": meta.get("title") or slug, "duration_seconds": duration},
        "audio": {"original": original, "listening_copy": copy,
                  **({"listening_copy_missing": missing} if missing else {})},
        "alignment_check": {
            "status": "passed",
            "method": "scripts/compare_hosted placement check: error inside the trustworthy spans "
                      f"against the whole file, limit x{MISPLACED_RATIO}",
            "detail": (f"Ratios {ratio_text}. Passing it does not mean every word is in place: "
                       f"{cut} where published words sit over {AGREE_SECONDS} s from where "
                       f"ElevenLabs heard them were removed from the trustworthy spans.")},
        "trustworthy_spans": [{"start": round(s.start, 3), "end": round(s.end, 3)} for s in spans],
        "untranscribed": [{"start": round(a, 3), "end": round(b, 3)}
                          for a, b in untranscribed(timed, duration)],
        "transcript": {"words": transcript},
        "stops": stops,
    }
    summary.update({"ratios": ratios, "dirty": bool(dirty), "spans": len(spans),
                    "outside_words": len(outside), "dropped": dropped})
    return package, summary


def pieces_note(stops: int, words: Counter, unasked: Counter) -> str:
    """The every-agreed-piece mode in one sentence, for producer.notes and the report."""
    covered = ", ".join(f"{n} {language}" for language, n in words.most_common())
    reasons = Counter()
    for (reason, _), n in unasked.items():
        reasons[reason] += n
    left = "; ".join(f"{n} {reason}" for reason, n in reasons.most_common())
    return (f"Agreement stops: one for every agreed piece where both sources wrote exactly the "
            f"same text, up to {AGREEMENT_WORDS} words in one language - {stops} stops holding "
            f"{sum(words.values())} words ({covered or 'none'}). No 3-second rule; context words "
            f"stop at disagreement and verse-check words. Agreed words not asked, so unchecked: "
            f"{sum(reasons.values())} ({left or 'none'}).")


def report(package: dict, summary: dict) -> str:
    """What the package holds, in plain words."""
    stops = package["stops"]
    lines = [f"{package['package']['id']}: {len(stops)} stops, "
             f"{len(package['transcript']['words']):,} transcript words"]
    by_kind = Counter(s["kind"] for s in stops)
    for kind, count in by_kind.most_common():
        langs = Counter(s["language"] for s in stops if s["kind"] == kind)
        lines.append(f"  {count:>4} {kind:18} " + ", ".join(f"{n} {l}" for l, n in langs.most_common()))
    clips = sorted(s["context"]["end"] - s["context"]["start"] for s in stops)
    asked = sorted(s["end"] - s["start"] for s in stops)
    if clips:
        lines.append(f"  clip seconds: median {clips[len(clips) // 2]:.1f}, "
                     f"90% under {clips[int(len(clips) * 0.9)]:.1f}, longest {clips[-1]:.1f}; "
                     f"listening total {sum(clips) / 60:.0f} min")
        lines.append(f"  stretch asked about: median {asked[len(asked) // 2]:.2f} s, "
                     f"longest {asked[-1]:.1f} s")
    ratios = ", ".join(f"{name} {r:.2f}" for name, r in summary["ratios"].items())
    seconds = sum(b - a for a, b, _ in summary["misplaced"])
    lines.append(f"  placement check passed ({ratios}); {len(summary['misplaced'])} misplaced "
                 f"stretches cut ({summary['misplaced_checked']} by the word check), {seconds:.0f} s; "
                 f"{summary['spans']} trustworthy spans")
    for start, published, heard in summary["oversized"]:
        lines.append(f"  not asked, too big: {start:.1f} s, {published} published / {heard} heard words")
    for text, start, seconds in summary["long_words"]:
        lines.append(f"  not asked, untimed recogniser word: {text!r} at {start:.1f} s lasting {seconds:.0f} s")
    if "unasked" in summary:
        lines.append(f"  every agreed piece asked: " + pieces_note(
            by_kind["agreement-sample"], summary["piece_words"], summary["unasked"]))
        for (reason, language), n in sorted(summary["unasked"].items()):
            lines.append(f"    not asked, {language}: {n:>5} {reason}")
    else:
        lines.append(f"  {summary['agreement_candidates']} agreement candidates")
    lines.append(f"  {summary['untimed_differences']} differences with no time were not asked")
    for start, why in summary["skipped_verses"]:
        lines.append(f"  verse at {start:.1f} s not asked: {why}")
    if summary["dirty"]:
        lines.append("  DRAFT: producer code has uncommitted changes (marked in producer.notes)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("lecture", help="the lecture's slug")
    parser.add_argument("--media-manifest", type=Path, default=MEDIA_MANIFEST,
                        help="a local copy of manifests/media-v2.json (default: the copy kept "
                             "in data/reference/review/manifests/)")
    parser.add_argument("--replace", action="store_true",
                        help="overwrite this lecture's local v1 - only ever for a draft that was "
                             "never uploaded, since answers name a package by its exact bytes")
    parser.add_argument("--every-agreed-piece", action="store_true",
                        help="ask every piece both sources wrote exactly alike, instead of a few "
                             "random agreement samples out of earshot of every other stop")
    args = parser.parse_args(argv)

    target = OUT / args.lecture / "v1.json"
    if target.exists() and not args.replace:
        print(f"{target} exists. A republished package must carry stop ids over, which is not "
              f"built yet; --replace overwrites a local draft that was never uploaded.")
        return 1
    package, summary = build(args.lecture, args.media_manifest,
                             every_agreed_piece=args.every_agreed_piece)
    write_package(package, target)
    print(report(package, summary))
    print(f"\nwritten to {target.relative_to(REPO)} "
          f"({target.stat().st_size / 1e6:.2f} MB, SHA-256 {sha256(target)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
