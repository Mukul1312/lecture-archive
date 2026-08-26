"""run_operation: the one idempotent, transactional path every handler uses.

Design 9.4 fixes the semantics: repeating an identical completed operation
returns the original result; repeating an operation id with different inputs
is rejected. Design 9.3 fixes the transaction: one aggregate root, and the
operation record becomes durable with the state it describes or not at all,
which is why the record is written inside the unit of work before commit.

A replay is verified, never trusted: the handler's `rederive` rebuilds the
result from stored state, and its digest must equal the recorded one. Stored
state that can no longer reproduce a recorded result is corruption, and
fails closed rather than returning a plausible answer.

Two limits of that verification, both deliberate and both the handler's to
manage:

* Only the result *payload* is checked, so verification reaches exactly as
  far as the payload projects the value. An aggregate whose unprojected
  state has drifted replays clean. Handlers should therefore project the
  state a caller depends on, not merely an identity.
* `rederive` runs outside the unit of work. Against a real SQLite adapter
  each read then gets its own snapshot, so a multi-table rederive can
  compare a torn read against the recorded digest. Task 7 should give the
  replay path a read transaction; the fakes cannot express the difference,
  so no test here would catch it.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.shared import ValidationError

from .errors import OperationConflictError, ReplayIntegrityError
from .idempotency import command_input_digest, command_name, command_result_digest
from .ports.infrastructure import OperationRecord


@dataclass(frozen=True, slots=True)
class OperationResult:
    """What a handler produces: a rich value and its canonical manifest."""

    value: object
    payload: dict

    def __post_init__(self) -> None:
        if type(self.payload) is not dict:
            raise ValidationError("a result payload must be a JSON object")


@dataclass(frozen=True, slots=True)
class CompletedOperation:
    record: OperationRecord
    result: object
    replayed: bool


def _require_operation_result(candidate: object, *, source: str) -> OperationResult:
    if type(candidate) is not OperationResult:
        raise ValidationError(f"{source} must return an OperationResult")
    return candidate


def run_operation(
    command: object,
    *,
    recorder,
    unit_of_work,
    clock,
    execute,
    rederive,
    prepare=None,
) -> CompletedOperation:
    name = command_name(command)
    input_digest = command_input_digest(command)
    existing = recorder.find(command.operation_id)
    if existing is not None:
        return _replay(command, name, input_digest, existing, rederive)
    if prepare is not None:
        # Artifact promotion and validation precede the one-root transaction,
        # so a rejected artifact never opens one and a real adapter never
        # holds a write lock across file I/O. It runs after the replay check
        # rather than before it: a completed operation must still return its
        # original result even if the artifact it validated has since gone.
        prepare()
    with unit_of_work as active:
        # `execute` deliberately takes no arguments. A handler that could
        # reach the transaction could commit it, making aggregate state
        # durable before the operation record exists -- after which the same
        # operation id finds no record and runs the handler a second time.
        # Withholding the transaction removes the capability rather than
        # detecting its misuse once the damage is already durable.
        produced = _require_operation_result(execute(), source="execute")
        # The clock's value is validated by OperationRecord itself, which is
        # where it becomes durable; re-checking it here would be a second copy
        # of one rule that no test could distinguish.
        record = OperationRecord(
            operation_id=command.operation_id,
            command_name=name,
            input_digest=input_digest,
            result_digest=command_result_digest(command, produced.payload),
            result_payload=produced.payload,
            completed_at_us=clock.now_us(),
        )
        recorder.record(record, transaction=active)
        active.commit()
    return CompletedOperation(record=record, result=produced.value, replayed=False)


def _replay(
    command: object,
    name: str,
    input_digest,
    existing: object,
    rederive,
) -> CompletedOperation:
    if type(existing) is not OperationRecord:
        raise ValidationError("the operation recorder returned a non-record")
    if existing.operation_id != command.operation_id:
        raise ReplayIntegrityError(
            "the recorder returned a record for another operation"
        )
    if existing.command_name != name:
        raise OperationConflictError(
            "this operation id was completed by a different command"
        )
    if existing.input_digest != input_digest:
        raise OperationConflictError(
            "this operation id was completed with different inputs"
        )
    # The record must be internally consistent before its payload is used to
    # find anything: a payload edited in storage would otherwise steer the
    # rederive to whatever root the editor chose.
    if command_result_digest(command, existing.result_payload) != existing.result_digest:
        raise ReplayIntegrityError("the stored operation record is internally inconsistent")
    replayed = _require_operation_result(rederive(existing), source="rederive")
    if command_result_digest(command, replayed.payload) != existing.result_digest:
        raise ReplayIntegrityError(
            "stored state no longer reproduces the recorded result"
        )
    return CompletedOperation(record=existing, result=replayed.value, replayed=True)
