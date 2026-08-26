"""Application-owned outbound ports.

Design section 10.2 names these; the application owns the interfaces and
infrastructure implements them, so dependencies point inward. Every port speaks
domain language: none exposes SQL, a filesystem path, a subprocess exception, an
HTTP response, or a JSONL row.
"""

from .repositories import (
    ASRProposalSetRepository,
    ProductionRepository,
    ReleasePolicyVersionRepository,
    ReviewFindingRepository,
    ReviewRoundRepository,
    TranscriptEditionRepository,
    Versioned,
)
from .infrastructure import (
    ArtifactDerivationVerifier,
    ArtifactMetadataReader,
    ArtifactStore,
    Clock,
    DomainEventOutbox,
    IdGenerator,
    OperationRecord,
    OperationRecorder,
    StagedArtifact,
    UnitOfWork,
)
from .adapters import (
    ActorAuthority,
    ApprovedReleaseExporter,
    LegacyProposalTranslator,
    ProcessResult,
    ProcessRunner,
    ReleasePackageRenderer,
    ReviewPackageRenderer,
    ReviewSubmissionParser,
    TranslatedProposal,
    VerifiedProof,
)
from .operations import (
    BackupManifest,
    BackupService,
    IntegrityIssue,
    IntegrityService,
    MigrationAuthorityRecord,
    MigrationAuthorityRecorder,
    ReadService,
)

__all__ = [
    "ASRProposalSetRepository",
    "ActorAuthority",
    "ApprovedReleaseExporter",
    "ArtifactDerivationVerifier",
    "ArtifactMetadataReader",
    "ArtifactStore",
    "BackupService",
    "Clock",
    "DomainEventOutbox",
    "IdGenerator",
    "IntegrityService",
    "LegacyProposalTranslator",
    "MigrationAuthorityRecorder",
    "OperationRecorder",
    "ProcessRunner",
    "ProductionRepository",
    "ReadService",
    "ReleasePackageRenderer",
    "ReleasePolicyVersionRepository",
    "ReviewFindingRepository",
    "ReviewPackageRenderer",
    "ReviewRoundRepository",
    "ReviewSubmissionParser",
    "TranscriptEditionRepository",
    "UnitOfWork",
]
