"""The pure release-eligibility evaluator and its immutable assessment."""

from __future__ import annotations

import unittest

from heritage_production.domain.production import (
    ExternalGateRequirement,
    ExternalGateSet,
)
from heritage_production.domain.release import (
    BlockingFindingRule,
    EligibilityAssessment,
    EligibilityInputSnapshot,
    GateOutcome,
    GateType,
    IntegrityCheckCode,
    IntegrityCheckResult,
    ReleaseEligibilityEvaluator,
    ReleasePolicyRules,
    ResolvedSignOffRequirement,
    ReviewCoverageRequirement,
    SelectedEditionEvidence,
    SignOffRequirement,
    TranscriptScopeAssessment,
    UncertaintyAllowance,
    UncertaintyLimitMetric,
    UncertaintyObservation,
    resolve_sign_off_requirements,
)
from heritage_production.domain.review import (
    FindingCategoryCode,
    FindingDecision,
    FindingSeverityCode,
)
from heritage_production.domain.shared import (
    AssuranceLevel,
    ContentDigest,
    EligibilityAssessmentId,
    EvaluatorUnavailableError,
    GateCode,
    GateScope,
    ManifestMemberRole,
    PolicyEvaluatorRef,
    ProductionId,
    RoleCode,
    SignOffDecision,
    SignOffTargetKind,
    SignOffTargetRule,
    StaleReferenceError,
    ValidationError,
    semantic_digest,
)
from heritage_production.domain.transcription import UncertaintyKind

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    attested_credential,
    closed_review,
    digest,
    edition_ref,
    partially_covered_review,
    production_id,
    successor_edition_ref,
    uid,
    verified_credential,
)
from tests.heritage_production.test_production_gates import (
    FINGERPRINT,
    gate_set_id,
    release_target,
    verified_sign_off,
)
from tests.heritage_production.test_release_content import seal_candidate, seal_content
from tests.heritage_production.test_release_policy import EVALUATOR, empty_rules, seal_policy


ASSESSMENT_ID = EligibilityAssessmentId(uid(90))
ASSESSED_AT = 1_700_000_000_000_020


def scope_assessment(uncovered: int = 0) -> TranscriptScopeAssessment:
    return TranscriptScopeAssessment(
        required_span_count=3,
        covered_span_count=3 - uncovered,
        declared_gap_count=0,
        uncovered_span_count=uncovered,
    )


def edition_evidence(
    *,
    observations: tuple[UncertaintyObservation, ...] = (),
    uncovered: int = 0,
    edition: object | None = None,
    owner: ProductionId | None = None,
) -> SelectedEditionEvidence:
    return SelectedEditionEvidence(
        production_id=owner or production_id(),
        edition_ref=edition or edition_ref(),
        scope_assessment=scope_assessment(uncovered),
        uncertainty_observations=observations,
    )


def gate_set(requirements: tuple[ExternalGateRequirement, ...] = ()) -> ExternalGateSet:
    return ExternalGateSet.seal(
        external_gate_set_id=gate_set_id(),
        production_id=production_id(),
        requirements=requirements,
        configured_by=actor(20),
        configured_at_us=1_700_000_000_000_000,
    )


def build_snapshot(
    *,
    rules: ReleasePolicyRules | None = None,
    evidence: object | None = None,
    observations: tuple[UncertaintyObservation, ...] = (),
    integrity_results: tuple[IntegrityCheckResult, ...] = (),
    gate_requirements: tuple[ExternalGateRequirement, ...] = (),
    sign_offs: tuple[object, ...] = (),
    edition_evidence_override: SelectedEditionEvidence | None = None,
) -> EligibilityInputSnapshot:
    review_evidence = evidence if evidence is not None else closed_review()
    policy = seal_policy(rules if rules is not None else empty_rules())
    gates = gate_set(gate_requirements)
    content = seal_content(
        evidence=review_evidence, policy_ref=policy.ref, gate_set_ref=gates.ref
    )
    candidate = seal_candidate(
        content,
        sign_off_digests=tuple(
            sorted(
                (value.sign_off_digest for value in sign_offs),
                key=lambda value: value.hex_digest,
            )
        ),
    )
    return EligibilityInputSnapshot.seal(
        production_id=content.production_id,
        candidate=candidate,
        content=content,
        edition_evidence=(
            edition_evidence_override
            if edition_evidence_override is not None
            else edition_evidence(
                observations=observations, edition=review_evidence.edition_ref
            )
        ),
        policy=policy,
        gate_set=gates,
        sign_offs=tuple(
            sorted(sign_offs, key=lambda value: value.sign_off_digest.hex_digest)
        ),
        integrity_results=integrity_results,
    )


