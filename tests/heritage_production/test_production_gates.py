"""Production-owned external gate sets and immutable external sign-offs."""

from __future__ import annotations

from copy import copy
import unittest

from heritage_production.domain.production import (
    gate_is_satisfied_by,
    ExternalGateRequirement,
    ExternalGateSet,
    ExternalSignOff,
    ExternalSignOffTarget,
    external_signoff_context_digest,
    external_signoff_intent_digest,
)
from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
    ActorAssuranceKind,
    ActorCredentialRef,
    AssuranceLevel,
    ContentDigest,
    ExternalGateSetId,
    ExternalGateSetRef,
    GateCode,
    GateScope,
    ManifestMemberRole,
    ProductionId,
    RoleCode,
    SignatureProof,
    SignOffDecision,
    SignOffTargetKind,
    SignOffTargetRule,
    ValidationError,
    semantic_digest,
)

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    artifact,
    attested_credential,
    content_manifest_ref,
    digest,
    production_id,
    uid,
    verified_credential,
)


FINGERPRINT = digest("c")
MEMBER_ROLE = ManifestMemberRole("source-audio")


def gate_set_id() -> ExternalGateSetId:
    return ExternalGateSetId(uid(30))


def release_target() -> ExternalSignOffTarget:
    return ExternalSignOffTarget(
        SignOffTargetKind.RELEASE_CONTENT, content_manifest_ref(), None, None
    )


def member_target() -> ExternalSignOffTarget:
    return ExternalSignOffTarget(
        SignOffTargetKind.MANIFEST_MEMBER, content_manifest_ref(), MEMBER_ROLE, digest("d")
    )


def rights_holder_requirement(
    *,
    scope: GateScope = GateScope.EXTERNAL_RELEASE,
    target_rule: SignOffTargetRule | None = None,
) -> ExternalGateRequirement:
    return ExternalGateRequirement(
        GateCode("rights-holder-approval"),
        scope,
        RoleCode("rights-holder"),
        verified_credential(40, FINGERPRINT),
        AssuranceLevel.VERIFIED_SIGNATURE,
        target_rule or SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
    )


def review_requirement() -> ExternalGateRequirement:
    return ExternalGateRequirement(
        GateCode("archivist-review"),
        GateScope.REVIEW,
        RoleCode("archivist"),
        attested_credential(44),
        AssuranceLevel.STEWARD_ATTESTED,
        SignOffTargetRule(SignOffTargetKind.REVIEW_TARGET),
    )


def seal_gate_set(
    requirements: tuple[ExternalGateRequirement, ...] | None = None,
) -> ExternalGateSet:
    return ExternalGateSet.seal(
        external_gate_set_id=gate_set_id(),
        production_id=production_id(),
        requirements=(
            requirements
            if requirements is not None
            else (review_requirement(), rights_holder_requirement())
        ),
        configured_by=actor(20),
        configured_at_us=1_700_000_000_000_000,
    )


def verified_sign_off(
    *,
    gate_code: GateCode = GateCode("rights-holder-approval"),
    role: RoleCode = RoleCode("rights-holder"),
    target: ExternalSignOffTarget | None = None,
    decision: SignOffDecision = SignOffDecision.APPROVED,
    signed_at_us: int = 1_700_000_000_000_001,
    owner: ProductionId | None = None,
    credential: ActorCredentialRef | None = None,
) -> ExternalSignOff:
    credential = credential or verified_credential(40, FINGERPRINT)
    bound_target = target or release_target()
    owning_production = owner or production_id()
    intent = external_signoff_intent_digest(
        credential=credential,
        role=role,
        gate_code=gate_code,
        production_id=owning_production,
        target=bound_target,
        decision=decision,
        signed_at_us=signed_at_us,
    )
    context = external_signoff_context_digest(
        sign_off_intent_digest=intent,
        actor_id=credential.actor_id,
        role=role,
        target=bound_target,
    )
    assurance = ActorAssuranceEvidence.verified_signature(
        credential=credential,
        signed_context_digest=context,
        proof=SignatureProof(
            "ed25519",
            credential.credential_fingerprint,
            artifact(60, "e", "application/octet-stream"),
        ),
    )
    return ExternalSignOff.seal(
        production_id=owning_production,
        gate_code=gate_code,
        credential=credential,
        assurance=assurance,
        role=role,
        target=bound_target,
        decision=decision,
        signed_at_us=signed_at_us,
    )


