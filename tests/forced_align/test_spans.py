"""From frame-level posteriors to the word spans a read-along page highlights.

These tests never load a model. They hand the aligner posteriors whose right answer is
obvious by construction, because the point is to prove our wiring - target order, span
recovery, frame-to-second conversion, chunk stitching - and not to re-test torchaudio's
Viterbi in C++.
"""

import unittest

import torch

from scripts.forced_align import DICTIONARY, align, stitch, to_seconds


def posteriors(frames: str, confidence: float = 0.9) -> torch.Tensor:
    """Log-probabilities that clearly say one symbol per frame. '-' means blank."""
    rest = (1.0 - confidence) / (len(DICTIONARY) - 1)
    probs = torch.full((len(frames), len(DICTIONARY)), rest)
    for t, ch in enumerate(frames):
        probs[t, DICTIONARY[ch]] = confidence
    return probs.log()


class AlignmentTests(unittest.TestCase):
    def test_a_word_is_placed_where_its_letters_were_said(self):
        spans = align(posteriors("--aabb--"), ["ab"])
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].word, "ab")
        self.assertEqual((spans[0].start, spans[0].end), (2, 6))

    def test_two_words_come_back_in_order_and_do_not_overlap(self):
        spans = align(posteriors("aa-bb-cc"), ["aa", "b", "cc"])
        self.assertEqual([s.word for s in spans], ["aa", "b", "cc"])
        for earlier, later in zip(spans, spans[1:]):
            self.assertLessEqual(earlier.end, later.start)

    def test_every_word_that_could_be_tokenised_gets_exactly_one_span(self):
        # CTC forced alignment emits each target once, so a missing span means our mapping
        # dropped it, not that the audio lacked it.
        words = ["hare", "krsna", "hare", "rama"]
        spans = align(posteriors("hare-krsna-hare-rama"), words)
        self.assertEqual(len(spans), len(words))
        self.assertEqual([s.index for s in spans], [0, 1, 2, 3])

    def test_a_word_with_no_alignable_letters_gets_no_span_and_is_not_faked(self):
        spans = align(posteriors("ab-cd"), ["ab", "12.10.2", "cd"])
        self.assertEqual([s.index for s in spans], [0, 2])

    def test_a_span_carries_a_score_between_zero_and_one(self):
        spans = align(posteriors("aabb", confidence=0.95), ["ab"])
        self.assertGreater(spans[0].score, 0.9)
        self.assertLessEqual(spans[0].score, 1.0)

    def test_an_unconfident_alignment_scores_lower_than_a_confident_one(self):
        sure = align(posteriors("aabb", confidence=0.99), ["ab"])[0]
        unsure = align(posteriors("aabb", confidence=0.20), ["ab"])[0]
        self.assertGreater(sure.score, unsure.score)

    def test_nothing_to_align_is_not_an_error(self):
        self.assertEqual(align(posteriors("---"), []), [])
        self.assertEqual(align(posteriors("---"), ["12.10.2"]), [])


class SecondsTests(unittest.TestCase):
    def test_frames_become_seconds_at_the_models_frame_rate(self):
        spans = to_seconds(align(posteriors("--aabb--"), ["ab"]), seconds_per_frame=0.02)
        self.assertAlmostEqual(spans[0].start, 0.04)
        self.assertAlmostEqual(spans[0].end, 0.12)

    def test_a_chunks_offset_is_added_so_spans_are_absolute(self):
        spans = to_seconds(align(posteriors("--aabb--"), ["ab"]),
                           seconds_per_frame=0.02, offset=600.0)
        self.assertAlmostEqual(spans[0].start, 600.04)


class StitchingTests(unittest.TestCase):
    """A seventy-minute lecture cannot be aligned in one forward pass, so it is aligned in
    chunks. Stitching is where drift would enter, and drift is invisible until someone reads
    along and finds the highlight a second behind the voice."""

    def test_stitched_chunks_keep_one_span_per_word_in_order(self):
        first = to_seconds(align(posteriors("ab-cd"), ["ab", "cd"]), 0.02, offset=0.0)
        second = to_seconds(align(posteriors("ef-gh"), ["ef", "gh"]), 0.02, offset=10.0)
        joined = stitch([(first, 0), (second, 2)])
        self.assertEqual([s.index for s in joined], [0, 1, 2, 3])
        self.assertEqual([s.word for s in joined], ["ab", "cd", "ef", "gh"])

    def test_stitching_makes_word_indices_absolute_across_chunks(self):
        second = to_seconds(align(posteriors("ef-gh"), ["ef", "gh"]), 0.02, offset=10.0)
        joined = stitch([(second, 40)])
        self.assertEqual([s.index for s in joined], [40, 41])

    def test_time_never_runs_backwards_across_a_chunk_boundary(self):
        first = to_seconds(align(posteriors("ab-cd"), ["ab", "cd"]), 0.02, offset=0.0)
        second = to_seconds(align(posteriors("ef-gh"), ["ef", "gh"]), 0.02, offset=10.0)
        joined = stitch([(first, 0), (second, 2)])
        for earlier, later in zip(joined, joined[1:]):
            self.assertLessEqual(earlier.start, later.start)

    def test_a_chunk_that_aligned_nothing_does_not_break_the_sequence(self):
        first = to_seconds(align(posteriors("ab-cd"), ["ab", "cd"]), 0.02, offset=0.0)
        joined = stitch([(first, 0), ([], 2)])
        self.assertEqual([s.index for s in joined], [0, 1])


class TooLittleAudioTests(unittest.TestCase):
    """CTC needs a frame per letter, plus one more for every doubled letter to hold the blank
    that keeps the pair apart. A chunk cut by time but filled by word count can violate that,
    and the failure arrives from C++ naming neither the chunk nor the text."""

    def test_a_chunk_with_fewer_frames_than_letters_says_so_in_our_own_words(self):
        with self.assertRaises(ValueError) as raised:
            align(posteriors("ab"), ["abcdef"])
        self.assertIn("6", str(raised.exception))
        self.assertIn("2", str(raised.exception))

    def test_doubled_letters_are_counted_in_what_the_audio_must_afford(self):
        # "aa" needs three frames, not two: a, blank, a.
        with self.assertRaises(ValueError):
            align(posteriors("aa"), ["aa"])
        self.assertEqual(len(align(posteriors("a-a"), ["aa"])), 1)


if __name__ == "__main__":
    unittest.main()
