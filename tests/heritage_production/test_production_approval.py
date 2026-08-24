"""Terminal Production approval: exact graph, freshness, and one decision."""

from __future__ import annotations

import unittest

from heritage_production.domain.production import (
    ApprovalEvidence,
    ExternalGateSet,
    Production,
    ReleaseApproval,
)
from heritage_production.domain.release import (
    EligibilityAssessmentRef,
    EligibilityInputSnapshot,
    IntegrityCheckCode,
    ReleaseEligibilityEvaluator,
    ReleasePolicyRules,
)
from heritage_production.domain.shared import (
    ActorId,
    DomainEventId,
    EditionRef,
    ExternalGateSetId,
    InvariantError,
    OperationId,
    ProductionId,
    StaleReferenceError,
    TranscriptEditionId,
    ValidationError,
    semantic_digest,
)

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    artifact,
    digest,
    edition_ref,
    production_id,
    uid,
)
from tests.heritage_production.test_production_aggregate import (
    STEWARD,
    configured_production,
    event_id,
    rights_holder_gate,
    selection_for,
)
from tests.heritage_production.test_release_content import seal_candidate
from tests.heritage_production.test_release_eligibility import (
    ASSESSED_AT,
    ASSESSMENT_ID,
    edition_evidence,
)
from tests.heritage_production.test_release_policy import EVALUATOR, empty_rules

OPERATION = OperationId(uid(700))
APPROVED_AT = 1_700_000_000_000_100


def integrity_rules() -> ReleasePolicyRules:
    return ReleasePolicyRules(
        required_integrity_checks=(IntegrityCheckCode("object-digests"),),
        uncertainty_allowances=(),
        blocking_finding_rules=(),
        review_coverage_requirements=(),
        review_signoff_requirements=(),
        external_signoff_requirements=(),
        required_release_members=(),
        maximum_unresolved_findings=0,
    )


def approvable(
    *, rules=None, requirements=()
) -> tuple[Production, ApprovalEvidence, object]:
    """Assemble a Production with a fresh assessment over its active candidate."""
    production, policy, content = configured_production(requirements=requirements)
    if rules is not None:
        raise AssertionError("configured_production pins the empty rule set")
    candidate = seal_candidate(content)
    production.assemble_candidate(
        candidate=candidate,
        content=content,
        event_id=event_id(5),
        event_occurred_at_us=1,
    )
    production.pull_events()

    snapshot = EligibilityInputSnapshot.seal(
        production_id=production.production_id,
        candidate=candidate,
        content=content,
        edition_evidence=edition_evidence(edition=content.edition_ref),
        policy=policy,
        gate_set=production.active_gate_set,
        sign_offs=(),
        integrity_results=(),
    )
    assessment = ReleaseEligibilityEvaluator(EVALUATOR).evaluate(
        snapshot=snapshot,
        eligibility_assessment_id=ASSESSMENT_ID,
        assessed_at_us=ASSESSED_AT,
    )
    evidence = ApprovalEvidence(
        assessment=assessment,
        assessment_ref=EligibilityAssessmentRef(
            assessment.eligibility_assessment_id,
            assessment.semantic_digest,
            artifact(300, "7"),
        ),
        candidate=candidate,
        content=content,
        policy=policy,
        gate_set=production.active_gate_set,
        accepted_sign_offs=(),
    )
    return production, evidence, content


def approve(
    production: Production, evidence: ApprovalEvidence
) -> ReleaseApproval:
    return production.approve_candidate(
        evidence=evidence,
        steward_actor_id=STEWARD,
        approved_at_us=APPROVED_AT,
        operation_id=OPERATION,
        event_id=event_id(7),
        event_occurred_at_us=APPROVED_AT + 1,
    )


