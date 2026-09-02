"""Opaque canonical identifiers retained for generic actor and artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import ValidationError


_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@dataclass(frozen=True, slots=True)
class _OpaqueId:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _UUID4.fullmatch(self.value) is None:
            raise ValidationError(
                f"{type(self).__name__} must be exact lowercase RFC 4122 UUIDv4 text"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ArtifactId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ActorId(_OpaqueId):
    pass
