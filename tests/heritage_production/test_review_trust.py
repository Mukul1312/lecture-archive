from __future__ import annotations

import unittest

from heritage_production.domain.review import ReviewerAssignment, ReviewSignOffRequirement

try:
    from heritage_production.domain.shared import (
        ActorAssuranceEvidence,
        SignOffDecision,
        SignOffTargetKind,
        SignatureProof,
    )
except ImportError:
    ActorAssuranceEvidence = None  # type: ignore[assignment,misc]
    SignOffDecision = None  # type: ignore[assignment,misc]
    SignOffTargetKind = None  # type: ignore[assignment,misc]
    SignatureProof = None  # type: ignore[assignment,misc]

from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    ArtifactId,
    ArtifactRef,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    RoleCode,
    ValidationError,
)


def uid(suffix: int) -> str:
    return f"323e4567-e89b-42d3-a456-{suffix:012x}"


def digest(character: str) -> ContentDigest:
    return ContentDigest("sha256", character * 64)


def artifact(suffix: int, character: str) -> ArtifactRef:
    return ArtifactRef(ArtifactId(uid(suffix)), digest(character), 64, "application/octet-stream")


class SharedTrustVocabularyTests(unittest.TestCase):
    def test_declared_minimum_cannot_exceed_pinned_credential_assurance(self) -> None:
        role = RoleCode("reviewer")
        attested = ActorCredentialRef(
            ActorId(uid(10)),
            CredentialVerificationMethod.STEWARD_ATTESTATION,
            AssuranceLevel.STEWARD_ATTESTED,
        )
        for value_type in (ReviewerAssignment, ReviewSignOffRequirement):
            with self.subTest(value_type=value_type.__name__):
                with self.assertRaises(ValidationError):
                    value_type(attested, role, AssuranceLevel.VERIFIED_SIGNATURE)

        verified = ActorCredentialRef(
            ActorId(uid(11)),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            digest("7"),
            artifact(12, "8"),
        )
        self.assertEqual(
            ReviewerAssignment(
                verified, role, AssuranceLevel.STEWARD_ATTESTED
            ).minimum_assurance,
            AssuranceLevel.STEWARD_ATTESTED,
        )
        self.assertEqual(
            ReviewSignOffRequirement(
                verified, role, AssuranceLevel.STEWARD_ATTESTED
            ).minimum_assurance,
            AssuranceLevel.STEWARD_ATTESTED,
        )

    def test_verified_and_attested_assurance_have_exact_nonoverlapping_shapes(self) -> None:
        self.assertIsNotNone(
            ActorAssuranceEvidence,
            "cross-module actor assurance must be shared",
        )
        credential = ActorCredentialRef(
            ActorId(uid(1)),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            digest("1"),
            artifact(2, "2"),
        )
        proof = SignatureProof("ed25519", digest("1"), artifact(3, "3"))
        verified = ActorAssuranceEvidence.verified_signature(
            credential=credential,
            signed_context_digest=digest("4"),
            proof=proof,
        )
        self.assertIs(verified.assurance, AssuranceLevel.VERIFIED_SIGNATURE)
        self.assertEqual(verified.actor_id, credential.actor_id)
        self.assertIsNone(verified.attesting_steward_id)

        claimed = ActorCredentialRef(
            ActorId(uid(4)),
            CredentialVerificationMethod.STEWARD_ATTESTATION,
            AssuranceLevel.STEWARD_ATTESTED,
        )
        attested = ActorAssuranceEvidence.steward_attested(
            credential=claimed,
            attesting_steward_id=ActorId(uid(5)),
            reason="Identity confirmed by telephone",
            attested_at_us=10,
        )
        self.assertIs(attested.assurance, AssuranceLevel.STEWARD_ATTESTED)
        self.assertIsNone(attested.proof)

        bad_proof = SignatureProof("ed25519", digest("9"), artifact(6, "6"))
        with self.assertRaises(ValidationError):
            ActorAssuranceEvidence.verified_signature(
                credential=credential,
                signed_context_digest=digest("4"),
                proof=bad_proof,
            )
        with self.assertRaises(ValidationError):
            ActorAssuranceEvidence.steward_attested(
                credential=claimed,
                attesting_steward_id=ActorId(uid(5)),
                reason="",
                attested_at_us=10,
            )

    def test_signoff_vocabulary_is_tagged_and_closed(self) -> None:
        self.assertEqual(SignOffTargetKind.REVIEW_TARGET.value, "review_target")
        self.assertEqual(SignOffTargetKind.RELEASE_CONTENT.value, "release_content")
        self.assertEqual(SignOffTargetKind.MANIFEST_MEMBER.value, "manifest_member")
        self.assertEqual(SignOffDecision.APPROVED.value, "approved")
        self.assertEqual(SignOffDecision.DECLINED.value, "declined")


if __name__ == "__main__":
    unittest.main()
