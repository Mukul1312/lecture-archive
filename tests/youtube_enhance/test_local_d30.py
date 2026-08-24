import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from scripts.youtube_enhance.manifest import write_json_atomic
from scripts.youtube_enhance.source import from_mid_side, sha256_file


class LocalD30Tests(unittest.TestCase):
    tool_versions = {
        "deepfilternet": "0.5.6",
        "deepfilter": "DeepFilterNet 0.5.6",
        "python": "Python 3.11",
        "numpy": "1.26",
        "soundfile": "0.14",
        "ffmpeg": "ffmpeg 8.1",
        "ffprobe": "ffprobe 8.1",
    }

    def _workspace(self, root: Path) -> tuple[Path, Path, np.ndarray, np.ndarray]:
        workspace = root / "workspace"
        work = workspace / "work"
        work.mkdir(parents=True)
        source = workspace / "source.bin"
        source.write_bytes(b"source PCM provenance")
        mid = np.array([0.10, -0.20, 0.30, -0.40, 0.25, -0.15, 0.05, 0.20], dtype=np.float32)
        side = np.array([0.02, 0.03, -0.01, -0.04, 0.01, 0.02, -0.03, 0.04], dtype=np.float32)
        sf.write(work / "original-mid.wav", mid, 48000, subtype="FLOAT")
        sf.write(work / "original-side.wav", side, 48000, subtype="FLOAT")
        sf.write(work / "decoded-raw.wav", from_mid_side(mid, side), 48000, subtype="FLOAT")
        manifest = {
            "source": {"path": str(source), "sha256": sha256_file(source), "decoded_samples": len(mid)},
            "reference": {
                "original_mid_sha256": sha256_file(work / "original-mid.wav"),
                "original_side_sha256": sha256_file(work / "original-side.wav"),
            },
            "working": {
                "original_mid": {"path": "work/original-mid.wav", "sha256": sha256_file(work / "original-mid.wav")},
                "original_side": {"path": "work/original-side.wav", "sha256": sha256_file(work / "original-side.wav")},
                "raw_stereo": {"path": "work/decoded-raw.wav", "sha256": sha256_file(work / "decoded-raw.wav")},
            },
            "processing": {"core_samples": 4, "halo_samples": 1, "blend_samples": 1},
            "versions": {
                "deepfilternet": self.tool_versions["deepfilternet"],
                "model": self.tool_versions["deepfilter"],
                "python": self.tool_versions["python"], "numpy": self.tool_versions["numpy"],
                "soundfile": self.tool_versions["soundfile"], "ffmpeg": self.tool_versions["ffmpeg"],
                "ffprobe": self.tool_versions["ffprobe"],
            },
        }
        write_json_atomic(workspace / "manifest.json", manifest)
        model = root / "DeepFilterNet3"
        (model / "checkpoints").mkdir(parents=True)
        (model / "config.ini").write_text("[model]\nname=DeepFilterNet3\n", encoding="utf-8")
        (model / "checkpoints" / "model_120.ckpt.best").write_bytes(b"checkpoint")
        return workspace, model, mid, side

    @staticmethod
    def _delivery_metrics(kind: str, frames: int) -> dict:
        return {
            "integrated_lufs": -16.0,
            "true_peak_dbtp": -1.6,
            "lra": 2.0,
            "decode_ok": True,
            "sample_rate": 48000,
            "channels": 2,
            "frames": frames,
            "bits_per_raw_sample": 24 if kind == "flac" else 0,
            "codec_name": kind,
            "container_name": kind,
            "bit_rate": 0 if kind == "flac" else 192000,
            "codec_delay_padding_samples": 0,
        }

    def test_local_d30_reconstructs_processed_mid_with_untouched_side_and_writes_pending_provenance(self):
        from scripts.youtube_enhance import local_d30

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace, model, mid, side = self._workspace(root)
            manifest_before = (workspace / "manifest.json").read_bytes()

            def fake_render(source, destination, _enhancer, _rate, attenuation, *_args):
                self.assertEqual(attenuation, 30)
                values, rate = sf.read(source, dtype="float32")
                sf.write(destination, values * 0.5, rate, subtype="FLOAT")
                return {"samples": len(values), "sample_rate": rate, "boundaries": []}

            def fake_normalize(_ffmpeg, source, destination, expected):
                values, rate = sf.read(source, dtype="float32", always_2d=True)
                self.assertEqual(expected, len(values))
                sf.write(destination, values, rate, subtype="FLOAT")
                return {"input_i": "-16.0"}

            def fake_export(_ffmpeg, master, flac, mp3, _measure):
                values, rate = sf.read(master, dtype="float32", always_2d=True)
                sf.write(flac, values, rate, subtype="PCM_24")
                mp3.write_bytes(b"test mp3 delivery")
                return {
                    "delivery_master": str(master),
                    "flac": self._delivery_metrics("flac", len(values)),
                    "mp3": self._delivery_metrics("mp3", len(values)),
                }

            with patch.object(local_d30, "AUTHORITATIVE_SOURCE_SHA256", sha256_file(workspace / "source.bin")), patch.object(
                local_d30, "AUTHORITATIVE_ORIGINAL_MID_SHA256", sha256_file(workspace / "work" / "original-mid.wav")
            ), patch.object(local_d30, "AUTHORITATIVE_FRAMES", len(mid)
            ), patch.object(local_d30, "resolve_tool", side_effect=lambda name: name), patch.object(
                local_d30, "_current_tool_versions", return_value=self.tool_versions
            ), patch.object(
                local_d30, "render_file", side_effect=fake_render
            ), patch.object(local_d30, "normalize_two_pass", side_effect=fake_normalize), patch.object(
                local_d30, "export_matched_pair", side_effect=fake_export
            ):
                completion = local_d30.run_local_d30(workspace, model)

            delivery = workspace / "deliveries" / "local-d30-review"
            adaptive, rate = sf.read(delivery / "adaptive.wav", dtype="float32", always_2d=True)
            self.assertEqual(rate, 48000)
            np.testing.assert_allclose(adaptive, np.column_stack((mid * 0.5 + side, mid * 0.5 - side)), atol=1e-7)
            self.assertEqual((workspace / "manifest.json").read_bytes(), manifest_before)
            self.assertEqual(completion["mode"], "dfn30_parallel")
            self.assertEqual(completion["attenuation_db"], 30)
            self.assertEqual(completion["source_sha256"], sha256_file(workspace / "source.bin"))
            self.assertEqual(completion["source_pcm_sha256"], sha256_file(workspace / "work" / "decoded-raw.wav"))
            self.assertEqual(completion["original_mid_sha256"], sha256_file(workspace / "work" / "original-mid.wav"))
            self.assertEqual(completion["model_hashes"], {
                "config.ini": sha256_file(model / "config.ini"),
                "checkpoints/model_120.ckpt.best": sha256_file(model / "checkpoints" / "model_120.ckpt.best"),
            })
            self.assertEqual(completion["listening_status"], "pending")
            self.assertEqual(completion["tool_versions"]["ffprobe"], "ffprobe 8.1")
            self.assertEqual(json.loads((delivery / "qa-report.json").read_text())["listening_checklist"]["status"], "pending")
            self.assertTrue((delivery / "listening-checklist.md").is_file())
            self.assertTrue((delivery / "Haladhara-lecture-D30-review.flac").is_file())
            self.assertTrue((delivery / "Haladhara-lecture-D30-review.mp3").is_file())

    def test_local_d30_refuses_a_preexisting_review_delivery_before_rendering(self):
        from scripts.youtube_enhance import local_d30

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace, model, _mid, _side = self._workspace(root)
            delivery = workspace / "deliveries" / "local-d30-review"
            delivery.mkdir(parents=True)
            manifest_before = (workspace / "manifest.json").read_bytes()
            with patch.object(local_d30, "render_file", side_effect=AssertionError("render reached")):
                with self.assertRaisesRegex(FileExistsError, "local-d30-review"):
                    local_d30.run_local_d30(workspace, model)
            self.assertEqual((workspace / "manifest.json").read_bytes(), manifest_before)

    def test_local_d30_uses_the_short_dedicated_d30_cache_root(self):
        from scripts.youtube_enhance import local_d30

        class StopAfterRenderRoot(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace, model, mid, _side = self._workspace(root)
            observed = []

            def stop_after_recording(*args):
                observed.append(args[-1])
                raise StopAfterRenderRoot()

            with patch.object(local_d30, "AUTHORITATIVE_SOURCE_SHA256", sha256_file(workspace / "source.bin")), patch.object(
                local_d30, "AUTHORITATIVE_ORIGINAL_MID_SHA256", sha256_file(workspace / "work" / "original-mid.wav")
            ), patch.object(local_d30, "AUTHORITATIVE_FRAMES", len(mid)
            ), patch.object(local_d30, "resolve_tool", side_effect=lambda name: name), patch.object(
                local_d30, "_current_tool_versions", return_value=self.tool_versions
            ), patch.object(local_d30, "render_file", side_effect=stop_after_recording):
                with self.assertRaises(StopAfterRenderRoot):
                    local_d30.run_local_d30(workspace, model)

            self.assertEqual(observed, [workspace / "d30"])

    def test_bound_inputs_rejects_same_format_side_or_source_pcm_hash_changes(self):
        from scripts.youtube_enhance import local_d30

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace, _model, mid, side = self._workspace(root)
            manifest = json.loads((workspace / "manifest.json").read_text())
            with patch.object(local_d30, "AUTHORITATIVE_SOURCE_SHA256", sha256_file(workspace / "source.bin")), patch.object(
                local_d30, "AUTHORITATIVE_ORIGINAL_MID_SHA256", sha256_file(workspace / "work" / "original-mid.wav")
            ), patch.object(local_d30, "AUTHORITATIVE_FRAMES", len(mid)):
                for filename, values in (
                    ("original-side.wav", side * 0.5),
                    ("decoded-raw.wav", from_mid_side(mid * 0.5, side)),
                ):
                    with self.subTest(filename=filename):
                        sf.write(workspace / "work" / filename, values, 48000, subtype="FLOAT")
                        with self.assertRaisesRegex(RuntimeError, "hash"):
                            local_d30._require_bound_inputs(workspace)
                        sf.write(workspace / "work" / filename, side if filename == "original-side.wav" else from_mid_side(mid, side), 48000, subtype="FLOAT")
            self.assertEqual(json.loads((workspace / "manifest.json").read_text()), manifest)

    def test_current_tool_versions_queries_each_executable(self):
        from scripts.youtube_enhance import local_d30

        if not hasattr(local_d30, "_current_tool_versions"):
            self.fail("local runner must query current executable versions")

        observed = []

        def fake_run(command, **_):
            observed.append(command)
            return type("Result", (), {"stdout": f"{command[0]} version\n", "stderr": ""})()

        with patch.object(local_d30.subprocess, "run", side_effect=fake_run), patch.object(
            local_d30.importlib.metadata, "version", side_effect=lambda package: {"DeepFilterNet": "0.5.6", "numpy": "1.26", "soundfile": "0.14"}[package]
        ):
            versions = local_d30._current_tool_versions("deepFilter.exe", "ffmpeg.exe", "ffprobe.exe")

        self.assertEqual(observed[0], ["deepFilter.exe", "--version"])
        self.assertEqual(observed[2], ["ffmpeg.exe", "-version"])
        self.assertEqual(observed[3], ["ffprobe.exe", "-version"])
        self.assertEqual(versions["deepfilter"], "deepFilter.exe version")
        self.assertEqual(versions["ffmpeg"], "ffmpeg.exe version")
        self.assertEqual(versions["ffprobe"], "ffprobe.exe version")

    def test_local_d30_rejects_stale_workspace_tool_versions_before_render(self):
        from scripts.youtube_enhance import local_d30

        if not hasattr(local_d30, "_current_tool_versions"):
            self.fail("local runner must reject stale executable versions")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace, model, mid, _side = self._workspace(root)
            changed = dict(self.tool_versions, ffmpeg="ffmpeg changed")
            with patch.object(local_d30, "AUTHORITATIVE_SOURCE_SHA256", sha256_file(workspace / "source.bin")), patch.object(
                local_d30, "AUTHORITATIVE_ORIGINAL_MID_SHA256", sha256_file(workspace / "work" / "original-mid.wav")
            ), patch.object(local_d30, "AUTHORITATIVE_FRAMES", len(mid)
            ), patch.object(local_d30, "resolve_tool", side_effect=lambda name: name), patch.object(
                local_d30, "_current_tool_versions", return_value=changed
            ), patch.object(local_d30, "render_file", side_effect=AssertionError("render reached")):
                with self.assertRaisesRegex(RuntimeError, "tool-version"):
                    local_d30.run_local_d30(workspace, model)

    def test_delivery_path_rejects_a_reparse_delivery_ancestor_before_reading_workspace(self):
        from scripts.youtube_enhance import local_d30

        if not hasattr(local_d30, "_safe_delivery_directory"):
            self.fail("local runner must validate delivery ancestry")
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            workspace.mkdir()
            delivery_parent = workspace / "deliveries"
            delivery_parent.mkdir()
            with patch.object(local_d30, "_is_reparse_point", side_effect=lambda path: Path(path) == delivery_parent):
                with self.assertRaisesRegex(RuntimeError, "reparse"):
                    local_d30._safe_delivery_directory(workspace)

    def test_delivery_path_rejects_an_actual_symlinked_delivery_ancestor(self):
        from scripts.youtube_enhance import local_d30

        if not hasattr(local_d30, "_safe_delivery_directory"):
            self.fail("local runner must validate delivery ancestry")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace, outside = root / "workspace", root / "outside"
            workspace.mkdir()
            outside.mkdir()
            try:
                os.symlink(outside, workspace / "deliveries", target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaisesRegex(RuntimeError, "reparse"):
                local_d30._safe_delivery_directory(workspace)
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
