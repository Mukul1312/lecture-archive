"""Injectable HTTPS download and ffprobe source intake."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from .store import ArtifactValidationError, JobStore, JobValidationError, RepositoryHealthError, safe_source_slug


@dataclass(frozen=True)
class SourceDownload:
    resolved_url: str
    filename: str
    tool_versions: dict[str, str] = field(default_factory=dict)


class SourceAdapter(Protocol):
    def download(self, requested_url: str, staging_path: Path) -> SourceDownload: ...
    def probe(self, source_path: Path) -> dict[str, Any]: ...


class HttpsFfprobeSourceAdapter:
    """Production adapter; HTTP and process boundaries remain injectable."""

    def __init__(self, http_open: Callable[..., Any] = urlopen, run_command: Callable[..., Any] = subprocess.run) -> None:
        self._http_open, self._run = http_open, run_command

    def download(self, requested_url: str, staging_path: Path) -> SourceDownload:
        request = Request(requested_url, headers={"User-Agent": "ggsm-transcription/1"})
        with self._http_open(request) as response, staging_path.open("wb") as target:
            shutil.copyfileobj(response, target)
            resolved = response.geturl()
            filename = Path(urlsplit(resolved).path).name or "source.bin"
        return SourceDownload(resolved, filename, {"downloader": "urllib.request"})

    def probe(self, source_path: Path) -> dict[str, Any]:
        probe = self._run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source_path)],
            capture_output=True, text=True, check=True,
        )
        version = self._run(["ffprobe", "-version"], capture_output=True, text=True, check=True)
        try:
            payload = json.loads(probe.stdout)
            streams = payload["streams"]
            audio = next(stream for stream in streams if stream.get("codec_type") == "audio" and stream.get("codec_name"))
            duration = float(payload.get("format", {}).get("duration", audio.get("duration")))
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
            raise JobValidationError("ffprobe returned incomplete source metadata") from error
        return {
            "duration_seconds": duration,
            "codec": audio["codec_name"],
            "streams": streams,
            "tool_versions": {"ffprobe": version.stdout.splitlines()[0].strip()},
        }


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def validate_https_url(url: str) -> str:
    JobStore._validate_https_url(url)
    return url


class IntakeService:
    def __init__(self, store: JobStore, source_adapter: SourceAdapter) -> None:
        self.store, self.source_adapter = store, source_adapter

    def _validated_hash_identity(self, digest: str) -> list[dict[str, Any]]:
        candidates = self.store.find_hash_candidates(digest)
        valid: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate["stage"] != "created":
                self.store.validate_source(candidate["job_id"])
            valid.append(candidate)
        if len(valid) > 1:
            raise JobValidationError("more than one valid job matches the source hash")
        return valid

    def intake(self, requested_url: str) -> dict[str, Any]:
        requested_url = validate_https_url(requested_url)
        with self.store.identity_lock():
            url_matches = self.store.find_url_candidates(requested_url)
            if url_matches:
                if len(url_matches) != 1:
                    raise JobValidationError("more than one valid job matches this source URL")
                candidate = url_matches[0]
                if candidate["stage"] == "created":
                    raise RepositoryHealthError("created job cannot be selected by URL provenance")
                self.store.validate_source(candidate["job_id"])
                if len(self._validated_hash_identity(candidate["source_sha256"])) != 1:
                    raise JobValidationError("source URL maps to an ambiguous source hash")
                return candidate

            staging = self.store.incoming_root / f"download-{uuid4().hex}.part"
            try:
                download = self.source_adapter.download(requested_url, staging)
                resolved = validate_https_url(download.resolved_url)
                if not staging.is_file() or staging.is_symlink():
                    raise ArtifactValidationError("downloader did not create a regular staging source")
                digest, size = _sha256_and_size(staging)
                matches = self._validated_hash_identity(digest)
                if matches and matches[0]["source"] is not None:
                    job_id = matches[0]["job_id"]
                    self.store.validate_source(job_id)
                    with self.store.transaction(job_id) as transaction:
                        transaction.record_source_alias(requested_url, resolved)
                    return self.store.load_job(job_id)
                probe = self.source_adapter.probe(staging)
                try:
                    source = {
                        "requested_url": requested_url, "resolved_url": resolved, "sha256": digest,
                        "byte_size": size, "duration_seconds": probe["duration_seconds"],
                        "codec": probe["codec"], "streams": probe["streams"],
                    }
                    versions = {**download.tool_versions, **probe["tool_versions"]}
                except (KeyError, TypeError) as error:
                    raise JobValidationError("source adapter returned incomplete metadata") from error
                self.store._validate_source_metadata(source, versions)
                if matches:
                    job_id = matches[0]["job_id"]
                else:
                    slug = safe_source_slug(Path(download.filename).stem or urlsplit(resolved).path.rsplit("/", 1)[-1])
                    job_id = self.store.create_job(slug, digest)["job_id"]
                with self.store.transaction(job_id) as transaction:
                    transaction.complete_source_intake(staging, source, versions)
                return self.store.load_job(job_id)
            finally:
                try:
                    staging.unlink()
                except FileNotFoundError:
                    pass
