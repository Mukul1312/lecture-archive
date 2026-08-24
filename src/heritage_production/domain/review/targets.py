"""Reviewer-independent target snapshots owned by ReviewRound."""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    EditionRef,
    ProductionId,
    ReviewRoundId,
    ReviewTargetManifestRef,
    RubricRef,
    SegmentRevisionRef,
    SourceSpan,
    TranscriptText,
    ValidationError,
    semantic_digest,
)
from heritage_production.domain.shared.text import require_canonical_text


@dataclass(frozen=True, slots=True)
class _OpaqueReviewText:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(
            self.value,
            field=type(self).__name__,
            nonempty=True,
        )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ReviewTargetKey(_OpaqueReviewText):
    pass


@dataclass(frozen=True, slots=True)
class FindingCategoryCode(_OpaqueReviewText):
    pass


@dataclass(frozen=True, slots=True)
class FindingSeverityCode(_OpaqueReviewText):
    pass


@dataclass(frozen=True, slots=True)
class SemanticAssetRole(_OpaqueReviewText):
    pass


@dataclass(frozen=True, slots=True)
class ReviewTargetAssetRef:
    role: SemanticAssetRole
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        if type(self.role) is not SemanticAssetRole:
            raise ValidationError("role must be an exact SemanticAssetRole")
        if type(self.artifact) is not ArtifactRef:
            raise ValidationError("artifact must be an exact ArtifactRef")


