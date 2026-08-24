from __future__ import annotations

import unittest

try:
    from heritage_production.domain.review import (
        ClientFindingNonce,
        ClientSubmissionNonce,
        ImportedFindingRef,
        ReviewerAssignment,
        ReviewCompleteness,
        ReviewRound,
        ReviewSubmissionSummary,
        ReviewTargetOutcome,
        TargetOutcomeKind,
        ReviewTargetKey,
        ReviewTargetManifest,
        ReviewTargetMember,
        review_submission_context_digest,
    )
except ImportError:
    ClientSubmissionNonce = None  # type: ignore[assignment,misc]
    ReviewCompleteness = None  # type: ignore[assignment,misc]
    ReviewSubmissionSummary = None  # type: ignore[assignment,misc]
    ReviewTargetOutcome = None  # type: ignore[assignment,misc]
    TargetOutcomeKind = None  # type: ignore[assignment,misc]

from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
    ActorCredentialRef,
    ActorId,
    ArtifactId,
    ArtifactRef,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    DomainEventId,
    ProductionId,
    ReviewFindingId,
    ReviewPackageId,
    ReviewPackageRef,
    ReviewSubmissionId,
    RoleCode,
    SignatureProof,
    SegmentId,
    SegmentRevisionId,
    SegmentRevisionRef,
    SourceSpan,
    TranscriptText,
    ValidationError,
)
from tests.heritage_production.test_review_rounds import make_target, uid
from tests.heritage_production.test_review_findings import submit_finding


def artifact(suffix: int, character: str, media_type: str = "application/octet-stream") -> ArtifactRef:
    return ArtifactRef(
        ArtifactId(uid(suffix)), ContentDigest("sha256", character * 64), 64, media_type
    )


def assigned_round() -> tuple[ReviewRound, ReviewerAssignment, ActorAssuranceEvidence]:
    target = make_target()
    credential = ActorCredentialRef(
        ActorId(uid(10)),
        CredentialVerificationMethod.STEWARD_ATTESTATION,
        AssuranceLevel.STEWARD_ATTESTED,
    )
    assignment = ReviewerAssignment(
        credential,
        RoleCode("language-reviewer"),
        AssuranceLevel.STEWARD_ATTESTED,
    )
    round_ = ReviewRound.open(
        review_round_id=target.review_round_id,
        production_id=target.production_id,
        edition_ref=target.edition_ref,
        target_manifest=target,
        rubric_ref=target.rubric_ref,
        package_schema_version=1,
        reviewer_assignments=(assignment,),
        sign_off_requirements=(),
        opened_by=ActorId(uid(11)),
        opened_at_us=1,
        event_id=DomainEventId(uid(12)),
        event_occurred_at_us=2,
    )
    round_.pull_events()
    assurance = ActorAssuranceEvidence.steward_attested(
        credential=credential,
        attesting_steward_id=ActorId(uid(13)),
        reason="Known reviewer",
        attested_at_us=3,
    )
    return round_, assignment, assurance


