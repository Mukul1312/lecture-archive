"""Two defects found by reading all thirty-nine runs the first pass produced.

**One unmarked word cut verses in half.** SB 1.2.10 is `jīvasya tattva-jijñāsā nārtho yaś ceha
karmabhiḥ`, and `ceha` carries no diacritics, so breaking on it turned one six-word quotation
into the two three-word fragments `jijñāsā nārtho yaś` and `lābho jīveta yāvatā`. A three-word
fragment is both harder to match and easier to match wrongly.

**And a matched window can be longer than what was recited.** `ahaṁ bīja-pradaḥ pitā` matched
the window `tāsāḿ brahma mahad yonir ahaḿ bīja-pradaḥ pitā`. The match is correct — it is
BG 14.4 — but only three of those words occupy the run's stretch of audio, so scoring both
systems on all seven charged them four words nobody said in that window.
"""

import unittest

from scripts.verse_runs import comparable_length, indic_runs

KRSNA = "kṛṣṇa"
NAMA = "nāma"
CINTAMANI = "cintāmaṇi"
SB_1_2_10 = ["jīvasya", "tattva-jijñāsā", "nārtho", "yaś",
             "ceha", "karmabhiḥ"]


def aligned(tokens):
    return [{"word": word, "start": float(i), "end": float(i) + 0.5}
            for i, word in enumerate(tokens)]


class GapTests(unittest.TestCase):
    def test_a_single_unmarked_word_does_not_split_a_run(self):
        found = indic_runs(aligned(SB_1_2_10), minimum=3, gap=1)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["words"], 6)

    def test_two_unmarked_words_still_split_it(self):
        tokens = [KRSNA, NAMA, CINTAMANI, "and", "then", KRSNA, NAMA, CINTAMANI]
        self.assertEqual(len(indic_runs(aligned(tokens), minimum=3, gap=1)), 2)

    def test_a_run_never_ends_on_an_unmarked_word(self):
        found = indic_runs(aligned([KRSNA, NAMA, CINTAMANI, "today"]), minimum=3, gap=1)
        self.assertEqual(found[0]["words"], 3)
        self.assertNotIn("today", found[0]["text"])

    def test_a_run_never_begins_on_an_unmarked_word(self):
        found = indic_runs(aligned(["he", "said", KRSNA, NAMA, CINTAMANI]), minimum=3, gap=1)
        self.assertEqual(found[0]["words"], 3)
        self.assertNotIn("said", found[0]["text"])

    def test_no_gap_allowed_loses_the_tail_of_the_verse(self):
        # What the first pass did: the four words before `ceha` survive as a run and
        # `karmabhiḥ` is dropped for being alone, so the quotation is reported two words short.
        found = indic_runs(aligned(SB_1_2_10), minimum=3, gap=0)
        self.assertEqual([r["words"] for r in found], [4])


class ComparableLengthTests(unittest.TestCase):
    def test_a_window_the_same_length_is_scoreable(self):
        self.assertTrue(comparable_length(run_words=3, printed_words=3))

    def test_a_window_more_than_half_again_as_long_is_not(self):
        self.assertFalse(comparable_length(run_words=3, printed_words=7))

    def test_a_window_a_little_longer_is_allowed(self):
        # The transcript's punctuation and the printed edition's differ, so exact equality
        # would refuse almost every real match.
        self.assertTrue(comparable_length(run_words=7, printed_words=9))

    def test_a_window_much_shorter_is_not_scoreable_either(self):
        self.assertFalse(comparable_length(run_words=8, printed_words=3))


class BridgeTimeTests(unittest.TestCase):
    """A one-word gap can be a six-second gap, and must not be bridged.

    Caught by an earlier test: two recitations of the same three words, nine seconds apart,
    joined by the single word `then`. In token terms that is a one-word gap; in time it is a
    silence longer than either recitation, and the run's window would have been mostly nothing.
    """

    def test_a_long_silence_is_not_bridged_by_one_word(self):
        words = ([{"word": w, "start": float(i), "end": float(i) + 0.5}
                  for i, w in enumerate([KRSNA, NAMA, CINTAMANI])]
                 + [{"word": "then", "start": 9.0, "end": 9.4}]
                 + [{"word": w, "start": 10.0 + i, "end": 10.5 + i}
                    for i, w in enumerate([KRSNA, NAMA, CINTAMANI])])
        self.assertEqual(len(indic_runs(words, minimum=3, gap=1)), 2)

    def test_a_brief_gap_is_bridged(self):
        words = ([{"word": w, "start": i * 0.6, "end": i * 0.6 + 0.5}
                  for i, w in enumerate([KRSNA, NAMA, CINTAMANI])]
                 + [{"word": "the", "start": 1.9, "end": 2.2}]
                 + [{"word": w, "start": 2.3 + i * 0.6, "end": 2.8 + i * 0.6}
                    for i, w in enumerate([KRSNA, NAMA, CINTAMANI])])
        self.assertEqual(len(indic_runs(words, minimum=3, gap=1)), 1)


