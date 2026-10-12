"""The read-along page: play a lecture and highlight its transcript word by word.

This is the archive's product - a devotee reads while Gurudeva speaks - and it is also the one
test that tables cannot run. An alignment that drifts slowly scores well everywhere and is
obviously wrong the moment text is watched against audio. Expect this page to find faults that
every number so far has missed; that is it working.

Three things it must not do, because each would make it look right while being wrong:

- **Highlight word N when the aligner timed a different word N.** The aligner numbered
  `spoken_words(transcript)`; the page lays the same text out by paragraph with speaker labels
  and editorial brackets left visible. `paragraphs` and `check_alignment` refuse any lecture
  where the two numberings disagree, rather than show it shifted.
- **Present an unchecked alignment as a checked one.** Trust comes from the placement check in
  `scripts/compare_hosted` and nothing else - not `alignment_confidence`, which ranks but does
  not grade. Most lectures have never been checked, and the page says so on every one of them.
- **Hide audio the transcript has no words for.** Stretches longer than a real pause are marked
  in the text and on the timeline as untranscribed. They are not labelled kirtan or anything
  else: nothing available here can tell what they contain.

The output is a static folder under the gitignored `data/reference/`, because the alignments
and audio it points at live there too and are not ours to redistribute. Open its `index.html`
straight from disk; no server is needed.

    .venv-indic/Scripts/python.exe -m scripts.scoreable      # first, if the aligner has moved on
    .venv-indic/Scripts/python.exe -m scripts.read_along
    .venv-indic/Scripts/python.exe -m scripts.read_along --encode   # accurate-seeking audio copies

The `--encode` copies matter: browsers jump seconds short in the archive's VBR MP3s (see
`encode`). Without a copy a lecture still plays, and its page says that jumping is inaccurate.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts.compare_hosted import MISPLACED_RATIO
from scripts.forced_align import problems, spoken_words
from scripts.scoreable import MAX_GAP
from scripts.transcript_accuracy import fold, written_only

REPO = Path(__file__).resolve().parents[1]
LECTURES = REPO / "data/lectures"
ALIGNED = REPO / "data/reference/analysis/archive-alignment"
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
COMPARISON = REPO / "data/reference/analysis/hosted-comparison.json"
HEARD = REPO / "data/reference/analysis/hosted/elevenlabs"
PAGE = REPO / "scripts/read_along_page"
OUT = REPO / "data/reference/read-along"

Token = tuple[str, "int | None"]


def paragraphs(text: str) -> list[list[Token]]:
    """The transcript as the reader sees it, each spoken word carrying the aligner's number.

    Speaker labels, verse references and editorial notes stay on the page - a reader wants to
    know who is speaking and which verse is meant - but carry no number, because nobody said
    them and the aligner never saw them. Which characters are notes comes from
    `transcript_accuracy.written_only`, the same spans `spoken_words` removes, so the two cannot
    disagree about a note even when it runs across a line break. The result is still checked
    against `spoken_words`, because a numbering that drifts by one word is wrong from there on.
    """
    notes = written_only(text)
    out: list[list[Token]] = []
    index = 0
    at = 0
    for line in text.splitlines(keepends=True):
        start, end = at, at + len(line)
        at = end
        tokens: list[Token] = []
        cursor = start
        for note_start, note_end in notes:
            if note_end <= start or note_start >= end:
                continue
            a, b = max(note_start, start), min(note_end, end)
            for word in text[cursor:a].split():
                tokens.append((word, index))
                index += 1
            if text[a:b].strip():
                tokens.append((text[a:b].strip(), None))
            cursor = b
        for word in text[cursor:end].split():
            tokens.append((word, index))
            index += 1
        if tokens:
            out.append(tokens)

    laid_out = [word for para in out for word, number in para if number is not None]
    expected = spoken_words(text)
    if laid_out != expected:
        first = next((i for i, (a, b) in enumerate(zip(laid_out, expected)) if a != b),
                     min(len(laid_out), len(expected)))
        raise ValueError(f"the page would number this transcript differently from the aligner: "
                         f"{len(laid_out)} words laid out against {len(expected)} aligned, "
                         f"first disagreement at word {first}")
    return out


def check_alignment(paras: list[list[Token]], words: list[dict]) -> None:
    """Refuse an alignment whose words are not the page's words at the same numbers."""
    by_index = {number: word for para in paras for word, number in para if number is not None}
    wrong = [w for w in words if by_index.get(w["index"]) != w["word"]]
    if wrong:
        w = wrong[0]
        raise ValueError(f"{len(wrong)} timed words do not match the transcript at their index; "
                         f"first: #{w['index']} timed as {w['word']!r}, "
                         f"page has {by_index.get(w['index'])!r}")


