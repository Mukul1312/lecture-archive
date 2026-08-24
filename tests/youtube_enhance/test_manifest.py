import unittest

from scripts.youtube_enhance.manifest import (
    RenderNotApproved,
    cache_key,
    processing_fingerprint,
    require_current_approval,
)


class ManifestTests(unittest.TestCase):
    def base_manifest(self):
        return {
            "schema_version": 1,
            "source": {"sha256": "abc", "decoded_samples": 480000},
            "versions": {"ffmpeg": "8.1.1", "deepfilter": "0.5.6"},
            "processing": {"attenuation_db": 22, "halo_samples": 48000},
            "segment_map_sha256": "segments-a",
            "candidate_report_sha256": "candidates-a",
            "approval": None,
        }

    def test_cache_key_is_canonical_and_stage_scoped(self):
        a = cache_key("decode", {"b": "2", "a": "1"}, {"gain": 0.9}, {"ffmpeg": "8"})
        b = cache_key("decode", {"a": "1", "b": "2"}, {"gain": 0.9}, {"ffmpeg": "8"})
        c = cache_key("render", {"a": "1", "b": "2"}, {"gain": 0.9}, {"ffmpeg": "8"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_render_is_blocked_without_approval(self):
        with self.assertRaises(RenderNotApproved):
            require_current_approval(self.base_manifest())

    def test_changed_inputs_invalidate_approval(self):
        manifest = self.base_manifest()
        fingerprint = processing_fingerprint(manifest)
        manifest["approval"] = {
            "blind_code": "B",
            "candidate_id": "adaptive-22",
            "pause_treatment": "original",
            "reviewer": "Mukul",
            "approved_at": "2026-08-21T12:00:00Z",
            "fingerprint": fingerprint,
        }
        require_current_approval(manifest)
        manifest["segment_map_sha256"] = "segments-b"
        with self.assertRaises(RenderNotApproved):
            require_current_approval(manifest)


if __name__ == "__main__":
    unittest.main()
