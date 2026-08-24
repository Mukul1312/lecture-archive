"""Shared pure-domain fixtures for the Production and Release test modules.

Closed-review evidence is produced through the real Review aggregate behaviour so
Release tests bind genuine immutable evidence rather than hand-forged snapshots.
"""

from __future__ import annotations

from heritage_production.domain.review import (
    ClientSubmissionNonce,
    ClosedReviewEvidence,
    FindingDecision,
    ImportedFindingRef,
    ReviewClosureSnapshot,
    ReviewCompleteness,
    ReviewFinding,
    ReviewRound,
    ReviewSubmissionSummary,
    ReviewTargetOutcome,
    TargetOutcomeKind,
)
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
    ReleaseContentManifestId,
    ReleaseContentManifestRef,
    ReleasePolicyVersionId,
    ReviewEvidenceRef,
    ReviewPackageId,
    ReviewPackageRef,
    ReviewRoundId,
    SourceRecordingId,
    SourceVersionId,
    SourceVersionRef,
    TranscriptEditionId,
    semantic_digest,
)

from tests.heritage_production.test_review_findings import submit_finding
from tests.heritage_production.test_review_rounds import make_target
from tests.heritage_production.test_review_submissions import assigned_round


def uid(suffix: int) -> str:
    """Return an exact lowercase UUIDv4 string derived from a small integer."""
    return f"7f3e4567-e89b-42d3-a456-{suffix:012x}"


def digest(character: str) -> ContentDigest:
    return ContentDigest("sha256", character * 64)


def artifact(suffix: int, character: str, media_type: str = "application/json") -> ArtifactRef:
    return ArtifactRef(ArtifactId(uid(suffix)), digest(character), 128, media_type)


def actor(suffix: int) -> ActorId:
    return ActorId(uid(suffix))


def attested_credential(suffix: int) -> ActorCredentialRef:
    return ActorCredentialRef(
        actor(suffix),
        CredentialVerificationMethod.STEWARD_ATTESTATION,
        AssuranceLevel.STEWARD_ATTESTED,
    )


def verified_credential(suffix: int, fingerprint: ContentDigest) -> ActorCredentialRef:
    return ActorCredentialRef(
        actor(suffix),
        CredentialVerificationMethod.ED25519,
        AssuranceLevel.VERIFIED_SIGNATURE,
        fingerprint,
        artifact(suffix + 1, "b", "application/octet-stream"),
    )


def production_id() -> ProductionId:
    """The Production identity every Review fixture in this suite already uses."""
    return make_target().production_id


def edition_ref() -> EditionRef:
    return make_target().edition_ref


def successor_edition_ref() -> EditionRef:
    return EditionRef(TranscriptEditionId(uid(2)), digest("7"))


def source_version(suffix: int = 3, character: str = "2") -> SourceVersionRef:
    return SourceVersionRef(
        SourceVersionId(uid(suffix)),
        SourceRecordingId(uid(suffix + 100)),
        digest(character),
        60_000_000,
        "integer microseconds",
    )


def review_evidence_ref(character: str = "4") -> ReviewEvidenceRef:
    return ReviewEvidenceRef(ReviewRoundId(uid(6)), digest(character))


def content_manifest_ref(character: str = "5") -> ReleaseContentManifestRef:
    return ReleaseContentManifestRef(
        ReleaseContentManifestId(uid(7)),
        digest(character),
        artifact(8, "6"),
    )


def policy_version_id() -> ReleasePolicyVersionId:
    return ReleasePolicyVersionId(uid(9))


def _disposition_digest(
    finding: ReviewFinding,
    decision: FindingDecision,
    rationale: str,
    steward: ActorId,
    decided_at_us: int,
) -> ContentDigest:
    return semantic_digest(
        "heritage-finding-disposition-v1",
        {
            "review_finding_id": finding.review_finding_id.value,
            "finding_payload_digest": {
                "algorithm": finding.finding_payload_digest.algorithm,
                "hex_digest": finding.finding_payload_digest.hex_digest,
            },
            "decision": decision.value,
            "rationale": rationale,
            "steward_actor_id": steward.value,
            "decided_at_us": decided_at_us,
        },
    )


