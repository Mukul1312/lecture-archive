from __future__ import annotations

import unittest

try:
    from heritage_production.domain.review import (
        ReviewSignOff,
        ReviewSignOffRequirement,
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
