"""What a review package must get right before a reviewer spends a minute on it.

Every stop costs a devotee about ten seconds, so a stop that asks the wrong question, plays the
wrong audio or counts toward the wrong language wastes their seva and corrupts the measurement it
feeds. The tests here are the ways that has been seen to go wrong on real data, not a matrix:

- the comparison must agree with the scorer about what a word is, or a stop appears where the
  scorer sees no difference (found: `Prabhupāda:` read as a speaker label, one word at a time);
- one stop, one language, without cutting a verse in half at a word the editor left unmarked;
- no stop where the published words are known to sit away from where they were spoken;
- a clip never runs past either end of the recording;
- nothing that breaks the format is ever written.
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_contract import package_rules, schema_errors
from scripts.review_package import (CONTEXT_SECONDS, TrustedSpan, Word, agreed_pieces,
                                    agreement_windows, assemble, check_against_scorer, clip,
                                    comparable_tokens, context_words, difference_stops,
                                    disagreement_draft, identical_pairs, out_of_earshot,
                                    piece_draft, recited, span_manifest_is_current,
                                    trusted_spans, unasked_agreed, word_languages, write_package)
from scripts.scoreable import scoreable_spans


def words(text: str, start: float = 10.0, step: float = 0.4) -> list[Word]:
    return [Word(w, round(start + i * step, 3), round(start + i * step + 0.3, 3))
            for i, w in enumerate(text.split())]


class ComparisonTests(unittest.TestCase):
    def test_tokens_are_the_scorers_tokens_even_for_a_word_that_looks_like_a_label(self):
        # One word at a time, "Prabhupāda:" is a whole line ending in a colon, which the scorer's
        # cleanup reads as a speaker label. In the transcript it ends "Translation by Śrīla
        # Prabhupāda:", is spoken, and the scorer keeps it.
        sentence = "Translation by Śrīla Prabhupāda: The Supreme".split()
        tokens, owners, _ = comparable_tokens(sentence)
        self.assertIn("prabhupada", tokens)
        self.assertEqual(owners[tokens.index("prabhupada")], 3)
        check_against_scorer(sentence)                   # raises if they ever drift apart

    def test_a_contraction_or_a_number_written_differently_is_not_a_stop(self):
        published = words("you'll see text 37 here")
        heard = words("you will see text thirty seven here")
        self.assertEqual(difference_stops(published, heard, ["english"] * 5), [])

    def test_a_word_stored_with_separate_accent_marks_is_written_composed(self):
        # Found on cc-adi-lila-4-256-258: its transcript stores ṛ as r plus a combining dot. The
        # format requires NFC (P9), and the two forms are the same text, so the package composes.
        decomposed = "Kṛṣṇa"
        self.assertEqual(Word(decomposed, 1.0, 1.5).text, "Kṛṣṇa")
        self.assertEqual(comparable_tokens([decomposed])[0], comparable_tokens(["Kṛṣṇa"])[0])

    def test_only_the_differing_words_are_highlighted(self):
        published = words("Not you'll live for only eating.")
        heard = words("Not we'll live for only eating.")
        [stop] = difference_stops(published, heard, ["english"] * 6)
        self.assertEqual([w.text for w in stop.published], ["you'll"])
        self.assertEqual(stop.differs_published, [0])
        self.assertEqual(stop.differs_heard, [0])


class LanguageTests(unittest.TestCase):
    def test_an_unmarked_sanskrit_word_inside_a_verse_keeps_the_verse_language(self):
        # `ceha` carries no diacritics, so by marks alone it is English and the verse is cut.
        self.assertEqual(word_languages(words("nārtho yaś ceha karmabhiḥ")), ["sanskrit"] * 4)

    def test_an_english_word_nearby_does_not_make_a_sanskrit_word_bengali(self):
        # English "more" is also the Bengali pronoun `more`; it labelled `śreya` Bengali on BG 3.37.
        labels = word_languages(words("about this preya not śreya how can we get more and"))
        self.assertEqual(labels[4], "sanskrit")

    def test_a_bengali_line_is_bengali(self):
        self.assertEqual(word_languages(words("'āmāra' bolite āre kichu nāi")), ["bengali"] * 5)

    def test_an_english_word_between_two_names_stays_english(self):
        self.assertEqual(word_languages(words("Kṛṣṇa is Rājā")),
                         ["sanskrit", "english", "sanskrit"])

    def test_a_differing_passage_that_changes_language_becomes_one_stop_per_language(self):
        published = words("Lord Kṛṣṇa says this")
        heard = words("Lord Krishna said this")
        stops = difference_stops(published, heard, word_languages(published))
        self.assertEqual([(s.language, [w.text for w in s.published], [w.text for w in s.heard])
                          for s in stops],
                         [("sanskrit", ["Kṛṣṇa"], ["Krishna"]), ("english", ["says"], ["said"])])

    def test_words_only_the_recogniser_heard_are_not_given_a_language(self):
        published = words("the material world")
        heard = words("the whole material world")
        [stop] = difference_stops(published, heard, ["english"] * 3)
        self.assertEqual((stop.language, [w.text for w in stop.heard]), ("unknown", ["whole"]))


class SpanTests(unittest.TestCase):
    def test_a_stretch_whose_words_were_heard_elsewhere_is_cut_out_of_the_trusted_spans(self):
        timed = [{"word": f"w{i}", "index": i, "start": float(i), "end": i + 0.5, "score": 0.5}
                 for i in range(30)]
        spans = trusted_spans(timed, misplaced=[[10.0, 14.5, 5]])
        self.assertEqual([(s.first, s.last) for s in spans], [(0, 9), (15, 29)])
        self.assertTrue(all(not (s.start < 14.5 and 10.0 < s.end) for s in spans))


class SpanManifestTests(unittest.TestCase):
    def test_the_span_manifest_is_checked_against_the_alignment_it_was_made_from(self):
        # Found on cc-adi-lila-9-46: dropping 32 timed editorial words under the newer cleanup
        # rule split one span, so spans recomputed after the drop never matched the manifest,
        # which was right for the alignment as stored.
        stored = [{"word": f"w{i}", "start": 10.0 + i * 0.5, "end": 10.4 + i * 0.5, "score": 0.9}
                  for i in range(400)]
        entry = {"spans_detail": [{"start": s.start, "end": s.end}
                                  for s in scoreable_spans(stored)]}
        self.assertTrue(span_manifest_is_current(stored, entry))
        later = [dict(w, start=w["start"] + 30, end=w["end"] + 30) if i > 200 else w
                 for i, w in enumerate(stored)]
        self.assertFalse(span_manifest_is_current(later, entry))


class ClipTests(unittest.TestCase):
    def test_a_clip_stays_inside_the_recording(self):
        self.assertEqual(clip(0.72, 3.48, 3649.016), (0.0, 6.48))
        self.assertEqual(clip(3647.0, 3648.976, 3649.016), (3644.0, 3649.016))


class VerseTests(unittest.TestCase):
    def test_only_the_printed_words_that_were_recited_are_suggested(self):
        printed = "kāmasya nendriyaprītirlābho jīveta yāvatā jīvasya tattvajijñāsā nārtho yaśceha karmabhiḥ"
        heard = "jīvasya tattva jijñāsā nārtho yaś ceha karmabhiḥ"
        self.assertEqual(recited(printed.split(), heard.split()), [4, 5, 6, 7, 8])

    def test_a_whole_printed_pada_heard_is_all_suggested(self):
        self.assertEqual(recited("lābho jīveta yāvatā".split(), "śreya, lābho jīveta yāvatā.".split()),
                         [0, 1, 2])


class AgreementTests(unittest.TestCase):
    def test_agreement_samples_come_only_from_exactly_identical_text(self):
        # Two versions shown as one text must be the same text, or showing one hides the other.
        published = words("a proper teacher, bona fide teacher. Thank you Kṛṣṇa all")
        heard = words("a proper teacher, bona fide teacher. Thank you Krishna all")
        windows = agreement_windows(published, heard, ["english"] * 10, size=4)
        self.assertEqual([(a, b) for a, b, _ in windows], [(0, 4), (4, 8)])

    def test_an_agreement_sample_is_out_of_earshot_of_every_other_stop(self):
        # Found on Brisbane: a sample starting 0.065 s after the "later"/"latter" stop played that
        # disagreement in its own clip and showed it in its context words, so the "one text" it
        # is shown as was not one text, and the sample gave itself away.
        later_latter = [(143.264, 143.7)]
        self.assertFalse(out_of_earshot(143.765, 146.76, later_latter))
        self.assertTrue(out_of_earshot(143.7 + CONTEXT_SECONDS + 0.01, 149.0, later_latter))
        self.assertFalse(out_of_earshot(137.0, 143.264 - CONTEXT_SECONDS + 0.01, later_latter))


def whole_span(published: list[Word]) -> list[TrustedSpan]:
    return [TrustedSpan(published[0].start, published[-1].end, 0, len(published) - 1)]


def texts(published: list[Word], heard: list[Word], piece: tuple) -> tuple[list[str], list[str]]:
    a, b, h, h_end = piece
    return [w.text for w in published[a:b]], [w.text for w in heard[h:h_end]]


class EveryAgreedPieceTests(unittest.TestCase):
    """The mode that asks every agreed piece (plan of 31 October 2026, section 3).

    Where both sources agree nobody listens, and both can be wrong together. Every word they
    wrote exactly alike is asked once, in a piece the app can show as one text.
    """

    def test_every_identical_agreed_word_is_in_exactly_one_piece_of_at_most_six(self):
        text = "we must hear from a bona fide teacher who knows the truth and acts"
        published, heard = words(text), words(text)
        pieces = agreed_pieces(published, heard, ["english"] * 14, whole_span(published),
                               set(), set())
        covered = [i for a, b, _, _ in pieces for i in range(a, b)]
        self.assertEqual(covered, list(range(14)))
        self.assertEqual([b - a for a, b, _, _ in pieces], [6, 6, 2])   # the last may be shorter
        for piece in pieces:
            mine, theirs = texts(published, heard, piece)
            self.assertEqual(mine, theirs)

    def test_a_piece_never_crosses_a_language_a_span_edge_or_another_stops_words(self):
        text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
        published, heard = words(text), words(text)
        languages = ["english"] * 5 + ["sanskrit"] * 3 + ["english"] * 8
        spans = [TrustedSpan(published[0].start, published[10].end, 0, 10),
                 TrustedSpan(published[11].start, published[15].end, 11, 15)]
        # Published word 13 is another stop's; so is the ElevenLabs word paired with 7.
        pieces = agreed_pieces(published, heard, languages, spans, taken_p={13}, taken_h={7})
        self.assertEqual([(a, b) for a, b, _, _ in pieces],
                         [(0, 5), (5, 7), (8, 11), (11, 13), (14, 16)])

    def test_untimed_unknown_or_differently_written_words_are_never_asked(self):
        published = words("a proper teacher, bona fide teacher. Thank you Kṛṣṇa all")
        heard = words("a proper teacher bona fide teacher. Thank you Krishna all")
        published[4] = Word("fide", None, None)          # the aligner could not place it
        languages = ["english"] * 10
        languages[1] = "unknown"
        pieces = agreed_pieces(published, heard, languages, whole_span(heard), set(), set())
        self.assertEqual([(a, b) for a, b, _, _ in pieces], [(0, 1), (3, 4), (5, 8), (9, 10)])

    def test_a_pairing_further_apart_than_a_timing_error_is_not_asked(self):
        # Matching text alone once paired `ei` with another occurrence 25 s away. A piece is
        # one clip, so both texts must have been heard in the same place.
        published = words("one two three four")
        heard = words("one two") + words("three four", start=12.5)
        pieces = agreed_pieces(published, heard, ["english"] * 4,
                               [TrustedSpan(10.0, 13.5, 0, 3)], set(), set())
        self.assertEqual([(a, b) for a, b, _, _ in pieces], [(0, 2)])

    def test_context_words_stop_at_another_stops_words(self):
        # A piece shown beside a disagreement's words would show which version is published.
        ws = words("a b c d e f g h i j k l m n")
        self.assertEqual(context_words(ws, 5, 7, blocked={2, 10}), (["d", "e"], ["h", "i", "j"]))
        self.assertEqual(context_words(ws, 7, 8, blocked=set()),
                         (list("bcdefg"), list("ijklmn")))       # otherwise six either side

    def test_a_package_with_pieces_beside_a_disagreement_keeps_the_format(self):
        published = words("we must hear the bona fide teacher who knows the truth and acts on it today",
                          start=100.0)
        heard = words("we must hear a bona fide teacher who knows the truth and acts on it today",
                      start=100.0)
        languages = ["english"] * 16
        spans = whole_span(published)
        [difference] = difference_stops(published, heard, languages)
        taken_p = set(range(difference.p_lo, difference.p_hi))
        taken_h = set(range(difference.h_lo, difference.h_hi))
        drafts = [disagreement_draft(difference, published, heard)] + [
            piece_draft(piece, published, heard, languages, taken_p, taken_h)
            for piece in agreed_pieces(published, heard, languages, spans, taken_p, taken_h)]
        package = json.loads(Path("contracts/review/examples/valid/package-bg-3-37-brisbane.json")
                             .read_text(encoding="utf-8"))
        stops, transcript = assemble(package["lecture"]["id"], drafts,
                                     package["lecture"]["duration_seconds"], published, languages,
                                     spans, heard, outside=[])
        package.update(trustworthy_spans=[{"start": spans[0].start, "end": spans[0].end}],
                       untranscribed=[], transcript={"words": transcript}, stops=stops)
        self.assertEqual(schema_errors("lecture-review-package", package), [])
        self.assertEqual(package_rules(package), [])
        self.assertTrue(all(w["stop"] for w in transcript))     # every agreed word is asked
        before, after, _ = [s for s in stops if s["kind"] == "agreement-sample"]
        # The piece before "the"/"a" shows nothing after it, the one after it nothing before.
        self.assertEqual([v["after"] for v in before["versions"]], [[], []])
        self.assertEqual([v["before"] for v in after["versions"]], [[], []])

    def test_every_agreed_word_not_asked_is_reported_with_its_reason(self):
        # Reported as unchecked, never as correct (plan, section 3).
        published = words("a proper teacher, bona fide teacher. Thank you all")
        heard = words("a proper teacher bona fide teacher. Thank you all")
        published[4] = Word("fide", None, None)
        spans = whole_span(heard)
        # Published word 3 lies in a disagreement too long to ask; ElevenLabs word 8 is a stop's.
        pieces = agreed_pieces(published, heard, ["english"] * 9, spans, {3}, {8})
        owned = {i for a, b, _, _ in pieces for i in range(a, b)}
        found = unasked_agreed(published, ["english"] * 9, spans, owned, too_long_p={3},
                               pairs=identical_pairs(published, heard, spans), taken_h={8})
        self.assertEqual(found, {("written differently (agreed only after folding)", "english"): 1,
                                 ("inside a disagreement too long to ask", "english"): 1,
                                 ("untimed", "english"): 1,
                                 ("its ElevenLabs word is in another stop or an unasked "
                                  "disagreement", "english"): 1})


class RefusalTests(unittest.TestCase):
    def test_a_package_that_breaks_a_rule_is_not_written(self):
        example = Path("contracts/review/examples/valid/package-bg-3-37-brisbane.json")
        package = json.loads(example.read_text(encoding="utf-8"))
        package["stops"].reverse()                       # P4: out of timeline order
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "v1.json"
            with self.assertRaises(ValueError):
                write_package(package, target)
            self.assertFalse(target.exists())

    def test_a_package_is_written_with_lf_line_endings(self):
        # Its SHA-256 is what every answer record names; a CRLF would change it on Windows.
        example = Path("contracts/review/examples/valid/package-bg-3-37-brisbane.json")
        package = json.loads(example.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "v1.json"
            write_package(package, target)
            self.assertNotIn(b"\r", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
