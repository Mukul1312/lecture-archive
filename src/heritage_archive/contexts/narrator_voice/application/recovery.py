"""Pure, deterministic recovery decisions for externally affected attempts.

This module deliberately has no storage, clock, provider, filesystem, or aggregate
repository dependency.  An adapter/reconciliation handler supplies only verified
private-workspace, artifact, provider-status, and budget facts; this reducer decides
the sole conservative root transition.  It never authorizes a new external call.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from heritage_archive.kernel import ValidationError

from ..domain.evidence import AttemptState, ProviderTerminalClass, SubmissionEvidence
from ..domain.ids import (
    BudgetReservationId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    GenerationAttemptId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
)


@dataclass(frozen=True, slots=True)
class GenerationRecoveryTarget:
    job_id: NarrationJobId
    attempt_id: GenerationAttemptId
    budget_reservation_id: BudgetReservationId

    def __post_init__(self) -> None:
        if (
            type(self.job_id) is not NarrationJobId
            or type(self.attempt_id) is not GenerationAttemptId
            or type(self.budget_reservation_id) is not BudgetReservationId
        ):
            raise ValidationError("generation recovery target requires exact nominal identities")


@dataclass(frozen=True, slots=True)
class NarrationAssemblyRecoveryTarget:
    job_id: NarrationJobId
    attempt_id: NarrationAssemblyAttemptId

    def __post_init__(self) -> None:
        if type(self.job_id) is not NarrationJobId or type(self.attempt_id) is not NarrationAssemblyAttemptId:
            raise ValidationError("narration assembly recovery target requires exact nominal identities")


@dataclass(frozen=True, slots=True)
class EpisodeAssemblyRecoveryTarget:
    episode_id: DiaryEpisodeId
    attempt_id: EpisodeAssemblyAttemptId

    def __post_init__(self) -> None:
        if type(self.episode_id) is not DiaryEpisodeId or type(self.attempt_id) is not EpisodeAssemblyAttemptId:
            raise ValidationError("episode assembly recovery target requires exact nominal identities")


RecoveryTarget: TypeAlias = (
    GenerationRecoveryTarget | NarrationAssemblyRecoveryTarget | EpisodeAssemblyRecoveryTarget
)


class RecoveryStage(str, Enum):
    RESERVED = "reserved"
    INPUT_FROZEN = "input_frozen"
    EXTERNAL_WORK_STARTED = "external_work_started"
    ARTIFACTS_STAGED = "artifacts_staged"
    ARTIFACTS_PUBLISHED = "artifacts_published"


class BudgetRecoveryState(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    UNKNOWN = "unknown"


class BudgetDisposition(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    SETTLED = "settled"
    RELEASE = "release"
    HOLD = "hold"


class RecoveryDisposition(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    UNKNOWN = "unknown"


class RecoveryReason(str, Enum):
    VERIFIED_COMPLETION = "verified_completion"
    PRE_SEND_REFUSAL = "pre_send_refusal"
    DEFINITE_EXTERNAL_FAILURE = "definite_external_failure"
    AMBIGUOUS_EXTERNAL_WORK = "ambiguous_external_work"
    BUDGET_UNVERIFIED = "budget_unverified"
    ARTIFACT_EVIDENCE_MISMATCH = "artifact_evidence_mismatch"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    WORKSPACE_OR_PLAN_MISMATCH = "workspace_or_plan_mismatch"
    TERMINAL_HISTORY = "terminal_history"


@dataclass(frozen=True, slots=True)
class RecoveryFacts:
    """Facts already verified by the application boundary, never browser input."""

    attempt_state: AttemptState
    last_confirmed_stage: RecoveryStage
    workspace_matches_attempt: bool
    frozen_plan_matches: bool
    submission: SubmissionEvidence
    provider_terminal: ProviderTerminalClass | None
    events_sealed: bool
    artifact_verified: bool
    publication_verified: bool
    authority_covers_completion: bool
    requires_budget: bool
    budget_state: BudgetRecoveryState
    artifact_observed: bool = True
    publication_observed: bool = True

    def __post_init__(self) -> None:
        if type(self.attempt_state) is not AttemptState or type(self.last_confirmed_stage) is not RecoveryStage:
            raise ValidationError("recovery attempt state/stage is invalid")
        if type(self.submission) is not SubmissionEvidence:
            raise ValidationError("recovery submission evidence is invalid")
        if self.provider_terminal is not None and type(self.provider_terminal) is not ProviderTerminalClass:
            raise ValidationError("recovery provider terminal evidence is invalid")
        if type(self.budget_state) is not BudgetRecoveryState:
            raise ValidationError("recovery budget state is invalid")
        for value in (
            self.workspace_matches_attempt,
            self.frozen_plan_matches,
            self.events_sealed,
            self.artifact_verified,
            self.publication_verified,
            self.authority_covers_completion,
            self.requires_budget,
            self.artifact_observed,
            self.publication_observed,
        ):
            if type(value) is not bool:
                raise ValidationError("recovery truth values must be exact booleans")
        if self.requires_budget != (self.budget_state is not BudgetRecoveryState.NOT_APPLICABLE):
            raise ValidationError("recovery budget applicability must match its budget state")
        if self.publication_observed and not self.artifact_observed:
            raise ValidationError("a publication cannot exist without an artifact")


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    disposition: RecoveryDisposition
    budget: BudgetDisposition
    reason: RecoveryReason
    may_start_external_work: bool = False

    def __post_init__(self) -> None:
        if type(self.disposition) is not RecoveryDisposition or type(self.budget) is not BudgetDisposition:
            raise ValidationError("recovery decision state is invalid")
        if type(self.reason) is not RecoveryReason or type(self.may_start_external_work) is not bool:
            raise ValidationError("recovery decision evidence is invalid")
        if self.may_start_external_work:
            raise ValidationError("reconciliation must never start external work")


def _budget_for_terminal(facts: RecoveryFacts) -> BudgetDisposition:
    if not facts.requires_budget:
        return BudgetDisposition.NOT_APPLICABLE
    if facts.budget_state is BudgetRecoveryState.SETTLED:
        return BudgetDisposition.SETTLED
    return BudgetDisposition.HOLD


def _decision(
    disposition: RecoveryDisposition,
    budget: BudgetDisposition,
    reason: RecoveryReason,
) -> RecoveryDecision:
    return RecoveryDecision(disposition, budget, reason)


def decide_recovery(facts: RecoveryFacts) -> RecoveryDecision:
    """Derive a conservative, idempotent outcome from trusted recovery facts.

    Completion is intentionally narrow: complete sealed evidence, an exact artifact
    publication, current authority, and (for generation) a settled budget are all
    necessary.  Every other ambiguous post-side-effect condition holds the budget
    and forbids a repeat call.
    """

    if not facts.workspace_matches_attempt or not facts.frozen_plan_matches:
        return _decision(
            RecoveryDisposition.QUARANTINED,
            _budget_for_terminal(facts),
            RecoveryReason.WORKSPACE_OR_PLAN_MISMATCH,
        )

    if facts.attempt_state is AttemptState.BLOCKED:
        return _decision(
            RecoveryDisposition.BLOCKED,
            BudgetDisposition.NOT_APPLICABLE if not facts.requires_budget else BudgetDisposition.RELEASE,
            RecoveryReason.TERMINAL_HISTORY,
        )
    if facts.attempt_state is AttemptState.FAILED:
        return _decision(RecoveryDisposition.FAILED, _budget_for_terminal(facts), RecoveryReason.TERMINAL_HISTORY)
    if facts.attempt_state is AttemptState.QUARANTINED:
        return _decision(RecoveryDisposition.QUARANTINED, _budget_for_terminal(facts), RecoveryReason.TERMINAL_HISTORY)

    if (
        facts.provider_terminal is ProviderTerminalClass.DEFINITE_PRE_SEND_FAILURE
        and facts.submission in {SubmissionEvidence.NOT_STARTED, SubmissionEvidence.DEFINITELY_NOT_SENT}
    ):
        return _decision(
            RecoveryDisposition.BLOCKED,
            BudgetDisposition.NOT_APPLICABLE if not facts.requires_budget else BudgetDisposition.RELEASE,
            RecoveryReason.PRE_SEND_REFUSAL,
        )

    if facts.provider_terminal is ProviderTerminalClass.AMBIGUOUS or facts.submission is SubmissionEvidence.AMBIGUOUS:
        return _decision(RecoveryDisposition.UNKNOWN, _budget_for_terminal(facts), RecoveryReason.AMBIGUOUS_EXTERNAL_WORK)

    if facts.provider_terminal is ProviderTerminalClass.FAILURE:
        if facts.requires_budget and facts.budget_state is not BudgetRecoveryState.SETTLED:
            return _decision(RecoveryDisposition.UNKNOWN, BudgetDisposition.HOLD, RecoveryReason.BUDGET_UNVERIFIED)
        return _decision(RecoveryDisposition.FAILED, _budget_for_terminal(facts), RecoveryReason.DEFINITE_EXTERNAL_FAILURE)

    if facts.requires_budget and facts.budget_state is not BudgetRecoveryState.SETTLED:
        return _decision(RecoveryDisposition.UNKNOWN, BudgetDisposition.HOLD, RecoveryReason.BUDGET_UNVERIFIED)

    if facts.artifact_observed and not facts.artifact_verified:
        return _decision(RecoveryDisposition.QUARANTINED, _budget_for_terminal(facts), RecoveryReason.ARTIFACT_EVIDENCE_MISMATCH)
    if facts.publication_observed and not facts.publication_verified:
        return _decision(RecoveryDisposition.QUARANTINED, _budget_for_terminal(facts), RecoveryReason.ARTIFACT_EVIDENCE_MISMATCH)
    if not facts.events_sealed or not facts.artifact_observed or not facts.publication_observed:
        return _decision(RecoveryDisposition.UNKNOWN, _budget_for_terminal(facts), RecoveryReason.AMBIGUOUS_EXTERNAL_WORK)
    if not facts.authority_covers_completion:
        return _decision(RecoveryDisposition.QUARANTINED, _budget_for_terminal(facts), RecoveryReason.AUTHORITY_UNAVAILABLE)

    # A dry assembly or timing operation has no provider terminal; a generation
    # must have succeeded.  Any other generation status above stayed conservative.
    return _decision(RecoveryDisposition.COMPLETED, _budget_for_terminal(facts), RecoveryReason.VERIFIED_COMPLETION)


def decide_target_recovery(target: RecoveryTarget, facts: RecoveryFacts) -> RecoveryDecision:
    """Apply the reducer only when typed attempt and budget semantics agree.

    Persistence and provider adapters remain responsible for constructing verified
    ``RecoveryFacts``.  This seam prevents an assembly/episode reconciler from
    accidentally borrowing generation's credit ledger semantics.
    """

    if type(target) is GenerationRecoveryTarget:
        if not facts.requires_budget:
            raise ValidationError("generation recovery requires a trusted budget fact")
    elif type(target) in {NarrationAssemblyRecoveryTarget, EpisodeAssemblyRecoveryTarget}:
        if facts.requires_budget:
            raise ValidationError("dry assembly recovery cannot carry a generation budget")
    else:
        raise ValidationError("recovery target is not a supported exact target type")
    return decide_recovery(facts)
