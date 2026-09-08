"""Process-lifetime one-shot generation confirmations and exclusion gate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from secrets import compare_digest, token_hex
from threading import Lock
from time import monotonic as system_monotonic

from heritage_archive.kernel import ContentDigest
from ...application.results import GenerationEstimateResult
from ...domain.evidence import AttemptState
from ...domain.ids import GenerationPreviewId, NarrationJobId


_TOKEN_LENGTH_BYTES = 32
_TOKEN_PATTERN_LENGTH = _TOKEN_LENGTH_BYTES * 2
_CONFIRMATION_TTL_SECONDS = 600.0
_MAX_LIVE_CONFIRMATIONS = 128
_COLLISION_ATTEMPTS = 8
RECONCILABLE_GENERATION_STATES = frozenset({
    AttemptState.UNKNOWN,
    AttemptState.RESERVED,
    AttemptState.INPUT_FROZEN,
    AttemptState.EXTERNAL_WORK_STARTED,
    AttemptState.ARTIFACTS_STAGED,
    AttemptState.ARTIFACTS_PUBLISHED,
})


class ConfirmationCapacityReached(Exception):
    """The bounded process store contains the maximum live confirmations."""


class ConfirmationUnavailable(Exception):
    """The submitted confirmation is absent, expired, consumed, or not owned."""


class ConfirmationTokenCreationFailed(Exception):
    """Cryptographic token creation did not produce a unique valid token."""


@dataclass(frozen=True, slots=True)
class _GenerationConfirmation:
    token: str = field(repr=False)
    session_identity: str = field(repr=False)
    job_id: NarrationJobId = field(repr=False)
    preview_id: GenerationPreviewId = field(repr=False)
    expected_revision: int = field(repr=False)
    preview_digest: ContentDigest = field(repr=False)
    estimated_usage: str = field(repr=False)
    expires_at: float = field(repr=False)


def _cryptographic_token() -> str:
    return token_hex(_TOKEN_LENGTH_BYTES)


def _is_token(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == _TOKEN_PATTERN_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


class ProcessGenerationControl:
    """Own one bounded confirmation store and one shared nonblocking gate."""

    def __init__(
        self,
        session_identity: str,
        *,
        monotonic: Callable[[], float] = system_monotonic,
        token_factory: Callable[[], str] = _cryptographic_token,
    ) -> None:
        if not _is_token(session_identity):
            raise ValueError("invalid process generation session")
        if not callable(monotonic) or not callable(token_factory):
            raise ValueError("process generation control requires callable sources")
        self._session_identity = session_identity
        self._monotonic = monotonic
        self._token_factory = token_factory
        self._confirmations: list[_GenerationConfirmation] = []
        self._store_lock = Lock()
        self._gate = Lock()

    @property
    def busy(self) -> bool:
        """Return only an informational snapshot; mutation callers must acquire."""
        return self._gate.locked()

    def acquire(self) -> bool:
        return self._gate.acquire(blocking=False)

    def release(self) -> None:
        self._gate.release()

    def issue(self, result: GenerationEstimateResult) -> str:
        if type(result) is not GenerationEstimateResult:
            raise TypeError("confirmation issue requires GenerationEstimateResult")
        with self._store_lock:
            now = self._now()
            self._prune(now)
            if len(self._confirmations) >= _MAX_LIVE_CONFIRMATIONS:
                raise ConfirmationCapacityReached()
            for _ in range(_COLLISION_ATTEMPTS):
                token = self._token_factory()
                if not _is_token(token):
                    raise ConfirmationTokenCreationFailed()
                if any(compare_digest(token, item.token) for item in self._confirmations):
                    continue
                preview = result.preview
                self._confirmations.append(
                    _GenerationConfirmation(
                        token,
                        self._session_identity,
                        result.job_id,
                        preview.preview_id,
                        result.revision,
                        preview.preview_digest,
                        preview.estimated_usage,
                        now + _CONFIRMATION_TTL_SECONDS,
                    )
                )
                return token
        raise ConfirmationTokenCreationFailed()

    def consume(self, token: str, job_id: NarrationJobId) -> _GenerationConfirmation:
        return self._consume_for_session(token, self._session_identity, job_id)

    def _consume_for_session(
        self,
        token: str,
        session_identity: str,
        job_id: NarrationJobId,
    ) -> _GenerationConfirmation:
        """Internal test seam for proving session binding without exposing identity."""
        if not _is_token(token) or not _is_token(session_identity) or type(job_id) is not NarrationJobId:
            raise ConfirmationUnavailable()
        with self._store_lock:
            now = self._now()
            self._prune(now)
            matched_index = None
            for index, item in enumerate(self._confirmations):
                token_matches = compare_digest(token, item.token)
                session_matches = compare_digest(session_identity, item.session_identity)
                if token_matches and session_matches and item.job_id == job_id:
                    matched_index = index
            if matched_index is None:
                raise ConfirmationUnavailable()
            return self._confirmations.pop(matched_index)

    def _now(self) -> float:
        value = self._monotonic()
        if type(value) not in (int, float) or not isfinite(value):
            raise ConfirmationTokenCreationFailed()
        return float(value)

    def _prune(self, now: float) -> None:
        self._confirmations[:] = [item for item in self._confirmations if now < item.expires_at]