class ApprovalEvidenceTests(unittest.TestCase):
    def test_assessment_reference_must_name_the_exact_assessment(self) -> None:
        _, evidence, _ = approvable()

        with self.assertRaises(StaleReferenceError):
            ApprovalEvidence(
                assessment=evidence.assessment,
                assessment_ref=EligibilityAssessmentRef(
                    evidence.assessment.eligibility_assessment_id,
                    digest("f"),
                    artifact(300, "7"),
                ),
                candidate=evidence.candidate,
                content=evidence.content,
                policy=evidence.policy,
                gate_set=evidence.gate_set,
                accepted_sign_offs=(),
            )

    def test_approval_requires_a_stored_assessment_artifact(self) -> None:
        _, evidence, _ = approvable()

        with self.assertRaises(ValidationError):
            ApprovalEvidence(
                assessment=evidence.assessment,
                assessment_ref=EligibilityAssessmentRef(
                    evidence.assessment.eligibility_assessment_id,
                    evidence.assessment.semantic_digest,
                    None,
                ),
                candidate=evidence.candidate,
                content=evidence.content,
                policy=evidence.policy,
                gate_set=evidence.gate_set,
                accepted_sign_offs=(),
            )

    def test_assessment_must_evaluate_this_exact_candidate(self) -> None:
        _, evidence, content = approvable()
        other_candidate = seal_candidate(
            content, candidate_id=evidence.candidate.release_candidate_id.__class__(uid(54))
        )

        with self.assertRaises(StaleReferenceError):
            ApprovalEvidence(
                assessment=evidence.assessment,
                assessment_ref=evidence.assessment_ref,
                candidate=other_candidate,
                content=content,
                policy=evidence.policy,
                gate_set=evidence.gate_set,
                accepted_sign_offs=(),
            )

    def test_accepted_sign_offs_must_match_the_candidate_exactly(self) -> None:
        production, evidence, content = approvable(
            requirements=(rights_holder_gate(),)
        )
        from tests.heritage_production.test_production_aggregate import (
            ExternalSignOffTests,
        )

        sign_off = ExternalSignOffTests().content_sign_off(content)

        with self.assertRaises(StaleReferenceError):
            ApprovalEvidence(
                assessment=evidence.assessment,
                assessment_ref=evidence.assessment_ref,
                candidate=evidence.candidate,
                content=content,
                policy=evidence.policy,
                gate_set=evidence.gate_set,
                accepted_sign_offs=(sign_off,),
            )


