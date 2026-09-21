from __future__ import annotations

import unittest

from scripts.transcript_accuracy import fold, has_diacritics, recognisable, score, skeleton


class TokenTests(unittest.TestCase):

    def test_folding_drops_fillers_punctuation_and_diacritics(self) -> None:
        self.assertEqual(fold("Śrī-Mārkaṇḍeya, uh, uvāca!"), ["sri", "markandeya", "uvaca"])
        self.assertEqual(fold("Don't"), ["don't"])

    def test_diacritics_mark_the_sanskrit_track(self) -> None:
        self.assertTrue(has_diacritics("Kṛṣṇa"))
        self.assertFalse(has_diacritics("understand"))

    def test_romanisation_differences_are_recognisable(self) -> None:
        for reference, heard in (("sri", "shri"), ("krsna", "krishna"), ("bhagavan", "bhagawan"),
                                 ("vaisnava", "vaishnava"), ("markandeya", "markandeyo")):
            with self.subTest(f"{reference}/{heard}"):
                self.assertTrue(recognisable(reference, heard))

    def test_different_words_are_not_recognisable(self) -> None:
        for reference, heard in (("krsna", "krishnaloka"), ("sadhu", "shadow"), ("prema", "problem")):
            with self.subTest(f"{reference}/{heard}"):
                self.assertFalse(recognisable(reference, heard))

    def test_skeleton_removes_meaningless_romanisation_choices(self) -> None:
        self.assertEqual(skeleton("shri"), skeleton("sri"))
        self.assertEqual(skeleton("vaisnava"), skeleton("baisnaba"))


class ScoreTests(unittest.TestCase):

    def test_sanskrit_spelt_differently_counts_as_recognised_but_english_stays_strict(self) -> None:
        reference = ["sri", "krsna", "take", "shelter", "of", "the", "soles"]
        is_indic = [True, True, False, False, False, False, False]
        hypothesis = ["shri", "krishna", "take", "shelter", "of", "the", "souls"]
        tally = score(reference, is_indic, hypothesis)
        self.assertEqual(tally["near"], 2, "both Sanskrit words were recognisable")
        self.assertEqual(tally["indic"]["errors"], 0)
        self.assertEqual(tally["english"]["errors"], 1, "soles/souls is a different word")

    def test_missing_and_invented_words_are_counted(self) -> None:
        tally = score(["take", "shelter", "now"], [False] * 3, ["take", "shelter", "right", "now"])
        self.assertEqual(tally["inserted"], 1)
        tally = score(["take", "shelter", "now"], [False] * 3, ["take", "now"])
        self.assertEqual(tally["missing"], 1)

    def test_a_perfect_transcript_has_no_errors(self) -> None:
        words = ["take", "shelter", "of", "krsna"]
        tally = score(words, [False, False, False, True], list(words))
        self.assertEqual((tally["exact"], tally["wrong"], tally["missing"], tally["inserted"]), (4, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
