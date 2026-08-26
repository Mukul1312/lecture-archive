"""Canonical payload helpers shared by the Release value modules.

This is a leaf module: it imports only the shared kernel. Keeping the helpers
here lets `gates` and `signoffs` both use them without importing each other,
which is what keeps the domain free of import cycles (design section 16.5).
"""

from __future__ import annotations

from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    JsonValue,
    SignOffTargetRule,
    ValidationError,
)


def digest_value(value: ContentDigest) -> dict[str, JsonValue]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


def artifact_value(value: ArtifactRef) -> dict[str, JsonValue]:
    return {
        "artifact_id": value.artifact_id.value,
        "content_digest": digest_value(value.content_digest),
        "byte_size": value.byte_size,
        "media_type": value.media_type,
    }


def credential_value(value: ActorCredentialRef) -> dict[str, JsonValue]:
    return {
        "actor_id": value.actor_id.value,
        "verification_method": value.verification_method.value,
        "assurance": value.assurance.value,
        "credential_fingerprint": (
            digest_value(value.credential_fingerprint)
            if value.credential_fingerprint is not None
            else None
        ),
        "public_key_artifact": (
            artifact_value(value.public_key_artifact)
            if value.public_key_artifact is not None
            else None
        ),
    }


def target_rule_value(value: SignOffTargetRule) -> dict[str, JsonValue]:
    return {
        "target_kind": value.target_kind.value,
        "required_member_role": (
            value.required_member_role.value
            if value.required_member_role is not None
            else None
        ),
    }


def credential_key(value: ActorCredentialRef) -> tuple[str, str, str, str]:
    """The exact identity of one pinned credential, not merely its actor."""
    return (
        value.actor_id.value,
        value.verification_method.value,
        value.assurance.value,
        (
            value.credential_fingerprint.hex_digest
            if value.credential_fingerprint is not None
            else ""
        ),
    )


def revalidate_credential(value: object, *, field: str) -> ActorCredentialRef:
    """Reconstruct a credential through its own constructor."""
    if type(value) is not ActorCredentialRef:
        raise ValidationError(f"{field} must be an exact ActorCredentialRef")
    try:
        return ActorCredentialRef(
            ActorId(value.actor_id.value),
            value.verification_method,
            value.assurance,
            (
                ContentDigest(
                    value.credential_fingerprint.algorithm,
                    value.credential_fingerprint.hex_digest,
                )
                if value.credential_fingerprint is not None
                else None
            ),
            (
                ArtifactRef(
                    ArtifactId(value.public_key_artifact.artifact_id.value),
                    ContentDigest(
                        value.public_key_artifact.content_digest.algorithm,
                        value.public_key_artifact.content_digest.hex_digest,
                    ),
                    value.public_key_artifact.byte_size,
                    value.public_key_artifact.media_type,
                )
                if value.public_key_artifact is not None
                else None
            ),
        )
    except AttributeError as error:
        raise ValidationError(f"{field} is incomplete") from error
