"""How much of the archive's measured error belongs to the reference, not the recogniser.

Every figure this project has published on the archive is **system error plus reference error**
with no way to separate them, and that has been the top-ranked gap for weeks. It looked like it
needed the steward transcribing a hundred spans by hand.

It does not, because there are now **two independent recognisers on the same five lectures**.
Where both put the same thing and the published transcript says otherwise, the transcript is the
likely error: two systems from different vendors, trained differently, do not invent the same
wrong word in the same place.

The whole method turns on not treating the three kinds of disagreement as equal evidence:

* Both systems **add** the same words → the transcript omitted speech. The archive's
  transcripts tidy, so this is the error they are most likely to make.
* Both systems **replace** a word identically → the transcript has the wrong word.
* Both systems **miss** words the transcript has → **this says nothing about the transcript.**
  Quiet, fast or accented speech is exactly what two recognisers lose together, and counting it
  would convert the recognisers' shared blind spot into a reference error.

What it yields is a **lower bound**: the two must agree exactly, so every reference error they
disagree about is invisible here. And it can overcount where both systems share a mishearing,
which is why the agreement rate at disputed sites is reported as a control and why examples are
printed to be read rather than trusted.

    python -m scripts.adjudicate_reference
"""

from __future__ import annotations

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path

from scripts.compare_hosted import MISPLACED_RATIO, paired, whole_file_error, words_for
from scripts.span_score import bootstrap_interval, heard_within
from scripts.transcript_accuracy import fold, folded_with_marks, normalise, recognisable

REPO = Path(__file__).resolve().parents[1]
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
HOSTED = REPO / "data/reference/analysis/hosted"
OUT = REPO / "data/reference/analysis/reference-error.json"

SERVICES = ("elevenlabs", "sarvam")


def disputes(reference: list[str], hypothesis: list[str]) -> dict[tuple[int, int], tuple]:
    """Every place a system put something other than what the reference says.

    Keyed by the reference positions it covers, so two systems can be asked whether they
    disagreed in the same place about the same thing. An addition occupies no reference
    position and so keys a zero-width site, which is exactly right: the transcript has nothing
    there at all.
    """
    found: dict[tuple[int, int], tuple] = {}
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, reference, hypothesis,
                                               autojunk=False).get_opcodes():
        if tag != "equal":
            found[(i1, i2)] = tuple(hypothesis[j1:j2])
    return found


def near_match(reference_tokens: tuple, heard_tokens: tuple) -> bool:
    """Is this only a difference of spelling the same sound?

    Both systems writing `krishna` where the transcript wrote `kṛṣṇa` is a romanisation
    variant the scorer already forgives. Counting it here would invent reference errors out of
    the one disagreement everybody agrees is not one.

    `recognisable` is the scorer's own rule, reused so the two cannot drift apart. Note it is
    applied to English as well, where the scorer applies it only to the Indic track: it
    forgives `soles` heard as `souls`. That is deliberate in this direction - a homophone is a
    poor basis for calling a transcript wrong, and forgiving it pushes the bound down, which is
    the safe way for a bound to be wrong.
    """
    if len(reference_tokens) != len(heard_tokens) or not reference_tokens:
        return False
    return all(recognisable(a, b) for a, b in zip(reference_tokens, heard_tokens))


def agreement_at_disputes(reference: list[str], first: list[str],
                          second: list[str]) -> float | None:
    """Of the sites either system disputed, at how many did both dispute the same thing?

    The control on the whole method. If two systems agree at nearly every disputed site then
    agreement is cheap and proves little; if they rarely agree, the sites where they do are
    worth taking seriously.
    """
    a, b = disputes(reference, first), disputes(reference, second)
    either = set(a) | set(b)
    if not either:
        return None
    # The denominator is every site either system disputed, not only the sites both did. Two
    # systems that dispute entirely different places have agreed about nothing, and scoring
    # that as "no data" would quietly discard the most informative case there is.
    return sum(1 for site in set(a) & set(b) if a[site] == b[site]) / len(either)


