"""Fixture-only, framework-neutral Narrator HTTP security tests."""

import json
import unittest
from unittest.mock import patch
import secrets
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from heritage_archive.platform.web import WebRequest, WebResponse
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity, json_success, parse_json_object


SESSION = "a" * 64
CSRF = "b" * 64
HOST = (b"host", b"127.0.0.1:8765")
POST_HEADERS = (HOST, (b"origin", b"http://127.0.0.1:8765"),
                (b"sec-fetch-site", b"same-origin"),
                (b"cookie", ("narrator_session=" + SESSION).encode()),
                (b"x-narrator-csrf", CSRF.encode()),
                (b"content-type", b"application/json"))


class WebSecurityTests(unittest.TestCase):
    def test_malformed_framing_and_nonfinite_numeric_json_fail_closed(self):
        for value in (b"-1", b"garbage", b"1, 1"):
            with self.subTest(value=value):
                self.assert_rejected(WebRequest("POST", "/fixture", POST_HEADERS + ((b"content-length", value),), b'{"value":1}'), 400, "malformed_request")
        with self.subTest(ambiguous_framing=True):
            self.assert_rejected(WebRequest("POST", "/fixture", POST_HEADERS + ((b"content-length", b"1"), (b"transfer-encoding", b"chunked")), b'{"value":1}'), 400, "malformed_request")
        self.assert_rejected(WebRequest("POST", "/fixture", POST_HEADERS, b'{"value":1e999}'), 400, "invalid_json")

    def test_fault_during_response_finalization_is_also_generic_and_secured(self):
        app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=lambda request: None)
        response = app(WebRequest("POST", "/fixture", POST_HEADERS, b'{}'))
        self.assertEqual(response.status, 500)
        self.assert_secured(response)

    def setUp(self):
        self.calls = []

        def dispatch(request):
            body = parse_json_object(request, frozenset({"value"}))
            self.calls.append(body)
            return json_success({"accepted": True})

        self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=dispatch)

    def assert_secured(self, response):
        headers = dict(response.headers)
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(headers[b"content-security-policy"],
            b"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'")
        for key, value in ((b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                           (b"x-frame-options", b"DENY"), (b"cross-origin-opener-policy", b"same-origin"),
                           (b"cross-origin-resource-policy", b"same-origin"),
                           (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")):
            self.assertEqual(headers[key], value)

    def assert_rejected(self, request, status, code):
        self.calls.clear()
        response = self.app(request)
        self.assertEqual(response.status, status)
        self.assertEqual(json.loads(response.body), {"ok": False, "error": {
            "code": code, "message": "The request could not be completed."}})
        self.assert_secured(response)
        self.assertEqual(self.calls, [])

    def test_protocol_and_authentication_matrix_rejects_before_dispatch(self):
        cases = (
            (b"host", None, 400, "malformed_request"),
            (b"host", b"localhost:8765", 403, "invalid_host"),
            (b"host", b"127.0.0.1:8765.evil", 403, "invalid_host"),
            (b"host", b"127.0.0.1:8766", 403, "invalid_host"),
            (b"host", b"[::1]:8765", 403, "invalid_host"),
            (b"origin", None, 403, "invalid_origin"),
            (b"origin", b"null", 403, "invalid_origin"),
            (b"origin", b"http://127.0.0.1:8765/", 403, "invalid_origin"),
            (b"sec-fetch-site", None, 403, "invalid_fetch_metadata"),
            (b"sec-fetch-site", b"same-site", 403, "invalid_fetch_metadata"),
            (b"sec-fetch-site", b"cross-site", 403, "invalid_fetch_metadata"),
            (b"cookie", None, 401, "session_required"),
            (b"cookie", b"narrator_session=" + b"c" * 64, 401, "session_required"),
            (b"cookie", b"narrator_session=short", 401, "session_required"),
            (b"cookie", b"narrator_session=" + b"a" * 64 + b"; narrator_session=" + b"a" * 64, 400, "malformed_request"),
            (b"cookie", b"broken-cookie", 400, "malformed_request"),
            (b"x-narrator-csrf", None, 403, "invalid_csrf"),
            (b"x-narrator-csrf", b"c" * 64, 403, "invalid_csrf"),
            (b"x-narrator-csrf", b"a" * 64, 403, "invalid_csrf"),
            (b"x-narrator-csrf", b"\xff", 403, "invalid_csrf"),
            (b"content-type", None, 415, "unsupported_media_type"),
            (b"content-type", b"application/json; charset=utf-8", 415, "unsupported_media_type"),
            (b"content-type", b"text/plain", 415, "unsupported_media_type"),
        )
        for key, value, status, code in cases:
            with self.subTest(key=key, value=value):
                headers = tuple((k, v) for k, v in POST_HEADERS if k != key)
                if value is not None:
                    headers += ((key, value),)
                self.assert_rejected(WebRequest("POST", "/fixture", headers, b'{"value":1}'), status, code)

    def test_duplicate_protocol_headers_and_control_characters_are_malformed(self):
        for key, value in POST_HEADERS:
            with self.subTest(key=key):
                self.assert_rejected(WebRequest("POST", "/fixture", POST_HEADERS + ((key.upper(), value),), b'{"value":1}'), 400, "malformed_request")
        self.assert_rejected(WebRequest("GET", "/", (HOST, (b"x-injected", b"one\r\ntwo"))), 400, "malformed_request")

    def test_only_get_head_post_and_all_dynamic_responses_are_secured(self):
        for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT"):
            with self.subTest(method=method):
                self.assert_rejected(WebRequest(method, "/", (HOST,)), 405, "method_not_allowed")
                self.assertEqual(dict(self.app(WebRequest(method, "/", (HOST,))).headers)[b"allow"], b"GET, HEAD, POST")
        self.assert_secured(self.app(WebRequest("GET", "/", (HOST,))))
        self.assert_secured(self.app(WebRequest("POST", "/fixture", POST_HEADERS, b'{"value":1}')))

    def test_private_get_needs_current_session_but_root_refreshes_old_session(self):
        app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=lambda request: WebResponse(200, b"private"))
        for cookie in ((), ((b"cookie", b"narrator_session=" + b"c" * 64),)):
            self.assertEqual(app(WebRequest("GET", "/audio/fixture", (HOST, *cookie))).status, 401)
            self.assertEqual(app(WebRequest("HEAD", "/", (HOST, *cookie))).status, 200)
        request = WebRequest("GET", "/audio/fixture", (HOST, POST_HEADERS[3]))
        self.assertEqual(app(request).body, b"private")
        restarted = NarratorWebApplication(ProcessSecurity("c" * 64, "d" * 64), dispatch=lambda request: WebResponse(200))
        self.assertEqual(restarted(request).status, 401)
        response = app(WebRequest("HEAD", "/", (HOST,)))
        self.assertEqual(response.body, b"")
        self.assertGreater(int(dict(response.headers)[b"content-length"]), 0)

    def test_tokens_are_shape_checked_and_compared_in_constant_time(self):
        original = secrets.compare_digest
        with patch("secrets.compare_digest", wraps=original) as compare:
            self.app(WebRequest("POST", "/fixture", POST_HEADERS, b'{"value":1}'))
        self.assertEqual(compare.call_args_list, [unittest.mock.call(SESSION, SESSION), unittest.mock.call(CSRF, CSRF)])
        self.assertNotIn(SESSION, repr(ProcessSecurity(SESSION, CSRF)))
        for session, csrf in ((SESSION, SESSION), ("short", CSRF), (SESSION, "x" * 64)):
            with self.assertRaises(ValueError):
                ProcessSecurity(session, csrf)

    def test_json_object_schema_duplicates_utf8_constants_and_size_are_strict(self):
        for body in (b'[]', b'null', b'{"value":1,"value":2}',
                     b'{"value":{"nested":1,"nested":2}}', b'{"value":[{"x":1,"x":2}]}',
                     b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
                     b'{"value":', b'{"value":"\xff"}', b'{"value":1,"actorId":"private"}', b'{}',
                     b'{"value":1,"path":"private"}'):
            with self.subTest(body=body):
                self.assert_rejected(WebRequest("POST", "/fixture", POST_HEADERS, body), 400, "invalid_json")
        self.assert_rejected(WebRequest("POST", "/fixture", POST_HEADERS, b"x" * 262145), 413, "body_too_large")
        self.assert_rejected(WebRequest("POST", "/fixture", POST_HEADERS, b"", True), 413, "body_too_large")
        body = b'{"value":"' + b"x" * (262144 - 12) + b'"}'
        self.assertEqual(len(body), 262144)
        self.assertEqual(self.app(WebRequest("POST", "/fixture", POST_HEADERS, body)).status, 200)

    def test_unexpected_fault_and_unknown_route_are_generic_secured_json(self):
        def fail(request):
            raise RuntimeError("SENTINEL-private-root-api-key")
        app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=fail)
        response = app(WebRequest("POST", "/fixture", POST_HEADERS, b'{}'))
        self.assertEqual(response.status, 500)
        self.assertNotIn(b"SENTINEL", response.body)
        self.assert_secured(response)
        empty = NarratorWebApplication(ProcessSecurity(SESSION, CSRF))
        response = empty(WebRequest("GET", "/unknown/", (HOST, POST_HEADERS[3])))
        self.assertEqual(response.status, 404)
        self.assert_secured(response)

    def test_fixed_assets_are_public_content_derived_and_never_accept_paths(self):
        app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), assets={"/assets/studio.css": b"abc"})
        response = app(WebRequest("GET", "/assets/studio.css", (HOST,)))
        self.assertEqual((response.status, response.body), (200, b"abc"))
        headers = dict(response.headers)
        self.assertEqual(headers[b"cache-control"], b"no-cache")
        self.assertEqual(headers[b"etag"], b'"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"')
        self.assertNotIn(b"set-cookie", headers)
        head = app(WebRequest("HEAD", "/assets/studio.css", (HOST,)))
        self.assertEqual((head.status, head.body, head.headers), (200, b"", response.headers))
        for method in ("GET", "HEAD"):
            cached = app(WebRequest(method, "/assets/studio.css", (HOST, (b"if-none-match", headers[b"etag"]))))
            self.assertEqual((cached.status, cached.body), (304, b""))
        with self.assertRaises(ValueError):
            NarratorWebApplication(ProcessSecurity(SESSION, CSRF), assets={"/assets/../private": b"private"})

    def test_root_bootstraps_cookie_and_separate_meta_without_dispatch(self):
        response = self.app(WebRequest("GET", "/", (HOST,)))
        headers = dict(response.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(headers[b"set-cookie"],
                         ("narrator_session=" + SESSION + "; Path=/; HttpOnly; SameSite=Strict").encode())
        self.assertIn(('<meta name="narrator-csrf" content="' + CSRF + '">').encode(), response.body)
        self.assertNotIn(SESSION.encode(), response.body)
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(self.calls, [])

    def test_valid_mutation_has_exact_envelope_and_hostile_origin_cannot_dispatch(self):
        response = self.app(WebRequest("POST", "/fixture", POST_HEADERS, b'{"value":1}'))
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body), {"ok": True, "result": {"accepted": True}})
        self.calls.clear()
        headers = tuple((k, b"https://hostile.invalid" if k == b"origin" else v) for k, v in POST_HEADERS)
        response = self.app(WebRequest("POST", "/fixture", headers, b'{"value":1}'))
        self.assertEqual(response.status, 403)
        self.assertEqual(json.loads(response.body)["error"]["code"], "invalid_origin")
        self.assertEqual(self.calls, [])


