"""Score ElevenLabs and Sarvam where the archive's transcripts can be trusted.

This is what the hosted run was for. Melbourne ranked the recognisers on one lecture; the
question is whether that ranking survives a different decade, venue and tape, and the answer
needs several lectures measured the same way. Six of the archive's lectures now carry both
systems, and `scripts/scoreable.py` has already marked, span by span, where the published
transcript can be believed.

**What the number is.** It is agreement with the archive's published transcript inside those
spans, which is *system error plus reference error* with no way yet to separate them. The
transcripts are faithful but they are not verbatim: they tidy, and six of them stop early. So
these figures rank systems against each other on identical material. They are not a word error
rate against what was actually said, and must not be quoted as one.

Two things had to be decided before anything could be compared, and both are stated in the
output rather than buried here: Sarvam returns segments and not words, and the Indic track has
to be split into Sanskrit and Bengali because no system here is best at both.

    python -m scripts.compare_hosted
    python -m scripts.compare_hosted --rounds 2000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.span_score import beats, bootstrap_interval, heard_within
from scripts.transcript_accuracy import (fold, folded_with_marks, indic_language, normalise,
                                          score)

REPO = Path(__file__).resolve().parents[1]
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
HOSTED = REPO / "data/reference/analysis/hosted"
OUT = REPO / "data/reference/analysis/hosted-comparison.json"

SERVICES = ("elevenlabs", "sarvam")

# Words either side of an Indic word that decide which language it belongs to. Thirteen words
# is about a line and a half of chanted verse - small enough that a verse and the Bengali song
# after it land in different buckets, large enough that `indic_language` has something to read.
CONTEXT = 6

# How much worse a lecture may score inside its spans than over the whole file before its
# timings are judged broken.
#
# The check is baseline-free, which is what makes it usable here: restricting the grade to the
# spans where the transcript can be trusted should only ever *help*, because it removes
# stretches nobody wrote down. A lecture that scores far worse inside its spans is therefore
# not being badly recognised - its words are in the wrong places, and the spans are built from
# those places.
#
# The threshold is measured, not borrowed. Across six lectures and two systems the five sound
# ones ran 1.00 to 1.23; the broken one hit 2.11 on its milder system and 5.64 on the other
# (90.9% inside its spans against 16.1% over the whole file). Nothing sits between.
MISPLACED_RATIO = 1.5


def words_from_segments(entries: list[dict]) -> list[dict]:
    """Spread each segment's words across its own duration, at a uniform rate.

    Sarvam returns segments of ten to sixty seconds. Span scoring places a word by its
    midpoint, so a segment handed over whole would put every one of its words - up to sixty -
    wherever the middle of the segment happened to fall, and a segment crossing a span edge
    would drop a minute of speech on the wrong side.

    Spreading them evenly is an estimate and is labelled as one. It is wrong about where any
    individual word sits by a second or two, which does not matter inside a span that runs for
    forty minutes, and it is right to within a word at the only place it matters: the edges.
    The count of words that fell in a straddling segment is reported alongside, so the size of
    the assumption is visible rather than implied.
    """
    placed = []
    for entry in entries:
        start, end = entry.get("s"), entry.get("e")
        if start is None or end is None:
            continue
        tokens = (entry.get("w") or "").split()
        if not tokens:
            continue
        step = (end - start) / len(tokens)
        for index, token in enumerate(tokens):
            # The last word ends exactly where the segment ends: a lecture is three thousand
            # seconds and accumulated rounding would walk the late words out of their span.
            placed.append({"w": token, "s": start + index * step,
                           "e": end if index == len(tokens) - 1 else start + (index + 1) * step})
    return placed


def words_for(record: dict) -> list[dict]:
    """The system's words in time, whatever granularity it reported them at."""
    if record.get("unit") == "segment":
        return words_from_segments(record["words"])
    return [w for w in record["words"] if w.get("s") is not None]


