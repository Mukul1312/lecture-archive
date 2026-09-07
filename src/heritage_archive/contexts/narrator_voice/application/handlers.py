"""Explicit synchronous application handlers for Narrator Voice production."""

from __future__ import annotations

from dataclasses import dataclass, replace

from heritage_archive.kernel import ValidationError

from ..domain.authorization import AuthorizationRecord
from ..domain.diary_episode import DiaryEpisode, EpisodeStatus
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
    ComponentOffset,
    CueProvenance,
    DecodedMediaFacts,
    EpisodeSpeechMaster,
    GenerationPreview,
    ListeningOutcome,
    NarrationTake,
    NarrationMaster,
    PassageOffset,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
    TimingReviewStatus,
    TimedNarrationPackage,
    SubmissionEvidence,
    episode_assembly_plan_digest,
    narration_assembly_plan_digest,
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
from ..domain.values import (
    AuthorityOperation,
    ControlProvenance,
    ComponentRole,
    EffectiveSynthesisInput,
    EffectiveTakeSettings,
    FixedTwoDecimal,
    Lane,
    NonNegativeDecimal,
    ResolvedControl,
)
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
    OverrideMode,
    RecipeAuthoringMode,
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
    AuthorityObservation,
    AuthorizationStatusReader,
    Clock,
    AttemptWorkspaceStore,
    AttemptWorkspaceVerifier,
    ArtifactEvidenceVerifier,
    BudgetReservationStatusReader,
    GenerationBudgetLedger,
    DryPcmAssembler,
    DryPcmSource,
    IdentifierSource,
    ImmutableArtifactStore,
    MediaInspector,
    NarrationJobRepository,
    NarrationReleasePolicyResolver,
    DiaryEpisodeRepository,
    RecipeCompileRequest,
    RecipeCompiler,
    SynthesisGateway,
    SynthesisInvocation,
    TimingNormalizer,
    TimingNormalizationRequest,
    TimingSourcePassage,
    RecipeAuthoringRequest,
    ProviderEventVerifier,
)
from .recovery import (
    BudgetDisposition,
    BudgetRecoveryState,
    EpisodeAssemblyRecoveryTarget,
    GenerationRecoveryTarget,
    NarrationAssemblyRecoveryTarget,
    RecoveryDecision,
    RecoveryDisposition,
    RecoveryFacts,
    RecoveryStage,
    decide_target_recovery,
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
    RenderRecipeValidatedResult,
    EpisodeAssemblyResult,
    EpisodeMutationResult,
    EpisodeStatusResult,
    PresentationHandoffResult,
    SnapshotIssuedResult,
    TimedPackageResult,
)
from .synthesis_failures import (
    SynthesisAmbiguousFailure,
    SynthesisFailureEvidence,
    SynthesisPreSendFailure,
    SynthesisSubmittedFailure,
)
from .status import (
    project_authorization_history,
    project_episode_status,
    project_narration_status,
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
        principal = self.actors.resolve_principal(command.principal)
        if not principal.can_administer_authority:
            raise AuthorizationDenied("authority administration requires the configured steward")
        actor_id = principal.actor_id
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
        principal = self.actors.resolve_principal(command.principal)
        if not principal.can_administer_authority:
            raise AuthorizationDenied("authority administration requires the configured steward")
        actor_id = principal.actor_id
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
    repository: AuthorizationRecordRepository
    clock: Clock

    def __call__(self, command: ShowAuthorizationStatusCommand) -> AuthorizationStatusResult:
        record = self.repository.load(command.record_id)
        if record is None:
            raise NotFound(f"authorization record {command.record_id} was not found")
        return project_authorization_history(record, self.clock.now())


def _status_authority_observation(
    reader: AuthorizationStatusReader,
    record_id: AuthorizationRecordId,
    observed_at,
) -> AuthorityObservation:
    try:
        return reader.read(record_id, observed_at)
    except Exception:
        return AuthorityObservation(record_id, None, None)


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


def _recovery_authority_covers(
    reader: AuthorizationStatusReader,
    contract,
    operation: AuthorityOperation,
    observed_at,
) -> bool:
    try:
        _active_authority(reader, contract, operation, observed_at)
    except Exception:
        return False
    return True


def _trusted_recovery_facts(
    *,
    workspaces: AttemptWorkspaceStore,
    workspace_verifier: AttemptWorkspaceVerifier,
    provider_events: ProviderEventVerifier,
    artifacts: ArtifactEvidenceVerifier,
    target,
    attempt_state: AttemptState,
    reservation_revision: int,
    expected_frozen_plan_digest: ContentDigest | None,
    requires_budget: bool,
    budget_state: BudgetRecoveryState,
    authority_covers_completion: bool,
) -> RecoveryFacts:
    """Build recovery facts only from adapters that verify private durable evidence.

    Any missing/corrupt/unreadable source becomes a mismatch, which the reducer
    quarantines; reconciliation never falls back to a caller-provided outcome.
    """
    try:
        workspace = workspaces.load(target.attempt_id)
        workspace_facts = workspace_verifier.verify(
            workspace, target, attempt_state, reservation_revision, expected_frozen_plan_digest
        )
        provider_facts = provider_events.verify(workspace)
        artifact_facts = artifacts.verify(workspace)
        return RecoveryFacts(
            attempt_state=attempt_state,
            last_confirmed_stage=workspace_facts.last_confirmed_stage,
            workspace_matches_attempt=workspace_facts.workspace_matches_attempt,
            frozen_plan_matches=workspace_facts.frozen_plan_matches,
            submission=workspace_facts.submission,
            provider_terminal=provider_facts.provider_terminal,
            events_sealed=provider_facts.events_sealed,
            artifact_observed=artifact_facts.artifact_observed,
            artifact_verified=artifact_facts.artifact_verified,
            publication_observed=artifact_facts.publication_observed,
            publication_verified=artifact_facts.publication_verified,
            authority_covers_completion=authority_covers_completion,
            requires_budget=requires_budget,
            budget_state=budget_state,
        )
    except Exception:
        return RecoveryFacts(
            attempt_state=attempt_state,
            last_confirmed_stage=RecoveryStage.RESERVED,
            workspace_matches_attempt=False,
            frozen_plan_matches=False,
            submission=SubmissionEvidence.NOT_STARTED,
            provider_terminal=None,
            events_sealed=False,
            artifact_observed=False,
            artifact_verified=False,
            publication_observed=False,
            publication_verified=False,
            authority_covers_completion=False,
            requires_budget=requires_budget,
            budget_state=budget_state,
        )


def _recovery_submission(disposition: RecoveryDisposition, observed: SubmissionEvidence) -> SubmissionEvidence:
    if disposition is RecoveryDisposition.BLOCKED:
        return SubmissionEvidence.DEFINITELY_NOT_SENT
    if disposition is RecoveryDisposition.UNKNOWN:
        return SubmissionEvidence.AMBIGUOUS
    return observed


def _recovery_transition_required(decision: RecoveryDecision, attempt_state: AttemptState) -> bool:
    if decision.disposition is RecoveryDisposition.COMPLETED:
        return attempt_state is not AttemptState.COMPLETED
    if attempt_state is AttemptState.UNKNOWN:
        return decision.disposition in {
            RecoveryDisposition.BLOCKED,
            RecoveryDisposition.FAILED,
            RecoveryDisposition.QUARANTINED,
        }
    return not attempt_state.terminal


def _verified_completion_workspace(
    workspaces: AttemptWorkspaceStore,
    workspace_verifier: AttemptWorkspaceVerifier,
    artifact_evidence: ArtifactEvidenceVerifier,
    target,
    attempt_state: AttemptState,
    reservation_revision: int,
    expected_frozen_plan_digest: ContentDigest | None,
) -> AttemptWorkspaceEvidence:
    """Re-read and verify the exact durable evidence immediately before completion."""
    workspace = workspaces.load(target.attempt_id)
    verified = workspace_verifier.verify(
        workspace, target, attempt_state, reservation_revision, expected_frozen_plan_digest
    )
    artifact = artifact_evidence.verify(workspace)
    if (
        workspace is None
        or not verified.workspace_matches_attempt
        or not verified.frozen_plan_matches
        or not artifact.artifact_observed
        or not artifact.artifact_verified
        or not artifact.publication_observed
        or not artifact.publication_verified
    ):
        raise ValidationError("recovery completion requires a freshly verified workspace publication")
    return workspace


def _verified_workspace_artifact_and_media(
    artifact_evidence: ArtifactEvidenceVerifier,
    workspace: AttemptWorkspaceEvidence,
):
    audio_publications = tuple(
        publication
        for publication in workspace.published_artifacts
        if publication.reference.media_type == "audio/wav"
    )
    if len(audio_publications) != 1:
        raise ValidationError("recovery completion requires exactly one canonical audio publication")
    artifact = audio_publications[0]
    media = artifact_evidence.recover_media(workspace, artifact)
    if type(media) is not DecodedMediaFacts or media.all_digital_silence:
        raise ValidationError("recovery completion requires verified non-silent decoded media")
    return artifact, media


def _recovery_id(identifiers: IdentifierSource | None, kind: type):
    if identifiers is None:
        raise ValidationError("recovery completion requires the server-side identity source")
    return identifiers.new_id(kind)


def _historical_episode_snapshot(episode, role: ComponentRole, revision: int):
    candidates = tuple(
        item.snapshot
        for item in episode.component_history
        if item.role is role and item.resulting_revision <= revision
    )
    if not candidates:
        raise ValidationError("episode recovery has no source snapshot at the attempt reservation revision")
    return candidates[-1]


def _load_job(repository: NarrationJobRepository, job_id):
    job = repository.load(job_id)
    if job is None:
        raise NotFound(f"narration job {job_id} was not found")
    return job


@dataclass(frozen=True, slots=True)
class PrepareDiaryNarrationHandler:
    repository: NarrationJobRepository
    policies: NarrationReleasePolicyResolver
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: PrepareDiaryNarrationCommand) -> NarrationPreparedResult:
        policy = self.policies.resolve_lane_b_diary()
        if policy.contract.lane is not Lane.B:
            raise ValidationError("Lane-B release policy resolved a non-diary contract")
        now = self.clock.now()
        _active_authority(self.authority, policy.contract, AuthorityOperation.PREFLIGHT, now)
        job_id = self.identifiers.new_id(NarrationJobId)
        job = prepare_lane_b_diary_job(
            job_id,
            policy.contract,
            policy.initial_defaults,
            command.passages,
            now,
        )
        _cas_or_conflict(self.repository.save(job, None), "narration job")
        return NarrationPreparedResult(
            command.command_id,
            job_id,
            job.revision,
            Lane.B,
            policy.contract.digest,
        )