def evaluate(snapshot: EligibilityInputSnapshot) -> EligibilityAssessment:
    return ReleaseEligibilityEvaluator(EVALUATOR).evaluate(
        snapshot=snapshot,
        eligibility_assessment_id=ASSESSMENT_ID,
        assessed_at_us=ASSESSED_AT,
    )


def outcome_for(assessment: EligibilityAssessment, gate_code: str) -> GateOutcome:
    for result in assessment.gate_results:
        if result.gate_code.value == gate_code:
            return result.outcome
    raise AssertionError(f"no gate result named {gate_code!r}")


class EligibilityInputSnapshotTests(unittest.TestCase):
    def test_snapshot_binds_a_recomputable_input_digest(self) -> None:
        snapshot = build_snapshot()

        self.assertEqual(snapshot, snapshot.validated())
        self.assertEqual(
            snapshot.input_digest, snapshot.validated().input_digest
        )

    def test_input_digest_matches_its_literal_documented_preimage(self) -> None:
        snapshot = build_snapshot()

        expected = semantic_digest(
            "heritage-eligibility-input-v1",
            {
                "production_id": snapshot.production_id.value,
                "candidate": {
                    "release_candidate_id": snapshot.candidate.release_candidate_id.value,
                    "semantic_digest": {
                        "algorithm": "sha256",
                        "hex_digest": snapshot.candidate.semantic_digest.hex_digest,
                    },
                },
                "content_manifest": {
                    "release_content_manifest_id": (
                        snapshot.content.content_manifest_ref.release_content_manifest_id.value
                    ),
                    "semantic_digest": {
                        "algorithm": "sha256",
                        "hex_digest": snapshot.content.semantic_digest.hex_digest,
                    },
                },
                "edition_evidence": {
                    "production_id": snapshot.production_id.value,
                    "edition_ref": {
                        "transcript_edition_id": (
                            snapshot.content.edition_ref.transcript_edition_id.value
                        ),
                        "content_digest": {
                            "algorithm": "sha256",
                            "hex_digest": (
                                snapshot.content.edition_ref.content_digest.hex_digest
                            ),
                        },
                    },
                    "scope_assessment": {
                        "required_span_count": 3,
                        "covered_span_count": 3,
                        "declared_gap_count": 0,
                        "uncovered_span_count": 0,
                    },
                    "uncertainty_observations": [],
                },
                "review_evidence_ref": {
                    "review_round_id": (
                        snapshot.content.review_evidence_ref.review_round_id.value
                    ),
                    "evidence_digest": {
                        "algorithm": "sha256",
                        "hex_digest": (
                            snapshot.content.review_evidence_ref.evidence_digest.hex_digest
                        ),
                    },
                },
                "policy_ref": {
                    "release_policy_version_id": (
                        snapshot.policy.release_policy_version_id.value
                    ),
                    "policy_digest": {
                        "algorithm": "sha256",
                        "hex_digest": snapshot.policy.policy_digest.hex_digest,
                    },
                },
                "external_gate_set_ref": {
                    "external_gate_set_id": (
                        snapshot.gate_set.external_gate_set_id.value
                    ),
                    "content_digest": {
                        "algorithm": "sha256",
                        "hex_digest": snapshot.gate_set.content_digest.hex_digest,
                    },
                },
                "sign_off_digests": [],
                "integrity_results": [],
            },
        )

        self.assertEqual(snapshot.input_digest, expected)

    def test_candidate_must_reference_the_supplied_content(self) -> None:
        snapshot = build_snapshot()
        other_content = seal_content(evidence=closed_review())

        with self.assertRaises((ValidationError, StaleReferenceError)):
            EligibilityInputSnapshot.seal(
                production_id=snapshot.production_id,
                candidate=snapshot.candidate,
                content=other_content,
                edition_evidence=snapshot.edition_evidence,
                policy=snapshot.policy,
                gate_set=snapshot.gate_set,
                sign_offs=(),
                integrity_results=(),
            )

    def test_content_must_bind_the_supplied_policy_and_gate_set(self) -> None:
        snapshot = build_snapshot()
        other_policy = seal_policy(
            ReleasePolicyRules(
                required_integrity_checks=(IntegrityCheckCode("x"),),
                uncertainty_allowances=(),
                blocking_finding_rules=(),
                review_coverage_requirements=(),
                review_signoff_requirements=(),
                external_signoff_requirements=(),
                required_release_members=(),
                maximum_unresolved_findings=0,
            )
        )

        with self.assertRaises((ValidationError, StaleReferenceError)):
            EligibilityInputSnapshot.seal(
                production_id=snapshot.production_id,
                candidate=snapshot.candidate,
                content=snapshot.content,
                edition_evidence=snapshot.edition_evidence,
                policy=other_policy,
                gate_set=snapshot.gate_set,
                sign_offs=(),
                integrity_results=(),
            )

    def test_edition_evidence_must_match_the_selected_edition(self) -> None:
        with self.assertRaises((ValidationError, StaleReferenceError)):
            build_snapshot(
                edition_evidence_override=edition_evidence(edition=successor_edition_ref())
            )

    def test_foreign_production_in_edition_evidence_is_rejected(self) -> None:
        with self.assertRaises((ValidationError, StaleReferenceError)):
            build_snapshot(
                edition_evidence_override=edition_evidence(owner=ProductionId(uid(555)))
            )

    def test_sign_off_set_must_exactly_match_the_candidate(self) -> None:
        sign_off = verified_sign_off()
        snapshot = build_snapshot(sign_offs=(sign_off,))

        with self.assertRaises((ValidationError, StaleReferenceError)):
            EligibilityInputSnapshot.seal(
                production_id=snapshot.production_id,
                candidate=snapshot.candidate,
                content=snapshot.content,
                edition_evidence=snapshot.edition_evidence,
                policy=snapshot.policy,
                gate_set=snapshot.gate_set,
                sign_offs=(),
                integrity_results=(),
            )

    def test_duplicate_integrity_results_and_observations_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            build_snapshot(
                integrity_results=(
                    IntegrityCheckResult(IntegrityCheckCode("a"), True, "ok"),
                    IntegrityCheckResult(IntegrityCheckCode("a"), False, "no"),
                )
            )
        with self.assertRaises(ValidationError):
            build_snapshot(
                observations=(
                    UncertaintyObservation(UncertaintyKind.INAUDIBLE, 1, 1, 1),
                    UncertaintyObservation(UncertaintyKind.INAUDIBLE, 2, 2, 2),
                )
            )

    def test_gate_set_must_belong_to_this_production(self) -> None:
        foreign_gate_set = ExternalGateSet.seal(
            external_gate_set_id=gate_set_id(),
            production_id=ProductionId(uid(555)),
            requirements=(),
            configured_by=actor(20),
            configured_at_us=1,
        )
        snapshot = build_snapshot()

        with self.assertRaises((ValidationError, StaleReferenceError)):
            EligibilityInputSnapshot.seal(
                production_id=snapshot.production_id,
                candidate=snapshot.candidate,
                content=snapshot.content,
                edition_evidence=snapshot.edition_evidence,
                policy=snapshot.policy,
                gate_set=foreign_gate_set,
                sign_offs=(),
                integrity_results=(),
            )


