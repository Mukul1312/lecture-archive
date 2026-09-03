"""Validation and layout of the explicit local Narrator Voice storage root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat


_LAYOUT_NAMES = ("aggregates", "staging", "artifacts", "attempts", "operations")


@dataclass(frozen=True, slots=True)
class LocalNarrationRoot:
    """An existing external directory dedicated to Narrator Voice durable state."""

    path: Path

    @classmethod
    def open(cls, path: str | Path, forbidden_roots: tuple[Path, ...]) -> LocalNarrationRoot:
        """Validate an explicit existing local root without creating it."""
        candidate = Path(path)
        if not candidate.is_absolute():
            raise ValueError("local narration root must be an explicit absolute path")
        if _contains_reparse_point(candidate):
            raise ValueError("local narration root cannot be a reparse point or use one")
        if not candidate.exists():
            raise ValueError("local narration root must already exist")
        if not candidate.is_dir():
            raise ValueError("local narration root must be a directory")
        resolved = candidate.resolve(strict=True)
        if resolved == Path(resolved.anchor):
            raise ValueError("local narration root cannot be a filesystem root")
        for forbidden_root in forbidden_roots:
            forbidden = Path(forbidden_root).resolve(strict=False)
            if resolved == forbidden or resolved.is_relative_to(forbidden):
                raise ValueError("local narration root cannot be inside a repository or worktree")
        return cls(path=resolved)

    @property
    def aggregates(self) -> Path:
        return self.path / "aggregates"

    @property
    def staging(self) -> Path:
        return self.path / "staging"

    @property
    def artifacts(self) -> Path:
        return self.path / "artifacts"

    @property
    def attempts(self) -> Path:
        return self.path / "attempts"

    @property
    def operations(self) -> Path:
        return self.path / "operations"

    @property
    def writer_lock(self) -> Path:
        return self.path / ".writer.lock"

    @property
    def layout_directories(self) -> tuple[Path, ...]:
        return tuple(self.path / name for name in _LAYOUT_NAMES)

    def initialize_layout(self) -> None:
        """Create only the approved storage directories below the validated root."""
        for directory in self.layout_directories:
            directory.mkdir(exist_ok=True)


def _contains_reparse_point(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if _is_reparse_point(current):
            return True
    return False


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
