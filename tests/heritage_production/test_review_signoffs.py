from __future__ import annotations

from copy import copy
import unittest

import heritage_production.domain.review as review_domain

try:
    from heritage_production.domain.review import (
        ReviewSignOff,
        ReviewSignOffRequirement,
        ReviewRoundState,
        review_signoff_context_digest,
    )
except ImportError:
    ReviewSignOff = None  # type: ignore[assignment,misc]
    ReviewSignOffRequirement = None  # type: ignore[assignment,misc]
    review_signoff_context_digest = None  # type: ignore[assignment,misc]

from heritage_production.domain.review import ReviewRound
from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
    ActorCredentialRef,
    ActorId,
    ArtifactId,
    ArtifactRef,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    DomainEventId,
    RoleCode,
    SignOffDecision,
    SignatureProof,
    ValidationError,
)
from tests.heritage_production.test_review_rounds import make_target, uid


def artifact(suffix: int, character: str) -> ArtifactRef:
    return ArtifactRef(
        ArtifactId(uid(suffix)),
        ContentDigest("sha256", character * 64),
        64,
        "application/octet-stream",
    )


class ReviewSignOffTests(unittest.TestCase):
    def test_reconstitution_reuses_complete_signoff_attachment_invariants(self) -> None:
        target = make_target()
        credential = ActorCredentialRef(
            ActorId(uid(55)),
            CredentialVerificationMethod.STEWARD_ATTESTATION,
            AssuranceLevel.STEWARD_ATTESTED,
        )
        role = RoleCode("rights-holder")
        requirement = ReviewSignOffRequirement(
            credential, role, AssuranceLevel.STEWARD_ATTESTED
        )
        round_ = ReviewRound.open(
            review_round_id=target.review_round_id,
            production_id=target.production_id,
            edition_ref=target.edition_ref,
            target_manifest=target,
            rubric_ref=target.rubric_ref,
            package_schema_version=1,
            reviewer_assignments=(),
            sign_off_requirements=(requirement,),
            opened_by=ActorId(uid(56)),
            opened_at_us=1,
            event_id=DomainEventId(uid(57)),
            event_occurred_at_us=2,
        )
        round_.pull_events()
        assurance = ActorAssuranceEvidence.steward_attested(
            credential=credential,
            attesting_steward_id=ActorId(uid(58)),
            reason="Known steward",
            attested_at_us=3,
        )
        sign_off = ReviewSignOff.seal(
            credential=credential,
            assurance=assurance,
            role=role,
            target_ref=target.ref,
            decision=SignOffDecision.APPROVED,
            signed_at_us=4,
        )

        def restore(sign_offs: tuple[ReviewSignOff, ...]) -> ReviewRound:
            return ReviewRound.reconstitute(
                review_round_id=round_.review_round_id,
                production_id=round_.production_id,
                edition_ref=round_.edition_ref,
                target_manifest=round_.target_manifest,
                rubric_ref=round_.rubric_ref,
                package_schema_version=round_.package_schema_version,
                reviewer_assignments=round_.reviewer_assignments,
                sign_off_requirements=round_.sign_off_requirements,
                opened_by=round_.opened_by,
                opened_at_us=round_.opened_at_us,
                state=ReviewRoundState.OPEN,
                submissions=(),
                sign_offs=sign_offs,
                closure_snapshot=None,
                closed_evidence=None,
                closed_by=None,
                closed_at_us=None,
            )

        restored = restore((sign_off,))
        self.assertEqual(restored.sign_offs, (sign_off,))
        self.assertEqual(restored.pull_events(), ())

        weak_assurance = copy(sign_off.assurance)
        object.__setattr__(
            weak_assurance, "assurance", AssuranceLevel.UNVERIFIED
        )
        weak_sign_off = copy(sign_off)
        object.__setattr__(weak_sign_off, "assurance", weak_assurance)
        foreign_target = copy(sign_off)
        object.__setattr__(
            foreign_target,
            "target_ref",
            type(target.ref)(
                target.review_round_id,
                ContentDigest("sha256", "9" * 64),
                target.ref.artifact,
            ),
        )
        for name, invalid in (
            ("below-minimum-assurance", (weak_sign_off,)),
            ("duplicate-key", (sign_off, sign_off)),
            ("foreign-target", (foreign_target,)),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    restore(invalid)

    def test_verified_context_authenticates_complete_signoff_intent(self) -> None:
        self.assertTrue(
            hasattr(review_domain, "review_signoff_intent_digest"),
            "verified sign-offs need a non-circular complete-intent digest",
        )
        target = make_target()
        role = RoleCode("rights-holder")
        credential = ActorCredentialRef(
            ActorId(uid(60)),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            ContentDigest("sha256", "1" * 64),
            artifact(61, "2"),
        )
        intent_digest = review_domain.review_signoff_intent_digest(
            credential=credential,
            role=role,
            target_ref=target.ref,
            decision=SignOffDecision.APPROVED,
            signed_at_us=10,
        )
        self.assertEqual(
            intent_digest.hex_digest,
            "22f6d28fe6205a2fcb464cce1bc09c2c3814f9bf79d969ef184b470832b39e16",
        )
        context_digest = review_signoff_context_digest(
            sign_off_intent_digest=intent_digest,
            actor_id=credential.actor_id,
            role=role,
            target_ref=target.ref,
        )
        self.assertEqual(
            context_digest.hex_digest,
            "48e9fd1da6de84918d295ee934fde6f3c68c5bf93ae753600b6e3a18504e4f42",
        )
        assurance = ActorAssuranceEvidence.verified_signature(
            credential=credential,
            signed_context_digest=context_digest,
            proof=SignatureProof(
                "ed25519", credential.credential_fingerprint, artifact(64, "3")
            ),
        )
        sign_off = ReviewSignOff.seal(
            credential=credential,
            assurance=assurance,
            role=role,
            target_ref=target.ref,
            decision=SignOffDecision.APPROVED,
            signed_at_us=10,
        )
        self.assertEqual(
            sign_off.sign_off_digest.hex_digest,
            "a4864d6d183e90a67739c3c3870f66724909c8a084c0b5b70bff7555b585f873",
        )

        for decision, signed_at_us in (
            (SignOffDecision.DECLINED, 10),
            (SignOffDecision.APPROVED, 11),
        ):
            with self.subTest(decision=decision, signed_at_us=signed_at_us):
                with self.assertRaises(ValidationError):
                    ReviewSignOff.seal(
                        credential=credential,
                        assurance=assurance,
                        role=role,
                        target_ref=target.ref,
                        decision=decision,
                        signed_at_us=signed_at_us,
                    )

    def test_verified_signoff_binds_exact_role_target_and_excludes_proof_artifact(self) -> None:
        self.assertIsNotNone(ReviewSignOff, "review sign-off evidence must exist")
        target = make_target()
        role = RoleCode("rights-holder")
        credential = ActorCredentialRef(
            ActorId(uid(60)),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            ContentDigest("sha256", "1" * 64),
            artifact(61, "2"),
        )
        requirement = ReviewSignOffRequirement(
            credential, role, AssuranceLevel.VERIFIED_SIGNATURE
        )
        round_ = ReviewRound.open(
            review_round_id=target.review_round_id,
            production_id=target.production_id,
            edition_ref=target.edition_ref,
            target_manifest=target,
            rubric_ref=target.rubric_ref,
            package_schema_version=1,
            reviewer_assignments=(),
            sign_off_requirements=(requirement,),
            opened_by=ActorId(uid(62)),
            opened_at_us=1,
            event_id=DomainEventId(uid(63)),
            event_occurred_at_us=2,
        )
        round_.pull_events()
        context_digest = review_signoff_context_digest(
            sign_off_intent_digest=review_domain.review_signoff_intent_digest(
                credential=credential,
                role=role,
                target_ref=target.ref,
                decision=SignOffDecision.APPROVED,
                signed_at_us=10,
            ),
            actor_id=credential.actor_id,
            role=role,
            target_ref=target.ref,
        )

        def evidence(proof_suffix: int) -> ActorAssuranceEvidence:
            return ActorAssuranceEvidence.verified_signature(
                credential=credential,
                signed_context_digest=context_digest,
                proof=SignatureProof(
                    "ed25519", credential.credential_fingerprint, artifact(proof_suffix, "3")
                ),
            )

        first = ReviewSignOff.seal(
            credential=credential,
            assurance=evidence(64),
            role=role,
            target_ref=target.ref,
            decision=SignOffDecision.APPROVED,
            signed_at_us=10,
        )
        second = ReviewSignOff.seal(
            credential=credential,
            assurance=evidence(65),
            role=role,
            target_ref=target.ref,
            decision=SignOffDecision.APPROVED,
            signed_at_us=10,
        )
        self.assertEqual(first.sign_off_digest, second.sign_off_digest)
        self.assertNotEqual(first.assurance.proof.artifact, second.assurance.proof.artifact)

        recorded = round_.record_sign_off(
            sign_off=first,
            event_id=DomainEventId(uid(66)),
            event_occurred_at_us=11,
        )
        self.assertEqual(recorded, first)
        self.assertEqual(round_.sign_offs, (first,))
        self.assertEqual(round_.pull_events()[0].event_type, "ReviewSignOffRecorded")

        with self.assertRaises(ValidationError):
            round_.record_sign_off(
                sign_off=second,
                event_id=DomainEventId(uid(67)),
                event_occurred_at_us=12,
            )
        self.assertEqual(round_.sign_offs, (first,))
        self.assertEqual(round_.pull_events(), ())

    def test_signoff_rejects_role_replay_inadequate_assurance_and_allows_decline(self) -> None:
        target = make_target()
        role = RoleCode("rights-holder")
        credential = ActorCredentialRef(
            ActorId(uid(70)),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            ContentDigest("sha256", "4" * 64),
            artifact(71, "5"),
        )
        wrong_context = review_signoff_context_digest(
            sign_off_intent_digest=review_domain.review_signoff_intent_digest(
                credential=credential,
                role=RoleCode("translator"),
                target_ref=target.ref,
                decision=SignOffDecision.DECLINED,
                signed_at_us=20,
            ),
            actor_id=credential.actor_id,
            role=RoleCode("translator"),
            target_ref=target.ref,
        )
        replayed = ActorAssuranceEvidence.verified_signature(
            credential=credential,
            signed_context_digest=wrong_context,
            proof=SignatureProof("ed25519", credential.credential_fingerprint, artifact(72, "6")),
        )
        with self.assertRaises(ValidationError):
            ReviewSignOff.seal(
                credential=credential,
                assurance=replayed,
                role=role,
                target_ref=target.ref,
                decision=SignOffDecision.DECLINED,
                signed_at_us=20,
            )

        attested_credential = ActorCredentialRef(
            credential.actor_id,
            CredentialVerificationMethod.STEWARD_ATTESTATION,
            AssuranceLevel.STEWARD_ATTESTED,
        )
        attested = ActorAssuranceEvidence.steward_attested(
            credential=attested_credential,
            attesting_steward_id=ActorId(uid(73)),
            reason="Known signer",
            attested_at_us=19,
        )
        declined = ReviewSignOff.seal(
            credential=attested_credential,
            assurance=attested,
            role=role,
            target_ref=target.ref,
            decision=SignOffDecision.DECLINED,
            signed_at_us=20,
        )
        self.assertIs(declined.decision, SignOffDecision.DECLINED)


if __name__ == "__main__":
    unittest.main()