class WebCompositionTests(unittest.TestCase):
    def test_real_fixture_graph_uses_three_distinct_tokens_and_closes_once_on_return_or_failure(self):
        from heritage_archive.composition_root import narrator_voice_web as web
        from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import initialize_local_studio
        from tests.heritage_archive.narrator_voice.test_cartesia_gateway import Identifiers
        from tests.heritage_archive.narrator_voice.test_cartesia_generation_integration import initialization

        original_get = os.environ.get
        def guarded_get(key, default=None):
            if key == "CARTESIA_API_KEY":
                self.fail("credential read forbidden")
            return original_get(key, default)

        for failure in (False, True):
            with self.subTest(failure=failure), TemporaryDirectory() as folder:
                root = LocalNarrationRoot.open(Path(folder), (Path(__file__).resolve().parents[3],))
                initialize_local_studio(root, initialization(), Identifiers())
                applications, studios, principals, closes = [], [], [], []
                real_builder = web.build_live_narration

                def build(root, *, process_principal):
                    principals.append(process_principal)
                    studio = real_builder(root, process_principal=process_principal)
                    studios.append(studio)
                    close = patch.object(studio.transport, "close", wraps=studio.transport.close)
                    closes.append(close.start())
                    self.addCleanup(close.stop)
                    return studio

                def server(application):
                    applications.append(application)
                    if failure:
                        raise RuntimeError("SENTINEL-server-failure")

                with (patch.object(os.environ, "get", side_effect=guarded_get),
                      patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")),
                      patch("socket.socket.connect", side_effect=AssertionError("connect forbidden")),
                      patch("socket.socket.connect_ex", side_effect=AssertionError("connect_ex forbidden")),
                      patch("socket.socket.bind", side_effect=AssertionError("bind forbidden")),
                      patch("httpx.Client.send", side_effect=AssertionError("HTTP forbidden")),
                      patch.object(web, "build_live_narration", side_effect=build),
                      patch.object(web, "serve_loopback", side_effect=server)):
                    if failure:
                        with self.assertRaises(RuntimeError):
                            web.serve_narration(root)
                    else:
                        self.assertIsNone(web.serve_narration(root))
                self.assertEqual(closes[0].call_count, 1)
                self.assertEqual(len(applications), 1)
                security = applications[0]._security
                tokens = {principals[0], security.session_token, security.csrf_token}
                self.assertEqual(len(tokens), 3)
                for token in tokens:
                    self.assertRegex(token, r"^[0-9a-f]{64}$")
                response = applications[0](WebRequest("GET", "/", (HOST,)))
                self.assertNotIn(principals[0].encode(), response.body)
                self.assertNotIn(principals[0], repr(applications[0]))


class WebAsgiSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_chunks_preserve_split_utf8_and_enforce_cap_despite_missing_or_lying_length(self):
        from heritage_archive.platform.web.loopback import build_asgi

        for length in (None, b"1"):
            for oversized in (False, True):
                with self.subTest(length=length, oversized=oversized):
                    calls, messages = [], []
                    def dispatch(request):
                        parsed = parse_json_object(request, frozenset({"value"}))
                        calls.append(parsed)
                        return json_success({"accepted": True})
                    app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=dispatch)
                    headers = POST_HEADERS + (() if length is None else ((b"content-length", length),))
                    body = (b"x" * 262145 if oversized else '{"value":"ଓଡ଼ିଆ"}'.encode("utf-8"))
                    width = 4096 if oversized else 1
                    chunks = iter(body[offset:offset + width] for offset in range(0, len(body), width))
                    consumed = 0
                    async def receive():
                        nonlocal consumed
                        chunk = next(chunks)
                        consumed += len(chunk)
                        return {"type": "http.request", "body": chunk, "more_body": consumed < len(body)}
                    async def send(message):
                        messages.append(message)
                    with patch("socket.socket.bind", side_effect=AssertionError("bind forbidden")):
                        await build_asgi(app)({"type": "http", "method": "POST", "path": "/fixture", "headers": headers}, receive, send)
                    self.assertEqual(messages[0]["status"], 413 if oversized else 200)
                    self.assertEqual(dict(messages[0]["headers"])[b"cache-control"], b"no-store")
                    self.assertEqual(calls, [] if oversized else [{"value": "ଓଡ଼ିଆ"}])


if __name__ == "__main__":
    unittest.main()