def _submission_for(
    round_: ReviewRound,
    assignment: object,
    assurance: object,
    finding: ReviewFinding | None,
    completeness: ReviewCompleteness,
) -> ReviewSubmissionSummary:
    target = round_.target_manifest
    target_keys = tuple(member.target_key for member in target.members)
    if finding is None:
        outcomes = (
            ()
            if completeness is ReviewCompleteness.PARTIAL
            else tuple(
                ReviewTargetOutcome(key, TargetOutcomeKind.NO_ISSUE, ())
                for key in target_keys
            )
        )
        unreviewed = target_keys if completeness is ReviewCompleteness.PARTIAL else ()
        submission_id = __import__(
            "heritage_production.domain.shared", fromlist=["ReviewSubmissionId"]
        ).ReviewSubmissionId(uid(300))
    else:
        ref = ImportedFindingRef(
            finding.client_finding_nonce,
            finding.review_finding_id,
            finding.finding_payload_digest,
            finding.target_key,
            finding.review_submission_id,
        )
        outcomes = (
            ReviewTargetOutcome(finding.target_key, TargetOutcomeKind.FINDINGS, (ref,)),
        )
        unreviewed = ()
        submission_id = finding.review_submission_id
    return ReviewSubmissionSummary.seal(
        review_submission_id=submission_id,
        client_submission_nonce=ClientSubmissionNonce("release-fixture-submission"),
        review_package_ref=ReviewPackageRef(
            ReviewPackageId(uid(310)),
            digest("3"),
            artifact(311, "4", "application/zip"),
        ),
        review_round_id=round_.review_round_id,
        production_id=round_.production_id,
        edition_ref=round_.edition_ref,
        rubric_ref=round_.rubric_ref,
        target_manifest_ref=target.ref,
        submission_schema_version=round_.package_schema_version,
        predecessor_submission_digest=None,
        assigned_actor_id=assignment.actor_id,
        role=assignment.role,
        assurance=assurance,
        completeness=completeness,
        outcomes=outcomes,
        unreviewed_target_keys=unreviewed,
        raw_result_artifact=artifact(312, "5", "application/zip"),
        completed_nonce_map_digest=digest("d"),
        imported_at_us=4,
        target_manifest=target,
    )


def closed_review(
    *,
    finding_decision: FindingDecision | None = None,
    completeness: ReviewCompleteness = ReviewCompleteness.COMPLETE,
    with_submission: bool = True,
) -> ClosedReviewEvidence:
    """Close a real ReviewRound and return its frozen public evidence snapshot."""
    round_, assignment, assurance = assigned_round()
    finding: ReviewFinding | None = None

    if with_submission:
        if finding_decision is not None:
            finding = submit_finding(round_, author_actor_id=assignment.actor_id)
            finding.pull_events()
        summary = _submission_for(round_, assignment, assurance, finding, completeness)
        round_.finalize_submission(
            summary=summary,
            findings=(finding,) if finding is not None else (),
            event_id=DomainEventId(uid(320)),
            event_occurred_at_us=5,
        )
        round_.pull_events()

    if finding is not None and finding_decision is not None:
        rationale = (
            "Apply correction"
            if finding_decision is FindingDecision.ACCEPTED
            else "Not an error in the source recording"
        )
        steward = actor(20)
        finding.record_disposition(
            context=round_.open_context(),
            decision=finding_decision,
            rationale=rationale,
            steward_actor_id=steward,
            decided_at_us=50,
            disposition_digest=_disposition_digest(
                finding, finding_decision, rationale, steward, 50
            ),
            event_id=DomainEventId(uid(321)),
            event_occurred_at_us=51,
        )
        finding.pull_events()

    evidence = round_.close(
        closure_snapshot=ReviewClosureSnapshot(
            (finding,) if finding is not None else (), ()
        ),
        closed_by=actor(20),
        closed_at_us=100,
        event_id=DomainEventId(uid(322)),
        event_occurred_at_us=101,
    )
    round_.pull_events()
    return evidence


