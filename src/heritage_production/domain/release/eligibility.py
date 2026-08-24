"""The pure release-eligibility evaluator and its normalized immutable inputs.

Evaluation performs no I/O, clock access, ID generation, mutation, or event
recording. Structural corruption is a typed refusal; a structurally valid but
policy-ineligible graph returns every canonical failed gate without
short-circuiting.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.review import (
    ClosedReviewEvidence,
    FindingDecision,
    ReviewCompleteness,
    ReviewSignOff,
)
from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    AssuranceLevel,
    ContentDigest,
    EditionRef,
    EligibilityAssessmentId,
    EvaluatorUnavailableError,
    GateCode,
    GateScope,
    JsonValue,
    ManifestMemberRole,
    PolicyEvaluatorRef,
    ProductionId,
    RoleCode,
    SignOffDecision,
    SignOffTargetKind,
    StaleReferenceError,
    TranscriptEditionId,
    ValidationError,
    assurance_satisfies,
    semantic_digest,
)
from heritage_production.domain.shared.text import require_canonical_text
from heritage_production.domain.transcription import UncertaintyKind

from .assessment import (
    EligibilityAssessment,
    GateOutcome,
    GateResult,
    GateType,
)
from .content import ReleaseCandidateSnapshot, ReleaseContentBinding
from .gates import ExternalGateRequirement, ExternalGateSet, credential_key, revalidate_credential
from .signoffs import ExternalSignOff
from .policy import (
    BASIS_POINTS_MAX,
    IntegrityCheckCode,
    ReleasePolicyVersion,
    SignOffRequirement,
    UncertaintyLimitMetric,
)


_ASSURANCE_STRENGTH = {
    AssuranceLevel.UNVERIFIED: 0,
    AssuranceLevel.STEWARD_ATTESTED: 1,
    AssuranceLevel.VERIFIED_SIGNATURE: 2,
}


def _digest_value(value: ContentDigest) -> dict[str, JsonValue]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


@dataclass(frozen=True, slots=True)
class UncertaintyObservation:
    """The measured uncertainty of one kind across the selected edition."""

    kind: UncertaintyKind
    mark_count: int
    source_duration_us: int
    character_count: int

    def __post_init__(self) -> None:
        _require_exact(self.kind, UncertaintyKind, "kind")
        for field_name, value in (
            ("mark_count", self.mark_count),
            ("source_duration_us", self.source_duration_us),
            ("character_count", self.character_count),
        ):
            if type(value) is not int or value < 0:
                raise ValidationError(f"{field_name} must be a nonnegative integer")

    def validated(self) -> UncertaintyObservation:
        return UncertaintyObservation(
            self.kind,
            self.mark_count,
            self.source_duration_us,
            self.character_count,
        )

    def value_for(self, metric: UncertaintyLimitMetric) -> int:
        if metric is UncertaintyLimitMetric.MARK_COUNT:
            return self.mark_count
        if metric is UncertaintyLimitMetric.SOURCE_DURATION_US:
            return self.source_duration_us
        return self.character_count

    def payload(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "mark_count": self.mark_count,
            "source_duration_us": self.source_duration_us,
            "character_count": self.character_count,
        }


@dataclass(frozen=True, slots=True)
class TranscriptScopeAssessment:
    """The edition's declared scope coverage, expressed as exact counts."""

    required_span_count: int
    covered_span_count: int
    declared_gap_count: int
    uncovered_span_count: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("required_span_count", self.required_span_count),
            ("covered_span_count", self.covered_span_count),
            ("declared_gap_count", self.declared_gap_count),
            ("uncovered_span_count", self.uncovered_span_count),
        ):
            if type(value) is not int or value < 0:
                raise ValidationError(f"{field_name} must be a nonnegative integer")
        if self.covered_span_count + self.uncovered_span_count != self.required_span_count:
            raise ValidationError(
                "covered and uncovered spans must account for every required span"
            )

    def validated(self) -> TranscriptScopeAssessment:
        return TranscriptScopeAssessment(
            self.required_span_count,
            self.covered_span_count,
            self.declared_gap_count,
            self.uncovered_span_count,
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "required_span_count": self.required_span_count,
            "covered_span_count": self.covered_span_count,
            "declared_gap_count": self.declared_gap_count,
            "uncovered_span_count": self.uncovered_span_count,
        }


