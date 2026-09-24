"""Where a transcript can be trusted, and therefore where a model may be graded.

This is the one boolean the archive corpus needs. Not a taxonomy of what the audio contains -
we measured that chanting and teaching cannot be told apart by any signal we have - but the
narrower question a fair comparison actually depends on: **is there reference text for this
stretch of audio?**

Getting it wrong in one direction wastes audio. Getting it wrong in the other charges a
recogniser for words it heard correctly, which is how a transcript that stops halfway makes a
good model look bad.

The gap threshold is measured, not chosen. On the Melbourne reference - verified cue by cue, so
its pauses are by definition normal - 99.9% of gaps between words are under 7.2 seconds. Ten
seconds therefore keeps essentially every real pause and cuts only the unusual.
"""

import unittest

from scripts.scoreable import Span, scoreable_spans, summarise


def words(*pairs):
    """(word, start, end) triples, written compactly."""
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


class SpanTests(unittest.TestCase):
    def test_a_continuous_transcript_is_one_span(self):
        spans = scoreable_spans(words(("a", 1.0, 1.4), ("b", 1.5, 1.9), ("c", 2.0, 2.4)),
                                min_words=1)
        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0].start, spans[0].end), (1.0, 2.4))

    def test_a_normal_pause_does_not_split_a_span(self):
        # Seven seconds is within what a verified transcript shows; it is a pause, not a hole.
        spans = scoreable_spans(words(("a", 1.0, 1.4), ("b", 8.0, 8.4)), min_words=1)
        self.assertEqual(len(spans), 1)

    def test_a_long_silence_splits_the_span(self):
        # Beyond ten seconds the transcript may simply not cover what is there.
        spans = scoreable_spans(words(("a", 1.0, 1.4), ("b", 30.0, 30.4)), min_words=1)
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0].end, 1.4)
        self.assertEqual(spans[1].start, 30.0)

    def test_a_span_carries_the_words_that_belong_to_it(self):
        spans = scoreable_spans(words(("hare", 1.0, 1.4), ("krsna", 1.5, 1.9),
                                      ("rama", 40.0, 40.4)), min_words=1)
        self.assertEqual(spans[0].words, ["hare", "krsna"])
        self.assertEqual(spans[1].words, ["rama"])

    def test_a_span_never_extends_past_its_own_words(self):
        # The whole point is to grade only where there is text, so a span may not claim audio
        # beyond the words it holds.
        for span in scoreable_spans(words(("a", 5.0, 5.4), ("b", 6.0, 6.4)), min_words=1):
            self.assertGreaterEqual(span.start, 5.0)
            self.assertLessEqual(span.end, 6.4)

    def test_a_fragment_too_short_to_grade_is_dropped(self):
        # One stray word after a long silence tells you nothing about a recogniser, and its
        # boundary effects are larger than its content.
        spans = scoreable_spans(words(("a", 1.0, 1.4), ("b", 1.5, 1.9), ("c", 2.0, 2.4),
                                      ("d", 2.5, 2.9), ("e", 3.0, 3.4), ("stray", 90.0, 90.4)),
                                min_words=5)
        self.assertEqual(len(spans), 1)
        self.assertNotIn("stray", spans[0].words)

    def test_nothing_aligned_gives_nothing_to_grade(self):
        self.assertEqual(scoreable_spans([]), [])

    def test_the_audio_after_a_transcript_ends_is_never_included(self):
        # The six archive lectures that stop early depend on exactly this.
        spans = scoreable_spans(words(("a", 1.0, 1.4), ("b", 2.0, 2.4)), min_words=1)
        self.assertLessEqual(max(s.end for s in spans), 2.4)


class SummaryTests(unittest.TestCase):
    def test_it_reports_how_much_can_be_graded(self):
        spans = scoreable_spans(words(("a", 0.0, 1.0), ("b", 1.0, 2.0), ("c", 50.0, 51.0)),
                                min_words=1)
        summary = summarise(spans, duration=100.0)
        self.assertAlmostEqual(summary["scoreable_seconds"], 3.0)
        self.assertEqual(summary["words"], 3)
        self.assertAlmostEqual(summary["share_of_audio"], 0.03)

    def test_an_empty_alignment_is_reported_rather_than_dividing_by_zero(self):
        summary = summarise([], duration=100.0)
        self.assertEqual(summary["scoreable_seconds"], 0.0)
        self.assertEqual(summary["share_of_audio"], 0.0)


if __name__ == "__main__":
    unittest.main()
