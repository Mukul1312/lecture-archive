"""CreateReleasePolicyVersion and ConfigureExternalGates.

`CreateReleasePolicyVersion` is the first handler to write a *sealed* root, so
it is the first with no optimistic version to expect and no events to publish.
Design 11.6 gives sealed records no update or delete, which the repository port
enforces by offering only `add` and `get`: a second operation naming an
existing policy id is refused rather than overwriting it.

`ConfigureExternalGates` seals the gate set inside the handler rather than
accepting one, so no caller can hand over a set whose digest disagrees with
its own contents. Design 9.2 makes an explicitly empty set valid, which is a
configuration decision and not a missing one.
"""

from __future__ import annotations

import dataclasses
import unittest

from heritage_production.application.errors import OperationConflictError
from heritage_production.domain.release import (
    ExternalGateRequirement,
    IntegrityCheckCode,
)
from heritage_production.domain.shared import (
    AssuranceLevel,
    GateCode,
    GateScope,
    InvariantError,
    ProductionId,
    ReleasePolicyVersionId,
    RoleCode,
    SignOffTargetKind,
    SignOffTargetRule,
    StaleReferenceError,
    ValidationError,
)

from tests.heritage_production.application_harness import (
    STEWARD,
    ApplicationHarness,
    empty_rules,
)
from tests.heritage_production.heritage_release_fixtures import (
    uid,
    verified_credential,
)


FINGERPRINT_SOURCE = "9"


def rights_holder_requirement() -> ExternalGateRequirement:
    from tests.heritage_production.heritage_release_fixtures import digest

    return ExternalGateRequirement(
        GateCode("rights-holder-approval"),
        GateScope.EXTERNAL_RELEASE,
        RoleCode("rights-holder"),
        verified_credential(40, digest(FINGERPRINT_SOURCE)),
        AssuranceLevel.VERIFIED_SIGNATURE,
        SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
    )


class CreateReleasePolicyVersionTests(unittest.TestCase):
    def test_it_seals_and_stores_the_policy(self) -> None:
        harness = ApplicationHarness()

        outcome = harness.create_policy()

        stored = harness.policies.get(ReleasePolicyVersionId(uid(720)))
        self.assertIs(outcome.result, stored)
        self.assertEqual(stored.semantic_label, "pilot-transcript-policy")
        self.assertEqual(stored.ref, outcome.result.ref)

    def test_the_commanding_actor_becomes_the_author(self) -> None:
        harness = ApplicationHarness()

        outcome = harness.create_policy()

        self.assertEqual(outcome.result.author_actor_id, STEWARD)

    def test_a_sealed_root_publishes_no_events(self) -> None:
        """Design 9.6 lists no policy-created fact, and sealed roots record none."""
        harness = ApplicationHarness()

        harness.create_policy()

        self.assertEqual(harness.events.events, [])

    def test_the_payload_pins_the_policy_digest(self) -> None:
        """A sealed root has no version, so the digest is what a replay pins."""
        harness = ApplicationHarness()

        outcome = harness.create_policy()

        self.assertEqual(
            outcome.record.result_payload,
            {
                "release_policy_version_id": uid(720),
                "policy_digest": outcome.result.policy_digest.hex_digest,
                "semantic_label": "pilot-transcript-policy",
            },
        )

    def test_a_replay_returns_the_same_sealed_policy(self) -> None:
        harness = ApplicationHarness()
        first = harness.create_policy()

        again = harness.create_policy()

        self.assertTrue(again.replayed)
        self.assertIs(again.result, first.result)
        self.assertEqual(len(harness.policies.rows), 1)

    def test_changed_rules_under_one_operation_id_conflict(self) -> None:
        harness = ApplicationHarness()
        harness.create_policy()
        stricter = dataclasses.replace(
            empty_rules(),
            required_integrity_checks=(IntegrityCheckCode("object-digests"),),
        )

        with self.assertRaises(OperationConflictError):
            harness.create_policy(rules=stricter)

        self.assertEqual(len(harness.policies.rows), 1)

    def test_a_second_operation_may_not_reuse_a_policy_id(self) -> None:
        """Sealed records have no update path, so this is refused, not merged."""
        harness = ApplicationHarness()
        harness.create_policy(suffix=7)

        with self.assertRaises(InvariantError):
            harness.create_policy(suffix=8, semantic_label="a different label")

        self.assertEqual(len(harness.policies.rows), 1)
        self.assertEqual(len(harness.recorder.records), 1)

    def test_a_rejected_policy_leaves_nothing_durable(self) -> None:
        harness = ApplicationHarness()

        with self.assertRaises(ValidationError):
            harness.create_policy(semantic_label="")

        self.assertEqual(harness.policies.rows, {})
        self.assertEqual(harness.recorder.records, {})

    def test_a_commit_failure_leaves_nothing_durable(self) -> None:
        harness = ApplicationHarness()
        harness.commit_failure = RuntimeError("disk full")

        with self.assertRaises(RuntimeError):
            harness.create_policy()

        self.assertEqual(harness.policies.rows, {})
        self.assertEqual(harness.recorder.records, {})

    def test_the_created_policy_can_then_be_selected(self) -> None:
        """The two halves of design 9.2 step 5 meet."""
        harness = ApplicationHarness()
        created = harness.create()
        policy = harness.create_policy()

        outcome = harness.select_policy(
            created.result.production_id, policy.result.ref, expected_version=1
        )

        self.assertEqual(outcome.result, policy.result.ref)


