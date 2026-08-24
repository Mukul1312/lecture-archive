"""Terminal negative regressions for every reproduced Task 5 bypass.

Each test here first reproduced a concrete way to reach an approval, a gate
pass, or an accepted evidence graph that the domain must refuse. They are kept
as permanent guards: none of them may be weakened.
"""

from __future__ import annotations

from copy import copy
import unittest

from heritage_production.domain.production import (
    ApprovalEvidence,
    AttachedSource,
    EditionSelection,
    Production,
)
from heritage_production.domain.release import (
    EligibilityAssessment,
    EligibilityAssessmentRef,
    EligibilityInputSnapshot,
    ExternalGateRequirement,
    ExternalGateSet,
    ExternalSignOffTarget,
    GateOutcome,
    GateResult,
    GateType,
    IntegrityCheckCode,
    ReleaseEligibilityEvaluator,
    ReleasePolicyRules,
    ReleasePolicyVersion,
)
from heritage_production.domain.review import FindingDecision
from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    DomainError,
    EditionRef,
    ExternalGateSetId,
    GateCode,
    GateScope,
    InvariantError,
    OperationId,
    ProductionId,
    ReleasePolicyVersionId,
    RoleCode,
    SignOffTargetKind,
    SignOffTargetRule,
    SourceVersionRef,
    StaleReferenceError,
    TranscriptEditionId,
    ValidationError,
)

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    artifact,
    closed_review,
    digest,
    edition_ref,
    production_id,
    source_version,
    uid,
    verified_credential,
)
from tests.heritage_production.test_production_aggregate import (
    STEWARD,
    attached_source,
    configured_production,
    event_id,
    gate_set,
    rights_holder_gate,
    selection_for,
)
from tests.heritage_production.test_production_approval import (
    APPROVED_AT,
    OPERATION,
    approvable,
    approve,
)
from tests.heritage_production.test_production_gates import (
    FINGERPRINT,
    verified_sign_off,
)
from tests.heritage_production.test_release_content import seal_candidate, seal_content
from tests.heritage_production.test_release_eligibility import (
    ASSESSED_AT,
    ASSESSMENT_ID,
    edition_evidence,
)
from tests.heritage_production.test_release_policy import (
    EVALUATOR,
    empty_rules,
    seal_policy,
)


def blocking_policy() -> ReleasePolicyVersion:
    """A policy whose integrity gate cannot pass without a supplied result."""
    return ReleasePolicyVersion.seal(
        release_policy_version_id=ReleasePolicyVersionId(uid(96)),
        semantic_label="blocking-transcript-policy",
        policy_schema_version=1,
        policy_schema_code="heritage-transcript-policy-v1",
        evaluator_ref=EVALUATOR,
        rules=ReleasePolicyRules(
            required_integrity_checks=(IntegrityCheckCode("object-digests"),),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        ),
        author_actor_id=actor(20),
        created_at_us=1_700_000_000_000_040,
    )


def production_with(policy: ReleasePolicyVersion, review_evidence=None):
    """Assemble a Production and a matching candidate for an arbitrary policy."""
    production, source = (lambda: None), None
    production = Production.create(
        production_id=production_id(),
        intended_deliverable="August 21 listening transcript",
        steward_actor_id=STEWARD,
        created_at_us=1_700_000_000_000_000,
        event_id=event_id(0),
        event_occurred_at_us=1_700_000_000_000_001,
    )
    source = attached_source()
    production.attach_source(
        attached_source=source, event_id=event_id(1), event_occurred_at_us=2
    )
    production.select_candidate_edition(
        selection=selection_for(source), event_id=event_id(2), event_occurred_at_us=3
    )
    production.select_release_policy(
        policy=policy, event_id=event_id(3), event_occurred_at_us=4
    )
    gates = gate_set()
    production.configure_external_gates(
        gate_set=gates, event_id=event_id(4), event_occurred_at_us=5
    )
    production.pull_events()
    content = seal_content(
        evidence=review_evidence if review_evidence is not None else closed_review(),
        policy_ref=policy.ref,
        gate_set_ref=gates.ref,
    )
    candidate = seal_candidate(content)
    production.assemble_candidate(
        candidate=candidate, content=content, event_id=event_id(5), event_occurred_at_us=6
    )
    production.pull_events()
    snapshot = EligibilityInputSnapshot.seal(
        production_id=production.production_id,
        candidate=candidate,
        content=content,
        edition_evidence=edition_evidence(edition=content.edition_ref),
        policy=policy,
        gate_set=gates,
        sign_offs=(),
        integrity_results=(),
    )
    return production, snapshot


