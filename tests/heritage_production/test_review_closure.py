from __future__ import annotations

from dataclasses import replace
import unittest

try:
    from heritage_production.domain.review import (
        AssignmentCoverage,
        ClientSubmissionNonce,
        ClosedReviewEvidence,
        FindingCategoryCode,
        FindingDecision,
        FindingDisposition,
        FindingSeverityCode,
        ImportedFindingRef,
        ReviewCharacterSpan,
        ReviewClosureSnapshot,
        ReviewCompleteness,
        ReviewCoverage,
        ReviewSubmissionSummary,
        ReviewTargetOutcome,
        TargetOutcomeKind,
        ReviewRoundState,
    )
except ImportError:
    ReviewClosureSnapshot = None  # type: ignore[assignment,misc]

from heritage_production.domain.shared import (
    ActorId,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    DomainEventId,
    OperationId,
    ReviewPackageId,
    ReviewPackageRef,
    ReviewEvidenceRef,
    SegmentId,
    SegmentRevisionId,
    SegmentRevisionRef,
    ValidationError,
    semantic_digest,
)
from tests.heritage_production.test_review_submissions import (
    assigned_round,
    reconstitute_open,
    summary_for_finding,
)
from tests.heritage_production.test_review_findings import submit_finding
from tests.heritage_production.test_review_rounds import uid


def forge_closed_evidence(
    evidence: ClosedReviewEvidence, **changes: object
) -> ClosedReviewEvidence:
    forged = object.__new__(ClosedReviewEvidence)
    for field_name in ClosedReviewEvidence.__dataclass_fields__:
        object.__setattr__(
            forged,
            field_name,
            changes.get(field_name, getattr(evidence, field_name)),
        )
    return forged


