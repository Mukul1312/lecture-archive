import unittest
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from scripts.youtube_enhance.models import Core
from scripts.youtube_enhance.render import (
    Support,
    compose_supports,
    crop_compensated,
    partition_cores,
    support_for_core,
    support_weights,
)


class RenderTests(unittest.TestCase):
    def test_cores_partition_the_timeline_without_loss(self):
        cores = partition_cores(1003, 256)
        self.assertEqual(cores[0].start_sample, 0)
        self.assertEqual(cores[-1].end_sample, 1003)
        self.assertEqual(
            [(a.end_sample, b.start_sample) for a, b in zip(cores, cores[1:])],
            [(item.end_sample, item.end_sample) for item in cores[:-1]],
        )

    def test_positive_latency_is_cropped_from_a_contextual_render(self):
        source = np.arange(300, dtype=np.float32)
        delay = 17
        processed = np.concatenate((np.zeros(delay, dtype=np.float32), source[:-delay]))
        core = crop_compensated(
            processed, core_offset=80, core_length=100, latency_samples=delay
        )
        np.testing.assert_array_equal(core, source[80:180])

    def test_same_timeline_supports_preserve_identity_and_length(self):
        source = np.sin(np.arange(1003, dtype=np.float32) * 0.01)
        supports = [
            support_for_core(source, core, blend_samples=32)
            for core in partition_cores(len(source), 256)
        ]
        output, weight = compose_supports(len(source), supports)
        self.assertEqual(len(output), len(source))
        self.assertTrue(np.all(weight > 0))
        np.testing.assert_allclose(output, source, atol=1e-6)
        np.testing.assert_array_equal(output, source)
        _, standalone_weights = support_weights(1003, partition_cores(1003, 256)[1], 32)
        np.testing.assert_array_equal(standalone_weights, supports[1].weights)

    def test_crop_rejects_non_mono_and_negative_latency(self):
        with self.assertRaises(ValueError):
            crop_compensated(np.zeros((8, 1), dtype=np.float32), 0, 4, 0)
        with self.assertRaises(ValueError):
            crop_compensated(np.zeros(8, dtype=np.float32), 0, 4, -1)

    def test_missing_timeline_coverage_is_fatal(self):
        support = Support(10, np.ones(20, dtype=np.float32), np.ones(20, dtype=np.float32))
        with self.assertRaises(ValueError):
            compose_supports(100, [support])

    def test_overlapping_supports_normalize_to_partition_of_unity(self):
        total_samples = 20
        cores = [Core(0, 12), Core(8, 20)]
        supports = [
            support_for_core(np.arange(total_samples, dtype=np.float32), core, 4)
            for core in cores
        ]
        _, total_weight = compose_supports(total_samples, supports)
        normalized = np.zeros(total_samples, dtype=np.float32)
        for support in supports:
            start = support.start_sample
            end = start + len(support.weights)
            normalized[start:end] += support.weights / total_weight[start:end]
        np.testing.assert_allclose(normalized, np.ones(total_samples), atol=1e-6)

    def test_bisection_keeps_exact_parent_coordinates(self):
        from scripts.youtube_enhance.render import bisect_core

        signal = np.ones(1000, dtype=np.float32)
        signal[498:503] = 0
        left, right = bisect_core(Core(100, 900), signal, search_samples=100)
        self.assertEqual(left.start_sample, 100)
        self.assertEqual(left.end_sample, right.start_sample)
        self.assertEqual(right.end_sample, 900)
        self.assertIn(left.end_sample, range(498, 503))

    def test_bisection_rejects_a_parent_outside_the_source(self):
        from scripts.youtube_enhance.render import bisect_core

        with self.assertRaises(ValueError):
            bisect_core(Core(0, 11), np.ones(10, dtype=np.float32), search_samples=3)

    def test_allocator_failure_bisects_and_still_returns_every_sample(self):
        from scripts.youtube_enhance.dfn import DfnAllocationError, Processed
        from scripts.youtube_enhance.render import render_array

        class LimitedIdentity:
            def enhance(self, samples, sample_rate, attenuation_db, work_directory):
                if len(samples) > 420:
                    raise DfnAllocationError("simulated allocation failure")
                return Processed(samples.copy(), 0)

        source = np.sin(np.arange(1500, dtype=np.float32) * 0.07)
        output = render_array(
            source=source,
            enhancer=LimitedIdentity(),
            sample_rate=48000,
            attenuation_db=22,
            core_samples=600,
            halo_samples=80,
            blend_samples=32,
        )
        self.assertEqual(len(output), len(source))
        np.testing.assert_allclose(output, source, atol=1e-6)

    def test_disk_backed_renderer_preserves_timeline_with_injected_identity(self):
        from scripts.youtube_enhance.dfn import Processed
        from scripts.youtube_enhance.render import render_file

        class Identity:
            def enhance(self, samples, sample_rate, attenuation_db, work_directory):
                return Processed(samples.copy(), 0)

        source = np.sin(np.arange(1003, dtype=np.float32) * 0.03)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_path = root / "source.wav"
            output_path = root / "output.wav"
            sf.write(source_path, source, 48000, subtype="FLOAT")
            result = render_file(
                source_path, output_path, Identity(), 48000, 22, 256, 80, 32, root / "work"
            )
            output, rate = sf.read(output_path, dtype="float32")
            output_info = sf.info(output_path)
        self.assertEqual(result, {"samples": 1003, "sample_rate": 48000, "boundaries": [256, 512, 768]})
        self.assertEqual(rate, 48000)
        self.assertEqual((output_info.samplerate, output_info.channels, output_info.subtype), (48000, 1, "FLOAT"))
        np.testing.assert_array_equal(output, source)

    def test_disk_backed_renderer_rejects_44k1_source_and_configuration(self):
        from scripts.youtube_enhance.render import render_file

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_path = root / "source-44k1.wav"
            sf.write(source_path, np.zeros(64, dtype=np.float32), 44100, subtype="FLOAT")
            with self.assertRaisesRegex(ValueError, "48 kHz"):
                render_file(source_path, root / "output.wav", object(), 44100, 22, 32, 8, 4, root / "work")
            source_path = root / "source-48k.wav"
            sf.write(source_path, np.zeros(64, dtype=np.float32), 48000, subtype="FLOAT")
            with self.assertRaisesRegex(ValueError, "48 kHz"):
                render_file(source_path, root / "output.wav", object(), 44100, 22, 32, 8, 4, root / "work")


if __name__ == "__main__":
    unittest.main()
