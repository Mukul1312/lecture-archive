from __future__ import annotations

from dataclasses import replace
import unittest

try:
    from heritage_production.domain.review import (
        ClientSubmissionNonce,
        FindingDecision,
        ImportedFindingRef,
        ReviewClosureSnapshot,
        ReviewCompleteness,
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
    ValidationError,
)
from tests.heritage_production.test_review_submissions import assigned_round
from tests.heritage_production.test_review_findings import submit_finding
from tests.heritage_production.test_review_rounds import uid


class ReviewClosureTests(unittest.TestCase):
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
        finding = submit_finding(round_)
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
                closure_snapshot=ReviewClosureSnapshot((finding.evidence,), ()),
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
            disposition_digest=ContentDigest(
                "sha256",
                "7af70c5b45779f7a472bf2ffe352ecb0698f652d9c54525a77547d4227053696",
            ),
            event_id=DomainEventId(uid(89)),
            event_occurred_at_us=51,
        )
        finding.pull_events()
        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot((finding.evidence,), ()),
            closed_by=ActorId(uid(80)),
            closed_at_us=100,
            event_id=DomainEventId(uid(88)),
            event_occurred_at_us=101,
        )
        exposed = evidence.findings[0]
        self.assertEqual(exposed.category_code.value, "accuracy")
        self.assertEqual(exposed.severity_code.value, "major")
        self.assertIs(exposed.disposition.decision, FindingDecision.ACCEPTED)
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
            "closed_evidence": evidence,
            "closed_by": round_.closed_by,
            "closed_at_us": round_.closed_at_us,
        }
        restored = type(round_).reconstitute(**values)
        self.assertEqual(restored.closed_evidence, evidence)
        self.assertEqual(restored.pull_events(), ())

        forged = replace(
            evidence,
            evidence_ref=ReviewEvidenceRef(
                round_.review_round_id, ContentDigest("sha256", "9" * 64)
            ),
        )
        with self.assertRaises(ValidationError):
            type(round_).reconstitute(**(values | {"closed_evidence": forged}))


if __name__ == "__main__":
    unittest.main()