class EvaluatorCompatibilityTests(unittest.TestCase):
    def test_incompatible_evaluator_is_a_dependency_failure(self) -> None:
        snapshot = build_snapshot()
        other = PolicyEvaluatorRef(
            "heritage-transcript-evaluator",
            "2.0.0",
            "heritage-transcript-policy-v1",
            ContentDigest("sha256", "e" * 64),
        )

        with self.assertRaises(EvaluatorUnavailableError):
            ReleaseEligibilityEvaluator(other).evaluate(
                snapshot=snapshot,
                eligibility_assessment_id=ASSESSMENT_ID,
                assessed_at_us=ASSESSED_AT,
            )


class EmptyPolicyEvaluationTests(unittest.TestCase):
    def test_empty_policy_still_reports_its_unresolved_finding_gate(self) -> None:
        assessment = evaluate(build_snapshot())

        self.assertTrue(assessment.eligible)
        self.assertEqual(len(assessment.gate_results), 1)
        self.assertIs(assessment.gate_results[0].gate_type, GateType.UNRESOLVED_FINDING)

    def test_assessment_digest_matches_its_literal_documented_preimage(self) -> None:
        snapshot = build_snapshot()
        assessment = evaluate(snapshot)
        result = assessment.gate_results[0]

        expected = semantic_digest(
            "heritage-eligibility-v1",
            {
                "candidate_input_digest": {
                    "algorithm": "sha256",
                    "hex_digest": snapshot.input_digest.hex_digest,
                },
                "evaluator_ref": {
                    "evaluator_name": EVALUATOR.evaluator_name,
                    "semantic_version": EVALUATOR.semantic_version,
                    "supported_policy_schema": EVALUATOR.supported_policy_schema,
                    "implementation_build_digest": {
                        "algorithm": "sha256",
                        "hex_digest": (
                            EVALUATOR.implementation_build_digest.hex_digest
                        ),
                    },
                },
                "gate_results": [
                    {
                        "gate_code": result.gate_code.value,
                        "gate_type": result.gate_type.value,
                        "outcome": result.outcome.value,
                        "reason_code": result.reason_code,
                        "expected": result.expected,
                        "actual": result.actual,
                        "evidence_digests": [
                            {"algorithm": "sha256", "hex_digest": value.hex_digest}
                            for value in result.evidence_digests
                        ],
                    }
                ],
            },
        )

        self.assertEqual(assessment.semantic_digest, expected)

    def test_assessment_identity_and_time_are_excluded_from_the_preimage(self) -> None:
        snapshot = build_snapshot()
        first = evaluate(snapshot)
        second = ReleaseEligibilityEvaluator(EVALUATOR).evaluate(
            snapshot=snapshot,
            eligibility_assessment_id=EligibilityAssessmentId(uid(91)),
            assessed_at_us=ASSESSED_AT + 5_000,
        )

        self.assertNotEqual(
            first.eligibility_assessment_id, second.eligibility_assessment_id
        )
        self.assertEqual(first.semantic_digest, second.semantic_digest)

    def test_eligible_flag_is_derived_and_never_supplied(self) -> None:
        assessment = evaluate(build_snapshot())

        with self.assertRaises(ValidationError):
            EligibilityAssessment.reconstitute(
                eligibility_assessment_id=assessment.eligibility_assessment_id,
                assessed_at_us=assessment.assessed_at_us,
                candidate_ref=assessment.candidate_ref,
                policy_ref=assessment.policy_ref,
                evaluator_ref=assessment.evaluator_ref,
                input_digest=assessment.input_digest,
                gate_results=assessment.gate_results,
                eligible=False,
                semantic_digest=assessment.semantic_digest,
            )


