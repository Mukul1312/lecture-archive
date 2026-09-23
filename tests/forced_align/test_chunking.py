"""Cutting audio the encoder cannot swallow whole, without moving anything.

A cue is a few seconds and aligns in one pass. A lecture is seventy minutes, and two separate
ceilings bite: wav2vec2's self-attention is quadratic in frames, so the encoder cannot see more
than about half a minute at once, and the Viterbi backtrack matrix is frames x letters, which
at full length runs to tens of gigabytes.

The encoder ceiling is the tractable one, because the fix does not move any word: score the
audio in overlapping windows, throw away the frames near each seam where the model was missing
context, and concatenate. Getting the arithmetic wrong there would drop or duplicate frames,
which shifts every later word by a little and is invisible until someone reads along.
"""

import unittest

from scripts.forced_align import plan_chunks

RATE = 16_000


class ChunkPlanTests(unittest.TestCase):
    def test_audio_that_already_fits_is_left_in_one_piece(self):
        plan = plan_chunks(20 * RATE, window=30.0, overlap=2.0)
        self.assertEqual(len(plan), 1)
        self.assertEqual((plan[0].start, plan[0].end), (0, 20 * RATE))

    def test_a_long_recording_is_cut_into_several(self):
        self.assertGreater(len(plan_chunks(300 * RATE, window=30.0, overlap=2.0)), 8)

    def test_the_pieces_cover_the_whole_recording_and_nothing_beyond_it(self):
        samples = 300 * RATE
        plan = plan_chunks(samples, window=30.0, overlap=2.0)
        self.assertEqual(plan[0].start, 0)
        self.assertEqual(plan[-1].end, samples)
        for piece in plan:
            self.assertLessEqual(piece.end, samples)

    def test_neighbours_overlap_so_no_frame_is_scored_without_context(self):
        plan = plan_chunks(300 * RATE, window=30.0, overlap=2.0)
        for earlier, later in zip(plan, plan[1:]):
            self.assertLess(later.start, earlier.end, "a seam with no overlap loses context")

    def test_the_kept_regions_tile_the_recording_exactly_once(self):
        # This is the property that matters: overlap exists to be thrown away, and what
        # survives must join edge to edge - no gap, no repetition.
        samples = 300 * RATE
        plan = plan_chunks(samples, window=30.0, overlap=2.0)
        self.assertEqual(plan[0].keep_from, 0)
        self.assertEqual(plan[-1].keep_to, samples)
        for earlier, later in zip(plan, plan[1:]):
            self.assertEqual(earlier.keep_to, later.keep_from)

    def test_what_is_kept_is_always_inside_what_was_scored(self):
        for piece in plan_chunks(300 * RATE, window=30.0, overlap=2.0):
            self.assertGreaterEqual(piece.keep_from, piece.start)
            self.assertLessEqual(piece.keep_to, piece.end)

    def test_a_seam_is_trimmed_on_both_sides_not_one(self):
        plan = plan_chunks(300 * RATE, window=30.0, overlap=2.0)
        self.assertGreater(plan[1].keep_from, plan[1].start, "no left trim at an inner seam")
        self.assertLess(plan[1].keep_to, plan[1].end, "no right trim at an inner seam")

    def test_the_outer_edges_are_not_trimmed_because_nothing_precedes_or_follows(self):
        plan = plan_chunks(300 * RATE, window=30.0, overlap=2.0)
        self.assertEqual(plan[0].keep_from, plan[0].start)
        self.assertEqual(plan[-1].keep_to, plan[-1].end)

    def test_a_recording_a_hair_longer_than_one_window_does_not_make_a_sliver(self):
        # A final chunk of a few samples would be scored without usable context and is a
        # classic source of a duplicated or dropped frame at the very end.
        for extra in (1, 100, RATE // 2):
            plan = plan_chunks(30 * RATE + extra, window=30.0, overlap=2.0)
            for piece in plan:
                self.assertGreater(piece.end - piece.start, RATE,
                                   f"a sliver chunk appeared for {extra} extra samples")

    def test_an_empty_recording_has_nothing_to_plan(self):
        self.assertEqual(plan_chunks(0, window=30.0, overlap=2.0), [])


if __name__ == "__main__":
    unittest.main()
