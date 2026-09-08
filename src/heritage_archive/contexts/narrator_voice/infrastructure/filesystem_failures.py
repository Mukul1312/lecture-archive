"""Shared typed boundaries for local operational evidence failures."""

from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from heritage_archive.kernel import ValidationError


class FilesystemOperationalFailure(ValidationError):
    """Operational filesystem/evidence failure, never caller validation."""


class FilesystemWriterLockBoundary:
    """Translate lock I/O without letting exit failure mask a body failure."""

    def __init__(
        self,
        lock_factory: Callable[[Path], Any],
        path: Path,
        failure_message: str,
    ) -> None:
        self._lock_factory = lock_factory
        self._path = path
        self._failure_message = failure_message
        self._lock: Any | None = None

    def __enter__(self) -> Any:
        try:
            self._lock = self._lock_factory(self._path)
            return self._lock.__enter__()
        except OSError as error:
            raise FilesystemOperationalFailure(self._failure_message) from error

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._lock is None:
            return None
        try:
            return self._lock.__exit__(exception_type, exception, traceback)
        except OSError as error:
            if exception is not None:
                # Let the context protocol re-raise the original body failure.
                return False
            raise FilesystemOperationalFailure(self._failure_message) from error
