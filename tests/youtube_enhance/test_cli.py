import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import get_type_hints
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

import scripts.youtube_enhance.cli as cli_module
from scripts.youtube_enhance.cli import (
    DISK_SPACE_REQUIREMENTS,
    _measure_delivery,
    _stream_probe,
    _validate_reviewed_windows,
    _verify_diagnose_state,
    _verify_qa_state,
    _verify_record,
    _verify_render_state,
    main,
    run_approve,
    run_candidates,
    run_diagnose,
    run_export,
    run_full_render,
    run_qa,
)
from scripts.youtube_enhance.dfn import Processed
from scripts.youtube_enhance.dfn import build_render_context_key
from scripts.youtube_enhance.diagnostics import WindowFeature, select_representative_windows
from scripts.youtube_enhance.loudness import export_matched_pair
from scripts.youtube_enhance.manifest import (
    candidate_context_fingerprint,
    read_json,
    render_approval_fingerprint,
    write_json_atomic,
)
from scripts.youtube_enhance.qa import QaFailure, collect_qa_report, publish_qa_pair
from scripts.youtube_enhance.source import sha256_file


class _DiskUsage:
    def __init__(self, free: int):
        self.total = free * 2
        self.used = free
        self.free = free


class _RecordingEnhancer:
    def __init__(self, name: str, calls: list[tuple[str, int | None, np.ndarray]]):
        self.name = name
        self.calls = calls

    def enhance(self, samples, sample_rate, attenuation_db, work_directory):
        before = samples.copy()
        self.calls.append((self.name, attenuation_db, before))
        samples[0] = 12345.0
        return Processed(before, 0)


