from __future__ import annotations

import unittest

try:
    from heritage_production.domain.review import (
        FindingCategoryCode,
        FindingSeverityCode,
        ReviewerAssignment,
        ReviewClosureSnapshot,
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

    def test_round_state_is_behavior_only_while_aggregate_methods_can_mutate(self) -> None:
        target = make_target()
        round_ = ReviewRound.open(
            review_round_id=target.review_round_id,
            production_id=target.production_id,
            edition_ref=target.edition_ref,
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
        round_.pull_events()

        protected_fields = (
            "review_round_id",
            "production_id",
            "edition_ref",
            "target_manifest",
            "rubric_ref",
            "package_schema_version",
            "reviewer_assignments",
            "sign_off_requirements",
            "opened_by",
            "opened_at_us",
            "state",
            "submissions",
            "sign_offs",
            "coverage",
            "evidence_ref",
            "closed_evidence",
            "closed_by",
            "closed_at_us",
        )
        before = tuple(getattr(round_, name) for name in protected_fields)
        for name in protected_fields:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(round_, name, getattr(round_, name))
        self.assertEqual(tuple(getattr(round_, name) for name in protected_fields), before)
        self.assertEqual(round_.pull_events(), ())

        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot((), ()),
            closed_by=ActorId(uid(14)),
            closed_at_us=102,
            event_id=DomainEventId(uid(15)),
            event_occurred_at_us=103,
        )
        self.assertIs(round_.state, ReviewRoundState.CLOSED)
        self.assertEqual(round_.closed_evidence, evidence)
        self.assertEqual(len(round_.pull_events()), 1)
        with self.assertRaises(AttributeError):
            round_.state = ReviewRoundState.OPEN
        self.assertIs(round_.state, ReviewRoundState.CLOSED)


if __name__ == "__main__":
    unittest.main()
