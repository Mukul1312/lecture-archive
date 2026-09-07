"""Explicit local studio composition; construction performs no provider work."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from secrets import token_hex
from uuid import uuid4

from heritage_archive.platform.cartesia.transport import CartesiaSseTransport
from heritage_archive.contexts.narrator_voice.application.handlers import (
    AssembleEpisodeSpeechMasterHandler, AssembleNarrationMasterHandler,
    AttachDiaryMasterHandler, AttachIntroMasterHandler, DiscoverStudioHandler,
    EstimateGenerationHandler, GenerateTakeHandler, IssueNarrationMasterSnapshotHandler,
    PrepareDiaryEpisodeHandler, PrepareDiaryNarrationHandler, PrepareIntroNarrationHandler,
    ReadEpisodeMasterAudioHandler, ReadNarrationMasterAudioHandler, ReadTakeAudioHandler,
    ReconcileEpisodeAssemblyAttemptHandler, ReconcileGenerationAttemptHandler,
    ReconcileNarrationAssemblyAttemptHandler, RecordEpisodeListeningHandler,
    RecordNarrationMasterListeningHandler, RecordReviewDecisionHandler,
    RegisterAuthorizationHandler, ReorderPassagesHandler, RequireDictionaryHandler,
    RequireRenderRecipeHandler, ReviseDeliveryDefaultsHandler, RevisePassageTextHandler,
    SelectWorkingTakeHandler, SetIntroDiaryGapHandler, ShowAuthorizationStatusHandler,
    ShowEpisodeStatusHandler, ShowNarrationEditorHandler, ShowNarrationStatusHandler,
    ValidateRenderRecipeHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import AuthorityObservation
from heritage_archive.contexts.narrator_voice.infrastructure.budget_ledger import FilesystemGenerationBudgetLedger
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaCredentialUnavailable, CartesiaSynthesisGateway
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_policy import ConfiguredNarrationReleasePolicyResolver
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_recipe import CartesiaRecipeCompiler
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemArtifactEvidenceVerifier, FilesystemArtifactStore,
    FilesystemAttemptWorkspaceStore, FilesystemAttemptWorkspaceVerifier,
    FilesystemProviderEventVerifier,
)
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import (
    FilesystemAuthorizationRecordRepository, FilesystemDiaryEpisodeRepository, FilesystemNarrationJobRepository,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.local_operator import SingleOperatorActorResolver
from heritage_archive.contexts.narrator_voice.infrastructure.operations import DoctorResult, doctor, load_local_studio_configuration
from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import CanonicalWavInspector, ExactPcmAssembler


class EnvironmentCartesiaCredentialSupplier:
    def read_for_transmission(self) -> str:
        value = os.environ.get("CARTESIA_API_KEY")
        if value is None or not value or value != value.strip() or any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise CartesiaCredentialUnavailable("credential_unavailable")
        return value


class _UtcClock:
    def now(self):
        return datetime.now(timezone.utc)


class _Identifiers:
    def new_id(self, kind):
        return kind(str(uuid4()))


@dataclass(frozen=True, slots=True)
class FilesystemAuthorizationStatusReader:
    repository: FilesystemAuthorizationRecordRepository

    def read(self, record_id, observed_at):
        record = self.repository.load(record_id)
        if record is None:
            return AuthorityObservation(record_id, None, None)
        return AuthorityObservation(record_id, record.status_at(observed_at), record.observe(observed_at))


@dataclass(frozen=True, slots=True)
class NarrationStudioHandlers:
    """Route dependencies: application handlers and read-only storage readiness."""

    register_authorization: RegisterAuthorizationHandler
    show_authorization_status: ShowAuthorizationStatusHandler
    discover: DiscoverStudioHandler
    show_editor: ShowNarrationEditorHandler
    show_narration_status: ShowNarrationStatusHandler
    show_episode_status: ShowEpisodeStatusHandler
    prepare_diary: PrepareDiaryNarrationHandler
    prepare_intro: PrepareIntroNarrationHandler
    revise_passage_text: RevisePassageTextHandler
    reorder_passages: ReorderPassagesHandler
    revise_defaults: ReviseDeliveryDefaultsHandler
    validate_recipe: ValidateRenderRecipeHandler
    require_recipe: RequireRenderRecipeHandler
    require_dictionary: RequireDictionaryHandler
    estimate: EstimateGenerationHandler
    generate: GenerateTakeHandler
    reconcile_generation: ReconcileGenerationAttemptHandler
    record_review: RecordReviewDecisionHandler
    select_take: SelectWorkingTakeHandler
    assemble_narration: AssembleNarrationMasterHandler
    record_narration_listening: RecordNarrationMasterListeningHandler
    issue_narration_snapshot: IssueNarrationMasterSnapshotHandler
    reconcile_narration_assembly: ReconcileNarrationAssemblyAttemptHandler
    prepare_episode: PrepareDiaryEpisodeHandler
    attach_intro: AttachIntroMasterHandler
    attach_diary: AttachDiaryMasterHandler
    set_intro_diary_gap: SetIntroDiaryGapHandler
    assemble_episode: AssembleEpisodeSpeechMasterHandler
    record_episode_listening: RecordEpisodeListeningHandler
    reconcile_episode_assembly: ReconcileEpisodeAssemblyAttemptHandler
    read_take_audio: ReadTakeAudioHandler
    read_narration_master_audio: ReadNarrationMasterAudioHandler
    read_episode_master_audio: ReadEpisodeMasterAudioHandler
    readiness: Callable[[], DoctorResult]


@dataclass(frozen=True, slots=True)
class LiveNarrationStudio:
    """Own the transport; pass only ``handlers`` to the web boundary."""

    policies: ConfiguredNarrationReleasePolicyResolver
    gateway: CartesiaSynthesisGateway
    handlers: NarrationStudioHandlers
    transport: CartesiaSseTransport

    def close(self):
        self.transport.close()

    # Keep the original generation composition's public handler attributes.
    @property
    def prepare_diary(self) -> PrepareDiaryNarrationHandler:
        return self.handlers.prepare_diary

    @property
    def prepare_intro(self) -> PrepareIntroNarrationHandler:
        return self.handlers.prepare_intro

    @property
    def validate_recipe(self) -> ValidateRenderRecipeHandler:
        return self.handlers.validate_recipe

    @property
    def require_recipe(self) -> RequireRenderRecipeHandler:
        return self.handlers.require_recipe

    @property
    def estimate(self) -> EstimateGenerationHandler:
        return self.handlers.estimate

    @property
    def generate(self) -> GenerateTakeHandler:
        return self.handlers.generate


def build_live_narration(
    root: LocalNarrationRoot, *, process_principal: str | None = None,
) -> LiveNarrationStudio:
    """Construct shared local adapters without reading a key or transmitting.

    Web composition supplies its process principal explicitly. Existing one-argument
    callers receive a fresh principal generated from 32 cryptographically random bytes.
    """
    configuration = load_local_studio_configuration(root)
    policies = ConfiguredNarrationReleasePolicyResolver(configuration.lane_b, configuration.lane_c)
    authorizations = FilesystemAuthorizationRecordRepository(root)
    jobs = FilesystemNarrationJobRepository(root)
    episodes = FilesystemDiaryEpisodeRepository(root)
    authority = FilesystemAuthorizationStatusReader(authorizations)
    actors = SingleOperatorActorResolver(
        token_hex(32) if process_principal is None else process_principal,
        configuration.actor_id,
    )
    clock, identifiers = _UtcClock(), _Identifiers()
    media = CanonicalWavInspector()
    artifacts = FilesystemArtifactStore(root, identifiers)
    artifact_reader = FilesystemArtifactEvidenceVerifier(root, media)
    workspaces = FilesystemAttemptWorkspaceStore(root)
    workspace_verifier = FilesystemAttemptWorkspaceVerifier()
    provider_events = FilesystemProviderEventVerifier()
    compiler = CartesiaRecipeCompiler()
    budget_configuration = configuration.budget
    budget = FilesystemGenerationBudgetLedger(
        root, project_id=budget_configuration.project_id, billing_cycle_id=budget_configuration.billing_cycle_id,
        usage_unit=budget_configuration.usage_unit, per_take_cap=budget_configuration.per_take_cap,
        per_run_cap=budget_configuration.per_run_cap, project_cap=budget_configuration.project_cap,
        billing_cycle_cap=budget_configuration.billing_cycle_cap,
    )
    transport = CartesiaSseTransport()
    gateway = CartesiaSynthesisGateway(
        transport=transport, credentials=EnvironmentCartesiaCredentialSupplier(),
        policies=policies, artifacts=artifacts, clock=clock, identifiers=identifiers,
    )
    assembler = ExactPcmAssembler(artifact_reader)

    def readiness() -> DoctorResult:
        return doctor(root)

    handlers = NarrationStudioHandlers(
        register_authorization=RegisterAuthorizationHandler(authorizations, actors, clock),
        show_authorization_status=ShowAuthorizationStatusHandler(authorizations, clock),
        discover=DiscoverStudioHandler(jobs, episodes),
        show_editor=ShowNarrationEditorHandler(jobs),
        show_narration_status=ShowNarrationStatusHandler(jobs, authority, clock),
        show_episode_status=ShowEpisodeStatusHandler(episodes, jobs, authority, clock),
        prepare_diary=PrepareDiaryNarrationHandler(jobs, policies, authority, clock, identifiers),
        prepare_intro=PrepareIntroNarrationHandler(jobs, episodes, policies, authority, clock, identifiers),
        revise_passage_text=RevisePassageTextHandler(jobs, clock),
        reorder_passages=ReorderPassagesHandler(jobs),
        revise_defaults=ReviseDeliveryDefaultsHandler(jobs, clock),
        validate_recipe=ValidateRenderRecipeHandler(jobs, compiler),
        require_recipe=RequireRenderRecipeHandler(jobs),
        require_dictionary=RequireDictionaryHandler(jobs),
        estimate=EstimateGenerationHandler(jobs, authority, compiler, clock, identifiers),
        generate=GenerateTakeHandler(jobs, authority, clock, identifiers, budget, gateway, artifacts, media, workspaces),
        reconcile_generation=ReconcileGenerationAttemptHandler(
            jobs, authority, clock, workspaces, workspace_verifier, provider_events,
            artifact_reader, budget, budget, identifiers,
        ),
        record_review=RecordReviewDecisionHandler(jobs, actors, clock, identifiers),
        select_take=SelectWorkingTakeHandler(jobs, authority, actors, clock, identifiers),
        assemble_narration=AssembleNarrationMasterHandler(
            jobs, authority, clock, identifiers, assembler, artifacts, workspaces,
        ),
        record_narration_listening=RecordNarrationMasterListeningHandler(jobs, actors, clock, identifiers),
        issue_narration_snapshot=IssueNarrationMasterSnapshotHandler(jobs, authority, clock, identifiers),
        reconcile_narration_assembly=ReconcileNarrationAssemblyAttemptHandler(
            jobs, authority, clock, workspaces, workspace_verifier, provider_events,
            artifact_reader, identifiers,
        ),
        prepare_episode=PrepareDiaryEpisodeHandler(episodes, clock, identifiers),
        attach_intro=AttachIntroMasterHandler(episodes, jobs, authority, clock),
        attach_diary=AttachDiaryMasterHandler(episodes, jobs, authority, clock),
        set_intro_diary_gap=SetIntroDiaryGapHandler(episodes, clock),
        assemble_episode=AssembleEpisodeSpeechMasterHandler(
            episodes, jobs, authority, clock, identifiers, assembler, artifacts, workspaces,
        ),
        record_episode_listening=RecordEpisodeListeningHandler(episodes, actors, clock, identifiers),
        reconcile_episode_assembly=ReconcileEpisodeAssemblyAttemptHandler(
            episodes, jobs, authority, clock, workspaces, workspace_verifier,
            provider_events, artifact_reader, identifiers,
        ),
        read_take_audio=ReadTakeAudioHandler(jobs, artifact_reader, media),
        read_narration_master_audio=ReadNarrationMasterAudioHandler(jobs, artifact_reader, media),
        read_episode_master_audio=ReadEpisodeMasterAudioHandler(episodes, artifact_reader, media),
        readiness=readiness,
    )
    return LiveNarrationStudio(policies=policies, gateway=gateway, handlers=handlers, transport=transport)