@dataclass(frozen=True, slots=True)
class SelectedEditionEvidence:
    """Independently verifiable evidence about the exact selected edition."""

    production_id: ProductionId
    edition_ref: EditionRef
    scope_assessment: TranscriptScopeAssessment
    uncertainty_observations: tuple[UncertaintyObservation, ...]

    def __post_init__(self) -> None:
        _require_exact(self.production_id, ProductionId, "production_id")
        _require_exact(self.edition_ref, EditionRef, "edition_ref")
        _require_exact(
            self.scope_assessment, TranscriptScopeAssessment, "scope_assessment"
        )
        if type(self.uncertainty_observations) is not tuple or not all(
            type(value) is UncertaintyObservation
            for value in self.uncertainty_observations
        ):
            raise ValidationError(
                "uncertainty_observations must be a tuple of UncertaintyObservation"
            )
        kinds = tuple(value.kind.value for value in self.uncertainty_observations)
        if kinds != tuple(sorted(kinds)):
            raise ValidationError("uncertainty observations must be in canonical order")
        if len(set(kinds)) != len(kinds):
            raise ValidationError("uncertainty observations must be unique by kind")

    def validated(self) -> SelectedEditionEvidence:
        """Reconstruct this evidence and every reachable child value."""
        try:
            edition_ref = EditionRef(
                TranscriptEditionId(self.edition_ref.transcript_edition_id.value),
                ContentDigest(
                    self.edition_ref.content_digest.algorithm,
                    self.edition_ref.content_digest.hex_digest,
                ),
            )
        except AttributeError as error:
            raise ValidationError("selected-edition evidence is incomplete") from error
        return SelectedEditionEvidence(
            ProductionId(self.production_id.value),
            edition_ref,
            self.scope_assessment.validated(),
            tuple(value.validated() for value in self.uncertainty_observations),
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "production_id": self.production_id.value,
            "edition_ref": {
                "transcript_edition_id": self.edition_ref.transcript_edition_id.value,
                "content_digest": _digest_value(self.edition_ref.content_digest),
            },
            "scope_assessment": self.scope_assessment.payload(),
            "uncertainty_observations": [
                value.payload() for value in self.uncertainty_observations
            ],
        }


