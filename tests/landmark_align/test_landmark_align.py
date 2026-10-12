"""Landmarks: places where the transcript and a recogniser agree, used as fixed points in time.

The walking aligner carried every mistake forward. A window handed more text than its audio held
crammed words minutes early, and text that was never said pushed every later word late, window
after window, because a walk that only moves forward cannot take time back: a darshan drifted
from 16 to 221 seconds late. Cutting the recording at landmarks makes each stretch between two
of them an alignment of its own, so no mistake can cross a landmark.

These tests never load a model. Like the forced-alignment tests, they hand the aligner audio
scores whose right answer is obvious, at one second per frame so the arithmetic reads plainly.
"""

import unittest

from scripts.forced_align import problems
from scripts.landmark_align import Landmark, Segment, align_segments, landmarks, segments

from tests.forced_align.test_spans import posteriors


def heard(*triples):
    return [{"w": w, "s": s, "e": e} for w, s, e in triples]


class LandmarkTests(unittest.TestCase):
    def test_a_run_both_agree_on_becomes_a_landmark(self):
        words = "so hare krsna hare rama is the name".split()
        h = heard(("so", 0.0, 0.2), ("hare", 0.3, 0.5), ("krsna", 0.6, 0.9), ("hare", 1.0, 1.2),
                  ("rama", 1.3, 1.6), ("is", 1.7, 1.8), ("the", 1.9, 2.0), ("name", 2.1, 2.4))
        [mark] = landmarks(words, h, min_run=4)
        self.assertEqual((mark.first, mark.last, mark.start, mark.end), (0, 7, 0.0, 2.4))

    def test_a_run_shorter_than_the_minimum_is_not_believed(self):
        # `ei` was once paired with another occurrence 25 s away. A word or two is not evidence.
        self.assertEqual(landmarks(["ei", "x", "y"], heard(("ei", 1.0, 1.2), ("z", 2.0, 2.2)),
                                   min_run=4), [])

    def test_a_disagreement_splits_the_landmarks(self):
        words = "a b c d X e f g h".split()
        h = heard(*[(w, float(i), i + 0.5) for i, w in enumerate("a b c d Y Z e f g h".split())])
        marks = landmarks(words, h, min_run=4)
        self.assertEqual([(m.first, m.last) for m in marks], [(0, 3), (5, 8)])
        self.assertEqual(marks[1].start, 6.0)

    def test_a_landmark_never_starts_inside_a_word(self):
        # "Vedānta-sūtras," folds to two tokens. A run that begins at its second token would date
        # the whole word by half of it, so the run starts at the next whole word instead.
        words = ["Vedānta-sūtras,", "are", "the", "last", "word"]
        h = heard(("sutras", 0.0, 0.4), ("are", 0.5, 0.6), ("the", 0.7, 0.8),
                  ("last", 0.9, 1.1), ("word", 1.2, 1.5))
        [mark] = landmarks(words, h, min_run=4)
        self.assertEqual((mark.first, mark.start), (1, 0.5))

    def test_the_cut_falls_in_the_pause_before_a_landmark(self):
        words = "x a b c d".split()
        h = heard(("y", 0.0, 1.0), ("a", 2.0, 2.2), ("b", 2.3, 2.5), ("c", 2.6, 2.8),
                  ("d", 2.9, 3.1))
        [mark] = landmarks(words, h, min_run=4)
        self.assertEqual(mark.cut, 1.5)