# Below this share of words carrying over, an old alignment is not the same transcript under a
# changed cleanup rule but a different text, and is refused rather than carried.
CARRY_OVER_FLOOR = 0.9


def renumber(paras: list[list[Token]], words: list[dict]) -> tuple[list[dict], int]:
    """Carry an alignment made under an older cleanup rule onto the current numbering.

    Returns the carried words, renumbered, and how many were dropped because the current rule
    treats them as notes - his name written as a label, a verse reference. Their timings go with
    them; every other word keeps the time the aligner gave it. Those times were found with the
    dropped words treated as speech, so they may sit late after each one, and the page says so.
    """
    from difflib import SequenceMatcher
    current = [word for para in paras for word, number in para if number is not None]
    old = sorted(words, key=lambda w: w["index"])
    matcher = SequenceMatcher(None, [w["word"] for w in old], current, autojunk=False)
    carried = [{**old[block.a + k], "index": block.b + k}
               for block in matcher.get_matching_blocks() for k in range(block.size)]
    if len(carried) < CARRY_OVER_FLOOR * min(len(old), len(current)):
        raise ValueError(f"only {len(carried)} of {len(old)} timed words carry over to the "
                         f"current transcript - a different text, not a changed rule")
    return carried, len(old) - len(carried)


def untranscribed(words: list[dict], duration: float,
                  max_gap: float = MAX_GAP) -> list[tuple[float, float]]:
    """Stretches of the recording the transcript has no words for.

    The same rule `scoreable_spans` breaks on - a silence longer than any pause the verified
    Melbourne reference shows - plus the head and tail, where a span by construction never
    reaches. What is in these stretches is unknown, and the page says only that.
    """
    gaps = []
    edge = 0.0
    for word in words:
        if word["start"] - edge > max_gap:
            gaps.append((edge, word["start"]))
        edge = max(edge, word["end"])
    if duration - edge > max_gap:
        gaps.append((edge, duration))
    return gaps


# A word counts as placed where the recogniser heard it within this. The four sound lectures
# agree with ElevenLabs to a median of 0.02 s, so a second is generous, not strict.
AGREE_SECONDS = 1.0

# Consecutive matching tokens needed before a pairing is believed. A single common word paired
# alone once put `ei` against another occurrence twenty-five seconds away.
MIN_RUN = 3

# Disagreeing words this close together are one fault; fewer than this many are not shown.
REGION_JOIN = 10.0
MIN_REGION = 3


def word_check(words: list[dict], heard: list[dict]) -> dict[int, float]:
    """Seconds between where the aligner put each word and where a recogniser heard it.

    Keyed by the aligner's word index, for the words that sit in a run of at least `MIN_RUN`
    tokens both sides agree on. Words outside such runs are unchecked, not good.
    """
    from difflib import SequenceMatcher
    ours = [(token, w["index"], w["start"])
            for w in sorted(words, key=lambda w: w["index"]) for token in fold(w["word"])]
    theirs = [(token, h["s"]) for h in heard if h.get("s") is not None for token in fold(h["w"])]
    matcher = SequenceMatcher(None, [t for t, _, _ in ours], [t for t, _ in theirs],
                              autojunk=False)
    offsets: dict[int, float] = {}
    for block in matcher.get_matching_blocks():
        if block.size < MIN_RUN:
            continue
        for k in range(block.size):
            _, index, start = ours[block.a + k]
            offsets.setdefault(index, round(start - theirs[block.b + k][1], 3))
    return offsets


def disagreements(words: list[dict], offsets: dict[int, float]) -> list[list]:
    """Stretches where several checked words in a row sit away from where they were heard."""
    regions, run = [], []

    def close():
        if len(run) >= MIN_REGION:
            regions.append([run[0]["start"], run[-1]["end"], len(run)])
        run.clear()

    for word in sorted(words, key=lambda w: w["index"]):
        offset = offsets.get(word["index"])
        if offset is None:
            continue
        if abs(offset) <= AGREE_SECONDS:
            close()
        else:
            if run and word["start"] - run[-1]["end"] > REGION_JOIN:
                close()
            run.append(word)
    close()
    return [[round(a, 3), round(b, 3), n] for a, b, n in regions]


