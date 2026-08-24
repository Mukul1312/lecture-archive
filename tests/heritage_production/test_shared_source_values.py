from __future__ import annotations

import unittest

from heritage_production.domain.shared import (
    ContentDigest,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptScope,
    TranscriptText,
    ValidationError,
)


SOURCE_RECORDING_ID = SourceRecordingId("123e4567-e89b-42d3-a456-426614174000")
SOURCE_VERSION_ID_1 = SourceVersionId("123e4567-e89b-42d3-a456-426614174001")
SOURCE_VERSION_ID_2 = SourceVersionId("123e4567-e89b-42d3-a456-426614174002")
DIGEST = ContentDigest("sha256", "1" * 64)


def source_version(identifier: SourceVersionId, duration_us: int = 10) -> SourceVersionRef:
    return SourceVersionRef(
        identifier,
        SOURCE_RECORDING_ID,
        DIGEST,
        duration_us,
        "container-timescale=1000000",
    )


class TranscriptTextTests(unittest.TestCase):
    def test_rejects_non_nfc_cr_lone_surrogate_and_non_string_values(self) -> None:
        for value in ("e\u0301", "line\r\n", "\ud800", b"bytes"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError):
                    TranscriptText(value)  # type: ignore[arg-type]

    def test_scalar_length_and_checked_half_open_slicing_cover_emoji_and_marks(self) -> None:
        text = TranscriptText("A🧡कि")
        self.assertEqual(len(text), 4)
        self.assertEqual(text.length, 4)
        self.assertEqual(text.slice(1, 2), TranscriptText("🧡"))
        self.assertEqual(text.slice(2, 4), TranscriptText("कि"))
        self.assertEqual(text.slice(4, 4), TranscriptText(""))

        for start, end in ((-1, 1), (2, 1), (0, 5), (True, 1)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValidationError):
                    text.slice(start, end)  # type: ignore[arg-type]


class SourceSpanTests(unittest.TestCase):
    def test_source_version_requires_exact_types_positive_duration_and_time_base(self) -> None:
        valid = source_version(SOURCE_VERSION_ID_1)
        self.assertEqual(valid.duration_us, 10)
        for duration, evidence in ((0, "evidence"), (-1, "evidence"), (True, "evidence"), (1, "")):
            with self.subTest(duration=duration, evidence=evidence):
                with self.assertRaises(ValidationError):
                    SourceVersionRef(
                        SOURCE_VERSION_ID_1,
                        SOURCE_RECORDING_ID,
                        DIGEST,
                        duration,  # type: ignore[arg-type]
                        evidence,
                    )

    def test_source_version_rejects_subclasses_of_typed_identity(self) -> None:
        class DerivedSourceVersionId(SourceVersionId):
            pass

        with self.assertRaises(ValidationError):
            SourceVersionRef(
                DerivedSourceVersionId(SOURCE_VERSION_ID_1.value),
                SOURCE_RECORDING_ID,
                DIGEST,
                10,
                "evidence",
            )

    def test_half_open_spans_allow_adjacency_and_reject_empty_or_out_of_bounds(self) -> None:
        version = source_version(SOURCE_VERSION_ID_1)
        first = SourceSpan(version, 0, 5)
        second = SourceSpan(version, 5, 10)
        self.assertEqual((first.end_us, second.start_us), (5, 5))

        for start, end in ((-1, 1), (0, 0), (7, 6), (0, 11), (False, 1)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValidationError):
                    SourceSpan(version, start, end)  # type: ignore[arg-type]


class TranscriptScopeTests(unittest.TestCase):
    def test_scope_accepts_ordered_adjacent_spans_from_declared_versions(self) -> None:
        first_version = source_version(SOURCE_VERSION_ID_1)
        second_version = source_version(SOURCE_VERSION_ID_2)
        scope = TranscriptScope(
            (first_version, second_version),
            (
                SourceSpan(first_version, 0, 5),
                SourceSpan(first_version, 5, 10),
                SourceSpan(second_version, 0, 4),
            ),
            (SourceSpan(second_version, 4, 10),),
        )
        self.assertEqual(len(scope.required_spans), 3)

    def test_scope_rejects_overlap_noncanonical_order_and_undeclared_sources(self) -> None:
        first_version = source_version(SOURCE_VERSION_ID_1)
        second_version = source_version(SOURCE_VERSION_ID_2)
        cases = (
            ((SourceSpan(first_version, 0, 6), SourceSpan(first_version, 5, 10)), ()),
            ((SourceSpan(first_version, 5, 10), SourceSpan(first_version, 0, 5)), ()),
            ((SourceSpan(second_version, 0, 1),), ()),
            ((), (SourceSpan(first_version, 0, 6), SourceSpan(first_version, 5, 10))),
        )
        for required, gaps in cases:
            with self.subTest(required=required, gaps=gaps):
                with self.assertRaises(ValidationError):
                    TranscriptScope((first_version,), required, gaps)

    def test_scope_requires_immutable_collections_and_unique_declared_versions(self) -> None:
        version = source_version(SOURCE_VERSION_ID_1)
        with self.assertRaises(ValidationError):
            TranscriptScope([version], (), ())  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            TranscriptScope((version, version), (), ())
