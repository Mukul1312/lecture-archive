"""Redacted immutable application results; private evidence stays in roots/workspaces."""

from __future__ import annotations

from dataclasses import dataclass

from heritage_archive.kernel import ActorId, ArtifactRef, ContentDigest

from ..domain.authorization import AuthorizationStatus
from ..domain.evidence import AttemptState, GenerationPreview, NarrationMasterSnapshot, PublishedArtifact
from ..domain.ids import (
    AuthorizationRecordId,
    CommandId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeSpeechMasterId,
    GenerationAttemptId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    TakeId,
    TimedNarrationPackageId,
)
from ..domain.values import Lane, NonNegativeDecimal, PassageRenderRecipe
from .status import (
    AuthorizationHistoryProjection,
    EpisodeStatusProjection,
    NarrationStatusProjection,
)


AuthorizationStatusResult = AuthorizationHistoryProjection
NarrationStatusResult = NarrationStatusProjection
EpisodeStatusResult = EpisodeStatusProjection


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    command_id: CommandId
    record_id: AuthorizationRecordId
    revision: int
    status: AuthorizationStatus


@dataclass(frozen=True, slots=True)
class NarrationMutationResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int


@dataclass(frozen=True, slots=True)
class NarrationPreparedResult(NarrationMutationResult):
    lane: Lane
    contract_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class RenderRecipeValidatedResult(NarrationMutationResult):
    recipe: PassageRenderRecipe
    canonical_projection: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GenerationEstimateResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int
    preview: GenerationPreview


@dataclass(frozen=True, slots=True)
class GenerationRunResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int
    attempt_id: GenerationAttemptId
    state: AttemptState
    take_id: TakeId | None
    budget_disposition: str


@dataclass(frozen=True, slots=True)
class GenerationBatchResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int
    runs: tuple[GenerationRunResult, ...]


@dataclass(frozen=True, slots=True)
class NarrationAssemblyResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int
    attempt_id: NarrationAssemblyAttemptId
    state: AttemptState
    master_id: NarrationMasterId | None


@dataclass(frozen=True, slots=True)
class SnapshotIssuedResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int
    snapshot: NarrationMasterSnapshot


@dataclass(frozen=True, slots=True)
class EpisodeMutationResult:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    revision: int


@dataclass(frozen=True, slots=True)
class EpisodeAssemblyResult:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    revision: int
    attempt_id: EpisodeAssemblyAttemptId
    state: AttemptState
    master_id: EpisodeSpeechMasterId | None


@dataclass(frozen=True, slots=True)
class TimedPackageResult:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    revision: int
    package_id: TimedNarrationPackageId
    version: int
    package_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class PresentationHandoffResult:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    episode_master_id: EpisodeSpeechMasterId
    speech_artifact: PublishedArtifact
    package_id: TimedNarrationPackageId
    package_digest: ContentDigest
    cue_count: int
    timing_artifact: ArtifactRef | None