def verification(slug: str, comparison: dict) -> dict:
    """Whether this lecture's alignment has been checked, and what the check found.

    Only the placement check counts: a lecture scoring far worse inside its trusted spans than
    over its whole file has its words in the wrong places. It needs a recogniser's words, so
    most lectures have never been through it - and those are `unverified`, not good.
    """
    for row in comparison.get("lectures", []):
        if row["slug"] == slug:
            systems = {name: {"span_error": one["span_error"],
                              "whole_file_error": one["whole_file_error"],
                              "ratio": round(one["span_error"] / one["whole_file_error"], 3)
                              if one["whole_file_error"] else None}
                       for name, one in row["systems"].items()}
            ratios = [one["ratio"] for one in systems.values() if one["ratio"] is not None]
            return {"status": "verified", "limit": MISPLACED_RATIO, "systems": systems,
                    "worst_ratio": max(ratios) if ratios else None}
    for row in comparison.get("excluded", []):
        if row["slug"] == slug:
            return {"status": "failed", "limit": MISPLACED_RATIO,
                    "systems": {name: {"ratio": ratio} for name, ratio in row["ratios"].items()},
                    "worst_ratio": max(row["ratios"].values())}
    return {"status": "unverified", "limit": MISPLACED_RATIO}


# How far a listening copy's length may differ from the original's before it is not trusted to
# share the original's clock. Re-encoding at a constant bitrate measured identical to the sample.
COPY_TOLERANCE = 0.05


def media_seconds(path: Path) -> float | None:
    """The length ffprobe reports, or None when there is no readable file."""
    if not path.exists():
        return None
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def copy_matches(copy_seconds: float | None, original_seconds: float) -> bool:
    return copy_seconds is not None and abs(copy_seconds - original_seconds) <= COPY_TOLERANCE


def listening_copy(slug: str) -> Path:
    return OUT / "audio" / f"{slug}.mp3"


def encode(slug: str) -> None:
    """A constant-bitrate copy of one recording, which browsers can seek accurately.

    The archive's MP3s are variable-bitrate, and measured in Edge on a 61-minute lecture a jump
    to 5, 25 and 50 minutes landed 4.4, 6.7 and 8.6 s short - while the player reported the
    time that was asked for, so every highlight after a jump ran seconds ahead of the voice.
    The same file re-encoded at a constant bitrate landed within 0.04 s at all three, and so
    did AAC and Opus copies. Decoding was not the fault: ffmpeg and libsndfile place the audio
    identically, so the copy keeps the clock the aligner timed against.
    """
    destination = listening_copy(slug)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part.mp3")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(LECTURES / slug / "audio.mp3"),
                    "-c:a", "libmp3lame", "-b:a", "128k", str(partial)], check=True)
    partial.replace(destination)


def build_lecture(entry: dict, comparison: dict) -> dict:
    """Everything the player needs for one lecture, checked before it is written."""
    slug = entry["slug"]
    folder = LECTURES / slug
    record = json.loads((ALIGNED / f"{slug}.json").read_text(encoding="utf-8"))
    paras = paragraphs((folder / "transcript.txt").read_text(encoding="utf-8"))
    timed, legacy = record["words"], None
    try:
        check_alignment(paras, timed)
    except ValueError:
        # Timed under an older cleanup rule. Carried over only if it is the same text.
        timed, dropped = renumber(paras, timed)
        check_alignment(paras, timed)
        legacy = {"dropped": dropped}

    words = sorted(timed, key=lambda w: w["index"])
    duration = record["audio_seconds"]
    found = problems([SimpleNamespace(start=w["start"], end=w["end"]) for w in words], duration)
    found += [p for p in record.get("invariants_violated", []) if p not in found]

    # Word times from a recogniser, where one has read this lecture. Sarvam reports segments of
    # 10-60 s, far too coarse to say where a word is, so only ElevenLabs is used.
    heard_path = HEARD / f"{slug}.json"
    offsets, check = {}, None
    if heard_path.exists():
        heard = json.loads(heard_path.read_text(encoding="utf-8"))
        if heard.get("unit", "word") == "word":
            offsets = word_check(words, heard["words"])
            regions = disagreements(words, offsets)
            check = {"against": "ElevenLabs", "words_checked": len(offsets),
                     "words_off": sum(1 for o in offsets.values() if abs(o) > AGREE_SECONDS),
                     "agree_seconds": AGREE_SECONDS, "regions": regions,
                     "seconds_in_regions": round(sum(b - a for a, b, _ in regions), 1)}

    spoken = sum(1 for para in paras for _, number in para if number is not None)
    timing: list = [None] * spoken
    spans = [(s["start"], s["end"]) for s in entry["spans_detail"]]
    for w in words:
        inside = any(start <= w["start"] and w["end"] <= end for start, end in spans)
        timing[w["index"]] = [round(w["start"], 3), round(w["end"], 3), 1 if inside else 0,
                              offsets.get(w["index"])]

    original = media_seconds(folder / "audio.mp3")
    copy = listening_copy(slug)
    copy_seconds = media_seconds(copy)
    exact = original is not None and copy_matches(copy_seconds, original)

    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return {
        "slug": slug,
        "title": meta.get("title") or slug,
        "source_url": meta.get("url"),
        "audio": f"audio/{slug}.mp3" if exact else f"../../lectures/{slug}/audio.mp3",
        "exact_seek": exact,
        "copy_rejected": copy_seconds is not None and not exact,
        "duration": duration,
        "verification": verification(slug, comparison),
        "word_check": check,
        "legacy": legacy,
        "problems": found,
        "duplicate_of": entry.get("duplicate_of"),
        "records_other_speakers": entry.get("transcript_records_other_speakers"),
        "transcript_words": spoken,
        "words_placed": len(words),
        "share_of_audio": entry["share_of_audio"],
        "spans": [[round(a, 3), round(b, 3)] for a, b in spans],
        "untranscribed": [[round(a, 3), round(b, 3)] for a, b in untranscribed(words, duration)],
        "paragraphs": [[[word, number] for word, number in para] for para in paras],
        "timing": timing,
    }


