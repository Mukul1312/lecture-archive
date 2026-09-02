"""Immutable Narrator Voice identities.

ActorId and ArtifactId deliberately remain the kernel-owned identities.  Every
identity below belongs to this bounded context and is nominal at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from heritage_archive.kernel import ValidationError


_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@dataclass(frozen=True, slots=True)
class _NarratorId:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _UUID4.fullmatch(self.value) is None:
            raise ValidationError(
                f"{type(self).__name__} must be exact lowercase RFC 4122 UUIDv4 text"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AuthorizationRecordId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class AuthorityChangeId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class NarrationJobId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class DiaryEpisodeId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class PassageId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class PassageRenderRecipeId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class GenerationPreviewId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class GenerationAttemptId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class NarrationAssemblyAttemptId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class EpisodeAssemblyAttemptId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class TakeId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class ReviewDecisionId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class SelectionDecisionId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class NarrationMasterId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class MasterListeningDecisionId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class NarrationMasterSnapshotId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class EpisodeSpeechMasterId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class EpisodeListeningDecisionId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class CueId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class TimedNarrationPackageId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class ProviderEventId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class AttemptWorkspaceId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class BudgetReservationId(_NarratorId):
    pass


@dataclass(frozen=True, slots=True)
class CommandId(_NarratorId):
    pass