def adjudicate(reference: list[str], first: list[str], second: list[str]) -> dict:
    """Charge each disagreement to the reference, to the recognisers, or to nobody."""
    a, b = disputes(reference, first), disputes(reference, second)
    result = {"reference_words": len(reference), "wrong_in_reference": 0,
              "omitted_by_reference": 0, "missed_by_both": 0, "disputed_sites": len(set(a) | set(b)),
              "agreed_sites": 0, "examples": []}

    for site, replacement in a.items():
        if b.get(site) != replacement:
            continue
        start, end = site
        words_here = tuple(reference[start:end])
        if near_match(words_here, replacement):
            continue
        result["agreed_sites"] += 1

        if not words_here:                      # both systems heard speech the transcript lacks
            result["omitted_by_reference"] += len(replacement)
            kind = "reference omitted"
        elif not replacement:                   # neither system heard what the transcript has
            result["missed_by_both"] += len(words_here)
            kind = "both systems missed"
        else:
            result["wrong_in_reference"] += len(words_here)
            kind = "reference wrong"

        if len(result["examples"]) < 40 and kind != "both systems missed":
            result["examples"].append({
                "kind": kind, "at": start,
                "reference": " ".join(words_here) or "(nothing)",
                "both_systems_heard": " ".join(replacement) or "(nothing)",
                "context": " ".join(reference[max(0, start - 6):end + 6])})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--examples", type=int, default=16)
    args = parser.parse_args()

    manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    lectures = sorted(paired(manifest), key=lambda l: l["audio_seconds"])

    rows, units_wrong, units_omitted = [], [], []
    print("Where TWO independent recognisers agree against the archive's transcript.\n")
    print(f"{'lecture':<44} {'ref words':>9} {'wrong':>7} {'omitted':>8} {'missed':>7} {'agree%':>7}")

    for lecture in lectures:
        heard = {}
        skip = False
        for service in SERVICES:
            record = json.loads(
                (HOSTED / service / f"{lecture['slug']}.json").read_text(encoding="utf-8"))
            heard[service] = words_for(record)
        # The same placement guard the comparison uses: a lecture whose words are in the wrong
        # places would report its whole transcript as reference error.
        for service in SERVICES:
            whole = whole_file_error(lecture, heard[service])
            inside = 0.0
            reference_all = [w for s in lecture["spans_detail"] for w in s["words"]]
            if whole:
                from scripts.compare_hosted import overall_error, score_lecture_by_language
                inside = overall_error(score_lecture_by_language(lecture["spans_detail"],
                                                                 heard[service]))
                if inside / whole > MISPLACED_RATIO:
                    skip = True
        if skip:
            print(f"{lecture['slug'][:44]:<44}   excluded - words are in the wrong places")
            continue

        totals = {"reference_words": 0, "wrong_in_reference": 0, "omitted_by_reference": 0,
                  "missed_by_both": 0, "disputed_sites": 0, "agreed_sites": 0, "examples": []}
        agreements = []
        for span in lecture["spans_detail"]:
            reference, _ = folded_with_marks(normalise(" ".join(span["words"])))
            sides = [fold(normalise(" ".join(heard_within(span["start"], span["end"],
                                                          heard[service]))))
                     for service in SERVICES]
            one = adjudicate(reference, sides[0], sides[1])
            for key in ("reference_words", "wrong_in_reference", "omitted_by_reference",
                        "missed_by_both", "disputed_sites", "agreed_sites"):
                totals[key] += one[key]
            totals["examples"].extend(one["examples"])
            rate = agreement_at_disputes(reference, sides[0], sides[1])
            if rate is not None:
                agreements.append(rate)

        share = (sum(agreements) / len(agreements)) if agreements else 0.0
        print(f"{lecture['slug'][:44]:<44} {totals['reference_words']:>9,} "
              f"{totals['wrong_in_reference']:>7,} {totals['omitted_by_reference']:>8,} "
              f"{totals['missed_by_both']:>7,} {share:>6.1%}")
        rows.append({"slug": lecture["slug"], **{k: v for k, v in totals.items()
                                                 if k != "examples"},
                     "agreement_at_disputes": round(share, 4)}
                    )
        units_wrong.append({"words": totals["reference_words"],
                            "errors": totals["wrong_in_reference"]})
        units_omitted.append({"words": totals["reference_words"],
                              "errors": totals["omitted_by_reference"]})
        totals["slug"] = lecture["slug"]
        rows[-1]["examples"] = totals["examples"]

    if not rows:
        raise SystemExit("no admissible lecture")

    words = sum(r["reference_words"] for r in rows)
    wrong = sum(r["wrong_in_reference"] for r in rows)
    omitted = sum(r["omitted_by_reference"] for r in rows)
    missed = sum(r["missed_by_both"] for r in rows)

    print("\n" + "=" * 78)
    print(f"THE REFERENCE'S OWN ERROR, over {len(rows)} lectures and {words:,} reference words\n")
    low, high = bootstrap_interval(units_wrong, rounds=args.rounds)
    print(f"  wrong word in the transcript   {wrong/words:6.2%}  95% CI "
          f"[{low:.2%}, {high:.2%}]   {wrong:,} words")
    low_o, high_o = bootstrap_interval(units_omitted, rounds=args.rounds)
    print(f"  speech the transcript omitted  {omitted/words:6.2%}  95% CI "
          f"[{low_o:.2%}, {high_o:.2%}]   {omitted:,} words")
    print(f"  REFERENCE ERROR, LOWER BOUND   {(wrong+omitted)/words:6.2%}"
          f"   {wrong+omitted:,} words\n")
    print(f"  (for scale: both systems missed {missed:,} words the transcript has - charged to")
    print("   neither, because two recognisers lose quiet speech together)")

    agree = sum(r["agreement_at_disputes"] * 1 for r in rows) / len(rows)
    print(f"\n  CONTROL: at sites where both disputed the transcript, they agreed exactly "
          f"{agree:.1%}\n  of the time. Agreement is therefore {'cheap' if agree > 0.5 else 'rare'}"
          f", so a site where they do agree is {'weak' if agree > 0.5 else 'strong'} evidence.")

    print("\n" + "=" * 78)
    print("READ THESE. Each is a place both systems heard the same thing and the "
          "transcript differs:\n")
    shown = 0
    for row in rows:
        for example in row["examples"]:
            if shown >= args.examples:
                break
            print(f"  [{example['kind']}]  transcript: {example['reference'][:46]!r}")
            print(f"      both heard: {example['both_systems_heard'][:46]!r}")
            print(f"      context   : ...{example['context'][:90]}...")
            shown += 1
        if shown >= args.examples:
            break

    print("\n⚠ This is a LOWER BOUND. The two systems must agree exactly, so every reference")
    print("  error they disagree about is invisible. It can also overcount where both share a")
    print("  mishearing - which is what the examples above are for.")

    OUT.write_text(json.dumps({"lectures": rows, "totals": {
        "reference_words": words, "wrong_in_reference": wrong,
        "omitted_by_reference": omitted, "missed_by_both": missed,
        "lower_bound_rate": round((wrong + omitted) / words, 5)}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
