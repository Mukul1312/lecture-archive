"""Immutable Production-owned source attachments and edition selections."""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ActorId,
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    EditionRef,
    ProductionId,
    SourceRecordingId,
    SourceRecordingRef,
    SourceVersionId,
    SourceVersionRef,
    TranscriptEditionId,
    ValidationError,
)


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


@dataclass(frozen=True, slots=True)
class AttachedSource:
    """One exact source version bound to its verified bytes."""

    source_recording_ref: SourceRecordingRef
    source_version_ref: SourceVersionRef
    artifact: ArtifactRef
    attached_by: ActorId
    attached_at_us: int

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("source_recording_ref", self.source_recording_ref, SourceRecordingRef),
            ("source_version_ref", self.source_version_ref, SourceVersionRef),
            ("artifact", self.artifact, ArtifactRef),
            ("attached_by", self.attached_by, ActorId),
        ):
            _require_exact(value, expected, field_name)
        if type(self.attached_at_us) is not int or self.attached_at_us <= 0:
            raise ValidationError("attached_at_us must be a positive integer")
        if (
            self.source_recording_ref.source_recording_id
            != self.source_version_ref.source_recording_id
        ):
            raise ValidationError(
                "source recording and source version name different recordings"
            )
        if self.artifact.content_digest != self.source_version_ref.artifact_digest:
            raise ValidationError(
                "attached artifact digest does not match its source version"
            )

    def validated(self) -> "AttachedSource":
        """Reconstruct this attachment and every reachable child value."""
        version = self.source_version_ref
        try:
            rebuilt_version = SourceVersionRef(
                SourceVersionId(version.source_version_id.value),
                SourceRecordingId(version.source_recording_id.value),
                ContentDigest(
                    version.artifact_digest.algorithm,
                    version.artifact_digest.hex_digest,
                ),
                version.duration_us,
                version.time_base_evidence,
            )
            rebuilt_artifact = ArtifactRef(
                ArtifactId(self.artifact.artifact_id.value),
                ContentDigest(
                    self.artifact.content_digest.algorithm,
                    self.artifact.content_digest.hex_digest,
                ),
                self.artifact.byte_size,
                self.artifact.media_type,
            )
            rebuilt_recording = SourceRecordingRef(
                SourceRecordingId(
                    self.source_recording_ref.source_recording_id.value
                ),
                self.source_recording_ref.descriptive_metadata,
            )
        except AttributeError as error:
            raise ValidationError("attached source is incomplete") from error
        return AttachedSource(
            rebuilt_recording,
            rebuilt_version,
            rebuilt_artifact,
            ActorId(self.attached_by.value),
            self.attached_at_us,
        )

    @property
    def source_recording_id(self) -> SourceRecordingId:
        return self.source_version_ref.source_recording_id

    @property
    def source_version_id(self) -> SourceVersionId:
        return self.source_version_ref.source_version_id

    @property
    def identity(self) -> tuple[str, str]:
        return (self.source_recording_id.value, self.source_version_id.value)

    @property
    def content(self) -> tuple[object, object, object]:
        """The fields that make two attachments the same evidence."""
        return (self.source_recording_ref, self.source_version_ref, self.artifact)


@dataclass(frozen=True, slots=True)
class EditionSelection:
    """A verified snapshot of the edition a steward proposes as the candidate."""

    production_id: ProductionId
    edition_ref: EditionRef
    source_version_refs: tuple[SourceVersionRef, ...]

    def __post_init__(self) -> None:
        _require_exact(self.production_id, ProductionId, "production_id")
        _require_exact(self.edition_ref, EditionRef, "edition_ref")
        if type(self.source_version_refs) is not tuple or not all(
            type(value) is SourceVersionRef for value in self.source_version_refs
        ):
            raise ValidationError(
                "source_version_refs must be an immutable tuple of SourceVersionRef"
            )
        if not self.source_version_refs:
            raise ValidationError("an edition selection must name at least one source")
        keys = tuple(value.source_version_id.value for value in self.source_version_refs)
        if keys != tuple(sorted(keys)):
            raise ValidationError("source version refs must be in canonical order")
        if len(set(keys)) != len(keys):
            raise ValidationError("source version refs must be unique")

    def validated(self) -> "EditionSelection":
        """Reconstruct this selection and every reachable child value."""
        try:
            return EditionSelection(
                ProductionId(self.production_id.value),
                EditionRef(
                    TranscriptEditionId(
                        self.edition_ref.transcript_edition_id.value
                    ),
                    ContentDigest(
                        self.edition_ref.content_digest.algorithm,
                        self.edition_ref.content_digest.hex_digest,
                    ),
                ),
                tuple(
                    SourceVersionRef(
                        SourceVersionId(value.source_version_id.value),
                        SourceRecordingId(value.source_recording_id.value),
                        ContentDigest(
                            value.artifact_digest.algorithm,
                            value.artifact_digest.hex_digest,
                        ),
                        value.duration_us,
                        value.time_base_evidence,
                    )
                    for value in self.source_version_refs
                ),
            )
        except AttributeError as error:
            raise ValidationError("edition selection is incomplete") from error
