"""Explicit synchronous application handlers for Narrator Voice production."""

from __future__ import annotations

from dataclasses import dataclass, replace

from heritage_archive.kernel import ValidationError

from ..domain.authorization import AuthorizationRecord
from ..domain.diary_episode import DiaryEpisode
from ..domain.errors import (
    AmbiguousExternalFailure,
    AuthorizationDenied,
    BudgetDenied,
    DefinitePreSendFailure,
    ExternalWorkFailed,
    NotFound,
    RevisionConflict,
)
from ..domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    GenerationPreview,
    ListeningOutcome,
    NarrationTake,
    PassageOffset,
    TimedNarrationPackage,
    SubmissionEvidence,
)
from ..domain.ids import (
    AttemptWorkspaceId,
    AuthorizationRecordId,
    AuthorityChangeId,
    BudgetReservationId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeListeningDecisionId,
    EpisodeSpeechMasterId,
    GenerationAttemptId,
    GenerationPreviewId,
    MasterListeningDecisionId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    NarrationMasterSnapshotId,
    ReviewDecisionId,
    SelectionDecisionId,
    TakeId,
    TimedNarrationPackageId,
)
from ..domain.narration_job import prepare_lane_b_diary_job, prepare_lane_c_intro_job
from ..domain.values import AuthorityOperation, EffectiveSynthesisInput, Lane, NonNegativeDecimal
from .commands import (
    EstimateGenerationCommand,
    AssembleNarrationMasterCommand,
    AssembleEpisodeSpeechMasterCommand,
    AttachDiaryMasterCommand,
    AttachIntroMasterCommand,
    BuildTimedNarrationPackageCommand,
    ExportPresentationHandoffCommand,
    GeneratePendingPassagesCommand,
    GenerateTakeCommand,
    IssueNarrationMasterSnapshotCommand,
    PrepareDiaryNarrationCommand,
    PrepareDiaryEpisodeCommand,
    PrepareIntroNarrationCommand,
    RecordNarrationMasterListeningCommand,
    RecordEpisodeListeningCommand,
    RecordTimingCorrectionCommand,
    RecordReviewDecisionCommand,
    RecordAuthorizationChangeCommand,
    ReconcileGenerationAttemptCommand,
    ReconcileNarrationAssemblyAttemptCommand,
    ReconcileEpisodeAssemblyAttemptCommand,
    ReorderPassagesCommand,
    RequireDictionaryCommand,
    RegisterAuthorizationCommand,
    RequireRenderRecipeCommand,
    ReviseDeliveryDefaultsCommand,
    RevisePassageTextCommand,
    SelectWorkingTakeCommand,
    SetIntroDiaryGapCommand,
    ShowEpisodeStatusCommand,
    ShowNarrationStatusCommand,
    ShowAuthorizationStatusCommand,
    ValidateRenderRecipeCommand,
)
from .ports import (
    ActorResolver,
    AuthorizationRecordRepository,
    AuthorizationStatusReader,
    Clock,
    AttemptWorkspaceStore,
    GenerationBudgetLedger,
    DryPcmAssembler,
    DryPcmSource,
    IdentifierSource,
    ImmutableArtifactStore,
    MediaInspector,
    NarrationJobRepository,
    DiaryEpisodeRepository,
    RecipeCompileRequest,
    RecipeCompiler,
    SynthesisGateway,
    TimingNormalizer,
    TimingNormalizationRequest,
)
from .results import (
    AuthorizationResult,
    AuthorizationStatusResult,
    GenerationEstimateResult,
    GenerationBatchResult,
    GenerationRunResult,
    NarrationMutationResult,
    NarrationAssemblyResult,
    NarrationPreparedResult,
    NarrationStatusResult,
    EpisodeAssemblyResult,
    EpisodeMutationResult,
    EpisodeStatusResult,
    PresentationHandoffResult,
    SnapshotIssuedResult,
    TimedPackageResult,
)


def _cas_or_conflict(saved: bool, aggregate: str) -> None:
    if not saved:
        raise RevisionConflict(f"{aggregate} compare-and-swap refused the mutation")


@dataclass(frozen=True, slots=True)
class RegisterAuthorizationHandler:
    repository: AuthorizationRecordRepository
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RegisterAuthorizationCommand) -> AuthorizationResult:
        actor_id = self.actors.resolve_actor(command.principal)
        now = self.clock.now()
        record_id = self.identifiers.new_id(AuthorizationRecordId)
        record = AuthorizationRecord.register(record_id, actor_id, command.scope, command.evidence_digest, now)
        _cas_or_conflict(self.repository.save(record, None), "authorization record")
        return AuthorizationResult(command.command_id, record_id, record.revision, record.status_at(now))


@dataclass(frozen=True, slots=True)
class RecordAuthorizationChangeHandler:
    repository: AuthorizationRecordRepository
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RecordAuthorizationChangeCommand) -> AuthorizationResult:
        record = self.repository.load(command.record_id)
        if record is None:
            raise NotFound(f"authorization record {command.record_id} was not found")
        actor_id = self.actors.resolve_actor(command.principal)
        now = self.clock.now()
        change_id = self.identifiers.new_id(AuthorityChangeId)
        if command.withdraw:
            if command.resulting_scope is not None:
                from heritage_archive.kernel import ValidationError

                raise ValidationError("withdrawal cannot also contain a resulting scope")
            record.withdraw(
                change_id,
                actor_id,
                command.reason,
                now,
                expected_revision=command.expected_revision,
            )
        else:
            if command.resulting_scope is None:
                from heritage_archive.kernel import ValidationError

                raise ValidationError("authority narrowing requires a resulting scope")
            record.narrow(
                change_id,
                actor_id,
                command.resulting_scope,
                command.reason,
                now,
                expected_revision=command.expected_revision,
            )
        _cas_or_conflict(
            self.repository.save(record, command.expected_revision),
            "authorization record",
        )
        return AuthorizationResult(command.command_id, record.record_id, record.revision, record.status_at(now))


