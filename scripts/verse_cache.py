"""Remember every verse resolved by search, and refuse the ones that cannot be shipped.

    python scripts/verse_cache.py list
    python scripts/verse_cache.py add --heard "upaja prapanna" --verse "..." --source URL
    python scripts/verse_cache.py sources

Caitanya-caritamrta and Caitanya-bhagavata have no machine-readable text anywhere, so some
verses can only be found by searching for them. Searching is not the same act as producing:
what comes back is a located quotation with an address, not something recalled from a model's
weights — and models reproduce scripture exactly 32.6% of the time in English and 7.3% in
other languages, so producing is out of the question.

The cost objection that ruled out a paid per-lecture service does not apply, because this is
not a per-lecture cost. Measured on the Melbourne reference: 59 verse occurrences, 53 of them
distinct. That looks bad until you notice the unit is wrong — he teaches from a fixed canon
across 3,766 lectures. **Keyed by skeleton, each distinct verse is looked up once, ever**, and
the cache becomes the archive's own corpus, with provenance attached to every line.

The allowlist is the load-bearing part. Without it a search returns vedabase, and
Bhaktivedanta Book Trust text enters the corpus silently, undoing every licence decision the
archive has made. Default is deny: a site nobody has checked does not get in.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verse_match import VerseIndex, skeleton  # noqa: E402

# Every host the archive has actually checked, with the reason it was checked in.
# Adding a host means having read its licence, not having found it useful.
SOURCES: dict[str, dict] = {
    "gretil.sub.uni-goettingen.de": {
        "allow": True,
        "why": "CC BY-NC-SA 4.0 stated in each TEI file's own publicationStmt; bare verse text",
    },
    "sanskrit.wikisource.org": {
        "allow": True, "why": "CC BY-SA 4.0, and the community's own transcription",
    },
    "bn.wikisource.org": {
        "allow": True, "why": "CC BY-SA 4.0; the Bengali side of the same project",
    },
    "kksongs.org": {
        "allow": True,
        "why": "songs are Bhaktivinoda (d. 1914) and long out of copyright; the steward "
               "decided to rely on it and a permission note goes to the site. LYRICS AND "
               "METADATA ONLY - never /authors/purports/, which is BBT material",
    },
    "vedabase.io": {
        "allow": False, "why": "Bhaktivedanta Book Trust, in copyright. The single most "
                               "likely thing a search will return, and the one that must not get in",
    },
    "www.vedabase.com": {"allow": False, "why": "same BBT material under an older address"},
    "granthamandira.org": {
        "allow": False, "why": "no licence statement at all, and its own page says the "
                               "Bhagavatam was typed from BBT Folio",
    },
    "www.sacred-texts.com": {"allow": False, "why": "its terms forbid bulk fetching"},
}


def source_allowed(url: str) -> bool:
    """Is this address one the archive has cleared?

    Matches the host exactly, so ``vedabase.io.evil.example`` does not inherit
    ``vedabase.io``'s entry — and an unlisted host is refused rather than assumed.
    """
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    entry = SOURCES.get(host)
    return bool(entry and entry["allow"])


@dataclass
class Entry:
    """One verse, and where it was found."""

    key: str
    verse: str
    source: str
    heard: str = ""     # the garbling that first led here, kept for debugging


class VerseCache:
    """Verses resolved once and remembered, keyed by the matcher's own skeleton."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._entries: dict[str, Entry] = {}
        if self.path.exists():
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            for row in stored.get("verses", []):
                self._entries[row["key"]] = Entry(**row)

    def __len__(self) -> int:
        return len(self._entries)

    def recall(self, heard: str, **thresholds) -> Entry | None:
        """The verse behind this recognition, if it has been resolved before.

        Lookup is fuzzy, through the same index the matcher uses, and it has to be: no two
        recognisers garble a verse the same way, so the skeleton of what was *heard* is not a
        stable key. Only the skeleton of the *verse* is. The cache is therefore a corpus that
        is searched, not a dictionary that is indexed — which is the same thing the archive
        wants it to become anyway.
        """
        if not self._entries:
            return None
        rows = list(self._entries.values())
        found = VerseIndex([row.verse for row in rows]).find(heard, **thresholds)
        return rows[found.index] if found else None

    def remember(self, heard: str, verse: str, source: str) -> Entry:
        """Record a verse and its address. Refuses anything the archive cannot ship."""
        if not source:
            raise ValueError("a verse with no source is text somebody produced, not found")
        if not source_allowed(source):
            host = (urlparse(source).hostname or "?").lower()
            why = SOURCES.get(host, {}).get("why", "this host has never been checked")
            raise ValueError(f"refusing {host}: {why}")
        if not verse.strip():
            raise ValueError("empty verse")
        # Keyed by the VERSE's skeleton, so re-resolving the same verse from a different
        # garbling updates one entry rather than creating a near-duplicate.
        entry = Entry(key=skeleton(verse), verse=verse.strip(), source=source, heard=heard)
        self._entries[entry.key] = entry
        self._save()
        return entry

    def verses(self) -> list[str]:
        """Everything resolved so far, ready to hand to a VerseIndex."""
        return [e.verse for e in self._entries.values()]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [asdict(e) for e in self._entries.values()]
        self.path.write_text(json.dumps({"verses": rows}, indent=1, ensure_ascii=False),
                             encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", type=Path, default=Path("data/reference/verse-cache.json"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every verse resolved so far")
    sub.add_parser("sources", help="the allowlist, and why each host is on it")
    add = sub.add_parser("add", help="record a verse found by search")
    add.add_argument("--heard", required=True)
    add.add_argument("--verse", required=True)
    add.add_argument("--source", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "sources":
        for host, entry in sorted(SOURCES.items(), key=lambda kv: (not kv[1]["allow"], kv[0])):
            print(f"  {'ALLOW ' if entry['allow'] else 'REFUSE'}  {host}\n          {entry['why']}")
        return 0

    cache = VerseCache(args.cache)
    if args.cmd == "list":
        print(f"{len(cache)} verses in {args.cache}")
        for entry in cache._entries.values():
            print(f"  {entry.verse[:72]}\n      {entry.source}")
        return 0

    entry = cache.remember(args.heard, args.verse, args.source)
    print(f"remembered as {entry.key[:40]}\n  {entry.verse}\n  {entry.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