@dataclass(frozen=True, slots=True)
class PrepareIntroNarrationHandler:
    repository: NarrationJobRepository
    episodes: DiaryEpisodeRepository
    policies: NarrationReleasePolicyResolver
    authority: AuthorizationStatusReader
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: PrepareIntroNarrationCommand) -> NarrationPreparedResult:
        episode = _load_episode(self.episodes, command.intended_episode_id)
        if episode.revision != command.expected_episode_revision:
            raise RevisionConflict(
                f"expected diary episode revision {command.expected_episode_revision!r}, "
                f"current is {episode.revision}"
            )
        if episode.status is not EpisodeStatus.DRAFT:
            raise ValidationError("Lane-C intro preparation requires an existing draft diary episode")

        policy = self.policies.resolve_lane_c_intro(command.intended_episode_id)
        if (
            policy.contract.lane is not Lane.C
            or policy.contract.intended_episode_id != command.intended_episode_id
        ):
            raise ValidationError("Lane-C release policy does not bind the intended diary episode")
        now = self.clock.now()
        _active_authority(self.authority, policy.contract, AuthorityOperation.PREFLIGHT, now)

        current_episode = _load_episode(self.episodes, command.intended_episode_id)
        if (
            current_episode.revision != command.expected_episode_revision
            or current_episode.status is not EpisodeStatus.DRAFT
        ):
            raise RevisionConflict("diary episode changed during Lane-C intro preparation")

        job_id = self.identifiers.new_id(NarrationJobId)
        job = prepare_lane_c_intro_job(
            job_id,
            policy.contract,
            policy.initial_defaults,
            command.passages,
            now,
        )
        _cas_or_conflict(self.repository.save(job, None), "narration job")
        return NarrationPreparedResult(
            command.command_id,
            job_id,
            job.revision,
            Lane.C,
            policy.contract.digest,
        )


@dataclass(frozen=True, slots=True)
class ValidateRenderRecipeHandler:
    repository: NarrationJobRepository
    compiler: RecipeCompiler

    def __call__(self, command: ValidateRenderRecipeCommand) -> RenderRecipeValidatedResult:
        job = _load_job(self.repository, command.job_id)
        if job.revision != command.expected_revision:
            raise RevisionConflict(
                f"expected narration revision {command.expected_revision!r}, current is {job.revision}"
            )
        passage = job.passage(command.passage_id)
        current_text = passage.current_text_revision
        authoring = command.authoring
        if authoring.mode is RecipeAuthoringMode.STRUCTURED:
            if authoring.advanced_source is not None:
                raise ValidationError("structured recipe authoring cannot include Advanced source")
            advanced_source = None
        elif authoring.mode is RecipeAuthoringMode.ADVANCED:
            if not authoring.advanced_source or authoring.structured_controls:
                raise ValidationError("Advanced recipe authoring requires source and no caller-compiled controls")
            advanced_source = authoring.advanced_source
        else:
            raise ValidationError("recipe authoring mode is invalid")

        compiled = self.compiler.compile_recipe(
            RecipeAuthoringRequest(
                job.job_id,
                passage.passage_id,
                current_text.revision,
                current_text.text,
                authoring.recipe_id,
                authoring.recipe_revision,
                authoring.structured_controls,
                advanced_source,
                job.contract,
            )
        )
        if (
            compiled.canonical_projection != current_text.text.value
            or compiled.recipe.recipe_id != authoring.recipe_id
            or compiled.recipe.revision != authoring.recipe_revision
            or compiled.recipe.text_revision != current_text.revision
            or compiled.recipe.text_digest != current_text.text.digest
        ):
            raise ValidationError("recipe compiler output is not lexically or revision equivalent")
        compiled.recipe.validate_for(current_text.text)

        current_job = _load_job(self.repository, command.job_id)
        current_passage = current_job.passage(command.passage_id)
        if (
            current_job.revision != command.expected_revision
            or current_passage.current_text_revision != current_text
        ):
            raise RevisionConflict("narration job changed during authoritative recipe compilation")
        current_job.record_render_recipe(
            command.passage_id,
            compiled.recipe,
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(current_job, command.expected_revision), "narration job")
        return RenderRecipeValidatedResult(
            command.command_id,
            command.job_id,
            current_job.revision,
            compiled.recipe,
            compiled.canonical_projection,
            compiled.warnings,
        )


