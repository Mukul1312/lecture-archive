"""CreateProduction and AttachSourceRecording through the real ports.

These are the first handlers, so they also pin what every later handler must
do: one aggregate root per transaction (design 9.3), the operation record and
the outbox rows durable with the aggregate or not at all (9.4, 9.6), and a
replay that returns the original result rather than doing the work twice.

`CreateProduction` is the sharpest case. Design 9.1 gives it no input ID --
its *result* is the Production ID -- so the identity is generated inside the
handler. A replay must therefore return the identity the first run generated,
which only works because the operation record stores its result (design 13.4).
"""

from __future__ import annotations

import unittest

from heritage_production.application import commands
from heritage_production.application.errors import (
    OperationConflictError,
    ReplayIntegrityError,
)
from heritage_production.application.execution import CompletedOperation
from heritage_production.application.handlers import ProductionCommandHandlers
from heritage_production.domain.production import AttachedSource, Production
from heritage_production.domain.shared import (
    ActorId,
    DomainEventId,
    OperationId,
    ProductionId,
    SourceRecordingRef,
    StaleReferenceError,
    ValidationError,
)

from tests.heritage_production.application_harness import (
    STEWARD,
    ApplicationHarness,
)
from tests.heritage_production.heritage_release_fixtures import (
    actor,
    artifact,
    source_version,
    uid,
)


def sample_attached_source(
    suffix: int = 3, media_digest: str = "2", *, title: str = "SSGGSM 1985-08-21"
) -> AttachedSource:
    """`suffix` fixes the identity; `media_digest` fixes the content.

    `AttachedSource` requires the artifact digest to equal the source
    version's, so the two move together -- varying only `media_digest` keeps
    one identity and changes what it claims to contain.
    """
    version = source_version(suffix=suffix, character=media_digest)
    return AttachedSource(
        SourceRecordingRef(version.source_recording_id, {"title": title}),
        version,
        artifact(200 + suffix, media_digest, "audio/mpeg"),
        STEWARD,
        1_700_000_000_000_000,
    )


