from __future__ import annotations

import unittest

try:
    from heritage_production.domain.review import (
        FindingCategoryCode,
        FindingSeverityCode,
        ReviewerAssignment,
        ReviewRound,
        ReviewRoundState,
        ReviewTargetKey,
        ReviewTargetManifest,
        ReviewTargetMember,
    )
except ImportError:
    ReviewerAssignment = None  # type: ignore[assignment,misc]
    ReviewRound = None  # type: ignore[assignment,misc]
    ReviewRoundState = None  # type: ignore[assignment,misc]

from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    ArtifactId,
    ArtifactRef,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    DomainEventId,
    EditionRef,
    ProductionId,
    ReviewRoundId,
    RoleCode,
    RubricId,
    RubricRef,
    SegmentId,
    SegmentRevisionId,
    SegmentRevisionRef,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptEditionId,
    TranscriptText,
    ValidationError,
)


def uid(suffix: int) -> str:
    return f"223e4567-e89b-42d3-a456-{suffix:012x}"


def digest(character: str) -> ContentDigest:
    return ContentDigest("sha256", character * 64)


def make_target(*, edition_ref: EditionRef | None = None) -> ReviewTargetManifest:
    edition = edition_ref or EditionRef(TranscriptEditionId(uid(1)), digest("1"))
    source = SourceVersionRef(
        SourceVersionId(uid(2)),
        SourceRecordingId(uid(3)),
        digest("2"),
        10_000,
        "integer microseconds",
    )
    member = ReviewTargetMember(
        0,
        ReviewTargetKey("target-1"),
        SegmentRevisionRef(SegmentId(uid(4)), SegmentRevisionId(uid(5)), digest("3")),
        SourceSpan(source, 0, 1_000),
        TranscriptText("one"),
        (FindingCategoryCode("accuracy"),),
        (FindingSeverityCode("major"),),
    )
    return ReviewTargetManifest.seal(
        review_round_id=ReviewRoundId(uid(6)),
        production_id=ProductionId(uid(7)),
        edition_ref=edition,
        rubric_ref=RubricRef(RubricId(uid(8)), 1, digest("4")),
        members=(member,),
        artifact=ArtifactRef(
            ArtifactId(uid(9)), digest("5"), 100, "application/json"
        ),
    )


class ReviewRoundOpenTests(unittest.TestCase):
    def test_open_binds_target_assignments_and_emits_stable_event(self) -> None:
        self.assertIsNotNone(ReviewRound, "the ReviewRound aggregate must exist")
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
            opened_at_us=100,
            event_id=DomainEventId(uid(12)),
            event_occurred_at_us=101,
        )

        self.assertIs(round_.state, ReviewRoundState.OPEN)
        context = round_.open_context()
        self.assertEqual(context.target_digest, target.semantic_digest)
        self.assertEqual(context.members, target.members)
        events = round_.pull_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ReviewRoundOpened")
        self.assertEqual(
            events[0].payload,
            {
                "edition_digest": digest("1").hex_digest,
                "production_id": target.production_id.value,
                "review_round_id": target.review_round_id.value,
                "rubric_digest": digest("4").hex_digest,
                "target_digest": target.semantic_digest.hex_digest,
            },
        )

    def test_open_rejects_stale_edition_before_creating_state(self) -> None:
        target = make_target()
        with self.assertRaises(ValidationError):
            ReviewRound.open(
                review_round_id=target.review_round_id,
                production_id=target.production_id,
                edition_ref=EditionRef(TranscriptEditionId(uid(13)), digest("6")),
                target_manifest=target,
                rubric_ref=target.rubric_ref,
                package_schema_version=1,
                reviewer_assignments=(),
                sign_off_requirements=(),
                opened_by=ActorId(uid(11)),
                opened_at_us=100,
                event_id=DomainEventId(uid(12)),
                event_occurred_at_us=101,
            )


if __name__ == "__main__":
    unittest.main()
