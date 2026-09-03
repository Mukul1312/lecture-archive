"""Restart-safe local safety ceilings for future paid generation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
import os
from pathlib import Path
import stat
from typing import Callable

from heritage_archive.kernel import (
    JsonValue,
    ValidationError,
    canonical_json,
    parse_strict_json,
    require_canonical_text,
)
from heritage_archive.platform.storage.local_files import (
    PublicationEvidenceMismatch,
    SingleWriterFileLock,
    replace_bytes_atomically,
)

from ..application.recovery import BudgetRecoveryState
from ..domain.errors import BudgetDenied
from ..domain.ids import BudgetReservationId, CommandId
from ..domain.values import NonNegativeDecimal
from .local_root import LocalNarrationRoot


_SCHEMA = "narrator_voice.generation_budget_ledger"
_SCHEMA_VERSION = 1
_DOCUMENT_FIELDS = {"schema", "schema_version", "scope", "caps", "facts"}
_SCOPE_FIELDS = {"project_id", "billing_cycle_id", "usage_unit"}
_CAP_FIELDS = {"per_take", "per_run", "project", "billing_cycle"}


@dataclass(frozen=True, slots=True)
class _Reservation:
    run_id: CommandId
    estimate: NonNegativeDecimal
    state: BudgetRecoveryState
    terminal_kind: str | None = None
    terminal_value: str | None = None

    @property
    def counted_usage(self) -> NonNegativeDecimal:
        if self.state is BudgetRecoveryState.RELEASED:
            return NonNegativeDecimal("0")
        if self.state is BudgetRecoveryState.SETTLED:
            return NonNegativeDecimal(self.terminal_value)
        return self.estimate


class FilesystemGenerationBudgetLedger:
    """One canonical operational ledger guarded by the application writer lock."""

    def __init__(
        self,
        root: LocalNarrationRoot,
        *,
        project_id: str,
        billing_cycle_id: str,
        usage_unit: str,
        per_take_cap: NonNegativeDecimal,
        per_run_cap: NonNegativeDecimal,
        project_cap: NonNegativeDecimal,
        billing_cycle_cap: NonNegativeDecimal,
    ) -> None:
        if type(root) is not LocalNarrationRoot:
            raise ValidationError("filesystem budget ledger requires a LocalNarrationRoot")
        self._root = root
        self._project_id = require_canonical_text(
            project_id, field="budget project id", nonempty=True
        )
        self._billing_cycle_id = require_canonical_text(
            billing_cycle_id, field="budget billing-cycle id", nonempty=True
        )
        self._usage_unit = require_canonical_text(
            usage_unit, field="budget usage unit", nonempty=True
        )
        caps = (per_take_cap, per_run_cap, project_cap, billing_cycle_cap)
        if any(type(cap) is not NonNegativeDecimal for cap in caps):
            raise ValidationError("budget caps must be exact NonNegativeDecimal values")
        self._per_take_cap, self._per_run_cap, self._project_cap, self._billing_cycle_cap = caps

    def reserve(
        self,
        reservation_id: BudgetReservationId,
        run_id: CommandId,
        estimated_usage: NonNegativeDecimal,
    ) -> None:
        if (
            type(reservation_id) is not BudgetReservationId
            or type(run_id) is not CommandId
            or type(estimated_usage) is not NonNegativeDecimal
        ):
            raise ValidationError("budget reserve requires exact reservation, run and usage values")

        def append(
            facts: list[JsonValue],
            reservations: dict[BudgetReservationId, _Reservation],
        ) -> bool:
            existing = reservations.get(reservation_id)
            if existing is not None:
                if existing.run_id == run_id and existing.estimate == estimated_usage:
                    return False
                raise ValidationError("budget reservation scope and estimated usage are immutable")
            self._enforce_caps(reservations, run_id, estimated_usage)
            facts.append(
                {
                    "kind": "reserve",
                    "reservation_id": reservation_id.value,
                    "run_id": run_id.value,
                    "usage": estimated_usage.value,
                }
            )
            return True

        self._mutate(append)

    def settle(
        self,
        reservation_id: BudgetReservationId,
        actual_usage: NonNegativeDecimal,
    ) -> None:
        if type(reservation_id) is not BudgetReservationId or type(actual_usage) is not NonNegativeDecimal:
            raise ValidationError("budget settlement requires exact reservation and usage values")
        self._finalize(reservation_id, "settle", actual_usage.value)

    def release(self, reservation_id: BudgetReservationId, reason: str) -> None:
        if type(reservation_id) is not BudgetReservationId:
            raise ValidationError("budget release requires an exact reservation identity")
        self._finalize(
            reservation_id,
            "release",
            require_canonical_text(reason, field="budget release reason", nonempty=True),
        )

    def hold(self, reservation_id: BudgetReservationId, reason: str) -> None:
        if type(reservation_id) is not BudgetReservationId:
            raise ValidationError("budget hold requires an exact reservation identity")
        self._finalize(
            reservation_id,
            "hold",
            require_canonical_text(reason, field="budget hold reason", nonempty=True),
        )

    def read(self, reservation_id: BudgetReservationId) -> BudgetRecoveryState:
        if type(reservation_id) is not BudgetReservationId:
            raise ValidationError("budget read requires an exact reservation identity")
        document = self._load_document(allow_missing=True)
        if document is None:
            return BudgetRecoveryState.UNKNOWN
        reservations = self._replay(document)
        found = reservations.get(reservation_id)
        return BudgetRecoveryState.UNKNOWN if found is None else found.state

    def _finalize(self, reservation_id: BudgetReservationId, kind: str, value: str) -> None:
        def append(
            facts: list[JsonValue],
            reservations: dict[BudgetReservationId, _Reservation],
        ) -> bool:
            existing = reservations.get(reservation_id)
            if existing is None:
                raise ValidationError("budget finalization requires an existing reservation")
            if existing.terminal_kind is not None:
                if existing.terminal_kind == kind and existing.terminal_value == value:
                    return False
                raise ValidationError("budget terminal facts are immutable")
            facts.append(
                {
                    "kind": kind,
                    "reservation_id": reservation_id.value,
                    "usage" if kind == "settle" else "reason": value,
                }
            )
            return True

        self._mutate(append)

    def _mutate(
        self,
        append: Callable[[list[JsonValue], dict[BudgetReservationId, _Reservation]], bool],
    ) -> None:
        path = self._ledger_path()
        with SingleWriterFileLock(self._root.writer_lock):
            document = self._load_document(allow_missing=True)
            if document is None:
                document = self._empty_document()
            reservations = self._replay(document)
            facts = document["facts"]
            if type(facts) is not list:
                raise ValidationError("budget ledger facts must be an array")
            if not append(facts, reservations):
                return
            payload = canonical_json(document)
            try:
                replace_bytes_atomically(self._root.staging, path, payload)
            except (OSError, PublicationEvidenceMismatch) as error:
                raise ValidationError("budget ledger could not be atomically replaced") from error

    def _load_document(self, *, allow_missing: bool) -> dict[str, JsonValue] | None:
        path = self._ledger_path()
        if not os.path.lexists(path):
            if allow_missing:
                return None
            raise ValidationError("budget ledger evidence is missing")
        _reject_reparse_point(path)
        try:
            if not path.is_file():
                raise ValidationError("budget ledger must be a regular file")
            raw = path.read_bytes()
            parsed = parse_strict_json(raw)
        except OSError as error:
            raise ValidationError("budget ledger evidence cannot be read") from error
        if canonical_json(parsed) != raw:
            raise ValidationError("budget ledger bytes are not canonical JSON")
        if type(parsed) is not dict:
            raise ValidationError("budget ledger must be a JSON object")
        self._validate_header(parsed)
        return parsed

    def _validate_header(self, document: dict[str, JsonValue]) -> None:
        if set(document) != _DOCUMENT_FIELDS:
            raise ValidationError("budget ledger has unknown or missing document fields")
        if document["schema"] != _SCHEMA or document["schema_version"] != _SCHEMA_VERSION:
            raise ValidationError("budget ledger schema is not supported")
        scope = document["scope"]
        caps = document["caps"]
        facts = document["facts"]
        if type(scope) is not dict or set(scope) != _SCOPE_FIELDS:
            raise ValidationError("budget ledger scope is invalid")
        if type(caps) is not dict or set(caps) != _CAP_FIELDS:
            raise ValidationError("budget ledger caps are invalid")
        if type(facts) is not list:
            raise ValidationError("budget ledger facts must be an array")
        expected_scope = self._scope_document()
        expected_caps = self._caps_document()
        if scope != expected_scope or caps != expected_caps:
            raise ValidationError("budget ledger configuration does not match this adapter")
        for value in caps.values():
            NonNegativeDecimal(value)

    def _replay(
        self,
        document: dict[str, JsonValue],
    ) -> dict[BudgetReservationId, _Reservation]:
        self._validate_header(document)
        reservations: dict[BudgetReservationId, _Reservation] = {}
        facts = document["facts"]
        assert type(facts) is list
        for fact in facts:
            if type(fact) is not dict or type(fact.get("kind")) is not str:
                raise ValidationError("budget ledger fact is invalid")
            kind = fact["kind"]
            if kind == "reserve":
                if set(fact) != {"kind", "reservation_id", "run_id", "usage"}:
                    raise ValidationError("budget reserve fact has unknown or missing fields")
                reservation_id = BudgetReservationId(fact["reservation_id"])
                if reservation_id in reservations:
                    raise ValidationError("budget reservation has duplicate reserve facts")
                run_id = CommandId(fact["run_id"])
                usage = NonNegativeDecimal(fact["usage"])
                self._enforce_caps(reservations, run_id, usage)
                reservations[reservation_id] = _Reservation(
                    run_id, usage, BudgetRecoveryState.RESERVED
                )
                continue
            if kind not in {"settle", "release", "hold"}:
                raise ValidationError("budget ledger fact kind is not supported")
            value_field = "usage" if kind == "settle" else "reason"
            if set(fact) != {"kind", "reservation_id", value_field}:
                raise ValidationError("budget terminal fact has unknown or missing fields")
            reservation_id = BudgetReservationId(fact["reservation_id"])
            existing = reservations.get(reservation_id)
            if existing is None or existing.terminal_kind is not None:
                raise ValidationError("budget terminal fact does not follow one open reservation")
            value = fact[value_field]
            if kind == "settle":
                value = NonNegativeDecimal(value).value
                state = BudgetRecoveryState.SETTLED
            else:
                value = require_canonical_text(
                    value, field=f"budget {kind} reason", nonempty=True
                )
                state = (
                    BudgetRecoveryState.RELEASED
                    if kind == "release"
                    else BudgetRecoveryState.UNKNOWN
                )
            reservations[reservation_id] = _Reservation(
                existing.run_id,
                existing.estimate,
                state,
                kind,
                value,
            )
        return reservations

    def _enforce_caps(
        self,
        reservations: dict[BudgetReservationId, _Reservation],
        run_id: CommandId,
        estimate: NonNegativeDecimal,
    ) -> None:
        if _decimal(estimate) > _decimal(self._per_take_cap):
            raise BudgetDenied("generation estimate exceeds the configured per-take cap")
        run_values = [
            reservation.counted_usage
            for reservation in reservations.values()
            if reservation.run_id == run_id
        ]
        if _sum_decimal((*run_values, estimate)) > _decimal(self._per_run_cap):
            raise BudgetDenied("generation estimate exceeds the configured per-run cap")
        all_values = [reservation.counted_usage for reservation in reservations.values()]
        projected = _sum_decimal((*all_values, estimate))
        if projected > _decimal(self._project_cap):
            raise BudgetDenied("generation estimate exceeds the configured project cap")
        if projected > _decimal(self._billing_cycle_cap):
            raise BudgetDenied("generation estimate exceeds the configured billing-cycle cap")

    def _empty_document(self) -> dict[str, JsonValue]:
        return {
            "schema": _SCHEMA,
            "schema_version": _SCHEMA_VERSION,
            "scope": self._scope_document(),
            "caps": self._caps_document(),
            "facts": [],
        }

    def _scope_document(self) -> dict[str, JsonValue]:
        return {
            "project_id": self._project_id,
            "billing_cycle_id": self._billing_cycle_id,
            "usage_unit": self._usage_unit,
        }

    def _caps_document(self) -> dict[str, JsonValue]:
        return {
            "per_take": self._per_take_cap.value,
            "per_run": self._per_run_cap.value,
            "project": self._project_cap.value,
            "billing_cycle": self._billing_cycle_cap.value,
        }

    def _ledger_path(self) -> Path:
        _require_safe_directory(self._root.operations, "budget operations directory")
        _require_safe_directory(self._root.staging, "budget staging directory")
        path = self._root.operations / "budget-ledger.json"
        _reject_reparse_point(path)
        return path


def _decimal(value: NonNegativeDecimal) -> Decimal:
    return Decimal(value.value)


def _sum_decimal(values: tuple[NonNegativeDecimal, ...]) -> Decimal:
    if not values:
        return Decimal(0)
    precision = sum(len(item.value.replace(".", "")) for item in values) + len(values) + 1
    with localcontext() as context:
        context.prec = max(precision, 1)
        return sum((_decimal(item) for item in values), Decimal(0))


def _require_safe_directory(path: Path, field: str) -> None:
    if not os.path.lexists(path):
        raise ValidationError(f"{field} is missing")
    _reject_reparse_point(path)
    try:
        if not path.is_dir():
            raise ValidationError(f"{field} must be a directory")
    except OSError as error:
        raise ValidationError(f"{field} cannot be inspected") from error


def _reject_reparse_point(path: Path) -> None:
    if not os.path.lexists(path):
        return
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValidationError("budget ledger path cannot be inspected") from error
    attributes = getattr(metadata, "st_file_attributes", 0)
    if stat.S_ISLNK(metadata.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValidationError("budget ledger path cannot be a reparse point")
