"""Application-owned ports and provider-neutral frozen boundary facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from heritage_archive.kernel import ActorId, ArtifactRef, ContentDigest, ValidationError

from ..domain.authorization import AuthorizationRecord, AuthorizationStatus
from ..domain.diary_episode import DiaryEpisode
from ..domain.evidence import (
    AttemptState,
    AttemptWorkspaceEvidence,
    AuthoritySnapshot,
    ComponentOffset,
    DecodedMediaFacts,
    NarrationMasterSnapshot,
    PassageOffset,
    ProviderEventEvidence,
    ProviderTerminalClass,
    ReviewAuthority,
    PublishedArtifact,
    TimingCue,
    TimingReviewStatus,
    SubmissionEvidence,
)
from ..domain.ids import (
    AuthorizationRecordId,
    BudgetReservationId,
    CommandId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    GenerationAttemptId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    PassageId,
    PassageRenderRecipeId,
)
from ..domain.narration_job import NarrationJob
from ..domain.values import (
    DeliveryControlDefaults,
    ComponentRole,
    EffectiveSynthesisInput,
    EffectiveTakeSettings,
    Lane,
    NonNegativeDecimal,
    PassageRenderRecipe,
    PassageText,
    RenderControl,
    ReleaseSynthesisContract,
    SafeRelativeArtifactPath,
)
from .recovery import BudgetRecoveryState, RecoveryStage, RecoveryTarget


IdT = TypeVar("IdT")


class AuthorizationRecordRepository(Protocol):
    def load(self, record_id: AuthorizationRecordId) -> AuthorizationRecord | None: ...
    def save(self, record: AuthorizationRecord, expected_revision: int | None) -> bool: ...


class NarrationJobRepository(Protocol):
    def list_ids(self) -> tuple[NarrationJobId, ...]: ...
    def load(self, job_id: NarrationJobId) -> NarrationJob | None: ...
    def save(self, job: NarrationJob, expected_revision: int | None) -> bool: ...


class DiaryEpisodeRepository(Protocol):
    def list_ids(self) -> tuple[DiaryEpisodeId, ...]: ...
    def load(self, episode_id: DiaryEpisodeId) -> DiaryEpisode | None: ...
    def save(self, episode: DiaryEpisode, expected_revision: int | None) -> bool: ...


@dataclass(frozen=True, slots=True)
class ReleasePolicyResolution:
    contract: ReleaseSynthesisContract
    initial_defaults: DeliveryControlDefaults


class NarrationReleasePolicyResolver(Protocol):
    def resolve_lane_b_diary(self) -> ReleasePolicyResolution: ...

    def resolve_lane_c_intro(
        self,
        intended_episode_id: DiaryEpisodeId,
    ) -> ReleasePolicyResolution: ...


@dataclass(frozen=True, slots=True)
class AuthorityObservation:
    record_id: AuthorizationRecordId
    status: AuthorizationStatus | None
    snapshot: AuthoritySnapshot | None

    @property
    def active(self) -> bool:
        return self.status is AuthorizationStatus.ACTIVE and self.snapshot is not None


class AuthorizationStatusReader(Protocol):
    def read(self, record_id: AuthorizationRecordId, observed_at: datetime) -> AuthorityObservation: ...


@dataclass(frozen=True, slots=True)
class PrincipalAuthority:
    actor_id: ActorId
    can_administer_authority: bool
    review_authority: ReviewAuthority | None
    timing_review_status: TimingReviewStatus | None


class ActorResolver(Protocol):
    def resolve_principal(self, principal: str) -> PrincipalAuthority: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierSource(Protocol):
    def new_id(self, kind: type[IdT]) -> IdT: ...


@dataclass(frozen=True, slots=True)
class RecipeCompileRequest:
    job_id: NarrationJobId
    text_revision: int
    text: PassageText
    recipe: PassageRenderRecipe
    settings: EffectiveTakeSettings
    contract: ReleaseSynthesisContract
    authority_snapshot: AuthoritySnapshot


@dataclass(frozen=True, slots=True)
class RecipeAuthoringRequest:
    job_id: NarrationJobId
    passage_id: PassageId
    text_revision: int
    text: PassageText
    recipe_id: PassageRenderRecipeId
    recipe_revision: int
    structured_controls: tuple[RenderControl, ...]
    advanced_source: str | None
    contract: ReleaseSynthesisContract


@dataclass(frozen=True, slots=True)
class RecipeAuthoringResult:
    recipe: PassageRenderRecipe
    canonical_projection: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreviewCompilerResult:
    compiler_version: str
    endpoint: str
    rendered_transcript: str
    canonical_projection: str
    timestamps_requested: bool
    normalization: str
    billable_rule: str
    billable_characters: int
    estimated_usage: NonNegativeDecimal


class RecipeCompiler(Protocol):
    def compile_recipe(self, request: RecipeAuthoringRequest) -> RecipeAuthoringResult: ...

    def compile(self, request: RecipeCompileRequest) -> PreviewCompilerResult: ...


@dataclass(frozen=True, slots=True)
class SynthesisInvocation:
    attempt_id: GenerationAttemptId
    contract: ReleaseSynthesisContract
    effective_input: EffectiveSynthesisInput

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not GenerationAttemptId
            or type(self.contract) is not ReleaseSynthesisContract
            or type(self.effective_input) is not EffectiveSynthesisInput
        ):
            raise ValidationError("synthesis invocation requires exact frozen boundary facts")
        if self.contract.digest != self.effective_input.contract_digest:
            raise ValidationError("synthesis invocation contract digest does not match frozen input")


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    events: tuple[ProviderEventEvidence, ...]
    canonical_wav_bytes: bytes
    evidence_publications: tuple[PublishedArtifact, ...]
    raw_timing_reference: ArtifactRef | None
    usage: NonNegativeDecimal

    def __post_init__(self) -> None:
        _validate_synthesis_evidence(
            self.events,
            self.evidence_publications,
            self.raw_timing_reference,
        )
        if type(self.canonical_wav_bytes) is not bytes:
            raise ValidationError("synthesis result canonical WAV payload must be bytes")
        if type(self.usage) is not NonNegativeDecimal:
            raise ValidationError("synthesis result usage must be authoritative nonnegative usage")


def _validate_synthesis_evidence(
    events: object,
    publications: object,
    raw_timing_reference: object,
) -> None:
    """Validate provider references against their immutable publication evidence."""
    if (
        type(events) is not tuple
        or any(type(event) is not ProviderEventEvidence for event in events)
        or tuple(event.sequence for event in events) != tuple(range(len(events)))
    ):
        raise ValidationError("synthesis provider events must be a contiguous immutable stream")
    if type(publications) is not tuple or any(
        type(publication) is not PublishedArtifact for publication in publications
    ):
        raise ValidationError("synthesis publications must be immutable artifact evidence")
    if raw_timing_reference is not None and type(raw_timing_reference) is not ArtifactRef:
        raise ValidationError("synthesis raw timing reference must be an ArtifactRef or None")

    references = tuple(
        reference
        for event in events
        for reference in (
            event.sanitized_raw_reference,
            event.pcm_reference,
            event.timing_reference,
        )
        if reference is not None
    )
    if raw_timing_reference is not None:
        references += (raw_timing_reference,)
    published_references = tuple(publication.reference for publication in publications)
    if any(published_references.count(reference) != 1 for reference in references):
        raise ValidationError("each synthesis evidence reference requires one exact publication")
    if any(reference not in references for reference in published_references):
        raise ValidationError("synthesis publications must be referenced by provider evidence")
    if len(set(published_references)) != len(published_references):
        raise ValidationError("synthesis publication identities must be unique")


class SynthesisGateway(Protocol):
    def synthesize(self, invocation: SynthesisInvocation) -> SynthesisResult: ...


class ImmutableArtifactStore(Protocol):
    def publish(
        self,
        location: SafeRelativeArtifactPath,
        payload: bytes,
        media_type: str,
        published_at: datetime,
    ) -> PublishedArtifact: ...


class AttemptWorkspaceStore(Protocol):
    def load(
        self,
        attempt_id: GenerationAttemptId | NarrationAssemblyAttemptId | EpisodeAssemblyAttemptId,
    ) -> AttemptWorkspaceEvidence | None: ...
    def save(self, workspace: AttemptWorkspaceEvidence) -> None: ...


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceRecoveryFacts:
    """Trusted binding and progression facts read from an attempt workspace."""

    workspace_matches_attempt: bool
    frozen_plan_matches: bool
    last_confirmed_stage: RecoveryStage
    submission: SubmissionEvidence


class AttemptWorkspaceVerifier(Protocol):
    """Verifies a private attempt workspace against its aggregate attempt."""

    def verify(
        self,
        workspace: AttemptWorkspaceEvidence | None,
        target: RecoveryTarget,
        attempt_state: AttemptState,
        reservation_revision: int,
        expected_frozen_plan_digest: ContentDigest | None,
    ) -> VerifiedWorkspaceRecoveryFacts: ...


@dataclass(frozen=True, slots=True)
class VerifiedProviderRecoveryFacts:
    """Provider-event facts derived from sealed private evidence, never caller text."""

    provider_terminal: ProviderTerminalClass | None
    events_sealed: bool


class ProviderEventVerifier(Protocol):
    def verify(self, workspace: AttemptWorkspaceEvidence | None) -> VerifiedProviderRecoveryFacts: ...


@dataclass(frozen=True, slots=True)
class VerifiedArtifactRecoveryFacts:
    """Artifact and publication verification against immutable backing storage."""

    artifact_observed: bool
    artifact_verified: bool
    publication_observed: bool
    publication_verified: bool


class ArtifactEvidenceVerifier(Protocol):
    def verify(self, workspace: AttemptWorkspaceEvidence | None) -> VerifiedArtifactRecoveryFacts: ...

    def recover_media(
        self,
        workspace: AttemptWorkspaceEvidence,
        artifact: PublishedArtifact,
    ) -> DecodedMediaFacts: ...


class BudgetReservationStatusReader(Protocol):
    """Reads the ledger's trusted state; this port has no reserve/settle side effect."""

    def read(self, reservation_id: BudgetReservationId) -> BudgetRecoveryState: ...


