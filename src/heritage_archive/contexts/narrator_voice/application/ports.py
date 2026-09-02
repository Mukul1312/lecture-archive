"""Application-owned ports and provider-neutral frozen boundary facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from heritage_archive.kernel import ActorId, ArtifactRef, ContentDigest

from ..domain.authorization import AuthorizationRecord, AuthorizationStatus
from ..domain.diary_episode import DiaryEpisode
from ..domain.evidence import (
    AttemptWorkspaceEvidence,
    AuthoritySnapshot,
    ComponentOffset,
    DecodedMediaFacts,
    NarrationMasterSnapshot,
    PassageOffset,
    ProviderEventEvidence,
    PublishedArtifact,
    TimingCue,
    TimingReviewStatus,
)
from ..domain.ids import (
    AuthorizationRecordId,
    BudgetReservationId,
    DiaryEpisodeId,
    NarrationJobId,
)
from ..domain.narration_job import NarrationJob
from ..domain.values import (
    EffectiveSynthesisInput,
    EffectiveTakeSettings,
    NonNegativeDecimal,
    PassageRenderRecipe,
    PassageText,
    ReleaseSynthesisContract,
    SafeRelativeArtifactPath,
)


IdT = TypeVar("IdT")


class AuthorizationRecordRepository(Protocol):
    def load(self, record_id: AuthorizationRecordId) -> AuthorizationRecord | None: ...
    def save(self, record: AuthorizationRecord, expected_revision: int | None) -> bool: ...


class NarrationJobRepository(Protocol):
    def load(self, job_id: NarrationJobId) -> NarrationJob | None: ...
    def save(self, job: NarrationJob, expected_revision: int | None) -> bool: ...


class DiaryEpisodeRepository(Protocol):
    def load(self, episode_id: DiaryEpisodeId) -> DiaryEpisode | None: ...
    def save(self, episode: DiaryEpisode, expected_revision: int | None) -> bool: ...


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


class ActorResolver(Protocol):
    def resolve_actor(self, principal: str) -> ActorId: ...


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
class PreviewCompilerResult:
    compiler_version: str
    endpoint: str
    rendered_transcript: str
    canonical_projection: str
    timestamps_requested: bool
    normalization: str
    billable_rule: str
    estimated_usage: NonNegativeDecimal


class RecipeCompiler(Protocol):
    def compile(self, request: RecipeCompileRequest) -> PreviewCompilerResult: ...


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    events: tuple[ProviderEventEvidence, ...]
    canonical_wav_bytes: bytes
    raw_timing_artifacts: tuple[ArtifactRef, ...]
    usage: NonNegativeDecimal


class SynthesisGateway(Protocol):
    def synthesize(self, effective_input: EffectiveSynthesisInput) -> SynthesisResult: ...


class ImmutableArtifactStore(Protocol):
    def publish(
        self,
        location: SafeRelativeArtifactPath,
        payload: bytes,
        media_type: str,
        published_at: datetime,
    ) -> PublishedArtifact: ...


class AttemptWorkspaceStore(Protocol):
    def load(self, attempt_id: str) -> AttemptWorkspaceEvidence | None: ...
    def save(self, workspace: AttemptWorkspaceEvidence) -> None: ...


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
class TimingNormalizationRequest:
    episode_id: DiaryEpisodeId
    episode_revision: int
    master_artifact: PublishedArtifact
    master_media: DecodedMediaFacts
    component_offsets: tuple[ComponentOffset, ...]
    intro_snapshot: NarrationMasterSnapshot
    diary_snapshot: NarrationMasterSnapshot
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
        estimated_usage: NonNegativeDecimal,
    ) -> None: ...

    def settle(self, reservation_id: BudgetReservationId, actual_usage: NonNegativeDecimal) -> None: ...
    def release(self, reservation_id: BudgetReservationId, reason: str) -> None: ...
    def hold(self, reservation_id: BudgetReservationId, reason: str) -> None: ...
