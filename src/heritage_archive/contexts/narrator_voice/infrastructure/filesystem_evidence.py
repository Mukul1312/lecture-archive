"""Immutable local artifact publication and recovery evidence verification."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat

from heritage_archive.kernel import ArtifactId, ArtifactRef, ContentDigest, ValidationError, require_canonical_text
from heritage_archive.platform.storage.local_files import (
    PublicationEvidenceMismatch,
    SingleWriterFileLock,
    publish_bytes_no_clobber,
    replace_bytes_atomically,
)

from ..application.ports import (
    IdentifierSource,
    MediaInspector,
    VerifiedArtifactRecoveryFacts,
    VerifiedProviderRecoveryFacts,
    VerifiedWorkspaceRecoveryFacts,
)
from ..application.recovery import (
    EpisodeAssemblyRecoveryTarget,
    GenerationRecoveryTarget,
    NarrationAssemblyRecoveryTarget,
    RecoveryStage,
    RecoveryTarget,
)
from ..application.schema_v1 import decode_schema_v1, encode_schema_v1
from ..domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    DecodedMediaFacts,
    ProviderEventKind,
    PublishedArtifact,
    SubmissionEvidence,
)
from ..domain.ids import (
    EpisodeAssemblyAttemptId,
    GenerationAttemptId,
    NarrationAssemblyAttemptId,
)
from ..domain.values import SafeRelativeArtifactPath
from .local_root import LocalNarrationRoot


_MEDIA_TYPE_TOKEN = r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+\-]*"
_MEDIA_TYPE = re.compile(rf"^{_MEDIA_TYPE_TOKEN}/{_MEDIA_TYPE_TOKEN}$")


class FilesystemArtifactStore:
    """Publishes one immutable payload at one pre-authorized local path."""

    def __init__(self, root: LocalNarrationRoot, identifiers: IdentifierSource) -> None:
        if type(root) is not LocalNarrationRoot:
            raise ValidationError("filesystem artifact store requires a LocalNarrationRoot")
        if not callable(getattr(identifiers, "new_id", None)):
            raise ValidationError("filesystem artifact store requires an IdentifierSource")
        self._root = root
        self._identifiers = identifiers

    def publish(
        self,
        location: SafeRelativeArtifactPath,
        payload: bytes,
        media_type: str,
        published_at,
    ) -> PublishedArtifact:
        if type(location) is not SafeRelativeArtifactPath:
            raise ValidationError("artifact publication requires a SafeRelativeArtifactPath")
        if type(payload) is not bytes:
            raise ValidationError("artifact publication payload must be bytes")
        _validate_media_type(media_type)
        _validate_publication_time(published_at)
        with SingleWriterFileLock(self._root.writer_lock):
            destination = _prepare_publish_destination(self._root, location)
            if os.path.lexists(destination):
                raise ValidationError("immutable artifact destination is already occupied")
            artifact_id = self._identifiers.new_id(ArtifactId)
            if type(artifact_id) is not ArtifactId:
                raise ValidationError("identifier source did not return an ArtifactId")
            try:
                evidence = publish_bytes_no_clobber(
                    self._root.staging,
                    destination,
                    payload,
                    staging_suffix=".artifact",
                )
            except FileExistsError as error:
                raise ValidationError("immutable artifact destination is already occupied") from error
            except (OSError, PublicationEvidenceMismatch) as error:
                raise ValidationError("immutable artifact publication failed") from error
        return PublishedArtifact(
            ArtifactRef(
                artifact_id,
                ContentDigest("sha256", evidence.sha256_hex),
                evidence.byte_length,
                media_type,
            ),
            location,
            published_at,
        )


class FilesystemArtifactEvidenceVerifier:
    """Checks workspace artifact facts against immutable bytes without retaining state."""

    def __init__(self, root: LocalNarrationRoot, media_inspector: MediaInspector | None = None) -> None:
        if type(root) is not LocalNarrationRoot:
            raise ValidationError("filesystem artifact verifier requires a LocalNarrationRoot")
        if media_inspector is not None and not callable(getattr(media_inspector, "inspect_canonical_wav", None)):
            raise ValidationError("filesystem artifact verifier media inspector is invalid")
        self._root = root
        self._media_inspector = media_inspector

    def verify(self, workspace: AttemptWorkspaceEvidence | None) -> VerifiedArtifactRecoveryFacts:
        if workspace is None:
            return VerifiedArtifactRecoveryFacts(False, False, False, False)
        if type(workspace) is not AttemptWorkspaceEvidence:
            raise ValidationError("artifact verifier requires an AttemptWorkspaceEvidence or None")
        artifact_observed = bool(workspace.staged_artifacts)
        publication_observed = bool(workspace.published_artifacts)
        published_references = tuple(item.reference for item in workspace.published_artifacts)
        locations_match_staging = workspace.staged_artifacts == published_references
        bytes_match_publications = publication_observed and all(
            self._publication_matches(publication) for publication in workspace.published_artifacts
        )
        verified = (
            artifact_observed
            and publication_observed
            and locations_match_staging
            and bytes_match_publications
        )
        return VerifiedArtifactRecoveryFacts(
            artifact_observed,
            verified,
            publication_observed,
            verified,
        )

    def read_verified_bytes(self, publication: PublishedArtifact) -> bytes:
        """Return immutable payload bytes only after the publication evidence matches."""
        if type(publication) is not PublishedArtifact:
            raise ValidationError("artifact byte read requires a PublishedArtifact")
        try:
            destination = _artifact_path(self._root, publication.relative_location)
            if not os.path.lexists(destination):
                raise ValidationError("published artifact is missing")
            _reject_existing_reparse_point(destination)
            if not destination.is_file():
                raise ValidationError("published artifact must be a regular file")
            payload = destination.read_bytes()
        except OSError as error:
            raise ValidationError("published artifact cannot be read safely") from error
        if (
            ContentDigest.from_bytes(payload) != publication.reference.content_digest
            or len(payload) != publication.reference.byte_size
        ):
            raise ValidationError("published artifact bytes do not match immutable evidence")
        return payload

    def _publication_matches(self, publication: PublishedArtifact) -> bool:
        try:
            self.read_verified_bytes(publication)
        except ValidationError:
            return False
        return True

    def recover_media(
        self,
        workspace: AttemptWorkspaceEvidence,
        artifact: PublishedArtifact,
    ) -> DecodedMediaFacts:
        """Inspect exactly one verified workspace publication without inventing media facts."""
        if type(workspace) is not AttemptWorkspaceEvidence or type(artifact) is not PublishedArtifact:
            raise ValidationError("media recovery requires exact workspace and publication evidence")
        if self._media_inspector is None:
            raise ValidationError("media recovery requires an injected MediaInspector")
        verified = self.verify(workspace)
        if not verified.artifact_verified or not verified.publication_verified:
            raise ValidationError("media recovery requires a fully verified workspace")
        audio_publications = tuple(
            publication
            for publication in workspace.published_artifacts
            if publication.reference.media_type == "audio/wav"
        )
        if (
            artifact.reference.media_type != "audio/wav"
            or audio_publications != (artifact,)
            or workspace.staged_artifacts.count(artifact.reference) != 1
            or workspace.published_artifacts.count(artifact) != 1
        ):
            raise ValidationError("media recovery requires one exact canonical audio publication")
        payload = self.read_verified_bytes(artifact)
        try:
            media = self._media_inspector.inspect_canonical_wav(payload)
        except Exception as error:
            raise ValidationError("published artifact media cannot be inspected") from error
        if type(media) is not DecodedMediaFacts or media.all_digital_silence:
            raise ValidationError("media recovery requires non-silent decoded media facts")
        return media


class FilesystemAttemptWorkspaceStore:
    """Durably replaces one canonical evidence file per nominal attempt identity."""

    def __init__(self, root: LocalNarrationRoot) -> None:
        if type(root) is not LocalNarrationRoot:
            raise ValidationError("filesystem workspace store requires a LocalNarrationRoot")
        self._root = root

    def load(
        self,
        attempt_id: GenerationAttemptId | NarrationAssemblyAttemptId | EpisodeAssemblyAttemptId,
    ) -> AttemptWorkspaceEvidence | None:
        kind = _attempt_kind_for_id(attempt_id)
        path = _workspace_path(self._root, kind, attempt_id.value, create_directory=False)
        if not os.path.lexists(path):
            return None
        _reject_existing_reparse_point(path)
        try:
            if not path.is_file():
                raise ValidationError("attempt workspace evidence must be a regular file")
            workspace = decode_schema_v1(path.read_bytes(), AttemptWorkspaceEvidence)
        except (OSError, TypeError, ValueError) as error:
            raise ValidationError("attempt workspace evidence is unreadable or noncanonical") from error
        if workspace.attempt_kind is not kind or workspace.attempt_id != attempt_id:
            raise ValidationError("attempt workspace filename and typed evidence do not match")
        return workspace

    def save(self, workspace: AttemptWorkspaceEvidence) -> None:
        if type(workspace) is not AttemptWorkspaceEvidence:
            raise ValidationError("workspace store requires AttemptWorkspaceEvidence")
        path = _workspace_path(self._root, workspace.attempt_kind, workspace.attempt_id.value, create_directory=True)
        with SingleWriterFileLock(self._root.writer_lock):
            existing = self.load(workspace.attempt_id)
            if existing == workspace:
                return
            if existing is not None:
                _validate_workspace_progression(existing, workspace)
            try:
                replace_bytes_atomically(self._root.staging, path, encode_schema_v1(workspace))
            except (OSError, PublicationEvidenceMismatch) as error:
                raise ValidationError("attempt workspace evidence cannot be durably replaced") from error


class FilesystemAttemptWorkspaceVerifier:
    """Derives trusted local recovery facts from typed workspace evidence only."""

    def verify(
        self,
        workspace: AttemptWorkspaceEvidence | None,
        target: RecoveryTarget,
        attempt_state: AttemptState,
        reservation_revision: int,
        expected_frozen_plan_digest: ContentDigest | None,
    ) -> VerifiedWorkspaceRecoveryFacts:
        if type(attempt_state) is not AttemptState or type(reservation_revision) is not int or reservation_revision < 0:
            raise ValidationError("recovery verification requires exact attempt state and reservation revision")
        if expected_frozen_plan_digest is not None and type(expected_frozen_plan_digest) is not ContentDigest:
            raise ValidationError("recovery verification expected plan digest is invalid")
        if workspace is None:
            return VerifiedWorkspaceRecoveryFacts(False, False, RecoveryStage.RESERVED, SubmissionEvidence.NOT_STARTED)
        if type(workspace) is not AttemptWorkspaceEvidence:
            raise ValidationError("recovery verification requires workspace evidence or None")
        expected_kind, aggregate_id, attempt_id, budget_id = _target_binding(target)
        matches = (
            workspace.attempt_kind is expected_kind
            and workspace.aggregate_id == aggregate_id
            and workspace.attempt_id == attempt_id
            and workspace.reservation_revision == reservation_revision
            and workspace.budget_reservation_id == budget_id
        )
        return VerifiedWorkspaceRecoveryFacts(
            matches,
            workspace.frozen_plan_digest == expected_frozen_plan_digest,
            _workspace_evidence_stage(workspace),
            workspace.submission,
        )


class FilesystemProviderEventVerifier:
    """Seals local provider-event structure; it never attests remote-provider authenticity."""

    def verify(self, workspace: AttemptWorkspaceEvidence | None) -> VerifiedProviderRecoveryFacts:
        if workspace is None:
            return VerifiedProviderRecoveryFacts(None, False)
        if type(workspace) is not AttemptWorkspaceEvidence:
            raise ValidationError("provider event verification requires workspace evidence or None")
        if workspace.attempt_kind is not AttemptKind.GENERATION:
            return VerifiedProviderRecoveryFacts(None, workspace.events == ())
        events = workspace.events
        terminals = tuple(event for event in events if event.terminal_classification is not None)
        sealed = (
            bool(events)
            and tuple(event.sequence for event in events) == tuple(range(len(events)))
            and len(terminals) == 1
            and events[-1] is terminals[0]
            and events[-1].kind is ProviderEventKind.TERMINAL
        )
        return VerifiedProviderRecoveryFacts(
            events[-1].terminal_classification if sealed else None,
            sealed,
        )


_WORKSPACE_KIND_BY_ATTEMPT_TYPE = {
    GenerationAttemptId: AttemptKind.GENERATION,
    NarrationAssemblyAttemptId: AttemptKind.NARRATION_ASSEMBLY,
    EpisodeAssemblyAttemptId: AttemptKind.EPISODE_ASSEMBLY,
}
_WORKSPACE_STATE_SUCCESSORS = {
    AttemptState.RESERVED: {
        AttemptState.RESERVED,
        AttemptState.INPUT_FROZEN,
        AttemptState.EXTERNAL_WORK_STARTED,
        AttemptState.ARTIFACTS_STAGED,
        AttemptState.ARTIFACTS_PUBLISHED,
        AttemptState.BLOCKED,
        AttemptState.FAILED,
        AttemptState.UNKNOWN,
        AttemptState.QUARANTINED,
    },
    AttemptState.INPUT_FROZEN: {
        AttemptState.INPUT_FROZEN,
        AttemptState.EXTERNAL_WORK_STARTED,
        AttemptState.ARTIFACTS_STAGED,
        AttemptState.ARTIFACTS_PUBLISHED,
        AttemptState.BLOCKED,
        AttemptState.FAILED,
        AttemptState.UNKNOWN,
        AttemptState.QUARANTINED,
    },
    AttemptState.EXTERNAL_WORK_STARTED: {
        AttemptState.EXTERNAL_WORK_STARTED,
        AttemptState.ARTIFACTS_STAGED,
        AttemptState.ARTIFACTS_PUBLISHED,
        AttemptState.FAILED,
        AttemptState.UNKNOWN,
        AttemptState.QUARANTINED,
    },
    AttemptState.ARTIFACTS_STAGED: {
        AttemptState.ARTIFACTS_STAGED,
        AttemptState.ARTIFACTS_PUBLISHED,
        AttemptState.FAILED,
        AttemptState.UNKNOWN,
        AttemptState.QUARANTINED,
    },
    AttemptState.ARTIFACTS_PUBLISHED: {
        AttemptState.ARTIFACTS_PUBLISHED,
        AttemptState.COMPLETED,
        AttemptState.QUARANTINED,
    },
}
_SUBMISSION_SUCCESSOR = {
    SubmissionEvidence.NOT_STARTED: {
        SubmissionEvidence.NOT_STARTED,
        SubmissionEvidence.DEFINITELY_NOT_SENT,
        SubmissionEvidence.STARTED,
        SubmissionEvidence.COMPLETED,
        SubmissionEvidence.AMBIGUOUS,
    },
    SubmissionEvidence.STARTED: {
        SubmissionEvidence.STARTED,
        SubmissionEvidence.COMPLETED,
        SubmissionEvidence.AMBIGUOUS,
    },
    SubmissionEvidence.COMPLETED: {SubmissionEvidence.COMPLETED},
    SubmissionEvidence.DEFINITELY_NOT_SENT: {SubmissionEvidence.DEFINITELY_NOT_SENT},
    SubmissionEvidence.AMBIGUOUS: {SubmissionEvidence.AMBIGUOUS},
}


def _attempt_kind_for_id(
    attempt_id: GenerationAttemptId | NarrationAssemblyAttemptId | EpisodeAssemblyAttemptId,
) -> AttemptKind:
    kind = _WORKSPACE_KIND_BY_ATTEMPT_TYPE.get(type(attempt_id))
    if kind is None:
        raise ValidationError("workspace load requires an exact nominal attempt identity")
    return kind


def _workspace_path(
    root: LocalNarrationRoot,
    kind: AttemptKind,
    attempt_value: str,
    *,
    create_directory: bool,
) -> Path:
    if type(kind) is not AttemptKind or type(attempt_value) is not str:
        raise ValidationError("workspace path requires exact attempt-kind evidence")
    attempts = root.attempts
    _require_existing_artifact_directory(attempts)
    kind_directory = attempts / kind.value
    if os.path.lexists(kind_directory):
        _require_existing_artifact_directory(kind_directory)
    elif not create_directory:
        return kind_directory / f"{attempt_value}.json"
    else:
        try:
            kind_directory.mkdir()
        except FileExistsError:
            _require_existing_artifact_directory(kind_directory)
        except OSError as error:
            raise ValidationError("workspace kind directory cannot be created") from error
        else:
            _require_existing_artifact_directory(kind_directory)
    result = kind_directory / f"{attempt_value}.json"
    _reject_existing_reparse_point(result)
    if not result.is_relative_to(attempts):
        raise ValidationError("workspace path escapes the local attempt root")
    return result


def _validate_workspace_progression(
    existing: AttemptWorkspaceEvidence,
    candidate: AttemptWorkspaceEvidence,
) -> None:
    if existing.attempt_id != candidate.attempt_id or existing.attempt_kind is not candidate.attempt_kind:
        raise ValidationError("workspace attempt identity is immutable")
    immutable = (
        "workspace_id",
        "attempt_kind",
        "aggregate_id",
        "attempt_id",
        "reservation_revision",
        "budget_reservation_id",
        "preview_digest",
    )
    if any(getattr(existing, field) != getattr(candidate, field) for field in immutable):
        raise ValidationError("workspace identity, reservation and preview bindings are immutable")
    _validate_frozen_bindings(existing, candidate)
    for field in ("events", "staged_artifacts", "published_artifacts", "recovery_evidence"):
        before = getattr(existing, field)
        after = getattr(candidate, field)
        if after[:len(before)] != before:
            raise ValidationError("workspace evidence can only grow by an exact tuple prefix")
    if any(event.terminal_classification is not None for event in existing.events) and candidate.events != existing.events:
        raise ValidationError("sealed provider evidence cannot be extended or rewritten")
    if candidate.submission not in _SUBMISSION_SUCCESSOR[existing.submission]:
        raise ValidationError("workspace submission evidence cannot regress or conflict")
    if existing.state.terminal:
        raise ValidationError("terminal workspace evidence cannot be rewritten")
    if candidate.state not in _WORKSPACE_STATE_SUCCESSORS[existing.state]:
        raise ValidationError("workspace state cannot regress or take a contradictory terminal transition")


def _validate_frozen_bindings(existing: AttemptWorkspaceEvidence, candidate: AttemptWorkspaceEvidence) -> None:
    before_input, before_plan = existing.effective_input_digest, existing.frozen_plan_digest
    after_input, after_plan = candidate.effective_input_digest, candidate.frozen_plan_digest
    if existing.attempt_kind is AttemptKind.GENERATION:
        if before_input is None and before_plan is None:
            if (after_input is None) != (after_plan is None) or (after_input is not None and after_input != after_plan):
                raise ValidationError("generation input and frozen plan must become the same digest together")
            return
        if before_input != after_input or before_plan != after_plan:
            raise ValidationError("frozen generation input and plan bindings are immutable")
        return
    if before_input != after_input or before_plan != after_plan:
        raise ValidationError("assembly frozen plan bindings are immutable")


def _target_binding(target: RecoveryTarget):
    if type(target) is GenerationRecoveryTarget:
        return AttemptKind.GENERATION, target.job_id, target.attempt_id, target.budget_reservation_id
    if type(target) is NarrationAssemblyRecoveryTarget:
        return AttemptKind.NARRATION_ASSEMBLY, target.job_id, target.attempt_id, None
    if type(target) is EpisodeAssemblyRecoveryTarget:
        return AttemptKind.EPISODE_ASSEMBLY, target.episode_id, target.attempt_id, None
    raise ValidationError("recovery target is not supported by filesystem evidence")


def _workspace_evidence_stage(workspace: AttemptWorkspaceEvidence) -> RecoveryStage:
    published = tuple(item.reference for item in workspace.published_artifacts)
    if published and workspace.staged_artifacts == published:
        return RecoveryStage.ARTIFACTS_PUBLISHED
    if workspace.staged_artifacts:
        return RecoveryStage.ARTIFACTS_STAGED
    if workspace.state is AttemptState.EXTERNAL_WORK_STARTED:
        return RecoveryStage.EXTERNAL_WORK_STARTED
    if workspace.submission in {SubmissionEvidence.STARTED, SubmissionEvidence.COMPLETED, SubmissionEvidence.AMBIGUOUS}:
        return RecoveryStage.EXTERNAL_WORK_STARTED
    if workspace.effective_input_digest is not None or workspace.frozen_plan_digest is not None:
        return RecoveryStage.INPUT_FROZEN
    return RecoveryStage.RESERVED


def _validate_media_type(value: object) -> str:
    media_type = require_canonical_text(value, field="media_type", nonempty=True)
    if _MEDIA_TYPE.fullmatch(media_type) is None:
        raise ValidationError("media_type must be a nonempty type/subtype value")
    return media_type


def _validate_publication_time(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError("artifact publication time must be an aware UTC datetime")
    return value


def _artifact_path(root: LocalNarrationRoot, location: SafeRelativeArtifactPath) -> Path:
    current = root.artifacts
    _reject_existing_reparse_point(current)
    for component in location.value.split("/"):
        current /= component
        _reject_existing_reparse_point(current)
    if not current.is_relative_to(root.artifacts):
        raise ValidationError("artifact location escapes the local artifact root")
    return current


def _prepare_publish_destination(root: LocalNarrationRoot, location: SafeRelativeArtifactPath) -> Path:
    current = root.artifacts
    _require_existing_artifact_directory(current)
    parts = location.value.split("/")
    for component in parts[:-1]:
        current /= component
        if os.path.lexists(current):
            _require_existing_artifact_directory(current)
            continue
        try:
            current.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise ValidationError("artifact parent directory cannot be created") from error
        _require_existing_artifact_directory(current)
    destination = current / parts[-1]
    _reject_existing_reparse_point(destination)
    return destination


def _require_existing_artifact_directory(path: Path) -> None:
    if not os.path.lexists(path):
        raise ValidationError("artifact root directory is missing")
    _reject_existing_reparse_point(path)
    try:
        is_directory = path.is_dir()
    except OSError as error:
        raise ValidationError("artifact path ancestor cannot be inspected") from error
    if not is_directory:
        raise ValidationError("artifact path ancestor must be a directory")


def _reject_existing_reparse_point(path: Path) -> None:
    if os.path.lexists(path) and _is_reparse_point(path):
        raise ValidationError("artifact location cannot traverse a reparse point")


def _is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
