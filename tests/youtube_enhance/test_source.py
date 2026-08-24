import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from scripts.youtube_enhance.source import (
    calculate_headroom_gain,
    decode_float_stereo,
    from_mid_side,
    sha256_file,
    stream_headroom_mid_side,
    to_mid_side,
)


class SourceTests(unittest.TestCase):
    def test_hash_reads_file_in_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.bin"
            path.write_bytes(b"lecture-source")
            self.assertEqual(
                sha256_file(path),
                hashlib.sha256(b"lecture-source").hexdigest().upper(),
            )

    def test_headroom_gain_never_boosts(self):
        self.assertEqual(calculate_headroom_gain(0.80), 1.0)
        self.assertAlmostEqual(calculate_headroom_gain(1.20), 0.95 / 1.20)

    def test_mid_side_round_trip(self):
        stereo = np.array([[0.5, -0.25], [1.2, 0.4], [-0.8, 0.1]], dtype=np.float32)
        mid, side = to_mid_side(stereo)
        np.testing.assert_allclose(from_mid_side(mid, side), stereo, atol=1e-7)

    def test_streaming_split_preserves_count_and_applies_one_gain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "decoded.wav"
            mid_path = root / "mid.wav"
            side_path = root / "side.wav"
            stereo = np.tile(
                np.array([[1.20, 0.40], [-1.10, -0.20]], dtype=np.float32),
                (200, 1),
            )
            sf.write(source, stereo, 48000, subtype="FLOAT")
            result = stream_headroom_mid_side(source, mid_path, side_path)
            mid, _ = sf.read(mid_path, dtype="float32")
            side, _ = sf.read(side_path, dtype="float32")
            rebuilt = from_mid_side(mid, side)
            self.assertEqual(result["samples"], len(stereo))
            self.assertEqual(len(rebuilt), len(stereo))
            np.testing.assert_allclose(rebuilt, stereo * (0.95 / 1.20), atol=1e-6)

    def test_streaming_split_rejects_existing_outputs_without_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "decoded.wav"
            mid_path = root / "mid.wav"
            side_path = root / "side.wav"
            sf.write(source, np.zeros((4, 2), dtype=np.float32), 48000, subtype="FLOAT")
            mid_path.write_bytes(b"immutable-mid")
            side_path.write_bytes(b"immutable-side")
            with self.assertRaises(FileExistsError):
                stream_headroom_mid_side(source, mid_path, side_path)
            self.assertEqual(mid_path.read_bytes(), b"immutable-mid")
            self.assertEqual(side_path.read_bytes(), b"immutable-side")

    def test_streaming_split_rejects_source_output_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "decoded.wav"
            sf.write(source, np.zeros((4, 2), dtype=np.float32), 48000, subtype="FLOAT")
            with self.assertRaises((FileExistsError, ValueError)):
                stream_headroom_mid_side(source, source, Path(folder) / "side.wav")

    def test_decode_rejects_existing_destination_without_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.webm"
            destination = root / "decoded.wav"
            source.write_bytes(b"source")
            destination.write_bytes(b"immutable-destination")
            with self.assertRaises(FileExistsError):
                decode_float_stereo(source, destination, "missing-ffmpeg")
            self.assertEqual(destination.read_bytes(), b"immutable-destination")

    def test_decode_rejects_source_destination_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.webm"
            source.write_bytes(b"source")
            with self.assertRaises((FileExistsError, ValueError)):
                decode_float_stereo(source, source, "missing-ffmpeg")

    def test_decode_uses_ffmpeg_no_clobber_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.webm"
            destination = root / "decoded.wav"
            source.write_bytes(b"source")
            with patch("scripts.youtube_enhance.source.subprocess.run") as run:
                decode_float_stereo(source, destination, "ffmpeg")
            command = run.call_args.args[0]
            self.assertIn("-n", command)
            self.assertNotIn("-y", command)

    def test_known_source_hash_when_file_is_present(self):
        source = Path("Haladhara-lecture.webm")
        if not source.exists():
            self.skipTest("local immutable source is not present")
        self.assertEqual(
            sha256_file(source),
            "262630088DCC07E4507C004A3E46FA4CAF430EEFC2D047509A0618AFAE43BF68",
        )


if __name__ == "__main__":
    unittest.main()
