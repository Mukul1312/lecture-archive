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
import re
from pathlib import Path

from scripts.compare_hosted import (MISPLACED_RATIO, overall_error, paired,
                                    score_lecture_by_language, score_span_by_language,
                                    whole_file_error, words_for)
from scripts.gretil_verses import load as load_gretil
from scripts.transcript_accuracy import has_diacritics
from scripts.verse_cache import VerseCache
from scripts.verse_match import VerseIndex, skeleton

REPO = Path(__file__).resolve().parents[1]
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
ALIGNED = REPO / "data/reference/analysis/archive-alignment"
HOSTED = REPO / "data/reference/analysis/hosted"
SONGS = REPO / "data/reference/kksongs/songs.jsonl"
WIKISOURCE = REPO / "data/reference/wikisource/gita-verses.jsonl"
VEDABASE = REPO / "data/reference/vaniwiki/bbt-verses.jsonl"
BHAGAVATA = REPO / "data/reference/caitanya-bhagavata/cb-verses.jsonl"
OUT = REPO / "data/reference/analysis/verse-runs.json"
WORKLIST = REPO / "data/reference/analysis/verse-worklist.json"
CACHE = REPO / "data/reference/verse-cache.json"

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

# A combining mark with no base letter in front of it means the letter it belonged to is gone.
# 1,962 KKSongs lines carry one, and the worst of them collapse to near-nonsense that matches
# almost anything: `nanenanam ninun nenam` survived a 90%-precision read as the single wrong
# identification, and once a length-comparable form of it existed it began contributing to the
# verse score. Same category as U+FFFD - information lost, so it cannot be ground truth. This
# is NOT the harmless case of an acute sitting ON an `m`, which `fold` and `skeleton` strip
# before anything is compared.
ORPHANED_MARK = re.compile(r"(?:^|\s)[̀-ͯ॑-॔]")


def damaged(line: str) -> bool:
    """Has this printed line lost characters, making it unusable as ground truth?"""
    return LOST_CHARACTER in line or bool(ORPHANED_MARK.search(line))


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
            if damaged(line):
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


def identify(index, text: str, min_score: float, min_margin: float, top: int = 12):
    """Which passage this is, with the margin taken over a different VERSE rather than address.

    `verse_match` defends its margin against the best candidate from a different *passage*,
    which was the right unit for a song book. Caitanya-caritāmṛta breaks it: **the text quotes
    the same verse verbatim at more than one address.** `rādhāyāḥ praṇaya-mahimā kīdṛśam` scores
    1.000 at both Cc. Ādi 1.6 and Cc. Ādi 4.230 with identical text, so the margin is 0.000 and
    a correct identification is refused - the rival is not a rival, it is the same verse under
    another number.

    So identity is taken on the verse's own skeleton. This is the same reasoning that
    introduced passage identity in the first place, extended from "the same song" to "the same
    words": a candidate that says what the winner says cannot be evidence against it.

    **The margin itself is not relaxed.** Two runs whose rivals are genuinely different verses
    - `Yāhāṅ kṛṣṇa tāhāṅ nāi` at 0.033 and `bhartsana-tāḍane kāke kichu nā` at 0.111 - stay
    refused, because for scripture a confident error is worse than an admitted gap.
    """
    # One scan, reused. `rank` compares the query against every window in the corpus, and the
    # corpus is 134,354 windows, so ranking twice per run - once to identify and once to pick
    # which printed form to score against - doubled the work for nothing.
    ranked = index.rank(text, top=top, min_length=0.55)
    if not ranked:
        return None, 0, 0.0, []
    winner = ranked[0]
    same = skeleton(winner.verse)

    def is_the_same_verse(candidate) -> bool:
        """Same address, or words that are part of the winner's words.

        Equality alone was not enough, and the first attempt at this proved it: the runner-up
        to `rādhāyāḥ praṇaya-mahimā kīdṛśam` is a *shorter window of the very same verse*, whose
        skeleton therefore differs, so it kept cancelling the margin. Containment covers both
        shapes - one verse printed at two addresses, and a half of the winner competing with
        the whole of it - while two genuinely different verses that merely share a phrase
        contain neither each other nor the winner, and still refuse.
        """
        if candidate.passage == winner.passage:
            return True
        theirs = skeleton(candidate.verse)
        return bool(theirs) and (theirs in same or same in theirs)

    rival = next((c.score for c in ranked if not is_the_same_verse(c)), 0.0)
    margin = winner.score - rival
    family = [c for c in ranked if is_the_same_verse(c)]
    addresses = len({c.passage for c in family})

    # Cite the scripture, not the song that quotes it.
    scriptural = next((c for c in family if SCRIPTURAL.match(c.passage)
                       and c.score >= winner.score - 1e-9), None)
    if scriptural is not None and not SCRIPTURAL.match(winner.passage):
        winner = scriptural
    if winner.score < min_score or margin < min_margin:
        return None, addresses, margin, ranked
    return winner, addresses, margin, ranked


