"""Focused contracts for the restart-safe local generation budget ledger."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ValidationError, parse_strict_json
from heritage_archive.contexts.narrator_voice.application.recovery import BudgetRecoveryState
from heritage_archive.contexts.narrator_voice.domain.errors import BudgetDenied
from heritage_archive.contexts.narrator_voice.domain.ids import (
    BudgetReservationId,
    CommandId,
)
from heritage_archive.contexts.narrator_voice.domain.values import NonNegativeDecimal
from heritage_archive.contexts.narrator_voice.infrastructure.budget_ledger import (
    FilesystemGenerationBudgetLedger,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from tests.heritage_archive.narrator_voice.fixtures import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FilesystemGenerationBudgetLedgerTests(unittest.TestCase):
    def test_reserve_enforces_each_configured_ceiling(self) -> None:
        """Removing any one cap check would authorize an over-budget provider request."""
        cases = (
            ("per-take", {"per_take": "5"}, ((1, 1, "6"),)),
            ("per-run", {"per_run": "10"}, ((1, 1, "6"), (2, 1, "5"))),
            ("project", {"project": "10"}, ((1, 1, "6"), (2, 2, "5"))),
            ("billing-cycle", {"billing_cycle": "10"}, ((1, 1, "6"), (2, 2, "5"))),
        )
        for label, overrides, reservations in cases:
            with self.subTest(label=label), self._storage_root() as root:
                ledger = self._ledger(root, **overrides)
                for index, (reservation, run, usage) in enumerate(reservations):
                    operation = lambda: ledger.reserve(
                        BudgetReservationId(uuid(100 + reservation)),
                        CommandId(uuid(200 + run)),
                        NonNegativeDecimal(usage),
                    )
                    if index == len(reservations) - 1:
                        with self.assertRaises(BudgetDenied):
                            operation()
                    else:
                        operation()

    def test_distinct_runs_do_not_share_the_per_run_total(self) -> None:
        """Charging one run against another run's ceiling would block valid sequential work."""
        with self._storage_root() as root:
            ledger = self._ledger(root, per_run="10")

            ledger.reserve(BudgetReservationId(uuid(301)), CommandId(uuid(401)), NonNegativeDecimal("6"))
            ledger.reserve(BudgetReservationId(uuid(302)), CommandId(uuid(402)), NonNegativeDecimal("6"))

            self.assertEqual(ledger.read(BudgetReservationId(uuid(302))), BudgetRecoveryState.RESERVED)

    def test_exact_repeats_are_noops_and_conflicting_repeats_fail_closed(self) -> None:
        """A retry must neither duplicate a fact nor silently rebind its run or usage."""
        with self._storage_root() as root:
            ledger = self._ledger(root)
            reservation = BudgetReservationId(uuid(501))
            run = CommandId(uuid(502))
            with self.assertRaises(ValidationError):
                ledger.settle(reservation, NonNegativeDecimal("4.25"))
            ledger.reserve(reservation, run, NonNegativeDecimal("4.25"))
            after_reserve = self._ledger_bytes(root)

            ledger.reserve(reservation, run, NonNegativeDecimal("4.25"))
            self.assertEqual(self._ledger_bytes(root), after_reserve)
            with self.assertRaises(ValidationError):
                ledger.reserve(reservation, CommandId(uuid(503)), NonNegativeDecimal("4.25"))
            with self.assertRaises(ValidationError):
                ledger.reserve(reservation, run, NonNegativeDecimal("4.5"))

            ledger.settle(reservation, NonNegativeDecimal("3.75"))
            after_settle = self._ledger_bytes(root)
            ledger.settle(reservation, NonNegativeDecimal("3.75"))
            self.assertEqual(self._ledger_bytes(root), after_settle)
            with self.assertRaises(ValidationError):
                ledger.settle(reservation, NonNegativeDecimal("3.5"))

            document = parse_strict_json(after_settle)
            self.assertEqual(len(document["facts"]), 2)

    def test_settled_usage_is_authoritative_and_cannot_be_downgraded(self) -> None:
        """Actual charged usage must survive even above estimate and later terminal retries."""
        with self._storage_root() as root:
            ledger = self._ledger(root, project="10", billing_cycle="10")
            reservation = BudgetReservationId(uuid(601))
            ledger.reserve(reservation, CommandId(uuid(602)), NonNegativeDecimal("4"))
            ledger.settle(reservation, NonNegativeDecimal("12"))

            self.assertEqual(ledger.read(reservation), BudgetRecoveryState.SETTLED)
            with self.assertRaises(ValidationError):
                ledger.release(reservation, "cannot downgrade a charge")
            with self.assertRaises(ValidationError):
                ledger.hold(reservation, "cannot obscure a known charge")
            with self.assertRaises(BudgetDenied):
                ledger.reserve(
                    BudgetReservationId(uuid(603)),
                    CommandId(uuid(604)),
                    NonNegativeDecimal("1"),
                )

    def test_held_usage_remains_counted_and_reads_unknown(self) -> None:
        """An ambiguous provider outcome must retain its estimated cap consumption."""
        with self._storage_root() as root:
            ledger = self._ledger(root, project="10", billing_cycle="10")
            reservation = BudgetReservationId(uuid(701))
            ledger.reserve(reservation, CommandId(uuid(702)), NonNegativeDecimal("6"))
            ledger.hold(reservation, "provider outcome is ambiguous")

            self.assertEqual(ledger.read(reservation), BudgetRecoveryState.UNKNOWN)
            ledger.hold(reservation, "provider outcome is ambiguous")
            with self.assertRaises(ValidationError):
                ledger.settle(reservation, NonNegativeDecimal("6"))
            with self.assertRaises(BudgetDenied):
                ledger.reserve(
                    BudgetReservationId(uuid(703)),
                    CommandId(uuid(704)),
                    NonNegativeDecimal("5"),
                )

    def test_restart_replays_states_and_totals_without_resetting_evidence(self) -> None:
        """Reopening the adapter must reconstruct both dispositions and occupied capacity."""
        with self._storage_root() as root:
            first = self._ledger(root, project="10", billing_cycle="10")
            settled = BudgetReservationId(uuid(801))
            held = BudgetReservationId(uuid(802))
            first.reserve(settled, CommandId(uuid(803)), NonNegativeDecimal("4"))
            first.settle(settled, NonNegativeDecimal("3"))
            first.reserve(held, CommandId(uuid(804)), NonNegativeDecimal("6"))
            first.hold(held, "uncertain charge")

            reopened = self._ledger(root, project="10", billing_cycle="10")

            self.assertEqual(
                (reopened.read(settled), reopened.read(held)),
                (BudgetRecoveryState.SETTLED, BudgetRecoveryState.UNKNOWN),
            )
            with self.assertRaises(BudgetDenied):
                reopened.reserve(
                    BudgetReservationId(uuid(805)),
                    CommandId(uuid(806)),
                    NonNegativeDecimal("2"),
                )

    def test_missing_is_unknown_and_malformed_or_mismatched_ledgers_fail_closed(self) -> None:
        """Absent reservation evidence is uncertain; corrupt or foreign scope cannot be reset."""
        with self._storage_root() as root:
            ledger = self._ledger(root)
            self.assertEqual(
                ledger.read(BudgetReservationId(uuid(901))),
                BudgetRecoveryState.UNKNOWN,
            )
            path = root.operations / "budget-ledger.json"
            path.write_bytes(b'{"schema_version":1,"facts":[')
            corrupt = path.read_bytes()
            with self.assertRaises(ValidationError):
                ledger.read(BudgetReservationId(uuid(901)))
            with self.assertRaises(ValidationError):
                ledger.reserve(
                    BudgetReservationId(uuid(902)),
                    CommandId(uuid(903)),
                    NonNegativeDecimal("1"),
                )
            self.assertEqual(path.read_bytes(), corrupt)

        with self._storage_root() as root:
            self._ledger(root).reserve(
                BudgetReservationId(uuid(904)),
                CommandId(uuid(905)),
                NonNegativeDecimal("1"),
            )
            with self.assertRaises(ValidationError):
                self._ledger(root, project_id="different-project").read(
                    BudgetReservationId(uuid(904))
                )

    def test_atomic_replacement_failure_preserves_the_previous_valid_document(self) -> None:
        """A failed whole-file publication must leave the last replayable authority untouched."""
        with self._storage_root() as root:
            ledger = self._ledger(root)
            reservation = BudgetReservationId(uuid(1001))
            ledger.reserve(reservation, CommandId(uuid(1002)), NonNegativeDecimal("2"))
            previous = self._ledger_bytes(root)

            with patch(
                "heritage_archive.contexts.narrator_voice.infrastructure.budget_ledger.replace_bytes_atomically",
                side_effect=OSError("simulated replacement failure"),
            ):
                with self.assertRaises(ValidationError):
                    ledger.settle(reservation, NonNegativeDecimal("2"))

            self.assertEqual(self._ledger_bytes(root), previous)
            self.assertEqual(ledger.read(reservation), BudgetRecoveryState.RESERVED)

    @staticmethod
    def _ledger(
        root: LocalNarrationRoot,
        *,
        project_id: str = "fake-project",
        billing_cycle_id: str = "fake-cycle-2026-09",
        per_take: str = "100",
        per_run: str = "100",
        project: str = "100",
        billing_cycle: str = "100",
    ) -> FilesystemGenerationBudgetLedger:
        return FilesystemGenerationBudgetLedger(
            root,
            project_id=project_id,
            billing_cycle_id=billing_cycle_id,
            usage_unit="fake-credits",
            per_take_cap=NonNegativeDecimal(per_take),
            per_run_cap=NonNegativeDecimal(per_run),
            project_cap=NonNegativeDecimal(project),
            billing_cycle_cap=NonNegativeDecimal(billing_cycle),
        )

    @staticmethod
    def _ledger_bytes(root: LocalNarrationRoot) -> bytes:
        return (root.operations / "budget-ledger.json").read_bytes()

    def _storage_root(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = LocalNarrationRoot.open(Path(temporary_directory.name), (PROJECT_ROOT,))
        root.initialize_layout()
        return _StorageRootContext(root)


class _StorageRootContext:
    def __init__(self, root: LocalNarrationRoot) -> None:
        self._root = root

    def __enter__(self) -> LocalNarrationRoot:
        return self._root

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
