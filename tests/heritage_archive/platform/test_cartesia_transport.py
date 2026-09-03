"""Fixture-only tests for the bounded HTTPX Cartesia SSE transport."""

from __future__ import annotations

from dataclasses import replace
import gzip
from pathlib import Path
import sys
import threading
import unittest
from collections.abc import Callable, Iterator

import httpx


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.platform.cartesia.contract import CARTESIA_TRANSPORT_CONTRACT
from heritage_archive.platform.cartesia.sse import SseFrame
from heritage_archive.platform.cartesia.transport import (
    CartesiaSseTransport,
    TransportSubmissionCertainty,
)


class FixtureStream(httpx.SyncByteStream):
    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        failure: httpx.TransportError | None = None,
        close_failure: httpx.TransportError | None = None,
    ) -> None:
        self._chunks = chunks
        self._failure = failure
        self._close_failure = close_failure
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks
        if self._failure is not None:
            raise self._failure

    def close(self) -> None:
        self.closed = True
        if self._close_failure is not None:
            raise self._close_failure


class AdvancingStream(httpx.SyncByteStream):
    def __init__(self, clock: "ManualClock") -> None:
        self._clock = clock
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield b"data: retained\n\n"
        self._clock.advance(181)
        yield b"data: outside-budget\n\n"

    def close(self) -> None:
        self.closed = True


class CredentialSequence:
    def __init__(
        self,
        *values: str,
        before_read: Callable[[], None] | None = None,
    ) -> None:
        self._values = values
        self._before_read = before_read
        self.calls = 0
        self.called = threading.Event()

    def read_for_transmission(self) -> str:
        if self._before_read is not None:
            self._before_read()
        self.called.set()
        value = self._values[self.calls]
        self.calls += 1
        return value


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


