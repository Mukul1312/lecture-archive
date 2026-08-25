"""run_operation: the one idempotent, transactional path every handler uses.

Design 9.4: repeating an identical completed operation returns the original
result; repeating an operation id with different inputs is rejected. Design
9.3: one transaction changes one aggregate root, and nothing becomes durable
when any step fails. The fakes model SQLite's serialized writers, so every
assertion here is a contract the Task 7 adapters must also satisfy.
"""

from __future__ import annotations

import dataclasses
import unittest

from heritage_production.application import commands
from heritage_production.application.errors import (
    OperationConflictError,
    ReplayIntegrityError,
    TransactionRuleError,
)
from heritage_production.application.execution import (
    CompletedOperation,
    OperationResult,
    run_operation,
)
from heritage_production.application.idempotency import (
    command_input_digest,
    command_result_digest,
)
from heritage_production.application.ports.adapters import ActorAuthority
from heritage_production.application.ports.infrastructure import (
    Clock,
    OperationRecord,
    OperationRecorder,
    UnitOfWork,
)
from heritage_production.application.ports.repositories import (
    ASRProposalSetRepository,
    ProductionRepository,
    ReleasePolicyVersionRepository,
    ReviewFindingRepository,
    ReviewRoundRepository,
    TranscriptEditionRepository,
)
from heritage_production.domain.shared import (
    InvariantError,
    OperationId,
    StaleReferenceError,
    ValidationError,
)

from tests.heritage_production.application_fakes import (
    FakeASRProposalSetRepository,
    FakeClock,
    FakeDatabase,
    FakeOperationRecorder,
    FakeProductionRepository,
    FakeReleasePolicyVersionRepository,
    FakeReviewFindingRepository,
    FakeReviewRoundRepository,
    FakeTranscriptEditionRepository,
    FakeUnitOfWork,
    sample_policy,
    sample_production,
)
from tests.heritage_production.heritage_release_fixtures import actor, digest, uid


def create_production_command(
    suffix: int = 1, deliverable: str = "August 21 listening transcript"
) -> commands.CreateProduction:
    return commands.CreateProduction(
        operation_id=OperationId(uid(suffix)),
        actor=commands.ActorContext(actor(20)),
        intended_deliverable=deliverable,
    )


class Scenario:
    def __init__(self) -> None:
        self.database = FakeDatabase()
        self.recorder = FakeOperationRecorder(self.database)
        self.productions = FakeProductionRepository(self.database)
        self.policies = FakeReleasePolicyVersionRepository(self.database)
        self.clock = FakeClock()

    def unit_of_work(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.database)

    def execute_create(self) -> OperationResult:
        production = sample_production()
        version = self.productions.save(production, expected_version=0)
        return OperationResult(
            value=production,
            payload={"production_id": production.production_id.value, "version": version},
        )

    def run(self, command, *, execute=None, rederive=None, unit_of_work=None):
        return run_operation(
            command,
            recorder=self.recorder,
            unit_of_work=unit_of_work if unit_of_work is not None else self.unit_of_work(),
            clock=self.clock,
            execute=execute if execute is not None else self.execute_create,
            rederive=rederive if rederive is not None else _never_rederive,
        )


def _never_rederive(record: OperationRecord) -> OperationResult:
    raise AssertionError("rederive must not run for a fresh operation")


def _never_execute() -> OperationResult:
    raise AssertionError("execute must not run for a replayed operation")


