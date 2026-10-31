"""Republish a published review package as its next version, asking every agreed piece.

    .venv/Scripts/python.exe -m scripts.review_republish bg-3-37-the-duty-of-a-human-being-brisbane

Writes `data/reference/review/packages/<lecture>/v2.json` beside the published `v1.json`, which
is never touched. Uploading it is `review_publish --version 2`, and only after the review app
carries answers over (plan of 31 October 2026, section 9).

**The new version is built from the published bytes, never by building the first again.** The
builder's code moves on, and a rebuild could draw different stops under the same ids, so earlier
answers would carry over to questions nobody was asked. So the first version must be the bytes
`docs/review-packages.md` records as published, and every input it names must still have the
hash it names. Its stops are kept byte for byte, under their ids; its transcript changes only
where a new stop claims a word that had none (rule P11).

**What is added** is the builder's every-agreed-piece mode: one agreement stop for every piece
both sources wrote exactly alike that no earlier stop holds. To cut those pieces the published
and ElevenLabs words are read again from the same inputs, and each earlier word and stop is found
among them by its text and times. The comparison is then run again on the published spans, only
to find disagreements too long to ask, whose words stay unasked; if it does not draw the earlier
version's disagreements exactly, the two do not fit together and nothing is written.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scripts.review_contract import republish_rules
from scripts.review_package import (MAX_STOP_WORDS, MAX_WORD_SECONDS, OUT, PRODUCER_FILES, REPO,
                                    STOP_ORDER, TrustedSpan, Word, agreed_pieces, git,
                                    identical_pairs, lecture_words, piece_draft, pieces_note,
                                    sha256, span_differences, stop_from_draft, unasked_agreed,
                                    write_package)

RECORD = REPO / "docs/review-packages.md"
REVIEW = REPO / "data/reference/review"
# A disagreement or verse check shown beside a piece would show which of its versions is published.
ASKED = ("word-disagreement", "verse-check")


def _key(word) -> tuple:
    if isinstance(word, Word):
        return word.text, word.start, word.end
    return word["text"], word["start"], word["end"]


def published_sha(slug: str, version: int, record: Path = RECORD) -> str | None:
    """The SHA-256 `docs/review-packages.md` records for a published package, or None.

    A row names `<lecture>` (version 1, as the table's heading says) or `<lecture>/v<n>.json`.
    """
    text = record.read_text(encoding="utf-8")
    section = text.partition("## Published packages")[2].partition("\n## ")[0]
    for name, number, digest in re.findall(
            r"^\| `([a-z0-9-]+)(?:/v(\d+)\.json)?` \| [\d,]+ \| `([0-9a-f]{64})` \|", section, re.M):
        if name == slug and int(number or 1) == version:
            return digest
    return None


def republish(previous: dict, previous_sha: str, published: list[Word], heard: list[Word],
              timed: list[dict], *, revision: str, now: str,
              draft: bool = False) -> tuple[dict, dict]:
    """The next version of `previous`, adding one agreement stop for every agreed piece.

    `published`, `heard` and `timed` are what `lecture_words` reads again from the inputs
    `previous` names; `timed` holds the aligner's unrounded times.
    """
    slug, version = previous["lecture"]["id"], previous["package"]["version"]
    lines = previous["transcript"]["words"]
    kinds = {s["id"]: s["kind"] for s in previous["stops"]}

    # Each trustworthy span's published words, found among the words read again. A span starts
    # and ends with a timed word, and its words follow one another without a gap.
    groups: list[list[int]] = [[] for _ in previous["trustworthy_spans"]]
    span = None
    for n, line in enumerate(lines):
        if line["source"] != "published":
            continue
        if line["start"] is not None:
            inside = [k for k, s in enumerate(previous["trustworthy_spans"])
                      if s["start"] <= line["start"] <= s["end"]]
            if len(inside) != 1:
                raise ValueError(f"transcript word {n} is not inside exactly one trustworthy span")
            span = inside[0]
        groups[span].append(n)
    timed_at: dict[tuple, list[int]] = {}
    for i, word in enumerate(published):
        if word.start is not None:
            timed_at.setdefault(_key(word), []).append(i)
    # A span's edges as the builder read them: unrounded, from the aligner. The package stores
    # them to the millisecond, and a recogniser word at 1414.3780 s lies inside the rounded edge
    # but outside the true one, 1414.378210 s (evening darshan).
    raw = {w["index"]: w for w in timed}
    spans, position = [], {}
    for interval, group in zip(previous["trustworthy_spans"], groups):
        found = timed_at.get(_key(lines[group[0]]), []) if group else []
        if len(found) != 1:
            raise ValueError(f"a span at {interval['start']} s does not start at a word read "
                             f"from the inputs")
        for k, n in enumerate(group):
            i = found[0] + k
            if i >= len(published) or _key(published[i]) != _key(lines[n]):
                raise ValueError(f"transcript word {n} ({lines[n]['text']!r}) is not the word read "
                                 f"from the inputs at its place: these are not the words version "
                                 f"{version} was built from")
            position[n] = i
        first, last = found[0], found[0] + len(group) - 1
        if (first not in raw or last not in raw
                or (round(raw[first]["start"], 3), round(raw[last]["end"], 3))
                != (interval["start"], interval["end"])):
            raise ValueError(f"the span at {interval['start']} s does not start and end at its "
                             f"first and last words' aligned times")
        spans.append(TrustedSpan(raw[first]["start"], raw[last]["end"], first, last))
    languages: list[str | None] = [None] * len(published)
    owner_p: dict[int, str] = {}
    for n, i in position.items():
        languages[i] = lines[n]["language"]
        if lines[n]["stop"] is not None:
            owner_p[i] = lines[n]["stop"]
    blocked_p = {i for i, stop_id in owner_p.items() if kinds[stop_id] in ASKED}

    # Each earlier stop's ElevenLabs words, found the same way.
    heard_at: dict[tuple, list[int]] = {}
    for j, word in enumerate(heard):
        heard_at.setdefault(_key(word), []).append(j)
    owned_h, blocked_h, heard_range = set(), set(), {}
    for stop in previous["stops"]:
        for v in stop["versions"]:
            if v["source"] != "elevenlabs" or not v["words"]:
                continue
            found = heard_at.get(_key(v["words"][0]), [])
            h = found[0] if len(found) == 1 else None
            if h is None or [_key(w) for w in heard[h:h + len(v["words"])]] != [
                    _key(w) for w in v["words"]]:
                raise ValueError(f"{stop['id']}: its ElevenLabs words are not the ones read from "
                                 f"the inputs")
            heard_range[stop["id"]] = range(h, h + len(v["words"]))
            owned_h.update(heard_range[stop["id"]])
            if stop["kind"] in ASKED:
                blocked_h.update(heard_range[stop["id"]])

    # The comparison again, on the published spans: it must draw the earlier disagreements
    # exactly, and the ones too long to ask are found here.
    runs = []
    for stop in previous["stops"]:
        if stop["kind"] == "verse-check":
            mine = sorted(i for i, stop_id in owner_p.items() if stop_id == stop["id"])
            runs.append((mine[0], mine[-1] + 1, published[mine[0]].start, published[mine[-1]].end))
    differences = []
    for span in spans:
        differences += span_differences(span, published, heard, languages, runs)
    too_long = [s for s in differences
                if max(len(s.published), len(s.heard)) > MAX_STOP_WORDS
                or any(w.end - w.start > MAX_WORD_SECONDS for w in s.heard)
                or s.start is None or not s.start < s.end]
    drawn = {(tuple(range(s.p_lo, s.p_hi)), tuple(range(s.h_lo, s.h_hi)))
             for s in differences if s not in too_long}
    earlier = {(tuple(sorted(i for i, stop_id in owner_p.items() if stop_id == stop["id"])),
                tuple(heard_range.get(stop["id"], ())))
               for stop in previous["stops"] if stop["kind"] == "word-disagreement"}
    if drawn != earlier:
        raise ValueError(f"the comparison draws {len(drawn - earlier)} disagreements version "
                         f"{version} does not have and misses {len(earlier - drawn)} it has, so "
                         f"new pieces could not be trusted to fit its stops")

    too_long_p = {i for s in too_long for i in range(s.p_lo, s.p_hi)}
    too_long_h = {j for s in too_long for j in range(s.h_lo, s.h_hi)}
    pieces = agreed_pieces(published, heard, languages, spans, set(owner_p) | too_long_p,
                           owned_h | too_long_h)
    owned = set(owner_p) | {i for a, b, _, _ in pieces for i in range(a, b)}
    unasked = unasked_agreed(published, languages, spans, owned, too_long_p,
                             identical_pairs(published, heard, spans), owned_h | too_long_h)
    piece_words = Counter()
    for a, b, _, _ in pieces:
        piece_words[languages[a]] += b - a

    # New stops take serials after every earlier one, in timeline order among themselves.
    highest = max(int(s["id"].rpartition("#")[2]) for s in previous["stops"])
    drafts = sorted((piece_draft(piece, published, heard, languages, blocked_p, blocked_h)
                     for piece in pieces), key=lambda d: (d["start"], d["end"]))
    duration = previous["lecture"]["duration_seconds"]
    new = [stop_from_draft(d, f"{slug}#{highest + k:04d}", duration)
           for k, d in enumerate(drafts, start=1)]
    stops = sorted(previous["stops"] + new,
                   key=lambda s: (s["start"], s["end"], STOP_ORDER[s["kind"]]))
    transcript = copy.deepcopy(lines)
    line_at = {i: n for n, i in position.items()}
    for stop, d in zip(new, drafts):
        for i in range(*d["p"]):
            transcript[line_at[i]]["stop"] = stop["id"]

    notes = []
    if draft:
        notes.append("DRAFT, not for publishing: built from producer code with uncommitted "
                     "changes, so the revision does not contain the code that built it.")
    notes.append(f"Republishes v{version} (SHA-256 {previous_sha}), keeping its "
                 f"{len(previous['stops'])} stops unchanged; adds {len(new)} agreement stops, one "
                 f"for every agreed piece where both texts are exactly the same.")
    notes.append(pieces_note(len(new), piece_words, unasked))
    notes.append(f"Version {version}'s notes: {previous['producer']['notes']}")
    current = copy.deepcopy(previous)
    current["package"] = {"id": f"{slug}/v{version + 1}", "version": version + 1,
                          "published_at": now}
    current["producer"].update(command=f"python -m scripts.review_republish {slug}",
                               revision=revision, notes=" ".join(notes)[:4000])
    current["transcript"] = {"words": transcript}
    current["stops"] = stops
    broken = republish_rules(previous, current)
    if broken:
        raise ValueError(f"refused - the new version breaks P11: {broken[0].message}")
    return current, {"kept": len(previous["stops"]), "new": len(new), "piece_words": piece_words,
                     "unasked": unasked, "too_long": len(too_long)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("lecture", help="the lecture's slug")
    parser.add_argument("--replace", action="store_true",
                        help="overwrite this lecture's local v2 - only ever for one that was "
                             "never uploaded, since answers name a package by its exact bytes")
    args = parser.parse_args(argv)

    source = OUT / args.lecture / "v1.json"
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    recorded = published_sha(args.lecture, 1)
    if digest != recorded:
        print(f"refused - {source.relative_to(REPO)} has SHA-256 {digest}, but "
              f"{RECORD.relative_to(REPO)} records {recorded} as published")
        return 1
    previous = json.loads(data.decode("utf-8"))
    paths = {}
    for item in previous["producer"]["inputs"]:
        path = (REVIEW / item["path"]) if item["role"] == "media-manifest" else (REPO / item["path"])
        if not path.exists() or sha256(path) != item["sha256"]:
            print(f"refused - input {item['path']} is not the file version 1 was built from")
            return 1
        paths[item["role"]] = path
    target = OUT / args.lecture / "v2.json"
    if target.exists() and not args.replace:
        print(f"{target.relative_to(REPO)} exists; --replace overwrites one that was never uploaded")
        return 1

    published, heard, timed, _ = lecture_words(
        paths["published-transcript"].read_text(encoding="utf-8"),
        json.loads(paths["alignment"].read_text(encoding="utf-8")),
        json.loads(paths["elevenlabs"].read_text(encoding="utf-8")))
    dirty = git("status", "--porcelain", "--", *PRODUCER_FILES, "scripts/review_republish.py")
    current, summary = republish(previous, digest, published, heard, timed,
                                 revision=git("rev-parse", "HEAD"),
                                 now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 draft=bool(dirty))
    write_package(current, target)
    print(f"{current['package']['id']}: {summary['kept']} stops kept from v1, {summary['new']} "
          f"agreement stops added, {len(current['stops'])} in all")
    print("  " + pieces_note(summary["new"], summary["piece_words"], summary["unasked"]))
    for (reason, language), n in sorted(summary["unasked"].items()):
        print(f"    not asked, {language}: {n:>5} {reason}")
    if dirty:
        print("  DRAFT: producer code has uncommitted changes (marked in producer.notes)")
    print(f"written to {target.relative_to(REPO)} ({target.stat().st_size / 1e6:.2f} MB, "
          f"SHA-256 {sha256(target)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
