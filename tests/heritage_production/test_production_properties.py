"""Property and state-machine proofs for Production approval reachability."""

from __future__ import annotations

import os
import unittest

from hypothesis import HealthCheck, given, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from heritage_production.domain.production import (
    ApprovalEvidence,
    ExternalGateSet,
    Production,
)
from heritage_production.domain.release import (
    EligibilityAssessmentRef,
    EligibilityInputSnapshot,
    ReleaseEligibilityEvaluator,
)
from heritage_production.domain.shared import (
    DomainError,
    DomainEventId,
    EditionRef,
    OperationId,
    TranscriptEditionId,
)

from tests.heritage_production.heritage_release_fixtures import (
    artifact,
    default_edition_evidence,
    digest,
    uid,
)
from tests.heritage_production.test_production_aggregate import (
    STEWARD,
    attached_source,
    configured_production,
    event_id,
    gate_set,
    new_production,
    selection_for,
)
from tests.heritage_production.test_release_content import seal_candidate
from tests.heritage_production.test_release_eligibility import (
    ASSESSED_AT,
    ASSESSMENT_ID,
    edition_evidence,
)
from tests.heritage_production.test_release_policy import EVALUATOR, empty_rules, seal_policy


def fresh_evidence(production: Production, candidate, content, policy) -> ApprovalEvidence:
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
    return ApprovalEvidence(
        snapshot=snapshot,
        assessment=assessment,
        assessment_ref=EligibilityAssessmentRef(
            assessment.eligibility_assessment_id,
            assessment.semantic_digest,
            artifact(300, "7"),
        ),
    )


class ProductionApprovalStateMachine(RuleBasedStateMachine):
    """Approval must stay unreachable until the complete exact graph exists."""

    # Counts successful approvals across every example. The invariant below
    # early-returns when no approval exists, so without this counter the whole
    # machine can pass while never once reaching an approval.
    approvals_reached = 0

    def __init__(self) -> None:
        super().__init__()
        self.production = new_production()
        self.source = None
        self.policy = None
        self.content = None
        self.candidate = None
        self.step = 0

    def _next_event(self) -> tuple[DomainEventId, int]:
        self.step += 1
        return DomainEventId(uid(800 + self.step)), 1_700_000_000_000_000 + self.step

    def _drain(self) -> None:
        self.production.pull_events()

    @rule()
    def attach_source(self) -> None:
        identifier, occurred = self._next_event()
        source = attached_source()
        try:
            self.production.attach_source(
                attached_source=source,
                event_id=identifier,
                event_occurred_at_us=occurred,
            )
        except DomainError:
            return
        self.source = source
        self._drain()

    @precondition(lambda self: self.source is not None)
    @rule()
    def select_edition(self) -> None:
        identifier, occurred = self._next_event()
        try:
            self.production.select_candidate_edition(
                selection=selection_for(self.source),
                event_id=identifier,
                event_occurred_at_us=occurred,
            )
        except DomainError:
            return
        self._drain()

    @rule()
    def select_policy(self) -> None:
        identifier, occurred = self._next_event()
        policy = seal_policy(empty_rules())
        try:
            self.production.select_release_policy(
                policy=policy, event_id=identifier, event_occurred_at_us=occurred
            )
        except DomainError:
            return
        self.policy = policy
        self._drain()

    @rule()
    def configure_gates(self) -> None:
        identifier, occurred = self._next_event()
        try:
            self.production.configure_external_gates(
                gate_set=gate_set(),
                event_id=identifier,
                event_occurred_at_us=occurred,
            )
        except DomainError:
            return
        self._drain()

    @rule()
    def assemble_candidate(self) -> None:
        from tests.heritage_production.test_release_content import seal_content

        identifier, occurred = self._next_event()
        if self.policy is None or self.production.active_gate_set_ref is None:
            return
        content = seal_content(
            policy_ref=self.policy.ref,
            gate_set_ref=self.production.active_gate_set_ref,
            provenance_input_digests=(default_edition_evidence().semantic_digest,),
            integrity_input_digests=(),
        )
        candidate = seal_candidate(content)
        try:
            self.production.assemble_candidate(
                candidate=candidate,
                content=content,
                event_id=identifier,
                event_occurred_at_us=occurred,
            )
        except DomainError:
            return
        self.content = content
        self.candidate = candidate
        self._drain()

    @precondition(lambda self: self.candidate is not None)
    @rule()
    def attempt_approval(self) -> None:
        identifier, occurred = self._next_event()
        if self.candidate is None or self.content is None or self.policy is None:
            return
        try:
            evidence = fresh_evidence(
                self.production, self.candidate, self.content, self.policy
            )
        except DomainError:
            return
        before = self._state()
        try:
            self.production.approve_candidate(
                evidence=evidence,
                steward_actor_id=STEWARD,
                approved_at_us=occurred,
                operation_id=OperationId(uid(900 + self.step)),
                event_id=identifier,
                event_occurred_at_us=occurred + 1,
            )
        except DomainError:
            assert self._state() == before
            assert self.production.pull_events() == ()
            return
        type(self).approvals_reached += 1
        self._drain()

    def _state(self) -> tuple[object, ...]:
        return (
            self.production.sources,
            self.production.selected_edition_ref,
            self.production.selected_policy_ref,
            self.production.gate_sets,
            self.production.active_gate_set_ref,
            self.production.external_sign_offs,
            self.production.candidates,
            self.production.active_candidate_ref,
            self.production.approval,
        )

    @invariant()
    def approval_requires_the_complete_exact_graph(self) -> None:
        approval = self.production.approval
        if approval is None:
            return
        assert self.production.selected_edition_ref is not None
        assert self.production.selected_policy_ref is not None
        assert self.production.active_gate_set_ref is not None
        assert self.production.active_candidate_ref is not None
        assert approval.release_candidate_ref == self.production.active_candidate_ref
        assert approval.edition_ref == self.production.selected_edition_ref
        assert approval.policy_ref == self.production.selected_policy_ref
        assert approval.external_gate_set_ref == self.production.active_gate_set_ref
        assert approval.steward_actor_id == self.production.steward_actor_id

    @invariant()
    def at_most_one_approval_exists(self) -> None:
        assert self.production.approval is None or (
            self.production.lifecycle_phase == "APPROVED"
        )

    @invariant()
    def candidate_history_is_append_only(self) -> None:
        for candidate in self.production.candidates:
            candidate.validated()


