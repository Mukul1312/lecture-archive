"""Cross-module immutable trust vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .digests import ArtifactRef, ContentDigest
from .errors import ValidationError
from .ids import ActorId, ArtifactId
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


class GateScope(str, Enum):
    """Separates review sign-off gates from external release/rights-holder gates."""

    REVIEW = "review"
    EXTERNAL_RELEASE = "external_release"


@dataclass(frozen=True, slots=True)
class GateCode:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.value, field="gate code", nonempty=True)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ManifestMemberRole:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.value, field="manifest member role", nonempty=True)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SignOffTargetRule:
    """The typed artifact a gate's sign-off must bind."""

    target_kind: SignOffTargetKind
    required_member_role: ManifestMemberRole | None = None

    def __post_init__(self) -> None:
        if type(self.target_kind) is not SignOffTargetKind:
            raise ValidationError("target_kind must be an exact SignOffTargetKind")
        if self.target_kind is SignOffTargetKind.MANIFEST_MEMBER:
            if type(self.required_member_role) is not ManifestMemberRole:
                raise ValidationError(
                    "a manifest-member target rule requires its exact member role"
                )
        elif self.required_member_role is not None:
            raise ValidationError(
                "only a manifest-member target rule may name a member role"
            )

    def permits_scope(self, scope: GateScope) -> bool:
        if type(scope) is not GateScope:
            raise ValidationError("scope must be an exact GateScope")
        if scope is GateScope.REVIEW:
            return self.target_kind is SignOffTargetKind.REVIEW_TARGET
        return self.target_kind in (
            SignOffTargetKind.RELEASE_CONTENT,
            SignOffTargetKind.MANIFEST_MEMBER,
        )


class ActorAssuranceKind(str, Enum):
    VERIFIED_SIGNATURE = "verified_signature"
    STEWARD_ATTESTATION = "steward_attestation"


_ASSURANCE_STRENGTH = {
    AssuranceLevel.UNVERIFIED: 0,
    AssuranceLevel.STEWARD_ATTESTED: 1,
    AssuranceLevel.VERIFIED_SIGNATURE: 2,
}


def _revalidate_digest(value: object, *, field: str) -> ContentDigest:
    if type(value) is not ContentDigest:
        raise ValidationError(f"{field} must be an exact ContentDigest")
    try:
        return ContentDigest(value.algorithm, value.hex_digest)
    except AttributeError as error:
        raise ValidationError(f"{field} is incomplete") from error


def _revalidate_actor_id(value: object, *, field: str) -> ActorId:
    if type(value) is not ActorId:
        raise ValidationError(f"{field} must be an exact ActorId")
    try:
        return ActorId(value.value)
    except AttributeError as error:
        raise ValidationError(f"{field} is incomplete") from error


def _revalidate_artifact(value: object, *, field: str) -> ArtifactRef:
    if type(value) is not ArtifactRef:
        raise ValidationError(f"{field} must be an exact ArtifactRef")
    try:
        artifact_id = ArtifactId(value.artifact_id.value)
        content_digest = _revalidate_digest(
            value.content_digest,
            field=f"{field} content digest",
        )
        return ArtifactRef(
            artifact_id,
            content_digest,
            value.byte_size,
            value.media_type,
        )
    except AttributeError as error:
        raise ValidationError(f"{field} is incomplete") from error


def _revalidate_credential(value: object) -> ActorCredentialRef:
    if type(value) is not ActorCredentialRef:
        raise ValidationError("credential must be an exact ActorCredentialRef")
    try:
        return ActorCredentialRef(
            _revalidate_actor_id(value.actor_id, field="credential actor_id"),
            value.verification_method,
            value.assurance,
            (
                _revalidate_digest(
                    value.credential_fingerprint,
                    field="credential fingerprint",
                )
                if value.credential_fingerprint is not None
                else None
            ),
            (
                _revalidate_artifact(
                    value.public_key_artifact,
                    field="credential public-key artifact",
                )
                if value.public_key_artifact is not None
                else None
            ),
        )
    except AttributeError as error:
        raise ValidationError("credential evidence is incomplete") from error


def assurance_satisfies(
    actual: AssuranceLevel,
    minimum: AssuranceLevel,
) -> bool:
    if type(actual) is not AssuranceLevel or type(minimum) is not AssuranceLevel:
        raise ValidationError("assurance comparison requires exact AssuranceLevel values")
    return _ASSURANCE_STRENGTH[actual] >= _ASSURANCE_STRENGTH[minimum]


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


