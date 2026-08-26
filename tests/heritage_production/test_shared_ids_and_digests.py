from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from heritage_production.domain.shared import (
    ActorId,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    DomainEventId,
    EligibilityAssessmentId,
    ExternalGateSetId,
    MigrationDecisionId,
    OperationId,
    ProductionId,
    ProposalItemId,
    ProposalSetId,
    ReleaseCandidateId,
    ReleaseContentManifestId,
    ReleasePolicyVersionId,
    ReviewFindingId,
    ReviewPackageId,
    ReviewRoundId,
    ReviewSubmissionId,
    RubricId,
    SegmentId,
    SegmentRevisionId,
    SourceRecordingId,
    SourceVersionId,
    TranscriptEditionId,
    ValidationError,
)


VALID_UUID = "123e4567-e89b-42d3-a456-426614174000"
ID_TYPES = (
    ProductionId,
    SourceRecordingId,
    SourceVersionId,
    ProposalSetId,
    ProposalItemId,
    TranscriptEditionId,
    SegmentId,
    SegmentRevisionId,
    ReviewRoundId,
    ReviewPackageId,
    ReviewSubmissionId,
    ReviewFindingId,
    RubricId,
    ReleasePolicyVersionId,
    ExternalGateSetId,
    ReleaseContentManifestId,
    ReleaseCandidateId,
    EligibilityAssessmentId,
    ArtifactId,
    MigrationDecisionId,
    ActorId,
    OperationId,
    DomainEventId,
)


class OpaqueIdTests(unittest.TestCase):
    def test_every_id_accepts_only_canonical_rfc4122_uuid4_text(self) -> None:
        invalid = (
            "",
            "123E4567-E89B-42D3-A456-426614174000",
            "{123e4567-e89b-42d3-a456-426614174000}",
            "123e4567-e89b-12d3-a456-426614174000",  # UUIDv1
            "123e4567-e89b-42d3-c456-426614174000",  # non-RFC variant
            "123e4567e89b42d3a456426614174000",
            "not-a-uuid",
        )
        for identifier_type in ID_TYPES:
            with self.subTest(identifier_type=identifier_type.__name__):
                identifier = identifier_type(VALID_UUID)
                self.assertEqual(identifier.value, VALID_UUID)
                self.assertEqual(str(identifier), VALID_UUID)
                self.assertEqual(hash(identifier), hash(identifier_type(VALID_UUID)))
                with self.assertRaises(FrozenInstanceError):
                    identifier.value = VALID_UUID  # type: ignore[misc]
            for text in invalid:
                with self.subTest(identifier_type=identifier_type.__name__, text=text):
                    with self.assertRaises(ValidationError):
                        identifier_type(text)

    def test_equal_text_in_distinct_id_types_is_not_equal(self) -> None:
        self.assertNotEqual(ProductionId(VALID_UUID), ArtifactId(VALID_UUID))

    def test_backup_id_is_part_of_the_public_id_set(self) -> None:
        from heritage_production.domain.shared import BackupId

        self.assertEqual(BackupId(VALID_UUID).value, VALID_UUID)


class DigestAndArtifactTests(unittest.TestCase):
    def test_sha256_byte_vectors_are_literal_and_lowercase(self) -> None:
        self.assertEqual(
            ContentDigest.from_bytes(b"").hex_digest,
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
        )
        self.assertEqual(
            ContentDigest.from_bytes(b"abc").hex_digest,
            "ba7816bf8f01cfea414140de5dae2223"
            "b00361a396177a9cb410ff61f20015ad",
        )

    def test_digest_rejects_unknown_algorithm_or_noncanonical_hex(self) -> None:
        valid_hex = "0" * 64
        for algorithm, hex_digest in (
            ("SHA256", valid_hex),
            ("sha512", valid_hex),
            ("sha256", "0" * 63),
            ("sha256", "A" * 64),
            ("sha256", "g" * 64),
        ):
            with self.subTest(algorithm=algorithm, hex_digest=hex_digest):
                with self.assertRaises(ValidationError):
                    ContentDigest(algorithm, hex_digest)

    def test_artifact_ref_validates_size_and_media_type(self) -> None:
        digest = ContentDigest("sha256", "0" * 64)
        artifact = ArtifactRef(ArtifactId(VALID_UUID), digest, 0, "audio/wav")
        self.assertEqual(artifact.byte_size, 0)

        for size in (-1, True, 1.5):
            with self.subTest(size=size):
                with self.assertRaises(ValidationError):
                    ArtifactRef(ArtifactId(VALID_UUID), digest, size, "audio/wav")  # type: ignore[arg-type]
        for media_type in (
            "",
            "audio",
            "/wav",
            "audio/",
            "audio/wav\r",
            "audio/wa(v",
            "audio/wa\u0000v",
        ):
            with self.subTest(media_type=media_type):
                with self.assertRaises(ValidationError):
                    ArtifactRef(ArtifactId(VALID_UUID), digest, 1, media_type)

    def test_artifact_ref_requires_exact_typed_values(self) -> None:
        class DerivedArtifactId(ArtifactId):
            pass

        with self.assertRaises(ValidationError):
            ArtifactRef(
                DerivedArtifactId(VALID_UUID),
                ContentDigest("sha256", "0" * 64),
                1,
                "audio/wav",
            )
