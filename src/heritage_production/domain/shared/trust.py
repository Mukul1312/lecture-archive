"""Cross-module immutable trust vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .digests import ArtifactRef, ContentDigest
from .errors import ValidationError
from .ids import ActorId
from .refs import ActorCredentialRef, AssuranceLevel, CredentialVerificationMethod
from .text import require_canonical_text


@dataclass(frozen=True, slots=True)
class RoleCode:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.value, field="role code", nonempty=True)

    def __str__(self) -> str:
        return self.value


class SignOffTargetKind(str, Enum):
    REVIEW_TARGET = "review_target"
    RELEASE_CONTENT = "release_content"
    MANIFEST_MEMBER = "manifest_member"


class SignOffDecision(str, Enum):
    APPROVED = "approved"
    DECLINED = "declined"


class ActorAssuranceKind(str, Enum):
    VERIFIED_SIGNATURE = "verified_signature"
    STEWARD_ATTESTATION = "steward_attestation"


@dataclass(frozen=True, slots=True)
class SignatureProof:
    algorithm: str
    credential_fingerprint: ContentDigest
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        require_canonical_text(self.algorithm, field="signature algorithm", nonempty=True)
        if type(self.credential_fingerprint) is not ContentDigest:
            raise ValidationError("credential_fingerprint must be a ContentDigest")
        if type(self.artifact) is not ArtifactRef:
            raise ValidationError("signature proof artifact must be an ArtifactRef")


@dataclass(frozen=True, slots=True, init=False)
class ActorAssuranceEvidence:
    kind: ActorAssuranceKind
    credential: ActorCredentialRef
    assurance: AssuranceLevel
    signed_context_digest: ContentDigest | None
    proof: SignatureProof | None
    attesting_steward_id: ActorId | None
    attestation_reason: str | None
    attested_at_us: int | None

    @classmethod
    def verified_signature(
        cls,
        *,
        credential: ActorCredentialRef,
        signed_context_digest: ContentDigest,
        proof: SignatureProof,
    ) -> ActorAssuranceEvidence:
        if type(credential) is not ActorCredentialRef:
            raise ValidationError("credential must be an exact ActorCredentialRef")
        if credential.verification_method is not CredentialVerificationMethod.ED25519:
            raise ValidationError("verified assurance requires an Ed25519 credential")
        if type(signed_context_digest) is not ContentDigest:
            raise ValidationError("signed_context_digest must be a ContentDigest")
        if type(proof) is not SignatureProof:
            raise ValidationError("proof must be an exact SignatureProof")
        if proof.algorithm != credential.verification_method.value:
            raise ValidationError("signature proof algorithm does not match credential")
        if proof.credential_fingerprint != credential.credential_fingerprint:
            raise ValidationError("signature proof fingerprint does not match credential")
        return cls._build(
            ActorAssuranceKind.VERIFIED_SIGNATURE,
            credential,
            AssuranceLevel.VERIFIED_SIGNATURE,
            signed_context_digest,
            proof,
            None,
            None,
            None,
        )

    @classmethod
    def steward_attested(
        cls,
        *,
        credential: ActorCredentialRef,
        attesting_steward_id: ActorId,
        reason: str,
        attested_at_us: int,
    ) -> ActorAssuranceEvidence:
        if type(credential) is not ActorCredentialRef:
            raise ValidationError("credential must be an exact ActorCredentialRef")
        if credential.verification_method is not CredentialVerificationMethod.STEWARD_ATTESTATION:
            raise ValidationError("attested assurance requires a steward-attestation credential")
        if type(attesting_steward_id) is not ActorId:
            raise ValidationError("attesting_steward_id must be an ActorId")
        require_canonical_text(reason, field="attestation reason", nonempty=True)
        if type(attested_at_us) is not int or attested_at_us <= 0:
            raise ValidationError("attested_at_us must be a positive integer")
        return cls._build(
            ActorAssuranceKind.STEWARD_ATTESTATION,
            credential,
            AssuranceLevel.STEWARD_ATTESTED,
            None,
            None,
            attesting_steward_id,
            reason,
            attested_at_us,
        )

    @classmethod
    def _build(cls, *values: object) -> ActorAssuranceEvidence:
        evidence = object.__new__(cls)
        for name, value in zip(cls.__dataclass_fields__, values, strict=True):
            object.__setattr__(evidence, name, value)
        return evidence

    @property
    def actor_id(self) -> ActorId:
        return self.credential.actor_id
