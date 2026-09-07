"""Bounded synchronous HTTPX transport for Cartesia SSE responses."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from time import monotonic, sleep as default_sleep
from types import TracebackType
from typing import Protocol

import httpx

from .contract import CARTESIA_TRANSPORT_CONTRACT, CartesiaTransportContract
from .sse import IncrementalSseParser, SseFrame, SseParseError


_PROCESS_REQUEST_LOCK = Lock()


class _ResponseIngressError(Exception):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class _BoundedResponseStream(httpx.SyncByteStream):
    """Guard every raw read, including reads HTTPX's decoder does not emit."""

    def __init__(
        self,
        stream: httpx.SyncByteStream,
        *,
        maximum_bytes: int,
        deadline: float,
        clock: Callable[[], float],
    ) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes
        self._deadline = deadline
        self._clock = clock

    def __iter__(self) -> Iterator[bytes]:
        chunks = iter(self._stream)
        received_bytes = 0
        while True:
            self._check_deadline()
            try:
                chunk = next(chunks)
            except StopIteration:
                self._check_deadline()
                return
            self._check_deadline()
            received_bytes += len(chunk)
            if received_bytes > self._maximum_bytes:
                raise _ResponseIngressError("response_too_large")
            yield chunk

    def _check_deadline(self) -> None:
        if self._clock() >= self._deadline:
            raise _ResponseIngressError("operation_timeout")

    def close(self) -> None:
        self._stream.close()


class TransportSubmissionCertainty(str, Enum):
    DEFINITELY_NOT_SENT = "definitely_not_sent"
    SENT = "sent"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class CartesiaTransportOutcome:
    frames: tuple[SseFrame, ...]
    http_status: int | None
    submission: TransportSubmissionCertainty
    stream_complete: bool
    reason_code: str | None
    retry_after_seconds: int | None


class CartesiaCredentialSupplier(Protocol):
    def read_for_transmission(self) -> str: ...


