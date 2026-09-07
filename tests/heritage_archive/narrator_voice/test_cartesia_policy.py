"""Fixture-only lane policy and strict private profile contracts."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.domain.ids import AuthorizationRecordId, DiaryEpisodeId
from heritage_archive.contexts.narrator_voice.domain.values import FixedTwoDecimal, Lane
from heritage_archive.contexts.narrator_voice.infrastructure.operations import LocalStudioVoiceProfile
from tests.heritage_archive.narrator_voice.fixtures import make_dictionary, uuid


def profile(lane=Lane.B):
    return LocalStudioVoiceProfile(
        "Fixture narrator", f"fake-speaker-{lane.value}", f"opaque-fake-voice-{lane.value}",
        make_dictionary(lane.value), f"fake-voice-{lane.value}",
        AuthorizationRecordId(uuid(3 if lane is Lane.B else 4)),
        FixedTwoDecimal("0.90" if lane is Lane.B else "1.10"),
        FixedTwoDecimal("1.00"), "calm" if lane is Lane.B else None,
    )


class CartesiaPolicyTests(unittest.TestCase):
    def test_resolves_fixed_lane_contracts_and_explicit_lane_c_defaults(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_policy import ConfiguredNarrationReleasePolicyResolver
        resolver = ConfiguredNarrationReleasePolicyResolver(profile(), profile(Lane.C))
        diary = resolver.resolve_lane_b_diary()
        intro = resolver.resolve_lane_c_intro(DiaryEpisodeId(uuid(2)))
        self.assertEqual(diary.contract.provider, "cartesia")
        self.assertEqual(diary.contract.model_snapshot, "sonic-3.6-2026-08-27")
        self.assertEqual(diary.contract.api_schema, "2026-08-14")
        self.assertEqual(diary.contract.capability_snapshot, "cartesia-ssml-2026-09-03-or-v1")
        self.assertEqual(diary.contract.voice_binding, "fake-voice-lane_b")
        self.assertEqual(diary.contract.purpose, "reviewed-odia-diary")
        self.assertIsNone(diary.contract.intended_episode_id)
        self.assertEqual(diary.initial_defaults.speed.value, "0.90")
        self.assertEqual(diary.initial_defaults.emotion, "calm")
        self.assertEqual(intro.contract.intended_episode_id, DiaryEpisodeId(uuid(2)))
        self.assertEqual(intro.contract.purpose, "reviewed-odia-diary-intro")
        self.assertEqual(intro.initial_defaults.speed.value, "1.10")
        self.assertIsNone(intro.initial_defaults.emotion)
        self.assertNotEqual(diary.contract.voice_binding, intro.contract.voice_binding)
        with self.assertRaises(ValidationError):
            resolver.resolve_lane_c_intro(None)
        with self.assertRaises(TypeError):
            resolver.resolve_lane_b_diary(DiaryEpisodeId(uuid(2)))

    def test_rejects_lane_b_starting_defaults_and_reused_voice_identity(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_policy import ConfiguredNarrationReleasePolicyResolver
        with self.assertRaises(ValidationError):
            ConfiguredNarrationReleasePolicyResolver(replace(profile(), initial_speed=FixedTwoDecimal("1.10")), profile(Lane.C))
        with self.assertRaises(ValidationError):
            ConfiguredNarrationReleasePolicyResolver(profile(), replace(profile(Lane.C), voice_binding=profile().voice_binding))
