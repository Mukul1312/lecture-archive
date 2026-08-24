from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping


class RenderNotApproved(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cache_key(
    stage: str,
    inputs: Mapping[str, str],
    params: Mapping[str, Any],
    versions: Mapping[str, str],
) -> str:
    payload = {"stage": stage, "inputs": inputs, "params": params, "versions": versions}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def processing_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Return the render-approval fingerprint, with legacy-schema support.

    Candidate evidence cannot hash a report which in turn hashes itself.  New
    manifests therefore use ``candidate_context_fingerprint`` before evidence
    publication and ``render_approval_fingerprint`` after a human selection.
    The original payload remains readable for manifests created by Tasks 1-8.
    """
    if "candidate_context" in manifest or "candidate_evidence" in manifest:
        return render_approval_fingerprint(manifest)
    payload = {
        "source": manifest["source"],
        "versions": manifest["versions"],
        "processing": manifest["processing"],
        "segment_map_sha256": manifest["segment_map_sha256"],
        "candidate_report_sha256": manifest["candidate_report_sha256"],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def candidate_context_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Fingerprint immutable inputs available before candidate publication."""
    processing = {
        key: value
        for key, value in manifest["processing"].items()
        if key not in {"attenuation_db", "pause_treatment"}
    }
    working = {
        name: {
            key: value
            for key, value in record.items()
            if key in {"sha256", "channels", "sample_rate", "frames"}
        }
        for name, record in manifest.get("working", {}).items()
    }
    payload = {
        "schema_version": manifest["schema_version"],
        "source": manifest["source"],
        "versions": manifest["versions"],
        "processing": processing,
        "working": working,
        "candidate_context": manifest["candidate_context"],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def render_approval_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Bind candidate bytes, finalized segments, and the reviewed selection."""
    payload = {
        "candidate_context_fingerprint": candidate_context_fingerprint(manifest),
        "candidate_evidence": manifest["candidate_evidence"],
        "segment_map_sha256": manifest["segment_map_sha256"],
        "processing": manifest["processing"],
        "selection": manifest["selection"],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def require_current_approval(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    approval = manifest.get("approval")
    if not approval:
        raise RenderNotApproved("Full render requires explicit candidate and segment-map approval")
    if "candidate_context" in manifest:
        recorded_context = manifest.get("candidate_context_fingerprint")
        if recorded_context != candidate_context_fingerprint(manifest):
            raise RenderNotApproved("Candidate context is stale because an input changed")
        evidence = manifest.get("candidate_evidence")
        if not isinstance(evidence, Mapping):
            raise RenderNotApproved("Candidate evidence is missing")
        if manifest.get("candidate_report_sha256") != evidence.get("public_report_sha256"):
            raise RenderNotApproved("Candidate report physical hash is stale")
    expected = processing_fingerprint(manifest)
    if approval.get("fingerprint") != expected:
        raise RenderNotApproved("Approval is stale because a fingerprinted input changed")
    return approval


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    parent_before = os.lstat(path.parent)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not stat.S_ISDIR(parent_before.st_mode)
        or stat.S_ISLNK(parent_before.st_mode)
        or bool(getattr(parent_before, "st_file_attributes", 0) & reparse_flag)
    ):
        raise RuntimeError("manifest parent must be a real non-reparse directory")
    if os.path.lexists(path):
        destination = os.lstat(path)
        if (
            not stat.S_ISREG(destination.st_mode)
            or stat.S_ISLNK(destination.st_mode)
            or bool(getattr(destination, "st_file_attributes", 0) & reparse_flag)
        ):
            raise RuntimeError("manifest destination must be a regular non-reparse file")

    payload = (canonical_json(value) + "\n").encode("utf-8")
    temporary_stat = None
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        temporary_stat = os.fstat(descriptor)
        if not stat.S_ISREG(temporary_stat.st_mode):
            raise RuntimeError("manifest private stage must be a regular file")
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        named = os.lstat(temporary)
        parent_after = os.lstat(path.parent)
        if (
            not os.path.samestat(temporary_stat, named)
            or not os.path.samestat(parent_before, parent_after)
            or stat.S_ISLNK(named.st_mode)
            or bool(getattr(named, "st_file_attributes", 0) & reparse_flag)
        ):
            raise RuntimeError("manifest publication path changed during commit")
        if os.path.lexists(path):
            destination = os.lstat(path)
            if (
                not stat.S_ISREG(destination.st_mode)
                or stat.S_ISLNK(destination.st_mode)
                or bool(getattr(destination, "st_file_attributes", 0) & reparse_flag)
            ):
                raise RuntimeError("manifest destination changed during commit")
        os.replace(temporary, path)
        temporary_stat = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_stat is not None:
            try:
                named = os.lstat(temporary)
                if os.path.samestat(temporary_stat, named):
                    os.unlink(temporary)
            except FileNotFoundError:
                pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
