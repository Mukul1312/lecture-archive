"""Portable repository paths for scripts run directly or imported as modules."""

from pathlib import Path


def repository_root(script_file: str | Path) -> Path:
    """Return the repository root containing the script's nearest scripts directory."""
    script = Path(script_file).resolve()
    for parent in script.parents:
        if parent.name == "scripts":
            return parent.parent
    raise ValueError(f"script is not located below a scripts directory: {script}")


def data_root(script_file: str | Path) -> Path:
    """Return the repository's data directory for a script location."""
    return repository_root(script_file) / "data"
