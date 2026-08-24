"""Fresh approval evidence and the terminal immutable release approval.

The application reloads every exact root and immediately re-runs the pure
evaluator before calling `Production.approve_candidate`. `ApprovalEvidence`
carries that fresh result as one already-cross-checked value so a stale
assessment cannot be mistaken for a current one.

Release submodules are imported directly rather than through the Release
package so Production and Release never form an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.release.assessment import (
    EligibilityAssessment,
    EligibilityAssessmentRef,
)
from heritage_production.domain.release.content import (
    ReleaseCandidateSnapshot,
    ReleaseContentBinding,
)
from heritage_production.domain.release.policy import ReleasePolicyVersion
from heritage_production.domain.shared import (
    ActorId,
    ContentDigest,
    EditionRef,
    ExternalGateSetRef,
    JsonValue,
    OperationId,
    PolicyEvaluatorRef,
    PolicyRef,
    ReleaseCandidateRef,
    ReleaseContentManifestRef,
    ReviewEvidenceRef,
    StaleReferenceError,
    ValidationError,
    semantic_digest,
)

from .gates import ExternalGateSet, digest_value
from .signoffs import ExternalSignOff


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


@dataclass(frozen=True, slots=True)
class ApprovalEvidence:
    """One immutable, internally consistent approval input graph."""

    assessment: EligibilityAssessment
    assessment_ref: EligibilityAssessmentRef
    candidate: ReleaseCandidateSnapshot
    content: ReleaseContentBinding
    policy: ReleasePolicyVersion
    gate_set: ExternalGateSet
    accepted_sign_offs: tuple[ExternalSignOff, ...]

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("assessment", self.assessment, EligibilityAssessment),
            ("assessment_ref", self.assessment_ref, EligibilityAssessmentRef),
            ("candidate", self.candidate, ReleaseCandidateSnapshot),
            ("content", self.content, ReleaseContentBinding),
            ("policy", self.policy, ReleasePolicyVersion),
            ("gate_set", self.gate_set, ExternalGateSet),
        ):
            _require_exact(value, expected, field_name)
        if type(self.accepted_sign_offs) is not tuple or not all(
            type(value) is ExternalSignOff for value in self.accepted_sign_offs
        ):
            raise ValidationError(
                "accepted_sign_offs must be an immutable tuple of ExternalSignOff"
            )

        # Every reachable immutable child revalidates before it is trusted.
        checked_assessment = self.assessment.validated()
        self.candidate.validated()
        self.content.validated()
        self.policy.validated()
        self.gate_set.validated()
        for sign_off in self.accepted_sign_offs:
            sign_off.validated()

        if (
            self.assessment_ref.eligibility_assessment_id
            != checked_assessment.eligibility_assessment_id
            or self.assessment_ref.semantic_digest != checked_assessment.semantic_digest
        ):
            raise StaleReferenceError(
                "assessment reference does not name this exact assessment"
            )
        if self.assessment_ref.artifact is None:
            raise ValidationError(
                "approval requires a stored eligibility-assessment artifact"
            )

        self.candidate.bind(self.content)
        if checked_assessment.candidate_ref != self.candidate.ref:
            raise StaleReferenceError("assessment does not evaluate this exact candidate")
        if checked_assessment.policy_ref != self.policy.ref:
            raise StaleReferenceError("assessment does not evaluate this exact policy")
        if checked_assessment.evaluator_ref != self.policy.evaluator_ref:
            raise StaleReferenceError(
                "assessment evaluator does not match the policy's pinned evaluator"
            )
        if self.content.policy_ref != self.policy.ref:
            raise StaleReferenceError("release content does not bind this exact policy")
        if self.content.external_gate_set_ref != self.gate_set.ref:
            raise StaleReferenceError("release content does not bind this exact gate set")
        if self.gate_set.production_id != self.candidate.production_id:
            raise StaleReferenceError("gate set names a different Production")
        if any(
            value.production_id != self.candidate.production_id
            for value in self.accepted_sign_offs
        ):
            raise StaleReferenceError("an accepted sign-off names a different Production")

        digests = tuple(value.sign_off_digest for value in self.accepted_sign_offs)
        if tuple(sorted(value.hex_digest for value in digests)) != tuple(
            value.hex_digest for value in digests
        ):
            raise ValidationError("accepted sign-offs must be in canonical digest order")
        if digests != self.candidate.included_sign_off_digests:
            raise StaleReferenceError(
                "accepted sign-offs do not exactly match the candidate snapshot"
            )

    @property
    def eligible(self) -> bool:
        return self.assessment.eligible

    @property
    def accepted_sign_off_digests(self) -> tuple[ContentDigest, ...]:
        return tuple(value.sign_off_digest for value in self.accepted_sign_offs)


def _approval_payload(
    release_candidate_ref: ReleaseCandidateRef,
    edition_ref: EditionRef,
    review_evidence_ref: ReviewEvidenceRef,
    policy_ref: PolicyRef,
    external_gate_set_ref: ExternalGateSetRef,
    evaluator_ref: PolicyEvaluatorRef,
    content_manifest_ref: ReleaseContentManifestRef,
    assessment_ref: EligibilityAssessmentRef,
    gate_results_digest: ContentDigest,
    accepted_sign_off_digests: tuple[ContentDigest, ...],
    steward_actor_id: ActorId,
    approved_at_us: int,
) -> dict[str, JsonValue]:
    return {
        "release_candidate_ref": {
            "release_candidate_id": release_candidate_ref.release_candidate_id.value,
            "semantic_digest": digest_value(release_candidate_ref.semantic_digest),
        },
        "edition_ref": {
            "transcript_edition_id": edition_ref.transcript_edition_id.value,
            "content_digest": digest_value(edition_ref.content_digest),
        },
        "review_evidence_ref": {
            "review_round_id": review_evidence_ref.review_round_id.value,
            "evidence_digest": digest_value(review_evidence_ref.evidence_digest),
        },
        "policy_ref": {
            "release_policy_version_id": policy_ref.release_policy_version_id.value,
            "policy_digest": digest_value(policy_ref.policy_digest),
        },
        "external_gate_set_ref": {
            "external_gate_set_id": external_gate_set_ref.external_gate_set_id.value,
            "content_digest": digest_value(external_gate_set_ref.content_digest),
        },
        "evaluator_ref": {
            "evaluator_name": evaluator_ref.evaluator_name,
            "semantic_version": evaluator_ref.semantic_version,
            "supported_policy_schema": evaluator_ref.supported_policy_schema,
            "implementation_build_digest": digest_value(
                evaluator_ref.implementation_build_digest
            ),
        },
        "content_manifest_ref": {
            "release_content_manifest_id": (
                content_manifest_ref.release_content_manifest_id.value
            ),
            "semantic_digest": digest_value(content_manifest_ref.semantic_digest),
        },
        "eligibility_assessment_ref": {
            "eligibility_assessment_id": (
                assessment_ref.eligibility_assessment_id.value
            ),
            "semantic_digest": digest_value(assessment_ref.semantic_digest),
        },
        "gate_results_digest": digest_value(gate_results_digest),
        "accepted_sign_off_digests": [
            digest_value(value) for value in accepted_sign_off_digests
        ],
        "steward_actor_id": steward_actor_id.value,
        "approved_at_us": approved_at_us,
    }


@dataclass(frozen=True, slots=True)
class ReleaseApproval:
    """The terminal immutable steward decision stored by Production."""

    release_candidate_ref: ReleaseCandidateRef
    edition_ref: EditionRef
    review_evidence_ref: ReviewEvidenceRef
    policy_ref: PolicyRef
    external_gate_set_ref: ExternalGateSetRef
    evaluator_ref: PolicyEvaluatorRef
    content_manifest_ref: ReleaseContentManifestRef
    assessment_ref: EligibilityAssessmentRef
    gate_results_digest: ContentDigest
    accepted_sign_off_digests: tuple[ContentDigest, ...]
    steward_actor_id: ActorId
    approved_at_us: int
    operation_id: OperationId
    approval_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            (
                "release_candidate_ref",
                self.release_candidate_ref,
                ReleaseCandidateRef,
            ),
            ("edition_ref", self.edition_ref, EditionRef),
            ("review_evidence_ref", self.review_evidence_ref, ReviewEvidenceRef),
            ("policy_ref", self.policy_ref, PolicyRef),
            (
                "external_gate_set_ref",
                self.external_gate_set_ref,
                ExternalGateSetRef,
            ),
            ("evaluator_ref", self.evaluator_ref, PolicyEvaluatorRef),
            (
                "content_manifest_ref",
                self.content_manifest_ref,
                ReleaseContentManifestRef,
            ),
            ("assessment_ref", self.assessment_ref, EligibilityAssessmentRef),
            ("gate_results_digest", self.gate_results_digest, ContentDigest),
            ("steward_actor_id", self.steward_actor_id, ActorId),
            ("operation_id", self.operation_id, OperationId),
            ("approval_digest", self.approval_digest, ContentDigest),
        ):
            _require_exact(value, expected, field_name)
        if type(self.approved_at_us) is not int or self.approved_at_us <= 0:
            raise ValidationError("approved_at_us must be a positive integer")
        if type(self.accepted_sign_off_digests) is not tuple or not all(
            type(value) is ContentDigest for value in self.accepted_sign_off_digests
        ):
            raise ValidationError(
                "accepted_sign_off_digests must be a tuple of ContentDigest"
            )
        keys = tuple(value.hex_digest for value in self.accepted_sign_off_digests)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValidationError(
                "accepted sign-off digests must be canonical and unique"
            )

        expected_digest = semantic_digest(
            "heritage-release-approval-v1",
            _approval_payload(
                self.release_candidate_ref,
                self.edition_ref,
                self.review_evidence_ref,
                self.policy_ref,
                self.external_gate_set_ref,
                self.evaluator_ref,
                self.content_manifest_ref,
                self.assessment_ref,
                self.gate_results_digest,
                self.accepted_sign_off_digests,
                self.steward_actor_id,
                self.approved_at_us,
            ),
        )
        if expected_digest != self.approval_digest:
            raise ValidationError("approval digest does not match its approval graph")

    @classmethod
    def seal(
        cls,
        *,
        evidence: ApprovalEvidence,
        steward_actor_id: ActorId,
        approved_at_us: int,
        operation_id: OperationId,
    ) -> ReleaseApproval:
        _require_exact(evidence, ApprovalEvidence, "evidence")
        values = (
            evidence.candidate.ref,
            evidence.content.edition_ref,
            evidence.content.review_evidence_ref,
            evidence.policy.ref,
            evidence.gate_set.ref,
            evidence.policy.evaluator_ref,
            evidence.content.content_manifest_ref,
            evidence.assessment_ref,
            evidence.assessment.gate_results_digest,
            evidence.accepted_sign_off_digests,
            steward_actor_id,
            approved_at_us,
        )
        try:
            digest = semantic_digest(
                "heritage-release-approval-v1", _approval_payload(*values)
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed release-approval semantic input") from error
        return cls(*values, operation_id, digest)

    @classmethod
    def reconstitute(
        cls,
        *,
        release_candidate_ref: ReleaseCandidateRef,
        edition_ref: EditionRef,
        review_evidence_ref: ReviewEvidenceRef,
        policy_ref: PolicyRef,
        external_gate_set_ref: ExternalGateSetRef,
        evaluator_ref: PolicyEvaluatorRef,
        content_manifest_ref: ReleaseContentManifestRef,
        assessment_ref: EligibilityAssessmentRef,
        gate_results_digest: ContentDigest,
        accepted_sign_off_digests: tuple[ContentDigest, ...],
        steward_actor_id: ActorId,
        approved_at_us: int,
        operation_id: OperationId,
        approval_digest: ContentDigest,
    ) -> ReleaseApproval:
        return cls(
            release_candidate_ref,
            edition_ref,
            review_evidence_ref,
            policy_ref,
            external_gate_set_ref,
            evaluator_ref,
            content_manifest_ref,
            assessment_ref,
            gate_results_digest,
            accepted_sign_off_digests,
            steward_actor_id,
            approved_at_us,
            operation_id,
            approval_digest,
        )

    def validated(self) -> ReleaseApproval:
        return type(self).reconstitute(
            release_candidate_ref=self.release_candidate_ref,
            edition_ref=self.edition_ref,
            review_evidence_ref=self.review_evidence_ref,
            policy_ref=self.policy_ref,
            external_gate_set_ref=self.external_gate_set_ref,
            evaluator_ref=self.evaluator_ref,
            content_manifest_ref=self.content_manifest_ref,
            assessment_ref=self.assessment_ref,
            gate_results_digest=self.gate_results_digest,
            accepted_sign_off_digests=self.accepted_sign_off_digests,
            steward_actor_id=self.steward_actor_id,
            approved_at_us=self.approved_at_us,
            operation_id=self.operation_id,
            approval_digest=self.approval_digest,
        )