@dataclass(frozen=True, slots=True)
class ShowAuthorizationStatusHandler:
    reader: AuthorizationStatusReader
    clock: Clock

    def __call__(self, command: ShowAuthorizationStatusCommand) -> AuthorizationStatusResult:
        observation = self.reader.read(command.record_id, self.clock.now())
        return AuthorizationStatusResult(
            command.command_id,
            command.record_id,
            None if observation.snapshot is None else observation.snapshot.record_revision,
            observation.status,
            None if observation.snapshot is None else observation.snapshot.snapshot_digest,
        )


def _active_authority(
    reader: AuthorizationStatusReader,
    contract,
    operation: AuthorityOperation,
    observed_at,
):
    try:
        observation = reader.read(contract.authority_record_id, observed_at)
    except Exception as error:
        raise AuthorizationDenied("current authority could not be read") from error
    if not observation.active or observation.snapshot is None:
        raise AuthorizationDenied("current active authority is required")
    scope = observation.snapshot.scope
    if (
        not scope.covers(operation, observed_at)
        or scope.speaker_binding != contract.speaker_binding
        or scope.voice_binding != contract.voice_binding
        or scope.language != contract.language
        or scope.purpose != contract.purpose
        or scope.intended_episode_id != contract.intended_episode_id
    ):
        raise AuthorizationDenied("current authority does not cover the fixed synthesis contract")
    return observation.snapshot


def _load_job(repository: NarrationJobRepository, job_id):
    job = repository.load(job_id)
    if job is None:
        raise NotFound(f"narration job {job_id} was not found")
    return job


@dataclass(frozen=True, slots=True)
class PrepareDiaryNarrationHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: PrepareDiaryNarrationCommand) -> NarrationPreparedResult:
        if command.contract.lane is not Lane.B:
            raise ValidationError("diary preparation accepts only an explicit Lane-B contract")
        now = self.clock.now()
        _active_authority(self.authority, command.contract, AuthorityOperation.PREFLIGHT, now)
        job_id = self.identifiers.new_id(NarrationJobId)
        job = prepare_lane_b_diary_job(job_id, command.contract, command.defaults, command.passages, now)
        _cas_or_conflict(self.repository.save(job, None), "narration job")
        return NarrationPreparedResult(command.command_id, job_id, job.revision, Lane.B)


@dataclass(frozen=True, slots=True)
class PrepareIntroNarrationHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: PrepareIntroNarrationCommand) -> NarrationPreparedResult:
        if command.contract.lane is not Lane.C:
            raise ValidationError("intro preparation accepts only an explicit Lane-C contract")
        now = self.clock.now()
        _active_authority(self.authority, command.contract, AuthorityOperation.PREFLIGHT, now)
        job_id = self.identifiers.new_id(NarrationJobId)
        job = prepare_lane_c_intro_job(job_id, command.contract, command.defaults, command.passages, now)
        _cas_or_conflict(self.repository.save(job, None), "narration job")
        return NarrationPreparedResult(command.command_id, job_id, job.revision, Lane.C)


