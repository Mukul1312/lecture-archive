"""Review-target sign-off requirements and immutable evidence."""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
    ActorAssuranceKind,
    ActorCredentialRef,
    ActorId,
    AssuranceLevel,
    ContentDigest,
    ReviewTargetManifestRef,
    RoleCode,
    SignOffDecision,
    SignOffTargetKind,
    ValidationError,
    assurance_satisfies,
    semantic_digest,
)

from .targets import _artifact_value, _digest_value


@dataclass(frozen=True, slots=True)
class ReviewSignOffRequirement:
    credential: ActorCredentialRef
    role: RoleCode
    minimum_assurance: AssuranceLevel

    def __post_init__(self) -> None:
        if type(self.credential) is not ActorCredentialRef:
            raise ValidationError("credential must be an ActorCredentialRef")
        if type(self.role) is not RoleCode:
            raise ValidationError("role must be a RoleCode")
        if type(self.minimum_assurance) is not AssuranceLevel:
            raise ValidationError("minimum_assurance must be an AssuranceLevel")
        if self.minimum_assurance is AssuranceLevel.UNVERIFIED:
            raise ValidationError("review sign-off requirements require canonical assurance")
        if not assurance_satisfies(self.credential.assurance, self.minimum_assurance):
            raise ValidationError("credential assurance is below the sign-off minimum")

    @property
    def actor_id(self) -> ActorId:
        return self.credential.actor_id


def review_signoff_context_digest(
    *,
    sign_off_intent_digest: ContentDigest,
    actor_id: ActorId,
    role: RoleCode,
    target_ref: ReviewTargetManifestRef,
) -> ContentDigest:
    if type(sign_off_intent_digest) is not ContentDigest:
        raise ValidationError("sign_off_intent_digest must be a ContentDigest")
    if type(actor_id) is not ActorId:
        raise ValidationError("actor_id must be an ActorId")
    if type(role) is not RoleCode:
        raise ValidationError("role must be a RoleCode")
    if type(target_ref) is not ReviewTargetManifestRef:
        raise ValidationError("target_ref must be a ReviewTargetManifestRef")
    return semantic_digest(
        "heritage-signoff-context-v1",
        {
            "semantic_payload_digest": _digest_value(sign_off_intent_digest),
            "actor_id": actor_id.value,
            "role": role.value,
            "target_kind": SignOffTargetKind.REVIEW_TARGET.value,
            "target_id": target_ref.review_round_id.value,
            "target_digest": _digest_value(target_ref.semantic_digest),
            "operation_kind": "review_sign_off",
            "schema_version": 1,
        },
    )


def _credential_value(value: ActorCredentialRef) -> dict[str, object]:
    return {
        "actor_id": value.actor_id.value,
        "verification_method": value.verification_method.value,
        "assurance": value.assurance.value,
        "credential_fingerprint": (
            _digest_value(value.credential_fingerprint)
            if value.credential_fingerprint is not None
            else None
        ),
        "public_key_artifact": (
            _artifact_value(value.public_key_artifact)
            if value.public_key_artifact is not None
            else None
        ),
    }


def _sign_off_intent_payload(
    credential: ActorCredentialRef,
    role: RoleCode,
    target_ref: ReviewTargetManifestRef,
    decision: SignOffDecision,
    signed_at_us: int,
) -> dict[str, object]:
    return {
        "credential": _credential_value(credential),
        "role": role.value,
        "target_kind": SignOffTargetKind.REVIEW_TARGET.value,
        "target_id": target_ref.review_round_id.value,
        "target_digest": _digest_value(target_ref.semantic_digest),
        "decision": decision.value,
        "signed_at_us": signed_at_us,
    }


def review_signoff_intent_digest(
    *,
    credential: ActorCredentialRef,
    role: RoleCode,
    target_ref: ReviewTargetManifestRef,
    decision: SignOffDecision,
    signed_at_us: int,
) -> ContentDigest:
    """Hash the complete proof-excluded Review sign-off intent."""
    for field_name, value, expected in (
        ("credential", credential, ActorCredentialRef),
        ("role", role, RoleCode),
        ("target_ref", target_ref, ReviewTargetManifestRef),
        ("decision", decision, SignOffDecision),
    ):
        if type(value) is not expected:
            raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
    if type(signed_at_us) is not int or signed_at_us <= 0:
        raise ValidationError("signed_at_us must be a positive integer")
    return semantic_digest(
        "heritage-signoff-intent-v1",
        _sign_off_intent_payload(credential, role, target_ref, decision, signed_at_us),
    )


