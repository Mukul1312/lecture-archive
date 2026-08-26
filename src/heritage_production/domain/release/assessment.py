"""Immutable gate results and eligibility assessments.

This module depends only on the shared kernel so Production can bind a fresh
assessment during approval without importing the evaluator that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    EligibilityAssessmentId,
    GateCode,
    JsonValue,
    PolicyEvaluatorRef,
    PolicyRef,
    ReleaseCandidateId,
    ReleaseCandidateRef,
    ReleasePolicyVersionId,
    ValidationError,
    semantic_digest,
)
from heritage_production.domain.shared.text import require_canonical_text
from enum import Enum


class GateOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class GateType(str, Enum):
    INTEGRITY = "integrity"
    UNCERTAINTY = "uncertainty"
    BLOCKING_FINDING = "blocking_finding"
    UNRESOLVED_FINDING = "unresolved_finding"
    REVIEW_COVERAGE = "review_coverage"
    REVIEW_SIGN_OFF = "review_sign_off"
    EXTERNAL_SIGN_OFF = "external_sign_off"
    REQUIRED_ARTIFACT = "required_artifact"


def _digest_value(value: ContentDigest) -> dict[str, JsonValue]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


def _evaluator_value(value: PolicyEvaluatorRef) -> dict[str, JsonValue]:
    return {
        "evaluator_name": value.evaluator_name,
        "semantic_version": value.semantic_version,
        "supported_policy_schema": value.supported_policy_schema,
        "implementation_build_digest": _digest_value(value.implementation_build_digest),
    }


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


@dataclass(frozen=True, slots=True)
class GateResult:
    """One deterministic gate outcome with canonical expected/actual evidence."""

    gate_code: GateCode
    gate_type: GateType
    outcome: GateOutcome
    reason_code: str
    expected: str
    actual: str
    evidence_digests: tuple[ContentDigest, ...]

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("gate_code", self.gate_code, GateCode),
            ("gate_type", self.gate_type, GateType),
            ("outcome", self.outcome, GateOutcome),
        ):
            _require_exact(value, expected, field_name)
        for field_name, value in (
            ("reason_code", self.reason_code),
            ("expected", self.expected),
            ("actual", self.actual),
        ):
            require_canonical_text(value, field=field_name, nonempty=True)
        if type(self.evidence_digests) is not tuple or not all(
            type(value) is ContentDigest for value in self.evidence_digests
        ):
            raise ValidationError(
                "evidence_digests must be an immutable tuple of ContentDigest"
            )
        keys = tuple(value.hex_digest for value in self.evidence_digests)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValidationError("gate evidence digests must be canonical and unique")

    def validated(self) -> "GateResult":
        """Reconstruct this result and every reachable child value."""
        try:
            digests = tuple(
                ContentDigest(value.algorithm, value.hex_digest)
                for value in self.evidence_digests
            )
        except AttributeError as error:
            raise ValidationError("gate evidence digest is incomplete") from error
        return GateResult(
            GateCode(self.gate_code.value),
            self.gate_type,
            self.outcome,
            self.reason_code,
            self.expected,
            self.actual,
            digests,
        )

    @property
    def passed(self) -> bool:
        return self.outcome is GateOutcome.PASS

    def payload(self) -> dict[str, JsonValue]:
        return {
            "gate_code": self.gate_code.value,
            "gate_type": self.gate_type.value,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "expected": self.expected,
            "actual": self.actual,
            "evidence_digests": [
                _digest_value(value) for value in self.evidence_digests
            ],
        }


@dataclass(frozen=True, slots=True)
class EligibilityAssessmentRef:
    """An exact assessment reference; the wrapper artifact appears once stored."""

    eligibility_assessment_id: EligibilityAssessmentId
    semantic_digest: ContentDigest
    artifact: ArtifactRef | None = None

    def __post_init__(self) -> None:
        _require_exact(
            self.eligibility_assessment_id,
            EligibilityAssessmentId,
            "eligibility_assessment_id",
        )
        _require_exact(self.semantic_digest, ContentDigest, "semantic_digest")
        if self.artifact is not None:
            _require_exact(self.artifact, ArtifactRef, "artifact")

    def validated(self) -> "EligibilityAssessmentRef":
        """Reconstruct this reference and its complete stored artifact."""
        try:
            artifact = (
                ArtifactRef(
                    ArtifactId(self.artifact.artifact_id.value),
                    ContentDigest(
                        self.artifact.content_digest.algorithm,
                        self.artifact.content_digest.hex_digest,
                    ),
                    self.artifact.byte_size,
                    self.artifact.media_type,
                )
                if self.artifact is not None
                else None
            )
        except AttributeError as error:
            raise ValidationError("assessment artifact is incomplete") from error
        return EligibilityAssessmentRef(
            EligibilityAssessmentId(self.eligibility_assessment_id.value),
            ContentDigest(
                self.semantic_digest.algorithm, self.semantic_digest.hex_digest
            ),
            artifact,
        )


def _assessment_payload(
    input_digest: ContentDigest,
    evaluator_ref: PolicyEvaluatorRef,
    gate_results: tuple[GateResult, ...],
) -> dict[str, JsonValue]:
    return {
        "candidate_input_digest": _digest_value(input_digest),
        "evaluator_ref": _evaluator_value(evaluator_ref),
        "gate_results": [value.payload() for value in gate_results],
    }


@dataclass(frozen=True, slots=True)
class EligibilityAssessment:
    """A deterministic, immutable evaluation result; ineligibility is a success."""

    eligibility_assessment_id: EligibilityAssessmentId
    assessed_at_us: int
    candidate_ref: ReleaseCandidateRef
    policy_ref: PolicyRef
    evaluator_ref: PolicyEvaluatorRef
    input_digest: ContentDigest
    gate_results: tuple[GateResult, ...]
    eligible: bool
    semantic_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            (
                "eligibility_assessment_id",
                self.eligibility_assessment_id,
                EligibilityAssessmentId,
            ),
            ("candidate_ref", self.candidate_ref, ReleaseCandidateRef),
            ("policy_ref", self.policy_ref, PolicyRef),
            ("evaluator_ref", self.evaluator_ref, PolicyEvaluatorRef),
            ("input_digest", self.input_digest, ContentDigest),
            ("semantic_digest", self.semantic_digest, ContentDigest),
        ):
            _require_exact(value, expected, field_name)
        if type(self.assessed_at_us) is not int or self.assessed_at_us <= 0:
            raise ValidationError("assessed_at_us must be a positive integer")
        if type(self.gate_results) is not tuple or not all(
            type(value) is GateResult for value in self.gate_results
        ):
            raise ValidationError("gate_results must be an immutable tuple of GateResult")
        codes = tuple(value.gate_code.value for value in self.gate_results)
        if codes != tuple(sorted(codes)):
            raise ValidationError("gate results must already be in canonical code order")
        if len(set(codes)) != len(codes):
            raise ValidationError("gate codes must be unique within one assessment")
        if type(self.eligible) is not bool:
            raise ValidationError("eligible must be a boolean")
        if self.eligible != all(value.passed for value in self.gate_results):
            raise ValidationError(
                "eligible is derived from the gate results and cannot be supplied"
            )

        expected_digest = semantic_digest(
            "heritage-eligibility-v1",
            _assessment_payload(
                self.input_digest, self.evaluator_ref, self.gate_results
            ),
        )
        if expected_digest != self.semantic_digest:
            raise ValidationError("eligibility digest does not match its gate results")

    @classmethod
    def seal(
        cls,
        *,
        eligibility_assessment_id: EligibilityAssessmentId,
        assessed_at_us: int,
        candidate_ref: ReleaseCandidateRef,
        policy_ref: PolicyRef,
        evaluator_ref: PolicyEvaluatorRef,
        input_digest: ContentDigest,
        gate_results: tuple[GateResult, ...],
    ) -> EligibilityAssessment:
        try:
            digest = semantic_digest(
                "heritage-eligibility-v1",
                _assessment_payload(input_digest, evaluator_ref, gate_results),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed eligibility semantic input") from error
        return cls(
            eligibility_assessment_id,
            assessed_at_us,
            candidate_ref,
            policy_ref,
            evaluator_ref,
            input_digest,
            gate_results,
            all(value.passed for value in gate_results),
            digest,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        eligibility_assessment_id: EligibilityAssessmentId,
        assessed_at_us: int,
        candidate_ref: ReleaseCandidateRef,
        policy_ref: PolicyRef,
        evaluator_ref: PolicyEvaluatorRef,
        input_digest: ContentDigest,
        gate_results: tuple[GateResult, ...],
        eligible: bool,
        semantic_digest: ContentDigest,
    ) -> EligibilityAssessment:
        return cls(
            eligibility_assessment_id,
            assessed_at_us,
            candidate_ref,
            policy_ref,
            evaluator_ref,
            input_digest,
            gate_results,
            eligible,
            semantic_digest,
        )

    def validated(self) -> EligibilityAssessment:
        """Reconstruct this assessment and every reachable gate result."""
        try:
            candidate_ref = ReleaseCandidateRef(
                ReleaseCandidateId(self.candidate_ref.release_candidate_id.value),
                ContentDigest(
                    self.candidate_ref.semantic_digest.algorithm,
                    self.candidate_ref.semantic_digest.hex_digest,
                ),
            )
            policy_ref = PolicyRef(
                ReleasePolicyVersionId(
                    self.policy_ref.release_policy_version_id.value
                ),
                ContentDigest(
                    self.policy_ref.policy_digest.algorithm,
                    self.policy_ref.policy_digest.hex_digest,
                ),
            )
            evaluator_ref = PolicyEvaluatorRef(
                self.evaluator_ref.evaluator_name,
                self.evaluator_ref.semantic_version,
                self.evaluator_ref.supported_policy_schema,
                ContentDigest(
                    self.evaluator_ref.implementation_build_digest.algorithm,
                    self.evaluator_ref.implementation_build_digest.hex_digest,
                ),
            )
        except AttributeError as error:
            raise ValidationError("eligibility assessment is incomplete") from error
        return type(self).reconstitute(
            eligibility_assessment_id=EligibilityAssessmentId(
                self.eligibility_assessment_id.value
            ),
            assessed_at_us=self.assessed_at_us,
            candidate_ref=candidate_ref,
            policy_ref=policy_ref,
            evaluator_ref=evaluator_ref,
            input_digest=ContentDigest(
                self.input_digest.algorithm, self.input_digest.hex_digest
            ),
            gate_results=tuple(value.validated() for value in self.gate_results),
            eligible=self.eligible,
            semantic_digest=ContentDigest(
                self.semantic_digest.algorithm, self.semantic_digest.hex_digest
            ),
        )

    @property
    def ref(self) -> EligibilityAssessmentRef:
        return EligibilityAssessmentRef(
            self.eligibility_assessment_id, self.semantic_digest
        )

    @property
    def failed_gates(self) -> tuple[GateResult, ...]:
        return tuple(value for value in self.gate_results if not value.passed)

    @property
    def gate_results_digest(self) -> ContentDigest:
        """The canonical digest of the complete ordered gate-result set."""
        return semantic_digest(
            "heritage-eligibility-gate-results-v1",
            {"gate_results": [value.payload() for value in self.gate_results]},
        )