class ApprovalTests(unittest.TestCase):
    def test_approval_binds_the_exact_graph_and_emits_the_terminal_fact(self) -> None:
        production, evidence, content = approvable()

        approval = approve(production, evidence)

        self.assertIs(production.approval, approval)
        self.assertEqual(approval.release_candidate_ref, evidence.candidate.ref)
        self.assertEqual(approval.edition_ref, content.edition_ref)
        self.assertEqual(approval.review_evidence_ref, content.review_evidence_ref)
        self.assertEqual(approval.policy_ref, evidence.policy.ref)
        self.assertEqual(approval.external_gate_set_ref, evidence.gate_set.ref)
        self.assertEqual(approval.evaluator_ref, EVALUATOR)
        self.assertEqual(approval.operation_id, OPERATION)
        self.assertEqual(approval, approval.validated())

        events = production.pull_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ReleaseCandidateApproved")
        payload = events[0].payload
        self.assertEqual(
            payload["release_candidate_id"],
            evidence.candidate.release_candidate_id.value,
        )
        self.assertEqual(payload["approval_digest"], approval.approval_digest.hex_digest)
        self.assertNotIn("transcript_text", payload)

    def test_approval_digest_excludes_the_operation_id(self) -> None:
        first_production, first_evidence, _ = approvable()
        second_production, second_evidence, _ = approvable()

        first = approve(first_production, first_evidence)
        second = second_production.approve_candidate(
            evidence=second_evidence,
            steward_actor_id=STEWARD,
            approved_at_us=APPROVED_AT,
            operation_id=OperationId(uid(701)),
            event_id=event_id(7),
            event_occurred_at_us=APPROVED_AT + 1,
        )

        self.assertNotEqual(first.operation_id, second.operation_id)
        self.assertEqual(first.approval_digest, second.approval_digest)

    def test_approval_digest_includes_the_explicit_decision_time(self) -> None:
        first_production, first_evidence, _ = approvable()
        second_production, second_evidence, _ = approvable()

        first = approve(first_production, first_evidence)
        second = second_production.approve_candidate(
            evidence=second_evidence,
            steward_actor_id=STEWARD,
            approved_at_us=APPROVED_AT + 5,
            operation_id=OPERATION,
            event_id=event_id(7),
            event_occurred_at_us=APPROVED_AT + 6,
        )

        self.assertNotEqual(first.approval_digest, second.approval_digest)

    def test_only_the_steward_can_approve(self) -> None:
        production, evidence, _ = approvable()

        with self.assertRaises(ValidationError):
            production.approve_candidate(
                evidence=evidence,
                steward_actor_id=ActorId(uid(999)),
                approved_at_us=APPROVED_AT,
                operation_id=OPERATION,
                event_id=event_id(7),
                event_occurred_at_us=APPROVED_AT + 1,
            )

        self.assertIsNone(production.approval)
        self.assertEqual(production.pull_events(), ())

    def test_an_ineligible_assessment_can_never_approve(self) -> None:
        production, evidence, content = approvable()
        snapshot = EligibilityInputSnapshot.seal(
            production_id=production.production_id,
            candidate=evidence.candidate,
            content=content,
            edition_evidence=edition_evidence(edition=content.edition_ref),
            policy=evidence.policy,
            gate_set=evidence.gate_set,
            sign_offs=(),
            integrity_results=(),
        )
        assessment = ReleaseEligibilityEvaluator(EVALUATOR).evaluate(
            snapshot=snapshot,
            eligibility_assessment_id=ASSESSMENT_ID,
            assessed_at_us=ASSESSED_AT,
        )
        # Forge an ineligible result by flipping one gate to FAIL.
        from heritage_production.domain.release import (
            EligibilityAssessment,
            GateOutcome,
            GateResult,
        )

        original = assessment.gate_results[0]
        failed = GateResult(
            original.gate_code,
            original.gate_type,
            GateOutcome.FAIL,
            "forced-failure",
            original.expected,
            "forced failure for this test",
            (),
        )
        ineligible = EligibilityAssessment.seal(
            eligibility_assessment_id=assessment.eligibility_assessment_id,
            assessed_at_us=assessment.assessed_at_us,
            candidate_ref=assessment.candidate_ref,
            policy_ref=assessment.policy_ref,
            evaluator_ref=assessment.evaluator_ref,
            input_digest=assessment.input_digest,
            gate_results=(failed,),
        )
        self.assertFalse(ineligible.eligible)

        blocked = ApprovalEvidence(
            assessment=ineligible,
            assessment_ref=EligibilityAssessmentRef(
                ineligible.eligibility_assessment_id,
                ineligible.semantic_digest,
                artifact(300, "7"),
            ),
            candidate=evidence.candidate,
            content=content,
            policy=evidence.policy,
            gate_set=evidence.gate_set,
            accepted_sign_offs=(),
        )

        with self.assertRaises(InvariantError):
            approve(production, blocked)

        self.assertIsNone(production.approval)
        self.assertEqual(production.pull_events(), ())

    def test_a_superseded_candidate_can_never_be_approved(self) -> None:
        production, evidence, content = approvable()
        superseding = seal_candidate(
            content,
            candidate_id=evidence.candidate.release_candidate_id.__class__(uid(55)),
        )
        # Reselect a different edition, which clears the active candidate.
        production.select_candidate_edition(
            selection=selection_for(
                production.sources[0],
                edition=EditionRef(TranscriptEditionId(uid(998)), digest("7")),
            ),
            event_id=event_id(23),
            event_occurred_at_us=2,
        )
        production.pull_events()

        with self.assertRaises(InvariantError):
            approve(production, evidence)

        self.assertIsNone(production.approval)

    def test_approval_is_terminal_for_every_later_mutation(self) -> None:
        production, evidence, content = approvable()
        approval = approve(production, evidence)
        production.pull_events()

        mutations = {
            "attach_source": lambda: production.attach_source(
                attached_source=production.sources[0],
                event_id=event_id(24),
                event_occurred_at_us=3,
            ),
            "select_candidate_edition": lambda: production.select_candidate_edition(
                selection=selection_for(production.sources[0]),
                event_id=event_id(25),
                event_occurred_at_us=3,
            ),
            "select_release_policy": lambda: production.select_release_policy(
                policy=evidence.policy, event_id=event_id(26), event_occurred_at_us=3
            ),
            "configure_external_gates": lambda: production.configure_external_gates(
                gate_set=evidence.gate_set,
                event_id=event_id(27),
                event_occurred_at_us=3,
            ),
            "assemble_candidate": lambda: production.assemble_candidate(
                candidate=evidence.candidate,
                content=content,
                event_id=event_id(28),
                event_occurred_at_us=3,
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(mutation=name):
                with self.assertRaises(InvariantError):
                    mutation()

        self.assertIs(production.approval, approval)
        self.assertEqual(production.pull_events(), ())

    def test_a_second_approval_is_refused_without_state_or_event_change(self) -> None:
        production, evidence, _ = approvable()
        approval = approve(production, evidence)
        production.pull_events()

        with self.assertRaises(InvariantError):
            approve(production, evidence)

        self.assertIs(production.approval, approval)
        self.assertEqual(production.pull_events(), ())

    def test_approval_requires_an_active_candidate(self) -> None:
        production, policy, content = configured_production()
        candidate = seal_candidate(content)
        snapshot = EligibilityInputSnapshot.seal(
            production_id=production.production_id,
            candidate=candidate,
            content=content,
            edition_evidence=edition_evidence(edition=content.edition_ref),
            policy=policy,
            gate_set=production.active_gate_set,
            sign_offs=(),
            integrity_results=(),
        )
        assessment = ReleaseEligibilityEvaluator(EVALUATOR).evaluate(
            snapshot=snapshot,
            eligibility_assessment_id=ASSESSMENT_ID,
            assessed_at_us=ASSESSED_AT,
        )
        evidence = ApprovalEvidence(
            assessment=assessment,
            assessment_ref=EligibilityAssessmentRef(
                assessment.eligibility_assessment_id,
                assessment.semantic_digest,
                artifact(300, "7"),
            ),
            candidate=candidate,
            content=content,
            policy=policy,
            gate_set=production.active_gate_set,
            accepted_sign_offs=(),
        )

        with self.assertRaises(InvariantError):
            approve(production, evidence)

    def test_approved_production_reconstitutes_without_events(self) -> None:
        production, evidence, _ = approvable()
        approval = approve(production, evidence)
        production.pull_events()

        restored = Production.reconstitute(
            production_id=production.production_id,
            intended_deliverable=production.intended_deliverable,
            steward_actor_id=production.steward_actor_id,
            created_at_us=production.created_at_us,
            sources=production.sources,
            selected_edition_ref=production.selected_edition_ref,
            selected_policy_ref=production.selected_policy_ref,
            gate_sets=production.gate_sets,
            active_gate_set_ref=production.active_gate_set_ref,
            external_sign_offs=production.external_sign_offs,
            candidates=production.candidates,
            active_candidate_ref=production.active_candidate_ref,
            approval=approval,
        )

        self.assertEqual(restored.pull_events(), ())
        self.assertEqual(restored.lifecycle_phase, "APPROVED")

    def test_reconstitute_rejects_an_approval_bound_to_another_graph(self) -> None:
        production, evidence, _ = approvable()
        approval = approve(production, evidence)

        with self.assertRaises(ValidationError):
            Production.reconstitute(
                production_id=production.production_id,
                intended_deliverable=production.intended_deliverable,
                steward_actor_id=ActorId(uid(997)),
                created_at_us=production.created_at_us,
                sources=production.sources,
                selected_edition_ref=production.selected_edition_ref,
                selected_policy_ref=production.selected_policy_ref,
                gate_sets=production.gate_sets,
                active_gate_set_ref=production.active_gate_set_ref,
                external_sign_offs=production.external_sign_offs,
                candidates=production.candidates,
                active_candidate_ref=production.active_candidate_ref,
                approval=approval,
            )


if __name__ == "__main__":
    unittest.main()
