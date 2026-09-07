"""Socket-free contracts for the neutral loopback transport."""

import threading
import unittest
from unittest.mock import patch

from heritage_archive.platform.web import WebRequest, WebResponse
from heritage_archive.platform.web.loopback import build_asgi


class _Application:
    """Neutral fixture boundary, including prebuilt transport fallback values."""
    def __init__(self, dispatch):
        self.dispatch = dispatch

    def __call__(self, request):
        return self.dispatch(request)

    def error_response(self, status):
        return WebResponse(status, b"fixture", ((b"content-length", b"7"),))


class LoopbackWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_and_websockets_never_dispatch_http_work(self):
        def application(request):
            self.fail("non-HTTP scope dispatched")
        for kind in ("lifespan", "websocket"):
            messages = []
            incoming = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
            async def receive():
                return next(incoming)
            async def send(message):
                messages.append(message)
            await build_asgi(_Application(application))({"type": kind}, receive, send)
            self.assertEqual(messages, [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]
                             if kind == "lifespan" else [{"type": "websocket.close", "code": 1008}])

    async def test_body_cap_is_inclusive_and_stops_before_an_excess_chunk_is_retained(self):
        for size in (262144, 262145):
            with self.subTest(size=size):
                calls, messages = [], []
                consumed = 0

                async def receive():
                    nonlocal consumed
                    consumed += 1
                    if consumed == 1:
                        return {"type": "http.request", "body": b"x" * 262143, "more_body": True}
                    if consumed == 2:
                        return {"type": "http.request", "body": b"y" * (size - 262143), "more_body": size > 262144}
                    self.fail("consumed beyond first excess")

                async def send(message):
                    messages.append(message)

                def application(request):
                    calls.append(request)
                    return WebResponse(200)

                await build_asgi(_Application(application))({"type": "http", "method": "POST", "path": "/", "headers": []}, receive, send)
                self.assertEqual(consumed, 2)
                self.assertEqual(calls[0].body_too_large, size > 262144)
                self.assertEqual(calls[0].body, b"" if size > 262144 else b"x" * 262143 + b"y")

    async def test_disconnect_never_dispatches_and_head_never_sends_body(self):
        for disconnected in (True, False):
            calls, messages = [], []

            async def receive():
                return {"type": "http.disconnect"} if disconnected else {"type": "http.request", "body": b""}

            async def send(message):
                messages.append(message)

            def application(request):
                calls.append(request)
                return WebResponse(200, b"private", ((b"content-length", b"7"),))

            await build_asgi(_Application(application))({"type": "http", "method": "HEAD", "path": "/", "headers": []}, receive, send)
            if disconnected:
                self.assertEqual((calls, messages), ([], []))
            else:
                self.assertEqual(messages[1]["body"], b"")
                self.assertEqual(messages[0]["headers"].count((b"content-length", b"7")), 1)

    def test_serve_has_only_fixed_safe_listener_configuration(self):
        from heritage_archive.platform.web.loopback import serve_loopback
        with patch("uvicorn.run") as run:
            serve_loopback(_Application(lambda request: WebResponse(200)))
        from uvicorn.protocols.http.h11_impl import H11Protocol
        arguments = dict(run.call_args.kwargs)
        self.assertTrue(issubclass(arguments.pop("http"), H11Protocol))
        self.assertEqual(arguments, {
            "host": "127.0.0.1", "port": 8765, "workers": 1,
            "proxy_headers": False, "reload": False, "access_log": False,
        })

    async def test_translation_preserves_duplicates_and_dispatches_in_worker(self):
        from heritage_archive.platform.web.loopback import WebResponse, build_asgi

        received = []
        event_thread = threading.get_ident()

        def application(request):
            received.append((request, threading.get_ident()))
            return WebResponse(202, b"done", ((b"x-result", b"one"),))

        messages = []
        chunks = iter([{"type": "http.request", "body": b"a", "more_body": True},
                       {"type": "http.request", "body": b"b", "more_body": False}])

        async def receive():
            return next(chunks)

        async def send(message):
            messages.append(message)

        await build_asgi(_Application(application))(
            {"type": "http", "method": "POST", "path": "/fixture",
             "headers": [(b"host", b"one"), (b"host", b"two")]}, receive, send)
        request, worker = received[0]
        self.assertNotEqual(worker, event_thread)
        self.assertEqual(request.headers, ((b"host", b"one"), (b"host", b"two")))
        self.assertEqual((request.method, request.path, request.body, request.body_too_large),
                         ("POST", "/fixture", b"ab", False))
        self.assertEqual(messages[0]["status"], 202)
        self.assertEqual(messages[1]["body"], b"done")


if __name__ == "__main__":
    unittest.main()
