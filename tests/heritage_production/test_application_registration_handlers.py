"""RegisterRubric and RegisterActorCredential — handlers that write no root.

Design 9.1 gives both "Artifact/operation records only" as their write set, so
these are the first handlers whose durable result lives entirely in the
operation record. The tests therefore assert two things no earlier checkpoint
could: that the transaction spends no aggregate root, and that artifact
validation happens outside the transaction but after the idempotency check.
"""

from __future__ import annotations

import dataclasses
import unittest

from heritage_production.application import commands
from heritage_production.application.errors import OperationConflictError
from heritage_production.application.idempotency import command_result_digest
from heritage_production.domain.shared import (
    ActorCredentialRef,
    ArtifactId,
    AssuranceLevel,
    ContentDigest,
    CredentialVerificationMethod,
    OperationId,
    RubricId,
    StaleReferenceError,
    ValidationError,
)

from tests.heritage_production.application_harness import (
    STEWARD,
    ApplicationHarness,
)
from tests.heritage_production.heritage_release_fixtures import (
    actor,
    attested_credential,
    uid,
)


RUBRIC_BYTES = b'{"criteria":["accuracy","diacritics"]}'
KEY_BYTES = b"ed25519-public-key-material"


class Fixture:
    def __init__(self) -> None:
        self.harness = ApplicationHarness()
        self.content = self.harness.artifacts.seed(ArtifactId(uid(300)), RUBRIC_BYTES)

    def verified_credential(self) -> ActorCredentialRef:
        key = self.harness.artifacts.seed(
            ArtifactId(uid(301)), KEY_BYTES, media_type="application/octet-stream"
        )
        return ActorCredentialRef(
            actor(40),
            CredentialVerificationMethod.ED25519,
            AssuranceLevel.VERIFIED_SIGNATURE,
            ContentDigest.from_bytes(KEY_BYTES),
            key,
        )


def rubric_command(fixture: "Fixture") -> commands.RegisterRubric:
    return commands.RegisterRubric(
        operation_id=OperationId(uid(12)),
        actor=fixture.harness.context(),
        rubric_id=RubricId(uid(740)),
        schema_version=1,
        content=fixture.content,
    )


class RegisterRubricTests(unittest.TestCase):
    def test_it_returns_a_reference_bound_to_the_stored_artifact(self) -> None:
        fixture = Fixture()

        outcome = fixture.harness.register_rubric(fixture.content)

        self.assertEqual(outcome.result.rubric_id.value, uid(740))
        self.assertEqual(outcome.result.content_digest, fixture.content.content_digest)
        self.assertEqual(outcome.result.artifact, fixture.content)

    def test_it_writes_no_aggregate_root(self) -> None:
        """Design 9.1: artifact and operation records only."""
        fixture = Fixture()

        fixture.harness.register_rubric(fixture.content)

        self.assertEqual(fixture.harness.units[-1]._root_writes, set())
        self.assertEqual(fixture.harness.productions.rows, {})
        self.assertEqual(fixture.harness.policies.rows, {})
        self.assertEqual(len(fixture.harness.recorder.records), 1)

    def test_validation_happens_before_any_transaction_opens(self) -> None:
        """A rejected artifact must never open a transaction at all."""
        fixture = Fixture()
        absent = ContentDigest.from_bytes(b"never stored")
        unstored = type(fixture.content)(
            ArtifactId(uid(399)), absent, 12, "application/json"
        )

        with self.assertRaises(StaleReferenceError):
            fixture.harness.register_rubric(unstored)

        # A unit of work object may be constructed; what matters is that none
        # was ever entered, since entering is what opens the transaction.
        self.assertEqual([u for u in fixture.harness.units if u.entered], [])
        self.assertEqual(fixture.harness.recorder.records, {})

    def test_bytes_that_no_longer_match_their_digest_are_refused(self) -> None:
        """The store is re-hashed; a reference is a claim, not evidence."""
        fixture = Fixture()
        fixture.harness.artifacts.corrupt(fixture.content, b"different bytes entirely")

        with self.assertRaises(StaleReferenceError):
            fixture.harness.register_rubric(fixture.content)

        self.assertEqual(fixture.harness.recorder.records, {})

    def test_a_replay_returns_the_original_reference(self) -> None:
        fixture = Fixture()
        first = fixture.harness.register_rubric(fixture.content)

        again = fixture.harness.register_rubric(fixture.content)

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, first.result)
        self.assertEqual(len(fixture.harness.recorder.records), 1)

    def test_a_replay_revalidates_no_artifact(self) -> None:
        """Validation is for fresh work; a completed operation is settled."""
        fixture = Fixture()
        fixture.harness.register_rubric(fixture.content)
        checked_after_first = len(fixture.harness.artifacts.verifications)

        fixture.harness.register_rubric(fixture.content)

        self.assertEqual(
            len(fixture.harness.artifacts.verifications), checked_after_first
        )

    def test_the_payload_pins_the_whole_reference(self) -> None:
        """No aggregate to reload, so the payload is the entire durable result."""
        fixture = Fixture()

        outcome = fixture.harness.register_rubric(fixture.content)

        self.assertEqual(
            outcome.record.result_payload,
            {
                "rubric_id": uid(740),
                "schema_version": 1,
                "content_digest": fixture.content.content_digest.hex_digest,
                "artifact_id": uid(300),
            },
        )

    def test_a_consistently_rewritten_record_is_refused(self) -> None:
        """The last guard, and the only one that can catch this.

        Rewriting the stored payload *and* recomputing its digest keeps the
        record self-consistent and the command's input digest unchanged, so
        every earlier check passes. Only comparing the rebuilt reference
        against the one this command names notices.
        """
        fixture = Fixture()
        command = rubric_command(fixture)
        first = fixture.harness.registrations.register_rubric(command)
        forged = {**first.record.result_payload, "rubric_id": uid(999)}
        fixture.harness.recorder.records[command.operation_id] = dataclasses.replace(
            first.record,
            result_payload=forged,
            result_digest=command_result_digest(command, forged),
        )

        with self.assertRaises(ValidationError):
            fixture.harness.registrations.register_rubric(command)

    def test_a_changed_schema_version_under_one_operation_id_conflicts(self) -> None:
        fixture = Fixture()
        fixture.harness.register_rubric(fixture.content, schema_version=1)

        with self.assertRaises(OperationConflictError):
            fixture.harness.register_rubric(fixture.content, schema_version=2)

    def test_a_different_rubric_id_needs_a_different_operation(self) -> None:
        fixture = Fixture()
        first = fixture.harness.register_rubric(fixture.content, rubric_suffix=740)

        second = fixture.harness.register_rubric(
            fixture.content, rubric_suffix=741, suffix=14
        )

        self.assertNotEqual(first.result.rubric_id, second.result.rubric_id)
        self.assertEqual(len(fixture.harness.recorder.records), 2)


