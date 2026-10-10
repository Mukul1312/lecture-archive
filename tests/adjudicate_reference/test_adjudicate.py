"""How much of our measured error belongs to the reference rather than to the recogniser.

Every figure this project has published on the archive is *system error plus reference error*
with no way to separate them. Two independent recognisers on the same five lectures give a way:
where both put the same thing and the reference says otherwise, the reference is the likely
error, because two systems from different vendors do not invent the same wrong word.

The care needed is in not treating the three kinds of disagreement as equal evidence. Both
systems *adding* the same words, or *replacing* a word identically, says something about the
reference. Both systems *missing* words the reference has says nothing - quiet speech is
exactly what two recognisers fail on together.
"""

import unittest

from scripts.adjudicate_reference import (
    adjudicate,
    agreement_at_disputes,
    disputes,
    near_match,
)


class DisputeTests(unittest.TestCase):
    def test_a_replaced_word_is_recorded_with_what_replaced_it(self):
        found = disputes(["the", "lord", "said"], ["the", "Lord's", "said"])
        self.assertEqual(found[(1, 2)], ("Lord's",))

    def test_a_missing_word_is_recorded_as_an_empty_replacement(self):
        found = disputes(["the", "lord", "said"], ["the", "said"])
        self.assertEqual(found[(1, 2)], ())

    def test_an_added_word_is_recorded_at_a_zero_width_site(self):
        # The reference tidies, so words the transcript never wrote are the likeliest
        # reference error of all - and they occupy no reference position.
        found = disputes(["the", "said"], ["the", "lord", "said"])
        self.assertEqual(found[(1, 1)], ("lord",))

    def test_an_agreeing_run_produces_no_dispute(self):
        self.assertEqual(disputes(["a", "b", "c"], ["a", "b", "c"]), {})


class NearMatchTests(unittest.TestCase):
    def test_a_romanisation_variant_is_not_a_reference_error(self):
        # Both systems writing "krishna" where the reference wrote "krsna" is a spelling
        # difference the scorer already forgives; counting it would invent reference errors.
        self.assertTrue(near_match(("krsna",), ("krishna",)))

    def test_a_genuinely_different_word_is_not_a_near_match(self):
        self.assertFalse(near_match(("lord",), ("lard",)))

    def test_different_lengths_are_not_near_matches(self):
        self.assertFalse(near_match(("krsna",), ("krishna", "consciousness")))


class AdjudicationTests(unittest.TestCase):
    def test_both_systems_adding_the_same_words_counts_as_an_omission(self):
        reference = "he said chant and be happy".split()
        heard = "he said please chant and be happy".split()
        result = adjudicate(reference, heard, list(heard))
        self.assertEqual(result["omitted_by_reference"], 1)
        self.assertEqual(result["wrong_in_reference"], 0)

    def test_both_systems_replacing_a_word_identically_counts_against_the_reference(self):
        reference = "he said chant and be happy".split()
        heard = "he said chant and feel happy".split()
        result = adjudicate(reference, heard, list(heard))
        self.assertEqual(result["wrong_in_reference"], 1)

    def test_both_systems_missing_a_word_is_NOT_counted_against_the_reference(self):
        # The crucial asymmetry. Quiet speech is what two recognisers lose together, so this
        # is evidence about the audio, not about the transcript.
        reference = "he said chant and be happy".split()
        heard = "he said chant and happy".split()
        result = adjudicate(reference, heard, list(heard))
        self.assertEqual(result["wrong_in_reference"], 0)
        self.assertEqual(result["omitted_by_reference"], 0)
        self.assertEqual(result["missed_by_both"], 1)

    def test_systems_disagreeing_with_each_other_prove_nothing(self):
        reference = "he said chant and be happy".split()
        first = "he said chant and feel happy".split()
        second = "he said chant and get happy".split()
        result = adjudicate(reference, first, second)
        self.assertEqual(result["wrong_in_reference"], 0)
        self.assertEqual(result["omitted_by_reference"], 0)

    def test_a_perfect_reference_is_charged_nothing(self):
        reference = "he said chant and be happy".split()
        result = adjudicate(reference, list(reference), list(reference))
        self.assertEqual(result["wrong_in_reference"], 0)
        self.assertEqual(result["omitted_by_reference"], 0)
        self.assertEqual(result["reference_words"], 6)

    def test_examples_are_kept_so_a_claim_can_be_read_not_trusted(self):
        reference = "he said chant and be happy".split()
        heard = "he said chant and feel happy".split()
        result = adjudicate(reference, heard, list(heard))
        self.assertTrue(result["examples"])
        self.assertIn("be", result["examples"][0]["reference"])


class AgreementControlTests(unittest.TestCase):
    """How much weight exact agreement deserves depends on how often it happens."""

    def test_two_identical_systems_agree_everywhere_they_dispute(self):
        reference = "a b c d".split()
        heard = "a x c y".split()
        self.assertEqual(agreement_at_disputes(reference, heard, list(heard)), 1.0)

    def test_two_systems_that_never_coincide_agree_nowhere(self):
        reference = "a b c d".split()
        self.assertEqual(
            agreement_at_disputes(reference, "a x c d".split(), "a b c y".split()), 0.0)

    def test_no_dispute_at_all_is_reported_as_no_rate(self):
        reference = "a b c".split()
        self.assertIsNone(agreement_at_disputes(reference, list(reference), list(reference)))
