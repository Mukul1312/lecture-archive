"""Strict in-memory no-network fakes for Narrator Voice application tests."""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from heritage_archive.kernel import ActorId, ArtifactId, ArtifactRef, ContentDigest
from heritage_archive.contexts.narrator_voice.application.ports import AuthorityObservation
from heritage_archive.contexts.narrator_voice.application.ports import DryAssemblyResult, PreviewCompilerResult, SynthesisResult
from heritage_archive.contexts.narrator_voice.domain.errors import (
    AmbiguousExternalFailure,
    BudgetDenied,
    DefinitePreSendFailure,
    ExternalWorkFailed,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import DecodedMediaFacts
from heritage_archive.contexts.narrator_voice.domain.values import CanonicalAudioFacts, NonNegativeDecimal
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord, AuthorizationStatus
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.ids import AuthorizationRecordId, DiaryEpisodeId, NarrationJobId
from heritage_archive.contexts.narrator_voice.domain.narration_job import NarrationJob


T = TypeVar("T")


class FakeActorResolver:
    def __init__(self, actors: dict[str, ActorId]) -> None:
        self.actors = dict(actors)
        self.calls: list[str] = []

    def resolve_actor(self, principal: str) -> ActorId:
        self.calls.append(principal)
        return self.actors[principal]


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
        self.syntax_families = list(syntax_families or [])

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
            NonNegativeDecimal(str(len(request.text.value) + 13)),
        )


class FakeBudgetLedger:
    def __init__(self) -> None:
        self.actions: list[tuple[str, object, object]] = []
        self.deny_reserve = False

    def reserve(self, reservation_id, estimated_usage) -> None:
        self.actions.append(("reserve", reservation_id, estimated_usage))
        if self.deny_reserve:
            raise BudgetDenied("fake budget denial")

    def settle(self, reservation_id, actual_usage) -> None:
        self.actions.append(("settle", reservation_id, actual_usage))

    def release(self, reservation_id, reason) -> None:
        self.actions.append(("release", reservation_id, reason))

    def hold(self, reservation_id, reason) -> None:
        self.actions.append(("hold", reservation_id, reason))


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
    def __init__(self, sample_count: int = 100) -> None:
        self.sample_count = sample_count
        self.calls = []

    def inspect_canonical_wav(self, payload):
        self.calls.append(payload)
        return DecodedMediaFacts(CanonicalAudioFacts(), self.sample_count, max(1, self.sample_count * 1000 // 44_100), False)


class FakeWorkspaceStore:
    def __init__(self) -> None:
        self.values = {}
        self.saves = []

    def load(self, attempt_id):
        return self.values.get(attempt_id)

    def save(self, workspace) -> None:
        self.values[workspace.attempt_id] = workspace
        self.saves.append(workspace)


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
        from heritage_archive.contexts.narrator_voice.domain.values import ComponentRole

        self.calls.append(request)
        cues = []
        for role, snapshot, component in (
            (ComponentRole.INTRO, request.intro_snapshot, request.component_offsets[0]),
            (ComponentRole.DIARY, request.diary_snapshot, request.component_offsets[1]),
        ):
            for offset in component.passage_offsets:
                cues.append(TimingCue(
                    self.cue_ids.pop(0), role, snapshot.lane, snapshot.issuing_job_id,
                    snapshot.source_master_id, offset.passage_id, offset.text_revision,
                    offset.text_digest, f"fake {role.value} passage", None,
                    offset.start_sample, offset.end_sample, CueGranularity.PASSAGE,
                    CueProvenance.DETERMINISTIC_ASSEMBLY, "fake timing fallback", "v1",
                    request.master_artifact.reference.content_digest, offset.text_digest,
                    TimingReviewStatus.VALIDATED,
                ))
        return TimingNormalizationResult(
            tuple(cues), None, ("fake monotonic bounds pass", "fake passage coverage pass"),
            TimingReviewStatus.VALIDATED,
        )
