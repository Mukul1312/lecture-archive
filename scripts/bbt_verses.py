"""Caitanya-caritāmṛta verses from the Vedabase corpus, under the steward's permission.

**No freely-licensed machine-readable Caitanya-caritāmṛta exists.** That was checked three ways
on 2026-10-11 - Exa returns only editions whose own pages name the Bhaktivedanta Vedabase as
their source, Sanskrit Wikisource does not carry it, and Bengali Wikisource returns zero hits -
and the project's earlier research had excluded BBT as in copyright. **On 2026-10-12 the steward
stated that full permission from BBT is held**, which settles the question their way and is why
this exists.

The source is `github.com/vaniwiki/prabhupada-books`, one file per verse under
`books/{book}/.../{verse}.txt`, with a JSON header carrying the address.

**Only the verse text is taken.** Each file holds the verse, then word-for-word synonyms, then
the translation, then Prabhupāda's purport. This reads the `===== Text =====` section and
nothing else - the same rule the KKSongs mirror follows, lyrics and never the purports. The
purports are a living teacher's commentary and are not what a recogniser is being graded
against; the verse is 400-year-old text by Kṛṣṇadāsa Kavirāja. Keeping the ingest to exactly
what the task needs is the point, and a test enforces it.

    python -m scripts.bbt_verses --count
    python -m scripts.bbt_verses --write
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "data/reference/vaniwiki/books"

# The corpus scope the steward set: KKSongs, SB, BG, CC and CB. The clone holds all of
# Prabhupada's books, so Nectar of Devotion, Upadesamrta and the rest are sitting there too -
# left out deliberately rather than missed, and a line away whenever the scope widens.
BOOKS = ("cc", "sb", "bg")
OUT = REPO / "data/reference/vaniwiki/bbt-verses.jsonl"

SOURCE = "https://github.com/vaniwiki/prabhupada-books"

# `===== Text =====` opens the verse; the next `=====` heading closes it. Verse lines are
# quoted with `> `, which is how the corpus marks recited text as against prose.
_HEADING = re.compile(r"^=+\s*(.*?)\s*=+\s*$")
_QUOTED = re.compile(r"^>\s?(.*)$")
_FRONT = re.compile(r"^---json\s*(\{.*?\})\s*---", re.S)
_WIKILINK = re.compile(r"\[\[[^\]]*\]\]")


# The same verse is addressed differently by different editions - GRETIL writes `BG 18.66`,
# this corpus writes `Bg. 18.66` - and that is not cosmetic. `verse_runs.SCRIPTURAL` decides
# whether a citation is scripture or a song that quotes it by matching the prefix, so
# `Bg. 18.66` would have lost that preference to a song title; and `best_printed_form` pools
# the printed forms of one passage by address, so a split label splits the pool.
CANONICAL = {"bg.": "BG", "bg": "BG", "sb.": "SB", "sb": "SB", "cc.": "Cc.", "cc": "Cc.",
             "cb.": "CB", "cb": "CB"}


def canonical_address(name: str) -> str:
    """One spelling per address, so two editions of a verse agree about what to call it."""
    parts = name.split(None, 1)
    if len(parts) == 2 and parts[0].lower() in CANONICAL:
        return f"{CANONICAL[parts[0].lower()]} {parts[1]}"
    return name


@dataclass(frozen=True)
class Verse:
    address: str                  # "Cc. Ādi 17.21", as the corpus itself names it
    text: str                     # the verse, and only the verse
    book: str                     # cc / sb / bg, as the corpus directories name them
    lines: tuple[str, ...] = ()

    def windows(self, sizes: tuple[int, ...] = (1, 2, 3)) -> list[str]:
        """The verse and its lines, so a half-quotation can match something its own size.

        Same reasoning as the printed Sanskrit: the archive quotes four to thirteen words while
        a verse runs longer, so offering only whole verses identifies a quotation and then
        refuses to score it.
        """
        out = [self.text]
        for size in sizes:
            for start in range(len(self.lines) - size + 1):
                window = " ".join(self.lines[start:start + size])
                if window and window != self.text:
                    out.append(window)
        return out


def verse_from_file(content: str) -> tuple[str, list[str]] | None:
    """The address and the verse lines from one corpus file, ignoring everything else.

    Returns None when the file carries no `Text` section - some entries are chapter summaries
    or notes rather than verses, and a parser that invented a verse for those would put prose
    into the index as scripture.
    """
    front = _FRONT.search(content)
    address = ""
    if front:
        try:
            address = json.loads(front.group(1)).get("name", "") or ""
        except json.JSONDecodeError:
            address = ""

    lines: list[str] = []
    inside = False
    for raw in content.splitlines():
        heading = _HEADING.match(raw.strip())
        if heading:
            # Only the Text section. Synonyms, Translation and Purport all close it.
            inside = heading.group(1).lower() == "text"
            continue
        if not inside:
            continue
        quoted = _QUOTED.match(raw.strip())
        if quoted:
            text = _WIKILINK.sub(" ", quoted.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                lines.append(text)
    if not address or not lines:
        return None
    return address, lines


def load(corpus: Path = CORPUS, books: tuple[str, ...] = BOOKS) -> list[Verse]:
    """Every verse on disk from the books in scope, verse text only.

    The Devanagari block each Śrīmad-Bhāgavatam file carries *before* its `===== Text =====`
    section is skipped for free, because the file's own `====== SB 1.2.10 ======` title is a
    heading and so closes any section - the parser is only ever inside `Text`.
    """
    found: list[Verse] = []
    for book in books:
        root = corpus / book
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.txt")):
            parts = path.relative_to(root).parts
            if len(parts) < 2:
                continue                         # chapter front matter, not a verse
            parsed = verse_from_file(path.read_text(encoding="utf-8", errors="replace"))
            if parsed is None:
                continue
            address, lines = parsed
            found.append(Verse(address=canonical_address(address), text=" ".join(lines),
                               book=book,
                               lines=tuple(lines)))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--find", default=None)
    args = parser.parse_args()

    verses = load()
    if not verses:
        raise SystemExit(f"nothing under {CORPUS} - clone vaniwiki/prabhupada-books first")

    per: dict[str, int] = {}
    for verse in verses:
        per[verse.book] = per.get(verse.book, 0) + 1
    print(f"{len(verses):,} verses from the Vedabase corpus (verse text only, no purports)")
    for book in sorted(per):
        print(f"  {book:8} {per[book]:>6,}")

    for address in ("Cc. Ādi 17.21", "SB 1.2.10", "BG 18.66"):
        one = next((v for v in verses if v.address == address), None)
        print(f"\n  {address}: {one.text[:92] if one else '(absent)'}")

    if args.find:
        from scripts.verse_match import VerseIndex
        index = VerseIndex([w for v in verses for w in v.windows()],
                           passages=[v.address for v in verses for _ in v.windows()])
        for candidate in index.rank(args.find, top=3):
            print(f"  {candidate.score:.3f}  {candidate.passage:<18} {candidate.verse[:70]}")
        found = index.find(args.find)
        print(f"\n-> {found.passage}: {found.verse[:80]}" if found
              else "\n-> unclear (nothing met the threshold)")

    if args.write:
        OUT.write_text("\n".join(json.dumps(
            {"address": v.address, "text": v.text, "book": v.book, "lines": list(v.lines),
             "source": SOURCE}, ensure_ascii=False) for v in verses), encoding="utf-8")
        print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
