"""Immutable external release sign-offs owned by Production.

The non-circular chain mirrors Review: `heritage-signoff-intent-v1` hashes the
proof-free intent, `heritage-signoff-context-v1` binds that intent to the actor,
role, and typed target, and `heritage-signoff-v1` hashes the stored evidence.
Proof bytes and proof artifacts never enter the sign-off digest.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
    ActorAssuranceKind,
    ActorCredentialRef,
    ActorId,
    ContentDigest,
    GateCode,
    JsonValue,
    ManifestMemberRole,
    ProductionId,
    ReleaseContentManifestRef,
    RoleCode,
    SignOffDecision,
    SignOffTargetKind,
    ValidationError,
    semantic_digest,
)

from .gates import credential_value, digest_value


EXTERNAL_SIGN_OFF_OPERATION = "external_sign_off"


@dataclass(frozen=True, slots=True)
class ExternalSignOffTarget:
    """The exact sealed release content, or one explicitly authorized member."""

    target_kind: SignOffTargetKind
    content_manifest_ref: ReleaseContentManifestRef
    member_role: ManifestMemberRole | None
    member_digest: ContentDigest | None

    def __post_init__(self) -> None:
        if type(self.target_kind) is not SignOffTargetKind:
            raise ValidationError("target_kind must be an exact SignOffTargetKind")
        if type(self.content_manifest_ref) is not ReleaseContentManifestRef:
            raise ValidationError(
                "content_manifest_ref must be an exact ReleaseContentManifestRef"
            )
        if self.target_kind is SignOffTargetKind.RELEASE_CONTENT:
            if self.member_role is not None or self.member_digest is not None:
                raise ValidationError(
                    "a release-content target must not name a manifest member"
                )
        elif self.target_kind is SignOffTargetKind.MANIFEST_MEMBER:
            if (
                type(self.member_role) is not ManifestMemberRole
                or type(self.member_digest) is not ContentDigest
            ):
                raise ValidationError(
                    "a manifest-member target requires its exact member role and digest"
                )
        else:
            raise ValidationError(
                "an external sign-off cannot target a review-target manifest"
            )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "target_kind": self.target_kind.value,
            "release_content_manifest_id": (
                self.content_manifest_ref.release_content_manifest_id.value
            ),
            "release_content_semantic_digest": digest_value(
                self.content_manifest_ref.semantic_digest
            ),
            "member_role": (
                self.member_role.value if self.member_role is not None else None
            ),
            "member_digest": (
                digest_value(self.member_digest) if self.member_digest is not None else None
            ),
        }

    @property
    def target_identity(self) -> str:
        if self.member_role is None:
            return self.content_manifest_ref.release_content_manifest_id.value
        return (
            f"{self.content_manifest_ref.release_content_manifest_id.value}"
            f"#{self.member_role.value}"
        )

    @property
    def target_digest(self) -> ContentDigest:
        if self.member_digest is None:
            return self.content_manifest_ref.semantic_digest
        return self.member_digest


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


def _intent_payload(
    production_id: ProductionId,
    gate_code: GateCode,
    credential: ActorCredentialRef,
    role: RoleCode,
    target: ExternalSignOffTarget,
    decision: SignOffDecision,
    signed_at_us: int,
) -> dict[str, JsonValue]:
    return {
        "production_id": production_id.value,
        "gate_code": gate_code.value,
        "credential": credential_value(credential),
        "role": role.value,
        "target": target.payload(),
        "decision": decision.value,
        "signed_at_us": signed_at_us,
    }


def external_signoff_intent_digest(
    *,
    credential: ActorCredentialRef,
    role: RoleCode,
    gate_code: GateCode,
    production_id: ProductionId,
    target: ExternalSignOffTarget,
    decision: SignOffDecision,
    signed_at_us: int,
) -> ContentDigest:
    """Hash the complete proof-excluded external sign-off intent."""
    for field_name, value, expected in (
        ("credential", credential, ActorCredentialRef),
        ("role", role, RoleCode),
        ("gate_code", gate_code, GateCode),
        ("production_id", production_id, ProductionId),
        ("target", target, ExternalSignOffTarget),
        ("decision", decision, SignOffDecision),
    ):
        _require_exact(value, expected, field_name)
    if type(signed_at_us) is not int or signed_at_us <= 0:
        raise ValidationError("signed_at_us must be a positive integer")
    return semantic_digest(
        "heritage-signoff-intent-v1",
        _intent_payload(
            production_id, gate_code, credential, role, target, decision, signed_at_us
        ),
    )


def external_signoff_context_digest(
    *,
    sign_off_intent_digest: ContentDigest,
    actor_id: ActorId,
    role: RoleCode,
    target: ExternalSignOffTarget,
) -> ContentDigest:
    """Bind an intent digest to its actor, role, typed target, and operation kind."""
    for field_name, value, expected in (
        ("sign_off_intent_digest", sign_off_intent_digest, ContentDigest),
        ("actor_id", actor_id, ActorId),
        ("role", role, RoleCode),
        ("target", target, ExternalSignOffTarget),
    ):
        _require_exact(value, expected, field_name)
    return semantic_digest(
        "heritage-signoff-context-v1",
        {
            "semantic_payload_digest": digest_value(sign_off_intent_digest),
            "actor_id": actor_id.value,
            "role": role.value,
            "target_kind": target.target_kind.value,
            "target_id": target.target_identity,
            "target_digest": digest_value(target.target_digest),
            "operation_kind": EXTERNAL_SIGN_OFF_OPERATION,
            "schema_version": 1,
        },
    )


def _assurance_value(value: ActorAssuranceEvidence) -> dict[str, JsonValue]:
    if value.kind is ActorAssuranceKind.VERIFIED_SIGNATURE:
        return {
            "kind": value.kind.value,
            "signed_context_digest": digest_value(value.signed_context_digest),
            "proof_algorithm": value.proof.algorithm,
            "proof_fingerprint": digest_value(value.proof.credential_fingerprint),
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
    production_id: ProductionId,
    gate_code: GateCode,
    credential: ActorCredentialRef,
    assurance: ActorAssuranceEvidence,
    role: RoleCode,
    target: ExternalSignOffTarget,
    decision: SignOffDecision,
    signed_at_us: int,
) -> dict[str, JsonValue]:
    return {
        "production_id": production_id.value,
        "gate_code": gate_code.value,
        "credential": credential_value(credential),
        "assurance_evidence": _assurance_value(assurance),
        "role": role.value,
        "target": target.payload(),
        "decision": decision.value,
        "signed_at_us": signed_at_us,
    }


@dataclass(frozen=True, slots=True)
class ExternalSignOff:
    """Immutable, append-only external sign-off evidence owned by Production."""

    production_id: ProductionId
    gate_code: GateCode
    credential: ActorCredentialRef
    assurance: ActorAssuranceEvidence
    role: RoleCode
    target: ExternalSignOffTarget
    decision: SignOffDecision
    signed_at_us: int
    sign_off_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("production_id", self.production_id, ProductionId),
            ("gate_code", self.gate_code, GateCode),
            ("credential", self.credential, ActorCredentialRef),
            ("assurance", self.assurance, ActorAssuranceEvidence),
            ("role", self.role, RoleCode),
            ("target", self.target, ExternalSignOffTarget),
            ("decision", self.decision, SignOffDecision),
            ("sign_off_digest", self.sign_off_digest, ContentDigest),
        ):
            _require_exact(value, expected, field_name)
        if type(self.signed_at_us) is not int or self.signed_at_us <= 0:
            raise ValidationError("signed_at_us must be a positive integer")

        validated_assurance = self.assurance.validated()
        if validated_assurance.credential != self.credential:
            raise ValidationError("sign-off assurance does not match its credential")
        object.__setattr__(self, "credential", validated_assurance.credential)
        object.__setattr__(self, "assurance", validated_assurance)

        if validated_assurance.kind is ActorAssuranceKind.VERIFIED_SIGNATURE:
            intent_digest = external_signoff_intent_digest(
                credential=self.credential,
                role=self.role,
                gate_code=self.gate_code,
                production_id=self.production_id,
                target=self.target,
                decision=self.decision,
                signed_at_us=self.signed_at_us,
            )
            expected_context = external_signoff_context_digest(
                sign_off_intent_digest=intent_digest,
                actor_id=self.credential.actor_id,
                role=self.role,
                target=self.target,
            )
            if validated_assurance.signed_context_digest != expected_context:
                raise ValidationError(
                    "signature context does not bind this exact Production, role, and target"
                )

        expected_digest = semantic_digest(
            "heritage-signoff-v1",
            _sign_off_payload(
                self.production_id,
                self.gate_code,
                self.credential,
                self.assurance,
                self.role,
                self.target,
                self.decision,
                self.signed_at_us,
            ),
        )
        if expected_digest != self.sign_off_digest:
            raise ValidationError("sign-off digest does not match its semantic evidence")

    @classmethod
    def seal(
        cls,
        *,
        production_id: ProductionId,
        gate_code: GateCode,
        credential: ActorCredentialRef,
        assurance: ActorAssuranceEvidence,
        role: RoleCode,
        target: ExternalSignOffTarget,
        decision: SignOffDecision,
        signed_at_us: int,
    ) -> ExternalSignOff:
        try:
            digest = semantic_digest(
                "heritage-signoff-v1",
                _sign_off_payload(
                    production_id,
                    gate_code,
                    credential,
                    assurance,
                    role,
                    target,
                    decision,
                    signed_at_us,
                ),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed external sign-off semantic input") from error
        return cls(
            production_id,
            gate_code,
            credential,
            assurance,
            role,
            target,
            decision,
            signed_at_us,
            digest,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        production_id: ProductionId,
        gate_code: GateCode,
        credential: ActorCredentialRef,
        assurance: ActorAssuranceEvidence,
        role: RoleCode,
        target: ExternalSignOffTarget,
        decision: SignOffDecision,
        signed_at_us: int,
        sign_off_digest: ContentDigest,
    ) -> ExternalSignOff:
        return cls(
            production_id,
            gate_code,
            credential,
            assurance,
            role,
            target,
            decision,
            signed_at_us,
            sign_off_digest,
        )

    def validated(self) -> ExternalSignOff:
        return type(self).reconstitute(
            production_id=self.production_id,
            gate_code=self.gate_code,
            credential=self.credential,
            assurance=self.assurance,
            role=self.role,
            target=self.target,
            decision=self.decision,
            signed_at_us=self.signed_at_us,
            sign_off_digest=self.sign_off_digest,
        )

    @property
    def actor_id(self) -> ActorId:
        return self.credential.actor_id