def zero_finding_summary(
    round_: ReviewRound,
    assignment: ReviewerAssignment,
    assurance: ActorAssuranceEvidence,
) -> ReviewSubmissionSummary:
    target = round_.target_manifest
    return ReviewSubmissionSummary.reconstitute(
        review_submission_id=ReviewSubmissionId(uid(51)),
        client_submission_nonce=ClientSubmissionNonce("submission-1"),
        review_package_ref=ReviewPackageRef(
            ReviewPackageId(uid(50)),
            ContentDigest("sha256", "a" * 64),
            artifact(52, "b", "application/zip"),
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
        outcomes=(
            ReviewTargetOutcome(
                target.members[0].target_key,
                TargetOutcomeKind.NO_ISSUE,
                (),
            ),
        ),
        unreviewed_target_keys=(),
        raw_result_artifact=artifact(53, "c", "application/zip"),
        completed_nonce_map_digest=ContentDigest("sha256", "d" * 64),
        imported_at_us=4,
        submission_digest=ContentDigest(
            "sha256",
            "c3f4a8e068d914ad128832837f8c472102141703cac55f12f21a4d0cb309c993",
        ),
        target_manifest=target,
    )


class ReviewSubmissionTests(unittest.TestCase):
    def test_verified_submission_signature_binds_payload_role_and_target_context(self) -> None:
        round_, assignment, attested = assigned_round()
        baseline = zero_finding_summary(round_, assignment, attested)
        fingerprint = ContentDigest("sha256", "e" * 64)
        credential = ActorCredentialRef(
            assignment.actor_id,
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            credential_fingerprint=fingerprint,
            public_key_artifact=artifact(48, "e"),
        )
        proof = SignatureProof("ed25519", fingerprint, artifact(49, "f"))

        def reconstitute(assurance: ActorAssuranceEvidence) -> ReviewSubmissionSummary:
            return ReviewSubmissionSummary.reconstitute(
                review_submission_id=baseline.review_submission_id,
                client_submission_nonce=baseline.client_submission_nonce,
                review_package_ref=baseline.review_package_ref,
                review_round_id=baseline.review_round_id,
                production_id=baseline.production_id,
                edition_ref=baseline.edition_ref,
                rubric_ref=baseline.rubric_ref,
                target_manifest_ref=baseline.target_manifest_ref,
                submission_schema_version=baseline.submission_schema_version,
                predecessor_submission_digest=baseline.predecessor_submission_digest,
                assigned_actor_id=baseline.assigned_actor_id,
                role=baseline.role,
                assurance=assurance,
                completeness=baseline.completeness,
                outcomes=baseline.outcomes,
                unreviewed_target_keys=baseline.unreviewed_target_keys,
                raw_result_artifact=baseline.raw_result_artifact,
                completed_nonce_map_digest=baseline.completed_nonce_map_digest,
                imported_at_us=baseline.imported_at_us,
                submission_digest=baseline.submission_digest,
                target_manifest=round_.target_manifest,
            )

        exact_context = review_submission_context_digest(
            actor_id=assignment.actor_id,
            role=assignment.role,
            target_ref=round_.target_manifest.ref,
            submission_digest=baseline.submission_digest,
            schema_version=baseline.submission_schema_version,
        )
        verified = ActorAssuranceEvidence.verified_signature(
            credential=credential,
            signed_context_digest=exact_context,
            proof=proof,
        )
        self.assertEqual(reconstitute(verified).assurance, verified)

        replay_context = review_submission_context_digest(
            actor_id=assignment.actor_id,
            role=RoleCode("different-role"),
            target_ref=round_.target_manifest.ref,
            submission_digest=baseline.submission_digest,
            schema_version=baseline.submission_schema_version,
        )
        replayed = ActorAssuranceEvidence.verified_signature(
            credential=credential,
            signed_context_digest=replay_context,
            proof=proof,
        )
        with self.assertRaises(ValidationError):
            reconstitute(replayed)

    def test_complete_zero_finding_submission_is_explicit_and_finalized(self) -> None:
        self.assertIsNotNone(
            ReviewSubmissionSummary,
            "review submission summaries must preserve zero-finding evidence",
        )
        round_, assignment, assurance = assigned_round()
        summary = zero_finding_summary(round_, assignment, assurance)
        self.assertEqual(
            summary.submission_digest.hex_digest,
            "c3f4a8e068d914ad128832837f8c472102141703cac55f12f21a4d0cb309c993",
        )

        finalized = round_.finalize_submission(
            summary=summary,
            findings=(),
            event_id=DomainEventId(uid(54)),
            event_occurred_at_us=5,
        )

        self.assertEqual(finalized, summary)
        self.assertEqual(round_.submissions, (summary,))
        self.assertEqual(summary.outcomes[0].kind, TargetOutcomeKind.NO_ISSUE)
        events = round_.pull_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ReviewSubmissionFinalized")

    def test_partial_partition_and_multiple_findings_per_target_are_explicit(self) -> None:
        self.assertTrue(
            hasattr(ReviewSubmissionSummary, "seal"),
            "canonical in-process summary creation must compute its semantic digest",
        )
        base_target = make_target()
        first = base_target.members[0]
        second = ReviewTargetMember(
            1,
            ReviewTargetKey("target-2"),
            SegmentRevisionRef(
                SegmentId(uid(90)), SegmentRevisionId(uid(91)), ContentDigest("sha256", "e" * 64)
            ),
            SourceSpan(first.source_span.source_version, 1_000, 2_000),
            TranscriptText("two"),
            first.allowed_category_codes,
            first.allowed_severity_codes,
        )
        target = ReviewTargetManifest.seal(
            review_round_id=base_target.review_round_id,
            production_id=base_target.production_id,
            edition_ref=base_target.edition_ref,
            rubric_ref=base_target.rubric_ref,
            members=(first, second),
            artifact=artifact(92, "f", "application/json"),
        )
        credential = ActorCredentialRef(
            ActorId(uid(10)),
            CredentialVerificationMethod.STEWARD_ATTESTATION,
            AssuranceLevel.STEWARD_ATTESTED,
        )
        assignment = ReviewerAssignment(
            credential, RoleCode("language-reviewer"), AssuranceLevel.STEWARD_ATTESTED
        )
        round_ = ReviewRound.open(
            review_round_id=target.review_round_id,
            production_id=target.production_id,
            edition_ref=target.edition_ref,
            target_manifest=target,
            rubric_ref=target.rubric_ref,
            package_schema_version=1,
            reviewer_assignments=(assignment,),
            sign_off_requirements=(),
            opened_by=ActorId(uid(11)),
            opened_at_us=1,
            event_id=DomainEventId(uid(12)),
            event_occurred_at_us=2,
        )
        round_.pull_events()
        assurance = ActorAssuranceEvidence.steward_attested(
            credential=credential,
            attesting_steward_id=ActorId(uid(13)),
            reason="Known reviewer",
            attested_at_us=3,
        )
        common = {
            "review_submission_id": ReviewSubmissionId(uid(93)),
            "client_submission_nonce": ClientSubmissionNonce("partial-1"),
            "review_package_ref": ReviewPackageRef(
                ReviewPackageId(uid(94)), ContentDigest("sha256", "a" * 64), artifact(95, "b", "application/zip")
            ),
            "review_round_id": round_.review_round_id,
            "production_id": round_.production_id,
            "edition_ref": round_.edition_ref,
            "rubric_ref": round_.rubric_ref,
            "target_manifest_ref": target.ref,
            "submission_schema_version": 1,
            "predecessor_submission_digest": None,
            "assigned_actor_id": assignment.actor_id,
            "role": assignment.role,
            "assurance": assurance,
            "raw_result_artifact": artifact(96, "c", "application/zip"),
            "completed_nonce_map_digest": ContentDigest("sha256", "d" * 64),
            "imported_at_us": 4,
            "target_manifest": target,
        }
        partial = ReviewSubmissionSummary.seal(
            completeness=ReviewCompleteness.PARTIAL,
            outcomes=(ReviewTargetOutcome(first.target_key, TargetOutcomeKind.NO_ISSUE, ()),),
            unreviewed_target_keys=(second.target_key,),
            **common,
        )
        round_.finalize_submission(
            summary=partial,
            findings=(),
            event_id=DomainEventId(uid(97)),
            event_occurred_at_us=5,
        )
        self.assertEqual(partial.unreviewed_target_keys, (second.target_key,))

        with self.assertRaises(ValidationError):
            ReviewSubmissionSummary.seal(
                completeness=ReviewCompleteness.COMPLETE,
                outcomes=partial.outcomes,
                unreviewed_target_keys=partial.unreviewed_target_keys,
                **common,
            )

        refs = tuple(
            ImportedFindingRef(
                ClientFindingNonce(f"finding-{index}"),
                ReviewFindingId(uid(100 + index)),
                ContentDigest("sha256", str(index + 1) * 64),
                first.target_key,
                common["review_submission_id"],
            )
            for index in range(2)
        )
        outcome = ReviewTargetOutcome(first.target_key, TargetOutcomeKind.FINDINGS, refs)
        self.assertEqual(outcome.finding_refs, refs)

    def test_finding_evidence_must_exactly_match_finalized_refs(self) -> None:
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
            client_submission_nonce=ClientSubmissionNonce("with-finding"),
            review_package_ref=ReviewPackageRef(
                ReviewPackageId(uid(110)), ContentDigest("sha256", "a" * 64), artifact(111, "b", "application/zip")
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
            raw_result_artifact=artifact(112, "c", "application/zip"),
            completed_nonce_map_digest=ContentDigest("sha256", "d" * 64),
            imported_at_us=4,
            target_manifest=target,
        )
        for findings in ((), (finding, finding)):
            with self.subTest(findings=findings):
                with self.assertRaises(ValidationError):
                    round_.finalize_submission(
                        summary=summary,
                        findings=findings,
                        event_id=DomainEventId(uid(113)),
                        event_occurred_at_us=5,
                    )
                self.assertEqual(round_.submissions, ())
                self.assertEqual(round_.pull_events(), ())

        round_.finalize_submission(
            summary=summary,
            findings=(finding,),
            event_id=DomainEventId(uid(114)),
            event_occurred_at_us=6,
        )
        self.assertEqual(round_.submissions, (summary,))

    def test_correction_chain_is_linear_and_identical_replay_is_idempotent(self) -> None:
        round_, assignment, assurance = assigned_round()
        first = zero_finding_summary(round_, assignment, assurance)
        round_.finalize_submission(
            summary=first,
            findings=(),
            event_id=DomainEventId(uid(120)),
            event_occurred_at_us=5,
        )
        round_.pull_events()
        target = round_.target_manifest

        def correction(
            suffix: int,
            predecessor: ContentDigest | None,
        ) -> ReviewSubmissionSummary:
            return ReviewSubmissionSummary.seal(
                review_submission_id=ReviewSubmissionId(uid(suffix)),
                client_submission_nonce=ClientSubmissionNonce(f"submission-{suffix}"),
                review_package_ref=ReviewPackageRef(
                    ReviewPackageId(uid(suffix + 1)),
                    ContentDigest("sha256", "e" * 64),
                    artifact(suffix + 2, "f", "application/zip"),
                ),
                review_round_id=round_.review_round_id,
                production_id=round_.production_id,
                edition_ref=round_.edition_ref,
                rubric_ref=round_.rubric_ref,
                target_manifest_ref=target.ref,
                submission_schema_version=1,
                predecessor_submission_digest=predecessor,
                assigned_actor_id=assignment.actor_id,
                role=assignment.role,
                assurance=assurance,
                completeness=ReviewCompleteness.COMPLETE,
                outcomes=(ReviewTargetOutcome(target.members[0].target_key, TargetOutcomeKind.NO_ISSUE, ()),),
                unreviewed_target_keys=(),
                raw_result_artifact=artifact(suffix + 3, "a", "application/zip"),
                completed_nonce_map_digest=ContentDigest("sha256", "b" * 64),
                imported_at_us=10 + suffix,
                target_manifest=target,
            )

        second = correction(121, first.submission_digest)
        round_.finalize_submission(
            summary=second,
            findings=(),
            event_id=DomainEventId(uid(125)),
            event_occurred_at_us=6,
        )
        round_.pull_events()
        replay = round_.finalize_submission(
            summary=second,
            findings=(),
            event_id=DomainEventId(uid(126)),
            event_occurred_at_us=7,
        )
        self.assertEqual(replay, second)
        self.assertEqual(round_.pull_events(), ())

        for predecessor in (None, first.submission_digest, ContentDigest("sha256", "9" * 64)):
            fork = correction(130 + (0 if predecessor is None else len(predecessor.hex_digest)), predecessor)
            with self.subTest(predecessor=predecessor):
                with self.assertRaises(ValidationError):
                    round_.finalize_submission(
                        summary=fork,
                        findings=(),
                        event_id=DomainEventId(uid(140)),
                        event_occurred_at_us=8,
                    )
                self.assertEqual(round_.submissions, (first, second))
                self.assertEqual(round_.pull_events(), ())


if __name__ == "__main__":
    unittest.main()
