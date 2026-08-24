import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from scripts.youtube_enhance.dfn import (
    CacheMiss,
    CachedDfnAdapter,
    DfnAdapter,
    LatencyUnmeasurable,
    Processed,
    build_render_context_key,
    build_dfn_command,
    estimate_latency,
    load_validated_cache,
)
from scripts.youtube_enhance.manifest import cache_key


class _IdentityEnhancer:
    def __init__(self):
        self.calls = 0

    def enhance(self, samples, sample_rate, attenuation_db, work_directory):
        self.calls += 1
        return Processed(samples.copy(), 0, ("fake-dfn",), "completed", "")


class DfnTests(unittest.TestCase):
    versions = {
        "deepfilternet": "dfn-1",
        "model": "model-1",
        "python": "3.11",
        "numpy": "2.0",
        "soundfile": "0.13",
        "ffmpeg": "7.0",
    }

    def test_command_uses_only_the_selected_parallel_attenuation(self):
        command = build_dfn_command(
            "deepFilter.exe", Path("in.wav"), Path("out"), attenuation_db=22
        )
        self.assertEqual(
            command,
            [
                "deepFilter.exe", "-o", "out", "--no-suffix",
                "--atten-lim", "22", "in.wav",
            ],
        )

    def test_explicit_model_directory_is_passed_without_changing_omitted_command(self):
        source = np.linspace(-0.2, 0.2, 32, dtype=np.float32)
        model = Path("DeepFilterNet3")
        self.assertEqual(
            build_dfn_command(
                "deepFilter.exe", Path("in.wav"), Path("out"), 30, model_directory=model
            ),
            [
                "deepFilter.exe", "-o", "out", "--no-suffix", "--model-base-dir",
                "DeepFilterNet3", "--atten-lim", "30", "in.wav",
            ],
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            observed = []

            def invoke(command, **_):
                observed.append(command)
                sf.write(Path(command[2]) / "chunk.wav", source, 48000, subtype="FLOAT")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("scripts.youtube_enhance.dfn.subprocess.run", side_effect=invoke):
                DfnAdapter("deepFilter.exe", "model-1", model_directory=model).enhance(
                    source, 48000, 30, root / "explicit"
                )
                DfnAdapter("deepFilter.exe", "model-1").enhance(
                    source, 48000, 30, root / "omitted"
                )

        self.assertEqual(
            observed[0][3:7],
            [
                "--no-suffix", "--model-base-dir", str(model), "--atten-lim",
            ],
        )
        self.assertNotIn("--model-base-dir", observed[1])

    def test_latency_estimator_finds_a_known_delay(self):
        rng = np.random.default_rng(7)
        reference = rng.normal(0, 0.1, 8000).astype(np.float32)
        delayed = np.concatenate((np.zeros(31, dtype=np.float32), reference[:-31]))
        self.assertEqual(estimate_latency(reference, delayed, max_lag_samples=100), 31)

    def test_latency_estimator_rejects_silent_constant_and_ambiguous_material(self):
        with self.assertRaises(LatencyUnmeasurable):
            estimate_latency(np.zeros(32, dtype=np.float32), np.zeros(32, dtype=np.float32), 10)
        with self.assertRaises(LatencyUnmeasurable):
            estimate_latency(np.ones(32, dtype=np.float32), np.ones(32, dtype=np.float32), 10)
        with self.assertRaises(LatencyUnmeasurable):
            estimate_latency(
                np.array([0.0, 0.0, 1.0], dtype=np.float32),
                np.array([1.0, 1.0, 0.0], dtype=np.float32),
                2,
            )

    def test_adapter_rejects_shorter_or_longer_model_output_before_latency(self):
        source = np.linspace(-0.2, 0.2, 32, dtype=np.float32)
        for output in (source[:-1], np.append(source, 0.0)):
            with self.subTest(output_samples=len(output)), tempfile.TemporaryDirectory() as folder:
                def invoke(command, **_):
                    sf.write(Path(command[2]) / "chunk.wav", output, 48000, subtype="FLOAT")
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

                with patch("scripts.youtube_enhance.dfn.subprocess.run", side_effect=invoke):
                    with self.assertRaisesRegex(RuntimeError, "sample count"):
                        DfnAdapter("deepFilter.exe", "model-1").enhance(
                            source, 48000, 22, Path(folder)
                        )

    def test_non_allocation_model_failure_is_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            failed = SimpleNamespace(returncode=1, stdout="ordinary model failure", stderr="")
            with patch("scripts.youtube_enhance.dfn.subprocess.run", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "DeepFilterNet failed") as error:
                    DfnAdapter("deepFilter.exe", "model-1").enhance(
                        np.arange(32, dtype=np.float32), 48000, 22, Path(folder)
                    )
        self.assertNotIn("DfnAllocationError", type(error.exception).__name__)

    def test_cache_requires_key_and_artifact_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "chunk.wav"
            artifact.write_bytes(b"valid-audio-artifact")
            sidecar = root / "chunk.json"
            sidecar.write_text(
                json.dumps({"cache_key": "expected", "artifact_sha256": "wrong"}),
                encoding="utf-8",
            )
            with self.assertRaises(CacheMiss):
                load_validated_cache(sidecar, artifact, "expected")

    def test_chunk_cache_rejects_a_stereo_artifact_even_with_matching_hash(self):
        samples = np.linspace(-0.1, 0.1, 16, dtype=np.float32)
        inner = _IdentityEnhancer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cached = CachedDfnAdapter(inner, {"render_context_key": "context"}, self.versions)
            cached.enhance(samples, 48000, 22, root)
            sidecar = next(root.glob("*/enhanced.json"))
            artifact = sidecar.with_name("enhanced.wav")
            sf.write(artifact, np.column_stack((samples, samples)), 48000, subtype="FLOAT")
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            metadata["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest().upper()
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")
            cached.enhance(samples, 48000, 22, root)
        self.assertEqual(inner.calls, 2)

    def test_chunk_cache_sidecar_retains_bounded_execution_metadata(self):
        samples = np.arange(16, dtype=np.float32)
        inner = _IdentityEnhancer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            CachedDfnAdapter(inner, {"render_context_key": "context"}, self.versions).enhance(
                samples, 48000, 22, root
            )
            metadata = json.loads(next(root.glob("*/enhanced.json")).read_text(encoding="utf-8"))
        self.assertEqual(metadata["command"], ["fake-dfn"])
        self.assertEqual(metadata["stdout"], "completed")
        self.assertEqual(metadata["stderr"], "")

    def test_chunk_cache_rejects_tampered_declared_or_actual_frame_metadata(self):
        samples = np.arange(16, dtype=np.float32)
        inner = _IdentityEnhancer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cached = CachedDfnAdapter(inner, {"render_context_key": "context"}, self.versions)
            cached.enhance(samples, 48000, 22, root)
            sidecar = next(root.glob("*/enhanced.json"))
            artifact = sidecar.with_name("enhanced.wav")
            for field, wrong_value in (
                ("sample_rate", 44100),
                ("channels", 2),
                ("input_samples", 15),
                ("output_samples", 15),
            ):
                with self.subTest(field=field):
                    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                    metadata[field] = wrong_value
                    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
                    cached.enhance(samples, 48000, 22, root)
            sf.write(artifact, samples, 44100, subtype="FLOAT")
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            metadata["sample_rate"] = 48000
            metadata["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest().upper()
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")
            cached.enhance(samples, 48000, 22, root)
            sf.write(artifact, samples[:-1], 48000, subtype="FLOAT")
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            metadata["output_samples"] = 15
            metadata["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest().upper()
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")
            cached.enhance(samples, 48000, 22, root)
        self.assertEqual(inner.calls, 7)

    def test_chunk_cache_refuses_to_write_mismatched_inner_frame_count(self):
        class ShortEnhancer:
            def enhance(self, samples, sample_rate, attenuation_db, work_directory):
                return Processed(samples[:-1], 0)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cached = CachedDfnAdapter(ShortEnhancer(), {"render_context_key": "context"}, self.versions)
            with self.assertRaisesRegex(RuntimeError, "sample count"):
                cached.enhance(np.arange(16, dtype=np.float32), 48000, 22, root)
            self.assertFalse(any(root.glob("*/enhanced.json")))

    def test_render_context_uses_sound_changing_parameters_and_input_hashes(self):
        versions = self.versions
        expected = cache_key(
            "dfn-render-context",
            {"source_sha256": "SOURCE", "original_mid_pcm_sha256": "MID"},
            {
                "attenuation_db": 22,
                "sample_rate": 48000,
                "core_samples": 480000,
                "halo_samples": 96000,
                "blend_samples": 24000,
                "latency_policy": "envelope-xcorr-v1",
                "segment_map_sha256": "SEGMENTS",
            },
            versions,
        )
        self.assertEqual(
            build_render_context_key(
                "SOURCE", "MID", 22, 48000, 480000, 96000, 24000, "SEGMENTS", versions
            ),
            expected,
        )

    def test_render_context_rejects_missing_versions_and_each_version_invalidates(self):
        baseline = build_render_context_key(
            "SOURCE", "MID", 22, 48000, 480000, 96000, 24000, "SEGMENTS", self.versions
        )
        for key in self.versions:
            with self.subTest(missing=key):
                incomplete = dict(self.versions)
                del incomplete[key]
                with self.assertRaisesRegex(ValueError, key):
                    build_render_context_key(
                        "SOURCE", "MID", 22, 48000, 480000, 96000, 24000, "SEGMENTS", incomplete
                    )
            with self.subTest(invalidator=key):
                changed = dict(self.versions)
                changed[key] += "+changed"
                self.assertNotEqual(
                    baseline,
                    build_render_context_key(
                        "SOURCE", "MID", 22, 48000, 480000, 96000, 24000, "SEGMENTS", changed
                    ),
                )

    def test_cached_adapter_requires_its_model_version_in_the_render_versions(self):
        mismatched = dict(self.versions, model="another-model")
        with self.assertRaisesRegex(ValueError, "model"):
            CachedDfnAdapter(
                DfnAdapter("deepFilter.exe", "model-1"),
                {"render_context_key": "context"},
                mismatched,
            )


if __name__ == "__main__":
    unittest.main()
