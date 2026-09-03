"""Strict in-memory no-network fakes for Narrator Voice application tests."""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from heritage_archive.kernel import ActorId, ArtifactId, ArtifactRef, ContentDigest
from heritage_archive.contexts.narrator_voice.application.ports import (
    AuthorityObservation,
    DryAssemblyResult,
    PreviewCompilerResult,
    PrincipalAuthority,
    RecipeAuthoringResult,
    ReleasePolicyResolution,
    SynthesisResult,
    VerifiedArtifactRecoveryFacts,
    VerifiedProviderRecoveryFacts,
    VerifiedWorkspaceRecoveryFacts,
)
from heritage_archive.contexts.narrator_voice.application.recovery import (
    BudgetRecoveryState,
    RecoveryStage,
)
from heritage_archive.contexts.narrator_voice.domain.errors import (
    AmbiguousExternalFailure,
    BudgetDenied,
    DefinitePreSendFailure,
    ExternalWorkFailed,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    DecodedMediaFacts,
    ReviewAuthority,
    SubmissionEvidence,
    TimingReviewStatus,
)
from heritage_archive.contexts.narrator_voice.domain.values import (
    CanonicalAudioFacts,
    NonNegativeDecimal,
    PassageRenderRecipe,
)
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord, AuthorizationStatus
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.ids import AuthorizationRecordId, DiaryEpisodeId, NarrationJobId
from heritage_archive.contexts.narrator_voice.domain.narration_job import NarrationJob


T = TypeVar("T")


class FakeActorResolver:
    def __init__(
        self,
        actors: dict[str, ActorId],
        *,
        profiles: dict[str, PrincipalAuthority] | None = None,
    ) -> None:
        self.profiles = dict(profiles or {
            principal: PrincipalAuthority(
                actor_id,
                True,
                ReviewAuthority.OPERATIONAL,
                TimingReviewStatus.HUMAN_REVIEWED,
            )
            for principal, actor_id in actors.items()
        })
        self.calls: list[str] = []

    def resolve_principal(self, principal: str) -> PrincipalAuthority:
        self.calls.append(principal)
        return self.profiles[principal]

    def resolve_actor(self, principal: str) -> ActorId:
        """Legacy seam retained only so RED tests expose missing policy enforcement as a failure."""
        self.calls.append(principal)
        return self.profiles[principal].actor_id


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class FakeIdentifierSource:
    def __init__(self, values: dict[type[object], list[object]]) -> None:
        self.values = {kind: list(items) for kind, items in values.items()}
        self.calls: list[type[object]] = []

    def new_id(self, kind: type[T]) -> T:
        self.calls.append(kind)
        return self.values[kind].pop(0)  # type: ignore[return-value]


class _CasRepository:
    def __init__(self) -> None:
        self.values: dict[object, object] = {}
        self.revisions: dict[object, int] = {}
        self.save_calls = 0
        self.reject_next_save = False
        self.reject_on_save_calls: set[int] = set()

    @staticmethod
    def _identity(value: object) -> object:
        for name in ("record_id", "job_id", "episode_id"):
            if hasattr(value, name):
                return getattr(value, name)
        raise AssertionError("fake repository received an unsupported root")

    @staticmethod
    def _clone(value: T) -> T:
        return type(value).from_snapshot(value.to_snapshot())

    def load(self, identity: object):
        value = self.values.get(identity)
        return None if value is None else self._clone(value)

    def save(self, value: object, expected_revision: int | None) -> bool:
        self.save_calls += 1
        identity = self._identity(value)
        if self.reject_next_save or self.save_calls in self.reject_on_save_calls:
            self.reject_next_save = False
            return False
        current = self.revisions.get(identity)
        if current != expected_revision:
            return False
        self.values[identity] = self._clone(value)
        self.revisions[identity] = value.revision
        return True


class FakeAuthorizationRepository(_CasRepository):
    def load(self, identity: AuthorizationRecordId) -> AuthorizationRecord | None:
        return super().load(identity)


class FakeNarrationJobRepository(_CasRepository):
    def load(self, identity: NarrationJobId) -> NarrationJob | None:
        return super().load(identity)