class RegisterActorCredentialTests(unittest.TestCase):
    def test_an_attested_credential_needs_no_key_material(self) -> None:
        fixture = Fixture()
        credential = attested_credential(41)

        outcome = fixture.harness.register_credential(credential)

        self.assertEqual(outcome.result, credential)
        self.assertIsNone(outcome.record.result_payload["public_key_artifact_id"])
        self.assertIsNone(outcome.record.result_payload["credential_fingerprint"])

    def test_an_attested_credential_verifies_no_artifact(self) -> None:
        fixture = Fixture()

        fixture.harness.register_credential(attested_credential(41))

        self.assertEqual(fixture.harness.artifacts.verifications, [])

    def test_a_verified_credential_binds_its_stored_public_key(self) -> None:
        fixture = Fixture()
        credential = fixture.verified_credential()

        outcome = fixture.harness.register_credential(credential)

        self.assertEqual(
            outcome.record.result_payload["public_key_artifact_id"], uid(301)
        )
        self.assertEqual(
            outcome.record.result_payload["verification_method"], "ed25519"
        )

    def test_a_verified_credential_whose_key_is_absent_is_refused(self) -> None:
        fixture = Fixture()
        credential = fixture.verified_credential()
        fixture.harness.artifacts.blobs.clear()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.register_credential(credential)

        self.assertEqual([u for u in fixture.harness.units if u.entered], [])
        self.assertEqual(fixture.harness.recorder.records, {})

    def test_the_payload_records_only_public_verification_evidence(self) -> None:
        """Design 15.1: private keys never reach the project store."""
        fixture = Fixture()
        credential = fixture.verified_credential()

        outcome = fixture.harness.register_credential(credential)

        self.assertEqual(
            set(outcome.record.result_payload),
            {
                "actor_id",
                "verification_method",
                "assurance",
                "credential_fingerprint",
                "public_key_artifact_id",
            },
        )

    def test_it_writes_no_aggregate_root(self) -> None:
        fixture = Fixture()

        fixture.harness.register_credential(attested_credential(41))

        self.assertEqual(fixture.harness.units[-1]._root_writes, set())
        self.assertEqual(fixture.harness.productions.rows, {})

    def test_a_replay_returns_the_original_credential(self) -> None:
        fixture = Fixture()
        credential = attested_credential(41)
        first = fixture.harness.register_credential(credential)

        again = fixture.harness.register_credential(credential)

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, first.result)
        self.assertEqual(len(fixture.harness.recorder.records), 1)

    def test_a_changed_credential_under_one_operation_id_conflicts(self) -> None:
        fixture = Fixture()
        fixture.harness.register_credential(attested_credential(41))

        with self.assertRaises(OperationConflictError):
            fixture.harness.register_credential(attested_credential(42))

    def test_a_consistently_rewritten_record_is_refused(self) -> None:
        fixture = Fixture()
        credential = attested_credential(41)
        command = commands.RegisterActorCredential(
            operation_id=OperationId(uid(13)),
            actor=fixture.harness.context(),
            credential=credential,
        )
        first = fixture.harness.registrations.register_actor_credential(command)
        forged = {**first.record.result_payload, "assurance": "verified_signature"}
        fixture.harness.recorder.records[command.operation_id] = dataclasses.replace(
            first.record,
            result_payload=forged,
            result_digest=command_result_digest(command, forged),
        )

        with self.assertRaises(ValidationError):
            fixture.harness.registrations.register_actor_credential(command)

    def test_the_command_requires_an_exact_credential(self) -> None:
        fixture = Fixture()
        for name, bad in (("actor", STEWARD), ("none", None), ("text", uid(41))):
            with self.subTest(credential=name):
                with self.assertRaises(ValidationError):
                    commands.RegisterActorCredential(
                        operation_id=OperationId(uid(13)),
                        actor=fixture.harness.context(),
                        credential=bad,  # type: ignore[arg-type]
                    )


if __name__ == "__main__":
    unittest.main()