class FreshExecutionTests(unittest.TestCase):
    def test_a_fresh_operation_commits_state_and_record_together(self) -> None:
        scenario = Scenario()
        command = create_production_command()

        outcome = scenario.run(command)

        self.assertIsInstance(outcome, CompletedOperation)
        self.assertFalse(outcome.replayed)
        self.assertEqual(len(scenario.productions.rows), 1)
        record = scenario.recorder.records[command.operation_id]
        self.assertEqual(outcome.record, record)
        self.assertEqual(record.command_name, "CreateProduction")
        self.assertEqual(record.input_digest, command_input_digest(command))
        self.assertEqual(
            record.result_digest,
            command_result_digest(
                command,
                {
                    "production_id": outcome.result.production_id.value,
                    "version": 1,
                },
            ),
        )
        self.assertEqual(record.completed_at_us, 1_700_000_000_500_000)
        self.assertEqual(scenario.clock.calls, 1)

    def test_the_returned_result_is_the_handler_value(self) -> None:
        scenario = Scenario()

        outcome = scenario.run(create_production_command())

        (stored_root, stored_version) = next(iter(scenario.productions.rows.values()))
        self.assertIs(outcome.result, stored_root)
        self.assertEqual(stored_version, 1)

    def test_a_failing_handler_leaves_nothing_durable(self) -> None:
        scenario = Scenario()

        def failing_execute():
            scenario.productions.save(sample_production(), expected_version=0)
            raise InvariantError("the deliverable is refused")

        unit_of_work = scenario.unit_of_work()
        with self.assertRaises(InvariantError):
            scenario.run(
                create_production_command(),
                execute=failing_execute,
                unit_of_work=unit_of_work,
            )

        self.assertEqual(scenario.productions.rows, {})
        self.assertEqual(scenario.recorder.records, {})
        self.assertEqual(unit_of_work.rollbacks, 1)
        self.assertEqual(unit_of_work.commits, 0)

    def test_a_failing_commit_leaves_nothing_durable(self) -> None:
        scenario = Scenario()
        unit_of_work = scenario.unit_of_work()
        unit_of_work.commit_failure = RuntimeError("disk full")

        with self.assertRaises(RuntimeError):
            scenario.run(create_production_command(), unit_of_work=unit_of_work)

        self.assertEqual(scenario.productions.rows, {})
        self.assertEqual(scenario.recorder.records, {})

    def test_a_handler_result_that_is_not_an_operation_result_is_rejected(self) -> None:
        scenario = Scenario()

        with self.assertRaises(ValidationError):
            scenario.run(
                create_production_command(), execute=lambda: "done"
            )

        self.assertEqual(scenario.productions.rows, {})
        self.assertEqual(scenario.recorder.records, {})

    def test_a_handler_is_never_handed_the_transaction(self) -> None:
        """A handler that could commit could make aggregate state durable
        before the operation record existed; the same operation id would then
        find no record and run the handler a second time. `execute` takes no
        arguments, so the capability does not exist to misuse."""
        scenario = Scenario()
        received: list = []

        def recording_execute(*args, **kwargs):
            received.append((args, kwargs))
            return scenario.execute_create()

        scenario.run(create_production_command(), execute=recording_execute)

        self.assertEqual(received, [((), {})])

    def test_a_broken_clock_is_rejected_before_anything_commits(self) -> None:
        """Both halves of the guard: a non-positive time and a non-int time.

        Testing only `0` leaves the exact-type half unexercised, and a float
        would then be written into a durable record -- `OperationRecord` does
        no validation of its own.
        """
        for name, value in (
            ("zero", 0),
            ("negative", -1),
            ("float", 1.5),
            ("bool", True),
            ("string", "1700000000500000"),
        ):
            with self.subTest(clock=name):
                scenario = Scenario()

                class BrokenClock:
                    def now_us(self):
                        return value

                with self.assertRaises(ValidationError):
                    run_operation(
                        create_production_command(),
                        recorder=scenario.recorder,
                        unit_of_work=scenario.unit_of_work(),
                        clock=BrokenClock(),
                        execute=scenario.execute_create,
                        rederive=_never_rederive,
                    )

                self.assertEqual(scenario.productions.rows, {})
                self.assertEqual(scenario.recorder.records, {})

    def test_a_twin_record_written_during_execution_forces_rollback(self) -> None:
        """Another process completing the same operation id wins."""
        scenario = Scenario()
        command = create_production_command()
        twin = OperationRecord(
            operation_id=command.operation_id,
            command_name="CreateProduction",
            input_digest=command_input_digest(command),
            result_digest=digest("a"),
            completed_at_us=5,
        )

        def racing_execute():
            result = scenario.execute_create()
            scenario.recorder.records[command.operation_id] = twin
            return result

        with self.assertRaises(OperationConflictError):
            scenario.run(command, execute=racing_execute)

        self.assertEqual(scenario.productions.rows, {})
        self.assertEqual(scenario.recorder.records, {command.operation_id: twin})