class MediaInspector(Protocol):
    def inspect_canonical_wav(self, payload: bytes) -> DecodedMediaFacts: ...


@dataclass(frozen=True, slots=True)
class DryPcmSource:
    artifact: PublishedArtifact
    media: DecodedMediaFacts


@dataclass(frozen=True, slots=True)
class DryAssemblyResult:
    canonical_wav_bytes: bytes
    media: DecodedMediaFacts
    passage_offsets: tuple[PassageOffset, ...] = ()
    component_offsets: tuple[ComponentOffset, ...] = ()


class DryPcmAssembler(Protocol):
    def assemble_narration(
        self,
        sources: tuple[DryPcmSource, ...],
        gaps_samples: tuple[int, ...],
        source_offsets: tuple[PassageOffset, ...],
    ) -> DryAssemblyResult: ...

    def assemble_episode(
        self,
        intro: DryPcmSource,
        diary: DryPcmSource,
        gap_samples: int,
        intro_offsets: tuple[PassageOffset, ...],
        diary_offsets: tuple[PassageOffset, ...],
        intro_snapshot_digest: ContentDigest,
        diary_snapshot_digest: ContentDigest,
    ) -> DryAssemblyResult: ...


@dataclass(frozen=True, slots=True)
class TimingSourcePassage:
    role: ComponentRole
    lane: Lane
    source_job_id: NarrationJobId
    source_master_id: NarrationMasterId
    passage_id: PassageId
    text_revision: int
    text_digest: ContentDigest
    display_text: str
    timing_reference: ArtifactRef | None
    start_sample: int
    end_sample: int


