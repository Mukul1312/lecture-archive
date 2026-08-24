"""Durable, hash-bound storage for local transcription jobs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
from typing import Any, Callable, Iterator


class JobValidationError(ValueError):
    """Raised when a job ID, path, source, or manifest violates the contract."""


class StageTransitionError(JobValidationError):
    """Raised when a job is advanced outside the declared workflow."""


class ArtifactValidationError(JobValidationError):
    """Raised when registered evidence is missing, unsafe, or no longer unchanged."""


class JobLockError(JobValidationError):
    """Raised when another process currently owns a job's exclusive lock."""


_JOB_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?-[0-9a-f]{8}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DEVICES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_NEXT_STAGE = {
    "created": "source_ready",
    "source_ready": "asr_ready",
    "asr_ready": "inspected",
    "inspected": "reviewed",
    "reviewed": "draft_ready",
    "draft_ready": "handed_off",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_source_slug(value: str) -> str:
    """Create a filesystem-safe, deterministic slug without device-name aliases."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = slug[:80].rstrip("-")
    if not slug or slug in _WINDOWS_DEVICES:
        raise JobValidationError("source slug must be a non-device filesystem name")
    return slug


def make_job_id(source_slug: str, source_sha256: str) -> str:
    """Return the deterministic ID used as the name of a job directory."""
    digest = source_sha256.lower()
    if not _SHA256.fullmatch(digest):
        raise JobValidationError("source SHA-256 must be 64 lowercase hexadecimal characters")
    return f"{safe_source_slug(source_slug)}-{digest[:8]}"


def validate_job_id(job_id: str) -> str:
    """Reject traversal, device aliases, and malformed deterministic IDs."""
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise JobValidationError("invalid job ID")
    slug, _separator, _short_hash = job_id.rpartition("-")
    if slug in _WINDOWS_DEVICES or any(part in _WINDOWS_DEVICES for part in slug.split("-")):
        raise JobValidationError("job ID uses a reserved Windows device name")
    if PureWindowsPath(job_id).is_absolute() or PureWindowsPath(job_id).drive:
        raise JobValidationError("job ID must be a relative path")
    return job_id


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class JobStore:
    """Owns manifests, evidence registration, and exclusive job-local locks."""

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root)
        self.jobs_root = self.data_root / "jobs"
        self.incoming_root = self.data_root / ".incoming"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.incoming_root.mkdir(parents=True, exist_ok=True)

    def job_root(self, job_id: str) -> Path:
        validated = validate_job_id(job_id)
        root = self.jobs_root / validated
        if root.parent.resolve() != self.jobs_root.resolve():
            raise JobValidationError("job root escapes jobs directory")
        return root

    def create_job(self, source_slug: str, source_sha256: str) -> dict[str, Any]:
        job_id = make_job_id(source_slug, source_sha256)
        root = self.job_root(job_id)
        if root.exists():
            raise JobValidationError(f"job already exists: {job_id}")
        root.mkdir(parents=True)
        for relative in ("source", "asr/reruns", "inspection", "review", "reference", "delivery"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        now = _utcnow()
        state: dict[str, Any] = {
            "schema_version": 1,
            "revision": 0,
            "job_id": job_id,
            "stage": "created",
            "created_at": now,
            "updated_at": now,
            "stage_history": [{"stage": "created", "at": now}],
            "source": None,
            "tool_versions": {},
            "artifacts": {},
        }
        self._write_manifest(root, state)
        return state

    def load_job(self, job_id: str) -> dict[str, Any]:
        root = self.job_root(job_id)
        manifest_path = root / "job.json"
        if not manifest_path.is_file():
            raise JobValidationError(f"job manifest is missing: {job_id}")
        try:
            state = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise JobValidationError(f"job manifest is unreadable: {job_id}") from error
        if state.get("job_id") != job_id:
            raise JobValidationError("job manifest ID does not match its directory")
        return state

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for candidate in self.jobs_root.iterdir():
            if candidate.is_dir() and not candidate.is_symlink():
                try:
                    jobs.append(self.load_job(candidate.name))
                except JobValidationError:
                    continue
        return jobs

    @contextmanager
    def lock_job(self, job_id: str) -> Iterator[None]:
        root = self.job_root(job_id)
        if not root.is_dir():
            raise JobValidationError(f"job does not exist: {job_id}")
        lock_path = root / ".lock"
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise JobLockError(f"job is locked: {job_id}") from error
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(descriptor)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def update_job(
        self, job_id: str, mutate: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        with self.lock_job(job_id):
            state = self.load_job(job_id)
            previous_revision = state.get("revision")
            if not isinstance(previous_revision, int) or previous_revision < 0:
                raise JobValidationError("manifest revision must be a non-negative integer")
            mutate(state)
            state["revision"] = previous_revision + 1
            state["updated_at"] = _utcnow()
            self._write_manifest(self.job_root(job_id), state)
            return state

    def advance_stage(self, job_id: str, target_stage: str) -> dict[str, Any]:
        def advance(state: dict[str, Any]) -> None:
            current = state.get("stage")
            if _NEXT_STAGE.get(current) != target_stage:
                raise StageTransitionError(f"cannot advance {current!r} to {target_stage!r}")
            state["stage"] = target_stage
            state["stage_history"].append({"stage": target_stage, "at": _utcnow()})

        return self.update_job(job_id, advance)

    def register_artifact(self, job_id: str, relative_path: str) -> dict[str, Any]:
        root = self.job_root(job_id)
        relative = self._safe_relative_path(relative_path)
        target = root.joinpath(*relative.parts)
        self._assert_safe_artifact_path(root, target)
        if not target.is_file():
            raise ArtifactValidationError(f"artifact is not a regular file: {relative.as_posix()}")
        digest, size = _sha256_and_size(target)

        def register(state: dict[str, Any]) -> None:
            state.setdefault("artifacts", {})[relative.as_posix()] = {
                "sha256": digest,
                "byte_size": size,
            }

        return self.update_job(job_id, register)

    def validate_artifact(self, job_id: str, relative_path: str) -> Path:
        state = self.load_job(job_id)
        root = self.job_root(job_id)
        relative = self._safe_relative_path(relative_path)
        recorded = state.get("artifacts", {}).get(relative.as_posix())
        if not isinstance(recorded, dict):
            raise ArtifactValidationError(f"artifact is not registered: {relative.as_posix()}")
        target = root.joinpath(*relative.parts)
        self._assert_safe_artifact_path(root, target)
        if not target.is_file():
            raise ArtifactValidationError(f"artifact is missing: {relative.as_posix()}")
        digest, size = _sha256_and_size(target)
        if digest != recorded.get("sha256") or size != recorded.get("byte_size"):
            raise ArtifactValidationError(f"artifact no longer matches recorded hash/size: {relative.as_posix()}")
        return target

    def validate_source(self, job_id: str) -> Path:
        state = self.load_job(job_id)
        source = state.get("source")
        if not isinstance(source, dict):
            raise ArtifactValidationError("job has no bound source metadata")
        path = self.validate_artifact(job_id, "source/source.bin")
        digest, size = _sha256_and_size(path)
        if digest != source.get("sha256") or size != source.get("byte_size"):
            raise ArtifactValidationError("source metadata does not match its artifact")
        return path

    def find_url_candidates(self, url: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for state in self.list_jobs():
            source = state.get("source")
            if isinstance(source, dict) and url in (source.get("requested_url"), source.get("resolved_url")):
                candidates.append(state)
        return candidates

    def find_valid_hash_matches(self, source_sha256: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for state in self.find_hash_candidates(source_sha256):
            try:
                self.validate_source(state["job_id"])
            except ArtifactValidationError:
                continue
            matches.append(state)
        return matches

    def find_hash_candidates(self, source_sha256: str) -> list[dict[str, Any]]:
        """Return every manifest claiming a source digest, valid or otherwise."""
        return [
            state
            for state in self.list_jobs()
            if isinstance(state.get("source"), dict) and state["source"].get("sha256") == source_sha256
        ]

    @staticmethod
    def _safe_relative_path(value: str) -> PurePosixPath:
        if not isinstance(value, str) or not value:
            raise JobValidationError("artifact path must be a non-empty relative path")
        windows = PureWindowsPath(value)
        posix = PurePosixPath(value.replace("\\", "/"))
        if windows.is_absolute() or windows.drive or posix.is_absolute():
            raise JobValidationError("artifact path must be relative")
        if any(part in ("", ".", "..") or part.lower().split(".", 1)[0] in _WINDOWS_DEVICES for part in posix.parts):
            raise JobValidationError("artifact path contains an unsafe component")
        return posix

    @staticmethod
    def _assert_safe_artifact_path(root: Path, target: Path) -> None:
        reparse = getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        try:
            relative_parts = target.relative_to(root).parts
        except ValueError as error:
            raise ArtifactValidationError("artifact resolves outside its job root") from error
        current = root
        for part in relative_parts:
            current = current / part
            try:
                attributes = current.lstat().st_file_attributes
            except FileNotFoundError:
                attributes = 0
            if current.is_symlink() or attributes & reparse:
                raise ArtifactValidationError("symlink/reparse artifacts are not allowed")
        try:
            target.resolve(strict=False).relative_to(root.resolve())
        except ValueError as error:
            raise ArtifactValidationError("artifact resolves outside its job root") from error

    @staticmethod
    def _write_manifest(root: Path, state: dict[str, Any]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".job.json.", suffix=".tmp", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, root / "job.json")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
