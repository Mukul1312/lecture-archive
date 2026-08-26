from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from heritage_production.domain.shared import (
    ActorCredentialRef,
    ActorId,
    ActorRef,
    ArtifactId,
    ArtifactManifestRef,
    ArtifactRef,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    EditionRef,
    ExternalGateSetId,
    ExternalGateSetRef,
    PolicyEvaluatorRef,
    PolicyRef,
    ReleaseCandidateId,
    ReleaseCandidateRef,
    ReleaseContentManifestId,
    ReleaseContentManifestRef,
    ReleasePolicyVersionId,
    ReviewEvidenceRef,
    ReviewPackageId,
    ReviewPackageRef,
    ReviewRoundId,
    ReviewTargetManifestRef,
    RubricId,
    RubricRef,
    SegmentId,
    SegmentRevisionId,
    SegmentRevisionRef,
    SourceRecordingId,
    SourceRecordingRef,
    TranscriptEditionId,
    ValidationError,
    VerificationMethod,
)


def uuid_text(suffix: int) -> str:
    return f"123e4567-e89b-42d3-a456-{suffix:012x}"


DIGEST = ContentDigest("sha256", "2" * 64)
ARTIFACT = ArtifactRef(ArtifactId(uuid_text(1)), DIGEST, 10, "application/json")


class SourceRecordingRefTests(unittest.TestCase):
    def test_metadata_is_canonical_detached_and_contains_no_path_authority_field(self) -> None:
        supplied = {"title": "Oral history", "language": "hi"}
        reference = SourceRecordingRef(SourceRecordingId(uuid_text(2)), supplied)
        supplied["title"] = "changed"
        exposed = reference.descriptive_metadata
        exposed["title"] = "also changed"

        self.assertEqual(
            reference.descriptive_metadata,
            {"language": "hi", "title": "Oral history"},
        )
        self.assertFalse(hasattr(reference, "path"))

    def test_metadata_rejects_noncanonical_json(self) -> None:
        for metadata in ({"title": "e\u0301"}, {"title": 1.0}, ["not", "an", "object"]):
            with self.subTest(metadata=metadata):
                with self.assertRaises(ValidationError):
                    SourceRecordingRef(SourceRecordingId(uuid_text(2)), metadata)  # type: ignore[arg-type]


class AssuranceTests(unittest.TestCase):
    def test_explicit_methods_map_to_exact_assurance_levels(self) -> None:
        actor_id = ActorId(uuid_text(3))
        unverified = ActorCredentialRef(
            actor_id,
            CredentialVerificationMethod.UNVERIFIED_CLAIM,
            AssuranceLevel.UNVERIFIED,
        )
        attested = ActorCredentialRef(
            actor_id,
            CredentialVerificationMethod.STEWARD_ATTESTATION,
            AssuranceLevel.STEWARD_ATTESTED,
        )
        verified = ActorCredentialRef(
            actor_id,
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            DIGEST,
            ARTIFACT,
        )
        self.assertIs(VerificationMethod, CredentialVerificationMethod)
        self.assertIsNone(unverified.public_key_artifact)
        self.assertIsNone(attested.credential_fingerprint)
        self.assertEqual(verified.public_key_artifact, ARTIFACT)

    def test_ed25519_requires_public_key_and_fingerprint(self) -> None:
        actor_id = ActorId(uuid_text(3))
        for fingerprint, public_key in ((None, ARTIFACT), (DIGEST, None), (None, None)):
            with self.subTest(fingerprint=fingerprint, public_key=public_key):
                with self.assertRaises(ValidationError):
                    ActorCredentialRef(
                        actor_id,
                        CredentialVerificationMethod.ED25519,
                        AssuranceLevel.VERIFIED_SIGNATURE,
                        fingerprint,
                        public_key,
                    )

    def test_attested_claim_cannot_claim_verified_assurance_or_key_material(self) -> None:
        actor_id = ActorId(uuid_text(3))
        with self.assertRaises(ValidationError):
            ActorCredentialRef(
                actor_id,
                CredentialVerificationMethod.STEWARD_ATTESTATION,
                AssuranceLevel.VERIFIED_SIGNATURE,
            )
        with self.assertRaises(ValidationError):
            ActorCredentialRef(
                actor_id,
                CredentialVerificationMethod.STEWARD_ATTESTATION,
                AssuranceLevel.STEWARD_ATTESTED,
                DIGEST,
                ARTIFACT,
            )


class ImmutableRefTests(unittest.TestCase):
    def test_all_later_task_refs_have_typed_frozen_constructors(self) -> None:
        refs = (
            RubricRef(RubricId(uuid_text(4)), 1, DIGEST, ARTIFACT),
            PolicyEvaluatorRef("heritage", "1.2.3", "policy-v1", DIGEST),
            EditionRef(TranscriptEditionId(uuid_text(5)), DIGEST),
            SegmentRevisionRef(
                SegmentId(uuid_text(6)), SegmentRevisionId(uuid_text(7)), DIGEST
            ),
            ReviewEvidenceRef(ReviewRoundId(uuid_text(8)), DIGEST),
            ReviewTargetManifestRef(ReviewRoundId(uuid_text(8)), DIGEST, ARTIFACT),
            ReviewPackageRef(ReviewPackageId(uuid_text(9)), DIGEST, ARTIFACT),
            PolicyRef(ReleasePolicyVersionId(uuid_text(10)), DIGEST),
            ExternalGateSetRef(ExternalGateSetId(uuid_text(11)), DIGEST),
            ArtifactManifestRef(ArtifactId(uuid_text(12)), DIGEST),
            ReleaseContentManifestRef(
                ReleaseContentManifestId(uuid_text(13)), DIGEST, ARTIFACT
            ),
            ReleaseCandidateRef(ReleaseCandidateId(uuid_text(14)), DIGEST),
            ActorRef(ActorId(uuid_text(15)), "Rights holder"),
        )
        self.assertEqual(len(set(refs)), len(refs))
        for reference in refs:
            with self.subTest(reference=type(reference).__name__):
                field_name = next(iter(reference.__dataclass_fields__))
                with self.assertRaises(FrozenInstanceError):
                    setattr(reference, field_name, None)

    def test_ref_scalar_validation_rejects_bad_versions_and_noncanonical_labels(self) -> None:
        with self.assertRaises(ValidationError):
            RubricRef(RubricId(uuid_text(4)), 0, DIGEST)
        with self.assertRaises(ValidationError):
            RubricRef(RubricId(uuid_text(4)), True, DIGEST)
        with self.assertRaises(ValidationError):
            PolicyEvaluatorRef("", "1.2.3", "policy-v1", DIGEST)
        with self.assertRaises(ValidationError):
            PolicyEvaluatorRef("heritage", "e\u0301", "policy-v1", DIGEST)
        with self.assertRaises(ValidationError):
            ActorRef(ActorId(uuid_text(15)), "line\rbreak")