def best_printed_form(windows: list[str], run_words: int) -> str:
    """Among the printed forms of ONE identified passage, the one closest in length to the run.

    Identification and length are separate questions, and conflating them cost real coverage.
    A nine-word run quoting both halves of SB 1.2.10 matched the verse's five-word pada, because
    containment scoring gives a short window the same 1.0 as the whole verse and the tie broke
    on index order. The whole nine-word verse was sitting in the index unused.

    ⚠ `windows` must already be filtered to forms that score as well as the winner. Choosing by
    length alone was a defect: for a KKSongs match the passage is a whole SONG, so every line
    of it is a candidate, and three correct matches were re-pointed at unrelated lines of the
    right song. For a GRETIL match the passage is one verse and its windows are that verse's
    own padas, which is the case this was written for.
    """
    return min(windows, key=lambda w: (abs(len(w.split()) - run_words), -len(w)))


def comparable_length(run_words: int, printed_words: int) -> bool:
    """Is the printed window close enough in length to be what was recited here?"""
    if not run_words:
        return False
    ratio = printed_words / run_words
    return LENGTH_BAND[0] <= ratio <= LENGTH_BAND[1]


# English function words, which quoted scripture does not contain. `gap` was added so that
# `ceha` - a Sanskrit word carrying no diacritics - would stop cutting SB 1.2.10 in half, and
# it bridged `is`, `and` and `in` just as happily: `Kṛṣṇa is Rājā Rājeśvara` and
# `rajo-guṇa, tamo-guṇa, and sattva-guṇa` were queried against 177,000 windows of scripture as
# though they were quotations. Eight of the twelve non-verse runs got in this way.
ENGLISH_GAP = frozenset("""
a an the and or but so as at by for from in into of on to with within without is are was were
be been being am do does did has have had this that these those it its they them their he him
his she her we us our you your i me my mine not no nor if then than when while where which who
whom whose what why how all any both each few more most other some such only own same too very
can will just dont don't cant can't im i'm says said say saying tells told asked answered
means meaning one two three four five six seven eight nine ten first second third next last
there here now also thus therefore because about after before again against between during
through under over up down out off again once
""".split())


def bridgeable(word: str) -> bool:
    """May this undiacriticed word sit inside a run of quoted scripture?

    Yes for anything that could be Indic - `ceha`, `yas`, `tat` - and no for a plainly English
    function word. The asymmetry is deliberate: letting an English word through produces a
    phantom quotation that is then searched against the whole canon, while refusing one merely
    trims a run back to the verse itself, which is the better query anyway. `Śrīmad-Bhāgavatam
    says, jīvasya ...` becomes `jīvasya ...`, and is fairer to score against printed text.
    """
    bare = re.sub(r"[^\w']+", "", word).lower()
    return bool(bare) and bare not in ENGLISH_GAP


# Above this share of words ending in a comma, the run is an enumeration rather than a verse
# line. `sādhu, bhakta, Vaiṣṇava, ācārya.` is a list of terms; printed verse carries commas but
# not one after every word - `gharma-vṛṣṭi sahe, ānera karaye rakṣaṇa` sits at one in five.
LIST_COMMA_SHARE = 0.6


def looks_like_a_list(text: str) -> bool:
    """Is this an enumeration of terms rather than a line of verse?"""
    words = text.split()
    if len(words) < 3:
        return False
    delimited = sum(1 for w in words if w.rstrip('."\'').endswith(","))
    return delimited / len(words) >= LIST_COMMA_SHARE