class IntegrityGateTests(unittest.TestCase):
    def test_required_check_missing_or_failed_blocks_without_short_circuit(self) -> None:
        rules = ReleasePolicyRules(
            required_integrity_checks=(
                IntegrityCheckCode("object-digests"),
                IntegrityCheckCode("sealed-manifests"),
            ),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        )
        assessment = evaluate(
            build_snapshot(
                rules=rules,
                integrity_results=(
                    IntegrityCheckResult(
                        IntegrityCheckCode("object-digests"), False, "digest mismatch"
                    ),
                ),
            )
        )

        self.assertFalse(assessment.eligible)
        self.assertEqual(
            outcome_for(assessment, "integrity:object-digests"), GateOutcome.FAIL
        )
        self.assertEqual(
            outcome_for(assessment, "integrity:sealed-manifests"), GateOutcome.FAIL
        )
        self.assertEqual(
            outcome_for(assessment, "unresolved-findings"), GateOutcome.PASS
        )

    def test_all_required_checks_present_and_passing_are_eligible(self) -> None:
        rules = ReleasePolicyRules(
            required_integrity_checks=(IntegrityCheckCode("object-digests"),),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        )
        assessment = evaluate(
            build_snapshot(
                rules=rules,
                integrity_results=(
                    IntegrityCheckResult(
                        IntegrityCheckCode("object-digests"), True, "verified"
                    ),
                ),
            )
        )

        self.assertTrue(assessment.eligible)


