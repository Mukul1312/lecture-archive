from __future__ import annotations

from decimal import Decimal
import unittest

from heritage_production.domain.shared import (
    ActorId,
    ActorRef,
    AggregateEventRecorder,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    DecimalTimeConversion,
    DomainEvent,
    DomainEventId,
    PolicyEvaluatorRef,
    ProductionId,
    RubricId,
    RubricRef,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptScope,
    TranscriptText,
    ValidationError,
    decimal_seconds_to_microseconds,
    parse_strict_json,
)


class MutableString(str):
    pass


class MutableInteger(int):
    pass


class MutableBytes(bytes):
    pass


class MutableTuple(tuple):
    pass


class MutableDecimal(Decimal):
    pass


UUID = "123e4567-e89b-42d3-a456-426614174000"
DIGEST = ContentDigest("sha256", "0" * 64)
SOURCE_VERSION = SourceVersionRef(
    SourceVersionId(UUID),
    SourceRecordingId(UUID),
    DIGEST,
    10,
    "evidence",
)


class ExactBuiltinRepresentationTests(unittest.TestCase):
    def test_ids_reject_string_subclasses(self) -> None:
        for identifier_type in (ProductionId, SourceVersionId, ActorId, DomainEventId):
            with self.subTest(identifier_type=identifier_type.__name__):
                with self.assertRaises(ValidationError):
                    identifier_type(MutableString(UUID))

    def test_text_digest_bytes_and_artifact_fields_reject_subclasses(self) -> None:
        invalid_calls = (
            lambda: TranscriptText(MutableString("text")),
            lambda: ContentDigest(MutableString("sha256"), "0" * 64),
            lambda: ContentDigest("sha256", MutableString("0" * 64)),
            lambda: ContentDigest.from_bytes(MutableBytes(b"abc")),
            lambda: ArtifactRef(ArtifactId(UUID), DIGEST, MutableInteger(1), "audio/wav"),
            lambda: ArtifactRef(ArtifactId(UUID), DIGEST, 1, MutableString("audio/wav")),
            lambda: parse_strict_json(MutableBytes(b"{}")),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValidationError):
                    call()

    def test_source_fields_and_collections_reject_subclasses(self) -> None:
        invalid_calls = (
            lambda: SourceVersionRef(
                SourceVersionId(UUID),
                SourceRecordingId(UUID),
                DIGEST,
                MutableInteger(10),
                "evidence",
            ),
            lambda: SourceVersionRef(
                SourceVersionId(UUID),
                SourceRecordingId(UUID),
                DIGEST,
                10,
                MutableString("evidence"),
            ),
            lambda: SourceSpan(SOURCE_VERSION, MutableInteger(0), 1),
            lambda: SourceSpan(SOURCE_VERSION, 0, MutableInteger(1)),
            lambda: TranscriptScope(MutableTuple((SOURCE_VERSION,)), (), ()),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValidationError):
                    call()

    def test_decimal_inputs_and_result_fields_reject_subclasses(self) -> None:
        invalid_calls = (
            lambda: decimal_seconds_to_microseconds(MutableString("1.0")),
            lambda: decimal_seconds_to_microseconds(MutableDecimal("1.0")),
            lambda: DecimalTimeConversion(MutableInteger(1), False, "1"),
            lambda: DecimalTimeConversion(1, False, MutableString("1")),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValidationError):
                    call()


class ExactEventAndRefTests(unittest.TestCase):
    def test_domain_event_fields_and_recorder_reject_subclasses(self) -> None:
        class DerivedDomainEventId(DomainEventId):
            pass

        class DerivedDomainEvent(DomainEvent):
            pass

        invalid_calls = (
            lambda: DomainEvent(DerivedDomainEventId(UUID), 1, "Event", {}),
            lambda: DomainEvent(DomainEventId(UUID), MutableInteger(1), "Event", {}),
            lambda: DomainEvent(DomainEventId(UUID), 1, MutableString("Event"), {}),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValidationError):
                    call()

        recorder = AggregateEventRecorder()
        derived_event = DerivedDomainEvent(DomainEventId(UUID), 1, "Event", {})
        with self.assertRaises(ValidationError):
            recorder._record_event(derived_event)

    def test_ref_builtin_fields_reject_subclasses(self) -> None:
        invalid_calls = (
            lambda: RubricRef(RubricId(UUID), MutableInteger(1), DIGEST),
            lambda: PolicyEvaluatorRef(
                MutableString("heritage"), "1.0.0", "policy-v1", DIGEST
            ),
            lambda: ActorRef(ActorId(UUID), MutableString("Steward")),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(ValidationError):
                    call()