def attested_sign_off(
    *, gate_code: GateCode = GateCode("archivist-approval")
) -> ExternalSignOff:
    credential = attested_credential(44)
    return ExternalSignOff.seal(
        production_id=production_id(),
        gate_code=gate_code,
        credential=credential,
        assurance=ActorAssuranceEvidence.steward_attested(
            credential=credential,
            attesting_steward_id=actor(20),
            reason="in-person confirmation recorded by the steward",
            attested_at_us=1_700_000_000_000_002,
        ),
        role=RoleCode("archivist"),
        target=release_target(),
        decision=SignOffDecision.APPROVED,
        signed_at_us=1_700_000_000_000_002,
    )


class ExternalGateRequirementTests(unittest.TestCase):
    def test_requirement_binds_scope_role_credential_and_typed_target(self) -> None:
        requirement = rights_holder_requirement()

        self.assertIs(requirement.scope, GateScope.EXTERNAL_RELEASE)
        self.assertEqual(requirement.actor_id, verified_credential(40, FINGERPRINT).actor_id)

    def test_target_rule_must_belong_to_the_declared_scope(self) -> None:
        with self.assertRaises(ValidationError):
            rights_holder_requirement(
                target_rule=SignOffTargetRule(SignOffTargetKind.REVIEW_TARGET)
            )
        with self.assertRaises(ValidationError):
            rights_holder_requirement(
                scope=GateScope.REVIEW,
                target_rule=SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
            )

    def test_credential_assurance_must_reach_the_declared_minimum(self) -> None:
        with self.assertRaises(ValidationError):
            ExternalGateRequirement(
                GateCode("rights-holder-approval"),
                GateScope.EXTERNAL_RELEASE,
                RoleCode("rights-holder"),
                attested_credential(44),
                AssuranceLevel.VERIFIED_SIGNATURE,
                SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
            )

    def test_unverified_minimum_assurance_is_never_a_canonical_gate(self) -> None:
        with self.assertRaises(ValidationError):
            ExternalGateRequirement(
                GateCode("weak"),
                GateScope.EXTERNAL_RELEASE,
                RoleCode("rights-holder"),
                attested_credential(44),
                AssuranceLevel.UNVERIFIED,
                SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
            )


class ExternalGateSetTests(unittest.TestCase):
    def test_explicit_empty_gate_set_is_supported(self) -> None:
        gate_set = seal_gate_set(())

        self.assertEqual(gate_set.requirements, ())
        self.assertEqual(
            gate_set.ref, ExternalGateSetRef(gate_set.external_gate_set_id, gate_set.content_digest)
        )

    def test_gate_set_digest_matches_its_literal_documented_preimage(self) -> None:
        gate_set = seal_gate_set(())

        expected = semantic_digest(
            "heritage-production-gates-v1",
            {"production_id": production_id().value, "requirements": []},
        )

        self.assertEqual(gate_set.content_digest, expected)

    def test_gate_set_identity_and_time_are_excluded_from_the_preimage(self) -> None:
        first = seal_gate_set()
        second = ExternalGateSet.seal(
            external_gate_set_id=ExternalGateSetId(uid(31)),
            production_id=production_id(),
            requirements=(review_requirement(), rights_holder_requirement()),
            configured_by=actor(20),
            configured_at_us=1_900_000_000_000_000,
        )

        self.assertNotEqual(first.external_gate_set_id, second.external_gate_set_id)
        self.assertEqual(first.content_digest, second.content_digest)

    def test_noncanonical_requirement_order_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            seal_gate_set((rights_holder_requirement(), review_requirement()))

    def test_duplicate_gate_codes_and_semantic_keys_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            seal_gate_set((rights_holder_requirement(), rights_holder_requirement()))

        alternate_code = ExternalGateRequirement(
            GateCode("zz-duplicate-semantics"),
            GateScope.EXTERNAL_RELEASE,
            RoleCode("rights-holder"),
            verified_credential(40, FINGERPRINT),
            AssuranceLevel.VERIFIED_SIGNATURE,
            SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
        )
        with self.assertRaises(ValidationError):
            seal_gate_set((rights_holder_requirement(), alternate_code))

    def test_reconstitute_requires_the_exact_digest_and_emits_no_events(self) -> None:
        gate_set = seal_gate_set()

        restored = ExternalGateSet.reconstitute(
            external_gate_set_id=gate_set.external_gate_set_id,
            production_id=gate_set.production_id,
            requirements=gate_set.requirements,
            configured_by=gate_set.configured_by,
            configured_at_us=gate_set.configured_at_us,
            content_digest=gate_set.content_digest,
        )

        self.assertEqual(restored, gate_set)
        self.assertFalse(hasattr(gate_set, "pull_events"))

        with self.assertRaises(ValidationError):
            ExternalGateSet.reconstitute(
                external_gate_set_id=gate_set.external_gate_set_id,
                production_id=gate_set.production_id,
                requirements=gate_set.requirements,
                configured_by=gate_set.configured_by,
                configured_at_us=gate_set.configured_at_us,
                content_digest=digest("f"),
            )

    def test_scoped_requirement_views_separate_review_from_external_release(self) -> None:
        gate_set = seal_gate_set()

        self.assertEqual(
            gate_set.requirements_for(GateScope.REVIEW), (review_requirement(),)
        )
        self.assertEqual(
            gate_set.requirements_for(GateScope.EXTERNAL_RELEASE),
            (rights_holder_requirement(),),
        )