class UncertaintyGateTests(unittest.TestCase):
    def uncertainty_rules(
        self, allowances: tuple[UncertaintyAllowance, ...]
    ) -> ReleasePolicyRules:
        return ReleasePolicyRules(
            required_integrity_checks=(),
            uncertainty_allowances=allowances,
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        )

    def test_maximum_is_inclusive(self) -> None:
        rules = self.uncertainty_rules(
            (
                UncertaintyAllowance(
                    UncertaintyKind.INAUDIBLE, UncertaintyLimitMetric.MARK_COUNT, 3
                ),
            )
        )
        for count, expected in ((3, GateOutcome.PASS), (4, GateOutcome.FAIL)):
            with self.subTest(count=count):
                assessment = evaluate(
                    build_snapshot(
                        rules=rules,
                        observations=(
                            UncertaintyObservation(
                                UncertaintyKind.INAUDIBLE, count, 100, 10
                            ),
                        ),
                    )
                )
                self.assertEqual(
                    outcome_for(assessment, "uncertainty:inaudible"), expected
                )

    def test_each_metric_reads_its_own_observed_value(self) -> None:
        for metric, passing, failing in (
            (UncertaintyLimitMetric.MARK_COUNT, 2, 9),
            (UncertaintyLimitMetric.SOURCE_DURATION_US, 2, 9),
            (UncertaintyLimitMetric.CHARACTER_COUNT, 2, 9),
        ):
            with self.subTest(metric=metric):
                rules = self.uncertainty_rules(
                    (UncertaintyAllowance(UncertaintyKind.INAUDIBLE, metric, 5),)
                )
                values = {
                    UncertaintyLimitMetric.MARK_COUNT: lambda v: (v, 0, 0),
                    UncertaintyLimitMetric.SOURCE_DURATION_US: lambda v: (0, v, 0),
                    UncertaintyLimitMetric.CHARACTER_COUNT: lambda v: (0, 0, v),
                }[metric]
                for value, expected in ((passing, GateOutcome.PASS), (failing, GateOutcome.FAIL)):
                    marks, duration, characters = values(value)
                    assessment = evaluate(
                        build_snapshot(
                            rules=rules,
                            observations=(
                                UncertaintyObservation(
                                    UncertaintyKind.INAUDIBLE,
                                    marks,
                                    duration,
                                    characters,
                                ),
                            ),
                        )
                    )
                    self.assertEqual(
                        outcome_for(assessment, "uncertainty:inaudible"), expected
                    )

    def test_kind_absent_from_the_allowed_set_is_forbidden(self) -> None:
        rules = self.uncertainty_rules(())
        assessment = evaluate(
            build_snapshot(
                rules=rules,
                observations=(
                    UncertaintyObservation(
                        UncertaintyKind.UNCERTAIN_SPEAKER, 1, 10, 5
                    ),
                ),
            )
        )

        self.assertFalse(assessment.eligible)
        self.assertEqual(
            outcome_for(assessment, "uncertainty-forbidden:uncertain_speaker"),
            GateOutcome.FAIL,
        )

    def test_allowed_but_unobserved_kind_passes_at_zero(self) -> None:
        rules = self.uncertainty_rules(
            (
                UncertaintyAllowance(
                    UncertaintyKind.INAUDIBLE, UncertaintyLimitMetric.MARK_COUNT, 0
                ),
            )
        )
        assessment = evaluate(build_snapshot(rules=rules))

        self.assertEqual(outcome_for(assessment, "uncertainty:inaudible"), GateOutcome.PASS)