@dataclass(frozen=True, slots=True)
class IntegrityCheckResult:
    check_code: IntegrityCheckCode
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        _require_exact(self.check_code, IntegrityCheckCode, "check_code")
        if type(self.passed) is not bool:
            raise ValidationError("passed must be a boolean")
        require_canonical_text(self.detail, field="detail", nonempty=True)

    def validated(self) -> IntegrityCheckResult:
        return IntegrityCheckResult(
            IntegrityCheckCode(self.check_code.value), self.passed, self.detail
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "check_code": self.check_code.value,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ResolvedSignOffRequirement:
    """One normalized sign-off gate after policy and Production union."""

    gate_code: GateCode
    scope: GateScope
    role: RoleCode
    target_kind: SignOffTargetKind
    required_member_role: ManifestMemberRole | None
    minimum_assurance: AssuranceLevel
    required_count: int
    pinned_credential: ActorCredentialRef | None

    def __post_init__(self) -> None:
        _require_exact(self.gate_code, GateCode, "gate_code")
        _require_exact(self.scope, GateScope, "scope")
        _require_exact(self.role, RoleCode, "role")
        _require_exact(self.target_kind, SignOffTargetKind, "target_kind")
        _require_exact(self.minimum_assurance, AssuranceLevel, "minimum_assurance")
        if self.required_member_role is not None:
            _require_exact(
                self.required_member_role, ManifestMemberRole, "required_member_role"
            )
        if self.pinned_credential is not None:
            _require_exact(
                self.pinned_credential, ActorCredentialRef, "pinned_credential"
            )
        if type(self.required_count) is not int or self.required_count <= 0:
            raise ValidationError("required_count must be a positive integer")

    @property
    def semantic_key(self) -> tuple[str, ...]:
        return (
            self.scope.value,
            self.role.value,
            self.target_kind.value,
            self.required_member_role.value if self.required_member_role else "",
            *(
                credential_key(self.pinned_credential)
                if self.pinned_credential is not None
                else ("", "", "", "")
            ),
        )


def resolve_sign_off_requirements(
    requirements: tuple[ResolvedSignOffRequirement, ...],
) -> tuple[ResolvedSignOffRequirement, ...]:
    """Union requirements, resolving duplicate keys to the stricter constraint.

    A weaker duplicate can never cancel a stronger one: assurance takes the
    stronger level and the required count takes the larger value.
    """
    if type(requirements) is not tuple or not all(
        type(value) is ResolvedSignOffRequirement for value in requirements
    ):
        raise ValidationError(
            "requirements must be a tuple of ResolvedSignOffRequirement"
        )
    merged: dict[tuple[str, ...], ResolvedSignOffRequirement] = {}
    for requirement in requirements:
        key = requirement.semantic_key
        existing = merged.get(key)
        if existing is None:
            merged[key] = requirement
            continue
        stronger_assurance = (
            requirement.minimum_assurance
            if _ASSURANCE_STRENGTH[requirement.minimum_assurance]
            > _ASSURANCE_STRENGTH[existing.minimum_assurance]
            else existing.minimum_assurance
        )
        merged[key] = ResolvedSignOffRequirement(
            gate_code=GateCode(
                min(existing.gate_code.value, requirement.gate_code.value)
            ),
            scope=existing.scope,
            role=existing.role,
            target_kind=existing.target_kind,
            required_member_role=existing.required_member_role,
            minimum_assurance=stronger_assurance,
            required_count=max(existing.required_count, requirement.required_count),
            pinned_credential=existing.pinned_credential,
        )
    return tuple(
        merged[key] for key in sorted(merged, key=lambda value: tuple(value))
    )


def _input_payload(
    production_id: ProductionId,
    candidate: ReleaseCandidateSnapshot,
    content: ReleaseContentBinding,
    edition_evidence: SelectedEditionEvidence,
    policy: ReleasePolicyVersion,
    gate_set: ExternalGateSet,
    sign_offs: tuple[ExternalSignOff, ...],
    integrity_results: tuple[IntegrityCheckResult, ...],
) -> dict[str, JsonValue]:
    return {
        "production_id": production_id.value,
        "candidate": {
            "release_candidate_id": candidate.release_candidate_id.value,
            "semantic_digest": _digest_value(candidate.semantic_digest),
        },
        "content_manifest": {
            "release_content_manifest_id": (
                content.content_manifest_ref.release_content_manifest_id.value
            ),
            "semantic_digest": _digest_value(content.semantic_digest),
        },
        "edition_evidence": edition_evidence.payload(),
        "review_evidence_ref": {
            "review_round_id": content.review_evidence_ref.review_round_id.value,
            "evidence_digest": _digest_value(
                content.review_evidence_ref.evidence_digest
            ),
        },
        "policy_ref": {
            "release_policy_version_id": policy.release_policy_version_id.value,
            "policy_digest": _digest_value(policy.policy_digest),
        },
        "external_gate_set_ref": {
            "external_gate_set_id": gate_set.external_gate_set_id.value,
            "content_digest": _digest_value(gate_set.content_digest),
        },
        "sign_off_digests": [
            _digest_value(value.sign_off_digest) for value in sign_offs
        ],
        "integrity_results": [value.payload() for value in integrity_results],
    }


@dataclass(frozen=True, slots=True)
class EligibilityInputSnapshot:
    """The complete, structurally verified immutable evaluation input graph."""

    production_id: ProductionId
    candidate: ReleaseCandidateSnapshot
    content: ReleaseContentBinding
    edition_evidence: SelectedEditionEvidence
    policy: ReleasePolicyVersion
    gate_set: ExternalGateSet
    sign_offs: tuple[ExternalSignOff, ...]
    integrity_results: tuple[IntegrityCheckResult, ...]
    input_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("production_id", self.production_id, ProductionId),
            ("candidate", self.candidate, ReleaseCandidateSnapshot),
            ("content", self.content, ReleaseContentBinding),
            ("edition_evidence", self.edition_evidence, SelectedEditionEvidence),
            ("policy", self.policy, ReleasePolicyVersion),
            ("gate_set", self.gate_set, ExternalGateSet),
            ("input_digest", self.input_digest, ContentDigest),
        ):
            _require_exact(value, expected, field_name)
        if type(self.sign_offs) is not tuple or not all(
            type(value) is ExternalSignOff for value in self.sign_offs
        ):
            raise ValidationError("sign_offs must be an immutable tuple of ExternalSignOff")
        if type(self.integrity_results) is not tuple or not all(
            type(value) is IntegrityCheckResult for value in self.integrity_results
        ):
            raise ValidationError(
                "integrity_results must be a tuple of IntegrityCheckResult"
            )

        # Every reachable immutable child is reconstructed before it is trusted,
        # so a value forged behind a retained digest cannot survive.
        if self.candidate.validated() != self.candidate:
            raise ValidationError("candidate snapshot failed reconstruction")
        if self.content.validated() != self.content:
            raise ValidationError("release content failed reconstruction")
        if self.policy.validated() != self.policy:
            raise ValidationError("release policy failed reconstruction")
        if self.gate_set.validated() != self.gate_set:
            raise ValidationError("gate set failed reconstruction")
        if self.edition_evidence.validated() != self.edition_evidence:
            raise ValidationError("selected-edition evidence failed reconstruction")
        for sign_off in self.sign_offs:
            if sign_off.validated() != sign_off:
                raise ValidationError("an external sign-off failed reconstruction")
        for result in self.integrity_results:
            if result.validated() != result:
                raise ValidationError("an integrity result failed reconstruction")

        check_codes = tuple(value.check_code.value for value in self.integrity_results)
        if check_codes != tuple(sorted(check_codes)):
            raise ValidationError("integrity results must be in canonical code order")
        if len(set(check_codes)) != len(check_codes):
            raise ValidationError("integrity results must be unique by check code")

        sign_off_digests = tuple(
            value.sign_off_digest.hex_digest for value in self.sign_offs
        )
        if sign_off_digests != tuple(sorted(sign_off_digests)):
            raise ValidationError("sign-offs must be in canonical digest order")
        if len(set(sign_off_digests)) != len(sign_off_digests):
            raise ValidationError("sign-offs must be unique by digest")

        if self.candidate.production_id != self.production_id:
            raise StaleReferenceError("candidate names a different Production")
        if self.content.production_id != self.production_id:
            raise StaleReferenceError("release content names a different Production")
        if self.gate_set.production_id != self.production_id:
            raise StaleReferenceError("gate set names a different Production")
        if self.edition_evidence.production_id != self.production_id:
            raise StaleReferenceError("edition evidence names a different Production")

        self.candidate.bind(self.content)
        if self.content.policy_ref != self.policy.ref:
            raise StaleReferenceError("release content does not bind this exact policy")
        if self.content.external_gate_set_ref != self.gate_set.ref:
            raise StaleReferenceError("release content does not bind this exact gate set")
        if self.edition_evidence.edition_ref != self.content.edition_ref:
            raise StaleReferenceError(
                "edition evidence does not describe the selected edition"
            )
        if any(
            value.production_id != self.production_id for value in self.sign_offs
        ):
            raise StaleReferenceError("a supplied sign-off names a different Production")
        if tuple(
            value.sign_off_digest for value in self.sign_offs
        ) != self.candidate.included_sign_off_digests:
            raise StaleReferenceError(
                "supplied sign-offs do not exactly match the candidate snapshot"
            )

        expected_digest = semantic_digest(
            "heritage-eligibility-input-v1",
            _input_payload(
                self.production_id,
                self.candidate,
                self.content,
                self.edition_evidence,
                self.policy,
                self.gate_set,
                self.sign_offs,
                self.integrity_results,
            ),
        )
        if expected_digest != self.input_digest:
            raise ValidationError("eligibility input digest does not match its graph")

    @classmethod
    def seal(
        cls,
        *,
        production_id: ProductionId,
        candidate: ReleaseCandidateSnapshot,
        content: ReleaseContentBinding,
        edition_evidence: SelectedEditionEvidence,
        policy: ReleasePolicyVersion,
        gate_set: ExternalGateSet,
        sign_offs: tuple[ExternalSignOff, ...],
        integrity_results: tuple[IntegrityCheckResult, ...],
    ) -> EligibilityInputSnapshot:
        try:
            digest = semantic_digest(
                "heritage-eligibility-input-v1",
                _input_payload(
                    production_id,
                    candidate,
                    content,
                    edition_evidence,
                    policy,
                    gate_set,
                    sign_offs,
                    integrity_results,
                ),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed eligibility input") from error
        return cls(
            production_id,
            candidate,
            content,
            edition_evidence,
            policy,
            gate_set,
            sign_offs,
            integrity_results,
            digest,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        production_id: ProductionId,
        candidate: ReleaseCandidateSnapshot,
        content: ReleaseContentBinding,
        edition_evidence: SelectedEditionEvidence,
        policy: ReleasePolicyVersion,
        gate_set: ExternalGateSet,
        sign_offs: tuple[ExternalSignOff, ...],
        integrity_results: tuple[IntegrityCheckResult, ...],
        input_digest: ContentDigest,
    ) -> EligibilityInputSnapshot:
        return cls(
            production_id,
            candidate,
            content,
            edition_evidence,
            policy,
            gate_set,
            sign_offs,
            integrity_results,
            input_digest,
        )

    def validated(self) -> EligibilityInputSnapshot:
        """Reconstruct the complete input graph through every child constructor."""
        # Composite children are deep-validated by __post_init__, so they are
        # passed through here rather than rebuilt a second time.
        return type(self).reconstitute(
            production_id=ProductionId(self.production_id.value),
            candidate=self.candidate,
            content=self.content,
            edition_evidence=self.edition_evidence,
            policy=self.policy,
            gate_set=self.gate_set,
            sign_offs=self.sign_offs,
            integrity_results=self.integrity_results,
            input_digest=ContentDigest(
                self.input_digest.algorithm, self.input_digest.hex_digest
            ),
        )

    @property
    def review_evidence(self) -> ClosedReviewEvidence:
        return self.content.review_evidence


def _member_suffix(role: ManifestMemberRole | None) -> str:
    return role.value if role is not None else ""


def _requirement_from_policy(value: SignOffRequirement) -> ResolvedSignOffRequirement:
    prefix = (
        "policy-review-signoff"
        if value.scope is GateScope.REVIEW
        else "policy-external-signoff"
    )
    return ResolvedSignOffRequirement(
        gate_code=GateCode(
            f"{prefix}:{value.role.value}:{value.target_kind.value}"
            f":{_member_suffix(value.required_member_role)}"
        ),
        scope=value.scope,
        role=value.role,
        target_kind=value.target_kind,
        required_member_role=value.required_member_role,
        minimum_assurance=value.minimum_assurance,
        required_count=value.required_count,
        pinned_credential=None,
    )


def _requirement_from_gate(value: ExternalGateRequirement) -> ResolvedSignOffRequirement:
    return ResolvedSignOffRequirement(
        gate_code=GateCode(f"production-gate:{value.gate_code.value}"),
        scope=value.scope,
        role=value.role,
        target_kind=value.target_rule.target_kind,
        required_member_role=value.target_rule.required_member_role,
        minimum_assurance=value.minimum_assurance,
        required_count=1,
        pinned_credential=value.credential,
    )


class ReleaseEligibilityEvaluator:
    """A stateless evaluator selected by exact `PolicyEvaluatorRef`."""

    __slots__ = ("_evaluator_ref",)

    def __init__(self, evaluator_ref: PolicyEvaluatorRef) -> None:
        _require_exact(evaluator_ref, PolicyEvaluatorRef, "evaluator_ref")
        self._evaluator_ref = evaluator_ref

    @property
    def evaluator_ref(self) -> PolicyEvaluatorRef:
        return self._evaluator_ref

    def evaluate(
        self,
        *,
        snapshot: EligibilityInputSnapshot,
        eligibility_assessment_id: EligibilityAssessmentId,
        assessed_at_us: int,
    ) -> EligibilityAssessment:
        _require_exact(snapshot, EligibilityInputSnapshot, "snapshot")
        _require_exact(
            eligibility_assessment_id,
            EligibilityAssessmentId,
            "eligibility_assessment_id",
        )
        if type(assessed_at_us) is not int or assessed_at_us <= 0:
            raise ValidationError("assessed_at_us must be a positive integer")

        checked = snapshot.validated()
        if checked.policy.evaluator_ref != self._evaluator_ref:
            raise EvaluatorUnavailableError(
                "this evaluator cannot interpret the policy's pinned evaluator version"
            )
        if checked.policy.policy_schema_code != self._evaluator_ref.supported_policy_schema:
            raise EvaluatorUnavailableError(
                "policy schema is unsupported by the selected evaluator"
            )

        results: list[GateResult] = []
        results.extend(self._integrity_gates(checked))
        results.extend(self._uncertainty_gates(checked))
        results.extend(self._finding_gates(checked))
        results.extend(self._coverage_gates(checked))
        results.extend(self._sign_off_gates(checked))
        results.extend(self._artifact_gates(checked))
        ordered = tuple(sorted(results, key=lambda value: value.gate_code.value))

        return EligibilityAssessment.seal(
            eligibility_assessment_id=eligibility_assessment_id,
            assessed_at_us=assessed_at_us,
            candidate_ref=checked.candidate.ref,
            policy_ref=checked.policy.ref,
            evaluator_ref=self._evaluator_ref,
            input_digest=checked.input_digest,
            gate_results=ordered,
        )

    @staticmethod
    def _result(
        code: str,
        gate_type: GateType,
        passed: bool,
        reason_code: str,
        expected: str,
        actual: str,
        evidence: tuple[ContentDigest, ...] = (),
    ) -> GateResult:
        return GateResult(
            GateCode(code),
            gate_type,
            GateOutcome.PASS if passed else GateOutcome.FAIL,
            reason_code,
            expected,
            actual,
            evidence,
        )

    def _integrity_gates(
        self, snapshot: EligibilityInputSnapshot
    ) -> tuple[GateResult, ...]:
        observed = {
            value.check_code.value: value for value in snapshot.integrity_results
        }
        gates: list[GateResult] = []
        for code in snapshot.policy.rules.required_integrity_checks:
            result = observed.get(code.value)
            if result is None:
                gates.append(
                    self._result(
                        f"integrity:{code.value}",
                        GateType.INTEGRITY,
                        False,
                        "integrity-check-missing",
                        "passed integrity check",
                        "no result recorded",
                    )
                )
                continue
            gates.append(
                self._result(
                    f"integrity:{code.value}",
                    GateType.INTEGRITY,
                    result.passed,
                    "integrity-check-passed" if result.passed else "integrity-check-failed",
                    "passed integrity check",
                    result.detail,
                )
            )
        return tuple(gates)

    def _uncertainty_gates(
        self, snapshot: EligibilityInputSnapshot
    ) -> tuple[GateResult, ...]:
        allowances = {
            value.kind.value: value
            for value in snapshot.policy.rules.uncertainty_allowances
        }
        observations = {
            value.kind.value: value
            for value in snapshot.edition_evidence.uncertainty_observations
        }
        gates: list[GateResult] = []
        for kind_value, allowance in sorted(allowances.items()):
            observation = observations.get(kind_value)
            actual = (
                observation.value_for(allowance.metric) if observation is not None else 0
            )
            gates.append(
                self._result(
                    f"uncertainty:{kind_value}",
                    GateType.UNCERTAINTY,
                    actual <= allowance.maximum,
                    "uncertainty-within-limit"
                    if actual <= allowance.maximum
                    else "uncertainty-over-limit",
                    f"{allowance.metric.value} at most {allowance.maximum}",
                    f"{allowance.metric.value} is {actual}",
                )
            )
        for kind_value in sorted(observations):
            if kind_value in allowances:
                continue
            gates.append(
                self._result(
                    f"uncertainty-forbidden:{kind_value}",
                    GateType.UNCERTAINTY,
                    False,
                    "uncertainty-kind-not-permitted",
                    "no uncertainty of this kind",
                    f"{observations[kind_value].mark_count} marks observed",
                )
            )
        return tuple(gates)

    @staticmethod
    def _unresolved_findings(snapshot: EligibilityInputSnapshot) -> tuple[object, ...]:
        # An ACCEPTED finding requires a correction the reviewed edition does not
        # yet contain, so it stays unresolved. REJECTED is resolved.
        return tuple(
            value
            for value in snapshot.review_evidence.findings
            if value.disposition is None
            or value.disposition.decision is FindingDecision.ACCEPTED
        )

    def _finding_gates(
        self, snapshot: EligibilityInputSnapshot
    ) -> tuple[GateResult, ...]:
        unresolved = self._unresolved_findings(snapshot)
        gates: list[GateResult] = []
        for rule in snapshot.policy.rules.blocking_finding_rules:
            severities = {value.value for value in rule.severity_codes}
            matches = tuple(
                value
                for value in unresolved
                if value.category_code == rule.category_code
                and value.severity_code.value in severities
            )
            gates.append(
                self._result(
                    f"blocking-findings:{rule.category_code.value}",
                    GateType.BLOCKING_FINDING,
                    not matches,
                    "no-blocking-findings" if not matches else "blocking-findings-present",
                    "no unresolved finding in the blocking severity set",
                    f"{len(matches)} unresolved blocking findings",
                    tuple(
                        sorted(
                            (value.finding_payload_digest for value in matches),
                            key=lambda value: value.hex_digest,
                        )
                    ),
                )
            )
        maximum = snapshot.policy.rules.maximum_unresolved_findings
        gates.append(
            self._result(
                "unresolved-findings",
                GateType.UNRESOLVED_FINDING,
                len(unresolved) <= maximum,
                "unresolved-within-limit"
                if len(unresolved) <= maximum
                else "unresolved-over-limit",
                f"at most {maximum} unresolved findings",
                f"{len(unresolved)} unresolved findings",
            )
        )
        return tuple(gates)

    def _coverage_gates(
        self, snapshot: EligibilityInputSnapshot
    ) -> tuple[GateResult, ...]:
        evidence = snapshot.review_evidence
        coverage = evidence.coverage
        summaries = {
            value.review_submission_id: value for value in evidence.submission_summaries
        }
        gates: list[GateResult] = []
        for requirement in snapshot.policy.rules.review_coverage_requirements:
            assignments = tuple(
                value for value in coverage.assignments if value.role == requirement.role
            )
            reviewed = {
                key for value in assignments for key in value.reviewed_target_keys
            }
            target_count = coverage.target_count
            # A zero-target round cannot demonstrate positive coverage; fail closed.
            satisfied_ratio = (
                len(reviewed) * BASIS_POINTS_MAX
                >= requirement.minimum_basis_points * target_count
                if target_count
                else requirement.minimum_basis_points == 0
            )
            actual_bp = (
                (len(reviewed) * BASIS_POINTS_MAX) // target_count if target_count else 0
            )
            complete_ok = True
            if requirement.require_complete_submission:
                complete_ok = bool(assignments) and all(
                    value.active_submission_id is not None
                    and summaries[value.active_submission_id].completeness
                    is ReviewCompleteness.COMPLETE
                    for value in assignments
                )
            if not assignments and requirement.minimum_basis_points > 0:
                satisfied_ratio = False
            passed = satisfied_ratio and complete_ok
            gates.append(
                self._result(
                    f"review-coverage:{requirement.role.value}",
                    GateType.REVIEW_COVERAGE,
                    passed,
                    "coverage-satisfied" if passed else "coverage-insufficient",
                    (
                        f"at least {requirement.minimum_basis_points} basis points"
                        + (
                            " with a complete submission"
                            if requirement.require_complete_submission
                            else ""
                        )
                    ),
                    f"{actual_bp} basis points across {len(assignments)} assignments",
                )
            )
        return tuple(gates)

    def _matching_review_sign_offs(
        self,
        sign_offs: tuple[ReviewSignOff, ...],
        requirement: ResolvedSignOffRequirement,
    ) -> tuple[ReviewSignOff, ...]:
        return tuple(
            value
            for value in sign_offs
            if value.decision is SignOffDecision.APPROVED
            and value.role == requirement.role
            and assurance_satisfies(
                value.assurance.assurance, requirement.minimum_assurance
            )
            and (
                requirement.pinned_credential is None
                or value.credential == requirement.pinned_credential
            )
        )

    def _matching_external_sign_offs(
        self,
        snapshot: EligibilityInputSnapshot,
        requirement: ResolvedSignOffRequirement,
    ) -> tuple[ExternalSignOff, ...]:
        content_ref = snapshot.content.content_manifest_ref
        matched: list[ExternalSignOff] = []
        for value in snapshot.sign_offs:
            if value.decision is not SignOffDecision.APPROVED:
                continue
            if value.role != requirement.role:
                continue
            if value.target.target_kind is not requirement.target_kind:
                continue
            if value.target.content_manifest_ref != content_ref:
                continue
            if (
                requirement.required_member_role is not None
                and value.target.member_role != requirement.required_member_role
            ):
                continue
            if requirement.required_member_role is not None:
                expected_member = snapshot.content.member_digest(
                    requirement.required_member_role
                )
                if expected_member is None or value.target.member_digest != expected_member:
                    continue
            if not assurance_satisfies(
                value.assurance.assurance, requirement.minimum_assurance
            ):
                continue
            if (
                requirement.pinned_credential is not None
                and value.credential != requirement.pinned_credential
            ):
                continue
            matched.append(value)
        return tuple(matched)

    def _sign_off_gates(
        self, snapshot: EligibilityInputSnapshot
    ) -> tuple[GateResult, ...]:
        policy_requirements = tuple(
            _requirement_from_policy(value)
            for value in (
                *snapshot.policy.rules.review_signoff_requirements,
                *snapshot.policy.rules.external_signoff_requirements,
            )
        )
        gate_requirements = tuple(
            _requirement_from_gate(value) for value in snapshot.gate_set.requirements
        )
        resolved = resolve_sign_off_requirements(
            (*policy_requirements, *gate_requirements)
        )

        gates: list[GateResult] = []
        for requirement in resolved:
            if requirement.scope is GateScope.REVIEW:
                matched = self._matching_review_sign_offs(
                    snapshot.review_evidence.sign_offs, requirement
                )
                gate_type = GateType.REVIEW_SIGN_OFF
                evidence = tuple(
                    sorted(
                        (value.sign_off_digest for value in matched),
                        key=lambda value: value.hex_digest,
                    )
                )
            else:
                matched = self._matching_external_sign_offs(snapshot, requirement)
                gate_type = GateType.EXTERNAL_SIGN_OFF
                evidence = tuple(
                    sorted(
                        (value.sign_off_digest for value in matched),
                        key=lambda value: value.hex_digest,
                    )
                )
            passed = len(matched) >= requirement.required_count
            gates.append(
                self._result(
                    requirement.gate_code.value,
                    gate_type,
                    passed,
                    "sign-offs-satisfied" if passed else "sign-offs-missing",
                    (
                        f"{requirement.required_count} approving "
                        f"{requirement.role.value} sign-offs at "
                        f"{requirement.minimum_assurance.value}"
                    ),
                    f"{len(matched)} qualifying sign-offs",
                    evidence,
                )
            )
        return tuple(gates)

    def _artifact_gates(
        self, snapshot: EligibilityInputSnapshot
    ) -> tuple[GateResult, ...]:
        available = {value.value for value in snapshot.content.member_roles}
        return tuple(
            self._result(
                f"required-member:{role.value}",
                GateType.REQUIRED_ARTIFACT,
                role.value in available,
                "member-present" if role.value in available else "member-absent",
                f"release member {role.value} is present",
                "present" if role.value in available else "absent",
            )
            for role in snapshot.policy.rules.required_release_members
        )