@dataclass(frozen=True, slots=True)
class RequireRenderRecipeHandler:
    repository: NarrationJobRepository

    def __call__(self, command: RequireRenderRecipeCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        job.require_render_recipe(command.passage_id, command.recipe_id, expected_revision=command.expected_revision)
        _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job")
        return NarrationMutationResult(command.command_id, command.job_id, job.revision)


def _resolve_text_control(intent, inherited_value: str | None, field: str, *, omittable: bool):
    if type(intent.mode) is not OverrideMode:
        raise ValidationError(f"{field} override mode is invalid")
    if intent.mode is OverrideMode.INHERIT:
        if intent.value is not None:
            raise ValidationError(f"inherited {field} cannot carry a caller-resolved value")
        if inherited_value is None:
            raise ValidationError(f"{field} has no current default to inherit")
        return ResolvedControl(ControlProvenance.INHERITED, inherited_value)
    if intent.mode is OverrideMode.OMIT:
        if intent.value is not None or not omittable:
            raise ValidationError(f"{field} cannot be omitted or carry an omitted value")
        return ResolvedControl(ControlProvenance.EXPLICITLY_OMITTED, None)
    if intent.mode is not OverrideMode.SET or intent.value is None:
        raise ValidationError(f"explicit {field} override requires a value")
    value = intent.value
    if field in {"speed", "volume"}:
        value = FixedTwoDecimal(value).value
    return ResolvedControl(ControlProvenance.EXPLICITLY_SET, value)


def _resolve_take_settings(defaults, intent) -> EffectiveTakeSettings:
    speed = _resolve_text_control(intent.speed, defaults.speed.value, "speed", omittable=False)
    volume = _resolve_text_control(intent.volume, defaults.volume.value, "volume", omittable=False)
    emotion = _resolve_text_control(intent.emotion, defaults.emotion, "emotion", omittable=True)
    dictionary_intent = intent.dictionary
    if type(dictionary_intent.mode) is not OverrideMode:
        raise ValidationError("dictionary override mode is invalid")
    if dictionary_intent.mode is OverrideMode.INHERIT:
        if dictionary_intent.value is not None:
            raise ValidationError("inherited dictionary cannot carry a caller-resolved binding")
        if defaults.dictionary is None:
            raise ValidationError("dictionary has no current default to inherit")
        dictionary = defaults.dictionary
        dictionary_provenance = ControlProvenance.INHERITED
    elif dictionary_intent.mode is OverrideMode.OMIT:
        if dictionary_intent.value is not None:
            raise ValidationError("omitted dictionary cannot carry a binding")
        dictionary = None
        dictionary_provenance = ControlProvenance.EXPLICITLY_OMITTED
    elif dictionary_intent.mode is OverrideMode.SET and dictionary_intent.value is not None:
        dictionary = dictionary_intent.value
        dictionary_provenance = ControlProvenance.EXPLICITLY_SET
    else:
        raise ValidationError("explicit dictionary override requires a binding")
    return EffectiveTakeSettings(speed, volume, emotion, dictionary, dictionary_provenance)


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
        settings = _resolve_take_settings(job.defaults, command.settings_intent)
        if (
            passage.required_dictionary_digest is not None
            and (
                settings.dictionary is None
                or settings.dictionary.content_digest != passage.required_dictionary_digest
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
                settings,
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
            settings=settings,
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
            billable_characters=compiled.billable_characters,
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
    publications=(),
    artifact=None,
    recovery=(),
    raw_timing_reference=None,
):
    all_publications = publications + (() if artifact is None else (artifact,))
    return AttemptWorkspaceEvidence(
        workspace_id,
        AttemptKind.GENERATION,
        job.job_id,
        attempt_id,
        job.generation_attempt(attempt_id).reservation_revision,
        reservation_id,
        preview.preview_digest,
        None if effective_input is None else effective_input.request_digest,
        None if effective_input is None else effective_input.request_digest,
        submission,
        events,
        tuple(publication.reference for publication in all_publications),
        all_publications,
        recovery,
        state,
        raw_timing_reference,
    )


def _independently_sealed_provider_events(events: object) -> tuple[ProviderEventEvidence, ...]:
    """Keep returned provider events only when their terminal closure is provable."""
    if (
        type(events) is not tuple
        or not events
        or any(type(event) is not ProviderEventEvidence for event in events)
        or tuple(event.sequence for event in events) != tuple(range(len(events)))
    ):
        return ()
    terminal = tuple(event for event in events if event.terminal_classification is not None)
    if (
        len(terminal) != 1
        or events[-1] is not terminal[0]
        or events[-1].kind is not ProviderEventKind.TERMINAL
    ):
        return ()
    return events


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

    def _record_invalid_provider_result(
        self,
        command: GenerateTakeCommand,
        job,
        attempt_id,
        reservation_id,
        workspace_id,
        preview,
        effective_input,
        generated,
        reason: str,
    ) -> GenerationRunResult:
        events = _independently_sealed_provider_events(generated.events)
        disposition = self._persist_workspace_then_finalize_budget(
            command, job, attempt_id, reservation_id,
            _workspace(
                workspace_id, job, attempt_id, reservation_id, preview,
                AttemptState.FAILED, SubmissionEvidence.COMPLETED,
                effective_input=effective_input, events=events,
                publications=generated.evidence_publications,
                recovery=(reason,),
                raw_timing_reference=generated.raw_timing_reference,
            ),
            "settle", generated.usage,
        )
        if disposition is not None:
            return self._recovery_required(command, attempt_id, disposition)
        previous = job.revision
        job.finalize_generation_outcome(
            attempt_id, AttemptState.FAILED, SubmissionEvidence.COMPLETED,
            reason, self.clock.now(), expected_revision=previous,
        )
        if not self.repository.save(job, previous):
            return self._recovery_required(command, attempt_id, "settled")
        return GenerationRunResult(
            command.command_id,
            job.job_id,
            job.revision,
            attempt_id,
            AttemptState.FAILED,
            None,
            "settled",
        )

    def _record_synthesis_failure(
        self,
        command: GenerateTakeCommand,
        job,
        attempt_id: GenerationAttemptId,
        reservation_id: BudgetReservationId,
        workspace_id: AttemptWorkspaceId,
        preview: GenerationPreview,
        effective_input: EffectiveSynthesisInput,
        evidence: SynthesisFailureEvidence,
        state: AttemptState,
        budget_action: str,
        aggregate_reason: str,
    ) -> GenerationRunResult:
        budget_fact = evidence.usage if budget_action == "settle" else evidence.reason_code
        recovery = (evidence.reason_code,)
        usage_fact = evidence.usage_recovery_fact
        if usage_fact is not None:
            recovery += (usage_fact,)
            if budget_action == "hold":
                budget_fact = usage_fact
        disposition = self._persist_workspace_then_finalize_budget(
            command,
            job,
            attempt_id,
            reservation_id,
            _workspace(
                workspace_id,
                job,
                attempt_id,
                reservation_id,
                preview,
                state,
                evidence.submission,
                effective_input=effective_input,
                events=evidence.events,
                publications=evidence.publications,
                recovery=recovery,
                raw_timing_reference=evidence.raw_timing_reference,
            ),
            budget_action,
            budget_fact,
            usage_hold_fact=usage_fact,
        )
        budget_disposition = {
            "release": "released",
            "hold": "held",
            "settle": "settled",
        }[budget_action]
        if disposition is not None:
            return self._recovery_required(command, attempt_id, disposition)
        previous = job.revision
        job.finalize_generation_outcome(
            attempt_id,
            state,
            evidence.submission,
            aggregate_reason,
            self.clock.now(),
            expected_revision=previous,
        )
        if not self.repository.save(job, previous):
            return self._recovery_required(command, attempt_id, budget_disposition)
        return GenerationRunResult(
            command.command_id,
            job.job_id,
            job.revision,
            attempt_id,
            state,
            None,
            budget_disposition,
        )

    def _recovery_required(
        self, command: GenerateTakeCommand, attempt_id: GenerationAttemptId, budget_disposition: str,
    ) -> GenerationRunResult:
        recovered = _load_job(self.repository, command.job_id)
        return GenerationRunResult(
            command.command_id, recovered.job_id, recovered.revision, attempt_id,
            AttemptState.UNKNOWN, None, budget_disposition,
        )

    def _persist_workspace_then_finalize_budget(
        self,
        command: GenerateTakeCommand,
        job,
        attempt_id: GenerationAttemptId,
        reservation_id: BudgetReservationId,
        workspace: AttemptWorkspaceEvidence,
        action: str,
        evidence: object,
        *,
        usage_hold_fact: str | None = None,
    ) -> str | None:
        """The post-gateway durable boundary: workspace, budget, then aggregate CAS."""
        try:
            self.workspaces.save(workspace)
        except Exception:
            try:
                self.budget.hold(
                    reservation_id, usage_hold_fact or "workspace persistence failed after external work"
                )
            except Exception:
                return "unknown"
            return "held"
        try:
            if action == "settle":
                self.budget.settle(reservation_id, evidence)
            elif action == "release":
                self.budget.release(reservation_id, str(evidence))
            elif action == "hold":
                self.budget.hold(reservation_id, str(evidence))
            else:
                raise AssertionError("unknown post-gateway budget action")
        except Exception:
            # The adapter can commit and then fail before responding. Its durable
            # disposition is therefore unknowable here; never issue a downgrade.
            return "unknown"
        return None

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
            self.budget.reserve(
                reservation_id,
                command.command_id,
                NonNegativeDecimal(preview.estimated_usage),
            )
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
            billable_characters=preview.billable_characters,
        )
        previous = job.revision
        job.freeze_generation_input(attempt_id, effective_input, expected_revision=previous)
        _cas_or_conflict(self.repository.save(job, previous), "narration job")
        self.workspaces.save(
            _workspace(
                workspace_id,
                job,
                attempt_id,
                reservation_id,
                preview,
                AttemptState.INPUT_FROZEN,
                SubmissionEvidence.NOT_STARTED,
                effective_input=effective_input,
            )
        )

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
            self.workspaces.save(
                _workspace(
                    workspace_id,
                    job,
                    attempt_id,
                    reservation_id,
                    preview,
                    AttemptState.EXTERNAL_WORK_STARTED,
                    SubmissionEvidence.NOT_STARTED,
                    effective_input=effective_input,
                )
            )
        except Exception:
            try:
                self.budget.hold(reservation_id, "external work boundary persistence failed")
            except Exception:
                return self._recovery_required(command, attempt_id, "unknown")
            return self._recovery_required(command, attempt_id, "held")

        try:
            generated = self.gateway.synthesize(
                SynthesisInvocation(attempt_id, job.contract, effective_input)
            )
        except SynthesisPreSendFailure as error:
            return self._record_synthesis_failure(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                error.evidence,
                AttemptState.BLOCKED,
                "release",
                "external gateway proved request was not sent",
            )
        except SynthesisAmbiguousFailure as error:
            return self._record_synthesis_failure(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                error.evidence,
                AttemptState.UNKNOWN,
                "hold",
                "external gateway outcome is ambiguous",
            )
        except SynthesisSubmittedFailure as error:
            action = "settle" if error.evidence.usage is not None else "hold"
            return self._record_synthesis_failure(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                error.evidence,
                AttemptState.FAILED,
                action,
                "external gateway recorded a definitive failure",
            )
        except DefinitePreSendFailure as error:
            disposition = self._persist_workspace_then_finalize_budget(
                command, job, attempt_id, reservation_id,
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.BLOCKED, SubmissionEvidence.DEFINITELY_NOT_SENT,
                    effective_input=effective_input, recovery=(str(error),),
                ),
                "release", "definite pre-send failure",
            )
            if disposition is not None:
                return self._recovery_required(command, attempt_id, disposition)
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.BLOCKED, SubmissionEvidence.DEFINITELY_NOT_SENT,
                "external gateway proved request was not sent", self.clock.now(),
                expected_revision=previous,
            )
            if not self.repository.save(job, previous):
                return self._recovery_required(command, attempt_id, "released")
            return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.BLOCKED, None, "released")
        except AmbiguousExternalFailure as error:
            disposition = self._persist_workspace_then_finalize_budget(
                command, job, attempt_id, reservation_id,
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.UNKNOWN, SubmissionEvidence.AMBIGUOUS,
                    effective_input=effective_input, recovery=(str(error),),
                ),
                "hold", "ambiguous external outcome",
            )
            if disposition is not None:
                return self._recovery_required(command, attempt_id, disposition)
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.UNKNOWN, SubmissionEvidence.AMBIGUOUS,
                "external gateway outcome is ambiguous", self.clock.now(),
                expected_revision=previous,
            )
            if not self.repository.save(job, previous):
                return self._recovery_required(command, attempt_id, "held")
            return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.UNKNOWN, None, "held")
        except ExternalWorkFailed as error:
            disposition = self._persist_workspace_then_finalize_budget(
                command, job, attempt_id, reservation_id,
                _workspace(
                    workspace_id, job, attempt_id, reservation_id, preview,
                    AttemptState.FAILED, SubmissionEvidence.STARTED,
                    effective_input=effective_input, recovery=(str(error),),
                ),
                "hold", "definitive submitted failure awaits usage evidence",
            )
            if disposition is not None:
                return self._recovery_required(command, attempt_id, disposition)
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.FAILED, SubmissionEvidence.STARTED,
                "external gateway recorded a definitive failure", self.clock.now(),
                expected_revision=previous,
            )
            if not self.repository.save(job, previous):
                return self._recovery_required(command, attempt_id, "held")
            return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.FAILED, None, "held")
        except Exception:
            evidence = SynthesisFailureEvidence(
                SubmissionEvidence.AMBIGUOUS,
                (),
                (),
                None,
                None,
                "unexpected_synthesis_failure",
            )
            return self._record_synthesis_failure(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                evidence,
                AttemptState.UNKNOWN,
                "hold",
                "unexpected synthesis failure requires reconciliation",
            )

        event_stream_is_contiguous = (
            type(generated.events) is tuple
            and all(type(event) is ProviderEventEvidence for event in generated.events)
            and tuple(event.sequence for event in generated.events)
            == tuple(range(len(generated.events)))
        )
        terminal_events = tuple(
            event for event in generated.events if event.terminal_classification is not None
        ) if event_stream_is_contiguous else ()
        if not (
            event_stream_is_contiguous
            and generated.events
            and len(terminal_events) == 1
            and generated.events[-1] is terminal_events[0]
            and generated.events[-1].kind is ProviderEventKind.TERMINAL
            and generated.events[-1].terminal_classification is ProviderTerminalClass.SUCCESS
        ):
            return self._record_invalid_provider_result(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                generated,
                "provider result lacked one final successful terminal event",
            )

        try:
            media = self.media.inspect_canonical_wav(generated.canonical_wav_bytes)
        except Exception:
            return self._record_invalid_provider_result(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                generated,
                "provider result could not be decoded into exact canonical media facts",
            )
        if type(media) is not DecodedMediaFacts or media.all_digital_silence:
            return self._record_invalid_provider_result(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                generated,
                "provider result decoded to all digital silence",
            )
        try:
            artifact = self.artifacts.publish(
                command.artifact_location,
                generated.canonical_wav_bytes,
                "audio/wav",
                self.clock.now(),
            )
        except Exception:
            return self._record_invalid_provider_result(
                command,
                job,
                attempt_id,
                reservation_id,
                workspace_id,
                preview,
                effective_input,
                generated,
                "canonical artifact publication failed after provider result",
            )
        disposition = self._persist_workspace_then_finalize_budget(
            command, job, attempt_id, reservation_id,
            _workspace(
                workspace_id, job, attempt_id, reservation_id, preview,
                AttemptState.ARTIFACTS_PUBLISHED, SubmissionEvidence.COMPLETED,
                effective_input=effective_input, events=generated.events,
                publications=generated.evidence_publications, artifact=artifact,
                raw_timing_reference=generated.raw_timing_reference,
            ),
            "settle", generated.usage,
        )
        if disposition is not None:
            return self._recovery_required(command, attempt_id, disposition)
        previous = job.revision
        job.stage_generation_artifacts(attempt_id, generated.events, artifact, media, expected_revision=previous)
        if not self.repository.save(job, previous):
            return self._recovery_required(command, attempt_id, "settled")
        previous = job.revision
        job.mark_generation_artifacts_published(attempt_id, expected_revision=previous)
        if not self.repository.save(job, previous):
            return self._recovery_required(command, attempt_id, "settled")

        try:
            _require_confirmed_preview_authority(self.authority, job, preview, self.clock.now())
        except AuthorizationDenied as error:
            previous = job.revision
            job.finalize_generation_outcome(
                attempt_id, AttemptState.QUARANTINED, SubmissionEvidence.COMPLETED,
                "authority changed while external work was in flight", self.clock.now(),
                expected_revision=previous,
            )
            if not self.repository.save(job, previous):
                return self._recovery_required(command, attempt_id, "settled")
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
            generated.raw_timing_reference,
            self.clock.now(),
        )
        previous = job.revision
        job.complete_generation_attempt(attempt_id, take, self.clock.now(), expected_revision=previous)
        if not self.repository.save(job, previous):
            return self._recovery_required(command, attempt_id, "settled")
        return GenerationRunResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.COMPLETED, take_id, "settled")


