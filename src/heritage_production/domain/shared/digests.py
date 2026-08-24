"""Content digests and content-addressed artifact references."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .errors import ValidationError
from .ids import ArtifactId
from .text import require_canonical_text


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE_TOKEN = r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+\-]*"
_MEDIA_TYPE = re.compile(rf"^{_MEDIA_TYPE_TOKEN}/{_MEDIA_TYPE_TOKEN}$")


@dataclass(frozen=True, slots=True)
class ContentDigest:
    algorithm: str
    hex_digest: str

    def __post_init__(self) -> None:
        if self.algorithm != "sha256":
            raise ValidationError("the only supported digest algorithm is sha256")
        if not isinstance(self.hex_digest, str) or _SHA256_HEX.fullmatch(self.hex_digest) is None:
            raise ValidationError("sha256 digest must contain 64 lowercase hexadecimal characters")

    @classmethod
    def from_bytes(cls, raw: bytes) -> ContentDigest:
        if not isinstance(raw, bytes):
            raise ValidationError("raw digest input must be bytes")
        return cls("sha256", hashlib.sha256(raw).hexdigest())


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: ArtifactId
    content_digest: ContentDigest
    byte_size: int
    media_type: str

    def __post_init__(self) -> None:
        if type(self.artifact_id) is not ArtifactId:
            raise ValidationError("artifact_id must be an ArtifactId")
        if type(self.content_digest) is not ContentDigest:
            raise ValidationError("content_digest must be a ContentDigest")
        if isinstance(self.byte_size, bool) or not isinstance(self.byte_size, int) or self.byte_size < 0:
            raise ValidationError("byte_size must be a nonnegative integer")
        media_type = require_canonical_text(self.media_type, field="media_type", nonempty=True)
        if _MEDIA_TYPE.fullmatch(media_type) is None:
            raise ValidationError("media_type must be a nonempty type/subtype value")
