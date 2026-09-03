"""Immutable canonical snapshot repositories for the three Narrator Voice roots."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from heritage_archive.kernel import ValidationError
from heritage_archive.platform.storage.local_files import (
    PublicationEvidenceMismatch,
    SingleWriterFileLock,
    publish_bytes_no_clobber,
)

from ..application.schema_v1 import decode_schema_v1, encode_schema_v1
from ..domain.authorization import AuthorizationRecord, AuthorizationRecordSnapshot
from ..domain.diary_episode import DiaryEpisode, DiaryEpisodeSnapshot
from ..domain.ids import AuthorizationRecordId, DiaryEpisodeId, NarrationJobId
from ..domain.narration_job import NarrationJob, NarrationJobSnapshot
from .local_root import LocalNarrationRoot


class _FilesystemSnapshotRepository:
    """Shared append-only revision-file implementation for one exact root type."""

    def __init__(
        self,
        root: LocalNarrationRoot,
        aggregate_kind: str,
        aggregate_id_type: type[Any],
        snapshot_type: type[Any],
        root_type: type[Any],
    ) -> None:
        if type(root) is not LocalNarrationRoot:
            raise ValidationError("filesystem repository requires a LocalNarrationRoot")
        self._root = root
        self._aggregate_kind = aggregate_kind
        self._aggregate_id_type = aggregate_id_type
        self._snapshot_type = snapshot_type
        self._root_type = root_type

    def load(self, aggregate_id: object) -> Any | None:
        return self._current_contiguous(aggregate_id)[1]

    def save(self, root: object, expected_revision: int | None) -> bool:
        if type(root) is not self._root_type:
            raise ValidationError("filesystem repository received the wrong aggregate root type")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValidationError("expected revision must be a positive integer or None")
        aggregate_id = self._aggregate_id(root)
        with SingleWriterFileLock(self._root.writer_lock):
            current_revision, _ = self._current_contiguous(aggregate_id)
            if expected_revision != current_revision:
                return False
            revision = 1 if current_revision is None else current_revision + 1
            if root.revision != revision:
                raise ValidationError("aggregate revision must be the next immutable repository revision")
            destination = self._revision_path(aggregate_id, revision)
            if os.path.lexists(destination):
                raise ValidationError("immutable aggregate revision destination is already occupied")
            self._reject_future_revision_files(aggregate_id, revision)
            try:
                payload = encode_schema_v1(root.to_snapshot())
            except (AttributeError, TypeError, ValueError) as error:
                raise ValidationError("aggregate snapshot cannot be encoded as schema-v1") from error
            try:
                publish_bytes_no_clobber(
                    self._root.staging,
                    destination,
                    payload,
                    staging_suffix=".json",
                )
            except FileExistsError as error:
                raise ValidationError("immutable aggregate revision destination is already occupied") from error
            except (OSError, PublicationEvidenceMismatch) as error:
                raise ValidationError("immutable aggregate revision publication failed") from error
        return True

    def _current_contiguous(self, aggregate_id: object) -> tuple[int | None, Any | None]:
        self._validate_aggregate_id(aggregate_id)
        current: Any | None = None
        revision = 1
        while True:
            path = self._revision_path(aggregate_id, revision)
            if not os.path.lexists(path):
                return (None if current is None else revision - 1, current)
            try:
                snapshot = decode_schema_v1(path.read_bytes(), self._snapshot_type)
                root = self._root_type.from_snapshot(snapshot)
            except (OSError, TypeError, ValueError) as error:
                # A later invalid revision is a recovery boundary, not a newer state.
                if current is not None:
                    return revision - 1, current
                raise ValidationError("first aggregate revision is not valid canonical data") from error
            if root.revision != revision:
                if current is not None:
                    return revision - 1, current
                raise ValidationError("first aggregate revision does not match its immutable filename")
            current = root
            revision += 1

    def _aggregate_id(self, root: object) -> object:
        if self._root_type is AuthorizationRecord:
            return root.record_id
        if self._root_type is NarrationJob:
            return root.job_id
        return root.episode_id

    def _validate_aggregate_id(self, aggregate_id: object) -> None:
        if type(aggregate_id) is not self._aggregate_id_type:
            raise ValidationError("filesystem repository received the wrong aggregate identity type")

    def _revision_path(self, aggregate_id: object, revision: int) -> Path:
        self._validate_aggregate_id(aggregate_id)
        return (
            self._root.aggregates
            / self._aggregate_kind
            / aggregate_id.value
            / "revisions"
            / f"{revision:020d}.json"
        )

    def _reject_future_revision_files(self, aggregate_id: object, revision: int) -> None:
        revisions = self._revision_path(aggregate_id, revision).parent
        if not revisions.exists():
            return
        try:
            entries = tuple(revisions.iterdir())
        except OSError as error:
            raise ValidationError("aggregate revision directory cannot be read") from error
        for entry in entries:
            name = entry.name
            if name.endswith(".json") and len(name) == 25 and name[:-5].isdigit() and int(name[:-5]) > revision:
                raise ValidationError("aggregate revision history has a gap or future revision")


class FilesystemAuthorizationRecordRepository:
    """Filesystem implementation of the authorization-record repository port."""

    def __init__(self, root: LocalNarrationRoot) -> None:
        self._snapshots = _FilesystemSnapshotRepository(
            root, "authorization-records", AuthorizationRecordId, AuthorizationRecordSnapshot, AuthorizationRecord
        )

    def load(self, record_id: AuthorizationRecordId) -> AuthorizationRecord | None:
        return self._snapshots.load(record_id)

    def save(self, record: AuthorizationRecord, expected_revision: int | None) -> bool:
        return self._snapshots.save(record, expected_revision)


class FilesystemNarrationJobRepository:
    """Filesystem implementation of the narration-job repository port."""

    def __init__(self, root: LocalNarrationRoot) -> None:
        self._snapshots = _FilesystemSnapshotRepository(
            root, "narration-jobs", NarrationJobId, NarrationJobSnapshot, NarrationJob
        )

    def load(self, job_id: NarrationJobId) -> NarrationJob | None:
        return self._snapshots.load(job_id)

    def save(self, job: NarrationJob, expected_revision: int | None) -> bool:
        return self._snapshots.save(job, expected_revision)


class FilesystemDiaryEpisodeRepository:
    """Filesystem implementation of the diary-episode repository port."""

    def __init__(self, root: LocalNarrationRoot) -> None:
        self._snapshots = _FilesystemSnapshotRepository(
            root, "diary-episodes", DiaryEpisodeId, DiaryEpisodeSnapshot, DiaryEpisode
        )

    def load(self, episode_id: DiaryEpisodeId) -> DiaryEpisode | None:
        return self._snapshots.load(episode_id)

    def save(self, episode: DiaryEpisode, expected_revision: int | None) -> bool:
        return self._snapshots.save(episode, expected_revision)
