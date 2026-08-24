from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
import unittest

from heritage_production.domain.shared import (
    AggregateEventRecorder,
    DomainEvent,
    DomainEventId,
    ValidationError,
    decimal_seconds_to_microseconds,
)


EVENT_ID_1 = DomainEventId("123e4567-e89b-42d3-a456-426614174001")
EVENT_ID_2 = DomainEventId("123e4567-e89b-42d3-a456-426614174002")


class DecimalTimeTests(unittest.TestCase):
    def test_exact_conversion_retains_original_evidence(self) -> None:
        decimal_result = decimal_seconds_to_microseconds(Decimal("1.234567"))
        self.assertEqual(decimal_result.microseconds, 1_234_567)
        self.assertFalse(decimal_result.rounded)
        self.assertEqual(decimal_result.original_token, "1.234567")

        string_result = decimal_seconds_to_microseconds("1.230000")
        self.assertEqual(string_result.microseconds, 1_230_000)
        self.assertFalse(string_result.rounded)
        self.assertEqual(string_result.original_token, "1.230000")

    def test_finer_values_use_round_half_even(self) -> None:
        cases = (
            ("0.0000005", 0),
            ("0.0000015", 2),
            ("1.2345674", 1_234_567),
            ("1.2345675", 1_234_568),
        )
        for token, expected in cases:
            with self.subTest(token=token):
                result = decimal_seconds_to_microseconds(token)
                self.assertEqual(result.microseconds, expected)
                self.assertTrue(result.rounded)
                self.assertEqual(result.original_token, token)

    def test_rejects_nonfinite_negative_binary_float_bool_and_other_types(self) -> None:
        for value in (
            "NaN",
            "Infinity",
            "-Infinity",
            "-0.1",
            " 1.0",
            1.25,
            True,
            1,
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValidationError):
                    decimal_seconds_to_microseconds(value)  # type: ignore[arg-type]


class ExampleRecorder(AggregateEventRecorder):
    def emit(self, event: DomainEvent) -> None:
        self._record_event(event)


class DomainEventTests(unittest.TestCase):
    def event(self, event_id: DomainEventId, event_type: str) -> DomainEvent:
        return DomainEvent(event_id, 1_725_000_000_000_000, event_type, {"x": 1})

    def test_event_validates_injected_identity_time_type_and_payload(self) -> None:
        event = self.event(EVENT_ID_1, "TranscriptEditionSealed")
        self.assertEqual(event.payload, {"x": 1})
        with self.assertRaises(FrozenInstanceError):
            event.event_type = "changed"  # type: ignore[misc]

        for event_id, occurred_at_us, event_type, payload in (
            ("not-an-id", 1, "Event", {}),
            (EVENT_ID_1, 0, "Event", {}),
            (EVENT_ID_1, True, "Event", {}),
            (EVENT_ID_1, 1, "", {}),
            (EVENT_ID_1, 1, "e\u0301", {}),
            (EVENT_ID_1, 1, "Event", {"bad": 1.0}),
        ):
            with self.subTest(event_id=event_id, occurred_at_us=occurred_at_us):
                with self.assertRaises(ValidationError):
                    DomainEvent(event_id, occurred_at_us, event_type, payload)  # type: ignore[arg-type]

    def test_payload_access_does_not_expose_mutable_event_state(self) -> None:
        supplied = {"items": [1]}
        event = DomainEvent(EVENT_ID_1, 1, "Event", supplied)
        supplied["items"].append(2)
        exposed = event.payload
        exposed["items"].append(3)  # type: ignore[union-attr]
        self.assertEqual(event.payload, {"items": [1]})

    def test_recorder_preserves_order_and_pulls_each_event_once(self) -> None:
        recorder = ExampleRecorder()
        first = self.event(EVENT_ID_1, "First")
        second = self.event(EVENT_ID_2, "Second")
        recorder.emit(first)
        recorder.emit(second)

        self.assertEqual(recorder.pull_events(), (first, second))
        self.assertEqual(recorder.pull_events(), ())

    def test_fresh_and_reconstituted_recorders_start_empty(self) -> None:
        self.assertEqual(ExampleRecorder().pull_events(), ())
        reconstituted = ExampleRecorder()
        self.assertEqual(reconstituted.pull_events(), ())