@dataclass(frozen=True, slots=True)
class TimingNormalizationRequest:
    episode_id: DiaryEpisodeId
    episode_revision: int
    master_artifact: PublishedArtifact
    master_media: DecodedMediaFacts
    component_offsets: tuple[ComponentOffset, ...]
    intro_snapshot: NarrationMasterSnapshot
    diary_snapshot: NarrationMasterSnapshot
    source_passages: tuple[TimingSourcePassage, ...]
    raw_timing_artifacts: tuple[ArtifactRef, ...]


@dataclass(frozen=True, slots=True)
class TimingNormalizationResult:
    cues: tuple[TimingCue, ...]
    normalized_timing_artifact: ArtifactRef | None
    validation_results: tuple[str, ...]
    review_status: TimingReviewStatus


class TimingNormalizer(Protocol):
    def normalize(self, request: TimingNormalizationRequest) -> TimingNormalizationResult: ...


class GenerationBudgetLedger(Protocol):
    def reserve(
        self,
        reservation_id: BudgetReservationId,
        run_id: CommandId,
        estimated_usage: NonNegativeDecimal,
    ) -> None: ...

    def settle(self, reservation_id: BudgetReservationId, actual_usage: NonNegativeDecimal) -> None: ...
    def release(self, reservation_id: BudgetReservationId, reason: str) -> None: ...
    def hold(self, reservation_id: BudgetReservationId, reason: str) -> None: ...