@dataclass(frozen=True, slots=True)
class ValidateRenderRecipeHandler:
    repository: NarrationJobRepository

    def __call__(self, command: ValidateRenderRecipeCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.record_render_recipe(command.passage_id, command.recipe, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, command.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class RequireRenderRecipeHandler:
    repository: NarrationJobRepository

    def __call__(self, command: RequireRenderRecipeCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.require_render_recipe(command.passage_id, command.recipe_id, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, command.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class EstimateGenerationHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    compiler: RecipeCompiler
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: EstimateGenerationCommand) -> GenerationEstimateResult:
        job = _load_job(self.repository, command.job_id)
        if command.expected_revision != job.revision:
            raise RevisionConflict(
                f"expected narration revision {command.expected_revision!r}, current is {job.revision}"
            )
        passage = job.passage(command.passage_id)
        recipe = passage.recipe(command.recipe_id)
        if passage.required_recipe_id != command.recipe_id:
            raise ValidationError("generation estimate must use the passage's explicitly required recipe")
        if (
            passage.required_dictionary_digest is not None
            and (
                command.settings.dictionary is None
                or command.settings.dictionary.content_digest != passage.required_dictionary_digest
            )
        ):
            raise ValidationError("generation estimate settings do not satisfy the required dictionary digest")
        now = self.clock.now()
        authority = _active_authority(self.authority, job.contract, AuthorityOperation.PREFLIGHT, now)
        compiled = self.compiler.compile(
            RecipeCompileRequest(
                job.job_id,
                passage.current_text_revision.revision,
                passage.current_text_revision.text,
                recipe,
                command.settings,
                job.contract,
                authority,
            )
        )
        preview = GenerationPreview.create(
            preview_id=self.identifiers.new_id(GenerationPreviewId),
            base_job_revision=job.revision,
            passage_id=passage.passage_id,
            text_revision=passage.current_text_revision.revision,
            text_digest=passage.current_text_revision.text.digest,
            recipe_id=recipe.recipe_id,
            recipe_revision=recipe.revision,
            recipe_digest=recipe.digest,
            settings=command.settings,
            contract_digest=job.contract.digest,
            authority_snapshot=authority,
            compiler_version=compiled.compiler_version,
            capability_snapshot=job.contract.capability_snapshot,
            endpoint=compiled.endpoint,
            rendered_transcript=compiled.rendered_transcript,
            canonical_projection=compiled.canonical_projection,
            timestamps_requested=compiled.timestamps_requested,
            normalization=compiled.normalization,
            output_audio=job.contract.audio,
            billable_rule=compiled.billable_rule,
            estimated_usage=compiled.estimated_usage.value,
            issued_at=now,
        )
        job.issue_generation_preview(preview, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return GenerationEstimateResult(command.command_id, job.job_id, job.revision, preview)


def _find_preview(job, preview_id):
    preview = next((value for value in job.previews if value.preview_id == preview_id), None)
    if preview is None:
        raise NotFound(f"generation preview {preview_id} was not found in narration job {job.job_id}")
    return preview


def _require_confirmed_preview_authority(
    reader: AuthorizationStatusReader,
    job,
    preview: GenerationPreview,
    observed_at,
):
    current = _active_authority(reader, job.contract, AuthorityOperation.GENERATE, observed_at)
    if (
        current.record_revision != preview.authority_snapshot.record_revision
        or current.record_digest != preview.authority_snapshot.record_digest
        or current.scope != preview.authority_snapshot.scope
    ):
        raise AuthorizationDenied("confirmed preview authority evidence is no longer current")
    return current


def _workspace(
    workspace_id: AttemptWorkspaceId,
    job,
    attempt_id: GenerationAttemptId,
    reservation_id: BudgetReservationId,
    preview: GenerationPreview,
    state: AttemptState,
    submission: SubmissionEvidence,
    *,
    effective_input=None,
    events=(),
    artifact=None,
    recovery=(),
):
    return AttemptWorkspaceEvidence(
        workspace_id,
        AttemptKind.GENERATION,
        job.job_id.value,
        attempt_id.value,
        preview.base_job_revision,
        reservation_id,
        preview.preview_digest,
        None if effective_input is None else effective_input.request_digest,
        submission,
        events,
        () if artifact is None else (artifact.reference,),
        () if artifact is None else (artifact,),
        recovery,
        state,
    )


@dataclass(frozen=True, slots=True)
class GenerateTakeHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource
    budget: GenerationBudgetLedger
    gateway: SynthesisGateway
    artifacts: ImmutableArtifactStore
    media: MediaInspector
    workspaces: AttemptWorkspaceStore

    def _record_post_external_cas_unknown(
        self,
        command: GenerateTakeCommand,
        attempt_id,
        reservation_id,
        workspace_id,
        preview,
        effective_input,
        generated,
        artifact,
    ) -> GenerationRunResult:
        recovered = _load_job(self.repository, command.job_id)
        attempt = recovered.generation_attempt(attempt_id)
        if not attempt.state.terminal:
            previous = recovered.revision
            recovered.finalize_generation_outcome(
                attempt_id,
                AttemptState.UNKNOWN,
                SubmissionEvidence.AMBIGUOUS,
                "repository CAS failed after external work; recovery evidence is incomplete",
                self.clock.now(),
                expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(recovered, previous), "narration job recovery")
        self.budget.hold(reservation_id, "post-provider repository CAS conflict")
        self.workspaces.save(
            _workspace(
                workspace_id, recovered, attempt_id, reservation_id, preview,
                AttemptState.UNKNOWN, SubmissionEvidence.AMBIGUOUS,
                effective_input=effective_input, events=generated.events,
                artifact=artifact,
                recovery=("post-provider repository CAS conflict",),
            )
        )
        return GenerationRunResult(
            command.command_id, recovered.job_id, recovered.revision, attempt_id,
            AttemptState.UNKNOWN, None, "held",
        )

    def __call__(self, command: GenerateTakeCommand) -> GenerationRunResult:
        job = _load_job(self.repository, command.job_id)
        preview = _find_preview(job, command.preview_id)
        now = self.clock.now()
        attempt_id = self.identifiers.new_id(GenerationAttemptId)
        reservation_id = self.identifiers.new_id(BudgetReservationId)
        workspace_id = self.identifiers.new_id(AttemptWorkspaceId)

        # The reservation CAS is deliberately first: a refusal cannot spend budget or call outward.
        job.reserve_generation_attempt(
            attempt_id,
            reservation_id,
            preview.preview_id,
            now,
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        self.workspaces.save(
            _workspace(
                workspace_id, job, attempt_id, reservation_id, preview,
                AttemptState.RESERVED, SubmissionEvidence.NOT_STARTED,
            )
        )
        try:
            self.budget.reserve(reservation_id, NonNegativeDecimal(preview.estimated_usage))
        except BudgetDenied as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.BLOCKED, SubmissionEvidence.NOT_STARTED,
                "budget reservation denied", now, expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.workspaces.save(
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.BLOCKED, SubmissionEvidence.NOT_STARTED,
                    recovery=(str(error),),
                )
            )
            return GenerationRunResult(
                command.command_id, job.job_id, job.revision, attempt_id,
                AttemptState.BLOCKED, None, "denied",
            )

        try:
            _require_confirmed_preview_authority(self.authority, job, preview, now)
        except AuthorizationDenied as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.BLOCKED, SubmissionEvidence.NOT_STARTED,
                "authority changed after reservation", now, expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.budget.release(reservation_id, "authority changed before external work")
            self.workspaces.save(
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.BLOCKED, SubmissionEvidence.NOT_STARTED,
                    recovery=(str(error),),
                )
            )
            return GenerationRunResult(
                command.command_id, job.job_id, job.revision, attempt_id,
                AttemptState.BLOCKED, None, "released",
            )

        passage = job.passage(preview.passage_id)
        billable_characters = int(preview.estimated_usage) if preview.estimated_usage.isdigit() else len(preview.canonical_projection)
        effective_input = EffectiveSynthesisInput.create(
            job_id=job.job_id,
            lane=job.lane,
            passage_id=preview.passage_id,
            text_revision=preview.text_revision,
            text=passage.current_text_revision.text,
            recipe_id=preview.recipe_id,
            recipe_revision=preview.recipe_revision,
            recipe_digest=preview.recipe_digest,
            compiler_version=preview.compiler_version,
            settings=preview.settings,
            contract_digest=preview.contract_digest,
            authority_scope=preview.authority_snapshot.scope,
            authority_revision=preview.authority_snapshot.record_revision,
            authority_digest=preview.authority_snapshot.record_digest,
            authority_observed_at=preview.authority_snapshot.observed_at,
            endpoint=preview.endpoint,
            api_schema=job.contract.api_schema,
            capability_snapshot=preview.capability_snapshot,
            rendered_transcript=preview.rendered_transcript,
            canonical_projection=preview.canonical_projection,
            timestamps_requested=preview.timestamps_requested,
            normalization=preview.normalization,
            output_audio=preview.output_audio,
            billable_rule=preview.billable_rule,
            billable_characters=billable_characters,
        )
        previous = job.revision
        job.freeze_generation_input(attempt_id, effective_input, expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")

        # This second read is intentionally adjacent to the persisted external-work transition.
        try:
            _require_confirmed_preview_authority(self.authority, job, preview, self.clock.now())
        except AuthorizationDenied as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.BLOCKED, SubmissionEvidence.NOT_STARTED,
                "authority changed immediately before external work", self.clock.now(),
                expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.budget.release(reservation_id, "authority changed before external work")
            self.workspaces.save(
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.BLOCKED, SubmissionEvidence.NOT_STARTED,
                    effective_input=effective_input, recovery=(str(error),),
                )
            )
            return GenerationRunResult(
                command.command_id, job.job_id, job.revision, attempt_id,
                AttemptState.BLOCKED, None, "released",
            )
        previous = job.revision
        job.mark_generation_external_work_started(attempt_id, self.clock.now(), expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")

        try:
            generated = self.gateway.synthesize(effective_input)
        except DefinitePreSendFailure as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.BLOCKED, SubmissionEvidence.DEFINITELY_NOT_SENT,
                "external gateway proved request was not sent", self.clock.now(),
                expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.budget.release(reservation_id, "definite pre-send failure")
            self.workspaces.save(
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.BLOCKED, SubmissionEvidence.DEFINITELY_NOT_SENT,
                    effective_input=effective_input, recovery=(str(error),),
                )
            )
            return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.BLOCKED, None, "released")
        except AmbiguousExternalFailure as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.UNKNOWN, SubmissionEvidence.AMBIGUOUS,
                "external gateway outcome is ambiguous", self.clock.now(),
                expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.budget.hold(reservation_id, "ambiguous external outcome")
            self.workspaces.save(
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.UNKNOWN, SubmissionEvidence.AMBIGUOUS,
                    effective_input=effective_input, recovery=(str(error),),
                )
            )
            return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.UNKNOWN, None, "held")
        except ExternalWorkFailed as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.FAILED, SubmissionEvidence.STARTED,
                "external gateway recorded a definitive failure", self.clock.now(),
                expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.budget.hold(reservation_id, "definitive submitted failure awaits usage evidence")
            self.workspaces.save(
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.FAILED, SubmissionEvidence.STARTED,
                    effective_input=effective_input, recovery=(str(error),),
                )
            )
            return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.FAILED, None, "held")

        media = self.media.inspect_canonical_wav(generated.canonical_wav_bytes)
        artifact = self.artifacts.publish(
            command.artifact_location,
            generated.canonical_wav_bytes,
            "audio/wav",
            self.clock.now(),
        )
        previous = job.revision
        job.stage_generation_artifacts(attempt_id, generated.events, artifact, media, expected_revision=previous)
        if not self.repository.save(job, previous):
            return self._record_post_external_cas_unknown(
                command, attempt_id, reservation_id, workspace_id, preview,
                effective_input, generated, artifact,
            )
        previous = job.revision
        job.mark_generation_artifacts_published(attempt_id, expected_revision=previous)
        if not self.repository.save(job, previous):
            return self._record_post_external_cas_unknown(
                command, attempt_id, reservation_id, workspace_id, preview,
                effective_input, generated, artifact,
            )

        try:
            _require_confirmed_preview_authority(self.authority, job, preview, self.clock.now())
        except AuthorizationDenied as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.QUARANTINED, SubmissionEvidence.COMPLETED,
                "authority changed while external work was in flight", self.clock.now(),
                expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.budget.settle(reservation_id, generated.usage)
            self.workspaces.save(
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.QUARANTINED, SubmissionEvidence.COMPLETED,
                    effective_input=effective_input, events=generated.events,
                    artifact=artifact, recovery=(str(error),),
                )
            )
            return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.QUARANTINED, None, "settled")

        take_id = self.identifiers.new_id(TakeId)
        take = NarrationTake(
            take_id,
            attempt_id,
            job.job_id,
            job.lane,
            effective_input.passage_id,
            effective_input.text_revision,
            effective_input.text.digest,
            effective_input.recipe_id,
            effective_input.recipe_revision,
            effective_input.recipe_digest,
            effective_input.settings,
            effective_input.contract_digest,
            preview.authority_snapshot,
            effective_input,
            artifact,
            media,
            generated.raw_timing_artifacts[0] if generated.raw_timing_artifacts else None,
            self.clock.now(),
        )
        previous = job.revision
        job.complete_generation_attempt(attempt_id, take, self.clock.now(), expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")
        self.budget.settle(reservation_id, generated.usage)
        self.workspaces.save(
            _workspace(
                workspace_id, job, attempt_id, reservation_id, preview,
                AttemptState.COMPLETED, SubmissionEvidence.COMPLETED,
                effective_input=effective_input, events=generated.events, artifact=artifact,
            )
        )
        return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.COMPLETED, take_id, "settled")


