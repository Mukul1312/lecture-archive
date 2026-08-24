"""Durable, hash-bound storage for local transcription jobs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import tempfile
import threading
from typing import Any, Iterator


class JobValidationError(ValueError):
    """A job value, manifest, or mutation violates the aggregate contract."""


class RepositoryHealthError(JobValidationError):
    """Repository state cannot safely establish an identity decision."""


class StageTransitionError(JobValidationError):
    """A requested stage is not the aggregate's one legal next stage."""


class ArtifactValidationError(JobValidationError):
    """Registered evidence is unsafe, absent, changed, or corrupted."""


class JobLockError(JobValidationError):
    """An OS-managed lock is held by another live owner."""


_JOB_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?-[0-9a-f]{8}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_NEXT_STAGE = {
    "created": "source_ready", "source_ready": "asr_ready", "asr_ready": "inspected",
    "inspected": "reviewed", "reviewed": "draft_ready", "draft_ready": "handed_off",
}
_LAYOUT = ("source", "asr/reruns", "inspection", "review", "reference", "delivery")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_reparse(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (FileNotFoundError, AttributeError):
        attributes = 0
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def safe_source_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80].rstrip("-")
    if not slug or slug in _WINDOWS_DEVICES:
        raise JobValidationError("source slug must be a non-device filesystem name")
    return slug


def make_job_id(source_slug: str, source_sha256: str) -> str:
    digest = source_sha256.lower()
    if not _is_sha256(digest):
        raise JobValidationError("source SHA-256 must be 64 lowercase hexadecimal characters")
    return validate_job_id(f"{safe_source_slug(source_slug)}-{digest[:8]}")


def validate_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise JobValidationError("invalid job ID")
    slug = job_id.rpartition("-")[0]
    if slug in _WINDOWS_DEVICES or PureWindowsPath(job_id).is_absolute() or PureWindowsPath(job_id).drive:
        raise JobValidationError("job ID uses an unsafe filesystem name")
    return job_id


