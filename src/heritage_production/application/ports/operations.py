"""Backup, integrity, migration-authority, and read-model ports.

Master-plan Task 6 names these alongside the design's section 10.2 list. They
are operational rather than domain ports: migration authority records and
canonical write markers are infrastructure facts, explicitly *not* a seventh
aggregate root (design section 17.2), and read services join tables without
loading aggregates (design section 9.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from heritage_production.domain.shared import (
    ActorId,
    ArtifactRef,
    BackupId,
    ContentDigest,
    MigrationDecisionId,
    OperationId,
    ProductionId,
)


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """A sealed backup: snapshot, schema, and the exact objects it contains."""

    backup_id: BackupId
    database_digest: ContentDigest
    schema_version: int
    referenced_object_digests: tuple[ContentDigest, ...]
    parent_backup_id: BackupId | None
    parent_manifest_digest: ContentDigest | None
    manifest_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    """One blocking or reportable integrity finding (design section 14.5)."""

    code: str
    detail: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class MigrationAuthorityRecord:
    """An append-only cutover fact in an unbroken predecessor-digest chain."""

    migration_decision_id: MigrationDecisionId
    production_id: ProductionId
    predecessor_decision_id: MigrationDecisionId | None
    predecessor_digest: ContentDigest | None
    from_authority: str
    to_authority: str
    canonical_write_watermark: int
    steward_actor_id: ActorId
    reason: str
    decided_at_us: int
    semantic_digest: ContentDigest
    wrapper: ArtifactRef


@runtime_checkable
class BackupService(Protocol):
    """Design 11.8: membership comes only from the closed SQLite snapshot."""

    def create(self, *, operation_id: OperationId, parent: BackupId | None) -> BackupManifest: ...

    def verify(self, backup_id: BackupId) -> tuple[IntegrityIssue, ...]: ...

    def restore_into_empty(self, *, backup_id: BackupId, target: str) -> tuple[IntegrityIssue, ...]: ...


@runtime_checkable
class IntegrityService(Protocol):
    """Design 14.5: the report the steward reads before trusting the store."""

    def check(self, production_id: ProductionId | None = None) -> tuple[IntegrityIssue, ...]: ...


@runtime_checkable
class MigrationAuthorityRecorder(Protocol):
    """Design 17.2: routing is decided only by the latest valid record.

    `canonical_write_markers` make the first post-cutover write irreversible,
    so `supersede_pre_write_cutover` is legal only while that count is zero.
    """

    def latest(self, production_id: ProductionId) -> MigrationAuthorityRecord | None: ...

    def append(self, record: MigrationAuthorityRecord) -> None: ...

    def canonical_write_count(self, production_id: ProductionId) -> int: ...


@runtime_checkable
class ReadService(Protocol):
    """Denormalized queries that never load an aggregate (design section 9.5)."""

    def production_summary(self, production_id: ProductionId) -> dict[str, object]: ...

    def edition_timeline(self, production_id: ProductionId) -> tuple[dict[str, object], ...]: ...

    def review_progress(self, production_id: ProductionId) -> dict[str, object]: ...

    def eligibility_report(self, production_id: ProductionId) -> dict[str, object]: ...

    def approval_history(self, production_id: ProductionId) -> tuple[dict[str, object], ...]: ...
