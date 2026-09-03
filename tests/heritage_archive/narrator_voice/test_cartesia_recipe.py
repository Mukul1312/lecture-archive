"""Fixture-only tests for the Narrator Voice Cartesia recipe compiler."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ContentDigest, ValidationError
from heritage_archive.contexts.narrator_voice.application.ports import (
    RecipeAuthoringRequest,
    RecipeCompileRequest,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    NarrationJobId,
    PassageId,
    PassageRenderRecipeId,
)
from heritage_archive.contexts.narrator_voice.domain.values import (
    BreakControl,
    ControlProvenance,
    EffectiveTakeSettings,
    FixedTwoDecimal,
    PassageText,
    ResolvedControl,
    SpeedControl,
    SpellingControl,
    TextSpan,
    VolumeControl,
)
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_recipe import (
    CartesiaRecipeCompiler,
)
from heritage_archive.platform.cartesia.markup import (
    CartesiaMarkupCapability,
    MarkupTagCapability,
)
from tests.heritage_archive.narrator_voice.fixtures import (
    make_authority,
    make_contract,
    make_settings,
    uuid,
)


CAPABILITY = CartesiaMarkupCapability(
    identity="cartesia-ssml-2026-09-03-or-test-v1",
    tags=(
        MarkupTagCapability("break", ("time",), False, False),
        MarkupTagCapability("speed", ("ratio",), True, False),
        MarkupTagCapability("volume", ("ratio",), True, False),
        MarkupTagCapability("spell", (), True, False),
    ),
)


class CartesiaRecipeCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = CartesiaRecipeCompiler(CAPABILITY)
        self.job_id = NarrationJobId(uuid(2101))
        self.passage_id = PassageId(uuid(2102))
        self.recipe_id = PassageRenderRecipeId(uuid(2103))
        self.contract = replace(
            make_contract(),
            provider="cartesia",
            model_snapshot="sonic-3.6-2026-08-27",
            api_schema="2026-08-14",
            capability_snapshot=CAPABILITY.identity,
        )
        self.authority = make_authority()

    def authoring_request(
        self,
        text: PassageText,
        *,
        controls: tuple[object, ...] = (),
        advanced_source: str | None = None,
        contract=None,
    ) -> RecipeAuthoringRequest:
        return RecipeAuthoringRequest(
            self.job_id,
            self.passage_id,
            1,
            text,
            self.recipe_id,
            1,
            controls,
            advanced_source,
            contract or self.contract,
        )

    def compile_request(
        self,
        text: PassageText,
        recipe,
        *,
        settings: EffectiveTakeSettings | None = None,
        contract=None,
    ) -> RecipeCompileRequest:
        return RecipeCompileRequest(
            self.job_id,
            1,
            text,
            recipe,
            settings or make_settings(),
            contract or self.contract,
            self.authority,
        )

    def test_plain_odia_preview_is_exact_deterministic_and_excludes_request_settings(self) -> None:
        """Settings or dictionary leakage would change reviewed provider transcript bytes."""
        text = PassageText("ଏହା ଏକ ସାଧାରଣ ପରୀକ୍ଷା ବାକ୍ୟ।")
        authored = self.compiler.compile_recipe(self.authoring_request(text))

        first = self.compiler.compile(self.compile_request(text, authored.recipe))
        second = self.compiler.compile(self.compile_request(text, authored.recipe))
        alternate_settings = EffectiveTakeSettings(
            ResolvedControl(ControlProvenance.EXPLICITLY_SET, "1.10"),
            ResolvedControl(ControlProvenance.EXPLICITLY_SET, "0.80"),
            ResolvedControl(ControlProvenance.EXPLICITLY_OMITTED, None),
            None,
            ControlProvenance.EXPLICITLY_OMITTED,
        )
        with_alternate_settings = self.compiler.compile(
            self.compile_request(text, authored.recipe, settings=alternate_settings)
        )

        expected_bytes = "ଏହା ଏକ ସାଧାରଣ ପରୀକ୍ଷା ବାକ୍ୟ।".encode("utf-8")
        self.assertEqual(authored.canonical_projection, text.value)
        self.assertEqual(authored.warnings, ())
        self.assertEqual(first.rendered_transcript.encode("utf-8"), expected_bytes)
        self.assertEqual(first, second)
        self.assertEqual(first, with_alternate_settings)
        self.assertEqual(first.compiler_version, "cartesia-odia-recipe-compiler-v1")
        self.assertEqual(first.endpoint, "https://api.cartesia.ai/tts/sse")
        self.assertEqual(first.canonical_projection, text.value)
        self.assertTrue(first.timestamps_requested)
        self.assertEqual(first.normalization, "off")
        self.assertEqual(
            first.billable_rule,
            "cartesia-rendered-unicode-scalars-2026-09-03",
        )
        self.assertEqual(first.billable_characters, len(first.rendered_transcript))
        self.assertEqual(first.estimated_usage.value, str(len(first.rendered_transcript)))
        self.assertEqual(
            ContentDigest.from_bytes(first.rendered_transcript.encode("utf-8")),
            ContentDigest.from_bytes(second.rendered_transcript.encode("utf-8")),
        )
        self.assertNotIn("calm", first.rendered_transcript)
        self.assertNotIn("fake-dictionary", first.rendered_transcript)

    def test_structured_and_advanced_authoring_produce_one_sorted_recipe_and_exact_markup(self) -> None:
        """Changing editor mode must not change the saved recipe or transmitted bytes."""
        text = PassageText("ଅଆଇଈଉ")
        structured_controls = (
            SpellingControl(TextSpan(3, 5), "ଈଉ"),
            VolumeControl(TextSpan(1, 3), FixedTwoDecimal("1.20")),
            BreakControl(1, 250),
            SpeedControl(TextSpan(0, 1), FixedTwoDecimal("0.90")),
        )
        advanced_source = (
            '<speed ratio="0.9">ଅ</speed><break time="0.25s"/>'
            '<volume ratio="1.2">ଆଇ</volume><spell>ଈଉ</spell>'
        )

        structured = self.compiler.compile_recipe(
            self.authoring_request(text, controls=structured_controls)
        )
        advanced = self.compiler.compile_recipe(
            self.authoring_request(text, advanced_source=advanced_source)
        )

        self.assertEqual(structured, advanced)
        self.assertEqual(
            tuple(type(control).__name__ for control in structured.recipe.controls),
            ("SpeedControl", "VolumeControl", "BreakControl", "SpellingControl"),
        )
        self.assertEqual(structured.recipe.digest, advanced.recipe.digest)
        structured_preview = self.compiler.compile(
            self.compile_request(text, structured.recipe)
        )
        advanced_preview = self.compiler.compile(
            self.compile_request(text, advanced.recipe)
        )
        expected = (
            '<speed ratio="0.90">ଅ</speed><break time="250ms"/>'
            '<volume ratio="1.20">ଆଇ</volume><spell>ଈଉ</spell>'
        )
        self.assertEqual(structured_preview, advanced_preview)
        self.assertEqual(structured_preview.rendered_transcript, expected)
        self.assertEqual(structured_preview.rendered_transcript.encode("utf-8"), expected.encode("utf-8"))

    def test_advanced_authoring_rejects_any_lexical_or_normalization_change(self) -> None:
        """Markup must not substitute punctuation/text that belongs in a passage revision."""
        text = PassageText("କାହାଣୀ।")
        changed_sources = (
            '<speed ratio="1.00">କାହାଣି।</speed>',
            '<speed ratio="1.00">କାହାଣୀ</speed>',
        )
        for source in changed_sources:
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValidationError, "exact canonical passage text"):
                    self.compiler.compile_recipe(
                        self.authoring_request(text, advanced_source=source)
                    )

        with self.assertRaises(ValidationError):
            self.compiler.compile_recipe(
                self.authoring_request(
                    PassageText("é"),
                    advanced_source='<spell>e\N{COMBINING ACUTE ACCENT}</spell>',
                )
            )

    def test_compiler_rejects_capability_mismatch_ranges_overlap_and_ambiguous_breaks(self) -> None:
        """Ignoring adapter-only constraints could render a different XML nesting or value."""
        text = PassageText("ଅଆଇଈଉ")
        invalid_controls = (
            (SpeedControl(TextSpan(0, 1), FixedTwoDecimal("0.59")),),
            (VolumeControl(TextSpan(0, 1), FixedTwoDecimal("2.01")),),
            (
                SpeedControl(TextSpan(0, 3), FixedTwoDecimal("1.00")),
                VolumeControl(TextSpan(2, 4), FixedTwoDecimal("1.00")),
            ),
            (
                SpeedControl(TextSpan(0, 3), FixedTwoDecimal("1.00")),
                BreakControl(1, 100),
            ),
            (BreakControl(1, 100), BreakControl(1, 200)),
            (SpellingControl(TextSpan(0, 2), "different"),),
        )
        for controls in invalid_controls:
            with self.subTest(controls=controls):
                with self.assertRaises(ValidationError):
                    self.compiler.compile_recipe(
                        self.authoring_request(text, controls=controls)
                    )

        many_breaks_text = PassageText("ଅ" * 20)
        with self.assertRaisesRegex(ValidationError, "at most 16"):
            self.compiler.compile_recipe(
                self.authoring_request(
                    many_breaks_text,
                    controls=tuple(BreakControl(index, 10) for index in range(17)),
                )
            )

        mismatched = replace(self.contract, capability_snapshot="different-capability")
        with self.assertRaisesRegex(ValidationError, "capability"):
            self.compiler.compile_recipe(
                self.authoring_request(text, contract=mismatched)
            )

    def test_rendered_transcript_has_the_same_exact_utf8_limit_as_frozen_input(self) -> None:
        """A structured recipe must not bypass the downstream 16,384-byte input bound."""
        text = PassageText("ଅ" * 5_462)
        recipe = self.compiler.compile_recipe(self.authoring_request(text)).recipe

        with self.assertRaisesRegex(ValidationError, "16,384"):
            self.compiler.compile(self.compile_request(text, recipe))

    def test_structured_rendering_rejects_xml_illegal_passage_scalars(self) -> None:
        """Domain-valid text must still be safe for the provider's XML transport grammar."""
        for illegal_scalar in ("\x00", "\ufffe"):
            with self.subTest(code_point=f"U+{ord(illegal_scalar):04X}"):
                text = PassageText(f"A{illegal_scalar}B")
                recipe = self.compiler.compile_recipe(self.authoring_request(text)).recipe

                with self.assertRaisesRegex(ValidationError, "XML 1.0"):
                    self.compiler.compile(self.compile_request(text, recipe))

    def test_structured_rendering_still_escapes_literal_ampersands(self) -> None:
        """Safe transport validation must not mistake passage ampersands for entity syntax."""
        text = PassageText("A & B")
        recipe = self.compiler.compile_recipe(self.authoring_request(text)).recipe

        preview = self.compiler.compile(self.compile_request(text, recipe))

        self.assertEqual(preview.rendered_transcript, "A &amp; B")


if __name__ == "__main__":
    unittest.main()
