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
)

from ..application.ports import IdentifierSource, VerifiedArtifactRecoveryFacts
from ..domain.evidence import AttemptWorkspaceEvidence, PublishedArtifact
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

    def __init__(self, root: LocalNarrationRoot) -> None:
        if type(root) is not LocalNarrationRoot:
            raise ValidationError("filesystem artifact verifier requires a LocalNarrationRoot")
        self._root = root

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
