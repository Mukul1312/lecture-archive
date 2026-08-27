import tempfile
import unittest
import copy
import hashlib
import json
from pathlib import Path

from scripts.youtube_enhance.qa import (
    QaFailure,
    collect_qa_report,
    validate_delivery,
    publish_qa_pair,
)


class QaTests(unittest.TestCase):
    def valid_bound_report(self, root: Path):
        paths = {name: root / f"{name}.bin" for name in ("source", "adaptive", "master", "flac", "mp3")}
        for name, path in paths.items(): path.write_bytes(name.encode())
        return collect_qa_report(
            8, 8, {"frames": 8},
            {"frames":8,"sample_rate":48000,"channels":2,"bits_per_raw_sample":24,"codec_name":"flac","container_name":"flac"},
            {"decoded_frames":8,"sample_rate":48000,"channels":2,"bit_rate":192000,"codec_delay_padding_samples":0,"codec_name":"mp3","container_name":"mp3"},
            {"integrated_lufs":-16.0,"true_peak_dbtp":-1.6,"lra":3.0,"decode_ok":True},
            {"integrated_lufs":-16.0,"true_peak_dbtp":-1.6,"decode_ok":True},
            paths["flac"], paths["mp3"],
            {"non_finite_samples":0,"unexpected_zero_run_samples":0,"reference_flat_top_runs":0,"flat_top_runs":0,"reference_pinned_samples":0,"pinned_samples":0,"reference_flat_top_runs_by_block":[0],"flat_top_runs_by_block":[0],"reference_flat_top_boundary_runs":0,"flat_top_boundary_runs":0,"crest_db":1.0},
            [], [], expected_boundary_samples=[], expected_candidate_window_ids=[],
            source_path=paths["source"], adaptive_path=paths["adaptive"], delivery_master_path=paths["master"],
            listening_checklist_path=root / "listening-checklist.md")
    def passing(self):
        return {
            "source_samples": 131864451,
            "adaptive_samples": 131864451,
            "master_samples": 131864451,
            "flac_samples": 131864451,
            "mp3_samples": 131864500,
            "mp3_delay_padding_samples": 49,
            "sample_rate": 48000,
            "channels": 2,
            "flac_sample_rate": 48000,
            "mp3_sample_rate": 48000,
            "flac_channels": 2,
            "mp3_channels": 2,
            "flac_bits_per_raw_sample": 24,
            "flac_codec_name": "flac", "flac_container_name": "flac",
            "mp3_bitrate": 192000,
            "mp3_codec_name": "mp3", "mp3_container_name": "mp3",
            "flac_lufs": -16.1,
            "mp3_lufs": -16.0,
            "flac_true_peak_dbtp": -1.7,
            "mp3_true_peak_dbtp": -1.6,
            "non_finite_samples": 0,
            "unexpected_zero_run_samples": 0,
            "reference_flat_top_runs": 3,
            "flat_top_runs": 3,
            "reference_pinned_samples": 20,
            "pinned_samples": 20,
            "reference_flat_top_runs_by_block": [1, 2],
            "flat_top_runs_by_block": [1, 2],
            "reference_flat_top_boundary_runs": 1,
            "flat_top_boundary_runs": 1,
            "crest_db": 12.0,
            "lra": 3.0,
            "flac_decode_ok": True,
            "mp3_decode_ok": True,
            "decode_ok": True,
            "expected_boundary_samples": [],
            "boundary_scores": [],
            "expected_candidate_window_ids": [],
            "candidate_window_scores": [],
            "hashes": {
                "source_sha256": "a" * 64,
                "adaptive_sha256": "d" * 64,
                "delivery_master_sha256": "e" * 64,
                "flac_sha256": "b" * 64,
                "mp3_sha256": "c" * 64,
            },
            "artifact_paths": {"source": "source.wav", "adaptive": "adaptive.wav", "delivery_master": "master.wav", "flac": "delivery.flac", "mp3": "delivery.mp3"},
            "listening_checklist": {"status": "pending", "required_sections": [
                "candidate windows", "segment transitions", "chunk boundaries", "quiet consonants", "overlaps", "music and chanting", "applause and crowd", "beginning", "ending", "naturalness veto", "word-integrity veto"], "path": "listening-checklist.md", "sha256": "f" * 64,
                "veto_text": "Naturalness and word integrity veto delivery."},
        }

    def test_accepts_exact_source_adaptive_master_flac_and_verified_mp3_padding(self):
        validate_delivery(self.passing())

    def test_rejects_source_or_flac_sample_loss(self):
        for field in ("source_samples", "flac_samples"):
            with self.subTest(field=field):
                report = self.passing()
                report[field] -= 1
                with self.assertRaises(QaFailure):
                    validate_delivery(report)

    def test_rejects_mp3_count_without_matching_codec_delay_padding_evidence(self):
        report = self.passing()
        report["mp3_delay_padding_samples"] = 48
        with self.assertRaises(QaFailure):
            validate_delivery(report)

    def test_rejects_mp3_truncation_even_when_its_absolute_difference_is_small(self):
        report = self.passing()
        report["mp3_samples"] -= 49
        report["mp3_delay_padding_samples"] = 49
        with self.assertRaises(QaFailure):
            validate_delivery(report)

    def test_rejects_loudness_or_true_peak_violation(self):
        report = self.passing()
        report["mp3_true_peak_dbtp"] = -1.49
        with self.assertRaises(QaFailure):
            validate_delivery(report)

    def test_accepts_a_new_zero_run_at_fifty_ms(self):
        report = self.passing()
        report["unexpected_zero_run_samples"] = 2400
        try:
            validate_delivery(report)
        except QaFailure as error:
            self.fail(f"50 ms zero run was rejected: {error}")

    def test_rejects_a_new_zero_run_one_frame_over_fifty_ms(self):
        report = self.passing()
        report["unexpected_zero_run_samples"] = 2401
        with self.assertRaisesRegex(QaFailure, "dropout"):
            validate_delivery(report)

    def test_rejects_nonfinite_samples_even_without_a_new_zero_run(self):
        report = self.passing()
        report["non_finite_samples"] = 1
        with self.assertRaisesRegex(QaFailure, "non-finite"):
            validate_delivery(report)

    def test_rejects_new_flat_top_runs_or_pinned_samples_against_reference(self):
        for field in ("flat_top_runs", "pinned_samples"):
            with self.subTest(field=field):
                report = self.passing()
                report[field] += 1
                with self.assertRaises(QaFailure):
                    validate_delivery(report)

    def test_rejects_new_flat_top_run_at_a_block_boundary(self):
        report = self.passing()
        report["flat_top_boundary_runs"] += 1
        with self.assertRaises(QaFailure):
            validate_delivery(report)

    def test_requires_unique_complete_boundary_and_window_score_coverage(self):
        report = self.passing()
        report["expected_boundary_samples"] = [10, 20]
        report["boundary_scores"] = [
            {"boundary_sample": 10, "jump": 0.0, "jump_over_local_median_db": 0.0},
        ]
        with self.assertRaises(QaFailure):
                    validate_delivery(report)

    def test_rejects_bad_expected_coordinates_nonintegral_counts_and_false_strings(self):
        report = self.passing()
        report["expected_boundary_samples"] = [10, 10]
        with self.assertRaises(QaFailure): validate_delivery(report)
        report = self.passing(); report["source_samples"] = 1.2
        with self.assertRaises(QaFailure): validate_delivery(report)
        report = self.passing(); report["mp3_decode_ok"] = "false"
        with self.assertRaises(QaFailure): validate_delivery(report)

    def test_rejects_incomplete_or_out_of_range_score_evidence_and_nonfinite_persisted_numbers(self):
        report = self.passing(); report["expected_boundary_samples"] = [10]
        report["boundary_scores"] = [{"boundary_sample": 10, "jump": 0.0}]
        with self.assertRaises(QaFailure): validate_delivery(report)
        report = self.passing(); report["expected_candidate_window_ids"] = ["w1"]
        report["candidate_window_scores"] = [{"window_id":"w1", "start_sample":0, "end_sample":999999999, "non_finite_samples":0, "peak":0.0}]
        with self.assertRaises(QaFailure): validate_delivery(report)
        report = self.passing(); report["crest_db"] = float("nan")
        with self.assertRaises(QaFailure): validate_delivery(report)
        report = self.passing()
        report["expected_candidate_window_ids"] = ["w1"]
        report["candidate_window_scores"] = [
            {"window_id": "w1", "non_finite_samples": 0, "peak": float("nan")},
        ]
        with self.assertRaises(QaFailure):
            validate_delivery(report)

    def test_rejects_a_new_boundary_impulse_or_bad_full_render_window(self):
        report = self.passing()
        report["boundary_scores"] = [{
            "boundary_sample": 480000,
            "jump": 0.2,
            "jump_over_local_median_db": 24.0,
        }]
        with self.assertRaises(QaFailure):
            validate_delivery(report)
        report = self.passing()
        report["candidate_window_scores"] = [{"non_finite_samples": 0, "peak": 1.01}]
        with self.assertRaises(QaFailure):
            validate_delivery(report)

    def test_collects_hashes_without_publishing_pending_human_listening_checklist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            flac = root / "delivery.flac"
            mp3 = root / "delivery.mp3"
            source = root / "source.wav"
            adaptive = root / "adaptive.wav"
            master = root / "master.wav"
            checklist = root / "listening-checklist.md"
            flac.write_bytes(b"flac")
            mp3.write_bytes(b"mp3")
            source.write_bytes(b"source")
            adaptive.write_bytes(b"adaptive")
            master.write_bytes(b"master")
            report = collect_qa_report(
                source_samples=8,
                adaptive_samples=8,
                master_probe={"frames": 8},
                flac_probe={"frames": 8, "sample_rate": 48000, "channels": 2, "bits_per_raw_sample": 24, "codec_name":"flac", "container_name":"flac"},
                mp3_probe={"decoded_frames": 8, "sample_rate":48000, "channels":2, "codec_name":"mp3", "container_name":"mp3", "bit_rate": 192000, "codec_delay_padding_samples": 0},
                flac_metrics={"integrated_lufs": -16.0, "true_peak_dbtp": -1.6, "lra": 3.0, "decode_ok": True},
                mp3_metrics={"integrated_lufs": -16.0, "true_peak_dbtp": -1.6, "decode_ok": True},
                flac_path=flac,
                mp3_path=mp3,
                integrity={
                    "non_finite_samples": 0,
                    "unexpected_zero_run_samples": 0,
                    "reference_flat_top_runs": 2,
                    "flat_top_runs": 2,
                    "reference_pinned_samples": 4,
                    "pinned_samples": 4,
                    "reference_flat_top_runs_by_block": [1, 1],
                    "flat_top_runs_by_block": [1, 1],
                    "reference_flat_top_boundary_runs": 0,
                    "flat_top_boundary_runs": 0,
                    "crest_db": 12.0,
                },
                boundary_scores=[],
                candidate_window_scores=[],
                expected_boundary_samples=[],
                expected_candidate_window_ids=[],
                source_path=source,
                adaptive_path=adaptive,
                delivery_master_path=master,
                listening_checklist_path=checklist,
            )
            self.assertEqual(report["listening_checklist"]["status"], "pending")
            self.assertEqual(len(report["hashes"]["source_sha256"]), 64)
            self.assertFalse(checklist.exists())
            from scripts.youtube_enhance.qa import _render_listening_checklist
            text = _render_listening_checklist(report).decode("utf-8")
            for section in (
                "Candidate windows", "Segment transitions", "Chunk boundaries",
                "Quiet consonants", "Overlaps", "Music and chanting",
                "Applause and crowd", "Beginning", "Ending",
                "Naturalness veto", "Word-integrity veto",
            ):
                self.assertIn(f"## {section}", text)
            self.assertIn("Status: pending", text)

    def test_pair_rejects_equal_and_resolved_alias_paths_before_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); report = self.passing()
            shared = root / "same.json"
            with self.assertRaises(QaFailure):
                publish_qa_pair(report, shared, shared)
            self.assertFalse(shared.exists())
            alias = root / "nested" / ".." / "same.json"
            with self.assertRaises(QaFailure):
                publish_qa_pair(report, shared, alias)
            self.assertFalse(any(root.iterdir()))

    def test_publish_pair_validates_before_writing_and_rolls_back_on_second_link_failure(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); report = self.passing()
            qa, checklist = root / "qa-report.json", root / "listening-checklist.md"
            report["listening_checklist"]["path"] = str(checklist)
            report["crest_db"] = float("nan")
            with self.assertRaises(QaFailure):
                publish_qa_pair(report, qa, checklist)
            self.assertFalse(qa.exists() or checklist.exists())

    def test_publish_qa_pair_rolls_back_first_link_and_preserves_second_link_racer(self):
        from unittest.mock import patch
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); report = self.valid_bound_report(root); qa, checklist = root/"qa.json", root/"checklist.md"
            real_link = os.link; calls = []
            def link(stage, destination):
                calls.append(destination)
                if Path(destination) == checklist:
                    checklist.write_bytes(b"racer")
                    raise FileExistsError("racer")
                return real_link(stage, destination)
            with patch("scripts.youtube_enhance.qa.os.link", side_effect=link):
                with self.assertRaises(FileExistsError): publish_qa_pair(report, qa, checklist)
            self.assertEqual(len(calls), 2); self.assertFalse(qa.exists()); self.assertEqual(checklist.read_bytes(), b"racer")
            self.assertEqual(list(root.glob("*.stage.*")), [])
            checklist.unlink(); publish_qa_pair(report, qa, checklist); self.assertTrue(qa.exists() and checklist.exists())

    def test_publish_qa_pair_success_is_canonical_hash_bound_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); report = self.valid_bound_report(root); before = copy.deepcopy(report); qa, checklist = root/"qa.json", root/"checklist.md"
            publish_qa_pair(report, qa, checklist)
            parsed = json.loads(qa.read_text()); self.assertEqual(report, before)
            self.assertEqual(qa.read_bytes(), (json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False)+"\n").encode())
            self.assertEqual(parsed["listening_checklist"]["sha256"], hashlib.sha256(checklist.read_bytes()).hexdigest())
            self.assertEqual(parsed["expected_boundary_samples"], []); self.assertEqual(parsed["expected_candidate_window_ids"], [])
            self.assertEqual(list(root.glob("*.stage.*")), [])

    def test_publish_rejects_shared_existing_or_final_alias_stage_before_hash_or_write(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); report=self.valid_bound_report(root); qa, checklist=root/"qa.json",root/"checklist.md"; shared=root/"shared.stage.json"
            with patch("scripts.youtube_enhance.qa._stage", return_value=shared), patch("scripts.youtube_enhance.qa.sha256_file", side_effect=AssertionError("hashed")):
                with self.assertRaises(QaFailure): publish_qa_pair(report, qa, checklist)
            self.assertFalse(shared.exists() or qa.exists() or checklist.exists())

    def test_stage_preflight_rejects_shared_existing_and_final_alias_before_hash_or_write(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); report=self.valid_bound_report(root); qa,checklist=root/"qa.json",root/"check.md"
            for stage in (root/"shared.stage.json", qa, root/"exists.stage.json"):
                if stage.name.startswith("exists"): stage.write_bytes(b"old")
                with self.subTest(stage=stage.name), patch("scripts.youtube_enhance.qa._stage", return_value=stage), patch("scripts.youtube_enhance.qa.sha256_file", side_effect=AssertionError("hash reached")):
                    with self.assertRaises(QaFailure): publish_qa_pair(report,qa,checklist)
                self.assertFalse(qa.exists() or checklist.exists())

    def test_successful_pair_nonempty_expected_evidence_is_rendered_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); report=self.valid_bound_report(root); report["expected_boundary_samples"]=[4]; report["boundary_scores"]=[{"boundary_sample":4,"jump":0.0,"jump_over_local_median_db":0.0}]; report["expected_candidate_window_ids"]=["w1"]; report["candidate_window_scores"]=[{"window_id":"w1","start_sample":0,"end_sample":8,"non_finite_samples":0,"peak":1.0}]
            qa,checklist=root/"qa.json",root/"check.md"; before=copy.deepcopy(report); publish_qa_pair(report,qa,checklist); data=json.loads(qa.read_text()); text=checklist.read_text()
            self.assertEqual(report,before); self.assertEqual(data["listening_checklist"]["path"],str(checklist)); self.assertIn("4",text); self.assertIn("w1",text); self.assertIn("Naturalness veto",text); self.assertEqual(data["listening_checklist"]["sha256"],hashlib.sha256(checklist.read_bytes()).hexdigest())

    def test_impulse_and_peak_thresholds_reach_complete_nonempty_score_rows(self):
        report=self.passing(); report["expected_boundary_samples"]=[4]; report["boundary_scores"]=[{"boundary_sample":4,"jump":0.05,"jump_over_local_median_db":20.0}]; validate_delivery(report)
        report["boundary_scores"][0]["jump"]=0.051; report["boundary_scores"][0]["jump_over_local_median_db"]=20.1
        with self.assertRaises(QaFailure): validate_delivery(report)
        report=self.passing(); report["expected_candidate_window_ids"]=["w"]; report["candidate_window_scores"]=[{"window_id":"w","start_sample":0,"end_sample":8,"non_finite_samples":0,"peak":1.0}]; validate_delivery(report)
        report["candidate_window_scores"][0]["peak"]=1.001
        with self.assertRaises(QaFailure): validate_delivery(report)

    def test_collect_rejects_every_non_raw_integer_field(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for bad in (8.9, True, "8"):
                with self.subTest(bad=bad):
                    with self.assertRaises(QaFailure): self.valid_bound_report(root) if False else collect_qa_report(bad,8,{"frames":8},{"frames":8,"sample_rate":48000,"channels":2,"bits_per_raw_sample":24,"codec_name":"flac","container_name":"flac"},{"decoded_frames":8,"sample_rate":48000,"channels":2,"bit_rate":192000,"codec_delay_padding_samples":0,"codec_name":"mp3","container_name":"mp3"},{"integrated_lufs":-16,"true_peak_dbtp":-1.6,"lra":1,"decode_ok":True},{"integrated_lufs":-16,"true_peak_dbtp":-1.6,"decode_ok":True},root/"f",root/"m",{},[],[],expected_boundary_samples=[],expected_candidate_window_ids=[],source_path=root/"s",adaptive_path=root/"a",delivery_master_path=root/"d")

    def test_generic_rate_and_channels_are_exactly_validated(self):
        for key in ("sample_rate", "channels"):
            report=self.passing(); report[key]=44100 if key=="sample_rate" else 1
            with self.subTest(key=key):
                with self.assertRaises(QaFailure): validate_delivery(report)

    def test_generic_rate_rejects_float(self):
        report=self.passing(); report["sample_rate"]=48000.0
        with self.assertRaises(QaFailure): validate_delivery(report)

    def test_generic_channels_rejects_boolean(self):
        report=self.passing(); report["channels"]=True
        with self.assertRaises(QaFailure): validate_delivery(report)

    def test_block_counts_reject_negative_or_string(self):
        for value in (-1, "0"):
            report=self.passing(); report["flat_top_runs_by_block"]=[value,2]
            with self.subTest(value=value):
                with self.assertRaises(QaFailure): validate_delivery(report)

if __name__ == "__main__":
    unittest.main()
