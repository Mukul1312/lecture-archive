"""ReviewRound lifecycle and its immutable child values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
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
    SignOffTargetKind,
    ValidationError,
    semantic_digest,
)

from .targets import ReviewTargetKey, ReviewTargetManifest, ReviewTargetMember, _digest_value
from .signoffs import ReviewSignOff, ReviewSignOffRequirement


_ASSURANCE_STRENGTH = {
    AssuranceLevel.UNVERIFIED: 0,
    AssuranceLevel.STEWARD_ATTESTED: 1,
    AssuranceLevel.VERIFIED_SIGNATURE: 2,
}


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
        from .findings import ReviewFindingEvidence

        if type(self.findings) is not tuple or not all(
            type(value) is ReviewFindingEvidence for value in self.findings
        ):
            raise ValidationError("findings must be a tuple of ReviewFindingEvidence")
        if type(self.incomplete_import_operation_ids) is not tuple or not all(
            type(value) is OperationId for value in self.incomplete_import_operation_ids
        ):
            raise ValidationError("incomplete import IDs must be a tuple of OperationId")
        if len(set(self.incomplete_import_operation_ids)) != len(self.incomplete_import_operation_ids):
            raise ValidationError("incomplete import operation IDs must be unique")


@dataclass(frozen=True, slots=True)
class AssignmentCoverage:
    actor_id: ActorId
    role: RoleCode
    active_submission_id: ReviewSubmissionId | None
    active_submission_digest: ContentDigest | None
    reviewed_target_keys: tuple[ReviewTargetKey, ...]
    unreviewed_target_keys: tuple[ReviewTargetKey, ...]


@dataclass(frozen=True, slots=True)
class ReviewCoverage:
    assignments: tuple[AssignmentCoverage, ...]
    reviewed_target_union: tuple[ReviewTargetKey, ...]
    unreviewed_target_union: tuple[ReviewTargetKey, ...]
    target_count: int
    reviewed_target_count: int


@dataclass(frozen=True, slots=True)
class ClosedReviewEvidence:
    evidence_ref: ReviewEvidenceRef
    edition_ref: EditionRef
    target_manifest_ref: ReviewTargetManifestRef
    coverage: ReviewCoverage
    submission_summaries: tuple[ReviewSubmissionSummary, ...]
    findings: tuple[object, ...]
    sign_offs: tuple[ReviewSignOff, ...]


def _derive_coverage(
    assignments: tuple[ReviewerAssignment, ...],
    submissions: tuple[ReviewSubmissionSummary, ...],
    target_manifest: ReviewTargetManifest,
) -> ReviewCoverage:
    target_keys = tuple(member.target_key for member in target_manifest.members)
    coverage: list[AssignmentCoverage] = []
    for assignment in assignments:
        chain = tuple(
            value for value in submissions
            if value.assigned_actor_id == assignment.actor_id and value.role == assignment.role
        )
        if chain:
            active = chain[-1]
            reviewed = tuple(value.target_key for value in active.outcomes)
            unreviewed = active.unreviewed_target_keys
            active_id = active.review_submission_id
            active_digest = active.submission_digest
        else:
            reviewed = ()
            unreviewed = target_keys
            active_id = None
            active_digest = None
        coverage.append(AssignmentCoverage(
            assignment.actor_id,
            assignment.role,
            active_id,
            active_digest,
            reviewed,
            unreviewed,
        ))
    reviewed_set = {key for item in coverage for key in item.reviewed_target_keys}
    unreviewed_set = {key for item in coverage for key in item.unreviewed_target_keys}
    return ReviewCoverage(
        tuple(coverage),
        tuple(key for key in target_keys if key in reviewed_set),
        tuple(key for key in target_keys if key in unreviewed_set),
        len(target_keys),
        len(reviewed_set),
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
        if summary.assurance.proof is not None:
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
    )

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
        for summary in submissions:
            if (
                summary.review_round_id != review_round_id
                or summary.production_id != production_id
                or summary.edition_ref != edition_ref
                or summary.rubric_ref != rubric_ref
                or summary.target_manifest_ref != target_manifest.ref
            ):
                raise ValidationError("stored submission does not match the review round")
            assignment = next(
                (
                    value for value in reviewer_assignments
                    if value.actor_id == summary.assigned_actor_id and value.role == summary.role
                ),
                None,
            )
            if assignment is None or summary.assurance.credential != assignment.credential:
                raise ValidationError("stored submission has foreign assignment evidence")
            prior = tuple(
                value for value in submissions[: submissions.index(summary)]
                if value.assigned_actor_id == summary.assigned_actor_id and value.role == summary.role
            )
            expected_predecessor = prior[-1].submission_digest if prior else None
            if summary.predecessor_submission_digest != expected_predecessor:
                raise ValidationError("stored submission correction chain is not linear")
        if len({value.review_submission_id for value in submissions}) != len(submissions):
            raise ValidationError("stored submission identities must be unique")
        for sign_off in sign_offs:
            if sign_off.target_ref != target_manifest.ref:
                raise ValidationError("stored sign-off targets another review manifest")
            requirement = next(
                (
                    value for value in sign_off_requirements
                    if value.actor_id == sign_off.credential.actor_id and value.role == sign_off.role
                ),
                None,
            )
            if requirement is None or sign_off.credential != requirement.credential:
                raise ValidationError("stored sign-off is not a declared requirement")
        round_.submissions = submissions
        round_.sign_offs = sign_offs
        if state is ReviewRoundState.OPEN:
            if closed_evidence is not None or closed_by is not None or closed_at_us is not None:
                raise ValidationError("open round must not carry closure state")
            return round_
        if type(closed_evidence) is not ClosedReviewEvidence:
            raise ValidationError("closed round requires exact ClosedReviewEvidence")
        if type(closed_by) is not ActorId:
            raise ValidationError("closed round requires closed_by ActorId")
        if type(closed_at_us) is not int or closed_at_us <= 0:
            raise ValidationError("closed round requires positive closed_at_us")
        generated = round_.close(
            closure_snapshot=ReviewClosureSnapshot(closed_evidence.findings, ()),
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
        if (
            summary.review_round_id != self.review_round_id
            or summary.production_id != self.production_id
            or summary.edition_ref != self.edition_ref
            or summary.rubric_ref != self.rubric_ref
            or summary.target_manifest_ref != self.target_manifest.ref
            or summary.submission_schema_version != self.package_schema_version
        ):
            raise ValidationError("submission summary does not match its review round")
        assignment = next(
            (
                value for value in self.reviewer_assignments
                if value.actor_id == summary.assigned_actor_id and value.role == summary.role
            ),
            None,
        )
        if assignment is None:
            raise ValidationError("submission actor and role are not assigned")
        if summary.assurance.credential != assignment.credential:
            raise ValidationError("submission assurance does not use the assigned credential")
        if _ASSURANCE_STRENGTH[summary.assurance.assurance] < _ASSURANCE_STRENGTH[assignment.minimum_assurance]:
            raise ValidationError("submission assurance is below the assignment minimum")
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
            ):
                raise ValidationError("submission finding evidence is orphaned or mismatched")
        existing_identical = next(
            (value for value in self.submissions if value.submission_digest == summary.submission_digest),
            None,
        )
        if existing_identical is not None:
            if existing_identical != summary:
                raise ValidationError("semantic submission replay conflicts with stored evidence")
            return existing_identical
        assignment_submissions = tuple(
            value for value in self.submissions
            if value.assigned_actor_id == summary.assigned_actor_id and value.role == summary.role
        )
        expected_predecessor = assignment_submissions[-1].submission_digest if assignment_submissions else None
        if summary.predecessor_submission_digest != expected_predecessor:
            raise ValidationError("submission predecessor is missing, stale, foreign, or forked")
        for attribute in ("review_submission_id", "client_submission_nonce", "submission_digest"):
            candidate = getattr(summary, attribute)
            if any(getattr(value, attribute) == candidate for value in self.submissions):
                raise ValidationError(f"submission {attribute} conflicts with prior evidence")
        self.submissions = (*self.submissions, summary)
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
        if sign_off.target_ref != self.target_manifest.ref:
            raise ValidationError("sign-off does not bind the exact review target")
        requirement = next(
            (
                value for value in self.sign_off_requirements
                if value.actor_id == sign_off.credential.actor_id and value.role == sign_off.role
            ),
            None,
        )
        if requirement is None:
            raise ValidationError("sign-off actor and role are not declared requirements")
        if sign_off.credential != requirement.credential:
            raise ValidationError("sign-off does not use the required credential")
        if _ASSURANCE_STRENGTH[sign_off.assurance.assurance] < _ASSURANCE_STRENGTH[requirement.minimum_assurance]:
            raise ValidationError("sign-off assurance is below the declared minimum")
        duplicate_key = (sign_off.role, sign_off.credential.actor_id, sign_off.target_ref.semantic_digest)
        if any(
            (value.role, value.credential.actor_id, value.target_ref.semantic_digest) == duplicate_key
            for value in self.sign_offs
        ):
            raise ValidationError("a sign-off already exists for this actor, role, and target")
        self.sign_offs = (*self.sign_offs, sign_off)
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

        findings = tuple(
            sorted(closure_snapshot.findings, key=lambda value: value.review_finding_id.value)
        )
        finding_ids = tuple(value.review_finding_id for value in findings)
        payload_digests = tuple(value.finding_payload_digest for value in findings)
        if len(set(finding_ids)) != len(finding_ids) or len(set(payload_digests)) != len(payload_digests):
            raise ValidationError("closure finding identities and payload digests must be unique")
        if any(value.review_round_id != self.review_round_id for value in findings):
            raise ValidationError("closure contains a foreign finding")
        if any(value.disposition is None for value in findings):
            raise ValidationError("every finding requires a disposition before closure")

        expected_refs = tuple(ref for summary in self.submissions for ref in summary.finding_refs)
        if len(expected_refs) != len(findings):
            raise ValidationError("closure finding evidence is dangling or incomplete")
        by_id = {value.review_finding_id: value for value in findings}
        for ref in expected_refs:
            finding = by_id.get(ref.review_finding_id)
            if finding is None or (
                finding.review_submission_id != ref.review_submission_id
                or finding.client_finding_nonce != ref.client_finding_nonce
                or finding.target_key != ref.target_key
                or finding.finding_payload_digest != ref.finding_payload_digest
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
        evidence_digest = semantic_digest(
            "heritage-review-evidence-v1",
            _evidence_payload(
                self.target_manifest.semantic_digest,
                ordered_submissions,
                findings,
                coverage,
                sign_offs,
            ),
        )
        evidence_ref = ReviewEvidenceRef(self.review_round_id, evidence_digest)
        closed_evidence = ClosedReviewEvidence(
            evidence_ref,
            self.edition_ref,
            self.target_manifest.ref,
            coverage,
            ordered_submissions,
            findings,
            sign_offs,
        )
        self.coverage = coverage
        self.evidence_ref = evidence_ref
        self.closed_evidence = closed_evidence
        self.closed_by = closed_by
        self.closed_at_us = closed_at_us
        self.state = ReviewRoundState.CLOSED
        self._record_event(DomainEvent(
            event_id,
            event_occurred_at_us,
            "ReviewRoundClosed",
            {
                "review_round_id": self.review_round_id.value,
                "target_digest": self.target_manifest.semantic_digest.hex_digest,
                "evidence_digest": evidence_digest.hex_digest,
                "closed_by": closed_by.value,
            },
        ))
        return closed_evidence
