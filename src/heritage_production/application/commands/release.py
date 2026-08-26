"""Release, registration, and export commands.

None of these mutates an aggregate root, so none carries an expected version.
`RegisterRubric`, `RegisterActorCredential`, `AssembleReleaseContent`,
`EvaluateReleaseEligibility`, and `ExportApprovedRelease` create
content-addressed artifacts and operation records only (design section 9.2).
The two that do write a root -- `RecordExternalSignOff` and
`AssembleReleaseCandidate` -- belong to Production and live beside it.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.release import (
    EligibilityInputSnapshot,
    ReleaseMember,
    ReleasePolicyRules,
)
from heritage_production.domain.shared import (
    ActorCredentialRef,
    ArtifactRef,
    ContentDigest,
    EligibilityAssessmentId,
    OperationId,
    PolicyEvaluatorRef,
    ProductionId,
    ReleaseContentManifestId,
    ReleasePolicyVersionId,
    RubricId,
)

from .context import (
    ActorContext,
    require_envelope,
    require_exact,
    require_text,
    require_tuple,
)


@dataclass(frozen=True, slots=True)
class CreateReleasePolicyVersion:
    """Seals an immutable policy; changing rules later means a new version."""

    operation_id: OperationId
    actor: ActorContext
    release_policy_version_id: ReleasePolicyVersionId
    semantic_label: str
    policy_schema_version: int
    policy_schema_code: str
    evaluator_ref: PolicyEvaluatorRef
    rules: ReleasePolicyRules

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(
            self.release_policy_version_id,
            ReleasePolicyVersionId,
            "release_policy_version_id",
        )
        require_text(self.semantic_label, field="semantic_label")
        if type(self.policy_schema_version) is not int or self.policy_schema_version <= 0:
            from heritage_production.domain.shared import ValidationError

            raise ValidationError("policy_schema_version must be a positive integer")
        require_text(self.policy_schema_code, field="policy_schema_code")
        require_exact(self.evaluator_ref, PolicyEvaluatorRef, "evaluator_ref")
        require_exact(self.rules, ReleasePolicyRules, "rules")


@dataclass(frozen=True, slots=True)
class RegisterRubric:
    operation_id: OperationId
    actor: ActorContext
    rubric_id: RubricId
    schema_version: int
    content: ArtifactRef

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.rubric_id, RubricId, "rubric_id")
        if type(self.schema_version) is not int or self.schema_version <= 0:
            from heritage_production.domain.shared import ValidationError

            raise ValidationError("schema_version must be a positive integer")
        require_exact(self.content, ArtifactRef, "content")


@dataclass(frozen=True, slots=True)
class RegisterActorCredential:
    """Only a public verification key is ever registered (design 15.1)."""

    operation_id: OperationId
    actor: ActorContext
    credential: ActorCredentialRef

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.credential, ActorCredentialRef, "credential")


@dataclass(frozen=True, slots=True)
class AssembleReleaseContent:
    """Seals the sign-off-free manifest external actors will sign."""

    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    release_content_manifest_id: ReleaseContentManifestId
    members: tuple[ReleaseMember, ...]
    provenance_input_digests: tuple[ContentDigest, ...]
    integrity_input_digests: tuple[ContentDigest, ...]

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(
            self.release_content_manifest_id,
            ReleaseContentManifestId,
            "release_content_manifest_id",
        )
        require_tuple(self.members, ReleaseMember, "members")
        require_tuple(
            self.provenance_input_digests, ContentDigest, "provenance_input_digests"
        )
        require_tuple(
            self.integrity_input_digests, ContentDigest, "integrity_input_digests"
        )


@dataclass(frozen=True, slots=True)
class EvaluateReleaseEligibility:
    """Ineligibility is a successful domain result, not a failure."""

    operation_id: OperationId
    actor: ActorContext
    eligibility_assessment_id: EligibilityAssessmentId
    snapshot: EligibilityInputSnapshot

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(
            self.eligibility_assessment_id,
            EligibilityAssessmentId,
            "eligibility_assessment_id",
        )
        require_exact(self.snapshot, EligibilityInputSnapshot, "snapshot")


@dataclass(frozen=True, slots=True)
class ExportApprovedRelease:
    """Design 13.4: verify the stored archive and copy it; never re-render."""

    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    destination: str

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_text(self.destination, field="destination")


__all__ = [
    "AssembleReleaseContent",
    "CreateReleasePolicyVersion",
    "EvaluateReleaseEligibility",
    "ExportApprovedRelease",
    "RegisterActorCredential",
    "RegisterRubric",
]
