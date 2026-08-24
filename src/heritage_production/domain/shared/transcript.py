"""Canonical transcript text and scalar-coordinate operations."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ValidationError
from .text import require_canonical_text


@dataclass(frozen=True, slots=True)
class TranscriptText:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.value, field="transcript text")

    def __len__(self) -> int:
        return len(self.value)

    @property
    def length(self) -> int:
        return len(self.value)

    def slice(self, start: int, end: int) -> TranscriptText:
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
        ):
            raise ValidationError("text slice coordinates must be integers")
        if start < 0 or end < start or end > len(self.value):
            raise ValidationError("text slice must be a valid half-open scalar range")
        return TranscriptText(self.value[start:end])
