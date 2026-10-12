"""Caitanya-bhāgavata Ādi and Madhya khaṇḍas, from wisdomlib, one verse at a time.

The Antya-khaṇḍa came off the Internet Archive as a single file - 3,352 verses, one download.
**Ādi and Madhya cannot be had that way.** Their archive.org scans were OCR'd badly (one item's
language was auto-detected as Armenian at "confidence 1.0", and its text is numeric noise), and
the one complete PDF edition answers 403 to everything, referer or not.

So they come from wisdomlib, which serves the same Bhumipati Dāsa / Gauḍīya-bhāṣya edition the
steward has licensed - but **one page per verse**, about 9,500 of them. That is a lot of
requests to a volunteer-run reference site, so this is built to be a good guest rather than a
fast one:

* Chapter pages first, which is 40-odd requests, and they carry every verse's link.
* Then verse pages, spaced, backing off on a refusal, and **skipping anything already on disk**,
  so an interrupted run resumes instead of starting over.
* Each page is saved raw before anything is parsed, so a parser change never means re-fetching.

Each verse page carries the verse in four scripts - Bengali, Devanagari, IAST and plain roman.
Only the IAST line is taken, and only the verse: the English translation and the Gauḍīya-bhāṣya
commentary are left where they are, by the same rule the rest of the corpus follows.

    python -m scripts.wisdomlib_cb --links          # chapter pages -> verse URLs
    python -m scripts.wisdomlib_cb --fetch          # the long, polite part
    python -m scripts.wisdomlib_cb --parse --write
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOME = REPO / "data/reference/caitanya-bhagavata"
PAGES = HOME / "wisdomlib"
LINKS = HOME / "wisdomlib-verse-urls.json"
OUT = HOME / "wisdomlib-verses.jsonl"

BOOK = "https://www.wisdomlib.org/hinduism/book/chaitanya-bhagavata"
AGENT = "lecture-archive/1.0 (devotional archive transcription research)"

# Somebody else's servers, and the archive is not in a hurry.
PAUSE = 1.5

# `Verse 1.11.100` or `Verse 1.1.27-28` - khanda, chapter, verse.
VERSE_LINK = re.compile(
    r'href="(/hinduism/book/chaitanya-bhagavata/d/doc\d+\.html)"[^>]*>\s*'
    r'Verse\s+([123])\.(\d+)\.([\d\-]+)')
CHAPTER_LINK = re.compile(
    r'href="(/hinduism/book/chaitanya-bhagavata/d/doc\d+\.html)"[^>]*>\s*'
    r'(?:Chapter|Book)\s')

KHANDA = {"1": "Ādi", "2": "Madhya", "3": "Antya"}

# The page prints the verse in four scripts in one blockquote. The third is IAST; the fourth
# drops the diacritics. IAST is what the rest of this corpus speaks.
_DIACRITIC = re.compile(r"[Ā-ſḀ-ỿ]")


def get(url: str, attempts: int = 4) -> str:
    wait = 15.0
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            print(f"    {exc.code} - waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
            wait *= 2
    raise RuntimeError("unreachable")


def collect_links() -> dict[str, str]:
    """Every verse URL in the Ādi and Madhya khaṇḍas, from the chapter pages.

    Antya is skipped: it is already complete from the Internet Archive, and fetching 3,352
    pages to obtain what is already on disk would be rude for no reason.
    """
    index = get(BOOK)
    chapters = sorted({path for path in CHAPTER_LINK.findall(index)})
    print(f"{len(chapters)} chapter pages")

    wanted: dict[str, str] = {}
    for position, path in enumerate(chapters, 1):
        time.sleep(PAUSE)
        page = get("https://www.wisdomlib.org" + path)
        found = 0
        for link, khanda, chapter, verse in VERSE_LINK.findall(page):
            if khanda == "3":
                continue                         # Antya already in hand
            address = f"CB {KHANDA[khanda]} {int(chapter)}.{verse}"
            wanted.setdefault(address, "https://www.wisdomlib.org" + link)
            found += 1
        print(f"  [{position}/{len(chapters)}] {path[-20:]} {found:>4} verse links "
              f"({len(wanted)} so far)", flush=True)
    return wanted


def fetch(links: dict[str, str], limit: int | None = None) -> None:
    PAGES.mkdir(parents=True, exist_ok=True)
    todo = [(a, u) for a, u in sorted(links.items())
            if not (PAGES / f"{a.replace(' ', '_').replace('.', '-')}.html").exists()]
    print(f"{len(links)} verses, {len(todo)} still to fetch")
    for position, (address, url) in enumerate(todo[:limit], 1):
        time.sleep(PAUSE)
        try:
            page = get(url)
        except Exception as exc:                 # noqa: BLE001 - one bad page must not stop it
            print(f"  [{position}] {address} FAILED {type(exc).__name__}", flush=True)
            continue
        (PAGES / f"{address.replace(' ', '_').replace('.', '-')}.html").write_text(
            page, encoding="utf-8")
        if position % 50 == 0 or position == 1:
            print(f"  [{position}/{min(len(todo), limit or len(todo))}] {address}", flush=True)


# Where the four renderings start and stop on the page.
BLOCK_START = re.compile(r"transliteration of verse\s*[\d.\-]+\s*:?", re.I)
BLOCK_END = re.compile(r"English translation", re.I)

# **The four renderings are terminated differently, and that is what tells them apart.**
# Bengali and Devanagari close with the danda - `॥ ১১৮ ॥` - the IAST line closes with ASCII
# pipes, `|| 118 ||`, and the diacritic-free fourth closes with `(118)`. So matching on the
# ASCII pipes identifies the IAST rendering uniquely, which beats guessing from diacritics:
# a first attempt did that and came back with the page's byline, "by Bhumipati Dasa | 2008".
IAST_RENDERING = re.compile(r"([^\n]{8,}?)\s*\|\|\s*[\d\-]+\s*\|\|")

_INDIC_SCRIPT = re.compile(r"[ऀ-ॿঀ-৿]")


def verse_from_page(page: str) -> tuple[str, list[str]] | None:
    """The address and the IAST verse from one wisdomlib verse page."""
    title = re.search(r"Verse\s+([123])\.(\d+)\.([\d\-]+)", page)
    if not title:
        return None
    address = f"CB {KHANDA[title.group(1)]} {int(title.group(2))}.{title.group(3)}"

    opened = BLOCK_START.search(page)
    if not opened:
        return None
    rest = page[opened.end():]
    closed = BLOCK_END.search(rest)
    block = rest[:closed.start()] if closed else rest[:4000]

    text = html.unescape(re.sub(r"<[^>]+>", "\n", block))
    for candidate in IAST_RENDERING.findall(text):
        line = re.sub(r"\s+", " ", candidate).strip()
        if not line or _INDIC_SCRIPT.search(line) or not _DIACRITIC.search(line):
            continue
        return address, [line]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--parse", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.links:
        links = collect_links()
        LINKS.parent.mkdir(parents=True, exist_ok=True)
        LINKS.write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{len(links)} verse URLs written to {LINKS.relative_to(REPO)}")
        return

    if args.fetch:
        if not LINKS.exists():
            raise SystemExit("run --links first")
        fetch(json.loads(LINKS.read_text(encoding="utf-8")), limit=args.limit)
        return

    if args.parse or args.write:
        verses = []
        for path in sorted(PAGES.glob("*.html")):
            parsed = verse_from_page(path.read_text(encoding="utf-8", errors="replace"))
            if parsed:
                address, lines = parsed
                verses.append({"address": address, "text": " ".join(lines),
                               "khanda": address.split()[1], "lines": lines,
                               "source": BOOK})
        print(f"{len(verses):,} verses parsed from {len(list(PAGES.glob('*.html'))):,} pages")
        for khanda in ("Ādi", "Madhya"):
            print(f"  {khanda:8} {sum(1 for v in verses if v['khanda'] == khanda):>6,}")
        if args.write and verses:
            OUT.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in verses),
                            encoding="utf-8")
            print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