class FindingGateTests(unittest.TestCase):
    def blocking_rules(self, maximum_unresolved: int = 0) -> ReleasePolicyRules:
        return ReleasePolicyRules(
            required_integrity_checks=(),
            uncertainty_allowances=(),
            blocking_finding_rules=(
                BlockingFindingRule(
                    FindingCategoryCode("accuracy"), (FindingSeverityCode("major"),)
                ),
            ),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=maximum_unresolved,
        )

    def test_accepted_finding_is_unresolved_and_blocks(self) -> None:
        assessment = evaluate(
            build_snapshot(
                rules=self.blocking_rules(),
                evidence=closed_review(finding_decision=FindingDecision.ACCEPTED),
            )
        )

        self.assertFalse(assessment.eligible)
        self.assertEqual(
            outcome_for(assessment, "blocking-findings:accuracy"), GateOutcome.FAIL
        )
        self.assertEqual(outcome_for(assessment, "unresolved-findings"), GateOutcome.FAIL)

    def test_rejected_finding_is_resolved_and_does_not_block(self) -> None:
        assessment = evaluate(
            build_snapshot(
                rules=self.blocking_rules(),
                evidence=closed_review(finding_decision=FindingDecision.REJECTED),
            )
        )

        self.assertTrue(assessment.eligible)
        self.assertEqual(
            outcome_for(assessment, "blocking-findings:accuracy"), GateOutcome.PASS
        )

    def test_unresolved_maximum_is_inclusive(self) -> None:
        assessment = evaluate(
            build_snapshot(
                rules=ReleasePolicyRules(
                    required_integrity_checks=(),
                    uncertainty_allowances=(),
                    blocking_finding_rules=(),
                    review_coverage_requirements=(),
                    review_signoff_requirements=(),
                    external_signoff_requirements=(),
                    required_release_members=(),
                    maximum_unresolved_findings=1,
                ),
                evidence=closed_review(finding_decision=FindingDecision.ACCEPTED),
            )
        )

        self.assertEqual(outcome_for(assessment, "unresolved-findings"), GateOutcome.PASS)

    def test_nonmatching_severity_never_blocks(self) -> None:
        rules = ReleasePolicyRules(
            required_integrity_checks=(),
            uncertainty_allowances=(),
            blocking_finding_rules=(
                BlockingFindingRule(
                    FindingCategoryCode("accuracy"), (FindingSeverityCode("critical"),)
                ),
            ),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=1,
        )
        assessment = evaluate(
            build_snapshot(
                rules=rules,
                evidence=closed_review(finding_decision=FindingDecision.ACCEPTED),
            )
        )

        self.assertEqual(
            outcome_for(assessment, "blocking-findings:accuracy"), GateOutcome.PASS
        )


class ReviewCoverageGateTests(unittest.TestCase):
    def coverage_rules(
        self, basis_points: int, complete: bool = False
    ) -> ReleasePolicyRules:
        return ReleasePolicyRules(
            required_integrity_checks=(),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(
                ReviewCoverageRequirement(
                    RoleCode("language-reviewer"), basis_points, complete
                ),
            ),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        )

    def test_full_coverage_satisfies_a_full_requirement(self) -> None:
        assessment = evaluate(build_snapshot(rules=self.coverage_rules(10_000)))

        self.assertEqual(
            outcome_for(assessment, "review-coverage:language-reviewer"),
            GateOutcome.PASS,
        )

    def test_partial_coverage_is_measured_in_basis_points(self) -> None:
        evidence = partially_covered_review()
        for basis_points, expected in (
            (5_000, GateOutcome.PASS),
            (5_001, GateOutcome.FAIL),
        ):
            with self.subTest(basis_points=basis_points):
                assessment = evaluate(
                    build_snapshot(
                        rules=self.coverage_rules(basis_points),
                        evidence=evidence,
                        edition_evidence_override=edition_evidence(
                            edition=evidence.edition_ref
                        ),
                    )
                )
                self.assertEqual(
                    outcome_for(assessment, "review-coverage:language-reviewer"),
                    expected,
                )

    def test_complete_submission_requirement_rejects_a_partial_submission(self) -> None:
        evidence = partially_covered_review()
        assessment = evaluate(
            build_snapshot(
                rules=self.coverage_rules(0, complete=True),
                evidence=evidence,
                edition_evidence_override=edition_evidence(edition=evidence.edition_ref),
            )
        )

        self.assertEqual(
            outcome_for(assessment, "review-coverage:language-reviewer"),
            GateOutcome.FAIL,
        )

    def test_role_without_any_submission_fails_a_positive_requirement(self) -> None:
        assessment = evaluate(
            build_snapshot(
                rules=self.coverage_rules(1),
                evidence=closed_review(with_submission=False),
            )
        )

        self.assertEqual(
            outcome_for(assessment, "review-coverage:language-reviewer"),
            GateOutcome.FAIL,
        )