class CartesiaSseTransport:
    """One-client, process-serialized transport with conservative replay rules.

    Retrying a pre-response ``ConnectError`` or ``ConnectTimeout`` relies on the
    production client retaining HTTPX's standard HTTP transport. Injected
    transports exist only so fixture tests can exercise that recorded policy.
    """

    def __init__(
        self,
        *,
        contract: CartesiaTransportContract = CARTESIA_TRANSPORT_CONTRACT,
        http_transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._contract = contract
        self._clock = clock
        self._sleep = sleep
        fixed_headers = {
            "Accept": "text/event-stream",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            contract.api_version_header: contract.api_version,
        }
        self._client = httpx.Client(
            base_url=contract.origin,
            headers=fixed_headers,
            timeout=self._phase_timeout(float(contract.operation_timeout_seconds)),
            transport=http_transport,
            **contract.http_client_options(),
        )

    def stream(
        self,
        *,
        request_body: bytes,
        credentials: CartesiaCredentialSupplier,
    ) -> CartesiaTransportOutcome:
        deadline = self._clock() + self._contract.operation_timeout_seconds
        remaining = self._remaining(deadline)
        if remaining <= 0:
            return self._operation_timeout(TransportSubmissionCertainty.DEFINITELY_NOT_SENT)
        if not _PROCESS_REQUEST_LOCK.acquire(timeout=remaining):
            return self._operation_timeout(TransportSubmissionCertainty.DEFINITELY_NOT_SENT)
        try:
            if self._remaining(deadline) <= 0:
                return self._operation_timeout(TransportSubmissionCertainty.DEFINITELY_NOT_SENT)
            return self._stream_locked(
                request_body=request_body,
                credentials=credentials,
                deadline=deadline,
            )
        finally:
            _PROCESS_REQUEST_LOCK.release()

    def _stream_locked(
        self,
        *,
        request_body: bytes,
        credentials: CartesiaCredentialSupplier,
        deadline: float,
    ) -> CartesiaTransportOutcome:
        for submission_index in range(self._contract.maximum_submissions):
            if self._remaining(deadline) <= 0:
                return self._operation_timeout(TransportSubmissionCertainty.DEFINITELY_NOT_SENT)

            api_key = credentials.read_for_transmission()
            remaining = self._remaining(deadline)
            if remaining <= 0:
                del api_key
                return self._operation_timeout(TransportSubmissionCertainty.DEFINITELY_NOT_SENT)
            timeout = self._phase_timeout(remaining)
            request_headers = {
                self._contract.authentication_header: f"Bearer {api_key}",
            }
            del api_key

            request: httpx.Request | None = None
            response: httpx.Response | None = None
            parser: IncrementalSseParser | None = None
            response_seen = False
            http_status: int | None = None
            retry_after: int | None = None
            try:
                request = self._client.build_request(
                    "POST",
                    self._contract.sse_path,
                    content=request_body,
                    headers=request_headers,
                    timeout=timeout,
                )
                response = self._client.send(request, stream=True)
                try:
                    response_seen = True
                    http_status = response.status_code
                    retry_after = self._bounded_retry_after(response.headers.get("Retry-After"))
                    if self._remaining(deadline) <= 0:
                        return self._operation_timeout(
                            TransportSubmissionCertainty.SENT,
                            http_status=http_status,
                            retry_after_seconds=retry_after,
                        )
                    assert isinstance(response.stream, httpx.SyncByteStream)
                    response.stream = _BoundedResponseStream(
                        response.stream,
                        maximum_bytes=self._contract.maximum_response_bytes,
                        deadline=deadline,
                        clock=self._clock,
                    )
                    if not 200 <= http_status < 300:
                        frames = ()
                        if self._is_sse_response(response):
                            frames = self._collect_non_success_frames(response, deadline)
                        return self._http_failure(http_status, retry_after, frames=frames)

                    parser = IncrementalSseParser(
                        maximum_event_bytes=self._contract.maximum_event_bytes
                    )
                    response_bytes = 0
                    chunks = response.iter_bytes()
                    while True:
                        if self._remaining(deadline) <= 0:
                            return self._operation_timeout(
                                TransportSubmissionCertainty.SENT,
                                frames=parser.frames,
                                http_status=http_status,
                                retry_after_seconds=retry_after,
                            )
                        try:
                            chunk = next(chunks)
                        except StopIteration:
                            break
                        if self._remaining(deadline) <= 0:
                            return self._operation_timeout(
                                TransportSubmissionCertainty.SENT,
                                frames=parser.frames,
                                http_status=http_status,
                                retry_after_seconds=retry_after,
                            )
                        response_bytes += len(chunk)
                        if response_bytes > self._contract.maximum_response_bytes:
                            return self._failure(
                                reason_code="response_too_large",
                                submission=TransportSubmissionCertainty.SENT,
                                frames=parser.frames,
                                http_status=http_status,
                                retry_after_seconds=retry_after,
                            )
                        parser.feed(chunk)

                    if self._remaining(deadline) <= 0:
                        return self._operation_timeout(
                            TransportSubmissionCertainty.SENT,
                            frames=parser.frames,
                            http_status=http_status,
                            retry_after_seconds=retry_after,
                        )
                    parser.finish()
                    return CartesiaTransportOutcome(
                        frames=parser.frames,
                        http_status=http_status,
                        submission=TransportSubmissionCertainty.SENT,
                        stream_complete=True,
                        reason_code=None,
                        retry_after_seconds=retry_after,
                    )
                finally:
                    try:
                        response.close()
                    except httpx.TransportError:
                        if http_status is None or 200 <= http_status < 300:
                            raise
            except (SseParseError, _ResponseIngressError) as error:
                return self._failure(
                    reason_code=error.reason_code,
                    submission=TransportSubmissionCertainty.SENT,
                    frames=() if parser is None else parser.frames,
                    http_status=http_status,
                    retry_after_seconds=retry_after,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                if response_seen:
                    return self._transport_failure(
                        error,
                        response_seen=True,
                        parser=parser,
                        http_status=http_status,
                        retry_after_seconds=retry_after,
                    )
                if submission_index + 1 >= self._contract.maximum_submissions:
                    return self._failure(
                        reason_code=self._transport_reason(error),
                        submission=TransportSubmissionCertainty.DEFINITELY_NOT_SENT,
                    )
                if submission_index >= len(self._contract.retry_backoff_seconds):
                    return self._failure(
                        reason_code=self._transport_reason(error),
                        submission=TransportSubmissionCertainty.DEFINITELY_NOT_SENT,
                    )
                backoff = self._contract.retry_backoff_seconds[submission_index]
                remaining = self._remaining(deadline)
                if remaining <= 0:
                    return self._operation_timeout(
                        TransportSubmissionCertainty.DEFINITELY_NOT_SENT
                    )
                if backoff > remaining:
                    return self._operation_timeout(
                        TransportSubmissionCertainty.DEFINITELY_NOT_SENT
                    )
                self._sleep(backoff)
                if self._remaining(deadline) <= 0:
                    return self._operation_timeout(
                        TransportSubmissionCertainty.DEFINITELY_NOT_SENT
                    )
            except httpx.TransportError as error:
                return self._transport_failure(
                    error,
                    response_seen=response_seen,
                    parser=parser,
                    http_status=http_status,
                    retry_after_seconds=retry_after,
                )
            except httpx.RequestError as error:
                return self._failure(
                    reason_code=(
                        "response_decoding_error"
                        if isinstance(error, httpx.DecodingError)
                        else "request_error"
                    ),
                    submission=(
                        TransportSubmissionCertainty.SENT
                        if response_seen
                        else TransportSubmissionCertainty.AMBIGUOUS
                    ),
                    frames=() if parser is None else parser.frames,
                    http_status=http_status,
                    retry_after_seconds=retry_after,
                )
            finally:
                self._scrub_authorization(request, response)
                request_headers.clear()

        raise RuntimeError("unreachable submission loop")

    def _phase_timeout(self, remaining: float) -> httpx.Timeout:
        contract = self._contract
        return httpx.Timeout(
            connect=min(float(contract.connect_timeout_seconds), remaining),
            read=min(float(contract.read_timeout_seconds), remaining),
            write=min(float(contract.write_timeout_seconds), remaining),
            pool=min(float(contract.connect_timeout_seconds), remaining),
        )

    def _remaining(self, deadline: float) -> float:
        return deadline - self._clock()

    def _transport_failure(
        self,
        error: httpx.TransportError,
        *,
        response_seen: bool,
        parser: IncrementalSseParser | None,
        http_status: int | None,
        retry_after_seconds: int | None,
    ) -> CartesiaTransportOutcome:
        return self._failure(
            reason_code=self._transport_reason(error),
            submission=(
                TransportSubmissionCertainty.SENT
                if response_seen
                else TransportSubmissionCertainty.AMBIGUOUS
            ),
            frames=() if parser is None else parser.frames,
            http_status=http_status,
            retry_after_seconds=retry_after_seconds,
        )

    @staticmethod
    def _transport_reason(error: httpx.TransportError) -> str:
        if isinstance(error, httpx.ConnectTimeout):
            return "connect_timeout"
        if isinstance(error, httpx.ConnectError):
            return "connect_error"
        if isinstance(error, httpx.ReadTimeout):
            return "read_timeout"
        if isinstance(error, httpx.WriteTimeout):
            return "write_timeout"
        if isinstance(error, httpx.PoolTimeout):
            return "pool_timeout"
        if isinstance(error, httpx.TimeoutException):
            return "transport_timeout"
        if isinstance(error, httpx.ReadError):
            return "read_error"
        if isinstance(error, httpx.WriteError):
            return "write_error"
        if isinstance(error, httpx.CloseError):
            return "close_error"
        if isinstance(error, httpx.NetworkError):
            return "network_error"
        if isinstance(error, httpx.ProtocolError):
            return "protocol_error"
        if isinstance(error, httpx.ProxyError):
            return "proxy_error"
        if isinstance(error, httpx.UnsupportedProtocol):
            return "unsupported_protocol"
        return "transport_error"

    @staticmethod
    def _is_sse_response(response: httpx.Response) -> bool:
        media_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        return media_type.strip().lower() == "text/event-stream"

    def _collect_non_success_frames(
        self,
        response: httpx.Response,
        deadline: float,
    ) -> tuple[SseFrame, ...]:
        """Best-effort bounded evidence collection that never replaces HTTP status."""
        parser = IncrementalSseParser(maximum_event_bytes=self._contract.maximum_event_bytes)
        response_bytes = 0
        chunks = response.iter_bytes()
        try:
            while self._remaining(deadline) > 0:
                try:
                    chunk = next(chunks)
                except StopIteration:
                    parser.finish()
                    break
                if self._remaining(deadline) <= 0:
                    break
                response_bytes += len(chunk)
                if response_bytes > self._contract.maximum_response_bytes:
                    break
                parser.feed(chunk)
        except (SseParseError, httpx.RequestError, _ResponseIngressError):
            pass
        return parser.frames

    def _http_failure(
        self,
        status: int,
        retry_after_seconds: int | None,
        *,
        frames: tuple[SseFrame, ...] = (),
    ) -> CartesiaTransportOutcome:
        if 300 <= status < 400:
            reason_code = "http_redirect"
            submission = TransportSubmissionCertainty.SENT
        elif status == 429:
            reason_code = "http_rate_limited"
            submission = TransportSubmissionCertainty.AMBIGUOUS
        elif 400 <= status < 500:
            reason_code = "http_client_error"
            submission = TransportSubmissionCertainty.SENT
        elif 500 <= status < 600:
            reason_code = "http_server_error"
            submission = TransportSubmissionCertainty.AMBIGUOUS
        else:
            reason_code = "http_unexpected_status"
            submission = TransportSubmissionCertainty.SENT
        return self._failure(
            reason_code=reason_code,
            submission=submission,
            frames=frames,
            http_status=status,
            retry_after_seconds=retry_after_seconds,
        )

    def _bounded_retry_after(self, value: str | None) -> int | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped or any(character not in "0123456789" for character in stripped):
            return None
        normalized = stripped.lstrip("0") or "0"
        maximum = str(self._contract.maximum_retry_after_seconds)
        if len(normalized) > len(maximum):
            return self._contract.maximum_retry_after_seconds
        if len(normalized) == len(maximum) and normalized > maximum:
            return self._contract.maximum_retry_after_seconds
        return int(normalized)

    def _scrub_authorization(
        self,
        request: httpx.Request | None,
        response: httpx.Response | None,
    ) -> None:
        requests: list[httpx.Request] = []
        if request is not None:
            requests.append(request)
        if response is not None:
            requests.append(response.request)
            if response.next_request is not None:
                requests.append(response.next_request)
            for historical_response in response.history:
                requests.append(historical_response.request)
                if historical_response.next_request is not None:
                    requests.append(historical_response.next_request)
        seen: set[int] = set()
        for retained_request in requests:
            identity = id(retained_request)
            if identity in seen:
                continue
            seen.add(identity)
            retained_request.headers.pop(self._contract.authentication_header, None)

    @staticmethod
    def _failure(
        *,
        reason_code: str,
        submission: TransportSubmissionCertainty,
        frames: tuple[SseFrame, ...] = (),
        http_status: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> CartesiaTransportOutcome:
        return CartesiaTransportOutcome(
            frames=frames,
            http_status=http_status,
            submission=submission,
            stream_complete=False,
            reason_code=reason_code,
            retry_after_seconds=retry_after_seconds,
        )

    @staticmethod
    def _operation_timeout(
        submission: TransportSubmissionCertainty,
        *,
        frames: tuple[SseFrame, ...] = (),
        http_status: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> CartesiaTransportOutcome:
        return CartesiaSseTransport._failure(
            reason_code="operation_timeout",
            submission=submission,
            frames=frames,
            http_status=http_status,
            retry_after_seconds=retry_after_seconds,
        )

    def close(self) -> None:
        with _PROCESS_REQUEST_LOCK:
            self._client.close()

    def __enter__(self) -> CartesiaSseTransport:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
