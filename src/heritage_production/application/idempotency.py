"""Command-input manifests: the semantic idempotency keys of design 9.4.

Every content-producing command hashes a versioned, digest-free input
manifest under its own `heritage-command-<command-name>-v1` label. The
manifest is a mechanical walk of every command field — operation id, actor,
and expected version included — so the key covers every domain-semantic
input rather than a convenient subset: an "identical replay" is an identical
command, and any difference at all under a reused operation id is a conflict.

The walk is strict and fails closed. Exact primitive types, tuples, enums,
and dataclass instances are the whole vocabulary; a float, list, dict, set,
or arbitrary object in a command field is a bug, not something to coerce.
Encoded enums and dataclasses carry their type name, so two values with the
same shape but different meanings can never collide. Nothing here hashes
itself: the manifest never contains its own digest (stored digests of *other*
objects are inputs, and belong in the key).
"""

from __future__ import annotations

import dataclasses
import re
from enum import Enum

from heritage_production.domain.shared import (
    ContentDigest,
    JsonValue,
    OperationId,
    ValidationError,
    semantic_digest,
)

from .commands.context import ActorContext


_CAMEL_CASE = re.compile(r"^[A-Z][A-Za-z]*$")
_WORD_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _command_type(command: object) -> type:
    return command if isinstance(command, type) else type(command)


def command_name(command: object) -> str:
    """The command's class name, the unit the design's label grammar names."""
    name = _command_type(command).__name__
    if _CAMEL_CASE.fullmatch(name) is None:
        raise ValidationError("a command type name must be CamelCase ASCII letters")
    return name


def _kebab(name: str) -> str:
    return _WORD_BOUNDARY.sub("-", name).lower()


def command_label(command: object) -> str:
    return f"heritage-command-{_kebab(command_name(command))}-v1"


def result_label(command: object) -> str:
    return f"heritage-command-{_kebab(command_name(command))}-result-v1"


def manifest_value(value: object) -> JsonValue:
    """Encode one command field for hashing; unknown types fail closed.

    Exact-type checks matter: `bool` must never collapse into `int`, and a
    str-backed enum member must never collapse into its string value.
    """
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is tuple:
        return [manifest_value(member) for member in value]
    if isinstance(value, Enum):
        return {"kind": "enum", "type": type(value).__name__, "member": value.name}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "kind": "value",
            "type": type(value).__name__,
            "fields": {
                field.name: manifest_value(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    raise ValidationError(
        f"unsupported manifest value type: {type(value).__name__}"
    )


def command_input_manifest(command: object) -> dict[str, JsonValue]:
    """The complete digest-free manifest: the command name and every field."""
    if not dataclasses.is_dataclass(command) or isinstance(command, type):
        raise ValidationError("a command must be a dataclass instance")
    if type(getattr(command, "operation_id", None)) is not OperationId:
        raise ValidationError("a command must carry an exact OperationId")
    if type(getattr(command, "actor", None)) is not ActorContext:
        raise ValidationError("a command must carry an exact ActorContext")
    return {
        "command": command_name(command),
        "inputs": {
            field.name: manifest_value(getattr(command, field.name))
            for field in dataclasses.fields(command)
        },
    }


def command_input_digest(command: object) -> ContentDigest:
    return semantic_digest(command_label(command), command_input_manifest(command))


def command_result_digest(command: object, payload: object) -> ContentDigest:
    """Digest of the operation's canonical result manifest.

    The result label is the input label with a `-result` marker, so a result
    can never be replayed as an input or claimed by another command.
    """
    if type(payload) is not dict:
        raise ValidationError("a result payload must be a JSON object")
    return semantic_digest(result_label(command), payload)
