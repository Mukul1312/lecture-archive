"""Commands that create sealed Transcription roots.

All three create rather than mutate, so none carries an expected version. Their
idempotency keys are large by design: section 9.4 requires edition creation to
hash the Production ID, the complete source-version refs, the parent edition
ref, the transcript scope, the ordered revision manifest, and the complete
edition-change manifest. A convenient subset would let two different editions
share one key.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import (
    ArtifactRef,
    OperationId,
    ProductionId,
    ProposalSetId,
    SourceVersionRef,
    TranscriptEditionId,
    TranscriptScope,
)
from heritage_production.domain.transcription import (
    EditionChangeManifest,
    GapDeclaration,
    ParentEditionManifest,
    ProposalSetRef,
    SegmentRevision,
    StewardAttestation,
)

from .context import (
    ActorContext,
    require_envelope,
    require_exact,
    require_text,
    require_tuple,
)


@dataclass(frozen=True, slots=True)
class ImportProposalPackage:
    """Design 10.4: the operator supplies the source; the package never binds it.

    `import_root` is the one explicit root a relative locator may resolve under.
    An absolute legacy path is retained as non-authoritative evidence only.
    """

    operation_id: OperationId
    actor: ActorContext
    proposal_set_id: ProposalSetId
    source_version: SourceVersionRef
    raw_package: ArtifactRef
    import_root: str
    importing_adapter: str
    importing_adapter_version: str
    steward_attestation: StewardAttestation | None = None

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.proposal_set_id, ProposalSetId, "proposal_set_id")
        require_exact(self.source_version, SourceVersionRef, "source_version")
        require_exact(self.raw_package, ArtifactRef, "raw_package")
        require_text(self.import_root, field="import_root")
        # Design 9.4 puts adapter identity and version in this command's
        # idempotency key, so they are declared inputs rather than something
        # learned from the translation. The handler checks the declaration
        # against the adapter that actually ran.
        require_text(self.importing_adapter, field="importing_adapter")
        require_text(self.importing_adapter_version, field="importing_adapter_version")
        if self.steward_attestation is not None:
            require_exact(
                self.steward_attestation, StewardAttestation, "steward_attestation"
            )


@dataclass(frozen=True, slots=True)
class CreateInitialTranscriptEdition:
    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    transcript_edition_id: TranscriptEditionId
    source_versions: tuple[SourceVersionRef, ...]
    transcript_scope: TranscriptScope
    proposal_set_refs: tuple[ProposalSetRef, ...]
    revisions: tuple[SegmentRevision, ...]
    gaps: tuple[GapDeclaration, ...]
    change_manifest: EditionChangeManifest

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(
            self.transcript_edition_id, TranscriptEditionId, "transcript_edition_id"
        )
        require_tuple(self.source_versions, SourceVersionRef, "source_versions")
        require_exact(self.transcript_scope, TranscriptScope, "transcript_scope")
        require_tuple(self.proposal_set_refs, ProposalSetRef, "proposal_set_refs")
        require_tuple(self.revisions, SegmentRevision, "revisions")
        require_tuple(self.gaps, GapDeclaration, "gaps")
        require_exact(self.change_manifest, EditionChangeManifest, "change_manifest")


@dataclass(frozen=True, slots=True)
class CreateSuccessorTranscriptEdition:
    """An accepted finding never alters an edition; it justifies a successor."""

    operation_id: OperationId
    actor: ActorContext
    production_id: ProductionId
    transcript_edition_id: TranscriptEditionId
    parent: ParentEditionManifest
    source_versions: tuple[SourceVersionRef, ...]
    transcript_scope: TranscriptScope
    proposal_set_refs: tuple[ProposalSetRef, ...]
    revisions: tuple[SegmentRevision, ...]
    gaps: tuple[GapDeclaration, ...]
    change_manifest: EditionChangeManifest

    def __post_init__(self) -> None:
        require_envelope(self.operation_id, self.actor)
        require_exact(self.production_id, ProductionId, "production_id")
        require_exact(
            self.transcript_edition_id, TranscriptEditionId, "transcript_edition_id"
        )
        require_exact(self.parent, ParentEditionManifest, "parent")
        require_tuple(self.source_versions, SourceVersionRef, "source_versions")
        require_exact(self.transcript_scope, TranscriptScope, "transcript_scope")
        require_tuple(self.proposal_set_refs, ProposalSetRef, "proposal_set_refs")
        require_tuple(self.revisions, SegmentRevision, "revisions")
        require_tuple(self.gaps, GapDeclaration, "gaps")
        require_exact(self.change_manifest, EditionChangeManifest, "change_manifest")


__all__ = [
    "CreateInitialTranscriptEdition",
    "CreateSuccessorTranscriptEdition",
    "ImportProposalPackage",
]