class FakeDiaryEpisodeRepository(_CasRepository):
    def load(self, identity: DiaryEpisodeId) -> DiaryEpisode | None:
        return super().load(identity)


class FakeReleasePolicyResolver:
    def __init__(
        self,
        *,
        lane_b: ReleasePolicyResolution | None = None,
        lane_c: ReleasePolicyResolution | None = None,
    ) -> None:
        self.lane_b = lane_b
        self.lane_c = lane_c
        self.calls: list[tuple[str, DiaryEpisodeId | None]] = []

    def resolve_lane_b_diary(self) -> ReleasePolicyResolution:
        self.calls.append(("lane_b", None))
        if self.lane_b is None:
            raise AssertionError("fake Lane-B release policy was not configured")
        return self.lane_b

    def resolve_lane_c_intro(self, intended_episode_id: DiaryEpisodeId) -> ReleasePolicyResolution:
        self.calls.append(("lane_c", intended_episode_id))
        if self.lane_c is None:
            raise AssertionError("fake Lane-C release policy was not configured")
        return self.lane_c


class FakeAuthorizationStatusReader:
    def __init__(self, repository: FakeAuthorizationRepository) -> None:
        self.repository = repository
        self.calls: list[tuple[AuthorizationRecordId, datetime]] = []
        self.outage = False

    def read(self, record_id: AuthorizationRecordId, observed_at: datetime) -> AuthorityObservation:
        self.calls.append((record_id, observed_at))
        if self.outage:
            raise RuntimeError("fake authority reader outage")
        record = self.repository.load(record_id)
        if record is None:
            return AuthorityObservation(record_id, None, None)
        status = record.status_at(observed_at)
        snapshot = record.observe(observed_at)
        return AuthorityObservation(record_id, status, snapshot)


class FakeRecipeCompiler:
    def __init__(self, syntax_families: list[str] | None = None) -> None:
        self.calls = []
        self.recipe_calls = []
        self.syntax_families = list(syntax_families or [])
        self.advanced_controls = {}

    def compile_recipe(self, request):
        self.recipe_calls.append(request)
        controls = (
            request.structured_controls
            if request.advanced_source is None
            else self.advanced_controls[request.advanced_source]
        )
        return RecipeAuthoringResult(
            PassageRenderRecipe(
                request.recipe_id,
                request.recipe_revision,
                request.text_revision,
                request.text.digest,
                "fake-compiler-v1",
                controls,
            ),
            request.text.value,
            (),
        )

    def compile(self, request):
        self.calls.append(request)
        family = self.syntax_families.pop(0) if self.syntax_families else "fake"
        return PreviewCompilerResult(
            "fake-compiler-v1",
            "fake://no-network",
            f"<{family}>{request.text.value}</{family}>",
            request.text.value,
            True,
            "off",
            "fake-billing-v1",
            len(request.text.value),
            NonNegativeDecimal(str(len(request.text.value) + 13)),
        )


class FakeBudgetLedger:
    def __init__(self) -> None:
        self.actions: list[tuple[str, object, object]] = []
        self.deny_reserve = False
        self.states = {}

    def reserve(self, reservation_id, estimated_usage) -> None:
        self.actions.append(("reserve", reservation_id, estimated_usage))
        if self.deny_reserve:
            raise BudgetDenied("fake budget denial")
        self.states[reservation_id] = BudgetRecoveryState.RESERVED

    def settle(self, reservation_id, actual_usage) -> None:
        self.actions.append(("settle", reservation_id, actual_usage))
        self.states[reservation_id] = BudgetRecoveryState.SETTLED

    def release(self, reservation_id, reason) -> None:
        self.actions.append(("release", reservation_id, reason))
        self.states[reservation_id] = BudgetRecoveryState.RELEASED

    def hold(self, reservation_id, reason) -> None:
        self.actions.append(("hold", reservation_id, reason))
        self.states[reservation_id] = BudgetRecoveryState.UNKNOWN

    def read(self, reservation_id):
        return self.states.get(reservation_id, BudgetRecoveryState.UNKNOWN)