def real_assessment(snapshot: EligibilityInputSnapshot) -> EligibilityAssessment:
    return ReleaseEligibilityEvaluator(EVALUATOR).evaluate(
        snapshot=snapshot,
        eligibility_assessment_id=ASSESSMENT_ID,
        assessed_at_us=ASSESSED_AT,
    )


def stored_ref(
    assessment: EligibilityAssessment, *, character: str = "7"
) -> EligibilityAssessmentRef:
    return EligibilityAssessmentRef(
        assessment.eligibility_assessment_id,
        assessment.semantic_digest,
        artifact(300, character),
    )


class FabricatedAssessmentTests(unittest.TestCase):
    """Critical 1 — approval must re-derive the assessment from its snapshot."""

    def test_assessment_with_a_foreign_input_digest_can_never_approve(self) -> None:
        production, snapshot = production_with(seal_policy(empty_rules()))
        genuine = real_assessment(snapshot)
        forged = EligibilityAssessment.seal(
            eligibility_assessment_id=genuine.eligibility_assessment_id,
            assessed_at_us=genuine.assessed_at_us,
            candidate_ref=genuine.candidate_ref,
            policy_ref=genuine.policy_ref,
            evaluator_ref=genuine.evaluator_ref,
            input_digest=digest("f"),
            gate_results=genuine.gate_results,
        )
        self.assertTrue(forged.eligible)

        with self.assertRaises(DomainError):
            ApprovalEvidence(
                snapshot=snapshot,
                assessment=forged,
                assessment_ref=stored_ref(forged),
            )

        self.assertIsNone(production.approval)

    def test_fabricated_passing_gates_can_never_approve_an_ineligible_graph(
        self,
    ) -> None:
        policy = blocking_policy()
        production, snapshot = production_with(policy)
        genuine = real_assessment(snapshot)
        self.assertFalse(genuine.eligible)

        forged = EligibilityAssessment.seal(
            eligibility_assessment_id=genuine.eligibility_assessment_id,
            assessed_at_us=genuine.assessed_at_us,
            candidate_ref=genuine.candidate_ref,
            policy_ref=genuine.policy_ref,
            evaluator_ref=genuine.evaluator_ref,
            input_digest=genuine.input_digest,
            gate_results=(
                GateResult(
                    GateCode("integrity:object-digests"),
                    GateType.INTEGRITY,
                    GateOutcome.PASS,
                    "fabricated-pass",
                    "passed integrity check",
                    "fabricated",
                    (),
                ),
                GateResult(
                    GateCode("unresolved-findings"),
                    GateType.UNRESOLVED_FINDING,
                    GateOutcome.PASS,
                    "unresolved-within-limit",
                    "at most 0 unresolved findings",
                    "0 unresolved findings",
                    (),
                ),
            ),
        )
        self.assertTrue(forged.eligible)

        with self.assertRaises(DomainError):
            ApprovalEvidence(
                snapshot=snapshot,
                assessment=forged,
                assessment_ref=stored_ref(forged),
            )

        self.assertIsNone(production.approval)

    def test_an_incomplete_gate_result_set_can_never_approve(self) -> None:
        policy = blocking_policy()
        production, snapshot = production_with(policy)
        genuine = real_assessment(snapshot)
        surviving = tuple(value for value in genuine.gate_results if value.passed)
        self.assertTrue(surviving)

        forged = EligibilityAssessment.seal(
            eligibility_assessment_id=genuine.eligibility_assessment_id,
            assessed_at_us=genuine.assessed_at_us,
            candidate_ref=genuine.candidate_ref,
            policy_ref=genuine.policy_ref,
            evaluator_ref=genuine.evaluator_ref,
            input_digest=genuine.input_digest,
            gate_results=surviving,
        )
        self.assertTrue(forged.eligible)

        with self.assertRaises(DomainError):
            ApprovalEvidence(
                snapshot=snapshot,
                assessment=forged,
                assessment_ref=stored_ref(forged),
            )

    def test_a_genuinely_ineligible_assessment_is_refused_at_approval(self) -> None:
        production, snapshot = production_with(blocking_policy())
        genuine = real_assessment(snapshot)
        evidence = ApprovalEvidence(
            snapshot=snapshot,
            assessment=genuine,
            assessment_ref=stored_ref(genuine),
        )

        with self.assertRaises(InvariantError):
            production.approve_candidate(
                evidence=evidence,
                steward_actor_id=STEWARD,
                approved_at_us=APPROVED_AT,
                operation_id=OPERATION,
                event_id=event_id(7),
                event_occurred_at_us=APPROVED_AT + 1,
            )

        self.assertIsNone(production.approval)
        self.assertEqual(production.pull_events(), ())

    def test_a_mutated_assessment_behind_its_digest_is_refused(self) -> None:
        production, snapshot = production_with(seal_policy(empty_rules()))
        genuine = real_assessment(snapshot)
        mutated = copy(genuine)
        object.__setattr__(mutated, "input_digest", digest("e"))

        with self.assertRaises(DomainError):
            ApprovalEvidence(
                snapshot=snapshot,
                assessment=mutated,
                assessment_ref=stored_ref(genuine),
            )


