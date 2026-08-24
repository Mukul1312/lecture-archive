from __future__ import annotations

import unittest

try:
    from heritage_production.domain.review import (
        ClientFindingNonce,
        FindingCategoryCode,
        FindingSeverityCode,
        ProposedChange,
        ReviewCharacterSpan,
        ReviewFinding,
        ReviewRound,
    )
except ImportError:
    ClientFindingNonce = None  # type: ignore[assignment,misc]
    ProposedChange = None  # type: ignore[assignment,misc]
    ReviewCharacterSpan = None  # type: ignore[assignment,misc]
    ReviewFinding = None  # type: ignore[assignment,misc]

from heritage_production.domain.shared import (
    ActorId,
    ContentDigest,
    DomainEventId,
    ReviewFindingId,
    ReviewRoundId,
    ReviewSubmissionId,
    RubricId,
    RubricRef,
    SegmentId,
    SegmentRevisionId,
    SegmentRevisionRef,
    SourceSpan,
    TranscriptEditionId,
    EditionRef,
    ValidationError,
)
from tests.heritage_production.test_review_rounds import make_target, uid


def open_round() -> ReviewRound:
    target = make_target()
    return ReviewRound.open(
        review_round_id=target.review_round_id,
        production_id=target.production_id,
        edition_ref=target.edition_ref,
        target_manifest=target,
        rubric_ref=target.rubric_ref,
        package_schema_version=1,
        reviewer_assignments=(),
        sign_off_requirements=(),
        opened_by=ActorId(uid(21)),
        opened_at_us=1,
        event_id=DomainEventId(uid(22)),
        event_occurred_at_us=2,
    )


def submit_finding(
    round_: ReviewRound,
    *,
    author_actor_id: ActorId | None = None,
    review_finding_id: ReviewFindingId | None = None,
    review_submission_id: ReviewSubmissionId | None = None,
    client_finding_nonce: ClientFindingNonce | None = None,
    observation: str = "Wrong word",
) -> ReviewFinding:
    member = round_.target_manifest.members[0]
    author = author_actor_id or ActorId(uid(20))
    finding_id = review_finding_id or ReviewFindingId(uid(23))
    submission_id = review_submission_id or ReviewSubmissionId(uid(24))
    nonce = client_finding_nonce or ClientFindingNonce("finding-1")
    payload_digest = ReviewFinding.compute_payload_digest(
        client_finding_nonce=nonce,
        review_round_id=round_.review_round_id,
        edition_ref=round_.edition_ref,
        rubric_ref=round_.rubric_ref,
        target_key=member.target_key,
        segment_revision_ref=member.segment_revision_ref,
        character_span=ReviewCharacterSpan(0, 3),
        source_subspan=None,
        category_code=FindingCategoryCode("accuracy"),
        severity_code=FindingSeverityCode("major"),
        observation=observation,
        proposed_change=ProposedChange.text_replacement("won"),
        author_actor_id=author,
    )
    return ReviewFinding.submit(
        review_finding_id=finding_id,
        review_round_id=round_.review_round_id,
        review_submission_id=submission_id,
        client_finding_nonce=nonce,
        context=round_.open_context(),
        edition_ref=round_.edition_ref,
        rubric_ref=round_.rubric_ref,
        target_key=member.target_key,
        segment_revision_ref=member.segment_revision_ref,
        character_span=ReviewCharacterSpan(0, 3),
        source_subspan=None,
        category_code=FindingCategoryCode("accuracy"),
        severity_code=FindingSeverityCode("major"),
        observation=observation,
        proposed_change=ProposedChange.text_replacement("won"),
        author_actor_id=author,
        finding_payload_digest=payload_digest,
        event_id=DomainEventId(uid(25)),
        event_occurred_at_us=3,
    )


