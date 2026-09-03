"""Immutable cross-stage evidence and schema-bearing child history records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from heritage_archive.kernel import ActorId, ArtifactRef, ContentDigest, ValidationError, semantic_digest

from .ids import (
    AttemptWorkspaceId,
    AuthorizationRecordId,
    BudgetReservationId,
    CueId,
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
    PassageId,
    PassageRenderRecipeId,
    ProviderEventId,
    ReviewDecisionId,
    SelectionDecisionId,
    TakeId,
    TimedNarrationPackageId,
)
from .values import (
    AuthorityScope,
    CanonicalAudioFacts,
    ComponentRole,
    EffectiveSynthesisInput,
    EffectiveTakeSettings,
    Lane,
    NonNegativeDecimal,
    PassageText,
    SafeRelativeArtifactPath,
    TextSpan,
)


def _utc(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f"{field} must be an aware UTC datetime")
    return value


def _positive_revision(value: object, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        raise ValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _required(value: object, field: str) -> str:
    from heritage_archive.kernel import require_canonical_text

    return require_canonical_text(value, field=field, nonempty=True)


class AttemptKind(str, Enum):
    GENERATION = "generation"
    NARRATION_ASSEMBLY = "narration_assembly"
    EPISODE_ASSEMBLY = "episode_assembly"


class AttemptState(str, Enum):
    RESERVED = "reserved"
    INPUT_FROZEN = "input_frozen"
    EXTERNAL_WORK_STARTED = "external_work_started"
    ARTIFACTS_STAGED = "artifacts_staged"
    ARTIFACTS_PUBLISHED = "artifacts_published"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNKNOWN = "unknown"
    QUARANTINED = "quarantined"
    COMPLETED = "completed"

    @property
    def terminal(self) -> bool:
        return self in {
            AttemptState.BLOCKED,
            AttemptState.FAILED,
            AttemptState.UNKNOWN,
            AttemptState.QUARANTINED,
            AttemptState.COMPLETED,
        }


def narration_assembly_plan_digest(
    selected_take_ids: tuple[TakeId, ...],
    gaps_samples: tuple[int, ...],
) -> ContentDigest:
    """Digest the exact ordered narration assembly plan owned by an attempt."""
    if (
        type(selected_take_ids) is not tuple
        or not selected_take_ids
        or any(type(value) is not TakeId for value in selected_take_ids)
        or len(set(selected_take_ids)) != len(selected_take_ids)
    ):
        raise ValidationError("narration assembly plan requires unique immutable selected take identities")
    if (
        type(gaps_samples) is not tuple
        or len(gaps_samples) != len(selected_take_ids) - 1
        or any(type(value) is not int or value < 0 for value in gaps_samples)
    ):
        raise ValidationError("narration assembly plan gaps must exactly separate selected takes")
    return semantic_digest(
        "narrator_voice.narration_assembly_plan.v1",
        {
            "selected_take_ids": [str(value.value) for value in selected_take_ids],
            "gaps_samples": list(gaps_samples),
        },
    )


def episode_assembly_plan_digest(
    component_snapshot_digests: tuple[ContentDigest, ...],
    gap_samples: int,
) -> ContentDigest:
    """Digest the exact intro/diary assembly plan owned by an episode attempt."""
    if (
        type(component_snapshot_digests) is not tuple
        or len(component_snapshot_digests) != 2
        or any(type(value) is not ContentDigest for value in component_snapshot_digests)
    ):
        raise ValidationError("episode assembly plan requires exactly intro and diary snapshot digests")
    if type(gap_samples) is not int or gap_samples < 0:
        raise ValidationError("episode assembly plan gap must be a nonnegative integer sample count")
    return semantic_digest(
        "narrator_voice.episode_assembly_plan.v1",
        {
            "component_snapshot_digests": [value.hex_digest for value in component_snapshot_digests],
            "gap_samples": gap_samples,
        },
    )


class SubmissionEvidence(str, Enum):
    NOT_STARTED = "not_started"
    DEFINITELY_NOT_SENT = "definitely_not_sent"
    STARTED = "started"
    COMPLETED = "completed"
    AMBIGUOUS = "ambiguous"


class ProviderEventKind(str, Enum):
    REQUEST = "request"
    AUDIO = "audio"
    TIMING = "timing"
    USAGE = "usage"
    TERMINAL = "terminal"
    ERROR = "error"


class ProviderTerminalClass(str, Enum):
    SUCCESS = "success"
    DEFINITE_PRE_SEND_FAILURE = "definite_pre_send_failure"
    FAILURE = "failure"
    AMBIGUOUS = "ambiguous"


class ReviewAuthority(str, Enum):
    OPERATIONAL = "operational"
    QUALIFIED_ODIA = "qualified_odia"


class ReviewOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ListeningOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class CueGranularity(str, Enum):
    COMPONENT = "component"
    PASSAGE = "passage"
    SENTENCE = "sentence"
    WORD = "word"


class CueProvenance(str, Enum):
    DETERMINISTIC_ASSEMBLY = "deterministic_assembly"
    PROVIDER_TIMESTAMP = "provider_timestamp"
    FORCED_ALIGNMENT = "forced_alignment"
    MANUAL_CORRECTION = "manual_correction"


class TimingReviewStatus(str, Enum):
    UNTRUSTED = "untrusted"
    VALIDATED = "validated"
    HUMAN_REVIEWED = "human_reviewed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class EligibilityFacts:
    text_stale: bool
    recipe_ineligible: bool
    dictionary_ineligible: bool
    contract_ineligible: bool
    authority_ineligible: bool

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (
            self.text_stale,
            self.recipe_ineligible,
            self.dictionary_ineligible,
            self.contract_ineligible,
            self.authority_ineligible,
        )):
            raise ValidationError("eligibility facts must be exact booleans")

    @property
    def eligible(self) -> bool:
        return not any((
            self.text_stale,
            self.recipe_ineligible,
            self.dictionary_ineligible,
            self.contract_ineligible,
            self.authority_ineligible,
        ))


@dataclass(frozen=True, slots=True)
class AuthoritySnapshot:
    record_id: AuthorizationRecordId
    record_revision: int
    scope: AuthorityScope
    record_digest: ContentDigest
    observed_at: datetime
    snapshot_digest: ContentDigest

    @classmethod
    def create(
        cls,
        record_id: AuthorizationRecordId,
        record_revision: int,
        scope: AuthorityScope,
        record_digest: ContentDigest,
        observed_at: datetime,
    ) -> AuthoritySnapshot:
        value = semantic_digest(
            "narrator_voice.authority_snapshot.v1",
            {
                "record_id": record_id.value,
                "record_revision": record_revision,
                "scope_digest": scope.digest.hex_digest,
                "record_digest": record_digest.hex_digest,
                "observed_at": observed_at.isoformat(),
            },
        )
        return cls(record_id, record_revision, scope, record_digest, observed_at, value)

    def __post_init__(self) -> None:
        if type(self.record_id) is not AuthorizationRecordId:
            raise ValidationError("authority snapshot requires an AuthorizationRecordId")
        _positive_revision(self.record_revision, "authority snapshot record revision")
        if type(self.scope) is not AuthorityScope or type(self.record_digest) is not ContentDigest:
            raise ValidationError("authority snapshot scope or record digest is invalid")
        _utc(self.observed_at, "authority snapshot observation time")
        expected = semantic_digest(
            "narrator_voice.authority_snapshot.v1",
            {
                "record_id": self.record_id.value,
                "record_revision": self.record_revision,
                "scope_digest": self.scope.digest.hex_digest,
                "record_digest": self.record_digest.hex_digest,
                "observed_at": self.observed_at.isoformat(),
            },
        )
        if self.snapshot_digest != expected:
            raise ValidationError("authority snapshot digest does not match its canonical facts")


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    reference: ArtifactRef
    relative_location: SafeRelativeArtifactPath
    published_at: datetime

    def __post_init__(self) -> None:
        if type(self.reference) is not ArtifactRef or type(self.relative_location) is not SafeRelativeArtifactPath:
            raise ValidationError("published artifact requires exact reference and safe relative location")
        _utc(self.published_at, "artifact publication time")


@dataclass(frozen=True, slots=True)
class DecodedMediaFacts:
    audio: CanonicalAudioFacts
    sample_count: int
    duration_ms: int
    all_digital_silence: bool

    def __post_init__(self) -> None:
        if type(self.audio) is not CanonicalAudioFacts:
            raise ValidationError("decoded media must use canonical audio facts")
        if type(self.sample_count) is not int or self.sample_count <= 0:
            raise ValidationError("decoded media sample count must be a positive integer")
        if type(self.duration_ms) is not int or self.duration_ms <= 0:
            raise ValidationError("decoded media duration must be a positive integer")
        expected_duration_ms = max(1, self.sample_count * 1_000 // self.audio.sample_rate_hz)
        if self.duration_ms != expected_duration_ms:
            raise ValidationError("decoded media duration must be the canonical projection of exact samples")
        if type(self.all_digital_silence) is not bool:
            raise ValidationError("digital-silence fact must be boolean")


@dataclass(frozen=True, slots=True)
class PassageOffset:
    passage_id: PassageId
    text_revision: int
    text_digest: ContentDigest
    start_sample: int
    end_sample: int

    def __post_init__(self) -> None:
        if type(self.passage_id) is not PassageId or type(self.text_digest) is not ContentDigest:
            raise ValidationError("passage offset binding is invalid")
        _positive_revision(self.text_revision, "passage offset text revision")
        if type(self.start_sample) is not int or type(self.end_sample) is not int or self.start_sample < 0 or self.end_sample <= self.start_sample:
            raise ValidationError("passage offset must be a nonempty nonnegative sample range")


@dataclass(frozen=True, slots=True)
class ComponentOffset:
    role: ComponentRole
    start_sample: int
    end_sample: int
    snapshot_digest: ContentDigest
    passage_offsets: tuple[PassageOffset, ...]

    def __post_init__(self) -> None:
        if type(self.role) is not ComponentRole or type(self.snapshot_digest) is not ContentDigest:
            raise ValidationError("component offset role or snapshot digest is invalid")
        if type(self.start_sample) is not int or type(self.end_sample) is not int or self.start_sample < 0 or self.end_sample <= self.start_sample:
            raise ValidationError("component offset must be a nonempty nonnegative sample range")
        if type(self.passage_offsets) is not tuple:
            raise ValidationError("component passage offsets must be an immutable tuple")
        previous = self.start_sample
        for offset in self.passage_offsets:
            if type(offset) is not PassageOffset or offset.start_sample < self.start_sample or offset.end_sample > self.end_sample or offset.start_sample < previous:
                raise ValidationError("component passage offsets must be ordered and contained")
            previous = offset.end_sample


@dataclass(frozen=True, slots=True)
class GenerationPreview:
    preview_id: GenerationPreviewId
    base_job_revision: int
    passage_id: PassageId
    text_revision: int
    text_digest: ContentDigest
    recipe_id: PassageRenderRecipeId
    recipe_revision: int
    recipe_digest: ContentDigest
    settings: EffectiveTakeSettings
    contract_digest: ContentDigest
    authority_snapshot: AuthoritySnapshot
    compiler_version: str
    capability_snapshot: str
    endpoint: str
    rendered_transcript: str
    rendered_transcript_byte_length: int
    rendered_transcript_digest: ContentDigest
    canonical_projection: str
    canonical_projection_digest: ContentDigest
    timestamps_requested: bool
    normalization: str
    output_audio: CanonicalAudioFacts
    billable_rule: str
    billable_characters: int
    estimated_usage: str
    issued_at: datetime
    preview_digest: ContentDigest

    @classmethod
    def create(cls, **arguments: object) -> GenerationPreview:
        rendered = _required(arguments.get("rendered_transcript"), "preview rendered transcript")
        projection = _required(arguments.get("canonical_projection"), "preview canonical projection")
        raw = rendered.encode("utf-8")
        if len(raw) > 16_384:
            raise ValidationError("advanced compiler output must not exceed 16,384 UTF-8 bytes")
        rendered_digest = ContentDigest.from_bytes(raw)
        projection_digest = ContentDigest.from_bytes(projection.encode("utf-8"))
        estimated_usage = arguments.get("estimated_usage")
        NonNegativeDecimal(estimated_usage)
        preview_digest = cls._digest(
            arguments,
            len(raw),
            rendered_digest,
            projection_digest,
        )
        return cls(
            **arguments,
            rendered_transcript_byte_length=len(raw),
            rendered_transcript_digest=rendered_digest,
            canonical_projection_digest=projection_digest,
            preview_digest=preview_digest,
        )

    @staticmethod
    def _digest(arguments: dict[str, object], byte_length: int, rendered_digest: ContentDigest, projection_digest: ContentDigest) -> ContentDigest:
        return semantic_digest(
            "narrator_voice.generation_preview.v1",
            {
                "preview_id": arguments["preview_id"].value,
                "base_job_revision": arguments["base_job_revision"],
                "passage_id": arguments["passage_id"].value,
                "text_revision": arguments["text_revision"],
                "text_digest": arguments["text_digest"].hex_digest,
                "recipe_id": arguments["recipe_id"].value,
                "recipe_revision": arguments["recipe_revision"],
                "recipe_digest": arguments["recipe_digest"].hex_digest,
                "settings_digest": arguments["settings"].digest.hex_digest,
                "contract_digest": arguments["contract_digest"].hex_digest,
                "authority_snapshot_digest": arguments["authority_snapshot"].snapshot_digest.hex_digest,
                "compiler_version": arguments["compiler_version"],
                "capability_snapshot": arguments["capability_snapshot"],
                "endpoint": arguments["endpoint"],
                "rendered_transcript_byte_length": byte_length,
                "rendered_transcript_digest": rendered_digest.hex_digest,
                "canonical_projection_digest": projection_digest.hex_digest,
                "timestamps_requested": arguments["timestamps_requested"],
                "normalization": arguments["normalization"],
                "output": "wav/pcm_s16le/16/little/1/44100",
                "billable_rule": arguments["billable_rule"],
                "billable_characters": arguments["billable_characters"],
                "estimated_usage": arguments["estimated_usage"],
                "issued_at": arguments["issued_at"].isoformat(),
            },
        )

    def __post_init__(self) -> None:
        if type(self.preview_id) is not GenerationPreviewId or type(self.passage_id) is not PassageId:
            raise ValidationError("generation preview identity binding is invalid")
        _positive_revision(self.base_job_revision, "preview base job revision", allow_zero=True)
        _positive_revision(self.text_revision, "preview text revision")
        _positive_revision(self.recipe_revision, "preview recipe revision")
        if type(self.text_digest) is not ContentDigest or type(self.recipe_id) is not PassageRenderRecipeId or type(self.recipe_digest) is not ContentDigest:
            raise ValidationError("generation preview text or recipe binding is invalid")
        if type(self.settings) is not EffectiveTakeSettings or type(self.contract_digest) is not ContentDigest or type(self.authority_snapshot) is not AuthoritySnapshot:
            raise ValidationError("generation preview settings, contract or authority binding is invalid")
        for field, value in (("compiler version", self.compiler_version), ("capability snapshot", self.capability_snapshot), ("endpoint", self.endpoint), ("rendered transcript", self.rendered_transcript), ("canonical projection", self.canonical_projection), ("normalization", self.normalization), ("billable rule", self.billable_rule)):
            _required(value, field)
        if type(self.timestamps_requested) is not bool or type(self.output_audio) is not CanonicalAudioFacts:
            raise ValidationError("generation preview request/output flags are invalid")
        NonNegativeDecimal(self.estimated_usage)
        if type(self.billable_characters) is not int or self.billable_characters < 0:
            raise ValidationError("preview billable characters must be a nonnegative integer")
        _utc(self.issued_at, "preview issuance time")
        raw = self.rendered_transcript.encode("utf-8")
        if len(raw) > 16_384:
            raise ValidationError("advanced compiler output must not exceed 16,384 UTF-8 bytes")
        if self.rendered_transcript_byte_length != len(raw) or self.rendered_transcript_digest != ContentDigest.from_bytes(raw):
            raise ValidationError("preview exact rendered transcript byte evidence is inconsistent")
        if self.canonical_projection_digest != ContentDigest.from_bytes(self.canonical_projection.encode("utf-8")):
            raise ValidationError("preview projection digest is inconsistent")
        arguments: dict[str, object] = {
            "preview_id": self.preview_id,
            "base_job_revision": self.base_job_revision,
            "passage_id": self.passage_id,
            "text_revision": self.text_revision,
            "text_digest": self.text_digest,
            "recipe_id": self.recipe_id,
            "recipe_revision": self.recipe_revision,
            "recipe_digest": self.recipe_digest,
            "settings": self.settings,
            "contract_digest": self.contract_digest,
            "authority_snapshot": self.authority_snapshot,
            "compiler_version": self.compiler_version,
            "capability_snapshot": self.capability_snapshot,
            "endpoint": self.endpoint,
            "timestamps_requested": self.timestamps_requested,
            "normalization": self.normalization,
            "output_audio": self.output_audio,
            "billable_rule": self.billable_rule,
            "billable_characters": self.billable_characters,
            "estimated_usage": self.estimated_usage,
            "issued_at": self.issued_at,
        }
        expected = self._digest(arguments, len(raw), self.rendered_transcript_digest, self.canonical_projection_digest)
        if self.preview_digest != expected:
            raise ValidationError("preview digest does not bind its exact constituent facts")

    @property
    def rendered_transcript_bytes(self) -> bytes:
        return self.rendered_transcript.encode("utf-8")


@dataclass(frozen=True, slots=True)
class ProviderEventEvidence:
    event_id: ProviderEventId
    sequence: int
    kind: ProviderEventKind
    sanitized_raw_reference: ArtifactRef
    sanitized_raw_digest: ContentDigest
    observed_at: datetime
    request_identity: str | None
    response_identity: str | None
    pcm_reference: ArtifactRef | None
    timing_reference: ArtifactRef | None
    usage: str | None
    terminal_classification: ProviderTerminalClass | None

    def __post_init__(self) -> None:
        if type(self.event_id) is not ProviderEventId or type(self.sequence) is not int or self.sequence < 0:
            raise ValidationError("provider event identity or sequence is invalid")
        if type(self.kind) is not ProviderEventKind or type(self.sanitized_raw_reference) is not ArtifactRef or type(self.sanitized_raw_digest) is not ContentDigest:
            raise ValidationError("provider event kind or raw evidence is invalid")
        if self.sanitized_raw_reference.content_digest != self.sanitized_raw_digest:
            raise ValidationError("provider raw reference and digest must match")
        _utc(self.observed_at, "provider event observation time")
        for field, value in (("request identity", self.request_identity), ("response identity", self.response_identity)):
            if value is not None:
                _required(value, field)
        for reference in (self.pcm_reference, self.timing_reference):
            if reference is not None and type(reference) is not ArtifactRef:
                raise ValidationError("provider PCM/timing reference must be an ArtifactRef or null")
        if self.usage is not None:
            NonNegativeDecimal(self.usage)
        if self.terminal_classification is not None and type(self.terminal_classification) is not ProviderTerminalClass:
            raise ValidationError("provider terminal classification is invalid")
        if self.kind is ProviderEventKind.TERMINAL:
            if self.terminal_classification is None:
                raise ValidationError("terminal provider event requires terminal classification")
        elif self.kind is ProviderEventKind.ERROR:
            if self.terminal_classification not in {
                ProviderTerminalClass.DEFINITE_PRE_SEND_FAILURE,
                ProviderTerminalClass.FAILURE,
                ProviderTerminalClass.AMBIGUOUS,
            }:
                raise ValidationError("provider error event requires a failure terminal classification")
        elif self.terminal_classification is not None:
            raise ValidationError("only terminal or error events may carry terminal classification")


def _successful_terminal_stream(events: tuple[ProviderEventEvidence, ...]) -> bool:
    terminal = tuple(event for event in events if event.terminal_classification is not None)
    return (
        bool(events)
        and len(terminal) == 1
        and events[-1] is terminal[0]
        and events[-1].kind is ProviderEventKind.TERMINAL
        and events[-1].terminal_classification is ProviderTerminalClass.SUCCESS
    )


@dataclass(frozen=True, slots=True)
class AttemptWorkspaceEvidence:
    workspace_id: AttemptWorkspaceId
    attempt_kind: AttemptKind
    aggregate_id: NarrationJobId | DiaryEpisodeId
    attempt_id: GenerationAttemptId | NarrationAssemblyAttemptId | EpisodeAssemblyAttemptId
    reservation_revision: int
    budget_reservation_id: BudgetReservationId | None
    preview_digest: ContentDigest | None
    effective_input_digest: ContentDigest | None
    frozen_plan_digest: ContentDigest | None
    submission: SubmissionEvidence
    events: tuple[ProviderEventEvidence, ...]
    staged_artifacts: tuple[ArtifactRef, ...]
    published_artifacts: tuple[PublishedArtifact, ...]
    recovery_evidence: tuple[str, ...]
    state: AttemptState
    raw_timing_reference: ArtifactRef | None = None

    def __post_init__(self) -> None:
        if type(self.workspace_id) is not AttemptWorkspaceId or type(self.attempt_kind) is not AttemptKind:
            raise ValidationError("attempt workspace identity or kind is invalid")
        expected_types = {
            AttemptKind.GENERATION: (NarrationJobId, GenerationAttemptId),
            AttemptKind.NARRATION_ASSEMBLY: (NarrationJobId, NarrationAssemblyAttemptId),
            AttemptKind.EPISODE_ASSEMBLY: (DiaryEpisodeId, EpisodeAssemblyAttemptId),
        }
        aggregate_type, attempt_type = expected_types[self.attempt_kind]
        if type(self.aggregate_id) is not aggregate_type or type(self.attempt_id) is not attempt_type:
            raise ValidationError("workspace aggregate and attempt identities must match its discriminated kind")
        _positive_revision(self.reservation_revision, "workspace reservation revision", allow_zero=True)
        if self.budget_reservation_id is not None and type(self.budget_reservation_id) is not BudgetReservationId:
            raise ValidationError("workspace budget reservation identity is invalid")
        for value in (self.preview_digest, self.effective_input_digest, self.frozen_plan_digest):
            if value is not None and type(value) is not ContentDigest:
                raise ValidationError("workspace digest binding is invalid")
        if type(self.submission) is not SubmissionEvidence or type(self.state) is not AttemptState:
            raise ValidationError("workspace submission or state is invalid")
        if self.attempt_kind is AttemptKind.GENERATION:
            if self.frozen_plan_digest != self.effective_input_digest:
                raise ValidationError("generation workspace frozen plan must exactly bind effective input")
            if (
                self.effective_input_digest is None
                and self.state not in {AttemptState.RESERVED, AttemptState.BLOCKED}
            ):
                raise ValidationError("generation workspace may omit frozen input only before it is frozen")
        elif self.frozen_plan_digest is None:
            raise ValidationError("assembly workspace requires a frozen assembly plan digest")
        if type(self.events) is not tuple or tuple(event.sequence for event in self.events) != tuple(range(len(self.events))):
            raise ValidationError("provider events must use contiguous ordered sequences from zero")
        if any(type(event) is not ProviderEventEvidence for event in self.events):
            raise ValidationError("workspace events must be ProviderEventEvidence values")
        if type(self.staged_artifacts) is not tuple or any(type(item) is not ArtifactRef for item in self.staged_artifacts):
            raise ValidationError("staged artifacts must be an immutable ArtifactRef tuple")
        if type(self.published_artifacts) is not tuple or any(type(item) is not PublishedArtifact for item in self.published_artifacts):
            raise ValidationError("published artifacts must be an immutable publication tuple")
        if self.raw_timing_reference is not None:
            if self.attempt_kind is not AttemptKind.GENERATION:
                raise ValidationError("only generation workspaces may carry raw timing evidence")
            if (
                type(self.raw_timing_reference) is not ArtifactRef
                or tuple(item.reference for item in self.published_artifacts).count(
                    self.raw_timing_reference
                ) != 1
            ):
                raise ValidationError("raw timing evidence requires one exact workspace publication")
        if type(self.recovery_evidence) is not tuple:
            raise ValidationError("recovery evidence must be an immutable tuple")
        for item in self.recovery_evidence:
            _required(item, "recovery evidence item")

    def matches_completion_binding(
        self,
        *,
        attempt_kind: AttemptKind,
        aggregate_id: NarrationJobId | DiaryEpisodeId,
        attempt_id: GenerationAttemptId | NarrationAssemblyAttemptId | EpisodeAssemblyAttemptId,
        reservation_revision: int,
        artifact: PublishedArtifact,
        budget_reservation_id: BudgetReservationId | None,
        preview_digest: ContentDigest | None,
        effective_input_digest: ContentDigest | None,
        frozen_plan_digest: ContentDigest | None,
    ) -> bool:
        """Return whether durable workspace facts exactly prove one output binding.

        Trust in the workspace is established by the application verifier.  This
        domain query still fails closed unless every aggregate-owned identity and
        frozen-input fact agrees and the exact immutable publication was staged.
        UNKNOWN is admitted because it is the persisted crash-recovery state whose
        complete evidence may later be verified without repeating external work.
        """

        if type(artifact) is not PublishedArtifact:
            return False
        return (
            self.attempt_kind is attempt_kind
            and self.aggregate_id == aggregate_id
            and self.attempt_id == attempt_id
            and self.reservation_revision == reservation_revision
            and self.budget_reservation_id == budget_reservation_id
            and self.preview_digest == preview_digest
            and self.effective_input_digest == effective_input_digest
            and self.frozen_plan_digest == frozen_plan_digest
            and self.submission is SubmissionEvidence.COMPLETED
            and self.state in {
                AttemptState.UNKNOWN,
                AttemptState.ARTIFACTS_PUBLISHED,
                AttemptState.COMPLETED,
            }
            and self.staged_artifacts.count(artifact.reference) == 1
            and self.published_artifacts.count(artifact) == 1
            and sum(
                publication.reference.media_type == "audio/wav"
                for publication in self.published_artifacts
            ) == 1
        )


@dataclass(frozen=True, slots=True)
class GenerationAttempt:
    attempt_id: GenerationAttemptId
    passage_id: PassageId
    reservation_revision: int
    budget_reservation_id: BudgetReservationId
    preview_id: GenerationPreviewId
    preview_digest: ContentDigest
    state: AttemptState
    submission: SubmissionEvidence
    effective_input: EffectiveSynthesisInput | None
    events: tuple[ProviderEventEvidence, ...]
    artifact: PublishedArtifact | None
    media: DecodedMediaFacts | None
    take_id: TakeId | None
    reason: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if type(self.attempt_id) is not GenerationAttemptId or type(self.passage_id) is not PassageId:
            raise ValidationError("generation attempt identity binding is invalid")
        _positive_revision(self.reservation_revision, "generation reservation revision", allow_zero=True)
        if type(self.budget_reservation_id) is not BudgetReservationId or type(self.preview_id) is not GenerationPreviewId or type(self.preview_digest) is not ContentDigest:
            raise ValidationError("generation attempt budget or preview binding is invalid")
        if type(self.state) is not AttemptState or type(self.submission) is not SubmissionEvidence:
            raise ValidationError("generation attempt state or submission is invalid")
        if self.effective_input is not None and type(self.effective_input) is not EffectiveSynthesisInput:
            raise ValidationError("generation effective input is invalid")
        if type(self.events) is not tuple or any(type(item) is not ProviderEventEvidence for item in self.events):
            raise ValidationError("generation events must be immutable ProviderEventEvidence values")
        if tuple(item.sequence for item in self.events) != tuple(range(len(self.events))):
            raise ValidationError("generation events must be contiguous and ordered")
        if self.artifact is not None and type(self.artifact) is not PublishedArtifact:
            raise ValidationError("generation artifact is invalid")
        if self.media is not None and type(self.media) is not DecodedMediaFacts:
            raise ValidationError("generation media facts are invalid")
        if self.take_id is not None and type(self.take_id) is not TakeId:
            raise ValidationError("generation take identity is invalid")
        if (self.artifact is None) != (self.media is None):
            raise ValidationError("generation artifact and media evidence must appear together")
        pre_artifact_states = {AttemptState.RESERVED, AttemptState.INPUT_FROZEN, AttemptState.EXTERNAL_WORK_STARTED}
        if self.state in pre_artifact_states and (self.events or self.artifact is not None):
            raise ValidationError("pre-artifact generation states cannot carry result evidence")
        if self.state is AttemptState.RESERVED and self.effective_input is not None:
            raise ValidationError("reserved generation cannot already carry frozen input")
        if self.state in {AttemptState.INPUT_FROZEN, AttemptState.EXTERNAL_WORK_STARTED, AttemptState.ARTIFACTS_STAGED, AttemptState.ARTIFACTS_PUBLISHED, AttemptState.COMPLETED} and self.effective_input is None:
            raise ValidationError("advanced generation state requires frozen effective input")
        expected_submission = {
            AttemptState.RESERVED: SubmissionEvidence.NOT_STARTED,
            AttemptState.INPUT_FROZEN: SubmissionEvidence.NOT_STARTED,
            AttemptState.EXTERNAL_WORK_STARTED: SubmissionEvidence.STARTED,
            AttemptState.ARTIFACTS_STAGED: SubmissionEvidence.COMPLETED,
            AttemptState.ARTIFACTS_PUBLISHED: SubmissionEvidence.COMPLETED,
            AttemptState.COMPLETED: SubmissionEvidence.COMPLETED,
        }
        if self.state in expected_submission and self.submission is not expected_submission[self.state]:
            raise ValidationError("generation state and submission evidence are incoherent")
        if self.state in {AttemptState.ARTIFACTS_STAGED, AttemptState.ARTIFACTS_PUBLISHED, AttemptState.COMPLETED} and self.artifact is None:
            raise ValidationError("artifact-bearing generation state requires artifact and media evidence")
        if self.state in {AttemptState.ARTIFACTS_STAGED, AttemptState.ARTIFACTS_PUBLISHED, AttemptState.COMPLETED}:
            if not _successful_terminal_stream(self.events):
                raise ValidationError("successful generation state requires one final successful terminal event")
            if self.media is None or self.media.all_digital_silence:
                raise ValidationError("successful generation state requires non-silent decoded media")
        if (self.state is AttemptState.COMPLETED) != (self.take_id is not None):
            raise ValidationError("only completed generation binds a take identity")
        if self.state is AttemptState.BLOCKED and self.submission not in {SubmissionEvidence.NOT_STARTED, SubmissionEvidence.DEFINITELY_NOT_SENT}:
            raise ValidationError("blocked generation must carry definite pre-send submission evidence")
        if self.state is AttemptState.UNKNOWN and self.submission is not SubmissionEvidence.AMBIGUOUS:
            raise ValidationError("unknown generation requires ambiguous submission evidence")
        terminal_failure = self.state in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.UNKNOWN, AttemptState.QUARANTINED}
        if terminal_failure:
            _required(self.reason, "generation outcome reason")
        elif self.reason is not None:
            raise ValidationError("nonterminal or completed generation cannot carry a failure reason")
        created = _utc(self.created_at, "generation attempt creation time")
        updated = _utc(self.updated_at, "generation attempt update time")
        if updated < created:
            raise ValidationError("generation attempt update cannot precede creation")


@dataclass(frozen=True, slots=True)
class NarrationAssemblyAttempt:
    attempt_id: NarrationAssemblyAttemptId
    reservation_revision: int
    selected_take_ids: tuple[TakeId, ...]
    gaps_samples: tuple[int, ...]
    state: AttemptState
    artifact: PublishedArtifact | None
    media: DecodedMediaFacts | None
    passage_offsets: tuple[PassageOffset, ...]
    master_id: NarrationMasterId | None
    reason: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if type(self.attempt_id) is not NarrationAssemblyAttemptId:
            raise ValidationError("narration assembly attempt identity is invalid")
        _positive_revision(self.reservation_revision, "narration assembly reservation revision", allow_zero=True)
        if (
            type(self.selected_take_ids) is not tuple
            or not self.selected_take_ids
            or any(type(value) is not TakeId for value in self.selected_take_ids)
            or len(set(self.selected_take_ids)) != len(self.selected_take_ids)
        ):
            raise ValidationError("narration assembly requires unique immutable selected take identities")
        if (
            type(self.gaps_samples) is not tuple
            or len(self.gaps_samples) != len(self.selected_take_ids) - 1
            or any(type(value) is not int or value < 0 for value in self.gaps_samples)
        ):
            raise ValidationError("narration assembly gaps must exactly separate selected takes")
        if type(self.state) is not AttemptState:
            raise ValidationError("narration assembly attempt state is invalid")
        if (self.artifact is None) != (self.media is None):
            raise ValidationError("narration assembly artifact and media evidence must appear together")
        if self.artifact is not None and type(self.artifact) is not PublishedArtifact:
            raise ValidationError("narration assembly artifact evidence is invalid")
        if self.media is not None and type(self.media) is not DecodedMediaFacts:
            raise ValidationError("narration assembly media evidence is invalid")
        if (
            type(self.passage_offsets) is not tuple
            or any(type(value) is not PassageOffset for value in self.passage_offsets)
            or (self.passage_offsets and len(self.passage_offsets) != len(self.selected_take_ids))
        ):
            raise ValidationError("narration assembly passage offsets are invalid")
        if self.state in {AttemptState.RESERVED, AttemptState.INPUT_FROZEN, AttemptState.EXTERNAL_WORK_STARTED} and (
            self.artifact is not None or self.passage_offsets
        ):
            raise ValidationError("pre-artifact narration assembly cannot carry result evidence")
        if self.state in {AttemptState.ARTIFACTS_STAGED, AttemptState.ARTIFACTS_PUBLISHED, AttemptState.COMPLETED} and (
            self.artifact is None or not self.passage_offsets
        ):
            raise ValidationError("advanced narration assembly state requires complete artifact and offset evidence")
        if self.artifact is not None:
            assert self.media is not None
            expected_start = 0
            for index, offset in enumerate(self.passage_offsets):
                if offset.start_sample != expected_start:
                    raise ValidationError("narration assembly offsets must preserve exact explicit gaps")
                expected_start = offset.end_sample
                if index < len(self.gaps_samples):
                    expected_start += self.gaps_samples[index]
            if expected_start != self.media.sample_count or self.media.all_digital_silence:
                raise ValidationError("narration assembly evidence must exactly cover non-silent decoded media")
        if (self.state is AttemptState.COMPLETED) != (self.master_id is not None):
            raise ValidationError("only completed narration assembly binds a master identity")
        if self.master_id is not None and type(self.master_id) is not NarrationMasterId:
            raise ValidationError("narration assembly master identity is invalid")
        if self.state in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.UNKNOWN, AttemptState.QUARANTINED}:
            _required(self.reason, "narration assembly terminal reason")
        elif self.reason is not None:
            raise ValidationError("nonterminal or completed narration assembly cannot carry a failure reason")
        created = _utc(self.created_at, "narration assembly attempt creation time")
        updated = _utc(self.updated_at, "narration assembly attempt update time")
        if updated < created:
            raise ValidationError("narration assembly update cannot precede creation")


@dataclass(frozen=True, slots=True)
class EpisodeAssemblyAttempt:
    attempt_id: EpisodeAssemblyAttemptId
    reservation_revision: int
    component_snapshot_digests: tuple[ContentDigest, ...]
    gap_samples: int
    state: AttemptState
    artifact: PublishedArtifact | None
    media: DecodedMediaFacts | None
    component_offsets: tuple[ComponentOffset, ...]
    master_id: EpisodeSpeechMasterId | None
    reason: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if type(self.attempt_id) is not EpisodeAssemblyAttemptId:
            raise ValidationError("episode assembly attempt identity is invalid")
        _positive_revision(self.reservation_revision, "episode assembly reservation revision", allow_zero=True)
        if (
            type(self.component_snapshot_digests) is not tuple
            or len(self.component_snapshot_digests) != 2
            or any(type(value) is not ContentDigest for value in self.component_snapshot_digests)
        ):
            raise ValidationError("episode assembly requires exactly intro and diary snapshot digests")
        if type(self.gap_samples) is not int or self.gap_samples < 0:
            raise ValidationError("episode assembly gap must be a nonnegative integer sample count")
        if type(self.state) is not AttemptState:
            raise ValidationError("episode assembly attempt state is invalid")
        if (self.artifact is None) != (self.media is None):
            raise ValidationError("episode assembly artifact and media evidence must appear together")
        if self.artifact is not None and type(self.artifact) is not PublishedArtifact:
            raise ValidationError("episode assembly artifact evidence is invalid")
        if self.media is not None and type(self.media) is not DecodedMediaFacts:
            raise ValidationError("episode assembly media evidence is invalid")
        if (
            type(self.component_offsets) is not tuple
            or any(type(value) is not ComponentOffset for value in self.component_offsets)
            or (self.component_offsets and tuple(value.role for value in self.component_offsets) != (ComponentRole.INTRO, ComponentRole.DIARY))
        ):
            raise ValidationError("episode assembly offsets must be immutable intro then diary evidence")
        if self.state in {AttemptState.RESERVED, AttemptState.INPUT_FROZEN, AttemptState.EXTERNAL_WORK_STARTED} and (
            self.artifact is not None or self.component_offsets
        ):
            raise ValidationError("pre-artifact episode assembly cannot carry result evidence")
        if self.state in {AttemptState.ARTIFACTS_STAGED, AttemptState.ARTIFACTS_PUBLISHED, AttemptState.COMPLETED} and (
            self.artifact is None or len(self.component_offsets) != 2
        ):
            raise ValidationError("advanced episode assembly state requires complete artifact and offset evidence")
        if self.artifact is not None:
            assert self.media is not None
            if len(self.component_offsets) != 2:
                raise ValidationError("artifact-bearing episode assembly requires exact component offsets")
            intro, diary = self.component_offsets
            if (
                tuple(value.snapshot_digest for value in self.component_offsets) != self.component_snapshot_digests
                or intro.start_sample != 0
                or diary.start_sample != intro.end_sample + self.gap_samples
                or diary.end_sample != self.media.sample_count
                or self.media.all_digital_silence
            ):
                raise ValidationError("episode assembly evidence must be exact non-silent intro-gap-diary media")
        if (self.state is AttemptState.COMPLETED) != (self.master_id is not None):
            raise ValidationError("only completed episode assembly binds a master identity")
        if self.master_id is not None and type(self.master_id) is not EpisodeSpeechMasterId:
            raise ValidationError("episode assembly master identity is invalid")
        if self.state in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.UNKNOWN, AttemptState.QUARANTINED}:
            _required(self.reason, "episode assembly terminal reason")
        elif self.reason is not None:
            raise ValidationError("nonterminal or completed episode assembly cannot carry a failure reason")
        created = _utc(self.created_at, "episode assembly attempt creation time")
        updated = _utc(self.updated_at, "episode assembly attempt update time")
        if updated < created:
            raise ValidationError("episode assembly update cannot precede creation")


@dataclass(frozen=True, slots=True)
class NarrationTake:
    take_id: TakeId
    attempt_id: GenerationAttemptId
    job_id: NarrationJobId
    lane: Lane
    passage_id: PassageId
    text_revision: int
    text_digest: ContentDigest
    recipe_id: PassageRenderRecipeId
    recipe_revision: int
    recipe_digest: ContentDigest
    settings: EffectiveTakeSettings
    contract_digest: ContentDigest
    authority_snapshot: AuthoritySnapshot
    effective_input: EffectiveSynthesisInput
    artifact: PublishedArtifact
    media: DecodedMediaFacts
    timing_reference: ArtifactRef | None
    created_at: datetime

    def __post_init__(self) -> None:
        # INV-NJ-2, INV-NJ-12: every immutable take binds all exact production inputs.
        if type(self.take_id) is not TakeId or type(self.attempt_id) is not GenerationAttemptId or type(self.job_id) is not NarrationJobId:
            raise ValidationError("take identity binding is invalid")
        if type(self.lane) is not Lane or type(self.passage_id) is not PassageId:
            raise ValidationError("take lane or passage binding is invalid")
        _positive_revision(self.text_revision, "take text revision")
        _positive_revision(self.recipe_revision, "take recipe revision")
        if any(type(item) is not ContentDigest for item in (self.text_digest, self.recipe_digest, self.contract_digest)):
            raise ValidationError("take digest binding is invalid")
        if type(self.recipe_id) is not PassageRenderRecipeId or type(self.settings) is not EffectiveTakeSettings:
            raise ValidationError("take recipe or settings binding is invalid")
        if type(self.authority_snapshot) is not AuthoritySnapshot or type(self.effective_input) is not EffectiveSynthesisInput:
            raise ValidationError("take authority or effective input binding is invalid")
        if type(self.artifact) is not PublishedArtifact or type(self.media) is not DecodedMediaFacts:
            raise ValidationError("take artifact or media facts are invalid")
        if self.timing_reference is not None and type(self.timing_reference) is not ArtifactRef:
            raise ValidationError("take timing reference is invalid")
        _utc(self.created_at, "take creation time")
        if (
            self.effective_input.job_id != self.job_id
            or self.effective_input.lane is not self.lane
            or self.effective_input.passage_id != self.passage_id
            or self.effective_input.text_revision != self.text_revision
            or self.effective_input.text.digest != self.text_digest
            or self.effective_input.recipe_id != self.recipe_id
            or self.effective_input.recipe_revision != self.recipe_revision
            or self.effective_input.recipe_digest != self.recipe_digest
            or self.effective_input.settings != self.settings
            or self.effective_input.contract_digest != self.contract_digest
            or self.effective_input.authority_scope != self.authority_snapshot.scope
            or self.effective_input.authority_revision != self.authority_snapshot.record_revision
            or self.effective_input.authority_digest != self.authority_snapshot.record_digest
            or self.effective_input.authority_observed_at != self.authority_snapshot.observed_at
        ):
            raise ValidationError("take metadata must exactly match EffectiveSynthesisInput")
        if self.media.all_digital_silence:
            raise ValidationError("a production take cannot be all digital silence")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision_id: ReviewDecisionId
    take_id: TakeId
    actor_id: ActorId
    authority: ReviewAuthority
    outcome: ReviewOutcome
    notes: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if type(self.decision_id) is not ReviewDecisionId or type(self.take_id) is not TakeId or type(self.actor_id) is not ActorId:
            raise ValidationError("review decision identity or actor is invalid")
        if type(self.authority) is not ReviewAuthority or type(self.outcome) is not ReviewOutcome:
            raise ValidationError("review authority or outcome is invalid")
        _required(self.notes, "review notes")
        _utc(self.decided_at, "review decision time")


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    decision_id: SelectionDecisionId
    passage_id: PassageId
    take_id: TakeId
    actor_id: ActorId
    eligibility: EligibilityFacts
    reason: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if type(self.decision_id) is not SelectionDecisionId or type(self.passage_id) is not PassageId or type(self.take_id) is not TakeId or type(self.actor_id) is not ActorId:
            raise ValidationError("selection identity or actor binding is invalid")
        if type(self.eligibility) is not EligibilityFacts or not self.eligibility.eligible:
            raise ValidationError("selection must freeze passing eligibility facts")
        _required(self.reason, "selection reason")
        _utc(self.decided_at, "selection decision time")


@dataclass(frozen=True, slots=True)
class NarrationMaster:
    master_id: NarrationMasterId
    job_id: NarrationJobId
    lane: Lane
    contract_digest: ContentDigest
    selected_take_ids: tuple[TakeId, ...]
    gaps_samples: tuple[int, ...]
    passage_offsets: tuple[PassageOffset, ...]
    timing_references: tuple[ArtifactRef | None, ...]
    artifact: PublishedArtifact
    media: DecodedMediaFacts
    created_at: datetime

    def __post_init__(self) -> None:
        if type(self.master_id) is not NarrationMasterId or type(self.job_id) is not NarrationJobId or type(self.lane) is not Lane:
            raise ValidationError("narration master identity or lane is invalid")
        if type(self.contract_digest) is not ContentDigest or type(self.selected_take_ids) is not tuple or not self.selected_take_ids:
            raise ValidationError("narration master contract/take binding is invalid")
        if any(type(item) is not TakeId for item in self.selected_take_ids) or len(set(self.selected_take_ids)) != len(self.selected_take_ids):
            raise ValidationError("narration master take IDs must be unique")
        if type(self.gaps_samples) is not tuple or any(type(item) is not int or item < 0 for item in self.gaps_samples):
            raise ValidationError("narration master gaps must be nonnegative integer samples")
        if len(self.gaps_samples) != max(0, len(self.selected_take_ids) - 1):
            raise ValidationError("narration master requires one explicit gap between adjacent takes")
        if (
            type(self.passage_offsets) is not tuple
            or len(self.passage_offsets) != len(self.selected_take_ids)
            or any(type(offset) is not PassageOffset for offset in self.passage_offsets)
        ):
            raise ValidationError("narration master requires one passage offset per selected take")
        if (
            type(self.timing_references) is not tuple
            or len(self.timing_references) != len(self.selected_take_ids)
            or any(reference is not None and type(reference) is not ArtifactRef for reference in self.timing_references)
        ):
            raise ValidationError("narration master requires one optional timing reference per selected take")
        if type(self.artifact) is not PublishedArtifact or type(self.media) is not DecodedMediaFacts:
            raise ValidationError("narration master artifact or media facts are invalid")
        expected_start = 0
        for index, offset in enumerate(self.passage_offsets):
            if offset.start_sample != expected_start:
                raise ValidationError("narration master offsets must preserve every exact explicit gap")
            expected_start = offset.end_sample
            if index < len(self.gaps_samples):
                expected_start += self.gaps_samples[index]
        if expected_start != self.media.sample_count or self.media.all_digital_silence:
            raise ValidationError("narration master offsets must exactly cover non-silent decoded media")
        _utc(self.created_at, "narration master creation time")


@dataclass(frozen=True, slots=True)
class NarrationMasterListeningDecision:
    decision_id: MasterListeningDecisionId
    master_id: NarrationMasterId
    actor_id: ActorId
    outcome: ListeningOutcome
    notes: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if type(self.decision_id) is not MasterListeningDecisionId or type(self.master_id) is not NarrationMasterId or type(self.actor_id) is not ActorId:
            raise ValidationError("master listening decision identity or actor is invalid")
        if type(self.outcome) is not ListeningOutcome:
            raise ValidationError("master listening outcome is invalid")
        _required(self.notes, "master listening notes")
        _utc(self.decided_at, "master listening decision time")


@dataclass(frozen=True, slots=True)
class NarrationMasterSnapshot:
    snapshot_id: NarrationMasterSnapshotId
    issuing_job_id: NarrationJobId
    issuing_job_revision: int
    source_master_id: NarrationMasterId
    listening_decision: NarrationMasterListeningDecision
    lane: Lane
    contract_digest: ContentDigest
    authority_snapshot: AuthoritySnapshot
    role: ComponentRole
    intended_episode_id: DiaryEpisodeId | None
    artifact: PublishedArtifact
    media: DecodedMediaFacts
    ordered_passage_ids: tuple[PassageId, ...]
    selected_take_ids: tuple[TakeId, ...]
    gaps_samples: tuple[int, ...]
    passage_offsets: tuple[PassageOffset, ...]
    timing_references: tuple[ArtifactRef | None, ...]
    issued_at: datetime
    snapshot_digest: ContentDigest

    @classmethod
    def create(cls, **arguments: object) -> NarrationMasterSnapshot:
        master = arguments.pop("source_master")
        if type(master) is not NarrationMaster:
            raise ValidationError("snapshot source must be a NarrationMaster")
        payload = {
            **arguments,
            "source_master_id": master.master_id,
            "lane": master.lane,
            "contract_digest": master.contract_digest,
            "artifact": master.artifact,
            "media": master.media,
            "gaps_samples": master.gaps_samples,
            "passage_offsets": master.passage_offsets,
            "timing_references": master.timing_references,
        }
        digest_value = cls._digest(payload)
        return cls(**payload, snapshot_digest=digest_value)

    @staticmethod
    def _digest(arguments: dict[str, object]) -> ContentDigest:
        def artifact_ref_payload(reference: ArtifactRef) -> dict[str, object]:
            return {
                "artifact_id": reference.artifact_id.value,
                "content_digest": reference.content_digest.hex_digest,
                "byte_size": reference.byte_size,
                "media_type": reference.media_type,
            }

        artifact = arguments["artifact"]
        media = arguments["media"]
        listening = arguments["listening_decision"]
        return semantic_digest(
            "narrator_voice.narration_master_snapshot.v1",
            {
                "snapshot_id": arguments["snapshot_id"].value,
                "issuing_job_id": arguments["issuing_job_id"].value,
                "issuing_job_revision": arguments["issuing_job_revision"],
                "source_master_id": arguments["source_master_id"].value,
                "listening_decision": {
                    "decision_id": listening.decision_id.value,
                    "master_id": listening.master_id.value,
                    "actor_id": listening.actor_id.value,
                    "outcome": listening.outcome.value,
                    "notes": listening.notes,
                    "decided_at": listening.decided_at.isoformat(),
                },
                "lane": arguments["lane"].value,
                "contract_digest": arguments["contract_digest"].hex_digest,
                "authority_snapshot_digest": arguments["authority_snapshot"].snapshot_digest.hex_digest,
                "role": arguments["role"].value,
                "intended_episode_id": None if arguments["intended_episode_id"] is None else arguments["intended_episode_id"].value,
                "artifact": {
                    "reference": artifact_ref_payload(artifact.reference),
                    "relative_location": artifact.relative_location.value,
                    "published_at": artifact.published_at.isoformat(),
                },
                "media": {
                    "audio": {
                        "container": media.audio.container,
                        "encoding": media.audio.encoding,
                        "sample_width_bits": media.audio.sample_width_bits,
                        "byte_order": media.audio.byte_order,
                        "channels": media.audio.channels,
                        "sample_rate_hz": media.audio.sample_rate_hz,
                    },
                    "sample_count": media.sample_count,
                    "duration_ms": media.duration_ms,
                    "all_digital_silence": media.all_digital_silence,
                },
                "ordered_passage_ids": [value.value for value in arguments["ordered_passage_ids"]],
                "selected_take_ids": [value.value for value in arguments["selected_take_ids"]],
                "gaps_samples": list(arguments["gaps_samples"]),
                "passage_offsets": [
                    {"passage_id": value.passage_id.value, "text_revision": value.text_revision, "text_digest": value.text_digest.hex_digest, "start": value.start_sample, "end": value.end_sample}
                    for value in arguments["passage_offsets"]
                ],
                "timing_references": [
                    None if reference is None else artifact_ref_payload(reference)
                    for reference in arguments["timing_references"]
                ],
                "issued_at": arguments["issued_at"].isoformat(),
            },
        )

    def __post_init__(self) -> None:
        if type(self.snapshot_id) is not NarrationMasterSnapshotId or type(self.issuing_job_id) is not NarrationJobId:
            raise ValidationError("narration snapshot identity binding is invalid")
        _positive_revision(self.issuing_job_revision, "snapshot issuing job revision")
        if type(self.source_master_id) is not NarrationMasterId or type(self.listening_decision) is not NarrationMasterListeningDecision:
            raise ValidationError("snapshot master/listening binding is invalid")
        if self.listening_decision.master_id != self.source_master_id or self.listening_decision.outcome is not ListeningOutcome.PASSED:
            raise ValidationError("snapshot requires passing listening for its exact source master")
        if type(self.lane) is not Lane or type(self.role) is not ComponentRole:
            raise ValidationError("snapshot lane or role is invalid")
        if (self.lane, self.role) not in {(Lane.B, ComponentRole.DIARY), (Lane.C, ComponentRole.INTRO)}:
            raise ValidationError("snapshot role must match its source lane")
        if self.lane is Lane.C and type(self.intended_episode_id) is not DiaryEpisodeId:
            raise ValidationError("Lane C snapshot requires an intended episode")
        if self.lane is Lane.B and self.intended_episode_id is not None:
            raise ValidationError("Lane B snapshot cannot be episode-bound")
        if type(self.contract_digest) is not ContentDigest or type(self.authority_snapshot) is not AuthoritySnapshot:
            raise ValidationError("snapshot contract or authority evidence is invalid")
        if type(self.artifact) is not PublishedArtifact or type(self.media) is not DecodedMediaFacts:
            raise ValidationError("snapshot artifact or media facts are invalid")
        if (
            type(self.ordered_passage_ids) is not tuple
            or type(self.selected_take_ids) is not tuple
            or not self.ordered_passage_ids
            or len(self.ordered_passage_ids) != len(self.selected_take_ids)
            or any(type(passage_id) is not PassageId for passage_id in self.ordered_passage_ids)
            or any(type(take_id) is not TakeId for take_id in self.selected_take_ids)
            or len(set(self.ordered_passage_ids)) != len(self.ordered_passage_ids)
            or len(set(self.selected_take_ids)) != len(self.selected_take_ids)
        ):
            raise ValidationError("snapshot passage/take identities must be parallel immutable tuples")
        if (
            type(self.gaps_samples) is not tuple
            or type(self.passage_offsets) is not tuple
            or len(self.gaps_samples) != len(self.selected_take_ids) - 1
            or len(self.passage_offsets) != len(self.selected_take_ids)
            or tuple(offset.passage_id for offset in self.passage_offsets) != self.ordered_passage_ids
        ):
            raise ValidationError("snapshot gap/offset facts must be immutable tuples")
        if (
            type(self.timing_references) is not tuple
            or len(self.timing_references) != len(self.selected_take_ids)
            or any(reference is not None and type(reference) is not ArtifactRef for reference in self.timing_references)
        ):
            raise ValidationError("snapshot timing references must parallel its selected takes")
        expected_start = 0
        for index, offset in enumerate(self.passage_offsets):
            if type(offset) is not PassageOffset or offset.start_sample != expected_start:
                raise ValidationError("snapshot offsets must preserve every exact explicit gap")
            expected_start = offset.end_sample
            if index < len(self.gaps_samples):
                gap = self.gaps_samples[index]
                if type(gap) is not int or gap < 0:
                    raise ValidationError("snapshot gaps must be nonnegative integer samples")
                expected_start += gap
        if expected_start != self.media.sample_count or self.media.all_digital_silence:
            raise ValidationError("snapshot offsets must exactly cover non-silent decoded media")
        _utc(self.issued_at, "snapshot issuance time")
        arguments: dict[str, object] = {
            "snapshot_id": self.snapshot_id,
            "issuing_job_id": self.issuing_job_id,
            "issuing_job_revision": self.issuing_job_revision,
            "source_master_id": self.source_master_id,
            "listening_decision": self.listening_decision,
            "lane": self.lane,
            "contract_digest": self.contract_digest,
            "authority_snapshot": self.authority_snapshot,
            "role": self.role,
            "intended_episode_id": self.intended_episode_id,
            "artifact": self.artifact,
            "media": self.media,
            "ordered_passage_ids": self.ordered_passage_ids,
            "selected_take_ids": self.selected_take_ids,
            "gaps_samples": self.gaps_samples,
            "passage_offsets": self.passage_offsets,
            "timing_references": self.timing_references,
            "issued_at": self.issued_at,
        }
        if self.snapshot_digest != self._digest(arguments):
            raise ValidationError("snapshot digest does not match exact snapshot facts")


@dataclass(frozen=True, slots=True)
class EpisodeSpeechMaster:
    master_id: EpisodeSpeechMasterId
    episode_id: DiaryEpisodeId
    component_snapshot_digests: tuple[ContentDigest, ...]
    gap_samples: int
    component_offsets: tuple[ComponentOffset, ...]
    artifact: PublishedArtifact
    media: DecodedMediaFacts
    created_at: datetime

    def __post_init__(self) -> None:
        if type(self.master_id) is not EpisodeSpeechMasterId or type(self.episode_id) is not DiaryEpisodeId:
            raise ValidationError("episode master identity binding is invalid")
        if type(self.component_snapshot_digests) is not tuple or len(self.component_snapshot_digests) != 2 or any(type(item) is not ContentDigest for item in self.component_snapshot_digests):
            raise ValidationError("episode master requires exactly two snapshot digests")
        if type(self.gap_samples) is not int or self.gap_samples < 0:
            raise ValidationError("episode master gap must be nonnegative integer samples")
        if (
            type(self.component_offsets) is not tuple
            or any(type(item) is not ComponentOffset for item in self.component_offsets)
            or tuple(item.role for item in self.component_offsets) != (ComponentRole.INTRO, ComponentRole.DIARY)
        ):
            raise ValidationError("episode component offsets must be exactly intro then diary")
        if type(self.artifact) is not PublishedArtifact or type(self.media) is not DecodedMediaFacts:
            raise ValidationError("episode master artifact/media evidence is invalid")
        intro, diary = self.component_offsets
        if (
            tuple(item.snapshot_digest for item in self.component_offsets) != self.component_snapshot_digests
            or intro.start_sample != 0
            or diary.start_sample != intro.end_sample + self.gap_samples
            or diary.end_sample != self.media.sample_count
            or self.media.all_digital_silence
        ):
            raise ValidationError("episode master must be exact non-silent intro plus explicit gap plus diary")
        _utc(self.created_at, "episode master creation time")


@dataclass(frozen=True, slots=True)
class EpisodeListeningDecision:
    decision_id: EpisodeListeningDecisionId
    master_id: EpisodeSpeechMasterId
    actor_id: ActorId
    outcome: ListeningOutcome
    notes: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if type(self.decision_id) is not EpisodeListeningDecisionId or type(self.master_id) is not EpisodeSpeechMasterId or type(self.actor_id) is not ActorId:
            raise ValidationError("episode listening identity or actor is invalid")
        if type(self.outcome) is not ListeningOutcome:
            raise ValidationError("episode listening outcome is invalid")
        _required(self.notes, "episode listening notes")
        _utc(self.decided_at, "episode listening time")


@dataclass(frozen=True, slots=True)
class TimingCue:
    cue_id: CueId
    role: ComponentRole
    lane: Lane
    source_job_id: NarrationJobId
    source_master_id: NarrationMasterId
    passage_id: PassageId
    text_revision: int
    text_digest: ContentDigest
    display_text: str
    text_span: TextSpan | None
    start_sample: int
    end_sample: int
    granularity: CueGranularity
    provenance: CueProvenance
    source: str
    source_version: str
    input_audio_digest: ContentDigest
    input_text_digest: ContentDigest
    review_status: TimingReviewStatus

    def __post_init__(self) -> None:
        if type(self.cue_id) is not CueId or type(self.role) is not ComponentRole or type(self.lane) is not Lane:
            raise ValidationError("timing cue identity, role or lane is invalid")
        if (self.role, self.lane) not in {
            (ComponentRole.INTRO, Lane.C),
            (ComponentRole.DIARY, Lane.B),
        }:
            raise ValidationError("timing cue role must use its exact source lane")
        if type(self.source_job_id) is not NarrationJobId or type(self.source_master_id) is not NarrationMasterId or type(self.passage_id) is not PassageId:
            raise ValidationError("timing cue source identity is invalid")
        _positive_revision(self.text_revision, "timing cue text revision")
        if any(type(item) is not ContentDigest for item in (self.text_digest, self.input_audio_digest, self.input_text_digest)):
            raise ValidationError("timing cue digest binding is invalid")
        _required(self.display_text, "timing cue display text")
        if self.text_span is not None:
            if type(self.text_span) is not TextSpan or self.text_span.end > len(self.display_text):
                raise ValidationError("timing cue text span is invalid")
        if type(self.start_sample) is not int or type(self.end_sample) is not int or self.start_sample < 0 or self.end_sample <= self.start_sample:
            raise ValidationError("timing cue must be a nonempty nonnegative sample range")
        if type(self.granularity) is not CueGranularity or type(self.provenance) is not CueProvenance or type(self.review_status) is not TimingReviewStatus:
            raise ValidationError("timing cue classification is invalid")
        _required(self.source, "timing cue source")
        _required(self.source_version, "timing cue source version")
        if self.input_text_digest != self.text_digest:
            raise ValidationError("timing cue input text digest must match source text digest")
        if self.text_span is None and ContentDigest.from_bytes(self.display_text.encode("utf-8")) != self.text_digest:
            raise ValidationError("unspanned timing cue display text must match its exact source digest")


@dataclass(frozen=True, slots=True)
class TimedNarrationPackage:
    package_id: TimedNarrationPackageId
    version: int
    episode_id: DiaryEpisodeId
    episode_revision: int
    episode_master_id: EpisodeSpeechMasterId
    episode_artifact: PublishedArtifact
    episode_media: DecodedMediaFacts
    intro_snapshot_digest: ContentDigest
    diary_snapshot_digest: ContentDigest
    gap_samples: int
    component_offsets: tuple[ComponentOffset, ...]
    cues: tuple[TimingCue, ...]
    raw_timing_artifacts: tuple[ArtifactRef, ...]
    normalized_timing_artifact: ArtifactRef | None
    validation_results: tuple[str, ...]
    timing_review_status: TimingReviewStatus
    authority_snapshots: tuple[AuthoritySnapshot, ...]
    source_package_digest: ContentDigest | None
    correction_actor_id: ActorId | None
    correction_reason: str | None
    created_at: datetime
    package_digest: ContentDigest

    @classmethod
    def create(cls, **arguments: object) -> TimedNarrationPackage:
        master = arguments.pop("episode_master")
        if type(master) is not EpisodeSpeechMaster:
            raise ValidationError("timed package source must be an EpisodeSpeechMaster")
        payload = {
            **arguments,
            "episode_master_id": master.master_id,
            "episode_artifact": master.artifact,
            "episode_media": master.media,
            "gap_samples": master.gap_samples,
            "component_offsets": master.component_offsets,
        }
        package_digest = cls._digest(payload)
        return cls(**payload, package_digest=package_digest)

    @staticmethod
    def _digest(arguments: dict[str, object]) -> ContentDigest:
        def artifact_ref_payload(reference: ArtifactRef) -> dict[str, object]:
            return {
                "artifact_id": reference.artifact_id.value,
                "content_digest": reference.content_digest.hex_digest,
                "byte_size": reference.byte_size,
                "media_type": reference.media_type,
            }

        def component_payload(component: ComponentOffset) -> dict[str, object]:
            return {
                "role": component.role.value,
                "start_sample": component.start_sample,
                "end_sample": component.end_sample,
                "snapshot_digest": component.snapshot_digest.hex_digest,
                "passage_offsets": [
                    {
                        "passage_id": offset.passage_id.value,
                        "text_revision": offset.text_revision,
                        "text_digest": offset.text_digest.hex_digest,
                        "start_sample": offset.start_sample,
                        "end_sample": offset.end_sample,
                    }
                    for offset in component.passage_offsets
                ],
            }

        def cue_payload(cue: TimingCue) -> dict[str, object]:
            return {
                "cue_id": cue.cue_id.value,
                "role": cue.role.value,
                "lane": cue.lane.value,
                "source_job_id": cue.source_job_id.value,
                "source_master_id": cue.source_master_id.value,
                "passage_id": cue.passage_id.value,
                "text_revision": cue.text_revision,
                "text_digest": cue.text_digest.hex_digest,
                "display_text": cue.display_text,
                "text_span": None if cue.text_span is None else {
                    "start": cue.text_span.start,
                    "end": cue.text_span.end,
                },
                "start_sample": cue.start_sample,
                "end_sample": cue.end_sample,
                "granularity": cue.granularity.value,
                "provenance": cue.provenance.value,
                "source": cue.source,
                "source_version": cue.source_version,
                "input_audio_digest": cue.input_audio_digest.hex_digest,
                "input_text_digest": cue.input_text_digest.hex_digest,
                "review_status": cue.review_status.value,
            }

        artifact = arguments["episode_artifact"]
        media = arguments["episode_media"]
        return semantic_digest(
            "narrator_voice.timed_narration_package.v1",
            {
                "package_id": arguments["package_id"].value,
                "version": arguments["version"],
                "episode_id": arguments["episode_id"].value,
                "episode_revision": arguments["episode_revision"],
                "episode_master_id": arguments["episode_master_id"].value,
                "episode_artifact": {
                    "reference": artifact_ref_payload(artifact.reference),
                    "relative_location": artifact.relative_location.value,
                    "published_at": artifact.published_at.isoformat(),
                },
                "episode_media": {
                    "audio": {
                        "container": media.audio.container,
                        "encoding": media.audio.encoding,
                        "sample_width_bits": media.audio.sample_width_bits,
                        "byte_order": media.audio.byte_order,
                        "channels": media.audio.channels,
                        "sample_rate_hz": media.audio.sample_rate_hz,
                    },
                    "sample_count": media.sample_count,
                    "duration_ms": media.duration_ms,
                    "all_digital_silence": media.all_digital_silence,
                },
                "intro_snapshot_digest": arguments["intro_snapshot_digest"].hex_digest,
                "diary_snapshot_digest": arguments["diary_snapshot_digest"].hex_digest,
                "gap_samples": arguments["gap_samples"],
                "component_offsets": [component_payload(component) for component in arguments["component_offsets"]],
                "cues": [cue_payload(cue) for cue in arguments["cues"]],
                "raw_timing_artifacts": [artifact_ref_payload(reference) for reference in arguments["raw_timing_artifacts"]],
                "normalized_timing_artifact": (
                    None
                    if arguments["normalized_timing_artifact"] is None
                    else artifact_ref_payload(arguments["normalized_timing_artifact"])
                ),
                "validation_results": list(arguments["validation_results"]),
                "timing_review_status": arguments["timing_review_status"].value,
                "authority_snapshot_digests": [
                    snapshot.snapshot_digest.hex_digest for snapshot in arguments["authority_snapshots"]
                ],
                "source_package_digest": None if arguments["source_package_digest"] is None else arguments["source_package_digest"].hex_digest,
                "correction_actor_id": None if arguments["correction_actor_id"] is None else arguments["correction_actor_id"].value,
                "correction_reason": arguments["correction_reason"],
                "created_at": arguments["created_at"].isoformat(),
            },
        )

    def __post_init__(self) -> None:
        if type(self.package_id) is not TimedNarrationPackageId or type(self.episode_id) is not DiaryEpisodeId or type(self.episode_master_id) is not EpisodeSpeechMasterId:
            raise ValidationError("timed package identity binding is invalid")
        _positive_revision(self.version, "timed package version")
        _positive_revision(self.episode_revision, "timed package episode revision")
        if type(self.episode_artifact) is not PublishedArtifact or type(self.episode_media) is not DecodedMediaFacts:
            raise ValidationError("timed package episode artifact/media is invalid")
        if self.episode_media.all_digital_silence:
            raise ValidationError("timed package cannot describe a digitally silent episode master")
        if any(type(item) is not ContentDigest for item in (self.intro_snapshot_digest, self.diary_snapshot_digest)):
            raise ValidationError("timed package snapshot digests are invalid")
        if type(self.gap_samples) is not int or self.gap_samples < 0 or type(self.component_offsets) is not tuple:
            raise ValidationError("timed package gap/component offsets are invalid")
        if (
            len(self.component_offsets) != 2
            or any(type(component) is not ComponentOffset for component in self.component_offsets)
            or tuple(component.role for component in self.component_offsets)
            != (ComponentRole.INTRO, ComponentRole.DIARY)
        ):
            raise ValidationError("timed package components must be exactly intro then diary")
        intro, diary = self.component_offsets
        if (
            intro.snapshot_digest != self.intro_snapshot_digest
            or diary.snapshot_digest != self.diary_snapshot_digest
            or intro.start_sample != 0
            or diary.start_sample != intro.end_sample + self.gap_samples
            or diary.end_sample != self.episode_media.sample_count
        ):
            raise ValidationError("timed package components must truthfully place the exact episode sources")
        if type(self.cues) is not tuple or not self.cues or len({cue.cue_id for cue in self.cues}) != len(self.cues):
            raise ValidationError("timed package cues must be a nonempty immutable uniquely identified tuple")
        previous = 0
        for cue in self.cues:
            if type(cue) is not TimingCue or cue.start_sample < previous or cue.end_sample > self.episode_media.sample_count:
                raise ValidationError("timing cues must be monotonic, nonoverlapping and within episode duration")
            component = intro if cue.role is ComponentRole.INTRO else diary
            matching_passage = any(
                cue.passage_id == offset.passage_id
                and cue.text_revision == offset.text_revision
                and cue.text_digest == offset.text_digest
                and cue.start_sample >= offset.start_sample
                and cue.end_sample <= offset.end_sample
                for offset in component.passage_offsets
            )
            if (
                cue.start_sample < component.start_sample
                or cue.end_sample > component.end_sample
                or not matching_passage
                or cue.input_audio_digest != self.episode_artifact.reference.content_digest
            ):
                raise ValidationError("timing cue must truthfully bind its component, passage and input audio")
            previous = cue.end_sample
        if (
            type(self.raw_timing_artifacts) is not tuple
            or any(type(item) is not ArtifactRef for item in self.raw_timing_artifacts)
            or len({item.artifact_id for item in self.raw_timing_artifacts}) != len(self.raw_timing_artifacts)
        ):
            raise ValidationError("raw timing artifacts must be an immutable ArtifactRef tuple")
        if self.normalized_timing_artifact is not None and type(self.normalized_timing_artifact) is not ArtifactRef:
            raise ValidationError("normalized timing artifact is invalid")
        if type(self.validation_results) is not tuple:
            raise ValidationError("timing validation results must be an immutable tuple")
        for value in self.validation_results:
            _required(value, "timing validation result")
        if (
            type(self.timing_review_status) is not TimingReviewStatus
            or type(self.authority_snapshots) is not tuple
            or len(self.authority_snapshots) != 2
            or any(type(snapshot) is not AuthoritySnapshot for snapshot in self.authority_snapshots)
        ):
            raise ValidationError("timing review/authority evidence is invalid")
        if self.source_package_digest is not None and type(self.source_package_digest) is not ContentDigest:
            raise ValidationError("source package digest is invalid")
        if self.correction_actor_id is not None and type(self.correction_actor_id) is not ActorId:
            raise ValidationError("timing correction actor is invalid")
        correction_facts = (self.source_package_digest, self.correction_actor_id, self.correction_reason)
        if any(value is not None for value in correction_facts) and any(value is None for value in correction_facts):
            raise ValidationError("timing correction requires source package, actor and reason together")
        if self.correction_reason is not None:
            _required(self.correction_reason, "timing correction reason")
        _utc(self.created_at, "timed package creation time")
        if type(self.package_digest) is not ContentDigest or self.package_digest != self._digest({
            "package_id": self.package_id,
            "version": self.version,
            "episode_id": self.episode_id,
            "episode_revision": self.episode_revision,
            "episode_master_id": self.episode_master_id,
            "episode_artifact": self.episode_artifact,
            "episode_media": self.episode_media,
            "intro_snapshot_digest": self.intro_snapshot_digest,
            "diary_snapshot_digest": self.diary_snapshot_digest,
            "gap_samples": self.gap_samples,
            "component_offsets": self.component_offsets,
            "cues": self.cues,
            "raw_timing_artifacts": self.raw_timing_artifacts,
            "normalized_timing_artifact": self.normalized_timing_artifact,
            "validation_results": self.validation_results,
            "timing_review_status": self.timing_review_status,
            "authority_snapshots": self.authority_snapshots,
            "source_package_digest": self.source_package_digest,
            "correction_actor_id": self.correction_actor_id,
            "correction_reason": self.correction_reason,
            "created_at": self.created_at,
        }):
            raise ValidationError("timed package digest does not match its canonical facts")
        arguments: dict[str, object] = {
            "package_id": self.package_id,
            "version": self.version,
            "episode_id": self.episode_id,
            "episode_revision": self.episode_revision,
            "episode_master_id": self.episode_master_id,
            "episode_artifact": self.episode_artifact,
            "episode_media": self.episode_media,
            "intro_snapshot_digest": self.intro_snapshot_digest,
            "diary_snapshot_digest": self.diary_snapshot_digest,
            "gap_samples": self.gap_samples,
            "component_offsets": self.component_offsets,
            "cues": self.cues,
            "raw_timing_artifacts": self.raw_timing_artifacts,
            "normalized_timing_artifact": self.normalized_timing_artifact,
            "validation_results": self.validation_results,
            "timing_review_status": self.timing_review_status,
            "authority_snapshots": self.authority_snapshots,
            "source_package_digest": self.source_package_digest,
            "correction_actor_id": self.correction_actor_id,
            "correction_reason": self.correction_reason,
            "created_at": self.created_at,
        }
        if self.package_digest != self._digest(arguments):
            raise ValidationError("timed package digest does not match exact package facts")