class ForgedReviewEvidenceTests(unittest.TestCase):
    """Critical 2 and 4 — closed review evidence must revalidate its own graph."""

    def test_zero_submission_review_cannot_be_bound_to_a_foreign_production(
        self,
    ) -> None:
        with self.assertRaises(DomainError):
            seal_content(
                evidence=closed_review(with_submission=False),
                owner=ProductionId(uid(555)),
            )

    def test_findings_cannot_be_stripped_behind_a_retained_evidence_digest(
        self,
    ) -> None:
        genuine = closed_review(finding_decision=FindingDecision.ACCEPTED)
        self.assertEqual(len(genuine.findings), 1)

        stripped = copy(genuine)
        object.__setattr__(stripped, "findings", ())

        with self.assertRaises(DomainError):
            seal_content(evidence=stripped)

    def test_coverage_cannot_be_replaced_behind_a_retained_evidence_digest(
        self,
    ) -> None:
        genuine = closed_review()
        other = closed_review(finding_decision=FindingDecision.ACCEPTED)
        forged = copy(genuine)
        object.__setattr__(forged, "coverage", other.coverage)

        with self.assertRaises(DomainError):
            seal_content(evidence=forged)

    def test_closed_evidence_self_identifies_its_production_and_target(self) -> None:
        evidence = closed_review()

        self.assertEqual(evidence.production_id, production_id())
        self.assertEqual(evidence.target_manifest.ref, evidence.target_manifest_ref)
        self.assertEqual(evidence, evidence.validated())