class SignOffGateTests(unittest.TestCase):
    def external_rules(
        self, minimum: AssuranceLevel, count: int = 1
    ) -> ReleasePolicyRules:
        return ReleasePolicyRules(
            required_integrity_checks=(),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(
                SignOffRequirement(
                    GateScope.EXTERNAL_RELEASE,
                    RoleCode("rights-holder"),
                    SignOffTargetKind.RELEASE_CONTENT,
                    None,
                    minimum,
                    count,
                ),
            ),
            required_release_members=(),
            maximum_unresolved_findings=0,
        )

    def signed_content_sign_off(self, snapshot_content: object) -> object:
        from heritage_production.domain.production import ExternalSignOffTarget

        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT,
            snapshot_content.content_manifest_ref,
            None,
            None,
        )
        return verified_sign_off(target=target)

    def test_missing_external_sign_off_fails_the_policy_gate(self) -> None:
        assessment = evaluate(
            build_snapshot(rules=self.external_rules(AssuranceLevel.VERIFIED_SIGNATURE))
        )

        self.assertFalse(assessment.eligible)
        self.assertEqual(
            outcome_for(
                assessment,
                "policy-external-signoff:rights-holder:release_content:",
            ),
            GateOutcome.FAIL,
        )

    def test_present_verified_sign_off_satisfies_the_policy_gate(self) -> None:
        policy = seal_policy(self.external_rules(AssuranceLevel.VERIFIED_SIGNATURE))
        gates = gate_set()
        content = seal_content(policy_ref=policy.ref, gate_set_ref=gates.ref)
        sign_off = self.signed_content_sign_off(content)
        candidate = seal_candidate(content, sign_off_digests=(sign_off.sign_off_digest,))
        snapshot = EligibilityInputSnapshot.seal(
            production_id=content.production_id,
            candidate=candidate,
            content=content,
            edition_evidence=edition_evidence(edition=content.edition_ref),
            policy=policy,
            gate_set=gates,
            sign_offs=(sign_off,),
            integrity_results=(),
        )

        assessment = evaluate(snapshot)

        self.assertTrue(assessment.eligible)

    def test_sign_off_for_other_content_never_satisfies_the_gate(self) -> None:
        policy = seal_policy(self.external_rules(AssuranceLevel.VERIFIED_SIGNATURE))
        gates = gate_set()
        content = seal_content(policy_ref=policy.ref, gate_set_ref=gates.ref)
        foreign = verified_sign_off(target=release_target())
        candidate = seal_candidate(content, sign_off_digests=(foreign.sign_off_digest,))
        snapshot = EligibilityInputSnapshot.seal(
            production_id=content.production_id,
            candidate=candidate,
            content=content,
            edition_evidence=edition_evidence(edition=content.edition_ref),
            policy=policy,
            gate_set=gates,
            sign_offs=(foreign,),
            integrity_results=(),
        )

        assessment = evaluate(snapshot)

        self.assertFalse(assessment.eligible)

    def test_production_gate_adds_a_requirement_policy_did_not_declare(self) -> None:
        requirement = ExternalGateRequirement(
            GateCode("rights-holder-approval"),
            GateScope.EXTERNAL_RELEASE,
            RoleCode("rights-holder"),
            verified_credential(40, FINGERPRINT),
            AssuranceLevel.VERIFIED_SIGNATURE,
            SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
        )
        assessment = evaluate(build_snapshot(gate_requirements=(requirement,)))

        self.assertFalse(assessment.eligible)
        self.assertEqual(
            outcome_for(assessment, "production-gate:rights-holder-approval"),
            GateOutcome.FAIL,
        )

    def test_review_scoped_production_gate_reads_review_sign_offs(self) -> None:
        requirement = ExternalGateRequirement(
            GateCode("archivist-review"),
            GateScope.REVIEW,
            RoleCode("archivist"),
            attested_credential(44),
            AssuranceLevel.STEWARD_ATTESTED,
            SignOffTargetRule(SignOffTargetKind.REVIEW_TARGET),
        )
        assessment = evaluate(build_snapshot(gate_requirements=(requirement,)))

        self.assertEqual(
            outcome_for(assessment, "production-gate:archivist-review"), GateOutcome.FAIL
        )


class RequiredArtifactGateTests(unittest.TestCase):
    def member_rules(self, roles: tuple[ManifestMemberRole, ...]) -> ReleasePolicyRules:
        return ReleasePolicyRules(
            required_integrity_checks=(),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=roles,
            maximum_unresolved_findings=0,
        )

    def test_present_member_passes_and_absent_member_fails(self) -> None:
        assessment = evaluate(
            build_snapshot(
                rules=self.member_rules(
                    (
                        ManifestMemberRole("source-audio"),
                        ManifestMemberRole("transcript-json"),
                    )
                )
            )
        )

        self.assertEqual(
            outcome_for(assessment, "required-member:transcript-json"), GateOutcome.PASS
        )
        self.assertEqual(
            outcome_for(assessment, "required-member:source-audio"), GateOutcome.FAIL
        )


