"""Domain value contracts for Narrator Voice Plan 2."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ContentDigest, ValidationError
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AuthorizationRecordId,
    DiaryEpisodeId,
    NarrationJobId,
    PassageId,
    PassageRenderRecipeId,
)
from heritage_archive.contexts.narrator_voice.domain.values import (
    AuthorityOperation,
    AuthorityScope,
    BreakControl,
    CanonicalAudioFacts,
    ControlProvenance,
    DeliveryControlDefaults,
    DictionaryBinding,
    EffectiveSynthesisInput,
    EffectiveTakeSettings,
    FixedTwoDecimal,
    Lane,
    NonNegativeDecimal,
    PassageRenderRecipe,
    PassageText,
    ReleaseSynthesisContract,
    ResolvedControl,
    SafeRelativeArtifactPath,
    SpeedControl,
    SpellingControl,
    TextSpan,
    VolumeControl,
)


UUIDS = [f"123e4567-e89b-42d3-a456-4266141740{n:02d}" for n in range(40)]
NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


class IdentifierAndTextTests(unittest.TestCase):
    def test_narrator_ids_are_exact_frozen_nominal_uuid4_values(self) -> None:
        job_id = NarrationJobId(UUIDS[0])
        self.assertEqual(str(job_id), UUIDS[0])
        self.assertNotEqual(job_id, DiaryEpisodeId(UUIDS[0]))
        with self.assertRaises(FrozenInstanceError):
            job_id.value = UUIDS[1]  # type: ignore[misc]
        for invalid in (UUIDS[0].upper(), "bad", True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    NarrationJobId(invalid)  # type: ignore[arg-type]

    def test_passage_text_is_exact_nfc_markup_free_and_bounded_to_8000_scalars(self) -> None:
        text = PassageText("ଓଡ଼ିଆ 🧡")
        self.assertEqual(text.scalar_length, 7)
        self.assertEqual(text.digest, ContentDigest.from_bytes(text.value.encode("utf-8")))
        for invalid in ("", "e\u0301", "<break time='1s'/>", "ଅ" * 8001):
            with self.subTest(length=len(invalid)):
                with self.assertRaises(ValidationError):
                    PassageText(invalid)


class DecimalAndSettingsTests(unittest.TestCase):
    def test_request_controls_require_unsigned_canonical_fixed_two_decimal_strings(self) -> None:
        self.assertEqual(FixedTwoDecimal("0.90").value, "0.90")
        self.assertEqual(FixedTwoDecimal("10.00").value, "10.00")
        for invalid in (".90", "00.90", "1", "1.0", "+1.00", "-0.10", "1e0", " 1.00", 1.0, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    FixedTwoDecimal(invalid)  # type: ignore[arg-type]

    def test_usage_money_decimal_has_independent_canonical_nonnegative_grammar(self) -> None:
        self.assertEqual(NonNegativeDecimal("0").value, "0")
        self.assertEqual(NonNegativeDecimal("12.25").value, "12.25")
        for invalid in ("0.0", "1.20", "01", "-1", "+1", "1e2", 1.25, False):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    NonNegativeDecimal(invalid)  # type: ignore[arg-type]

    def test_effective_settings_preserve_inherited_set_and_omitted_provenance(self) -> None:
        dictionary = DictionaryBinding("dictionary-binding", ContentDigest.from_bytes(b"dict"), "rev-a", "cap-a")
        settings = EffectiveTakeSettings(
            speed=ResolvedControl(ControlProvenance.INHERITED, "0.90"),
            volume=ResolvedControl(ControlProvenance.EXPLICITLY_SET, "1.00"),
            emotion=ResolvedControl(ControlProvenance.EXPLICITLY_OMITTED, None),
            dictionary=dictionary,
            dictionary_provenance=ControlProvenance.INHERITED,
        )
        self.assertEqual(settings.emotion.provenance, ControlProvenance.EXPLICITLY_OMITTED)
        with self.assertRaises(ValidationError):
            ResolvedControl(ControlProvenance.EXPLICITLY_OMITTED, "calm")
        with self.assertRaises(ValidationError):
            ResolvedControl(ControlProvenance.INHERITED, None)


class RecipeTests(unittest.TestCase):
    def make_recipe(self, text: PassageText, controls: tuple[object, ...]) -> PassageRenderRecipe:
        return PassageRenderRecipe(
            recipe_id=PassageRenderRecipeId(UUIDS[4]),
            revision=1,
            text_revision=1,
            text_digest=text.digest,
            compiler_version="fake-compiler-v1",
            controls=controls,
        )

    def test_recipe_uses_scalar_half_open_spans_and_deterministic_control_order(self) -> None:
        text = PassageText("ଅଆଇଈ")
        recipe = self.make_recipe(
            text,
            (
                SpellingControl(TextSpan(2, 4), "fake-spelling"),
                BreakControl(1, 250),
                VolumeControl(TextSpan(0, 2), FixedTwoDecimal("1.00")),
                SpeedControl(TextSpan(2, 4), FixedTwoDecimal("0.90")),
            ),
        )
        recipe.validate_for(text)
        self.assertEqual(
            tuple(type(control).__name__ for control in recipe.controls),
            ("VolumeControl", "BreakControl", "SpeedControl", "SpellingControl"),
        )

    def test_recipe_enforces_control_limits_ranges_overlap_and_spell_nesting(self) -> None:
        text = PassageText("ଅ" * 100)
        invalid_controls = (
            lambda: tuple(BreakControl(i, 10) for i in range(17)),
            lambda: (BreakControl(0, 9),),
            lambda: tuple(BreakControl(i, 1500) for i in range(14)),
            lambda: (SpeedControl(TextSpan(0, 2), FixedTwoDecimal("0.90")), SpeedControl(TextSpan(1, 3), FixedTwoDecimal("1.00"))),
            lambda: (SpellingControl(TextSpan(0, 65), "too-long"),),
            lambda: (SpellingControl(TextSpan(0, 10), "outer"), SpellingControl(TextSpan(2, 5), "inner")),
            lambda: (VolumeControl(TextSpan(99, 101), FixedTwoDecimal("1.00")),),
        )
        for make_controls in invalid_controls:
            with self.subTest(make_controls=make_controls):
                with self.assertRaises(ValidationError):
                    self.make_recipe(text, make_controls()).validate_for(text)


class ContractAndEffectiveInputTests(unittest.TestCase):
    def make_scope(self, episode_id: DiaryEpisodeId | None) -> AuthorityScope:
        return AuthorityScope(
            speaker_binding="speaker-binding",
            voice_binding="voice-binding",
            language="or",
            purpose="reviewed-odia-diary-intro" if episode_id else "reviewed-odia-diary",
            intended_episode_id=episode_id,
            operations=frozenset({AuthorityOperation.GENERATE, AuthorityOperation.ASSEMBLE, AuthorityOperation.DELIVER}),
            valid_from=NOW,
            valid_until=datetime(2027, 9, 2, tzinfo=timezone.utc),
        )

    def test_lane_contracts_are_fixed_mono_pcm16_wav_and_lane_c_is_episode_bound(self) -> None:
        audio = CanonicalAudioFacts()
        self.assertEqual((audio.container, audio.encoding, audio.channels, audio.sample_rate_hz), ("wav", "pcm_s16le", 1, 44100))
        episode_id = DiaryEpisodeId(UUIDS[2])
        lane_c = ReleaseSynthesisContract(
            lane=Lane.C,
            purpose="reviewed-odia-diary-intro",
            speaker_binding="speaker-binding",
            voice_binding="voice-binding",
            provider="fake-provider",
            opaque_provider_voice_ref="opaque-intro-voice",
            language="or",
            model_snapshot="fake-model-2026-09-02",
            api_schema="fake-api-v1",
            capability_snapshot="fake-capability-v1",
            authority_record_id=AuthorizationRecordId(UUIDS[3]),
            audio=audio,
            permitted_role="intro",
            intended_episode_id=episode_id,
        )
        self.assertEqual(lane_c.intended_episode_id, episode_id)
        with self.assertRaises(ValidationError):
            replace(lane_c, intended_episode_id=None)

    def test_effective_input_freezes_exact_utf8_bytes_and_all_constituent_digests(self) -> None:
        text = PassageText("ଅଆ")
        episode_id = DiaryEpisodeId(UUIDS[2])
        scope = self.make_scope(episode_id)
        dictionary = DictionaryBinding("dictionary-binding", ContentDigest.from_bytes(b"dict"), "rev-a", "cap-a")
        settings = EffectiveTakeSettings(
            ResolvedControl(ControlProvenance.INHERITED, "0.90"),
            ResolvedControl(ControlProvenance.INHERITED, "1.00"),
            ResolvedControl(ControlProvenance.EXPLICITLY_OMITTED, None),
            dictionary,
            ControlProvenance.EXPLICITLY_SET,
        )
        contract_digest = ContentDigest.from_bytes(b"contract")
        recipe_digest = ContentDigest.from_bytes(b"recipe")
        rendered = "<fake>ଅଆ</fake>"
        effective = EffectiveSynthesisInput.create(
            job_id=NarrationJobId(UUIDS[0]),
            lane=Lane.C,
            passage_id=PassageId(UUIDS[1]),
            text_revision=1,
            text=text,
            recipe_id=PassageRenderRecipeId(UUIDS[4]),
            recipe_revision=1,
            recipe_digest=recipe_digest,
            compiler_version="fake-compiler-v1",
            settings=settings,
            contract_digest=contract_digest,
            authority_scope=scope,
            authority_revision=1,
            authority_digest=ContentDigest.from_bytes(b"authority"),
            authority_observed_at=NOW,
            endpoint="fake://no-network",
            api_schema="fake-api-v1",
            capability_snapshot="fake-capability-v1",
            rendered_transcript=rendered,
            canonical_projection=text.value,
            timestamps_requested=True,
            normalization="off",
            output_audio=CanonicalAudioFacts(),
            billable_rule="fake-rule-v1",
            billable_characters=15,
        )
        self.assertEqual(effective.rendered_transcript_bytes, rendered.encode("utf-8"))
        self.assertEqual(effective.rendered_transcript_digest, ContentDigest.from_bytes(rendered.encode("utf-8")))
        self.assertEqual(effective.canonical_projection_digest, text.digest)
        self.assertIsInstance(effective.request_digest, ContentDigest)
        with self.assertRaises(ValidationError):
            EffectiveSynthesisInput.create(
                **{**effective.creation_arguments(), "canonical_projection": "ଅ"}
            )

        with self.assertRaises(ValidationError):
            replace(effective, request_digest=ContentDigest.from_bytes(b"forged-request"))

        with self.assertRaises(ValidationError):
            EffectiveSynthesisInput.create(
                **{
                    **effective.creation_arguments(),
                    "authority_scope": self.make_scope(None),
                }
            )

    def test_safe_relative_artifact_paths_reject_controls_and_nonportable_segments(self) -> None:
        self.assertEqual(SafeRelativeArtifactPath("fake/sub-dir/a_b-1.2.wav").value, "fake/sub-dir/a_b-1.2.wav")
        for invalid in (
            "fake/control\n.wav",
            "fake/control\x00.wav",
            "fake/trailing. ",
            "fake/NUL.wav",
            f"fake/{'a' * 256}.wav",
        ):
            with self.subTest(invalid=invalid[:40]):
                with self.assertRaises(ValidationError):
                    SafeRelativeArtifactPath(invalid)


if __name__ == "__main__":
    unittest.main()