def catalogue_row(lecture: dict) -> dict:
    keys = ("slug", "title", "duration", "verification", "word_check", "problems", "duplicate_of",
            "exact_seek", "legacy",
            "records_other_speakers", "transcript_words", "words_placed", "share_of_audio")
    return {key: lecture[key] for key in keys}


def as_script(name: str, value) -> str:
    """Data as a script assignment, so the pages work opened from disk where fetch() cannot."""
    return f"window.{name} = {json.dumps(value, ensure_ascii=False, separators=(',', ':'))};\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="build just these slugs")
    parser.add_argument("--encode", action="store_true",
                        help="make constant-bitrate listening copies first, where missing "
                             "(CPU-heavy: about 6 min a lecture while the aligner runs)")
    args = parser.parse_args()

    manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    aligned = {p.stem for p in ALIGNED.glob("*.json")} - {"SUMMARY"}
    listed = {entry["slug"] for entry in manifest["detail"]}
    if aligned - listed:
        raise SystemExit(f"{len(aligned - listed)} aligned lecture(s) are missing from the span "
                         f"manifest, so the page would silently omit them. Run first:\n"
                         f"  .venv-indic/Scripts/python.exe -m scripts.scoreable")

    (OUT / "lectures").mkdir(parents=True, exist_ok=True)
    for asset in PAGE.iterdir():
        shutil.copy2(asset, OUT / asset.name)

    rows, refused = [], []
    for entry in manifest["detail"]:
        if args.only and entry["slug"] not in args.only:
            continue
        try:
            lecture = build_lecture(entry, comparison)
        except ValueError as error:
            refused.append({"slug": entry["slug"], "reason": str(error)})
            print(f"REFUSED {entry['slug'][:56]}\n        {error}")
            continue
        if args.encode and not lecture["exact_seek"]:
            print(f"encoding {entry['slug'][:60]}", flush=True)
            encode(entry["slug"])
            lecture = build_lecture(entry, comparison)
        if lecture["copy_rejected"]:
            print(f"COPY NOT USED {entry['slug'][:50]}: its length differs from the original "
                  f"by more than {COPY_TOLERANCE}s, so it may not share the aligner's clock")
        (OUT / "lectures" / f"{entry['slug']}.js").write_text(
            as_script("LECTURE", lecture), encoding="utf-8")
        rows.append(catalogue_row(lecture))

    (OUT / "catalogue.js").write_text(
        as_script("CATALOGUE", {"lectures": rows, "refused": refused, "max_gap": MAX_GAP,
                                "misplaced_ratio": MISPLACED_RATIO}), encoding="utf-8")

    by_status: dict[str, int] = {}
    for row in rows:
        status = row["verification"]["status"]
        by_status[status] = by_status.get(status, 0) + 1
    print(f"{len(rows)} lectures written: "
          + ", ".join(f"{n} {s}" for s, n in sorted(by_status.items())))
    inexact = [row["slug"] for row in rows if not row["exact_seek"]]
    if inexact:
        print(f"{len(inexact)} still play the archive's VBR MP3, where a jump lands seconds "
              f"short (flagged on the page). Make copies with --encode.")
    broken = [row["slug"] for row in rows if row["problems"]]
    if broken:
        print(f"{len(broken)} with broken timing invariants (shown, and flagged on the page): "
              + ", ".join(broken))
    if refused:
        print(f"{len(refused)} refused - listed on the index page with the reason")
    print(f"\nopen {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
