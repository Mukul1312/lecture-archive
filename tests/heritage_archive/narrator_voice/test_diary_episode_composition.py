"""DiaryEpisode component and configuration invariant tests."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.application.schema_v1 import decode_schema_v1, encode_schema_v1
from heritage_archive.contexts.narrator_voice.domain.diary_episode import (
    DiaryEpisode,
    DiaryEpisodeSnapshot,
    EpisodeStatus,
)
from heritage_archive.contexts.narrator_voice.domain.errors import DomainInvariantError
from heritage_archive.contexts.narrator_voice.domain.ids import DiaryEpisodeId
from heritage_archive.contexts.narrator_voice.domain.values import ComponentRole, Lane
from tests.heritage_archive.narrator_voice.fixtures import NOW, make_master_snapshot, uuid


class DiaryEpisodeCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.episode_id = DiaryEpisodeId(uuid(400))
        self.episode = DiaryEpisode.prepare(self.episode_id, NOW)
        self.intro = make_master_snapshot(lane=Lane.C, episode_id=self.episode_id, index=401, samples=100)
        self.diary = make_master_snapshot(lane=Lane.B, episode_id=None, index=410, samples=200)

    def test_INV_DE_1_episode_is_draft_until_exactly_one_intro_then_diary_and_explicit_gap_are_configured(self) -> None:
        self.assertEqual(self.episode.status, EpisodeStatus.DRAFT)
        with self.assertRaises(DomainInvariantError):
            self.episode.reserve_assembly_preview(expected_revision=1)
        self.episode.attach_intro(self.intro, NOW, expected_revision=1)
        self.assertEqual((self.episode.status, tuple(value.role for value in self.episode.components)), (EpisodeStatus.DRAFT, (ComponentRole.INTRO,)))
        self.episode.attach_diary(self.diary, NOW, expected_revision=2)
        self.assertEqual(self.episode.status, EpisodeStatus.DRAFT)
        self.episode.set_intro_diary_gap(50, NOW, expected_revision=3)
        self.assertEqual((self.episode.status, tuple(value.role for value in self.episode.components)), (EpisodeStatus.CONFIGURED, (ComponentRole.INTRO, ComponentRole.DIARY)))

    def test_INV_DE_2_components_accept_only_root_issued_role_eligible_snapshots_and_lane_c_episode_binding(self) -> None:
        wrong_episode = make_master_snapshot(lane=Lane.C, episode_id=DiaryEpisodeId(uuid(420)), index=421, samples=100)
        with self.assertRaises(ValidationError):
            self.episode.attach_intro(wrong_episode, NOW, expected_revision=1)
        with self.assertRaises(ValidationError):
            self.episode.attach_intro(self.diary, NOW, expected_revision=1)
        self.episode.attach_intro(self.intro, NOW, expected_revision=1)
        with self.assertRaises(ValidationError):
            self.episode.attach_intro(self.intro, NOW, expected_revision=2)

    def test_INV_DE_6_component_and_gap_changes_preserve_history_and_increment_revision(self) -> None:
        self.episode.attach_intro(self.intro, NOW, expected_revision=1)
        replacement = make_master_snapshot(lane=Lane.C, episode_id=self.episode_id, index=430, samples=110)
        self.episode.attach_intro(replacement, NOW, expected_revision=2)
        self.episode.attach_diary(self.diary, NOW, expected_revision=3)
        self.episode.set_intro_diary_gap(50, NOW, expected_revision=4)
        self.episode.set_intro_diary_gap(75, NOW, expected_revision=5)
        self.assertEqual(self.episode.revision, 6)
        self.assertEqual(tuple(value.snapshot.snapshot_digest for value in self.episode.component_history if value.role is ComponentRole.INTRO), (self.intro.snapshot_digest, replacement.snapshot_digest))
        self.assertEqual(tuple(value.gap_samples for value in self.episode.gap_history), (50, 75))

    def test_INV_DE_10_snapshot_has_no_background_subtitle_video_or_presentation_children(self) -> None:
        fields = set(DiaryEpisodeSnapshot.__dataclass_fields__)
        self.assertFalse(fields & {"background", "music", "subtitle", "video", "presentation", "publishing"})

    def test_schema_v1_round_trip_preserves_component_and_gap_histories(self) -> None:
        self.episode.attach_intro(self.intro, NOW, expected_revision=1)
        self.episode.attach_diary(self.diary, NOW, expected_revision=2)
        self.episode.set_intro_diary_gap(50, NOW, expected_revision=3)
        raw = encode_schema_v1(self.episode.to_snapshot())
        restored = DiaryEpisode.from_snapshot(decode_schema_v1(raw, DiaryEpisodeSnapshot))
        self.assertEqual(restored.to_snapshot(), self.episode.to_snapshot())
        self.assertEqual(encode_schema_v1(restored.to_snapshot()), raw)


if __name__ == "__main__":
    unittest.main()