class ExternalSignOffTargetTests(unittest.TestCase):
    def test_release_content_target_forbids_member_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ExternalSignOffTarget(
                SignOffTargetKind.RELEASE_CONTENT,
                content_manifest_ref(),
                MEMBER_ROLE,
                digest("d"),
            )

    def test_manifest_member_target_requires_both_member_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ExternalSignOffTarget(
                SignOffTargetKind.MANIFEST_MEMBER, content_manifest_ref(), MEMBER_ROLE, None
            )

    def test_review_target_kind_is_not_an_external_release_target(self) -> None:
        with self.assertRaises(ValidationError):
            ExternalSignOffTarget(
                SignOffTargetKind.REVIEW_TARGET, content_manifest_ref(), None, None
            )


class ExternalSignOffTests(unittest.TestCase):
    def test_verified_sign_off_binds_its_signed_context(self) -> None:
        sign_off = verified_sign_off()

        self.assertIs(sign_off.assurance.kind, ActorAssuranceKind.VERIFIED_SIGNATURE)
        self.assertIs(sign_off.decision, SignOffDecision.APPROVED)
        self.assertEqual(sign_off, sign_off.validated())

    def test_steward_attested_sign_off_is_canonical_evidence(self) -> None:
        sign_off = attested_sign_off()

        self.assertIs(sign_off.assurance.kind, ActorAssuranceKind.STEWARD_ATTESTATION)
        self.assertIs(sign_off.assurance.assurance, AssuranceLevel.STEWARD_ATTESTED)

    def test_declined_sign_off_is_representable_evidence(self) -> None:
        sign_off = verified_sign_off(decision=SignOffDecision.DECLINED)

        self.assertIs(sign_off.decision, SignOffDecision.DECLINED)

    def test_proof_bytes_and_artifact_are_excluded_from_the_signoff_digest(self) -> None:
        sign_off = verified_sign_off()
        other_proof_artifact = artifact(70, "9", "application/octet-stream")
        replacement_assurance = ActorAssuranceEvidence.verified_signature(
            credential=sign_off.credential,
            signed_context_digest=sign_off.assurance.signed_context_digest,
            proof=SignatureProof("ed25519", FINGERPRINT, other_proof_artifact),
        )

        rebuilt = ExternalSignOff.seal(
            production_id=sign_off.production_id,
            gate_code=sign_off.gate_code,
            credential=sign_off.credential,
            assurance=replacement_assurance,
            role=sign_off.role,
            target=sign_off.target,
            decision=sign_off.decision,
            signed_at_us=sign_off.signed_at_us,
        )

        self.assertNotEqual(sign_off.assurance.proof.artifact, rebuilt.assurance.proof.artifact)
        self.assertEqual(sign_off.sign_off_digest, rebuilt.sign_off_digest)

    def test_cross_production_signature_replay_is_rejected(self) -> None:
        sign_off = verified_sign_off()
        foreign_production = ProductionId(uid(999))

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=foreign_production,
                gate_code=sign_off.gate_code,
                credential=sign_off.credential,
                assurance=sign_off.assurance,
                role=sign_off.role,
                target=sign_off.target,
                decision=sign_off.decision,
                signed_at_us=sign_off.signed_at_us,
            )

    def test_cross_role_and_cross_content_replay_is_rejected(self) -> None:
        sign_off = verified_sign_off()

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=sign_off.production_id,
                gate_code=sign_off.gate_code,
                credential=sign_off.credential,
                assurance=sign_off.assurance,
                role=RoleCode("subject-matter-expert"),
                target=sign_off.target,
                decision=sign_off.decision,
                signed_at_us=sign_off.signed_at_us,
            )

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=sign_off.production_id,
                gate_code=sign_off.gate_code,
                credential=sign_off.credential,
                assurance=sign_off.assurance,
                role=sign_off.role,
                target=ExternalSignOffTarget(
                    SignOffTargetKind.RELEASE_CONTENT, content_manifest_ref("8"), None, None
                ),
                decision=sign_off.decision,
                signed_at_us=sign_off.signed_at_us,
            )

    def test_member_target_replay_against_another_member_is_rejected(self) -> None:
        sign_off = verified_sign_off(target=member_target())

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=sign_off.production_id,
                gate_code=sign_off.gate_code,
                credential=sign_off.credential,
                assurance=sign_off.assurance,
                role=sign_off.role,
                target=ExternalSignOffTarget(
                    SignOffTargetKind.MANIFEST_MEMBER,
                    content_manifest_ref(),
                    ManifestMemberRole("transcript-json"),
                    digest("d"),
                ),
                decision=sign_off.decision,
                signed_at_us=sign_off.signed_at_us,
            )

    def test_decision_and_time_replay_is_rejected(self) -> None:
        sign_off = verified_sign_off()

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=sign_off.production_id,
                gate_code=sign_off.gate_code,
                credential=sign_off.credential,
                assurance=sign_off.assurance,
                role=sign_off.role,
                target=sign_off.target,
                decision=SignOffDecision.DECLINED,
                signed_at_us=sign_off.signed_at_us,
            )

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=sign_off.production_id,
                gate_code=sign_off.gate_code,
                credential=sign_off.credential,
                assurance=sign_off.assurance,
                role=sign_off.role,
                target=sign_off.target,
                decision=sign_off.decision,
                signed_at_us=sign_off.signed_at_us + 1,
            )

    def test_review_sign_off_context_cannot_be_replayed_as_an_external_sign_off(
        self,
    ) -> None:
        sign_off = verified_sign_off()
        intent = external_signoff_intent_digest(
            credential=sign_off.credential,
            role=sign_off.role,
            gate_code=sign_off.gate_code,
            production_id=sign_off.production_id,
            target=sign_off.target,
            decision=sign_off.decision,
            signed_at_us=sign_off.signed_at_us,
        )
        foreign_context = semantic_digest(
            "heritage-signoff-context-v1",
            {
                "semantic_payload_digest": {
                    "algorithm": intent.algorithm,
                    "hex_digest": intent.hex_digest,
                },
                "actor_id": sign_off.credential.actor_id.value,
                "role": sign_off.role.value,
                "target_kind": SignOffTargetKind.RELEASE_CONTENT.value,
                "target_id": content_manifest_ref().release_content_manifest_id.value,
                "target_digest": {
                    "algorithm": "sha256",
                    "hex_digest": content_manifest_ref().semantic_digest.hex_digest,
                },
                "operation_kind": "review_sign_off",
                "schema_version": 1,
            },
        )
        forged = ActorAssuranceEvidence.verified_signature(
            credential=sign_off.credential,
            signed_context_digest=foreign_context,
            proof=sign_off.assurance.proof,
        )

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=sign_off.production_id,
                gate_code=sign_off.gate_code,
                credential=sign_off.credential,
                assurance=forged,
                role=sign_off.role,
                target=sign_off.target,
                decision=sign_off.decision,
                signed_at_us=sign_off.signed_at_us,
            )

    def test_assurance_credential_must_match_the_sign_off_credential(self) -> None:
        sign_off = verified_sign_off()
        other = attested_sign_off()

        with self.assertRaises(ValidationError):
            ExternalSignOff.seal(
                production_id=sign_off.production_id,
                gate_code=sign_off.gate_code,
                credential=other.credential,
                assurance=sign_off.assurance,
                role=sign_off.role,
                target=sign_off.target,
                decision=sign_off.decision,
                signed_at_us=sign_off.signed_at_us,
            )

    def test_tampered_sign_off_digest_is_rejected_on_revalidation(self) -> None:
        sign_off = verified_sign_off()
        forged = copy(sign_off)
        object.__setattr__(forged, "sign_off_digest", digest("f"))

        with self.assertRaises(ValidationError):
            forged.validated()

    def test_signoff_digest_matches_the_documented_preimage_shape(self) -> None:
        sign_off = attested_sign_off()

        expected = semantic_digest(
            "heritage-signoff-v1",
            {
                "production_id": sign_off.production_id.value,
                "gate_code": sign_off.gate_code.value,
                "credential": {
                    "actor_id": sign_off.credential.actor_id.value,
                    "verification_method": sign_off.credential.verification_method.value,
                    "assurance": sign_off.credential.assurance.value,
                    "credential_fingerprint": None,
                    "public_key_artifact": None,
                },
                "assurance_evidence": {
                    "kind": ActorAssuranceKind.STEWARD_ATTESTATION.value,
                    "signed_context_digest": None,
                    "proof_algorithm": None,
                    "proof_fingerprint": None,
                    "attesting_steward_id": actor(20).value,
                    "attestation_reason": "in-person confirmation recorded by the steward",
                    "attested_at_us": 1_700_000_000_000_002,
                },
                "role": sign_off.role.value,
                "target": {
                    "target_kind": SignOffTargetKind.RELEASE_CONTENT.value,
                    "release_content_manifest_id": (
                        content_manifest_ref().release_content_manifest_id.value
                    ),
                    "release_content_semantic_digest": {
                        "algorithm": "sha256",
                        "hex_digest": content_manifest_ref().semantic_digest.hex_digest,
                    },
                    "member_role": None,
                    "member_digest": None,
                },
                "decision": SignOffDecision.APPROVED.value,
                "signed_at_us": 1_700_000_000_000_002,
            },
        )

        self.assertEqual(sign_off.sign_off_digest, expected)


