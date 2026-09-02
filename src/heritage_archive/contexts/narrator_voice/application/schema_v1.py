"""Strict canonical schema version 1 codec for Task-3 persistence handoff."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import types
from typing import Any, get_args, get_origin, get_type_hints

from heritage_archive.kernel import JsonValue, ValidationError, canonical_json, parse_strict_json


SCHEMA_VERSION = 1


def _to_primitive(value: object) -> JsonValue:
    if value is None or type(value) in {bool, int, str}:
        return value  # type: ignore[return-value]
    if type(value) is float:
        raise ValidationError("schema-v1 payloads never contain binary floats")
    if isinstance(value, datetime):
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValidationError("schema-v1 datetimes must be exact aware UTC values")
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        result: dict[str, JsonValue] = {"__type__": type(value).__name__}
        for field in fields(value):
            result[field.name] = _to_primitive(getattr(value, field.name))
        return result
    if type(value) in {tuple, list}:
        return [_to_primitive(item) for item in value]
    if type(value) in {frozenset, set}:
        encoded = [_to_primitive(item) for item in value]
        return sorted(encoded, key=canonical_json)
    if type(value) is dict:
        result: dict[str, JsonValue] = {}
        for key, member in value.items():
            if type(key) is not str:
                raise ValidationError("schema-v1 object keys must be strings")
            result[key] = _to_primitive(member)
        return result
    raise ValidationError(f"unsupported schema-v1 value type: {type(value).__name__}")


def schema_v1_payload(value: object) -> dict[str, JsonValue]:
    payload = _to_primitive(value)
    if type(payload) is not dict:
        raise ValidationError("schema-v1 records require an object payload")
    return payload


def encode_schema_v1(value: object) -> bytes:
    envelope: JsonValue = {
        "schema_version": SCHEMA_VERSION,
        "record_type": type(value).__name__,
        "payload": schema_v1_payload(value),
    }
    return canonical_json(envelope)


def _decode(value: JsonValue, annotation: object) -> object:
    if annotation is Any:
        return value
    if annotation is type(None):
        if value is not None:
            raise ValidationError("expected null")
        return None
    if annotation in {str, int, bool}:
        if type(value) is not annotation:
            raise ValidationError(f"expected exact {annotation.__name__}")
        return value
    if annotation is datetime:
        if type(value) is not str:
            raise ValidationError("expected canonical UTC datetime string")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValidationError("invalid schema-v1 datetime") from error
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValidationError("schema-v1 datetime must be UTC")
        return parsed
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if type(value) is not str:
            raise ValidationError(f"expected {annotation.__name__} string")
        try:
            return annotation(value)
        except ValueError as error:
            raise ValidationError(f"unknown {annotation.__name__} value") from error
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in {tuple, list, frozenset, set}:
        if type(value) is not list:
            raise ValidationError("expected schema-v1 array")
        member_type = arguments[0] if arguments else Any
        decoded = [_decode(member, member_type) for member in value]
        if origin is tuple:
            return tuple(decoded)
        if origin is frozenset:
            return frozenset(decoded)
        if origin is set:
            return set(decoded)
        return decoded
    if origin in {types.UnionType} or str(origin) == "typing.Union":
        if value is None and type(None) in arguments:
            return None
        if type(value) is dict and type(value.get("__type__")) is str:
            named = [candidate for candidate in arguments if isinstance(candidate, type) and candidate.__name__ == value["__type__"]]
            if len(named) == 1:
                return _decode(value, named[0])
        errors: list[ValidationError] = []
        for candidate in arguments:
            if candidate is type(None):
                continue
            try:
                return _decode(value, candidate)
            except ValidationError as error:
                errors.append(error)
        raise ValidationError("value does not match any allowed schema-v1 union member") from (errors[-1] if errors else None)
    if isinstance(annotation, type) and is_dataclass(annotation):
        if type(value) is not dict:
            raise ValidationError(f"expected {annotation.__name__} object")
        expected = {field.name for field in fields(annotation)} | {"__type__"}
        if set(value) != expected:
            unknown = sorted(set(value) - expected)
            missing = sorted(expected - set(value))
            raise ValidationError(f"invalid {annotation.__name__} fields; unknown={unknown}, missing={missing}")
        if value["__type__"] != annotation.__name__:
            raise ValidationError(f"schema-v1 nested type must be {annotation.__name__}")
        hints = get_type_hints(annotation)
        decoded: dict[str, object] = {}
        for field in fields(annotation):
            decoded[field.name] = _decode(value[field.name], hints[field.name])
        try:
            return annotation(**decoded)
        except (TypeError, ValueError, ValidationError) as error:
            if isinstance(error, ValidationError):
                raise
            raise ValidationError(f"invalid {annotation.__name__} payload") from error
    raise ValidationError(f"unsupported schema-v1 annotation: {annotation!r}")


def decode_schema_v1(raw: bytes, record_type: type[Any]) -> Any:
    envelope = parse_strict_json(raw)
    if type(envelope) is not dict or set(envelope) != {"schema_version", "record_type", "payload"}:
        raise ValidationError("schema-v1 envelope has unknown or missing fields")
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("unknown schema version")
    if envelope["record_type"] != record_type.__name__:
        raise ValidationError("schema-v1 record type mismatch")
    return _decode(envelope["payload"], record_type)
