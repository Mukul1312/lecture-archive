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
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if (
            type(occurred_at_us) is not int
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


class SealedAggregateRoot:
    """Marker for an aggregate root that is sealed at creation and emits nothing.

    It carries no behaviour: it exists so the architecture test can enumerate
    the sealed roots structurally, exactly as it enumerates the event-recording
    roots, rather than trusting a hand-maintained name list.
    """

    __slots__ = ()


class AggregateEventRecorder:
    """Records events emitted by behavior until an application transaction pulls them."""

    __slots__ = ("_pending_events",)

    def __init__(self) -> None:
        self._pending_events: list[DomainEvent] = []

    def _record_event(self, event: DomainEvent) -> None:
        if type(event) is not DomainEvent:
            raise ValidationError("only DomainEvent values can be recorded")
        self._pending_events.append(event)

    def pull_events(self) -> tuple[DomainEvent, ...]:
        pending = tuple(self._pending_events)
        self._pending_events.clear()
        return pending
