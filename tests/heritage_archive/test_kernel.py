"""Consumer-facing characterization tests for the trimmed generic kernel."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import importlib
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import heritage_archive
from heritage_archive.kernel import (
    ActorId,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    TranscriptText,
    ValidationError,
    canonical_json,
    parse_strict_json,
    require_canonical_text,
    semantic_digest,
)


UUID = "123e4567-e89b-42d3-a456-426614174000"
PUBLIC_SYMBOLS = {
    "ActorId",
    "ArtifactId",
    "ArtifactRef",
    "ContentDigest",
    "JsonValue",
    "TranscriptText",
    "ValidationError",
    "canonical_json",
    "parse_strict_json",
    "require_canonical_text",
    "semantic_digest",
}


class PublicKernelTests(unittest.TestCase):
    def test_exact_trimmed_export_surface_is_importable(self) -> None:
        self.assertEqual(set(heritage_archive.kernel.__all__), PUBLIC_SYMBOLS)
        self.assertTrue(all(hasattr(heritage_archive.kernel, name) for name in PUBLIC_SYMBOLS))
        self.assertFalse(hasattr(heritage_archive, "ActorId"))
        self.assertFalse(hasattr(heritage_archive, "canonical_json"))
        self.assertFalse(hasattr(heritage_archive.kernel, "DomainError"))
        self.assertFalse(hasattr(heritage_archive.kernel, "ProductionId"))
        self.assertFalse(hasattr(heritage_archive.kernel, "AggregateEventRecorder"))
        for module in (
            "heritage_archive.kernel",
            "heritage_archive.kernel.canonical",
            "heritage_archive.kernel.digests",
            "heritage_archive.kernel.errors",
            "heritage_archive.kernel.ids",
            "heritage_archive.kernel.text",
            "heritage_archive.kernel.transcript",
        ):
            with self.subTest(module=module):
                self.assertIsNotNone(importlib.import_module(module))

    def test_canonical_text_requires_exact_nfc_utf8_lf_only_text(self) -> None:
        self.assertEqual(require_canonical_text("\u00e9", field="label", nonempty=True), "\u00e9")
        for value in ("", "e\u0301", "line\rbreak", "\ud800", b"bytes"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError):
                    require_canonical_text(value, field="label", nonempty=True)
        class StringSubclass(str):
            pass
        with self.assertRaises(ValidationError):
            require_canonical_text(StringSubclass("ok"), field="label")

    def test_strict_json_rejects_duplicate_float_and_surrogate_values(self) -> None:
        self.assertEqual(
            parse_strict_json(b'{"maximum":9007199254740991,"items":[null,true,"ok"]}'),
            {"maximum": 9_007_199_254_740_991, "items": [None, True, "ok"]},
        )
        for raw in (
            b'{"a":1,"a":2}', b'{"nested":{"a":1,"a":2}}', b"1.0", b"1e0",
            b"NaN", b"Infinity", b"-Infinity", b'"\\ud800"', b"\xef\xbb\xbf{}",
            b'"\xff"', b"9007199254740992",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    parse_strict_json(raw)
        class BytesSubclass(bytes):
            pass
        with self.assertRaises(ValidationError):
            parse_strict_json(BytesSubclass(b"{}"))

    def test_canonical_json_uses_utf16_key_order_and_never_accepts_float(self) -> None:
        self.assertEqual(
            canonical_json({"\U0001f600": 1, "\uffff": 2, "b": [None, True, False, -1], "a": "\u00e9"}),
            b'{"a":"\xc3\xa9","b":[null,true,false,-1],"\xf0\x9f\x98\x80":1,"\xef\xbf\xbf":2}',
        )
        for value in ({"fraction": 1.0}, {"bad": "e\u0301"}, {"bad": "\ud800"}):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError):
                    canonical_json(value)
        class IntegerSubclass(int):
            pass
        with self.assertRaises(ValidationError):
            canonical_json({"integer": IntegerSubclass(1)})

    def test_semantic_digest_is_domain_separated_and_rejects_top_level_self_digest(self) -> None:
        expected = hashlib.sha256(
            b'{"digest_schema":"example.v1","payload":{"value":1},"schema_version":1}'
        ).hexdigest()
        self.assertEqual(semantic_digest("example.v1", {"value": 1}), ContentDigest("sha256", expected))
        with self.assertRaises(ValidationError):
            semantic_digest("example.v1", {"digest": "0" * 64})
        self.assertIsInstance(semantic_digest("example.v1", {"nested": {"digest": "ok"}}), ContentDigest)
        class StringSubclass(str):
            pass
        with self.assertRaises(ValidationError):
            semantic_digest(StringSubclass("example.v1"), {"value": 1})

    def test_ids_are_frozen_exact_lowercase_uuid4_values(self) -> None:
        self.assertEqual(str(ActorId(UUID)), UUID)
        self.assertNotEqual(ActorId(UUID), ArtifactId(UUID))
        with self.assertRaises(FrozenInstanceError):
            ActorId(UUID).value = UUID  # type: ignore[misc]
        for invalid in (UUID.upper(), "123e4567-e89b-12d3-a456-426614174000", "123e4567-e89b-42d3-c456-426614174000", "bad"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    ActorId(invalid)
        class StringSubclass(str):
            pass
        with self.assertRaises(ValidationError):
            ArtifactId(StringSubclass(UUID))

    def test_digest_and_generic_artifact_reference_use_exact_typed_values(self) -> None:
        digest = ContentDigest.from_bytes(b"abc")
        self.assertEqual(digest.hex_digest, hashlib.sha256(b"abc").hexdigest())
        reference = ArtifactRef(ArtifactId(UUID), digest, 0, "audio/wav")
        self.assertEqual(reference.media_type, "audio/wav")
        for constructor in (
            lambda: ContentDigest("SHA256", "0" * 64),
            lambda: ContentDigest("sha256", "A" * 64),
            lambda: ArtifactRef(ArtifactId(UUID), digest, True, "audio/wav"),
            lambda: ArtifactRef(ArtifactId(UUID), digest, 1, "audio/wav; charset=utf-8"),
        ):
            with self.subTest(constructor=constructor):
                with self.assertRaises(ValidationError):
                    constructor()
        class DerivedArtifactId(ArtifactId):
            pass
        class DerivedDigest(ContentDigest):
            pass
        class StringSubclass(str):
            pass
        class IntegerSubclass(int):
            pass
        class BytesSubclass(bytes):
            pass
        with self.assertRaises(ValidationError):
            ArtifactRef(DerivedArtifactId(UUID), digest, 1, "audio/wav")
        with self.assertRaises(ValidationError):
            ArtifactRef(ArtifactId(UUID), DerivedDigest("sha256", "0" * 64), 1, "audio/wav")
        with self.assertRaises(ValidationError):
            ContentDigest(StringSubclass("sha256"), "0" * 64)
        with self.assertRaises(ValidationError):
            ContentDigest.from_bytes(BytesSubclass(b"abc"))
        with self.assertRaises(ValidationError):
            ArtifactRef(ArtifactId(UUID), digest, IntegerSubclass(1), "audio/wav")
        with self.assertRaises(ValidationError):
            ArtifactRef(ArtifactId(UUID), digest, 1, StringSubclass("audio/wav"))

    def test_transcript_text_counts_scalars_and_validates_half_open_slices(self) -> None:
        text = TranscriptText("A\U0001f9e1\u0915\u093f")
        self.assertEqual((len(text), text.length), (4, 4))
        self.assertEqual(text.slice(1, 2), TranscriptText("\U0001f9e1"))
        self.assertEqual(text.slice(4, 4), TranscriptText(""))
        for start, end in ((-1, 1), (2, 1), (0, 5), (True, 1)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValidationError):
                    text.slice(start, end)  # type: ignore[arg-type]
        class IntegerSubclass(int):
            pass
        class StringSubclass(str):
            pass
        with self.assertRaises(ValidationError):
            text.slice(IntegerSubclass(0), 1)
        with self.assertRaises(ValidationError):
            TranscriptText(StringSubclass("text"))
