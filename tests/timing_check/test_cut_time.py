"""Putting four systems' timestamps back on the recording's own clock.

The bake-off did not decode the lecture. It decoded a *cut* of it: 66.4 minutes in eleven
pieces, with 3.4 minutes of never-subtitled speech removed so that a system without word
timestamps could still be scored fairly. Every timestamp those systems emitted is therefore on
a spliced clock that skips 205.6 seconds in ten places.

Comparing them with a forced aligner means putting them back. An error here does not look like
an error - it looks like the aligner disagreeing with four independent systems, which is
exactly the conclusion one would wrongly draw.
"""

import unittest

from scripts.timing_check import CutMap

# The real piece list, from data/reference/melbourne-cut.json.
KEEP = [[650.0, 655.8], [681.5, 716.3], [753.9, 1062.6], [1073.4, 1511.8], [1521.3, 2774.2],
        [2814.3, 2877.3], [2885.3, 3550.2], [3569.5, 4439.4], [4469.2, 4531.9],
        [4543.4, 4763.8], [4777.1, 4840.0]]


class CutMapTests(unittest.TestCase):
    def setUp(self):
        self.cut = CutMap(KEEP)

    def test_the_first_piece_starts_where_the_recording_does(self):
        self.assertAlmostEqual(self.cut.to_original(0.0), 650.0)

    def test_time_inside_a_piece_moves_by_that_pieces_offset(self):
        self.assertAlmostEqual(self.cut.to_original(3.0), 653.0)

    def test_a_splice_skips_the_removed_audio(self):
        # The first piece is 5.8s long, so cut-time 5.8 is the instant the second piece begins
        # - at 681.5 in the recording, not at 655.8.
        self.assertAlmostEqual(self.cut.to_original(5.8), 681.5)
        self.assertAlmostEqual(self.cut.to_original(5.9), 681.6)

    def test_the_total_length_is_the_kept_audio_and_not_the_recording(self):
        self.assertAlmostEqual(self.cut.duration, 3984.4, places=1)

    def test_the_last_instant_maps_to_the_end_of_the_recording(self):
        self.assertAlmostEqual(self.cut.to_original(self.cut.duration), 4840.0)

    def test_every_piece_boundary_lands_on_its_own_start(self):
        at = 0.0
        for start, end in KEEP:
            self.assertAlmostEqual(self.cut.to_original(at), start,
                                   msg=f"piece starting at {start} is misplaced")
            at += end - start

    def test_mapping_never_runs_backwards(self):
        previous = -1.0
        for step in range(0, int(self.cut.duration), 37):
            now = self.cut.to_original(step)
            self.assertGreater(now, previous)
            previous = now

    def test_a_timestamp_past_the_end_is_clamped_rather_than_extrapolated(self):
        # Recognisers occasionally emit an end time a shade past the audio. Extrapolating that
        # into the removed region would invent a time that was never in the cut.
        self.assertAlmostEqual(self.cut.to_original(self.cut.duration + 5.0), 4840.0)

    def test_a_negative_timestamp_is_clamped_to_the_start(self):
        self.assertAlmostEqual(self.cut.to_original(-2.0), 650.0)

    def test_removed_audio_is_never_the_answer(self):
        # 655.8 to 681.5 was cut out. No cut-time may map into it.
        for step in range(0, int(self.cut.duration)):
            self.assertFalse(655.8 < self.cut.to_original(step) < 681.5)


if __name__ == "__main__":
    unittest.main()
