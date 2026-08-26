"""The command envelope every use case shares, and its validation helpers.

Design section 9.4 gives every command an `OperationId`; section 9.1 gives every
handler an actor context. Commands are values, not requests: they validate their
own shape at construction so a handler never has to re-check types, and a
malformed command can never reach an aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import ActorId, OperationId, ValidationError
from heritage_production.domain.shared.text import require_canonical_text


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Who is issuing a command.

    Authorization is an application concern (the domain stays auth-agnostic),
    so this carries identity only. Whether that actor may perform the operation
    is decided by the handler or, for the terminal approval, by `Production`
    checking its own steward.
    """

    actor_id: ActorId

    def __post_init__(self) -> None:
        if type(self.actor_id) is not ActorId:
            raise ValidationError("actor_id must be an exact ActorId")


def require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


def require_envelope(operation_id: object, actor: object) -> None:
    """Every command carries an exact operation identity and actor context."""
    require_exact(operation_id, OperationId, "operation_id")
    require_exact(actor, ActorContext, "actor")


def require_expected_version(value: object) -> None:
    """Optimistic versions start at one; zero would mean 'no row read'."""
    if type(value) is not int or value <= 0:
        raise ValidationError("expected_version must be a positive integer")


def require_text(value: object, *, field: str) -> None:
    require_canonical_text(value, field=field, nonempty=True)


def require_tuple(value: object, expected: type[object], field: str) -> None:
    if type(value) is not tuple or not all(type(item) is expected for item in value):
        raise ValidationError(f"{field} must be an immutable tuple of {expected.__name__}")
