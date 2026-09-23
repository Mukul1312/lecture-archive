"""Differences of writing must not be counted as differences of hearing.

Reading the bake-off's mistakes word by word showed three ways the measurement blamed a
recogniser for something it did not do: contractions, speaker labels, and the reference's
own typos. The first two are mechanical and belong here; the third is not mechanical and
is reported rather than repaired.
"""

import unittest

from scripts.transcript_accuracy import (
    expand_contractions, fold, join_orphan_clitics, strip_speaker_label)


class ContractionTests(unittest.TestCase):
    def test_a_contraction_and_its_long_form_become_the_same_words(self):
        self.assertEqual(fold(expand_contractions("he's full of danger")),
                         fold(expand_contractions("he is full of danger")))

    def test_every_unambiguous_contraction_is_expanded(self):
        for short, long in [("I'll go", "I will go"), ("we've seen", "we have seen"),
                            ("they're here", "they are here"), ("isn't it", "is not it"),
                            ("I'm quoting", "I am quoting")]:
            with self.subTest(short=short):
                self.assertEqual(fold(expand_contractions(short)), fold(expand_contractions(long)))

    def test_an_ambiguous_possessive_expands_the_same_way_on_both_sides(self):
        # "Krsna's mercy" becomes odd text, but it becomes the SAME odd text in the
        # reference and in the transcript, so it never scores as an error.
        self.assertEqual(fold(expand_contractions("Krsna's mercy")),
                         fold(expand_contractions("Krsna's mercy")))

    def test_a_word_with_no_apostrophe_is_untouched(self):
        self.assertEqual(expand_contractions("assures him"), "assures him")

    def test_the_curly_apostrophe_counts_too(self):
        self.assertEqual(fold(expand_contractions("he’ll")), fold(expand_contractions("he will")))


class OrphanCliticTests(unittest.TestCase):
    """Some recognisers write the clitic as its own word: "isn t", "he ll".

    That is a defect one regular expression repairs, not a word misheard, so it is
    normalised rather than counted. Applied to both sides, where the reference has
    already been expanded and so contains none of these.
    """

    def test_a_split_negation_is_joined(self):
        self.assertEqual(fold(join_orphan_clitics("isn t it")),
                         fold(expand_contractions("isn't it")))

    def test_a_split_negation_of_a_longer_verb_is_joined(self):
        self.assertEqual(fold(join_orphan_clitics("doesn t matter")),
                         fold(expand_contractions("doesn't matter")))

    def test_the_other_split_clitics_are_joined(self):
        for split, apostrophe in [("he ll die", "he'll die"), ("we ve seen", "we've seen"),
                                  ("they re here", "they're here"), ("i m quoting", "i'm quoting"),
                                  ("it s full", "it's full")]:
            with self.subTest(split=split):
                self.assertEqual(fold(join_orphan_clitics(split)), fold(expand_contractions(apostrophe)))

    def test_an_already_expanded_reference_is_left_alone(self):
        self.assertEqual(join_orphan_clitics("it is not full of danger"), "it is not full of danger")

    def test_ordinary_words_are_not_mistaken_for_clitics(self):
        self.assertEqual(join_orphan_clitics("the lotus feet of krsna"), "the lotus feet of krsna")


class SpeakerLabelTests(unittest.TestCase):
    def test_a_speaker_label_is_removed_because_nobody_says_it(self):
        self.assertEqual(strip_speaker_label("Mr Peter: Identification with the body."),
                         "Identification with the body.")

    def test_a_label_of_several_names_is_removed(self):
        self.assertEqual(strip_speaker_label("Gour Govinda Swami: And therefore you fear?"),
                         "And therefore you fear?")

    def test_a_section_heading_is_not_a_speaker_and_stays(self):
        # He reads these aloud, so they are words he spoke.
        self.assertEqual(strip_speaker_label("Translation: Sri Markandeya said"),
                         "Translation: Sri Markandeya said")
        self.assertEqual(strip_speaker_label("Purport: conditioned souls"),
                         "Purport: conditioned souls")

    def test_a_colon_in_the_middle_of_a_line_is_left_alone(self):
        self.assertEqual(strip_speaker_label("he said this: fear comes from the second"),
                         "he said this: fear comes from the second")

    def test_a_lowercase_word_before_a_colon_is_not_a_label(self):
        self.assertEqual(strip_speaker_label("bhayam: fear"), "bhayam: fear")

    def test_a_verse_citation_is_not_a_label(self):
        self.assertEqual(strip_speaker_label("SB 11.2.37: bhayam dvitiya"),
                         "SB 11.2.37: bhayam dvitiya")


if __name__ == "__main__":
    unittest.main()
