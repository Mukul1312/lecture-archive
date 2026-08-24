"""Immutable source-version and transcript-scope values."""

from __future__ import annotations

from dataclasses import dataclass

from .digests import ContentDigest
from .errors import ValidationError
from .ids import SourceRecordingId, SourceVersionId
from .text import require_canonical_text


@dataclass(frozen=True, slots=True)
class SourceVersionRef:
    source_version_id: SourceVersionId
    source_recording_id: SourceRecordingId
    artifact_digest: ContentDigest
    duration_us: int
    time_base_evidence: str

    def __post_init__(self) -> None:
        if type(self.source_version_id) is not SourceVersionId:
            raise ValidationError("source_version_id must be a SourceVersionId")
        if type(self.source_recording_id) is not SourceRecordingId:
            raise ValidationError("source_recording_id must be a SourceRecordingId")
        if type(self.artifact_digest) is not ContentDigest:
            raise ValidationError("artifact_digest must be a ContentDigest")
        if (
            isinstance(self.duration_us, bool)
            or not isinstance(self.duration_us, int)
            or self.duration_us <= 0
        ):
            raise ValidationError("duration_us must be a positive integer")
        require_canonical_text(
            self.time_base_evidence,
            field="time_base_evidence",
            nonempty=True,
        )


@dataclass(frozen=True, slots=True)
class SourceSpan:
    source_version: SourceVersionRef
    start_us: int
    end_us: int

    def __post_init__(self) -> None:
        if type(self.source_version) is not SourceVersionRef:
            raise ValidationError("source_version must be an exact SourceVersionRef")
        if (
            isinstance(self.start_us, bool)
            or not isinstance(self.start_us, int)
            or isinstance(self.end_us, bool)
            or not isinstance(self.end_us, int)
        ):
            raise ValidationError("source span boundaries must be integers")
        if self.start_us < 0 or self.end_us <= self.start_us:
            raise ValidationError("source span must be a nonempty half-open interval")
        if self.end_us > self.source_version.duration_us:
            raise ValidationError("source span exceeds its source-version duration")


@dataclass(frozen=True, slots=True)
class TranscriptScope:
    source_versions: tuple[SourceVersionRef, ...]
    required_spans: tuple[SourceSpan, ...]
    excluded_gap_spans: tuple[SourceSpan, ...]

    def __post_init__(self) -> None:
        for field_name, values, expected_type in (
            ("source_versions", self.source_versions, SourceVersionRef),
            ("required_spans", self.required_spans, SourceSpan),
            ("excluded_gap_spans", self.excluded_gap_spans, SourceSpan),
        ):
            if not isinstance(values, tuple) or not all(
                type(value) is expected_type for value in values
            ):
                raise ValidationError(f"{field_name} must be a tuple of {expected_type.__name__}")

        if len(set(self.source_versions)) != len(self.source_versions):
            raise ValidationError("declared source versions must be unique")
        source_order = {source: index for index, source in enumerate(self.source_versions)}
        self._validate_spans(self.required_spans, source_order, "required_spans")
        self._validate_spans(self.excluded_gap_spans, source_order, "excluded_gap_spans")

    @staticmethod
    def _validate_spans(
        spans: tuple[SourceSpan, ...],
        source_order: dict[SourceVersionRef, int],
        field_name: str,
    ) -> None:
        previous_key: tuple[int, int, int] | None = None
        previous_span: SourceSpan | None = None
        for span in spans:
            if span.source_version not in source_order:
                raise ValidationError(f"{field_name} contains an undeclared source version")
            key = (source_order[span.source_version], span.start_us, span.end_us)
            if previous_key is not None and key < previous_key:
                raise ValidationError(f"{field_name} must be in canonical source/time order")
            if (
                previous_span is not None
                and previous_span.source_version == span.source_version
                and span.start_us < previous_span.end_us
            ):
                raise ValidationError(f"{field_name} spans must not overlap")
            previous_key = key
            previous_span = span
