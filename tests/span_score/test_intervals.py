"""How sure can we be that one system beat another?

Every figure in this project is a bare number. "ElevenLabs 10.5%, Whisper 17.6%" invites the
reading that ElevenLabs is better, and over that gap it almost certainly is - but the same table
carries pairs a point apart, and a point on this much data may be nothing at all.

The bootstrap answers it without any distributional assumption: resample the LECTURES, with
replacement, recompute the rate each time, and read off the spread. Lectures, not words, because
words inside one lecture are not independent - one speaker, one room, one tape.
"""

import unittest

from scripts.span_score import bootstrap_interval, beats


def unit(words, errors):
    """One lecture's contribution: so many reference words, so many of them wrong."""
    return {"words": words, "errors": errors}


class IntervalTests(unittest.TestCase):
    def test_an_interval_brackets_the_measured_rate(self):
        low, high = bootstrap_interval([unit(100, 10)] * 12, rounds=200, seed=1)
        self.assertLessEqual(low, 0.10)
        self.assertGreaterEqual(high, 0.10)

    def test_identical_lectures_give_a_tight_interval(self):
        low, high = bootstrap_interval([unit(100, 10)] * 12, rounds=200, seed=1)
        self.assertAlmostEqual(high - low, 0.0, places=6)

    def test_disagreeing_lectures_give_a_wide_one(self):
        mixed = [unit(100, 1), unit(100, 40), unit(100, 5), unit(100, 30)]
        low, high = bootstrap_interval(mixed, rounds=400, seed=1)
        self.assertGreater(high - low, 0.05)

    def test_more_lectures_narrow_the_interval(self):
        few = [unit(100, 5), unit(100, 25)] * 2
        many = [unit(100, 5), unit(100, 25)] * 20
        self.assertGreater(bootstrap_interval(few, rounds=400, seed=1)[1]
                           - bootstrap_interval(few, rounds=400, seed=1)[0],
                           bootstrap_interval(many, rounds=400, seed=1)[1]
                           - bootstrap_interval(many, rounds=400, seed=1)[0])

    def test_nothing_measured_is_not_a_crash(self):
        self.assertEqual(bootstrap_interval([], rounds=10, seed=1), (0.0, 0.0))


class ComparisonTests(unittest.TestCase):
    def test_a_large_consistent_gap_is_called(self):
        good = [unit(100, 5)] * 10
        bad = [unit(100, 30)] * 10
        self.assertTrue(beats(good, bad, rounds=400, seed=1)["separated"])

    def test_a_tiny_gap_is_not_called(self):
        # One point apart, and the lectures disagree among themselves - the honest answer is
        # that this data cannot separate them.
        a = [unit(100, 10), unit(100, 30), unit(100, 5), unit(100, 25)]
        b = [unit(100, 11), unit(100, 31), unit(100, 4), unit(100, 26)]
        self.assertFalse(beats(a, b, rounds=400, seed=1)["separated"])

    def test_the_comparison_is_paired_lecture_by_lecture(self):
        # Both systems are measured on the SAME lectures, so the difference is taken per
        # lecture. Unpaired resampling throws away the thing that makes small gaps visible.
        a = [unit(100, 10), unit(100, 40)]
        b = [unit(100, 12), unit(100, 42)]
        result = beats(a, b, rounds=400, seed=1)
        self.assertLess(result["difference"], 0)          # a has fewer errors
        self.assertIn("separated", result)

    def test_systems_measured_on_different_numbers_of_lectures_are_refused(self):
        with self.assertRaises(ValueError):
            beats([unit(100, 10)], [unit(100, 10)] * 3, rounds=10, seed=1)


if __name__ == "__main__":
    unittest.main()