class DeterminismTests(unittest.TestCase):
    def test_repeated_evaluation_of_identical_inputs_is_byte_stable(self) -> None:
        snapshot = build_snapshot()

        first = evaluate(snapshot)
        second = evaluate(snapshot)

        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(
            tuple(value.gate_code for value in first.gate_results),
            tuple(value.gate_code for value in second.gate_results),
        )

    def test_input_permutation_produces_the_same_assessment(self) -> None:
        rules = ReleasePolicyRules(
            required_integrity_checks=(
                IntegrityCheckCode("a-check"),
                IntegrityCheckCode("b-check"),
            ),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        )
        results = (
            IntegrityCheckResult(IntegrityCheckCode("a-check"), True, "ok"),
            IntegrityCheckResult(IntegrityCheckCode("b-check"), True, "ok"),
        )

        first = evaluate(build_snapshot(rules=rules, integrity_results=results))
        second = evaluate(build_snapshot(rules=rules, integrity_results=results))

        self.assertEqual(first.semantic_digest, second.semantic_digest)

        # Permutation cannot change a digest because non-canonical input is
        # refused at the boundary rather than silently reordered.
        with self.assertRaises(ValidationError):
            build_snapshot(rules=rules, integrity_results=tuple(reversed(results)))

    def test_gate_results_are_returned_in_a_stable_canonical_order(self) -> None:
        rules = ReleasePolicyRules(
            required_integrity_checks=(IntegrityCheckCode("z-check"),),
            uncertainty_allowances=(
                UncertaintyAllowance(
                    UncertaintyKind.INAUDIBLE, UncertaintyLimitMetric.MARK_COUNT, 5
                ),
            ),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(ManifestMemberRole("transcript-json"),),
            maximum_unresolved_findings=0,
        )
        assessment = evaluate(build_snapshot(rules=rules))
        codes = [value.gate_code.value for value in assessment.gate_results]

        self.assertEqual(codes, sorted(codes))


class RequirementResolutionTests(unittest.TestCase):
    def test_duplicate_semantic_keys_resolve_to_the_stricter_requirement(self) -> None:
        weaker = ResolvedSignOffRequirement(
            gate_code=GateCode("shared-key"),
            scope=GateScope.EXTERNAL_RELEASE,
            role=RoleCode("rights-holder"),
            target_kind=SignOffTargetKind.RELEASE_CONTENT,
            required_member_role=None,
            minimum_assurance=AssuranceLevel.STEWARD_ATTESTED,
            required_count=1,
            pinned_credential=None,
        )
        stronger = ResolvedSignOffRequirement(
            gate_code=GateCode("shared-key"),
            scope=GateScope.EXTERNAL_RELEASE,
            role=RoleCode("rights-holder"),
            target_kind=SignOffTargetKind.RELEASE_CONTENT,
            required_member_role=None,
            minimum_assurance=AssuranceLevel.VERIFIED_SIGNATURE,
            required_count=3,
            pinned_credential=None,
        )

        for ordering in ((weaker, stronger), (stronger, weaker)):
            with self.subTest(ordering=[value.required_count for value in ordering]):
                resolved = resolve_sign_off_requirements(ordering)

                self.assertEqual(len(resolved), 1)
                self.assertIs(
                    resolved[0].minimum_assurance, AssuranceLevel.VERIFIED_SIGNATURE
                )
                self.assertEqual(resolved[0].required_count, 3)

    def test_distinct_keys_are_preserved_as_separate_requirements(self) -> None:
        first = ResolvedSignOffRequirement(
            gate_code=GateCode("a"),
            scope=GateScope.EXTERNAL_RELEASE,
            role=RoleCode("rights-holder"),
            target_kind=SignOffTargetKind.RELEASE_CONTENT,
            required_member_role=None,
            minimum_assurance=AssuranceLevel.STEWARD_ATTESTED,
            required_count=1,
            pinned_credential=None,
        )
        second = ResolvedSignOffRequirement(
            gate_code=GateCode("b"),
            scope=GateScope.EXTERNAL_RELEASE,
            role=RoleCode("rights-holder"),
            target_kind=SignOffTargetKind.RELEASE_CONTENT,
            required_member_role=None,
            minimum_assurance=AssuranceLevel.STEWARD_ATTESTED,
            required_count=1,
            pinned_credential=verified_credential(40, digest("c")),
        )

        self.assertEqual(len(resolve_sign_off_requirements((first, second))), 2)


if __name__ == "__main__":
    unittest.main()
