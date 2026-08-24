"""ReviewRound lifecycle and its immutable child values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
    ActorAssuranceKind,
    ActorCredentialRef,
    ActorId,
    AggregateEventRecorder,
    AssuranceLevel,
    ContentDigest,
    DomainEvent,
    DomainEventId,
    EditionRef,
    ProductionId,
    ReviewRoundId,
    ReviewPackageRef,
    ReviewEvidenceRef,
    ReviewSubmissionId,
    ReviewTargetManifestRef,
    OperationId,
    RoleCode,
    RubricRef,
    SignatureProof,
    SignOffTargetKind,
    ValidationError,
    assurance_satisfies,
    semantic_digest,
)

from .targets import ReviewTargetKey, ReviewTargetManifest, ReviewTargetMember, _digest_value
from .signoffs import ReviewSignOff, ReviewSignOffRequirement


@dataclass(frozen=True, slots=True)
class ReviewerAssignment:
    credential: ActorCredentialRef
    role: RoleCode
    minimum_assurance: AssuranceLevel

    def __post_init__(self) -> None:
        if type(self.credential) is not ActorCredentialRef:
            raise ValidationError("credential must be an exact ActorCredentialRef")
        if type(self.role) is not RoleCode:
            raise ValidationError("role must be an exact RoleCode")
        if type(self.minimum_assurance) is not AssuranceLevel:
            raise ValidationError("minimum_assurance must be an AssuranceLevel")
        if self.minimum_assurance is AssuranceLevel.UNVERIFIED:
            raise ValidationError("canonical reviewer assignments require assurance")
        if not assurance_satisfies(self.credential.assurance, self.minimum_assurance):
            raise ValidationError("credential assurance is below the reviewer minimum")

    @property
    def actor_id(self) -> ActorId:
        return self.credential.actor_id


class ReviewRoundState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ClientSubmissionNonce:
    value: str

    def __post_init__(self) -> None:
        from heritage_production.domain.shared.text import require_canonical_text

        require_canonical_text(self.value, field="client submission nonce", nonempty=True)


@dataclass(frozen=True, slots=True)
class ImportedFindingRef:
    client_finding_nonce: object
    review_finding_id: object
    finding_payload_digest: ContentDigest
    target_key: ReviewTargetKey
    review_submission_id: ReviewSubmissionId

    def __post_init__(self) -> None:
        from heritage_production.domain.shared import ReviewFindingId
        from .findings import ClientFindingNonce

        for field_name, value, expected in (
            ("client_finding_nonce", self.client_finding_nonce, ClientFindingNonce),
            ("review_finding_id", self.review_finding_id, ReviewFindingId),
            ("finding_payload_digest", self.finding_payload_digest, ContentDigest),
            ("target_key", self.target_key, ReviewTargetKey),
            ("review_submission_id", self.review_submission_id, ReviewSubmissionId),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")


class TargetOutcomeKind(str, Enum):
    NO_ISSUE = "no_issue"
    FINDINGS = "findings"


@dataclass(frozen=True, slots=True)
class ReviewTargetOutcome:
    target_key: ReviewTargetKey
    kind: TargetOutcomeKind
    finding_refs: tuple[ImportedFindingRef, ...]

    def __post_init__(self) -> None:
        if type(self.target_key) is not ReviewTargetKey:
            raise ValidationError("target_key must be an exact ReviewTargetKey")
        if type(self.kind) is not TargetOutcomeKind:
            raise ValidationError("outcome kind must be a TargetOutcomeKind")
        if type(self.finding_refs) is not tuple or not all(
            type(value) is ImportedFindingRef for value in self.finding_refs
        ):
            raise ValidationError("finding_refs must be a tuple of ImportedFindingRef")
        if len(set(self.finding_refs)) != len(self.finding_refs):
            raise ValidationError("outcome finding references must be unique")
        if self.kind is TargetOutcomeKind.NO_ISSUE and self.finding_refs:
            raise ValidationError("NO_ISSUE must not carry finding references")
        if self.kind is TargetOutcomeKind.FINDINGS and not self.finding_refs:
            raise ValidationError("FINDINGS requires one or more finding references")
        if any(value.target_key != self.target_key for value in self.finding_refs):
            raise ValidationError("outcome finding references must target its target key")


class ReviewCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class ReviewClosureSnapshot:
    findings: tuple[object, ...]
    incomplete_import_operation_ids: tuple[OperationId, ...]

    def __post_init__(self) -> None:
        from .findings import ReviewFinding

        if type(self.findings) is not tuple or not all(
            type(value) is ReviewFinding for value in self.findings
        ):
            raise ValidationError("findings must be a tuple of exact ReviewFinding roots")
        if type(self.incomplete_import_operation_ids) is not tuple or not all(
            type(value) is OperationId for value in self.incomplete_import_operation_ids
        ):
            raise ValidationError("incomplete import IDs must be a tuple of OperationId")
        if len(set(self.incomplete_import_operation_ids)) != len(self.incomplete_import_operation_ids):
            raise ValidationError("incomplete import operation IDs must be unique")


@dataclass(frozen=True, slots=True, init=False)
class AssignmentCoverage:
    actor_id: ActorId
    role: RoleCode
    active_submission_id: ReviewSubmissionId | None
    active_submission_digest: ContentDigest | None
    reviewed_target_keys: tuple[ReviewTargetKey, ...]
    unreviewed_target_keys: tuple[ReviewTargetKey, ...]

    @classmethod
    def _build(cls, *values: object) -> AssignmentCoverage:
        coverage = object.__new__(cls)
        for name, value in zip(cls.__dataclass_fields__, values, strict=True):
            object.__setattr__(coverage, name, value)
        return coverage

    @classmethod
    def seal(
        cls,
        *,
        target_manifest: ReviewTargetManifest,
        assignment: ReviewerAssignment,
        active_submission: ReviewSubmissionSummary | None,
    ) -> AssignmentCoverage:
        if type(target_manifest) is not ReviewTargetManifest:
            raise ValidationError("target_manifest must be an exact ReviewTargetManifest")
        if type(assignment) is not ReviewerAssignment:
            raise ValidationError("assignment must be an exact ReviewerAssignment")
        if active_submission is not None and type(active_submission) is not ReviewSubmissionSummary:
            raise ValidationError("active_submission must be an exact ReviewSubmissionSummary")
        target_keys = tuple(member.target_key for member in target_manifest.members)
        if active_submission is None:
            values: tuple[object, ...] = (
                assignment.actor_id,
                assignment.role,
                None,
                None,
                (),
                target_keys,
            )
        else:
            values = (
                assignment.actor_id,
                assignment.role,
                active_submission.review_submission_id,
                active_submission.submission_digest,
                tuple(value.target_key for value in active_submission.outcomes),
                active_submission.unreviewed_target_keys,
            )
        return cls.reconstitute(
            target_manifest=target_manifest,
            assignment=assignment,
            active_submission=active_submission,
            actor_id=values[0],
            role=values[1],
            active_submission_id=values[2],
            active_submission_digest=values[3],
            reviewed_target_keys=values[4],
            unreviewed_target_keys=values[5],
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        target_manifest: ReviewTargetManifest,
        assignment: ReviewerAssignment,
        active_submission: ReviewSubmissionSummary | None,
        actor_id: ActorId,
        role: RoleCode,
        active_submission_id: ReviewSubmissionId | None,
        active_submission_digest: ContentDigest | None,
        reviewed_target_keys: tuple[ReviewTargetKey, ...],
        unreviewed_target_keys: tuple[ReviewTargetKey, ...],
    ) -> AssignmentCoverage:
        if type(target_manifest) is not ReviewTargetManifest:
            raise ValidationError("target_manifest must be an exact ReviewTargetManifest")
        if type(assignment) is not ReviewerAssignment:
            raise ValidationError("assignment must be an exact ReviewerAssignment")
        if active_submission is not None and type(active_submission) is not ReviewSubmissionSummary:
            raise ValidationError("active_submission must be an exact ReviewSubmissionSummary")
        if type(actor_id) is not ActorId or type(role) is not RoleCode:
            raise ValidationError("assignment coverage actor and role must use exact types")
        if (active_submission_id is None) != (active_submission_digest is None):
            raise ValidationError("active submission ID and digest must be present together")
        if active_submission_id is not None and type(active_submission_id) is not ReviewSubmissionId:
            raise ValidationError("active_submission_id must be a ReviewSubmissionId")
        if active_submission_digest is not None and type(active_submission_digest) is not ContentDigest:
            raise ValidationError("active_submission_digest must be a ContentDigest")
        for field_name, values in (
            ("reviewed_target_keys", reviewed_target_keys),
            ("unreviewed_target_keys", unreviewed_target_keys),
        ):
            if type(values) is not tuple or not all(
                type(value) is ReviewTargetKey for value in values
            ):
                raise ValidationError(f"{field_name} must be a tuple of ReviewTargetKey")
            if len(set(values)) != len(values):
                raise ValidationError(f"{field_name} must not contain duplicates")
        target_keys = tuple(member.target_key for member in target_manifest.members)
        if active_submission is None:
            expected = (assignment.actor_id, assignment.role, None, None, (), target_keys)
        else:
            _revalidate_submission_summary(active_submission, target_manifest)
            if (
                active_submission.assigned_actor_id != assignment.actor_id
                or active_submission.role != assignment.role
                or active_submission.review_round_id != target_manifest.review_round_id
                or active_submission.target_manifest_ref != target_manifest.ref
            ):
                raise ValidationError("active submission is foreign to assignment coverage")
            expected = (
                assignment.actor_id,
                assignment.role,
                active_submission.review_submission_id,
                active_submission.submission_digest,
                tuple(value.target_key for value in active_submission.outcomes),
                active_submission.unreviewed_target_keys,
            )
        supplied = (
            actor_id,
            role,
            active_submission_id,
            active_submission_digest,
            reviewed_target_keys,
            unreviewed_target_keys,
        )
        if supplied != expected:
            raise ValidationError("assignment coverage does not match its active submission")
        if tuple(key for key in target_keys if key in set(reviewed_target_keys)) != reviewed_target_keys:
            raise ValidationError("reviewed target keys are not in manifest order")
        if tuple(key for key in target_keys if key in set(unreviewed_target_keys)) != unreviewed_target_keys:
            raise ValidationError("unreviewed target keys are not in manifest order")
        return cls._build(*supplied)


@dataclass(frozen=True, slots=True, init=False)
class ReviewCoverage:
    assignments: tuple[AssignmentCoverage, ...]
    reviewed_target_union: tuple[ReviewTargetKey, ...]
    unreviewed_target_union: tuple[ReviewTargetKey, ...]
    target_count: int
    reviewed_target_count: int

    @classmethod
    def _build(cls, *values: object) -> ReviewCoverage:
        coverage = object.__new__(cls)
        for name, value in zip(cls.__dataclass_fields__, values, strict=True):
            object.__setattr__(coverage, name, value)
        return coverage

    @classmethod
    def _derived_values(
        cls,
        *,
        target_manifest: ReviewTargetManifest,
        reviewer_assignments: tuple[ReviewerAssignment, ...],
        submission_summaries: tuple[ReviewSubmissionSummary, ...],
    ) -> tuple[object, ...]:
        if type(target_manifest) is not ReviewTargetManifest:
            raise ValidationError("target_manifest must be an exact ReviewTargetManifest")
        if type(reviewer_assignments) is not tuple or not all(
            type(value) is ReviewerAssignment for value in reviewer_assignments
        ):
            raise ValidationError("reviewer_assignments must be a tuple of ReviewerAssignment")
        assignment_keys = tuple(
            (value.role.value, value.actor_id.value) for value in reviewer_assignments
        )
        if (
            assignment_keys != tuple(sorted(assignment_keys))
            or len(set(assignment_keys)) != len(assignment_keys)
        ):
            raise ValidationError("reviewer_assignments must be unique and canonical")
        if type(submission_summaries) is not tuple or not all(
            type(value) is ReviewSubmissionSummary for value in submission_summaries
        ):
            raise ValidationError("submission_summaries must be a tuple of ReviewSubmissionSummary")
        validated_summaries: tuple[ReviewSubmissionSummary, ...] = ()
        for summary in submission_summaries:
            _validate_submission_attachment(
                review_round_id=target_manifest.review_round_id,
                production_id=target_manifest.production_id,
                edition_ref=target_manifest.edition_ref,
                rubric_ref=target_manifest.rubric_ref,
                target_manifest=target_manifest,
                package_schema_version=summary.submission_schema_version,
                reviewer_assignments=reviewer_assignments,
                existing_submissions=validated_summaries,
                summary=summary,
                allow_semantic_replay=False,
            )
            validated_summaries = (*validated_summaries, summary)
        target_keys = tuple(member.target_key for member in target_manifest.members)
        assignment_values: list[AssignmentCoverage] = []
        for assignment in reviewer_assignments:
            chain = tuple(
                value
                for value in validated_summaries
                if value.assigned_actor_id == assignment.actor_id
                and value.role == assignment.role
            )
            assignment_values.append(
                AssignmentCoverage.seal(
                    target_manifest=target_manifest,
                    assignment=assignment,
                    active_submission=chain[-1] if chain else None,
                )
            )
        reviewed_set = {
            key for item in assignment_values for key in item.reviewed_target_keys
        }
        unreviewed_set = {
            key for item in assignment_values for key in item.unreviewed_target_keys
        }
        return (
            tuple(assignment_values),
            tuple(key for key in target_keys if key in reviewed_set),
            tuple(key for key in target_keys if key in unreviewed_set),
            len(target_keys),
            len(reviewed_set),
        )

    @classmethod
    def seal(
        cls,
        *,
        target_manifest: ReviewTargetManifest,
        reviewer_assignments: tuple[ReviewerAssignment, ...],
        submission_summaries: tuple[ReviewSubmissionSummary, ...],
    ) -> ReviewCoverage:
        values = cls._derived_values(
            target_manifest=target_manifest,
            reviewer_assignments=reviewer_assignments,
            submission_summaries=submission_summaries,
        )
        return cls._build(*values)

    @classmethod
    def reconstitute(
        cls,
        *,
        target_manifest: ReviewTargetManifest,
        reviewer_assignments: tuple[ReviewerAssignment, ...],
        submission_summaries: tuple[ReviewSubmissionSummary, ...],
        assignments: tuple[AssignmentCoverage, ...],
        reviewed_target_union: tuple[ReviewTargetKey, ...],
        unreviewed_target_union: tuple[ReviewTargetKey, ...],
        target_count: int,
        reviewed_target_count: int,
    ) -> ReviewCoverage:
        if type(target_manifest) is not ReviewTargetManifest:
            raise ValidationError("target_manifest must be an exact ReviewTargetManifest")
        if type(reviewer_assignments) is not tuple or not all(
            type(value) is ReviewerAssignment for value in reviewer_assignments
        ):
            raise ValidationError("reviewer_assignments must be a tuple of ReviewerAssignment")
        if type(submission_summaries) is not tuple or not all(
            type(value) is ReviewSubmissionSummary for value in submission_summaries
        ):
            raise ValidationError("submission_summaries must be a tuple of ReviewSubmissionSummary")
        if type(assignments) is not tuple or not all(
            type(value) is AssignmentCoverage for value in assignments
        ):
            raise ValidationError("assignments must be a tuple of AssignmentCoverage")
        for field_name, values in (
            ("reviewed_target_union", reviewed_target_union),
            ("unreviewed_target_union", unreviewed_target_union),
        ):
            if type(values) is not tuple or not all(
                type(value) is ReviewTargetKey for value in values
            ):
                raise ValidationError(f"{field_name} must be a tuple of ReviewTargetKey")
            if len(set(values)) != len(values):
                raise ValidationError(f"{field_name} must not contain duplicates")
        if type(target_count) is not int or type(reviewed_target_count) is not int:
            raise ValidationError("coverage counts must be exact integers")
        supplied = (
            assignments,
            reviewed_target_union,
            unreviewed_target_union,
            target_count,
            reviewed_target_count,
        )
        expected = cls._derived_values(
            target_manifest=target_manifest,
            reviewer_assignments=reviewer_assignments,
            submission_summaries=submission_summaries,
        )
        if supplied != expected:
            raise ValidationError("review coverage does not match assignments and active heads")
        return cls._build(*supplied)


@dataclass(frozen=True, slots=True, init=False)
class ClosedReviewEvidence:
    """A frozen, self-identifying projection of one closed review round.

    The evidence carries its own Production, target manifest, and reviewer
    assignments so a downstream consumer can revalidate the complete graph with
    `validated()` instead of trusting a retained `evidence_ref`. A round closed
    with zero submissions still names its exact Production.
    """

    evidence_ref: ReviewEvidenceRef
    production_id: ProductionId
    edition_ref: EditionRef
    target_manifest_ref: ReviewTargetManifestRef
    target_manifest: ReviewTargetManifest
    reviewer_assignments: tuple[ReviewerAssignment, ...]
    coverage: ReviewCoverage
    submission_summaries: tuple[ReviewSubmissionSummary, ...]
    findings: tuple[object, ...]
    sign_offs: tuple[ReviewSignOff, ...]

    @classmethod
    def _build(cls, *values: object) -> ClosedReviewEvidence:
        evidence = object.__new__(cls)
        for name, value in zip(cls.__dataclass_fields__, values, strict=True):
            object.__setattr__(evidence, name, value)
        return evidence

    @classmethod
    def seal(
        cls,
        *,
        target_manifest: ReviewTargetManifest,
        reviewer_assignments: tuple[ReviewerAssignment, ...],
        coverage: ReviewCoverage,
        submission_summaries: tuple[ReviewSubmissionSummary, ...],
        findings: tuple[object, ...],
        sign_offs: tuple[ReviewSignOff, ...],
    ) -> ClosedReviewEvidence:
        _validate_closed_evidence_snapshot(
            target_manifest=target_manifest,
            reviewer_assignments=reviewer_assignments,
            edition_ref=target_manifest.edition_ref,
            target_manifest_ref=target_manifest.ref,
            coverage=coverage,
            submission_summaries=submission_summaries,
            findings=findings,
            sign_offs=sign_offs,
        )
        evidence_digest = semantic_digest(
            "heritage-review-evidence-v1",
            _evidence_payload(
                target_manifest.semantic_digest,
                submission_summaries,
                findings,
                coverage,
                sign_offs,
            ),
        )
        return cls._build(
            ReviewEvidenceRef(target_manifest.review_round_id, evidence_digest),
            target_manifest.production_id,
            target_manifest.edition_ref,
            target_manifest.ref,
            target_manifest,
            reviewer_assignments,
            coverage,
            submission_summaries,
            findings,
            sign_offs,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        target_manifest: ReviewTargetManifest,
        reviewer_assignments: tuple[ReviewerAssignment, ...],
        evidence_ref: ReviewEvidenceRef,
        edition_ref: EditionRef,
        target_manifest_ref: ReviewTargetManifestRef,
        coverage: ReviewCoverage,
        submission_summaries: tuple[ReviewSubmissionSummary, ...],
        findings: tuple[object, ...],
        sign_offs: tuple[ReviewSignOff, ...],
    ) -> ClosedReviewEvidence:
        if type(evidence_ref) is not ReviewEvidenceRef:
            raise ValidationError("evidence_ref must be an exact ReviewEvidenceRef")
        _validate_closed_evidence_snapshot(
            target_manifest=target_manifest,
            reviewer_assignments=reviewer_assignments,
            edition_ref=edition_ref,
            target_manifest_ref=target_manifest_ref,
            coverage=coverage,
            submission_summaries=submission_summaries,
            findings=findings,
            sign_offs=sign_offs,
        )
        expected_digest = semantic_digest(
            "heritage-review-evidence-v1",
            _evidence_payload(
                target_manifest.semantic_digest,
                submission_summaries,
                findings,
                coverage,
                sign_offs,
            ),
        )
        if evidence_ref != ReviewEvidenceRef(target_manifest.review_round_id, expected_digest):
            raise ValidationError("review evidence ref does not match its semantic projection")
        return cls._build(
            evidence_ref,
            target_manifest.production_id,
            edition_ref,
            target_manifest_ref,
            target_manifest,
            reviewer_assignments,
            coverage,
            submission_summaries,
            findings,
            sign_offs,
        )

    def validated(self) -> ClosedReviewEvidence:
        """Recompute this evidence from its own stored graph.

        Any child forged behind a retained `evidence_ref` -- stripped findings,
        replaced coverage, a substituted submission -- fails the recomputed
        `heritage-review-evidence-v1` digest here.
        """
        return type(self).reconstitute(
            target_manifest=self.target_manifest,
            reviewer_assignments=self.reviewer_assignments,
            evidence_ref=self.evidence_ref,
            edition_ref=self.edition_ref,
            target_manifest_ref=self.target_manifest_ref,
            coverage=self.coverage,
            submission_summaries=self.submission_summaries,
            findings=self.findings,
            sign_offs=self.sign_offs,
        )


def _derive_coverage(
    assignments: tuple[ReviewerAssignment, ...],
    submissions: tuple[ReviewSubmissionSummary, ...],
    target_manifest: ReviewTargetManifest,
) -> ReviewCoverage:
    return ReviewCoverage.seal(
        target_manifest=target_manifest,
        reviewer_assignments=assignments,
        submission_summaries=submissions,
    )


def _evidence_payload(
    target_digest: ContentDigest,
    submissions: tuple[ReviewSubmissionSummary, ...],
    findings: tuple[object, ...],
    coverage: ReviewCoverage,
    sign_offs: tuple[ReviewSignOff, ...],
) -> dict[str, object]:
    return {
        "target_digest": _digest_value(target_digest),
        "submissions": [
            {
                "review_submission_id": value.review_submission_id.value,
                "submission_digest": _digest_value(value.submission_digest),
            }
            for value in submissions
        ],
        "findings": [
            {
                "review_finding_id": value.review_finding_id.value,
                "review_round_id": value.review_round_id.value,
                "review_submission_id": value.review_submission_id.value,
                "target_key": value.target_key.value,
                "segment_revision_ref": {
                    "segment_id": value.segment_revision_ref.segment_id.value,
                    "segment_revision_id": value.segment_revision_ref.segment_revision_id.value,
                    "revision_digest": _digest_value(
                        value.segment_revision_ref.revision_digest
                    ),
                },
                "category_code": value.category_code.value,
                "severity_code": value.severity_code.value,
                "finding_payload_digest": _digest_value(value.finding_payload_digest),
                "decision": value.disposition.decision.value,
                "disposition_digest": _digest_value(value.disposition.disposition_digest),
            }
            for value in findings
        ],
        "coverage": [
            {
                "actor_id": value.actor_id.value,
                "role": value.role.value,
                "active_submission_id": (
                    value.active_submission_id.value if value.active_submission_id is not None else None
                ),
                "active_submission_digest": (
                    _digest_value(value.active_submission_digest)
                    if value.active_submission_digest is not None
                    else None
                ),
                "reviewed_target_keys": [key.value for key in value.reviewed_target_keys],
                "unreviewed_target_keys": [key.value for key in value.unreviewed_target_keys],
            }
            for value in coverage.assignments
        ],
        "sign_offs": [
            {
                "role": value.role.value,
                "actor_id": value.credential.actor_id.value,
                "target_digest": _digest_value(value.target_ref.semantic_digest),
                "sign_off_digest": _digest_value(value.sign_off_digest),
            }
            for value in sign_offs
        ],
    }


def _validate_closed_evidence_snapshot(
    *,
    target_manifest: ReviewTargetManifest,
    reviewer_assignments: tuple[ReviewerAssignment, ...],
    edition_ref: EditionRef,
    target_manifest_ref: ReviewTargetManifestRef,
    coverage: ReviewCoverage,
    submission_summaries: tuple[ReviewSubmissionSummary, ...],
    findings: tuple[object, ...],
    sign_offs: tuple[ReviewSignOff, ...],
) -> None:
    from .findings import ReviewFindingEvidence

    if type(target_manifest) is not ReviewTargetManifest:
        raise ValidationError("target_manifest must be an exact ReviewTargetManifest")
    if type(reviewer_assignments) is not tuple or not all(
        type(value) is ReviewerAssignment for value in reviewer_assignments
    ):
        raise ValidationError("reviewer_assignments must be a tuple of ReviewerAssignment")
    if type(edition_ref) is not EditionRef or edition_ref != target_manifest.edition_ref:
        raise ValidationError("closed evidence edition is foreign to its target")
    if (
        type(target_manifest_ref) is not ReviewTargetManifestRef
        or target_manifest_ref != target_manifest.ref
    ):
        raise ValidationError("closed evidence target manifest ref is not exact")
    if type(submission_summaries) is not tuple or not all(
        type(value) is ReviewSubmissionSummary for value in submission_summaries
    ):
        raise ValidationError("submission_summaries must be a tuple of ReviewSubmissionSummary")
    validated_submissions: tuple[ReviewSubmissionSummary, ...] = ()
    for summary in submission_summaries:
        _validate_submission_attachment(
            review_round_id=target_manifest.review_round_id,
            production_id=target_manifest.production_id,
            edition_ref=target_manifest.edition_ref,
            rubric_ref=target_manifest.rubric_ref,
            target_manifest=target_manifest,
            package_schema_version=summary.submission_schema_version,
            reviewer_assignments=reviewer_assignments,
            existing_submissions=validated_submissions,
            summary=summary,
            allow_semantic_replay=False,
        )
        validated_submissions = (*validated_submissions, summary)
    canonical_submissions = tuple(
        summary
        for assignment in reviewer_assignments
        for summary in submission_summaries
        if summary.assigned_actor_id == assignment.actor_id
        and summary.role == assignment.role
    )
    if canonical_submissions != submission_summaries:
        raise ValidationError("closed submissions are not in assignment/chain order")

    if type(coverage) is not ReviewCoverage:
        raise ValidationError("coverage must be an exact ReviewCoverage")
    validated_coverage = ReviewCoverage.reconstitute(
        target_manifest=target_manifest,
        reviewer_assignments=reviewer_assignments,
        submission_summaries=submission_summaries,
        assignments=coverage.assignments,
        reviewed_target_union=coverage.reviewed_target_union,
        unreviewed_target_union=coverage.unreviewed_target_union,
        target_count=coverage.target_count,
        reviewed_target_count=coverage.reviewed_target_count,
    )
    if validated_coverage != coverage:
        raise ValidationError("closed review coverage is not canonical")

    if type(findings) is not tuple or not all(
        type(value) is ReviewFindingEvidence for value in findings
    ):
        raise ValidationError("findings must be a tuple of ReviewFindingEvidence")
    canonical_findings = tuple(
        sorted(findings, key=lambda value: value.review_finding_id.value)
    )
    if findings != canonical_findings:
        raise ValidationError("closed findings must be sorted by finding ID")
    finding_ids = tuple(value.review_finding_id for value in findings)
    payload_digests = tuple(value.finding_payload_digest for value in findings)
    if len(set(finding_ids)) != len(findings) or len(set(payload_digests)) != len(findings):
        raise ValidationError("closed finding identities and payloads must be unique")
    members = {value.target_key: value for value in target_manifest.members}
    for finding in findings:
        ReviewFindingEvidence(
            finding.review_finding_id,
            finding.review_round_id,
            finding.review_submission_id,
            finding.target_key,
            finding.segment_revision_ref,
            finding.category_code,
            finding.severity_code,
            finding.finding_payload_digest,
            finding.disposition,
        )
        member = members.get(finding.target_key)
        if (
            finding.review_round_id != target_manifest.review_round_id
            or member is None
            or finding.segment_revision_ref != member.segment_revision_ref
            or finding.category_code not in member.allowed_category_codes
            or finding.severity_code not in member.allowed_severity_codes
        ):
            raise ValidationError("closed finding projection is foreign to its target")
        if finding.disposition is None:
            raise ValidationError("closed finding requires a disposition")
    expected_refs = tuple(
        ref for summary in submission_summaries for ref in summary.finding_refs
    )
    if len(expected_refs) != len(findings):
        raise ValidationError("closed findings do not cover finalized references")
    by_id = {value.review_finding_id: value for value in findings}
    for ref in expected_refs:
        finding = by_id.get(ref.review_finding_id)
        if finding is None or (
            finding.review_submission_id != ref.review_submission_id
            or finding.target_key != ref.target_key
            or finding.finding_payload_digest != ref.finding_payload_digest
        ):
            raise ValidationError("closed finding projection mismatches finalized references")

    if type(sign_offs) is not tuple or not all(
        type(value) is ReviewSignOff for value in sign_offs
    ):
        raise ValidationError("sign_offs must be a tuple of ReviewSignOff")
    canonical_sign_offs = tuple(
        sorted(
            sign_offs,
            key=lambda value: (
                value.role.value,
                value.credential.actor_id.value,
                value.target_ref.semantic_digest.hex_digest,
                value.sign_off_digest.hex_digest,
            ),
        )
    )
    if sign_offs != canonical_sign_offs:
        raise ValidationError("closed sign-offs are not in canonical order")
    sign_off_keys = tuple(
        (value.role, value.credential.actor_id, value.target_ref.semantic_digest)
        for value in sign_offs
    )
    if len(set(sign_off_keys)) != len(sign_offs):
        raise ValidationError("closed sign-off keys must be unique")
    for sign_off in sign_offs:
        _revalidate_sign_off(sign_off)
        if sign_off.target_ref != target_manifest.ref:
            raise ValidationError("closed sign-off targets another review manifest")


def _submission_payload(summary: ReviewSubmissionSummary) -> dict[str, object]:
    return {
        "client_submission_nonce": summary.client_submission_nonce.value,
        "submission_schema_version": summary.submission_schema_version,
        "review_package": {
            "review_package_id": summary.review_package_ref.review_package_id.value,
            "semantic_digest": _digest_value(summary.review_package_ref.semantic_digest),
        },
        "review_round_id": summary.review_round_id.value,
        "production_id": summary.production_id.value,
        "edition_ref": {
            "transcript_edition_id": summary.edition_ref.transcript_edition_id.value,
            "content_digest": _digest_value(summary.edition_ref.content_digest),
        },
        "rubric_ref": {
            "rubric_id": summary.rubric_ref.rubric_id.value,
            "schema_version": summary.rubric_ref.schema_version,
            "content_digest": _digest_value(summary.rubric_ref.content_digest),
        },
        "target_manifest_digest": _digest_value(summary.target_manifest_ref.semantic_digest),
        "assigned_actor_id": summary.assigned_actor_id.value,
        "role": summary.role.value,
        "predecessor_submission_digest": (
            _digest_value(summary.predecessor_submission_digest)
            if summary.predecessor_submission_digest is not None
            else None
        ),
        "completeness": summary.completeness.value,
        "outcomes": [
            {
                "target_key": outcome.target_key.value,
                "outcome": outcome.kind.value,
                "finding_refs": [
                    {
                        "client_finding_nonce": ref.client_finding_nonce.value,
                        "finding_payload_digest": _digest_value(ref.finding_payload_digest),
                    }
                    for ref in outcome.finding_refs
                ],
            }
            for outcome in summary.outcomes
        ],
        "unreviewed_target_keys": [value.value for value in summary.unreviewed_target_keys],
    }


def _assurance_replay_identity(evidence: ActorAssuranceEvidence) -> tuple[object, ...]:
    if evidence.kind is ActorAssuranceKind.VERIFIED_SIGNATURE:
        proof = evidence.proof
        if type(proof) is not SignatureProof:
            raise ValidationError("verified assurance requires an exact SignatureProof")
        proof_algorithm: object = proof.algorithm
        proof_fingerprint: object = proof.credential_fingerprint
    elif evidence.kind is ActorAssuranceKind.STEWARD_ATTESTATION:
        proof_algorithm = None
        proof_fingerprint = None
    else:
        raise ValidationError("unsupported actor assurance kind")
    return (
        evidence.kind,
        evidence.credential,
        evidence.assurance,
        evidence.signed_context_digest,
        proof_algorithm,
        proof_fingerprint,
        evidence.attesting_steward_id,
        evidence.attestation_reason,
        evidence.attested_at_us,
    )


def _submission_replay_equivalent(
    stored: ReviewSubmissionSummary,
    candidate: ReviewSubmissionSummary,
) -> bool:
    """Compare semantic identity while excluding approved import wrappers."""
    return (
        stored.review_submission_id == candidate.review_submission_id
        and stored.client_submission_nonce == candidate.client_submission_nonce
        and stored.review_package_ref.review_package_id
        == candidate.review_package_ref.review_package_id
        and stored.review_package_ref.semantic_digest
        == candidate.review_package_ref.semantic_digest
        and stored.review_round_id == candidate.review_round_id
        and stored.production_id == candidate.production_id
        and stored.edition_ref == candidate.edition_ref
        and stored.rubric_ref == candidate.rubric_ref
        and stored.target_manifest_ref == candidate.target_manifest_ref
        and stored.submission_schema_version == candidate.submission_schema_version
        and stored.predecessor_submission_digest
        == candidate.predecessor_submission_digest
        and stored.assigned_actor_id == candidate.assigned_actor_id
        and stored.role == candidate.role
        and _assurance_replay_identity(stored.assurance)
        == _assurance_replay_identity(candidate.assurance)
        and stored.completeness == candidate.completeness
        and stored.outcomes == candidate.outcomes
        and stored.unreviewed_target_keys == candidate.unreviewed_target_keys
        and stored.completed_nonce_map_digest
        == candidate.completed_nonce_map_digest
        and stored.submission_digest == candidate.submission_digest
    )


def review_submission_context_digest(
    *,
    actor_id: ActorId,
    role: RoleCode,
    target_ref: ReviewTargetManifestRef,
    submission_digest: ContentDigest,
    schema_version: int,
) -> ContentDigest:
    """Bind a verified reviewer signature to one exact submission operation."""
    for field_name, value, expected in (
        ("actor_id", actor_id, ActorId),
        ("role", role, RoleCode),
        ("target_ref", target_ref, ReviewTargetManifestRef),
        ("submission_digest", submission_digest, ContentDigest),
    ):
        if type(value) is not expected:
            raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
    if type(schema_version) is not int or schema_version <= 0:
        raise ValidationError("schema_version must be a positive integer")
    return semantic_digest(
        "heritage-review-submission-context-v1",
        {
            "semantic_payload_digest": _digest_value(submission_digest),
            "actor_id": actor_id.value,
            "role": role.value,
            "target_kind": SignOffTargetKind.REVIEW_TARGET.value,
            "target_id": target_ref.review_round_id.value,
            "target_digest": _digest_value(target_ref.semantic_digest),
            "operation_kind": "review_submission",
            "schema_version": schema_version,
        },
    )


@dataclass(frozen=True, slots=True, init=False)
class ReviewSubmissionSummary:
    review_submission_id: ReviewSubmissionId
    client_submission_nonce: ClientSubmissionNonce
    review_package_ref: ReviewPackageRef
    review_round_id: ReviewRoundId
    production_id: ProductionId
    edition_ref: EditionRef
    rubric_ref: RubricRef
    target_manifest_ref: ReviewTargetManifestRef
    submission_schema_version: int
    predecessor_submission_digest: ContentDigest | None
    assigned_actor_id: ActorId
    role: RoleCode
    assurance: ActorAssuranceEvidence
    completeness: ReviewCompleteness
    outcomes: tuple[ReviewTargetOutcome, ...]
    unreviewed_target_keys: tuple[ReviewTargetKey, ...]
    raw_result_artifact: object
    completed_nonce_map_digest: ContentDigest
    imported_at_us: int
    submission_digest: ContentDigest

    @classmethod
    def seal(cls, *, target_manifest: ReviewTargetManifest, **values: object) -> ReviewSubmissionSummary:
        provisional = object.__new__(cls)
        for name in cls.__dataclass_fields__:
            if name != "submission_digest":
                object.__setattr__(provisional, name, values.get(name))
        try:
            digest = semantic_digest(
                "heritage-review-submission-v1", _submission_payload(provisional)
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed review-submission semantic input") from error
        return cls.reconstitute(
            target_manifest=target_manifest,
            submission_digest=digest,
            **values,
        )

    @classmethod
    def reconstitute(cls, *, target_manifest: ReviewTargetManifest, **values: object) -> ReviewSubmissionSummary:
        from heritage_production.domain.shared import ArtifactRef

        expected_types = (
            ("review_submission_id", ReviewSubmissionId),
            ("client_submission_nonce", ClientSubmissionNonce),
            ("review_package_ref", ReviewPackageRef),
            ("review_round_id", ReviewRoundId),
            ("production_id", ProductionId),
            ("edition_ref", EditionRef),
            ("rubric_ref", RubricRef),
            ("target_manifest_ref", ReviewTargetManifestRef),
            ("assigned_actor_id", ActorId),
            ("role", RoleCode),
            ("assurance", ActorAssuranceEvidence),
            ("completeness", ReviewCompleteness),
            ("raw_result_artifact", ArtifactRef),
            ("completed_nonce_map_digest", ContentDigest),
            ("submission_digest", ContentDigest),
        )
        for field_name, expected in expected_types:
            if type(values.get(field_name)) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        values["assurance"] = values["assurance"].validated()
        if type(values.get("submission_schema_version")) is not int or values["submission_schema_version"] <= 0:
            raise ValidationError("submission_schema_version must be a positive integer")
        if type(values.get("imported_at_us")) is not int or values["imported_at_us"] <= 0:
            raise ValidationError("imported_at_us must be a positive integer")
        predecessor = values.get("predecessor_submission_digest")
        if predecessor is not None and type(predecessor) is not ContentDigest:
            raise ValidationError("predecessor_submission_digest must be a ContentDigest")
        outcomes = values.get("outcomes")
        unreviewed = values.get("unreviewed_target_keys")
        if type(outcomes) is not tuple or not all(type(value) is ReviewTargetOutcome for value in outcomes):
            raise ValidationError("outcomes must be a tuple of ReviewTargetOutcome")
        if type(unreviewed) is not tuple or not all(type(value) is ReviewTargetKey for value in unreviewed):
            raise ValidationError("unreviewed_target_keys must be a tuple of ReviewTargetKey")
        if type(target_manifest) is not ReviewTargetManifest:
            raise ValidationError("target_manifest must be an exact ReviewTargetManifest")
        if (
            values["review_round_id"] != target_manifest.review_round_id
            or values["production_id"] != target_manifest.production_id
            or values["edition_ref"] != target_manifest.edition_ref
            or values["rubric_ref"] != target_manifest.rubric_ref
            or values["target_manifest_ref"] != target_manifest.ref
        ):
            raise ValidationError("submission does not bind the exact review target context")
        if values["assigned_actor_id"] != values["assurance"].actor_id:
            raise ValidationError("submission actor does not match assurance evidence")
        target_keys = tuple(member.target_key for member in target_manifest.members)
        outcome_keys = tuple(value.target_key for value in outcomes)
        if len(set(outcome_keys)) != len(outcome_keys) or len(set(unreviewed)) != len(unreviewed):
            raise ValidationError("reviewed and unreviewed target keys must be unique")
        expected_outcomes = tuple(key for key in target_keys if key in set(outcome_keys))
        expected_unreviewed = tuple(key for key in target_keys if key in set(unreviewed))
        if outcome_keys != expected_outcomes or unreviewed != expected_unreviewed:
            raise ValidationError("submission target sets must follow manifest order")
        if set(outcome_keys) & set(unreviewed) or set(outcome_keys) | set(unreviewed) != set(target_keys):
            raise ValidationError("reviewed and unreviewed targets must partition the manifest")
        if values["completeness"] is ReviewCompleteness.COMPLETE and unreviewed:
            raise ValidationError("complete submission cannot have unreviewed targets")
        if values["completeness"] is ReviewCompleteness.PARTIAL and (not outcomes or not unreviewed):
            raise ValidationError("partial submission must explicitly contain both target sets")
        finding_refs = tuple(ref for outcome in outcomes for ref in outcome.finding_refs)
        for attribute in ("client_finding_nonce", "review_finding_id", "finding_payload_digest"):
            identities = tuple(getattr(ref, attribute) for ref in finding_refs)
            if len(set(identities)) != len(identities):
                raise ValidationError(f"submission finding {attribute} values must be unique")
        if any(ref.review_submission_id != values["review_submission_id"] for ref in finding_refs):
            raise ValidationError("finding references must use the reserved submission identity")
        summary = object.__new__(cls)
        for name in cls.__dataclass_fields__:
            object.__setattr__(summary, name, values[name])
        expected_digest = semantic_digest("heritage-review-submission-v1", _submission_payload(summary))
        if expected_digest != summary.submission_digest:
            raise ValidationError("review-submission digest does not match its semantic payload")
        if summary.assurance.kind is ActorAssuranceKind.VERIFIED_SIGNATURE:
            expected_context = review_submission_context_digest(
                actor_id=summary.assigned_actor_id,
                role=summary.role,
                target_ref=summary.target_manifest_ref,
                submission_digest=summary.submission_digest,
                schema_version=summary.submission_schema_version,
            )
            if summary.assurance.signed_context_digest != expected_context:
                raise ValidationError(
                    "signature context does not bind exact submission payload, role, and target"
                )
        return summary

    @property
    def finding_refs(self) -> tuple[ImportedFindingRef, ...]:
        return tuple(ref for outcome in self.outcomes for ref in outcome.finding_refs)


def _revalidate_submission_summary(
    summary: ReviewSubmissionSummary,
    target_manifest: ReviewTargetManifest,
) -> None:
    ReviewSubmissionSummary.reconstitute(
        target_manifest=target_manifest,
        **{
            name: getattr(summary, name)
            for name in ReviewSubmissionSummary.__dataclass_fields__
        },
    )


def _validate_submission_attachment(
    *,
    review_round_id: ReviewRoundId,
    production_id: ProductionId,
    edition_ref: EditionRef,
    rubric_ref: RubricRef,
    target_manifest: ReviewTargetManifest,
    package_schema_version: int,
    reviewer_assignments: tuple[ReviewerAssignment, ...],
    existing_submissions: tuple[ReviewSubmissionSummary, ...],
    summary: ReviewSubmissionSummary,
    allow_semantic_replay: bool,
) -> ReviewSubmissionSummary | None:
    if type(summary) is not ReviewSubmissionSummary:
        raise ValidationError("summary must be an exact ReviewSubmissionSummary")
    _revalidate_submission_summary(summary, target_manifest)
    if (
        summary.review_round_id != review_round_id
        or summary.production_id != production_id
        or summary.edition_ref != edition_ref
        or summary.rubric_ref != rubric_ref
        or summary.target_manifest_ref != target_manifest.ref
        or summary.submission_schema_version != package_schema_version
    ):
        raise ValidationError("submission summary does not match its review round")
    assignment = next(
        (
            value
            for value in reviewer_assignments
            if value.actor_id == summary.assigned_actor_id and value.role == summary.role
        ),
        None,
    )
    if assignment is None:
        raise ValidationError("submission actor and role are not assigned")
    if summary.assurance.credential != assignment.credential:
        raise ValidationError("submission assurance does not use the assigned credential")
    if not assurance_satisfies(summary.assurance.assurance, assignment.minimum_assurance):
        raise ValidationError("submission assurance is below the assignment minimum")

    semantic_match = next(
        (
            value
            for value in existing_submissions
            if value.submission_digest == summary.submission_digest
        ),
        None,
    )
    if semantic_match is not None:
        if allow_semantic_replay and _submission_replay_equivalent(semantic_match, summary):
            return semantic_match
        raise ValidationError("semantic submission replay conflicts with stored evidence")

    assignment_submissions = tuple(
        value
        for value in existing_submissions
        if value.assigned_actor_id == summary.assigned_actor_id and value.role == summary.role
    )
    expected_predecessor = (
        assignment_submissions[-1].submission_digest if assignment_submissions else None
    )
    if summary.predecessor_submission_digest != expected_predecessor:
        raise ValidationError("submission predecessor is missing, stale, foreign, or forked")
    if assignment_submissions and any(
        value.review_package_ref.review_package_id
        == summary.review_package_ref.review_package_id
        or value.review_package_ref.artifact == summary.review_package_ref.artifact
        for value in assignment_submissions
    ):
        raise ValidationError(
            "a correction requires a newly issued package ID and outer artifact"
        )
    if any(
        value.review_submission_id == summary.review_submission_id
        for value in existing_submissions
    ):
        raise ValidationError("submission review_submission_id conflicts with prior evidence")
    package_nonce_key = (
        summary.review_package_ref.review_package_id,
        summary.client_submission_nonce,
    )
    if any(
        (
            value.review_package_ref.review_package_id,
            value.client_submission_nonce,
        )
        == package_nonce_key
        for value in existing_submissions
    ):
        raise ValidationError("submission package-local nonce conflicts with prior evidence")
    historical_refs = tuple(
        ref for value in existing_submissions for ref in value.finding_refs
    )
    for ref in summary.finding_refs:
        if any(
            historical.review_finding_id == ref.review_finding_id
            or historical.finding_payload_digest == ref.finding_payload_digest
            for historical in historical_refs
        ):
            raise ValidationError("submission reuses historical finding identity or payload")
        finding_nonce_key = (
            summary.review_package_ref.review_package_id,
            ref.client_finding_nonce,
        )
        if any(
            (
                value.review_package_ref.review_package_id,
                historical.client_finding_nonce,
            )
            == finding_nonce_key
            for value in existing_submissions
            for historical in value.finding_refs
        ):
            raise ValidationError("submission finding package-local nonce conflicts")
    return None


def _revalidate_sign_off(sign_off: ReviewSignOff) -> None:
    ReviewSignOff(
        sign_off.credential,
        sign_off.assurance,
        sign_off.role,
        sign_off.target_kind,
        sign_off.target_ref,
        sign_off.decision,
        sign_off.signed_at_us,
        sign_off.sign_off_digest,
    )


def _validate_sign_off_attachment(
    *,
    target_ref: ReviewTargetManifestRef,
    sign_off_requirements: tuple[ReviewSignOffRequirement, ...],
    existing_sign_offs: tuple[ReviewSignOff, ...],
    sign_off: ReviewSignOff,
) -> None:
    if type(sign_off) is not ReviewSignOff:
        raise ValidationError("sign_off must be an exact ReviewSignOff")
    _revalidate_sign_off(sign_off)
    if sign_off.target_ref != target_ref:
        raise ValidationError("sign-off does not bind the exact review target")
    requirement = next(
        (
            value
            for value in sign_off_requirements
            if value.actor_id == sign_off.credential.actor_id and value.role == sign_off.role
        ),
        None,
    )
    if requirement is None:
        raise ValidationError("sign-off actor and role are not declared requirements")
    if sign_off.credential != requirement.credential:
        raise ValidationError("sign-off does not use the required credential")
    if not assurance_satisfies(
        sign_off.assurance.assurance, requirement.minimum_assurance
    ):
        raise ValidationError("sign-off assurance is below the declared minimum")
    duplicate_key = (
        sign_off.role,
        sign_off.credential.actor_id,
        sign_off.target_ref.semantic_digest,
    )
    if any(
        (value.role, value.credential.actor_id, value.target_ref.semantic_digest)
        == duplicate_key
        for value in existing_sign_offs
    ):
        raise ValidationError("a sign-off already exists for this actor, role, and target")


@dataclass(frozen=True, slots=True, init=False)
class OpenReviewContext:
    review_round_id: ReviewRoundId
    target_digest: ContentDigest
    edition_ref: EditionRef
    rubric_ref: RubricRef
    members: tuple[ReviewTargetMember, ...]
    _round: ReviewRound

    @classmethod
    def _from_round(cls, round_: ReviewRound) -> OpenReviewContext:
        context = object.__new__(cls)
        object.__setattr__(context, "review_round_id", round_.review_round_id)
        object.__setattr__(context, "target_digest", round_.target_manifest.semantic_digest)
        object.__setattr__(context, "edition_ref", round_.edition_ref)
        object.__setattr__(context, "rubric_ref", round_.rubric_ref)
        object.__setattr__(context, "members", round_.target_manifest.members)
        object.__setattr__(context, "_round", round_)
        return context

    def _require_open(self) -> None:
        if type(self._round) is not ReviewRound or self._round.state is not ReviewRoundState.OPEN:
            raise ValidationError("review-round authorization is no longer open")
        if self != OpenReviewContext._from_round(self._round):
            raise ValidationError("review-round authorization context is stale or forged")


class ReviewRound(AggregateEventRecorder):
    __slots__ = (
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
        "_sealed",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("ReviewRound state is behavior-only")
        object.__setattr__(self, name, value)

    def _write(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)

    @classmethod
    def open(
        cls,
        *,
        review_round_id: ReviewRoundId,
        production_id: ProductionId,
        edition_ref: EditionRef,
        target_manifest: ReviewTargetManifest,
        rubric_ref: RubricRef,
        package_schema_version: int,
        reviewer_assignments: tuple[ReviewerAssignment, ...],
        sign_off_requirements: tuple[ReviewSignOffRequirement, ...],
        opened_by: ActorId,
        opened_at_us: int,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ReviewRound:
        for field_name, value, expected in (
            ("review_round_id", review_round_id, ReviewRoundId),
            ("production_id", production_id, ProductionId),
            ("edition_ref", edition_ref, EditionRef),
            ("target_manifest", target_manifest, ReviewTargetManifest),
            ("rubric_ref", rubric_ref, RubricRef),
            ("opened_by", opened_by, ActorId),
            ("event_id", event_id, DomainEventId),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if type(package_schema_version) is not int or package_schema_version <= 0:
            raise ValidationError("package_schema_version must be a positive integer")
        for field_name, value in (
            ("opened_at_us", opened_at_us),
            ("event_occurred_at_us", event_occurred_at_us),
        ):
            if type(value) is not int or value <= 0:
                raise ValidationError(f"{field_name} must be a positive integer")
        if type(reviewer_assignments) is not tuple or not all(
            type(value) is ReviewerAssignment for value in reviewer_assignments
        ):
            raise ValidationError("reviewer_assignments must be a tuple of ReviewerAssignment")
        assignment_keys = tuple(
            (value.role.value, value.actor_id.value) for value in reviewer_assignments
        )
        if assignment_keys != tuple(sorted(assignment_keys)) or len(set(assignment_keys)) != len(assignment_keys):
            raise ValidationError("reviewer assignments must be unique and canonical by role and actor")
        if type(sign_off_requirements) is not tuple or not all(
            type(value) is ReviewSignOffRequirement for value in sign_off_requirements
        ):
            raise ValidationError("sign_off_requirements must be a tuple of ReviewSignOffRequirement")
        requirement_keys = tuple(
            (value.role.value, value.actor_id.value) for value in sign_off_requirements
        )
        if requirement_keys != tuple(sorted(requirement_keys)) or len(set(requirement_keys)) != len(requirement_keys):
            raise ValidationError("sign-off requirements must be unique and canonical by role and actor")
        if (
            target_manifest.review_round_id != review_round_id
            or target_manifest.production_id != production_id
            or target_manifest.edition_ref != edition_ref
            or target_manifest.rubric_ref != rubric_ref
        ):
            raise ValidationError("review target snapshot does not match round bindings")

        round_ = cls()
        round_.review_round_id = review_round_id
        round_.production_id = production_id
        round_.edition_ref = edition_ref
        round_.target_manifest = target_manifest
        round_.rubric_ref = rubric_ref
        round_.package_schema_version = package_schema_version
        round_.reviewer_assignments = reviewer_assignments
        round_.sign_off_requirements = sign_off_requirements
        round_.opened_by = opened_by
        round_.opened_at_us = opened_at_us
        round_.state = ReviewRoundState.OPEN
        round_.submissions = ()
        round_.sign_offs = ()
        round_.coverage = None
        round_.evidence_ref = None
        round_.closed_evidence = None
        round_.closed_by = None
        round_.closed_at_us = None
        round_._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "ReviewRoundOpened",
                {
                    "review_round_id": review_round_id.value,
                    "production_id": production_id.value,
                    "edition_digest": edition_ref.content_digest.hex_digest,
                    "target_digest": target_manifest.semantic_digest.hex_digest,
                    "rubric_digest": rubric_ref.content_digest.hex_digest,
                },
            )
        )
        object.__setattr__(round_, "_sealed", True)
        return round_

    @classmethod
    def reconstitute(
        cls,
        *,
        review_round_id: ReviewRoundId,
        production_id: ProductionId,
        edition_ref: EditionRef,
        target_manifest: ReviewTargetManifest,
        rubric_ref: RubricRef,
        package_schema_version: int,
        reviewer_assignments: tuple[ReviewerAssignment, ...],
        sign_off_requirements: tuple[ReviewSignOffRequirement, ...],
        opened_by: ActorId,
        opened_at_us: int,
        state: ReviewRoundState,
        submissions: tuple[ReviewSubmissionSummary, ...],
        sign_offs: tuple[ReviewSignOff, ...],
        closure_snapshot: ReviewClosureSnapshot | None,
        closed_evidence: ClosedReviewEvidence | None,
        closed_by: ActorId | None,
        closed_at_us: int | None,
    ) -> ReviewRound:
        if type(state) is not ReviewRoundState:
            raise ValidationError("state must be a ReviewRoundState")
        if type(submissions) is not tuple or not all(
            type(value) is ReviewSubmissionSummary for value in submissions
        ):
            raise ValidationError("submissions must be a tuple of ReviewSubmissionSummary")
        if type(sign_offs) is not tuple or not all(type(value) is ReviewSignOff for value in sign_offs):
            raise ValidationError("sign_offs must be a tuple of ReviewSignOff")
        round_ = cls.open(
            review_round_id=review_round_id,
            production_id=production_id,
            edition_ref=edition_ref,
            target_manifest=target_manifest,
            rubric_ref=rubric_ref,
            package_schema_version=package_schema_version,
            reviewer_assignments=reviewer_assignments,
            sign_off_requirements=sign_off_requirements,
            opened_by=opened_by,
            opened_at_us=opened_at_us,
            event_id=DomainEventId("00000000-0000-4000-8000-000000000000"),
            event_occurred_at_us=1,
        )
        round_.pull_events()
        validated_submissions: tuple[ReviewSubmissionSummary, ...] = ()
        for summary in submissions:
            _validate_submission_attachment(
                review_round_id=review_round_id,
                production_id=production_id,
                edition_ref=edition_ref,
                rubric_ref=rubric_ref,
                target_manifest=target_manifest,
                package_schema_version=package_schema_version,
                reviewer_assignments=reviewer_assignments,
                existing_submissions=validated_submissions,
                summary=summary,
                allow_semantic_replay=False,
            )
            validated_submissions = (*validated_submissions, summary)
        validated_sign_offs: tuple[ReviewSignOff, ...] = ()
        for sign_off in sign_offs:
            _validate_sign_off_attachment(
                target_ref=target_manifest.ref,
                sign_off_requirements=sign_off_requirements,
                existing_sign_offs=validated_sign_offs,
                sign_off=sign_off,
            )
            validated_sign_offs = (*validated_sign_offs, sign_off)
        round_._write("submissions", validated_submissions)
        round_._write("sign_offs", validated_sign_offs)
        if state is ReviewRoundState.OPEN:
            if (
                closure_snapshot is not None
                or closed_evidence is not None
                or closed_by is not None
                or closed_at_us is not None
            ):
                raise ValidationError("open round must not carry closure state")
            return round_
        if type(closure_snapshot) is not ReviewClosureSnapshot:
            raise ValidationError("closed round requires an exact closure snapshot")
        if type(closed_evidence) is not ClosedReviewEvidence:
            raise ValidationError("closed round requires exact ClosedReviewEvidence")
        if type(closed_by) is not ActorId:
            raise ValidationError("closed round requires closed_by ActorId")
        if type(closed_at_us) is not int or closed_at_us <= 0:
            raise ValidationError("closed round requires positive closed_at_us")
        generated = round_.close(
            closure_snapshot=closure_snapshot,
            closed_by=closed_by,
            closed_at_us=closed_at_us,
            event_id=DomainEventId("00000000-0000-4000-8000-000000000001"),
            event_occurred_at_us=1,
        )
        if generated != closed_evidence:
            raise ValidationError("closed review evidence does not match reconstituted state")
        round_.pull_events()
        return round_

    def open_context(self) -> OpenReviewContext:
        if self.state is not ReviewRoundState.OPEN:
            raise ValidationError("review round is closed")
        return OpenReviewContext._from_round(self)

    def finalize_submission(
        self,
        *,
        summary: ReviewSubmissionSummary,
        findings: tuple[object, ...],
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ReviewSubmissionSummary:
        from .findings import ReviewFinding

        if self.state is not ReviewRoundState.OPEN:
            raise ValidationError("review round is closed")
        if type(summary) is not ReviewSubmissionSummary:
            raise ValidationError("summary must be an exact ReviewSubmissionSummary")
        if type(findings) is not tuple or not all(type(value) is ReviewFinding for value in findings):
            raise ValidationError("findings must be an immutable tuple of ReviewFinding")
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if type(event_occurred_at_us) is not int or event_occurred_at_us <= 0:
            raise ValidationError("event_occurred_at_us must be a positive integer")
        for finding in findings:
            finding.validated_evidence(target_manifest=self.target_manifest)
        refs = summary.finding_refs
        if len(set(findings)) != len(findings):
            raise ValidationError("loaded finding evidence must be unique")
        if len(refs) != len(findings):
            raise ValidationError("submission finding references and evidence must be complete")
        by_id = {value.review_finding_id: value for value in findings}
        for ref in refs:
            finding = by_id.get(ref.review_finding_id)
            if finding is None or (
                finding.review_round_id != self.review_round_id
                or finding.review_submission_id != summary.review_submission_id
                or finding.client_finding_nonce != ref.client_finding_nonce
                or finding.finding_payload_digest != ref.finding_payload_digest
                or finding.target_key != ref.target_key
                or finding.author_actor_id != summary.assigned_actor_id
            ):
                raise ValidationError("submission finding evidence is orphaned or mismatched")
        existing_identical = _validate_submission_attachment(
            review_round_id=self.review_round_id,
            production_id=self.production_id,
            edition_ref=self.edition_ref,
            rubric_ref=self.rubric_ref,
            target_manifest=self.target_manifest,
            package_schema_version=self.package_schema_version,
            reviewer_assignments=self.reviewer_assignments,
            existing_submissions=self.submissions,
            summary=summary,
            allow_semantic_replay=True,
        )
        if existing_identical is not None:
            return existing_identical
        self._write("submissions", (*self.submissions, summary))
        self._record_event(DomainEvent(
            event_id,
            event_occurred_at_us,
            "ReviewSubmissionFinalized",
            {
                "review_round_id": self.review_round_id.value,
                "review_submission_id": summary.review_submission_id.value,
                "submission_digest": summary.submission_digest.hex_digest,
                "assigned_actor_id": summary.assigned_actor_id.value,
                "role": summary.role.value,
            },
        ))
        return summary

    def record_sign_off(
        self,
        *,
        sign_off: ReviewSignOff,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ReviewSignOff:
        if self.state is not ReviewRoundState.OPEN:
            raise ValidationError("review round is closed")
        if type(sign_off) is not ReviewSignOff:
            raise ValidationError("sign_off must be an exact ReviewSignOff")
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if type(event_occurred_at_us) is not int or event_occurred_at_us <= 0:
            raise ValidationError("event_occurred_at_us must be a positive integer")
        _validate_sign_off_attachment(
            target_ref=self.target_manifest.ref,
            sign_off_requirements=self.sign_off_requirements,
            existing_sign_offs=self.sign_offs,
            sign_off=sign_off,
        )
        self._write("sign_offs", (*self.sign_offs, sign_off))
        self._record_event(DomainEvent(
            event_id,
            event_occurred_at_us,
            "ReviewSignOffRecorded",
            {
                "review_round_id": self.review_round_id.value,
                "actor_id": sign_off.credential.actor_id.value,
                "role": sign_off.role.value,
                "target_digest": sign_off.target_ref.semantic_digest.hex_digest,
                "decision": sign_off.decision.value,
                "sign_off_digest": sign_off.sign_off_digest.hex_digest,
            },
        ))
        return sign_off

    def close(
        self,
        *,
        closure_snapshot: ReviewClosureSnapshot,
        closed_by: ActorId,
        closed_at_us: int,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> ClosedReviewEvidence:
        if self.state is not ReviewRoundState.OPEN:
            raise ValidationError("review round is already closed")
        if type(closure_snapshot) is not ReviewClosureSnapshot:
            raise ValidationError("closure_snapshot must be a ReviewClosureSnapshot")
        if type(closed_by) is not ActorId:
            raise ValidationError("closed_by must be an ActorId")
        for field_name, value in (
            ("closed_at_us", closed_at_us),
            ("event_occurred_at_us", event_occurred_at_us),
        ):
            if type(value) is not int or value <= 0:
                raise ValidationError(f"{field_name} must be a positive integer")
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if closure_snapshot.incomplete_import_operation_ids:
            raise ValidationError("review round cannot close with incomplete imports")

        finding_roots = tuple(
            sorted(closure_snapshot.findings, key=lambda value: value.review_finding_id.value)
        )
        findings = tuple(
            value.validated_evidence(target_manifest=self.target_manifest)
            for value in finding_roots
        )
        finding_ids = tuple(value.review_finding_id for value in findings)
        payload_digests = tuple(value.finding_payload_digest for value in findings)
        if len(set(finding_ids)) != len(finding_ids) or len(set(payload_digests)) != len(payload_digests):
            raise ValidationError("closure finding identities and payload digests must be unique")
        if any(value.review_round_id != self.review_round_id for value in findings):
            raise ValidationError("closure contains a foreign finding")
        if any(value.disposition is None for value in findings):
            raise ValidationError("every finding requires a disposition before closure")

        expected_refs = tuple(
            (summary, ref)
            for summary in self.submissions
            for ref in summary.finding_refs
        )
        if len(expected_refs) != len(findings):
            raise ValidationError("closure finding evidence is dangling or incomplete")
        by_id = {value.review_finding_id: value for value in finding_roots}
        for summary, ref in expected_refs:
            finding = by_id.get(ref.review_finding_id)
            if finding is None or (
                finding.review_submission_id != ref.review_submission_id
                or finding.client_finding_nonce != ref.client_finding_nonce
                or finding.target_key != ref.target_key
                or finding.finding_payload_digest != ref.finding_payload_digest
                or finding.author_actor_id != summary.assigned_actor_id
            ):
                raise ValidationError("closure finding evidence does not match finalized submissions")

        ordered_submissions = tuple(
            summary
            for assignment in self.reviewer_assignments
            for summary in self.submissions
            if summary.assigned_actor_id == assignment.actor_id and summary.role == assignment.role
        )
        if len(ordered_submissions) != len(self.submissions):
            raise ValidationError("finalized submission evidence is not assigned canonically")
        coverage = _derive_coverage(
            self.reviewer_assignments,
            ordered_submissions,
            self.target_manifest,
        )
        sign_offs = tuple(sorted(
            self.sign_offs,
            key=lambda value: (
                value.role.value,
                value.credential.actor_id.value,
                value.target_ref.semantic_digest.hex_digest,
                value.sign_off_digest.hex_digest,
            ),
        ))
        closed_evidence = ClosedReviewEvidence.seal(
            target_manifest=self.target_manifest,
            reviewer_assignments=self.reviewer_assignments,
            coverage=coverage,
            submission_summaries=ordered_submissions,
            findings=findings,
            sign_offs=sign_offs,
        )
        evidence_ref = closed_evidence.evidence_ref
        self._write("coverage", coverage)
        self._write("evidence_ref", evidence_ref)
        self._write("closed_evidence", closed_evidence)
        self._write("closed_by", closed_by)
        self._write("closed_at_us", closed_at_us)
        self._write("state", ReviewRoundState.CLOSED)
        self._record_event(DomainEvent(
            event_id,
            event_occurred_at_us,
            "ReviewRoundClosed",
            {
                "review_round_id": self.review_round_id.value,
                "target_digest": self.target_manifest.semantic_digest.hex_digest,
                "evidence_digest": evidence_ref.evidence_digest.hex_digest,
                "closed_by": closed_by.value,
            },
        ))
        return closed_evidence
