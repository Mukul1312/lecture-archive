"""Edit sites: the places a corrector must stop and type.

The bake-off table is quoted in the steward's hours, so the count must be defined
once, in the scorer, rather than recomputed by whichever script needs it.
"""

import unittest

from scripts.transcript_accuracy import edit_sites


def sites(reference, hypothesis, indic=None):
    indic = indic if indic is not None else [False] * len(reference)
    return edit_sites(reference, indic, hypothesis)


class EditSiteTests(unittest.TestCase):
    def test_a_perfect_transcript_has_nothing_to_correct(self):
        self.assertEqual(sites(["one", "two"], ["one", "two"]), [])

    def test_one_wrong_word_is_one_stop(self):
        found = sites(["he", "said", "so"], ["he", "sad", "so"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "wrong")
        self.assertEqual(found[0].reference, ["said"])
        self.assertEqual(found[0].heard, ["sad"])

    def test_a_run_of_dropped_words_is_one_stop_not_four(self):
        found = sites(["a", "b", "c", "d", "e"], ["a", "e"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "dropped")
        self.assertEqual(found[0].reference, ["b", "c", "d"])
        self.assertEqual(found[0].heard, [])

    def test_words_nobody_spoke_are_a_stop_of_their_own(self):
        found = sites(["a", "b"], ["a", "x", "y", "b"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].kind, "invented")
        self.assertEqual(found[0].heard, ["x", "y"])

    def test_two_faults_separated_by_a_good_word_are_two_stops(self):
        found = sites(["a", "b", "c"], ["x", "b", "y"])
        self.assertEqual(len(found), 2)

    def test_a_recognisable_romanisation_is_not_a_stop(self):
        # "śrī" folds to "sri"; heard as "shri" a reader recognises it, so nobody types.
        self.assertEqual(sites(["sri"], ["shri"], indic=[True]), [])

    def test_english_beside_a_forgiven_romanisation_is_still_a_stop(self):
        found = sites(["sri", "and"], ["shri", "end"], indic=[True, False])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reference, ["and"])

    def test_a_site_carries_the_surrounding_words_so_it_can_be_read(self):
        found = sites(["the", "lord", "said", "to", "him"], ["the", "lord", "sad", "to", "him"])
        self.assertEqual(found[0].before, ["the", "lord"])
        self.assertEqual(found[0].after, ["to", "him"])

    def test_distance_to_the_nearest_sanskrit_word_is_recorded(self):
        # reference: krsna(indic) then three English words, the last one wrong.
        found = sites(["krsna", "is", "the", "lord"], ["krsna", "is", "the", "lard"],
                      indic=[True, False, False, False])
        self.assertEqual(found[0].sanskrit_distance, 3)


if __name__ == "__main__":
    unittest.main()