def _revalidate_signature_proof(value: object) -> SignatureProof:
    if type(value) is not SignatureProof:
        raise ValidationError("proof must be an exact SignatureProof")
    try:
        return SignatureProof(
            value.algorithm,
            _revalidate_digest(
                value.credential_fingerprint,
                field="signature proof fingerprint",
            ),
            _revalidate_artifact(
                value.artifact,
                field="signature proof artifact",
            ),
        )
    except AttributeError as error:
        raise ValidationError("signature proof is incomplete") from error


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
        return cls.reconstitute(
            kind=ActorAssuranceKind.VERIFIED_SIGNATURE,
            credential=credential,
            assurance=AssuranceLevel.VERIFIED_SIGNATURE,
            signed_context_digest=signed_context_digest,
            proof=proof,
            attesting_steward_id=None,
            attestation_reason=None,
            attested_at_us=None,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        kind: ActorAssuranceKind,
        credential: ActorCredentialRef,
        assurance: AssuranceLevel,
        signed_context_digest: ContentDigest | None,
        proof: SignatureProof | None,
        attesting_steward_id: ActorId | None,
        attestation_reason: str | None,
        attested_at_us: int | None,
    ) -> ActorAssuranceEvidence:
        if type(kind) is not ActorAssuranceKind:
            raise ValidationError("kind must be an exact ActorAssuranceKind")
        checked_credential = _revalidate_credential(credential)
        if type(assurance) is not AssuranceLevel:
            raise ValidationError("assurance must be an exact AssuranceLevel")

        if kind is ActorAssuranceKind.VERIFIED_SIGNATURE:
            if assurance is not AssuranceLevel.VERIFIED_SIGNATURE:
                raise ValidationError("verified evidence requires verified assurance")
            checked_context = _revalidate_digest(
                signed_context_digest,
                field="signed_context_digest",
            )
            checked_proof = _revalidate_signature_proof(proof)
            if (
                attesting_steward_id is not None
                or attestation_reason is not None
                or attested_at_us is not None
            ):
                raise ValidationError("verified evidence must not carry attestation fields")
            if (
                checked_credential.verification_method
                is not CredentialVerificationMethod.ED25519
            ):
                raise ValidationError("verified assurance requires an Ed25519 credential")
            if checked_proof.algorithm != checked_credential.verification_method.value:
                raise ValidationError("signature proof algorithm does not match credential")
            if (
                checked_proof.credential_fingerprint
                != checked_credential.credential_fingerprint
            ):
                raise ValidationError("signature proof fingerprint does not match credential")
            return cls._build(
                kind,
                checked_credential,
                assurance,
                checked_context,
                checked_proof,
                None,
                None,
                None,
            )

        if assurance is not AssuranceLevel.STEWARD_ATTESTED:
            raise ValidationError("attested evidence requires steward-attested assurance")
        if signed_context_digest is not None or proof is not None:
            raise ValidationError("attested evidence must not carry signature fields")
        checked_steward_id = _revalidate_actor_id(
            attesting_steward_id,
            field="attesting_steward_id",
        )
        require_canonical_text(
            attestation_reason,
            field="attestation reason",
            nonempty=True,
        )
        if type(attested_at_us) is not int or attested_at_us <= 0:
            raise ValidationError("attested_at_us must be a positive integer")
        if (
            checked_credential.verification_method
            is not CredentialVerificationMethod.STEWARD_ATTESTATION
        ):
            raise ValidationError(
                "attested assurance requires a steward-attestation credential"
            )
        return cls._build(
            kind,
            checked_credential,
            assurance,
            None,
            None,
            checked_steward_id,
            attestation_reason,
            attested_at_us,
        )

    def validated(self) -> ActorAssuranceEvidence:
        return type(self).reconstitute(
            kind=self.kind,
            credential=self.credential,
            assurance=self.assurance,
            signed_context_digest=self.signed_context_digest,
            proof=self.proof,
            attesting_steward_id=self.attesting_steward_id,
            attestation_reason=self.attestation_reason,
            attested_at_us=self.attested_at_us,
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
        return cls.reconstitute(
            kind=ActorAssuranceKind.STEWARD_ATTESTATION,
            credential=credential,
            assurance=AssuranceLevel.STEWARD_ATTESTED,
            signed_context_digest=None,
            proof=None,
            attesting_steward_id=attesting_steward_id,
            attestation_reason=reason,
            attested_at_us=attested_at_us,
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
