"""Mirror the Gaudiya song lyrics from kksongs.org.

    python scripts/kksongs_mirror.py index          # collect song addresses from A-Z
    python scripts/kksongs_mirror.py fetch          # fetch songs not yet held
    python scripts/kksongs_mirror.py corpus         # write the lyric lines for the matcher

There is no openly-licensed bulk corpus of Bengali padavali anywhere; this is the only clean
machine-readable source, and the archive's longest measured transcription blackout - 41 words
of Bhaktivinoda Thakura's *Bhuliya tomare samsare asiya* - is exactly the material it holds.

Three rules the site's own shape imposes:

* **Lyrics only.** Every page runs LYRICS, then TRANSLATION, then remarks. Only the first
  section is taken. The translations are somebody's work and the archive does not need them.
* **Never /authors/purports/.** Those pages are Bhaktivedanta Book Trust and Prabhupada
  material, which is not KKSongs' to give away. The fetcher refuses that path outright.
* **Politely.** This is a volunteer site that has been up since 2001. One request at a time,
  with a pause, identifying itself, and resumable so it is never fetched twice.

Plain HTTP is enough - the pages are static HTML from the 2000s - so no scraping service and
no credits are needed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import html as html_lib
import json
from pathlib import Path
import re
import time
import unicodedata
import urllib.error
import urllib.request

INDEX = "http://kksongs.org/songs/song_{letter}.html"
AGENT = "lecture-archive/1.0 (Gaudiya lecture transcription research; contact via repository)"
FORBIDDEN = "/authors/purports/"

# Sections that end the lyrics. The page always runs LYRICS -> TRANSLATION -> remarks.
_END = re.compile(r"^(TRANSLATION|PURPORT|SYNONYMS|WORD[- ]FOR[- ]WORD|COMMENTARY|"
                  r"Remarks\s*/|UPDATED)", re.I)
_FIELD = re.compile(r"^(Song|Official|Book)?\s*Name:\s*(.*)$|^(Author|Language):\s*(.*)$", re.I)


@dataclass
class Song:
    url: str
    name: str = ""
    official: str = ""
    author: str = ""
    book: str = ""
    language: str = ""
    lyrics: list[str] = None

    def __post_init__(self) -> None:
        if self.lyrics is None:
            self.lyrics = []


def _lines(markup: str) -> list[str]:
    """The page as readable lines.

    Block tags become line breaks and everything else becomes a space — not nothing, because
    KKSongs wraps the first word of each line in its own tag, and joining without a space
    would weld it to the next word.
    """
    # These pages are Word exports: the source wraps long lines with real newlines *inside*
    # the text, so "ab\nkī ṭeka hamārī" is one lyric line, not two. The line structure lives
    # in the tags. Flatten the source newlines first, then let the block tags break lines.
    text = markup.replace("\r", "").replace("\n", " ")
    text = re.sub(r"(?i)<(br|/p|/tr|/div|/h\d)[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    # The site writes its diacritics as numeric entities, and many are combining marks:
    # "ṭ" arrives as "t" plus U+0323, not as U+1E6D. Composing to NFC keeps the stored
    # corpus canonical, so anything comparing strings to it does not have to know that.
    text = unicodedata.normalize("NFC", html_lib.unescape(text)).replace(" ", " ")
    return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]


def parse_song(markup: str, url: str = "") -> Song:
    """Header fields and the lyric lines, and nothing after them."""
    song = Song(url=url)
    lines = [line for line in _lines(markup) if line]
    collecting = False
    for line in lines:
        if not collecting:
            if re.match(r"^LYRICS\s*:", line, re.I):
                collecting = True
                rest = re.sub(r"^LYRICS\s*:\s*", "", line, flags=re.I).strip()
                if rest:
                    song.lyrics.append(rest)
            else:
                field = _FIELD.match(line)
                if field:
                    kind = (field.group(1) or field.group(3) or "").lower()
                    value = (field.group(2) or field.group(4) or "").strip()
                    if value.lower() in ("none", ""):
                        continue
                    if kind == "song":
                        song.name = value
                    elif kind == "official":
                        song.official = value
                    elif kind == "book":
                        song.book = value
                    elif kind == "author":
                        song.author = value
                    elif kind == "language":
                        song.language = value
            continue
        if _END.match(line):
            break
        song.lyrics.append(line)
    return song


def _get(url: str, pause: float) -> str:
    if FORBIDDEN in url:
        raise ValueError(f"refusing {url}: purports are BBT material, not KKSongs' to give")
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read()
    time.sleep(pause)
    return body.decode("utf-8", errors="replace")


def cmd_index(out: Path, pause: float) -> None:
    urls: list[str] = []
    for letter in "abcdefghijklmnopqrstuvwxyz":
        try:
            markup = _get(INDEX.format(letter=letter), pause)
        except urllib.error.HTTPError as error:
            print(f"  {letter}: HTTP {error.code}")
            continue
        found = re.findall(r'href="(https?://[^"]*?/songs/[a-z]/[^"]+\.html)"', markup, re.I)
        fresh = [u for u in dict.fromkeys(found) if FORBIDDEN not in u]
        urls += fresh
        print(f"  {letter}: {len(fresh)} songs")
    urls = list(dict.fromkeys(urls))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(urls), encoding="utf-8")
    print(f"\n{len(urls)} song addresses -> {out}")


def cmd_fetch(index: Path, out: Path, pause: float, limit: int) -> None:
    urls = [u.strip() for u in index.read_text(encoding="utf-8").splitlines() if u.strip()]
    held = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                held[row["url"]] = row
    todo = [u for u in urls if u not in held][:limit or None]
    print(f"{len(held)} already held, {len(todo)} to fetch")
    for n, url in enumerate(todo, 1):
        try:
            song = parse_song(_get(url, pause), url)
        except Exception as error:                      # noqa: BLE001 - one bad page must not stop a mirror
            print(f"  [{n}/{len(todo)}] {url} FAILED: {error}")
            continue
        held[url] = asdict(song)
        if n % 25 == 0 or n == len(todo):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in held.values()),
                           encoding="utf-8")
            print(f"  [{n}/{len(todo)}] {len(held)} songs held")
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in held.values()),
                   encoding="utf-8")
    print(f"{len(held)} songs -> {out}")


def cmd_corpus(songs: Path, out: Path, min_words: int) -> None:
    """One lyric line per row, which is the unit the verse matcher retrieves."""
    seen: set[str] = set()
    rows: list[str] = []
    for line in songs.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for lyric in row.get("lyrics", []):
            clean = lyric.strip()
            if len(clean.split()) >= min_words and clean.lower() not in seen:
                seen.add(clean.lower())
                rows.append(clean)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows), encoding="utf-8")
    print(f"{len(rows)} distinct lyric lines -> {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", type=Path, default=Path("data/reference/kksongs"))
    parser.add_argument("--pause", type=float, default=0.4, help="seconds between requests")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--limit", type=int, default=0, help="stop after this many (0 = all)")
    corpus = sub.add_parser("corpus")
    corpus.add_argument("--min-words", type=int, default=3)
    args = parser.parse_args(argv)

    if args.cmd == "index":
        cmd_index(args.dir / "song-urls.txt", args.pause)
    elif args.cmd == "fetch":
        cmd_fetch(args.dir / "song-urls.txt", args.dir / "songs.jsonl", args.pause, args.limit)
    else:
        cmd_corpus(args.dir / "songs.jsonl", args.dir / "lyric-lines.txt", args.min_words)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