class CreateProductionTests(unittest.TestCase):
    def test_it_creates_one_production_at_version_one(self) -> None:
        harness = ApplicationHarness()

        outcome = harness.create()

        self.assertIsInstance(outcome, CompletedOperation)
        self.assertFalse(outcome.replayed)
        self.assertEqual(len(harness.productions.rows), 1)
        (root, version) = next(iter(harness.productions.rows.values()))
        self.assertIs(outcome.result, root)
        self.assertEqual(version, 1)
        self.assertEqual(root.intended_deliverable, "August 21 listening transcript")

    def test_the_commanding_actor_becomes_the_steward(self) -> None:
        harness = ApplicationHarness()

        outcome = harness.create()

        self.assertEqual(outcome.result.steward_actor_id, STEWARD)
        self.assertIs(type(outcome.result.steward_actor_id), ActorId)

    def test_the_identity_is_generated_not_supplied(self) -> None:
        """Design 9.1: CreateProduction's result *is* the Production ID."""
        harness = ApplicationHarness()

        outcome = harness.create()

        self.assertIn(outcome.result.production_id.value, harness.ids.issued)
        self.assertEqual(
            outcome.record.result_payload["production_id"],
            outcome.result.production_id.value,
        )

    def test_the_payload_projects_the_state_a_caller_depends_on(self) -> None:
        """Replay verification reaches exactly as far as the payload does.

        An identity-only payload would let an aggregate whose phase, version,
        or source set had drifted replay clean, so the projection is asserted
        exactly rather than loosely.
        """
        harness = ApplicationHarness()

        outcome = harness.create()

        self.assertEqual(
            outcome.record.result_payload,
            {
                "production_id": outcome.result.production_id.value,
                "version": 1,
                "lifecycle_phase": "DRAFT",
                "source_count": 0,
            },
        )

    def test_a_replay_whose_stored_state_has_drifted_fails_closed(self) -> None:
        """The behavioural half: the projection must actually do the work."""
        harness = ApplicationHarness()
        first = harness.create()
        harness.attach(first.result.production_id, source_version(suffix=3, character='2'))

        with self.assertRaises(ReplayIntegrityError):
            harness.create()

    def test_two_creations_get_distinct_identities(self) -> None:
        harness = ApplicationHarness()

        first = harness.create(suffix=1)
        second = harness.create(suffix=2)

        self.assertNotEqual(first.result.production_id, second.result.production_id)
        self.assertEqual(len(harness.productions.rows), 2)

    def test_it_enqueues_the_creation_event(self) -> None:
        harness = ApplicationHarness()

        outcome = harness.create()

        self.assertEqual(harness.events.names(), ("ProductionCreated",))
        self.assertEqual(
            harness.events.events[0].payload["production_id"],
            outcome.result.production_id.value,
        )

    def test_the_aggregate_keeps_no_unpublished_events(self) -> None:
        """Events left on the root would never reach the outbox."""
        harness = ApplicationHarness()

        outcome = harness.create()

        self.assertEqual(outcome.result.pull_events(), ())

    def test_state_record_and_events_commit_in_one_transaction(self) -> None:
        harness = ApplicationHarness()

        harness.create()

        self.assertEqual(len(harness.units), 1)
        self.assertEqual(harness.units[0].commits, 1)
        self.assertEqual(harness.units[0].rollbacks, 0)

    def test_a_replay_returns_the_generated_identity(self) -> None:
        """The property the whole design of the record exists to support."""
        harness = ApplicationHarness()
        first = harness.create()

        again = harness.create()

        self.assertTrue(again.replayed)
        self.assertEqual(again.result.production_id, first.result.production_id)
        self.assertEqual(again.record, first.record)
        self.assertEqual(len(harness.productions.rows), 1)
        self.assertEqual(harness.events.names(), ("ProductionCreated",))

    def test_a_replay_issues_no_new_identity(self) -> None:
        harness = ApplicationHarness()
        harness.create()
        issued_after_first = list(harness.ids.issued)

        harness.create()

        self.assertEqual(harness.ids.issued, issued_after_first)

    def test_a_changed_deliverable_under_one_operation_id_conflicts(self) -> None:
        harness = ApplicationHarness()
        harness.create(deliverable="August 21 listening transcript")

        with self.assertRaises(OperationConflictError):
            harness.create(deliverable="August 22 listening transcript")

        self.assertEqual(len(harness.productions.rows), 1)

    def test_a_rejected_deliverable_leaves_nothing_durable(self) -> None:
        harness = ApplicationHarness()

        with self.assertRaises(ValidationError):
            harness.create(deliverable="")

        self.assertEqual(harness.durable(), ({}, {}, []))

    def test_a_commit_failure_leaves_nothing_durable(self) -> None:
        harness = ApplicationHarness()
        harness.commit_failure = RuntimeError("disk full")

        with self.assertRaises(RuntimeError):
            harness.create()

        self.assertEqual(harness.durable(), ({}, {}, []))


