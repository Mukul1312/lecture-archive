"""Strict byte-oriented SSE framing for the Cartesia transport."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SseFrame:
    event: str | None
    data: bytes


class SseParseError(ValueError):
    """A stable, sanitized failure at the SSE byte boundary."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class IncrementalSseParser:
    def __init__(self, *, maximum_event_bytes: int) -> None:
        if maximum_event_bytes <= 0:
            raise ValueError("maximum_event_bytes must be positive")
        self._maximum_event_bytes = maximum_event_bytes
        self._buffer = bytearray()
        self._event_wire_bytes = 0
        self._frame_lines: list[bytes] = []
        self._event: bytes | None = None
        self._data: list[bytes] = []
        self._frames: list[SseFrame] = []
        self._finished = False
        self._failed = False

    @property
    def frames(self) -> tuple[SseFrame, ...]:
        return tuple(self._frames)

    def feed(self, chunk: bytes) -> tuple[SseFrame, ...]:
        if self._finished:
            raise RuntimeError("SSE parser is already finished")
        if self._failed:
            raise RuntimeError("SSE parser has already failed")
        if not isinstance(chunk, bytes):
            raise TypeError("SSE chunks must be bytes")

        self._buffer.extend(chunk)
        emitted: list[SseFrame] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                self._validate_incomplete_line()
                return tuple(emitted)

            raw_line = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            if raw_line.endswith(b"\r"):
                line = raw_line[:-1]
            else:
                line = raw_line
            if b"\r" in line:
                self._raise("sse_malformed_field")
            if line:
                self._event_wire_bytes += len(raw_line) + 1
                self._guard_event_size()
                self._accept_field(line)
                continue

            frame = self._dispatch()
            if frame is not None:
                self._frames.append(frame)
                emitted.append(frame)

    def finish(self) -> None:
        if self._finished:
            return
        if self._failed:
            raise RuntimeError("SSE parser has already failed")
        if self._buffer or self._frame_lines:
            self._raise("sse_truncated")
        self._finished = True

    def _validate_incomplete_line(self) -> None:
        carriage_scan = self._buffer[:-1] if self._buffer.endswith(b"\r") else self._buffer
        if b"\r" in carriage_scan:
            self._raise("sse_malformed_field")
        if self._event_wire_bytes + len(self._buffer) > self._maximum_event_bytes:
            self._raise("sse_event_too_large")

    def _guard_event_size(self) -> None:
        if self._event_wire_bytes > self._maximum_event_bytes:
            self._raise("sse_event_too_large")

    def _accept_field(self, line: bytes) -> None:
        self._frame_lines.append(line)
        if line.startswith(b":"):
            return
        if b":" not in line:
            self._raise("sse_malformed_field")
        field, value = line.split(b":", 1)
        if value.startswith(b" "):
            value = value[1:]
        if field == b"event":
            self._event = value
        elif field == b"data":
            self._data.append(value)
        else:
            self._raise("sse_malformed_field")

    def _dispatch(self) -> SseFrame | None:
        try:
            b"\n".join(self._frame_lines).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            self._raise("sse_invalid_utf8")

        frame: SseFrame | None = None
        if self._data:
            event = None if self._event is None else self._event.decode("utf-8", errors="strict")
            frame = SseFrame(event=event, data=b"\n".join(self._data))
        self._event_wire_bytes = 0
        self._frame_lines.clear()
        self._event = None
        self._data.clear()
        return frame

    def _raise(self, reason_code: str) -> None:
        self._failed = True
        raise SseParseError(reason_code)
