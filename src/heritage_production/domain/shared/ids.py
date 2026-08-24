"""Opaque canonical identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import ValidationError


_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@dataclass(frozen=True, slots=True)
class _OpaqueId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _UUID4.fullmatch(self.value) is None:
            raise ValidationError(
                f"{type(self).__name__} must be exact lowercase RFC 4122 UUIDv4 text"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ProductionId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class SourceRecordingId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class SourceVersionId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ProposalSetId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ProposalItemId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class TranscriptEditionId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class SegmentId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class SegmentRevisionId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ReviewRoundId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ReviewPackageId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ReviewSubmissionId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ReviewFindingId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class RubricId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ReleasePolicyVersionId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ExternalGateSetId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseContentManifestId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseCandidateId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class EligibilityAssessmentId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class BackupId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class MigrationDecisionId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class ActorId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class OperationId(_OpaqueId):
    pass


@dataclass(frozen=True, slots=True)
class DomainEventId(_OpaqueId):
    pass
