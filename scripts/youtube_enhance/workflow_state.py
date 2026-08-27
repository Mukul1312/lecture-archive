from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import threading
from typing import Any, BinaryIO, Mapping


JOB_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
WINDOWS_DEVICES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
SKILL_RELATIVE = Path(".agents/skills/enhancing-lecture-audio/SKILL.md")
JOBS_RELATIVE = Path("data/enhance/jobs")
PROTECTED_RELATIVE = Path("data/enhance/youtube")

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_FORBIDDEN = frozenset('<>:"\\|?*')
_JOB_THREAD_LOCKS: dict[str, threading.Lock] = {}
_JOB_THREAD_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class RepositoryIdentity:
    canonical_root: Path
    git_common_dir: Path
    git_common_file_id: tuple[int, int]
    identity_sha256: str


@dataclass(frozen=True)
class JobPaths:
    repository: RepositoryIdentity
    data_root: Path
    job_root: Path
    job_file: Path
    lock_file: Path


@dataclass(frozen=True)
class ArtifactRecord:
    relative_path: str
    sha256: str
    size_bytes: int
    file_id: tuple[int, int]
    media: Mapping[str, Any] | None


class JobBusy(RuntimeError):
    pass


class InvalidJobState(RuntimeError):
    pass


class InvalidTransition(RuntimeError):
    pass


class StaleJobState(RuntimeError):
    pass


def _filesystem_path(path: Path | str) -> str:
    value = os.fspath(path)
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    absolute = os.path.abspath(value)
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _ordinary_path(path: str) -> Path:
    if path.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + path[8:])
    if path.startswith("\\\\?\\"):
        return Path(path[4:])
    return Path(path)


def _lstat(path: Path) -> os.stat_result:
    return os.lstat(_filesystem_path(path))


def _is_reparse(status: os.stat_result) -> bool:
    return stat.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _reject_existing_reparse_components(path: Path, *, require_complete: bool) -> None:
    if not path.is_absolute():
        raise ValueError(f"path must be absolute: {path}")

    current = Path(path.anchor)
    components = path.parts[1:]
    candidates = (current, *(current.joinpath(*components[:index]) for index in range(1, len(components) + 1)))
    for candidate in candidates:
        try:
            status = _lstat(candidate)
        except FileNotFoundError as error:
            if require_complete:
                raise ValueError(f"required path component is missing: {candidate}") from error
            return
        if _is_reparse(status):
            raise ValueError(f"path contains a reparse component: {candidate}")


def _normalized_path_text(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))


def _physical_path(path: Path) -> Path:
    return _ordinary_path(os.path.realpath(_filesystem_path(path)))


def _require_directory(path: Path) -> os.stat_result:
    _reject_existing_reparse_components(path, require_complete=True)
    status = _lstat(path)
    if _is_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise ValueError(f"expected a real non-reparse directory: {path}")
    return status


def _require_regular_file(path: Path) -> os.stat_result:
    _reject_existing_reparse_components(path, require_complete=True)
    status = _lstat(path)
    if _is_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise ValueError(f"expected a regular non-reparse file: {path}")
    return status


