"""Transaction, artifact, operation, event, and deterministic-input ports.

These are the ports the application owns and infrastructure implements. They
speak domain language only: no SQL, no filesystem path, no subprocess
exception, no HTTP response, no JSONL row (design section 10.2).

`Clock` and `IdGenerator` exist so the domain never generates its own time or
identity. Every aggregate factory in Tasks 2-5 takes exact IDs and times as
arguments for exactly this reason, which keeps them deterministic under test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from heritage_production.domain.shared import (
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    DomainEvent,
    DomainEventId,
    OperationId,
    SourceSpan,
    ValidationError,
)


@dataclass(frozen=True, slots=True)
class StagedArtifact:
    """Bytes that have been hashed and size-checked but not yet promoted."""

    staging_token: str
    content_digest: ContentDigest
    byte_size: int
    media_type: str


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """The durable result of one completed content-producing command.

    Design 13.4 stores the operation's *result*, not only a digest of it.
    That is what makes design 9.4's "an identical replay returns the original
    result" reachable for a command whose result is a generated identity:
    `CreateProduction` takes no Production ID and returns one (design 9.1), so
    without the stored payload a replay would have nothing to reload.

    `result_digest` stays alongside it, so a payload edited in storage is
    detectable rather than authoritative.
    """

    operation_id: OperationId
    command_name: str
    input_digest: ContentDigest
    result_digest: ContentDigest
    result_payload: dict
    completed_at_us: int

    def __post_init__(self) -> None:
        if type(self.operation_id) is not OperationId:
            raise ValidationError("operation_id must be an exact OperationId")
        if type(self.command_name) is not str or not self.command_name:
            raise ValidationError("command_name must be a nonempty string")
        for field_name in ("input_digest", "result_digest"):
            if type(getattr(self, field_name)) is not ContentDigest:
                raise ValidationError(f"{field_name} must be an exact ContentDigest")
        if type(self.result_payload) is not dict:
            raise ValidationError("result_payload must be a JSON object")
        if type(self.completed_at_us) is not int or self.completed_at_us <= 0:
            raise ValidationError("completed_at_us must be positive epoch microseconds")


@runtime_checkable
class UnitOfWork(Protocol):
    """One transaction, one aggregate root (design section 9.3).

    The aggregate state, the operation result, any canonical write marker, and
    every emitted outbox event commit together or not at all.
    """

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Content-addressed storage; the domain never sees a path."""

    def stage(self, data: bytes, *, media_type: str) -> StagedArtifact: ...

    def promote(self, staged: StagedArtifact, *, operation_id: OperationId) -> ArtifactRef: ...

    def open(self, artifact_id: ArtifactId) -> bytes: ...

    def verify(self, artifact: ArtifactRef) -> bool: ...


@runtime_checkable
class ArtifactMetadataReader(Protocol):
    """Media properties read from stored bytes, never from a filename."""

    def duration_us(self, artifact: ArtifactRef) -> int: ...

    def media_properties(self, artifact: ArtifactRef) -> dict[str, str]: ...


@runtime_checkable
class ArtifactDerivationVerifier(Protocol):
    """Design 11.5: a derived artifact must match its source version and span.

    A hash-valid excerpt taken from the wrong span is rejected, so verification
    takes the declared span rather than trusting the output digest alone.
    """

    def verify_derivation(
        self,
        *,
        output: ArtifactRef,
        inputs: tuple[ArtifactRef, ...],
        source_span: SourceSpan,
        renderer_version: str,
        configuration_digest: ContentDigest,
    ) -> bool: ...


@runtime_checkable
class OperationRecorder(Protocol):
    """Idempotency: an identical replay returns the original result.

    Repeating an operation ID with different inputs is a conflict, never a
    silent overwrite (design section 9.4).

    `record` takes the transaction explicitly. Design 9.4 requires the record
    and the aggregate change to become durable together, and an adapter that
    held its own connection would satisfy this signature only by ignoring the
    argument -- which is visible in review, unlike a shared connection that is
    merely assumed.
    """

    def find(self, operation_id: OperationId) -> OperationRecord | None: ...

    def record(self, record: OperationRecord, *, transaction: object) -> None: ...


@runtime_checkable
class DomainEventOutbox(Protocol):
    """At-least-once delivery for events whose after-commit effect must survive.

    The row is inserted in the same transaction as the aggregate, so a crash
    between the two is impossible (design section 9.6).
    """

    def enqueue(self, event: DomainEvent) -> None: ...

    def mark_delivered(self, event_id: DomainEventId, *, handler: str) -> None: ...


@runtime_checkable
class Clock(Protocol):
    """UTC epoch microseconds; the domain never reads a wall clock itself."""

    def now_us(self) -> int: ...


@runtime_checkable
class IdGenerator(Protocol):
    """Opaque application-generated identity, never derived from content."""

    def new_id(self) -> str: ...
