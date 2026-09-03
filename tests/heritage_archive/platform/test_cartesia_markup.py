"""Focused fixture-only tests for safe Cartesia markup parsing."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ValidationError
from heritage_archive.platform.cartesia.markup import (
    CartesiaMarkupCapability,
    MarkupTagCapability,
    ParsedMarkupAnnotation,
    parse_safe_markup_fragment,
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


class CartesiaMarkupParserTests(unittest.TestCase):
    def test_projection_and_annotations_use_exact_unicode_scalar_offsets(self) -> None:
        """Counting UTF-8 bytes or UTF-16 units would misplace controls after emoji/Odia."""
        parsed = parse_safe_markup_fragment(
            'ଅ😀<speed ratio="0.9">କା</speed><break time="0.25s"/>'
            '<volume ratio="2">ଖ</volume><spell>AB</spell>',
            CAPABILITY,
        )

        self.assertEqual(parsed.canonical_projection, "ଅ😀କାଖAB")
        self.assertEqual(
            parsed.annotations,
            (
                ParsedMarkupAnnotation("speed", 2, 4, "0.90"),
                ParsedMarkupAnnotation("break", 4, 4, "250"),
                ParsedMarkupAnnotation("volume", 4, 5, "2.00"),
                ParsedMarkupAnnotation("spelling", 5, 7, "AB"),
            ),
        )

    def test_rejects_declarations_dtd_entities_comments_and_processing_instructions(self) -> None:
        """Parser-discarded nodes or entity expansion must never hide changed lexical input."""
        dangerous_sources = (
            '<?xml version="1.0"?>ଅ',
            '<!DOCTYPE x [<!ENTITY hidden "ଖ">]><speed ratio="1.0">&hidden;</speed>',
            "ଅ&amp;ଆ",
            "ଅ<!-- hidden -->ଆ",
            "ଅ<?hidden value?>ଆ",
            "<![CDATA[ଅ]]>",
        )

        for source in dangerous_sources:
            with self.subTest(source=source):
                with self.assertRaises(ValidationError):
                    parse_safe_markup_fragment(source, CAPABILITY)

    def test_rejects_unknown_syntax_attributes_nesting_and_invalid_numeric_values(self) -> None:
        """Relaxing any allowlist branch could turn unreviewed markup into provider input."""
        invalid_sources = (
            "<unknown>ଅ</unknown>",
            '<emotion value="calm">ଅ</emotion>',
            '<speed ratio="1.00" style="hidden">ଅ</speed>',
            '<speed ratio="1.00">ଅ<spell>ଆ</spell></speed>',
            '<speed ratio="1.51">ଅ</speed>',
            '<speed ratio="nan">ଅ</speed>',
            '<volume ratio="0.49">ଅ</volume>',
            '<break time="9ms"/>ଅ',
            '<break time="5.001s"/>ଅ',
            '<break time="10.5ms"/>ଅ',
            '<break time="250ms">ଅ</break>',
            "<spell></spell>ଅ",
        )

        for source in invalid_sources:
            with self.subTest(source=source):
                with self.assertRaises(ValidationError):
                    parse_safe_markup_fragment(source, CAPABILITY)

    def test_advanced_source_has_an_exact_16384_utf8_byte_limit(self) -> None:
        """Removing the byte check would allow an oversized XML parse before domain validation."""
        at_limit = "x" * 16_384
        over_limit = at_limit + "x"

        self.assertEqual(
            parse_safe_markup_fragment(at_limit, CAPABILITY).canonical_projection,
            at_limit,
        )
        with self.assertRaisesRegex(ValidationError, "16,384"):
            parse_safe_markup_fragment(over_limit, CAPABILITY)


if __name__ == "__main__":
    unittest.main()
