"""Caitanya-bhāgavata verses, from the full text rather than one web page per verse.

Vṛndāvana dāsa Ṭhākura's Caitanya-bhāgavata is the other text this archive quotes constantly,
and the steward has licensed the Bhumipati Dāsa / Gauḍīya-bhāṣya edition that wisdomlib serves.
Wisdomlib serves **one page per verse**, about 13,000 of them, and crawling that many pages off
a volunteer-run reference site to obtain a text that exists as a single file elsewhere is poor
manners. The Internet Archive holds the same edition as full text with the verse addresses
embedded, so the Antya-khaṇḍa costs **one download** instead of 3,494 requests.

**Ādi and Madhya are not available this way.** Their archive.org scans were OCR'd badly - one
item's language was auto-detected as Armenian with "confidence 1.0", and its text is numeric
noise - and the one complete PDF edition is behind hotlink protection. Those two khaṇḍas are
fetched from wisdomlib instead, by `scripts/wisdomlib_cb.py`, which is slower and politer.

**Two landmarks, not one.** Each verse is announced by a printed `Text 95` header and closed by
a `//CB, Antya 1.095//` marker. Both are OCR output and either can be wrong: the marker for
Text 95 actually reads `1.0905`, with a stray digit. So the chapter comes from the marker, the
verse number from the printed header, and a disagreement is counted rather than hidden.

Verse text only: `TRANSLATION` and `COMMENTARY` close it, by the same rule the rest of the
corpus follows.

    python -m scripts.caitanya_bhagavata --count
    python -m scripts.caitanya_bhagavata --write
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "data/reference/caitanya-bhagavata"
OUT = CORPUS / "cb-verses.jsonl"

# `//CB, Antya 1.001//` - the khanda, the chapter, and usually the verse.
MARKER = re.compile(r"//\s*CB,?\s*([A-Za-z-]+)\s*([0-9]+)\.([0-9]+)\s*//")

# The printed verse label, which is the authority on the verse number.
LABEL = re.compile(r"(?m)^[ \t]*Text[ \t]+([0-9]+(?:[-–][0-9]+)?)[ \t]*$")

# What closes the verse. Anything after these belongs to the translator or the commentator.
CLOSES = re.compile(r"\b(TRANSLATION|COMMENTARY|PURPORT)\b")

KHANDA = {"adi": "Ādi", "ādi": "Ādi", "madhya": "Madhya", "antya": "Antya"}


@dataclass(frozen=True)
class Verse:
    address: str                  # "CB Antya 1.95"
    text: str
    khanda: str
    lines: tuple[str, ...] = ()
    label_disagreed: bool = False  # the printed label and the marker gave different numbers

    def windows(self, sizes: tuple[int, ...] = (1, 2)) -> list[str]:
        out = [self.text]
        for size in sizes:
            for start in range(len(self.lines) - size + 1):
                window = " ".join(self.lines[start:start + size])
                if window and window != self.text:
                    out.append(window)
        return out


def _clean(block: str) -> list[str]:
    """The verse lines from one block: marker gone, page furniture dropped."""
    block = MARKER.sub(" ", block)
    lines = []
    for raw in block.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        # A bare number is a scanned page number, not a word of the verse.
        if re.fullmatch(r"[0-9ivxlcIVXLC.\-\[\]()]+", line):
            continue
        lines.append(line)
    return lines


def verses_from_archive_text(text: str) -> list[Verse]:
    """Every addressed verse in an archive.org full-text file of one khaṇḍa."""
    found: list[Verse] = []
    labels = [(m.start(), m.group(1)) for m in LABEL.finditer(text)]
    previous_end = 0

    for marker in MARKER.finditer(text):
        # The verse is whatever sits between the last printed label before this marker and the
        # marker itself - never reaching back past the previous verse.
        label_pos, label = None, None
        for position, value in labels:
            if previous_end <= position < marker.start():
                label_pos, label = position, value
        start = label_pos + len(f"Text {label}") if label_pos is not None else previous_end
        block = text[start:marker.start()]
        previous_end = marker.end()

        if CLOSES.search(block):
            block = block[:CLOSES.search(block).start()]
        lines = _clean(block)
        if not lines:
            continue

        khanda = KHANDA.get(marker.group(1).lower(), marker.group(1))
        chapter = int(marker.group(2))
        from_marker = int(marker.group(3))
        number = label.split("-")[0] if label else str(from_marker)
        disagreed = bool(label) and int(number) != from_marker
        verse = label if label else str(from_marker)
        found.append(Verse(address=f"CB {khanda} {chapter}.{verse}",
                           text=" ".join(lines), khanda=khanda, lines=tuple(lines),
                           label_disagreed=disagreed))
    return found


def load(corpus: Path = CORPUS) -> list[Verse]:
    """Every Caitanya-bhāgavata verse on disk, from whichever sources are present."""
    best: dict[str, Verse] = {}
    for path in sorted(corpus.glob("*_djvu.txt")):
        for verse in verses_from_archive_text(
                path.read_text(encoding="utf-8", errors="replace")):
            previous = best.get(verse.address)
            if previous is None or len(verse.text) > len(previous.text):
                best[verse.address] = verse

    extra = corpus / "wisdomlib-verses.jsonl"
    if extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            previous = best.get(row["address"])
            if previous is None or len(row["text"]) > len(previous.text):
                best[row["address"]] = Verse(address=row["address"], text=row["text"],
                                             khanda=row.get("khanda", ""),
                                             lines=tuple(row.get("lines", [])))
    return list(best.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    verses = load()
    if not verses:
        raise SystemExit(f"nothing under {CORPUS}")

    per: dict[str, int] = {}
    for verse in verses:
        per[verse.khanda] = per.get(verse.khanda, 0) + 1
    disagreed = sum(1 for v in verses if v.label_disagreed)
    print(f"{len(verses):,} Caitanya-bhāgavata verses (verse text only)")
    for khanda in sorted(per):
        print(f"  {khanda or '(unknown)':10} {per[khanda]:>6,}")
    print(f"  printed label and embedded marker disagreed on {disagreed} "
          f"({disagreed/len(verses):.1%}) - OCR slips in one or the other")

    for address in ("CB Antya 1.1", "CB Antya 1.95"):
        one = next((v for v in verses if v.address == address), None)
        print(f"\n  {address}: {one.text[:90] if one else '(absent)'}")

    if args.write:
        OUT.write_text("\n".join(json.dumps(
            {"address": v.address, "text": v.text, "khanda": v.khanda,
             "lines": list(v.lines)}, ensure_ascii=False) for v in verses), encoding="utf-8")
        print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
