"""Immutable domain events and aggregate-local pending-event recording."""

from __future__ import annotations

from dataclasses import dataclass

from .canonical import JsonValue, canonical_json, parse_strict_json
from .errors import ValidationError
from .ids import DomainEventId
from .text import require_canonical_text


@dataclass(frozen=True, slots=True, init=False)
class DomainEvent:
    event_id: DomainEventId
    occurred_at_us: int
    event_type: str
    _canonical_payload: bytes

    def __init__(
        self,
        event_id: DomainEventId,
        occurred_at_us: int,
        event_type: str,
        payload: JsonValue,
    ) -> None:
        if not isinstance(event_id, DomainEventId):
            raise ValidationError("event_id must be a DomainEventId")
        if (
            isinstance(occurred_at_us, bool)
            or not isinstance(occurred_at_us, int)
            or occurred_at_us <= 0
        ):
            raise ValidationError("occurred_at_us must be a positive integer")
        require_canonical_text(event_type, field="event_type", nonempty=True)
        encoded_payload = canonical_json(payload)
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "occurred_at_us", occurred_at_us)
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "_canonical_payload", encoded_payload)

    @property
    def payload(self) -> JsonValue:
        return parse_strict_json(self._canonical_payload)

    @property
    def canonical_payload(self) -> bytes:
        return self._canonical_payload


class AggregateEventRecorder:
    """Records events emitted by behavior until an application transaction pulls them."""

    __slots__ = ("_pending_events",)

    def __init__(self) -> None:
        self._pending_events: list[DomainEvent] = []

    def _record_event(self, event: DomainEvent) -> None:
        if not isinstance(event, DomainEvent):
            raise ValidationError("only DomainEvent values can be recorded")
        self._pending_events.append(event)

    def pull_events(self) -> tuple[DomainEvent, ...]:
        pending = tuple(self._pending_events)
        self._pending_events.clear()
        return pending
