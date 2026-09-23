"""Joining the windows back into one score for the whole recording.

The encoder cannot see more than about half a minute at once, so long audio is scored in
overlapping windows and the frames near each seam are discarded in favour of the neighbour's.
What must survive that is simple and easy to get wrong: every moment of audio represented
exactly once, and a frame duration that still means what it says.

A stand-in for the acoustic model keeps these tests honest and instant - the arithmetic is
ours, the weights are not.
"""

import unittest

import torch

from scripts.forced_align import DICTIONARY, SAMPLE_RATE, emissions_long

FRAME = 320  # wav2vec2 advances one frame per 320 samples, so 50 a second at 16 kHz


def fake_scores(waveform: torch.Tensor):
    """Log-probabilities that encode each frame's position, so misplacement is visible."""
    frames = max(1, waveform.size(0) // FRAME)
    scores = torch.zeros(1, frames, len(DICTIONARY))
    scores[0, :, 0] = torch.arange(frames, dtype=torch.float)
    return scores, FRAME / SAMPLE_RATE


class LongAudioTests(unittest.TestCase):
    def test_short_audio_is_scored_in_one_window(self):
        audio = torch.zeros(20 * SAMPLE_RATE)
        joined, _ = emissions_long(audio, score=fake_scores)
        self.assertEqual(joined.size(1), 20 * SAMPLE_RATE // FRAME)

    def test_long_audio_keeps_about_one_frame_per_hop(self):
        # Seams cost a frame here and there to rounding; what must not happen is a window's
        # worth going missing or being counted twice.
        audio = torch.zeros(300 * SAMPLE_RATE)
        joined, _ = emissions_long(audio, window=30.0, overlap=2.0, score=fake_scores)
        expected = 300 * SAMPLE_RATE // FRAME
        self.assertAlmostEqual(joined.size(1), expected, delta=len(str(expected)) + 12)

    def test_the_frame_duration_is_measured_from_what_survived(self):
        audio = torch.zeros(300 * SAMPLE_RATE)
        joined, seconds_per_frame = emissions_long(audio, score=fake_scores)
        self.assertAlmostEqual(joined.size(1) * seconds_per_frame, 300.0, places=4)

    def test_a_windows_own_frames_stay_in_order(self):
        audio = torch.zeros(300 * SAMPLE_RATE)
        joined, _ = emissions_long(audio, window=30.0, overlap=2.0, score=fake_scores)
        counter = joined[0, :, 0]
        # Within a window the stand-in counts upward; across a seam it restarts. Neither
        # should ever be a repeated value sitting next to itself, which is what a duplicated
        # frame would look like.
        self.assertTrue(bool((counter[1:] != counter[:-1]).all()))

    def test_nothing_to_score_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            emissions_long(torch.zeros(0), score=fake_scores)


if __name__ == "__main__":
    unittest.main()