class AttachSourceRecordingTests(unittest.TestCase):
    def created(self) -> tuple[Harness, ProductionId]:
        harness = ApplicationHarness()
        outcome = harness.create()
        return harness, outcome.result.production_id

    def test_it_attaches_the_exact_source_and_bumps_the_version(self) -> None:
        harness, production_id = self.created()

        outcome = harness.attach(production_id, source_version(suffix=3, character='2'))

        (root, version) = harness.productions.rows[production_id]
        self.assertEqual(version, 2)
        self.assertEqual(len(root.sources), 1)
        self.assertEqual(outcome.result, root.sources[0])

    def test_it_enqueues_the_attachment_event(self) -> None:
        harness, production_id = self.created()

        harness.attach(production_id, source_version(suffix=3, character='2'))

        self.assertEqual(
            harness.events.names(), ("ProductionCreated", "SourceRecordingAttached")
        )

    def test_a_replay_returns_the_original_attachment(self) -> None:
        harness, production_id = self.created()
        first = harness.attach(production_id, source_version(suffix=3, character='2'))

        again = harness.attach(production_id, source_version(suffix=3, character='2'))

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, first.result)
        self.assertEqual(harness.productions.rows[production_id][1], 2)
        self.assertEqual(len(harness.events.events), 2)

    def test_a_stale_expected_version_changes_nothing(self) -> None:
        harness, production_id = self.created()
        before = harness.durable()

        with self.assertRaises(StaleReferenceError):
            harness.attach(production_id, source_version(suffix=3, character='2'), expected_version=99)

        self.assertEqual(harness.durable(), before)

    def test_a_rejected_attach_leaves_the_aggregate_unmutated(self) -> None:
        """A rejected operation must leave the aggregate unchanged.

        Checking the expected version before touching the root is what makes
        that true: saving would catch the conflict too, but only after an
        in-memory mutation and a recorded event.
        """
        harness, production_id = self.created()

        with self.assertRaises(StaleReferenceError):
            harness.attach(production_id, source_version(suffix=3, character='2'), expected_version=99)

        (root, version) = harness.productions.rows[production_id]
        self.assertEqual(version, 1)
        self.assertEqual(root.sources, ())
        self.assertEqual(root.pull_events(), ())

    def test_a_replay_returns_the_source_the_command_named(self) -> None:
        """With several attached, replaying must not return merely the first."""
        harness, production_id = self.created()
        harness.attach(production_id, source_version(suffix=3, character='2'), suffix=2, expected_version=1)
        second = harness.attach(
            production_id,
            source_version(suffix=4, character="3"),
            suffix=3,
            expected_version=2,
        )

        again = harness.attach(
            production_id,
            source_version(suffix=4, character="3"),
            suffix=3,
            expected_version=2,
        )

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, second.result)
        self.assertEqual(again.result.source_version_ref.source_version_id.value, uid(4))

    def test_a_replay_missing_its_recorded_attachment_fails_closed(self) -> None:
        """Storage that lost the attachment must not quietly return the root."""
        harness, production_id = self.created()
        harness.attach(production_id, source_version(suffix=3, character='2'))
        stripped = Production.create(
            production_id=production_id,
            intended_deliverable="August 21 listening transcript",
            steward_actor_id=STEWARD,
            created_at_us=1_700_000_000_000_000,
            event_id=DomainEventId(uid(800)),
            event_occurred_at_us=1_700_000_000_000_001,
        )
        stripped.pull_events()
        harness.productions.rows[production_id] = (stripped, 2)

        with self.assertRaises(StaleReferenceError):
            harness.attach(production_id, source_version(suffix=3, character='2'))

    def test_an_unknown_production_changes_nothing(self) -> None:
        harness, _ = self.created()
        before = harness.durable()

        with self.assertRaises(StaleReferenceError):
            harness.attach(ProductionId(uid(404)), source_version(suffix=3, character='2'))

        self.assertEqual(harness.durable(), before)

    def test_the_same_identity_with_different_content_is_refused(self) -> None:
        harness, production_id = self.created()
        harness.attach(production_id, source_version(suffix=3, character='2'), suffix=2, expected_version=1)
        before = harness.durable()
        # Same identity, different content: one source version cannot claim
        # two different sets of bytes.
        conflicting = sample_attached_source(3, "3")

        with self.assertRaises(ValidationError):
            harness.attach(
                production_id,
                source_version(suffix=3, character="3"),
                suffix=3,
                expected_version=2,
                attached_source=conflicting,
            )

        self.assertEqual(harness.durable(), before)

    def test_a_second_distinct_source_attaches_at_the_next_version(self) -> None:
        harness, production_id = self.created()
        harness.attach(production_id, source_version(suffix=3, character='2'), suffix=2, expected_version=1)

        harness.attach(production_id, source_version(suffix=4, character='3'), suffix=3, expected_version=2)

        (root, version) = harness.productions.rows[production_id]
        self.assertEqual(version, 3)
        self.assertEqual(len(root.sources), 2)


if __name__ == "__main__":
    unittest.main()
