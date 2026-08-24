import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from scripts.youtube_enhance.loudness import (
    build_export_commands,
    build_second_pass_filter,
    export_matched_pair,
    normalize_two_pass,
    parse_loudnorm_json,
)


class LoudnessTests(unittest.TestCase):
    def test_normalize_and_export_generated_stage_paths_preserve_muxer_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/"source.wav"; master=root/"master.wav"; flac=root/"out.flac"; mp3=root/"out.mp3"
            samples=np.zeros((8,2),dtype=np.float32); sf.write(source,samples,48000,subtype="FLOAT"); commands=[]
            def runner(command, **kwargs):
                commands.append(command)
                if "-f" in command: return type("R",(),{"returncode":0,"stderr":'{"input_i":"-20","input_tp":"-2","input_lra":"7","input_thresh":"-30","target_offset":"0"}'})()
                output=Path(command[-1]);
                if output.suffix==".wav": sf.write(output,samples,48000,subtype="FLOAT")
                else: output.write_bytes(b"encoded")
                return type("R",(),{"returncode":0,"stderr":""})()
            normalize_two_pass("ffmpeg",source,master,8,runner=runner)
            def measure(path):
                is_mp3=path.suffix==".mp3"; return {"true_peak_dbtp":-1.6,"integrated_lufs":-16.0,"decode_ok":True,"sample_rate":48000,"channels":2,"frames":8,"bits_per_raw_sample":24,"codec_name":"mp3" if is_mp3 else "flac","container_name":"mp3" if is_mp3 else "flac","bit_rate":192000,"codec_delay_padding_samples":0}
            export_matched_pair("ffmpeg",master,flac,mp3,measure,runner=runner)
            outputs=[Path(command[-1]) for command in commands if command[-1] != "-"]
            self.assertTrue(any(path.name.startswith(".master.") and path.suffix==".wav" for path in outputs))
            self.assertTrue(any(path.name.startswith(".out.") and path.suffix==".flac" for path in outputs))
            self.assertTrue(any(path.name.startswith(".out.") and path.suffix==".mp3" for path in outputs))

    def test_decoded_delivery_rejects_each_exact_metadata_mutation(self):
        from scripts.youtube_enhance.loudness import _validate_decoded_delivery
        base={"true_peak_dbtp":-1.6,"integrated_lufs":-16.0,"decode_ok":True,"sample_rate":48000,"channels":2,"frames":8,"bits_per_raw_sample":24,"codec_name":"flac","container_name":"flac"}
        for key,bad in (("codec_name","mp3"),("container_name","mp3"),("sample_rate",48000.0),("channels","2"),("frames",True),("bits_per_raw_sample",24.0)):
            with self.subTest(key=key):
                value=dict(base); value[key]=bad
                with self.assertRaises(RuntimeError): _validate_decoded_delivery(value,"FLAC",8)
    def test_parses_first_pass_json(self):
        stderr = (
            'prefix {"input_i":"-20.10","input_tp":"-2.30",'
            '"input_lra":"7.00","input_thresh":"-30.00",'
            '"target_offset":"0.10"} suffix'
        )
        self.assertEqual(parse_loudnorm_json(stderr)["input_i"], "-20.10")

    def test_rejects_nonfinite_first_pass_measurements(self):
        stderr = (
            '{"input_i":"nan","input_tp":"-2.30","input_lra":"7.00",'
            '"input_thresh":"-30.00","target_offset":"0.10"}'
        )
        with self.assertRaises(RuntimeError):
            parse_loudnorm_json(stderr)

    def test_second_pass_is_linear_and_uses_every_first_pass_measurement(self):
        measured = {
            "input_i": "-20.10",
            "input_tp": "-2.30",
            "input_lra": "7.00",
            "input_thresh": "-30.00",
            "target_offset": "0.10",
        }
        value = build_second_pass_filter(measured, target_i=-16.0, target_tp=-1.5)
        self.assertIn("linear=true", value)
        for key, expected in (
            ("measured_I", "-20.10"),
            ("measured_TP", "-2.30"),
            ("measured_LRA", "7.00"),
            ("measured_thresh", "-30.00"),
            ("offset", "0.10"),
        ):
            self.assertIn(f"{key}={expected}", value)

    def test_export_commands_are_no_clobber_24_bit_flac_and_192k_stereo_mp3(self):
        flac, mp3 = build_export_commands(
            "ffmpeg", Path("master.wav"), Path("enhanced.flac"), Path("enhanced.mp3")
        )
        for command in (flac, mp3):
            self.assertIn("-n", command)
            self.assertNotIn("-y", command)
            self.assertEqual(command[command.index("-ar") + 1], "48000")
            self.assertEqual(command[command.index("-ac") + 1], "2")
        self.assertEqual(flac[flac.index("-c:a") + 1], "flac")
        self.assertEqual(flac[flac.index("-bits_per_raw_sample") + 1], "24")
        self.assertEqual(mp3[mp3.index("-c:a") + 1], "libmp3lame")
        self.assertEqual(mp3[mp3.index("-b:a") + 1], "192k")

    def test_staged_commands_keep_unambiguous_container_suffixes(self):
        flac, mp3 = build_export_commands(
            "ffmpeg", Path("master.wav"), Path(".delivery.token.flac"), Path(".delivery.token.mp3")
        )
        self.assertEqual(Path(flac[-1]).suffix, ".flac")
        self.assertEqual(Path(mp3[-1]).suffix, ".mp3")
        self.assertNotIn("-f", flac)
        self.assertNotIn("-f", mp3)

    def test_normalization_refuses_existing_destination_before_invoking_encoder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "adaptive.wav"
            destination = root / "master.wav"
            sf.write(source, np.zeros((8, 2), dtype=np.float32), 48000, subtype="FLOAT")
            destination.write_bytes(b"immutable")
            calls = []
            with self.assertRaises(FileExistsError):
                normalize_two_pass("ffmpeg", source, destination, 8, runner=lambda *args, **kwargs: calls.append(args))
            self.assertEqual(calls, [])
            self.assertEqual(destination.read_bytes(), b"immutable")

    def test_normalization_preflights_float_48k_stereo_and_exact_input_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "adaptive.wav"
            destination = root / "master.wav"
            sf.write(source, np.zeros((8, 2), dtype=np.float32), 48000, subtype="PCM_16")
            calls = []
            with self.assertRaises(RuntimeError):
                normalize_two_pass("ffmpeg", source, destination, 8, runner=lambda *args, **kwargs: calls.append(args))
            self.assertEqual(calls, [])

    def test_normalization_uses_two_pass_linear_filter_and_preserves_exact_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "adaptive.wav"
            destination = root / "master.wav"
            samples = np.zeros((8, 2), dtype=np.float32)
            sf.write(source, samples, 48000, subtype="FLOAT")
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                if "-f" in command:
                    return type("Result", (), {
                        "returncode": 0,
                        "stderr": '{"input_i":"-20.10","input_tp":"-2.30","input_lra":"7.00","input_thresh":"-30.00","target_offset":"0.10"}',
                    })()
                sf.write(Path(command[-1]), samples, 48000, subtype="FLOAT")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            normalize_two_pass("ffmpeg", source, destination, 8, runner=runner)

        self.assertEqual(len(calls), 2)
        self.assertIn("linear=true", calls[1][calls[1].index("-af") + 1])
        self.assertIn("-n", calls[1])

    def test_normalization_discards_partial_stage_when_second_pass_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, destination = root / "adaptive.wav", root / "master.wav"
            sf.write(source, np.zeros((8, 2), dtype=np.float32), 48000, subtype="FLOAT")

            def runner(command, **kwargs):
                if "-f" in command:
                    return type("Result", (), {"returncode": 0, "stderr": '{"input_i":"-20","input_tp":"-2","input_lra":"7","input_thresh":"-30","target_offset":"0"}'})()
                Path(command[-1]).write_bytes(b"partial")
                return type("Result", (), {"returncode": 1, "stderr": "failed"})()

            with self.assertRaises(RuntimeError):
                normalize_two_pass("ffmpeg", source, destination, 8, runner=runner)
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob("*.stage.*")), [])

    def test_matched_export_regenerates_both_deliverables_from_corrected_master(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.wav"
            flac = root / "delivery.flac"
            mp3 = root / "delivery.mp3"
            samples = np.zeros((8, 2), dtype=np.float32)
            sf.write(master, samples, 48000, subtype="FLOAT")
            commands = []
            corrected = False

            def runner(command, **kwargs):
                nonlocal corrected
                commands.append(command)
                output = Path(command[-1])
                if "volume=" in " ".join(command):
                    corrected = True
                    sf.write(output, samples, 48000, subtype="FLOAT")
                elif ".flac" in output.name:
                    output.write_bytes(b"flac-corrected" if corrected else b"flac-initial")
                else:
                    output.write_bytes(b"mp3-corrected" if corrected else b"mp3-initial")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            def measure(path):
                is_mp3 = ".mp3" in path.name
                initial = not corrected
                return {
                    "true_peak_dbtp": -1.4 if is_mp3 and initial else -1.6,
                    "integrated_lufs": -16.0,
                    "decode_ok": True,
                    "sample_rate": 48000,
                    "channels": 2,
                    "frames": 8 if not is_mp3 else 8,
                    "bits_per_raw_sample": 24,
                    "codec_name": "mp3" if is_mp3 else "flac",
                    "container_name": "mp3" if is_mp3 else "flac",
                    "bit_rate": 192000,
                    "codec_delay_padding_samples": 0,
                }

            result = export_matched_pair("ffmpeg", master, flac, mp3, measure, runner=runner)

            encodes = [
                command for command in commands
                if "-c:a" in command and command[command.index("-c:a") + 1] in ("flac", "libmp3lame")
            ]
            self.assertEqual(len(encodes), 4)
            self.assertTrue(encodes[2][encodes[2].index("-i") + 1].endswith(".stage.wav"))
            self.assertEqual(encodes[2][encodes[2].index("-i") + 1], encodes[3][encodes[3].index("-i") + 1])
            self.assertTrue(result["delivery_master"].endswith("master-tp-corrected.wav"))
            self.assertEqual(flac.read_bytes(), b"flac-corrected")
            self.assertEqual(mp3.read_bytes(), b"mp3-corrected")

    def test_matched_export_refuses_existing_final_path_before_invoking_encoder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.wav"
            flac = root / "delivery.flac"
            mp3 = root / "delivery.mp3"
            sf.write(master, np.zeros((8, 2), dtype=np.float32), 48000, subtype="FLOAT")
            flac.write_bytes(b"immutable")
            calls = []
            with self.assertRaises(FileExistsError):
                export_matched_pair(
                    "ffmpeg", master, flac, mp3, lambda _: {}, runner=lambda *args, **kwargs: calls.append(args)
                )
            self.assertEqual(calls, [])
            self.assertEqual(flac.read_bytes(), b"immutable")

    def test_matched_export_corrects_for_a_high_flac_peak_even_when_mp3_is_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.wav"
            flac = root / "delivery.flac"
            mp3 = root / "delivery.mp3"
            sf.write(master, np.zeros((8, 2), dtype=np.float32), 48000, subtype="FLOAT")
            corrected = False
            commands = []

            def runner(command, **kwargs):
                nonlocal corrected
                commands.append(command)
                output = Path(command[-1])
                if "volume=" in " ".join(command):
                    corrected = True
                    sf.write(output, np.zeros((8, 2), dtype=np.float32), 48000, subtype="FLOAT")
                else:
                    output.write_bytes(b"delivery")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            def measure(path):
                is_flac = ".flac" in path.name
                return {
                    "true_peak_dbtp": -1.3 if is_flac and not corrected else -1.6,
                    "integrated_lufs": -16.0,
                    "decode_ok": True,
                    "sample_rate": 48000,
                    "channels": 2,
                    "frames": 8,
                    "bits_per_raw_sample": 24,
                    "codec_name": "mp3" if not is_flac else "flac",
                    "container_name": "mp3" if not is_flac else "flac",
                    "bit_rate": 192000,
                    "codec_delay_padding_samples": 0,
                }

            export_matched_pair("ffmpeg", master, flac, mp3, measure, runner=runner)
            self.assertTrue(any("volume=" in " ".join(command) for command in commands))

    def test_export_rolls_back_its_flac_when_mp3_publication_races(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master, flac, mp3 = root / "master.wav", root / "delivery.flac", root / "delivery.mp3"
            sf.write(master, np.zeros((8, 2), dtype=np.float32), 48000, subtype="FLOAT")
            def runner(command, **kwargs):
                Path(command[-1]).write_bytes(b"staged")
                return type("Result", (), {"returncode": 0, "stderr": ""})()
            metrics = {"true_peak_dbtp": -1.6, "integrated_lufs": -16.0, "decode_ok": True,
                       "sample_rate": 48000, "channels": 2, "frames": 8, "bits_per_raw_sample": 24,
                       "codec_name": "flac", "container_name": "flac", "bit_rate": 192000,
                       "codec_delay_padding_samples": 0}
            def measure(path):
                value = dict(metrics)
                if ".mp3" in path.name:
                    value.update(codec_name="mp3", container_name="mp3")
                return value
            real_link = __import__("os").link
            def race_on_mp3(stage, destination):
                if Path(destination) == mp3:
                    mp3.write_bytes(b"racer")
                    raise FileExistsError("race")
                return real_link(stage, destination)
            with patch("scripts.youtube_enhance.loudness.os.link", side_effect=race_on_mp3):
                with self.assertRaises(FileExistsError):
                    export_matched_pair("ffmpeg", master, flac, mp3, measure, runner=runner)
            self.assertFalse(flac.exists())
            self.assertEqual(mp3.read_bytes(), b"racer")
            mp3.unlink()
            export_matched_pair("ffmpeg", master, flac, mp3, measure, runner=runner)
            self.assertTrue(flac.exists() and mp3.exists())


if __name__ == "__main__":
    unittest.main()