# A scriptural address, as against a song title. Several sources hold the same verse - KKSongs
# quotes BG 3.37 inside "Jyayasi Cet Karmanas Te Mata" - and when they tie, the citation should
# be the scripture rather than the song that quotes it. The text is identical either way, so
# this changes what is cited and nothing that is scored.
SCRIPTURAL = re.compile(r"^(SB|BG|Cc\.|CB)\s")


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
        # A gap may be bridged only by a word that could be Indic. An English function word
        # ends the run instead, which is why `Kṛṣṇa is Rājā Rājeśvara` is no longer offered to
        # the matcher as a quotation.
        if current and len(pending) < gap and bridgeable(word["word"]):
            pending.append(word)
            continue
        close(current)
        current, pending = [], []
    close(current)                               # a run the lecture ends on

    found = [{"text": " ".join(w["word"] for w in run), "words": len(run),
              "start": run[0]["start"], "end": run[-1]["end"]} for run in runs]
    # An enumeration of terms is not a quotation, however many diacritics it carries.
    return [run for run in found if not looks_like_a_list(run["text"])]


def worklist(unmatched: list[dict]) -> list[dict]:
    """The DISTINCT quotations still to resolve, each with every place it was heard.

    This is where the economics of the whole approach becomes visible. He teaches from a fixed
    canon, so the same verse recurs across lectures - SB 1.2.10 appeared six times in five
    lectures before GRETIL could answer it - and a verse resolved once is resolved for all
    3,766 lectures. Grouping by the matcher's own skeleton rather than by the written text is
    what makes two renderings of one quotation a single item of work.
    """
    groups: dict[str, dict] = {}
    for run in unmatched:
        key = skeleton(run["text"])
        if not key:
            continue
        group = groups.setdefault(key, {"key": key, "longest": run["text"], "occurrences": []})
        group["occurrences"].append({"slug": run["slug"], "start": round(run["start"], 1),
                                     "words": run["words"], "text": run["text"]})
        if len(run["text"].split()) > len(group["longest"].split()):
            # The fullest rendering is the best thing to search with.
            group["longest"] = run["text"]
    ordered = sorted(groups.values(), key=lambda g: (-len(g["occurrences"]),
                                                     -len(g["longest"].split())))
    for group in ordered:
        group["heard_in"] = len(group["occurrences"])
    return ordered


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
    # 0.15, measured rather than chosen, by sweeping the gate against
    # `tests/fixtures/verse_truth.json` - 23 run/address pairs read by hand and 5 runs that are
    # not quotations at all. It is **the lowest margin at which no correct run is sent to a
    # wrong address and no non-quotation is sent to any address**, and it recovers two verified
    # identifications that 0.25 was discarding: SB 5.5.8 at 0.167 and Ohe Vaiṣṇava Ṭhākura at
    # 0.194.
    #
    # Below it: the first wrong answer appears at 0.12, but it is the one fixture entry marked
    # low confidence, so that boundary is soft. The FIRM boundary is 0.08, where `tri-tāpas:
    # ādhyātmika, ādhidaivika, ādhibhautika` - a list of terms - is handed a verse address.
    #
    # ⚠ The evidence is 28 runs from 5 lectures, judged by reading, with 64 aligned lectures
    # unexamined. This is "no wrong answer among the runs we have read", not "safe". Lower it
    # further only with more read ground truth, and re-read whatever a change newly admits.
    parser.add_argument("--margin", type=float, default=0.15)
    parser.add_argument("--min-score", type=float, default=0.30)
    args = parser.parse_args()

    songs = [json.loads(line) for line in SONGS.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    verses, passages = song_windows(songs)
    from_songs = len(verses)

    # GRETIL carries what a song book cannot: the Bhāgavatam and Gītā this archive is built on.
    # Each verse contributes itself AND its pādas, labelled with its own address, so a
    # four-word quotation can match something its own size instead of being identified and
    # then refused for scoring.
    scripture = load_gretil()
    for verse in scripture:
        for window in verse.windows():
            verses.append(window)
            passages.append(verse.address)

    from_gretil = len(verses) - from_songs

    # Sanskrit Wikisource supplies the chapter GRETIL has not got - BG 18, and with it BG 18.66,
    # the archive's most-cited Gītā verse - and stands as a second witness for 1-17. It is read
    # from a written file rather than transliterated here, because only `.venv-indic` holds
    # `indic_transliteration` and this script has to run anywhere.
    #
    # Both editions use the ADDRESS as the passage, so two printings of BG 18.66 are the same
    # passage and cannot cancel each other's margin - while their different sandhi segmentation
    # gives a garbled quotation two different skeletons to match against.
    gita = []
    if WIKISOURCE.exists():
        gita = [json.loads(line) for line in WIKISOURCE.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        for verse in gita:
            for window in [verse["text"], *verse.get("lines", [])]:
                if window and len(window.split()) >= 3:
                    verses.append(window)
                    passages.append(verse["address"])

    from_gita = len(verses) - from_songs - from_gretil

    # The scope the steward set is KKSongs, SB, BG, CC and CB. SB, BG and CC come from the
    # Vedabase corpus - available because the steward holds full permission from BBT, stated
    # 2026-10-12, verse text only and never the purports - and Caitanya-bhāgavata from the
    # Internet Archive's full text of the same edition wisdomlib serves.
    added: dict[str, tuple[int, int]] = {}
    for label, path in (("Vedabase SB/BG/CC", VEDABASE), ("Caitanya-bhāgavata", BHAGAVATA)):
        before, rows = len(verses), []
        if path.exists():
            rows = [json.loads(line) for line
                    in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for verse in rows:
                for window in [verse["text"], *verse.get("lines", [])]:
                    if window and len(window.split()) >= 3:
                        verses.append(window)
                        passages.append(verse["address"])
        added[label] = (len(verses) - before, len(rows))

    print(f"corpus: {len(verses):,} windows")
    print(f"  {from_songs:>7,} from {len(set(passages[:from_songs])):,} Indic songs (KKSongs)")
    print(f"  {from_gretil:>7,} from {len(scripture):,} printed verses (GRETIL)")
    print(f"  {from_gita:>7,} from {len(gita):,} verses (Sanskrit Wikisource)")
    for label, (windows, rows) in added.items():
        print(f"  {windows:>7,} from {rows:,} verses ({label})")
    print()
    # Verses resolved one at a time and remembered, which is the only route open for
    # Caitanya-caritamrta: no freely-licensed machine-readable text of it exists anywhere -
    # checked against Exa, Sanskrit Wikisource and Bengali Wikisource, and every digital
    # edition traces back to the Bhaktivedanta Vedabase. Whatever the steward resolves lands
    # here and becomes searchable immediately, with its provenance attached.
    cache = VerseCache(CACHE)
    for entry in cache._entries.values():
        verses.append(entry.verse)
        passages.append(f"cached {entry.key[:12]}")
    if len(cache):
        print(f"  plus {len(cache)} verse(s) resolved by search and cached\n")

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
            found, addresses, margin, ranked = identify(index, run["text"], args.min_score,
                                                        args.margin, top=80)
            entry = {"slug": lecture["slug"], **run}
            if found is None:
                report["unmatched"].append({**entry, "best_margin": round(margin, 3)})
                continue
            matched += 1
            # When one verse is printed at several addresses, say so rather than implying the
            # winner is the only place it appears.
            entry["also_at_addresses"] = addresses - 1
            # Only forms of the identified passage that account for the run as well as the
            # winner does. Length then breaks the tie among equals - it never overrules the
            # similarity that established the match.
            equal = [m.verse for m in ranked
                     if m.passage == found.passage and m.score >= found.score - 1e-9]
            printed_form = best_printed_form(equal or [found.verse], run["words"])
            found = found.__class__(printed_form, found.score, found.margin, found.index,
                                    found.passage)
            printed = len(found.verse.split())
            entry.update({"verse": found.verse, "song": found.passage,
                          "score": round(found.score, 3), "margin": round(margin, 3),
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

    todo = worklist(report["unmatched"])
    WORKLIST.write_text(json.dumps({"distinct": len(todo), "quotations": todo},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(report['unmatched'])} unmatched runs are {len(todo)} DISTINCT quotations, "
          f"each to be resolved once and then known for all 3,766 lectures:")
    for group in todo[:6]:
        print(f"  heard {group['heard_in']}x  {group['longest'][:62]}")

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(REPO)} and {WORKLIST.relative_to(REPO)}")


if __name__ == "__main__":
    main()
