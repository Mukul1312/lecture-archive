from __future__ import annotations

from decimal import Decimal
import unittest

from hypothesis import given, strategies as st
import rfc8785

from heritage_production.domain.shared import (
    ValidationError,
    canonical_json,
    parse_strict_json,
    semantic_digest,
)


SAFE_MAX = 9_007_199_254_740_991


class StrictJsonParsingTests(unittest.TestCase):
    def test_parses_supported_json_and_safe_integer_boundaries(self) -> None:
        self.assertEqual(
            parse_strict_json(
                b'{"maximum":9007199254740991,"minimum":-9007199254740991,'
                b'"values":[null,true,false,"text"]}'
            ),
            {
                "maximum": SAFE_MAX,
                "minimum": -SAFE_MAX,
                "values": [None, True, False, "text"],
            },
        )

    def test_rejects_duplicate_keys_at_any_depth(self) -> None:
        for raw in (b'{"a":1,"a":2}', b'{"outer":{"x":1,"x":2}}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    parse_strict_json(raw)

    def test_rejects_float_constants_bom_invalid_utf8_and_unsafe_integers(self) -> None:
        invalid_documents = (
            b"1.0",
            b"1e0",
            b"NaN",
            b"Infinity",
            b"-Infinity",
            b"9007199254740992",
            b"-9007199254740992",
            b"\xef\xbb\xbf{}",
            b'"\xff"',
        )
        for raw in invalid_documents:
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    parse_strict_json(raw)

    def test_rejects_noncanonical_strings_in_keys_and_values(self) -> None:
        invalid_documents = (
            b'"e\\u0301"',
            b'{"e\\u0301":1}',
            b'"line\\rbreak"',
            b'"\\ud800"',
        )
        for raw in invalid_documents:
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    parse_strict_json(raw)


class CanonicalJsonEncodingTests(unittest.TestCase):
    def test_emits_hand_derived_compact_unicode_and_control_escaping(self) -> None:
        self.assertEqual(
            canonical_json({"b": [None, True, False, -1], "a": "é"}),
            '{"a":"é","b":[null,true,false,-1]}'.encode("utf-8"),
        )
        self.assertEqual(
            canonical_json("\b\t\n\f\u0000\u001f\"\\/"),
            b'"\\b\\t\\n\\f\\u0000\\u001f\\"\\\\/"',
        )

    def test_supplementary_plane_key_proves_utf16_code_unit_order(self) -> None:
        self.assertEqual(
            canonical_json({"\ue000": 2, "😀": 1}),
            '{"😀":1,"\ue000":2}'.encode("utf-8"),
        )

    def test_rejects_every_value_outside_the_supported_subset(self) -> None:
        invalid_values = (
            1.0,
            float("nan"),
            Decimal("1"),
            SAFE_MAX + 1,
            {1: "non-string-key"},
            (1, 2),
            {1, 2},
            b"bytes",
            "e\u0301",
            "line\rbreak",
            "\udfff",
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError):
                    canonical_json(value)  # type: ignore[arg-type]


_CANONICAL_CHARACTERS = list('abcXYZ019é漢😀\n\t\b\f\u0000\u001f"\\/')
_CANONICAL_TEXT = st.text(alphabet=_CANONICAL_CHARACTERS, max_size=5)
_JSON_VALUES = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(-SAFE_MAX, SAFE_MAX), _CANONICAL_TEXT),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(_CANONICAL_TEXT, children, max_size=3),
    ),
    max_leaves=10,
)


class CanonicalJsonOracleTests(unittest.TestCase):
    @given(_JSON_VALUES)
    def test_supported_subset_matches_rfc8785_oracle(self, value: object) -> None:
        self.assertEqual(canonical_json(value), rfc8785.dumps(value))  # type: ignore[arg-type]


class SemanticDigestTests(unittest.TestCase):
    def test_uses_exact_domain_separation_envelope_and_literal_digest(self) -> None:
        digest = semantic_digest("example-v1", {"x": 1})
        self.assertEqual(digest.algorithm, "sha256")
        self.assertEqual(
            digest.hex_digest,
            "13a9cece9795efbead7863ef9cea6f6c16f7304a895a4db6c22bd11de07833e8",
        )
        self.assertNotEqual(
            semantic_digest("other-v1", {"x": 1}),
            digest,
        )

    def test_rejects_self_digest_only_at_top_level_and_accepts_specific_refs(self) -> None:
        for payload in ({"digest": "x"}, {"semantic_digest": "x"}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    semantic_digest("example-v1", payload)

        semantic_digest(
            "example-v1",
            {"artifact_digest": "x", "nested": {"digest": "referenced"}},
        )
        for label in ("", "e\u0301", "line\rbreak"):
            with self.subTest(label=repr(label)):
                with self.assertRaises(ValidationError):
                    semantic_digest(label, {})
