"""Canonical text validation shared by identity-bearing values."""

from __future__ import annotations

import unicodedata

from .errors import ValidationError


def require_canonical_text(value: object, *, field: str, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    if nonempty and not value:
        raise ValidationError(f"{field} must not be empty")
    if "\r" in value:
        raise ValidationError(f"{field} must use LF-only line endings")
    if unicodedata.normalize("NFC", value) != value:
        raise ValidationError(f"{field} must already be Unicode NFC")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValidationError(f"{field} must not contain lone surrogates")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValidationError(f"{field} must be UTF-8 encodable") from error
    return value
