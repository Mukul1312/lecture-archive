"""Fixture-only checked whole-file playback through opaque parent-bound routes."""

from __future__ import annotations

from itertools import count
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.application import handlers as application_handlers
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.ids import CommandId, DiaryEpisodeId
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.generation import ProcessGenerationControl
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import AuthoringBindings, NarrationAuthoringRoutes
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity
from heritage_archive.platform.web import WebRequest
from tests.heritage_archive.narrator_voice.fixtures import uuid
from tests.heritage_archive.narrator_voice import test_application_audio_playback as playback_fixture
from tests.heritage_archive.narrator_voice.test_web_security import CSRF, HOST, SESSION


class _Identifiers:
    def __init__(self):
        self._values = count(7000)

    def new_id(self, kind):
        return kind(uuid(next(self._values)))


class WebMediaTests(unittest.TestCase):
    def setUp(self):
        fixture = playback_fixture.AudioPlaybackTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.identifiers = _Identifiers()
        self.handlers = SimpleNamespace(
            read_take_audio=application_handlers.ReadTakeAudioHandler(
                fixture.flow.jobs, fixture.reader, fixture.inspector,
            ),
            read_narration_master_audio=application_handlers.ReadNarrationMasterAudioHandler(
                fixture.flow.jobs, fixture.reader, fixture.inspector,
            ),
            read_episode_master_audio=application_handlers.ReadEpisodeMasterAudioHandler(
                fixture.flow.episodes, fixture.reader, fixture.inspector,
            ),
        )
        bindings = AuthoringBindings(
            "fixture-principal",
            lambda lane: (_ for _ in ()).throw(AssertionError("authority lookup forbidden")),
            lambda *args: (_ for _ in ()).throw(AssertionError("scope lookup forbidden")),
            lambda lane: (_ for _ in ()).throw(AssertionError("dictionary lookup forbidden")),
        )
        routes = NarrationAuthoringRoutes(
            self.handlers, bindings, self.identifiers, ProcessGenerationControl(SESSION),
        )
        self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=routes)
        job = fixture.job
        episode = fixture.flow.episodes.load(fixture.episode_id)
        self.cases = (
            (
                f"/audio/jobs/{job.job_id.value}/takes/{job.takes[0].take_id.value}.wav",
                job.takes[0],
            ),
            (
                f"/audio/jobs/{job.job_id.value}/masters/{job.masters[0].master_id.value}.wav",
                job.masters[0],
            ),
            (
                f"/audio/episodes/{episode.episode_id.value}/masters/{episode.speech_masters[0].master_id.value}.wav",
                episode.speech_masters[0],
            ),
        )
        self.headers = (HOST, (b"cookie", ("narrator_session=" + SESSION).encode()))

    def get(self, path, *, method="GET", headers=()):
        return self.app(WebRequest(method, path, (*self.headers, *headers)))

    @staticmethod
    def error_code(response):
        return json.loads(response.body.decode("utf-8"))["error"]["code"]

    def test_all_three_audio_routes_return_only_fully_verified_whole_wav_metadata_for_get_and_head(self):
        for path, evidence in self.cases:
            with self.subTest(path=path):
                expected = self.fixture.reader.read_verified_bytes(evidence.artifact)
                response = self.get(path)
                headers = dict(response.headers)
                self.assertEqual((response.status, response.body), (200, expected))
                self.assertEqual(headers[b"content-type"], b"audio/wav")
                self.assertEqual(headers[b"content-length"], str(len(expected)).encode())
                self.assertEqual(
                    headers[b"etag"],
                    ('"' + evidence.artifact.reference.content_digest.hex_digest + '"').encode(),
                )
                self.assertEqual(headers[b"cache-control"], b"no-store")
                self.assertTrue({
                    b"content-security-policy", b"x-content-type-options", b"referrer-policy",
                    b"x-frame-options", b"cross-origin-opener-policy",
                    b"cross-origin-resource-policy", b"permissions-policy",
                }.issubset(headers))
                self.assertTrue({
                    b"content-disposition", b"last-modified", b"accept-ranges", b"content-range",
                }.isdisjoint(headers))
                head = self.get(path, method="HEAD")
                self.assertEqual((head.status, head.body, head.headers), (200, b"", response.headers))
                for request_header in (
                    (b"range", b"bytes=0-1"),
                    (b"if-none-match", headers[b"etag"]),
                ):
                    complete = self.get(path, headers=(request_header,))
                    self.assertEqual((complete.status, complete.body), (200, expected))

    def test_wrong_parent_missing_and_lexically_invalid_audio_ids_fail_closed(self):
        job = self.fixture.job
        episode = self.fixture.flow.episodes.load(self.fixture.episode_id)
        other_episode = DiaryEpisode.prepare(DiaryEpisodeId(uuid(7090)), self.fixture.flow.clock.now())
        self.fixture.flow.episodes.save(other_episode, None)
        cross_owner = (
            f"/audio/jobs/{self.fixture.intro.issuing_job_id.value}/takes/{job.takes[0].take_id.value}.wav",
            f"/audio/jobs/{self.fixture.intro.issuing_job_id.value}/masters/{job.masters[0].master_id.value}.wav",
            f"/audio/episodes/{other_episode.episode_id.value}/masters/{episode.speech_masters[0].master_id.value}.wav",
        )
        for path in cross_owner:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual((response.status, self.error_code(response)), (404, "not_found"))
        missing_parent = uuid(7091)
        missing = (
            f"/audio/jobs/{missing_parent}/takes/{job.takes[0].take_id.value}.wav",
            f"/audio/jobs/{missing_parent}/masters/{job.masters[0].master_id.value}.wav",
            f"/audio/episodes/{missing_parent}/masters/{episode.speech_masters[0].master_id.value}.wav",
        )
        for path in missing:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual((response.status, self.error_code(response)), (404, "not_found"))
        valid_job = job.job_id.value
        valid_take = job.takes[0].take_id.value
        for raw in ("not-a-uuid", "..", valid_job.upper(), valid_job[:14] + "1" + valid_job[15:]):
            for path in (
                f"/audio/jobs/{raw}/takes/{valid_take}.wav",
                f"/audio/jobs/{valid_job}/takes/{raw}.wav",
            ):
                with self.subTest(raw=raw, path=path):
                    response = self.get(path)
                    self.assertEqual((response.status, self.error_code(response)), (400, "invalid_input"))

    def test_missing_or_tampered_stored_media_is_redacted_internal_failure(self):
        for path, evidence in self.cases:
            publication = evidence.artifact
            artifact_path = self.fixture.root.artifacts / publication.relative_location.value
            original = artifact_path.read_bytes()
            for replacement in (None, original[:-1] + b"\xff"):
                with self.subTest(path=path, missing=replacement is None):
                    artifact_path.unlink()
                    try:
                        if replacement is not None:
                            artifact_path.write_bytes(replacement)
                        response = self.get(path)
                        self.assertEqual((response.status, self.error_code(response)), (500, "internal_error"))
                        self.assertNotIn(str(self.fixture.root).encode(), response.body)
                        self.assertNotIn(publication.relative_location.value.encode(), response.body)
                    finally:
                        if artifact_path.exists():
                            artifact_path.unlink()
                        artifact_path.write_bytes(original)

    def test_plain_playback_validation_faults_are_internal_for_every_audio_route(self):
        handler_names = (
            "read_take_audio", "read_narration_master_audio", "read_episode_master_audio",
        )
        for (path, _), handler_name in zip(self.cases, handler_names, strict=True):
            original = getattr(self.handlers, handler_name)
            setattr(
                self.handlers,
                handler_name,
                lambda command: (_ for _ in ()).throw(ValidationError("private stored-media detail")),
            )
            try:
                response = self.get(path)
                self.assertEqual((response.status, self.error_code(response)), (500, "internal_error"))
                self.assertNotIn(b"private stored-media detail", response.body)
            finally:
                setattr(self.handlers, handler_name, original)

    def test_session_rejection_precedes_playback_dispatch(self):
        calls = []
        self.handlers.read_take_audio = lambda command: calls.append(command)
        path = self.cases[0][0]
        for headers in ((HOST,), (HOST, (b"cookie", b"narrator_session=" + b"c" * 64))):
            response = self.app(WebRequest("GET", path, headers))
            self.assertEqual((response.status, self.error_code(response)), (401, "session_required"))
        self.assertEqual(calls, [])

    def test_raw_asgi_head_suppresses_only_body_after_full_media_verification(self):
        from heritage_archive.platform.web.loopback import build_asgi

        sent = []
        incoming = [{"type": "http.request", "body": b"", "more_body": False}]

        async def receive():
            return incoming.pop(0)

        async def send(message):
            sent.append(message)

        async def inline(call, *args):
            return call(*args)

        path, evidence = self.cases[0]
        scope = {
            "type": "http", "http_version": "1.1", "method": "HEAD", "path": path,
            "raw_path": path.encode(), "query_string": b"", "headers": list(self.headers),
            "scheme": "http", "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1),
        }
        with patch("heritage_archive.platform.web.loopback.run_in_threadpool", inline):
            coroutine = build_asgi(self.app)(scope, receive, send)
            with self.assertRaises(StopIteration):
                coroutine.send(None)
        start, body = sent
        headers = dict(start["headers"])
        self.assertEqual(start["status"], 200)
        self.assertEqual(body, {"type": "http.response.body", "body": b""})
        self.assertEqual(
            headers[b"content-length"],
            str(evidence.artifact.reference.byte_size).encode(),
        )
        self.assertEqual(
            headers[b"etag"],
            ('"' + evidence.artifact.reference.content_digest.hex_digest + '"').encode(),
        )


if __name__ == "__main__":
    unittest.main()