class GateSatisfactionTests(unittest.TestCase):
    def test_requirement_accepts_only_its_pinned_credential_and_target(self) -> None:
        requirement = rights_holder_requirement()
        sign_off = verified_sign_off()

        self.assertTrue(gate_is_satisfied_by(requirement, sign_off))
        self.assertFalse(gate_is_satisfied_by(requirement, attested_sign_off()))
        self.assertFalse(
            gate_is_satisfied_by(requirement, verified_sign_off(decision=SignOffDecision.DECLINED))
        )

    def test_verified_signature_satisfies_an_attested_minimum(self) -> None:
        requirement = ExternalGateRequirement(
            GateCode("rights-holder-approval"),
            GateScope.EXTERNAL_RELEASE,
            RoleCode("rights-holder"),
            verified_credential(40, FINGERPRINT),
            AssuranceLevel.STEWARD_ATTESTED,
            SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
        )

        self.assertTrue(gate_is_satisfied_by(requirement, verified_sign_off()))

    def test_attested_evidence_never_satisfies_a_verified_minimum(self) -> None:
        requirement = ExternalGateRequirement(
            GateCode("archivist-approval"),
            GateScope.EXTERNAL_RELEASE,
            RoleCode("archivist"),
            attested_credential(44),
            AssuranceLevel.STEWARD_ATTESTED,
            SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
        )

        self.assertTrue(gate_is_satisfied_by(requirement, attested_sign_off()))

        stricter = ExternalGateRequirement(
            GateCode("archivist-approval"),
            GateScope.EXTERNAL_RELEASE,
            RoleCode("archivist"),
            verified_credential(44, FINGERPRINT),
            AssuranceLevel.VERIFIED_SIGNATURE,
            SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
        )

        self.assertFalse(gate_is_satisfied_by(stricter, attested_sign_off()))


if __name__ == "__main__":
    unittest.main()
