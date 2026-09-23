"""Mirror the official archive: every lecture that has both audio and a transcript.

taptajivanam.com publishes 112 of Gour Govinda Swami's lectures, and 100 of them carry an
official transcript beside the recording. That is about 425,000 words of human-made text over
roughly seventy-eight hours of speech - against which this project has, so far, measured
everything on one lecture.

Two things make this corpus different from the Melbourne reference, and both matter more than
its size.

**The transcripts have no timings and no diarisation.** They are prose, in paragraphs. Which
makes them the honest test of forced alignment: not cue-shaped text already bounded by a human,
but a published document that has to be placed against the audio from nothing.

**They are not verbatim.** They are edited for publication, and questioner turns are largely
left out - so the audio contains speech the text does not. A recogniser scored against them will
be charged for words it heard correctly. That is a property of the corpus, not a defect to be
fixed here, and it is why this script records what it fetched rather than pretending the text is
ground truth.

Polite by construction: the page HTML is already cached under `data/.triage_cache/` from the
triage pass, so no page is fetched twice, and audio downloads are spaced and resumable. Nothing
is re-downloaded that is already on disk.

    python scripts/taptajivanam_mirror.py plan        # what would be fetched, and how big
    python scripts/taptajivanam_mirror.py fetch       # transcripts + audio, resumable
    python scripts/taptajivanam_mirror.py fetch --limit 10 --solo
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import re  # noqa: E402

from fetch_lecture import P_RE, extract_mp3, slugify, strip_tags  # noqa: E402

# The site runs two page templates. The older one marks the lecture body with dir="ltr" AND a
# justified style; the newer one drops the dir attribute. The triage pass counted 100 usable
# transcripts by trying both, so this does the same - anything stricter silently loses a third of
# the corpus, which is exactly the kind of quiet shortfall that looks like the site's fault.
_NEWER = re.compile(r'<p style="text-align:\s*justify;?"[^>]*>(.*?)</p>', re.I | re.S)


def transcript_of(page: str) -> str:
    paragraphs = [strip_tags(p) for p in P_RE.findall(page)]
    if len([p for p in paragraphs if len(p) > 40]) < 3:
        paragraphs = [strip_tags(p) for p in _NEWER.findall(page)]
    return "\n\n".join(p for p in paragraphs if len(p) > 40).strip()


TRIAGE = REPO / "data/lecture_triage.tsv"
CACHE = REPO / "data/.triage_cache"
OUT = REPO / "data/lectures"

# The site was already crawled once for triage. Leave a gap between audio downloads anyway:
# this is a devotional archive run on someone's hosting, not a CDN.
PAUSE_SECONDS = 2.0


def truthy(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def lectures(solo_only: bool = False) -> list[dict]:
    """Every lecture with both a transcript and audio, hardest-to-dispute first.

    `solo_only` keeps those whose transcript records no other speaker at all. Those are the ones
    where the missing-questioner problem is smallest, so they are the fairest place to measure.
    """
    rows = list(csv.DictReader(TRIAGE.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
    keep = [r for r in rows
            if truthy(r["has_transcript"]) and (truthy(r["has_audio"]) or truthy(r["js_audio"]))]
    if solo_only:
        keep = [r for r in keep if r["discussion"].strip() and float(r["discussion"]) == 0]
    # Most English first: those are the ones whose alignment we can judge against the systems
    # that emit their own word times.
    keep.sort(key=lambda r: -float(r["english_pct"] or 0))
    return keep


def page_html(row: dict) -> str | None:
    """The lecture page, from the triage cache if it is there."""
    cached = CACHE / f"a{row['aid']}.html"
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")
    try:
        request = urllib.request.Request(row["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            html = response.read().decode("utf-8", errors="replace")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(html, encoding="utf-8")
        time.sleep(PAUSE_SECONDS)
        return html
    except (urllib.error.URLError, OSError) as exc:
        print(f"    page unavailable: {str(exc)[:80]}")
        return None


def encoded(url: str) -> str:
    """The same URL with the path made legal.

    These filenames were typed by a person: "19920630_AA_BBSR_Arrival from USA_No Question of
    Disappointment....mp3". urllib refuses a path containing a space outright, and the refusal is
    an InvalidURL, which is neither a URLError nor an OSError - so it escapes the obvious except
    clause and takes the whole run with it.
    """
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(
        path=urllib.parse.quote(parts.path, safe="/%")))


def download(url: str, destination: Path) -> bool:
    """Fetch audio to a temporary name, then rename - so a half file is never mistaken for done."""
    partial = destination.with_suffix(".part")
    try:
        request = urllib.request.Request(encoded(url), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=300) as response, partial.open("wb") as out:
            while chunk := response.read(1 << 16):
                out.write(chunk)
        partial.replace(destination)
        return True
    except Exception as exc:                       # one unreachable lecture must not end the run
        partial.unlink(missing_ok=True)
        print(f"    audio failed: {type(exc).__name__}: {str(exc)[:70]}")
        return False


def fetch_one(row: dict) -> dict:
    """One lecture's transcript, audio and provenance. Anything already on disk is left alone."""
    html = page_html(row)
    if html is None:
        return {"aid": row["aid"], "state": "no page"}

    slug = slugify(row["url"])
    folder = OUT / slug
    folder.mkdir(parents=True, exist_ok=True)
    transcript_path, audio_path = folder / "transcript.txt", folder / "audio.mp3"

    transcript = transcript_of(html)
    if len(transcript.split()) < 200:
        return {"aid": row["aid"], "slug": slug, "state": "transcript too short to be the lecture"}
    try:
        mp3_url = extract_mp3(html, row["url"])
    except SystemExit:                             # no static <source>; the page injects it by JS
        return {"aid": row["aid"], "slug": slug, "state": "audio url is JavaScript-injected"}

    if not transcript_path.exists():
        transcript_path.write_text(transcript, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({
        "url": row["url"], "mp3_url": mp3_url, "slug": slug, "aid": row["aid"],
        "title": row["title"], "source": "taptajivanam.com",
        "transcript_is_verbatim": False,
        "note": "published transcript: no timings, no diarisation, questioner turns largely absent",
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    if audio_path.exists():
        return {"aid": row["aid"], "slug": slug, "state": "already here",
                "words": len(transcript.split()), "mb": audio_path.stat().st_size / 1e6}
    if not download(mp3_url, audio_path):
        return {"aid": row["aid"], "slug": slug, "state": "audio failed"}
    time.sleep(PAUSE_SECONDS)
    return {"aid": row["aid"], "slug": slug, "state": "fetched",
            "words": len(transcript.split()), "mb": audio_path.stat().st_size / 1e6}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["plan", "fetch"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--solo", action="store_true",
                        help="only lectures whose transcript records no other speaker")
    args = parser.parse_args()

    chosen = lectures(args.solo)[:args.limit]
    if args.stage == "plan":
        words = sum(int(r["words"]) for r in chosen if r["words"].strip().isdigit())
        print(f"{len(chosen)} lectures, {words:,} transcript words")
        print(f"~{words / 91 / 60:.0f} hours of audio at the 91 wpm measured on the one we have")
        already = sum(1 for r in chosen if (OUT / slugify(r["url"]) / "audio.mp3").exists())
        print(f"{already} already downloaded, {len(chosen) - already} to go")
        return

    done = []
    for index, row in enumerate(chosen, 1):
        print(f"[{index}/{len(chosen)}] {row['title'][:54]}", flush=True)
        try:
            result = fetch_one(row)
        except Exception as exc:                   # a mirror that stops at the first oddity is
            result = {"aid": row["aid"],           # not a mirror; record it and keep going
                      "state": f"{type(exc).__name__}: {str(exc)[:70]}"}
        done.append(result)
        if result.get("mb"):
            print(f"    {result['state']}: {result['words']:,} words, {result['mb']:.0f} MB",
                  flush=True)
        else:
            print(f"    {result['state']}", flush=True)

    fetched = [d for d in done if d["state"] in ("fetched", "already here")]
    (REPO / "data/lectures/MIRROR.json").write_text(json.dumps({
        "source": "taptajivanam.com",
        "lectures": done,
        "usable": len(fetched),
        "total_words": sum(d.get("words", 0) for d in fetched),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(fetched)}/{len(chosen)} lectures on disk, "
          f"{sum(d.get('words', 0) for d in fetched):,} transcript words")


if __name__ == "__main__":
    main()
