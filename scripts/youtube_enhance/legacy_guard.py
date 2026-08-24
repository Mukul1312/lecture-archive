from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import stat
from typing import Any, Mapping


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


def _filesystem_path(path: Path | str) -> str:
    """Return an OS-I/O path without exposing Windows long-path syntax publicly."""
    value = os.fspath(path)
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    absolute = os.path.abspath(value)
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _lstat(path: Path | str) -> os.stat_result:
    return os.lstat(_filesystem_path(path))


def _ordinary_path(path: str) -> Path:
    if path.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + path[8:])
    if path.startswith("\\\\?\\"):
        return Path(path[4:])
    return Path(path)


def _is_reparse(status: os.stat_result) -> bool:
    return stat.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _require_real_directory(path: Path) -> None:
    status = _lstat(path)
    if _is_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise ValueError(f"expected a real non-reparse directory: {path}")


def inventory_tree(root: Path) -> dict[str, Any]:
    """Return a read-only, lexical-relative inventory of regular files below root."""
    root = Path(root)
    _require_real_directory(root)
    physical_root = root.resolve(strict=True)
    entries: list[dict[str, Any]] = []

    def visit(directory: Path) -> None:
        with os.scandir(_filesystem_path(directory)) as scanned:
            children = sorted(scanned, key=lambda entry: entry.name)
        for child in children:
            path = directory / child.name
            status = _lstat(path)
            if _is_reparse(status):
                raise ValueError(f"protected tree contains a reparse entry: {path}")
            if stat.S_ISDIR(status.st_mode):
                visit(path)
            elif stat.S_ISREG(status.st_mode):
                entries.append(
                    {
                        "path": path.relative_to(physical_root).as_posix(),
                        "kind": "file",
                        "size_bytes": status.st_size,
                        "mtime_ns": status.st_mtime_ns,
                    }
                )

    visit(physical_root)
    entries.sort(key=lambda entry: entry["path"])
    return {
        "schema_version": 1,
        "root": str(physical_root),
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entries": entries,
    }


def _require_regular_external_path(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"external artifact path must be absolute: {candidate}")
    lexical = Path(os.path.normpath(str(candidate)))
    if str(candidate) != str(lexical):
        raise ValueError(f"external artifact path must already be normalized: {candidate}")

    if len(candidate.parts) == 1:
        raise ValueError(f"external artifact must be a regular non-reparse file: {candidate}")

    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        status = _lstat(current)
        if _is_reparse(status):
            raise ValueError(f"external artifact path contains a reparse entry: {current}")

    if _is_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise ValueError(f"external artifact must be a regular non-reparse file: {candidate}")
    physical = _ordinary_path(os.path.realpath(_filesystem_path(candidate)))
    if str(candidate) != str(physical):
        raise ValueError(f"external artifact path must already be physical: {candidate}")
    return physical


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(_filesystem_path(path), "rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest().upper()


def hash_external_artifacts(expected_hashes: Mapping[Path, str]) -> dict[str, Any]:
    """Hash only explicitly supplied regular files; never discover adjacent paths."""
    artifacts: dict[str, Any] = {}
    for requested_path, expected in expected_hashes.items():
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or expected != expected.upper()
            or any(character not in "0123456789ABCDEF" for character in expected)
        ):
            raise ValueError("expected SHA-256 must be an uppercase hexadecimal digest")
        path = _require_regular_external_path(Path(requested_path))
        actual = _sha256(path)
        artifacts[str(path)] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "matches": hmac.compare_digest(expected, actual),
        }
    return artifacts


def write_baseline(root: Path, destination: Path, expected_hashes: Mapping[Path, str]) -> None:
    """Write a snapshot outside a protected tree without modifying that tree."""
    inventory = inventory_tree(root)
    protected_root = Path(inventory["root"])
    output = Path(destination).resolve()
    if output.is_relative_to(protected_root):
        raise ValueError("baseline destination must be outside the protected tree")
    external_artifacts = hash_external_artifacts(expected_hashes)
    if not all(record["matches"] for record in external_artifacts.values()):
        raise ValueError("external artifact hash mismatch")
    baseline = {
        **inventory,
        "external_artifacts": external_artifacts,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
