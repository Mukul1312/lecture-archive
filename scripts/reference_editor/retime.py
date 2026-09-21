"""Re-time subtitle cues against word timings heard in the audio.

    python -m scripts.reference_editor.retime --srt in.srt --words words.jsonl --out out.srt

A constant or smoothly warped offset cannot follow a subtitle file that skipped
speech (for example a repeated translation) or was timed against a different copy
of the recording. For each cue this searches the recognised words near the cue's
current time, scores candidate positions by letter-level similarity (Whisper glues
Sanskrit compounds together, so word-level matching misses them), then chooses the
highest-scoring set of positions that stays in time order across the whole lecture.
The existing timings act only as a prior: between two identical readings, the one
nearer the expected time wins. Cue numbers and text are kept byte-for-byte, so a
review can be carried over to the re-timed file.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import statistics
import sys
import unicodedata

from .review import Cue, format_time, parse_srt, plain_text


SEARCH_WINDOW_S = 120.0     # how far from its current time a cue may move
PRIOR_PENALTY_PER_S = 0.002 # score lost per second away from the current time; breaks ties between repeats
MIN_SCORE = 0.55            # below this a position is not considered a match
CANDIDATES_PER_CUE = 4
WORD_SECONDS = 0.4          # typical time per word, for cues with no match
UNCOVERED_GAP_SECONDS = 8.0


@dataclass(frozen=True)
class HeardWord:
    token: str
    start: float
    end: float


@dataclass(frozen=True)
class _Candidate:
    score: float
    first: int   # index of the first heard word
    last: int    # index of the last heard word


def fold(text: str) -> list[str]:
    """Lowercase ASCII tokens with diacritics removed, so IAST and plain spellings compare equal."""
    stripped = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).split()


def load_words(path: Path) -> list[HeardWord]:
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        for token in fold(item["w"]):
            words.append(HeardWord(token, float(item["s"]), float(item["e"])))
    return words


def _candidates(letters: str, prior: float, heard: list[HeardWord], starts: list[float]) -> list[_Candidate]:
    if not letters:
        return []
    found = []
    low = bisect_left(starts, prior - SEARCH_WINDOW_S)
    high = bisect_right(starts, prior + SEARCH_WINDOW_S)
    for first in range(low, high):
        text, last = "", first
        while last < len(heard) and len(text) < len(letters):
            text += heard[last].token
            last += 1
        matcher = SequenceMatcher(None, letters, text, autojunk=False)
        if matcher.real_quick_ratio() < MIN_SCORE or matcher.quick_ratio() < MIN_SCORE:
            continue
        score = matcher.ratio() - PRIOR_PENALTY_PER_S * abs(heard[first].start - prior)
        if score >= MIN_SCORE:
            found.append(_Candidate(score, first, last - 1))
    found.sort(key=lambda c: c.score, reverse=True)
    return found[:CANDIDATES_PER_CUE]


def _best_ordered_path(options: list[list[_Candidate]], heard: list[HeardWord]) -> dict[int, _Candidate]:
    """Pick at most one candidate per cue, in time order, maximising the total score."""
    states = [(cue, candidate) for cue, choices in enumerate(options) for candidate in choices]
    best = [0.0] * len(states)
    back = [-1] * len(states)
    for i, (cue, candidate) in enumerate(states):
        start = heard[candidate.first].start
        best[i] = candidate.score
        for j in range(i):
            earlier_cue, earlier = states[j]
            if earlier_cue < cue and heard[earlier.last].start <= start and best[j] + candidate.score > best[i]:
                best[i] = best[j] + candidate.score
                back[i] = j
    chosen: dict[int, _Candidate] = {}
    i = max(range(len(states)), key=best.__getitem__) if states else -1
    while i >= 0:
        cue, candidate = states[i]
        chosen[cue] = candidate
        i = back[i]
    return chosen


def retime(cues: list[Cue], heard: list[HeardWord]) -> tuple[list[tuple[int, int]], dict]:
    """Return new (start_ms, end_ms) per cue and a report of how well the cues matched."""
    if not heard:
        raise ValueError("no recognised words to align against")
    cue_tokens = [fold(plain_text(cue.raw)) for cue in cues]
    starts_heard = [word.start for word in heard]
    options = [_candidates("".join(tokens), cue.start_ms / 1000, heard, starts_heard)
               for cue, tokens in zip(cues, cue_tokens)]
    chosen = _best_ordered_path(options, heard)
    if not chosen:
        raise ValueError("no cue could be matched to the recognised words")

    starts: list[float | None] = [None] * len(cues)
    ends: list[float | None] = [None] * len(cues)
    for index, candidate in chosen.items():
        starts[index] = heard[candidate.first].start
        ends[index] = heard[candidate.last].end
    anchored = sorted(chosen)

    # Cues with no match sit between their matched neighbours, spaced by word count.
    for i in range(len(cues)):
        if starts[i] is not None:
            continue
        before = max((a for a in anchored if a < i), default=None)
        after = min((a for a in anchored if a > i), default=None)
        if before is None:
            starts[i] = max(0.0, starts[after] - WORD_SECONDS * sum(len(t) for t in cue_tokens[i:after]))
        elif after is None:
            starts[i] = ends[before] + WORD_SECONDS * sum(len(t) for t in cue_tokens[before + 1:i])
        else:
            span_words = sum(len(t) for t in cue_tokens[before:after]) or 1
            done = sum(len(t) for t in cue_tokens[before:i])
            starts[i] = starts[before] + (starts[after] - starts[before]) * done / span_words

    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1])
    timings = []
    for i, start in enumerate(starts):
        following = starts[i + 1] if i + 1 < len(starts) else None
        own_end = ends[i] if ends[i] is not None else start + WORD_SECONDS * max(1, len(cue_tokens[i]))
        end = min(own_end + 0.5, following) if following is not None else own_end + 0.5
        timings.append((round(start * 1000), round(max(end, start) * 1000)))

    covered = [False] * len(heard)
    for candidate in chosen.values():
        for k in range(candidate.first, candidate.last + 1):
            covered[k] = True
    uncovered, run_start = [], None
    for k, is_covered in enumerate(covered + [True]):
        if not is_covered and run_start is None:
            run_start = k
        elif is_covered and run_start is not None:
            if heard[k - 1].end - heard[run_start].start >= UNCOVERED_GAP_SECONDS:
                uncovered.append((heard[run_start].start, heard[k - 1].end))
            run_start = None

    shifts = [timings[i][0] / 1000 - cues[i].start_ms / 1000 for i in range(len(cues))]
    scores = [candidate.score for candidate in chosen.values()]
    report = {
        "cues": len(cues),
        "cues_anchored": len(chosen),
        "median_match_score": round(statistics.median(scores), 3),
        "heard_words": len(heard),
        "median_shift_s": round(statistics.median(shifts), 2),
        "largest_shift_s": round(max(shifts, key=abs), 2),
        "unmatched_cues": [cues[i].number for i in range(len(cues)) if i not in chosen],
        "spoken_but_not_subtitled": [(round(a, 1), round(b, 1)) for a, b in uncovered],
    }
    return timings, report


def write_srt(cues: list[Cue], timings: list[tuple[int, int]]) -> str:
    blocks = [f"{cue.number}\n{format_time(start)} --> {format_time(end)}\n{cue.raw}"
              for cue, (start, end) in zip(cues, timings)]
    return ("\n\n".join(blocks) + "\n").replace("\n", "\r\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.reference_editor.retime", description=__doc__.split("\n\n")[0])
    parser.add_argument("--srt", required=True, type=Path)
    parser.add_argument("--words", required=True, type=Path, help="JSON lines of {w, s, e} recognised words in audio seconds")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        print(f"retime: {args.out} already exists; refusing to overwrite it", file=sys.stderr)
        return 2
    cues = parse_srt(args.srt.read_text(encoding="utf-8"))
    timings, report = retime(cues, load_words(args.words))
    args.out.write_bytes(write_srt(cues, timings).encode("utf-8"))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