class ConfigureExternalGatesTests(unittest.TestCase):
    def prepared(self) -> tuple[ApplicationHarness, ProductionId]:
        harness = ApplicationHarness()
        created = harness.create()
        return harness, created.result.production_id

    def test_it_configures_and_activates_the_gate_set(self) -> None:
        harness, production_id = self.prepared()

        outcome = harness.configure_gates(
            production_id, (rights_holder_requirement(),), expected_version=1
        )

        (root, version) = harness.productions.rows[production_id]
        self.assertEqual(version, 2)
        self.assertEqual(root.active_gate_set_ref, outcome.result)
        self.assertEqual(len(root.gate_sets), 1)

    def test_it_enqueues_the_configuration_event(self) -> None:
        harness, production_id = self.prepared()

        harness.configure_gates(
            production_id, (rights_holder_requirement(),), expected_version=1
        )

        self.assertEqual(
            harness.events.names(), ("ProductionCreated", "ExternalGateSetConfigured")
        )

    def test_an_explicitly_empty_gate_set_is_valid(self) -> None:
        """Design 9.2: an explicit empty set is a decision, not an omission."""
        harness, production_id = self.prepared()

        outcome = harness.configure_gates(production_id, (), expected_version=1)

        (root, _) = harness.productions.rows[production_id]
        self.assertEqual(root.active_gate_set_ref, outcome.result)
        self.assertEqual(root.gate_sets[0].requirements, ())

    def test_the_gate_set_digest_covers_the_requirements(self) -> None:
        """Sealing in the handler is what makes this true of every caller."""
        harness, production_id = self.prepared()
        empty = harness.configure_gates(production_id, (), expected_version=1)

        other, other_production = self.prepared()
        filled = other.configure_gates(
            other_production, (rights_holder_requirement(),), expected_version=1
        )

        self.assertNotEqual(empty.result.content_digest, filled.result.content_digest)

    def test_a_replay_returns_the_same_gate_set_reference(self) -> None:
        harness, production_id = self.prepared()
        first = harness.configure_gates(
            production_id, (rights_holder_requirement(),), expected_version=1
        )

        again = harness.configure_gates(
            production_id, (rights_holder_requirement(),), expected_version=1
        )

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, first.result)
        self.assertEqual(harness.productions.rows[production_id][1], 2)

    def test_one_gate_set_id_may_not_hold_two_different_requirement_sets(self) -> None:
        harness, production_id = self.prepared()
        harness.configure_gates(production_id, (), suffix=6, expected_version=1)
        before = harness.durable()

        with self.assertRaises(ValidationError):
            harness.configure_gates(
                production_id,
                (rights_holder_requirement(),),
                suffix=9,
                expected_version=2,
            )

        self.assertEqual(harness.durable(), before)

    def test_a_stale_expected_version_leaves_the_aggregate_unmutated(self) -> None:
        harness, production_id = self.prepared()
        before = harness.durable()

        with self.assertRaises(StaleReferenceError):
            harness.configure_gates(production_id, (), expected_version=99)

        self.assertEqual(harness.durable(), before)
        (root, _) = harness.productions.rows[production_id]
        self.assertIsNone(root.active_gate_set_ref)
        self.assertEqual(root.pull_events(), ())

    def test_gates_for_a_production_that_does_not_exist_are_refused(self) -> None:
        harness, _ = self.prepared()
        before = harness.durable()

        with self.assertRaises(StaleReferenceError):
            harness.configure_gates(
                ProductionId(uid(999)), (), suffix=11, expected_version=1
            )

        self.assertEqual(harness.durable(), before)


if __name__ == "__main__":
    unittest.main()