def multi_target_round() -> tuple[ReviewRound, object, object]:
    """Open a two-target round so partial reviewer coverage is representable."""
    from heritage_production.domain.review import (
        FindingCategoryCode,
        FindingSeverityCode,
        ReviewerAssignment,
        ReviewTargetKey,
        ReviewTargetManifest,
        ReviewTargetMember,
    )
    from heritage_production.domain.shared import (
        ActorAssuranceEvidence,
        RoleCode,
        RubricId,
        RubricRef,
        SegmentId,
        SegmentRevisionId,
        SegmentRevisionRef,
        SourceSpan,
        TranscriptText,
    )

    base = make_target()
    source = source_version()
    members = tuple(
        ReviewTargetMember(
            index,
            ReviewTargetKey(f"target-{index + 1}"),
            SegmentRevisionRef(
                SegmentId(uid(400 + index)),
                SegmentRevisionId(uid(410 + index)),
                digest(str(index + 1)),
            ),
            SourceSpan(source, index * 1_000, (index + 1) * 1_000),
            TranscriptText(f"segment {index}"),
            (FindingCategoryCode("accuracy"),),
            (FindingSeverityCode("major"),),
        )
        for index in range(2)
    )
    target = ReviewTargetManifest.seal(
        review_round_id=base.review_round_id,
        production_id=base.production_id,
        edition_ref=base.edition_ref,
        rubric_ref=RubricRef(RubricId(uid(420)), 1, digest("4")),
        members=members,
        artifact=artifact(421, "5"),
    )
    credential = attested_credential(430)
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
        opened_by=actor(20),
        opened_at_us=1,
        event_id=DomainEventId(uid(431)),
        event_occurred_at_us=2,
    )
    round_.pull_events()
    assurance = ActorAssuranceEvidence.steward_attested(
        credential=credential,
        attesting_steward_id=actor(20),
        reason="Known reviewer",
        attested_at_us=3,
    )
    return round_, assignment, assurance


def partially_covered_review() -> ClosedReviewEvidence:
    """Close a two-target round whose only submission reviewed one target."""
    round_, assignment, assurance = multi_target_round()
    target = round_.target_manifest
    keys = tuple(member.target_key for member in target.members)
    summary = ReviewSubmissionSummary.seal(
        review_submission_id=__import__(
            "heritage_production.domain.shared", fromlist=["ReviewSubmissionId"]
        ).ReviewSubmissionId(uid(440)),
        client_submission_nonce=ClientSubmissionNonce("partial-submission"),
        review_package_ref=ReviewPackageRef(
            ReviewPackageId(uid(441)), digest("3"), artifact(442, "4", "application/zip")
        ),
        review_round_id=round_.review_round_id,
        production_id=round_.production_id,
        edition_ref=round_.edition_ref,
        rubric_ref=round_.rubric_ref,
        target_manifest_ref=target.ref,
        submission_schema_version=round_.package_schema_version,
        predecessor_submission_digest=None,
        assigned_actor_id=assignment.actor_id,
        role=assignment.role,
        assurance=assurance,
        completeness=ReviewCompleteness.PARTIAL,
        outcomes=(ReviewTargetOutcome(keys[0], TargetOutcomeKind.NO_ISSUE, ()),),
        unreviewed_target_keys=(keys[1],),
        raw_result_artifact=artifact(443, "5", "application/zip"),
        completed_nonce_map_digest=digest("d"),
        imported_at_us=4,
        target_manifest=target,
    )
    round_.finalize_submission(
        summary=summary,
        findings=(),
        event_id=DomainEventId(uid(444)),
        event_occurred_at_us=5,
    )
    round_.pull_events()
    evidence = round_.close(
        closure_snapshot=ReviewClosureSnapshot((), ()),
        closed_by=actor(20),
        closed_at_us=100,
        event_id=DomainEventId(uid(445)),
        event_occurred_at_us=101,
    )
    round_.pull_events()
    return evidence
