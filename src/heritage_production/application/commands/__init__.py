"""Every command named in design section 9.2, as an immutable DTO.

A command is a value, not a request: it validates its own shape at construction,
so a handler never re-checks types and a malformed command cannot reach an
aggregate. Each carries an `OperationId` for idempotency and an `ActorContext`;
those targeting an existing mutable root also carry the version they expect.
"""

from .context import ActorContext
from .production import (
    ApproveReleaseCandidate,
    AssembleReleaseCandidate,
    AttachSourceRecording,
    ConfigureExternalGates,
    CreateProduction,
    RecordExternalSignOff,
    SelectCandidateEdition,
    SelectReleasePolicyVersion,
)
from .transcription import (
    CreateInitialTranscriptEdition,
    CreateSuccessorTranscriptEdition,
    ImportProposalPackage,
)
from .review import (
    CloseReviewRound,
    DecideReviewFinding,
    ExportReviewPackage,
    FinalizeReviewSubmission,
    ImportReviewSubmission,
    OpenReviewRound,
    RecordReviewSignOff,
    SubmitReviewFinding,
)
from .release import (
    AssembleReleaseContent,
    CreateReleasePolicyVersion,
    EvaluateReleaseEligibility,
    ExportApprovedRelease,
    RegisterActorCredential,
    RegisterRubric,
)
from .migration import RecordProductionAuthorityCutover, SupersedePreWriteCutover

__all__ = [
    "ActorContext",
    "ApproveReleaseCandidate",
    "AssembleReleaseCandidate",
    "AssembleReleaseContent",
    "AttachSourceRecording",
    "CloseReviewRound",
    "ConfigureExternalGates",
    "CreateInitialTranscriptEdition",
    "CreateProduction",
    "CreateReleasePolicyVersion",
    "CreateSuccessorTranscriptEdition",
    "DecideReviewFinding",
    "EvaluateReleaseEligibility",
    "ExportApprovedRelease",
    "ExportReviewPackage",
    "FinalizeReviewSubmission",
    "ImportProposalPackage",
    "ImportReviewSubmission",
    "OpenReviewRound",
    "RecordExternalSignOff",
    "RecordProductionAuthorityCutover",
    "RecordReviewSignOff",
    "RegisterActorCredential",
    "RegisterRubric",
    "SelectCandidateEdition",
    "SelectReleasePolicyVersion",
    "SubmitReviewFinding",
    "SupersedePreWriteCutover",
]