class ReviewClosureTests(unittest.TestCase):
    def test_closed_graph_rejects_valid_root_authored_by_unassigned_actor(self) -> None:
        round_, assignment, assurance = assigned_round()
        finding = submit_finding(round_, author_actor_id=ActorId(uid(59)))
        finding.pull_events()
        disposition_digest = semantic_digest(
            "heritage-finding-disposition-v1",
            {
                "review_finding_id": finding.review_finding_id.value,
                "finding_payload_digest": {
                    "algorithm": finding.finding_payload_digest.algorithm,
                    "hex_digest": finding.finding_payload_digest.hex_digest,
                },
                "decision": FindingDecision.ACCEPTED.value,
                "rationale": None,
                "steward_actor_id": ActorId(uid(60)).value,
                "decided_at_us": 50,
            },
        )
        finding.record_disposition(
            context=round_.open_context(),
            decision=FindingDecision.ACCEPTED,
            rationale=None,
            steward_actor_id=ActorId(uid(60)),
            decided_at_us=50,
            disposition_digest=disposition_digest,
            event_id=DomainEventId(uid(61)),
            event_occurred_at_us=51,
        )
        finding.pull_events()
        summary = summary_for_finding(
            round_,
            assignment,
            assurance,
            finding,
            submission_nonce="persisted-wrong-author",
            package_suffix=62,
            predecessor=None,
        )
        restored = reconstitute_open(round_, submissions=(summary,))
        with self.assertRaises(ValidationError):
            restored.close(
                closure_snapshot=ReviewClosureSnapshot((finding,), ()),
                closed_by=ActorId(uid(65)),
                closed_at_us=100,
                event_id=DomainEventId(uid(66)),
                event_occurred_at_us=101,
            )
        self.assertIs(restored.state, ReviewRoundState.OPEN)
        self.assertEqual(restored.pull_events(), ())

    def test_reconstitution_rejects_impossible_open_and_closed_shapes(self) -> None:
        round_, _, _ = assigned_round()
        open_values = {
            "review_round_id": round_.review_round_id,
            "production_id": round_.production_id,
            "edition_ref": round_.edition_ref,
            "target_manifest": round_.target_manifest,
            "rubric_ref": round_.rubric_ref,
            "package_schema_version": round_.package_schema_version,
            "reviewer_assignments": round_.reviewer_assignments,
            "sign_off_requirements": round_.sign_off_requirements,
            "opened_by": round_.opened_by,
            "opened_at_us": round_.opened_at_us,
            "state": ReviewRoundState.OPEN,
            "submissions": (),
            "sign_offs": (),
            "closure_snapshot": None,
            "closed_evidence": None,
            "closed_by": None,
            "closed_at_us": None,
        }
        self.assertEqual(type(round_).reconstitute(**open_values).pull_events(), ())
        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot((), ()),
            closed_by=ActorId(uid(61)),
            closed_at_us=100,
            event_id=DomainEventId(uid(62)),
            event_occurred_at_us=101,
        )
        round_.pull_events()
        closed_values = open_values | {
            "state": ReviewRoundState.CLOSED,
            "closure_snapshot": ReviewClosureSnapshot((), ()),
            "closed_evidence": evidence,
            "closed_by": round_.closed_by,
            "closed_at_us": round_.closed_at_us,
        }
        for name, changes in (
            (
                "open-with-closure",
                {
                    "state": ReviewRoundState.OPEN,
                    "closure_snapshot": ReviewClosureSnapshot((), ()),
                },
            ),
            ("closed-without-roots", {"closure_snapshot": None}),
            ("closed-without-evidence", {"closed_evidence": None}),
            ("closed-without-actor", {"closed_by": None}),
            ("closed-without-time", {"closed_at_us": None}),
        ):
            base = closed_values if name != "open-with-closure" else open_values
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    type(round_).reconstitute(**(base | changes))

    def test_exported_frozen_evidence_requires_contextual_factories(self) -> None:
        round_, _, _ = assigned_round()
        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot((), ()),
            closed_by=ActorId(uid(65)),
            closed_at_us=100,
            event_id=DomainEventId(uid(66)),
            event_occurred_at_us=101,
        )
        round_.pull_events()

        assignment_coverage = evidence.coverage.assignments[0]
        with self.assertRaises(TypeError):
            AssignmentCoverage(
                assignment_coverage.actor_id,
                assignment_coverage.role,
                assignment_coverage.active_submission_id,
                assignment_coverage.active_submission_digest,
                assignment_coverage.reviewed_target_keys,
                assignment_coverage.unreviewed_target_keys,
            )
        with self.assertRaises(TypeError):
            ReviewCoverage(
                evidence.coverage.assignments,
                evidence.coverage.reviewed_target_union,
                evidence.coverage.unreviewed_target_union,
                evidence.coverage.target_count,
                evidence.coverage.reviewed_target_count,
            )
        with self.assertRaises(TypeError):
            ClosedReviewEvidence(
                evidence.evidence_ref,
                evidence.edition_ref,
                evidence.target_manifest_ref,
                evidence.coverage,
                evidence.submission_summaries,
                evidence.findings,
                evidence.sign_offs,
            )

        coverage_values = {
            "target_manifest": round_.target_manifest,
            "reviewer_assignments": round_.reviewer_assignments,
            "submission_summaries": evidence.submission_summaries,
            "assignments": evidence.coverage.assignments,
            "reviewed_target_union": evidence.coverage.reviewed_target_union,
            "unreviewed_target_union": evidence.coverage.unreviewed_target_union,
            "target_count": evidence.coverage.target_count,
            "reviewed_target_count": evidence.coverage.reviewed_target_count,
        }
        self.assertEqual(
            ReviewCoverage.reconstitute(**coverage_values), evidence.coverage
        )
        for name, changes in (
            ("mutable-assignments", {"assignments": list(evidence.coverage.assignments)}),
            ("fabricated-count", {"reviewed_target_count": 1}),
            ("fabricated-union", {
                "reviewed_target_union": (
                    round_.target_manifest.members[0].target_key,
                )
            }),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    ReviewCoverage.reconstitute(**(coverage_values | changes))

        evidence_values = {
            "target_manifest": round_.target_manifest,
            "reviewer_assignments": round_.reviewer_assignments,
            "evidence_ref": evidence.evidence_ref,
            "edition_ref": evidence.edition_ref,
            "target_manifest_ref": evidence.target_manifest_ref,
            "coverage": evidence.coverage,
            "submission_summaries": evidence.submission_summaries,
            "findings": evidence.findings,
            "sign_offs": evidence.sign_offs,
        }
        self.assertEqual(
            ClosedReviewEvidence.reconstitute(**evidence_values), evidence
        )
        foreign_edition = type(evidence.edition_ref)(
            evidence.edition_ref.transcript_edition_id,
            ContentDigest("sha256", "8" * 64),
        )
        foreign_target = type(evidence.target_manifest_ref)(
            evidence.target_manifest_ref.review_round_id,
            ContentDigest("sha256", "9" * 64),
            evidence.target_manifest_ref.artifact,
        )
        for name, changes in (
            ("foreign-edition", {"edition_ref": foreign_edition}),
            ("foreign-target", {"target_manifest_ref": foreign_target}),
            (
                "fabricated-coverage",
                {
                    "coverage": object.__new__(ReviewCoverage),
                },
            ),
        ):
            if name == "fabricated-coverage":
                forged_coverage = changes["coverage"]
                for field, value in (
                    ("assignments", evidence.coverage.assignments),
                    ("reviewed_target_union", evidence.coverage.reviewed_target_union),
                    (
                        "unreviewed_target_union",
                        evidence.coverage.unreviewed_target_union,
                    ),
                    ("target_count", evidence.coverage.target_count),
                    ("reviewed_target_count", 1),
                ):
                    object.__setattr__(forged_coverage, field, value)
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    ClosedReviewEvidence.reconstitute(**(evidence_values | changes))

    def test_close_revalidates_nonprojected_finding_root_body(self) -> None:
        round_, assignment, assurance = assigned_round()
        finding = submit_finding(round_, author_actor_id=assignment.actor_id)
        finding.pull_events()
        finding.record_disposition(
            context=round_.open_context(),
            decision=FindingDecision.ACCEPTED,
            rationale=None,
            steward_actor_id=ActorId(uid(40)),
            decided_at_us=50,
            disposition_digest=semantic_digest(
                "heritage-finding-disposition-v1",
                {
                    "review_finding_id": finding.review_finding_id.value,
                    "finding_payload_digest": {
                        "algorithm": finding.finding_payload_digest.algorithm,
                        "hex_digest": finding.finding_payload_digest.hex_digest,
                    },
                    "decision": FindingDecision.ACCEPTED.value,
                    "rationale": None,
                    "steward_actor_id": ActorId(uid(40)).value,
                    "decided_at_us": 50,
                },
            ),
            event_id=DomainEventId(uid(74)),
            event_occurred_at_us=51,
        )
        finding.pull_events()
        summary = summary_for_finding(
            round_,
            assignment,
            assurance,
            finding,
            submission_nonce="closure-root-validation",
            package_suffix=75,
            predecessor=None,
        )
        round_.finalize_submission(
            summary=summary,
            findings=(finding,),
            event_id=DomainEventId(uid(78)),
            event_occurred_at_us=52,
        )
        round_.pull_events()

        def clone_finding():
            return type(finding).reconstitute(
                target_manifest=round_.target_manifest,
                disposition=finding.disposition,
                review_finding_id=finding.review_finding_id,
                review_round_id=finding.review_round_id,
                review_submission_id=finding.review_submission_id,
                client_finding_nonce=finding.client_finding_nonce,
                edition_ref=finding.edition_ref,
                rubric_ref=finding.rubric_ref,
                target_key=finding.target_key,
                segment_revision_ref=finding.segment_revision_ref,
                character_span=finding.character_span,
                source_subspan=finding.source_subspan,
                category_code=finding.category_code,
                severity_code=finding.severity_code,
                observation=finding.observation,
                proposed_change=finding.proposed_change,
                author_actor_id=finding.author_actor_id,
                finding_payload_digest=finding.finding_payload_digest,
            )

        for name, attribute, replacement in (
            ("observation", "observation", "Forged observation"),
            ("author", "author_actor_id", ActorId(uid(79))),
            ("span", "character_span", ReviewCharacterSpan(0, 1)),
        ):
            forged = clone_finding()
            object.__setattr__(forged, attribute, replacement)
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    round_.close(
                        closure_snapshot=ReviewClosureSnapshot((forged,), ()),
                        closed_by=ActorId(uid(80)),
                        closed_at_us=100,
                        event_id=DomainEventId(uid(81)),
                        event_occurred_at_us=101,
                    )
                self.assertIs(round_.state, ReviewRoundState.OPEN)
                self.assertEqual(round_.pull_events(), ())

    def test_closed_reconstitution_rederives_projection_from_exact_roots(self) -> None:
        round_, assignment, assurance = assigned_round()
        finding = submit_finding(round_, author_actor_id=assignment.actor_id)
        finding.pull_events()
        accepted_digest = semantic_digest(
            "heritage-finding-disposition-v1",
            {
                "review_finding_id": finding.review_finding_id.value,
                "finding_payload_digest": {
                    "algorithm": finding.finding_payload_digest.algorithm,
                    "hex_digest": finding.finding_payload_digest.hex_digest,
                },
                "decision": FindingDecision.ACCEPTED.value,
                "rationale": None,
                "steward_actor_id": ActorId(uid(40)).value,
                "decided_at_us": 50,
            },
        )
        finding.record_disposition(
            context=round_.open_context(),
            decision=FindingDecision.ACCEPTED,
            rationale=None,
            steward_actor_id=ActorId(uid(40)),
            decided_at_us=50,
            disposition_digest=accepted_digest,
            event_id=DomainEventId(uid(90)),
            event_occurred_at_us=51,
        )
        finding.pull_events()
        summary = summary_for_finding(
            round_,
            assignment,
            assurance,
            finding,
            submission_nonce="root-derived-evidence",
            package_suffix=91,
            predecessor=None,
        )
        round_.finalize_submission(
            summary=summary,
            findings=(finding,),
            event_id=DomainEventId(uid(94)),
            event_occurred_at_us=52,
        )
        round_.pull_events()
        closure_snapshot = ReviewClosureSnapshot((finding,), ())
        evidence = round_.close(
            closure_snapshot=closure_snapshot,
            closed_by=ActorId(uid(95)),
            closed_at_us=100,
            event_id=DomainEventId(uid(96)),
            event_occurred_at_us=101,
        )
        round_.pull_events()
        values = {
            "review_round_id": round_.review_round_id,
            "production_id": round_.production_id,
            "edition_ref": round_.edition_ref,
            "target_manifest": round_.target_manifest,
            "rubric_ref": round_.rubric_ref,
            "package_schema_version": round_.package_schema_version,
            "reviewer_assignments": round_.reviewer_assignments,
            "sign_off_requirements": round_.sign_off_requirements,
            "opened_by": round_.opened_by,
            "opened_at_us": round_.opened_at_us,
            "state": round_.state,
            "submissions": round_.submissions,
            "sign_offs": round_.sign_offs,
            "closure_snapshot": closure_snapshot,
            "closed_evidence": evidence,
            "closed_by": round_.closed_by,
            "closed_at_us": round_.closed_at_us,
        }

        projection = evidence.findings[0]
        stale_projection_tampers = (
            replace(projection, category_code=FindingCategoryCode("forged")),
            replace(projection, severity_code=FindingSeverityCode("forged")),
            replace(
                projection,
                segment_revision_ref=SegmentRevisionRef(
                    SegmentId(uid(97)),
                    SegmentRevisionId(uid(98)),
                    ContentDigest("sha256", "7" * 64),
                ),
            ),
        )
        for index, tampered in enumerate(stale_projection_tampers):
            with self.subTest(projection=index):
                with self.assertRaises(ValidationError):
                    type(round_).reconstitute(
                        **(
                            values
                            | {
                                "closed_evidence": forge_closed_evidence(
                                    evidence, findings=(tampered,)
                                )
                            }
                        )
                    )
        with self.assertRaises(ValidationError):
            replace(
                projection.disposition,
                decision=FindingDecision.REJECTED,
                rationale="Forged rejection",
            )
        with self.assertRaises(ValidationError):
            replace(
                projection.disposition,
                disposition_digest=ContentDigest("sha256", "8" * 64),
            )

        rejected_digest = semantic_digest(
            "heritage-finding-disposition-v1",
            {
                "review_finding_id": finding.review_finding_id.value,
                "finding_payload_digest": {
                    "algorithm": finding.finding_payload_digest.algorithm,
                    "hex_digest": finding.finding_payload_digest.hex_digest,
                },
                "decision": FindingDecision.REJECTED.value,
                "rationale": "Self-consistent forgery",
                "steward_actor_id": ActorId(uid(99)).value,
                "decided_at_us": 60,
            },
        )
        alternative_disposition = FindingDisposition(
            finding.review_finding_id,
            finding.finding_payload_digest,
            FindingDecision.REJECTED,
            "Self-consistent forgery",
            ActorId(uid(99)),
            60,
            rejected_digest,
        )
        forged_projection = replace(
            projection, disposition=alternative_disposition
        )
        self_consistent = ClosedReviewEvidence.seal(
            target_manifest=round_.target_manifest,
            reviewer_assignments=round_.reviewer_assignments,
            coverage=evidence.coverage,
            submission_summaries=evidence.submission_summaries,
            findings=(forged_projection,),
            sign_offs=evidence.sign_offs,
        )
        self.assertNotEqual(self_consistent.evidence_ref, evidence.evidence_ref)
        with self.assertRaises(ValidationError):
            type(round_).reconstitute(
                **(values | {"closed_evidence": self_consistent})
            )

    def test_close_without_submissions_freezes_explicit_zero_coverage_literal_digest(self) -> None:
        self.assertIsNotNone(
            ReviewClosureSnapshot,
            "round closure requires a typed repository evidence snapshot",
        )
        round_, assignment, _ = assigned_round()
        context = round_.open_context()

        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot((), ()),
            closed_by=ActorId(uid(80)),
            closed_at_us=100,
            event_id=DomainEventId(uid(81)),
            event_occurred_at_us=101,
        )

        self.assertIs(round_.state, ReviewRoundState.CLOSED)
        self.assertEqual(
            evidence.evidence_ref.evidence_digest.hex_digest,
            "0a3616c788b85dd4f611875a8b43900ec130b5316248dd73cc2fbfda8a2d827d",
        )
        assignment_coverage = evidence.coverage.assignments[0]
        self.assertEqual(assignment_coverage.actor_id, assignment.actor_id)
        self.assertEqual(assignment_coverage.reviewed_target_keys, ())
        self.assertEqual(
            assignment_coverage.unreviewed_target_keys,
            (round_.target_manifest.members[0].target_key,),
        )
        self.assertEqual(evidence.edition_ref, round_.edition_ref)
        self.assertEqual(evidence.target_manifest_ref, round_.target_manifest.ref)
        self.assertEqual(evidence.findings, ())
        self.assertEqual(evidence.sign_offs, ())
        self.assertEqual(round_.pull_events()[0].event_type, "ReviewRoundClosed")

        with self.assertRaises(ValidationError):
            context._require_open()
        with self.assertRaises(ValidationError):
            round_.close(
                closure_snapshot=ReviewClosureSnapshot((), ()),
                closed_by=ActorId(uid(80)),
                closed_at_us=102,
                event_id=DomainEventId(uid(82)),
                event_occurred_at_us=103,
            )
        self.assertEqual(round_.pull_events(), ())

    def test_close_requires_complete_disposed_finding_evidence_and_exposes_policy_facts(self) -> None:
        round_, assignment, assurance = assigned_round()
        finding = submit_finding(round_, author_actor_id=assignment.actor_id)
        finding.pull_events()
        ref = ImportedFindingRef(
            finding.client_finding_nonce,
            finding.review_finding_id,
            finding.finding_payload_digest,
            finding.target_key,
            finding.review_submission_id,
        )
        target = round_.target_manifest
        summary = ReviewSubmissionSummary.seal(
            review_submission_id=finding.review_submission_id,
            client_submission_nonce=ClientSubmissionNonce("submission-with-finding"),
            review_package_ref=ReviewPackageRef(
                ReviewPackageId(uid(84)),
                ContentDigest("sha256", "a" * 64),
                ArtifactRef(ArtifactId(uid(85)), ContentDigest("sha256", "b" * 64), 10, "application/zip"),
            ),
            review_round_id=round_.review_round_id,
            production_id=round_.production_id,
            edition_ref=round_.edition_ref,
            rubric_ref=round_.rubric_ref,
            target_manifest_ref=target.ref,
            submission_schema_version=1,
            predecessor_submission_digest=None,
            assigned_actor_id=assignment.actor_id,
            role=assignment.role,
            assurance=assurance,
            completeness=ReviewCompleteness.COMPLETE,
            outcomes=(ReviewTargetOutcome(finding.target_key, TargetOutcomeKind.FINDINGS, (ref,)),),
            unreviewed_target_keys=(),
            raw_result_artifact=ArtifactRef(
                ArtifactId(uid(86)), ContentDigest("sha256", "c" * 64), 10, "application/zip"
            ),
            completed_nonce_map_digest=ContentDigest("sha256", "d" * 64),
            imported_at_us=4,
            target_manifest=target,
        )
        round_.finalize_submission(
            summary=summary,
            findings=(finding,),
            event_id=DomainEventId(uid(87)),
            event_occurred_at_us=5,
        )
        round_.pull_events()

        with self.assertRaises(ValidationError):
            round_.close(
                closure_snapshot=ReviewClosureSnapshot((finding,), ()),
                closed_by=ActorId(uid(80)),
                closed_at_us=100,
                event_id=DomainEventId(uid(88)),
                event_occurred_at_us=101,
            )
        self.assertIs(round_.state, ReviewRoundState.OPEN)
        self.assertEqual(round_.pull_events(), ())

        finding.record_disposition(
            context=round_.open_context(),
            decision=FindingDecision.ACCEPTED,
            rationale="Apply correction",
            steward_actor_id=ActorId(uid(40)),
            decided_at_us=50,
            disposition_digest=semantic_digest(
                "heritage-finding-disposition-v1",
                {
                    "review_finding_id": finding.review_finding_id.value,
                    "finding_payload_digest": {
                        "algorithm": finding.finding_payload_digest.algorithm,
                        "hex_digest": finding.finding_payload_digest.hex_digest,
                    },
                    "decision": FindingDecision.ACCEPTED.value,
                    "rationale": "Apply correction",
                    "steward_actor_id": ActorId(uid(40)).value,
                    "decided_at_us": 50,
                },
            ),
            event_id=DomainEventId(uid(89)),
            event_occurred_at_us=51,
        )
        finding.pull_events()
        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot((finding,), ()),
            closed_by=ActorId(uid(80)),
            closed_at_us=100,
            event_id=DomainEventId(uid(88)),
            event_occurred_at_us=101,
        )
        exposed = evidence.findings[0]
        self.assertEqual(
            evidence.evidence_ref.evidence_digest.hex_digest,
            "dced8d1b52abb06cc943e1ad7931008dc9953162f83096f4af2d82c73a58282c",
        )
        self.assertEqual(exposed.category_code.value, "accuracy")
        self.assertEqual(exposed.severity_code.value, "major")
        self.assertIs(exposed.disposition.decision, FindingDecision.ACCEPTED)
        self.assertFalse(hasattr(exposed, "client_finding_nonce"))
        self.assertEqual(
            evidence.coverage.assignments[0].reviewed_target_keys,
            (finding.target_key,),
        )

        with self.assertRaises(ValidationError):
            submit_finding(round_)

    def test_close_rejects_incomplete_import_without_mutation(self) -> None:
        round_, _, _ = assigned_round()
        before = (round_.state, round_.coverage, round_.evidence_ref)
        with self.assertRaises(ValidationError):
            round_.close(
                closure_snapshot=ReviewClosureSnapshot(
                    (), (OperationId(uid(83)),)
                ),
                closed_by=ActorId(uid(80)),
                closed_at_us=100,
                event_id=DomainEventId(uid(81)),
                event_occurred_at_us=101,
            )
        self.assertEqual((round_.state, round_.coverage, round_.evidence_ref), before)
        self.assertEqual(round_.pull_events(), ())

    def test_closed_round_reconstitution_is_event_free_and_rejects_evidence_tamper(self) -> None:
        self.assertTrue(
            hasattr(type(assigned_round()[0]), "reconstitute"),
            "stored ReviewRound state requires validating reconstitution",
        )
        round_, _, _ = assigned_round()
        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot((), ()),
            closed_by=ActorId(uid(80)),
            closed_at_us=100,
            event_id=DomainEventId(uid(81)),
            event_occurred_at_us=101,
        )
        round_.pull_events()
        values = {
            "review_round_id": round_.review_round_id,
            "production_id": round_.production_id,
            "edition_ref": round_.edition_ref,
            "target_manifest": round_.target_manifest,
            "rubric_ref": round_.rubric_ref,
            "package_schema_version": round_.package_schema_version,
            "reviewer_assignments": round_.reviewer_assignments,
            "sign_off_requirements": round_.sign_off_requirements,
            "opened_by": round_.opened_by,
            "opened_at_us": round_.opened_at_us,
            "state": round_.state,
            "submissions": round_.submissions,
            "sign_offs": round_.sign_offs,
            "closure_snapshot": ReviewClosureSnapshot((), ()),
            "closed_evidence": evidence,
            "closed_by": round_.closed_by,
            "closed_at_us": round_.closed_at_us,
        }
        restored = type(round_).reconstitute(**values)
        self.assertEqual(restored.closed_evidence, evidence)
        self.assertEqual(restored.pull_events(), ())

        forged = object.__new__(ClosedReviewEvidence)
        for field_name in ClosedReviewEvidence.__dataclass_fields__:
            object.__setattr__(
                forged,
                field_name,
                ReviewEvidenceRef(
                    round_.review_round_id, ContentDigest("sha256", "9" * 64)
                )
                if field_name == "evidence_ref"
                else getattr(evidence, field_name),
            )
        with self.assertRaises(ValidationError):
            type(round_).reconstitute(**(values | {"closed_evidence": forged}))


if __name__ == "__main__":
    unittest.main()
