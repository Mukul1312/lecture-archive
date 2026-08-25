"""Commands for the offline review workflow.

`OpenReviewRound` and `ImportReviewSubmission` are application *workflows*
rather than single transactions (design section 9.1), but each still enters
through one command value. `SubmitReviewFinding` creates a new root, so it
carries no expected version; the three that mutate an existing `ReviewRound`,
and the one that appends a disposition to a `ReviewFinding`, all do.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.review import (
    FindingDecision,
    ReviewClosureSnapshot,
    ReviewSignOff,
    ReviewSignOffRequirement,
    ReviewSubmissionSummary,
    ReviewTargetManifest,
    ReviewerAssignment,
)
from heritage_production.domain.shared import (
    ActorCredentialRef,
    ArtifactRef,
    EditionRef,
    OperationId,
    ProductionId,
    ReviewFindingId,
    ReviewPackageRef,
    ReviewRoundId,
    RubricRef,
)

from .context import (
    ActorContext,
    require_envelope,
    require_exact,
    require_expected_version,
    require_text,
    require_tuple,
)


@dataclass(frozen=True, slots=True)
class OpenReviewRound:
    """One transaction, but only after every target artifact is verified.

    A failure before the root transaction can leave reportable unreferenced
    artifacts; it can never leave a half-open round.
    """

    operation_id: OperationId
    actor: ActorContext
    review_round_id: ReviewRoundId
    production_id: ProductionId
    edition_ref: EditionRef
    target_manifest: ReviewTargetManifest
    rubric_ref: RubricRef
    package_schema_version: int
    reviewer_assignments: tuple[ReviewerAssignment, ...]
    sign_off_requirements: tuple[ReviewSignOffRequirement, ...]

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_round_id, ReviewRoundId, "review_round_id")
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(self.edition_ref, EditionRef, "edition_ref")
        require_exact(self.target_manifest, ReviewTargetManifest, "target_manifest")
        require_exact(self.rubric_ref, RubricRef, "rubric_ref")
        if type(self.package_schema_version) is not int or self.package_schema_version <= 0:
            from heritage_production.domain.shared import ValidationError

            raise ValidationError("package_schema_version must be a positive integer")
        require_tuple(self.reviewer_assignments, ReviewerAssignment, "reviewer_assignments")
        require_tuple(
            self.sign_off_requirements, ReviewSignOffRequirement, "sign_off_requirements"
        )


@dataclass(frozen=True, slots=True)
class ExportReviewPackage:
    """Creates an artifact only; it mutates no aggregate."""

    operation_id: OperationId
    actor: ActorContext
    review_round_id: ReviewRoundId
    assigned_credential: ActorCredentialRef

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_round_id, ReviewRoundId, "review_round_id")
        require_exact(self.assigned_credential, ActorCredentialRef, "assigned_credential")


@dataclass(frozen=True, slots=True)
class ImportReviewSubmission:
    """A resumable workflow: it stores raw bytes, then submits each finding."""

    operation_id: OperationId
    actor: ActorContext
    review_round_id: ReviewRoundId
    review_package_ref: ReviewPackageRef
    raw_result: ArtifactRef

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_round_id, ReviewRoundId, "review_round_id")
        require_exact(self.review_package_ref, ReviewPackageRef, "review_package_ref")
        require_exact(self.raw_result, ArtifactRef, "raw_result")


@dataclass(frozen=True, slots=True)
class SubmitReviewFinding:
    """Creates a new ReviewFinding root, so there is no version to expect."""

    operation_id: OperationId
    actor: ActorContext
    review_round_id: ReviewRoundId
    review_finding_id: ReviewFindingId
    payload: object

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_round_id, ReviewRoundId, "review_round_id")
        require_exact(self.review_finding_id, ReviewFindingId, "review_finding_id")
        if self.payload is None:
            from heritage_production.domain.shared import ValidationError

            raise ValidationError("payload must be a validated finding payload")


@dataclass(frozen=True, slots=True)
class FinalizeReviewSubmission:
    operation_id: OperationId
    actor: ActorContext
    review_round_id: ReviewRoundId
    summary: ReviewSubmissionSummary
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_round_id, ReviewRoundId, "review_round_id")
        require_exact(self.summary, ReviewSubmissionSummary, "summary")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class DecideReviewFinding:
    """The steward's one append-only disposition; a rejection needs a reason."""

    operation_id: OperationId
    actor: ActorContext
    review_finding_id: ReviewFindingId
    decision: FindingDecision
    rationale: str | None
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_finding_id, ReviewFindingId, "review_finding_id")
        require_exact(self.decision, FindingDecision, "decision")
        if self.rationale is not None:
            require_text(self.rationale, field="rationale")
        if self.decision is FindingDecision.REJECTED and self.rationale is None:
            from heritage_production.domain.shared import ValidationError

            raise ValidationError("a rejected finding requires a nonempty reason")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class RecordReviewSignOff:
    operation_id: OperationId
    actor: ActorContext
    review_round_id: ReviewRoundId
    sign_off: ReviewSignOff
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_round_id, ReviewRoundId, "review_round_id")
        require_exact(self.sign_off, ReviewSignOff, "sign_off")
        require_expected_version(self.expected_version)


@dataclass(frozen=True, slots=True)
class CloseReviewRound:
    """Closing is permanent and freezes a deterministic evidence digest."""

    operation_id: OperationId
    actor: ActorContext
    review_round_id: ReviewRoundId
    closure_snapshot: ReviewClosureSnapshot
    expected_version: int

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.review_round_id, ReviewRoundId, "review_round_id")
        require_exact(self.closure_snapshot, ReviewClosureSnapshot, "closure_snapshot")
        require_expected_version(self.expected_version)


__all__ = [
    "CloseReviewRound",
    "DecideReviewFinding",
    "ExportReviewPackage",
    "FinalizeReviewSubmission",
    "ImportReviewSubmission",
    "OpenReviewRound",
    "RecordReviewSignOff",
    "SubmitReviewFinding",
]
