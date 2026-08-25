"""SelectCandidateEdition and SelectReleasePolicyVersion.

Both are the first handlers to read an immutable input from *another*
aggregate. Design 9.3 says those are read by exact ID and digest, so each
loads the referenced root and refuses a reference that names something not
stored, something stored under a different digest, or something belonging to
a different Production. A command carrying only a reference cannot be trusted
to describe what it points at.
"""

from __future__ import annotations

import unittest

from heritage_production.application import commands
from heritage_production.application.errors import OperationConflictError
from heritage_production.domain.production import EditionSelection
from heritage_production.domain.shared import (
    ContentDigest,
    OperationId,
    EditionRef,
    PolicyRef,
    ProductionId,
    ReleasePolicyVersionId,
    StaleReferenceError,
    TranscriptEditionId,
    ValidationError,
)

from tests.heritage_production.application_fakes import sample_policy
from tests.heritage_production.application_harness import STEWARD, ApplicationHarness
from tests.heritage_production.heritage_release_fixtures import uid
from tests.heritage_production.test_transcript_editions import seal_initial
from tests.heritage_production.test_transcription_proposals import SOURCE


OTHER_DIGEST = ContentDigest("sha256", "f" * 64)


class Fixture:
    """A Production with SOURCE attached, plus a sealed edition for it."""

    def __init__(self) -> None:
        self.harness = ApplicationHarness()
        created = self.harness.create()
        self.production_id = created.result.production_id
        self.harness.attach(self.production_id, SOURCE)
        self.edition = seal_initial(production_id=self.production_id)
        self.edition.pull_events()
        self.harness.store_edition(self.edition)

    def selection(self, edition_ref: EditionRef | None = None) -> EditionSelection:
        return EditionSelection(
            production_id=self.production_id,
            edition_ref=edition_ref or self.edition.ref,
            source_version_refs=(SOURCE,),
        )


class SelectCandidateEditionTests(unittest.TestCase):
    def test_it_selects_the_edition_and_bumps_the_version(self) -> None:
        fixture = Fixture()

        outcome = fixture.harness.select_edition(
            fixture.production_id, fixture.selection()
        )

        (root, version) = fixture.harness.productions.rows[fixture.production_id]
        self.assertEqual(version, 3)
        self.assertEqual(root.selected_edition_ref, fixture.edition.ref)
        self.assertEqual(outcome.result, fixture.edition.ref)
        self.assertEqual(root.lifecycle_phase, "TRANSCRIPT_SELECTED")

    def test_it_enqueues_the_selection_event(self) -> None:
        fixture = Fixture()

        fixture.harness.select_edition(fixture.production_id, fixture.selection())

        self.assertEqual(
            fixture.harness.events.names(),
            ("ProductionCreated", "SourceRecordingAttached", "CandidateEditionSelected"),
        )

    def test_the_payload_reports_the_selected_edition(self) -> None:
        fixture = Fixture()

        outcome = fixture.harness.select_edition(
            fixture.production_id, fixture.selection()
        )

        self.assertEqual(
            outcome.record.result_payload["lifecycle_phase"], "TRANSCRIPT_SELECTED"
        )
        self.assertEqual(outcome.record.result_payload["version"], 3)

    def test_a_replay_returns_the_same_edition_reference(self) -> None:
        fixture = Fixture()
        first = fixture.harness.select_edition(
            fixture.production_id, fixture.selection()
        )

        again = fixture.harness.select_edition(
            fixture.production_id, fixture.selection()
        )

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, first.result)
        self.assertEqual(fixture.harness.productions.rows[fixture.production_id][1], 3)

    def test_an_edition_that_was_never_stored_is_refused(self) -> None:
        fixture = Fixture()
        before = fixture.harness.durable()
        missing = EditionRef(TranscriptEditionId(uid(777)), fixture.edition.semantic_digest)

        with self.assertRaises(StaleReferenceError):
            fixture.harness.select_edition(
                fixture.production_id, fixture.selection(missing)
            )

        self.assertEqual(fixture.harness.durable(), before)

    def test_an_edition_reference_with_the_wrong_digest_is_refused(self) -> None:
        """The stored edition exists, but not with the content claimed."""
        fixture = Fixture()
        before = fixture.harness.durable()
        forged = EditionRef(fixture.edition.transcript_edition_id, OTHER_DIGEST)

        with self.assertRaises(StaleReferenceError):
            fixture.harness.select_edition(
                fixture.production_id, fixture.selection(forged)
            )

        self.assertEqual(fixture.harness.durable(), before)

    def test_an_edition_belonging_to_another_production_is_refused(self) -> None:
        fixture = Fixture()
        foreign = seal_initial(
            transcript_edition_id=TranscriptEditionId(uid(500)),
            production_id=ProductionId(uid(501)),
        )
        foreign.pull_events()
        fixture.harness.store_edition(foreign)
        before = fixture.harness.durable()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.select_edition(
                fixture.production_id, fixture.selection(foreign.ref)
            )

        self.assertEqual(fixture.harness.durable(), before)

    def test_a_stale_expected_version_leaves_the_aggregate_unmutated(self) -> None:
        fixture = Fixture()
        before = fixture.harness.durable()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.select_edition(
                fixture.production_id, fixture.selection(), expected_version=99
            )

        self.assertEqual(fixture.harness.durable(), before)
        (root, _) = fixture.harness.productions.rows[fixture.production_id]
        self.assertIsNone(root.selected_edition_ref)
        self.assertEqual(root.pull_events(), ())

    def test_a_selection_naming_another_production_is_refused(self) -> None:
        fixture = Fixture()
        before = fixture.harness.durable()
        wrong = EditionSelection(
            production_id=ProductionId(uid(601)),
            edition_ref=fixture.edition.ref,
            source_version_refs=(SOURCE,),
        )

        with self.assertRaises(ValidationError):
            fixture.harness.select_edition(fixture.production_id, wrong)

        self.assertEqual(fixture.harness.durable(), before)