class CartesiaSseTransportTests(unittest.TestCase):
    def make_transport(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        *,
        contract=CARTESIA_TRANSPORT_CONTRACT,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> CartesiaSseTransport:
        transport = CartesiaSseTransport(
            contract=contract,
            http_transport=httpx.MockTransport(handler),
            **({} if clock is None else {"clock": clock}),
            **({} if sleep is None else {"sleep": sleep}),
        )
        self.addCleanup(transport.close)
        return transport

    def test_posts_frozen_bytes_to_fixed_endpoint_with_ephemeral_credentials(self) -> None:
        """Serializing JSON or retaining authorization would violate the transport boundary."""
        requests: list[httpx.Request] = []
        responses: list[httpx.Response] = []
        authorizations: list[str] = []
        response_stream = FixtureStream(
            (b"event: chunk\r\ndata: \xe0\xac", b"\x93\r\n\r\ndata: done\n\n")
        )

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            authorizations.append(request.headers["authorization"])
            response = httpx.Response(200, stream=response_stream)
            responses.append(response)
            return response

        secret = "fixture-secret-never-evidence"
        credentials = CredentialSequence(secret)
        transport = self.make_transport(handler)

        outcome = transport.stream(request_body=b"\xffalready-frozen", credentials=credentials)

        self.assertEqual(
            outcome.frames,
            (
                SseFrame(event="chunk", data="ଓ".encode("utf-8")),
                SseFrame(event=None, data=b"done"),
            ),
        )
        self.assertEqual(outcome.http_status, 200)
        self.assertEqual(outcome.submission, TransportSubmissionCertainty.SENT)
        self.assertTrue(outcome.stream_complete)
        self.assertIsNone(outcome.reason_code)
        self.assertIsNone(outcome.retry_after_seconds)
        self.assertTrue(response_stream.closed)
        self.assertEqual(credentials.calls, 1)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), "https://api.cartesia.ai/tts/sse")
        self.assertEqual(request.content, b"\xffalready-frozen")
        self.assertEqual(request.headers["accept"], "text/event-stream")
        self.assertEqual(request.headers["content-type"], "application/json")
        self.assertEqual(request.headers["accept-encoding"], "identity")
        self.assertEqual(request.headers["cartesia-version"], "2026-08-14")
        self.assertEqual(authorizations, [f"Bearer {secret}"])
        self.assertNotIn("authorization", request.headers)
        self.assertNotIn("authorization", responses[0].request.headers)
        self.assertEqual(
            request.extensions["timeout"],
            {"connect": 10.0, "read": 30.0, "write": 10.0, "pool": 10.0},
        )
        self.assertNotIn(secret, repr(outcome))

    def test_http_content_encoding_is_decoded_before_sse_and_before_response_cap(self) -> None:
        """A peer ignoring identity encoding must not corrupt SSE or bypass its decoded cap."""
        wire = b"data: " + (b"a" * 128) + b"\n\n"
        compressed = gzip.compress(wire)

        success_transport = self.make_transport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=FixtureStream((compressed[:7], compressed[7:])),
            )
        )
        success = success_transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(success.frames, (SseFrame(event=None, data=b"a" * 128),))
        self.assertTrue(success.stream_complete)

        capped_contract = replace(CARTESIA_TRANSPORT_CONTRACT, maximum_response_bytes=64)
        capped_transport = self.make_transport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Encoding": "gzip"},
                stream=FixtureStream((compressed,)),
            ),
            contract=capped_contract,
        )
        capped = capped_transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(capped.reason_code, "response_too_large")
        self.assertEqual(capped.frames, ())

    def test_connect_failures_before_a_response_retry_with_fixed_backoff(self) -> None:
        """Removing the narrow retry would discard a request proven not to have been sent."""
        authorizations: list[str] = []
        failures: list[type[httpx.TransportError]] = [httpx.ConnectError, httpx.ConnectTimeout]
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            authorizations.append(request.headers["authorization"])
            if failures:
                failure = failures.pop(0)
                raise failure("sanitized fixture")
            return httpx.Response(200, stream=FixtureStream((b"data: complete\n\n",)))

        credentials = CredentialSequence("first", "second", "third")
        transport = self.make_transport(handler, sleep=sleeps.append)

        outcome = transport.stream(request_body=b"body", credentials=credentials)

        self.assertEqual(outcome.frames, (SseFrame(event=None, data=b"complete"),))
        self.assertTrue(outcome.stream_complete)
        self.assertEqual(credentials.calls, 3)
        self.assertEqual(authorizations, ["Bearer first", "Bearer second", "Bearer third"])
        self.assertEqual(sleeps, [1, 3])

    def test_connect_retry_exhaustion_is_definitely_not_sent_and_bounded(self) -> None:
        """A fourth connection attempt would exceed the frozen retry envelope."""
        calls = 0
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("fixture text must not escape")

        credentials = CredentialSequence("one", "two", "three")
        transport = self.make_transport(handler, sleep=sleeps.append)

        outcome = transport.stream(request_body=b"body", credentials=credentials)

        self.assertEqual(calls, 3)
        self.assertEqual(credentials.calls, 3)
        self.assertEqual(sleeps, [1, 3])
        self.assertEqual(outcome.frames, ())
        self.assertIsNone(outcome.http_status)
        self.assertEqual(
            outcome.submission,
            TransportSubmissionCertainty.DEFINITELY_NOT_SENT,
        )
        self.assertFalse(outcome.stream_complete)
        self.assertEqual(outcome.reason_code, "connect_error")
        self.assertNotIn("fixture text", repr(outcome))

    def test_retained_connect_exception_has_its_request_credential_scrubbed(self) -> None:
        """An exception retained by a transport must not keep Authorization after return."""
        retained: list[httpx.ConnectError] = []
        contract = replace(CARTESIA_TRANSPORT_CONTRACT, maximum_submissions=1)

        def handler(request: httpx.Request) -> httpx.Response:
            error = httpx.ConnectError("fixture")
            retained.append(error)
            raise error

        transport = self.make_transport(handler, contract=contract)
        outcome = transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(outcome.reason_code, "connect_error")
        self.assertEqual(len(retained), 1)
        self.assertNotIn("authorization", retained[0].request.headers)

    def test_non_connect_transport_failures_are_never_replayed(self) -> None:
        """Write/read/pool/protocol failures do not prove that paid work was unsent."""
        fixtures: tuple[tuple[type[httpx.TransportError], str], ...] = (
            (httpx.WriteTimeout, "write_timeout"),
            (httpx.ReadTimeout, "read_timeout"),
            (httpx.PoolTimeout, "pool_timeout"),
            (httpx.RemoteProtocolError, "protocol_error"),
        )

        for failure, reason_code in fixtures:
            with self.subTest(failure=failure.__name__):
                calls = 0
                sleeps: list[float] = []

                def handler(request: httpx.Request) -> httpx.Response:
                    nonlocal calls
                    calls += 1
                    raise failure("credential-like-secret")

                credentials = CredentialSequence("credential-like-secret")
                transport = self.make_transport(handler, sleep=sleeps.append)
                outcome = transport.stream(request_body=b"body", credentials=credentials)

                self.assertEqual(calls, 1)
                self.assertEqual(credentials.calls, 1)
                self.assertEqual(sleeps, [])
                self.assertEqual(outcome.submission, TransportSubmissionCertainty.AMBIGUOUS)
                self.assertEqual(outcome.reason_code, reason_code)
                self.assertNotIn("credential-like-secret", repr(outcome))

    def test_completed_frames_survive_a_read_timeout_and_response_closes(self) -> None:
        """A later read timeout must retain partial evidence without replaying the request."""
        response_stream = FixtureStream(
            (b"data: retained\n\n",),
            failure=httpx.ReadTimeout("private provider detail"),
        )
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=response_stream)

        transport = self.make_transport(handler, sleep=lambda seconds: self.fail("must not retry"))

        outcome = transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(calls, 1)
        self.assertEqual(outcome.frames, (SseFrame(event=None, data=b"retained"),))
        self.assertEqual(outcome.http_status, 200)
        self.assertEqual(outcome.submission, TransportSubmissionCertainty.SENT)
        self.assertFalse(outcome.stream_complete)
        self.assertEqual(outcome.reason_code, "read_timeout")
        self.assertTrue(response_stream.closed)

    def test_429_and_5xx_are_ambiguous_never_retried_and_retry_after_is_bounded(self) -> None:
        """HTTP status alone is not authoritative evidence that synthesis was unprocessed."""
        fixtures = (
            (429, "999", "http_rate_limited", 30),
            (503, "not-a-delta", "http_server_error", None),
        )

        for status, retry_after, reason_code, expected_retry_after in fixtures:
            with self.subTest(status=status):
                calls = 0
                sleeps: list[float] = []

                def handler(request: httpx.Request) -> httpx.Response:
                    nonlocal calls
                    calls += 1
                    return httpx.Response(status, headers={"Retry-After": retry_after})

                transport = self.make_transport(handler, sleep=sleeps.append)
                outcome = transport.stream(
                    request_body=b"body",
                    credentials=CredentialSequence("secret"),
                )

                self.assertEqual(calls, 1)
                self.assertEqual(sleeps, [])
                self.assertEqual(outcome.http_status, status)
                self.assertEqual(outcome.submission, TransportSubmissionCertainty.AMBIGUOUS)
                self.assertEqual(outcome.reason_code, reason_code)
                self.assertEqual(outcome.retry_after_seconds, expected_retry_after)

    def test_retry_after_rejects_duplicates_and_caps_arbitrarily_long_digits(self) -> None:
        """Header ambiguity or Python's digit limit must not escape the evidence boundary."""
        fixtures = (
            ([('Retry-After', '7'), ('Retry-After', '8')], None),
            ({"Retry-After": "9" * 10_000}, 30),
        )

        for headers, expected in fixtures:
            with self.subTest(expected=expected):
                transport = self.make_transport(
                    lambda request, headers=headers: httpx.Response(429, headers=headers)
                )
                outcome = transport.stream(
                    request_body=b"body",
                    credentials=CredentialSequence("secret"),
                )

                self.assertEqual(outcome.reason_code, "http_rate_limited")
                self.assertEqual(outcome.retry_after_seconds, expected)

    def test_non_success_sse_preserves_frames_without_obscuring_http_reason(self) -> None:
        """Completed error frames are evidence, while status remains the primary failure."""
        response_stream = FixtureStream(
            (b"event: error\ndata: retained\n\n", b"data: " + (b"x" * 64)),
            close_failure=httpx.CloseError("secondary close failure"),
        )
        contract = replace(CARTESIA_TRANSPORT_CONTRACT, maximum_event_bytes=32)
        transport = self.make_transport(
            lambda request: httpx.Response(
                503,
                headers={"Content-Type": "text/event-stream"},
                stream=response_stream,
            ),
            contract=contract,
        )

        outcome = transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(outcome.frames, (SseFrame(event="error", data=b"retained"),))
        self.assertEqual(outcome.http_status, 503)
        self.assertEqual(outcome.submission, TransportSubmissionCertainty.AMBIGUOUS)
        self.assertFalse(outcome.stream_complete)
        self.assertEqual(outcome.reason_code, "http_server_error")
        self.assertTrue(response_stream.closed)

    def test_redirect_is_returned_as_rejected_evidence_and_never_followed(self) -> None:
        """Following a redirect could transmit credentials beyond the fixed provider URL."""
        seen_urls: list[str] = []
        responses: list[httpx.Response] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            response = httpx.Response(307, headers={"Location": "/must-not-follow"})
            responses.append(response)
            return response

        transport = self.make_transport(handler)
        outcome = transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(seen_urls, ["https://api.cartesia.ai/tts/sse"])
        self.assertEqual(outcome.http_status, 307)
        self.assertEqual(outcome.submission, TransportSubmissionCertainty.SENT)
        self.assertFalse(outcome.stream_complete)
        self.assertEqual(outcome.reason_code, "http_redirect")
        self.assertIsNotNone(responses[0].next_request)
        self.assertNotIn("authorization", responses[0].next_request.headers)

    def test_truncated_invalid_and_oversized_sse_return_stable_failure_evidence(self) -> None:
        """Parser failures must be classified without exception text or lost prior frames."""
        fixtures = (
            ((b"data: retained\n\ndata: partial",), 128, "sse_truncated"),
            ((b"data: retained\n\ndata: \xff\n\n",), 128, "sse_invalid_utf8"),
            ((b"data: retained\n\ndata: 12345678901234567",), 16, "sse_event_too_large"),
        )

        for chunks, event_limit, reason_code in fixtures:
            with self.subTest(reason_code=reason_code):
                response_stream = FixtureStream(chunks)
                contract = replace(
                    CARTESIA_TRANSPORT_CONTRACT,
                    maximum_event_bytes=event_limit,
                )
                transport = self.make_transport(
                    lambda request: httpx.Response(200, stream=response_stream),
                    contract=contract,
                )

                outcome = transport.stream(
                    request_body=b"body",
                    credentials=CredentialSequence("secret"),
                )

                self.assertEqual(outcome.frames, (SseFrame(event=None, data=b"retained"),))
                self.assertEqual(outcome.http_status, 200)
                self.assertEqual(outcome.submission, TransportSubmissionCertainty.SENT)
                self.assertFalse(outcome.stream_complete)
                self.assertEqual(outcome.reason_code, reason_code)
                self.assertTrue(response_stream.closed)

    def test_total_response_limit_preserves_only_frames_completed_below_the_cap(self) -> None:
        """One oversized chunk must not enter either the parser or retained evidence."""
        first = b"data: retained\n\n"
        response_stream = FixtureStream((first, b"data: outside-limit\n\n"))
        contract = replace(
            CARTESIA_TRANSPORT_CONTRACT,
            maximum_response_bytes=len(first) + 4,
        )
        transport = self.make_transport(
            lambda request: httpx.Response(200, stream=response_stream),
            contract=contract,
        )

        outcome = transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(outcome.frames, (SseFrame(event=None, data=b"retained"),))
        self.assertEqual(outcome.reason_code, "response_too_large")
        self.assertEqual(outcome.submission, TransportSubmissionCertainty.SENT)
        self.assertFalse(outcome.stream_complete)
        self.assertTrue(response_stream.closed)

    def test_monotonic_budget_includes_backoff_and_stops_before_another_attempt(self) -> None:
        """Retry sleeping must consume the same total-operation budget as HTTP work."""
        clock = ManualClock()
        calls = 0
        contract = replace(CARTESIA_TRANSPORT_CONTRACT, operation_timeout_seconds=1)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("fixture")

        credentials = CredentialSequence("first", "unused-second")
        transport = self.make_transport(
            handler,
            contract=contract,
            clock=clock,
            sleep=clock.sleep,
        )

        outcome = transport.stream(request_body=b"body", credentials=credentials)

        self.assertEqual(clock.now, 1)
        self.assertEqual(calls, 1)
        self.assertEqual(credentials.calls, 1)
        self.assertEqual(outcome.submission, TransportSubmissionCertainty.DEFINITELY_NOT_SENT)
        self.assertEqual(outcome.reason_code, "operation_timeout")

    def test_phase_timeouts_are_capped_by_budget_remaining_after_credential_read(self) -> None:
        """A slow credential read must reduce every following blocking HTTP phase bound."""
        clock = ManualClock()
        seen_timeout: list[dict[str, float]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_timeout.append(request.extensions["timeout"])
            return httpx.Response(200, stream=FixtureStream((b"data: complete\n\n",)))

        credentials = CredentialSequence("secret", before_read=lambda: clock.advance(175))
        transport = self.make_transport(handler, clock=clock, sleep=clock.sleep)

        outcome = transport.stream(request_body=b"body", credentials=credentials)

        self.assertTrue(outcome.stream_complete)
        self.assertEqual(
            seen_timeout,
            [{"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}],
        )

    def test_budget_expiry_during_a_blocking_chunk_is_detected_at_next_boundary(self) -> None:
        """The sync adapter must fail closed without claiming in-call cancellation."""
        clock = ManualClock()
        response_stream = AdvancingStream(clock)
        transport = self.make_transport(
            lambda request: httpx.Response(200, stream=response_stream),
            clock=clock,
            sleep=clock.sleep,
        )

        outcome = transport.stream(
            request_body=b"body",
            credentials=CredentialSequence("secret"),
        )

        self.assertEqual(outcome.frames, (SseFrame(event=None, data=b"retained"),))
        self.assertEqual(outcome.http_status, 200)
        self.assertEqual(outcome.submission, TransportSubmissionCertainty.SENT)
        self.assertFalse(outcome.stream_complete)
        self.assertEqual(outcome.reason_code, "operation_timeout")
        self.assertTrue(response_stream.closed)

    def test_process_lock_serializes_calls_across_transport_instances(self) -> None:
        """Creating a second adapter must not permit a second provider call in flight."""
        first_entered = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_handler_called = threading.Event()
        results: list[object] = []
        errors: list[BaseException] = []

        def first_handler(request: httpx.Request) -> httpx.Response:
            first_entered.set()
            if not release_first.wait(timeout=2):
                raise AssertionError("test did not release first request")
            return httpx.Response(200, stream=FixtureStream((b"data: first\n\n",)))

        def second_handler(request: httpx.Request) -> httpx.Response:
            second_handler_called.set()
            return httpx.Response(200, stream=FixtureStream((b"data: second\n\n",)))

        first_transport = self.make_transport(first_handler)
        second_transport = self.make_transport(second_handler)
        first_credentials = CredentialSequence("first-secret")
        second_credentials = CredentialSequence("second-secret")

        def invoke(
            transport: CartesiaSseTransport,
            body: bytes,
            credentials: CredentialSequence,
            started: threading.Event | None = None,
        ) -> None:
            if started is not None:
                started.set()
            try:
                results.append(transport.stream(request_body=body, credentials=credentials))
            except BaseException as error:  # pragma: no cover - reported by the main test thread
                errors.append(error)

        first = threading.Thread(
            target=invoke,
            args=(first_transport, b"first", first_credentials),
        )
        second = threading.Thread(
            target=invoke,
            args=(second_transport, b"second", second_credentials, second_started),
        )
        first.start()
        self.assertTrue(first_entered.wait(timeout=1))
        second.start()
        self.assertTrue(second_started.wait(timeout=1))
        try:
            self.assertFalse(second_credentials.called.wait(timeout=0.1))
            self.assertFalse(second_handler_called.is_set())
        finally:
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(first_credentials.calls, 1)
        self.assertEqual(second_credentials.calls, 1)
        self.assertTrue(second_handler_called.is_set())
        self.assertTrue(all(result.stream_complete for result in results))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
