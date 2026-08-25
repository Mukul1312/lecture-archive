"""Anti-corruption ports for legacy tools, review packages, and release output.

Every one of these sits at the boundary described in design section 10.4: the
adapter receives an application-owned request, resolves exact input artifacts,
validates output, and translates only valid results into domain values. Legacy
schema fields the domain does not understand stay raw evidence; the adapter
never adds guessed semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from heritage_production.domain.production import ExternalSignOff
from heritage_production.domain.review import ReviewSignOff, ReviewTargetManifest
from heritage_production.domain.shared import (
    ActorCredentialRef,
    ArtifactRef,
    ContentDigest,
    OperationId,
    SourceVersionRef,
)


@dataclass(frozen=True, slots=True)
class TranslatedProposal:
    """A legacy package translated into proposal language, warnings included.

    Warnings are structured evidence. Design 14.3 forbids a warning silently
    downgrading a failure into a pass, so they travel beside the payload rather
    than replacing it.
    """

    raw_package: ArtifactRef
    tool_name: str
    model_name: str | None
    model_revision: str | None
    configuration_digest: ContentDigest | None
    warnings: tuple[str, ...]
    quarantined: bool
    quarantine_reason: str | None


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """A completed subprocess attempt with its provenance captured."""

    exit_status: int
    stdout: bytes
    stderr: bytes
    started_at_us: int
    ended_at_us: int
    executable_version: str


@dataclass(frozen=True, slots=True)
class VerifiedProof:
    """The outcome of checking one externally produced signature."""

    verified: bool
    algorithm: str
    credential_fingerprint: ContentDigest
    diagnostic: str


@runtime_checkable
class LegacyProposalTranslator(Protocol):
    """Design 10.4: an absolute legacy path is never dereferenced as authority."""

    def translate(
        self,
        *,
        raw_package: ArtifactRef,
        import_root: str,
        bound_source: SourceVersionRef,
    ) -> TranslatedProposal: ...


@runtime_checkable
class ProcessRunner(Protocol):
    """Design 10.5: allowlisted executable, argument array, never a shell string."""

    def run(
        self,
        *,
        executable: str,
        arguments: tuple[str, ...],
        timeout_seconds: int,
        operation_id: OperationId,
    ) -> ProcessResult: ...


@runtime_checkable
class ReviewPackageRenderer(Protocol):
    """Deterministic offline review ZIPs (design section 12.2)."""

    def render(
        self,
        *,
        target_manifest: ReviewTargetManifest,
        assigned_credential: ActorCredentialRef,
        operation_id: OperationId,
    ) -> ArtifactRef: ...


@runtime_checkable
class ReviewSubmissionParser(Protocol):
    """Validates an exported result wrapper before any finding is created."""

    def parse(self, *, raw_package: ArtifactRef) -> object: ...


@runtime_checkable
class ReleasePackageRenderer(Protocol):
    """Design 13.3: rebuilding from identical inputs is byte-identical."""

    def render(self, *, approval_digest: ContentDigest, operation_id: OperationId) -> ArtifactRef: ...


@runtime_checkable
class ApprovedReleaseExporter(Protocol):
    """Design 13.4: verify the stored archive, then copy those exact bytes.

    It never re-renders content, so a failed copy leaves the approval and the
    stored package unchanged.
    """

    def export(self, *, archive: ArtifactRef, destination: str, operation_id: OperationId) -> str: ...


@runtime_checkable
class ActorAuthority(Protocol):
    """Verifies pinned reviewer and signatory credentials (design section 8.9).

    The application never creates or stores a private key; only public
    verification evidence is retained.
    """

    def verify_review_sign_off(self, sign_off: ReviewSignOff) -> VerifiedProof: ...

    def verify_external_sign_off(self, sign_off: ExternalSignOff) -> VerifiedProof: ...