class SelectReleasePolicyVersionTests(unittest.TestCase):
    def prepared(self) -> tuple[Fixture, object]:
        fixture = Fixture()
        fixture.harness.select_edition(fixture.production_id, fixture.selection())
        policy = sample_policy()
        fixture.harness.store_policy(policy)
        return fixture, policy

    def test_it_selects_the_policy_and_bumps_the_version(self) -> None:
        fixture, policy = self.prepared()

        outcome = fixture.harness.select_policy(fixture.production_id, policy.ref)

        (root, version) = fixture.harness.productions.rows[fixture.production_id]
        self.assertEqual(version, 4)
        self.assertEqual(root.selected_policy_ref, policy.ref)
        self.assertEqual(outcome.result, policy.ref)

    def test_it_enqueues_the_selection_event(self) -> None:
        fixture, policy = self.prepared()

        fixture.harness.select_policy(fixture.production_id, policy.ref)

        self.assertEqual(
            fixture.harness.events.names()[-1], "ReleasePolicyVersionSelected"
        )

    def test_a_replay_returns_the_same_policy_reference(self) -> None:
        fixture, policy = self.prepared()
        first = fixture.harness.select_policy(fixture.production_id, policy.ref)

        again = fixture.harness.select_policy(fixture.production_id, policy.ref)

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, first.result)
        self.assertEqual(fixture.harness.productions.rows[fixture.production_id][1], 4)

    def test_a_policy_that_was_never_stored_is_refused(self) -> None:
        fixture, policy = self.prepared()
        before = fixture.harness.durable()
        missing = PolicyRef(ReleasePolicyVersionId(uid(888)), policy.policy_digest)

        with self.assertRaises(StaleReferenceError):
            fixture.harness.select_policy(fixture.production_id, missing)

        self.assertEqual(fixture.harness.durable(), before)

    def test_a_policy_reference_with_the_wrong_digest_is_refused(self) -> None:
        """A fabricated policy body can no longer be smuggled in as a ref."""
        fixture, policy = self.prepared()
        before = fixture.harness.durable()
        forged = PolicyRef(policy.release_policy_version_id, OTHER_DIGEST)

        with self.assertRaises(StaleReferenceError):
            fixture.harness.select_policy(fixture.production_id, forged)

        self.assertEqual(fixture.harness.durable(), before)

    def test_a_stale_expected_version_leaves_the_aggregate_unmutated(self) -> None:
        fixture, policy = self.prepared()
        before = fixture.harness.durable()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.select_policy(
                fixture.production_id, policy.ref, expected_version=99
            )

        self.assertEqual(fixture.harness.durable(), before)
        (root, _) = fixture.harness.productions.rows[fixture.production_id]
        self.assertIsNone(root.selected_policy_ref)
        self.assertEqual(root.pull_events(), ())

    def test_a_changed_policy_under_one_operation_id_conflicts(self) -> None:
        fixture, policy = self.prepared()
        other = sample_policy(suffix=1)
        fixture.harness.store_policy(other)
        fixture.harness.select_policy(fixture.production_id, policy.ref)

        with self.assertRaises(OperationConflictError):
            fixture.harness.select_policy(fixture.production_id, other.ref)


class SelectReleasePolicyVersionCommandTests(unittest.TestCase):
    def test_the_command_requires_an_exact_policy_reference(self) -> None:
        """Design 9.1 reads an exact PolicyRef, so a near-miss is not a ref.

        Accepting a bare id, a digest, or a whole policy body would put the
        handler's storage lookup on an input it cannot pin.
        """
        policy = sample_policy()
        for name, bad in (
            ("id only", policy.release_policy_version_id),
            ("digest only", policy.policy_digest),
            ("the policy body", policy),
            ("none", None),
            ("text", str(policy.release_policy_version_id)),
        ):
            with self.subTest(policy_ref=name):
                with self.assertRaises(ValidationError):
                    commands.SelectReleasePolicyVersion(
                        operation_id=OperationId(uid(1)),
                        actor=commands.ActorContext(STEWARD),
                        production_id=ProductionId(uid(2)),
                        policy_ref=bad,  # type: ignore[arg-type]
                        expected_version=1,
                    )


if __name__ == "__main__":
    unittest.main()
