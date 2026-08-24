"""External gate requirements and sealed gate sets.

Release defines gate and eligibility concepts; Production owns the data and is
the only aggregate that appends a gate set or records a sign-off against one.
Keeping the definitions here makes the dependency spine strictly one-way
(production -> release), so no Production/Release cycle can form.

A requirement pins an exact `ActorCredentialRef`, never merely an `ActorId`: a
second credential belonging to the same actor must never discharge a gate that
pinned a specific verification key.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    ArtifactId,
    ArtifactRef,
    AssuranceLevel,
    ContentDigest,
    ExternalGateSetId,
    ExternalGateSetRef,
    GateCode,
    GateScope,
    JsonValue,
    ManifestMemberRole,
    ProductionId,
    RoleCode,
    SignOffTargetRule,
    ValidationError,
    assurance_satisfies,
    semantic_digest,
)


def digest_value(value: ContentDigest) -> dict[str, JsonValue]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


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
            {
                "artifact_id": value.public_key_artifact.artifact_id.value,
                "content_digest": digest_value(value.public_key_artifact.content_digest),
                "byte_size": value.public_key_artifact.byte_size,
                "media_type": value.public_key_artifact.media_type,
            }
            if value.public_key_artifact is not None
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


def target_rule_value(value: SignOffTargetRule) -> dict[str, JsonValue]:
    return {
        "target_kind": value.target_kind.value,
        "required_member_role": (
            value.required_member_role.value
            if value.required_member_role is not None
            else None
        ),
    }


@dataclass(frozen=True, slots=True)
class ExternalGateRequirement:
    """One named Production gate pinning an exact credential and typed target."""

    gate_code: GateCode
    scope: GateScope
    role: RoleCode
    credential: ActorCredentialRef
    minimum_assurance: AssuranceLevel
    target_rule: SignOffTargetRule

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("gate_code", self.gate_code, GateCode),
            ("scope", self.scope, GateScope),
            ("role", self.role, RoleCode),
            ("credential", self.credential, ActorCredentialRef),
            ("minimum_assurance", self.minimum_assurance, AssuranceLevel),
            ("target_rule", self.target_rule, SignOffTargetRule),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if self.minimum_assurance is AssuranceLevel.UNVERIFIED:
            raise ValidationError("canonical gates require at least steward attestation")
        if not self.target_rule.permits_scope(self.scope):
            raise ValidationError("gate target rule does not belong to its declared scope")
        if not assurance_satisfies(self.credential.assurance, self.minimum_assurance):
            raise ValidationError("pinned credential assurance is below the gate minimum")

    @property
    def actor_id(self) -> ActorId:
        return self.credential.actor_id

    @property
    def semantic_key(self) -> tuple[str, ...]:
        return (
            self.scope.value,
            self.role.value,
            *credential_key(self.credential),
            self.target_rule.target_kind.value,
            (
                self.target_rule.required_member_role.value
                if self.target_rule.required_member_role is not None
                else ""
            ),
        )

    def is_satisfied_by(self, sign_off: object) -> bool:
        """Report whether one immutable external sign-off discharges this gate."""
        from .signoffs import ExternalSignOff
        from heritage_production.domain.shared import SignOffDecision

        if type(sign_off) is not ExternalSignOff:
            return False
        if sign_off.decision is not SignOffDecision.APPROVED:
            return False
        # The pinned credential must match exactly; an actor may hold several.
        if sign_off.role != self.role or sign_off.credential != self.credential:
            return False
        if sign_off.target.target_kind is not self.target_rule.target_kind:
            return False
        if (
            self.target_rule.required_member_role is not None
            and sign_off.target.member_role != self.target_rule.required_member_role
        ):
            return False
        return assurance_satisfies(sign_off.assurance.assurance, self.minimum_assurance)

    def validated(self) -> ExternalGateRequirement:
        """Reconstruct this requirement and every reachable child value."""
        return ExternalGateRequirement(
            GateCode(self.gate_code.value),
            self.scope,
            RoleCode(self.role.value),
            revalidate_credential(self.credential, field="gate credential"),
            self.minimum_assurance,
            SignOffTargetRule(
                self.target_rule.target_kind,
                (
                    ManifestMemberRole(self.target_rule.required_member_role.value)
                    if self.target_rule.required_member_role is not None
                    else None
                ),
            ),
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "gate_code": self.gate_code.value,
            "scope": self.scope.value,
            "role": self.role.value,
            "credential": credential_value(self.credential),
            "minimum_assurance": self.minimum_assurance.value,
            "target_rule": target_rule_value(self.target_rule),
        }


def _gate_set_payload(
    production_id: ProductionId,
    requirements: tuple[ExternalGateRequirement, ...],
) -> dict[str, JsonValue]:
    return {
        "production_id": production_id.value,
        "requirements": [value.payload() for value in requirements],
    }


@dataclass(frozen=True, slots=True)
class ExternalGateSet:
    """An immutable, append-only Production gate configuration."""

    external_gate_set_id: ExternalGateSetId
    production_id: ProductionId
    requirements: tuple[ExternalGateRequirement, ...]
    configured_by: ActorId
    configured_at_us: int
    content_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("external_gate_set_id", self.external_gate_set_id, ExternalGateSetId),
            ("production_id", self.production_id, ProductionId),
            ("configured_by", self.configured_by, ActorId),
            ("content_digest", self.content_digest, ContentDigest),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if type(self.requirements) is not tuple or not all(
            type(value) is ExternalGateRequirement for value in self.requirements
        ):
            raise ValidationError(
                "requirements must be an immutable tuple of ExternalGateRequirement"
            )
        if type(self.configured_at_us) is not int or self.configured_at_us <= 0:
            raise ValidationError("configured_at_us must be a positive integer")

        gate_codes = tuple(value.gate_code.value for value in self.requirements)
        if gate_codes != tuple(sorted(gate_codes)):
            raise ValidationError("gate requirements must already be in canonical order")
        if len(set(gate_codes)) != len(gate_codes):
            raise ValidationError("gate codes must be unique within a gate set")
        semantic_keys = tuple(value.semantic_key for value in self.requirements)
        if len(set(semantic_keys)) != len(semantic_keys):
            raise ValidationError("gate requirements must not repeat a semantic key")

        expected_digest = semantic_digest(
            "heritage-production-gates-v1",
            _gate_set_payload(self.production_id, self.requirements),
        )
        if expected_digest != self.content_digest:
            raise ValidationError("gate-set digest does not match its requirements")

    @classmethod
    def seal(
        cls,
        *,
        external_gate_set_id: ExternalGateSetId,
        production_id: ProductionId,
        requirements: tuple[ExternalGateRequirement, ...],
        configured_by: ActorId,
        configured_at_us: int,
    ) -> ExternalGateSet:
        try:
            digest = semantic_digest(
                "heritage-production-gates-v1",
                _gate_set_payload(production_id, requirements),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed gate-set semantic input") from error
        return cls(
            external_gate_set_id,
            production_id,
            requirements,
            configured_by,
            configured_at_us,
            digest,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        external_gate_set_id: ExternalGateSetId,
        production_id: ProductionId,
        requirements: tuple[ExternalGateRequirement, ...],
        configured_by: ActorId,
        configured_at_us: int,
        content_digest: ContentDigest,
    ) -> ExternalGateSet:
        return cls(
            external_gate_set_id,
            production_id,
            requirements,
            configured_by,
            configured_at_us,
            content_digest,
        )

    def validated(self) -> ExternalGateSet:
        """Reconstruct this gate set and every reachable requirement."""
        return type(self).reconstitute(
            external_gate_set_id=ExternalGateSetId(self.external_gate_set_id.value),
            production_id=ProductionId(self.production_id.value),
            requirements=tuple(value.validated() for value in self.requirements),
            configured_by=ActorId(self.configured_by.value),
            configured_at_us=self.configured_at_us,
            content_digest=ContentDigest(
                self.content_digest.algorithm, self.content_digest.hex_digest
            ),
        )

    def requirements_for(self, scope: GateScope) -> tuple[ExternalGateRequirement, ...]:
        if type(scope) is not GateScope:
            raise ValidationError("scope must be an exact GateScope")
        return tuple(value for value in self.requirements if value.scope is scope)

    @property
    def ref(self) -> ExternalGateSetRef:
        return ExternalGateSetRef(self.external_gate_set_id, self.content_digest)
