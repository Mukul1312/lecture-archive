"""Immutable HTTP values; importing these does not load a web framework."""

from dataclasses import dataclass, field
from typing import Protocol


MAX_BODY_BYTES = 262144


@dataclass(frozen=True, slots=True)
class WebRequest:
    method: str
    path: str
    headers: tuple[tuple[bytes, bytes], ...] = field(default=(), repr=False)
    body: bytes = field(default=b"", repr=False)
    body_too_large: bool = False


@dataclass(frozen=True, slots=True)
class WebResponse:
    status: int
    body: bytes = field(default=b"", repr=False)
    headers: tuple[tuple[bytes, bytes], ...] = field(default=(), repr=False)


class WebApplication(Protocol):
    def __call__(self, request: WebRequest) -> WebResponse: ...
    def error_response(self, status: int) -> WebResponse: ...
