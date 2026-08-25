"""Commands that write the `Production` aggregate root.

Every one after `CreateProduction` targets an existing mutable root, so each
carries the version it expects to find (design section 9.3). Approval never
retries blindly after a version conflict: the handler reloads and re-evaluates
all candidate evidence instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.production import (
    ApprovalEvidence,
    AttachedSource,
    EditionSelection,
)
from heritage_production.domain.release import (
    ExternalGateRequirement,
    ExternalSignOff,
    ReleaseContentBinding,
    ReleasePolicyVersion,
)
from heritage_production.domain.shared import (
    ExternalGateSetId,
    OperationId,
    ProductionId,
    ReleaseCandidateId,
)

from .context import (
    ActorContext,
    require_envelope,
    require_exact,
    require_expected_version,
    require_text,
    require_tuple,
)


@dataclass(frozen=True, slots=True)
class CreateProduction:
    operation_id: OperationId
    actor: ActorContext
    intended_deliverable: str

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_text(self.intended_deliverable, field="intended_deliverable")


@dataclass(frozen=True, slots=True)
class AttachSourceRecording:
    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    attached_source: AttachedSource
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.attached_source, AttachedSource, "attached_source")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class SelectCandidateEdition:
    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    edition_selection: EditionSelection
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.edition_selection, EditionSelection, "edition_selection")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class SelectReleasePolicyVersion:
    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    policy: ReleasePolicyVersion
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.policy, ReleasePolicyVersion, "policy")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class ConfigureExternalGates:
    """Production gates may strengthen the policy but never relax it."""

    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    external_gate_set_id: ExternalGateSetId
    requirements: tuple[ExternalGateRequirement, ...]
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.external_gate_set_id, ExternalGateSetId, "external_gate_set_id")
        require_tuple(self.requirements, ExternalGateRequirement, "requirements")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class RecordExternalSignOff:
    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    sign_off: ExternalSignOff
    content: ReleaseContentBinding
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.sign_off, ExternalSignOff, "sign_off")
        require_exact(self.content, ReleaseContentBinding, "content")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class AssembleReleaseCandidate:
    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    release_candidate_id: ReleaseCandidateId
    content: ReleaseContentBinding
    included_sign_offs: tuple[ExternalSignOff, ...]
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.release_candidate_id, ReleaseCandidateId, "release_candidate_id")
        require_exact(self.content, ReleaseContentBinding, "content")
        require_tuple(self.included_sign_offs, ExternalSignOff, "included_sign_offs")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class ApproveReleaseCandidate:
    """The terminal decision; its evidence is re-derived, never trusted.

    `ApprovalEvidence` re-runs the pinned evaluator over its own snapshot during
    construction, so a fabricated or stale assessment cannot reach the root.
    """

    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    evidence: ApprovalEvidence
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.evidence, ApprovalEvidence, "evidence")
        require_expected_version(self.expected_version)


__all__ = [
    "ApproveReleaseCandidate",
    "AssembleReleaseCandidate",
    "AttachSourceRecording",
    "ConfigureExternalGates",
    "CreateProduction",
    "RecordExternalSignOff",
    "SelectCandidateEdition",
    "SelectReleasePolicyVersion",
]
