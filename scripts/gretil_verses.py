"""Read GRETIL's TEI Sanskrit into printed verses with their addresses.

The archive's Sanskrit problem is not transcription, it is **retrieval**. Only 6.0% of the
archive's Indic tokens sit in connected runs, and reading all 39 unmatched runs from five
lectures showed that about 26 are quotations - overwhelmingly Bhāgavatam and
Caitanya-caritāmṛta, which a song book cannot hold. He teaches from a fixed canon, so each
distinct verse needs identifying **once, ever**, after which its printed text is exact for all
3,766 lectures.

This supplies the Bhāgavatam and the Gītā. Both files state their own licence in the TEI
header - **CC BY-NC-SA 4.0** - which was checked here rather than taken on trust.
ShareAlike has one consequence worth remembering: an index derived from this and then
*published* must carry the same licence. `data/reference/` is not in git, so nothing is
published by building it.

**Two conventions, because the two files do not agree.** The Bhāgavatam closes a verse with
`// BhP_01.01.001* //` and separates pādas with `$`, `%` and `&`; the Gītā commentary closes
with `||BhG_1.1||` and uses `|` and `||`. Both are handled, and the Gītā file covers only
**chapters 1-17** - chapter 18 needs a separate source, as the sourcing research warned.

**One documented repair, verified here.** 584 of 844 starred long-metre Bhāgavatam verses repeat
their first half-verse in the XML. It is visible in the file: BhP 1.1.2, BhP 1.1.3 and
**BhP 3.9.10** - one of the Melbourne reference's own citations - each print
`ahny āpṛtārta-karaṇā ...` twice. The rule is to drop any pāda group identical to the one
before it, and the regression test is written on SB 3.9.10 by name.

    python -m scripts.gretil_verses --count
    python -m scripts.gretil_verses --find "jivasya tattva-jijnasa"
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GRETIL = REPO / "data/reference/gretil"
OUT = GRETIL / "verses.jsonl"

# `// BhP_03.09.010* //` or `||BhG_1.1||`. The star marks a long-metre verse, which is exactly
# the class carrying the duplication defect, so it is captured rather than discarded.
ADDRESS = re.compile(r"(?://|\|\|)\s*([A-Za-z]+)_([0-9][0-9.]*)(\*?)\s*(?://|\|\|)")

LINE = re.compile(r"<l\b[^>]*>(.*?)</l>", re.S)

# Pāda separators and half-verse marks from both conventions. They are typography, not words.
MARKERS = re.compile(r"[$%&|/]+")

# How GRETIL names a text against how this project cites it.
WORK_NAMES = {"BhP": "SB", "BhG": "BG"}


@dataclass(frozen=True)
class Verse:
    address: str                  # "SB 3.9.10"
    text: str                     # the printed verse, markers stripped
    work: str                     # "SB"
    long_metre: bool              # the starred class, which carried the duplication
    lines: tuple[str, ...] = ()   # the padas as printed, kept for length-comparable matching

    def windows(self, sizes: tuple[int, ...] = (1, 2, 3)) -> list[str]:
        """The verse and its padas, so a remembered fragment can match something its own size.

        A GRETIL verse runs twelve to twenty words while the archive quotes four to thirteen -
        a teacher cites a half-verse and carries on talking. Offering only whole verses would
        identify the quotation and then refuse to score it, because scoring a four-word run
        against a sixteen-word verse charges the recogniser twelve words nobody said there.

        Every window keeps the verse's own address as its passage, so `verse_match`'s margin -
        taken over the best candidate from a DIFFERENT passage - is not cancelled by a verse's
        own halves competing with each other.
        """
        out = [self.text]
        for size in sizes:
            for start in range(len(self.lines) - size + 1):
                window = " ".join(self.lines[start:start + size])
                if window and window != self.text:
                    out.append(window)
        return out


def _clean(line: str) -> str:
    """One TEI line as words: entities resolved, markers and the address removed.

    The order is deliberate. Tags are stripped **before** entities are resolved, because
    unescaping first would turn `&lt;` into `<` and the tag-stripping regex would then eat the
    text after it as if it were markup. And `html.unescape` is used rather than a handful of
    hand-written replacements because TEI permits numeric references as well as named ones -
    these files happen to carry literal UTF-8, but a fixture written with `&#257;` is just as
    valid and should not silently become the word `#257`.
    """
    import html
    line = re.sub(r"<[^>]+>", " ", ADDRESS.sub(" ", line))
    line = html.unescape(line)
    return re.sub(r"\s+", " ", MARKERS.sub(" ", line)).strip()


def _drop_repeated_groups(groups: list[str]) -> list[str]:
    """The documented repair: drop any pāda group identical to the one before it.

    GRETIL repeats the first half of most starred long-metre verses. Comparing only against
    the *previous* group is deliberate - a verse may legitimately repeat a refrain further
    along, and this is a known encoding artefact of adjacent duplication, not a licence to
    deduplicate a poem.
    """
    kept: list[str] = []
    for group in groups:
        if kept and group == kept[-1]:
            continue
        kept.append(group)
    return kept


def verses_from_tei(xml: str) -> list[Verse]:
    """Every addressed verse in a GRETIL TEI file, in document order."""
    found: list[Verse] = []
    pending: list[str] = []
    for raw in LINE.findall(xml):
        match = ADDRESS.search(raw)
        text = _clean(raw)
        if text:
            pending.append(text)
        if not match:
            continue                                   # verse not finished yet
        work = WORK_NAMES.get(match.group(1), match.group(1))
        numbers = ".".join(str(int(part)) for part in match.group(2).split("."))
        groups = _drop_repeated_groups(pending)
        body = " ".join(groups)
        pending = []
        if body:
            found.append(Verse(f"{work} {numbers}", body, work, bool(match.group(3)),
                               tuple(groups)))
    return found


def load(directory: Path = GRETIL) -> list[Verse]:
    """Every verse from every TEI file on disk, one entry per address.

    Where an address appears more than once - the Gītā file is a commentary and quotes verses
    again inside it - the longest text wins, which is the verse itself rather than the
    fragment the commentary picked up.
    """
    best: dict[str, Verse] = {}
    for path in sorted(directory.glob("*.xml")):
        for verse in verses_from_tei(path.read_text(encoding="utf-8")):
            previous = best.get(verse.address)
            if previous is None or len(verse.text) > len(previous.text):
                best[verse.address] = verse
    return list(best.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true")
    parser.add_argument("--find", default=None, help="a garbled recollection to look up")
    parser.add_argument("--write", action="store_true", help="write verses.jsonl")
    args = parser.parse_args()

    verses = load()
    if not verses:
        raise SystemExit(f"no TEI files in {GRETIL}")

    if args.count or not (args.find or args.write):
        works: dict[str, int] = {}
        for verse in verses:
            works[verse.work] = works.get(verse.work, 0) + 1
        print(f"{len(verses):,} verses with addresses")
        for work, total in sorted(works.items()):
            starred = sum(1 for v in verses if v.work == work and v.long_metre)
            print(f"  {work:4} {total:>6,}   ({starred:,} long-metre)")
        for address in ("SB 3.9.10", "SB 1.2.10", "BG 3.37"):
            one = next((v for v in verses if v.address == address), None)
            print(f"\n  {address}: {one.text[:96] if one else '(absent)'}")

    if args.find:
        from scripts.verse_match import VerseIndex
        index = VerseIndex([v.text for v in verses], passages=[v.address for v in verses])
        for candidate in index.rank(args.find, top=3):
            print(f"  {candidate.score:.3f}  {candidate.passage:<12} {candidate.verse[:76]}")
        found = index.find(args.find)
        print(f"\n-> {found.passage}: {found.text if False else found.verse[:90]}"
              if found else "\n-> unclear (nothing met the threshold)")

    if args.write:
        OUT.write_text("\n".join(json.dumps({"address": v.address, "text": v.text,
                                             "work": v.work, "long_metre": v.long_metre},
                                            ensure_ascii=False) for v in verses),
                        encoding="utf-8")
        print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