@dataclass(frozen=True, slots=True)
class ReconcileGenerationAttemptHandler:
    repository: NarrationJobRepository
    clock: Clock

    def __call__(self, command: ReconcileGenerationAttemptCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.reconcile_generation_attempt(
            command.attempt_id,
            command.outcome,
            command.recorded_evidence,
            self.clock.now(),
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class GeneratePendingPassagesHandler:
    single: GenerateTakeHandler

    def __call__(self, command: GeneratePendingPassagesCommand) -> GenerationBatchResult:
        if len(command.preview_ids) != len(command.artifact_locations):
            raise ValidationError("sequential generation requires one artifact location per preview")
        revision = command.expected_revision
        runs = []
        for preview_id, location in zip(command.preview_ids, command.artifact_locations):
            run = self.single(
                GenerateTakeCommand(command.command_id, command.job_id, preview_id, revision, location)
            )
            runs.append(run)
            revision = run.revision
            if run.state is not AttemptState.COMPLETED:
                break
        return GenerationBatchResult(command.command_id, command.job_id, revision, tuple(runs))


@dataclass(frozen=True, slots=True)
class RevisePassageTextHandler:
    repository: NarrationJobRepository
    clock: Clock

    def __call__(self, command: RevisePassageTextCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.revise_passage_text(
            command.passage_id, command.text, self.clock.now(), expected_revision=command.expected_revision
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class ReorderPassagesHandler:
    repository: NarrationJobRepository

    def __call__(self, command: ReorderPassagesCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.reorder_passages(command.ordered_passage_ids, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class ReviseDeliveryDefaultsHandler:
    repository: NarrationJobRepository
    clock: Clock

    def __call__(self, command: ReviseDeliveryDefaultsCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.revise_delivery_defaults(
            command.defaults, self.clock.now(), expected_revision=command.expected_revision
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class RequireDictionaryHandler:
    repository: NarrationJobRepository

    def __call__(self, command: RequireDictionaryCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.require_dictionary_digest(
            command.passage_id, command.dictionary_digest, expected_revision=command.expected_revision
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class RecordReviewDecisionHandler:
    repository: NarrationJobRepository
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RecordReviewDecisionCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.record_review_decision(
            self.identifiers.new_id(ReviewDecisionId),
            command.take_id,
            self.actors.resolve_actor(command.principal),
            command.authority,
            command.outcome,
            command.notes,
            self.clock.now(),
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class SelectWorkingTakeHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: SelectWorkingTakeCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        now = self.clock.now()
        _active_authority(self.authority, job.contract, AuthorityOperation.GENERATE, now)
        job.select_working_take(
            self.identifiers.new_id(SelectionDecisionId),
            command.passage_id,
            command.take_id,
            self.actors.resolve_actor(command.principal),
            True,
            now,
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


def _narration_assembly_workspace(
    workspace_id,
    job,
    attempt_id,
    state,
    *,
    artifact=None,
    recovery=(),
):
    return AttemptWorkspaceEvidence(
        workspace_id,
        AttemptKind.NARRATION_ASSEMBLY,
        job.job_id.value,
        attempt_id.value,
        job.narration_assembly_attempt(attempt_id).reservation_revision,
        None,
        None,
        None,
        SubmissionEvidence.NOT_STARTED if state in {AttemptState.RESERVED, AttemptState.INPUT_FROZEN} else SubmissionEvidence.COMPLETED,
        (),
        () if artifact is None else (artifact.reference,),
        () if artifact is None else (artifact,),
        recovery,
        state,
    )


@dataclass(frozen=True, slots=True)
class AssembleNarrationMasterHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource
    assembler: DryPcmAssembler
    artifacts: ImmutableArtifactStore
    workspaces: AttemptWorkspaceStore

    def __call__(self, command: AssembleNarrationMasterCommand) -> NarrationAssemblyResult:
        job = _load_job(self.repository, command.job_id)
        now = self.clock.now()
        _active_authority(self.authority, job.contract, AuthorityOperation.ASSEMBLE, now)
        attempt_id = self.identifiers.new_id(NarrationAssemblyAttemptId)
        workspace_id = self.identifiers.new_id(AttemptWorkspaceId)
        job.reserve_narration_assembly(
            attempt_id, command.gaps_samples, True, now, expected_revision=command.expected_revision
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        self.workspaces.save(_narration_assembly_workspace(workspace_id, job, attempt_id, AttemptState.RESERVED))
        previous = job.revision
        job.freeze_narration_assembly_input(attempt_id, expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")
        try:
            _active_authority(self.authority, job.contract, AuthorityOperation.ASSEMBLE, self.clock.now())
        except AuthorizationDenied as error:
            previous = job.revision
            job.finalize_narration_assembly_outcome(
                attempt_id, AttemptState.BLOCKED, "authority changed before dry assembly",
                self.clock.now(), expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.workspaces.save(
                _narration_assembly_workspace(
                    workspace_id, job, attempt_id, AttemptState.BLOCKED, recovery=(str(error),)
                )
            )
            return NarrationAssemblyResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.BLOCKED, None)
        previous = job.revision
        job.mark_narration_assembly_work_started(attempt_id, expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")
        attempt = job.narration_assembly_attempt(attempt_id)
        selected = tuple(job.take(value) for value in attempt.selected_take_ids)
        sources = tuple(DryPcmSource(value.artifact, value.media) for value in selected)
        source_offsets = tuple(
            PassageOffset(
                value.passage_id, value.text_revision, value.text_digest, 0, value.media.sample_count
            )
            for value in selected
        )
        assembled = self.assembler.assemble_narration(sources, command.gaps_samples, source_offsets)
        artifact = self.artifacts.publish(
            command.artifact_location, assembled.canonical_wav_bytes, "audio/wav", self.clock.now()
        )
        previous = job.revision
        job.stage_narration_master(
            attempt_id, artifact, assembled.media, assembled.passage_offsets, expected_revision=previous
        )
        _cas_or_conflict(self.repository.save(job, previous), "narration job")
        previous = job.revision
        job.mark_narration_master_published(attempt_id, expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")
        try:
            _active_authority(self.authority, job.contract, AuthorityOperation.ASSEMBLE, self.clock.now())
        except AuthorizationDenied as error:
            previous = job.revision
            job.finalize_narration_assembly_outcome(
                attempt_id, AttemptState.QUARANTINED, "authority changed during dry assembly",
                self.clock.now(), expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(job, previous), "narration job")
            self.workspaces.save(
                _narration_assembly_workspace(
                    workspace_id, job, attempt_id, AttemptState.QUARANTINED,
                    artifact=artifact, recovery=(str(error),),
                )
            )
            return NarrationAssemblyResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.QUARANTINED, None)
        master_id = self.identifiers.new_id(NarrationMasterId)
        previous = job.revision
        job.complete_narration_assembly(attempt_id, master_id, self.clock.now(), expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")
        self.workspaces.save(
            _narration_assembly_workspace(
                workspace_id, job, attempt_id, AttemptState.COMPLETED, artifact=artifact
            )
        )
        return NarrationAssemblyResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.COMPLETED, master_id)


@dataclass(frozen=True, slots=True)
class RecordNarrationMasterListeningHandler:
    repository: NarrationJobRepository
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RecordNarrationMasterListeningCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.record_narration_master_listening(
            self.identifiers.new_id(MasterListeningDecisionId),
            command.master_id,
            self.actors.resolve_actor(command.principal),
            command.outcome,
            command.notes,
            self.clock.now(),
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class IssueNarrationMasterSnapshotHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: IssueNarrationMasterSnapshotCommand) -> SnapshotIssuedResult:
        job = _load_job(self.repository, command.job_id)
        now = self.clock.now()
        authority = _active_authority(self.authority, job.contract, AuthorityOperation.ATTACH, now)
        snapshot = job.issue_narration_master_snapshot(
            self.identifiers.new_id(NarrationMasterSnapshotId),
            command.master_id,
            authority,
            True,
            now,
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return SnapshotIssuedResult(command.command_id, job.job_id, job.revision, snapshot)


@dataclass(frozen=True, slots=True)
class ShowNarrationStatusHandler:
    repository: NarrationJobRepository

    def __call__(self, command: ShowNarrationStatusCommand) -> NarrationStatusResult:
        job = _load_job(self.repository, command.job_id)
        return NarrationStatusResult(
            command.command_id, job.job_id, job.revision, job.lane,
            len(job.passages), len(job.takes), len(job.masters), len(job.issued_snapshots),
        )


@dataclass(frozen=True, slots=True)
class ReconcileNarrationAssemblyAttemptHandler:
    repository: NarrationJobRepository
    clock: Clock

    def __call__(self, command: ReconcileNarrationAssemblyAttemptCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.reconcile_narration_assembly(
            command.attempt_id, command.outcome, command.recorded_evidence,
            self.clock.now(), expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


def _load_episode(repository: DiaryEpisodeRepository, episode_id):
    episode = repository.load(episode_id)
    if episode is None:
        raise NotFound(f"diary episode {episode_id} was not found")
    return episode


def _require_current_source_snapshot(
    jobs: NarrationJobRepository,
    authority: AuthorizationStatusReader,
    snapshot,
    operation: AuthorityOperation,
    observed_at,
):
    job = _load_job(jobs, snapshot.issuing_job_id)
    if (
        not job.issued_snapshots
        or job.issued_snapshots[-1] != snapshot
        or job.revision != snapshot.issuing_job_revision + 1
    ):
        raise AuthorizationDenied("attached narration snapshot is no longer the source job's current issued product")
    current = _active_authority(authority, job.contract, operation, observed_at)
    if (
        current.record_revision != snapshot.authority_snapshot.record_revision
        or current.record_digest != snapshot.authority_snapshot.record_digest
        or current.scope != snapshot.authority_snapshot.scope
    ):
        raise AuthorizationDenied("source snapshot authority evidence is no longer current")
    return job


def _require_episode_sources_current(
    episode,
    jobs: NarrationJobRepository,
    authority: AuthorizationStatusReader,
    operation: AuthorityOperation,
    observed_at,
) -> None:
    if episode.intro_snapshot is None or episode.diary_snapshot is None:
        raise AuthorizationDenied("episode source snapshots are incomplete")
    _require_current_source_snapshot(jobs, authority, episode.intro_snapshot, operation, observed_at)
    _require_current_source_snapshot(jobs, authority, episode.diary_snapshot, operation, observed_at)


@dataclass(frozen=True, slots=True)
class PrepareDiaryEpisodeHandler:
    repository: DiaryEpisodeRepository
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: PrepareDiaryEpisodeCommand) -> EpisodeMutationResult:
        episode_id = self.identifiers.new_id(DiaryEpisodeId)
        episode = DiaryEpisode.prepare(episode_id, self.clock.now())
        _cas_or_conflict(self.repository.save(episode, None), "diary episode")
        return EpisodeMutationResult(command.command_id, episode_id, episode.revision)


@dataclass(frozen=True, slots=True)
class AttachIntroMasterHandler:
    repository: DiaryEpisodeRepository
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock

    def __call__(self, command: AttachIntroMasterCommand) -> EpisodeMutationResult:
        episode = _load_episode(self.repository, command.episode_id)
        now = self.clock.now()
        _require_current_source_snapshot(self.jobs, self.authority, command.snapshot, AuthorityOperation.ATTACH, now)
        episode.attach_intro(command.snapshot, now, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)


@dataclass(frozen=True, slots=True)
class AttachDiaryMasterHandler:
    repository: DiaryEpisodeRepository
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock

    def __call__(self, command: AttachDiaryMasterCommand) -> EpisodeMutationResult:
        episode = _load_episode(self.repository, command.episode_id)
        now = self.clock.now()
        _require_current_source_snapshot(self.jobs, self.authority, command.snapshot, AuthorityOperation.ATTACH, now)
        episode.attach_diary(command.snapshot, now, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)


@dataclass(frozen=True, slots=True)
class SetIntroDiaryGapHandler:
    repository: DiaryEpisodeRepository
    clock: Clock

    def __call__(self, command: SetIntroDiaryGapCommand) -> EpisodeMutationResult:
        episode = _load_episode(self.repository, command.episode_id)
        episode.set_intro_diary_gap(
            command.gap_samples, self.clock.now(), expected_revision=command.expected_revision
        )
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)


def _episode_assembly_workspace(workspace_id, episode, attempt_id, state, *, artifact=None, recovery=()):
    return AttemptWorkspaceEvidence(
        workspace_id,
        AttemptKind.EPISODE_ASSEMBLY,
        episode.episode_id.value,
        attempt_id.value,
        episode.episode_assembly_attempt(attempt_id).reservation_revision,
        None,
        None,
        None,
        SubmissionEvidence.NOT_STARTED if state in {AttemptState.RESERVED, AttemptState.INPUT_FROZEN} else SubmissionEvidence.COMPLETED,
        (),
        () if artifact is None else (artifact.reference,),
        () if artifact is None else (artifact,),
        recovery,
        state,
    )


@dataclass(frozen=True, slots=True)
class AssembleEpisodeSpeechMasterHandler:
    repository: DiaryEpisodeRepository
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource
    assembler: DryPcmAssembler
    artifacts: ImmutableArtifactStore
    workspaces: AttemptWorkspaceStore

    def __call__(self, command: AssembleEpisodeSpeechMasterCommand) -> EpisodeAssemblyResult:
        episode = _load_episode(self.repository, command.episode_id)
        now = self.clock.now()
        _require_episode_sources_current(episode, self.jobs, self.authority, AuthorityOperation.ASSEMBLE, now)
        attempt_id = self.identifiers.new_id(EpisodeAssemblyAttemptId)
        workspace_id = self.identifiers.new_id(AttemptWorkspaceId)
        episode.reserve_episode_assembly(attempt_id, True, now, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        self.workspaces.save(_episode_assembly_workspace(workspace_id, episode, attempt_id, AttemptState.RESERVED))
        previous = episode.revision
        episode.freeze_episode_assembly_input(attempt_id, expected_revision=previous)
        _cas_or_conflict(self.repository.save(episode, previous), "diary episode")
        try:
            _require_episode_sources_current(
                episode, self.jobs, self.authority, AuthorityOperation.ASSEMBLE, self.clock.now()
            )
        except AuthorizationDenied as error:
            previous = episode.revision
            episode.finalize_episode_assembly_outcome(
                attempt_id, AttemptState.BLOCKED, "source authority changed before dry assembly",
                self.clock.now(), expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(episode, previous), "diary episode")
            self.workspaces.save(
                _episode_assembly_workspace(
                    workspace_id, episode, attempt_id, AttemptState.BLOCKED, recovery=(str(error),)
                )
            )
            return EpisodeAssemblyResult(command.command_id, episode.episode_id, episode.revision, attempt_id, AttemptState.BLOCKED, None)
        previous = episode.revision
        episode.mark_episode_assembly_work_started(attempt_id, expected_revision=previous)
        _cas_or_conflict(self.repository.save(episode, previous), "diary episode")
        assert episode.intro_snapshot is not None and episode.diary_snapshot is not None and episode.gap_samples is not None
        assembled = self.assembler.assemble_episode(
            DryPcmSource(episode.intro_snapshot.artifact, episode.intro_snapshot.media),
            DryPcmSource(episode.diary_snapshot.artifact, episode.diary_snapshot.media),
            episode.gap_samples,
            episode.intro_snapshot.passage_offsets,
            episode.diary_snapshot.passage_offsets,
            episode.intro_snapshot.snapshot_digest,
            episode.diary_snapshot.snapshot_digest,
        )
        artifact = self.artifacts.publish(
            command.artifact_location, assembled.canonical_wav_bytes, "audio/wav", self.clock.now()
        )
        previous = episode.revision
        episode.stage_episode_speech_master(
            attempt_id, artifact, assembled.media, assembled.component_offsets, expected_revision=previous
        )
        _cas_or_conflict(self.repository.save(episode, previous), "diary episode")
        previous = episode.revision
        episode.mark_episode_speech_master_published(attempt_id, expected_revision=previous)
        _cas_or_conflict(self.repository.save(episode, previous), "diary episode")
        try:
            _require_episode_sources_current(
                episode, self.jobs, self.authority, AuthorityOperation.ASSEMBLE, self.clock.now()
            )
        except AuthorizationDenied as error:
            previous = episode.revision
            episode.finalize_episode_assembly_outcome(
                attempt_id, AttemptState.QUARANTINED, "source authority changed during dry assembly",
                self.clock.now(), expected_revision=previous,
            )
            _cas_or_conflict(self.repository.save(episode, previous), "diary episode")
            self.workspaces.save(
                _episode_assembly_workspace(
                    workspace_id, episode, attempt_id, AttemptState.QUARANTINED,
                    artifact=artifact, recovery=(str(error),),
                )
            )
            return EpisodeAssemblyResult(command.command_id, episode.episode_id, episode.revision, attempt_id, AttemptState.QUARANTINED, None)
        master_id = self.identifiers.new_id(EpisodeSpeechMasterId)
        previous = episode.revision
        episode.complete_episode_assembly(attempt_id, master_id, self.clock.now(), expected_revision=previous)
        _cas_or_conflict(self.repository.save(episode, previous), "diary episode")
        self.workspaces.save(
            _episode_assembly_workspace(
                workspace_id, episode, attempt_id, AttemptState.COMPLETED, artifact=artifact
            )
        )
        return EpisodeAssemblyResult(command.command_id, episode.episode_id, episode.revision, attempt_id, AttemptState.COMPLETED, master_id)


@dataclass(frozen=True, slots=True)
class RecordEpisodeListeningHandler:
    repository: DiaryEpisodeRepository
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RecordEpisodeListeningCommand) -> EpisodeMutationResult:
        episode = _load_episode(self.repository, command.episode_id)
        episode.record_episode_listening(
            self.identifiers.new_id(EpisodeListeningDecisionId),
            command.master_id,
            self.actors.resolve_actor(command.principal),
            command.outcome,
            command.notes,
            self.clock.now(),
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)


@dataclass(frozen=True, slots=True)
class BuildTimedNarrationPackageHandler:
    repository: DiaryEpisodeRepository
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource
    normalizer: TimingNormalizer

    def __call__(self, command: BuildTimedNarrationPackageCommand) -> TimedPackageResult:
        episode = _load_episode(self.repository, command.episode_id)
        if episode.timing_packages:
            raise ValidationError("initial timed package already exists; use an explicit correction")
        _require_episode_sources_current(
            episode, self.jobs, self.authority, AuthorityOperation.DELIVER, self.clock.now()
        )
        master = episode.speech_master(command.master_id)
        assert episode.intro_snapshot is not None and episode.diary_snapshot is not None
        normalized = self.normalizer.normalize(
            TimingNormalizationRequest(
                episode.episode_id,
                episode.revision,
                master.artifact,
                master.media,
                master.component_offsets,
                episode.intro_snapshot,
                episode.diary_snapshot,
                command.raw_timing_artifacts,
            )
        )
        package = TimedNarrationPackage.create(
            package_id=self.identifiers.new_id(TimedNarrationPackageId),
            version=1,
            episode_id=episode.episode_id,
            episode_revision=episode.revision,
            episode_master=master,
            intro_snapshot_digest=episode.intro_snapshot.snapshot_digest,
            diary_snapshot_digest=episode.diary_snapshot.snapshot_digest,
            cues=normalized.cues,
            raw_timing_artifacts=command.raw_timing_artifacts,
            normalized_timing_artifact=normalized.normalized_timing_artifact,
            validation_results=normalized.validation_results,
            timing_review_status=normalized.review_status,
            authority_snapshots=(
                episode.intro_snapshot.authority_snapshot,
                episode.diary_snapshot.authority_snapshot,
            ),
            source_package_digest=None,
            correction_actor_id=None,
            correction_reason=None,
            created_at=self.clock.now(),
        )
        episode.record_timed_package(package, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return TimedPackageResult(
            command.command_id, episode.episode_id, episode.revision,
            package.package_id, package.version, package.package_digest,
        )


@dataclass(frozen=True, slots=True)
class RecordTimingCorrectionHandler:
    repository: DiaryEpisodeRepository
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RecordTimingCorrectionCommand) -> TimedPackageResult:
        episode = _load_episode(self.repository, command.episode_id)
        _require_episode_sources_current(
            episode, self.jobs, self.authority, AuthorityOperation.DELIVER, self.clock.now()
        )
        source = next(
            (value for value in episode.timing_packages if value.package_id == command.source_package_id),
            None,
        )
        if source is None or not episode.timing_packages or episode.timing_packages[-1] != source:
            raise ValidationError("timing correction must name the latest package")
        master = episode.speech_master(source.episode_master_id)
        corrected = TimedNarrationPackage.create(
            package_id=self.identifiers.new_id(TimedNarrationPackageId),
            version=source.version + 1,
            episode_id=episode.episode_id,
            episode_revision=episode.revision,
            episode_master=master,
            intro_snapshot_digest=source.intro_snapshot_digest,
            diary_snapshot_digest=source.diary_snapshot_digest,
            cues=command.corrected_cues,
            raw_timing_artifacts=source.raw_timing_artifacts,
            normalized_timing_artifact=source.normalized_timing_artifact,
            validation_results=(*source.validation_results, "manual correction recorded"),
            timing_review_status=command.review_status,
            authority_snapshots=source.authority_snapshots,
            source_package_digest=source.package_digest,
            correction_actor_id=self.actors.resolve_actor(command.principal),
            correction_reason=command.reason,
            created_at=self.clock.now(),
        )
        episode.record_timed_package(corrected, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return TimedPackageResult(
            command.command_id, episode.episode_id, episode.revision,
            corrected.package_id, corrected.version, corrected.package_digest,
        )


@dataclass(frozen=True, slots=True)
class ShowEpisodeStatusHandler:
    repository: DiaryEpisodeRepository

    def __call__(self, command: ShowEpisodeStatusCommand) -> EpisodeStatusResult:
        episode = _load_episode(self.repository, command.episode_id)
        latest_master = episode.speech_masters[-1] if episode.speech_masters else None
        latest_listen = next(
            (
                value for value in reversed(episode.listening_decisions)
                if latest_master is not None and value.master_id == latest_master.master_id
            ),
            None,
        )
        return EpisodeStatusResult(
            command.command_id, episode.episode_id, episode.revision, episode.status,
            latest_master is not None,
            latest_listen is not None and latest_listen.outcome is ListeningOutcome.PASSED,
            len(episode.timing_packages),
        )


@dataclass(frozen=True, slots=True)
class ExportPresentationHandoffHandler:
    repository: DiaryEpisodeRepository
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock

    def __call__(self, command: ExportPresentationHandoffCommand) -> PresentationHandoffResult:
        episode = _load_episode(self.repository, command.episode_id)
        _require_episode_sources_current(
            episode, self.jobs, self.authority, AuthorityOperation.DELIVER, self.clock.now()
        )
        package = next(
            (value for value in episode.timing_packages if value.package_id == command.package_id),
            None,
        )
        if package is None or not episode.timing_packages or episode.timing_packages[-1] != package:
            raise ValidationError("presentation handoff requires the latest timed package")
        master = episode.speech_master(package.episode_master_id)
        latest_listening = next(
            (value for value in reversed(episode.listening_decisions) if value.master_id == master.master_id),
            None,
        )
        if latest_listening is None or latest_listening.outcome is not ListeningOutcome.PASSED:
            raise AuthorizationDenied("presentation handoff requires a current passing episode listen")
        return PresentationHandoffResult(
            command.command_id, episode.episode_id, master.master_id, master.artifact,
            package.package_id, package.package_digest, len(package.cues),
            package.normalized_timing_artifact,
        )


@dataclass(frozen=True, slots=True)
class ReconcileEpisodeAssemblyAttemptHandler:
    repository: DiaryEpisodeRepository
    clock: Clock

    def __call__(self, command: ReconcileEpisodeAssemblyAttemptCommand) -> EpisodeMutationResult:
        episode = _load_episode(self.repository, command.episode_id)
        episode.reconcile_episode_assembly(
            command.attempt_id, command.outcome, command.recorded_evidence,
            self.clock.now(), expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)
