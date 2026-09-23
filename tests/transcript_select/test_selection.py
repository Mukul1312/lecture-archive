"""Choosing between recognisers, word by word.

The bake-off established that no single system is best, and that picking the best of three
per word would reach 92.4% on plain English against the 82.9% the gap-filling fusion
delivers. This is the thing that does the picking.
"""

import unittest

from scripts.transcript_select import confusion_network, overrule_where_confident, select


def net(pivot, *others):
    return confusion_network([pivot, *others])


class ConfusionNetworkTests(unittest.TestCase):
    def test_identical_transcripts_give_one_candidate_per_slot(self):
        slots = net(["the", "lotus", "feet"], ["the", "lotus", "feet"])
        self.assertEqual([s.candidates for s in slots],
                         [["the", "the"], ["lotus", "lotus"], ["feet", "feet"]])

    def test_a_substitution_puts_both_words_in_the_same_slot(self):
        slots = net(["he", "said", "so"], ["he", "sad", "so"])
        self.assertEqual(slots[1].candidates, ["said", "sad"])

    def test_a_word_one_system_lacks_becomes_an_empty_candidate(self):
        slots = net(["take", "shelter", "now"], ["take", "now"])
        self.assertEqual(slots[1].candidates, ["shelter", None])

    def test_a_word_only_one_system_heard_becomes_its_own_slot(self):
        slots = net(["all", "sorts", "religion"], ["all", "sorts", "of", "religion"])
        self.assertEqual([s.candidates for s in slots],
                         [["all", "all"], ["sorts", "sorts"], [None, "of"], ["religion", "religion"]])

    def test_every_slot_has_one_candidate_per_system(self):
        slots = net(["a", "b", "c"], ["a", "x", "c"], ["a", "b", "y"])
        for slot in slots:
            self.assertEqual(len(slot.candidates), 3)


class VotingTests(unittest.TestCase):
    def test_a_majority_overrules_the_first_system(self):
        # flex-en writes "takes"; whisper and flex-bn write "take". The majority wins,
        # which the gap-filling fusion could never do.
        self.assertEqual(select([["he", "takes", "shelter"],
                                 ["he", "take", "shelter"],
                                 ["he", "take", "shelter"]]),
                         ["he", "take", "shelter"])

    def test_with_no_majority_the_first_system_is_kept(self):
        self.assertEqual(select([["a", "b", "c"], ["a", "x", "c"], ["a", "y", "c"]]),
                         ["a", "b", "c"])

    def test_a_majority_can_vote_a_word_away(self):
        self.assertEqual(select([["he", "verily", "said"], ["he", "said"], ["he", "said"]]),
                         ["he", "said"])

    def test_a_majority_can_vote_a_missing_word_in(self):
        self.assertEqual(select([["all", "sorts", "religion"],
                                 ["all", "sorts", "of", "religion"],
                                 ["all", "sorts", "of", "religion"]]),
                         ["all", "sorts", "of", "religion"])

    def test_a_word_only_one_system_heard_is_not_inserted(self):
        self.assertEqual(select([["all", "sorts", "religion"],
                                 ["all", "sorts", "of", "religion"],
                                 ["all", "sorts", "religion"]]),
                         ["all", "sorts", "religion"])

    def test_weights_break_a_tie_towards_the_trusted_system(self):
        # Two systems, two different words: whoever is trusted more wins.
        self.assertEqual(select([["a", "b"], ["a", "x"]], weights=[1.0, 2.0]), ["a", "x"])
        self.assertEqual(select([["a", "b"], ["a", "x"]], weights=[2.0, 1.0]), ["a", "b"])

    def test_one_transcript_alone_is_returned_unchanged(self):
        self.assertEqual(select([["nothing", "to", "choose"]]), ["nothing", "to", "choose"])

    def test_an_empty_input_gives_an_empty_transcript(self):
        self.assertEqual(select([[]]), [])



class ConfidenceTests(unittest.TestCase):
    """Overruling by confidence, which is what plain voting could not do.

    Measured on the Melbourne reference: Whisper's own per-word probability separates
    49.6% correct in its lowest quarter from 98.5% in its highest, and using it to
    overrule the best single system took English error from 17.8% to 15.1%.
    """

    def test_agreement_is_left_alone(self):
        self.assertEqual(
            overrule_where_confident(["take", "shelter"], ["take", "shelter"], [0.9, 0.9], 0.5),
            ["take", "shelter"])

    def test_a_confident_challenger_overrules_the_base(self):
        self.assertEqual(
            overrule_where_confident(["he", "takes", "it"], ["he", "take", "it"], [0.9, 0.9, 0.9], 0.5),
            ["he", "take", "it"])

    def test_an_unsure_challenger_does_not(self):
        self.assertEqual(
            overrule_where_confident(["he", "takes", "it"], ["he", "take", "it"], [0.9, 0.1, 0.9], 0.5),
            ["he", "takes", "it"])

    def test_a_confident_challenger_can_add_a_word_the_base_lacks(self):
        self.assertEqual(
            overrule_where_confident(["all", "sorts", "religion"],
                                     ["all", "sorts", "of", "religion"], [0.9] * 4, 0.5),
            ["all", "sorts", "of", "religion"])

    def test_the_base_is_never_shortened_on_confidence_alone(self):
        # The challenger simply lacking a word is not evidence it was not spoken, so a
        # dropped word is never taken on the challenger's say-so.
        self.assertEqual(
            overrule_where_confident(["take", "full", "shelter"], ["take", "shelter"], [0.99, 0.99], 0.5),
            ["take", "full", "shelter"])

    def test_confidence_must_cover_the_challenger(self):
        with self.assertRaises(ValueError):
            overrule_where_confident(["a"], ["a", "b"], [0.9], 0.5)

if __name__ == "__main__":
    unittest.main()
