"""Redacted, immutable status projections built from trusted aggregate facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from heritage_archive.kernel import ValidationError

from ..domain.authorization import (
    AuthorizationRecord,
    AuthorizationStatus,
)
from ..domain.diary_episode import DiaryEpisode, EpisodeStatus
from ..domain.evidence import (
    AttemptState,
    CueGranularity,
    CueProvenance,
    ListeningOutcome,
    ReviewAuthority,
    ReviewOutcome,
    SubmissionEvidence,
    TimingReviewStatus,
)
from ..domain.ids import (
    AuthorizationRecordId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeListeningDecisionId,
    EpisodeSpeechMasterId,
    GenerationAttemptId,
    GenerationPreviewId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    PassageId,
    PassageRenderRecipeId,
    TakeId,
    TimedNarrationPackageId,
)
from ..domain.narration_job import NarrationJob
from ..domain.values import AuthorityOperation, ComponentRole, Lane, RenderControl
from .ports import AuthorityObservation


@dataclass(frozen=True, slots=True)
class StudioDiscoveryProjection:
    job_ids: tuple[NarrationJobId, ...]
    episode_ids: tuple[DiaryEpisodeId, ...]


@dataclass(frozen=True, slots=True)
class EditorDeliveryControlsProjection:
    speed: str
    volume: str
    emotion: str | None
    dictionary_configured: bool


@dataclass(frozen=True, slots=True)
class EditorRecipeProjection:
    recipe_id: PassageRenderRecipeId
    revision: int
    text_revision: int
    controls: tuple[RenderControl, ...]
    current: bool
    required: bool


@dataclass(frozen=True, slots=True)
class EditorPreviewProjection:
    """Persisted display facts only; this is never generation confirmation authority."""

    preview_id: GenerationPreviewId
    base_job_revision: int
    canonical_projection: str
    billable_characters: int
    estimated_usage: str
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class EditorPassageProjection:
    passage_id: PassageId
    order: int
    text: str
    text_revision: int
    recipes: tuple[EditorRecipeProjection, ...]
    recipe_required: bool
    dictionary_required: bool
    latest_preview: EditorPreviewProjection | None


@dataclass(frozen=True, slots=True)
class NarrationEditorProjection:
    job_id: NarrationJobId
    revision: int
    lane: Lane
    defaults: EditorDeliveryControlsProjection
    passages: tuple[EditorPassageProjection, ...]


def project_narration_editor(job: NarrationJob) -> NarrationEditorProjection:
    if type(job) is not NarrationJob:
        raise ValidationError("narration editor requires a NarrationJob")
    latest_previews = {preview.passage_id: preview for preview in job.previews}
    passages = []
    for passage in job.passages:
        text = passage.current_text_revision
        preview = latest_previews.get(passage.passage_id)
        passages.append(EditorPassageProjection(
            passage.passage_id,
            passage.order,
            text.text.value,
            text.revision,
            tuple(EditorRecipeProjection(
                recipe.recipe_id,
                recipe.revision,
                recipe.text_revision,
                recipe.controls,
                recipe.text_revision == text.revision and recipe.text_digest == text.text.digest,
                recipe.recipe_id == passage.required_recipe_id,
            ) for recipe in passage.recipes),
            passage.required_recipe_id is not None,
            passage.required_dictionary_digest is not None,
            None if preview is None else EditorPreviewProjection(
                preview.preview_id,
                preview.base_job_revision,
                preview.canonical_projection,
                preview.billable_characters,
                preview.estimated_usage,
                preview.issued_at,
            ),
        ))
    defaults = job.defaults
    return NarrationEditorProjection(
        job.job_id,
        job.revision,
        job.lane,
        EditorDeliveryControlsProjection(
            defaults.speed.value, defaults.volume.value, defaults.emotion, defaults.dictionary is not None,
        ),
        tuple(passages),
    )


class AuthorityHistoryKind(str, Enum):
    ATTESTED = "attested"
    NARROWED = "narrowed"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class AuthorityHistoryEntryProjection:
    kind: AuthorityHistoryKind
    resulting_revision: int
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class AuthorizationHistoryProjection:
    record_id: AuthorizationRecordId
    revision: int
    status: AuthorizationStatus
    withdrawn: bool
    valid_from: datetime
    valid_until: datetime
    covered_operations: tuple[AuthorityOperation, ...]
    history: tuple[AuthorityHistoryEntryProjection, ...]


@dataclass(frozen=True, slots=True)
class CurrentAuthorityProjection:
    record_id: AuthorizationRecordId
    status: AuthorizationStatus | None
    record_revision: int | None
    contract_matches: bool
    active_for_contract: bool
    covered_operations: tuple[AuthorityOperation, ...]


@dataclass(frozen=True, slots=True)
class GenerationAttemptProjection:
    attempt_id: GenerationAttemptId
    passage_id: PassageId
    state: AttemptState
    submission: SubmissionEvidence
    terminal: bool
    needs_reconciliation: bool
    output_ready: bool


@dataclass(frozen=True, slots=True)
class TakeProjection:
    take_id: TakeId
    attempt_id: GenerationAttemptId
    text_revision: int
    eligible: bool
    ineligibility_reasons: tuple[str, ...]
    latest_operational_review: ReviewOutcome | None
    latest_qualified_review: ReviewOutcome | None
    selected: bool


@dataclass(frozen=True, slots=True)
class PassageProjection:
    passage_id: PassageId
    order: int
    current_text_revision: int
    recipe_required: bool
    dictionary_required: bool
    selected_take_id: TakeId | None
    ready_for_assembly: bool
    takes: tuple[TakeProjection, ...]


@dataclass(frozen=True, slots=True)
class NarrationAssemblyAttemptProjection:
    attempt_id: NarrationAssemblyAttemptId
    state: AttemptState
    terminal: bool
    needs_reconciliation: bool
    selected_take_count: int
    output_ready: bool


@dataclass(frozen=True, slots=True)
class NarrationMasterProjection:
    master_id: NarrationMasterId
    selected_take_count: int
    source_timing_available_count: int
    current: bool
    attach_ready: bool
    latest_listening: ListeningOutcome | None
    issued_snapshot_count: int


@dataclass(frozen=True, slots=True)
class NarrationStatusProjection:
    job_id: NarrationJobId
    revision: int
    lane: Lane
    current_authority: CurrentAuthorityProjection
    passages: tuple[PassageProjection, ...]
    generation_attempts: tuple[GenerationAttemptProjection, ...]
    assembly_attempts: tuple[NarrationAssemblyAttemptProjection, ...]
    masters: tuple[NarrationMasterProjection, ...]
    assembly_ready: bool


@dataclass(frozen=True, slots=True)
class EpisodeComponentProjection:
    role: ComponentRole
    attached: bool
    source_job_id: NarrationJobId | None
    source_master_id: NarrationMasterId | None
    attached_revision: int | None
    passage_count: int
    source_timing_available_count: int
    source_authority: CurrentAuthorityProjection | None
    source_current: bool
    eligible_operations: tuple[AuthorityOperation, ...]


@dataclass(frozen=True, slots=True)
class EpisodeAssemblyAttemptProjection:
    attempt_id: EpisodeAssemblyAttemptId
    state: AttemptState
    terminal: bool
    needs_reconciliation: bool
    component_count: int
    gap_configured: bool
    output_ready: bool


@dataclass(frozen=True, slots=True)
class EpisodeMasterProjection:
    master_id: EpisodeSpeechMasterId
    component_count: int
    gap_configured: bool
    current: bool
    latest_listening: ListeningOutcome | None


@dataclass(frozen=True, slots=True)
class EpisodeListeningProjection:
    decision_id: EpisodeListeningDecisionId
    master_id: EpisodeSpeechMasterId
    outcome: ListeningOutcome


@dataclass(frozen=True, slots=True)
class TimingConfidenceProjection:
    package_id: TimedNarrationPackageId
    version: int
    confidence: TimingReviewStatus
    cue_count: int
    granularity_counts: tuple[tuple[CueGranularity, int], ...]
    provenance_counts: tuple[tuple[CueProvenance, int], ...]
    validation_count: int
    normalized_timing_available: bool
    source_timing_available_count: int
    current: bool
    is_latest: bool


@dataclass(frozen=True, slots=True)
class EpisodeStatusProjection:
    episode_id: DiaryEpisodeId
    revision: int
    status: EpisodeStatus
    assembly_ready: bool
    gap_samples: int | None
    components: tuple[EpisodeComponentProjection, ...]
    assembly_attempts: tuple[EpisodeAssemblyAttemptProjection, ...]
    masters: tuple[EpisodeMasterProjection, ...]
    listening: tuple[EpisodeListeningProjection, ...]
    timing: tuple[TimingConfidenceProjection, ...]
    delivery_ready: bool


def _require_utc(value: datetime) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError("status observation time must be an aware UTC datetime")


def _sorted_operations(values) -> tuple[AuthorityOperation, ...]:
    return tuple(sorted(values, key=lambda operation: operation.value))


def project_authorization_history(
    record: AuthorizationRecord,
    observed_at: datetime,
) -> AuthorizationHistoryProjection:
    if type(record) is not AuthorizationRecord:
        raise ValidationError("authorization status requires an AuthorizationRecord")
    _require_utc(observed_at)
    scope = record.current_scope
    status = record.status_at(observed_at)
    return AuthorizationHistoryProjection(
        record.record_id,
        record.revision,
        status,
        record.withdrawn,
        scope.valid_from,
        scope.valid_until,
        (
            _sorted_operations(
                operation for operation in scope.operations if scope.covers(operation, observed_at)
            )
            if status is AuthorizationStatus.ACTIVE
            else ()
        ),
        (
            AuthorityHistoryEntryProjection(
                AuthorityHistoryKind.ATTESTED, 1, record.attested_at
            ),
            *(
                AuthorityHistoryEntryProjection(
                    AuthorityHistoryKind(change.kind.value),
                    change.resulting_revision,
                    change.changed_at,
                )
                for change in record.changes
            ),
        ),
    )


def _project_current_authority(
    job: NarrationJob,
    observation: AuthorityObservation | None,
    observed_at: datetime,
) -> CurrentAuthorityProjection:
    expected_record_id = job.contract.authority_record_id
    if observation is None or observation.record_id != expected_record_id:
        return CurrentAuthorityProjection(expected_record_id, None, None, False, False, ())
    snapshot = observation.snapshot
    if snapshot is None or snapshot.record_id != expected_record_id:
        return CurrentAuthorityProjection(
            expected_record_id, observation.status, None, False, False, ()
        )
    scope = snapshot.scope
    contract_matches = (
        scope.speaker_binding == job.contract.speaker_binding
        and scope.voice_binding == job.contract.voice_binding
        and scope.language == job.contract.language
        and scope.purpose == job.contract.purpose
        and scope.intended_episode_id == job.contract.intended_episode_id
    )
    active_for_contract = observation.active and contract_matches
    covered = (
        _sorted_operations(
            operation
            for operation in AuthorityOperation
            if active_for_contract and scope.covers(operation, observed_at)
        )
        if active_for_contract
        else ()
    )
    return CurrentAuthorityProjection(
        expected_record_id,
        observation.status,
        snapshot.record_revision,
        contract_matches,
        active_for_contract,
        covered,
    )


def _latest_review(job: NarrationJob, take_id: TakeId, authority: ReviewAuthority):
    return next(
        (
            review
            for review in reversed(job.reviews)
            if review.take_id == take_id and review.authority is authority
        ),
        None,
    )


def _latest_selection(job: NarrationJob, passage_id: PassageId):
    return next(
        (selection for selection in reversed(job.selections) if selection.passage_id == passage_id),
        None,
    )


def _ineligibility_reasons(eligibility) -> tuple[str, ...]:
    return tuple(
        name
        for name in (
            "text_stale",
            "recipe_ineligible",
            "dictionary_ineligible",
            "contract_ineligible",
            "authority_ineligible",
        )
        if getattr(eligibility, name)
    )


def _current_selected_take_ids(job: NarrationJob, authority_eligible: bool):
    selected = []
    for passage in job.passages:
        selection = _latest_selection(job, passage.passage_id)
        if selection is None:
            return None
        take = next((value for value in job.takes if value.take_id == selection.take_id), None)
        review = None if take is None else _latest_review(job, take.take_id, ReviewAuthority.OPERATIONAL)
        if (
            take is None
            or review is None
            or review.outcome is not ReviewOutcome.ACCEPTED
            or not job.eligibility_for(take, authority_eligible=authority_eligible).eligible
        ):
            return None
        selected.append(take.take_id)
    return tuple(selected)


def project_narration_status(
    job: NarrationJob,
    authority_observation: AuthorityObservation | None,
    observed_at: datetime,
) -> NarrationStatusProjection:
    if type(job) is not NarrationJob or (
        authority_observation is not None
        and type(authority_observation) is not AuthorityObservation
    ):
        raise ValidationError("narration status requires a root and trusted authority observation")
    _require_utc(observed_at)
    current_authority = _project_current_authority(job, authority_observation, observed_at)
    current_authority_eligible = current_authority.active_for_contract
    assembly_authority = AuthorityOperation.ASSEMBLE in current_authority.covered_operations
    selected_for_assembly = _current_selected_take_ids(job, current_authority_eligible)

    passages = []
    for passage in job.passages:
        selection = _latest_selection(job, passage.passage_id)
        take_projections = []
        for take in (value for value in job.takes if value.passage_id == passage.passage_id):
            eligibility = job.eligibility_for(take, authority_eligible=current_authority_eligible)
            operational = _latest_review(job, take.take_id, ReviewAuthority.OPERATIONAL)
            qualified = _latest_review(job, take.take_id, ReviewAuthority.QUALIFIED_ODIA)
            take_projections.append(
                TakeProjection(
                    take.take_id,
                    take.attempt_id,
                    take.text_revision,
                    eligibility.eligible,
                    _ineligibility_reasons(eligibility),
                    None if operational is None else operational.outcome,
                    None if qualified is None else qualified.outcome,
                    selection is not None and selection.take_id == take.take_id,
                )
            )
        selected_take = next(
            (value for value in take_projections if value.selected),
            None,
        )
        passages.append(
            PassageProjection(
                passage.passage_id,
                passage.order,
                passage.current_text_revision.revision,
                passage.required_recipe_id is not None,
                passage.required_dictionary_digest is not None,
                None if selection is None else selection.take_id,
                (
                    selected_take is not None
                    and selected_take.eligible
                    and selected_take.latest_operational_review is ReviewOutcome.ACCEPTED
                    and assembly_authority
                ),
                tuple(take_projections),
            )
        )

    generation_attempts = tuple(
        GenerationAttemptProjection(
            attempt.attempt_id,
            attempt.passage_id,
            attempt.state,
            attempt.submission,
            attempt.state.terminal,
            attempt.state is AttemptState.UNKNOWN,
            attempt.state is AttemptState.COMPLETED and attempt.take_id is not None,
        )
        for attempt in job.generation_attempts
    )
    assembly_attempts = tuple(
        NarrationAssemblyAttemptProjection(
            attempt.attempt_id,
            attempt.state,
            attempt.state.terminal,
            attempt.state is AttemptState.UNKNOWN,
            len(attempt.selected_take_ids),
            attempt.state is AttemptState.COMPLETED and attempt.master_id is not None,
        )
        for attempt in job.assembly_attempts
    )

    master_selected_ids = _current_selected_take_ids(job, current_authority_eligible)
    masters = []
    for master in job.masters:
        latest_listening = next(
            (
                decision
                for decision in reversed(job.master_listening)
                if decision.master_id == master.master_id
            ),
            None,
        )
        current = (
            master_selected_ids is not None
            and master.job_id == job.job_id
            and master.lane is job.lane
            and master.contract_digest == job.contract.digest
            and master.selected_take_ids == master_selected_ids
            and tuple(offset.passage_id for offset in master.passage_offsets)
            == tuple(passage.passage_id for passage in job.passages)
        )
        masters.append(
            NarrationMasterProjection(
                master.master_id,
                len(master.selected_take_ids),
                sum(reference is not None for reference in master.timing_references),
                current,
                (
                    current
                    and AuthorityOperation.ATTACH in current_authority.covered_operations
                    and latest_listening is not None
                    and latest_listening.outcome is ListeningOutcome.PASSED
                ),
                None if latest_listening is None else latest_listening.outcome,
                sum(snapshot.source_master_id == master.master_id for snapshot in job.issued_snapshots),
            )
        )

    return NarrationStatusProjection(
        job.job_id,
        job.revision,
        job.lane,
        current_authority,
        tuple(passages),
        generation_attempts,
        assembly_attempts,
        tuple(masters),
        selected_for_assembly is not None and assembly_authority,
    )


def _missing_authority(record_id: AuthorizationRecordId) -> CurrentAuthorityProjection:
    return CurrentAuthorityProjection(record_id, None, None, False, False, ())


def _counts(values, enum_type):
    values = tuple(values)
    return tuple(
        (member, sum(value is member for value in values))
        for member in enum_type
        if any(value is member for value in values)
    )


def project_episode_status(
    episode: DiaryEpisode,
    source_jobs: tuple[NarrationJob, ...],
    authority_observations: tuple[AuthorityObservation, ...],
    observed_at: datetime,
) -> EpisodeStatusProjection:
    if type(episode) is not DiaryEpisode:
        raise ValidationError("episode status requires a DiaryEpisode")
    if type(source_jobs) is not tuple or any(type(job) is not NarrationJob for job in source_jobs):
        raise ValidationError("episode status source jobs must be an immutable typed tuple")
    if type(authority_observations) is not tuple or any(
        type(observation) is not AuthorityObservation for observation in authority_observations
    ):
        raise ValidationError("episode status authority observations must be an immutable typed tuple")
    if len({job.job_id for job in source_jobs}) != len(source_jobs) or len(
        {observation.record_id for observation in authority_observations}
    ) != len(authority_observations):
        raise ValidationError("episode status source facts must be unambiguous")
    _require_utc(observed_at)
    jobs_by_id = {job.job_id: job for job in source_jobs}
    observations_by_id = {
        observation.record_id: observation for observation in authority_observations
    }

    components = []
    source_current_by_role = {}
    source_operations_by_role = {}
    attachments_by_role = {attachment.role: attachment for attachment in episode.components}
    for role in (ComponentRole.INTRO, ComponentRole.DIARY):
        attachment = attachments_by_role.get(role)
        if attachment is None:
            source_current_by_role[role] = False
            source_operations_by_role[role] = ()
            components.append(
                EpisodeComponentProjection(role, False, None, None, None, 0, 0, None, False, ())
            )
            continue
        snapshot = attachment.snapshot
        source_job = jobs_by_id.get(snapshot.issuing_job_id)
        if source_job is None:
            authority = _missing_authority(snapshot.authority_snapshot.record_id)
            source_current = False
        else:
            authority = _project_current_authority(
                source_job,
                observations_by_id.get(source_job.contract.authority_record_id),
                observed_at,
            )
            source_current = source_job.is_snapshot_current(
                snapshot, authority_eligible=authority.active_for_contract
            )
        source_current_by_role[attachment.role] = source_current
        eligible_operations = authority.covered_operations if source_current else ()
        source_operations_by_role[attachment.role] = eligible_operations
        components.append(
            EpisodeComponentProjection(
                attachment.role,
                True,
                snapshot.issuing_job_id,
                snapshot.source_master_id,
                attachment.resulting_revision,
                len(snapshot.ordered_passage_ids),
                sum(reference is not None for reference in snapshot.timing_references),
                authority,
                source_current,
                eligible_operations,
            )
        )

    assembly_attempts = tuple(
        EpisodeAssemblyAttemptProjection(
            attempt.attempt_id,
            attempt.state,
            attempt.state.terminal,
            attempt.state is AttemptState.UNKNOWN,
            len(attempt.component_snapshot_digests),
            attempt.gap_samples >= 0,
            attempt.state is AttemptState.COMPLETED and attempt.master_id is not None,
        )
        for attempt in episode.assembly_attempts
    )
    current_snapshot_digests = (
        None
        if episode.intro_snapshot is None or episode.diary_snapshot is None
        else (episode.intro_snapshot.snapshot_digest, episode.diary_snapshot.snapshot_digest)
    )
    every_source_current = (
        source_current_by_role.get(ComponentRole.INTRO, False)
        and source_current_by_role.get(ComponentRole.DIARY, False)
    )
    every_source_can_assemble = all(
        AuthorityOperation.ASSEMBLE in source_operations_by_role.get(role, ())
        for role in (ComponentRole.INTRO, ComponentRole.DIARY)
    )
    every_source_can_deliver = all(
        AuthorityOperation.DELIVER in source_operations_by_role.get(role, ())
        for role in (ComponentRole.INTRO, ComponentRole.DIARY)
    )
    master_current = {}
    masters = []
    for master in episode.speech_masters:
        latest_listening = next(
            (
                decision
                for decision in reversed(episode.listening_decisions)
                if decision.master_id == master.master_id
            ),
            None,
        )
        current = (
            every_source_current
            and current_snapshot_digests is not None
            and master.component_snapshot_digests == current_snapshot_digests
            and episode.gap_samples is not None
            and master.gap_samples == episode.gap_samples
        )
        master_current[master.master_id] = current
        masters.append(
            EpisodeMasterProjection(
                master.master_id,
                len(master.component_snapshot_digests),
                episode.gap_samples is not None and master.gap_samples == episode.gap_samples,
                current,
                None if latest_listening is None else latest_listening.outcome,
            )
        )

    listening = tuple(
        EpisodeListeningProjection(decision.decision_id, decision.master_id, decision.outcome)
        for decision in episode.listening_decisions
    )
    timing = []
    latest_package = episode.timing_packages[-1] if episode.timing_packages else None
    for package in episode.timing_packages:
        package_current = (
            master_current.get(package.episode_master_id, False)
            and current_snapshot_digests is not None
            and (package.intro_snapshot_digest, package.diary_snapshot_digest)
            == current_snapshot_digests
        )
        timing.append(
            TimingConfidenceProjection(
                package.package_id,
                package.version,
                package.timing_review_status,
                len(package.cues),
                _counts((cue.granularity for cue in package.cues), CueGranularity),
                _counts((cue.provenance for cue in package.cues), CueProvenance),
                len(package.validation_results),
                package.normalized_timing_artifact is not None,
                len(package.raw_timing_artifacts),
                package_current,
                package is latest_package,
            )
        )

    latest_master = episode.speech_masters[-1] if episode.speech_masters else None
    latest_listening = (
        None
        if latest_master is None
        else next(
            (
                decision
                for decision in reversed(episode.listening_decisions)
                if decision.master_id == latest_master.master_id
            ),
            None,
        )
    )
    delivery_ready = (
        latest_master is not None
        and master_current.get(latest_master.master_id, False)
        and every_source_can_deliver
        and latest_listening is not None
        and latest_listening.outcome is ListeningOutcome.PASSED
        and latest_package is not None
        and timing[-1].current
        and timing[-1].confidence in {
            TimingReviewStatus.VALIDATED,
            TimingReviewStatus.HUMAN_REVIEWED,
        }
    )
    return EpisodeStatusProjection(
        episode.episode_id,
        episode.revision,
        episode.status,
        episode.assembly_ready and every_source_current and every_source_can_assemble,
        episode.gap_samples,
        tuple(components),
        assembly_attempts,
        tuple(masters),
        listening,
        tuple(timing),
        delivery_ready,
    )
