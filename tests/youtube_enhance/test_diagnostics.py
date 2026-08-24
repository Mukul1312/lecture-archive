import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from scripts.youtube_enhance.diagnostics import (
    FrameProposal,
    WindowFeature,
    _feature_from_report,
    _timeline_proposal,
    propose_segments,
    run_diagnostics,
    scan_stereo_blocks,
    select_representative_windows,
    transition_windows,
    write_original_review_material,
)
from scripts.youtube_enhance.models import SegmentLabel


class DiagnosticTests(unittest.TestCase):
    def test_stereo_scan_reports_integrity_and_side_energy(self):
        rate = 48000
        time = np.arange(rate, dtype=np.float32) / rate
        left = 0.20 * np.sin(2 * np.pi * 440 * time)
        right = 0.19 * np.sin(2 * np.pi * 440 * time)
        stereo = np.column_stack((left, right)).astype(np.float32)

        report = scan_stereo_blocks([stereo], rate)

        self.assertEqual(report["samples"], rate)
        self.assertIn("decoded_peak_dbfs", report)
        self.assertIn("true_peak_dbfs", report)
        self.assertIn("dc_offset", report)
        self.assertIn("longest_zero_run_samples", report)
        self.assertIn("flat_top_runs", report)
        self.assertGreater(report["left_right_correlation"], 0.99)
        self.assertLess(report["side_to_mid_db"], -20)

    def test_stereo_scan_counts_dropouts_across_block_boundaries(self):
        blocks = [
            np.array([[0.1, 0.1], [0.0, 0.0]], dtype=np.float32),
            np.array([[0.0, 0.0], [0.0, 0.0], [0.1, 0.1]], dtype=np.float32),
        ]

        report = scan_stereo_blocks(blocks, 48000)

        self.assertEqual(report["longest_zero_run_samples"], 3)

    def test_stereo_scan_counts_separated_and_trailing_dropouts_per_channel(self):
        blocks = [
            np.array([[0.0, 0.0], [0.0, 0.0], [0.1, 0.2], [0.0, 0.0]], dtype=np.float32),
            np.array([[0.0, 0.0], [0.0, 0.0]], dtype=np.float32),
        ]

        report = scan_stereo_blocks(blocks, 48000)

        self.assertEqual(report["dropout_runs"], 2)
        self.assertEqual(report["longest_zero_run_samples"], 3)
        self.assertEqual(report["per_channel_zero_run_counts"], [2, 2])
        self.assertEqual(report["per_channel_longest_zero_run_samples"], [3, 3])

    def test_stereo_scan_does_not_merge_alternating_channel_flat_tops(self):
        blocks = [
            np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
            np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        ]

        report = scan_stereo_blocks(blocks, 48000)

        self.assertEqual(report["flat_top_runs"], 0)
        self.assertEqual(report["per_channel_flat_top_runs"], [0, 0])
        self.assertEqual(report["per_channel_longest_flat_top_run_samples"], [1, 1])

    def test_window_selection_covers_measured_roles_without_relabeling_uncertain(self):
        rows = [
            WindowFeature("begin-clean", 100, "main_speech", -55, -18, 0.95, 0),
            WindowFeature("begin-noisy", 200, "main_speech", -35, -20, 0.95, 0),
            WindowFeature("middle-low", 500, "main_speech", -48, -32, 0.95, 1),
            WindowFeature("middle-pause", 600, "guarded_pause", -70, -65, 0.95, 1),
            WindowFeature("end-uncertain", 900, "uncertain", -42, -20, 0.40, 2),
            WindowFeature("end-speech", 950, "main_speech", -45, -19, 0.95, 2),
        ]

        selected = select_representative_windows(rows)

        roles = {item.role for item in selected}
        self.assertTrue(
            {"clean_speech", "noisy_speech", "low_energy_speech", "guarded_pause", "non_speech"}
            <= roles
        )
        self.assertEqual({item.timeline_third for item in selected}, {0, 1, 2})
        uncertain = next(item for item in selected if item.window_id == "end-uncertain")
        self.assertEqual(uncertain.label_hint, "uncertain")
        self.assertEqual(uncertain.role, "non_speech")

    def test_near_silence_feature_is_available_as_unreviewed_guarded_pause(self):
        feature = _feature_from_report(
            "near-silence", 100, 300,
            {"level": {"floor_db": -80.0, "speech_db": -70.0}},
        )

        selected = select_representative_windows([feature])

        self.assertEqual(feature.label_hint, "guarded_pause")
        self.assertEqual(selected[0].role, "guarded_pause")

    def test_proposed_segments_cover_timeline_and_keep_low_confidence_uncertain(self):
        proposals = [
            FrameProposal(20, 50, "main_speech", 0.95),
            FrameProposal(50, 80, "chanting_or_music", 1.0),
            FrameProposal(80, 100, "guarded_pause", 0.89),
        ]

        segments = propose_segments(proposals, 100)

        self.assertEqual(
            [(item.start_sample, item.end_sample, item.label) for item in segments],
            [
                (0, 20, SegmentLabel.UNCERTAIN),
                (20, 50, SegmentLabel.MAIN_SPEECH),
                (50, 100, SegmentLabel.UNCERTAIN),
            ],
        )

    def test_nonfinite_confidence_is_always_uncertain(self):
        proposals = [
            FrameProposal(0, 10, "main_speech", float("nan")),
            FrameProposal(10, 20, "main_speech", float("inf")),
            FrameProposal(20, 30, "guarded_pause", float("-inf")),
        ]

        segments = propose_segments(proposals, 30)

        self.assertEqual([(item.start_sample, item.end_sample, item.label) for item in segments], [
            (0, 30, SegmentLabel.UNCERTAIN),
        ])

    def test_active_synthetic_material_is_never_auto_labeled_main_speech(self):
        rate = 48000
        time = np.arange(rate, dtype=np.float32) / rate
        gate = np.concatenate((np.zeros(rate // 2, dtype=np.float32), np.ones(rate // 2, dtype=np.float32)))
        fixtures = {
            "gated_tone": 0.3 * np.sin(2 * np.pi * 440 * time) * gate,
            "chant_like_harmonics": gate * (0.20 * np.sin(2 * np.pi * 160 * time) + 0.10 * np.sin(2 * np.pi * 320 * time)),
            "crowd_noise": gate * np.random.default_rng(4).normal(0.0, 0.12, rate).astype(np.float32),
            "overlapping_sources": gate * (0.16 * np.sin(2 * np.pi * 300 * time) + 0.16 * np.sin(2 * np.pi * 710 * time)),
        }

        for name, values in fixtures.items():
            with self.subTest(name=name):
                proposal = _timeline_proposal(values.astype(np.float32), 0, rate)
                self.assertEqual(proposal.label_hint, "uncertain")

    def test_run_diagnostics_records_noise_evidence_without_inline_timeline_proposals(self):
        measured = {
            "integrity": {"dc_offset": 0.0},
            "level": {"floor_db": -60.0, "speech_db": -30.0, "floor_drift_db": 1.0},
            "tonal": [],
            "reverb": {"rt60_s": None},
            "bandwidth": {"rolloff95_khz": 4.0},
            "snr_by_band": [{"lo": 0, "hi": 60, "noise_db": -60.0, "speech_db": -30.0, "margin_db": 30.0}],
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stereo_path = root / "stereo.wav"
            mid_path = root / "mid.wav"
            output_path = root / "analysis" / "diagnostics.json"
            sf.write(stereo_path, np.zeros((8, 2), dtype=np.float32), 48000, subtype="FLOAT")
            sf.write(mid_path, np.zeros(8, dtype=np.float32), 48000, subtype="FLOAT")
            with patch("scripts.youtube_enhance.diagnostics._mid_window_report", return_value=measured), \
                 patch("scripts.youtube_enhance.diagnostics._whole_timeline_proposals", return_value=[FrameProposal(0, 8, "uncertain", 0.0)]), \
                 patch("scripts.youtube_enhance.diagnostics._loudness_measurement", return_value={"input_tp": "-1.0"}):
                report = run_diagnostics(stereo_path, mid_path, "ffmpeg", output_path)

        self.assertNotIn("timeline_proposals", report)
        self.assertEqual(len(report["noise_spectrum"]["per_window"]), 9)
        self.assertEqual(report["noise_spectrum"]["per_window"][0]["window_id"], "w00")
        self.assertEqual(report["noise_spectrum"]["aggregate"]["bands"][0]["mean_noise_db"], -60.0)

    def test_transition_windows_are_clamped_to_source_coordinates(self):
        segments = propose_segments(
            [FrameProposal(0, 10, "main_speech", 0.95)], 20
        )

        windows = transition_windows(segments, total_samples=20, radius_samples=8)

        self.assertEqual(
            windows,
            [{
                "boundary_sample": 10,
                "start_sample": 2,
                "end_sample": 18,
                "from": "main_speech",
                "to": "uncertain",
            }],
        )

    def test_original_review_material_is_stereo_coordinate_stable_and_non_clobbering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "decoded.wav"
            output = root / "review-original"
            samples = np.column_stack((np.arange(20), -np.arange(20))).astype(np.float32) / 20
            sf.write(source, samples, 48000, subtype="FLOAT")
            representatives = [
                WindowFeature("safe role", 4, "uncertain", -60, -40, 0.2, 0, "non_speech")
            ]
            transitions = [{"boundary_sample": 15, "start_sample": 12, "end_sample": 20,
                            "from": "main_speech", "to": "uncertain"}]

            result = write_original_review_material(
                source, representatives, transitions, output, window_samples=8
            )

            representative = output / "representative-safe-role.wav"
            values, rate = sf.read(representative, dtype="float32", always_2d=True)
            self.assertEqual(rate, 48000)
            self.assertEqual(values.shape, (8, 2))
            np.testing.assert_allclose(values, samples[4:12], atol=1e-7)
            self.assertEqual(result["representatives"][0]["start_sample"], 4)
            self.assertIn("representative-safe-role.wav", (output / "index.html").read_text("utf-8"))

            representative.write_bytes(b"mismatched")
            with self.assertRaises(FileExistsError):
                write_original_review_material(
                    source, representatives, transitions, output, window_samples=8
                )


if __name__ == "__main__":
    unittest.main()
