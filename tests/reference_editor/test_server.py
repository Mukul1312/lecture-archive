from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from scripts.reference_editor import review as review_model
from scripts.reference_editor.server import build_server


SRT = (
    "1\r\n00:00:01,000 --> 00:00:02,500\r\n<b>śrī-mārkaṇḍeya uvāca</b>\r\n\r\n"
    "2\r\n00:00:02,500 --> 00:00:05,000\r\n<b>Take shelter of this Holy Name</b>\r\n"
)
AUDIO = bytes(range(256)) * 40


class EditorServerTests(unittest.TestCase):

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.srt = root / "ref.srt"
        self.srt.write_bytes(SRT.encode("utf-8"))
        self.audio = root / "clip.mp3"
        self.audio.write_bytes(AUDIO)
        self.review_path = root / "ref-review.json"
        self.start()

    def start(self) -> None:
        self.server = build_server(self.srt, self.review_path, str(self.audio), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def tearDown(self) -> None:
        self.stop()
        self._temporary.cleanup()

    def request(self, path: str, *, method: str = "GET", body: bytes | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method=method,
                                         headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def save(self, review: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        default = {"Content-Type": "application/json", "X-Reference-Editor": "1"}
        status, _, body = self.request("/api/review", method="POST", body=json.dumps(review).encode("utf-8"),
                                       headers=headers if headers is not None else default)
        return status, json.loads(body or b"{}")

    def current(self) -> dict:
        status, _, body = self.request("/api/review")
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_first_start_writes_a_review_built_from_the_subtitles(self) -> None:
        saved = json.loads(self.review_path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["cues"]), 2)
        self.assertEqual(saved["source_srt_sha256"], review_model.source_digest(self.srt.read_bytes()))
        data = self.current()
        self.assertEqual(data["audio_src"], "/audio")
        self.assertEqual(data["counts"]["unchecked"], 2)

    def test_a_saved_correction_persists_with_a_backup_and_a_snapshot(self) -> None:
        review = self.current()
        review["cues"][1].update(text="Take shelter of the Holy Name", status="ok")
        status, result = self.save(review)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["counts"]["fixed"], 1)
        saved = json.loads(self.review_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["cues"][1]["text"], "Take shelter of the Holy Name")
        self.assertEqual(saved["cues"][1]["status"], "fixed")
        self.assertNotIn("audio_src", saved, "view-only fields must not be persisted")
        self.assertTrue(self.review_path.with_name(self.review_path.name + ".bak").exists())
        self.assertTrue(any(self.review_path.with_name("ref-review-snapshots").iterdir()))

    def test_corrections_survive_a_restart(self) -> None:
        review = self.current()
        review["cues"][0].update(text="śrī-mārkaṇḍeya uvāca.", status="fixed")
        self.assertEqual(self.save(review)[0], 200)
        self.stop()
        self.start()
        self.assertEqual(self.current()["cues"][0]["text"], "śrī-mārkaṇḍeya uvāca.")

    def test_saves_without_the_editor_header_are_refused_and_change_nothing(self) -> None:
        before = self.review_path.read_bytes()
        review = self.current()
        review["cues"][0]["text"] = "tampered"
        status, _ = self.save(review, headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)
        self.assertEqual(self.review_path.read_bytes(), before)

    def test_a_foreign_host_header_is_refused(self) -> None:
        status, _, _ = self.request("/api/review", headers={"Host": "attacker.example"})
        self.assertEqual(status, 421)

    def test_changed_timings_are_refused_and_change_nothing(self) -> None:
        before = self.review_path.read_bytes()
        review = self.current()
        review["cues"][0]["start_ms"] = 0
        status, result = self.save(review)
        self.assertEqual(status, 400)
        self.assertIn("start_ms cannot be changed", result["error"])
        self.assertEqual(self.review_path.read_bytes(), before)

    def test_exported_srt_carries_saved_corrections(self) -> None:
        review = self.current()
        review["cues"][1].update(text="Take shelter of the Holy Name", status="fixed")
        self.assertEqual(self.save(review)[0], 200)
        status, headers, body = self.request("/api/export.srt")
        self.assertEqual(status, 200)
        self.assertIn("ref-verified.srt", headers["Content-Disposition"])
        self.assertIn("00:00:02,500 --> 00:00:05,000\r\nTake shelter of the Holy Name", body.decode("utf-8"))

    def test_local_audio_supports_byte_ranges_for_seeking(self) -> None:
        status, headers, body = self.request("/audio", headers={"Range": "bytes=100-199"})
        self.assertEqual((status, headers["Content-Range"], body), (206, f"bytes 100-199/{len(AUDIO)}", AUDIO[100:200]))
        status, _, body = self.request("/audio", headers={"Range": "bytes=-10"})
        self.assertEqual((status, body), (206, AUDIO[-10:]))
        status, _, body = self.request("/audio")
        self.assertEqual((status, body), (200, AUDIO))
        status, headers, _ = self.request("/audio", headers={"Range": f"bytes={len(AUDIO)}-"})
        self.assertEqual((status, headers["Content-Range"]), (416, f"bytes */{len(AUDIO)}"))

    def test_the_page_is_served_with_a_restrictive_content_security_policy(self) -> None:
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertIn(b"/static/app.js", body)

    def test_a_review_from_different_subtitles_blocks_startup_and_is_kept(self) -> None:
        self.stop()
        before = self.review_path.read_bytes()
        self.srt.write_bytes(SRT.replace("Holy Name", "holy name").encode("utf-8"))
        with self.assertRaisesRegex(review_model.ReviewError, "different subtitle file"):
            build_server(self.srt, self.review_path, str(self.audio), port=0)
        self.assertEqual(self.review_path.read_bytes(), before)
        self.srt.write_bytes(SRT.encode("utf-8"))
        self.start()

    def test_remote_audio_must_be_archive_org(self) -> None:
        with self.assertRaises(review_model.ReviewError):
            build_server(self.srt, self.review_path, "https://example.com/a.mp3", port=0)


if __name__ == "__main__":
    unittest.main()
