"""Re-time subtitle cues against word timings heard in the audio.

    python -m scripts.reference_editor.retime --srt in.srt --words words.jsonl --out out.srt

A constant or smoothly warped offset cannot follow a subtitle file that skipped
speech (for example a repeated translation) or was timed against a different copy
of the recording. This aligns the cue words to recognised words in order and takes
each cue's time from where its own words were heard. Cue numbers and cue text are
kept byte-for-byte, so a review can be carried over to the re-timed file.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import statistics
import sys
import unicodedata

from .review import Cue, format_time, parse_srt, plain_text


WORD_SECONDS = 0.4          # typical time per word, to place a cue whose first words were not matched
MIN_BLOCK = 2               # ignore single-word matches, which pair common words far apart
UNCOVERED_GAP_SECONDS = 8.0


@dataclass(frozen=True)
class HeardWord:
    token: str
    start: float
    end: float


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


def retime(cues: list[Cue], heard: list[HeardWord]) -> tuple[list[tuple[int, int]], dict]:
    """Return new (start_ms, end_ms) per cue and a report of how well the cues matched."""
    cue_tokens = [fold(plain_text(cue.raw)) for cue in cues]
    flat = [(index, position, token) for index, tokens in enumerate(cue_tokens) for position, token in enumerate(tokens)]
    matcher = SequenceMatcher(None, [t for _, _, t in flat], [w.token for w in heard], autojunk=False)
    anchors: dict[int, list[tuple[int, HeardWord]]] = {}
    matched_heard: set[int] = set()
    for block in matcher.get_matching_blocks():
        if block.size < MIN_BLOCK:
            continue
        for k in range(block.size):
            index, position, _ = flat[block.a + k]
            anchors.setdefault(index, []).append((position, heard[block.b + k]))
            matched_heard.add(block.b + k)

    starts: list[float | None] = [None] * len(cues)
    ends: list[float | None] = [None] * len(cues)
    for index, hits in anchors.items():
        position, first = hits[0]
        starts[index] = max(0.0, first.start - position * WORD_SECONDS)
        ends[index] = hits[-1][1].end
    anchored = [i for i, s in enumerate(starts) if s is not None]
    if not anchored:
        raise ValueError("no cue could be matched to the recognised words")

    # Cues with no matched words sit between their anchored neighbours, spaced by word count.
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

    uncovered = []
    run_start = None
    for j, word in enumerate(heard):
        if j in matched_heard:
            if run_start is not None and heard[j - 1].end - heard[run_start].start >= UNCOVERED_GAP_SECONDS:
                uncovered.append((heard[run_start].start, heard[j - 1].end))
            run_start = None
        elif run_start is None:
            run_start = j
    if run_start is not None and heard[-1].end - heard[run_start].start >= UNCOVERED_GAP_SECONDS:
        uncovered.append((heard[run_start].start, heard[-1].end))

    shifts = [timings[i][0] / 1000 - cues[i].start_ms / 1000 for i in range(len(cues))]
    report = {
        "cues": len(cues),
        "cues_anchored": len(anchored),
        "cue_words_matched": sum(len(h) for h in anchors.values()),
        "cue_words_total": len(flat),
        "heard_words": len(heard),
        "median_shift_s": round(statistics.median(shifts), 2),
        "largest_shift_s": round(max(shifts, key=abs), 2),
        "unmatched_cues": [cues[i].number for i in range(len(cues)) if i not in anchors],
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
