import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts.youtube_enhance.candidates import (
    blind_order,
    blend_mid,
    build_candidate_arrays,
    match_active_rms,
    write_candidate_artifacts,
    write_candidate_window,
    write_gallery,
)
from scripts.youtube_enhance.gates import gate_report
from scripts.youtube_enhance.source import from_mid_side


class CandidateTests(unittest.TestCase):
    def test_blind_order_is_stable_and_contains_every_candidate_once(self):
        first = blind_order("source-hash", ["original", "adaptive-22", "adaptive-24"])
        second = blind_order("source-hash", ["original", "adaptive-22", "adaptive-24"])
        self.assertEqual(first, second)
        self.assertEqual(set(first.values()), {"original", "adaptive-22", "adaptive-24"})
        self.assertEqual(set(first), {"A", "B", "C"})

    def test_zero_mask_returns_original_mid_and_stereo(self):
        original_mid = np.array([0.2, -0.1, 0.3], dtype=np.float32)
        enhanced_mid = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        side = np.array([0.01, -0.02, 0.03], dtype=np.float32)
        selected = blend_mid(original_mid, enhanced_mid, np.zeros(3, dtype=np.float32))
        np.testing.assert_array_equal(from_mid_side(selected, side), from_mid_side(original_mid, side))

    def test_zero_mask_preserves_signed_zero_and_ignores_nonfinite_enhancement(self):
        original = np.array([-0.0, 0.25, 0.0], dtype=np.float32)
        enhanced = np.array([np.nan, np.inf, -np.inf], dtype=np.float32)
        selected = blend_mid(original, enhanced, np.zeros(3, dtype=np.float32))
        np.testing.assert_array_equal(selected.view(np.uint32), original.view(np.uint32))

    def test_active_rms_matching_does_not_change_length(self):
        reference = np.array([0.0, 0.2, -0.2, 0.0], dtype=np.float32)
        candidate = reference * 0.5
        matched = match_active_rms(reference, candidate)
        self.assertEqual(len(matched), len(reference))
        self.assertAlmostEqual(float(np.max(np.abs(matched))), 0.2, places=5)

    def test_arrays_keep_raw_original_while_only_audition_is_loudness_matched(self):
        original_mid = np.array([0.2, -0.2, 0.1, -0.1], dtype=np.float32)
        side = np.array([0.02, -0.02, 0.01, -0.01], dtype=np.float32)
        mask = np.ones(4, dtype=np.float32)
        raw, audition, mapping = build_candidate_arrays(
            "source", original_mid, side, mask, original_mid * 0.25, original_mid * 0.5
        )
        np.testing.assert_array_equal(raw["original"], from_mid_side(original_mid, side))
        adaptive_code = next(code for code, value in mapping.items() if value == "adaptive-22")
        self.assertFalse(np.array_equal(audition[adaptive_code], raw["adaptive-22"]))
        self.assertEqual(audition[adaptive_code].shape, raw["adaptive-22"].shape)

    def test_candidate_window_is_immutable_but_can_reuse_equivalent_existing_files(self):
        audition = {
            "A": np.zeros((4, 2), dtype=np.float32),
            "B": np.full((4, 2), 0.1, dtype=np.float32),
            "C": np.full((4, 2), -0.1, dtype=np.float32),
        }
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "window-001"
            write_candidate_window(directory, audition, 48000, trusted_root=Path(folder))
            before = {path.name: path.read_bytes() for path in directory.iterdir()}
            write_candidate_window(directory, audition, 48000, trusted_root=Path(folder))
            self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})
            mismatched = dict(audition)
            mismatched["B"] = np.full((4, 2), 0.2, dtype=np.float32)
            with self.assertRaises(FileExistsError):
                write_candidate_window(directory, mismatched, 48000, trusted_root=Path(folder))

    def test_gallery_uses_blind_codes_and_transition_roles_without_identities(self):
        with tempfile.TemporaryDirectory() as folder:
            gallery = Path(folder) / "index.html"
            write_gallery(gallery, ["speech-001"], transition_window_ids=["transition-001"])
            text = gallery.read_text(encoding="utf-8")
        self.assertIn("speech-001/A.wav", text)
        self.assertIn("transition-001/A.wav", text)
        self.assertNotIn("adaptive-22", text)
        self.assertNotIn("original", text)

    def test_candidate_window_rejects_a_traversal_directory(self):
        audition = {
            code: np.zeros((4, 2), dtype=np.float32)
            for code in ("A", "B", "C")
        }
        with tempfile.TemporaryDirectory() as folder:
            traversal = Path(folder) / "candidate" / ".." / "escape"
            with self.assertRaises(ValueError):
                write_candidate_window(traversal, audition, 48000, trusted_root=Path(folder))

    def test_candidate_artifacts_reject_nested_identity_leaks_from_public_report(self):
        report = _report("fingerprint-a")
        report["metrics"]["A"]["adversarial"] = {"candidate_id": "adaptive-22"}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                write_candidate_artifacts(
                    Path(folder), "source", report["blind_map"], report, ["speech-001"],
                    audition_by_window=_audition_windows("speech-001"), sample_rate=48000,
                )

    def test_candidate_artifacts_reject_embedded_identity_tokens_in_public_text_and_keys(self):
        report = _report("fingerprint-a")
        report["metrics"]["A"]["note"] = "looks like ADAPTIVE-24 material"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                write_candidate_artifacts(Path(folder), "source", report["blind_map"], report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)
        report = _report("fingerprint-a")
        report["metrics"]["A"]["original_label"] = "safe"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                write_candidate_artifacts(Path(folder), "source", report["blind_map"], report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)

    def test_candidate_artifact_set_is_complete_or_refused_and_public_is_blind_only(self):
        report = _report("fingerprint-a")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "work"
            report_hash = write_candidate_artifacts(
                root, "source", report["blind_map"], report, ["speech-001"],
                audition_by_window=_audition_windows("speech-001"), sample_rate=48000,
            )
            self.assertEqual(report_hash, report["report_sha256"])
            public = json.loads((root / "candidates" / "candidate-report.json").read_text())
            self.assertEqual(set(public["metrics"]), {"A", "B", "C"})
            self.assertNotIn("blind_map", public)
            self.assertTrue((root / "candidates" / "completion.json").exists())
            write_candidate_artifacts(root, "source", report["blind_map"], report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)
            (root / "candidates" / "index.html").unlink()
            with self.assertRaises(FileExistsError):
                write_candidate_artifacts(root, "source", report["blind_map"], report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)

    def test_candidate_artifacts_commit_map_and_every_referenced_audio_file(self):
        report = _report("fingerprint-a")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "work"
            write_candidate_artifacts(root, "source", report["blind_map"], report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)
            completion = json.loads((root / "candidates" / "completion.json").read_text())
            self.assertEqual(completion["blind_map_sha256"], report["blind_map_sha256"])
            self.assertEqual(set(completion["artifacts"]), {"candidate-map.private.json", "candidates/candidate-report.json", "candidates/index.html", "candidates/speech-001/A.wav", "candidates/speech-001/B.wav", "candidates/speech-001/C.wav"})
            swapped = dict(report["blind_map"])
            swapped["A"], swapped["B"] = swapped["B"], swapped["A"]
            with self.assertRaises(ValueError):
                write_candidate_artifacts(root, "source", swapped, report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)

    def test_candidate_window_rejects_symlink_escape_from_trusted_root(self):
        audition = {code: np.zeros((4, 2), dtype=np.float32) for code in ("A", "B", "C")}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "root"
            outside = Path(folder) / "outside"
            root.mkdir()
            outside.mkdir()
            link = root / "link"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaises(ValueError):
                write_candidate_window(link / "window", audition, 48000, trusted_root=root)

    def test_candidate_window_rejects_leaf_symlink_before_audio_read(self):
        audition = {code: np.zeros((4, 2), dtype=np.float32) for code in ("A", "B", "C")}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / "window"
            write_candidate_window(directory, audition, 48000, trusted_root=root)
            with patch("scripts.youtube_enhance.candidates.Path.is_symlink", lambda path: path.name == "A.wav"), patch("scripts.youtube_enhance.candidates.sf.info", side_effect=AssertionError("audio was read")):
                with self.assertRaises(ValueError):
                    write_candidate_window(directory, audition, 48000, trusted_root=root)

    def test_candidate_window_checks_logical_symlink_leaf_before_reuse_read(self):
        audition = {code: np.zeros((4, 2), dtype=np.float32) for code in ("A", "B", "C")}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / "window"
            write_candidate_window(directory, audition, 48000, trusted_root=root)
            logical_a = directory / "A.wav"
            original = __import__("scripts.youtube_enhance.candidates", fromlist=["_safe_destination"])._safe_destination
            def resolve_a_else_normally(trusted_root, path):
                if Path(path) == logical_a:
                    return root / "resolved-looking-A.wav"
                return original(trusted_root, path)
            with patch("scripts.youtube_enhance.candidates._safe_destination", side_effect=resolve_a_else_normally), patch("scripts.youtube_enhance.candidates.Path.is_symlink", lambda path: path == logical_a), patch("scripts.youtube_enhance.candidates._same_audio_content", side_effect=AssertionError("reuse audio was read")):
                with self.assertRaises(ValueError):
                    write_candidate_window(directory, audition, 48000, trusted_root=root)

    def test_artifact_preflight_failure_writes_nothing(self):
        report = _report("fingerprint-a")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "work"
            original = __import__("scripts.youtube_enhance.candidates", fromlist=["_safe_destination"])._safe_destination
            def fail_later(trusted_root, path):
                if Path(path).name == "candidate-report.json":
                    raise ValueError("injected safety failure")
                return original(trusted_root, path)
            with patch("scripts.youtube_enhance.candidates._safe_destination", side_effect=fail_later):
                with self.assertRaises(ValueError):
                    write_candidate_artifacts(root, "source", report["blind_map"], report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)
            self.assertFalse((root / "candidate-map.private.json").exists())

    def test_dangling_artifact_leaf_is_rejected_before_any_publication(self):
        report = _report("fingerprint-a")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "work"
            with patch("scripts.youtube_enhance.candidates.Path.is_symlink", lambda path: path.name == "candidate-report.json"), patch("scripts.youtube_enhance.candidates._write_immutable_bytes", side_effect=AssertionError("publication reached")):
                with self.assertRaises(ValueError):
                    write_candidate_artifacts(root, "source", report["blind_map"], report, ["speech-001"], audition_by_window=_audition_windows("speech-001"), sample_rate=48000)
            self.assertFalse(any(root.rglob("*") if root.exists() else []))

    def test_candidate_window_preflights_every_leaf_before_audio_write(self):
        audition = {code: np.zeros((4, 2), dtype=np.float32) for code in ("A", "B", "C")}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / "window"
            original = __import__("scripts.youtube_enhance.candidates", fromlist=["_safe_destination"])._safe_destination
            def fail_c_leaf(trusted_root, path):
                if Path(path).name == "C.wav":
                    raise ValueError("injected leaf containment failure")
                return original(trusted_root, path)
            with patch("scripts.youtube_enhance.candidates._safe_destination", side_effect=fail_c_leaf), patch("scripts.youtube_enhance.candidates._write_window_files", side_effect=AssertionError("audio write reached")):
                with self.assertRaises(ValueError):
                    write_candidate_window(directory, audition, 48000, trusted_root=root)
            self.assertFalse(directory.exists())


def _report(fingerprint):
    metrics = {
        "original": {"natural_anchor_mean": 0.9, "identity_mean": 0.9, "longest_new_zero_run_samples": 0, "sample_count_equal": True, "non_finite_samples": 0, "peak": 0.9},
        "adaptive-22": {"natural_anchor_mean": 0.9, "identity_mean": 0.9, "longest_new_zero_run_samples": 0, "sample_count_equal": True, "non_finite_samples": 0, "peak": 0.9},
        "adaptive-24": {"natural_anchor_mean": 0.9, "identity_mean": 0.9, "longest_new_zero_run_samples": 0, "sample_count_equal": True, "non_finite_samples": 0, "peak": 0.9},
    }
    return gate_report(
        {"A": "original", "B": "adaptive-22", "C": "adaptive-24"},
        metrics,
        48000,
        processing_fingerprint=fingerprint,
    )


def _audition_windows(*window_ids):
    return {
        window_id: {code: np.full((4, 2), index / 10, dtype=np.float32) for index, code in enumerate(("A", "B", "C"))}
        for window_id in window_ids
    }


if __name__ == "__main__":
    unittest.main()
