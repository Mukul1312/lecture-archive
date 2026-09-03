"""Minimum offline initialization, diagnostics, backup, and restore operations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from heritage_archive.kernel import (
    ActorId,
    ContentDigest,
    JsonValue,
    ValidationError,
    canonical_json,
    parse_strict_json,
    require_canonical_text,
)
from heritage_archive.platform.storage.local_files import (
    PublicationEvidenceMismatch,
    SingleWriterFileLock,
    publish_bytes_no_clobber,
)

from ..application.ports import IdentifierSource
from ..domain.values import DictionaryBinding, NonNegativeDecimal, SafeRelativeArtifactPath
from .local_root import LocalNarrationRoot


_INITIALIZATION_SCHEMA = "narrator_voice.local_studio_initialization"
_CONFIGURATION_SCHEMA = "narrator_voice.local_studio_configuration"
_BACKUP_SCHEMA = "narrator_voice.full_backup_manifest"
_SCHEMA_VERSION = 1
_INITIALIZATION_FIELDS = {
    "schema",
    "schema_version",
    "operator_display_label",
    "lane_b",
    "lane_c",
    "budget",
    "default_passage_gap_samples",
    "default_intro_to_diary_gap_samples",
}
_CONFIGURATION_FIELDS = _INITIALIZATION_FIELDS | {"actor_id"}
_PROFILE_FIELDS = {
    "display_label",
    "speaker_identity",
    "opaque_provider_voice_reference",
    "dictionary_binding",
}
_DICTIONARY_FIELDS = {
    "opaque_reference",
    "content_sha256",
    "revision",
    "capability_identity",
}
_BUDGET_FIELDS = {
    "project_id",
    "billing_cycle_id",
    "usage_unit",
    "per_take_cap",
    "per_run_cap",
    "project_cap",
    "billing_cycle_cap",
}
_MANIFEST_FIELDS = {"schema", "schema_version", "files"}
_MANIFEST_ENTRY_FIELDS = {"path", "byte_length", "sha256"}
_REVISION_FILE = re.compile(r"^[0-9]{20}\.json$")


@dataclass(frozen=True, slots=True)
class LocalStudioVoiceProfile:
    display_label: str
    speaker_identity: str
    opaque_provider_voice_reference: str
    dictionary_binding: DictionaryBinding | None

    def __post_init__(self) -> None:
        for field, value in (
            ("profile display label", self.display_label),
            ("profile speaker identity", self.speaker_identity),
            ("opaque provider voice reference", self.opaque_provider_voice_reference),
        ):
            require_canonical_text(value, field=field, nonempty=True)
        if self.dictionary_binding is not None and type(self.dictionary_binding) is not DictionaryBinding:
            raise ValidationError("profile dictionary binding must be complete or null")


@dataclass(frozen=True, slots=True)
class LocalStudioBudgetConfiguration:
    project_id: str
    billing_cycle_id: str
    usage_unit: str
    per_take_cap: NonNegativeDecimal
    per_run_cap: NonNegativeDecimal
    project_cap: NonNegativeDecimal
    billing_cycle_cap: NonNegativeDecimal

    def __post_init__(self) -> None:
        for field, value in (
            ("budget project id", self.project_id),
            ("budget billing-cycle id", self.billing_cycle_id),
            ("budget usage unit", self.usage_unit),
        ):
            require_canonical_text(value, field=field, nonempty=True)
        if any(
            type(value) is not NonNegativeDecimal
            for value in (
                self.per_take_cap,
                self.per_run_cap,
                self.project_cap,
                self.billing_cycle_cap,
            )
        ):
            raise ValidationError("budget caps must be exact nonnegative decimals")


@dataclass(frozen=True, slots=True)
class LocalStudioInitialization:
    operator_display_label: str
    lane_b: LocalStudioVoiceProfile
    lane_c: LocalStudioVoiceProfile
    budget: LocalStudioBudgetConfiguration
    default_passage_gap_samples: int
    default_intro_to_diary_gap_samples: int

    def __post_init__(self) -> None:
        _validate_studio_values(
            self.operator_display_label,
            self.lane_b,
            self.lane_c,
            self.budget,
            self.default_passage_gap_samples,
            self.default_intro_to_diary_gap_samples,
        )


@dataclass(frozen=True, slots=True)
class LocalStudioConfiguration:
    actor_id: ActorId
    operator_display_label: str
    lane_b: LocalStudioVoiceProfile
    lane_c: LocalStudioVoiceProfile
    budget: LocalStudioBudgetConfiguration
    default_passage_gap_samples: int
    default_intro_to_diary_gap_samples: int

    def __post_init__(self) -> None:
        if type(self.actor_id) is not ActorId:
            raise ValidationError("local studio configuration requires one stable ActorId")
        _validate_studio_values(
            self.operator_display_label,
            self.lane_b,
            self.lane_c,
            self.budget,
            self.default_passage_gap_samples,
            self.default_intro_to_diary_gap_samples,
        )


@dataclass(frozen=True, slots=True)
class InitResult:
    initialized: bool
    configuration_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class DoctorResult:
    healthy: bool
    checked_file_count: int
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackupResult:
    file_count: int
    byte_count: int
    manifest_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class BackupVerificationResult:
    valid: bool
    file_count: int
    byte_count: int
    manifest_digest: ContentDigest | None
    issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RestoreResult:
    file_count: int
    byte_count: int
    manifest_digest: ContentDigest


@dataclass(frozen=True, slots=True)
class _BackupEntry:
    path: str
    byte_length: int
    digest: ContentDigest


def load_local_studio_initialization(
    path: str | Path,
    forbidden_roots: tuple[Path, ...],
) -> LocalStudioInitialization:
    """Load one external, canonical, strict v1 private initialization document."""
    source = _external_file(path, forbidden_roots)
    document, _ = _read_canonical_object(source)
    return _decode_initialization(document)


def initialize_local_studio(
    root: LocalNarrationRoot,
    request: LocalStudioInitialization,
    identifiers: IdentifierSource,
) -> InitResult:
    """Create one no-clobber private configuration and the standard local layout."""
    _require_root(root)
    if type(request) is not LocalStudioInitialization:
        raise ValidationError("local studio initialization request is invalid")
    config_path = root.operations / "studio-config.json"
    with SingleWriterFileLock(root.writer_lock):
        if os.path.lexists(config_path):
            configuration = load_local_studio_configuration(root)
            payload = config_path.read_bytes()
            if _configuration_request(configuration) != request:
                raise ValidationError("local studio configuration conflicts with initialization")
            return InitResult(False, ContentDigest.from_bytes(payload))

        try:
            existing = tuple(item for item in root.path.iterdir() if item.name != ".writer.lock")
        except OSError as error:
            raise ValidationError("local studio root cannot be inspected") from error
        if existing:
            raise ValidationError("local studio initialization refuses orphan or unrelated evidence")
        new_id = getattr(identifiers, "new_id", None)
        if not callable(new_id):
            raise ValidationError("local studio initialization requires an identifier source")
        actor_id = new_id(ActorId)
        if type(actor_id) is not ActorId:
            raise ValidationError("identifier source did not return an ActorId")
        configuration = LocalStudioConfiguration(
            actor_id,
            request.operator_display_label,
            request.lane_b,
            request.lane_c,
            request.budget,
            request.default_passage_gap_samples,
            request.default_intro_to_diary_gap_samples,
        )
        root.initialize_layout()
        for directory in root.layout_directories:
            _require_safe_directory(directory, "local studio layout")
        payload = canonical_json(_configuration_document(configuration))
        try:
            publish_bytes_no_clobber(root.staging, config_path, payload)
        except (OSError, PublicationEvidenceMismatch, FileExistsError) as error:
            raise ValidationError("local studio configuration could not be published") from error
        return InitResult(True, ContentDigest.from_bytes(payload))


def load_local_studio_configuration(root: LocalNarrationRoot) -> LocalStudioConfiguration:
    """Strictly decode the private configuration for composition-root use only."""
    _require_root(root)
    _require_safe_directory(root.operations, "operations directory")
    path = root.operations / "studio-config.json"
    _reject_reparse(path)
    if not os.path.lexists(path):
        raise ValidationError("local studio configuration is missing")
    document, _ = _read_canonical_object(path)
    return _decode_configuration(document)


def doctor(root: LocalNarrationRoot) -> DoctorResult:
    """Inspect local evidence without acquiring a lock or changing any byte."""
    _require_root(root)
    issues: set[str] = set()
    checked_files = 0

    for directory in root.layout_directories:
        if not os.path.lexists(directory):
            issues.add("layout_missing")
            continue
        try:
            metadata = directory.lstat()
            if _metadata_is_reparse(metadata):
                issues.add("path_reparse")
            elif not stat.S_ISDIR(metadata.st_mode):
                issues.add("path_nonregular")
        except OSError:
            issues.add("path_unreadable")

    config_path = root.operations / "studio-config.json"
    if not os.path.lexists(config_path):
        issues.add("config_missing")
    else:
        try:
            load_local_studio_configuration(root)
        except (OSError, ValidationError):
            issues.add("config_invalid")

    if os.path.lexists(root.staging):
        try:
            if any(root.staging.iterdir()):
                issues.add("staging_nonempty")
        except OSError:
            issues.add("path_unreadable")

    stack = [root.path]
    while stack:
        current = stack.pop()
        try:
            children = tuple(current.iterdir())
        except OSError:
            issues.add("path_unreadable")
            continue
        for path in children:
            try:
                metadata = path.lstat()
            except OSError:
                issues.add("path_unreadable")
                continue
            if _metadata_is_reparse(metadata):
                issues.add("path_reparse")
                continue
            if stat.S_ISDIR(metadata.st_mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                issues.add("path_nonregular")
                continue
            checked_files += 1
            relative = path.relative_to(root.path)
            if _json_is_operational_evidence(relative):
                try:
                    raw = path.read_bytes()
                    parsed = parse_strict_json(raw)
                    if canonical_json(parsed) != raw:
                        issues.add("json_noncanonical")
                except (OSError, ValidationError):
                    issues.add("json_invalid")

    _check_aggregate_revisions(root, issues)
    issue_codes = tuple(sorted(issues))
    return DoctorResult(not issue_codes, checked_files, issue_codes)


def backup(
    root: LocalNarrationRoot,
    destination: str | Path,
    forbidden_roots: tuple[Path, ...],
) -> BackupResult:
    """Create one locked full copy and publish its hash manifest last."""
    _require_root(root)
    target = _external_directory(destination, forbidden_roots, require_empty=True)
    _reject_overlap(root.path, target)
    entries: list[_BackupEntry] = []
    with SingleWriterFileLock(root.writer_lock):
        _require_empty(target)
        for source, relative in _regular_tree_files(root.path, {".writer.lock"}):
            entry = _copy_verified(source, target / Path(*relative.split("/")))
            entries.append(_BackupEntry(relative, entry.byte_length, entry.digest))
        entries.sort(key=lambda item: item.path.encode("utf-8"))
        manifest_bytes = canonical_json(_manifest_document(tuple(entries)))
        manifest_path = target / "backup-manifest.json"
        try:
            publish_bytes_no_clobber(target, manifest_path, manifest_bytes, staging_suffix=".manifeststage")
        except (OSError, PublicationEvidenceMismatch, FileExistsError) as error:
            raise ValidationError("backup manifest could not be published") from error
    return BackupResult(
        len(entries),
        sum(entry.byte_length for entry in entries),
        ContentDigest.from_bytes(manifest_bytes),
    )


def verify_backup(
    source: str | Path,
    forbidden_roots: tuple[Path, ...],
) -> BackupVerificationResult:
    """Read and compare an exact backup file set without changing the backup."""
    root = _external_directory(source, forbidden_roots, require_empty=False)
    issues: set[str] = set()
    manifest_path = root / "backup-manifest.json"
    manifest_digest: ContentDigest | None = None
    entries: tuple[_BackupEntry, ...] = ()
    try:
        entries, manifest_digest = _load_manifest(manifest_path)
    except ValidationError:
        issues.add("backup_manifest_invalid")
        return BackupVerificationResult(False, 0, 0, manifest_digest, tuple(sorted(issues)))

    try:
        actual = {
            relative: path
            for path, relative in _regular_tree_files(
                root,
                {".writer.lock", "backup-manifest.json"},
            )
        }
    except ValidationError:
        issues.add("backup_path_unsafe")
        return BackupVerificationResult(
            False,
            len(entries),
            sum(item.byte_length for item in entries),
            manifest_digest,
            tuple(sorted(issues)),
        )

    expected = {entry.path: entry for entry in entries}
    if set(expected) - set(actual):
        issues.add("backup_file_missing")
    if set(actual) - set(expected):
        issues.add("backup_file_extra")
    for relative in set(expected) & set(actual):
        entry = expected[relative]
        try:
            digest, length = _hash_file(actual[relative])
        except OSError:
            issues.add("backup_file_unreadable")
            continue
        if length != entry.byte_length:
            issues.add("backup_file_size_mismatch")
        if digest != entry.digest:
            issues.add("backup_file_digest_mismatch")
    issue_codes = tuple(sorted(issues))
    return BackupVerificationResult(
        not issue_codes,
        len(entries),
        sum(item.byte_length for item in entries),
        manifest_digest,
        issue_codes,
    )


def restore(
    source: str | Path,
    destination: str | Path,
    forbidden_roots: tuple[Path, ...],
) -> RestoreResult:
    """Restore one verified backup into an explicit empty external root."""
    backup_root = _external_directory(source, forbidden_roots, require_empty=False)
    target = _external_directory(destination, forbidden_roots, require_empty=True)
    _reject_overlap(backup_root, target)
    verification = verify_backup(backup_root, forbidden_roots)
    if not verification.valid or verification.manifest_digest is None:
        raise ValidationError("restore source backup is not valid")
    entries, manifest_digest = _load_manifest(backup_root / "backup-manifest.json")

    local_root = LocalNarrationRoot.open(target, forbidden_roots)
    with SingleWriterFileLock(local_root.writer_lock):
        if any(item.name != ".writer.lock" for item in target.iterdir()):
            raise ValidationError("restore destination must remain empty")
        local_root.initialize_layout()
        for entry in entries:
            copied = _copy_verified(
                backup_root / Path(*entry.path.split("/")),
                target / Path(*entry.path.split("/")),
            )
            if copied.byte_length != entry.byte_length or copied.digest != entry.digest:
                raise ValidationError("restored file does not match backup evidence")
        restored = {
            relative: path
            for path, relative in _regular_tree_files(target, {".writer.lock"})
        }
        if set(restored) != {entry.path for entry in entries}:
            raise ValidationError("restored file set does not match backup evidence")
        for entry in entries:
            digest, length = _hash_file(restored[entry.path])
            if digest != entry.digest or length != entry.byte_length:
                raise ValidationError("restored bytes do not match backup evidence")
    return RestoreResult(
        len(entries),
        sum(entry.byte_length for entry in entries),
        manifest_digest,
    )


def _validate_studio_values(
    operator_display_label: object,
    lane_b: object,
    lane_c: object,
    budget: object,
    passage_gap: object,
    intro_gap: object,
) -> None:
    require_canonical_text(operator_display_label, field="operator display label", nonempty=True)
    if type(lane_b) is not LocalStudioVoiceProfile or type(lane_c) is not LocalStudioVoiceProfile:
        raise ValidationError("local studio requires exact Lane-B and Lane-C profiles")
    if type(budget) is not LocalStudioBudgetConfiguration:
        raise ValidationError("local studio budget configuration is invalid")
    if type(passage_gap) is not int or passage_gap < 0:
        raise ValidationError("default passage gap must be a nonnegative sample count")
    if type(intro_gap) is not int or intro_gap < 0:
        raise ValidationError("default intro-to-diary gap must be a nonnegative sample count")


def _decode_initialization(document: dict[str, JsonValue]) -> LocalStudioInitialization:
    _require_fields(document, _INITIALIZATION_FIELDS, _INITIALIZATION_SCHEMA)
    return LocalStudioInitialization(
        _text(document["operator_display_label"], "operator display label"),
        _decode_profile(document["lane_b"]),
        _decode_profile(document["lane_c"]),
        _decode_budget(document["budget"]),
        _sample_count(document["default_passage_gap_samples"], "default passage gap"),
        _sample_count(document["default_intro_to_diary_gap_samples"], "default intro-to-diary gap"),
    )


def _decode_configuration(document: dict[str, JsonValue]) -> LocalStudioConfiguration:
    _require_fields(document, _CONFIGURATION_FIELDS, _CONFIGURATION_SCHEMA)
    return LocalStudioConfiguration(
        ActorId(document["actor_id"]),
        _text(document["operator_display_label"], "operator display label"),
        _decode_profile(document["lane_b"]),
        _decode_profile(document["lane_c"]),
        _decode_budget(document["budget"]),
        _sample_count(document["default_passage_gap_samples"], "default passage gap"),
        _sample_count(document["default_intro_to_diary_gap_samples"], "default intro-to-diary gap"),
    )


def _decode_profile(value: JsonValue) -> LocalStudioVoiceProfile:
    profile = _object(value, _PROFILE_FIELDS, "voice profile")
    dictionary_value = profile["dictionary_binding"]
    dictionary = None
    if dictionary_value is not None:
        item = _object(dictionary_value, _DICTIONARY_FIELDS, "dictionary binding")
        dictionary = DictionaryBinding(
            _text(item["opaque_reference"], "opaque dictionary reference"),
            ContentDigest("sha256", item["content_sha256"]),
            _text(item["revision"], "dictionary revision"),
            _text(item["capability_identity"], "dictionary capability identity"),
        )
    return LocalStudioVoiceProfile(
        _text(profile["display_label"], "profile display label"),
        _text(profile["speaker_identity"], "profile speaker identity"),
        _text(profile["opaque_provider_voice_reference"], "opaque provider voice reference"),
        dictionary,
    )


def _decode_budget(value: JsonValue) -> LocalStudioBudgetConfiguration:
    budget = _object(value, _BUDGET_FIELDS, "budget configuration")
    return LocalStudioBudgetConfiguration(
        _text(budget["project_id"], "budget project id"),
        _text(budget["billing_cycle_id"], "budget billing-cycle id"),
        _text(budget["usage_unit"], "budget usage unit"),
        NonNegativeDecimal(budget["per_take_cap"]),
        NonNegativeDecimal(budget["per_run_cap"]),
        NonNegativeDecimal(budget["project_cap"]),
        NonNegativeDecimal(budget["billing_cycle_cap"]),
    )


def _configuration_document(configuration: LocalStudioConfiguration) -> dict[str, JsonValue]:
    document = _initialization_document(_configuration_request(configuration))
    document["schema"] = _CONFIGURATION_SCHEMA
    document["actor_id"] = configuration.actor_id.value
    return document


def _initialization_document(request: LocalStudioInitialization) -> dict[str, JsonValue]:
    return {
        "schema": _INITIALIZATION_SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "operator_display_label": request.operator_display_label,
        "lane_b": _profile_document(request.lane_b),
        "lane_c": _profile_document(request.lane_c),
        "budget": {
            "project_id": request.budget.project_id,
            "billing_cycle_id": request.budget.billing_cycle_id,
            "usage_unit": request.budget.usage_unit,
            "per_take_cap": request.budget.per_take_cap.value,
            "per_run_cap": request.budget.per_run_cap.value,
            "project_cap": request.budget.project_cap.value,
            "billing_cycle_cap": request.budget.billing_cycle_cap.value,
        },
        "default_passage_gap_samples": request.default_passage_gap_samples,
        "default_intro_to_diary_gap_samples": request.default_intro_to_diary_gap_samples,
    }


def _profile_document(profile: LocalStudioVoiceProfile) -> dict[str, JsonValue]:
    dictionary: JsonValue = None
    if profile.dictionary_binding is not None:
        dictionary = {
            "opaque_reference": profile.dictionary_binding.opaque_reference,
            "content_sha256": profile.dictionary_binding.content_digest.hex_digest,
            "revision": profile.dictionary_binding.revision,
            "capability_identity": profile.dictionary_binding.capability_identity,
        }
    return {
        "display_label": profile.display_label,
        "speaker_identity": profile.speaker_identity,
        "opaque_provider_voice_reference": profile.opaque_provider_voice_reference,
        "dictionary_binding": dictionary,
    }


def _configuration_request(configuration: LocalStudioConfiguration) -> LocalStudioInitialization:
    return LocalStudioInitialization(
        configuration.operator_display_label,
        configuration.lane_b,
        configuration.lane_c,
        configuration.budget,
        configuration.default_passage_gap_samples,
        configuration.default_intro_to_diary_gap_samples,
    )


def _require_fields(
    document: dict[str, JsonValue],
    fields: set[str],
    schema: str,
) -> None:
    if set(document) != fields:
        raise ValidationError("private studio document has unknown or missing fields")
    schema_version = document["schema_version"]
    if (
        document["schema"] != schema
        or type(schema_version) is not int
        or schema_version != _SCHEMA_VERSION
    ):
        raise ValidationError("private studio document schema is not supported")


def _object(value: JsonValue, fields: set[str], name: str) -> dict[str, JsonValue]:
    if type(value) is not dict or set(value) != fields:
        raise ValidationError(f"{name} has unknown or missing fields")
    return value


def _text(value: object, name: str) -> str:
    return require_canonical_text(value, field=name, nonempty=True)


def _sample_count(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{name} must be a nonnegative sample count")
    return value


def _read_canonical_object(path: Path) -> tuple[dict[str, JsonValue], bytes]:
    _reject_reparse(path)
    try:
        if not path.is_file():
            raise ValidationError("JSON evidence must be a regular file")
        raw = path.read_bytes()
    except OSError as error:
        raise ValidationError("JSON evidence cannot be read") from error
    parsed = parse_strict_json(raw)
    if canonical_json(parsed) != raw or type(parsed) is not dict:
        raise ValidationError("JSON evidence must be one canonical object")
    return parsed, raw


def _external_file(path: str | Path, forbidden_roots: tuple[Path, ...]) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not os.path.lexists(candidate):
        raise ValidationError("initialization file must be an explicit existing absolute path")
    _reject_reparse_chain(candidate)
    try:
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValidationError("initialization file cannot be inspected") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValidationError("initialization file must be regular")
    _reject_forbidden(resolved, forbidden_roots)
    return resolved


def _external_directory(
    path: str | Path,
    forbidden_roots: tuple[Path, ...],
    *,
    require_empty: bool,
) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not os.path.lexists(candidate):
        raise ValidationError("operation directory must be an explicit existing absolute path")
    _reject_reparse_chain(candidate)
    try:
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValidationError("operation directory cannot be inspected") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValidationError("operation directory must be a regular directory")
    if resolved == Path(resolved.anchor):
        raise ValidationError("operation directory cannot be a filesystem root")
    _reject_forbidden(resolved, forbidden_roots)
    if require_empty:
        _require_empty(resolved)
    return resolved


def _reject_forbidden(path: Path, forbidden_roots: tuple[Path, ...]) -> None:
    for forbidden_root in forbidden_roots:
        forbidden = Path(forbidden_root).resolve(strict=False)
        if path == forbidden or path.is_relative_to(forbidden):
            raise ValidationError("operation path cannot be inside a forbidden root")


def _reject_overlap(first: Path, second: Path) -> None:
    if first == second or first.is_relative_to(second) or second.is_relative_to(first):
        raise ValidationError("operation source and destination cannot overlap")


def _require_empty(path: Path) -> None:
    try:
        if any(path.iterdir()):
            raise ValidationError("operation destination must be empty")
    except OSError as error:
        raise ValidationError("operation destination cannot be inspected") from error


def _require_root(root: object) -> None:
    if type(root) is not LocalNarrationRoot:
        raise ValidationError("operation requires a LocalNarrationRoot")


def _require_safe_directory(path: Path, name: str) -> None:
    if not os.path.lexists(path):
        raise ValidationError(f"{name} is missing")
    _reject_reparse(path)
    try:
        if not path.is_dir():
            raise ValidationError(f"{name} must be a directory")
    except OSError as error:
        raise ValidationError(f"{name} cannot be inspected") from error


def _reject_reparse_chain(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if os.path.lexists(current):
            _reject_reparse(current)


def _reject_reparse(path: Path) -> None:
    if not os.path.lexists(path):
        return
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValidationError("operation path cannot be inspected") from error
    if _metadata_is_reparse(metadata):
        raise ValidationError("operation path cannot be a reparse point")


def _metadata_is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _regular_tree_files(root: Path, excluded: set[str]) -> tuple[tuple[Path, str], ...]:
    found: list[tuple[Path, str]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = tuple(current.iterdir())
        except OSError as error:
            raise ValidationError("operation tree cannot be read") from error
        for path in children:
            relative = path.relative_to(root).as_posix()
            try:
                metadata = path.lstat()
            except OSError as error:
                raise ValidationError("operation tree entry cannot be inspected") from error
            if _metadata_is_reparse(metadata):
                raise ValidationError("operation tree cannot contain a reparse point")
            if stat.S_ISDIR(metadata.st_mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValidationError("operation tree cannot contain a special file")
            if relative in excluded:
                continue
            SafeRelativeArtifactPath(relative)
            found.append((path, relative))
    found.sort(key=lambda item: item[1].encode("utf-8"))
    return tuple(found)


def _copy_verified(source: Path, destination: Path) -> _BackupEntry:
    if os.path.lexists(destination):
        raise ValidationError("operation copy refuses to overwrite a destination")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse_chain(destination.parent)
        digest = hashlib.sha256()
        length = 0
        with source.open("rb") as reader, destination.open("xb") as writer:
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
                digest.update(chunk)
                length += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
    except OSError as error:
        raise ValidationError("operation file copy failed") from error
    evidence = _BackupEntry(
        destination.name,
        length,
        ContentDigest("sha256", digest.hexdigest()),
    )
    destination_digest, destination_length = _hash_file(destination)
    if destination_digest != evidence.digest or destination_length != evidence.byte_length:
        raise ValidationError("copied bytes do not match source evidence")
    return evidence


def _hash_file(path: Path) -> tuple[ContentDigest, int]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            length += len(chunk)
    return ContentDigest("sha256", digest.hexdigest()), length


def _manifest_document(entries: tuple[_BackupEntry, ...]) -> dict[str, JsonValue]:
    return {
        "schema": _BACKUP_SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "files": [
            {
                "path": entry.path,
                "byte_length": entry.byte_length,
                "sha256": entry.digest.hex_digest,
            }
            for entry in entries
        ],
    }


def _load_manifest(path: Path) -> tuple[tuple[_BackupEntry, ...], ContentDigest]:
    document, raw = _read_canonical_object(path)
    if set(document) != _MANIFEST_FIELDS:
        raise ValidationError("backup manifest has unknown or missing fields")
    schema_version = document["schema_version"]
    if (
        document["schema"] != _BACKUP_SCHEMA
        or type(schema_version) is not int
        or schema_version != _SCHEMA_VERSION
    ):
        raise ValidationError("backup manifest schema is not supported")
    values = document["files"]
    if type(values) is not list:
        raise ValidationError("backup manifest files must be an array")
    entries: list[_BackupEntry] = []
    for value in values:
        item = _object(value, _MANIFEST_ENTRY_FIELDS, "backup manifest entry")
        relative = _text(item["path"], "backup manifest path")
        SafeRelativeArtifactPath(relative)
        if relative in {".writer.lock", "backup-manifest.json"}:
            raise ValidationError("backup manifest contains a reserved path")
        byte_length = item["byte_length"]
        if type(byte_length) is not int or byte_length < 0:
            raise ValidationError("backup manifest byte length is invalid")
        entries.append(
            _BackupEntry(
                relative,
                byte_length,
                ContentDigest("sha256", item["sha256"]),
            )
        )
    paths = tuple(entry.path for entry in entries)
    if paths != tuple(sorted(paths, key=lambda item: item.encode("utf-8"))) or len(set(paths)) != len(paths):
        raise ValidationError("backup manifest paths must be unique and sorted")
    return tuple(entries), ContentDigest.from_bytes(raw)


def _json_is_operational_evidence(relative: Path) -> bool:
    return relative.suffix == ".json" and bool(relative.parts) and relative.parts[0] in {
        "aggregates",
        "attempts",
        "operations",
    }


def _check_aggregate_revisions(root: LocalNarrationRoot, issues: set[str]) -> None:
    if not os.path.lexists(root.aggregates):
        return
    try:
        directories = tuple(path for path in root.aggregates.rglob("revisions") if path.is_dir())
    except OSError:
        issues.add("path_unreadable")
        return
    for directory in directories:
        relative = directory.relative_to(root.path)
        if len(relative.parts) != 4 or relative.parts[0] != "aggregates":
            continue
        try:
            children = tuple(directory.iterdir())
        except OSError:
            issues.add("path_unreadable")
            continue
        revisions: list[int] = []
        for child in children:
            if not child.is_file() or _REVISION_FILE.fullmatch(child.name) is None:
                issues.add("revision_name_invalid")
                continue
            revision = int(child.stem)
            if revision < 1:
                issues.add("revision_name_invalid")
            else:
                revisions.append(revision)
        if revisions and sorted(revisions) != list(range(1, max(revisions) + 1)):
            issues.add("revision_gap")
