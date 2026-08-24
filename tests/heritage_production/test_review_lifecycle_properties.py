from __future__ import annotations

import unittest

from hypothesis import given, settings, strategies as st

from heritage_production.domain.review import (
    ClientFindingNonce,
    ClientSubmissionNonce,
    FindingCategoryCode,
    FindingDecision,
    FindingSeverityCode,
    ImportedFindingRef,
    ReviewClosureSnapshot,
    ReviewCompleteness,
    ReviewFinding,
    ReviewSubmissionSummary,
    ReviewTargetOutcome,
    TargetOutcomeKind,
)
from heritage_production.domain.shared import (
    ActorId,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    DomainEventId,
    ReviewFindingId,
    ReviewPackageId,
    ReviewPackageRef,
    ReviewSubmissionId,
    ValidationError,
    semantic_digest,
)
from tests.heritage_production.test_review_rounds import uid
from tests.heritage_production.test_review_submissions import assigned_round


def build_finding(round_, suffix: int, nonce: str, observation: str) -> ReviewFinding:
    member = round_.target_manifest.members[0]
    body = {
        "client_finding_nonce": ClientFindingNonce(nonce),
        "review_round_id": round_.review_round_id,
        "edition_ref": round_.edition_ref,
        "rubric_ref": round_.rubric_ref,
        "target_key": member.target_key,
        "segment_revision_ref": member.segment_revision_ref,
        "character_span": None,
        "source_subspan": None,
        "category_code": FindingCategoryCode("accuracy"),
        "severity_code": FindingSeverityCode("major"),
        "observation": observation,
        "proposed_change": None,
        "author_actor_id": ActorId(uid(150)),
    }
    finding = ReviewFinding.submit(
        review_finding_id=ReviewFindingId(uid(suffix)),
        review_submission_id=ReviewSubmissionId(uid(155)),
        context=round_.open_context(),
        finding_payload_digest=ReviewFinding.compute_payload_digest(**body),
        event_id=DomainEventId(uid(suffix + 10)),
        event_occurred_at_us=suffix,
        **body,
    )
    finding.pull_events()
    disposition_digest = semantic_digest(
        "heritage-finding-disposition-v1",
        {
            "review_finding_id": finding.review_finding_id.value,
            "finding_payload_digest": {
                "algorithm": finding.finding_payload_digest.algorithm,
                "hex_digest": finding.finding_payload_digest.hex_digest,
            },
            "decision": "accepted",
            "rationale": None,
            "steward_actor_id": uid(151),
            "decided_at_us": suffix + 100,
        },
    )
    finding.record_disposition(
        context=round_.open_context(),
        decision=FindingDecision.ACCEPTED,
        rationale=None,
        steward_actor_id=ActorId(uid(151)),
        decided_at_us=suffix + 100,
        disposition_digest=disposition_digest,
        event_id=DomainEventId(uid(suffix + 20)),
        event_occurred_at_us=suffix + 101,
    )
    finding.pull_events()
    return finding


def ready_round():
    round_, assignment, assurance = assigned_round()
    first = build_finding(round_, 160, "finding-a", "First concern")
    second = build_finding(round_, 161, "finding-b", "Second concern")
    refs = tuple(
        ImportedFindingRef(
            value.client_finding_nonce,
            value.review_finding_id,
            value.finding_payload_digest,
            value.target_key,
            value.review_submission_id,
        )
        for value in (first, second)
    )
    target = round_.target_manifest
    summary = ReviewSubmissionSummary.seal(
        review_submission_id=ReviewSubmissionId(uid(155)),
        client_submission_nonce=ClientSubmissionNonce("submission-two-findings"),
        review_package_ref=ReviewPackageRef(
            ReviewPackageId(uid(156)),
            ContentDigest("sha256", "a" * 64),
            ArtifactRef(ArtifactId(uid(157)), ContentDigest("sha256", "b" * 64), 10, "application/zip"),
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
        outcomes=(ReviewTargetOutcome(target.members[0].target_key, TargetOutcomeKind.FINDINGS, refs),),
        unreviewed_target_keys=(),
        raw_result_artifact=ArtifactRef(
            ArtifactId(uid(158)), ContentDigest("sha256", "c" * 64), 10, "application/zip"
        ),
        completed_nonce_map_digest=ContentDigest("sha256", "d" * 64),
        imported_at_us=10,
        target_manifest=target,
    )
    round_.finalize_submission(
        summary=summary,
        findings=(first, second),
        event_id=DomainEventId(uid(159)),
        event_occurred_at_us=11,
    )
    round_.pull_events()
    return round_, (first, second)


class ReviewLifecyclePropertyTests(unittest.TestCase):
    @settings(max_examples=6, deadline=None)
    @given(order=st.permutations((0, 1)))
    def test_closure_is_insertion_order_independent_and_rejection_is_atomic(
        self, order: list[int]
    ) -> None:
        round_, findings = ready_round()
        before = (round_.state, round_.submissions, round_.coverage, round_.evidence_ref)
        with self.assertRaises(ValidationError):
            round_.close(
                closure_snapshot=ReviewClosureSnapshot((findings[0].evidence,), ()),
                closed_by=ActorId(uid(170)),
                closed_at_us=200,
                event_id=DomainEventId(uid(171)),
                event_occurred_at_us=201,
            )
        self.assertEqual(
            (round_.state, round_.submissions, round_.coverage, round_.evidence_ref),
            before,
        )
        self.assertEqual(round_.pull_events(), ())

        evidence = round_.close(
            closure_snapshot=ReviewClosureSnapshot(
                tuple(findings[index].evidence for index in order), ()
            ),
            closed_by=ActorId(uid(170)),
            closed_at_us=200,
            event_id=DomainEventId(uid(171)),
            event_occurred_at_us=201,
        )
        baseline_round, baseline_findings = ready_round()
        baseline = baseline_round.close(
            closure_snapshot=ReviewClosureSnapshot(
                tuple(value.evidence for value in baseline_findings), ()
            ),
            closed_by=ActorId(uid(170)),
            closed_at_us=200,
            event_id=DomainEventId(uid(171)),
            event_occurred_at_us=201,
        )
        self.assertEqual(evidence.evidence_ref, baseline.evidence_ref)
        self.assertEqual(
            tuple(value.review_finding_id for value in evidence.findings),
            tuple(sorted((value.review_finding_id for value in findings), key=lambda value: value.value)),
        )


if __name__ == "__main__":
    unittest.main()