class CorpusHygieneTests(unittest.TestCase):
    """A line with a lost character cannot be ground truth, and attracts false matches.

    Found by reading: a nine-word run matched the printed line `nanenanam ninun nenam`. The
    KKSongs mirror stores 4,646 lines with U+FFFD where a letter was lost, and `fold` turns
    that into a space - so `jnana` becomes the two tokens `j` and `ana`, which resemble
    everything and identify nothing.
    """

    def test_a_line_with_a_lost_character_is_not_indexed(self):
        from scripts.verse_runs import song_windows
        songs = [{"name": "A", "language": "Sanskrit",
                  "lyrics": ["abhayam sattva-samsuddhir j\ufffdana-yoga-vyavasthitih",
                             "govindam adi purusam tam aham bhajami"]}]
        verses, _ = song_windows(songs, sizes=(1,))
        self.assertEqual(verses, ["govindam adi purusam tam aham bhajami"])

    def test_a_damaged_line_breaks_the_run_instead_of_being_skipped_over(self):
        # Skipping it would splice the line before to the line after and index a verse nobody
        # printed - the same fault as letting a window cross two songs.
        from scripts.verse_runs import song_windows
        songs = [{"name": "A", "language": "Sanskrit",
                  "lyrics": ["alpha beta gamma", "j\ufffdana lost line", "delta epsilon zeta"]}]
        verses, _ = song_windows(songs, sizes=(2,))
        self.assertEqual(verses, [])


class BestPrintedFormTests(unittest.TestCase):
    """Identification and length are separate questions, and conflating them cost coverage.

    A nine-word run quoting both halves of SB 1.2.10 matched the verse's five-word pada,
    because containment scoring gives a short window the same 1.0 as the whole verse and the
    tie broke on index order. The whole nine-word verse was in the index, unused, and the
    length gate then refused to score the match at all.
    """

    def test_the_form_closest_in_length_to_the_run_is_chosen(self):
        from scripts.verse_runs import best_printed_form
        forms = ["jivasya tattvajijnasa nartho yasceha karmabhih",
                 "kamasya nendriyapritirlabho jiveta yavata jivasya tattvajijnasa nartho "
                 "yasceha karmabhih"]
        self.assertEqual(len(best_printed_form(forms, run_words=9).split()), 9)

    def test_a_short_run_still_gets_the_short_form(self):
        from scripts.verse_runs import best_printed_form
        forms = ["alpha beta gamma", "alpha beta gamma delta epsilon zeta eta theta"]
        self.assertEqual(best_printed_form(forms, run_words=3), "alpha beta gamma")

    def test_ties_on_length_prefer_the_fuller_text(self):
        from scripts.verse_runs import best_printed_form
        forms = ["a b c", "aa bb cc dd"]
        self.assertEqual(best_printed_form(forms, run_words=4), "aa bb cc dd")


class OrphanedMarkTests(unittest.TestCase):
    """A combining mark with no base letter means the letter it belonged to is gone.

    `nanenanam ninun nenam` was the single wrong identification in a 90%-precision read, and
    once a length-comparable form of it existed it started contributing to the verse score.
    The length gate had been protecting against it by accident, which is not a guard.
    """

    def test_a_line_with_a_detached_diacritic_is_damaged(self):
        from scripts.verse_runs import damaged
        self.assertTrue(damaged("n\u0101nen\u0101nam \u0301 ninun nenam \u0301"))

    def test_a_diacritic_sitting_on_its_letter_is_fine(self):
        # The anusvara mis-decode: cosmetic, because fold and skeleton strip combining marks
        # before anything is compared. Dropping these would discard 5,482 usable lines.
        from scripts.verse_runs import damaged
        self.assertFalse(damaged("abhayam\u0301 sattva-sam\u0301\u015buddhir"))

    def test_clean_text_is_not_damaged(self):
        from scripts.verse_runs import damaged
        self.assertFalse(damaged("jaya radha madhava kunja bihari"))


class WorklistTests(unittest.TestCase):
    """The same verse quoted in five lectures is ONE item of work, not five.

    This is where the economics of retrieval become visible: he teaches from a fixed canon, so
    a verse resolved once is resolved for all 3,766 lectures. Grouping by the matcher's own
    skeleton rather than by the written text is what makes two renderings of one quotation a
    single item.
    """

    def runs(self, *pairs):
        return [{"slug": slug, "text": text, "start": 1.0, "words": len(text.split())}
                for slug, text in pairs]

    def test_two_renderings_of_one_quotation_collapse(self):
        from scripts.verse_runs import worklist
        got = worklist(self.runs(("a", "jivasya tattva-jijnasa nartho"),
                                 ("b", "jivasya tattva jijnasa nartho")))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["heard_in"], 2)

    def test_different_quotations_stay_separate(self):
        from scripts.verse_runs import worklist
        got = worklist(self.runs(("a", "jivasya tattva-jijnasa nartho"),
                                 ("b", "mahajano yena gatah sa pantha")))
        self.assertEqual(len(got), 2)

    def test_every_place_it_was_heard_is_recorded(self):
        from scripts.verse_runs import worklist
        got = worklist(self.runs(("lecture-one", "mahajano yena gatah sa pantha"),
                                 ("lecture-two", "mahajano yena gatah sa pantha")))
        self.assertEqual({o["slug"] for o in got[0]["occurrences"]},
                         {"lecture-one", "lecture-two"})

    def test_the_fullest_rendering_is_what_gets_searched_with(self):
        from scripts.verse_runs import worklist
        got = worklist(self.runs(("a", "gatah sa pantha"),
                                 ("b", "mahajano yena gatah sa pantha")))
        self.assertEqual(len(got[0]["longest"].split()), 5)

    def test_the_most_quoted_comes_first(self):
        from scripts.verse_runs import worklist
        got = worklist(self.runs(("a", "mahajano yena gatah sa pantha"),
                                 ("b", "mahajano yena gatah sa pantha"),
                                 ("c", "jivasya tattva-jijnasa nartho")))
        self.assertEqual(got[0]["heard_in"], 2)
