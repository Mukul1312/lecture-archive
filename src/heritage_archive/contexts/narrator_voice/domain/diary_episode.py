"""DiaryEpisode aggregate: exact dry intro-then-diary composition and timing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from heritage_archive.kernel import ActorId, ContentDigest, ValidationError

from .errors import AuthorizationDenied, DomainInvariantError, NotFound, RevisionConflict
from .evidence import (
    AttemptState,
    ComponentOffset,
    DecodedMediaFacts,
    EpisodeAssemblyAttempt,
    EpisodeListeningDecision,
    EpisodeSpeechMaster,
    ListeningOutcome,
    NarrationMasterSnapshot,
    PublishedArtifact,
    TimedNarrationPackage,
    TimingReviewStatus,
)
from .ids import (
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeListeningDecisionId,
    EpisodeSpeechMasterId,
)
from .values import ComponentRole, Lane


def _utc(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f"{field} must be an aware UTC datetime")
    return value


class EpisodeStatus(str, Enum):
    DRAFT = "draft"
    CONFIGURED = "configured"


@dataclass(frozen=True, slots=True)
class EpisodeComponentAttachment:
    role: ComponentRole
    snapshot: NarrationMasterSnapshot
    attached_at: datetime
    resulting_revision: int

    def __post_init__(self) -> None:
        if type(self.role) is not ComponentRole or type(self.snapshot) is not NarrationMasterSnapshot:
            raise ValidationError("episode component attachment role or snapshot is invalid")
        _utc(self.attached_at, "episode component attachment time")
        if type(self.resulting_revision) is not int or self.resulting_revision < 2:
            raise ValidationError("episode component revision must be an integer >= 2")


@dataclass(frozen=True, slots=True)
class EpisodeGapRevision:
    gap_samples: int
    changed_at: datetime
    resulting_revision: int

    def __post_init__(self) -> None:
        if type(self.gap_samples) is not int or self.gap_samples < 0:
            raise ValidationError("episode gap must be explicit nonnegative integer samples")
        _utc(self.changed_at, "episode gap revision time")
        if type(self.resulting_revision) is not int or self.resulting_revision < 2:
            raise ValidationError("episode gap revision must be an integer >= 2")


@dataclass(frozen=True, slots=True)
class DiaryEpisodeSnapshot:
    episode_id: DiaryEpisodeId
    revision: int
    intro_snapshot: NarrationMasterSnapshot | None
    diary_snapshot: NarrationMasterSnapshot | None
    component_history: tuple[EpisodeComponentAttachment, ...]
    gap_samples: int | None
    gap_history: tuple[EpisodeGapRevision, ...]
    assembly_attempts: tuple[EpisodeAssemblyAttempt, ...]
    speech_masters: tuple[EpisodeSpeechMaster, ...]
    listening_decisions: tuple[EpisodeListeningDecision, ...]
    timing_packages: tuple[TimedNarrationPackage, ...]
    prepared_at: datetime


class DiaryEpisode:
    __slots__ = tuple(f"_{field}" for field in DiaryEpisodeSnapshot.__dataclass_fields__)

    def __init__(self, snapshot: DiaryEpisodeSnapshot) -> None:
        if type(snapshot) is not DiaryEpisodeSnapshot:
            raise ValidationError("episode root requires a DiaryEpisodeSnapshot")
        if type(snapshot.episode_id) is not DiaryEpisodeId or type(snapshot.revision) is not int or snapshot.revision < 1:
            raise ValidationError("episode identity or revision is invalid")
        if snapshot.intro_snapshot is not None:
            self._validate_component(ComponentRole.INTRO, snapshot.intro_snapshot, snapshot.episode_id)
        if snapshot.diary_snapshot is not None:
            self._validate_component(ComponentRole.DIARY, snapshot.diary_snapshot, snapshot.episode_id)
        if type(snapshot.component_history) is not tuple or any(type(value) is not EpisodeComponentAttachment for value in snapshot.component_history):
            raise ValidationError("episode component history must be immutable")
        latest_intro = next((value.snapshot for value in reversed(snapshot.component_history) if value.role is ComponentRole.INTRO), None)
        latest_diary = next((value.snapshot for value in reversed(snapshot.component_history) if value.role is ComponentRole.DIARY), None)
        if latest_intro != snapshot.intro_snapshot or latest_diary != snapshot.diary_snapshot:
            raise ValidationError("episode current components must equal latest append-only attachments")
        if snapshot.gap_samples is not None and (type(snapshot.gap_samples) is not int or snapshot.gap_samples < 0):
            raise ValidationError("episode current gap must be nonnegative integer samples or null")
        if type(snapshot.gap_history) is not tuple or any(type(value) is not EpisodeGapRevision for value in snapshot.gap_history):
            raise ValidationError("episode gap history must be immutable")
        latest_gap = snapshot.gap_history[-1].gap_samples if snapshot.gap_history else None
        if latest_gap != snapshot.gap_samples:
            raise ValidationError("episode current gap must equal latest append-only gap revision")
        for field in ("assembly_attempts", "speech_masters", "listening_decisions", "timing_packages"):
            if type(getattr(snapshot, field)) is not tuple:
                raise ValidationError(f"episode {field} must be immutable")
        _utc(snapshot.prepared_at, "episode preparation time")
        for field in DiaryEpisodeSnapshot.__dataclass_fields__:
            object.__setattr__(self, f"_{field}", getattr(snapshot, field))

    @staticmethod
    def _validate_component(role: ComponentRole, snapshot: NarrationMasterSnapshot, episode_id: DiaryEpisodeId) -> None:
        # INV-DE-2: only a complete root-issued by-value snapshot can be attached.
        if type(snapshot) is not NarrationMasterSnapshot or snapshot.role is not role:
            raise ValidationError("episode component snapshot role does not match attachment role")
        if role is ComponentRole.INTRO:
            if snapshot.lane is not Lane.C or snapshot.intended_episode_id != episode_id:
                raise ValidationError("intro snapshot must be Lane C and bound to this exact episode")
        elif snapshot.lane is not Lane.B or snapshot.intended_episode_id is not None:
            raise ValidationError("diary snapshot must be Lane B and unbound to another episode")

    @classmethod
    def prepare(cls, episode_id: DiaryEpisodeId, prepared_at: datetime) -> DiaryEpisode:
        return cls(DiaryEpisodeSnapshot(episode_id, 1, None, None, (), None, (), (), (), (), (), prepared_at))

    @classmethod
    def from_snapshot(cls, snapshot: DiaryEpisodeSnapshot) -> DiaryEpisode:
        return cls(snapshot)

    def to_snapshot(self) -> DiaryEpisodeSnapshot:
        return DiaryEpisodeSnapshot(**{field: getattr(self, f"_{field}") for field in DiaryEpisodeSnapshot.__dataclass_fields__})

    @property
    def episode_id(self) -> DiaryEpisodeId:
        return self._episode_id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def intro_snapshot(self) -> NarrationMasterSnapshot | None:
        return self._intro_snapshot

    @property
    def diary_snapshot(self) -> NarrationMasterSnapshot | None:
        return self._diary_snapshot

    @property
    def component_history(self) -> tuple[EpisodeComponentAttachment, ...]:
        return self._component_history

    @property
    def gap_samples(self) -> int | None:
        return self._gap_samples

    @property
    def gap_history(self) -> tuple[EpisodeGapRevision, ...]:
        return self._gap_history

    @property
    def components(self) -> tuple[EpisodeComponentAttachment, ...]:
        latest: list[EpisodeComponentAttachment] = []
        for role in (ComponentRole.INTRO, ComponentRole.DIARY):
            value = next((item for item in reversed(self._component_history) if item.role is role), None)
            if value is not None:
                latest.append(value)
        return tuple(latest)

    @property
    def status(self) -> EpisodeStatus:
        if self._intro_snapshot is not None and self._diary_snapshot is not None and self._gap_samples is not None:
            return EpisodeStatus.CONFIGURED
        return EpisodeStatus.DRAFT

    @property
    def assembly_attempts(self) -> tuple[EpisodeAssemblyAttempt, ...]:
        return self._assembly_attempts

    @property
    def speech_masters(self) -> tuple[EpisodeSpeechMaster, ...]:
        return self._speech_masters

    @property
    def listening_decisions(self) -> tuple[EpisodeListeningDecision, ...]:
        return self._listening_decisions

    @property
    def timing_packages(self) -> tuple[TimedNarrationPackage, ...]:
        return self._timing_packages

    def _check_revision(self, expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision != self._revision:
            raise RevisionConflict(f"expected episode revision {expected_revision!r}, current is {self._revision}")

    def _attach(self, role: ComponentRole, snapshot: NarrationMasterSnapshot, attached_at: datetime, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        self._validate_component(role, snapshot, self._episode_id)
        current = self._intro_snapshot if role is ComponentRole.INTRO else self._diary_snapshot
        if current == snapshot:
            raise ValidationError("the exact episode component snapshot is already attached")
        _utc(attached_at, "episode component attachment time")
        self._revision += 1
        attachment = EpisodeComponentAttachment(role, snapshot, attached_at, self._revision)
        self._component_history = (*self._component_history, attachment)
        if role is ComponentRole.INTRO:
            self._intro_snapshot = snapshot
        else:
            self._diary_snapshot = snapshot

    def attach_intro(self, snapshot: NarrationMasterSnapshot, attached_at: datetime, *, expected_revision: int) -> None:
        self._attach(ComponentRole.INTRO, snapshot, attached_at, expected_revision)

    def attach_diary(self, snapshot: NarrationMasterSnapshot, attached_at: datetime, *, expected_revision: int) -> None:
        self._attach(ComponentRole.DIARY, snapshot, attached_at, expected_revision)

    def set_intro_diary_gap(self, gap_samples: int, changed_at: datetime, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        if type(gap_samples) is not int or gap_samples < 0 or gap_samples == self._gap_samples:
            raise ValidationError("episode gap must be a changed explicit nonnegative integer sample count")
        _utc(changed_at, "episode gap revision time")
        self._revision += 1
        self._gap_samples = gap_samples
        self._gap_history = (*self._gap_history, EpisodeGapRevision(gap_samples, changed_at, self._revision))

    def reserve_assembly_preview(self, *, expected_revision: int) -> tuple[ContentDigest, ContentDigest, int]:
        self._check_revision(expected_revision)
        if self.status is not EpisodeStatus.CONFIGURED:
            # INV-DE-1: only configured exact intro+diary+gap input is assembly-ready.
            raise DomainInvariantError("episode is not configured for assembly")
        assert self._intro_snapshot is not None and self._diary_snapshot is not None and self._gap_samples is not None
        return self._intro_snapshot.snapshot_digest, self._diary_snapshot.snapshot_digest, self._gap_samples

    def episode_assembly_attempt(self, attempt_id: EpisodeAssemblyAttemptId) -> EpisodeAssemblyAttempt:
        for attempt in self._assembly_attempts:
            if attempt.attempt_id == attempt_id:
                return attempt
        raise NotFound(f"episode assembly attempt {attempt_id} is not part of episode {self._episode_id}")

    def _replace_assembly_attempt(self, updated: EpisodeAssemblyAttempt) -> None:
        self._assembly_attempts = tuple(
            updated if value.attempt_id == updated.attempt_id else value
            for value in self._assembly_attempts
        )

    def reserve_episode_assembly(
        self,
        attempt_id: EpisodeAssemblyAttemptId,
        sources_eligible: bool,
        reserved_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        self._check_revision(expected_revision)
        if sources_eligible is not True:
            # INV-DE-3: current source jobs and current authority are mandatory.
            raise AuthorizationDenied("current source-job and authority eligibility is required for episode assembly")
        if self.status is not EpisodeStatus.CONFIGURED:
            raise DomainInvariantError("episode is not configured for assembly")
        if type(attempt_id) is not EpisodeAssemblyAttemptId or any(
            value.attempt_id == attempt_id for value in self._assembly_attempts
        ):
            raise ValidationError("episode assembly attempt identity is invalid or duplicated")
        _utc(reserved_at, "episode assembly reservation time")
        assert self._intro_snapshot is not None and self._diary_snapshot is not None and self._gap_samples is not None
        attempt = EpisodeAssemblyAttempt(
            attempt_id,
            self._revision,
            (self._intro_snapshot.snapshot_digest, self._diary_snapshot.snapshot_digest),
            self._gap_samples,
            AttemptState.RESERVED,
            None,
            None,
            (),
            None,
            None,
            reserved_at,
            reserved_at,
        )
        self._assembly_attempts = (*self._assembly_attempts, attempt)
        self._revision += 1

    def _current_assembly_input(self) -> tuple[ContentDigest, ContentDigest, int]:
        if self.status is not EpisodeStatus.CONFIGURED:
            raise DomainInvariantError("episode is not configured for assembly")
        assert self._intro_snapshot is not None and self._diary_snapshot is not None and self._gap_samples is not None
        return self._intro_snapshot.snapshot_digest, self._diary_snapshot.snapshot_digest, self._gap_samples

    def freeze_episode_assembly_input(self, attempt_id: EpisodeAssemblyAttemptId, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        attempt = self.episode_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.RESERVED:
            raise DomainInvariantError("episode assembly input may freeze only from reserved")
        intro_digest, diary_digest, gap_samples = self._current_assembly_input()
        if attempt.component_snapshot_digests != (intro_digest, diary_digest) or attempt.gap_samples != gap_samples:
            raise DomainInvariantError("episode components or gap changed before input freeze")
        self._replace_assembly_attempt(replace(attempt, state=AttemptState.INPUT_FROZEN))
        self._revision += 1

    def mark_episode_assembly_work_started(self, attempt_id: EpisodeAssemblyAttemptId, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        attempt = self.episode_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.INPUT_FROZEN:
            raise DomainInvariantError("episode assembly work starts only after input freeze")
        self._replace_assembly_attempt(replace(attempt, state=AttemptState.EXTERNAL_WORK_STARTED))
        self._revision += 1

    @staticmethod
    def _validate_shifted_passages(
        component: ComponentOffset,
        source: NarrationMasterSnapshot,
    ) -> None:
        if len(component.passage_offsets) != len(source.passage_offsets):
            raise ValidationError("episode component must carry every source passage offset")
        for carried, original in zip(component.passage_offsets, source.passage_offsets):
            if (
                carried.passage_id != original.passage_id
                or carried.text_revision != original.text_revision
                or carried.text_digest != original.text_digest
                or carried.start_sample != component.start_sample + original.start_sample
                or carried.end_sample != component.start_sample + original.end_sample
            ):
                raise ValidationError("episode passage offsets must be exact shifted source-master offsets")

    def stage_episode_speech_master(
        self,
        attempt_id: EpisodeAssemblyAttemptId,
        artifact: PublishedArtifact,
        media: DecodedMediaFacts,
        component_offsets: tuple[ComponentOffset, ...],
        *,
        expected_revision: int,
    ) -> None:
        self._check_revision(expected_revision)
        attempt = self.episode_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.EXTERNAL_WORK_STARTED:
            raise DomainInvariantError("episode speech master may stage only after assembly work starts")
        if type(artifact) is not PublishedArtifact or type(media) is not DecodedMediaFacts:
            raise ValidationError("episode master staging requires immutable artifact/media evidence")
        if type(component_offsets) is not tuple or tuple(value.role for value in component_offsets) != (
            ComponentRole.INTRO,
            ComponentRole.DIARY,
        ):
            raise ValidationError("episode master requires exactly intro then diary offsets")
        assert self._intro_snapshot is not None and self._diary_snapshot is not None
        intro, diary = component_offsets
        expected_diary_start = self._intro_snapshot.media.sample_count + attempt.gap_samples
        expected_total = expected_diary_start + self._diary_snapshot.media.sample_count
        if (
            intro.snapshot_digest != attempt.component_snapshot_digests[0]
            or intro.start_sample != 0
            or intro.end_sample != self._intro_snapshot.media.sample_count
            or diary.snapshot_digest != attempt.component_snapshot_digests[1]
            or diary.start_sample != expected_diary_start
            or diary.end_sample != expected_total
            or media.sample_count != expected_total
        ):
            raise ValidationError("episode offsets/media must be exact intro plus explicit gap plus diary")
        self._validate_shifted_passages(intro, self._intro_snapshot)
        self._validate_shifted_passages(diary, self._diary_snapshot)
        self._replace_assembly_attempt(
            replace(
                attempt,
                state=AttemptState.ARTIFACTS_STAGED,
                artifact=artifact,
                media=media,
                component_offsets=component_offsets,
            )
        )
        self._revision += 1

    def mark_episode_speech_master_published(
        self,
        attempt_id: EpisodeAssemblyAttemptId,
        *,
        expected_revision: int,
    ) -> None:
        self._check_revision(expected_revision)
        attempt = self.episode_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.ARTIFACTS_STAGED:
            raise DomainInvariantError("episode master publication requires staged evidence")
        self._replace_assembly_attempt(replace(attempt, state=AttemptState.ARTIFACTS_PUBLISHED))
        self._revision += 1

    def complete_episode_assembly(
        self,
        attempt_id: EpisodeAssemblyAttemptId,
        master_id: EpisodeSpeechMasterId,
        completed_at: datetime,
        *,
        expected_revision: int,
    ) -> EpisodeSpeechMaster:
        self._check_revision(expected_revision)
        attempt = self.episode_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.ARTIFACTS_PUBLISHED or attempt.artifact is None or attempt.media is None:
            raise DomainInvariantError("episode assembly completes only after publication")
        if type(master_id) is not EpisodeSpeechMasterId or any(value.master_id == master_id for value in self._speech_masters):
            raise ValidationError("episode speech master identity is invalid or duplicated")
        _utc(completed_at, "episode assembly completion time")
        master = EpisodeSpeechMaster(
            master_id,
            self._episode_id,
            attempt.component_snapshot_digests,
            attempt.gap_samples,
            attempt.component_offsets,
            attempt.artifact,
            attempt.media,
            completed_at,
        )
        self._replace_assembly_attempt(
            replace(attempt, state=AttemptState.COMPLETED, master_id=master_id, updated_at=completed_at)
        )
        self._speech_masters = (*self._speech_masters, master)
        self._revision += 1
        return master

    def finalize_episode_assembly_outcome(
        self,
        attempt_id: EpisodeAssemblyAttemptId,
        outcome: AttemptState,
        reason: str,
        finalized_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        from heritage_archive.kernel import require_canonical_text

        self._check_revision(expected_revision)
        attempt = self.episode_assembly_attempt(attempt_id)
        if attempt.state.terminal:
            raise DomainInvariantError("terminal episode assembly history is immutable")
        if outcome not in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.UNKNOWN, AttemptState.QUARANTINED}:
            raise ValidationError("episode assembly outcome is invalid")
        require_canonical_text(reason, field="episode assembly outcome reason", nonempty=True)
        _utc(finalized_at, "episode assembly outcome time")
        self._replace_assembly_attempt(replace(attempt, state=outcome, reason=reason, updated_at=finalized_at))
        self._revision += 1

    def reconcile_episode_assembly(
        self,
        attempt_id: EpisodeAssemblyAttemptId,
        outcome: AttemptState,
        recorded_evidence: str,
        reconciled_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        from heritage_archive.kernel import require_canonical_text

        self._check_revision(expected_revision)
        attempt = self.episode_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.UNKNOWN:
            raise DomainInvariantError("only unknown episode assembly attempts may be reconciled")
        if outcome not in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.QUARANTINED}:
            raise DomainInvariantError("episode assembly recovery must resolve to a conservative terminal outcome")
        require_canonical_text(recorded_evidence, field="episode assembly reconciliation evidence", nonempty=True)
        _utc(reconciled_at, "episode assembly reconciliation time")
        self._replace_assembly_attempt(
            replace(
                attempt,
                state=outcome,
                reason=f"{attempt.reason}; reconciliation: {recorded_evidence}",
                updated_at=reconciled_at,
            )
        )
        self._revision += 1

    def speech_master(self, master_id: EpisodeSpeechMasterId) -> EpisodeSpeechMaster:
        for master in self._speech_masters:
            if master.master_id == master_id:
                return master
        raise NotFound(f"episode speech master {master_id} is not part of episode {self._episode_id}")

    def record_episode_listening(
        self,
        decision_id: EpisodeListeningDecisionId,
        master_id: EpisodeSpeechMasterId,
        actor_id: ActorId,
        outcome: ListeningOutcome,
        notes: str,
        decided_at: datetime,
        *,
        expected_revision: int,
    ) -> EpisodeListeningDecision:
        self._check_revision(expected_revision)
        self.speech_master(master_id)
        if any(value.decision_id == decision_id for value in self._listening_decisions):
            raise ValidationError("episode listening decision identity already exists")
        decision = EpisodeListeningDecision(decision_id, master_id, actor_id, outcome, notes, decided_at)
        self._listening_decisions = (*self._listening_decisions, decision)
        self._revision += 1
        return decision

    def _validate_timing_cue_coverage(self, package: TimedNarrationPackage) -> None:
        assert self._intro_snapshot is not None and self._diary_snapshot is not None
        components = (
            (ComponentRole.INTRO, self._intro_snapshot, package.component_offsets[0]),
            (ComponentRole.DIARY, self._diary_snapshot, package.component_offsets[1]),
        )
        for role, snapshot, component in components:
            for carried in component.passage_offsets:
                matching = tuple(
                    cue for cue in package.cues
                    if cue.role is role
                    and cue.lane is snapshot.lane
                    and cue.source_job_id == snapshot.issuing_job_id
                    and cue.source_master_id == snapshot.source_master_id
                    and cue.passage_id == carried.passage_id
                    and cue.text_revision == carried.text_revision
                    and cue.text_digest == carried.text_digest
                    and cue.input_text_digest == carried.text_digest
                    and cue.input_audio_digest == package.episode_artifact.reference.content_digest
                    and cue.start_sample >= carried.start_sample
                    and cue.end_sample <= carried.end_sample
                )
                if not matching:
                    raise ValidationError("timed package must cover every exact source passage without invented provenance")

    def record_timed_package(self, package: TimedNarrationPackage, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        if type(package) is not TimedNarrationPackage:
            raise ValidationError("episode timing history requires a TimedNarrationPackage")
        if any(value.package_id == package.package_id for value in self._timing_packages):
            raise ValidationError("timed package identity already exists")
        if package.episode_id != self._episode_id or package.episode_revision != self._revision:
            raise ValidationError("timed package must bind the exact current episode identity and revision")
        master = self.speech_master(package.episode_master_id)
        latest_listening = next(
            (value for value in reversed(self._listening_decisions) if value.master_id == master.master_id),
            None,
        )
        if latest_listening is None or latest_listening.outcome is not ListeningOutcome.PASSED:
            raise DomainInvariantError("timed package requires a current passing listen for its exact episode master")
        intro_digest, diary_digest, gap_samples = self._current_assembly_input()
        if (
            master.component_snapshot_digests != (intro_digest, diary_digest)
            or master.gap_samples != gap_samples
            or package.intro_snapshot_digest != intro_digest
            or package.diary_snapshot_digest != diary_digest
            or package.episode_artifact != master.artifact
            or package.episode_media != master.media
            or package.component_offsets != master.component_offsets
        ):
            raise ValidationError("timed package must bind the exact current episode master and source snapshots")
        assert self._intro_snapshot is not None and self._diary_snapshot is not None
        if package.authority_snapshots != (
            self._intro_snapshot.authority_snapshot,
            self._diary_snapshot.authority_snapshot,
        ):
            raise ValidationError("timed package must preserve both exact source authority snapshots")
        if package.timing_review_status not in {TimingReviewStatus.VALIDATED, TimingReviewStatus.HUMAN_REVIEWED}:
            raise DomainInvariantError("timed package must carry validated or human-reviewed timing")
        if not package.cues or len({value.cue_id for value in package.cues}) != len(package.cues):
            raise ValidationError("timed package requires nonempty uniquely identified cues")
        self._validate_timing_cue_coverage(package)
        expected_version = len(self._timing_packages) + 1
        if package.version != expected_version:
            raise ValidationError("timed package version must be the next append-only version")
        if not self._timing_packages:
            if any(
                value is not None
                for value in (package.source_package_digest, package.correction_actor_id, package.correction_reason)
            ):
                raise ValidationError("initial timed package cannot claim correction lineage")
        else:
            latest = self._timing_packages[-1]
            if (
                package.source_package_digest != latest.package_digest
                or package.correction_actor_id is None
                or package.correction_reason is None
                or package.episode_master_id != latest.episode_master_id
            ):
                raise ValidationError("timing correction must name the exact latest package, actor, reason and master")
        self._timing_packages = (*self._timing_packages, package)
        self._revision += 1
