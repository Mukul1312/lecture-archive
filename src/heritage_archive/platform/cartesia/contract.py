"""Frozen provider-transport facts and local Cartesia client safety policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CartesiaTransportContract:
    """Provider protocol facts plus bounded local HTTP client safety settings."""

    origin: str
    sse_path: str
    api_version: str
    authentication_header: str
    connect_timeout_seconds: int
    write_timeout_seconds: int
    read_timeout_seconds: int
    operation_timeout_seconds: int
    maximum_submissions: int
    retry_backoff_seconds: tuple[int, ...]
    maximum_retry_after_seconds: int
    maximum_event_bytes: int
    maximum_response_bytes: int
    maximum_decoded_pcm_bytes: int

    @property
    def api_version_header(self) -> str:
        """Return the Cartesia API-version header name fixed by the protocol."""
        return "Cartesia-Version"

    def http_client_options(self) -> dict[str, bool]:
        """Return the non-negotiable redirect and proxy boundary for HTTPX."""
        return {"follow_redirects": False, "trust_env": False}


CARTESIA_TRANSPORT_CONTRACT = CartesiaTransportContract(
    origin="https://api.cartesia.ai",
    sse_path="/tts/sse",
    api_version="2026-08-14",
    authentication_header="Authorization",
    connect_timeout_seconds=10,
    write_timeout_seconds=10,
    read_timeout_seconds=30,
    operation_timeout_seconds=180,
    maximum_submissions=3,
    retry_backoff_seconds=(1, 3),
    maximum_retry_after_seconds=30,
    maximum_event_bytes=1 * 1024 * 1024,
    maximum_response_bytes=32 * 1024 * 1024,
    maximum_decoded_pcm_bytes=16 * 1024 * 1024,
)
