"""Where a transcript can be trusted, and therefore where a recogniser may be graded.

The archive's 78 lectures carry published transcripts that were never meant to be references.
They omit questioner turns, six of them stop while the recording continues, and all of them are
edited for reading rather than transcribed verbatim. Graded naively, a recogniser is charged for
every word it hears correctly in a stretch the transcript does not cover - which is how a good
model is made to look bad by a gap in the paper.

What this produces is deliberately the narrowest useful thing: **one boolean per stretch of
audio, is there reference text here or not.** Not a taxonomy of what the audio contains. That
was attempted and abandoned on evidence: voice-activity detection finds 27 seconds of speech in
ninety for kirtan and 24 for teaching, and Whisper reads Sanskrit prayers as Malayalam, so
nothing available here tells chanting from a class.

Fortunately the narrow question is the one grading depends on. Whether the untranscribed stretch
is chanting or Gurudeva still speaking, grading against a transcript that omits it is wrong
either way.

    .venv-indic/Scripts/python.exe -m scripts.scoreable          # manifest for every alignment
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALIGNED = REPO / "data/reference/analysis/archive-alignment"
OUT = REPO / "data/reference/analysis/scoreable-spans.json"

# Measured on the Melbourne reference, which was verified cue by cue against the audio and whose
# pauses are therefore normal by definition: 99% of its gaps between words are under 2.8s and
# 99.9% under 7.2s. Ten seconds keeps every ordinary pause and cuts only the unusual - where the
# transcript may simply not cover what is there.
MAX_GAP = 10.0

# Below this a stretch says nothing about a recogniser, and its boundary effects outweigh its
# content: a model's first word may straddle the edge either way.
MIN_WORDS = 5


@dataclass
class Span:
    """A stretch of audio with reference text for all of it."""

    start: float
    end: float
    words: list[str]


def scoreable_spans(words: list[dict], max_gap: float = MAX_GAP,
                    min_words: int = MIN_WORDS) -> list[Span]:
    """The stretches a recogniser can fairly be graded on.

    A span runs from a word to a word, never beyond - so audio after the transcript ends is
    excluded by construction, which is what the six early-stopping lectures need. Inside, the
    run breaks wherever the silence is longer than a real pause, because the transcript may not
    cover what is in it.
    """
    if not words:
        return []

    spans, run = [], [words[0]]
    for previous, word in zip(words, words[1:]):
        if word["start"] - previous["end"] > max_gap:
            spans.append(run)
            run = []
        run.append(word)
    spans.append(run)

    return [Span(start=group[0]["start"], end=group[-1]["end"],
                 words=[w["word"] for w in group])
            for group in spans if len(group) >= min_words]


def summarise(spans: list[Span], duration: float) -> dict:
    seconds = sum(s.end - s.start for s in spans)
    return {
        "spans": len(spans),
        "scoreable_seconds": round(seconds, 1),
        "words": sum(len(s.words) for s in spans),
        "share_of_audio": round(seconds / duration, 4) if duration > 0 else 0.0,
    }


def records_other_speakers() -> dict[str, bool]:
    """Which transcripts admit that somebody other than Gurudeva spoke.

    This decides how far a lecture can be trusted INSIDE a span, not just at its edges. These
    transcripts omit questioner turns, and a question of three to ten seconds falls under the gap
    threshold - so it stays inside a span, invisible, and every word a recogniser correctly hears
    there is charged against it.

    Measured over the aligned lectures: those recording other speakers carry 6.3 seconds of
    2-10s gap per minute against 4.3 for those that do not. About two seconds a minute, or
    roughly 3% of audio, that may be speech with no reference. The sample is small and the
    difference could be speaking style, so this marks the lectures rather than excluding them.
    """
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    from taptajivanam_mirror import slugify
    triage = REPO / "data/lecture_triage.tsv"
    if not triage.exists():
        return {}
    return {slugify(r["url"]): float(r["discussion"] or 0) > 0
            for r in csv.DictReader(triage.read_text(encoding="utf-8").splitlines(),
                                    delimiter="	")}


def duplicate_audio() -> dict[str, str]:
    """Slugs whose audio is byte-identical to another slug's, mapped to the one kept.

    The archive publishes the same recording under two pages more than once - "only he can lead
    you" and "only he can lead you bhubaneswar" are the same file and the same transcript, and
    cc-adi-lila 9.49-51 appears twice with two different transcripts of one recording. Graded
    without noticing, such a lecture votes twice.
    """
    first: dict[str, str] = {}
    duplicates: dict[str, str] = {}
    for audio in sorted(REPO.glob("data/lectures/*/audio.mp3")):
        slug = audio.parent.name
        digest = hashlib.sha256(audio.read_bytes()).hexdigest()
        if digest in first:
            duplicates[slug] = first[digest]
        else:
            first[digest] = slug
    return duplicates


def manifest() -> dict:
    """Every aligned lecture, with the stretches of it a model may be graded on."""
    others = records_other_speakers()
    duplicates = duplicate_audio()
    lectures = []
    for path in sorted(ALIGNED.glob("*.json")):
        if path.name == "SUMMARY.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        spans = scoreable_spans(record["words"])
        summary = summarise(spans, record["audio_seconds"])
        lectures.append({
            "slug": record["slug"],
            "audio": f"data/lectures/{record['slug']}/audio.mp3",
            "audio_seconds": record["audio_seconds"],
            "transcript_records_other_speakers": others.get(record["slug"]),
            "duplicate_of": duplicates.get(record["slug"]),
            **summary,
            "spans_detail": [asdict(s) for s in spans],
        })

    # A duplicate stays in the listing so it can be seen, and is kept out of every total so it
    # cannot vote twice.
    counted = [l for l in lectures if not l["duplicate_of"]]
    graded = sum(l["scoreable_seconds"] for l in counted)
    total = sum(l["audio_seconds"] for l in counted)
    solo = [l for l in counted if l["transcript_records_other_speakers"] is False]
    return {
        "what_this_is": "Stretches of archive audio that have trustworthy reference text.",
        "how": ("from the forced alignment: a span runs word to word, breaking where silence "
                f"exceeds {MAX_GAP}s, which is beyond any pause the verified reference shows"),
        "not_included": ("audio after a transcript ends, and long silences within it - both may "
                         "contain speech the transcript never covered"),
        "max_gap_seconds": MAX_GAP,
        "min_words_per_span": MIN_WORDS,
        "lectures": len(counted),
        "audio_hours": round(total / 3600, 2),
        "scoreable_hours": round(graded / 3600, 2),
        "scoreable_share": round(graded / total, 4) if total else 0.0,
        "scoreable_words": sum(l["words"] for l in counted),
        "duplicates_excluded": [l["slug"] for l in lectures if l["duplicate_of"]],
        "grade_on_these_first": {
            "why": ("transcripts recording no other speaker: a question of 3-10s falls under the "
                    "gap threshold and hides inside a span, so the rest carry roughly 3% of audio "
                    "that may be speech with no reference, biasing against every recogniser"),
            "lectures": len(solo),
            "scoreable_hours": round(sum(l["scoreable_seconds"] for l in solo) / 3600, 2),
            "scoreable_words": sum(l["words"] for l in solo),
            "slugs": [l["slug"] for l in solo],
        },
        "detail": lectures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = manifest()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{result['lectures']} lectures, {result['audio_hours']} h of audio")
    print(f"gradeable: {result['scoreable_hours']} h "
          f"({result['scoreable_share']:.0%}), {result['scoreable_words']:,} words")
    if not args.quiet:
        worst = sorted(result["detail"], key=lambda l: l["share_of_audio"])[:5]
        print("\nleast gradeable:")
        for lecture in worst:
            print(f"  {lecture['share_of_audio']:>5.0%}  {lecture['spans']:>3} spans  "
                  f"{lecture['slug'][:48]}")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
