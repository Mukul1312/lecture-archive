"""DiaryEpisode exact dry assembly, listening and recovery tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptState,
    ComponentOffset,
    ListeningOutcome,
    PassageOffset,
)
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, DomainInvariantError
from heritage_archive.contexts.narrator_voice.domain.ids import (
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeListeningDecisionId,
    EpisodeSpeechMasterId,
)
from heritage_archive.contexts.narrator_voice.domain.values import CanonicalAudioFacts, ComponentRole, Lane
from tests.heritage_archive.narrator_voice.fixtures import NOW, make_artifact, make_master_snapshot, uuid


class DiaryEpisodeAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.episode_id = DiaryEpisodeId(uuid(500))
        self.episode = DiaryEpisode.prepare(self.episode_id, NOW)
        self.intro = make_master_snapshot(lane=Lane.C, episode_id=self.episode_id, index=501, samples=100)
        self.diary = make_master_snapshot(lane=Lane.B, episode_id=None, index=510, samples=200)
        self.episode.attach_intro(self.intro, NOW, expected_revision=1)
        self.episode.attach_diary(self.diary, NOW, expected_revision=2)
        self.episode.set_intro_diary_gap(50, NOW, expected_revision=3)
        self.attempt_id = EpisodeAssemblyAttemptId(uuid(520))

    def assemble(self) -> None:
        self.episode.reserve_episode_assembly(self.attempt_id, True, NOW, expected_revision=4)
        self.episode.freeze_episode_assembly_input(self.attempt_id, expected_revision=5)
        self.episode.mark_episode_assembly_work_started(self.attempt_id, expected_revision=6)
        artifact, media = make_artifact(521, "episode-master", samples=350)
        intro_passage = self.intro.passage_offsets[0]
        diary_passage = self.diary.passage_offsets[0]
        offsets = (
            ComponentOffset(ComponentRole.INTRO, 0, 100, self.intro.snapshot_digest, (intro_passage,)),
            ComponentOffset(ComponentRole.DIARY, 150, 350, self.diary.snapshot_digest, (PassageOffset(diary_passage.passage_id, diary_passage.text_revision, diary_passage.text_digest, 150, 350),)),
        )
        self.episode.stage_episode_speech_master(self.attempt_id, artifact, media, offsets, expected_revision=7)
        self.episode.mark_episode_speech_master_published(self.attempt_id, expected_revision=8)
        self.episode.complete_episode_assembly(self.attempt_id, EpisodeSpeechMasterId(uuid(522)), NOW, expected_revision=9)

    def test_INV_DE_3_assembly_fails_closed_without_current_source_job_and_authority_eligibility(self) -> None:
        with self.assertRaises(AuthorizationDenied):
            self.episode.reserve_episode_assembly(self.attempt_id, False, NOW, expected_revision=4)
        self.assertEqual((self.episode.revision, self.episode.assembly_attempts), (4, ()))

    def test_INV_DE_4_both_components_and_episode_master_share_exact_canonical_audio_contract(self) -> None:
        self.assemble()
        master = self.episode.speech_masters[0]
        self.assertEqual((self.intro.media.audio, self.diary.media.audio, master.media.audio), (CanonicalAudioFacts(), CanonicalAudioFacts(), CanonicalAudioFacts()))

    def test_INV_DE_5_episode_master_is_exact_intro_gap_diary_evidence_with_no_hidden_dsp(self) -> None:
        self.assemble()
        master = self.episode.speech_masters[0]
        self.assertEqual(master.component_snapshot_digests, (self.intro.snapshot_digest, self.diary.snapshot_digest))
        self.assertEqual(master.gap_samples, 50)
        self.assertEqual(tuple((value.role, value.start_sample, value.end_sample) for value in master.component_offsets), ((ComponentRole.INTRO, 0, 100), (ComponentRole.DIARY, 150, 350)))
        with self.assertRaises(FrozenInstanceError):
            master.gap_samples = 0  # type: ignore[misc]

    def test_INV_DE_6_new_gap_preserves_old_master_and_requires_another_master_identity(self) -> None:
        self.assemble()
        old_master = self.episode.speech_masters[0]
        self.episode.set_intro_diary_gap(75, NOW, expected_revision=10)
        self.assertEqual((self.episode.speech_masters, self.episode.gap_samples), ((old_master,), 75))

    def test_INV_DE_7_episode_listening_is_append_only_actor_attributed_and_exact_master_bound(self) -> None:
        self.assemble()
        master = self.episode.speech_masters[0]
        actor = ActorId(uuid(523))
        first = self.episode.record_episode_listening(EpisodeListeningDecisionId(uuid(524)), master.master_id, actor, ListeningOutcome.PASSED, "fake episode pass", NOW, expected_revision=10)
        second = self.episode.record_episode_listening(EpisodeListeningDecisionId(uuid(525)), master.master_id, actor, ListeningOutcome.FAILED, "fake later issue", NOW, expected_revision=11)
        self.assertEqual(self.episode.listening_decisions, (first, second))

    def test_episode_unknown_attempt_reconciles_only_from_recorded_evidence_to_conservative_terminal(self) -> None:
        self.episode.reserve_episode_assembly(self.attempt_id, True, NOW, expected_revision=4)
        self.episode.finalize_episode_assembly_outcome(self.attempt_id, AttemptState.UNKNOWN, "fake ambiguous assembly", NOW, expected_revision=5)
        self.episode.reconcile_episode_assembly(self.attempt_id, AttemptState.QUARANTINED, "fake staged evidence mismatch", NOW, expected_revision=6)
        self.assertEqual((self.episode.revision, self.episode.assembly_attempts[0].state), (7, AttemptState.QUARANTINED))
        with self.assertRaises(DomainInvariantError):
            self.episode.reconcile_episode_assembly(self.attempt_id, AttemptState.FAILED, "cannot rewrite terminal", NOW, expected_revision=7)


if __name__ == "__main__":
    unittest.main()
