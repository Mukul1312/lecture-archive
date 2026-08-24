import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from scripts.youtube_enhance.dfn import CachedDfnAdapter, Processed
from scripts.youtube_enhance.manifest import write_json_atomic
from scripts.youtube_enhance.source import sha256_file
from scripts.youtube_enhance.workflow_state import (
    JobBusy,
    discover_canonical_repository,
    job_lock,
    job_paths,
)
from tests.youtube_enhance.workflow_fixtures import run_git


class GenericD30Tests(unittest.TestCase):
    versions = {
        "deepfilternet": "0.5.6",
        "deepfilter": "DeepFilterNet 0.5.6",
        "python": "Python 3.11",
        "numpy": "1.26",
        "soundfile": "0.14",
        "ffmpeg": "ffmpeg 8.1",
        "ffprobe": "ffprobe 8.1",
    }

    def _job(self, root: Path) -> tuple[Path, Path, np.ndarray]:
        repository = root / "repository"
        repository.mkdir()
        run_git(repository, "init", "-b", "main")
        skill = repository / ".agents" / "skills" / "enhancing-lecture-audio" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# Installed test skill\n", encoding="utf-8")
        job_root = repository / "data" / "enhance" / "jobs" / "sample-approved-job"
        job_root.mkdir(parents=True)
        source = job_root / "approved-source.wav"
        samples = np.array([0.1, -0.2, 0.3, -0.4, 0.25, -0.15, 0.05, 0.2], dtype=np.float32)
        sf.write(source, samples, 48_000, subtype="FLOAT")
        model = job_root / "model" / "DeepFilterNet3"
        (model / "checkpoints").mkdir(parents=True)
        (model / "config.ini").write_text("[model]\nname=DeepFilterNet3\n", encoding="utf-8")
        (model / "checkpoints" / "model_120.ckpt.best").write_bytes(b"checkpoint")
        job = {
            "schema_version": 1,
            "job_id": "sample-approved-job",
            "stage": "full_render_approved",
            "source": {"path": str(source), "sha256": sha256_file(source)},
            "treatment": {
                "mode": "dfn30_parallel", "model": "DeepFilterNet3",
                "attenuation_limit_db": 30, "preserve_complete_timeline": True,
            },
            "audition": {
                "status": "ready",
                "choice": {"selected_candidate": "dfn30_parallel", "result": "unanimous"},
            },
            "delivery": {"status": "approved_pending_render", "formats": ["flac_24bit", "mp3_192kbps"]},
        }
        job_path = job_root / "job.json"
        write_json_atomic(job_path, job)
        return job_path, source, samples

    def test_job_outside_canonical_jobs_root_is_rejected_before_processing(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, _samples = self._job(Path(folder))
            repository = job_path.parents[4]
            outside = repository / "data" / "enhance" / "audio" / job_path.parent.name / "job.json"
            outside.parent.mkdir(parents=True)
            outside.write_bytes(job_path.read_bytes())

            with patch.object(
                generic_d30,
                "decode_float_stereo",
                side_effect=AssertionError("processing reached"),
            ):
                with self.assertRaisesRegex(ValueError, "canonical"):
                    generic_d30.run_generic_d30(outside)

    def test_busy_canonical_job_is_rejected_before_processing(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            repository = discover_canonical_repository(job_path.parent)
            paths = job_paths(repository, job_path.parent.name)
            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                with job_lock(paths, blocking=False):
                    with self.assertRaisesRegex(JobBusy, "already running"):
                        generic_d30.run_generic_d30(job_path)

    def test_cli_reports_busy_job_without_a_traceback(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, _samples = self._job(Path(folder))
            repository = discover_canonical_repository(job_path.parent)
            paths = job_paths(repository, job_path.parent.name)
            stderr = io.StringIO()
            with job_lock(paths, blocking=False), redirect_stderr(stderr):
                result = generic_d30.main(["--job", str(job_path)])

            self.assertEqual(result, 2)
            self.assertIn("job is already running", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    @staticmethod
    def _metrics(kind: str, frames: int) -> dict:
        return {
            "integrated_lufs": -16.0, "true_peak_dbtp": -1.6, "lra": 2.0,
            "decode_ok": True, "sample_rate": 48_000, "channels": 2, "frames": frames,
            "bits_per_raw_sample": 24 if kind == "flac" else 0,
            "codec_name": kind, "container_name": kind,
            "bit_rate": 0 if kind == "flac" else 192_000,
            "codec_delay_padding_samples": 0,
        }

    def _boundaries(self, module, samples: np.ndarray):
        def decode(_source, destination, _ffmpeg):
            destination.parent.mkdir(parents=True, exist_ok=True)
            sf.write(destination, np.column_stack((samples, samples)), 48_000, subtype="FLOAT")

        def render(source, destination, enhancer, _rate, attenuation, *_args):
            self.assertEqual(attenuation, 30)
            self.assertEqual(enhancer.inner.inner.inner.model_directory.name, "DeepFilterNet3")
            self.assertEqual(enhancer.inner.inner.scratch_root, source.parent / "dfn-scratch")
            self.assertEqual(enhancer.cache_root, source.parent / "c")
            values, rate = sf.read(source, dtype="float32")
            sf.write(destination, values * 0.5, rate, subtype="FLOAT")
            return {"samples": len(values), "sample_rate": rate, "boundaries": []}

        def normalize(_ffmpeg, source, destination, expected):
            values, rate = sf.read(source, dtype="float32", always_2d=True)
            self.assertEqual(expected, len(values))
            sf.write(destination, values, rate, subtype="FLOAT")
            return {"input_i": "-16.0"}

        def export(_ffmpeg, master, flac, mp3, _measure):
            values, rate = sf.read(master, dtype="float32", always_2d=True)
            sf.write(flac, values, rate, subtype="PCM_24")
            mp3.write_bytes(b"tiny fake mp3")
            return {
                "delivery_master": str(master),
                "flac": self._metrics("flac", len(values)),
                "mp3": self._metrics("mp3", len(values)),
            }

        return (
            patch.object(module, "resolve_tool", side_effect=lambda name: name),
            patch.object(module, "_current_tool_versions", return_value=self.versions),
            patch.object(module, "decode_float_stereo", side_effect=decode),
            patch.object(module, "render_file", side_effect=render),
            patch.object(module, "normalize_two_pass", side_effect=normalize),
            patch.object(module, "export_matched_pair", side_effect=export),
        )

    def test_cached_d30_adapter_uses_short_job_scratch_without_weakening_cache_paths(self):
        from scripts.youtube_enhance import generic_d30

        if not hasattr(generic_d30, "_ScratchDfnAdapter"):
            self.fail("generic runner must separate DFN attempt scratch from content-addressed cache")

        class RecordingAdapter:
            model_version = "DeepFilterNet3:test"

            def __init__(self):
                self.work_directories = []

            def enhance(self, samples, _rate, _attenuation, work_directory):
                self.work_directories.append(work_directory)
                return Processed(samples.copy(), 0, model_version=self.model_version)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "job-with-a-long-but-valid-name"
            scratch = root / "work" / "dfn-scratch"
            cache_chunk_root = root / "work" / "cache" / "chunks" / "0-11520000"
            recorded = RecordingAdapter()
            adapter = generic_d30._ScratchDfnAdapter(recorded, scratch)
            cached = CachedDfnAdapter(
                adapter,
                {"render_context_key": "A" * 64, "stage": "generic-d30"},
                {
                    "deepfilternet": "0.5.6", "model": "DeepFilterNet3:test",
                    "python": "Python 3.11", "numpy": "1.26", "soundfile": "0.14", "ffmpeg": "ffmpeg 8.1",
                },
            )
            cached.enhance(np.array([0.1, -0.2, 0.3], dtype=np.float32), 48_000, 30, cache_chunk_root)

            self.assertEqual(recorded.work_directories, [scratch])
            artifacts = list(cache_chunk_root.glob("*/enhanced.wav"))
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(len(artifacts[0].parent.name), 64)
            self.assertFalse(list(cache_chunk_root.rglob("attempt-*")))
            self.assertLess(len(str(scratch / "attempt-abcdefgh" / "input" / "chunk.wav")), 260)

    def test_cached_d30_adapter_uses_fixed_short_cache_root_for_long_core_ranges(self):
        from scripts.youtube_enhance import generic_d30

        if not hasattr(generic_d30, "_CacheRootDfnAdapter"):
            self.fail("generic runner must separate content-addressed cache from render core grouping")

        class RecordingAdapter:
            model_version = "DeepFilterNet3:test"

            def __init__(self):
                self.work_directories = []

            def enhance(self, samples, _rate, _attenuation, work_directory):
                self.work_directories.append(Path(work_directory))
                return Processed(samples.copy(), 0, model_version=self.model_version)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "job-with-a-long-but-valid-name"
            scratch = root / "work" / "dfn-scratch"
            fixed_cache_root = root / "work" / "c"
            long_core_group = root / "work" / "cache" / "chunks" / "103680000-115200000"
            recorded = RecordingAdapter()
            cached = CachedDfnAdapter(
                generic_d30._ScratchDfnAdapter(recorded, scratch),
                {"render_context_key": "A" * 64, "stage": "generic-d30"},
                {
                    "deepfilternet": "0.5.6", "model": "DeepFilterNet3:test",
                    "python": "Python 3.11", "numpy": "1.26", "soundfile": "0.14", "ffmpeg": "ffmpeg 8.1",
                },
            )
            adapter = generic_d30._CacheRootDfnAdapter(cached, fixed_cache_root)
            adapter.enhance(np.array([0.1, -0.2, 0.3], dtype=np.float32), 48_000, 30, long_core_group)

            self.assertEqual(recorded.work_directories, [scratch])
            artifacts = list(fixed_cache_root.glob("*/enhanced.wav"))
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(len(artifacts[0].parent.name), 64)
            self.assertLess(len(str(artifacts[0].with_name("enhanced.json.new"))), 260)
            self.assertFalse(long_core_group.exists())

    def test_delivery_stage_budget_covers_private_export_paths(self):
        from scripts.youtube_enhance import generic_d30
        from scripts.youtube_enhance import loudness

        if not hasattr(generic_d30, "_delivery_stage"):
            self.fail("generic runner must provide a short delivery staging root")

        work = Path(
            r"C:\Users\Example\code\audio-projects\lecture-enhancement\.worktrees\publication-validation"
            r"\data\enhance\jobs\sample-lecture-12345678\work"
        )
        stage = generic_d30._delivery_stage(work, "a" * 32)
        master = stage / "normalized-master.wav"
        flac_name, mp3_name = generic_d30._delivery_names(
            Path("A very long lecture title that must remain inside the Windows path budget.mp3")
        )
        flac = stage / flac_name
        mp3 = stage / mp3_name
        corrected = master.with_name(f"{master.stem}-tp-corrected.wav")
        private_paths = (
            loudness._stage_for(flac),
            loudness._stage_for(mp3),
            loudness._stage_for(corrected),
        )

        self.assertTrue(all(path.parent == stage for path in (master, flac, mp3, corrected, *private_paths)))
        self.assertLess(max(len(str(path)) for path in (stage, master, flac, mp3, corrected, *private_paths)), 260)

    def test_approved_arbitrary_source_runs_once_at_d30_and_preserves_timeline(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, source, samples = self._job(Path(folder))
            boundaries = self._boundaries(generic_d30, samples)
            for boundary in boundaries:
                boundary.__enter__()
            try:
                completion = generic_d30.run_generic_d30(job_path)
            finally:
                for boundary in reversed(boundaries):
                    boundary.__exit__(None, None, None)

            root = job_path.parent
            delivery = root / "delivery"
            self.assertEqual(completion["source_sha256"], sha256_file(source))
            self.assertEqual(completion["attenuation_db"], 30)
            self.assertEqual(completion["frames"], len(samples))
            self.assertEqual(completion["model_directory"], str((root / "model" / "DeepFilterNet3").resolve()))
            self.assertEqual(completion["model_hashes"]["config.ini"], sha256_file(root / "model" / "DeepFilterNet3" / "config.ini"))
            raw_provenance = json.loads((root / "work" / "decoded-raw.wav.provenance.json").read_text(encoding="utf-8"))
            adaptive_provenance = json.loads((root / "work" / "adaptive.wav.provenance.json").read_text(encoding="utf-8"))
            normalized_provenance = json.loads((root / "work" / "normalized-master.wav.provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(raw_provenance["context"]["source_sha256"], sha256_file(source))
            self.assertEqual(adaptive_provenance["context"]["render_context_key"], completion["cache_context_key"])
            self.assertEqual(normalized_provenance["context"]["adaptive_sha256"], sha256_file(root / "work" / "adaptive.wav"))
            adaptive, rate = sf.read(root / "work" / "adaptive.wav", dtype="float32", always_2d=True)
            self.assertEqual(rate, 48_000)
            self.assertEqual(len(adaptive), len(samples))
            np.testing.assert_allclose(adaptive, np.column_stack((samples * 0.5, samples * 0.5)), atol=1e-7)
            self.assertEqual(sf.info(delivery / "approved-source-D30.flac").frames, len(samples))
            self.assertTrue((delivery / "approved-source-D30.mp3").is_file())
            self.assertIn("approved-source-D30.flac", completion["artifacts"])
            self.assertIn("approved-source-D30.mp3", completion["artifacts"])
            self.assertTrue((delivery / "qa-report.json").is_file())
            self.assertTrue((delivery / "listening-checklist.md").is_file())
            updated = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["stage"], "awaiting_final_listening")
            self.assertEqual(updated["delivery"]["status"], "awaiting_final_listening")
            self.assertTrue(updated["delivery"]["flac_path"].endswith("approved-source-D30.flac"))
            self.assertTrue(updated["delivery"]["mp3_path"].endswith("approved-source-D30.mp3"))
            self.assertNotIn("human_approved", updated["delivery"])

    def test_changed_source_or_non_d30_approval_is_rejected_before_processing(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, source, _samples = self._job(Path(folder))
            source.write_bytes(b"changed source")
            with patch.object(generic_d30, "decode_float_stereo", side_effect=AssertionError("processing reached")):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    generic_d30.run_generic_d30(job_path)

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, _samples = self._job(Path(folder))
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["treatment"]["attenuation_limit_db"] = 29
            write_json_atomic(job_path, job)
            with patch.object(generic_d30, "decode_float_stereo", side_effect=AssertionError("processing reached")):
                with self.assertRaisesRegex(RuntimeError, "D30"):
                    generic_d30.run_generic_d30(job_path)

    def test_genuine_completed_delivery_is_immutable(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                generic_d30.run_generic_d30(job_path)
            with patch.object(generic_d30, "render_file", side_effect=AssertionError("render reached")):
                with self.assertRaisesRegex(RuntimeError, "not approved"):
                    generic_d30.run_generic_d30(job_path)

    def test_completed_cache_chunks_survive_a_failed_render(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))

            def decode(_source, destination, _ffmpeg):
                destination.parent.mkdir(parents=True, exist_ok=True)
                sf.write(destination, np.column_stack((samples, samples)), 48_000, subtype="FLOAT")

            def fail_after_chunk(*args):
                cache = args[-1] / "chunks" / "completed-content-addressed-chunk"
                cache.mkdir(parents=True)
                (cache / "enhanced.wav").write_bytes(b"completed chunk")
                raise RuntimeError("interrupted render")

            with patch.object(generic_d30, "resolve_tool", side_effect=lambda name: name), patch.object(
                generic_d30, "_current_tool_versions", return_value=self.versions
            ), patch.object(generic_d30, "decode_float_stereo", side_effect=decode), patch.object(
                generic_d30, "render_file", side_effect=fail_after_chunk
            ):
                with self.assertRaisesRegex(RuntimeError, "interrupted render"):
                    generic_d30.run_generic_d30(job_path)
            self.assertTrue((job_path.parent / "work" / "cache" / "chunks" / "completed-content-addressed-chunk" / "enhanced.wav").is_file())

    def test_same_length_intermediates_without_matching_provenance_are_rebuilt(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            work = job_path.parent / "work"
            work.mkdir()
            stale = samples * 0.25
            sf.write(work / "decoded-raw.wav", np.column_stack((stale, stale)), 48_000, subtype="FLOAT")
            sf.write(work / "original-mid.wav", stale, 48_000, subtype="FLOAT")
            sf.write(work / "original-side.wav", np.zeros_like(stale), 48_000, subtype="FLOAT")
            sf.write(work / "rendered-mid.wav", stale * 0.4, 48_000, subtype="FLOAT")
            sf.write(work / "adaptive.wav", np.column_stack((stale * 0.4, stale * 0.4)), 48_000, subtype="FLOAT")
            sf.write(work / "normalized-master.wav", np.column_stack((stale * 0.4, stale * 0.4)), 48_000, subtype="FLOAT")
            for artifact in work.glob("*.wav"):
                write_json_atomic(artifact.with_suffix(artifact.suffix + ".provenance.json"), {
                    "schema_version": 1, "artifact_sha256": sha256_file(artifact),
                    "context": {"source": "different job"},
                })
            calls = {"decode": 0, "render": 0, "normalize": 0}

            def decode(_source, destination, _ffmpeg):
                calls["decode"] += 1
                sf.write(destination, np.column_stack((samples, samples)), 48_000, subtype="FLOAT")

            def render(source, destination, _enhancer, _rate, attenuation, *_args):
                calls["render"] += 1
                self.assertEqual(attenuation, 30)
                values, rate = sf.read(source, dtype="float32")
                sf.write(destination, values * 0.5, rate, subtype="FLOAT")
                return {"samples": len(values), "sample_rate": rate, "boundaries": []}

            def normalize(_ffmpeg, source, destination, expected):
                calls["normalize"] += 1
                values, rate = sf.read(source, dtype="float32", always_2d=True)
                self.assertEqual(expected, len(values))
                sf.write(destination, values, rate, subtype="FLOAT")
                return {"input_i": "-16.0"}

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "decode_float_stereo", side_effect=decode))
                stack.enter_context(patch.object(generic_d30, "render_file", side_effect=render))
                stack.enter_context(patch.object(generic_d30, "normalize_two_pass", side_effect=normalize))
                generic_d30.run_generic_d30(job_path)
            self.assertEqual(calls, {"decode": 1, "render": 1, "normalize": 1})

    def test_export_failure_leaves_no_delivery_leaf_and_a_retry_can_publish(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "export_matched_pair", side_effect=RuntimeError("export interrupted")))
                with self.assertRaisesRegex(RuntimeError, "export interrupted"):
                    generic_d30.run_generic_d30(job_path)
            self.assertFalse((job_path.parent / "delivery").exists())
            self.assertFalse(list((job_path.parent / "work").glob(".delivery-stage-*")))

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                completion = generic_d30.run_generic_d30(job_path)
            self.assertEqual(completion["frames"], len(samples))
            self.assertTrue((job_path.parent / "delivery" / "completion.json").is_file())

    def test_qa_failure_after_delivery_creation_is_cleaned_up_for_retry(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "publish_qa_pair", side_effect=RuntimeError("QA interrupted")))
                with self.assertRaisesRegex(RuntimeError, "QA interrupted"):
                    generic_d30.run_generic_d30(job_path)
            self.assertFalse((job_path.parent / "delivery").exists())

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                completion = generic_d30.run_generic_d30(job_path)
            self.assertEqual(completion["listening_status"], "pending")

    def test_corrected_master_is_attempt_local_after_qa_failure_and_retry(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))

            def corrected_export(_ffmpeg, master, flac, mp3, _measure):
                values, rate = sf.read(master, dtype="float32", always_2d=True)
                corrected = master.with_name("normalized-master-tp-corrected.wav")
                if corrected.exists():
                    raise FileExistsError("stale corrected master")
                sf.write(corrected, values, rate, subtype="FLOAT")
                sf.write(flac, values, rate, subtype="PCM_24")
                mp3.write_bytes(b"tiny fake mp3")
                return {
                    "delivery_master": str(corrected),
                    "flac": self._metrics("flac", len(values)),
                    "mp3": self._metrics("mp3", len(values)),
                }

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "export_matched_pair", side_effect=corrected_export))
                stack.enter_context(patch.object(generic_d30, "publish_qa_pair", side_effect=RuntimeError("QA interrupted")))
                with self.assertRaisesRegex(RuntimeError, "QA interrupted"):
                    generic_d30.run_generic_d30(job_path)
            self.assertFalse((job_path.parent / "work" / "normalized-master-tp-corrected.wav").exists())

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "export_matched_pair", side_effect=corrected_export))
                completion = generic_d30.run_generic_d30(job_path)
            self.assertEqual(completion["frames"], len(samples))

    def test_corrupt_completion_is_quarantined_and_does_not_block_retry(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                generic_d30.run_generic_d30(job_path)
            completion_path = job_path.parent / "delivery" / "completion.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion["source_sha256"] = "0" * 64
            write_json_atomic(completion_path, completion)
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["stage"] = "full_render_approved"
            job["delivery"]["status"] = "approved_pending_render"
            write_json_atomic(job_path, job)

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                completion = generic_d30.run_generic_d30(job_path)
            self.assertNotEqual(completion["source_sha256"], "0" * 64)
            self.assertTrue((job_path.parent / "delivery" / "completion.json").is_file())
            self.assertTrue(list((job_path.parent / "work").glob("interrupted-delivery-*")))

    def test_invalid_utf8_completion_is_quarantined_and_does_not_block_retry(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                generic_d30.run_generic_d30(job_path)
            completion_path = job_path.parent / "delivery" / "completion.json"
            completion_path.write_bytes(b"\xffnot-json")
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["stage"] = "full_render_approved"
            job["delivery"]["status"] = "approved_pending_render"
            write_json_atomic(job_path, job)

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                completion = generic_d30.run_generic_d30(job_path)
            self.assertEqual(completion["source_sha256"], sha256_file(job_path.parent / "approved-source.wav"))
            self.assertTrue(list((job_path.parent / "work").glob("interrupted-delivery-*")))

    def test_valid_completion_retries_only_the_failed_job_state_publication(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            real_write = generic_d30.write_json_atomic

            def fail_job_write(path, value):
                if Path(path) == job_path:
                    raise OSError("job update interrupted")
                real_write(path, value)

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "write_json_atomic", side_effect=fail_job_write))
                with self.assertRaisesRegex(OSError, "job update interrupted"):
                    generic_d30.run_generic_d30(job_path)
            self.assertTrue((job_path.parent / "delivery" / "completion.json").is_file())

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "render_file", side_effect=AssertionError("render reached")))
                completion = generic_d30.run_generic_d30(job_path)
            self.assertEqual(completion["listening_status"], "pending")
            self.assertEqual(json.loads(job_path.read_text(encoding="utf-8"))["stage"], "awaiting_final_listening")

    def test_missing_corrected_delivery_master_quarantines_failed_job_publication(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            real_write = generic_d30.write_json_atomic

            def corrected_export(_ffmpeg, master, flac, mp3, _measure):
                values, rate = sf.read(master, dtype="float32", always_2d=True)
                corrected = master.with_name("normalized-master-tp-corrected.wav")
                sf.write(corrected, values, rate, subtype="FLOAT")
                sf.write(flac, values, rate, subtype="PCM_24")
                mp3.write_bytes(b"tiny fake mp3")
                return {
                    "delivery_master": str(corrected),
                    "flac": self._metrics("flac", len(values)),
                    "mp3": self._metrics("mp3", len(values)),
                }

            def fail_job_write(path, value):
                if Path(path) == job_path:
                    raise OSError("job update interrupted")
                real_write(path, value)

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "export_matched_pair", side_effect=corrected_export))
                stack.enter_context(patch.object(generic_d30, "write_json_atomic", side_effect=fail_job_write))
                with self.assertRaisesRegex(OSError, "job update interrupted"):
                    generic_d30.run_generic_d30(job_path)
            master = job_path.parent / "delivery" / "D30-delivery-master.wav"
            master.unlink()

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                stack.enter_context(patch.object(generic_d30, "export_matched_pair", side_effect=corrected_export))
                completion = generic_d30.run_generic_d30(job_path)
            self.assertIn("delivery_master", completion)
            self.assertEqual(completion["delivery_master"]["path"], str(master))
            self.assertTrue(list((job_path.parent / "work").glob("interrupted-delivery-*")))

    def test_completion_boundary_corruption_is_quarantined_before_job_recovery(self):
        from scripts.youtube_enhance import generic_d30

        with tempfile.TemporaryDirectory() as folder:
            job_path, _source, samples = self._job(Path(folder))
            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                generic_d30.run_generic_d30(job_path)
            completion_path = job_path.parent / "delivery" / "completion.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion["chunk_boundaries"] = [1]
            write_json_atomic(completion_path, completion)
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["stage"] = "full_render_approved"
            job["delivery"]["status"] = "approved_pending_render"
            write_json_atomic(job_path, job)

            with ExitStack() as stack:
                for boundary in self._boundaries(generic_d30, samples):
                    stack.enter_context(boundary)
                recovered = generic_d30.run_generic_d30(job_path)
            self.assertEqual(recovered["chunk_boundaries"], [])
            self.assertTrue(list((job_path.parent / "work").glob("interrupted-delivery-*")))


if __name__ == "__main__":
    unittest.main()
