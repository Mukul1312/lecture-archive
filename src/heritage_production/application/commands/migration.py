"""Migration-administration commands.

Design section 17.2 is explicit that these are infrastructure/operational facts,
not domain aggregate commands and not a seventh aggregate root. They mutate no
aggregate, so neither carries an expected version; their protection is the
append-only predecessor-digest chain and the canonical-write marker count.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ContentDigest,
    MigrationDecisionId,
    OperationId,
    ProductionId,
)

from .context import ActorContext, require_envelope, require_exact, require_text


@dataclass(frozen=True, slots=True)
class RecordProductionAuthorityCutover:
    """One Production at a time; never an implicit migration of another."""

    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    migration_decision_id: MigrationDecisionId
    expected_predecessor_id: MigrationDecisionId | None
    expected_predecessor_digest: ContentDigest | None
    reason: str

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(
            self.migration_decision_id, MigrationDecisionId, "migration_decision_id"
        )
        if (self.expected_predecessor_id is None) != (
            self.expected_predecessor_digest is None
        ):
            from heritage_production.domain.shared import ValidationError

            raise ValidationError(
                "a predecessor decision needs both its ID and its digest"
            )
        if self.expected_predecessor_id is not None:
            require_exact(
                self.expected_predecessor_id,
                MigrationDecisionId,
                "expected_predecessor_id",
            )
            require_exact(
                self.expected_predecessor_digest,
                ContentDigest,
                "expected_predecessor_digest",
            )
        require_text(self.reason, field="reason")


@dataclass(frozen=True, slots=True)
class SupersedePreWriteCutover:
    """Legal only while no canonical write marker exists (design 17.4).

    After the first post-cutover canonical write, rollback never makes legacy
    state authoritative again; recovery restores a verified new store instead.
    """

    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    migration_decision_id: MigrationDecisionId
    expected_cutover_id: MigrationDecisionId
    expected_cutover_digest: ContentDigest
    reason: str

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(
            self.migration_decision_id, MigrationDecisionId, "migration_decision_id"
        )
        require_exact(
            self.expected_cutover_id, MigrationDecisionId, "expected_cutover_id"
        )
        require_exact(
            self.expected_cutover_digest, ContentDigest, "expected_cutover_digest"
        )
        require_text(self.reason, field="reason")


__all__ = ["RecordProductionAuthorityCutover", "SupersedePreWriteCutover"]