class FakeSynthesisGateway:
    """No SDK/network capability: only records exact frozen input and returns fixture evidence."""

    def __init__(self, result: SynthesisResult) -> None:
        self.result = result
        self.mode = "success"
        self.calls = []
        self.after_call = None

    def synthesize(self, effective_input):
        self.calls.append(effective_input)
        if self.after_call is not None:
            self.after_call()
        if self.mode == "pre_send":
            raise DefinitePreSendFailure("fake definitely not sent")
        if self.mode == "ambiguous":
            raise AmbiguousExternalFailure("fake ambiguous provider outcome")
        if self.mode == "failed":
            raise ExternalWorkFailed("fake definitive provider failure")
        return self.result


class FakeArtifactStore:
    def __init__(self, artifact_ids: list[ArtifactId]) -> None:
        self.artifact_ids = list(artifact_ids)
        self.calls = []

    def publish(self, location, payload, media_type, published_at):
        from heritage_archive.contexts.narrator_voice.domain.evidence import PublishedArtifact

        self.calls.append((location, payload, media_type, published_at))
        reference = ArtifactRef(self.artifact_ids.pop(0), ContentDigest.from_bytes(payload), len(payload), media_type)
        return PublishedArtifact(reference, location, published_at)


class FakeMediaInspector:
    def __init__(self, sample_count: int = 100, *, all_digital_silence: bool = False) -> None:
        self.sample_count = sample_count
        self.all_digital_silence = all_digital_silence
        self.calls = []

    def inspect_canonical_wav(self, payload):
        self.calls.append(payload)
        return DecodedMediaFacts(
            CanonicalAudioFacts(),
            self.sample_count,
            max(1, self.sample_count * 1000 // 44_100),
            self.all_digital_silence,
        )


class FakeWorkspaceStore:
    def __init__(self) -> None:
        self.values = {}
        self.saves = []

    def load(self, attempt_id):
        return self.values.get(attempt_id)

    def save(self, workspace) -> None:
        self.values[workspace.attempt_id] = workspace
        self.saves.append(workspace)


class FakeAttemptWorkspaceVerifier:
    def __init__(
        self,
        *,
        force_workspace_match: bool | None = None,
        force_frozen_plan_match: bool | None = None,
    ) -> None:
        self.force_workspace_match = force_workspace_match
        self.force_frozen_plan_match = force_frozen_plan_match

    def verify(self, workspace, target, attempt_state, reservation_revision, expected_frozen_plan_digest):
        matches = (
            workspace is not None
            and workspace.attempt_id == target.attempt_id
            and workspace.reservation_revision == reservation_revision
        )
        if self.force_workspace_match is not None:
            matches = self.force_workspace_match
        if workspace is None:
            return VerifiedWorkspaceRecoveryFacts(False, False, RecoveryStage.RESERVED, SubmissionEvidence.NOT_STARTED)
        frozen_plan_matches = workspace.frozen_plan_digest == expected_frozen_plan_digest
        if self.force_frozen_plan_match is not None:
            frozen_plan_matches = self.force_frozen_plan_match
        stage = {
            AttemptState.RESERVED: RecoveryStage.RESERVED,
            AttemptState.INPUT_FROZEN: RecoveryStage.INPUT_FROZEN,
            AttemptState.EXTERNAL_WORK_STARTED: RecoveryStage.EXTERNAL_WORK_STARTED,
            AttemptState.ARTIFACTS_STAGED: RecoveryStage.ARTIFACTS_STAGED,
            AttemptState.ARTIFACTS_PUBLISHED: RecoveryStage.ARTIFACTS_PUBLISHED,
        }.get(workspace.state, RecoveryStage.ARTIFACTS_PUBLISHED)
        return VerifiedWorkspaceRecoveryFacts(matches, frozen_plan_matches, stage, workspace.submission)


class FakeProviderEventVerifier:
    def verify(self, workspace):
        if workspace is None:
            return VerifiedProviderRecoveryFacts(None, False)
        if workspace.attempt_kind is not AttemptKind.GENERATION:
            return VerifiedProviderRecoveryFacts(None, True)
        terminal = workspace.events[-1] if workspace.events else None
        return VerifiedProviderRecoveryFacts(
            None if terminal is None else terminal.terminal_classification,
            terminal is not None and terminal.kind.value == "terminal",
        )


class FakeArtifactEvidenceVerifier:
    def __init__(self, media=None) -> None:
        self.media = media

    def verify(self, workspace):
        if workspace is None:
            return VerifiedArtifactRecoveryFacts(False, False, False, False)
        observed = bool(workspace.staged_artifacts)
        published = bool(workspace.published_artifacts)
        return VerifiedArtifactRecoveryFacts(observed, observed, published, published)

    def recover_media(self, workspace, artifact):
        self.verify(workspace)
        if (
            type(workspace) is not AttemptWorkspaceEvidence
            or workspace.published_artifacts != (artifact,)
            or self.media is None
        ):
            raise ValidationError("fake recovery requires the workspace's exact configured publication")
        if type(self.media) is not DecodedMediaFacts or self.media.all_digital_silence:
            raise ValidationError("fake recovery media must be configured non-silent decoded facts")
        return self.media


class FakeDryPcmAssembler:
    def __init__(self) -> None:
        self.narration_calls = []
        self.episode_calls = []

    def assemble_narration(self, sources, gaps_samples, source_offsets):
        from heritage_archive.contexts.narrator_voice.domain.evidence import PassageOffset

        self.narration_calls.append((sources, gaps_samples, source_offsets))
        shifted = []
        cursor = 0
        for index, (source, offset) in enumerate(zip(sources, source_offsets)):
            shifted.append(PassageOffset(offset.passage_id, offset.text_revision, offset.text_digest, cursor, cursor + source.media.sample_count))
            cursor += source.media.sample_count
            if index < len(gaps_samples):
                cursor += gaps_samples[index]
        media = DecodedMediaFacts(CanonicalAudioFacts(), cursor, max(1, cursor * 1000 // 44_100), False)
        return DryAssemblyResult(b"RIFF-fake-dry-narration", media, tuple(shifted), ())

    def assemble_episode(self, intro, diary, gap_samples, intro_offsets, diary_offsets, intro_snapshot_digest, diary_snapshot_digest):
        from heritage_archive.contexts.narrator_voice.domain.evidence import ComponentOffset, PassageOffset
        from heritage_archive.contexts.narrator_voice.domain.values import ComponentRole

        self.episode_calls.append((intro, diary, gap_samples, intro_offsets, diary_offsets, intro_snapshot_digest, diary_snapshot_digest))
        diary_start = intro.media.sample_count + gap_samples
        shifted_diary = tuple(
            PassageOffset(value.passage_id, value.text_revision, value.text_digest, value.start_sample + diary_start, value.end_sample + diary_start)
            for value in diary_offsets
        )
        components = (
            ComponentOffset(ComponentRole.INTRO, 0, intro.media.sample_count, intro_snapshot_digest, intro_offsets),
            ComponentOffset(ComponentRole.DIARY, diary_start, diary_start + diary.media.sample_count, diary_snapshot_digest, shifted_diary),
        )
        total = diary_start + diary.media.sample_count
        media = DecodedMediaFacts(CanonicalAudioFacts(), total, max(1, total * 1000 // 44_100), False)
        return DryAssemblyResult(b"RIFF-fake-dry-episode", media, (), components)


class FakeTimingNormalizer:
    def __init__(self, cue_ids) -> None:
        self.cue_ids = list(cue_ids)
        self.calls = []

    def normalize(self, request):
        from heritage_archive.contexts.narrator_voice.application.ports import TimingNormalizationResult
        from heritage_archive.contexts.narrator_voice.domain.evidence import (
            CueGranularity,
            CueProvenance,
            TimingCue,
            TimingReviewStatus,
        )
        self.calls.append(request)
        cues = [
            TimingCue(
                self.cue_ids.pop(0), source.role, source.lane, source.source_job_id,
                source.source_master_id, source.passage_id, source.text_revision,
                source.text_digest, source.display_text, None,
                source.start_sample, source.end_sample, CueGranularity.PASSAGE,
                CueProvenance.DETERMINISTIC_ASSEMBLY, "fake timing fallback", "v1",
                request.master_artifact.reference.content_digest, source.text_digest,
                TimingReviewStatus.VALIDATED,
            )
            for source in request.source_passages
        ]
        return TimingNormalizationResult(
            tuple(cues), None, ("fake monotonic bounds pass", "fake passage coverage pass"),
            TimingReviewStatus.VALIDATED,
        )
