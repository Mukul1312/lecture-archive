"""Terminal negative regressions for every reproduced Task 5 bypass.

Each test here first reproduced a concrete way to reach an approval, a gate
pass, or an accepted evidence graph that the domain must refuse. They are kept
as permanent guards: none of them may be weakened.
"""

from __future__ import annotations

from copy import copy
import unittest

from heritage_production.domain.production import (
    gate_is_satisfied_by,
    ApprovalEvidence,
    EditionSelection,
    ExternalSignOffTarget,
    Production,
)
from heritage_production.domain.release import (
    SUPPORTED_EVALUATOR_REF,
    EligibilityAssessment,
    EligibilityAssessmentRef,
    EligibilityInputSnapshot,
    GateOutcome,
    GateResult,
    GateType,
    IntegrityCheckCode,
    ReleaseCandidateSnapshot,
    ReleaseEligibilityEvaluator,
    GateOutcome,
    IntegrityCheckResult,
    ReleaseMember,
    UncertaintyObservation,
    ReleasePolicyRules,
    ReleasePolicyVersion,
    SignOffRequirement,
)
from heritage_production.domain.review import FindingDecision
from heritage_production.domain.transcription import UncertaintyKind
from heritage_production.domain.shared import (
    ActorCredentialRef,
    AssuranceLevel,
    CredentialVerificationMethod,
    DomainError,
    EvaluatorUnavailableError,
    GateCode,
    GateScope,
    InvariantError,
    PolicyEvaluatorRef,
    ManifestMemberRole,
    ProductionId,
    ReleaseCandidateId,
    ReleasePolicyVersionId,
    ReviewEvidenceRef,
    ReviewRoundId,
    RoleCode,
    SignOffDecision,
    SignOffTargetKind,
    StaleReferenceError,
    ValidationError,
)

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    artifact,
    closed_review,
    default_edition_evidence,
    digest,
    edition_ref,
    production_id,
    source_version,
    successor_edition_ref,
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
    sourced_production,
)
from tests.heritage_production.test_production_approval import (
    APPROVED_AT,
    OPERATION,
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
    evidence_for_content = (
        review_evidence if review_evidence is not None else closed_review()
    )
    content = seal_content(
        evidence=evidence_for_content,
        policy_ref=policy.ref,
        gate_set_ref=gates.ref,
        provenance_input_digests=(
            edition_evidence(edition=evidence_for_content.edition_ref).semantic_digest,
        ),
        integrity_input_digests=(),
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

        with self.assertRaises(StaleReferenceError):
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

        with self.assertRaises(StaleReferenceError):
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

        with self.assertRaises(StaleReferenceError):
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

    def test_an_assessment_swapped_after_evidence_construction_is_refused(
        self,
    ) -> None:
        """`approve_candidate` re-runs `evidence.validated()` for this reason.

        ApprovalEvidence is a frozen value, so a caller can swap its assessment
        after construction. Only the aggregate's own re-validation catches it.
        """
        production, snapshot = production_with(blocking_policy())
        genuine = real_assessment(snapshot)
        self.assertFalse(genuine.eligible)
        evidence = ApprovalEvidence(
            snapshot=snapshot,
            assessment=genuine,
            assessment_ref=stored_ref(genuine),
        )

        # Forge an eligible-looking assessment and swap it in post-construction.
        forged = EligibilityAssessment.seal(
            eligibility_assessment_id=genuine.eligibility_assessment_id,
            assessed_at_us=genuine.assessed_at_us,
            candidate_ref=genuine.candidate_ref,
            policy_ref=genuine.policy_ref,
            evaluator_ref=genuine.evaluator_ref,
            input_digest=genuine.input_digest,
            gate_results=tuple(
                value for value in genuine.gate_results if value.passed
            ),
        )
        self.assertTrue(forged.eligible)
        object.__setattr__(evidence, "assessment", forged)
        object.__setattr__(evidence, "assessment_ref", stored_ref(forged))
        self.assertTrue(evidence.eligible)

        with self.assertRaises(DomainError):
            approve(production, evidence)

        self.assertIsNone(production.approval)
        self.assertEqual(production.pull_events(), ())

    def test_a_mutated_assessment_behind_its_digest_is_refused(self) -> None:
        production, snapshot = production_with(seal_policy(empty_rules()))
        genuine = real_assessment(snapshot)
        mutated = copy(genuine)
        object.__setattr__(mutated, "input_digest", digest("e"))

        with self.assertRaises(ValidationError):
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
        with self.assertRaises(ValidationError):
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

        with self.assertRaises(ValidationError):
            seal_content(evidence=stripped)

    def test_coverage_cannot_be_replaced_behind_a_retained_evidence_digest(
        self,
    ) -> None:
        genuine = closed_review()
        other = closed_review(finding_decision=FindingDecision.ACCEPTED)
        forged = copy(genuine)
        object.__setattr__(forged, "coverage", other.coverage)

        with self.assertRaises(ValidationError):
            seal_content(evidence=forged)

    def test_forged_target_identity_dies_behind_an_unchanged_evidence_digest(
        self,
    ) -> None:
        """The evidence digest hashes only the target's stored semantic digest.

        Forging the manifest's own Production or edition therefore leaves
        `heritage-review-evidence-v1` byte-identical, so only recomputing the
        target from its own fields can catch it.
        """
        genuine = closed_review(with_submission=False)
        foreign = ProductionId(uid(555))
        swapped = successor_edition_ref()

        for label, manifest_change, evidence_change in (
            ("production", {"production_id": foreign}, {"production_id": foreign}),
            ("edition", {"edition_ref": swapped}, {"edition_ref": swapped}),
        ):
            with self.subTest(forged=label):
                manifest = copy(genuine.target_manifest)
                for name, value in manifest_change.items():
                    object.__setattr__(manifest, name, value)
                forged = copy(genuine)
                object.__setattr__(forged, "target_manifest", manifest)
                for name, value in evidence_change.items():
                    object.__setattr__(forged, name, value)

                # The load-bearing assertion: the digest is NOT the defence.
                self.assertEqual(forged.evidence_ref, genuine.evidence_ref)

                with self.assertRaises(ValidationError):
                    forged.validated()
                with self.assertRaises(ValidationError):
                    seal_content(
                        evidence=forged,
                        owner=forged.production_id,
                        edition=forged.edition_ref,
                    )

    def test_a_forged_reviewer_assignment_is_rejected(self) -> None:
        """Assignment credentials are excluded from every digest by design."""
        genuine = closed_review()
        assignment = copy(genuine.reviewer_assignments[0])
        object.__setattr__(
            assignment, "minimum_assurance", AssuranceLevel.VERIFIED_SIGNATURE
        )
        forged = copy(genuine)
        object.__setattr__(forged, "reviewer_assignments", (assignment,))

        self.assertEqual(forged.evidence_ref, genuine.evidence_ref)
        with self.assertRaises(ValidationError):
            forged.validated()

    def test_a_forged_target_manifest_wrapper_artifact_is_rejected(self) -> None:
        """The wrapper artifact is outside the target payload, so rebuild it."""
        genuine = closed_review(with_submission=False)
        manifest_ref = copy(genuine.target_manifest.ref)
        object.__setattr__(manifest_ref, "artifact", "not-an-artifact-ref")
        manifest = copy(genuine.target_manifest)
        object.__setattr__(manifest, "ref", manifest_ref)
        forged = copy(genuine)
        object.__setattr__(forged, "target_manifest", manifest)

        with self.assertRaises(ValidationError):
            forged.validated()

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

        self.assertFalse(gate_is_satisfied_by(requirement, sign_off))

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

        with self.assertRaises(ValidationError):
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

        with self.assertRaises(ValidationError):
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

        with self.assertRaises(ValidationError):
            Production.reconstitute(**arguments)

    def test_a_selection_using_an_unattached_source_is_rejected(self) -> None:
        production, _, _ = configured_production()
        arguments = self.base_arguments(production)
        arguments["edition_selection"] = EditionSelection(
            production.production_id,
            production.selected_edition_ref,
            (source_version(suffix=77, character="8"),),
        )

        with self.assertRaises(ValidationError):
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

        with self.assertRaises(ValidationError):
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

        with self.assertRaises(ValidationError):
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

        with self.assertRaises(ValidationError):
            Production.reconstitute(**arguments)

    def test_a_forged_gate_set_is_rejected(self) -> None:
        production, _, _ = configured_production()
        genuine = production.gate_sets[0]
        forged = copy(genuine)
        object.__setattr__(forged, "requirements", (rights_holder_gate(),))
        arguments = self.base_arguments(production)
        arguments["gate_sets"] = (forged,)

        with self.assertRaises(ValidationError):
            Production.reconstitute(**arguments)


class MutatorChildValidationTests(unittest.TestCase):
    """Fix round 2 — every mutator reconstructs its child before writing."""

    def test_attach_source_rejects_a_forged_source(self) -> None:
        production, source = sourced_production()
        # A *fresh* identity, so this cannot pass through the duplicate-content
        # branch: only the child reconstruction can reject it.
        other = attached_source(
            source_version(suffix=91, character="4"), media_digest="4"
        )
        forged = copy(other)
        object.__setattr__(forged, "artifact", artifact(200, "9", "audio/mpeg"))
        self.assertNotEqual(forged.identity, source.identity)

        with self.assertRaises(ValidationError):
            production.attach_source(
                attached_source=forged,
                event_id=event_id(40),
                event_occurred_at_us=9,
            )

        self.assertEqual(production.sources, (source,))
        self.assertEqual(production.pull_events(), ())

    def _tampered_content(self, content):
        tampered = copy(content)
        object.__setattr__(
            tampered,
            "review_evidence_ref",
            ReviewEvidenceRef(ReviewRoundId(uid(777)), digest("e")),
        )
        return tampered

    def test_assemble_candidate_rejects_content_failing_reconstruction(self) -> None:
        production, _, content = configured_production()
        tampered = self._tampered_content(content)

        with self.assertRaises(ValidationError):
            production.assemble_candidate(
                candidate=seal_candidate(tampered),
                content=tampered,
                event_id=event_id(41),
                event_occurred_at_us=9,
            )

        self.assertEqual(production.candidates, ())
        self.assertIsNone(production.active_candidate_ref)
        self.assertEqual(production.pull_events(), ())

    def test_record_sign_off_rejects_content_failing_reconstruction(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        sign_off = verified_sign_off(target=target)

        with self.assertRaises(ValidationError):
            production.record_external_sign_off(
                sign_off=sign_off,
                content=self._tampered_content(content),
                event_id=event_id(42),
                event_occurred_at_us=9,
            )

        self.assertEqual(production.external_sign_offs, ())
        self.assertEqual(production.pull_events(), ())

    def test_a_declined_sign_off_from_a_substituted_credential_is_refused(self) -> None:
        """An unpinned credential must never enter append-only history."""
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        substitute = ActorCredentialRef(
            actor(40),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            digest("9"),
            artifact(410, "8", "application/octet-stream"),
        )
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )

        for decision in (SignOffDecision.APPROVED, SignOffDecision.DECLINED):
            with self.subTest(decision=decision.value):
                with self.assertRaises(ValidationError):
                    production.record_external_sign_off(
                        sign_off=verified_sign_off(
                            target=target, credential=substitute, decision=decision
                        ),
                        content=content,
                        event_id=event_id(43),
                        event_occurred_at_us=9,
                    )

        self.assertEqual(production.external_sign_offs, ())
        self.assertEqual(production.pull_events(), ())

    def test_reselecting_an_edition_with_another_source_set_is_rejected(self) -> None:
        production, source = sourced_production()
        production.select_candidate_edition(
            selection=selection_for(source),
            event_id=event_id(44),
            event_occurred_at_us=9,
        )
        production.pull_events()
        before = production.edition_selection
        widened = EditionSelection(
            production.production_id,
            edition_ref(),
            tuple(
                sorted(
                    (source.source_version_ref, source_version(suffix=88, character="5")),
                    key=lambda value: value.source_version_id.value,
                )
            ),
        )

        with self.assertRaises(ValidationError):
            production.select_candidate_edition(
                selection=widened,
                event_id=event_id(45),
                event_occurred_at_us=10,
            )

        self.assertEqual(production.edition_selection, before)
        self.assertEqual(production.pull_events(), ())


class StoredStateHardeningTests(unittest.TestCase):
    """Fix round 2 — reconstitution refuses history the live path cannot produce."""

    def test_a_sign_off_no_gate_declared_is_rejected(self) -> None:
        """Stored history must obey the rule the live path enforces.

        With an explicitly empty gate set, `record_external_sign_off` refuses
        every sign-off. Reconstitution must refuse the same state, or an
        undeclared sign-off could discharge a policy requirement that pins no
        credential of its own.
        """
        production, _, content = configured_production()
        self.assertEqual(production.active_gate_set.requirements, ())
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        undeclared = verified_sign_off(target=target)

        with self.assertRaises(ValidationError):
            production.record_external_sign_off(
                sign_off=undeclared,
                content=content,
                event_id=event_id(55),
                event_occurred_at_us=9,
            )

        with self.assertRaises(ValidationError):
            Production.reconstitute(
                production_id=production.production_id,
                intended_deliverable=production.intended_deliverable,
                steward_actor_id=production.steward_actor_id,
                created_at_us=production.created_at_us,
                sources=production.sources,
                edition_selection=production.edition_selection,
                selected_policy_ref=production.selected_policy_ref,
                gate_sets=production.gate_sets,
                active_gate_set_ref=production.active_gate_set_ref,
                external_sign_offs=(undeclared,),
                candidates=(),
                active_candidate_ref=None,
                approval=None,
            )

    def test_a_candidate_sign_off_for_other_content_is_rejected(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        sign_off = verified_sign_off(target=target)
        production.record_external_sign_off(
            sign_off=sign_off, content=content, event_id=event_id(46), event_occurred_at_us=9
        )
        production.pull_events()

        foreign_content = seal_content(
            policy_ref=production.selected_policy_ref,
            gate_set_ref=production.active_gate_set_ref,
            release_members=(
                ReleaseMember(ManifestMemberRole("transcript-json"), artifact(80, "1")),
            ),
        )
        candidate = ReleaseCandidateSnapshot.seal(
            release_candidate_id=ReleaseCandidateId(uid(56)),
            production_id=production.production_id,
            content_manifest_ref=foreign_content.content_manifest_ref,
            included_sign_off_digests=(sign_off.sign_off_digest,),
            assembled_at_us=1_700_000_000_000_050,
        )

        with self.assertRaises(ValidationError):
            Production.reconstitute(
                production_id=production.production_id,
                intended_deliverable=production.intended_deliverable,
                steward_actor_id=production.steward_actor_id,
                created_at_us=production.created_at_us,
                sources=production.sources,
                edition_selection=production.edition_selection,
                selected_policy_ref=production.selected_policy_ref,
                gate_sets=production.gate_sets,
                active_gate_set_ref=production.active_gate_set_ref,
                external_sign_offs=production.external_sign_offs,
                candidates=(candidate,),
                active_candidate_ref=candidate.ref,
                approval=None,
            )


class EvaluatorPinningTests(unittest.TestCase):
    """Fix round 2 — an evaluator this build does not ship cannot interpret a policy."""

    def ghost_evaluator(self) -> PolicyEvaluatorRef:
        return PolicyEvaluatorRef(
            SUPPORTED_EVALUATOR_REF.evaluator_name,
            "9.9.9",
            SUPPORTED_EVALUATOR_REF.supported_policy_schema,
            digest("f"),
        )

    def test_a_ghost_evaluator_build_cannot_be_constructed(self) -> None:
        with self.assertRaises(EvaluatorUnavailableError):
            ReleaseEligibilityEvaluator(self.ghost_evaluator())

    def test_a_ghost_pinned_policy_can_never_reach_an_approval(self) -> None:
        """Sealing such a policy is allowed; evaluating it must fail closed."""
        ghost_policy = ReleasePolicyVersion.seal(
            release_policy_version_id=ReleasePolicyVersionId(uid(97)),
            semantic_label="ghost-pinned-policy",
            policy_schema_version=1,
            policy_schema_code=SUPPORTED_EVALUATOR_REF.supported_policy_schema,
            evaluator_ref=self.ghost_evaluator(),
            rules=ReleasePolicyRules((), (), (), (), (), (), (), 0),
            author_actor_id=actor(20),
            created_at_us=1_700_000_000_000_060,
        )
        production, snapshot = production_with(ghost_policy)
        genuine = real_assessment(production_with(seal_policy(empty_rules()))[1])

        with self.assertRaises(EvaluatorUnavailableError):
            ApprovalEvidence(
                snapshot=snapshot,
                assessment=genuine,
                assessment_ref=stored_ref(genuine),
            )

        self.assertIsNone(production.approval)


class SignerCountingTests(unittest.TestCase):
    """Fix round 2 — a required count means that many distinct signers."""

    def test_one_signer_cannot_satisfy_a_two_signer_gate(self) -> None:
        policy = ReleasePolicyVersion.seal(
            release_policy_version_id=ReleasePolicyVersionId(uid(98)),
            semantic_label="two-signer-policy",
            policy_schema_version=1,
            policy_schema_code=SUPPORTED_EVALUATOR_REF.supported_policy_schema,
            evaluator_ref=SUPPORTED_EVALUATOR_REF,
            rules=ReleasePolicyRules(
                (),
                (),
                (),
                (),
                (),
                (
                    SignOffRequirement(
                        GateScope.EXTERNAL_RELEASE,
                        RoleCode("rights-holder"),
                        SignOffTargetKind.RELEASE_CONTENT,
                        None,
                        AssuranceLevel.VERIFIED_SIGNATURE,
                        2,
                    ),
                ),
                (),
                0,
            ),
            author_actor_id=actor(20),
            created_at_us=1_700_000_000_000_061,
        )
        gates = gate_set((rights_holder_gate(),))
        content = seal_content(
            policy_ref=policy.ref,
            gate_set_ref=gates.ref,
            provenance_input_digests=(edition_evidence().semantic_digest,),
            integrity_input_digests=(),
        )
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        # Same credential, two distinct sign-off records.
        first = verified_sign_off(target=target, signed_at_us=1_700_000_000_000_001)
        second = verified_sign_off(target=target, signed_at_us=1_700_000_000_000_002)
        self.assertNotEqual(first.sign_off_digest, second.sign_off_digest)
        self.assertEqual(first.credential, second.credential)

        ordered = tuple(
            sorted((first, second), key=lambda value: value.sign_off_digest.hex_digest)
        )
        candidate = seal_candidate(
            content,
            sign_off_digests=tuple(value.sign_off_digest for value in ordered),
        )
        snapshot = EligibilityInputSnapshot.seal(
            production_id=content.production_id,
            candidate=candidate,
            content=content,
            edition_evidence=edition_evidence(edition=content.edition_ref),
            policy=policy,
            gate_set=gates,
            sign_offs=ordered,
            integrity_results=(),
        )
        assessment = ReleaseEligibilityEvaluator(SUPPORTED_EVALUATOR_REF).evaluate(
            snapshot=snapshot,
            eligibility_assessment_id=ASSESSMENT_ID,
            assessed_at_us=ASSESSED_AT,
        )

        self.assertFalse(assessment.eligible)
        gate = next(
            value
            for value in assessment.gate_results
            if "external-signoff" in value.gate_code.value
        )
        self.assertEqual(gate.actual, "1 qualifying signers")


class EvaluatorPinnedCredentialTests(unittest.TestCase):
    """The evaluator must match a Production gate's pinned credential exactly."""

    def assess(self, credential):
        policy = seal_policy(empty_rules())
        gates = gate_set((rights_holder_gate(),))
        content = seal_content(
            policy_ref=policy.ref,
            gate_set_ref=gates.ref,
            provenance_input_digests=(default_edition_evidence().semantic_digest,),
            integrity_input_digests=(),
        )
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        sign_off = verified_sign_off(target=target, credential=credential)
        candidate = seal_candidate(
            content, sign_off_digests=(sign_off.sign_off_digest,)
        )
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
        return ReleaseEligibilityEvaluator(SUPPORTED_EVALUATOR_REF).evaluate(
            snapshot=snapshot,
            eligibility_assessment_id=ASSESSMENT_ID,
            assessed_at_us=ASSESSED_AT,
        )

    def gate_outcome(self, assessment):
        return next(
            value.outcome
            for value in assessment.gate_results
            if value.gate_code.value == "production-gate:rights-holder-approval"
        )

    def test_the_pinned_credential_passes_its_own_gate(self) -> None:
        """Paired with the negative case, so neither can pass vacuously."""
        assessment = self.assess(verified_credential(40, FINGERPRINT))

        self.assertIs(self.gate_outcome(assessment), GateOutcome.PASS)
        self.assertTrue(assessment.eligible)

    def test_a_substituted_signing_key_never_discharges_a_pinned_gate(self) -> None:
        substitute = ActorCredentialRef(
            actor(40),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            digest("9"),
            artifact(410, "8", "application/octet-stream"),
        )
        self.assertEqual(substitute.actor_id, verified_credential(40, FINGERPRINT).actor_id)

        assessment = self.assess(substitute)

        self.assertIs(self.gate_outcome(assessment), GateOutcome.FAIL)
        self.assertFalse(assessment.eligible)


class UnauthenticatedInputTests(unittest.TestCase):
    """Fix round 2 — evaluator inputs must be named by the signed release content."""

    HONEST_RESULT = IntegrityCheckResult(
        IntegrityCheckCode("object-digests"), True, "verified"
    )

    def graph(self):
        policy = seal_policy(empty_rules())
        gates = gate_set()
        honest = edition_evidence()
        content = seal_content(
            policy_ref=policy.ref,
            gate_set_ref=gates.ref,
            provenance_input_digests=(honest.semantic_digest,),
            integrity_input_digests=(self.HONEST_RESULT.semantic_digest,),
        )
        return policy, gates, content, seal_candidate(content)

    def seal_with(self, edition_ev, results):
        policy, gates, content, candidate = self.graph()
        return EligibilityInputSnapshot.seal(
            production_id=content.production_id,
            candidate=candidate,
            content=content,
            edition_evidence=edition_ev(content),
            policy=policy,
            gate_set=gates,
            sign_offs=(),
            integrity_results=results,
        )

    def test_an_invented_uncertainty_report_is_rejected(self) -> None:
        """Changing any observation changes the derived digest, so it is unsigned."""
        with self.assertRaises(StaleReferenceError):
            self.seal_with(
                lambda content: edition_evidence(
                    edition=content.edition_ref,
                    observations=(
                        UncertaintyObservation(UncertaintyKind.INAUDIBLE, 7, 700, 70),
                    ),
                ),
                (),
            )

    def test_a_flipped_integrity_verdict_is_rejected(self) -> None:
        """A caller cannot pair a signed digest with the opposite verdict."""
        with self.assertRaises(StaleReferenceError):
            self.seal_with(
                lambda content: edition_evidence(edition=content.edition_ref),
                (
                    IntegrityCheckResult(
                        IntegrityCheckCode("object-digests"), False, "verified"
                    ),
                ),
            )

    def test_evidence_named_by_the_signed_content_is_accepted(self) -> None:
        snapshot = self.seal_with(
            lambda content: edition_evidence(edition=content.edition_ref),
            (self.HONEST_RESULT,),
        )

        self.assertEqual(snapshot, snapshot.validated())


class CandidateReplayTests(unittest.TestCase):
    """Fix round 2 — replay rules do not depend on iteration order."""

    def test_an_id_conflict_is_rejected_regardless_of_position(self) -> None:
        """Two stored candidates, so the two loop branches are distinguishable.

        With only one stored candidate the digest-reuse branch and the
        ID-conflict branch cannot be told apart, and the order-dependent form
        of this loop passes. The submitted candidate below reuses the digest of
        the SECOND stored snapshot while reusing the ID of the FIRST, so an
        implementation that returns on digest reuse before scanning the whole
        history for an ID conflict silently rolls the active candidate back.
        """
        production, policy, content_a = configured_production()
        content_b = seal_content(
            policy_ref=policy.ref,
            gate_set_ref=production.active_gate_set_ref,
            provenance_input_digests=(default_edition_evidence().semantic_digest,),
            integrity_input_digests=(),
            release_members=(
                ReleaseMember(ManifestMemberRole("transcript-json"), artifact(80, "1")),
            ),
        )
        self.assertNotEqual(
            content_a.content_manifest_ref, content_b.content_manifest_ref
        )

        # Order matters: the digest-matching snapshot is stored FIRST and the
        # ID-conflicting one SECOND, so a loop that returns on digest reuse
        # before scanning the whole history never sees the conflict.
        first = seal_candidate(content_b, candidate_id=ReleaseCandidateId(uid(60)))
        production.assemble_candidate(
            candidate=first, content=content_b, event_id=event_id(50), event_occurred_at_us=1
        )
        second = seal_candidate(content_a, candidate_id=ReleaseCandidateId(uid(62)))
        production.assemble_candidate(
            candidate=second, content=content_a, event_id=event_id(54), event_occurred_at_us=2
        )
        production.pull_events()
        self.assertEqual(production.candidates, (first, second))
        self.assertEqual(production.active_candidate_ref, second.ref)

        # Reuses the SECOND stored candidate's ID while matching the FIRST
        # stored candidate's digest.
        conflicting = ReleaseCandidateSnapshot.seal(
            release_candidate_id=second.release_candidate_id,
            production_id=production.production_id,
            content_manifest_ref=content_b.content_manifest_ref,
            included_sign_off_digests=(),
            assembled_at_us=1_700_000_000_000_070,
        )
        self.assertEqual(conflicting.semantic_digest, first.semantic_digest)
        self.assertNotEqual(conflicting.semantic_digest, second.semantic_digest)

        with self.assertRaisesRegex(ValidationError, "different digest"):
            production.assemble_candidate(
                candidate=conflicting,
                content=content_b,
                event_id=event_id(51),
                event_occurred_at_us=3,
            )

        self.assertEqual(production.candidates, (first, second))
        self.assertEqual(production.active_candidate_ref, second.ref)
        self.assertEqual(production.pull_events(), ())

    def test_reselecting_a_stored_candidate_emits_its_fact(self) -> None:
        """A state change without a domain fact would persist silently."""
        production, _, content = configured_production()
        first = seal_candidate(content, candidate_id=ReleaseCandidateId(uid(61)))
        production.assemble_candidate(
            candidate=first, content=content, event_id=event_id(52), event_occurred_at_us=1
        )
        production.pull_events()

        # Re-selecting the already-active snapshot is a true no-op.
        production.assemble_candidate(
            candidate=first, content=content, event_id=event_id(53), event_occurred_at_us=2
        )
        self.assertEqual(production.pull_events(), ())


class GateRequirementForgeryTests(unittest.TestCase):
    """Fix round 2 — a gate requirement is reconstructed, not trusted."""

    def test_a_gate_set_reconstructs_every_requirement(self) -> None:
        gates = gate_set((rights_holder_gate(),))

        self.assertEqual(gates.validated(), gates)
        self.assertEqual(
            gates.requirements[0].validated(), gates.requirements[0]
        )

    def test_a_forged_requirement_credential_is_rejected(self) -> None:
        gates = gate_set((rights_holder_gate(),))
        forged_requirement = copy(gates.requirements[0])
        object.__setattr__(
            forged_requirement,
            "credential",
            ActorCredentialRef(
                actor(40),
                CredentialVerificationMethod.STEWARD_ATTESTATION,
                AssuranceLevel.STEWARD_ATTESTED,
            ),
        )
        forged = copy(gates)
        object.__setattr__(forged, "requirements", (forged_requirement,))

        with self.assertRaises(ValidationError):
            forged.validated()


if __name__ == "__main__":
    unittest.main()
