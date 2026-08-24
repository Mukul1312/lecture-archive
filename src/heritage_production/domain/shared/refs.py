"""Frozen typed references shared by later aggregates and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .canonical import JsonValue, canonical_json, parse_strict_json
from .digests import ArtifactRef, ContentDigest
from .errors import ValidationError
from .ids import (
    ActorId,
    ArtifactId,
    ExternalGateSetId,
    ReleaseCandidateId,
    ReleaseContentManifestId,
    ReleasePolicyVersionId,
    ReviewPackageId,
    ReviewRoundId,
    RubricId,
    SegmentId,
    SegmentRevisionId,
    SourceRecordingId,
    TranscriptEditionId,
)
from .text import require_canonical_text


def _require_type(value: object, expected_type: type[object], field: str) -> None:
    if type(value) is not expected_type:
        raise ValidationError(f"{field} must be a {expected_type.__name__}")


@dataclass(frozen=True, slots=True, init=False)
class SourceRecordingRef:
    source_recording_id: SourceRecordingId
    _descriptive_metadata_bytes: bytes

    def __init__(
        self,
        source_recording_id: SourceRecordingId,
        descriptive_metadata: dict[str, JsonValue],
    ) -> None:
        _require_type(source_recording_id, SourceRecordingId, "source_recording_id")
        if type(descriptive_metadata) is not dict:
            raise ValidationError("descriptive_metadata must be a JSON object")
        encoded = canonical_json(descriptive_metadata)
        object.__setattr__(self, "source_recording_id", source_recording_id)
        object.__setattr__(self, "_descriptive_metadata_bytes", encoded)

    @property
    def descriptive_metadata(self) -> dict[str, JsonValue]:
        value = parse_strict_json(self._descriptive_metadata_bytes)
        if type(value) is not dict:  # construction guarantees this; keeps the return contract explicit
            raise ValidationError("stored descriptive metadata is not an object")
        return value


@dataclass(frozen=True, slots=True)
class RubricRef:
    rubric_id: RubricId
    schema_version: int
    content_digest: ContentDigest
    artifact: ArtifactRef | None = None

    def __post_init__(self) -> None:
        _require_type(self.rubric_id, RubricId, "rubric_id")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version <= 0
        ):
            raise ValidationError("schema_version must be a positive integer")
        _require_type(self.content_digest, ContentDigest, "content_digest")
        if self.artifact is not None:
            _require_type(self.artifact, ArtifactRef, "artifact")


class CredentialVerificationMethod(str, Enum):
    UNVERIFIED_CLAIM = "unverified_claim"
    STEWARD_ATTESTATION = "steward_attestation"
    ED25519 = "ed25519"


VerificationMethod = CredentialVerificationMethod


class AssuranceLevel(str, Enum):
    UNVERIFIED = "unverified"
    STEWARD_ATTESTED = "steward_attested"
    VERIFIED_SIGNATURE = "verified_signature"


@dataclass(frozen=True, slots=True)
class ActorCredentialRef:
    actor_id: ActorId
    verification_method: CredentialVerificationMethod
    assurance: AssuranceLevel
    credential_fingerprint: ContentDigest | None = None
    public_key_artifact: ArtifactRef | None = None

    def __post_init__(self) -> None:
        _require_type(self.actor_id, ActorId, "actor_id")
        _require_type(
            self.verification_method,
            CredentialVerificationMethod,
            "verification_method",
        )
        _require_type(self.assurance, AssuranceLevel, "assurance")
        expected_assurance = {
            CredentialVerificationMethod.UNVERIFIED_CLAIM: AssuranceLevel.UNVERIFIED,
            CredentialVerificationMethod.STEWARD_ATTESTATION: AssuranceLevel.STEWARD_ATTESTED,
            CredentialVerificationMethod.ED25519: AssuranceLevel.VERIFIED_SIGNATURE,
        }[self.verification_method]
        if self.assurance is not expected_assurance:
            raise ValidationError("verification method and assurance level do not match")

        if self.verification_method is CredentialVerificationMethod.ED25519:
            _require_type(
                self.credential_fingerprint,
                ContentDigest,
                "credential_fingerprint",
            )
            _require_type(self.public_key_artifact, ArtifactRef, "public_key_artifact")
        elif self.credential_fingerprint is not None or self.public_key_artifact is not None:
            raise ValidationError("noncryptographic claims must not carry verified key evidence")


@dataclass(frozen=True, slots=True)
class PolicyEvaluatorRef:
    evaluator_name: str
    semantic_version: str
    supported_policy_schema: str
    implementation_build_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value in (
            ("evaluator_name", self.evaluator_name),
            ("semantic_version", self.semantic_version),
            ("supported_policy_schema", self.supported_policy_schema),
        ):
            require_canonical_text(value, field=field_name, nonempty=True)
        _require_type(
            self.implementation_build_digest,
            ContentDigest,
            "implementation_build_digest",
        )


@dataclass(frozen=True, slots=True)
class EditionRef:
    transcript_edition_id: TranscriptEditionId
    content_digest: ContentDigest

    def __post_init__(self) -> None:
        _require_type(self.transcript_edition_id, TranscriptEditionId, "transcript_edition_id")
        _require_type(self.content_digest, ContentDigest, "content_digest")


@dataclass(frozen=True, slots=True)
class SegmentRevisionRef:
    segment_id: SegmentId
    segment_revision_id: SegmentRevisionId
    revision_digest: ContentDigest

    def __post_init__(self) -> None:
        _require_type(self.segment_id, SegmentId, "segment_id")
        _require_type(self.segment_revision_id, SegmentRevisionId, "segment_revision_id")
        _require_type(self.revision_digest, ContentDigest, "revision_digest")


@dataclass(frozen=True, slots=True)
class ReviewEvidenceRef:
    review_round_id: ReviewRoundId
    evidence_digest: ContentDigest

    def __post_init__(self) -> None:
        _require_type(self.review_round_id, ReviewRoundId, "review_round_id")
        _require_type(self.evidence_digest, ContentDigest, "evidence_digest")


@dataclass(frozen=True, slots=True)
class ReviewTargetManifestRef:
    review_round_id: ReviewRoundId
    semantic_digest: ContentDigest
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        _require_type(self.review_round_id, ReviewRoundId, "review_round_id")
        _require_type(self.semantic_digest, ContentDigest, "semantic_digest")
        _require_type(self.artifact, ArtifactRef, "artifact")


@dataclass(frozen=True, slots=True)
class ReviewPackageRef:
    review_package_id: ReviewPackageId
    semantic_digest: ContentDigest
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        _require_type(self.review_package_id, ReviewPackageId, "review_package_id")
        _require_type(self.semantic_digest, ContentDigest, "semantic_digest")
        _require_type(self.artifact, ArtifactRef, "artifact")


@dataclass(frozen=True, slots=True)
class PolicyRef:
    release_policy_version_id: ReleasePolicyVersionId
    policy_digest: ContentDigest

    def __post_init__(self) -> None:
        _require_type(
            self.release_policy_version_id,
            ReleasePolicyVersionId,
            "release_policy_version_id",
        )
        _require_type(self.policy_digest, ContentDigest, "policy_digest")


@dataclass(frozen=True, slots=True)
class ExternalGateSetRef:
    external_gate_set_id: ExternalGateSetId
    content_digest: ContentDigest

    def __post_init__(self) -> None:
        _require_type(self.external_gate_set_id, ExternalGateSetId, "external_gate_set_id")
        _require_type(self.content_digest, ContentDigest, "content_digest")


@dataclass(frozen=True, slots=True)
class ArtifactManifestRef:
    artifact_id: ArtifactId
    content_digest: ContentDigest

    def __post_init__(self) -> None:
        _require_type(self.artifact_id, ArtifactId, "artifact_id")
        _require_type(self.content_digest, ContentDigest, "content_digest")


@dataclass(frozen=True, slots=True)
class ReleaseContentManifestRef:
    release_content_manifest_id: ReleaseContentManifestId
    semantic_digest: ContentDigest
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        _require_type(
            self.release_content_manifest_id,
            ReleaseContentManifestId,
            "release_content_manifest_id",
        )
        _require_type(self.semantic_digest, ContentDigest, "semantic_digest")
        _require_type(self.artifact, ArtifactRef, "artifact")


@dataclass(frozen=True, slots=True)
class ReleaseCandidateRef:
    release_candidate_id: ReleaseCandidateId
    semantic_digest: ContentDigest

    def __post_init__(self) -> None:
        _require_type(self.release_candidate_id, ReleaseCandidateId, "release_candidate_id")
        _require_type(self.semantic_digest, ContentDigest, "semantic_digest")


@dataclass(frozen=True, slots=True)
class ActorRef:
    actor_id: ActorId
    display_label: str

    def __post_init__(self) -> None:
        _require_type(self.actor_id, ActorId, "actor_id")
        require_canonical_text(self.display_label, field="display_label", nonempty=True)