class PinnedCredentialTests(unittest.TestCase):
    """Critical 3 — a gate pins an exact credential, never merely an actor."""

    def substitute_credential(self) -> ActorCredentialRef:
        """A different verified credential belonging to the same actor."""
        return ActorCredentialRef(
            actor(40),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            digest("9"),
            artifact(410, "8", "application/octet-stream"),
        )

    def test_a_substituted_credential_never_satisfies_a_pinned_gate(self) -> None:
        requirement = rights_holder_gate()
        substitute = self.substitute_credential()
        self.assertEqual(substitute.actor_id, requirement.credential.actor_id)
        self.assertNotEqual(substitute, requirement.credential)

        sign_off = verified_sign_off(credential=substitute)

        self.assertFalse(requirement.is_satisfied_by(sign_off))

    def test_production_refuses_a_sign_off_from_a_substituted_credential(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        sign_off = verified_sign_off(
            target=target, credential=self.substitute_credential()
        )

        with self.assertRaises(DomainError):
            production.record_external_sign_off(
                sign_off=sign_off,
                content=content,
                event_id=event_id(6),
                event_occurred_at_us=1,
            )

        self.assertEqual(production.external_sign_offs, ())
        self.assertEqual(production.pull_events(), ())

    def test_an_attested_credential_never_stands_in_for_a_pinned_verified_key(
        self,
    ) -> None:
        requirement = rights_holder_gate()
        attested = ActorCredentialRef(
            actor(40),
            CredentialVerificationMethod.STEWARD_ATTESTATION,
            AssuranceLevel.STEWARD_ATTESTED,
        )

        self.assertEqual(attested.actor_id, requirement.credential.actor_id)
        self.assertNotEqual(attested, requirement.credential)


class AssessmentArtifactBindingTests(unittest.TestCase):
    """Important 5 — approval binds the complete stored assessment artifact."""

    def test_swapping_the_assessment_artifact_changes_the_approval_digest(self) -> None:
        first_production, first_snapshot = production_with(seal_policy(empty_rules()))
        second_production, second_snapshot = production_with(seal_policy(empty_rules()))
        first_assessment = real_assessment(first_snapshot)
        second_assessment = real_assessment(second_snapshot)

        first = approve(
            first_production,
            ApprovalEvidence(
                snapshot=first_snapshot,
                assessment=first_assessment,
                assessment_ref=stored_ref(first_assessment, character="7"),
            ),
        )
        second = approve(
            second_production,
            ApprovalEvidence(
                snapshot=second_snapshot,
                assessment=second_assessment,
                assessment_ref=stored_ref(second_assessment, character="8"),
            ),
        )

        self.assertNotEqual(
            first.assessment_ref.artifact, second.assessment_ref.artifact
        )
        self.assertNotEqual(first.approval_digest, second.approval_digest)

    def test_reconstitution_rejects_an_approval_missing_its_artifact(self) -> None:
        production, snapshot = production_with(seal_policy(empty_rules()))
        assessment = real_assessment(snapshot)
        approval = approve(
            production,
            ApprovalEvidence(
                snapshot=snapshot,
                assessment=assessment,
                assessment_ref=stored_ref(assessment),
            ),
        )
        stripped = copy(approval)
        object.__setattr__(
            stripped,
            "assessment_ref",
            EligibilityAssessmentRef(
                assessment.eligibility_assessment_id, assessment.semantic_digest, None
            ),
        )

        with self.assertRaises(DomainError):
            stripped.validated()


class ProductionReconstitutionHardeningTests(unittest.TestCase):
    """Important 6 — reconstitution refuses impossible stored state."""

    def base_arguments(self, production: Production) -> dict[str, object]:
        return {
            "production_id": production.production_id,
            "intended_deliverable": production.intended_deliverable,
            "steward_actor_id": production.steward_actor_id,
            "created_at_us": production.created_at_us,
            "sources": production.sources,
            "edition_selection": production.edition_selection,
            "selected_policy_ref": production.selected_policy_ref,
            "gate_sets": production.gate_sets,
            "active_gate_set_ref": production.active_gate_set_ref,
            "external_sign_offs": production.external_sign_offs,
            "candidates": production.candidates,
            "active_candidate_ref": production.active_candidate_ref,
            "approval": None,
        }

    def test_a_forged_source_is_rejected(self) -> None:
        production, _, _ = configured_production()
        forged = copy(production.sources[0])
        object.__setattr__(forged, "artifact", artifact(200, "9", "audio/mpeg"))
        arguments = self.base_arguments(production)
        arguments["sources"] = (forged,)

        with self.assertRaises(DomainError):
            Production.reconstitute(**arguments)

    def test_a_selection_using_an_unattached_source_is_rejected(self) -> None:
        production, _, _ = configured_production()
        arguments = self.base_arguments(production)
        arguments["edition_selection"] = EditionSelection(
            production.production_id,
            production.selected_edition_ref,
            (source_version(suffix=77, character="8"),),
        )

        with self.assertRaises(DomainError):
            Production.reconstitute(**arguments)

    def test_an_active_candidate_without_a_selected_policy_is_rejected(self) -> None:
        production, _, content = configured_production()
        candidate = seal_candidate(content)
        production.assemble_candidate(
            candidate=candidate, content=content, event_id=event_id(5), event_occurred_at_us=1
        )
        production.pull_events()
        arguments = self.base_arguments(production)
        arguments["selected_policy_ref"] = None

        with self.assertRaises(DomainError):
            Production.reconstitute(**arguments)

    def test_an_active_candidate_without_an_active_gate_set_is_rejected(self) -> None:
        production, _, content = configured_production()
        candidate = seal_candidate(content)
        production.assemble_candidate(
            candidate=candidate, content=content, event_id=event_id(5), event_occurred_at_us=1
        )
        production.pull_events()
        arguments = self.base_arguments(production)
        arguments["active_gate_set_ref"] = None
        arguments["gate_sets"] = ()

        with self.assertRaises(DomainError):
            Production.reconstitute(**arguments)

    def test_an_active_candidate_without_a_selection_is_rejected(self) -> None:
        production, _, content = configured_production()
        candidate = seal_candidate(content)
        production.assemble_candidate(
            candidate=candidate, content=content, event_id=event_id(5), event_occurred_at_us=1
        )
        production.pull_events()
        arguments = self.base_arguments(production)
        arguments["edition_selection"] = None

        with self.assertRaises(DomainError):
            Production.reconstitute(**arguments)

    def test_a_forged_gate_set_is_rejected(self) -> None:
        production, _, _ = configured_production()
        genuine = production.gate_sets[0]
        forged = copy(genuine)
        object.__setattr__(forged, "requirements", (rights_holder_gate(),))
        arguments = self.base_arguments(production)
        arguments["gate_sets"] = (forged,)

        with self.assertRaises(DomainError):
            Production.reconstitute(**arguments)


if __name__ == "__main__":
    unittest.main()
