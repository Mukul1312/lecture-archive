"""What must be true of a finished alignment, however it was produced.

Read-along fails quietly. A word placed before its predecessor, or past the end of the
recording, gives a page that highlights the wrong line and reports nothing. These checks run on
the result rather than inside any one code path, because the ways of producing spans - one pass,
cue by cue, segment by segment with offsets added back - each have their own way of going wrong
and the same way of looking fine.
"""

import unittest

from scripts.forced_align import WordSpan, problems


def span(word, start, end, score=0.9, index=0):
    return WordSpan(word=word, index=index, start=start, end=end, score=score)


class InvariantTests(unittest.TestCase):
    def test_a_sound_alignment_has_nothing_to_report(self):
        good = [span("hare", 1.0, 1.5), span("krsna", 1.6, 2.2), span("hare", 2.3, 2.8)]
        self.assertEqual(problems(good, duration=10.0), [])

    def test_a_word_that_goes_backwards_is_caught(self):
        # The signature of a chunk offset applied wrongly, or chunks joined out of order.
        out_of_order = [span("hare", 5.0, 5.5), span("krsna", 1.0, 1.5)]
        self.assertTrue(any("before the word before" in p for p in problems(out_of_order)))

    def test_a_word_that_ends_before_it_starts_is_caught(self):
        self.assertTrue(any("end before they start" in p for p in problems([span("x", 3.0, 2.0)])))

    def test_a_word_before_the_recording_began_is_caught(self):
        self.assertTrue(any("before the recording" in p for p in problems([span("x", -0.4, 0.2)])))

    def test_a_word_past_the_end_of_the_recording_is_caught(self):
        late = [span("x", 99.0, 99.9)]
        self.assertTrue(any("after the recording" in p for p in problems(late, duration=50.0)))
        self.assertEqual(problems(late, duration=100.0), [])

    def test_touching_words_are_not_a_problem(self):
        # Speech is continuous; one word ending exactly where the next begins is normal.
        self.assertEqual(problems([span("a", 1.0, 1.5), span("b", 1.5, 2.0)]), [])

    def test_an_empty_alignment_has_no_problems_to_report(self):
        self.assertEqual(problems([], duration=10.0), [])

    def test_without_a_duration_the_end_of_the_recording_is_not_judged(self):
        self.assertEqual(problems([span("x", 99.0, 99.9)]), [])


if __name__ == "__main__":
    unittest.main()
