"""Redacted immutable application results; private evidence stays in roots/workspaces."""

from __future__ import annotations

from dataclasses import dataclass

from heritage_archive.kernel import ActorId, ArtifactRef, ContentDigest

from ..domain.authorization import AuthorizationStatus
from ..domain.diary_episode import EpisodeStatus
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
from ..domain.values import Lane, NonNegativeDecimal


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    command_id: CommandId
    record_id: AuthorizationRecordId
    revision: int
    status: AuthorizationStatus


@dataclass(frozen=True, slots=True)
class AuthorizationStatusResult:
    command_id: CommandId
    record_id: AuthorizationRecordId
    revision: int | None
    status: AuthorizationStatus | None
    observed_snapshot_digest: ContentDigest | None


@dataclass(frozen=True, slots=True)
class NarrationMutationResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int


@dataclass(frozen=True, slots=True)
class NarrationPreparedResult(NarrationMutationResult):
    lane: Lane


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
class NarrationStatusResult:
    command_id: CommandId
    job_id: NarrationJobId
    revision: int
    lane: Lane
    passage_count: int
    take_count: int
    master_count: int
    snapshot_count: int


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
class EpisodeStatusResult:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    revision: int
    status: EpisodeStatus
    has_master: bool
    has_passing_listen: bool
    timing_versions: int


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
