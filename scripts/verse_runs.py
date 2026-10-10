"""Find the recited verse in the archive, where the printed text can be the reference.

The archive cannot be used to choose a Sanskrit system: only **6.0%** of its Indic tokens sit
in runs of five or more words, against Melbourne's 24.6%, because its transcripts carry Indic
words almost entirely as names inside English sentences. The obvious remedy - have somebody
listen to chanted verse and write it down - is expensive.

It is also unnecessary, for verse specifically. **A quotation has fixed printed text.** Where a
run of connected Indic words in the transcript can be matched to a printed verse, ground truth
is exact and free, and the systems can be scored on it against text neither of them saw.

This measures the inventory and proves the method on whatever the corpus on disk can resolve:

* **What connected Indic is actually there** - every run of three or more words, with the time
  it occupies, taken from the forced alignment.
* **Which of them are quotation** - matched against KKSongs with `verse_match`, whose margin
  gate refuses rather than guesses, because a verse of scripture attributed to this teacher
  wrongly is worse than an admitted gap.
* **What is left** - printed in full, to be read. A three-word run may be `Śrīla
  Bhaktisiddhānta Sarasvatī`, which is a name and not a verse at all, and no heuristic on disk
  separates those honestly: the archive's own glossary is built from the archive, so a verse
  word appears in it as readily as a name.

**The corpus on disk is songs only.** KKSongs is Bengali padāvalī; the Bhāgavatam and
Caitanya-caritāmṛta citations these lectures are built on are not in it. GRETIL's TEI
Bhāgavatam - 14,067 verses, explicitly licensed, every citation in the Melbourne reference
present at its exact address - is researched but not downloaded. So an unmatched run here means
"not in this corpus" and not "not a verse", and the count of them is the size of the prize for
fetching GRETIL.

    python -m scripts.verse_runs
    python -m scripts.verse_runs --min-run 4 --margin 0.25
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.compare_hosted import (MISPLACED_RATIO, overall_error, paired,
                                    score_lecture_by_language, score_span_by_language,
                                    whole_file_error, words_for)
from scripts.transcript_accuracy import has_diacritics
from scripts.verse_match import VerseIndex

REPO = Path(__file__).resolve().parents[1]
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
ALIGNED = REPO / "data/reference/analysis/archive-alignment"
HOSTED = REPO / "data/reference/analysis/hosted"
SONGS = REPO / "data/reference/kksongs/songs.jsonl"
OUT = REPO / "data/reference/analysis/verse-runs.json"

SERVICES = ("elevenlabs", "sarvam")

# KKSongs carries songs in several European languages as well, which are translations and not
# anything this archive recites.
NOT_INDIC = {"spanish", "english", "german", "french", "portuguese", "hungarian", "russian",
             "lithuanian", "italian", "polish", "czech", "dutch", "swedish"}

# The KKSongs mirror has an undocumented encoding defect, found by reading a match whose
# printed side came back as `nanenanam ninun nenam`. Two distinct faults:
#
#   * 4,646 lines contain U+FFFD, the replacement character, where a letter was lost:
#     `jnana` is stored as `j<FFFD>ana`. These CANNOT be ground truth - `fold` turns the
#     replacement into a space and splits one word into `j` and `ana` - and worse, the
#     wreckage matches almost anything, so it acts as an attractor. Dropped.
#   * 5,482 lines carry a combining acute on `m` where the anusvara belongs: `samsuddhir`
#     stored as `sam<U+0301>suddhir`. This one is cosmetic here, because both `skeleton` and
#     `fold` strip combining marks before anything is compared, so it changes no number. It is
#     left alone rather than repaired, since a repair asserted without checking the source is
#     exactly the kind of guess this corpus does not need.
LOST_CHARACTER = "�"


def song_windows(songs: list[dict], sizes: tuple[int, ...] = (1, 2, 3),
                 minimum_words: int = 3) -> tuple[list[str], list[str]]:
    """Overlapping windows of consecutive lyric lines, each labelled with its song.

    Overlapping windows are what let a run of unknown length find its verse, and the song
    label is what lets the margin mean anything: `verse_match` takes its margin over the best
    candidate from a *different* passage, so without labels a winner's own neighbouring windows
    cancel the margin out. That one change took Bengali coverage from 13% to 67%.

    A window never crosses two songs, because that would invent a verse nobody wrote and then
    defend the margin against a line that does not exist.

    Three lines, not two, and the data said so: the run `Kṛṣṇa de tomāra, Kṛṣṇa dite pāra,
    tomāra śakti āche. Āmi ye kaṅgāla Kṛṣṇa` is thirteen words, and a KKSongs line runs four
    to six, so no two-line window could ever hold it. It went unmatched while a three-word
    fragment of the same song matched easily.
    """
    verses: list[str] = []
    passages: list[str] = []
    for song in songs:
        if (song.get("language") or "").strip().lower() in NOT_INDIC:
            continue
        # Structural markers - "(1)", "(refrain)" - are the printed edition's scaffolding and
        # are not recited.
        # A damaged line BREAKS the run of lines rather than being skipped over. Skipping it
        # would splice the line before to the line after and index a verse nobody printed -
        # the same fault as letting a window cross two songs.
        segments: list[list[str]] = [[]]
        for raw in song.get("lyrics") or []:
            line = raw.strip()
            if not line or line.startswith("("):
                continue
            if LOST_CHARACTER in line:
                segments.append([])
                continue
            segments[-1].append(line)

        for lines in segments:
            for size in sizes:
                for start in range(len(lines) - size + 1):
                    window = " ".join(lines[start:start + size])
                    if len(window.split()) >= minimum_words:
                        verses.append(window)
                        passages.append(song.get("name") or "(unnamed)")
    return verses, passages


# How far a matched printed window may differ in length from the run before the systems stop
# being scored on it. `ahaṁ bīja-pradaḥ pitā` matched `tāsāḿ brahma mahad yonir ahaḿ
# bīja-pradaḥ pitā`, which is the right verse - BG 14.4 - but only three of those seven words
# occupy the run's stretch of audio, so scoring both systems on all seven charged them four
# words nobody said there. Some slack is needed because the transcript's punctuation and the
# printed edition's do not agree.
LENGTH_BAND = (0.7, 1.4)


def comparable_length(run_words: int, printed_words: int) -> bool:
    """Is the printed window close enough in length to be what was recited here?"""
    if not run_words:
        return False
    ratio = printed_words / run_words
    return LENGTH_BAND[0] <= ratio <= LENGTH_BAND[1]


# A bridged gap must be short in TIME as well as in words. One unmarked word inside a verse
# takes well under a second - the archive speaks at 88-91 words a minute, so about 0.7 s - and
# a breath either side fits in 1.5. Without this bound a single word such as "then" would join
# two recitations six seconds apart into one run whose window is mostly silence, and the
# matcher would be handed a verse that was never recited in most of it.
MAX_BRIDGE_SECONDS = 1.5


def indic_runs(words: list[dict], minimum: int = 3, gap: int = 1,
               spans: list[dict] | None = None,
               max_bridge: float = MAX_BRIDGE_SECONDS) -> list[dict]:
    """Every stretch of words the transcript wrote with diacritics, tolerating short gaps.

    The run's times come from the forced alignment, which is what makes this usable: a matched
    verse arrives with the window of audio it occupies, so each system can be scored on exactly
    that stretch.

    `gap` exists because **one unmarked word was cutting verses in half.** SB 1.2.10 is
    `jīvasya tattva-jijñāsā nārtho yaś ceha karmabhiḥ`, and `ceha` carries no diacritics, so
    breaking on it reported a four-word run and dropped `karmabhiḥ` for standing alone. A
    fragment is both harder to match and easier to match wrongly, so a single unmarked word
    inside a run is kept. A run still never begins or ends on one.
    """
    def inside(word: dict) -> bool:
        if spans is None:
            return True
        middle = (word["start"] + word["end"]) / 2
        return any(s["start"] <= middle < s["end"] for s in spans)

    def close(run: list[dict]) -> None:
        while run and not has_diacritics(run[-1]["word"]):
            run.pop()                            # never end on an unmarked word
        if len(run) >= minimum:
            runs.append(list(run))

    runs: list[list[dict]] = []
    current: list[dict] = []
    pending: list[dict] = []                     # unmarked words that may yet be bridged
    for word in words:
        if has_diacritics(word["word"]) and inside(word):
            if current and word["start"] - current[-1]["end"] > max_bridge:
                close(current)                   # too long a silence to be the same recitation
                current, pending = [], []
            current.extend(pending)              # the gap was bridged, so keep what was in it
            pending = []
            current.append(word)
            continue
        if current and len(pending) < gap:
            pending.append(word)
            continue
        close(current)
        current, pending = [], []
    close(current)                               # a run the lecture ends on

    return [{"text": " ".join(w["word"] for w in run), "words": len(run),
             "start": run[0]["start"], "end": run[-1]["end"]} for run in runs]


def heard_between(words: list[dict], start: float, end: float) -> list[str]:
    return [w["w"] for w in sorted(words, key=lambda w: w["s"])
            if start <= (w["s"] + w["e"]) / 2 < end]


def admissible(manifest: dict) -> list[dict]:
    """Paired lectures whose words are where the alignment says they are."""
    keep = []
    for lecture in paired(manifest):
        if not (ALIGNED / f"{lecture['slug']}.json").exists():
            continue
        broken = False
        for service in SERVICES:
            record = json.loads(
                (HOSTED / service / f"{lecture['slug']}.json").read_text(encoding="utf-8"))
            words = words_for(record)
            whole = whole_file_error(lecture, words)
            if whole and overall_error(score_lecture_by_language(
                    lecture["spans_detail"], words)) / whole > MISPLACED_RATIO:
                broken = True
        if not broken:
            keep.append(lecture)
    return keep


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Four, not three, and measured rather than chosen. Of thirteen matches at a floor of
    # three, five were wrong by reading - and every one of those was a three-word run.
    # `Babu eka paisa` matched `tumhare darasa ke bhuke pyase` three separate times. Three
    # words of folded, vowel-dropped skeleton is simply not enough text to identify a verse
    # out of fifty thousand windows, and for scripture a confident error is worse than a gap.
    parser.add_argument("--min-run", type=int, default=4)
    parser.add_argument("--margin", type=float, default=0.25)
    parser.add_argument("--min-score", type=float, default=0.30)
    args = parser.parse_args()

    songs = [json.loads(line) for line in SONGS.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    verses, passages = song_windows(songs)
    print(f"corpus: {len(verses):,} windows from "
          f"{len(set(passages)):,} Indic songs (KKSongs)\n")
    index = VerseIndex(verses, passages=passages)

    manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    lectures = admissible(manifest)

    report = {"corpus_windows": len(verses), "lectures": [], "matched": [], "unmatched": []}
    all_runs = 0

    for lecture in lectures:
        alignment = json.loads(
            (ALIGNED / f"{lecture['slug']}.json").read_text(encoding="utf-8"))
        runs = indic_runs(alignment["words"], minimum=args.min_run,
                          spans=lecture["spans_detail"])
        all_runs += len(runs)
        heard = {service: words_for(json.loads(
            (HOSTED / service / f"{lecture['slug']}.json").read_text(encoding="utf-8")))
            for service in SERVICES}

        matched = 0
        for run in runs:
            found = index.find(run["text"], args.min_score, args.margin)
            entry = {"slug": lecture["slug"], **run}
            if found is None:
                report["unmatched"].append(entry)
                continue
            matched += 1
            printed = len(found.verse.split())
            entry.update({"verse": found.verse, "song": found.passage,
                          "score": round(found.score, 3), "margin": round(found.margin, 3),
                          "printed_words": printed,
                          "scoreable": comparable_length(run["words"], printed)})
            # Scored against the PRINTED text, which neither recogniser has seen, over exactly
            # the stretch of audio the alignment says the run occupies - but only when the
            # window is the length of what was recited there.
            if entry["scoreable"]:
                for service in SERVICES:
                    result = score_span_by_language(
                        found.verse.split(),
                        heard_between(heard[service], run["start"], run["end"]))
                    counted = result["english"]["words"] + result["indic"]["words"]
                    errors = result["english"]["errors"] + result["indic"]["errors"]
                    entry[service] = {"words": counted, "errors": errors,
                                      "rate": round(errors / counted, 4) if counted else None}
            report["matched"].append(entry)

        report["lectures"].append({"slug": lecture["slug"], "runs": len(runs),
                                   "matched": matched})
        print(f"{lecture['slug'][:52]:<52} {len(runs):>3} runs, {matched:>2} matched")

    print(f"\n{'=' * 78}")
    print(f"INVENTORY: {all_runs} runs of {args.min_run}+ connected Indic words across "
          f"{len(lectures)} lectures,\n           {len(report['matched'])} matched to a printed "
          f"verse at margin {args.margin}\n")

    if report["matched"]:
        print("MATCHED - scored against the printed text, which neither system has seen:\n")
        for entry in report["matched"]:
            print(f"  transcript: {entry['text'][:66]}")
            print(f"  printed   : {entry['verse'][:66]}")
            print(f"  from      : {entry['song'][:50]}  "
                  f"(score {entry['score']}, margin {entry['margin']})")
            if not entry["scoreable"]:
                print(f"    NOT SCORED - {entry['printed_words']} printed words against a "
                      f"{entry['words']}-word run, so most of that window was not recited here")
                print()
                continue
            for service in SERVICES:
                one = entry[service]
                shown = f"{one['rate']:.1%}" if one["rate"] is not None else "nothing heard"
                print(f"    {service:11} {shown} of {one['words']} printed words")
            print()
        scored = [e for e in report["matched"] if e["scoreable"]]
        print(f"  {len(scored)} of {len(report['matched'])} matches are length-comparable "
              f"and therefore scoreable\n")
        for service in SERVICES:
            words = sum(e[service]["words"] for e in scored)
            errors = sum(e[service]["errors"] for e in scored)
            if words:
                print(f"  {service:11} {errors/words:6.1%} over {words} printed verse words")

    print(f"\n{'=' * 78}")
    print("UNMATCHED - read these. A run of three may be a name and not a verse at all,\n"
          "and the Bhagavatam citations these lectures are built on are not in a song book:\n")
    for entry in report["unmatched"][:30]:
        print(f"  {entry['words']}w  {entry['start']:7.1f}s  {entry['text'][:68]}")
    if len(report["unmatched"]) > 30:
        print(f"  ... and {len(report['unmatched']) - 30} more")

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
