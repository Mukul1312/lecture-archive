"""Reducing both sides of a comparison to what was actually said.

Every rule here removes a difference that is not a mishearing - an editor's aside, a contraction
written one way or the other, a number printed as digits. Without them a recogniser is marked
wrong for typography, and the measurement becomes one of the transcript's house style.

These were defined for the Melbourne reference and lived in a gitignored file. The official
archive writes things Melbourne never did, and each of those was a guaranteed error against every
model: 72 ordinals, 19 bracketed asides past the old length limit, 11 grouped thousands.
"""

import unittest

from scripts.transcript_accuracy import normalise, spell_number, spell_numbers


class NumberTests(unittest.TestCase):
    def test_small_numbers_are_spelled(self):
        self.assertEqual(spell_number(7), "seven")
        self.assertEqual(spell_number(24), "twenty four")
        self.assertEqual(spell_number(500), "five hundred")

    def test_a_year_is_not_left_as_digits(self):
        # "1977" appears five times; a model says "nineteen seventy seven" and was marked wrong.
        self.assertNotIn("1977", spell_numbers("in 1977 he came"))

    def test_grouped_thousands_are_spelled(self):
        self.assertEqual(spell_numbers("36,000 verses").split()[0], "thirty")
        self.assertNotIn(",", spell_numbers("36,000 verses"))

    def test_ordinals_become_words(self):
        self.assertEqual(spell_numbers("the 10th canto"), "the tenth canto")
        self.assertEqual(spell_numbers("the 7th chapter"), "the seventh chapter")

    def test_an_unusual_number_is_left_rather_than_mangled(self):
        # Better an untouched digit string than a confident wrong spelling.
        self.assertEqual(spell_number(1977), "1977")


class NormaliseTests(unittest.TestCase):
    def test_editorial_asides_go_in_either_bracket(self):
        self.assertNotIn("laughs", normalise("He said so (laughs) yes"))
        self.assertNotIn("inaudible", normalise("He said so [inaudible] yes"))

    def test_a_long_aside_is_removed_too(self):
        # The old rule stopped at 40 characters, so the longest asides - exactly the ones
        # carrying the most phantom words - were the ones it let through.
        long = "[Song: Durlabha manava-janma labhiya samsare, Bhaktivinoda Thakura, Kalyana]"
        self.assertNotIn("Bhaktivinoda", normalise(f"listen {long} now"))

    def test_a_speaker_label_is_not_speech(self):
        self.assertNotIn("Devotee", normalise("Devotee: There is no loss."))

    def test_contractions_match_whichever_way_they_were_written(self):
        self.assertEqual(normalise("he's here").split(), normalise("he is here").split())

    def test_the_words_themselves_survive(self):
        self.assertIn("surrender", normalise("You must surrender (he says) to Krsna"))


if __name__ == "__main__":
    unittest.main()
