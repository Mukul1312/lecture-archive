"""Scoring the hosted recognisers where the two sides do not speak the same units.

Two hazards, both of them about honesty rather than arithmetic.

ElevenLabs returns word times. Sarvam returns segments of ten to sixty seconds. Span scoring
places a word by its midpoint, so a segment handed over whole would put up to sixty words
wherever its own middle happened to fall - a minute of speech dropped on the wrong side of a
span edge.

And the Indic track must be split, because Sanskrit and Bengali are different languages and no
system here is best at both. `indic_language` judges a line, and on the Melbourne reference it
was fed cues a few seconds long. These spans run to forty minutes and hold both languages, so a
span-level label would call a whole lecture Sanskrit.
"""

import unittest

from scripts.compare_hosted import (
    language_mask,
    score_span_by_language,
    straddling_words,
    words_for,
    words_from_segments,
)


class SegmentTests(unittest.TestCase):
    def test_a_segment_becomes_evenly_spaced_words(self):
        words = words_from_segments([{"w": "hare krsna hare rama", "s": 10.0, "e": 18.0}])
        self.assertEqual([w["w"] for w in words], ["hare", "krsna", "hare", "rama"])
        self.assertAlmostEqual(words[0]["s"], 10.0)
        self.assertAlmostEqual(words[1]["s"], 12.0)
        self.assertAlmostEqual(words[3]["e"], 18.0)

    def test_the_last_word_ends_where_the_segment_ends(self):
        # No drift: a lecture is three thousand seconds and accumulated rounding would walk
        # the late words out of their span entirely.
        words = words_from_segments([{"w": "a b c", "s": 0.0, "e": 9.0},
                                     {"w": "d e", "s": 9.0, "e": 14.0}])
        self.assertAlmostEqual(words[2]["e"], 9.0)
        self.assertAlmostEqual(words[-1]["e"], 14.0)

    def test_a_segment_with_no_times_is_dropped_not_placed_at_zero(self):
        self.assertEqual(words_from_segments([{"w": "hare", "s": None, "e": None}]), [])

    def test_an_empty_segment_contributes_nothing(self):
        self.assertEqual(words_from_segments([{"w": "   ", "s": 1.0, "e": 2.0}]), [])

    def test_a_word_level_record_passes_through_untouched(self):
        record = {"unit": "word", "words": [{"w": "hare", "s": 1.0, "e": 1.4}]}
        self.assertEqual(words_for(record), record["words"])

    def test_a_segment_level_record_is_interpolated(self):
        record = {"unit": "segment", "words": [{"w": "hare krsna", "s": 0.0, "e": 2.0}]}
        self.assertEqual(len(words_for(record)), 2)

    def test_straddling_words_are_counted_so_the_exposure_is_stated(self):
        # One segment sits across the edge at 100.0; its words are the ones interpolation
        # had to decide, and the reader is entitled to know how many there were.
        segments = [{"w": "a b", "s": 10.0, "e": 20.0},
                    {"w": "c d e f", "s": 96.0, "e": 104.0}]
        self.assertEqual(straddling_words(segments, [{"start": 0.0, "end": 100.0}]), 4)

    def test_nothing_straddles_when_every_segment_is_inside(self):
        segments = [{"w": "a b", "s": 10.0, "e": 20.0}]
        self.assertEqual(straddling_words(segments, [{"start": 0.0, "end": 100.0}]), 0)


class LanguageMaskTests(unittest.TestCase):
    def test_a_bengali_neighbourhood_is_called_bengali(self):
        words = "ami tomara kariya bhuliya asiya".split()
        mask = language_mask(words, [True] * len(words))
        self.assertEqual(set(mask), {"bengali"})

    def test_a_sanskrit_neighbourhood_is_called_sanskrit(self):
        words = "iti eva hi bhagavan namah".split()
        mask = language_mask(words, [True] * len(words))
        self.assertEqual(set(mask), {"sanskrit"})

    def test_an_english_word_gets_no_language(self):
        mask = language_mask(["the", "ami", "lord"], [False, True, False])
        self.assertEqual(mask[0], None)
        self.assertEqual(mask[2], None)

    def test_the_window_is_local_so_one_span_can_hold_both(self):
        # The whole point: a span-level label would call all of this one language.
        words = ("ami tomara kariya bhuliya asiya chilama " + " ".join(["english"] * 40)
                 + " iti eva hi bhagavan namah tat").split()
        indic = [True] * 6 + [False] * 40 + [True] * 6
        mask = language_mask(words, indic)
        self.assertEqual(set(mask[:6]), {"bengali"})
        self.assertEqual(set(mask[-6:]), {"sanskrit"})


class SplitInvariantTests(unittest.TestCase):
    def test_the_two_languages_account_for_every_indic_word(self):
        # An aggregate invariant: a word must be charged to exactly one language, or a
        # comparison silently loses words and both rates improve.
        reference = ("Gurudeva said ami tomara kariya and then he chanted "
                     "iti eva hi bhagavan namah today").split()
        heard = "Gurudeva said ami tomara kariya and then he chanted iti eva hi namah".split()
        result = score_span_by_language(reference, heard)
        self.assertEqual(result["sanskrit"]["words"] + result["bengali"]["words"],
                         result["indic"]["words"])

    def test_english_and_indic_account_for_every_reference_word(self):
        reference = "Gurudeva said ami tomara and chanted namah".split()
        result = score_span_by_language(reference, reference)
        self.assertEqual(result["english"]["words"] + result["indic"]["words"],
                         result["reference_words"])

    def test_a_perfect_hypothesis_scores_no_errors_on_either_language(self):
        reference = "he said ami tomara kariya then iti eva hi namah".split()
        result = score_span_by_language(reference, reference)
        self.assertEqual(result["sanskrit"]["errors"], 0)
        self.assertEqual(result["bengali"]["errors"], 0)

    def test_an_empty_reference_span_is_scored_as_nothing_not_as_failure(self):
        result = score_span_by_language([], "whatever it heard".split())
        self.assertEqual(result["reference_words"], 0)
        self.assertEqual(result["indic"]["words"], 0)
