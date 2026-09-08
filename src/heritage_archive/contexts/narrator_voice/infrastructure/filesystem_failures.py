"""Shared typed boundary for local operational evidence failures."""

from heritage_archive.kernel import ValidationError


class FilesystemOperationalFailure(ValidationError):
    """Operational filesystem/evidence failure, never caller validation."""
