"""Injectable local-source intake use case for transcription jobs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from typing import Any, Protocol

from .store import ArtifactValidationError, JobStore, JobValidationError, safe_source_slug


@dataclass(frozen=True)
class SourceDownload:
    """The final URL and filename returned by a source downloader."""

    resolved_url: str
    filename: str


class SourceAdapter(Protocol):
    def download(self, requested_url: str, staging_path: Path) -> SourceDownload: ...

    def probe(self, source_path: Path) -> dict[str, Any]: ...


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def validate_https_url(url: str) -> str:
    if not isinstance(url, str):
        raise JobValidationError("source URL must be an HTTPS URL")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise JobValidationError("source URL must be an HTTPS URL")
    return url


class IntakeService:
    """Coordinates URL/hash matching without coupling job policy to HTTP or ffprobe."""

    def __init__(self, store: JobStore, source_adapter: SourceAdapter) -> None:
        self.store = store
        self.source_adapter = source_adapter

    def intake(self, requested_url: str) -> dict[str, Any]:
        requested_url = validate_https_url(requested_url)
        url_candidates = self.store.find_url_candidates(requested_url)
        if url_candidates:
            valid: list[dict[str, Any]] = []
            invalid: list[str] = []
            for candidate in url_candidates:
                try:
                    self.store.validate_source(candidate["job_id"])
                except ArtifactValidationError:
                    invalid.append(candidate["job_id"])
                else:
                    valid.append(candidate)
            if invalid:
                raise ArtifactValidationError(
                    "matching source job cannot resume because its source evidence is invalid: " + ", ".join(invalid)
                )
            if len(valid) != 1:
                raise JobValidationError("more than one valid job matches this source URL")
            return valid[0]

        staging_path = self.store.incoming_root / f"download-{uuid4().hex}.part"
        try:
            download = self.source_adapter.download(requested_url, staging_path)
            resolved_url = validate_https_url(download.resolved_url)
            if not staging_path.is_file() or staging_path.is_symlink():
                raise ArtifactValidationError("downloader did not create a regular staging source")
            source_sha256, byte_size = _sha256_and_size(staging_path)
            hash_candidates = self.store.find_hash_candidates(source_sha256)
            matching_jobs = []
            invalid_hash_candidates = []
            for candidate in hash_candidates:
                try:
                    self.store.validate_source(candidate["job_id"])
                except ArtifactValidationError:
                    invalid_hash_candidates.append(candidate["job_id"])
                else:
                    matching_jobs.append(candidate)
            if invalid_hash_candidates:
                raise ArtifactValidationError(
                    "matching source hash cannot create a duplicate while existing evidence is invalid: "
                    + ", ".join(invalid_hash_candidates)
                )
            if len(matching_jobs) > 1:
                raise JobValidationError("more than one valid job matches the downloaded source hash")
            if matching_jobs:
                return matching_jobs[0]
            probe = self.source_adapter.probe(staging_path)
            try:
                duration_seconds = probe["duration_seconds"]
                codec = probe["codec"]
                streams = probe["streams"]
                tool_versions = probe["tool_versions"]
            except KeyError as error:
                raise JobValidationError(f"source probe metadata is missing {error.args[0]!r}") from error
            if not isinstance(duration_seconds, (int, float)) or duration_seconds < 0:
                raise JobValidationError("source probe duration must be a non-negative number")
            if not isinstance(codec, str) or not codec or not isinstance(streams, list) or not isinstance(tool_versions, dict):
                raise JobValidationError("source probe returned invalid metadata")
            source_slug = safe_source_slug(Path(download.filename).stem or urlsplit(resolved_url).path.rsplit("/", 1)[-1])
            job = self.store.create_job(source_slug, source_sha256)
            job_id = job["job_id"]
            source_path = self.store.job_root(job_id) / "source" / "source.bin"
            staging_path.replace(source_path)
            source_metadata = {
                "requested_url": requested_url,
                "resolved_url": resolved_url,
                "sha256": source_sha256,
                "byte_size": byte_size,
                "duration_seconds": duration_seconds,
                "codec": codec,
                "streams": streams,
            }
            self.store.update_job(
                job_id,
                lambda state: state.update({"source": source_metadata, "tool_versions": dict(tool_versions)}),
            )
            self.store.register_artifact(job_id, "source/source.bin")
            return self.store.advance_stage(job_id, "source_ready")
        finally:
            try:
                staging_path.unlink()
            except FileNotFoundError:
                pass