def _assurance_value(value: ActorAssuranceEvidence) -> dict[str, object]:
    if value.kind is ActorAssuranceKind.VERIFIED_SIGNATURE:
        return {
            "kind": value.kind.value,
            "signed_context_digest": _digest_value(value.signed_context_digest),
            "proof_algorithm": value.proof.algorithm,
            "proof_fingerprint": _digest_value(value.proof.credential_fingerprint),
            "attesting_steward_id": None,
            "attestation_reason": None,
            "attested_at_us": None,
        }
    return {
        "kind": value.kind.value,
        "signed_context_digest": None,
        "proof_algorithm": None,
        "proof_fingerprint": None,
        "attesting_steward_id": value.attesting_steward_id.value,
        "attestation_reason": value.attestation_reason,
        "attested_at_us": value.attested_at_us,
    }


def _sign_off_payload(
    credential: ActorCredentialRef,
    assurance: ActorAssuranceEvidence,
    role: RoleCode,
    target_ref: ReviewTargetManifestRef,
    decision: SignOffDecision,
    signed_at_us: int,
) -> dict[str, object]:
    return {
        "credential": _credential_value(credential),
        "assurance_evidence": _assurance_value(assurance),
        "role": role.value,
        "target_kind": SignOffTargetKind.REVIEW_TARGET.value,
        "target_id": target_ref.review_round_id.value,
        "target_digest": _digest_value(target_ref.semantic_digest),
        "decision": decision.value,
        "signed_at_us": signed_at_us,
    }


@dataclass(frozen=True, slots=True)
class ReviewSignOff:
    credential: ActorCredentialRef
    assurance: ActorAssuranceEvidence
    role: RoleCode
    target_kind: SignOffTargetKind
    target_ref: ReviewTargetManifestRef
    decision: SignOffDecision
    signed_at_us: int
    sign_off_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("credential", self.credential, ActorCredentialRef),
            ("assurance", self.assurance, ActorAssuranceEvidence),
            ("role", self.role, RoleCode),
            ("target_kind", self.target_kind, SignOffTargetKind),
            ("target_ref", self.target_ref, ReviewTargetManifestRef),
            ("decision", self.decision, SignOffDecision),
            ("sign_off_digest", self.sign_off_digest, ContentDigest),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if self.target_kind is not SignOffTargetKind.REVIEW_TARGET:
            raise ValidationError("ReviewSignOff only permits REVIEW_TARGET")
        if type(self.signed_at_us) is not int or self.signed_at_us <= 0:
            raise ValidationError("signed_at_us must be a positive integer")
        validated_assurance = self.assurance.validated()
        if validated_assurance.credential != self.credential:
            raise ValidationError("sign-off assurance does not match its credential")
        object.__setattr__(self, "credential", validated_assurance.credential)
        object.__setattr__(self, "assurance", validated_assurance)
        if self.assurance.kind is ActorAssuranceKind.VERIFIED_SIGNATURE:
            intent_digest = review_signoff_intent_digest(
                credential=self.credential,
                role=self.role,
                target_ref=self.target_ref,
                decision=self.decision,
                signed_at_us=self.signed_at_us,
            )
            expected_context = review_signoff_context_digest(
                sign_off_intent_digest=intent_digest,
                actor_id=self.credential.actor_id,
                role=self.role,
                target_ref=self.target_ref,
            )
            if self.assurance.signed_context_digest != expected_context:
                raise ValidationError("signature context does not bind exact sign-off role and target")
        expected = semantic_digest(
            "heritage-signoff-v1",
            _sign_off_payload(
                self.credential,
                self.assurance,
                self.role,
                self.target_ref,
                self.decision,
                self.signed_at_us,
            ),
        )
        if expected != self.sign_off_digest:
            raise ValidationError("sign-off digest does not match its semantic evidence")

    @classmethod
    def seal(
        cls,
        *,
        credential: ActorCredentialRef,
        assurance: ActorAssuranceEvidence,
        role: RoleCode,
        target_ref: ReviewTargetManifestRef,
        decision: SignOffDecision,
        signed_at_us: int,
    ) -> ReviewSignOff:
        try:
            digest = semantic_digest(
                "heritage-signoff-v1",
                _sign_off_payload(
                    credential, assurance, role, target_ref, decision, signed_at_us
                ),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed review sign-off semantic input") from error
        return cls(
            credential,
            assurance,
            role,
            SignOffTargetKind.REVIEW_TARGET,
            target_ref,
            decision,
            signed_at_us,
            digest,
        )