@dataclass(frozen=True, slots=True)
class ReconcileGenerationAttemptHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    workspaces: AttemptWorkspaceStore
    workspace_verifier: AttemptWorkspaceVerifier
    provider_events: ProviderEventVerifier
    artifact_evidence: ArtifactEvidenceVerifier
    budget_status: BudgetReservationStatusReader
    budget: GenerationBudgetLedger
    identifiers: IdentifierSource | None = None

    def __call__(self, command: ReconcileGenerationAttemptCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        attempt = job.generation_attempt(command.attempt_id)
        if job.revision != command.expected_revision:
            raise RevisionConflict("generation recovery expected revision is stale")
        try:
            budget_state = self.budget_status.read(attempt.budget_reservation_id)
        except Exception:
            budget_state = BudgetRecoveryState.UNKNOWN
        target = GenerationRecoveryTarget(job.job_id, attempt.attempt_id, attempt.budget_reservation_id)
        facts = _trusted_recovery_facts(
            workspaces=self.workspaces,
            workspace_verifier=self.workspace_verifier,
            provider_events=self.provider_events,
            artifacts=self.artifact_evidence,
            target=target,
            attempt_state=attempt.state,
            reservation_revision=attempt.reservation_revision,
            expected_frozen_plan_digest=(
                None if attempt.effective_input is None else attempt.effective_input.request_digest
            ),
            requires_budget=True,
            budget_state=budget_state,
            authority_covers_completion=_recovery_authority_covers(
                self.authority, job.contract, AuthorityOperation.GENERATE, self.clock.now()
            ),
        )
        decision = decide_target_recovery(target, facts)
        if decision.disposition is RecoveryDisposition.COMPLETED:
            workspace = _verified_completion_workspace(
                self.workspaces,
                self.workspace_verifier,
                self.artifact_evidence,
                target,
                attempt.state,
                attempt.reservation_revision,
                None if attempt.effective_input is None else attempt.effective_input.request_digest,
            )
            if attempt.state is AttemptState.COMPLETED:
                assert attempt.take_id is not None
                take = job.take(attempt.take_id)
            else:
                if attempt.effective_input is None:
                    raise ValidationError("generation recovery completion requires the frozen effective input")
                artifact, media = _verified_workspace_artifact_and_media(self.artifact_evidence, workspace)
                preview = _find_preview(job, attempt.preview_id)
                timing_reference = workspace.raw_timing_reference
                effective_input = attempt.effective_input
                take = NarrationTake(
                    _recovery_id(self.identifiers, TakeId),
                    attempt.attempt_id,
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
                    timing_reference,
                    self.clock.now(),
                )
            previous = job.revision
            job.recover_generation_completion(
                attempt.attempt_id,
                workspace,
                take,
                facts.authority_covers_completion,
                self.clock.now(),
                expected_revision=previous,
            )
            if job.revision != previous:
                _cas_or_conflict(self.repository.save(job, previous), "narration generation recovery")
            return NarrationMutationResult(command.command_id, job.job_id, job.revision)
        if _recovery_transition_required(decision, attempt.state):
            if attempt.state is AttemptState.UNKNOWN:
                job.reconcile_generation_attempt(
                    attempt.attempt_id,
                    AttemptState(decision.disposition.value),
                    decision.reason.value,
                    self.clock.now(),
                    expected_revision=command.expected_revision,
                )
            else:
                job.finalize_generation_outcome(
                    attempt.attempt_id,
                    AttemptState(decision.disposition.value),
                    _recovery_submission(decision.disposition, facts.submission),
                    decision.reason.value,
                    self.clock.now(),
                    expected_revision=command.expected_revision,
                )
            _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job recovery")
        if decision.budget is BudgetDisposition.RELEASE and budget_state is BudgetRecoveryState.RESERVED:
            self.budget.release(attempt.budget_reservation_id, decision.reason.value)
        elif decision.budget is BudgetDisposition.HOLD and budget_state is BudgetRecoveryState.RESERVED:
            self.budget.hold(attempt.budget_reservation_id, decision.reason.value)
        return NarrationMutationResult(command.command_id, job.job_id, job.revision)


@dataclass(frozen=True, slots=True)
class GeneratePendingPassagesHandler:
    single: GenerateTakeHandler

    def __call__(self, command: GeneratePendingPassagesCommand) -> GenerationBatchResult:
        if len(command.preview_ids) != len(command.artifact_locations):
            raise ValidationError("sequential generation requires one artifact location per preview")
        if (
            type(command.accepted_billable_character_cap) is not int
            or command.accepted_billable_character_cap < 0
        ):
            raise ValidationError("accepted billable character cap must be a non-negative integer")
        if len(set(command.preview_ids)) != len(command.preview_ids):
            raise ValidationError("sequential generation preview ids must be unique")
        job = _load_job(self.single.repository, command.job_id)
        if job.revision != command.expected_revision:
            raise RevisionConflict("generation batch expected revision is stale")
        previews = tuple(_find_preview(job, preview_id) for preview_id in command.preview_ids)
        exact_total = sum(preview.billable_characters for preview in previews)
        if exact_total > command.accepted_billable_character_cap:
            raise ValidationError("exact batch billable characters exceed the caller-accepted cap")
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
        principal = self.actors.resolve_principal(command.principal)
        if principal.review_authority is None:
            raise AuthorizationDenied("principal has no configured narration-review authority")
        job.record_review_decision(
            self.identifiers.new_id(ReviewDecisionId),
            command.take_id,
            principal.actor_id,
            principal.review_authority,
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
        principal = self.actors.resolve_principal(command.principal)
        now = self.clock.now()
        _active_authority(self.authority, job.contract, AuthorityOperation.GENERATE, now)
        job.select_working_take(
            self.identifiers.new_id(SelectionDecisionId),
            command.passage_id,
            command.take_id,
            principal.actor_id,
            True,
            command.reason,
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
        job.job_id,
        attempt_id,
        job.narration_assembly_attempt(attempt_id).reservation_revision,
        None,
        None,
        None,
        narration_assembly_plan_digest(
            job.narration_assembly_attempt(attempt_id).selected_take_ids,
            job.narration_assembly_attempt(attempt_id).gaps_samples,
        ),
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

    def _post_artifact_recovery_required(
        self,
        command: AssembleNarrationMasterCommand,
        attempt_id: NarrationAssemblyAttemptId,
    ) -> NarrationAssemblyResult:
        recovered = _load_job(self.repository, command.job_id)
        return NarrationAssemblyResult(
            command.command_id,
            recovered.job_id,
            recovered.revision,
            attempt_id,
            AttemptState.UNKNOWN,
            None,
        )

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
        try:
            self.workspaces.save(
                _narration_assembly_workspace(
                    workspace_id, job, attempt_id, AttemptState.ARTIFACTS_PUBLISHED, artifact=artifact
                )
            )
        except Exception:
            return self._post_artifact_recovery_required(command, attempt_id)
        previous = job.revision
        job.stage_narration_master(
            attempt_id, artifact, assembled.media, assembled.passage_offsets, expected_revision=previous
        )
        if not self.repository.save(job, previous):
            return self._post_artifact_recovery_required(command, attempt_id)
        previous = job.revision
        job.mark_narration_master_published(attempt_id, expected_revision=previous)
        if not self.repository.save(job, previous):
            return self._post_artifact_recovery_required(command, attempt_id)
        try:
            _active_authority(self.authority, job.contract, AuthorityOperation.ASSEMBLE, self.clock.now())
        except AuthorizationDenied as error:
            previous = job.revision
            job.finalize_narration_assembly_outcome(
                attempt_id, AttemptState.QUARANTINED, "authority changed during dry assembly",
                self.clock.now(), expected_revision=previous,
            )
            if not self.repository.save(job, previous):
                return self._post_artifact_recovery_required(command, attempt_id)
            return NarrationAssemblyResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.QUARANTINED, None)
        master_id = self.identifiers.new_id(NarrationMasterId)
        previous = job.revision
        job.complete_narration_assembly(attempt_id, master_id, self.clock.now(), expected_revision=previous)
        if not self.repository.save(job, previous):
            return self._post_artifact_recovery_required(command, attempt_id)
        return NarrationAssemblyResult(command.command_id, job.job_id, job.revision, attempt_id, AttemptState.COMPLETED, master_id)


@dataclass(frozen=True, slots=True)
class RecordNarrationMasterListeningHandler:
    repository: NarrationJobRepository
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RecordNarrationMasterListeningCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        principal = self.actors.resolve_principal(command.principal)
        job.record_narration_master_listening(
            self.identifiers.new_id(MasterListeningDecisionId),
            command.master_id,
            principal.actor_id,
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
    authority: AuthorizationStatusReader
    clock: Clock

    def __call__(self, command: ShowNarrationStatusCommand) -> NarrationStatusResult:
        job = _load_job(self.repository, command.job_id)
        observed_at = self.clock.now()
        observation = _status_authority_observation(
            self.authority, job.contract.authority_record_id, observed_at
        )
        return project_narration_status(job, observation, observed_at)


@dataclass(frozen=True, slots=True)
class ReconcileNarrationAssemblyAttemptHandler:
    repository: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    workspaces: AttemptWorkspaceStore
    workspace_verifier: AttemptWorkspaceVerifier
    provider_events: ProviderEventVerifier
    artifact_evidence: ArtifactEvidenceVerifier
    identifiers: IdentifierSource | None = None

    def __call__(self, command: ReconcileNarrationAssemblyAttemptCommand) -> NarrationMutationResult:
        job = _load_job(self.repository, command.job_id)
        attempt = job.narration_assembly_attempt(command.attempt_id)
        if job.revision != command.expected_revision:
            raise RevisionConflict("narration assembly recovery expected revision is stale")
        target = NarrationAssemblyRecoveryTarget(job.job_id, attempt.attempt_id)
        facts = _trusted_recovery_facts(
            workspaces=self.workspaces,
            workspace_verifier=self.workspace_verifier,
            provider_events=self.provider_events,
            artifacts=self.artifact_evidence,
            target=target,
            attempt_state=attempt.state,
            reservation_revision=attempt.reservation_revision,
            expected_frozen_plan_digest=narration_assembly_plan_digest(
                attempt.selected_take_ids, attempt.gaps_samples
            ),
            requires_budget=False,
            budget_state=BudgetRecoveryState.NOT_APPLICABLE,
            authority_covers_completion=_recovery_authority_covers(
                self.authority, job.contract, AuthorityOperation.ASSEMBLE, self.clock.now()
            ),
        )
        decision = decide_target_recovery(target, facts)
        if decision.disposition is RecoveryDisposition.COMPLETED:
            workspace = _verified_completion_workspace(
                self.workspaces,
                self.workspace_verifier,
                self.artifact_evidence,
                target,
                attempt.state,
                attempt.reservation_revision,
                narration_assembly_plan_digest(attempt.selected_take_ids, attempt.gaps_samples),
            )
            if attempt.state is AttemptState.COMPLETED:
                assert attempt.master_id is not None
                master = job.master(attempt.master_id)
            else:
                artifact, media = _verified_workspace_artifact_and_media(self.artifact_evidence, workspace)
                selected = tuple(job.take(take_id) for take_id in attempt.selected_take_ids)
                cursor = 0
                offsets = []
                for index, take in enumerate(selected):
                    offsets.append(
                        PassageOffset(
                            take.passage_id,
                            take.text_revision,
                            take.text_digest,
                            cursor,
                            cursor + take.media.sample_count,
                        )
                    )
                    cursor += take.media.sample_count
                    if index < len(attempt.gaps_samples):
                        cursor += attempt.gaps_samples[index]
                master = NarrationMaster(
                    _recovery_id(self.identifiers, NarrationMasterId),
                    job.job_id,
                    job.lane,
                    job.contract.digest,
                    attempt.selected_take_ids,
                    attempt.gaps_samples,
                    tuple(offsets),
                    tuple(take.timing_reference for take in selected),
                    artifact,
                    media,
                    self.clock.now(),
                )
            previous = job.revision
            job.recover_narration_assembly_completion(
                attempt.attempt_id,
                workspace,
                master,
                facts.authority_covers_completion,
                self.clock.now(),
                expected_revision=previous,
            )
            if job.revision != previous:
                _cas_or_conflict(self.repository.save(job, previous), "narration assembly recovery")
            return NarrationMutationResult(command.command_id, job.job_id, job.revision)
        if _recovery_transition_required(decision, attempt.state):
            if attempt.state is AttemptState.UNKNOWN:
                job.reconcile_narration_assembly(
                    attempt.attempt_id,
                    AttemptState(decision.disposition.value),
                    decision.reason.value,
                    self.clock.now(),
                    expected_revision=command.expected_revision,
                )
            else:
                job.finalize_narration_assembly_outcome(
                    attempt.attempt_id,
                    AttemptState(decision.disposition.value),
                    decision.reason.value,
                    self.clock.now(),
                    expected_revision=command.expected_revision,
                )
            _cas_or_conflict(self.repository.save(job, command.expected_revision), "narration job recovery")
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
    current = _active_authority(authority, job.contract, operation, observed_at)
    if not job.is_snapshot_current(snapshot, authority_eligible=True):
        raise AuthorizationDenied("attached narration snapshot is no longer a current eligible source product")
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
        episode.episode_id,
        attempt_id,
        episode.episode_assembly_attempt(attempt_id).reservation_revision,
        None,
        None,
        None,
        episode_assembly_plan_digest(
            episode.episode_assembly_attempt(attempt_id).component_snapshot_digests,
            episode.episode_assembly_attempt(attempt_id).gap_samples,
        ),
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

    def _post_artifact_recovery_required(
        self,
        command: AssembleEpisodeSpeechMasterCommand,
        attempt_id: EpisodeAssemblyAttemptId,
    ) -> EpisodeAssemblyResult:
        recovered = _load_episode(self.repository, command.episode_id)
        return EpisodeAssemblyResult(
            command.command_id,
            recovered.episode_id,
            recovered.revision,
            attempt_id,
            AttemptState.UNKNOWN,
            None,
        )

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
        try:
            self.workspaces.save(
                _episode_assembly_workspace(
                    workspace_id, episode, attempt_id, AttemptState.ARTIFACTS_PUBLISHED, artifact=artifact
                )
            )
        except Exception:
            return self._post_artifact_recovery_required(command, attempt_id)
        previous = episode.revision
        episode.stage_episode_speech_master(
            attempt_id, artifact, assembled.media, assembled.component_offsets, expected_revision=previous
        )
        if not self.repository.save(episode, previous):
            return self._post_artifact_recovery_required(command, attempt_id)
        previous = episode.revision
        episode.mark_episode_speech_master_published(attempt_id, expected_revision=previous)
        if not self.repository.save(episode, previous):
            return self._post_artifact_recovery_required(command, attempt_id)
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
            if not self.repository.save(episode, previous):
                return self._post_artifact_recovery_required(command, attempt_id)
            return EpisodeAssemblyResult(command.command_id, episode.episode_id, episode.revision, attempt_id, AttemptState.QUARANTINED, None)
        master_id = self.identifiers.new_id(EpisodeSpeechMasterId)
        previous = episode.revision
        episode.complete_episode_assembly(attempt_id, master_id, self.clock.now(), expected_revision=previous)
        if not self.repository.save(episode, previous):
            return self._post_artifact_recovery_required(command, attempt_id)
        return EpisodeAssemblyResult(command.command_id, episode.episode_id, episode.revision, attempt_id, AttemptState.COMPLETED, master_id)


@dataclass(frozen=True, slots=True)
class RecordEpisodeListeningHandler:
    repository: DiaryEpisodeRepository
    actors: ActorResolver
    clock: Clock
    identifiers: IdentifierSource

    def __call__(self, command: RecordEpisodeListeningCommand) -> EpisodeMutationResult:
        episode = _load_episode(self.repository, command.episode_id)
        principal = self.actors.resolve_principal(command.principal)
        episode.record_episode_listening(
            self.identifiers.new_id(EpisodeListeningDecisionId),
            command.master_id,
            principal.actor_id,
            command.outcome,
            command.notes,
            self.clock.now(),
            expected_revision=command.expected_revision,
        )
        _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode")
        return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)


def _derive_timing_sources(episode, master, jobs, authority, observed_at):
    if episode.intro_snapshot is None or episode.diary_snapshot is None:
        raise AuthorizationDenied("episode source snapshots are incomplete")
    components_by_role = {component.role: component for component in master.component_offsets}
    sources = []
    for role, snapshot in (
        (ComponentRole.INTRO, episode.intro_snapshot),
        (ComponentRole.DIARY, episode.diary_snapshot),
    ):
        source_job = _require_current_source_snapshot(
            jobs, authority, snapshot, AuthorityOperation.DELIVER, observed_at
        )
        component = components_by_role.get(role)
        if component is None or len(component.passage_offsets) != len(snapshot.selected_take_ids):
            raise ValidationError("episode master timing offsets do not cover the exact source snapshot")
        for passage_id, take_id, timing_reference, offset in zip(
            snapshot.ordered_passage_ids,
            snapshot.selected_take_ids,
            snapshot.timing_references,
            component.passage_offsets,
        ):
            take = source_job.take(take_id)
            if (
                take.passage_id != passage_id
                or offset.passage_id != passage_id
                or take.text_revision != offset.text_revision
                or take.text_digest != offset.text_digest
            ):
                raise ValidationError("timing source facts do not match the selected take and episode offset")
            sources.append(
                TimingSourcePassage(
                    role,
                    snapshot.lane,
                    snapshot.issuing_job_id,
                    snapshot.source_master_id,
                    passage_id,
                    take.text_revision,
                    take.text_digest,
                    take.effective_input.text.value,
                    timing_reference,
                    offset.start_sample,
                    offset.end_sample,
                )
            )
    return tuple(sources)


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
        master = episode.speech_master(command.master_id)
        observed_at = self.clock.now()
        source_passages = _derive_timing_sources(
            episode, master, self.jobs, self.authority, observed_at
        )
        raw_timing_artifacts = tuple(
            source.timing_reference for source in source_passages if source.timing_reference is not None
        )
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
                source_passages,
                raw_timing_artifacts,
            )
        )
        _require_episode_sources_current(
            episode, self.jobs, self.authority, AuthorityOperation.DELIVER, self.clock.now()
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
            raw_timing_artifacts=raw_timing_artifacts,
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
        principal = self.actors.resolve_principal(command.principal)
        if principal.timing_review_status is None:
            raise AuthorizationDenied("principal has no configured timing-review authority")
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
        corrected_cues = tuple(
            replace(
                cue,
                provenance=CueProvenance.MANUAL_CORRECTION,
                source="manual timing correction",
                source_version="application-v1",
                review_status=principal.timing_review_status,
            )
            for cue in command.corrected_cues
        )
        corrected = TimedNarrationPackage.create(
            package_id=self.identifiers.new_id(TimedNarrationPackageId),
            version=source.version + 1,
            episode_id=episode.episode_id,
            episode_revision=episode.revision,
            episode_master=master,
            intro_snapshot_digest=source.intro_snapshot_digest,
            diary_snapshot_digest=source.diary_snapshot_digest,
            cues=corrected_cues,
            raw_timing_artifacts=source.raw_timing_artifacts,
            normalized_timing_artifact=source.normalized_timing_artifact,
            validation_results=(*source.validation_results, "manual correction recorded"),
            timing_review_status=principal.timing_review_status,
            authority_snapshots=source.authority_snapshots,
            source_package_digest=source.package_digest,
            correction_actor_id=principal.actor_id,
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
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock

    def __call__(self, command: ShowEpisodeStatusCommand) -> EpisodeStatusResult:
        episode = _load_episode(self.repository, command.episode_id)
        observed_at = self.clock.now()
        snapshots = tuple(
            snapshot
            for snapshot in (episode.intro_snapshot, episode.diary_snapshot)
            if snapshot is not None
        )
        source_job_ids = tuple(dict.fromkeys(snapshot.issuing_job_id for snapshot in snapshots))
        source_jobs = tuple(
            job
            for job_id in source_job_ids
            if (job := self.jobs.load(job_id)) is not None
        )
        authority_record_ids = tuple(
            dict.fromkeys(job.contract.authority_record_id for job in source_jobs)
        )
        observations = tuple(
            _status_authority_observation(self.authority, record_id, observed_at)
            for record_id in authority_record_ids
        )
        return project_episode_status(episode, source_jobs, observations, observed_at)


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
    jobs: NarrationJobRepository
    authority: AuthorizationStatusReader
    clock: Clock
    workspaces: AttemptWorkspaceStore
    workspace_verifier: AttemptWorkspaceVerifier
    provider_events: ProviderEventVerifier
    artifact_evidence: ArtifactEvidenceVerifier
    identifiers: IdentifierSource | None = None

    def __call__(self, command: ReconcileEpisodeAssemblyAttemptCommand) -> EpisodeMutationResult:
        episode = _load_episode(self.repository, command.episode_id)
        attempt = episode.episode_assembly_attempt(command.attempt_id)
        if episode.revision != command.expected_revision:
            raise RevisionConflict("episode assembly recovery expected revision is stale")
        target = EpisodeAssemblyRecoveryTarget(episode.episode_id, attempt.attempt_id)
        try:
            _require_episode_sources_current(
                episode, self.jobs, self.authority, AuthorityOperation.ASSEMBLE, self.clock.now()
            )
            authority_covers_completion = True
        except Exception:
            authority_covers_completion = False
        facts = _trusted_recovery_facts(
            workspaces=self.workspaces,
            workspace_verifier=self.workspace_verifier,
            provider_events=self.provider_events,
            artifacts=self.artifact_evidence,
            target=target,
            attempt_state=attempt.state,
            reservation_revision=attempt.reservation_revision,
            expected_frozen_plan_digest=episode_assembly_plan_digest(
                attempt.component_snapshot_digests, attempt.gap_samples
            ),
            requires_budget=False,
            budget_state=BudgetRecoveryState.NOT_APPLICABLE,
            authority_covers_completion=authority_covers_completion,
        )
        decision = decide_target_recovery(target, facts)
        if decision.disposition is RecoveryDisposition.COMPLETED:
            workspace = _verified_completion_workspace(
                self.workspaces,
                self.workspace_verifier,
                self.artifact_evidence,
                target,
                attempt.state,
                attempt.reservation_revision,
                episode_assembly_plan_digest(
                    attempt.component_snapshot_digests, attempt.gap_samples
                ),
            )
            if attempt.state is AttemptState.COMPLETED:
                assert attempt.master_id is not None
                master = episode.speech_master(attempt.master_id)
            else:
                artifact, media = _verified_workspace_artifact_and_media(self.artifact_evidence, workspace)
                intro = _historical_episode_snapshot(
                    episode, ComponentRole.INTRO, attempt.reservation_revision
                )
                diary = _historical_episode_snapshot(
                    episode, ComponentRole.DIARY, attempt.reservation_revision
                )
                diary_start = intro.media.sample_count + attempt.gap_samples
                diary_offsets = tuple(
                    PassageOffset(
                        offset.passage_id,
                        offset.text_revision,
                        offset.text_digest,
                        offset.start_sample + diary_start,
                        offset.end_sample + diary_start,
                    )
                    for offset in diary.passage_offsets
                )
                master = EpisodeSpeechMaster(
                    _recovery_id(self.identifiers, EpisodeSpeechMasterId),
                    episode.episode_id,
                    attempt.component_snapshot_digests,
                    attempt.gap_samples,
                    (
                        ComponentOffset(
                            ComponentRole.INTRO,
                            0,
                            intro.media.sample_count,
                            intro.snapshot_digest,
                            intro.passage_offsets,
                        ),
                        ComponentOffset(
                            ComponentRole.DIARY,
                            diary_start,
                            diary_start + diary.media.sample_count,
                            diary.snapshot_digest,
                            diary_offsets,
                        ),
                    ),
                    artifact,
                    media,
                    self.clock.now(),
                )
            previous = episode.revision
            episode.recover_episode_assembly_completion(
                attempt.attempt_id,
                workspace,
                master,
                authority_covers_completion,
                self.clock.now(),
                expected_revision=previous,
            )
            if episode.revision != previous:
                _cas_or_conflict(self.repository.save(episode, previous), "episode assembly recovery")
            return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)
        if _recovery_transition_required(decision, attempt.state):
            if attempt.state is AttemptState.UNKNOWN:
                episode.reconcile_episode_assembly(
                    attempt.attempt_id,
                    AttemptState(decision.disposition.value),
                    decision.reason.value,
                    self.clock.now(),
                    expected_revision=command.expected_revision,
                )
            else:
                episode.finalize_episode_assembly_outcome(
                    attempt.attempt_id,
                    AttemptState(decision.disposition.value),
                    decision.reason.value,
                    self.clock.now(),
                    expected_revision=command.expected_revision,
                )
            _cas_or_conflict(self.repository.save(episode, command.expected_revision), "diary episode recovery")
        return EpisodeMutationResult(command.command_id, episode.episode_id, episode.revision)
