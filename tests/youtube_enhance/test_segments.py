import unittest

import numpy as np

from scripts.youtube_enhance.models import Segment, SegmentLabel
from scripts.youtube_enhance.segments import (
    build_guarded_pause_mask,
    build_speech_mask,
    segments_from_json,
    validate_segment_map,
)


class SegmentTests(unittest.TestCase):
    def test_rejects_gap_overlap_and_unreviewed_map(self):
        gap = [
            Segment(0, 100, SegmentLabel.MAIN_SPEECH, True),
            Segment(101, 200, SegmentLabel.UNCERTAIN, True),
        ]
        with self.assertRaises(ValueError):
            validate_segment_map(gap, 200, require_reviewed=True)
        unreviewed = [Segment(0, 200, SegmentLabel.MAIN_SPEECH, False)]
        with self.assertRaises(ValueError):
            validate_segment_map(unreviewed, 200, require_reviewed=True)

    def test_uncertain_and_non_speech_never_receive_speech_enhancement(self):
        segments = [
            Segment(0, 100, SegmentLabel.UNCERTAIN, True),
            Segment(100, 200, SegmentLabel.CHANTING_OR_MUSIC, True),
            Segment(200, 400, SegmentLabel.MAIN_SPEECH, True),
            Segment(400, 500, SegmentLabel.APPLAUSE_OR_CROWD, True),
        ]
        mask = build_speech_mask(segments, 500, fade_samples=20)
        self.assertEqual(len(mask), 500)
        self.assertTrue(np.all(mask[:200] == 0))
        self.assertTrue(np.all(mask[400:] == 0))
        self.assertGreater(float(mask[250]), 0.99)

    def test_fades_stay_inside_main_speech(self):
        segments = [
            Segment(0, 100, SegmentLabel.UNCERTAIN, True),
            Segment(100, 300, SegmentLabel.MAIN_SPEECH, True),
            Segment(300, 400, SegmentLabel.UNCERTAIN, True),
        ]
        mask = build_speech_mask(segments, 400, fade_samples=40)
        self.assertTrue(np.all(mask[:100] == 0))
        self.assertTrue(np.all(mask[300:] == 0))
        self.assertEqual(mask[100], 0)
        self.assertLess(mask[299], 0.1)

    def test_pause_guard_and_fade_do_not_leak_outside_reviewed_pause(self):
        segments = [
            Segment(0, 100, SegmentLabel.MAIN_SPEECH, True),
            Segment(100, 500, SegmentLabel.GUARDED_PAUSE, True),
            Segment(500, 600, SegmentLabel.MAIN_SPEECH, True),
        ]
        mask = build_guarded_pause_mask(
            segments, 600, guard_samples=100, fade_samples=40
        )
        self.assertTrue(np.all(mask[:200] == 0))
        self.assertTrue(np.all(mask[400:] == 0))
        self.assertGreater(mask[300], 0.99)

    def test_rejects_negative_fade_for_both_masks(self):
        segments = [Segment(0, 100, SegmentLabel.MAIN_SPEECH, True)]
        with self.assertRaises(ValueError):
            build_speech_mask(segments, 100, fade_samples=-1)
        pause_segments = [Segment(0, 100, SegmentLabel.GUARDED_PAUSE, True)]
        with self.assertRaises(ValueError):
            build_guarded_pause_mask(
                pause_segments, 100, guard_samples=0, fade_samples=-1
            )

    def test_rejects_negative_guard(self):
        segments = [Segment(0, 100, SegmentLabel.GUARDED_PAUSE, True)]
        with self.assertRaises(ValueError):
            build_guarded_pause_mask(segments, 100, guard_samples=-1, fade_samples=0)

    def test_rejects_fractional_or_boolean_sample_coordinates(self):
        # Each fixture is numerically contiguous and complete, so legacy
        # equality-based validation would accept it; only the types are invalid.
        invalid_maps = (
            ([Segment(0.0, 10.0, SegmentLabel.MAIN_SPEECH, True)], 10.0),
            ([Segment(False, True, SegmentLabel.MAIN_SPEECH, True)], 1),
            ([Segment(0, 10, SegmentLabel.MAIN_SPEECH, True)], 10.0),
        )
        for segments, total_samples in invalid_maps:
            with self.subTest(segments=segments, total_samples=total_samples):
                with self.assertRaises(ValueError):
                    validate_segment_map(segments, total_samples, require_reviewed=True)

    def test_rejects_non_boolean_reviewed_json(self):
        with self.assertRaises(ValueError):
            segments_from_json(
                [
                    {
                        "start_sample": 0,
                        "end_sample": 100,
                        "label": SegmentLabel.MAIN_SPEECH.value,
                        "reviewed": "false",
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
