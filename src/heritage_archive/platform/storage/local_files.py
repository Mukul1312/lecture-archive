"""Small, explicit local-file publication primitives."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import BinaryIO
import uuid


class WriterLockUnavailable(RuntimeError):
    """The application-wide local writer lock is already held."""


class PublicationEvidenceMismatch(RuntimeError):
    """Staged bytes do not prove the evidence derived from the supplied payload."""


@dataclass(frozen=True, slots=True)
class PublishedFile:
    """Digest evidence for bytes whose publication completed."""

    sha256_hex: str
    byte_length: int


class SingleWriterFileLock:
    """A non-blocking one-byte advisory lock for all local mutations."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._handle: BinaryIO | None = None

    def __enter__(self) -> SingleWriterFileLock:
        if self._handle is not None:
            raise RuntimeError("writer lock is already held by this instance")
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path.open("a+b")
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.seek(0)
                handle.write(b"\x00")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            _lock_one_byte_nonblocking(handle)
        except OSError as error:
            handle.close()
            raise WriterLockUnavailable("the local narration writer lock is already held") from error
        self._handle = handle
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            _unlock_one_byte(handle)
        finally:
            handle.close()


def publish_bytes_no_clobber(
    staging_directory: Path, destination: Path, payload: bytes
) -> PublishedFile:
    """Publish immutable bytes after staging and reread evidence verification."""
    stage, published = _stage_and_verify(staging_directory, payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(destination):
        raise FileExistsError(f"immutable destination already exists: {destination}")
    stage.rename(destination)
    return published


def replace_bytes_atomically(
    staging_directory: Path, destination: Path, payload: bytes
) -> PublishedFile:
    """Replace an explicitly mutable operational file after evidence verification."""
    stage, published = _stage_and_verify(staging_directory, payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage, destination)
    return published


def _stage_and_verify(staging_directory: Path, payload: bytes) -> tuple[Path, PublishedFile]:
    if type(payload) is not bytes:
        raise TypeError("published payload must be bytes")
    staging_directory.mkdir(parents=True, exist_ok=True)
    stage = staging_directory / f"{uuid.uuid4().hex}.stage"
    with stage.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    published = _published_evidence(stage.read_bytes())
    expected = _published_evidence(payload)
    if published != expected:
        raise PublicationEvidenceMismatch("staged file evidence differs from supplied payload")
    return stage, published


def _published_evidence(payload: bytes) -> PublishedFile:
    return PublishedFile(
        sha256_hex=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
    )


def _lock_one_byte_nonblocking(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0, 0)


def _unlock_one_byte(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.lockf(handle.fileno(), fcntl.LOCK_UN, 1, 0, 0)
