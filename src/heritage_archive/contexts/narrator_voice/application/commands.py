"""Frozen command envelope and explicit Narrator Voice use-case commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from heritage_archive.kernel import ContentDigest

from ..domain.evidence import (
    ListeningOutcome,
    NarrationMasterSnapshot,
    ReviewOutcome,
    TimingCue,
)
from ..domain.ids import (
    AuthorizationRecordId,
    CommandId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
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
from ..domain.narration_job import PassageDraft
from ..domain.values import (
    AuthorityScope,
    DictionaryBinding,
    DeliveryControlDefaults,
    PassageText,
    RenderControl,
    SafeRelativeArtifactPath,
)


class OverrideMode(str, Enum):
    INHERIT = "inherit"
    SET = "set"
    OMIT = "omit"


@dataclass(frozen=True, slots=True)
class TextControlOverride:
    mode: OverrideMode
    value: str | None = None


@dataclass(frozen=True, slots=True)
class DictionaryOverride:
    mode: OverrideMode
    value: DictionaryBinding | None = None


@dataclass(frozen=True, slots=True)
class TakeSettingsIntent:
    speed: TextControlOverride
    volume: TextControlOverride
    emotion: TextControlOverride
    dictionary: DictionaryOverride


class RecipeAuthoringMode(str, Enum):
    STRUCTURED = "structured"
    ADVANCED = "advanced"


@dataclass(frozen=True, slots=True)
class RecipeAuthoringIntent:
    recipe_id: PassageRenderRecipeId
    recipe_revision: int
    mode: RecipeAuthoringMode
    structured_controls: tuple[RenderControl, ...] = ()
    advanced_source: str | None = None


@dataclass(frozen=True, slots=True)
class RegisterAuthorizationCommand:
    command_id: CommandId
    principal: str
    record_id: AuthorizationRecordId
    scope: AuthorityScope
    evidence_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class RecordAuthorizationChangeCommand:
    command_id: CommandId
    principal: str
    record_id: AuthorizationRecordId
    expected_revision: int
    resulting_scope: AuthorityScope | None
    withdraw: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ShowAuthorizationStatusCommand:
    command_id: CommandId
    record_id: AuthorizationRecordId


@dataclass(frozen=True, slots=True)
class PrepareDiaryNarrationCommand:
    command_id: CommandId
    passages: tuple[PassageDraft, ...]


@dataclass(frozen=True, slots=True)
class PrepareIntroNarrationCommand:
    command_id: CommandId
    intended_episode_id: DiaryEpisodeId
    expected_episode_revision: int
    passages: tuple[PassageDraft, ...]


@dataclass(frozen=True, slots=True)
class RevisePassageTextCommand:
    command_id: CommandId
    job_id: NarrationJobId
    passage_id: PassageId
    text: PassageText
    expected_revision: int


@dataclass(frozen=True, slots=True)
class ReorderPassagesCommand:
    command_id: CommandId
    job_id: NarrationJobId
    ordered_passage_ids: tuple[PassageId, ...]
    expected_revision: int


@dataclass(frozen=True, slots=True)
class ReviseDeliveryDefaultsCommand:
    command_id: CommandId
    job_id: NarrationJobId
    defaults: DeliveryControlDefaults
    expected_revision: int


@dataclass(frozen=True, slots=True)
class ValidateRenderRecipeCommand:
    command_id: CommandId
    job_id: NarrationJobId
    passage_id: PassageId
    authoring: RecipeAuthoringIntent
    expected_revision: int


@dataclass(frozen=True, slots=True)
class RequireRenderRecipeCommand:
    command_id: CommandId
    job_id: NarrationJobId
    passage_id: PassageId
    recipe_id: PassageRenderRecipeId
    expected_revision: int


@dataclass(frozen=True, slots=True)
class RequireDictionaryCommand:
    command_id: CommandId
    job_id: NarrationJobId
    passage_id: PassageId
    dictionary_digest: ContentDigest
    expected_revision: int


@dataclass(frozen=True, slots=True)
class EstimateGenerationCommand:
    command_id: CommandId
    job_id: NarrationJobId
    passage_id: PassageId
    recipe_id: PassageRenderRecipeId
    settings_intent: TakeSettingsIntent
    expected_revision: int


@dataclass(frozen=True, slots=True)
class GenerateTakeCommand:
    command_id: CommandId
    job_id: NarrationJobId
    preview_id: GenerationPreviewId
    expected_revision: int
    artifact_location: SafeRelativeArtifactPath


@dataclass(frozen=True, slots=True)
class GeneratePendingPassagesCommand:
    command_id: CommandId
    job_id: NarrationJobId
    preview_ids: tuple[GenerationPreviewId, ...]
    expected_revision: int
    artifact_locations: tuple[SafeRelativeArtifactPath, ...]
    accepted_billable_character_cap: int


@dataclass(frozen=True, slots=True)
class RecordReviewDecisionCommand:
    command_id: CommandId
    principal: str
    job_id: NarrationJobId
    take_id: TakeId
    outcome: ReviewOutcome
    notes: str
    expected_revision: int


@dataclass(frozen=True, slots=True)
class SelectWorkingTakeCommand:
    command_id: CommandId
    principal: str
    job_id: NarrationJobId
    passage_id: PassageId
    take_id: TakeId
    reason: str
    expected_revision: int


@dataclass(frozen=True, slots=True)
class AssembleNarrationMasterCommand:
    command_id: CommandId
    job_id: NarrationJobId
    gaps_samples: tuple[int, ...]
    expected_revision: int
    artifact_location: SafeRelativeArtifactPath


@dataclass(frozen=True, slots=True)
class RecordNarrationMasterListeningCommand:
    command_id: CommandId
    principal: str
    job_id: NarrationJobId
    master_id: NarrationMasterId
    outcome: ListeningOutcome
    notes: str
    expected_revision: int


@dataclass(frozen=True, slots=True)
class IssueNarrationMasterSnapshotCommand:
    command_id: CommandId
    job_id: NarrationJobId
    master_id: NarrationMasterId
    expected_revision: int


@dataclass(frozen=True, slots=True)
class DiscoverStudioCommand:
    command_id: CommandId


@dataclass(frozen=True, slots=True)
class ShowNarrationEditorCommand:
    command_id: CommandId
    job_id: NarrationJobId


@dataclass(frozen=True, slots=True)
class ShowNarrationStatusCommand:
    command_id: CommandId
    job_id: NarrationJobId


@dataclass(frozen=True, slots=True)
class ReconcileGenerationAttemptCommand:
    command_id: CommandId
    job_id: NarrationJobId
    attempt_id: GenerationAttemptId
    expected_revision: int


@dataclass(frozen=True, slots=True)
class ReconcileNarrationAssemblyAttemptCommand:
    command_id: CommandId
    job_id: NarrationJobId
    attempt_id: NarrationAssemblyAttemptId
    expected_revision: int


@dataclass(frozen=True, slots=True)
class PrepareDiaryEpisodeCommand:
    command_id: CommandId


@dataclass(frozen=True, slots=True)
class AttachIntroMasterCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    snapshot: NarrationMasterSnapshot
    expected_revision: int


@dataclass(frozen=True, slots=True)
class AttachDiaryMasterCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    snapshot: NarrationMasterSnapshot
    expected_revision: int


@dataclass(frozen=True, slots=True)
class SetIntroDiaryGapCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    gap_samples: int
    expected_revision: int


@dataclass(frozen=True, slots=True)
class AssembleEpisodeSpeechMasterCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    expected_revision: int
    artifact_location: SafeRelativeArtifactPath


@dataclass(frozen=True, slots=True)
class RecordEpisodeListeningCommand:
    command_id: CommandId
    principal: str
    episode_id: DiaryEpisodeId
    master_id: EpisodeSpeechMasterId
    outcome: ListeningOutcome
    notes: str
    expected_revision: int


@dataclass(frozen=True, slots=True)
class BuildTimedNarrationPackageCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    master_id: EpisodeSpeechMasterId
    expected_revision: int


@dataclass(frozen=True, slots=True)
class RecordTimingCorrectionCommand:
    command_id: CommandId
    principal: str
    episode_id: DiaryEpisodeId
    source_package_id: TimedNarrationPackageId
    corrected_cues: tuple[TimingCue, ...]
    reason: str
    expected_revision: int


@dataclass(frozen=True, slots=True)
class ShowEpisodeStatusCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId


@dataclass(frozen=True, slots=True)
class ExportPresentationHandoffCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    package_id: TimedNarrationPackageId


@dataclass(frozen=True, slots=True)
class ReconcileEpisodeAssemblyAttemptCommand:
    command_id: CommandId
    episode_id: DiaryEpisodeId
    attempt_id: EpisodeAssemblyAttemptId
    expected_revision: int