def straddling_words(entries: list[dict], spans: list[dict]) -> int:
    """How many words sat in a segment crossing a span edge - the size of the assumption."""
    edges = [span["start"] for span in spans] + [span["end"] for span in spans]
    exposed = 0
    for entry in entries:
        start, end = entry.get("s"), entry.get("e")
        if start is None or end is None:
            continue
        if any(start < edge < end for edge in edges):
            exposed += len((entry.get("w") or "").split())
    return exposed


def language_mask(words: list[str], is_indic: list[bool],
                  context: int = CONTEXT) -> list[str | None]:
    """Sanskrit or Bengali for each Indic word, read from the words around it.

    `indic_language` judges a line, and the Melbourne work fed it cues a few seconds long.
    These spans run to forty minutes and hold both languages, so a span-level label would call
    an entire lecture Sanskrit and the split would be worthless. A local window is the smallest
    honest unit available short of hand-labelling, and the examples printed at the end of a run
    are there so the classification can be checked by reading it rather than trusted.
    """
    out: list[str | None] = []
    for index, indic in enumerate(is_indic):
        if not indic:
            out.append(None)
            continue
        window = words[max(0, index - context):index + context + 1]
        out.append(indic_language(" ".join(window)))
    return out


def score_span_by_language(reference_words: list[str], heard_words: list[str]) -> dict:
    """One span, with the Indic track split in two.

    The scorer already buckets every reference word by a boolean it is handed, so the split
    costs nothing but three calls over the same alignment: once with every Indic word marked
    to get the English track and the Indic total, then once per language with only that
    language's words marked. The alignment is identical in all three, so the parts add up to
    the whole - which a test asserts, because a word charged to neither language would quietly
    improve both rates.
    """
    reference = fold(normalise(" ".join(reference_words)))
    hypothesis = fold(normalise(" ".join(heard_words)))
    empty = {"words": 0, "exact": 0, "near": 0, "errors": 0}
    if not reference:
        return {"reference_words": 0, "heard_words": len(hypothesis), "examples": {},
                "english": dict(empty), "indic": dict(empty),
                "sanskrit": dict(empty), "bengali": dict(empty)}

    reference, marks = folded_with_marks(normalise(" ".join(reference_words)))
    languages = language_mask(reference, marks)
    whole = score(reference, marks, hypothesis)
    result = {"reference_words": whole["reference_words"], "heard_words": whole["hypothesis_words"],
              "english": whole["english"], "indic": whole["indic"],
              "examples": {"wrong": whole["examples_wrong"][:4]}}
    for name in ("sanskrit", "bengali"):
        only = [mark and languages[index] == name for index, mark in enumerate(marks)]
        result[name] = score(reference, only, hypothesis)["indic"]
        result.setdefault("words_by_language", {})[name] = [
            reference[index] for index, flag in enumerate(only) if flag][:12]
    return result


def add(into: dict, track: str, counts: dict) -> None:
    bucket = into.setdefault(track, {"words": 0, "exact": 0, "near": 0, "errors": 0})
    for key in ("words", "exact", "near", "errors"):
        bucket[key] += counts.get(key, 0)


def score_lecture_by_language(spans: list[dict], words: list[dict]) -> dict:
    totals: dict = {"reference_words": 0}
    examples: dict[str, list] = {"sanskrit": [], "bengali": []}
    for span in spans:
        heard = heard_within(span["start"], span["end"], words)
        one = score_span_by_language(span["words"], heard)
        totals["reference_words"] += one["reference_words"]
        for track in ("english", "indic", "sanskrit", "bengali"):
            add(totals, track, one[track])
        for name in ("sanskrit", "bengali"):
            examples[name].extend(one.get("words_by_language", {}).get(name, []))
    totals["examples"] = {name: words[:15] for name, words in examples.items()}
    return totals


def rate(counts: dict) -> float | None:
    return counts["errors"] / counts["words"] if counts["words"] else None


def overall_error(totals: dict) -> float:
    words = totals["english"]["words"] + totals["indic"]["words"]
    errors = totals["english"]["errors"] + totals["indic"]["errors"]
    return errors / words if words else 0.0