class CliTests(unittest.TestCase):
    def test_parser_lists_every_stage_without_running_one(self):
        with self.assertRaises(SystemExit) as error:
            main(["--help"])
        self.assertEqual(error.exception.code, 0)

    def test_script_entry_point_runs_from_the_repository_root(self):
        repository = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(repository / "scripts" / "enhance_youtube_lecture.py"), "--help"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("diagnose", result.stdout)
        self.assertIn("candidates", result.stdout)
        self.assertIn("approve", result.stdout)
        self.assertIn("render", result.stdout)
        self.assertIn("export", result.stdout)
        self.assertIn("qa", result.stdout)

    def test_cli_converts_malformed_state_and_io_failures_to_controlled_errors(self):
        failures = (
            KeyError("missing persisted field"),
            AttributeError("malformed persisted object"),
            OSError("synthetic I/O failure"),
            subprocess.CalledProcessError(1, ["synthetic-tool"]),
        )
        argv = [
            "diagnose", "--source", "synthetic.webm", "--workspace", "synthetic-workspace",
            "--expected-sha256", "A" * 64,
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch(
                "scripts.youtube_enhance.cli.run_diagnose", side_effect=failure
            ):
                try:
                    main(argv)
                except SystemExit as error:
                    self.assertEqual(error.code, 2)
                except Exception as error:  # pragma: no cover - the failure is the regression
                    self.fail(f"CLI leaked {type(error).__name__}: {error}")
                else:
                    self.fail("CLI accepted a failed command")

    def test_manifest_commit_refuses_preexisting_private_stage_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest_path = Path(folder) / "manifest.json"
            manifest_path.write_bytes(b"original manifest")
            stage = manifest_path.with_suffix(".json.new")
            stage.write_bytes(b"racer evidence")
            with self.assertRaises(FileExistsError):
                write_json_atomic(manifest_path, {"schema_version": 1})
            self.assertEqual(manifest_path.read_bytes(), b"original manifest")
            self.assertEqual(stage.read_bytes(), b"racer evidence")

    def test_render_refuses_manifest_without_approval_before_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            write_json_atomic(workspace / "manifest.json", _minimal_manifest())
            with patch(
                "scripts.youtube_enhance.cli.run_full_render",
                side_effect=AssertionError("render was dispatched"),
            ):
                with self.assertRaises(SystemExit) as error:
                    main(["render", "--workspace", str(workspace)])
            self.assertNotEqual(error.exception.code, 0)

    def test_candidates_dispatch_never_crosses_the_render_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            with patch("scripts.youtube_enhance.cli.run_candidates") as candidates, patch(
                "scripts.youtube_enhance.cli.run_full_render"
            ) as render:
                self.assertEqual(main(["candidates", "--workspace", str(workspace)]), 0)
            candidates.assert_called_once_with(workspace)
            render.assert_not_called()

    def test_candidate_and_render_fingerprints_are_distinct_and_noncyclic(self):
        manifest = _fingerprinted_manifest()
        context = candidate_context_fingerprint(manifest)
        approval = render_approval_fingerprint(manifest)

        changed_evidence = copy.deepcopy(manifest)
        changed_evidence["candidate_evidence"]["public_report_sha256"] = "9" * 64
        self.assertEqual(candidate_context_fingerprint(changed_evidence), context)
        self.assertNotEqual(render_approval_fingerprint(changed_evidence), approval)

        changed_selection = copy.deepcopy(manifest)
        changed_selection["selection"]["blind_code"] = "C"
        self.assertEqual(candidate_context_fingerprint(changed_selection), context)
        self.assertNotEqual(render_approval_fingerprint(changed_selection), approval)

    def test_render_context_contract_accepts_nullable_strong_pause_attenuation(self):
        self.assertEqual(get_type_hints(build_render_context_key)["attenuation_db"], int | None)

    def test_diagnose_disk_gate_precedes_decode_and_records_observed_threshold(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.webm"
            source.write_bytes(b"source")
            workspace = root / "workspace"
            required = DISK_SPACE_REQUIREMENTS["diagnose"]
            args = argparse.Namespace(
                source=source,
                workspace=workspace,
                expected_sha256=sha256_file(source),
            )
            with patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(required - 1),
            ), patch(
                "scripts.youtube_enhance.cli.decode_float_stereo",
                side_effect=AssertionError("decode ran below the disk threshold"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    rf"observed_free_bytes={required - 1}.*required_free_bytes={required}",
                ):
                    run_diagnose(args)
            self.assertFalse(workspace.exists())

    def test_exact_complete_diagnose_replay_skips_disk_gate_and_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            manifest = _diagnosed_workspace(workspace)
            write_json_atomic(workspace / "manifest.json", manifest)
            source = Path(manifest["source"]["path"])
            args = argparse.Namespace(
                source=source,
                workspace=workspace,
                expected_sha256=sha256_file(source),
            )
            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ) as verify, patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                side_effect=AssertionError("disk gate reached on complete replay"),
            ), patch(
                "scripts.youtube_enhance.cli.write_json_atomic",
                side_effect=AssertionError("complete replay wrote state"),
            ):
                run_diagnose(args)
            verify.assert_called_once()

    def test_diagnose_uses_one_headroom_mid_side_stereo_reference_everywhere(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.webm"
            source.write_bytes(b"source")
            workspace = root / "workspace"
            args = argparse.Namespace(
                source=source,
                workspace=workspace,
                expected_sha256=sha256_file(source),
            )
            decoded = np.array(
                [[1.0, -0.5], [0.75, 0.25], [-1.0, 0.5], [0.25, -0.75]],
                dtype=np.float32,
            )
            observed = {}

            def fake_decode(_source, destination, _ffmpeg):
                destination.parent.mkdir(parents=True, exist_ok=True)
                sf.write(destination, decoded, 48000, subtype="FLOAT")

            def fake_diagnostics(stereo_path, _mid_path, _ffmpeg, output_path):
                observed["diagnostics"], _ = sf.read(stereo_path, dtype="float32", always_2d=True)
                report = {
                    "schema_version": 1, "integrity": {}, "level": {}, "noise_floor": {},
                    "noise_spectrum": {}, "tonal": [], "reverb": [], "bandwidth": [],
                    "snr_by_band": [], "stereo": {}, "window_features": [],
                    "representative_windows": [], "recommendations": [],
                }
                write_json_atomic(output_path, report)
                write_json_atomic(output_path.parent / "segments-proposed.json", [{
                    "start_sample": 0, "end_sample": len(decoded), "label": "uncertain",
                    "reviewed": False, "notes": "complete conservative proposal",
                }])
                write_json_atomic(output_path.parent / "transitions.json", [])
                return report

            def fake_review(stereo_path, _representatives, _transitions, output_dir):
                observed["review"], _ = sf.read(stereo_path, dtype="float32", always_2d=True)
                output_dir.mkdir(parents=True)
                (output_dir / "index.html").write_text("review", encoding="utf-8")
                return {"artifacts": []}

            with patch(
                "scripts.youtube_enhance.cli.AUTHORITATIVE_SAMPLES", len(decoded)
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ), patch(
                "scripts.youtube_enhance.cli.resolve_tool", side_effect=lambda name: name
            ), patch(
                "scripts.youtube_enhance.cli.probe_audio",
                return_value={"streams": [{"codec_name": "opus", "sample_rate": "48000", "channels": 2}]},
            ), patch(
                "scripts.youtube_enhance.cli.decode_float_stereo", side_effect=fake_decode
            ), patch(
                "scripts.youtube_enhance.cli.run_diagnostics", side_effect=fake_diagnostics
            ), patch(
                "scripts.youtube_enhance.cli.write_original_review_material", side_effect=fake_review
            ), patch(
                "scripts.youtube_enhance.cli._first_version_line", return_value="test-version"
            ), patch(
                "scripts.youtube_enhance.cli.importlib.metadata.version", return_value="test-version"
            ):
                run_diagnose(args)

            manifest = read_json(workspace / "manifest.json")
            mid, _ = sf.read(workspace / manifest["working"]["original_mid"]["path"], dtype="float32")
            side, _ = sf.read(workspace / manifest["working"]["original_side"]["path"], dtype="float32")
            expected = np.column_stack((mid + side, mid - side))
            np.testing.assert_array_equal(observed["diagnostics"], expected)
            np.testing.assert_array_equal(observed["review"], expected)
            reference_path = workspace / manifest["working"]["reference_stereo"]["path"]
            self.assertEqual(manifest["reference"]["reference_stereo_sha256"], sha256_file(reference_path))
            self.assertEqual(manifest["reference"]["headroom_gain"], manifest["source"]["headroom_gain"])

    def test_diagnose_replay_requires_exact_space_evidence_and_known_stage_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            manifest = _diagnosed_workspace(workspace)
            valid = copy.deepcopy(manifest["preflight_space"]["diagnose"])
            invalid_cases = {
                "missing-space-map": None,
                "missing-diagnose": {},
                "wrong-threshold": {
                    "diagnose": {
                        "observed_free_bytes": valid["observed_free_bytes"],
                        "required_free_bytes": DISK_SPACE_REQUIREMENTS["diagnose"] - 1,
                    }
                },
                "negative-observed": {
                    "diagnose": {
                        "observed_free_bytes": -1,
                        "required_free_bytes": DISK_SPACE_REQUIREMENTS["diagnose"],
                    }
                },
                "unknown-stage": {"diagnose": valid, "mystery": valid},
            }
            for name, space in invalid_cases.items():
                with self.subTest(name=name):
                    changed = copy.deepcopy(manifest)
                    if space is None:
                        changed.pop("preflight_space", None)
                    else:
                        changed["preflight_space"] = space
                    with self.assertRaises(RuntimeError):
                        _verify_diagnose_state(workspace, changed)

    def test_diagnose_manifest_rejects_wrong_version_unknown_and_missing_base_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            manifest = _diagnosed_workspace(workspace)
            mutations = {}
            for version in (2, True, 1.0, "1"):
                changed = copy.deepcopy(manifest)
                changed["schema_version"] = version
                mutations[f"schema-{version!r}"] = changed
            changed = copy.deepcopy(manifest)
            changed["unknown_top_level"] = "accepted before strict schemas"
            mutations["unknown-top-level"] = changed
            changed = copy.deepcopy(manifest)
            changed.pop("versions")
            mutations["missing-base-key"] = changed

            for name, changed in mutations.items():
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    _verify_diagnose_state(workspace, changed)

    def test_candidates_use_finalized_map_real_halos_and_independent_original_copies(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            manifest, mid = _candidate_workspace(workspace)
            calls: list[tuple[str, int | None, np.ndarray]] = []
            enhancers = {
                22: _RecordingEnhancer("22", calls),
                24: _RecordingEnhancer("24", calls),
            }
            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                return_value=enhancers,
            ), patch(
                "scripts.youtube_enhance.cli.score_candidate_windows",
                return_value=_passing_candidate_metrics(),
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                run_candidates(workspace)

            self.assertEqual([(name, attenuation) for name, attenuation, _ in calls], [
                ("22", 22), ("24", 24), ("22", 22), ("24", 24),
                ("22", 22), ("24", 24),
            ])
            np.testing.assert_array_equal(calls[0][2], mid[4:20])
            np.testing.assert_array_equal(calls[1][2], mid[4:20])
            np.testing.assert_array_equal(calls[2][2], mid[20:36])
            np.testing.assert_array_equal(calls[3][2], mid[20:36])
            self.assertFalse(np.shares_memory(calls[0][2], calls[1][2]))

            committed = read_json(workspace / "manifest.json")
            self.assertEqual(
                committed["candidate_context_fingerprint"],
                candidate_context_fingerprint(committed),
            )
            self.assertIn("candidate_evidence", committed)
            run_root = workspace / committed["candidate_evidence"]["root"]
            self.assertEqual(
                run_root,
                workspace / "candidate-runs" / committed["candidate_context_fingerprint"],
            )
            self.assertFalse((run_root / "candidates" / "gate-report.json").exists())
            self.assertTrue((run_root / "candidate-map.private.json").is_file())
            self.assertTrue((run_root / "candidates" / "candidate-report.json").is_file())
            self.assertTrue((run_root / "candidates" / "completion.json").is_file())
            private = read_json(run_root / "candidate-map.private.json")
            transition_id = next(
                artifact_id
                for artifact_id, identity in private["evidence_map"].items()
                if identity["window_id"] == "transition-36"
            )
            self.assertTrue((run_root / "candidates" / transition_id / "A.wav").is_file())
            completion = read_json(run_root / "candidates" / "completion.json")
            self.assertEqual(
                completion["provenance"]["preflight_space"],
                committed["preflight_space"]["candidates"],
            )
            for key in ("report_evidence_sha256", "blind_map_sha256"):
                self.assertRegex(committed["candidate_evidence"][key], r"^[0-9a-f]{64}$")
            for key in ("public_report_sha256", "completion_sha256", "private_map_sha256"):
                self.assertRegex(committed["candidate_evidence"][key], r"^[0-9A-F]{64}$")

            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                side_effect=AssertionError("model reached on complete replay"),
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                side_effect=AssertionError("disk gate reached on complete replay"),
            ):
                run_candidates(workspace)

            (run_root / "candidates" / "gate-report.json").write_text("{}", encoding="utf-8")
            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                side_effect=AssertionError("model reached with stale gate-report evidence"),
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                side_effect=AssertionError("disk gate reached before stale evidence rejection"),
            ):
                with self.assertRaisesRegex(RuntimeError, "partial, extra, or aliased"):
                    run_candidates(workspace)

    def test_candidates_refuse_unreviewed_complete_map_before_model_work(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            _candidate_workspace(workspace)
            rows = read_json(workspace / "analysis" / "segments-reviewed.json")
            rows[0]["reviewed"] = False
            write_json_atomic(workspace / "analysis" / "segments-reviewed.json", rows)
            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                side_effect=AssertionError("model ran with an unreviewed map"),
            ):
                with self.assertRaises(ValueError):
                    run_candidates(workspace)

    def test_candidates_reject_windows_not_exactly_bounded_to_diagnostic_ids(self):
        expected = [{
            "window_id": "w1", "start_sample": 0, "label_hint": "main_speech",
            "floor_db": -60.0, "active_db": -20.0, "speech_confidence": 0.9,
            "timeline_third": 0, "role": "clean_speech",
        }]
        whole_file = [{
            "window_id": "w1", "start_sample": 0, "end_sample": 2_000_000,
            "reviewed_label": "main_speech", "role": "clean_speech", "reviewed": True,
        }]
        missing_expected = [{
            "window_id": "w2", "start_sample": 1_440_000, "end_sample": 2_000_000,
            "reviewed_label": "main_speech", "role": "clean_speech", "reviewed": True,
        }]
        excessive = [
            {
                "window_id": f"w{index}", "start_sample": index * 50_000,
                "end_sample": (index + 1) * 50_000,
                "reviewed_label": "main_speech", "role": "clean_speech", "reviewed": True,
            }
            for index in range(40)
        ]
        for name, rows in (
            ("whole-file", whole_file),
            ("missing-and-extra", missing_expected),
            ("excessive-count", excessive),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                workspace = Path(folder)
                _candidate_workspace(workspace)
                manifest = read_json(workspace / "manifest.json")
                manifest["source"]["decoded_samples"] = 2_000_000
                diagnostics_path = workspace / manifest["reports"]["diagnostics"]["path"]
                diagnostics = read_json(diagnostics_path)
                diagnostics["representative_windows"] = expected
                write_json_atomic(diagnostics_path, diagnostics)
                manifest["reports"]["diagnostics"]["sha256"] = sha256_file(diagnostics_path)
                write_json_atomic(workspace / "analysis" / "segments-reviewed.json", [{
                    "start_sample": 0, "end_sample": 2_000_000, "label": "main_speech",
                    "reviewed": True, "notes": "synthetic complete timeline",
                }])
                write_json_atomic(workspace / "analysis" / "windows-reviewed.json", rows)
                write_json_atomic(workspace / "manifest.json", manifest)
                with patch(
                    "scripts.youtube_enhance.cli._verify_diagnose_state"
                ), patch(
                    "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
                ), patch(
                    "scripts.youtube_enhance.cli._candidate_enhancers",
                    side_effect=AssertionError("invalid windows reached model allocation"),
                ), patch(
                    "scripts.youtube_enhance.cli.shutil.disk_usage",
                    return_value=_DiskUsage(100 * 1024**3),
                ):
                    with self.assertRaises(ValueError):
                        run_candidates(workspace)

    def test_candidates_real_scorer_deduplicates_anchors_and_keeps_every_task6_role(self):
        representatives = select_representative_windows([
            WindowFeature(
                window_id="w1", start_sample=8, label_hint="main_speech",
                floor_db=-60.0, active_db=-30.0, speech_confidence=0.95,
                timeline_third=0,
            ),
            WindowFeature(
                window_id="w2", start_sample=24, label_hint="main_speech",
                floor_db=-30.0, active_db=-20.0, speech_confidence=0.95,
                timeline_third=0,
            ),
        ])
        self.assertEqual(
            {(item.window_id, item.role) for item in representatives},
            {
                ("w1", "clean_speech"),
                ("w1", "low_energy_speech"),
                ("w2", "noisy_speech"),
            },
        )
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            _candidate_workspace(workspace)
            manifest = read_json(workspace / "manifest.json")
            diagnostics_path = workspace / manifest["reports"]["diagnostics"]["path"]
            diagnostics = read_json(diagnostics_path)
            diagnostics["representative_windows"] = [
                {
                    "window_id": item.window_id, "start_sample": item.start_sample,
                    "label_hint": item.label_hint, "floor_db": item.floor_db,
                    "active_db": item.active_db,
                    "speech_confidence": item.speech_confidence,
                    "timeline_third": item.timeline_third, "role": item.role,
                }
                for item in representatives
            ]
            write_json_atomic(diagnostics_path, diagnostics)
            manifest["reports"]["diagnostics"]["sha256"] = sha256_file(diagnostics_path)
            write_json_atomic(workspace / "analysis" / "windows-reviewed.json", [
                {
                    "window_id": item.window_id, "start_sample": item.start_sample,
                    "end_sample": item.start_sample + 8, "reviewed_label": "main_speech",
                    "role": item.role, "reviewed": True,
                }
                for item in representatives
            ])
            write_json_atomic(workspace / "manifest.json", manifest)

            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                return_value={22: _RecordingEnhancer("22", []), 24: _RecordingEnhancer("24", [])},
            ), patch(
                "scripts.youtube_enhance.gates._mono16",
                side_effect=lambda _values, _rate: np.full(15 * 16000, 0.1, dtype=np.float32),
            ), patch(
                "scripts.youtube_enhance.gates.VoiceEncoder", return_value=object()
            ), patch(
                "scripts.youtube_enhance.gates.embed_chunks",
                side_effect=lambda _encoder, chunks, _rate: np.tile(
                    np.array([[1.0, 0.0]], dtype=np.float32), (len(chunks), 1)
                ),
            ), patch(
                "scripts.youtube_enhance.gates._voice_quality",
                return_value={
                    "cpps": 1.0, "hnr": 1.0, "hammarberg": 1.0, "alpha_std": 1.0,
                },
            ), patch(
                "scripts.youtube_enhance.gates._mfcc_distance", return_value=0.0
            ), patch(
                "scripts.youtube_enhance.gates._pumping_index", return_value=0.0
            ), patch(
                "scripts.youtube_enhance.gates._floor_db", return_value=-50.0
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                run_candidates(workspace)

            committed = read_json(workspace / "manifest.json")
            run_root = workspace / committed["candidate_evidence"]["root"]
            private = read_json(run_root / "candidate-map.private.json")
            evidence_map = private["evidence_map"]
            self.assertEqual(len(evidence_map), 4)  # three role artifacts plus one transition
            role_rows = [row for row in evidence_map.values() if row["kind"] == "window"]
            self.assertEqual(
                {(row["window_id"], row["role"]) for row in role_rows},
                {
                    ("w1", "clean_speech"),
                    ("w1", "low_energy_speech"),
                    ("w2", "noisy_speech"),
                },
            )
            self.assertEqual(len(set(evidence_map)), len(evidence_map))
            self.assertTrue(all(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", artifact_id)
                for artifact_id in evidence_map
            ))
            completion = read_json(run_root / "candidates" / "completion.json")
            artifact_directories = {
                Path(relative).parts[1]
                for relative in completion["artifacts"]
                if relative.endswith("/A.wav")
            }
            self.assertEqual(artifact_directories, set(evidence_map))
            gallery = (run_root / "candidates" / "index.html").read_text(encoding="utf-8")
            self.assertTrue(all(artifact_id in gallery for artifact_id in evidence_map))
            report = read_json(run_root / "candidates" / "candidate-report.json")
            self.assertEqual(set(report["evidence_ids"]), set(evidence_map))
            self.assertTrue(all(
                metrics["status"] == "scored" for metrics in report["metrics"].values()
            ))

            adaptive = workspace / "work" / "qa-adaptive.wav"
            mid, _ = sf.read(workspace / "work" / "original-mid.wav", dtype="float32")
            sf.write(adaptive, np.column_stack((mid, mid)), 48000, subtype="FLOAT")
            with patch("scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8):
                qa_rows = cli_module._candidate_window_scores(workspace, adaptive, committed)
            self.assertEqual(
                {row["window_id"] for row in qa_rows},
                {artifact_id for artifact_id, row in evidence_map.items() if row["kind"] == "window"},
            )

    def test_repeated_task6_roles_with_one_interval_fail_before_heavy_scoring_or_publish(self):
        feature = WindowFeature(
            window_id="w00", start_sample=8, label_hint="main_speech",
            floor_db=-60.0, active_db=-20.0, speech_confidence=0.95,
            timeline_third=0,
        )
        representatives = select_representative_windows([feature])
        self.assertEqual(
            {item.role for item in representatives},
            {"clean_speech", "low_energy_speech", "noisy_speech"},
        )
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            _candidate_workspace(workspace)
            manifest = read_json(workspace / "manifest.json")
            diagnostics_path = workspace / manifest["reports"]["diagnostics"]["path"]
            diagnostics = read_json(diagnostics_path)
            diagnostics["representative_windows"] = [
                {
                    "window_id": item.window_id, "start_sample": item.start_sample,
                    "label_hint": item.label_hint, "floor_db": item.floor_db,
                    "active_db": item.active_db,
                    "speech_confidence": item.speech_confidence,
                    "timeline_third": item.timeline_third, "role": item.role,
                }
                for item in representatives
            ]
            write_json_atomic(diagnostics_path, diagnostics)
            manifest["reports"]["diagnostics"]["sha256"] = sha256_file(diagnostics_path)
            write_json_atomic(workspace / "analysis" / "windows-reviewed.json", [
                {
                    "window_id": item.window_id, "start_sample": item.start_sample,
                    "end_sample": 16, "reviewed_label": "main_speech",
                    "role": item.role, "reviewed": True,
                }
                for item in representatives
            ])
            write_json_atomic(workspace / "manifest.json", manifest)
            publisher = Mock()

            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                return_value={22: _RecordingEnhancer("22", []), 24: _RecordingEnhancer("24", [])},
            ), patch(
                "scripts.youtube_enhance.gates._mono16",
                side_effect=lambda _values, _rate: np.full(30 * 16000, 0.1, dtype=np.float32),
            ), patch(
                "scripts.youtube_enhance.gates.VoiceEncoder",
                side_effect=AssertionError("insufficient anchors reached the encoder"),
            ), patch(
                "scripts.youtube_enhance.gates._voice_quality",
                side_effect=AssertionError("insufficient anchors reached voice-quality scoring"),
            ), patch(
                "scripts.youtube_enhance.gates._mfcc_distance",
                side_effect=AssertionError("insufficient anchors reached MFCC scoring"),
            ), patch(
                "scripts.youtube_enhance.gates._pumping_index",
                side_effect=AssertionError("insufficient anchors reached pumping scoring"),
            ), patch(
                "scripts.youtube_enhance.gates._floor_db",
                side_effect=AssertionError("insufficient anchors reached floor scoring"),
            ), patch(
                "scripts.youtube_enhance.cli.write_candidate_artifacts", publisher
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                with self.assertRaisesRegex(
                    ValueError, "identity anchor requires at least two unique source intervals"
                ):
                    run_candidates(workspace)
            publisher.assert_not_called()

    def test_candidate_retained_memory_budget_has_an_exact_boundary_and_persisted_evidence(self):
        for budget, rejected in ((2688, False), (2687, True)):
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as folder:
                workspace = Path(folder)
                _candidate_workspace(workspace)
                adapters = Mock(return_value={
                    22: _RecordingEnhancer("22", []), 24: _RecordingEnhancer("24", [])
                })
                scorer = Mock(return_value=_passing_candidate_metrics())
                publisher = Mock()
                patches = (
                    patch("scripts.youtube_enhance.cli._verify_diagnose_state"),
                    patch("scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8),
                    patch("scripts.youtube_enhance.cli.CANDIDATE_MEMORY_BUDGET_BYTES", budget,
                          create=True),
                    patch("scripts.youtube_enhance.cli._candidate_enhancers", adapters),
                    patch("scripts.youtube_enhance.cli.score_candidate_windows", scorer),
                    patch("scripts.youtube_enhance.cli.shutil.disk_usage",
                          return_value=_DiskUsage(100 * 1024**3)),
                )
                with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                    if rejected:
                        with patch("scripts.youtube_enhance.cli.write_candidate_artifacts", publisher):
                            with self.assertRaisesRegex(
                                RuntimeError,
                                r"observed_request_samples=56.*required_retained_bytes=2688"
                                r".*budget_bytes=2687",
                            ):
                                run_candidates(workspace)
                        adapters.assert_not_called()
                        scorer.assert_not_called()
                        publisher.assert_not_called()
                    else:
                        run_candidates(workspace)
                        committed = read_json(workspace / "manifest.json")
                        self.assertEqual(committed["candidate_evidence"]["memory_budget"], {
                            "observed_request_samples": 56,
                            "retained_bytes_per_sample": 48,
                            "required_retained_bytes": 2688,
                            "budget_bytes": 2688,
                        })

    def test_candidate_replay_rejects_self_consistent_memory_unrelated_to_request_ledger(self):
        for observed_samples in (0, 1):
            with self.subTest(observed_samples=observed_samples), tempfile.TemporaryDirectory() as folder:
                workspace = Path(folder)
                _candidate_workspace(workspace)
                _generate_candidate_run(workspace)
                manifest = read_json(workspace / "manifest.json")
                run_root = workspace / manifest["candidate_evidence"]["root"]
                completion_path = run_root / "candidates" / "completion.json"
                completion = read_json(completion_path)
                unrelated = {
                    "observed_request_samples": observed_samples,
                    "retained_bytes_per_sample": 48,
                    "required_retained_bytes": observed_samples * 48,
                    "budget_bytes": 1024**3,
                }
                completion["provenance"]["memory_budget"] = unrelated
                write_json_atomic(completion_path, completion)
                manifest["candidate_evidence"]["memory_budget"] = unrelated
                manifest["candidate_evidence"]["completion_sha256"] = sha256_file(
                    completion_path
                )
                write_json_atomic(workspace / "manifest.json", manifest)
                adapters = Mock()
                scorer = Mock()
                publisher = Mock()

                with patch(
                    "scripts.youtube_enhance.cli._verify_diagnose_state"
                ), patch(
                    "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
                ), patch(
                    "scripts.youtube_enhance.cli._candidate_enhancers", adapters
                ), patch(
                    "scripts.youtube_enhance.cli.score_candidate_windows", scorer
                ), patch(
                    "scripts.youtube_enhance.cli.write_candidate_artifacts", publisher
                ), patch(
                    "scripts.youtube_enhance.cli.shutil.disk_usage",
                    side_effect=AssertionError("memory replay reached the disk gate"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "retained-memory provenance"):
                        run_candidates(workspace)
                adapters.assert_not_called()
                scorer.assert_not_called()
                publisher.assert_not_called()

    def test_many_transitions_reject_memory_before_adapter_scorer_or_publisher(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            _candidate_workspace(workspace)
            total = 12_000_000
            boundaries = [round(index * total / 101) for index in range(102)]
            segments = [
                {
                    "start_sample": boundaries[index], "end_sample": boundaries[index + 1],
                    "label": "main_speech" if index % 2 == 0 else "uncertain",
                    "reviewed": True, "notes": "synthetic aggregate-memory ledger",
                }
                for index in range(101)
            ]
            write_json_atomic(workspace / "analysis" / "segments-reviewed.json", segments)
            manifest = read_json(workspace / "manifest.json")
            manifest["source"]["decoded_samples"] = total
            diagnostics_path = workspace / manifest["reports"]["diagnostics"]["path"]
            diagnostics = read_json(diagnostics_path)
            diagnostics["representative_windows"] = [{
                "window_id": "w-ledger", "start_sample": 0, "label_hint": "main_speech",
                "floor_db": -60.0, "active_db": -20.0, "speech_confidence": 0.9,
                "timeline_third": 0, "role": "clean_speech",
            }]
            write_json_atomic(diagnostics_path, diagnostics)
            manifest["reports"]["diagnostics"]["sha256"] = sha256_file(diagnostics_path)
            write_json_atomic(workspace / "analysis" / "windows-reviewed.json", [{
                "window_id": "w-ledger", "start_sample": 0, "end_sample": 1_440_000,
                "reviewed_label": "main_speech", "role": "clean_speech", "reviewed": True,
            }])
            write_json_atomic(workspace / "manifest.json", manifest)
            adapters = Mock()
            scorer = Mock()
            publisher = Mock()
            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers", adapters
            ), patch(
                "scripts.youtube_enhance.cli.score_candidate_windows", scorer
            ), patch(
                "scripts.youtube_enhance.cli.write_candidate_artifacts", publisher
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    r"observed_request_samples=.*required_retained_bytes=.*budget_bytes=1073741824",
                ):
                    run_candidates(workspace)
            adapters.assert_not_called()
            scorer.assert_not_called()
            publisher.assert_not_called()

    def test_changed_candidate_recovery_refuses_existing_evidence_after_render(self):
        for downstream_key in ("render", "outputs", "qa"):
            with self.subTest(downstream_key=downstream_key), tempfile.TemporaryDirectory() as folder:
                workspace = Path(folder)
                previous = _seed_changed_candidate_evidence(workspace)
                previous[downstream_key] = {}
                write_json_atomic(workspace / "manifest.json", previous)

                with patch(
                    "scripts.youtube_enhance.cli._verify_diagnose_state"
                ), patch(
                    "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
                ), patch(
                    "scripts.youtube_enhance.cli._candidate_enhancers",
                    side_effect=AssertionError("model reached during versioned recovery"),
                ), patch(
                    "scripts.youtube_enhance.cli.shutil.disk_usage",
                    side_effect=AssertionError("disk gate reached during versioned recovery"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "new workflow workspace"):
                        run_candidates(workspace)

    def test_changed_candidate_recovery_invalidates_pre_render_approval_state(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            previous = _seed_changed_candidate_evidence(workspace)
            previous["approval"] = {"reviewer": "Mukul", "fingerprint": "stale"}
            previous["selection"] = {
                "blind_code": "A", "candidate_id": "original", "pause_treatment": "original",
            }
            previous["segment_map_sha256"] = "F" * 64
            write_json_atomic(workspace / "manifest.json", previous)

            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                side_effect=AssertionError("model reached during versioned recovery"),
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                side_effect=AssertionError("disk gate reached during versioned recovery"),
            ):
                run_candidates(workspace)

            recovered = read_json(workspace / "manifest.json")
            self.assertIsNone(recovered["approval"])
            self.assertNotIn("selection", recovered)
            self.assertNotIn("segment_map_sha256", recovered)

    def test_approval_binds_post_evidence_fingerprint_and_segment_map_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            _candidate_workspace(workspace)
            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
            ), patch(
                "scripts.youtube_enhance.cli._candidate_enhancers",
                return_value={22: _RecordingEnhancer("22", []), 24: _RecordingEnhancer("24", [])},
            ), patch(
                "scripts.youtube_enhance.cli.score_candidate_windows",
                return_value=_passing_candidate_metrics(),
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                run_candidates(workspace)

            manifest = read_json(workspace / "manifest.json")
            run_root = workspace / manifest["candidate_evidence"]["root"]
            private = read_json(run_root / "candidate-map.private.json")["blind_map"]
            blind_code = next(code for code, candidate in private.items() if candidate == "original")
            args = argparse.Namespace(
                workspace=workspace,
                blind_code=blind_code,
                segments=workspace / "analysis" / "segments-reviewed.json",
                pause="original",
                reviewer="Mukul",
            )
            different = workspace / "analysis" / "segments-different.json"
            different_rows = read_json(args.segments)
            different_rows[0]["notes"] = "would change reviewed evidence"
            write_json_atomic(different, different_rows)
            immutable_bytes = args.segments.read_bytes()
            manifest_bytes = (workspace / "manifest.json").read_bytes()
            mismatched_args = argparse.Namespace(**{**vars(args), "segments": different})
            with patch("scripts.youtube_enhance.cli._verify_diagnose_state"):
                with self.assertRaisesRegex(RuntimeError, "new candidate evidence run"):
                    run_approve(mismatched_args)
            self.assertEqual(args.segments.read_bytes(), immutable_bytes)
            self.assertEqual((workspace / "manifest.json").read_bytes(), manifest_bytes)

            with patch("scripts.youtube_enhance.cli._verify_diagnose_state"):
                run_approve(args)

            approved = read_json(workspace / "manifest.json")
            self.assertEqual(approved["selection"]["candidate_id"], "original")
            self.assertEqual(
                approved["approval"]["fingerprint"],
                render_approval_fingerprint(approved),
            )
            self.assertNotEqual(
                approved["approval"]["fingerprint"],
                approved["candidate_context_fingerprint"],
            )

            changed = read_json(args.segments)
            changed[0]["notes"] = "changed after listening"
            write_json_atomic(args.segments, changed)
            with patch(
                "scripts.youtube_enhance.cli.run_full_render",
                side_effect=AssertionError("render ran after segment mutation"),
            ), patch("scripts.youtube_enhance.cli._verify_diagnose_state"):
                with self.assertRaises(SystemExit):
                    main(["render", "--workspace", str(workspace)])

    def test_approval_replay_rejects_a_different_reviewer(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            _candidate_workspace(workspace)
            _generate_candidate_run(workspace)
            manifest = read_json(workspace / "manifest.json")
            run_root = workspace / manifest["candidate_evidence"]["root"]
            private = read_json(run_root / "candidate-map.private.json")["blind_map"]
            blind_code = next(code for code, candidate in private.items() if candidate == "original")
            args = argparse.Namespace(
                workspace=workspace,
                blind_code=blind_code,
                segments=workspace / "analysis" / "segments-reviewed.json",
                pause="original",
                reviewer="Mukul",
            )
            with patch("scripts.youtube_enhance.cli._verify_diagnose_state"):
                run_approve(args)

            changed_reviewer = argparse.Namespace(**{**vars(args), "reviewer": "Another reviewer"})
            with patch("scripts.youtube_enhance.cli._verify_diagnose_state"):
                with self.assertRaisesRegex(RuntimeError, "reviewer"):
                    run_approve(changed_reviewer)

    def test_conflicting_approvals_are_serialized_from_reload_through_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            _candidate_workspace(workspace)
            _generate_candidate_run(workspace)
            manifest = read_json(workspace / "manifest.json")
            run_root = workspace / manifest["candidate_evidence"]["root"]
            private = read_json(run_root / "candidate-map.private.json")["blind_map"]
            first_code, second_code = sorted(private)[:2]
            first_entered = threading.Event()
            second_entered = threading.Event()
            release_first = threading.Event()
            real_approve = cli_module.approve_candidate
            real_write = write_json_atomic
            write_gate = threading.Lock()
            outcomes = []

            def paused_approve(*args, **kwargs):
                if args[1] == first_code:
                    first_entered.set()
                    if not release_first.wait(5):
                        raise RuntimeError("approval concurrency probe timed out")
                else:
                    second_entered.set()
                return real_approve(*args, **kwargs)

            def serialized_write(*args, **kwargs):
                with write_gate:
                    return real_write(*args, **kwargs)

            def worker(code):
                args = argparse.Namespace(
                    workspace=workspace,
                    blind_code=code,
                    segments=workspace / "analysis" / "segments-reviewed.json",
                    pause="original",
                    reviewer="Mukul",
                )
                try:
                    run_approve(args)
                except Exception as error:
                    outcomes.append(("error", type(error)))
                else:
                    outcomes.append(("success", code))

            with patch(
                "scripts.youtube_enhance.cli._verify_diagnose_state"
            ), patch(
                "scripts.youtube_enhance.cli.approve_candidate", side_effect=paused_approve
            ), patch(
                "scripts.youtube_enhance.cli.write_json_atomic", side_effect=serialized_write
            ):
                first = threading.Thread(target=worker, args=(first_code,))
                second = threading.Thread(target=worker, args=(second_code,))
                first.start()
                self.assertTrue(first_entered.wait(5))
                second.start()
                second_entered.wait(0.25)
                release_first.set()
                first.join(5)
                second.join(5)

            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(sum(kind == "success" for kind, _ in outcomes), 1)
            self.assertEqual(sum(kind == "error" for kind, _ in outcomes), 1)

    def test_original_winner_full_render_reconstructs_headroom_mid_side_without_dfn(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            manifest, mid, side = _approved_original_workspace(workspace)
            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli._cached_enhancer",
                side_effect=AssertionError("Original winner invoked DFN"),
            ), patch(
                "scripts.youtube_enhance.cli.render_file",
                side_effect=AssertionError("Original winner rendered processed mid"),
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                run_full_render(workspace, manifest)

            committed = read_json(workspace / "manifest.json")
            adaptive = workspace / committed["render"]["adaptive_path"]
            values, rate = sf.read(adaptive, dtype="float32", always_2d=True)
            self.assertEqual(rate, 48000)
            np.testing.assert_array_equal(values, np.column_stack((mid + side, mid - side)))
            self.assertEqual(committed["render"]["reference_gain"], 0.75)
            completion = read_json(
                workspace / "final" / committed["active_run_id"] / "render-completion.json"
            )
            self.assertEqual(
                completion["preflight_space"], committed["preflight_space"]["render"]
            )

            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                side_effect=AssertionError("disk gate reached on render replay"),
            ), patch(
                "scripts.youtube_enhance.cli._cached_enhancer",
                side_effect=AssertionError("DFN reached on render replay"),
            ):
                run_full_render(workspace, read_json(workspace / "manifest.json"))

    def test_render_completion_persists_canonical_run_sample_and_path_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            committed = _rendered_original_workspace(workspace)
            run_id = committed["active_run_id"]
            completion_relative = f"final/{run_id}/render-completion.json"
            completion = read_json(workspace / completion_relative)

            self.assertEqual(completion.get("run_id"), run_id)
            self.assertEqual(
                completion.get("authoritative_samples"), committed["source"]["decoded_samples"]
            )
            self.assertEqual(completion["adaptive_path"], f"final/{run_id}/adaptive.wav")
            self.assertEqual(committed["render"].get("completion_path"), completion_relative)

    def test_render_manifest_must_equal_the_completion_derived_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            committed = _rendered_original_workspace(workspace)
            run_id = committed["active_run_id"]
            rogue = workspace / "work" / "rogue-adaptive.wav"
            sf.write(
                rogue,
                np.zeros((committed["source"]["decoded_samples"], 2), dtype=np.float32),
                48000,
                subtype="FLOAT",
            )
            completion_relative = f"final/{run_id}/render-completion.json"
            committed["render"].setdefault("completion_path", completion_relative)
            mutations = {
                "run-id": ("run_id", "other-run"),
                "adaptive-path": ("adaptive_path", rogue.relative_to(workspace).as_posix()),
                "adaptive-hash": ("adaptive_sha256", sha256_file(rogue)),
                "samples": ("samples", committed["source"]["decoded_samples"] - 1),
                "chunk-boundaries": ("chunk_boundaries", [4]),
                "reference-gain": ("reference_gain", 0.5),
                "completion-path": ("completion_path", "work/rogue-completion.json"),
                "completion-hash": ("completion_sha256", "0" * 64),
            }
            for name, (key, value) in mutations.items():
                with self.subTest(name=name):
                    changed = copy.deepcopy(committed)
                    changed["render"][key] = value
                    with self.assertRaises(RuntimeError):
                        _verify_render_state(workspace, changed)

            changed = copy.deepcopy(committed)
            changed["preflight_space"]["render"]["observed_free_bytes"] += 1
            with self.assertRaises(RuntimeError):
                _verify_render_state(workspace, changed)

    def test_render_completion_adaptive_path_must_name_its_canonical_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            committed = _rendered_original_workspace(workspace)
            run_id = committed["active_run_id"]
            marker = workspace / "final" / run_id / "render-completion.json"
            completion = read_json(marker)
            completion["adaptive_path"] = f"final/{run_id}/speech-mask.f32"
            write_json_atomic(marker, completion)
            committed["render"]["completion_sha256"] = sha256_file(marker)
            committed["render"].setdefault(
                "completion_path", f"final/{run_id}/render-completion.json"
            )

            with self.assertRaises(RuntimeError):
                _verify_render_state(workspace, committed)

    def test_render_completion_malformed_json_never_leaks_lookup_errors(self):
        malformed_values = (None, [], "completion", {"schema_version": 1})
        for value in malformed_values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                workspace = Path(folder)
                committed = _rendered_original_workspace(workspace)
                marker = workspace / committed["render"]["completion_path"]
                write_json_atomic(marker, value)
                committed["render"]["completion_sha256"] = sha256_file(marker)
                try:
                    _verify_render_state(workspace, committed)
                except RuntimeError:
                    pass
                except (KeyError, AttributeError, TypeError) as error:
                    self.fail(f"malformed render completion leaked {type(error).__name__}: {error}")
                else:
                    self.fail("malformed render completion was accepted")

    def test_render_rejects_reparse_final_seam_before_stage_work(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            manifest, _, _ = _approved_original_workspace(workspace)
            final_root = workspace / "final"
            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli._is_reparse_point",
                create=True,
                side_effect=lambda path: Path(path) == final_root,
            ), patch(
                "scripts.youtube_enhance.cli._cached_enhancer",
                side_effect=AssertionError("reparse path reached DFN"),
            ), patch(
                "scripts.youtube_enhance.cli.render_file",
                side_effect=AssertionError("reparse path reached rendering"),
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                with self.assertRaisesRegex(RuntimeError, "reparse"):
                    run_full_render(workspace, manifest)
            self.assertFalse(any((workspace / "work").glob("render-stage-*")))

    def test_workspace_rejects_reparse_hidden_before_dotdot_normalization(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sentinel = root / "sentinel-reparse"
            workspace = root / "workspace"
            sentinel.mkdir()
            workspace.mkdir()
            spellings = (
                sentinel / ".." / workspace.name,
                root / "unused-safe-component" / ".." / sentinel.name / ".." / workspace.name,
            )
            for spelling in spellings:
                with self.subTest(spelling=spelling):
                    observed = []

                    def observe(path):
                        candidate = Path(path)
                        observed.append(candidate)
                        return candidate == sentinel

                    with patch.object(cli_module, "_is_reparse_point", side_effect=observe):
                        with self.assertRaisesRegex(RuntimeError, "reparse"):
                            cli_module._canonical_workspace(spelling)
                    self.assertIn(sentinel, observed)

    @unittest.skipUnless(os.name == "nt", "Windows junction behavior")
    def test_render_never_publishes_through_an_actual_final_junction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / "workspace"
            outside = root / "outside"
            outside.mkdir()
            manifest, _, _ = _approved_original_workspace(workspace)
            junction = workspace / "final"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"junction unavailable: {result.stderr or result.stdout}")
            try:
                with patch(
                    "scripts.youtube_enhance.cli._verify_approved_state"
                ), patch(
                    "scripts.youtube_enhance.cli._cached_enhancer",
                    side_effect=AssertionError("Original winner invoked DFN"),
                ), patch(
                    "scripts.youtube_enhance.cli.render_file",
                    side_effect=AssertionError("Original winner rendered processed mid"),
                ), patch(
                    "scripts.youtube_enhance.cli.shutil.disk_usage",
                    return_value=_DiskUsage(100 * 1024**3),
                ):
                    try:
                        run_full_render(workspace, manifest)
                    except Exception:
                        pass
                    else:
                        self.fail("render accepted a final-root junction")
                self.assertEqual(list(outside.iterdir()), [])
            finally:
                if junction.exists():
                    os.rmdir(junction)

    def test_render_verification_rejects_every_extra_final_root_sibling(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            committed = _rendered_original_workspace(workspace)
            (workspace / "final" / "unrelated-partial-run").mkdir()
            with self.assertRaisesRegex(RuntimeError, "final"):
                _verify_render_state(workspace, committed)

    def test_delivery_probe_rejects_noncanonical_numeric_representations(self):
        base_stream = {
            "sample_rate": "48000", "channels": 2, "bit_rate": "192000",
            "codec_name": "mp3",
        }
        invalid = {
            "sample-rate-float": ("sample_rate", 48000.0),
            "sample-rate-whitespace": ("sample_rate", " 48000"),
            "sample-rate-sign": ("sample_rate", "+48000"),
            "channels-float": ("channels", 2.0),
            "channels-bool": ("channels", True),
            "channels-string": ("channels", "2"),
            "bit-rate-float": ("bit_rate", 192000.0),
            "bit-rate-bool": ("bit_rate", True),
            "bit-rate-junk": ("bit_rate", "192000bps"),
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "delivery.mp3"
            path.write_bytes(b"synthetic")
            for name, (field, value) in invalid.items():
                with self.subTest(name=name):
                    stream = dict(base_stream)
                    stream[field] = value
                    with patch(
                        "scripts.youtube_enhance.cli._stream_probe",
                        return_value=(stream, {"format_name": "mp3"}),
                    ), patch(
                        "scripts.youtube_enhance.cli._measure_loudness",
                        return_value={"integrated_lufs": -16.0, "true_peak_dbtp": -1.6, "lra": 3.0,
                                      "decode_ok": True},
                    ), patch(
                        "scripts.youtube_enhance.cli._decoded_frames", return_value=8
                    ):
                        try:
                            _measure_delivery("ffmpeg", "ffprobe", path, 8)
                        except RuntimeError:
                            pass
                        except Exception as error:
                            self.fail(f"probe parser leaked {type(error).__name__}: {error}")
                        else:
                            self.fail(f"probe parser accepted {name}")

    def test_stream_probe_rejects_every_malformed_json_shape_as_runtime_error(self):
        payloads = (
            [],
            {},
            {"streams": {}, "format": {}},
            {"streams": [None], "format": {}},
            {"streams": [{}, {}], "format": {}},
            {"streams": [{}], "format": []},
        )
        for payload in payloads:
            with self.subTest(payload=payload), patch(
                "scripts.youtube_enhance.cli.subprocess.run",
                return_value=type("Result", (), {"stdout": json.dumps(payload)})(),
            ):
                try:
                    _stream_probe("ffprobe", Path("synthetic.flac"))
                except RuntimeError:
                    pass
                except Exception as error:
                    self.fail(f"stream probe leaked {type(error).__name__}: {error}")
                else:
                    self.fail("stream probe accepted malformed JSON")

    def test_export_and_qa_commit_successful_disk_provenance_in_stage_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            manifest, _, _ = _approved_original_workspace(workspace)
            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ):
                run_full_render(workspace, manifest)

            def fake_normalize(_ffmpeg, source, destination, _expected):
                values, rate = sf.read(source, dtype="float32", always_2d=True)
                sf.write(destination, values, rate, subtype="FLOAT")

            def fake_export(_ffmpeg, master, flac, mp3, _measure):
                values, rate = sf.read(master, dtype="float32", always_2d=True)
                sf.write(flac, values, rate, subtype="PCM_24")
                mp3.write_bytes(b"synthetic mp3")
                return {
                    "delivery_master": str(master),
                    "flac": _delivery_metrics(flac, high_peak=False),
                    "mp3": _delivery_metrics(mp3, high_peak=False),
                }

            manifest = read_json(workspace / "manifest.json")
            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli._verify_render_state"
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ), patch(
                "scripts.youtube_enhance.cli.resolve_tool", side_effect=lambda name: name
            ), patch(
                "scripts.youtube_enhance.cli.normalize_two_pass", side_effect=fake_normalize
            ), patch(
                "scripts.youtube_enhance.cli.export_matched_pair", side_effect=fake_export
            ):
                run_export(workspace, manifest)

            committed = read_json(workspace / "manifest.json")
            run_directory = workspace / "final" / committed["active_run_id"]
            export_completion = read_json(run_directory / "export-completion.json")
            self.assertEqual(
                export_completion["preflight_space"], committed["preflight_space"]["export"]
            )

            qa_fixture = Path(folder) / "qa-fixture"
            qa_fixture.mkdir()
            report = _bound_qa_report(qa_fixture)
            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli._verify_render_state"
            ), patch(
                "scripts.youtube_enhance.cli._verify_export_state"
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                return_value=_DiskUsage(100 * 1024**3),
            ), patch(
                "scripts.youtube_enhance.cli._build_qa_report", return_value=report
            ):
                run_qa(workspace, committed)

            committed = read_json(workspace / "manifest.json")
            qa_report = read_json(run_directory / "qa-report.json")
            self.assertEqual(
                qa_report["orchestration"]["preflight_space"],
                committed["preflight_space"]["qa"],
            )
            self.assertEqual(
                qa_report["orchestration"]["approval_fingerprint"],
                committed["approval"]["fingerprint"],
            )

            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli._verify_render_state"
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                side_effect=AssertionError("disk gate reached on export replay"),
            ), patch(
                "scripts.youtube_enhance.cli.normalize_two_pass",
                side_effect=AssertionError("encoder reached on export replay"),
            ):
                run_export(workspace, committed)

            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli._verify_render_state"
            ), patch(
                "scripts.youtube_enhance.cli._verify_export_state"
            ), patch(
                "scripts.youtube_enhance.cli.shutil.disk_usage",
                side_effect=AssertionError("disk gate reached on QA replay"),
            ), patch(
                "scripts.youtube_enhance.cli._build_qa_report",
                side_effect=AssertionError("QA measurements reached on replay"),
            ):
                run_qa(workspace, committed)

            (run_directory / "unexpected-final-artifact.bin").write_bytes(b"unexpected")
            with patch(
                "scripts.youtube_enhance.cli._verify_approved_state"
            ), patch(
                "scripts.youtube_enhance.cli._verify_render_state"
            ):
                with self.assertRaisesRegex(RuntimeError, "unexpected final-run artifact"):
                    run_export(workspace, committed)

    def test_qa_state_is_exact_pending_and_canonical_to_the_active_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / "workspace"
            committed = _completed_qa_workspace(workspace, root / "qa-fixture")
            copied_report = workspace / "copied-qa-report.json"
            copied_checklist = workspace / "copied-listening-checklist.md"
            canonical_report = workspace / committed["qa"]["report_path"]
            canonical_checklist = workspace / committed["qa"]["checklist_path"]
            shutil.copyfile(canonical_report, copied_report)
            shutil.copyfile(canonical_checklist, copied_checklist)

            copied = copy.deepcopy(committed)
            copied["qa"].update(
                report_path=copied_report.relative_to(workspace).as_posix(),
                checklist_path=copied_checklist.relative_to(workspace).as_posix(),
                report_sha256=sha256_file(copied_report),
                checklist_sha256=sha256_file(copied_checklist),
            )
            completed = copy.deepcopy(committed)
            completed["qa"]["listening_status"] = "complete"
            unknown = copy.deepcopy(committed)
            unknown["qa"]["unexpected"] = True
            for name, changed in (
                ("copied-renamed-pair", copied),
                ("completed-status", completed),
                ("unknown-state-key", unknown),
            ):
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    _verify_qa_state(workspace, changed)

            report = read_json(canonical_report)
            report["listening_checklist"]["path"] = str(copied_checklist)
            write_json_atomic(canonical_report, report)
            internal_mismatch = copy.deepcopy(committed)
            internal_mismatch["qa"]["report_sha256"] = sha256_file(canonical_report)
            with self.assertRaises(RuntimeError):
                _verify_qa_state(workspace, internal_mismatch)

    def test_qa_paths_replay_across_relative_absolute_dot_and_cwd_spellings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / "workspace"
            relative = Path(os.path.relpath(workspace, Path.cwd()))
            committed = _completed_qa_workspace(
                workspace, root / "qa-fixture", qa_workspace=relative
            )
            run_directory = workspace / "final" / committed["active_run_id"]
            report = read_json(run_directory / "qa-report.json")
            self.assertEqual(
                Path(report["listening_checklist"]["path"]),
                (run_directory / "listening-checklist.md").absolute(),
            )
            self.assertTrue(all(
                Path(value).is_absolute() for value in report["artifact_paths"].values()
            ))

            spellings = (
                workspace.absolute(),
                relative,
                relative.parent / "unused-dot-segment" / ".." / relative.name,
            )
            for spelling in spellings:
                with self.subTest(spelling=spelling), patch(
                    "scripts.youtube_enhance.cli._verify_approved_state"
                ), patch(
                    "scripts.youtube_enhance.cli._verify_render_state"
                ), patch(
                    "scripts.youtube_enhance.cli._verify_export_state"
                ), patch(
                    "scripts.youtube_enhance.cli.shutil.disk_usage",
                    side_effect=AssertionError("QA replay reached disk gate"),
                ):
                    run_qa(spelling, committed)

            previous_cwd = Path.cwd()
            try:
                os.chdir(workspace.parent)
                with patch(
                    "scripts.youtube_enhance.cli._verify_approved_state"
                ), patch(
                    "scripts.youtube_enhance.cli._verify_render_state"
                ), patch(
                    "scripts.youtube_enhance.cli._verify_export_state"
                ):
                    run_qa(Path(workspace.name), committed)
            finally:
                os.chdir(previous_cwd)

    def test_artifact_records_reject_unknown_keys_and_noncanonical_raw_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            path = workspace / "mono.wav"
            sf.write(path, np.zeros(8, dtype=np.float32), 48000, subtype="FLOAT")
            valid = _artifact_record(workspace, path, channels=1)
            mutations = {}
            changed = dict(valid)
            changed["unexpected"] = "extra"
            mutations["unknown-key"] = changed
            for field, values in {
                "channels": (True, 1.0, "1"),
                "sample_rate": (True, 48000.0, "48000"),
                "frames": (True, 8.0, "8"),
                "path": (path, ""),
                "sha256": (valid["sha256"].lower(), True),
                "subtype": (True, 32),
            }.items():
                for value in values:
                    changed = dict(valid)
                    changed[field] = value
                    mutations[f"{field}-{value!r}"] = changed
            for name, changed in mutations.items():
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    _verify_record(
                        workspace, changed, frames=8, channels=1, subtype="FLOAT"
                    )

            generic = {"path": "mono.wav", "sha256": sha256_file(path), "extra": False}
            with self.assertRaises(RuntimeError):
                _verify_record(workspace, generic)


class Task8CarriedProofTests(unittest.TestCase):
    def test_qa_stage_preflight_subcases_are_isolated_before_hash_or_write(self):
        cases = ("shared", "existing", "final-alias")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                report = _bound_qa_report(root)
                qa = root / "qa-report.json"
                checklist = root / "listening-checklist.md"
                first = root / "qa.stage.json"
                second = root / "checklist.stage.md"
                if case == "shared":
                    stages = [first, first]
                elif case == "existing":
                    first.write_bytes(b"existing")
                    stages = [first, second]
                else:
                    stages = [qa, second]
                with patch(
                    "scripts.youtube_enhance.qa._stage", side_effect=stages
                ), patch(
                    "scripts.youtube_enhance.qa.sha256_file",
                    side_effect=AssertionError("hashing preceded stage preflight"),
                ):
                    with self.assertRaises(QaFailure):
                        publish_qa_pair(report, qa, checklist)
                self.assertFalse(qa.exists() or checklist.exists())

    def test_qa_collector_rejects_the_complete_raw_integer_matrix(self):
        integer_paths = (
            ("source_samples",), ("adaptive_samples",), ("master_probe", "frames"),
            ("flac_probe", "frames"), ("flac_probe", "sample_rate"),
            ("flac_probe", "channels"), ("flac_probe", "bits_per_raw_sample"),
            ("mp3_probe", "decoded_frames"), ("mp3_probe", "sample_rate"),
            ("mp3_probe", "channels"), ("mp3_probe", "bit_rate"),
            ("mp3_probe", "codec_delay_padding_samples"),
            ("integrity", "non_finite_samples"),
            ("integrity", "unexpected_zero_run_samples"),
            ("integrity", "reference_flat_top_runs"),
            ("integrity", "flat_top_runs"),
            ("integrity", "reference_pinned_samples"),
            ("integrity", "pinned_samples"),
            ("integrity", "reference_flat_top_runs_by_block", 0),
            ("integrity", "flat_top_runs_by_block", 0),
            ("integrity", "reference_flat_top_boundary_runs"),
            ("integrity", "flat_top_boundary_runs"),
            ("expected_boundary_samples", 0),
        )
        self.assertEqual(len(integer_paths), 23)
        for path in integer_paths:
            for bad in (True, 8.5, "8"):
                with self.subTest(path=path, bad=bad), tempfile.TemporaryDirectory() as folder:
                    kwargs = _qa_collect_kwargs(Path(folder), nonempty_boundary=True)
                    _set_nested(kwargs, path, bad)
                    with self.assertRaises(QaFailure):
                        collect_qa_report(**kwargs)

    def test_corrected_master_is_published_as_exact_float_48k_stereo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.wav"
            flac = root / "delivery.flac"
            mp3 = root / "delivery.mp3"
            samples = np.zeros((8, 2), dtype=np.float32)
            sf.write(master, samples, 48000, subtype="FLOAT")
            corrected = False

            def runner(command, **_kwargs):
                nonlocal corrected
                output = Path(command[-1])
                if "volume=" in " ".join(command):
                    corrected = True
                    sf.write(output, samples, 48000, subtype="FLOAT")
                else:
                    output.write_bytes(b"encoded")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            result = export_matched_pair(
                "ffmpeg", master, flac, mp3,
                lambda path: _delivery_metrics(path, high_peak=not corrected),
                runner=runner,
            )

            corrected_path = Path(result["delivery_master"])
            info = sf.info(corrected_path)
            self.assertTrue(corrected_path.is_file())
            self.assertEqual((info.frames, info.samplerate, info.channels, info.subtype), (8, 48000, 2, "FLOAT"))
            self.assertTrue(flac.is_file() and mp3.is_file())

    def test_corrected_third_link_failure_rolls_back_pair_and_preserves_racer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.wav"
            flac = root / "delivery.flac"
            mp3 = root / "delivery.mp3"
            corrected = root / "master-tp-corrected.wav"
            samples = np.zeros((8, 2), dtype=np.float32)
            sf.write(master, samples, 48000, subtype="FLOAT")
            correction_done = False

            def runner(command, **_kwargs):
                nonlocal correction_done
                output = Path(command[-1])
                if "volume=" in " ".join(command):
                    correction_done = True
                    sf.write(output, samples, 48000, subtype="FLOAT")
                else:
                    output.write_bytes(b"encoded")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            real_link = os.link

            def race_on_corrected(stage, destination):
                if Path(destination) == corrected:
                    corrected.write_bytes(b"racer")
                    raise FileExistsError("corrected-master race")
                return real_link(stage, destination)

            with patch("scripts.youtube_enhance.loudness.os.link", side_effect=race_on_corrected):
                with self.assertRaises(FileExistsError):
                    export_matched_pair(
                        "ffmpeg", master, flac, mp3,
                        lambda path: _delivery_metrics(path, high_peak=not correction_done),
                        runner=runner,
                    )
            self.assertFalse(flac.exists() or mp3.exists())
            self.assertEqual(corrected.read_bytes(), b"racer")

    def test_mp3_decoded_metadata_matrix_fails_closed(self):
        from scripts.youtube_enhance.loudness import _validate_decoded_delivery

        base = _delivery_metrics(Path("delivery.mp3"), high_peak=False)
        mutations = (
            ("decode_ok", False),
            ("sample_rate", 48000.0),
            ("channels", True),
            ("frames", "8"),
            ("bit_rate", 192000.0),
            ("codec_delay_padding_samples", True),
            ("codec_name", "flac"),
            ("container_name", "flac"),
            ("frames", 7),
        )
        self.assertEqual(len(mutations), 9)
        for key, bad in mutations:
            with self.subTest(key=key, bad=bad):
                metrics = dict(base)
                metrics[key] = bad
                with self.assertRaises(RuntimeError):
                    _validate_decoded_delivery(metrics, "MP3", 8)


def _minimal_manifest():
    return {
        "schema_version": 1,
        "source": {"sha256": "A" * 64, "decoded_samples": 8},
        "versions": {},
        "processing": {},
        "segment_map_sha256": "B" * 64,
        "candidate_report_sha256": "C" * 64,
        "approval": None,
    }


def _fingerprinted_manifest():
    return {
        "schema_version": 1,
        "source": {"sha256": "A" * 64, "decoded_samples": 8, "headroom_gain": 0.75},
        "versions": {"python": "3.11", "deepfilternet": "0.5.6"},
        "processing": {
            "sample_rate": 48000,
            "candidate_attenuations_db": [22, 24],
            "attenuation_db": 22,
            "pause_treatment": "original",
        },
        "working": {
            "original_mid": {"sha256": "1" * 64},
            "original_side": {"sha256": "2" * 64},
        },
        "candidate_context": {
            "segment_map_sha256": "3" * 64,
            "windows_reviewed_sha256": "4" * 64,
            "transitions_sha256": "5" * 64,
        },
        "candidate_context_fingerprint": "",
        "candidate_evidence": {
            "report_evidence_sha256": "6" * 64,
            "public_report_sha256": "7" * 64,
            "completion_sha256": "8" * 64,
            "private_map_sha256": "9" * 64,
            "blind_map_sha256": "A" * 64,
        },
        "segment_map_sha256": "3" * 64,
        "candidate_report_sha256": "7" * 64,
        "selection": {
            "blind_code": "B",
            "candidate_id": "adaptive-22",
            "pause_treatment": "original",
        },
        "approval": None,
    }


def _base_processing(halo_samples=4):
    return {
        "attenuation_db": None,
        "pause_treatment": "original",
        "candidate_attenuations_db": [22, 24],
        "sample_rate": 48000,
        "core_samples": 16,
        "halo_samples": halo_samples,
        "blend_samples": 2,
        "segment_fade_samples": 0,
        "pause_guard_samples": 2,
        "loudness_lufs": -16.0,
        "true_peak_dbtp": -1.5,
        "flac_bits": 24,
        "mp3_bitrate": 192000,
    }


def _diagnosed_workspace(workspace: Path):
    workspace.mkdir(parents=True, exist_ok=True)
    analysis = workspace / "analysis"
    review = analysis / "original-review"
    work = workspace / "work"
    analysis.mkdir()
    review.mkdir()
    work.mkdir()
    source_path = workspace / "source.webm"
    source_path.write_bytes(b"synthetic immutable source")
    values = np.linspace(-0.25, 0.25, 8, dtype=np.float32)
    stereo = np.column_stack((values, values))
    raw_path = work / "decoded-raw.wav"
    reference_path = work / "reference-stereo.wav"
    mid_path = work / "original-mid.wav"
    side_path = work / "original-side.wav"
    sf.write(raw_path, stereo, 48000, subtype="FLOAT")
    sf.write(reference_path, stereo, 48000, subtype="FLOAT")
    sf.write(mid_path, values, 48000, subtype="FLOAT")
    sf.write(side_path, np.zeros(8, dtype=np.float32), 48000, subtype="FLOAT")
    diagnostics_path = analysis / "diagnostics.json"
    proposed_path = analysis / "segments-proposed.json"
    transitions_path = analysis / "transitions.json"
    index_path = review / "index.html"
    write_json_atomic(diagnostics_path, {
        "schema_version": 1, "integrity": {}, "level": {}, "noise_floor": {},
        "noise_spectrum": {}, "tonal": [], "reverb": [], "bandwidth": [],
        "snr_by_band": [], "stereo": {}, "window_features": [],
        "representative_windows": [], "recommendations": [],
    })
    write_json_atomic(proposed_path, [{
        "start_sample": 0, "end_sample": 8, "label": "uncertain",
        "reviewed": False, "notes": "conservative complete proposal",
    }])
    write_json_atomic(transitions_path, [])
    index_path.write_text("synthetic review", encoding="utf-8")

    def record(path: Path):
        return {"path": path.relative_to(workspace).as_posix(), "sha256": sha256_file(path)}

    source_hash = sha256_file(source_path)
    manifest = {
        "schema_version": 1,
        "source": {
            "path": str(source_path), "sha256": source_hash,
            "bytes": source_path.stat().st_size, "decoded_samples": 8,
            "headroom_gain": 1.0, "decoded_peak": 0.25, "probe": {},
        },
        "versions": {
            "deepfilternet": "0.5.6", "model": "DeepFilterNet3",
            "python": "3.11", "numpy": "1.26", "soundfile": "0.14",
            "ffmpeg": "8.1.1", "ffprobe": "8.1.1",
        },
        "processing": _base_processing(),
        "working": {
            "raw_stereo": _artifact_record(workspace, raw_path, 2),
            "reference_stereo": _artifact_record(workspace, reference_path, 2),
            "original_mid": _artifact_record(workspace, mid_path, 1),
            "original_side": _artifact_record(workspace, side_path, 1),
        },
        "reference": {
            "representation": "headroom-adjusted-mid-side-v1",
            "source_sha256": source_hash,
            "headroom_gain": 1.0,
            "reference_stereo_sha256": sha256_file(reference_path),
            "original_mid_sha256": sha256_file(mid_path),
            "original_side_sha256": sha256_file(side_path),
        },
        "reports": {
            "diagnostics": record(diagnostics_path),
            "segments_proposed": record(proposed_path),
            "transitions": record(transitions_path),
            "original_review": {"index": record(index_path), "artifacts": []},
        },
        "approval": None,
        "active_run_id": None,
        "preflight_space": {
            "diagnose": {
                "observed_free_bytes": DISK_SPACE_REQUIREMENTS["diagnose"],
                "required_free_bytes": DISK_SPACE_REQUIREMENTS["diagnose"],
            }
        },
    }
    _verify_diagnose_state(workspace, manifest)
    return manifest


def _generate_candidate_run(workspace: Path) -> None:
    with patch(
        "scripts.youtube_enhance.cli._verify_diagnose_state"
    ), patch(
        "scripts.youtube_enhance.cli.REVIEW_WINDOW_SAMPLES", 8
    ), patch(
        "scripts.youtube_enhance.cli._candidate_enhancers",
        return_value={22: _RecordingEnhancer("22", []), 24: _RecordingEnhancer("24", [])},
    ), patch(
        "scripts.youtube_enhance.cli.score_candidate_windows",
        return_value=_passing_candidate_metrics(),
    ), patch(
        "scripts.youtube_enhance.cli.shutil.disk_usage",
        return_value=_DiskUsage(100 * 1024**3),
    ):
        run_candidates(workspace)


def _seed_changed_candidate_evidence(workspace: Path):
    _candidate_workspace(workspace)
    _generate_candidate_run(workspace)
    previous = read_json(workspace / "manifest.json")
    rows = read_json(workspace / "analysis" / "segments-reviewed.json")
    rows[0]["notes"] = "changed final boundary context"
    write_json_atomic(workspace / "analysis" / "segments-reviewed.json", rows)
    _generate_candidate_run(workspace)
    return previous


def _rendered_original_workspace(workspace: Path):
    manifest, _, _ = _approved_original_workspace(workspace)
    with patch(
        "scripts.youtube_enhance.cli._verify_approved_state"
    ), patch(
        "scripts.youtube_enhance.cli._cached_enhancer",
        side_effect=AssertionError("Original winner invoked DFN"),
    ), patch(
        "scripts.youtube_enhance.cli.render_file",
        side_effect=AssertionError("Original winner rendered processed mid"),
    ), patch(
        "scripts.youtube_enhance.cli.shutil.disk_usage",
        return_value=_DiskUsage(100 * 1024**3),
    ):
        run_full_render(workspace, manifest)
    return read_json(workspace / "manifest.json")


def _completed_qa_workspace(
    workspace: Path, qa_fixture: Path, *, qa_workspace: Path | None = None
):
    committed = _rendered_original_workspace(workspace)

    def fake_normalize(_ffmpeg, source, destination, _expected):
        values, rate = sf.read(source, dtype="float32", always_2d=True)
        sf.write(destination, values, rate, subtype="FLOAT")

    def fake_export(_ffmpeg, master, flac, mp3, _measure):
        values, rate = sf.read(master, dtype="float32", always_2d=True)
        sf.write(flac, values, rate, subtype="PCM_24")
        mp3.write_bytes(b"synthetic mp3")
        return {
            "delivery_master": str(master),
            "flac": _delivery_metrics(flac, high_peak=False),
            "mp3": _delivery_metrics(mp3, high_peak=False),
        }

    with patch(
        "scripts.youtube_enhance.cli._verify_approved_state"
    ), patch(
        "scripts.youtube_enhance.cli._verify_render_state"
    ), patch(
        "scripts.youtube_enhance.cli.shutil.disk_usage",
        return_value=_DiskUsage(100 * 1024**3),
    ), patch(
        "scripts.youtube_enhance.cli.resolve_tool", side_effect=lambda name: name
    ), patch(
        "scripts.youtube_enhance.cli.normalize_two_pass", side_effect=fake_normalize
    ), patch(
        "scripts.youtube_enhance.cli.export_matched_pair", side_effect=fake_export
    ):
        run_export(workspace, committed)

    committed = read_json(workspace / "manifest.json")
    qa_fixture.mkdir()
    report = _bound_qa_report(qa_fixture)
    with patch(
        "scripts.youtube_enhance.cli._verify_approved_state"
    ), patch(
        "scripts.youtube_enhance.cli._verify_render_state"
    ), patch(
        "scripts.youtube_enhance.cli._verify_export_state"
    ), patch(
        "scripts.youtube_enhance.cli.shutil.disk_usage",
        return_value=_DiskUsage(100 * 1024**3),
    ), patch(
        "scripts.youtube_enhance.cli._build_qa_report", return_value=report
    ):
        run_qa(qa_workspace or workspace, committed)
    return read_json(workspace / "manifest.json")


def _candidate_workspace(workspace: Path):
    (workspace / "analysis").mkdir(parents=True)
    (workspace / "work").mkdir()
    mid = np.arange(40, dtype=np.float32) / 100
    side = np.zeros(40, dtype=np.float32)
    mid_path = workspace / "work" / "original-mid.wav"
    side_path = workspace / "work" / "original-side.wav"
    raw_path = workspace / "work" / "decoded-raw.wav"
    sf.write(mid_path, mid, 48000, subtype="FLOAT")
    sf.write(side_path, side, 48000, subtype="FLOAT")
    sf.write(raw_path, np.column_stack((mid, mid)), 48000, subtype="FLOAT")
    write_json_atomic(workspace / "analysis" / "segments-reviewed.json", [
        {
            "start_sample": 0, "end_sample": 36, "label": "main_speech",
            "reviewed": True, "notes": "finalized before candidates",
        },
        {
            "start_sample": 36, "end_sample": 40, "label": "chanting_or_music",
            "reviewed": True, "notes": "reviewed final boundary absent from proposals",
        },
    ])
    write_json_atomic(workspace / "analysis" / "windows-reviewed.json", [
        {"window_id": "w1", "start_sample": 8, "end_sample": 16,
         "reviewed_label": "main_speech", "role": "clean_speech", "reviewed": True},
        {"window_id": "w2", "start_sample": 24, "end_sample": 32,
         "reviewed_label": "main_speech", "role": "noisy_speech", "reviewed": True},
    ])
    write_json_atomic(workspace / "analysis" / "transitions.json", [])
    diagnostics_path = workspace / "analysis" / "diagnostics.json"
    write_json_atomic(diagnostics_path, {
        "schema_version": 1, "integrity": {}, "level": {}, "noise_floor": {},
        "noise_spectrum": {}, "tonal": [], "reverb": [], "bandwidth": [],
        "snr_by_band": [], "stereo": {}, "window_features": [],
        "representative_windows": [
            {
                "window_id": "w1", "start_sample": 8, "label_hint": "main_speech",
                "floor_db": -60.0, "active_db": -20.0, "speech_confidence": 0.9,
                "timeline_third": 0, "role": "clean_speech",
            },
            {
                "window_id": "w2", "start_sample": 24, "label_hint": "main_speech",
                "floor_db": -58.0, "active_db": -18.0, "speech_confidence": 0.9,
                "timeline_third": 1, "role": "noisy_speech",
            },
        ],
        "recommendations": [],
    })
    manifest = {
        "schema_version": 1,
        "source": {"path": "source.webm", "sha256": "A" * 64, "decoded_samples": 40,
                   "headroom_gain": 1.0, "bytes": 1, "probe": {}},
        "versions": {
            "deepfilternet": "0.5.6", "model": "DeepFilterNet3",
            "python": "3.11", "numpy": "1.26", "soundfile": "0.14", "ffmpeg": "8.1.1",
            "ffprobe": "8.1.1",
        },
        "processing": _base_processing(),
        "working": {
            "raw_stereo": _artifact_record(workspace, raw_path, channels=2),
            "original_mid": _artifact_record(workspace, mid_path, channels=1),
            "original_side": _artifact_record(workspace, side_path, channels=1),
        },
        "reports": {
            "diagnostics": {
                "path": diagnostics_path.relative_to(workspace).as_posix(),
                "sha256": sha256_file(diagnostics_path),
            },
        },
        "reference": {},
        "approval": None,
        "active_run_id": None,
        "preflight_space": {},
    }
    write_json_atomic(workspace / "manifest.json", manifest)
    return manifest, mid


def _artifact_record(workspace: Path, path: Path, channels: int):
    return {
        "path": path.relative_to(workspace).as_posix(),
        "sha256": sha256_file(path),
        "channels": channels,
        "sample_rate": 48000,
        "frames": sf.info(path).frames,
        "subtype": sf.info(path).subtype,
    }


def _passing_candidate_metrics():
    base = {
        "natural_anchor_mean": 0.9,
        "identity_mean": 0.9,
        "longest_new_zero_run_samples": 0,
        "sample_count_equal": True,
        "non_finite_samples": 0,
        "peak": 0.9,
    }
    return {name: dict(base) for name in ("original", "adaptive-22", "adaptive-24")}


def _approved_original_workspace(workspace: Path):
    (workspace / "analysis").mkdir(parents=True)
    (workspace / "work").mkdir()
    mid = np.array([0.1, -0.2, 0.3, -0.4, 0.2, -0.1, 0.0, 0.05], dtype=np.float32)
    side = np.array([0.01, 0.02, -0.01, 0.0, 0.03, -0.02, 0.01, 0.0], dtype=np.float32)
    mid_path = workspace / "work" / "original-mid.wav"
    side_path = workspace / "work" / "original-side.wav"
    sf.write(mid_path, mid, 48000, subtype="FLOAT")
    sf.write(side_path, side, 48000, subtype="FLOAT")
    write_json_atomic(workspace / "analysis" / "segments-reviewed.json", [{
        "start_sample": 0, "end_sample": len(mid), "label": "main_speech",
        "reviewed": True, "notes": "approved",
    }])
    manifest = _fingerprinted_manifest()
    manifest["source"].update(decoded_samples=len(mid), headroom_gain=0.75)
    manifest["processing"] = _base_processing(halo_samples=2)
    manifest["processing"].update(attenuation_db=None, pause_treatment="original")
    manifest["working"] = {
        "original_mid": _artifact_record(workspace, mid_path, 1),
        "original_side": _artifact_record(workspace, side_path, 1),
    }
    manifest["reference"] = {
        "representation": "headroom-adjusted-mid-side-v1",
        "source_sha256": manifest["source"]["sha256"],
        "headroom_gain": 0.75,
        "original_mid_sha256": sha256_file(mid_path),
        "original_side_sha256": sha256_file(side_path),
    }
    manifest["reports"] = {}
    manifest["segment_map_sha256"] = sha256_file(workspace / "analysis" / "segments-reviewed.json")
    manifest["selection"] = {
        "blind_code": "A", "candidate_id": "original", "pause_treatment": "original",
    }
    manifest["candidate_context_fingerprint"] = candidate_context_fingerprint(manifest)
    manifest["approval"] = {
        "blind_code": "A", "candidate_id": "original", "pause_treatment": "original",
        "reviewer": "Mukul", "approved_at": "2026-08-21T12:00:00Z",
        "fingerprint": render_approval_fingerprint(manifest),
        "evidence_sha256": manifest["candidate_evidence"]["report_evidence_sha256"],
    }
    manifest["preflight_space"] = {}
    manifest["active_run_id"] = None
    write_json_atomic(workspace / "manifest.json", manifest)
    return manifest, mid, side


def _delivery_metrics(path: Path, high_peak: bool):
    is_mp3 = path.suffix.lower() == ".mp3"
    return {
        "true_peak_dbtp": -1.4 if high_peak and is_mp3 else -1.6,
        "integrated_lufs": -16.0,
        "lra": 3.0,
        "decode_ok": True,
        "sample_rate": 48000,
        "channels": 2,
        "frames": 8,
        "bits_per_raw_sample": 0 if is_mp3 else 24,
        "codec_name": "mp3" if is_mp3 else "flac",
        "container_name": "mp3" if is_mp3 else "flac",
        "bit_rate": 192000 if is_mp3 else 0,
        "codec_delay_padding_samples": 0,
    }


def _qa_collect_kwargs(root: Path, *, nonempty_boundary: bool):
    paths = {name: root / f"{name}.bin" for name in ("source", "adaptive", "master", "flac", "mp3")}
    for name, path in paths.items():
        path.write_bytes(name.encode("ascii"))
    return {
        "source_samples": 8,
        "adaptive_samples": 8,
        "master_probe": {"frames": 8},
        "flac_probe": {"frames": 8, "sample_rate": 48000, "channels": 2,
                       "bits_per_raw_sample": 24, "codec_name": "flac", "container_name": "flac"},
        "mp3_probe": {"decoded_frames": 8, "sample_rate": 48000, "channels": 2,
                      "bit_rate": 192000, "codec_delay_padding_samples": 0,
                      "codec_name": "mp3", "container_name": "mp3"},
        "flac_metrics": {"integrated_lufs": -16.0, "true_peak_dbtp": -1.6,
                         "lra": 3.0, "decode_ok": True},
        "mp3_metrics": {"integrated_lufs": -16.0, "true_peak_dbtp": -1.6,
                        "decode_ok": True},
        "flac_path": paths["flac"],
        "mp3_path": paths["mp3"],
        "integrity": {
            "non_finite_samples": 0, "unexpected_zero_run_samples": 0,
            "reference_flat_top_runs": 0, "flat_top_runs": 0,
            "reference_pinned_samples": 0, "pinned_samples": 0,
            "reference_flat_top_runs_by_block": [0], "flat_top_runs_by_block": [0],
            "reference_flat_top_boundary_runs": 0, "flat_top_boundary_runs": 0,
            "crest_db": 1.0,
        },
        "boundary_scores": ([{"boundary_sample": 4, "jump": 0.0,
                              "jump_over_local_median_db": 0.0}] if nonempty_boundary else []),
        "candidate_window_scores": [],
        "expected_boundary_samples": [4] if nonempty_boundary else [],
        "expected_candidate_window_ids": [],
        "source_path": paths["source"],
        "adaptive_path": paths["adaptive"],
        "delivery_master_path": paths["master"],
        "listening_checklist_path": root / "listening-checklist.md",
    }


def _bound_qa_report(root: Path):
    return collect_qa_report(**_qa_collect_kwargs(root, nonempty_boundary=False))


def _set_nested(mapping, path, value):
    current = mapping
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


if __name__ == "__main__":
    unittest.main()