class ReplayTests(unittest.TestCase):
    def replayed_scenario(self) -> tuple[Scenario, commands.CreateProduction, CompletedOperation]:
        scenario = Scenario()
        command = create_production_command()
        first = scenario.run(command)
        return scenario, command, first

    def test_an_identical_replay_returns_the_original_record(self) -> None:
        scenario, command, first = self.replayed_scenario()

        def rederive(record: OperationRecord) -> OperationResult:
            (root, version) = scenario.productions.rows[first.result.production_id]
            return OperationResult(
                value=root,
                payload={"production_id": root.production_id.value, "version": version},
            )

        unit_of_work = scenario.unit_of_work()
        outcome = scenario.run(
            command, execute=_never_execute, rederive=rederive, unit_of_work=unit_of_work
        )

        self.assertTrue(outcome.replayed)
        self.assertEqual(outcome.record, first.record)
        self.assertIs(outcome.result, first.result)
        self.assertFalse(unit_of_work.entered)
        self.assertEqual(scenario.clock.calls, 1)
        self.assertEqual(len(scenario.productions.rows), 1)

    def test_a_changed_input_under_the_same_operation_id_is_a_conflict(self) -> None:
        scenario, command, _ = self.replayed_scenario()
        changed = dataclasses.replace(
            command, intended_deliverable="August 22 listening transcript"
        )

        unit_of_work = scenario.unit_of_work()
        with self.assertRaises(OperationConflictError):
            scenario.run(changed, execute=_never_execute, unit_of_work=unit_of_work)

        self.assertFalse(unit_of_work.entered)
        self.assertEqual(len(scenario.productions.rows), 1)
        self.assertEqual(len(scenario.recorder.records), 1)

    def test_a_record_forged_under_another_command_name_is_a_conflict(self) -> None:
        scenario = Scenario()
        command = create_production_command()
        scenario.recorder.records[command.operation_id] = OperationRecord(
            operation_id=command.operation_id,
            command_name="SelectCandidateEdition",
            input_digest=command_input_digest(command),
            result_digest=digest("a"),
            completed_at_us=5,
        )

        with self.assertRaises(OperationConflictError):
            scenario.run(command, execute=_never_execute)

    def test_a_record_stored_under_the_wrong_operation_id_fails_closed(self) -> None:
        scenario = Scenario()
        command = create_production_command(suffix=1)
        foreign = create_production_command(suffix=7)
        scenario.recorder.records[command.operation_id] = OperationRecord(
            operation_id=foreign.operation_id,
            command_name="CreateProduction",
            input_digest=command_input_digest(command),
            result_digest=digest("a"),
            completed_at_us=5,
        )

        with self.assertRaises(ReplayIntegrityError):
            scenario.run(command, execute=_never_execute)

    def test_a_recorder_returning_garbage_fails_closed(self) -> None:
        scenario = Scenario()
        command = create_production_command()
        scenario.recorder.records[command.operation_id] = "garbage"

        with self.assertRaises(ValidationError):
            scenario.run(command, execute=_never_execute)

    def test_a_rederived_result_that_no_longer_matches_fails_closed(self) -> None:
        scenario, command, _ = self.replayed_scenario()

        def drifted(record: OperationRecord) -> OperationResult:
            return OperationResult(value=None, payload={"production_id": uid(99)})

        with self.assertRaises(ReplayIntegrityError):
            scenario.run(command, execute=_never_execute, rederive=drifted)

    def test_a_rederive_that_returns_garbage_fails_closed(self) -> None:
        scenario, command, _ = self.replayed_scenario()

        with self.assertRaises(ValidationError):
            scenario.run(
                command, execute=_never_execute, rederive=lambda record: "done"
            )


class OperationResultTests(unittest.TestCase):
    def test_the_payload_must_be_a_json_object(self) -> None:
        for bad in (None, "done", 7, [1], (1,)):
            with self.subTest(payload=bad):
                with self.assertRaises(ValidationError):
                    OperationResult(value=None, payload=bad)

    def test_the_value_may_be_anything_including_none(self) -> None:
        result = OperationResult(value=None, payload={"outcome": "recorded"})

        self.assertIsNone(result.value)


