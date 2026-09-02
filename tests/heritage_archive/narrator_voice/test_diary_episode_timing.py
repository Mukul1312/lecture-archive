"""DiaryEpisode timed-package and immutable correction tests."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ValidationError
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    ComponentOffset,
    CueGranularity,
    CueProvenance,
    ListeningOutcome,
    PassageOffset,
    TimedNarrationPackage,
    TimingCue,
    TimingReviewStatus,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    CueId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeListeningDecisionId,
    EpisodeSpeechMasterId,
    TimedNarrationPackageId,
)
from heritage_archive.contexts.narrator_voice.domain.values import ComponentRole, Lane
from tests.heritage_archive.narrator_voice.fixtures import NOW, make_artifact, make_master_snapshot, uuid


class DiaryEpisodeTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.episode_id = DiaryEpisodeId(uuid(600))
        self.episode = DiaryEpisode.prepare(self.episode_id, NOW)
        self.intro = make_master_snapshot(lane=Lane.C, episode_id=self.episode_id, index=601, samples=100)
        self.diary = make_master_snapshot(lane=Lane.B, episode_id=None, index=610, samples=200)
        self.episode.attach_intro(self.intro, NOW, expected_revision=1)
        self.episode.attach_diary(self.diary, NOW, expected_revision=2)
        self.episode.set_intro_diary_gap(50, NOW, expected_revision=3)
        attempt_id = EpisodeAssemblyAttemptId(uuid(620))
        self.episode.reserve_episode_assembly(attempt_id, True, NOW, expected_revision=4)
        self.episode.freeze_episode_assembly_input(attempt_id, expected_revision=5)
        self.episode.mark_episode_assembly_work_started(attempt_id, expected_revision=6)
        artifact, media = make_artifact(621, "timed-episode-master", samples=350)
        intro_passage = self.intro.passage_offsets[0]
        diary_passage = self.diary.passage_offsets[0]
        offsets = (
            ComponentOffset(ComponentRole.INTRO, 0, 100, self.intro.snapshot_digest, (intro_passage,)),
            ComponentOffset(
                ComponentRole.DIARY,
                150,
                350,
                self.diary.snapshot_digest,
                (PassageOffset(diary_passage.passage_id, diary_passage.text_revision, diary_passage.text_digest, 150, 350),),
            ),
        )
        self.episode.stage_episode_speech_master(attempt_id, artifact, media, offsets, expected_revision=7)
        self.episode.mark_episode_speech_master_published(attempt_id, expected_revision=8)
        self.master = self.episode.complete_episode_assembly(
            attempt_id, EpisodeSpeechMasterId(uuid(622)), NOW, expected_revision=9
        )
        self.actor = ActorId(uuid(623))
        self.episode.record_episode_listening(
            EpisodeListeningDecisionId(uuid(624)), self.master.master_id, self.actor,
            ListeningOutcome.PASSED, "fake timing readiness pass", NOW, expected_revision=10,
        )

    def cue(self, role: ComponentRole, index: int, *, start: int, end: int) -> TimingCue:
        source = self.intro if role is ComponentRole.INTRO else self.diary
        source_offset = source.passage_offsets[0]
        return TimingCue(
            CueId(uuid(index)), role, source.lane, source.issuing_job_id, source.source_master_id,
            source_offset.passage_id, source_offset.text_revision, source_offset.text_digest,
            f"fake {role.value} display text", None, start, end, CueGranularity.PASSAGE,
            CueProvenance.DETERMINISTIC_ASSEMBLY, "fake deterministic normalizer", "v1",
            self.master.artifact.reference.content_digest, source_offset.text_digest,
            TimingReviewStatus.VALIDATED,
        )

    def package(
        self,
        package_id: TimedNarrationPackageId,
        version: int,
        cues: tuple[TimingCue, ...],
        *,
        episode_revision: int,
        source_digest=None,
        correction_actor=None,
        correction_reason=None,
    ) -> TimedNarrationPackage:
        return TimedNarrationPackage.create(
            package_id=package_id,
            version=version,
            episode_id=self.episode_id,
            episode_revision=episode_revision,
            episode_master=self.master,
            intro_snapshot_digest=self.intro.snapshot_digest,
            diary_snapshot_digest=self.diary.snapshot_digest,
            cues=cues,
            raw_timing_artifacts=(),
            normalized_timing_artifact=None,
            validation_results=("fake offsets checked", "fake passage coverage checked"),
            timing_review_status=TimingReviewStatus.VALIDATED,
            authority_snapshots=(self.intro.authority_snapshot, self.diary.authority_snapshot),
            source_package_digest=source_digest,
            correction_actor_id=correction_actor,
            correction_reason=correction_reason,
            created_at=NOW,
        )

    def test_INV_DE_8_package_binds_exact_master_sources_text_and_append_only_correction_lineage(self) -> None:
        cues = (self.cue(ComponentRole.INTRO, 630, start=0, end=100), self.cue(ComponentRole.DIARY, 631, start=150, end=350))
        first = self.package(TimedNarrationPackageId(uuid(632)), 1, cues, episode_revision=11)
        self.episode.record_timed_package(first, expected_revision=11)
        corrected_cues = (cues[0], self.cue(ComponentRole.DIARY, 633, start=155, end=350))
        corrected = self.package(
            TimedNarrationPackageId(uuid(634)), 2, corrected_cues, episode_revision=12,
            source_digest=first.package_digest, correction_actor=self.actor,
            correction_reason="fake qualified correction",
        )
        self.episode.record_timed_package(corrected, expected_revision=12)
        self.assertEqual(self.episode.timing_packages, (first, corrected))
        self.assertEqual((corrected.source_package_digest, corrected.correction_actor_id), (first.package_digest, self.actor))

    def test_INV_DE_9_monotonic_bounded_passage_cues_are_required_without_fabricated_word_timing(self) -> None:
        cues = (self.cue(ComponentRole.INTRO, 640, start=0, end=100), self.cue(ComponentRole.DIARY, 641, start=150, end=350))
        package = self.package(TimedNarrationPackageId(uuid(642)), 1, cues, episode_revision=11)
        self.episode.record_timed_package(package, expected_revision=11)
        self.assertEqual(tuple(cue.granularity for cue in package.cues), (CueGranularity.PASSAGE, CueGranularity.PASSAGE))
        self.assertTrue(all(cue.text_span is None for cue in package.cues))
        with self.assertRaises(ValidationError):
            self.package(
                TimedNarrationPackageId(uuid(643)), 2,
                (self.cue(ComponentRole.INTRO, 644, start=0, end=200), self.cue(ComponentRole.DIARY, 645, start=150, end=350)),
                episode_revision=12, source_digest=package.package_digest,
                correction_actor=self.actor, correction_reason="fake overlap",
            )

    def test_package_rejects_missing_passage_coverage_and_correction_without_exact_latest_source(self) -> None:
        intro_only = (self.cue(ComponentRole.INTRO, 650, start=0, end=100),)
        first = self.package(TimedNarrationPackageId(uuid(651)), 1, intro_only, episode_revision=11)
        with self.assertRaises(ValidationError):
            self.episode.record_timed_package(first, expected_revision=11)
        complete = self.package(
            TimedNarrationPackageId(uuid(652)), 1,
            (intro_only[0], self.cue(ComponentRole.DIARY, 653, start=150, end=350)),
            episode_revision=11,
        )
        self.episode.record_timed_package(complete, expected_revision=11)
        wrong_source = self.package(
            TimedNarrationPackageId(uuid(654)), 2, complete.cues, episode_revision=12,
            source_digest=self.intro.snapshot_digest, correction_actor=self.actor,
            correction_reason="fake wrong source",
        )
        with self.assertRaises(ValidationError):
            self.episode.record_timed_package(wrong_source, expected_revision=12)


if __name__ == "__main__":
    unittest.main()
