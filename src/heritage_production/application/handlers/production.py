"""Handlers for the commands that write the `Production` aggregate root.

Every handler is the same three-part shape, and later handlers should copy it:

* `execute` does the work inside the one transaction. It takes no arguments,
  so it cannot commit -- `run_operation` owns that.
* `rederive` rebuilds the result from stored state on a replay, so a repeated
  operation returns the original result without doing the work twice.
* the payload is the canonical projection of the result. Replay verification
  reaches exactly as far as the payload does, so it carries the state a
  caller depends on rather than an identity alone.

`CreateProduction` is the case that shapes the rest. Design 9.1 gives it no
input ID -- its *result* is the Production ID -- so identity is generated
here, and a replay recovers it from the stored record rather than issuing a
new one.
"""

from __future__ import annotations

from heritage_production.domain.production import Production
from heritage_production.domain.shared import (
    DomainEventId,
    ProductionId,
    StaleReferenceError,
)

from ..commands.production import AttachSourceRecording, CreateProduction
from ..execution import CompletedOperation, OperationResult, run_operation


def _production_payload(production: Production, version: int) -> dict:
    """The canonical projection of a Production write.

    `lifecycle_phase` is included deliberately. A payload of identity alone
    would let an aggregate whose phase had drifted replay clean, because
    replay verification only checks what the payload projects.
    """
    return {
        "production_id": production.production_id.value,
        "version": version,
        "lifecycle_phase": production.lifecycle_phase,
        "source_count": len(production.sources),
    }


class ProductionCommandHandlers:
    """One instance per wiring; every method is one idempotent operation."""

    def __init__(
        self,
        *,
        productions,
        transactions,
        recorder,
        events,
        clock,
        ids,
    ) -> None:
        self._productions = productions
        self._transactions = transactions
        self._recorder = recorder
        self._events = events
        self._clock = clock
        self._ids = ids

    def _publish(self, root) -> None:
        """Drain the aggregate into the outbox inside the same transaction.

        Events left on the root would never be delivered, so this must run
        for every write, and it must run before the transaction commits
        (design 9.6).
        """
        for event in root.pull_events():
            self._events.enqueue(event)

    def _run(self, command, *, execute, rederive) -> CompletedOperation:
        return run_operation(
            command,
            recorder=self._recorder,
            unit_of_work=self._transactions(),
            clock=self._clock,
            execute=execute,
            rederive=rederive,
        )

    def _reload(self, record) -> OperationResult:
        stored = self._productions.load(
            ProductionId(record.result_payload["production_id"])
        )
        return OperationResult(
            value=stored.root,
            payload=_production_payload(stored.root, stored.version),
        )

    def create_production(self, command: CreateProduction) -> CompletedOperation:
        def execute() -> OperationResult:
            production = Production.create(
                production_id=ProductionId(self._ids.new_id()),
                intended_deliverable=command.intended_deliverable,
                steward_actor_id=command.actor.actor_id,
                created_at_us=self._clock.now_us(),
                event_id=DomainEventId(self._ids.new_id()),
                event_occurred_at_us=self._clock.now_us(),
            )
            version = self._productions.save(production, expected_version=0)
            self._publish(production)
            return OperationResult(
                value=production, payload=_production_payload(production, version)
            )

        return self._run(command, execute=execute, rederive=self._reload)

    def attach_source_recording(
        self, command: AttachSourceRecording
    ) -> CompletedOperation:
        def execute() -> OperationResult:
            loaded = self._productions.load(command.production_id)
            # Checked before the aggregate is touched. Saving would catch the
            # conflict too, but only after an in-memory mutation that the
            # caller could mistake for a partial success.
            if loaded.version != command.expected_version:
                raise StaleReferenceError(
                    "this Production has moved since the expected version"
                )
            attached = loaded.root.attach_source(
                attached_source=command.attached_source,
                event_id=DomainEventId(self._ids.new_id()),
                event_occurred_at_us=self._clock.now_us(),
            )
            version = self._productions.save(
                loaded.root, expected_version=command.expected_version
            )
            self._publish(loaded.root)
            return OperationResult(
                value=attached, payload=_production_payload(loaded.root, version)
            )

        def rederive(record) -> OperationResult:
            reloaded = self._reload(record)
            # The command names the exact source it attached, so the replay
            # returns that member rather than the aggregate.
            identity = command.attached_source.source_version_ref
            for source in reloaded.value.sources:
                if source.source_version_ref == identity:
                    return OperationResult(value=source, payload=reloaded.payload)
            raise StaleReferenceError(
                "the recorded attachment is no longer present on this Production"
            )

        return self._run(command, execute=execute, rederive=rederive)


__all__ = ["ProductionCommandHandlers"]
