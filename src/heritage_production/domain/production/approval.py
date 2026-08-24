"""Fresh approval evidence and the terminal immutable release approval.

`ApprovalEvidence` carries the exact `EligibilityInputSnapshot` the assessment
was produced from, and re-runs the pinned evaluator over that snapshot during
construction. A fabricated, incomplete, stale, or mutated assessment therefore
cannot reach `Production.approve_candidate`: only a result the evaluator itself
re-derives from the supplied graph is accepted.

Release defines candidate, gate, and eligibility concepts; Production stores
them. The dependency is one-way (production -> release), so no cycle forms.
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
from heritage_production.domain.release.eligibility import (
    EligibilityInputSnapshot,
    ReleaseEligibilityEvaluator,
)
from heritage_production.domain.release.gates import ExternalGateSet, digest_value
from heritage_production.domain.release.policy import ReleasePolicyVersion
from heritage_production.domain.release.signoffs import ExternalSignOff
from heritage_production.domain.shared import (
    ActorId,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    EditionRef,
    ExternalGateSetId,
    ExternalGateSetRef,
    JsonValue,
    OperationId,
    PolicyEvaluatorRef,
    PolicyRef,
    ReleaseCandidateId,
    ReleaseCandidateRef,
    ReleaseContentManifestId,
    ReleaseContentManifestRef,
    ReleasePolicyVersionId,
    ReviewEvidenceRef,
    ReviewRoundId,
    StaleReferenceError,
    TranscriptEditionId,
    ValidationError,
    semantic_digest,
)


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


@dataclass(frozen=True, slots=True)
class ApprovalEvidence:
    """One immutable approval input graph, re-derived from the evaluator."""

    snapshot: EligibilityInputSnapshot
    assessment: EligibilityAssessment
    assessment_ref: EligibilityAssessmentRef

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("snapshot", self.snapshot, EligibilityInputSnapshot),
            ("assessment", self.assessment, EligibilityAssessment),
            ("assessment_ref", self.assessment_ref, EligibilityAssessmentRef),
        ):
            _require_exact(value, expected, field_name)

        # Reconstruct every reachable child before anything is trusted.
        checked_snapshot = self.snapshot.validated()
        if checked_snapshot != self.snapshot:
            raise ValidationError("eligibility input snapshot failed reconstruction")
        checked_assessment = self.assessment.validated()
        if checked_assessment != self.assessment:
            raise ValidationError("eligibility assessment failed reconstruction")
        checked_ref = self.assessment_ref.validated()
        if checked_ref != self.assessment_ref:
            raise ValidationError("assessment reference failed reconstruction")

        if checked_ref.artifact is None:
            raise ValidationError(
                "approval requires a stored eligibility-assessment artifact"
            )
        if (
            checked_ref.eligibility_assessment_id
            != checked_assessment.eligibility_assessment_id
            or checked_ref.semantic_digest != checked_assessment.semantic_digest
        ):
            raise StaleReferenceError(
                "assessment reference does not name this exact assessment"
            )

        # Re-derive the assessment from its own snapshot using the pinned
        # evaluator. Equality covers the input digest, the complete ordered gate
        # results, and the derived eligible flag, so a fabricated, incomplete,
        # or mutated assessment cannot pass.
        recomputed = ReleaseEligibilityEvaluator(
            checked_snapshot.policy.evaluator_ref
        ).evaluate(
            snapshot=checked_snapshot,
            eligibility_assessment_id=checked_assessment.eligibility_assessment_id,
            assessed_at_us=checked_assessment.assessed_at_us,
        )
        if recomputed != checked_assessment:
            raise StaleReferenceError(
                "the supplied assessment is not what the pinned evaluator derives "
                "from this exact input snapshot"
            )

        object.__setattr__(self, "snapshot", checked_snapshot)
        object.__setattr__(self, "assessment", checked_assessment)
        object.__setattr__(self, "assessment_ref", checked_ref)

    def validated(self) -> ApprovalEvidence:
        """Re-run the complete construction check, including the evaluator."""
        return type(self)(
            snapshot=self.snapshot,
            assessment=self.assessment,
            assessment_ref=self.assessment_ref,
        )

    @property
    def candidate(self) -> ReleaseCandidateSnapshot:
        return self.snapshot.candidate

    @property
    def content(self) -> ReleaseContentBinding:
        return self.snapshot.content

    @property
    def policy(self) -> ReleasePolicyVersion:
        return self.snapshot.policy

    @property
    def gate_set(self) -> ExternalGateSet:
        return self.snapshot.gate_set

    @property
    def accepted_sign_offs(self) -> tuple[ExternalSignOff, ...]:
        return self.snapshot.sign_offs

    @property
    def eligible(self) -> bool:
        return self.assessment.eligible

    @property
    def accepted_sign_off_digests(self) -> tuple[ContentDigest, ...]:
        return tuple(value.sign_off_digest for value in self.accepted_sign_offs)


def _artifact_value(value: ArtifactRef) -> dict[str, JsonValue]:
    return {
        "artifact_id": value.artifact_id.value,
        "content_digest": digest_value(value.content_digest),
        "byte_size": value.byte_size,
        "media_type": value.media_type,
    }


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
    if assessment_ref.artifact is None:
        raise ValidationError(
            "approval evidence requires a stored eligibility-assessment artifact"
        )
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
            "artifact": _artifact_value(content_manifest_ref.artifact),
        },
        "eligibility_assessment_ref": {
            "eligibility_assessment_id": (
                assessment_ref.eligibility_assessment_id.value
            ),
            "semantic_digest": digest_value(assessment_ref.semantic_digest),
            "artifact": _artifact_value(assessment_ref.artifact),
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
        if self.assessment_ref.artifact is None:
            raise ValidationError(
                "a stored approval must bind its eligibility-assessment artifact"
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
        """Reconstruct this approval and every reachable reference."""
        try:
            rebuilt = {
                "release_candidate_ref": ReleaseCandidateRef(
                    ReleaseCandidateId(
                        self.release_candidate_ref.release_candidate_id.value
                    ),
                    ContentDigest(
                        self.release_candidate_ref.semantic_digest.algorithm,
                        self.release_candidate_ref.semantic_digest.hex_digest,
                    ),
                ),
                "edition_ref": EditionRef(
                    TranscriptEditionId(self.edition_ref.transcript_edition_id.value),
                    ContentDigest(
                        self.edition_ref.content_digest.algorithm,
                        self.edition_ref.content_digest.hex_digest,
                    ),
                ),
                "review_evidence_ref": ReviewEvidenceRef(
                    ReviewRoundId(self.review_evidence_ref.review_round_id.value),
                    ContentDigest(
                        self.review_evidence_ref.evidence_digest.algorithm,
                        self.review_evidence_ref.evidence_digest.hex_digest,
                    ),
                ),
                "policy_ref": PolicyRef(
                    ReleasePolicyVersionId(
                        self.policy_ref.release_policy_version_id.value
                    ),
                    ContentDigest(
                        self.policy_ref.policy_digest.algorithm,
                        self.policy_ref.policy_digest.hex_digest,
                    ),
                ),
                "external_gate_set_ref": ExternalGateSetRef(
                    ExternalGateSetId(
                        self.external_gate_set_ref.external_gate_set_id.value
                    ),
                    ContentDigest(
                        self.external_gate_set_ref.content_digest.algorithm,
                        self.external_gate_set_ref.content_digest.hex_digest,
                    ),
                ),
                "evaluator_ref": PolicyEvaluatorRef(
                    self.evaluator_ref.evaluator_name,
                    self.evaluator_ref.semantic_version,
                    self.evaluator_ref.supported_policy_schema,
                    ContentDigest(
                        self.evaluator_ref.implementation_build_digest.algorithm,
                        self.evaluator_ref.implementation_build_digest.hex_digest,
                    ),
                ),
                "content_manifest_ref": ReleaseContentManifestRef(
                    ReleaseContentManifestId(
                        self.content_manifest_ref.release_content_manifest_id.value
                    ),
                    ContentDigest(
                        self.content_manifest_ref.semantic_digest.algorithm,
                        self.content_manifest_ref.semantic_digest.hex_digest,
                    ),
                    ArtifactRef(
                        ArtifactId(
                            self.content_manifest_ref.artifact.artifact_id.value
                        ),
                        ContentDigest(
                            self.content_manifest_ref.artifact.content_digest.algorithm,
                            self.content_manifest_ref.artifact.content_digest.hex_digest,
                        ),
                        self.content_manifest_ref.artifact.byte_size,
                        self.content_manifest_ref.artifact.media_type,
                    ),
                ),
                "assessment_ref": self.assessment_ref.validated(),
                "gate_results_digest": ContentDigest(
                    self.gate_results_digest.algorithm,
                    self.gate_results_digest.hex_digest,
                ),
                "accepted_sign_off_digests": tuple(
                    ContentDigest(value.algorithm, value.hex_digest)
                    for value in self.accepted_sign_off_digests
                ),
                "steward_actor_id": ActorId(self.steward_actor_id.value),
                "operation_id": OperationId(self.operation_id.value),
                "approval_digest": ContentDigest(
                    self.approval_digest.algorithm, self.approval_digest.hex_digest
                ),
            }
        except AttributeError as error:
            raise ValidationError("release approval is incomplete") from error
        return type(self).reconstitute(
            approved_at_us=self.approved_at_us, **rebuilt
        )