class _OSFileLock:
    """A non-blocking advisory lock released automatically with its process handle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.handle.write(b"0")
                    self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            self.handle = None
            raise JobLockError(f"lock is held: {self.path.name}") from error

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class JobTransaction:
    """The only mutation session: one job lock, typed changes, one revision."""

    def __init__(self, store: "JobStore", job_id: str) -> None:
        self.store, self.job_id = store, job_id
        self._state = store.load_job(job_id)
        self._dirty = False

    @property
    def state(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state, allow_nan=False))

    def register_artifact(self, relative_path: str) -> None:
        root = self.store.job_root(self.job_id)
        relative = self.store._safe_relative_path(relative_path)
        target = root.joinpath(*relative.parts)
        self.store._assert_safe_artifact_path(root, target)
        if not target.is_file():
            raise ArtifactValidationError(f"artifact is not a regular file: {relative.as_posix()}")
        digest, size = _hash_file(target)
        record = {"sha256": digest, "byte_size": size}
        existing = self._state["artifacts"].get(relative.as_posix())
        if existing is not None:
            if existing != record:
                raise ArtifactValidationError("registered artifact changed and cannot be re-registered")
            return
        self._state["artifacts"][relative.as_posix()] = record
        self._dirty = True

    def advance_stage(self, target_stage: str) -> None:
        current = self._state["stage"]
        if current == "created" and target_stage == "source_ready":
            raise StageTransitionError("source_ready is entered only by source intake completion")
        if _NEXT_STAGE.get(current) != target_stage:
            raise StageTransitionError(f"cannot advance {current!r} to {target_stage!r}")
        self._state["stage"] = target_stage
        self._state["stage_history"].append({"stage": target_stage, "at": _utcnow()})
        self._dirty = True

    def record_source_alias(self, requested_url: str, resolved_url: str) -> None:
        self.store._validate_https_url(requested_url)
        self.store._validate_https_url(resolved_url)
        if self._state["source"] is None:
            raise JobValidationError("source aliases require a bound source")
        alias = {"requested_url": requested_url, "resolved_url": resolved_url}
        if alias not in self._state["source_url_aliases"]:
            self._state["source_url_aliases"].append(alias)
            self._dirty = True

    def complete_source_intake(self, staging_path: Path, source: dict[str, Any], tool_versions: dict[str, str]) -> None:
        self.store._validate_source_metadata(source, tool_versions)
        digest, size = source["sha256"], source["byte_size"]
        if digest != self._state["source_sha256"]:
            raise ArtifactValidationError("incoming source hash does not match this deterministic job")
        root = self.store.job_root(self.job_id)
        target = root / "source" / "source.bin"
        if target.exists():
            self.store._assert_safe_artifact_path(root, target)
            if _hash_file(target) != (digest, size):
                raise ArtifactValidationError("existing source evidence is corrupt")
        else:
            self.store._assert_safe_artifact_path(root, target)
            if not staging_path.is_file() or _is_reparse(staging_path) or _hash_file(staging_path) != (digest, size):
                raise ArtifactValidationError("staging source is unsafe or changed before installation")
            staging_path.replace(target)
        if self._state["source"] is not None:
            immutable_fields = ("sha256", "byte_size", "duration_seconds", "codec", "streams")
            if any(self._state["source"].get(key) != source.get(key) for key in immutable_fields):
                raise ArtifactValidationError("bound source metadata is immutable")
        if self._state["source"] is None:
            self._state["source"] = dict(source)
            self._state["tool_versions"] = dict(tool_versions)
            self._dirty = True
        self.register_artifact("source/source.bin")
        self.record_source_alias(source["requested_url"], source["resolved_url"])
        if self._state["stage"] == "created":
            self._state["stage"] = "source_ready"
            self._state["stage_history"].append({"stage": "source_ready", "at": _utcnow()})
            self._dirty = True
        elif self._state["stage"] != "source_ready":
            raise StageTransitionError("source intake cannot modify a job beyond source_ready")

    def commit(self) -> dict[str, Any]:
        if not self._dirty:
            return self._state
        candidate = json.loads(json.dumps(self._state, allow_nan=False))
        candidate["revision"] += 1
        candidate["updated_at"] = _utcnow()
        self.store._validate_manifest(candidate, self.job_id)
        self.store._write_manifest(self.store.job_root(self.job_id), candidate)
        self._state = candidate
        self._dirty = False
        return candidate


class JobStore:
    """Owns aggregate manifests, trusted paths, OS locks, and strict identity scans."""

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root)
        self.jobs_root, self.incoming_root = self.data_root / "jobs", self.data_root / ".incoming"
        self.creation_root = self.data_root / ".creating"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._assert_safe_directory(self.data_root, "data root")
        self.jobs_root.mkdir(exist_ok=True)
        self.incoming_root.mkdir(exist_ok=True)
        self.creation_root.mkdir(exist_ok=True)
        self._assert_safe_directory(self.jobs_root, "jobs root")
        self._assert_safe_directory(self.incoming_root, "incoming root")
        self._assert_safe_directory(self.creation_root, "creation root")
        self._held_locks: set[str] = set()
        self._held_guard = threading.Lock()

    def job_root(self, job_id: str) -> Path:
        job_id = validate_job_id(job_id)
        self._assert_safe_directory(self.data_root, "data root")
        self._assert_safe_directory(self.jobs_root, "jobs root")
        root = self.jobs_root / job_id
        if root.exists():
            self._assert_safe_directory(root, "job root")
        try:
            root.resolve(strict=False).relative_to(self.jobs_root.resolve())
        except ValueError as error:
            raise RepositoryHealthError("job root escapes the jobs directory") from error
        return root

    def create_job(self, source_slug: str, source_sha256: str) -> dict[str, Any]:
        job_id = make_job_id(source_slug, source_sha256)
        root = self.job_root(job_id)
        if root.exists():
            if root.is_dir():
                try:
                    self.load_job(job_id)
                except JobValidationError as health_error:
                    raise RepositoryHealthError(f"existing job directory is corrupt: {job_id}") from health_error
            raise JobValidationError(f"job already exists: {job_id}")
        temporary = Path(tempfile.mkdtemp(prefix=f"{job_id}-", dir=self.creation_root))
        now = _utcnow()
        state: dict[str, Any] = {
            "schema_version": 1, "revision": 0, "job_id": job_id, "source_sha256": source_sha256,
            "stage": "created", "created_at": now, "updated_at": now,
            "stage_history": [{"stage": "created", "at": now}], "source": None,
            "source_url_aliases": [], "tool_versions": {}, "artifacts": {},
        }
        try:
            for relative in _LAYOUT:
                (temporary / relative).mkdir(parents=True, exist_ok=True)
            self._validate_manifest(state, job_id)
            self._write_manifest(temporary, state)
            os.replace(temporary, root)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return state

    def load_job(self, job_id: str) -> dict[str, Any]:
        root = self.job_root(job_id)
        manifest = root / "job.json"
        self._assert_safe_artifact_path(root, manifest)
        if not manifest.is_file():
            raise RepositoryHealthError(f"job manifest is missing: {job_id}")
        try:
            state = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RepositoryHealthError(f"job manifest is unreadable: {job_id}") from error
        self._validate_manifest(state, job_id)
        return state

    def list_jobs(self) -> list[dict[str, Any]]:
        self._assert_safe_directory(self.jobs_root, "jobs root")
        jobs: list[dict[str, Any]] = []
        for candidate in self.jobs_root.iterdir():
            if candidate.name == ".identity.lock" and candidate.is_file() and not _is_reparse(candidate):
                continue
            if not candidate.is_dir() or _is_reparse(candidate):
                raise RepositoryHealthError(f"unsafe or non-directory job entry: {candidate.name}")
            jobs.append(self.load_job(candidate.name))
        return jobs

    @contextmanager
    def _lock(self, name: str, path: Path) -> Iterator[None]:
        with self._held_guard:
            if name in self._held_locks:
                raise JobLockError(f"lock is already held in this process: {name}")
            self._held_locks.add(name)
        lock = _OSFileLock(path)
        try:
            lock.acquire()
            yield
        finally:
            lock.release()
            with self._held_guard:
                self._held_locks.discard(name)

    @contextmanager
    def lock_job(self, job_id: str) -> Iterator[None]:
        root = self.job_root(job_id)
        if not root.is_dir():
            raise JobValidationError(f"job does not exist: {job_id}")
        with self._lock(f"job:{job_id}", root / ".lock"):
            yield

    @contextmanager
    def identity_lock(self) -> Iterator[None]:
        with self._lock("identity", self.jobs_root / ".identity.lock"):
            yield

    @contextmanager
    def transaction(self, job_id: str) -> Iterator[JobTransaction]:
        root = self.job_root(job_id)
        if not root.is_dir():
            raise JobValidationError(f"job does not exist: {job_id}")
        with self._lock(f"job:{job_id}", root / ".lock"):
            transaction = JobTransaction(self, job_id)
            try:
                yield transaction
                transaction.commit()
            except OSError as error:
                raise JobValidationError("atomic job manifest replacement failed") from error

    def update_job(self, *_args: Any, **_kwargs: Any) -> None:
        raise JobValidationError("unrestricted job mutation is not supported; use transaction()")

    def advance_stage(self, job_id: str, target_stage: str) -> dict[str, Any]:
        with self.transaction(job_id) as transaction:
            transaction.advance_stage(target_stage)
        return self.load_job(job_id)

    def register_artifact(self, job_id: str, relative_path: str) -> dict[str, Any]:
        with self.transaction(job_id) as transaction:
            transaction.register_artifact(relative_path)
        return self.load_job(job_id)

    def validate_artifact(self, job_id: str, relative_path: str) -> Path:
        state = self.load_job(job_id)
        root = self.job_root(job_id)
        relative = self._safe_relative_path(relative_path)
        record = state["artifacts"].get(relative.as_posix())
        if not isinstance(record, dict):
            raise ArtifactValidationError(f"artifact is not registered: {relative.as_posix()}")
        target = root.joinpath(*relative.parts)
        self._assert_safe_artifact_path(root, target)
        if not target.is_file() or _hash_file(target) != (record["sha256"], record["byte_size"]):
            raise ArtifactValidationError(f"artifact no longer matches recorded hash/size: {relative.as_posix()}")
        return target

    def validate_source(self, job_id: str) -> Path:
        state = self.load_job(job_id)
        source = state["source"]
        if not isinstance(source, dict):
            raise ArtifactValidationError("job has no bound source metadata")
        path = self.validate_artifact(job_id, "source/source.bin")
        if _hash_file(path) != (state["source_sha256"], source["byte_size"]):
            raise ArtifactValidationError("source metadata does not match its artifact")
        return path

    def find_url_candidates(self, url: str) -> list[dict[str, Any]]:
        return [state for state in self.list_jobs() if any(url in (pair["requested_url"], pair["resolved_url"]) for pair in state["source_url_aliases"])]

    def find_hash_candidates(self, source_sha256: str) -> list[dict[str, Any]]:
        return [state for state in self.list_jobs() if state["source_sha256"] == source_sha256]

    @staticmethod
    def _validate_https_url(url: object) -> None:
        from urllib.parse import urlsplit
        parsed = urlsplit(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme.lower() != "https" or not parsed.netloc:
            raise JobValidationError("source URL must be an HTTPS URL")

    @staticmethod
    def _safe_relative_path(value: str) -> PurePosixPath:
        if not isinstance(value, str) or not value:
            raise JobValidationError("artifact path must be a non-empty relative path")
        windows, posix = PureWindowsPath(value), PurePosixPath(value.replace("\\", "/"))
        if windows.is_absolute() or windows.drive or posix.is_absolute():
            raise JobValidationError("artifact path must be relative")
        for part in posix.parts:
            base = part.lower().split(".", 1)[0]
            if part in ("", ".", "..") or base in _WINDOWS_DEVICES or part.endswith((".", " ")) or any(c in part for c in '<>:"|?*'):
                raise JobValidationError("artifact path contains an unsafe Windows component")
        return posix

    def _assert_safe_directory(self, path: Path, label: str) -> None:
        if not path.is_dir() or _is_reparse(path):
            raise RepositoryHealthError(f"{label} must be a non-reparse directory")

    def _assert_safe_artifact_path(self, root: Path, target: Path) -> None:
        self._assert_safe_directory(self.data_root, "data root")
        self._assert_safe_directory(self.jobs_root, "jobs root")
        self._assert_safe_directory(root, "job root")
        try:
            parts = target.relative_to(root).parts
        except ValueError as error:
            raise ArtifactValidationError("artifact path escapes its job root") from error
        current = root
        for part in parts:
            current = current / part
            if current.exists() and _is_reparse(current):
                raise ArtifactValidationError("symlink/reparse artifacts are not allowed")
        try:
            target.resolve(strict=False).relative_to(root.resolve())
        except ValueError as error:
            raise ArtifactValidationError("artifact resolves outside its job root") from error

    def _validate_source_metadata(self, source: object, tool_versions: object) -> None:
        if not isinstance(source, dict):
            raise JobValidationError("source metadata must be an object")
        for key in ("requested_url", "resolved_url"):
            self._validate_https_url(source.get(key))
        if not _is_sha256(source.get("sha256")) or not isinstance(source.get("byte_size"), int) or isinstance(source.get("byte_size"), bool) or source["byte_size"] < 0:
            raise JobValidationError("source hash/size metadata is invalid")
        duration = source.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
            raise JobValidationError("source duration must be finite and non-negative")
        if not isinstance(source.get("codec"), str) or not source["codec"] or not isinstance(source.get("streams"), list) or not source["streams"]:
            raise JobValidationError("source codec/streams metadata is invalid")
        if not any(isinstance(stream, dict) and stream.get("codec_type") == "audio" and isinstance(stream.get("codec_name"), str) and stream["codec_name"] for stream in source["streams"]):
            raise JobValidationError("source probe has no valid audio stream")
        if not isinstance(tool_versions, dict) or any(not isinstance(tool_versions.get(key), str) or not tool_versions[key].strip() for key in ("downloader", "ffprobe")):
            raise JobValidationError("source tool versions must include downloader and ffprobe")

    def _validate_manifest(self, state: object, expected_id: str) -> None:
        if not isinstance(state, dict):
            raise RepositoryHealthError("job manifest must be a JSON object")
        required = {"schema_version", "revision", "job_id", "source_sha256", "stage", "created_at", "updated_at", "stage_history", "source", "source_url_aliases", "tool_versions", "artifacts"}
        if not required.issubset(state) or state["schema_version"] != 1 or state["job_id"] != expected_id or not _is_sha256(state["source_sha256"]):
            raise RepositoryHealthError("job manifest identity/schema is invalid")
        if not isinstance(state["revision"], int) or isinstance(state["revision"], bool) or state["revision"] < 0 or state["stage"] not in (set(_NEXT_STAGE) | {"handed_off"}):
            raise RepositoryHealthError("job manifest revision or stage is invalid")
        if not all(isinstance(state[key], str) and state[key] for key in ("created_at", "updated_at")) or not isinstance(state["stage_history"], list) or not state["stage_history"]:
            raise RepositoryHealthError("job manifest timestamps/history are invalid")
        stages = [entry.get("stage") for entry in state["stage_history"] if isinstance(entry, dict) and isinstance(entry.get("at"), str)]
        if len(stages) != len(state["stage_history"]) or stages[0] != "created" or stages[-1] != state["stage"] or any(_NEXT_STAGE.get(before) != after for before, after in zip(stages, stages[1:])):
            raise RepositoryHealthError("job manifest stage history is invalid")
        if not expected_id.endswith("-" + state["source_sha256"][:8]):
            raise RepositoryHealthError("job ID is not bound to its source hash")
        if not isinstance(state["source_url_aliases"], list) or not isinstance(state["tool_versions"], dict) or not isinstance(state["artifacts"], dict):
            raise RepositoryHealthError("job manifest evidence collections are invalid")
        for alias in state["source_url_aliases"]:
            if not isinstance(alias, dict):
                raise RepositoryHealthError("job source alias is invalid")
            self._validate_https_url(alias.get("requested_url"))
            self._validate_https_url(alias.get("resolved_url"))
        for path, record in state["artifacts"].items():
            self._safe_relative_path(path)
            if not isinstance(record, dict) or not _is_sha256(record.get("sha256")) or not isinstance(record.get("byte_size"), int) or isinstance(record.get("byte_size"), bool) or record["byte_size"] < 0:
                raise RepositoryHealthError("job artifact record is invalid")
        if state["source"] is None:
            if state["stage"] != "created" or state["artifacts"] or state["source_url_aliases"] or state["tool_versions"]:
                raise RepositoryHealthError("unbound job carries source evidence")
        else:
            self._validate_source_metadata(state["source"], state["tool_versions"])
            if state["source"]["sha256"] != state["source_sha256"] or "source/source.bin" not in state["artifacts"] or not state["source_url_aliases"]:
                raise RepositoryHealthError("bound source evidence is incomplete")

    @staticmethod
    def _write_manifest(root: Path, state: dict[str, Any]) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".job.json.", suffix=".tmp", dir=root)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(state, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, root / "job.json")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