ProductionApprovalStateMachine.TestCase.settings = settings(
    max_examples=120,
    stateful_step_count=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
ProductionApprovalTests = ProductionApprovalStateMachine.TestCase


class StateMachineReachabilityTests(unittest.TestCase):
    """Guards the state machine against silently proving nothing."""

    def test_the_state_machine_actually_reaches_an_approval(self) -> None:
        ProductionApprovalStateMachine.approvals_reached = 0
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(
            ProductionApprovalStateMachine.TestCase
        )
        with open(os.devnull, "w", encoding="utf-8") as sink:
            result = unittest.TextTestRunner(verbosity=0, stream=sink).run(suite)

        self.assertTrue(result.wasSuccessful())
        self.assertGreater(
            ProductionApprovalStateMachine.approvals_reached,
            0,
            "the approval invariant never fired: the machine proved nothing",
        )


class RejectedOperationTests(unittest.TestCase):
    @settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(st.integers(min_value=1, max_value=40))
    def test_a_rejected_selection_leaves_state_and_events_unchanged(
        self, suffix: int
    ) -> None:
        production, policy, content = configured_production()
        before = (
            production.sources,
            production.selected_edition_ref,
            production.selected_policy_ref,
            production.gate_sets,
            production.active_gate_set_ref,
            production.candidates,
            production.active_candidate_ref,
        )

        tampered = selection_for(
            production.sources[0],
            edition=EditionRef(
                production.selected_edition_ref.transcript_edition_id,
                digest(f"{suffix % 10}"),
            ),
        )
        if tampered.edition_ref == production.selected_edition_ref:
            return

        with self.assertRaises(DomainError):
            production.select_candidate_edition(
                selection=tampered,
                event_id=event_id(30),
                event_occurred_at_us=10,
            )

        self.assertEqual(
            (
                production.sources,
                production.selected_edition_ref,
                production.selected_policy_ref,
                production.gate_sets,
                production.active_gate_set_ref,
                production.candidates,
                production.active_candidate_ref,
            ),
            before,
        )
        self.assertEqual(production.pull_events(), ())

    @settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(st.integers(min_value=900, max_value=940))
    def test_approval_is_unreachable_without_an_assembled_candidate(
        self, suffix: int
    ) -> None:
        production, policy, content = configured_production()
        candidate = seal_candidate(content)
        evidence = fresh_evidence(production, candidate, content, policy)

        with self.assertRaises(DomainError):
            production.approve_candidate(
                evidence=evidence,
                steward_actor_id=STEWARD,
                approved_at_us=1_700_000_000_000_200,
                operation_id=OperationId(uid(suffix)),
                event_id=event_id(31),
                event_occurred_at_us=1_700_000_000_000_201,
            )

        self.assertIsNone(production.approval)
        self.assertEqual(production.pull_events(), ())


if __name__ == "__main__":
    unittest.main()