class SegmentTests(unittest.TestCase):
    def test_every_word_is_in_one_segment_and_the_segments_tile_the_recording(self):
        marks = [Landmark(first=2, last=4, start=3.0, end=5.0, cut=2.8),
                 Landmark(first=7, last=9, start=10.0, end=12.0, cut=9.5)]
        self.assertEqual(segments(marks, n_words=12, duration=20.0),
                         [Segment(0, 2, 0.0, 2.8), Segment(2, 7, 2.8, 9.5),
                          Segment(7, 12, 9.5, 20.0)])

    def test_without_landmarks_the_whole_lecture_is_one_segment(self):
        self.assertEqual(segments([], n_words=5, duration=10.0), [Segment(0, 5, 0.0, 10.0)])

    def test_a_landmark_at_the_very_start_leaves_no_empty_segment(self):
        marks = [Landmark(first=0, last=3, start=0.0, end=2.0, cut=0.0)]
        self.assertEqual(segments(marks, n_words=6, duration=8.0), [Segment(0, 6, 0.0, 8.0)])


class AlignmentTests(unittest.TestCase):
    """Each segment is aligned as [skip] + its words + [skip]. Forced alignment gives every
    symbol at least one frame, so a skip costs one frame - 20 ms in real audio, a whole second
    here - and the made-up audio below leaves a pause ('-') where each one sits."""

    def test_speech_the_transcript_leaves_out_does_not_drag_the_words(self):
        # "ab", then ten frames of speech nobody wrote down, then "cd".
        frames = "-ab" + "q" * 10 + "-cd-"
        marks = [Landmark(first=1, last=1, start=14.0, end=16.0, cut=13.0)]
        placed, _ = align_segments(posteriors(frames), 1.0, ["ab", "cd"],
                                   segments(marks, n_words=2, duration=17.0))
        self.assertEqual([(s.word, s.start, s.end) for s in placed],
                         [("ab", 1.0, 3.0), ("cd", 14.0, 16.0)])

    def test_text_never_said_cannot_push_the_words_after_a_landmark(self):
        # "zyx" is written but was never said. The walking aligner spent the next words' audio
        # on it and every later word fell late; here it must stay inside its own segment.
        frames = "-ab-----" + "-cdef-"
        marks = [Landmark(first=2, last=3, start=9.0, end=13.0, cut=8.0)]
        placed, _ = align_segments(posteriors(frames), 1.0, ["ab", "zyx", "cd", "ef"],
                                   segments(marks, n_words=4, duration=14.0))
        timed = {s.word: (s.start, s.end) for s in placed}
        self.assertEqual(timed["cd"], (9.0, 11.0))
        self.assertEqual(timed["ef"], (11.0, 13.0))

    def test_words_are_numbered_on_the_whole_transcript(self):
        frames = "-ab--cdef-"
        marks = [Landmark(first=1, last=2, start=5.0, end=9.0, cut=4.0)]
        placed, _ = align_segments(posteriors(frames), 1.0, ["ab", "cd", "ef"],
                                   segments(marks, n_words=3, duration=10.0))
        self.assertEqual([s.index for s in placed], [0, 1, 2])

    def test_a_segment_too_short_for_its_words_is_reported_not_faked(self):
        frames = "-a-" + "-cd-"
        marks = [Landmark(first=1, last=1, start=4.0, end=6.0, cut=3.0)]
        placed, steps = align_segments(posteriors(frames), 1.0, ["abcdefgh", "cd"],
                                       segments(marks, n_words=2, duration=7.0))
        self.assertEqual([s.word for s in placed], ["cd"])
        self.assertTrue(any(step.get("why") for step in steps))

    def test_the_result_passes_the_timing_checks(self):
        frames = "-ab" + "q" * 4 + "-cdef" + "q" * 3 + "-gh-"
        words = ["ab", "cd", "ef", "gh"]
        marks = [Landmark(first=1, last=2, start=8.0, end=12.0, cut=7.0),
                 Landmark(first=3, last=3, start=16.0, end=18.0, cut=15.0)]
        placed, _ = align_segments(posteriors(frames), 1.0, words,
                                   segments(marks, n_words=4, duration=19.0))
        self.assertEqual(problems(placed, duration=19.0), [])
        self.assertEqual(len(placed), 4)


if __name__ == "__main__":
    unittest.main()