@dataclass(frozen=True, slots=True)
class ReviewTargetMember:
    ordinal: int
    target_key: ReviewTargetKey
    segment_revision_ref: SegmentRevisionRef
    source_span: SourceSpan
    transcript_text: TranscriptText
    allowed_category_codes: tuple[FindingCategoryCode, ...]
    allowed_severity_codes: tuple[FindingSeverityCode, ...]
    derived_audio: tuple[ReviewTargetAssetRef, ...] = ()

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValidationError("target ordinal must be a nonnegative integer")
        for field_name, value, expected in (
            ("target_key", self.target_key, ReviewTargetKey),
            ("segment_revision_ref", self.segment_revision_ref, SegmentRevisionRef),
            ("source_span", self.source_span, SourceSpan),
            ("transcript_text", self.transcript_text, TranscriptText),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        for field_name, values, expected in (
            ("allowed_category_codes", self.allowed_category_codes, FindingCategoryCode),
            ("allowed_severity_codes", self.allowed_severity_codes, FindingSeverityCode),
            ("derived_audio", self.derived_audio, ReviewTargetAssetRef),
        ):
            if type(values) is not tuple or not all(type(item) is expected for item in values):
                raise ValidationError(f"{field_name} must be an immutable tuple of {expected.__name__}")
            if field_name != "derived_audio" and not values:
                raise ValidationError(f"{field_name} must not be empty")
            if len(set(values)) != len(values):
                raise ValidationError(f"{field_name} must contain unique values")
        roles = tuple(asset.role for asset in self.derived_audio)
        artifacts = tuple(asset.artifact for asset in self.derived_audio)
        if len(set(roles)) != len(roles) or len(set(artifacts)) != len(artifacts):
            raise ValidationError("derived audio roles and artifacts must be unique")


def _digest_value(value: ContentDigest) -> dict[str, object]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


def _artifact_value(value: ArtifactRef) -> dict[str, object]:
    return {
        "artifact_id": value.artifact_id.value,
        "content_digest": _digest_value(value.content_digest),
        "byte_size": value.byte_size,
        "media_type": value.media_type,
    }


def _source_value(value: SourceSpan) -> dict[str, object]:
    source = value.source_version
    return {
        "source_version": {
            "source_version_id": source.source_version_id.value,
            "source_recording_id": source.source_recording_id.value,
            "artifact_digest": _digest_value(source.artifact_digest),
            "duration_us": source.duration_us,
            "time_base_evidence": source.time_base_evidence,
        },
        "start_us": value.start_us,
        "end_us": value.end_us,
    }


def _member_value(value: ReviewTargetMember) -> dict[str, object]:
    revision = value.segment_revision_ref
    return {
        "ordinal": value.ordinal,
        "target_key": value.target_key.value,
        "segment_revision_ref": {
            "segment_id": revision.segment_id.value,
            "segment_revision_id": revision.segment_revision_id.value,
            "revision_digest": _digest_value(revision.revision_digest),
        },
        "source_span": _source_value(value.source_span),
        "transcript_text": value.transcript_text.value,
        "allowed_category_codes": [code.value for code in value.allowed_category_codes],
        "allowed_severity_codes": [code.value for code in value.allowed_severity_codes],
        "derived_audio": [
            {"role": asset.role.value, "artifact": _artifact_value(asset.artifact)}
            for asset in value.derived_audio
        ],
    }


def _target_payload(
    review_round_id: ReviewRoundId,
    production_id: ProductionId,
    edition_ref: EditionRef,
    rubric_ref: RubricRef,
    members: tuple[ReviewTargetMember, ...],
) -> dict[str, object]:
    return {
        "review_round_id": review_round_id.value,
        "production_id": production_id.value,
        "edition_ref": {
            "transcript_edition_id": edition_ref.transcript_edition_id.value,
            "content_digest": _digest_value(edition_ref.content_digest),
        },
        "rubric_ref": {
            "rubric_id": rubric_ref.rubric_id.value,
            "schema_version": rubric_ref.schema_version,
            "content_digest": _digest_value(rubric_ref.content_digest),
        },
        "members": [_member_value(member) for member in members],
    }


@dataclass(frozen=True, slots=True)
class ReviewTargetManifest:
    ref: ReviewTargetManifestRef
    production_id: ProductionId
    edition_ref: EditionRef
    rubric_ref: RubricRef
    members: tuple[ReviewTargetMember, ...]

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("ref", self.ref, ReviewTargetManifestRef),
            ("production_id", self.production_id, ProductionId),
            ("edition_ref", self.edition_ref, EditionRef),
            ("rubric_ref", self.rubric_ref, RubricRef),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if type(self.members) is not tuple or not all(
            type(member) is ReviewTargetMember for member in self.members
        ):
            raise ValidationError("members must be an immutable tuple of ReviewTargetMember")
        if tuple(member.ordinal for member in self.members) != tuple(range(len(self.members))):
            raise ValidationError("target membership ordinals must be contiguous from zero")
        for label, values in (
            ("target keys", tuple(member.target_key for member in self.members)),
            (
                "segment revisions",
                tuple(member.segment_revision_ref for member in self.members),
            ),
        ):
            if len(set(values)) != len(values):
                raise ValidationError(f"review target {label} must be unique")
        asset_roles = tuple(
            asset.role for member in self.members for asset in member.derived_audio
        )
        if len(set(asset_roles)) != len(asset_roles):
            raise ValidationError("review target semantic asset roles must be unique")
        expected = semantic_digest(
            "heritage-review-target-v1",
            _target_payload(
                self.ref.review_round_id,
                self.production_id,
                self.edition_ref,
                self.rubric_ref,
                self.members,
            ),
        )
        if expected != self.ref.semantic_digest:
            raise ValidationError("review-target digest does not match its stored snapshot")

    @classmethod
    def seal(
        cls,
        *,
        review_round_id: ReviewRoundId,
        production_id: ProductionId,
        edition_ref: EditionRef,
        rubric_ref: RubricRef,
        members: tuple[ReviewTargetMember, ...],
        artifact: ArtifactRef,
    ) -> ReviewTargetManifest:
        try:
            digest = semantic_digest(
                "heritage-review-target-v1",
                _target_payload(
                    review_round_id, production_id, edition_ref, rubric_ref, members
                ),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed review-target semantic input") from error
        return cls(
            ReviewTargetManifestRef(review_round_id, digest, artifact),
            production_id,
            edition_ref,
            rubric_ref,
            members,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        ref: ReviewTargetManifestRef,
        production_id: ProductionId,
        edition_ref: EditionRef,
        rubric_ref: RubricRef,
        members: tuple[ReviewTargetMember, ...],
    ) -> ReviewTargetManifest:
        return cls(ref, production_id, edition_ref, rubric_ref, members)

    def validated(self) -> ReviewTargetManifest:
        """Recompute this manifest from its own stored fields.

        `heritage-review-target-v1` covers production_id, edition_ref,
        rubric_ref and every member, so a field forged behind the stored
        `ref.semantic_digest` fails the recomputation in `__post_init__`.
        """
        ref = self.ref
        try:
            checked_ref = ReviewTargetManifestRef(
                ReviewRoundId(ref.review_round_id.value),
                ContentDigest(
                    ref.semantic_digest.algorithm, ref.semantic_digest.hex_digest
                ),
                ArtifactRef(
                    ArtifactId(ref.artifact.artifact_id.value),
                    ContentDigest(
                        ref.artifact.content_digest.algorithm,
                        ref.artifact.content_digest.hex_digest,
                    ),
                    ref.artifact.byte_size,
                    ref.artifact.media_type,
                ),
            )
        except AttributeError as error:
            raise ValidationError("review target manifest ref is incomplete") from error
        return type(self).reconstitute(
            ref=checked_ref,
            production_id=self.production_id,
            edition_ref=self.edition_ref,
            rubric_ref=self.rubric_ref,
            members=self.members,
        )

    @property
    def review_round_id(self) -> ReviewRoundId:
        return self.ref.review_round_id

    @property
    def semantic_digest(self) -> ContentDigest:
        return self.ref.semantic_digest
