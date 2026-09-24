"""Grading a recogniser only where the transcript can be trusted.

The bake-off compared whole transcripts, which works when the reference covers the whole
recording. The archive's do not: six stop while the recording continues, and all of them omit
something. So a model is graded span by span, and everything it says outside those spans is
neither credited nor charged.

That makes one thing load-bearing: deciding which of a model's words fall inside a span. Get it
wrong at the edges and words are double-counted or lost, which looks exactly like a model that
mishears at sentence boundaries.
"""

import unittest

from scripts.span_score import heard_within, score_span, combine


def heard(*triples):
    return [{"w": w, "s": s, "e": e} for w, s, e in triples]


class BoundaryTests(unittest.TestCase):
    def test_a_word_inside_the_span_is_taken(self):
        got = heard_within(10.0, 20.0, heard(("yes", 12.0, 12.4)))
        self.assertEqual(got, ["yes"])

    def test_a_word_outside_the_span_is_left(self):
        self.assertEqual(heard_within(10.0, 20.0, heard(("no", 1.0, 1.4))), [])
        self.assertEqual(heard_within(10.0, 20.0, heard(("no", 40.0, 40.4))), [])

    def test_a_word_straddling_the_edge_belongs_to_the_side_holding_most_of_it(self):
        # Its midpoint decides. Using the start would pull in a word that mostly precedes the
        # span; using the end would drop one that mostly lies inside it.
        mostly_inside = heard(("in", 9.6, 10.8))     # midpoint 10.2
        mostly_outside = heard(("out", 9.0, 10.2))   # midpoint 9.6
        self.assertEqual(heard_within(10.0, 20.0, mostly_inside), ["in"])
        self.assertEqual(heard_within(10.0, 20.0, mostly_outside), [])

    def test_a_word_is_never_counted_in_two_spans(self):
        words = heard(("a", 9.9, 10.3), ("b", 15.0, 15.4), ("c", 19.9, 20.3))
        first = heard_within(0.0, 10.0, words)
        second = heard_within(10.0, 20.0, words)
        third = heard_within(20.0, 30.0, words)
        self.assertEqual(len(first) + len(second) + len(third), 3)
        self.assertEqual(set(first) & set(second), set())

    def test_words_come_back_in_the_order_they_were_said(self):
        got = heard_within(0.0, 100.0, heard(("second", 20.0, 20.4), ("first", 10.0, 10.4)))
        self.assertEqual(got, ["first", "second"])


class ScoringTests(unittest.TestCase):
    def test_a_perfect_recognition_scores_no_errors(self):
        result = score_span(["hare", "krsna", "hare", "rama"],
                            ["hare", "krsna", "hare", "rama"])
        self.assertEqual(result["english"]["errors"], 0)
        self.assertEqual(result["reference_words"], 4)

    def test_a_misheard_word_is_charged(self):
        result = score_span(["surrender", "to", "krsna"], ["surrender", "two", "krsna"])
        self.assertGreater(result["english"]["errors"], 0)

    def test_sanskrit_is_scored_by_closeness_not_spelling(self):
        # "śrī" heard as "shri" is recognition, not an error - the scorer's existing rule.
        result = score_span(["śrī", "kṛṣṇa"], ["shri", "krishna"])
        self.assertEqual(result["indic"]["errors"], 0)
        self.assertEqual(result["indic"]["words"], 2)

    def test_the_two_languages_are_counted_apart(self):
        result = score_span(["the", "śrī", "lord"], ["the", "shri", "lord"])
        self.assertEqual(result["english"]["words"], 2)
        self.assertEqual(result["indic"]["words"], 1)

    def test_a_span_the_model_said_nothing_in_is_all_errors_not_a_crash(self):
        result = score_span(["hare", "krsna"], [])
        self.assertEqual(result["reference_words"], 2)
        self.assertEqual(result["heard_words"], 0)

    def test_an_empty_reference_scores_nothing_rather_than_dividing_by_zero(self):
        result = score_span([], ["hare"])
        self.assertEqual(result["reference_words"], 0)


class CombineTests(unittest.TestCase):
    def test_totals_add_across_spans(self):
        a = score_span(["hare", "krsna"], ["hare", "krsna"])
        b = score_span(["rama", "rama"], ["rama", "wrong"])
        both = combine([a, b])
        self.assertEqual(both["reference_words"], 4)
        self.assertEqual(both["english"]["words"], 4)
        self.assertGreater(both["english"]["errors"], 0)

    def test_combining_nothing_is_not_an_error(self):
        self.assertEqual(combine([])["reference_words"], 0)


if __name__ == "__main__":
    unittest.main()