class TransactionContractTests(unittest.TestCase):
    """The fake models the rules the Task 7 SQLite adapters must satisfy."""

    def setUp(self) -> None:
        self.database = FakeDatabase()
        self.recorder = FakeOperationRecorder(self.database)
        self.productions = FakeProductionRepository(self.database)
        self.policies = FakeReleasePolicyVersionRepository(self.database)

    def test_a_write_outside_a_transaction_is_refused(self) -> None:
        with self.assertRaises(TransactionRuleError):
            self.productions.save(sample_production(), expected_version=0)

    def test_one_transaction_cannot_write_two_aggregate_roots(self) -> None:
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.productions.save(sample_production(), expected_version=0)
            with self.assertRaises(TransactionRuleError):
                self.policies.add(sample_policy())
            unit_of_work.rollback()

    def test_saving_one_root_twice_at_the_same_version_conflicts(self) -> None:
        """A real `UPDATE ... WHERE version = ?` matches zero rows the second
        time. The fake must agree, or it blesses a handler that breaks in
        Task 7."""
        production = sample_production()
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.productions.save(production, expected_version=0)
            with self.assertRaises(StaleReferenceError):
                self.productions.save(production, expected_version=0)
            unit_of_work.rollback()

    def test_a_second_save_must_expect_the_version_the_first_produced(self) -> None:
        production = sample_production()
        with FakeUnitOfWork(self.database) as unit_of_work:
            first = self.productions.save(production, expected_version=0)
            second = self.productions.save(production, expected_version=first)
            unit_of_work.commit()

        self.assertEqual((first, second), (1, 2))
        self.assertEqual(self.productions.rows[production.production_id][1], 2)

    def test_a_rolled_back_save_leaves_no_pending_version_behind(self) -> None:
        """Pending state must not leak into the next transaction."""
        production = sample_production()
        with FakeUnitOfWork(self.database):
            self.productions.save(production, expected_version=0)

        with FakeUnitOfWork(self.database) as unit_of_work:
            self.assertEqual(self.productions.save(production, expected_version=0), 1)
            unit_of_work.commit()

    def test_an_operation_record_is_not_an_aggregate_root_write(self) -> None:
        production = sample_production()
        record = OperationRecord(
            operation_id=OperationId(uid(1)),
            command_name="CreateProduction",
            input_digest=digest("b"),
            result_digest=digest("c"),
            completed_at_us=5,
        )
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.productions.save(production, expected_version=0)
            self.recorder.record(record, transaction=unit_of_work)
            unit_of_work.commit()

        self.assertIn(production.production_id, self.productions.rows)
        self.assertIn(record.operation_id, self.recorder.records)

    def test_exiting_without_commit_rolls_back(self) -> None:
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.productions.save(sample_production(), expected_version=0)

        self.assertEqual(self.productions.rows, {})
        self.assertEqual(unit_of_work.rollbacks, 1)

    def test_a_unit_of_work_is_single_use(self) -> None:
        unit_of_work = FakeUnitOfWork(self.database)
        with unit_of_work:
            unit_of_work.commit()

        with self.assertRaises(TransactionRuleError):
            unit_of_work.__enter__()

    def test_commit_requires_an_active_transaction(self) -> None:
        with self.assertRaises(TransactionRuleError):
            FakeUnitOfWork(self.database).commit()

    def test_writers_are_serialized(self) -> None:
        with FakeUnitOfWork(self.database):
            with self.assertRaises(TransactionRuleError):
                FakeUnitOfWork(self.database).__enter__()

    def test_a_stale_expected_version_is_refused_at_save(self) -> None:
        production = sample_production()
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.productions.save(production, expected_version=0)
            unit_of_work.commit()

        with FakeUnitOfWork(self.database):
            with self.assertRaises(StaleReferenceError):
                self.productions.save(production, expected_version=0)

    def test_a_version_that_moved_before_commit_is_refused_at_commit(self) -> None:
        production = sample_production()
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.productions.save(production, expected_version=0)
            self.productions.rows[production.production_id] = (production, 99)
            with self.assertRaises(StaleReferenceError):
                unit_of_work.commit()

        self.assertEqual(self.productions.rows[production.production_id][1], 99)

    def test_a_missing_mutable_root_fails_closed_on_load(self) -> None:
        with self.assertRaises(StaleReferenceError):
            self.productions.load(sample_production().production_id)

    def test_a_sealed_root_is_added_once(self) -> None:
        policy = sample_policy()
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.policies.add(policy)
            unit_of_work.commit()

        self.assertIs(self.policies.get(policy.release_policy_version_id), policy)
        with FakeUnitOfWork(self.database):
            with self.assertRaises(InvariantError):
                self.policies.add(policy)

    def test_a_sealed_root_added_concurrently_is_refused_at_commit(self) -> None:
        policy = sample_policy()
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.policies.add(policy)
            self.policies.rows[policy.release_policy_version_id] = policy
            with self.assertRaises(InvariantError):
                unit_of_work.commit()

    def test_a_missing_sealed_root_fails_closed_on_get(self) -> None:
        with self.assertRaises(StaleReferenceError):
            self.policies.get(sample_policy().release_policy_version_id)

    def test_repositories_take_exactly_their_own_root_type(self) -> None:
        with FakeUnitOfWork(self.database) as unit_of_work:
            with self.assertRaises(ValidationError):
                self.productions.save(sample_policy(), expected_version=0)
            with self.assertRaises(ValidationError):
                self.policies.add(sample_production())
            unit_of_work.rollback()

    def test_expected_version_must_be_a_nonnegative_integer(self) -> None:
        with FakeUnitOfWork(self.database) as unit_of_work:
            for bad in ("0", -1, None, 1.0, True):
                with self.subTest(expected_version=bad):
                    with self.assertRaises(ValidationError):
                        self.productions.save(
                            sample_production(), expected_version=bad
                        )
            unit_of_work.rollback()

    def test_the_recorder_refuses_a_foreign_transaction(self) -> None:
        """Design 9.4 wants the record durable with the state it describes.

        A Task 7 recorder holding its own connection would satisfy the port
        signature by ignoring the handle, so the fake asserts the handle is
        the transaction the aggregate write is in.
        """
        record = OperationRecord(
            operation_id=OperationId(uid(1)),
            command_name="CreateProduction",
            input_digest=digest("b"),
            result_digest=digest("c"),
            completed_at_us=5,
        )
        with FakeUnitOfWork(self.database) as unit_of_work:
            for name, foreign in (
                ("none", None),
                ("other", FakeUnitOfWork(self.database)),
                ("string", "the transaction"),
            ):
                with self.subTest(transaction=name):
                    with self.assertRaises(TransactionRuleError):
                        self.recorder.record(record, transaction=foreign)
            unit_of_work.rollback()

        self.assertEqual(self.recorder.records, {})

    def test_a_duplicate_operation_id_is_refused_when_staged(self) -> None:
        record = OperationRecord(
            operation_id=OperationId(uid(1)),
            command_name="CreateProduction",
            input_digest=digest("b"),
            result_digest=digest("c"),
            completed_at_us=5,
        )
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.recorder.record(record, transaction=unit_of_work)
            unit_of_work.commit()

        with FakeUnitOfWork(self.database) as second:
            with self.assertRaises(OperationConflictError):
                self.recorder.record(record, transaction=second)

    def test_an_operation_id_recorded_concurrently_is_refused_at_commit(self) -> None:
        production = sample_production()
        record = OperationRecord(
            operation_id=OperationId(uid(1)),
            command_name="CreateProduction",
            input_digest=digest("b"),
            result_digest=digest("c"),
            completed_at_us=5,
        )
        twin = dataclasses.replace(record, completed_at_us=6)
        with FakeUnitOfWork(self.database) as unit_of_work:
            self.productions.save(production, expected_version=0)
            self.recorder.record(record, transaction=unit_of_work)
            self.recorder.records[record.operation_id] = twin
            with self.assertRaises(OperationConflictError):
                unit_of_work.commit()

        self.assertEqual(self.productions.rows, {})
        self.assertIs(self.recorder.records[record.operation_id], twin)


class FakePortConformanceTests(unittest.TestCase):
    def test_every_fake_satisfies_its_port_protocol(self) -> None:
        database = FakeDatabase()
        conformances: tuple[tuple[object, type], ...] = (
            (FakeProductionRepository(database), ProductionRepository),
            (FakeReviewRoundRepository(database), ReviewRoundRepository),
            (FakeReviewFindingRepository(database), ReviewFindingRepository),
            (FakeASRProposalSetRepository(database), ASRProposalSetRepository),
            (FakeTranscriptEditionRepository(database), TranscriptEditionRepository),
            (FakeReleasePolicyVersionRepository(database), ReleasePolicyVersionRepository),
            (FakeOperationRecorder(database), OperationRecorder),
            (FakeUnitOfWork(database), UnitOfWork),
            (FakeClock(), Clock),
        )
        for fake, port in conformances:
            with self.subTest(port=port.__name__):
                self.assertIsInstance(fake, port)

    def test_a_fake_never_masquerades_as_an_unrelated_port(self) -> None:
        self.assertNotIsInstance(FakeClock(), ActorAuthority)


if __name__ == "__main__":
    unittest.main()
