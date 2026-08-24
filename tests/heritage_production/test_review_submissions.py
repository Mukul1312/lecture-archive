from __future__ import annotations

from copy import copy
import unittest

try:
    from heritage_production.domain.review import (
        ClientFindingNonce,
        ClientSubmissionNonce,
        ImportedFindingRef,
        ReviewerAssignment,
        ReviewCompleteness,
        ReviewRound,
        ReviewRoundState,
        ReviewSubmissionSummary,
        ReviewFinding,
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
    ReviewRoundId,
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


def summary_for_finding(
    round_: ReviewRound,
    assignment: ReviewerAssignment,
    assurance: ActorAssuranceEvidence,
    finding: ReviewFinding,
    *,
    submission_nonce: str,
    package_suffix: int,
    predecessor: ContentDigest | None,
    package_digest: ContentDigest | None = None,
) -> ReviewSubmissionSummary:
    ref = ImportedFindingRef(
        finding.client_finding_nonce,
        finding.review_finding_id,
        finding.finding_payload_digest,
        finding.target_key,
        finding.review_submission_id,
    )
    return ReviewSubmissionSummary.seal(
        review_submission_id=finding.review_submission_id,
        client_submission_nonce=ClientSubmissionNonce(submission_nonce),
        review_package_ref=ReviewPackageRef(
            ReviewPackageId(uid(package_suffix)),
            package_digest
            or ContentDigest("sha256", f"{package_suffix % 10}" * 64),
            artifact(package_suffix + 1, "b", "application/zip"),
        ),
        review_round_id=round_.review_round_id,
        production_id=round_.production_id,
        edition_ref=round_.edition_ref,
        rubric_ref=round_.rubric_ref,
        target_manifest_ref=round_.target_manifest.ref,
        submission_schema_version=round_.package_schema_version,
        predecessor_submission_digest=predecessor,
        assigned_actor_id=assignment.actor_id,
        role=assignment.role,
        assurance=assurance,
        completeness=ReviewCompleteness.COMPLETE,
        outcomes=(
            ReviewTargetOutcome(
                finding.target_key, TargetOutcomeKind.FINDINGS, (ref,)
            ),
        ),
        unreviewed_target_keys=(),
        raw_result_artifact=artifact(package_suffix + 2, "c", "application/zip"),
        completed_nonce_map_digest=ContentDigest("sha256", "d" * 64),
        imported_at_us=package_suffix,
        target_manifest=round_.target_manifest,
    )


def zero_finding_variant(
    round_: ReviewRound,
    assignment: ReviewerAssignment,
    assurance: ActorAssuranceEvidence,
    *,
    submission_suffix: int,
    submission_nonce: str,
    package_ref: ReviewPackageRef,
    predecessor: ContentDigest | None,
    raw_artifact: ArtifactRef,
    imported_at_us: int,
    nonce_map_digest: ContentDigest | None = None,
) -> ReviewSubmissionSummary:
    target = round_.target_manifest
    return ReviewSubmissionSummary.seal(
        review_submission_id=ReviewSubmissionId(uid(submission_suffix)),
        client_submission_nonce=ClientSubmissionNonce(submission_nonce),
        review_package_ref=package_ref,
        review_round_id=round_.review_round_id,
        production_id=round_.production_id,
        edition_ref=round_.edition_ref,
        rubric_ref=round_.rubric_ref,
        target_manifest_ref=target.ref,
        submission_schema_version=round_.package_schema_version,
        predecessor_submission_digest=predecessor,
        assigned_actor_id=assignment.actor_id,
        role=assignment.role,
        assurance=assurance,
        completeness=ReviewCompleteness.COMPLETE,
        outcomes=(
            ReviewTargetOutcome(
                target.members[0].target_key, TargetOutcomeKind.NO_ISSUE, ()
            ),
        ),
        unreviewed_target_keys=(),
        raw_result_artifact=raw_artifact,
        completed_nonce_map_digest=nonce_map_digest
        or ContentDigest("sha256", "d" * 64),
        imported_at_us=imported_at_us,
        target_manifest=target,
    )


def forged(value: object, **changes: object) -> object:
    forged_value = copy(value)
    for name, replacement in changes.items():
        object.__setattr__(forged_value, name, replacement)
    return forged_value


def reconstitute_open(
    round_: ReviewRound,
    *,
    submissions: tuple[ReviewSubmissionSummary, ...],
) -> ReviewRound:
    return ReviewRound.reconstitute(
        review_round_id=round_.review_round_id,
        production_id=round_.production_id,
        edition_ref=round_.edition_ref,
        target_manifest=round_.target_manifest,
        rubric_ref=round_.rubric_ref,
        package_schema_version=round_.package_schema_version,
        reviewer_assignments=round_.reviewer_assignments,
        sign_off_requirements=round_.sign_off_requirements,
        opened_by=round_.opened_by,
        opened_at_us=round_.opened_at_us,
        state=ReviewRoundState.OPEN,
        submissions=submissions,
        sign_offs=(),
        closure_snapshot=None,
        closed_evidence=None,
        closed_by=None,
        closed_at_us=None,
    )


class ReviewSubmissionTests(unittest.TestCase):
    def test_finalize_revalidates_loaded_finding_root_body_atomically(self) -> None:
        round_, assignment, assurance = assigned_round()
        finding = submit_finding(round_, author_actor_id=assignment.actor_id)
        finding.pull_events()
        summary = summary_for_finding(
            round_,
            assignment,
            assurance,
            finding,
            submission_nonce="root-revalidation",
            package_suffix=215,
            predecessor=None,
        )
        forged = type(finding).reconstitute(
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
        object.__setattr__(forged, "observation", "Forged imported body")

        with self.assertRaises(ValidationError):
            round_.finalize_submission(
                summary=summary,
                findings=(forged,),
                event_id=DomainEventId(uid(219)),
                event_occurred_at_us=5,
            )
        self.assertEqual(round_.submissions, ())
        self.assertEqual(round_.pull_events(), ())

    def test_reconstitution_reuses_complete_submission_attachment_invariants(self) -> None:
        round_, assignment, assurance = assigned_round()
        first = zero_finding_summary(round_, assignment, assurance)
        correction = zero_finding_variant(
            round_,
            assignment,
            assurance,
            submission_suffix=220,
            submission_nonce="correction",
            package_ref=ReviewPackageRef(
                ReviewPackageId(uid(221)),
                first.review_package_ref.semantic_digest,
                artifact(222, "e", "application/zip"),
            ),
            predecessor=first.submission_digest,
            raw_artifact=artifact(223, "f", "application/zip"),
            imported_at_us=20,
        )
        self.assertEqual(
            reconstitute_open(round_, submissions=(first, correction)).submissions,
            (first, correction),
        )

        weak_assurance = forged(
            correction.assurance, assurance=AssuranceLevel.UNVERIFIED
        )
        reused_package = zero_finding_variant(
            round_,
            assignment,
            assurance,
            submission_suffix=224,
            submission_nonce=first.client_submission_nonce.value,
            package_ref=ReviewPackageRef(
                first.review_package_ref.review_package_id,
                first.review_package_ref.semantic_digest,
                artifact(225, "1", "application/zip"),
            ),
            predecessor=first.submission_digest,
            raw_artifact=artifact(226, "2", "application/zip"),
            imported_at_us=21,
        )
        duplicate_id = zero_finding_variant(
            round_,
            assignment,
            assurance,
            submission_suffix=51,
            submission_nonce="different-id-mapping",
            package_ref=ReviewPackageRef(
                ReviewPackageId(uid(227)),
                ContentDigest("sha256", "3" * 64),
                artifact(228, "4", "application/zip"),
            ),
            predecessor=first.submission_digest,
            raw_artifact=artifact(229, "5", "application/zip"),
            imported_at_us=22,
        )
        invalid_graphs = {
            "schema": (first, forged(correction, submission_schema_version=2)),
            "assurance": (first, forged(correction, assurance=weak_assurance)),
            "predecessor": (
                first,
                forged(correction, predecessor_submission_digest=None),
            ),
            "reused-package-and-qualified-nonce": (first, reused_package),
            "duplicate-submission-id": (first, duplicate_id),
            "duplicate-semantic-digest": (first, first),
            "foreign-round": (
                first,
                forged(correction, review_round_id=ReviewRoundId(uid(230))),
            ),
            "foreign-production": (
                first,
                forged(correction, production_id=ProductionId(uid(231))),
            ),
            "foreign-edition": (
                first,
                forged(
                    correction,
                    edition_ref=type(round_.edition_ref)(
                        round_.edition_ref.transcript_edition_id,
                        ContentDigest("sha256", "6" * 64),
                    ),
                ),
            ),
            "foreign-rubric": (
                first,
                forged(
                    correction,
                    rubric_ref=type(round_.rubric_ref)(
                        round_.rubric_ref.rubric_id,
                        round_.rubric_ref.schema_version,
                        ContentDigest("sha256", "7" * 64),
                    ),
                ),
            ),
            "foreign-target": (
                first,
                forged(
                    correction,
                    target_manifest_ref=type(round_.target_manifest.ref)(
                        round_.review_round_id,
                        ContentDigest("sha256", "8" * 64),
                        round_.target_manifest.ref.artifact,
                    ),
                ),
            ),
        }
        for name, submissions in invalid_graphs.items():
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    reconstitute_open(round_, submissions=submissions)

    def test_reconstitution_rejects_historical_finding_identity_and_payload_collisions(self) -> None:
        round_, assignment, assurance = assigned_round()
        first_finding = submit_finding(
            round_,
            author_actor_id=assignment.actor_id,
            review_submission_id=ReviewSubmissionId(uid(240)),
            review_finding_id=ReviewFindingId(uid(241)),
            client_finding_nonce=ClientFindingNonce("history-one"),
        )
        first = summary_for_finding(
            round_,
            assignment,
            assurance,
            first_finding,
            submission_nonce="history-submission-one",
            package_suffix=242,
            predecessor=None,
        )
        duplicate_id_finding = submit_finding(
            round_,
            author_actor_id=assignment.actor_id,
            review_submission_id=ReviewSubmissionId(uid(245)),
            review_finding_id=first_finding.review_finding_id,
            client_finding_nonce=ClientFindingNonce("history-two"),
            observation="Different body",
        )
        duplicate_id = summary_for_finding(
            round_,
            assignment,
            assurance,
            duplicate_id_finding,
            submission_nonce="history-submission-two",
            package_suffix=246,
            predecessor=first.submission_digest,
        )
        duplicate_payload_finding = submit_finding(
            round_,
            author_actor_id=assignment.actor_id,
            review_submission_id=ReviewSubmissionId(uid(249)),
            review_finding_id=ReviewFindingId(uid(250)),
            client_finding_nonce=first_finding.client_finding_nonce,
        )
        self.assertEqual(
            duplicate_payload_finding.finding_payload_digest,
            first_finding.finding_payload_digest,
        )
        duplicate_payload = summary_for_finding(
            round_,
            assignment,
            assurance,
            duplicate_payload_finding,
            submission_nonce="history-submission-three",
            package_suffix=251,
            predecessor=first.submission_digest,
        )

        for name, candidate in (
            ("finding-id", duplicate_id),
            ("finding-payload", duplicate_payload),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    reconstitute_open(round_, submissions=(first, candidate))

    def test_semantic_replay_retains_first_wrapper_but_rejects_mapping_conflicts(self) -> None:
        round_, assignment, assurance = assigned_round()
        first = zero_finding_summary(round_, assignment, assurance)
        round_.finalize_submission(
            summary=first,
            findings=(),
            event_id=DomainEventId(uid(200)),
            event_occurred_at_us=5,
        )
        correction = zero_finding_variant(
            round_,
            assignment,
            assurance,
            submission_suffix=201,
            submission_nonce="new-head",
            package_ref=ReviewPackageRef(
                ReviewPackageId(uid(202)),
                first.review_package_ref.semantic_digest,
                artifact(203, "e", "application/zip"),
            ),
            predecessor=first.submission_digest,
            raw_artifact=artifact(204, "f", "application/zip"),
            imported_at_us=10,
        )
        round_.finalize_submission(
            summary=correction,
            findings=(),
            event_id=DomainEventId(uid(205)),
            event_occurred_at_us=6,
        )
        round_.pull_events()

        replay = zero_finding_variant(
            round_,
            assignment,
            assurance,
            submission_suffix=51,
            submission_nonce=first.client_submission_nonce.value,
            package_ref=first.review_package_ref,
            predecessor=None,
            raw_artifact=artifact(206, "1", "application/zip"),
            imported_at_us=99,
        )
        self.assertEqual(replay.submission_digest, first.submission_digest)
        self.assertNotEqual(replay.raw_result_artifact, first.raw_result_artifact)
        stored = round_.finalize_submission(
            summary=replay,
            findings=(),
            event_id=DomainEventId(uid(207)),
            event_occurred_at_us=7,
        )
        self.assertIs(stored, first)
        self.assertEqual(round_.submissions, (first, correction))
        self.assertEqual(round_.pull_events(), ())

        conflicts = (
            zero_finding_variant(
                round_,
                assignment,
                assurance,
                submission_suffix=208,
                submission_nonce=first.client_submission_nonce.value,
                package_ref=first.review_package_ref,
                predecessor=None,
                raw_artifact=artifact(209, "2", "application/zip"),
                imported_at_us=100,
            ),
            zero_finding_variant(
                round_,
                assignment,
                assurance,
                submission_suffix=51,
                submission_nonce=first.client_submission_nonce.value,
                package_ref=first.review_package_ref,
                predecessor=None,
                raw_artifact=artifact(210, "3", "application/zip"),
                imported_at_us=101,
                nonce_map_digest=ContentDigest("sha256", "e" * 64),
            ),
        )
        for index, conflict in enumerate(conflicts):
            self.assertEqual(conflict.submission_digest, first.submission_digest)
            with self.subTest(index=index):
                with self.assertRaises(ValidationError):
                    round_.finalize_submission(
                        summary=conflict,
                        findings=(),
                        event_id=DomainEventId(uid(211 + index)),
                        event_occurred_at_us=8 + index,
                    )
                self.assertEqual(round_.submissions, (first, correction))
                self.assertEqual(round_.pull_events(), ())

    def test_correction_requires_new_package_id_and_outer_artifact(self) -> None:
        round_, assignment, assurance = assigned_round()
        first = zero_finding_summary(round_, assignment, assurance)
        round_.finalize_submission(
            summary=first,
            findings=(),
            event_id=DomainEventId(uid(190)),
            event_occurred_at_us=5,
        )
        round_.pull_events()

        reused_id = ReviewPackageRef(
            first.review_package_ref.review_package_id,
            first.review_package_ref.semantic_digest,
            artifact(191, "e", "application/zip"),
        )
        reused_artifact = ReviewPackageRef(
            ReviewPackageId(uid(192)),
            first.review_package_ref.semantic_digest,
            first.review_package_ref.artifact,
        )
        for index, package_ref in enumerate((reused_id, reused_artifact)):
            correction = zero_finding_variant(
                round_,
                assignment,
                assurance,
                submission_suffix=193 + index,
                submission_nonce=f"fresh-package-{index}",
                package_ref=package_ref,
                predecessor=first.submission_digest,
                raw_artifact=artifact(195 + index, "f", "application/zip"),
                imported_at_us=10 + index,
            )
            with self.subTest(index=index):
                with self.assertRaises(ValidationError):
                    round_.finalize_submission(
                        summary=correction,
                        findings=(),
                        event_id=DomainEventId(uid(197 + index)),
                        event_occurred_at_us=6 + index,
                    )
                self.assertEqual(round_.submissions, (first,))
                self.assertEqual(round_.pull_events(), ())

    def test_correction_protects_global_finding_history_but_scopes_nonces_to_package(self) -> None:
        round_, assignment, assurance = assigned_round()
        first_finding = submit_finding(
            round_,
            author_actor_id=assignment.actor_id,
            review_finding_id=ReviewFindingId(uid(150)),
            review_submission_id=ReviewSubmissionId(uid(151)),
            client_finding_nonce=ClientFindingNonce("historical-finding"),
        )
        first_finding.pull_events()
        first = summary_for_finding(
            round_,
            assignment,
            assurance,
            first_finding,
            submission_nonce="historical-submission",
            package_suffix=152,
            predecessor=None,
        )
        round_.finalize_submission(
            summary=first,
            findings=(first_finding,),
            event_id=DomainEventId(uid(155)),
            event_occurred_at_us=5,
        )
        round_.pull_events()

        candidates = (
            submit_finding(
                round_,
                author_actor_id=assignment.actor_id,
                review_finding_id=first_finding.review_finding_id,
                review_submission_id=ReviewSubmissionId(uid(156)),
                client_finding_nonce=ClientFindingNonce("new-id-collision"),
                observation="Different body",
            ),
            submit_finding(
                round_,
                author_actor_id=assignment.actor_id,
                review_finding_id=ReviewFindingId(uid(157)),
                review_submission_id=ReviewSubmissionId(uid(158)),
                client_finding_nonce=first_finding.client_finding_nonce,
            ),
        )
        for index, finding in enumerate(candidates):
            finding.pull_events()
            correction = summary_for_finding(
                round_,
                assignment,
                assurance,
                finding,
                submission_nonce=f"collision-{index}",
                package_suffix=161 + index * 4,
                predecessor=first.submission_digest,
            )
            with self.subTest(index=index):
                with self.assertRaises(ValidationError):
                    round_.finalize_submission(
                        summary=correction,
                        findings=(finding,),
                        event_id=DomainEventId(uid(180 + index)),
                        event_occurred_at_us=6 + index,
                    )
                self.assertEqual(round_.submissions, (first,))
                self.assertEqual(round_.pull_events(), ())

        package_local_nonce = submit_finding(
            round_,
            author_actor_id=assignment.actor_id,
            review_finding_id=ReviewFindingId(uid(159)),
            review_submission_id=ReviewSubmissionId(uid(160)),
            client_finding_nonce=first_finding.client_finding_nonce,
            observation="Different body",
        )
        package_local_nonce.pull_events()
        correction = summary_for_finding(
            round_,
            assignment,
            assurance,
            package_local_nonce,
            submission_nonce=first.client_submission_nonce.value,
            package_suffix=169,
            predecessor=first.submission_digest,
            package_digest=first.review_package_ref.semantic_digest,
        )
        round_.finalize_submission(
            summary=correction,
            findings=(package_local_nonce,),
            event_id=DomainEventId(uid(181)),
            event_occurred_at_us=8,
        )
        self.assertEqual(round_.submissions, (first, correction))

    def test_finalize_rejects_finding_authored_by_another_actor_atomically(self) -> None:
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
            client_submission_nonce=ClientSubmissionNonce("spoofed-author"),
            review_package_ref=ReviewPackageRef(
                ReviewPackageId(uid(141)),
                ContentDigest("sha256", "a" * 64),
                artifact(142, "b", "application/zip"),
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
                    finding.target_key, TargetOutcomeKind.FINDINGS, (ref,)
                ),
            ),
            unreviewed_target_keys=(),
            raw_result_artifact=artifact(143, "c", "application/zip"),
            completed_nonce_map_digest=ContentDigest("sha256", "d" * 64),
            imported_at_us=4,
            target_manifest=target,
        )

        with self.assertRaises(ValidationError):
            round_.finalize_submission(
                summary=summary,
                findings=(finding,),
                event_id=DomainEventId(uid(144)),
                event_occurred_at_us=5,
            )
        self.assertEqual(round_.submissions, ())
        self.assertEqual(round_.pull_events(), ())

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