class ReviewFindingSubmissionTests(unittest.TestCase):
    def test_submit_has_literal_payload_digest_immutable_body_and_stable_event(self) -> None:
        self.assertIsNotNone(ReviewFinding, "the ReviewFinding aggregate must exist")
        self.assertTrue(
            hasattr(ReviewFinding, "compute_payload_digest"),
            "adapters need the exact public finding semantic contract",
        )
        round_ = open_round()
        round_.pull_events()
        target = round_.target_manifest.members[0]
        supplied_digest = ContentDigest(
            "sha256",
            "caccc3a4f721ae093657bd336945eab6577e6992890142522942f40a4feaf5ac",
        )
        computed = ReviewFinding.compute_payload_digest(
            client_finding_nonce=ClientFindingNonce("finding-1"),
            review_round_id=round_.review_round_id,
            edition_ref=round_.edition_ref,
            rubric_ref=round_.rubric_ref,
            target_key=target.target_key,
            segment_revision_ref=target.segment_revision_ref,
            character_span=ReviewCharacterSpan(0, 3),
            source_subspan=None,
            category_code=FindingCategoryCode("accuracy"),
            severity_code=FindingSeverityCode("major"),
            observation="Wrong word",
            proposed_change=ProposedChange.text_replacement("won"),
            author_actor_id=ActorId(uid(20)),
        )
        self.assertEqual(computed, supplied_digest)

        finding = ReviewFinding.submit(
            review_finding_id=ReviewFindingId(uid(23)),
            review_submission_id=ReviewSubmissionId(uid(24)),
            client_finding_nonce=ClientFindingNonce("finding-1"),
            context=round_.open_context(),
            review_round_id=round_.review_round_id,
            edition_ref=round_.edition_ref,
            rubric_ref=round_.rubric_ref,
            target_key=target.target_key,
            segment_revision_ref=target.segment_revision_ref,
            character_span=ReviewCharacterSpan(0, 3),
            source_subspan=None,
            category_code=FindingCategoryCode("accuracy"),
            severity_code=FindingSeverityCode("major"),
            observation="Wrong word",
            proposed_change=ProposedChange.text_replacement("won"),
            author_actor_id=ActorId(uid(20)),
            finding_payload_digest=supplied_digest,
            event_id=DomainEventId(uid(25)),
            event_occurred_at_us=3,
        )

        self.assertEqual(finding.finding_payload_digest, supplied_digest)
        with self.assertRaises(AttributeError):
            finding.observation = "mutated"  # type: ignore[misc]
        events = finding.pull_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ReviewFindingSubmitted")
        self.assertEqual(
            events[0].payload,
            {
                "finding_payload_digest": supplied_digest.hex_digest,
                "review_finding_id": uid(23),
                "review_round_id": uid(6),
                "review_submission_id": uid(24),
                "segment_revision_digest": "3" * 64,
                "target_key": "target-1",
            },
        )

        restored = ReviewFinding.reconstitute(
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
            target_manifest=round_.target_manifest,
            disposition=None,
        )
        self.assertEqual(restored.evidence, finding.evidence)
        self.assertEqual(restored.pull_events(), ())

    def test_submit_rejects_inexact_target_rubric_spans_codes_and_digest(self) -> None:
        round_ = open_round()
        round_.pull_events()
        member = round_.target_manifest.members[0]
        base = {
            "review_finding_id": ReviewFindingId(uid(30)),
            "review_round_id": round_.review_round_id,
            "review_submission_id": ReviewSubmissionId(uid(31)),
            "client_finding_nonce": ClientFindingNonce("finding-1"),
            "context": round_.open_context(),
            "edition_ref": round_.edition_ref,
            "rubric_ref": round_.rubric_ref,
            "target_key": member.target_key,
            "segment_revision_ref": member.segment_revision_ref,
            "character_span": ReviewCharacterSpan(0, 3),
            "source_subspan": None,
            "category_code": FindingCategoryCode("accuracy"),
            "severity_code": FindingSeverityCode("major"),
            "observation": "Wrong word",
            "proposed_change": ProposedChange.text_replacement("won"),
            "author_actor_id": ActorId(uid(20)),
            "finding_payload_digest": ContentDigest(
                "sha256",
                "caccc3a4f721ae093657bd336945eab6577e6992890142522942f40a4feaf5ac",
            ),
            "event_id": DomainEventId(uid(32)),
            "event_occurred_at_us": 3,
        }
        invalid = (
            {"review_round_id": ReviewRoundId(uid(33))},
            {"edition_ref": EditionRef(TranscriptEditionId(uid(34)), ContentDigest("sha256", "6" * 64))},
            {"rubric_ref": RubricRef(RubricId(uid(35)), 1, ContentDigest("sha256", "7" * 64))},
            {"segment_revision_ref": SegmentRevisionRef(SegmentId(uid(36)), SegmentRevisionId(uid(37)), ContentDigest("sha256", "8" * 64))},
            {"category_code": FindingCategoryCode("timing")},
            {"severity_code": FindingSeverityCode("minor")},
            {"character_span": ReviewCharacterSpan(0, 4)},
            {"source_subspan": SourceSpan(member.source_span.source_version, 0, 2_000)},
            {"finding_payload_digest": ContentDigest("sha256", "9" * 64)},
        )
        for override in invalid:
            with self.subTest(override=override):
                with self.assertRaises(ValidationError):
                    ReviewFinding.submit(**(base | override))
                self.assertEqual(round_.pull_events(), ())

    def test_proposed_change_shapes_reject_ambiguous_required_and_forbidden_fields(self) -> None:
        source = make_target().members[0].source_span
        valid = (
            ProposedChange.text_replacement(""),
            ProposedChange.source_boundary(source),
            ProposedChange.speaker_set("speaker-a"),
            ProposedChange.speaker_clear(),
            ProposedChange.language_set("hi"),
            ProposedChange.language_clear(),
            ProposedChange.uncertainty_clear(),
        )
        self.assertEqual(len(valid), 7)
        with self.assertRaises(ValidationError):
            ProposedChange(ProposedChange.text_replacement("x").kind)
        with self.assertRaises(ValidationError):
            ProposedChange(
                ProposedChange.speaker_clear().kind,
                scalar_value="ambiguous",
            )

    def test_disposition_is_single_append_only_decision_with_literal_digest(self) -> None:
        self.assertTrue(
            hasattr(ReviewFinding, "record_disposition"),
            "findings require append-only steward disposition behavior",
        )
        from heritage_production.domain.review import FindingDecision

        round_ = open_round()
        round_.pull_events()
        finding = submit_finding(round_)
        finding.pull_events()
        disposition = finding.record_disposition(
            context=round_.open_context(),
            decision=FindingDecision.ACCEPTED,
            rationale="Apply correction",
            steward_actor_id=ActorId(uid(40)),
            decided_at_us=50,
            disposition_digest=ContentDigest(
                "sha256",
                "7af70c5b45779f7a472bf2ffe352ecb0698f652d9c54525a77547d4227053696",
            ),
            event_id=DomainEventId(uid(41)),
            event_occurred_at_us=51,
        )
        self.assertEqual(finding.disposition, disposition)
        self.assertEqual(
            disposition.disposition_digest.hex_digest,
            "7af70c5b45779f7a472bf2ffe352ecb0698f652d9c54525a77547d4227053696",
        )
        events = finding.pull_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ReviewFindingDispositionRecorded")

        before = finding.evidence
        with self.assertRaises(ValidationError):
            finding.record_disposition(
                context=round_.open_context(),
                decision=FindingDecision.REJECTED,
                rationale="Changed mind",
                steward_actor_id=ActorId(uid(40)),
                decided_at_us=52,
                disposition_digest=ContentDigest("sha256", "9" * 64),
                event_id=DomainEventId(uid(42)),
                event_occurred_at_us=53,
            )
        self.assertEqual(finding.evidence, before)
        self.assertEqual(finding.pull_events(), ())

    def test_rejected_disposition_requires_reason_and_digest_tamper_is_atomic(self) -> None:
        from heritage_production.domain.review import FindingDecision

        round_ = open_round()
        round_.pull_events()
        for rationale in (None, ""):
            finding = submit_finding(round_)
            finding.pull_events()
            with self.subTest(rationale=rationale):
                with self.assertRaises(ValidationError):
                    finding.record_disposition(
                        context=round_.open_context(),
                        decision=FindingDecision.REJECTED,
                        rationale=rationale,
                        steward_actor_id=ActorId(uid(40)),
                        decided_at_us=50,
                        disposition_digest=ContentDigest("sha256", "8" * 64),
                        event_id=DomainEventId(uid(41)),
                        event_occurred_at_us=51,
                    )
                self.assertIsNone(finding.disposition)
                self.assertEqual(finding.pull_events(), ())

        finding = submit_finding(round_)
        finding.pull_events()
        with self.assertRaises(ValidationError):
            finding.record_disposition(
                context=round_.open_context(),
                decision=FindingDecision.ACCEPTED,
                rationale="Apply correction",
                steward_actor_id=ActorId(uid(40)),
                decided_at_us=50,
                disposition_digest=ContentDigest("sha256", "8" * 64),
                event_id=DomainEventId(uid(41)),
                event_occurred_at_us=51,
            )
        self.assertIsNone(finding.disposition)
        self.assertEqual(finding.pull_events(), ())


if __name__ == "__main__":
    unittest.main()
