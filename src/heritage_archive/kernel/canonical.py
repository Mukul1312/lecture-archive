"""Strict JSON parsing and canonicalization for the I-JSON subset."""

from __future__ import annotations

import json
from typing import TypeAlias

from .digests import ContentDigest
from .errors import ValidationError
from .text import require_canonical_text


JsonValue: TypeAlias = None | bool | int | str | list["JsonValue"] | dict[str, "JsonValue"]
SAFE_INTEGER_MAX = 9_007_199_254_740_991


def _reject_number(token: str) -> None:
    raise ValidationError(f"unsupported JSON number: {token}")


def _parse_integer(token: str) -> int:
    value = int(token)
    if not -SAFE_INTEGER_MAX <= value <= SAFE_INTEGER_MAX:
        raise ValidationError("JSON integer is outside the interoperable safe range")
    return value


def _object_from_pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON object key: {key!r}")
        require_canonical_text(key, field="JSON object key")
        result[key] = value
    return result


def parse_strict_json(raw: bytes) -> JsonValue:
    if type(raw) is not bytes:
        raise ValidationError("strict JSON input must be bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValidationError("UTF-8 BOM is not permitted")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValidationError("JSON input must be valid UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_from_pairs,
            parse_float=_reject_number,
            parse_int=_parse_integer,
            parse_constant=_reject_number,
        )
    except ValidationError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValidationError("invalid JSON input") from error
    _validate_json_value(value)
    return value


def _validate_json_value(value: object) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not -SAFE_INTEGER_MAX <= value <= SAFE_INTEGER_MAX:
            raise ValidationError("JSON integer is outside the interoperable safe range")
        return
    if type(value) is str:
        require_canonical_text(value, field="JSON string")
        return
    if type(value) is list:
        for member in value:
            _validate_json_value(member)
        return
    if type(value) is dict:
        for key, member in value.items():
            if type(key) is not str:
                raise ValidationError("JSON object keys must be strings")
            require_canonical_text(key, field="JSON object key")
            _validate_json_value(member)
        return
    raise ValidationError(f"unsupported JSON value type: {type(value).__name__}")


_SHORT_ESCAPES = {0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0C: "\\f"}


def _encode_string(value: str) -> str:
    require_canonical_text(value, field="JSON string")
    encoded: list[str] = ['"']
    for character in value:
        code_point = ord(character)
        if character == '"':
            encoded.append('\\"')
        elif character == "\\":
            encoded.append("\\\\")
        elif code_point in _SHORT_ESCAPES:
            encoded.append(_SHORT_ESCAPES[code_point])
        elif code_point < 0x20:
            encoded.append(f"\\u{code_point:04x}")
        else:
            encoded.append(character)
    encoded.append('"')
    return "".join(encoded)


def _encode_value(value: JsonValue) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        if not -SAFE_INTEGER_MAX <= value <= SAFE_INTEGER_MAX:
            raise ValidationError("JSON integer is outside the interoperable safe range")
        return str(value)
    if type(value) is str:
        return _encode_string(value)
    if type(value) is list:
        return "[" + ",".join(_encode_value(member) for member in value) + "]"
    if type(value) is dict:
        keys: list[str] = []
        for key in value:
            if type(key) is not str:
                raise ValidationError("JSON object keys must be strings")
            require_canonical_text(key, field="JSON object key")
            keys.append(key)
        keys.sort(key=lambda key: key.encode("utf-16-be"))
        return "{" + ",".join(f"{_encode_string(key)}:{_encode_value(value[key])}" for key in keys) + "}"
    raise ValidationError(f"unsupported JSON value type: {type(value).__name__}")


def canonical_json(value: JsonValue) -> bytes:
    _validate_json_value(value)
    return _encode_value(value).encode("utf-8")


def semantic_digest(digest_schema: str, payload: JsonValue) -> ContentDigest:
    require_canonical_text(digest_schema, field="digest_schema", nonempty=True)
    _validate_json_value(payload)
    if type(payload) is dict and ({"digest", "semantic_digest"} & payload.keys()):
        raise ValidationError("semantic digest payload must not contain a top-level self-digest")
    envelope: JsonValue = {"digest_schema": digest_schema, "schema_version": 1, "payload": payload}
    return ContentDigest.from_bytes(canonical_json(envelope))