def whole_file_error(lecture: dict, words: list[dict]) -> float:
    """The same reference text scored against the whole transcript, ignoring where words sit.

    This is the control for the span scoring, not a result in itself. It uses exactly the
    reference the spans use, so the only difference between the two numbers is whether the
    system's words had to land in the right place.
    """
    reference = [word for span in lecture["spans_detail"] for word in span["words"]]
    heard = [w["w"] for w in sorted(words, key=lambda w: w["s"])]
    one = score_span_by_language(reference, heard)
    words_counted = one["english"]["words"] + one["indic"]["words"]
    errors = one["english"]["errors"] + one["indic"]["errors"]
    return errors / words_counted if words_counted else 0.0


def paired(manifest: dict) -> list[dict]:
    """The lectures both services have read. A lecture only one has read compares with nothing."""
    have = {service: {p.stem for p in (HOSTED / service).glob("*.json")} for service in SERVICES}
    both = have[SERVICES[0]] & have[SERVICES[1]]
    return [l for l in manifest["detail"] if l["slug"] in both]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1000,
                        help="bootstrap resamples of the lecture list")
    args = parser.parse_args()

    manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    lectures = sorted(paired(manifest), key=lambda l: l["audio_seconds"])
    if not lectures:
        raise SystemExit("no lecture has been read by both services yet")

    print(f"{len(lectures)} lectures read by both services, "
          f"{sum(l['audio_seconds'] for l in lectures)/3600:.1f} hours\n")

    # Measure everything first, then decide what is admissible. Judging a lecture on the way
    # past would mean the exclusion depended on the order they were read in.
    measured: dict[str, dict] = {}
    for lecture in lectures:
        measured[lecture["slug"]] = {}
        for service in SERVICES:
            record = json.loads(
                (HOSTED / service / f"{lecture['slug']}.json").read_text(encoding="utf-8"))
            words = words_for(record)
            totals = score_lecture_by_language(lecture["spans_detail"], words)
            whole = whole_file_error(lecture, words)
            inside = overall_error(totals)
            measured[lecture["slug"]][service] = {
                "unit": record.get("unit"), "totals": totals,
                "span_error": inside, "whole_file_error": whole,
                "ratio": inside / whole if whole else 1.0,
                "straddling_words": (straddling_words(record["words"], lecture["spans_detail"])
                                     if record.get("unit") == "segment" else 0)}

    misplaced = [l for l in lectures
                 if any(measured[l["slug"]][s]["ratio"] > MISPLACED_RATIO for s in SERVICES)]
    usable = [l for l in lectures if l not in misplaced]

    if misplaced:
        print("EXCLUDED - these score far worse inside their spans than over the whole file,")
        print("which means the words are in the wrong places, not that they were misheard:\n")
        for lecture in misplaced:
            worst = max(measured[lecture["slug"]][s]["ratio"] for s in SERVICES)
            print(f"   {lecture['slug'][:52]}")
            for service in SERVICES:
                one = measured[lecture["slug"]][service]
                print(f"     {service:11} {one['span_error']:6.1%} in spans against "
                      f"{one['whole_file_error']:6.1%} whole file  (x{one['ratio']:.2f})")
            print(f"     alignment_confidence {lecture['alignment_confidence']:.4f}, "
                  f"worst ratio x{worst:.2f} - above the measured limit of "
                  f"x{MISPLACED_RATIO}\n")

    if not usable:
        raise SystemExit("every paired lecture failed the placement check")

    per_lecture: dict[str, list[dict]] = {service: [] for service in SERVICES}
    report: dict = {"lectures": [], "systems": {},
                    "excluded": [{"slug": l["slug"],
                                  "alignment_confidence": l["alignment_confidence"],
                                  "ratios": {s: round(measured[l["slug"]][s]["ratio"], 3)
                                             for s in SERVICES}} for l in misplaced]}

    for lecture in usable:
        row = {"slug": lecture["slug"], "audio_seconds": lecture["audio_seconds"],
               "spans": lecture["spans"], "systems": {}}
        print(f"{lecture['slug'][:56]}  ({lecture['audio_seconds']/60:.0f} min, "
              f"{lecture['spans']} span(s))")
        for service in SERVICES:
            one = measured[lecture["slug"]][service]
            totals = one["totals"]
            per_lecture[service].append(totals)
            row["systems"][service] = {
                "unit": one["unit"], "straddling_words": one["straddling_words"],
                "span_error": round(one["span_error"], 4),
                "whole_file_error": round(one["whole_file_error"], 4),
                **{track: totals[track] for track in ("english", "indic", "sanskrit", "bengali")},
                "reference_words": totals["reference_words"]}
            parts = []
            for track in ("english", "indic"):
                value = rate(totals[track])
                parts.append(f"{track} {value:6.1%} ({totals[track]['words']:,})"
                             if value is not None else f"{track}    n/a")
            note = (f"  [{one['straddling_words']} words in straddling segments]"
                    if one["straddling_words"] else "")
            print(f"   {service:11} " + "  ".join(parts) + note)
        report["lectures"].append(row)
        print()

    print("=" * 78)
    print(f"TOTALS over the {len(usable)} admissible lectures, "
          f"95% intervals from resampling LECTURES\n")
    for service in SERVICES:
        print(f"  {service}")
        summary = {}
        for track in ("english", "indic", "sanskrit", "bengali"):
            units = [{"words": one[track]["words"], "errors": one[track]["errors"]}
                     for one in per_lecture[service]]
            words = sum(u["words"] for u in units)
            if not words:
                continue
            errors = sum(u["errors"] for u in units)
            low, high = bootstrap_interval(units, rounds=args.rounds)
            summary[track] = {"words": words, "errors": errors, "rate": errors / words,
                              "interval": [round(low, 4), round(high, 4)]}
            print(f"    {track:9} {errors/words:6.1%}   95% CI [{low:.1%}, {high:.1%}]"
                  f"   {words:,} words")
        report["systems"][service] = summary

    print("\n" + "=" * 78)
    print("DOES THE GAP SURVIVE RESAMPLING?  (positive = ElevenLabs has the higher error rate)\n")
    report["comparison"] = {}
    for track in ("english", "indic", "sanskrit", "bengali"):
        first = [{"words": one[track]["words"], "errors": one[track]["errors"]}
                 for one in per_lecture[SERVICES[0]]]
        second = [{"words": one[track]["words"], "errors": one[track]["errors"]}
                  for one in per_lecture[SERVICES[1]]]
        if not sum(u["words"] for u in first):
            continue
        verdict = beats(first, second, rounds=args.rounds)
        report["comparison"][track] = verdict
        better = "sarvam" if verdict["difference"] > 0 else "elevenlabs"
        words = sum(u["words"] for u in first)
        print(f"    {track:9} {verdict['difference']:+7.2%}   "
              f"95% CI [{verdict['interval'][0]:+.2%}, {verdict['interval'][1]:+.2%}]   "
              + (f"SEPARATED - {better} is better" if verdict["separated"]
                 else "straddles zero - this data cannot say which is better")
              + (f"  [only {words} words]" if words < 300 else ""))

    print("\n" + "=" * 78)
    print("THE SANSKRIT/BENGALI SPLIT IS PROVISIONAL. Read these and judge it:\n")
    for name in ("sanskrit", "bengali"):
        seen = []
        for one in per_lecture[SERVICES[0]]:
            seen.extend(one["examples"][name])
        print(f"    {name:9} {' '.join(seen[:18]) or '(none)'}")
    print("\n  `indic_language` returns sanskrit when neither orthography is evident, which is "
          "right\n  for a verse and wrong for a Bengali song built of words its pattern does "
          "not list -\n  `pache`, `kangal`, `babu`, `paisa` all land in the Sanskrit bucket. "
          "The split is\n  therefore biased towards Sanskrit, and the Bengali figure rests on "
          "too few words to\n  carry a claim. The combined Indic figure is the sound one.")

    print("\n⚠ These are agreement rates against the archive's published transcripts, which "
          "tidy\n  what was said. Every figure is system error PLUS reference error, and the "
          "reference's\n  own rate is still unmeasured. They rank systems; they are not word "
          "error rates.")

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