def discover_canonical_repository(
    start: Path, *, git_executable: str = "git"
) -> RepositoryIdentity:
    try:
        completed = subprocess.run(
            [
                git_executable,
                "-C",
                os.fspath(start),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, ValueError) as error:
        raise ValueError("could not execute canonical repository discovery") from error
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise ValueError("git common-directory discovery failed")

    lines = completed.stdout.splitlines()
    if len(lines) != 1 or not lines[0] or lines[0] != lines[0].strip():
        raise ValueError("git must return exactly one non-empty common-directory line")
    raw_common_dir = lines[0]
    raw_components = re.split(r"[\\/]", raw_common_dir)
    if any(component in {".", ".."} for component in raw_components):
        raise ValueError("git common-directory output must be normalized")

    common_candidate = Path(raw_common_dir)
    if not common_candidate.is_absolute():
        raise ValueError("git common directory must be absolute")
    common_candidate = Path(os.path.normpath(raw_common_dir))
    _require_directory(common_candidate)
    if common_candidate.name != ".git":
        raise ValueError("git common directory must be a real directory named .git")

    git_common_dir = _physical_path(common_candidate)
    common_status = _require_directory(git_common_dir)
    canonical_root = git_common_dir.parent
    root_common = canonical_root / ".git"
    root_common_status = _require_directory(root_common)
    if not os.path.samestat(common_status, root_common_status):
        raise ValueError("canonical root .git does not match the Git common directory")

    skill = canonical_root / SKILL_RELATIVE
    _require_regular_file(skill)

    file_id = (common_status.st_dev, common_status.st_ino)
    identity_input = "\0".join(
        (
            _normalized_path_text(canonical_root),
            _normalized_path_text(git_common_dir),
            str(file_id[0]),
            str(file_id[1]),
        )
    ).encode("utf-8")
    return RepositoryIdentity(
        canonical_root=canonical_root,
        git_common_dir=git_common_dir,
        git_common_file_id=file_id,
        identity_sha256=hashlib.sha256(identity_input).hexdigest(),
    )


def _device_stem(component: str) -> str:
    return component.rstrip(" .").split(".", 1)[0].upper()


def job_paths(repository: RepositoryIdentity, job_id: str) -> JobPaths:
    if not isinstance(job_id, str) or JOB_ID.fullmatch(job_id) is None:
        raise ValueError("job ID must contain lowercase ASCII letters, digits, or hyphens")
    if job_id == ".locks" or _device_stem(job_id) in WINDOWS_DEVICES:
        raise ValueError("job ID is reserved")
    if not repository.canonical_root.is_absolute():
        raise ValueError("canonical repository root must be absolute")

    data_root = repository.canonical_root / JOBS_RELATIVE
    job_root = data_root / job_id
    normalized_job_root = _normalized_path_text(job_root)
    lock_id = hashlib.sha256(normalized_job_root.encode("utf-8")).hexdigest()
    return JobPaths(
        repository=repository,
        data_root=data_root,
        job_root=job_root,
        job_file=job_root / "job.json",
        lock_file=data_root / ".locks" / f"{lock_id}.lock",
    )


def existing_job_paths(job_file: Path) -> JobPaths:
    """Bind an existing job file to its canonical repository root and job ID."""
    job_file = Path(job_file)
    if ".." in job_file.parts:
        raise ValueError("job state path must not contain traversal components")
    absolute_job_file = Path(os.path.abspath(os.path.normpath(os.fspath(job_file))))
    if absolute_job_file.name != "job.json":
        raise ValueError("job state path must end with job.json")

    repository = discover_canonical_repository(absolute_job_file.parent)
    protected_root_text = _normalized_path_text(
        repository.canonical_root / PROTECTED_RELATIVE
    )
    job_file_text = _normalized_path_text(absolute_job_file)
    try:
        inside_protected_root = (
            os.path.commonpath((protected_root_text, job_file_text))
            == protected_root_text
        )
    except ValueError:
        inside_protected_root = False
    if inside_protected_root:
        raise ValueError("job state path is inside protected legacy storage")

    paths = job_paths(repository, absolute_job_file.parent.name)
    if job_file_text != _normalized_path_text(paths.job_file):
        raise ValueError("job state path is outside the canonical jobs root")
    _require_regular_file(paths.job_file)
    return paths


def _validate_job_paths(paths: JobPaths) -> None:
    expected_data_root = paths.repository.canonical_root / JOBS_RELATIVE
    if _normalized_path_text(paths.data_root) != _normalized_path_text(expected_data_root):
        raise ValueError("job data root is not canonical")
    if paths.job_root.parent != paths.data_root or paths.job_root.name == ".locks":
        raise ValueError("job root is not an immediate child of the canonical data root")
    if paths.job_file != paths.job_root / "job.json":
        raise ValueError("job state path is not canonical")
    lock_id = hashlib.sha256(
        _normalized_path_text(paths.job_root).encode("utf-8")
    ).hexdigest()
    expected_lock_file = paths.data_root / ".locks" / f"{lock_id}.lock"
    if _normalized_path_text(paths.lock_file) != _normalized_path_text(expected_lock_file):
        raise ValueError("job lock path is not canonical")


def _validate_repository_identity(repository: RepositoryIdentity) -> None:
    root_status = _require_directory(repository.canonical_root)
    common_status = _require_directory(repository.git_common_dir)
    if (common_status.st_dev, common_status.st_ino) != repository.git_common_file_id:
        raise ValueError("Git common-directory identity has changed")
    root_common_status = _require_directory(repository.canonical_root / ".git")
    if not os.path.samestat(common_status, root_common_status):
        raise ValueError("canonical root .git no longer matches the Git common directory")
    if not stat.S_ISDIR(root_status.st_mode):
        raise ValueError("canonical repository root is not a directory")


def _create_real_directory(path: Path) -> None:
    _reject_existing_reparse_components(path, require_complete=False)
    try:
        path.mkdir()
    except FileExistsError:
        pass
    _require_directory(path)


@contextmanager
def job_lock(paths: JobPaths, *, blocking: bool = True):
    """Hold the canonical per-job lock, optionally failing fast when busy."""
    _validate_job_paths(paths)
    _validate_repository_identity(paths.repository)

    current = paths.repository.canonical_root
    for component in JOBS_RELATIVE.parts:
        current = current / component
        _create_real_directory(current)
    lock_root = paths.data_root / ".locks"
    _create_real_directory(lock_root)

    lock_key = _normalized_path_text(paths.lock_file)
    with _JOB_THREAD_LOCKS_GUARD:
        thread_lock = _JOB_THREAD_LOCKS.setdefault(lock_key, threading.Lock())
    if not thread_lock.acquire(blocking=blocking):
        raise JobBusy(f"job is already running: {paths.job_root.name}")

    try:
        if os.path.lexists(paths.lock_file):
            existing = _lstat(paths.lock_file)
            if _is_reparse(existing) or not stat.S_ISREG(existing.st_mode):
                raise ValueError("job lock must be a regular non-reparse file")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(_filesystem_path(paths.lock_file), flags, 0o600)
        try:
            with os.fdopen(descriptor, "r+b", closefd=True) as handle:
                descriptor = -1
                opened = os.fstat(handle.fileno())
                named = _lstat(paths.lock_file)
                if (
                    _is_reparse(named)
                    or not stat.S_ISREG(opened.st_mode)
                    or not os.path.samestat(opened, named)
                ):
                    raise ValueError("job lock path changed while opening")
                if opened.st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                    os.fsync(handle.fileno())
                handle.seek(0)

                try:
                    if os.name == "nt":
                        import msvcrt

                        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                        msvcrt.locking(handle.fileno(), mode, 1)
                        unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        mode = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                        fcntl.flock(handle.fileno(), mode)
                        unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError as error:
                    raise JobBusy(f"job is already running: {paths.job_root.name}") from error
                try:
                    yield paths
                finally:
                    handle.seek(0)
                    unlock()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    finally:
        thread_lock.release()


def _validate_relative_component(component: str) -> None:
    if component in {"", ".", ".."}:
        raise ValueError("output path contains a dot or traversal component")
    if component[-1] in {" ", "."}:
        raise ValueError("output path contains a Windows-unsafe trailing character")
    if any(character in _WINDOWS_FORBIDDEN or ord(character) < 32 for character in component):
        raise ValueError("output path contains a Windows-unsafe character")
    if _device_stem(component) in WINDOWS_DEVICES:
        raise ValueError("output path contains a reserved Windows device component")


def safe_output_path(paths: JobPaths, relative_path: PurePosixPath) -> Path:
    _validate_job_paths(paths)
    if not isinstance(relative_path, PurePosixPath):
        raise ValueError("output path must be a relative POSIX path")
    if relative_path.is_absolute() or not relative_path.parts:
        raise ValueError("output path must be relative")
    for component in relative_path.parts:
        _validate_relative_component(component)

    candidate = paths.job_root.joinpath(*relative_path.parts)
    root_text = _normalized_path_text(paths.job_root)
    candidate_text = _normalized_path_text(candidate)
    try:
        contained = os.path.commonpath((root_text, candidate_text)) == root_text
    except ValueError:
        contained = False
    if not contained:
        raise ValueError("output path escapes the job root")
    _reject_existing_reparse_components(Path(candidate_text), require_complete=False)
    return candidate


def _open_artifact_handle(path: Path) -> BinaryIO:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(_filesystem_path(path), flags)
    try:
        return os.fdopen(descriptor, "rb", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def _sha256_file(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    while block := handle.read(1024 * 1024):
        digest.update(block)
    return digest.hexdigest()


def _stable_filesystem_metadata(status: os.stat_result) -> tuple[int, ...]:
    values = [
        status.st_mode,
        status.st_size,
        status.st_dev,
        status.st_ino,
        status.st_mtime_ns,
    ]
    if hasattr(status, "st_ctime_ns"):
        values.append(status.st_ctime_ns)
    return tuple(values)


def validate_existing_artifact(paths: JobPaths, record: ArtifactRecord) -> Path:
    if not isinstance(record, ArtifactRecord):
        raise ValueError("artifact record has the wrong type")
    if not isinstance(record.relative_path, str) or not record.relative_path:
        raise ValueError("artifact path must be a non-empty relative POSIX string")
    relative_path = PurePosixPath(record.relative_path)
    if relative_path.as_posix() != record.relative_path:
        raise ValueError("artifact path must already be normalized")
    path = safe_output_path(paths, relative_path)

    try:
        before = _require_regular_file(path)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(f"artifact is not an existing regular file: {path}") from error
    if before.st_size != record.size_bytes:
        raise ValueError("artifact size does not match its record")
    if (before.st_dev, before.st_ino) != record.file_id:
        raise ValueError("artifact file ID does not match its record")
    if not isinstance(record.sha256, str) or _SHA256.fullmatch(record.sha256) is None:
        raise ValueError("artifact SHA-256 must be lowercase hexadecimal")

    try:
        with _open_artifact_handle(path) as handle:
            handle_before = os.fstat(handle.fileno())
            if _is_reparse(handle_before) or not stat.S_ISREG(handle_before.st_mode):
                raise ValueError("artifact handle is not a regular non-reparse file")
            if _stable_filesystem_metadata(handle_before) != _stable_filesystem_metadata(before):
                raise ValueError("artifact handle does not match the prevalidated path")
            if handle_before.st_size != record.size_bytes:
                raise ValueError("artifact handle size does not match its record")
            if (handle_before.st_dev, handle_before.st_ino) != record.file_id:
                raise ValueError("artifact handle file ID does not match its record")

            actual_sha256 = _sha256_file(handle)
            handle_after = os.fstat(handle.fileno())
            if _stable_filesystem_metadata(handle_before) != _stable_filesystem_metadata(
                handle_after
            ):
                raise ValueError("artifact handle metadata changed while hashing")
    except (FileNotFoundError, OSError) as error:
        raise ValueError("artifact changed while it was being validated") from error

    try:
        after = _require_regular_file(path)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("artifact changed while it was being validated") from error
    if (
        _stable_filesystem_metadata(before) != _stable_filesystem_metadata(after)
        or _stable_filesystem_metadata(handle_before) != _stable_filesystem_metadata(after)
    ):
        raise ValueError("artifact identity or metadata changed while it was being validated")
    if not hmac.compare_digest(actual_sha256, record.sha256):
        raise ValueError("artifact SHA-256 does not match its record")
    return path
