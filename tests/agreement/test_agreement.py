"""Do two runs of the same alignment agree?

Before trusting fifty lectures aligned on rented hardware, align two of them on both and check
the answers match. The risk is specific and this project has already been bitten by its cousin:
batched Whisper decoding was faster and destroyed the chanted verse, 88% wrong. A GPU brings its
own version - float16 instead of float32, different kernels, cuDNN non-determinism - and a faster
number that differs from the laptop's number is worse than no number, because every figure built
on the Melbourne baseline stops being comparable.

The same check guards any change that could move a timing: a library upgrade, a refactor of the
walk, a different decoder. It is a regression test whose fixture is a previous run.
"""

import unittest

from scripts.agreement import compare_alignments, FRAME


def words(*triples):
    return [{"word": w, "start": s, "end": e} for w, s, e in triples]


class IdenticalTests(unittest.TestCase):
    def test_a_run_agrees_with_itself(self):
        run = words(("hare", 1.0, 1.4), ("krsna", 1.5, 1.9))
        result = compare_alignments(run, run)
        self.assertEqual(result["verdict"], "identical")
        self.assertEqual(result["max_shift"], 0.0)

    def test_agreement_within_one_frame_is_still_identical(self):
        # The model emits one frame every 20 ms, so a difference smaller than that is not a
        # difference at all - it is the same frame reported with different floating point.
        a = words(("hare", 1.000, 1.400))
        b = words(("hare", 1.000 + FRAME * 0.4, 1.400))
        self.assertEqual(compare_alignments(a, b)["verdict"], "identical")


class DivergenceTests(unittest.TestCase):
    def test_a_small_consistent_shift_is_reported_not_hidden(self):
        a = words(("hare", 1.0, 1.4), ("krsna", 2.0, 2.4), ("rama", 3.0, 3.4))
        b = words(("hare", 1.06, 1.46), ("krsna", 2.06, 2.46), ("rama", 3.06, 3.46))
        result = compare_alignments(a, b)
        self.assertNotEqual(result["verdict"], "identical")
        self.assertAlmostEqual(result["median_shift"], 0.06, places=3)

    def test_a_large_shift_is_called_diverged(self):
        a = words(("hare", 1.0, 1.4), ("krsna", 2.0, 2.4))
        b = words(("hare", 3.0, 3.4), ("krsna", 4.0, 4.4))
        self.assertEqual(compare_alignments(a, b)["verdict"], "diverged")

    def test_one_bad_word_among_many_is_surfaced_by_the_maximum(self):
        # A median hides a single catastrophic placement; the maximum is what catches it.
        a = words(*[(f"w{i}", i * 1.0, i * 1.0 + 0.4) for i in range(30)])
        b = [dict(w) for w in a]
        b[17]["start"] += 5.0
        result = compare_alignments(a, b)
        self.assertGreater(result["max_shift"], 4.9)
        self.assertLess(result["median_shift"], 0.01)
        self.assertNotEqual(result["verdict"], "identical")


class ShapeTests(unittest.TestCase):
    def test_a_different_number_of_words_is_a_failure_not_a_shift(self):
        a = words(("hare", 1.0, 1.4), ("krsna", 2.0, 2.4))
        b = words(("hare", 1.0, 1.4))
        result = compare_alignments(a, b)
        self.assertEqual(result["verdict"], "different text")
        self.assertIn("2", result["why"])

    def test_different_words_are_a_failure_even_at_the_same_times(self):
        a = words(("hare", 1.0, 1.4))
        b = words(("rama", 1.0, 1.4))
        self.assertEqual(compare_alignments(a, b)["verdict"], "different text")

    def test_two_empty_runs_agree_vacuously(self):
        self.assertEqual(compare_alignments([], [])["verdict"], "identical")

    def test_the_share_within_a_frame_is_reported(self):
        a = words(*[(f"w{i}", i * 1.0, i * 1.0 + 0.4) for i in range(10)])
        b = [dict(w) for w in a]
        b[0]["start"] += 1.0
        self.assertAlmostEqual(compare_alignments(a, b)["within_one_frame"], 0.9, places=2)


if __name__ == "__main__":
    unittest.main()
