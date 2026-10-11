"""The Bhagavad-gītā from Sanskrit Wikisource, to supply the chapter GRETIL cannot.

GRETIL's cleanly-licensed Gītā stops at **chapter 17**, so **BG 18.66 - the verse this archive
cites more than any other Gītā verse - is absent**. GRETIL's complete 700-verse Gītā is the BORI
critical edition, outside the CC layer, whose upstream asks that copies not be passed on. So the
sourcing research named Sanskrit Wikisource as the thing to check, and never checked it.

It holds all eighteen chapters, and the licence is **CC BY-SA 4.0**, read from the wiki's own
`siteinfo` rather than assumed. Each page is fetched with its revision id, because "the verse at
this address" is only reproducible if the revision is recorded.

**It is in Devanagari, and this project works in IAST.** Transliteration is a mechanical,
reversible re-encoding rather than a translation, so it is not the forbidden act of *producing*
scripture - but it is still a step that can go wrong silently, so it is checked rather than
trusted: chapters 1-17 exist in both sources, and `--check` scores this one against GRETIL
address by address. A transliteration that disagrees with an independent IAST edition is a
defect, and chapter 18 is only usable if the overlap agrees.

Each verse's own marker carries its chapter and number - `॥१८- १॥` - so the verses are
self-labelling and no mapping from Sanskrit chapter titles to numbers is needed.

    .venv-indic/Scripts/python.exe -m scripts.wikisource_gita --fetch
    .venv-indic/Scripts/python.exe -m scripts.wikisource_gita --check
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGES = REPO / "data/reference/wikisource/pages"
OUT = REPO / "data/reference/wikisource/gita-verses.jsonl"

API = "https://sa.wikisource.org/w/api.php"
PREFIX = "भगवद्गीता/"

# `॥१८- १॥` - the chapter and the verse, in Devanagari or Arabic digits, with the spacing the
# page actually uses rather than the spacing it ought to.
MARKER = re.compile(r"॥\s*([०-९0-9]+)\s*[-–]\s*([०-९0-9]+)\s*॥")
POEM = re.compile(r"<poem>(.*?)</poem>", re.S)
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Wiki markup that is not the verse: bold quotes, templates, references, comments.
_BOLD = re.compile(r"'{2,}")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_TAG = re.compile(r"<[^>]+>")
_DANDA = re.compile(r"[।॥]")


# Wikisource answered the fourteenth request in a row with 429. These are somebody else's
# servers and the archive is not in a hurry, so requests are spaced and a refusal is waited
# out rather than retried immediately.
PAUSE = 2.0


def _api(params: dict, attempts: int = 4) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json"})
    request = urllib.request.Request(f"{API}?{query}",
                                     headers={"User-Agent": "lecture-archive/1.0 (research)"})
    wait = 10.0
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == attempts - 1:
                raise
            print(f"    429 - waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
            wait *= 2
    raise RuntimeError("unreachable")


def licence() -> str:
    """What the wiki itself says its text may be used under."""
    rights = _api({"action": "query", "meta": "siteinfo", "siprop": "rightsinfo"})
    return rights["query"]["rightsinfo"]["text"]


def fetch(destination: Path = PAGES) -> list[Path]:
    """Every Gītā chapter page, one request each, saved with its revision id.

    One request per page on purpose. Asking for twenty pages' content in a single call returns
    eight of them with no `revisions` key at all - the API caps the content it will serve per
    request - and a loop that trusted the batch would have silently lost chapters 13 to 18,
    which is precisely the half this exists to supply.
    """
    destination.mkdir(parents=True, exist_ok=True)
    listing = _api({"action": "query", "list": "allpages", "apprefix": PREFIX, "aplimit": "50"})
    written = []
    for page in listing["query"]["allpages"]:
        title = page["title"]
        safe_name = re.sub(r"[^\w]+", "_", title)[:80]
        if (destination / f"{safe_name}.json").exists():
            print(f"  {title[:46]:<46} already fetched")
            continue
        time.sleep(PAUSE)
        got = _api({"action": "query", "prop": "revisions", "rvprop": "content|ids|timestamp",
                    "rvslots": "main", "titles": title})
        record = list(got["query"]["pages"].values())[0]
        if not record.get("revisions"):
            print(f"  no content: {title}")
            continue
        safe = re.sub(r"[^\w]+", "_", title)[:80]
        path = destination / f"{safe}.json"
        path.write_text(json.dumps({"title": title, "revid": record["revisions"][0]["revid"],
                                    "timestamp": record["revisions"][0]["timestamp"],
                                    "wikitext": record["revisions"][0]["slots"]["main"]["*"]},
                                   ensure_ascii=False), encoding="utf-8")
        written.append(path)
        print(f"  {title[:46]:<46} revid {record['revisions'][0]['revid']}")
    return written


def clean_line(line: str) -> str:
    """One line of a poem block as recited text: markup, dandas and the marker removed."""
    line = MARKER.sub(" ", line)
    line = _TEMPLATE.sub(" ", _TAG.sub(" ", _BOLD.sub("", line)))
    return re.sub(r"\s+", " ", _DANDA.sub(" ", line)).strip()


def verses_from_wikitext(wikitext: str) -> list[dict]:
    """Every addressed verse in one chapter page, in Devanagari.

    Only `<poem>` blocks are read. The pages carry Śaṅkara's commentary in `{{व्याख्या}}`
    templates - on chapter 18 that is 760,000 characters against the verses' few thousand - and
    a parser that took every line would index the commentary as scripture.
    """
    found: list[dict] = []
    for block in POEM.findall(wikitext):
        pending: list[str] = []
        for raw in block.splitlines():
            marker = MARKER.search(raw)
            text = clean_line(raw)
            if text:
                pending.append(text)
            if not marker:
                continue
            chapter = int(marker.group(1).translate(DIGITS))
            number = int(marker.group(2).translate(DIGITS))
            if pending:
                found.append({"chapter": chapter, "verse": number,
                              "lines": list(pending), "devanagari": " ".join(pending)})
            pending = []
    return found


def to_iast(devanagari: str) -> str:
    """Devanagari to IAST, by table rather than by judgement.

    A re-encoding, not a translation: the same letters in a different script, reversible and
    checkable, which is why it is allowed where *producing* a verse from memory is not.
    """
    from indic_transliteration import sanscript
    return sanscript.transliterate(devanagari, sanscript.DEVANAGARI, sanscript.IAST)


def load(directory: Path = PAGES) -> list[dict]:
    """Every Gītā verse on disk, as IAST, keyed by address, longest text winning."""
    best: dict[str, dict] = {}
    for path in sorted(directory.glob("*.json")):
        page = json.loads(path.read_text(encoding="utf-8"))
        for verse in verses_from_wikitext(page["wikitext"]):
            address = f"BG {verse['chapter']}.{verse['verse']}"
            text = to_iast(verse["devanagari"])
            previous = best.get(address)
            if previous is None or len(text) > len(previous["text"]):
                best[address] = {"address": address, "text": text,
                                 "devanagari": verse["devanagari"],
                                 "lines": [to_iast(line) for line in verse["lines"]],
                                 "source": f"https://sa.wikisource.org/?curid=&oldid={page['revid']}",
                                 "title": page["title"], "revid": page["revid"]}
    return list(best.values())


def comparable(text: str) -> str:
    """The letter sequence, with spaces and hyphens gone, for comparing two IAST editions.

    **Word boundaries must not be compared, and a first attempt that compared them measured
    the wrong thing entirely** - 12.3% token agreement, which read as a broken transliteration
    and was nothing of the kind. The two editions segment sandhi differently by convention:
    Wikisource prints `anantavijayaṃ ... sahadevaśca`, GRETIL `ananta-vijayaṃ ... sahadevaś
    ca`. Identical sounds, different typography. Sandhi is exactly why `verse_match.skeleton`
    drops boundaries too, so dropping them here is the same decision, not a convenience.
    """
    plain = "".join(c for c in unicodedata.normalize("NFKD", text)
                    if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", plain.lower())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--check", action="store_true", help="score against GRETIL on 1-17")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if args.fetch:
        print(f"licence: {licence()}")
        fetch()
        return

    verses = load()
    if not verses:
        raise SystemExit(f"nothing in {PAGES}; run --fetch first")

    chapters: dict[int, int] = {}
    for verse in verses:
        chapter = int(verse["address"].split()[1].split(".")[0])
        chapters[chapter] = chapters.get(chapter, 0) + 1
    print(f"{len(verses)} verses across {len(chapters)} chapters")
    print("  " + "  ".join(f"{c}:{chapters[c]}" for c in sorted(chapters)))

    eighteen = next((v for v in verses if v["address"] == "BG 18.66"), None)
    print(f"\n  BG 18.66: {eighteen['text'] if eighteen else '(absent)'}")
    if eighteen:
        print(f"            {eighteen['source']}")

    if args.check:
        from scripts.gretil_verses import load as load_gretil
        gretil = {v.address: v.text for v in load_gretil() if v.work == "BG"}
        shared = [v for v in verses if v["address"] in gretil]
        exact = sum(1 for v in shared if comparable(v["text"]) == comparable(gretil[v["address"]]))
        tokens = agree = 0
        worst = []
        for verse in shared:
            mine, theirs = comparable(verse["text"]), comparable(gretil[verse["address"]])
            same = sum(1 for a, b in zip(mine, theirs) if a == b)
            tokens += max(len(mine), len(theirs))
            agree += same
            if same < max(len(mine), len(theirs)):
                worst.append((same / max(1, max(len(mine), len(theirs))), verse["address"],
                              verse["text"], gretil[verse["address"]]))
        print(f"\nAGAINST GRETIL, on the {len(shared)} addresses both editions carry:")
        print(f"  identical after stripping diacritics: {exact}/{len(shared)} "
              f"({exact/max(1,len(shared)):.1%})")
        print(f"  token agreement:                      {agree/max(1,tokens):.1%}")
        worst.sort()
        print(f"\n  the {min(4, len(worst))} widest disagreements, to be read:")
        for share, address, mine, theirs in worst[:4]:
            print(f"    {address} ({share:.0%})")
            print(f"      wikisource: {mine[:86]}")
            print(f"      gretil    : {theirs[:86]}")

    if args.write:
        OUT.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in verses),
                       encoding="utf-8")
        print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
