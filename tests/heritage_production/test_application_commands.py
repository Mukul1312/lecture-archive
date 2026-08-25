"""Every command named in design section 9.2, as an immutable DTO."""

from __future__ import annotations

import dataclasses
import unittest

from heritage_production.application import commands
from heritage_production.domain.shared import ActorId, OperationId, ValidationError

from tests.heritage_production.heritage_release_fixtures import uid


# Design section 9.2's command table, verbatim and complete. A command added or
# dropped without amending the design is a design change, so it breaks here.
DESIGN_9_2_COMMANDS = {
    "CreateProduction",
    "AttachSourceRecording",
    "ImportProposalPackage",
    "CreateInitialTranscriptEdition",
    "SelectCandidateEdition",
    "CreateReleasePolicyVersion",
    "SelectReleasePolicyVersion",
    "ConfigureExternalGates",
    "RegisterRubric",
    "RegisterActorCredential",
    "OpenReviewRound",
    "ExportReviewPackage",
    "ImportReviewSubmission",
    "SubmitReviewFinding",
    "FinalizeReviewSubmission",
    "DecideReviewFinding",
    "RecordReviewSignOff",
    "CloseReviewRound",
    "CreateSuccessorTranscriptEdition",
    "AssembleReleaseContent",
    "RecordExternalSignOff",
    "AssembleReleaseCandidate",
    "EvaluateReleaseEligibility",
    "ApproveReleaseCandidate",
    "ExportApprovedRelease",
    "RecordProductionAuthorityCutover",
    "SupersedePreWriteCutover",
}

# Commands whose write target is an already-existing mutable root. Design 9.3
# requires these to carry the version they expect to find.
MUTABLE_ROOT_COMMANDS = {
    "AttachSourceRecording",
    "SelectCandidateEdition",
    "SelectReleasePolicyVersion",
    "ConfigureExternalGates",
    "RecordExternalSignOff",
    "AssembleReleaseCandidate",
    "ApproveReleaseCandidate",
    "FinalizeReviewSubmission",
    "RecordReviewSignOff",
    "CloseReviewRound",
    "DecideReviewFinding",
}


def command_types() -> dict[str, type]:
    return {name: getattr(commands, name) for name in commands.__all__ if name[0].isupper()}


class CommandVocabularyTests(unittest.TestCase):
    def test_exactly_the_design_commands_are_defined(self) -> None:
        defined = {name for name in command_types() if name != "ActorContext"}

        self.assertEqual(defined, DESIGN_9_2_COMMANDS)
        self.assertEqual(len(defined), 27)

    def test_every_command_is_a_frozen_slotted_dataclass(self) -> None:
        for name, command in command_types().items():
            with self.subTest(command=name):
                self.assertTrue(dataclasses.is_dataclass(command))
                self.assertTrue(command.__dataclass_params__.frozen, f"{name} must be frozen")
                self.assertTrue(hasattr(command, "__slots__"), f"{name} must be slotted")
                # Every class object has a __dict__; what matters is that its
                # *instances* do not, which is what __dictoffset__ == 0 means.
                self.assertEqual(
                    command.__dictoffset__, 0, f"{name} instances must not carry a __dict__"
                )


class CommandEnvelopeTests(unittest.TestCase):
    def test_every_command_carries_an_operation_id_and_actor(self) -> None:
        for name in DESIGN_9_2_COMMANDS:
            with self.subTest(command=name):
                fields = {f.name for f in dataclasses.fields(getattr(commands, name))}
                self.assertIn("operation_id", fields, f"{name} needs an OperationId")
                self.assertIn("actor", fields, f"{name} needs an actor context")

    def test_mutable_root_commands_carry_an_expected_version(self) -> None:
        for name in MUTABLE_ROOT_COMMANDS:
            with self.subTest(command=name):
                fields = {f.name for f in dataclasses.fields(getattr(commands, name))}
                self.assertIn("expected_version", fields, f"{name} writes a mutable root")

    def test_creating_commands_never_carry_an_expected_version(self) -> None:
        """A root that does not exist yet has no version to expect."""
        for name in DESIGN_9_2_COMMANDS - MUTABLE_ROOT_COMMANDS:
            with self.subTest(command=name):
                fields = {f.name for f in dataclasses.fields(getattr(commands, name))}
                self.assertNotIn("expected_version", fields)


class ActorContextTests(unittest.TestCase):
    def test_actor_context_binds_an_exact_actor(self) -> None:
        context = commands.ActorContext(ActorId(uid(20)))

        self.assertEqual(context.actor_id, ActorId(uid(20)))

    def test_actor_context_rejects_a_loose_actor(self) -> None:
        for bad in (uid(20), None, 7):
            with self.subTest(actor=bad):
                with self.assertRaises(ValidationError):
                    commands.ActorContext(bad)  # type: ignore[arg-type]


class CommandValidationTests(unittest.TestCase):
    def context(self) -> commands.ActorContext:
        return commands.ActorContext(ActorId(uid(20)))

    def test_a_command_rejects_a_loose_operation_id(self) -> None:
        with self.assertRaises(ValidationError):
            commands.CreateProduction(
                operation_id=uid(1),  # type: ignore[arg-type]
                actor=self.context(),
                intended_deliverable="August 21 listening transcript",
            )

    def test_a_command_rejects_a_loose_actor_context(self) -> None:
        with self.assertRaises(ValidationError):
            commands.CreateProduction(
                operation_id=OperationId(uid(1)),
                actor=ActorId(uid(20)),  # type: ignore[arg-type]
                intended_deliverable="August 21 listening transcript",
            )

    def test_a_command_rejects_a_nonpositive_expected_version(self) -> None:
        from heritage_production.domain.shared import ProductionId

        with self.assertRaises(ValidationError):
            commands.SelectCandidateEdition(
                operation_id=OperationId(uid(1)),
                actor=self.context(),
                production_id=ProductionId(uid(2)),
                edition_selection=None,  # type: ignore[arg-type]
                expected_version=0,
            )

    def test_a_command_is_immutable(self) -> None:
        command = commands.CreateProduction(
            operation_id=OperationId(uid(1)),
            actor=self.context(),
            intended_deliverable="August 21 listening transcript",
        )

        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.intended_deliverable = "changed"  # type: ignore[misc]

    def test_a_command_rejects_empty_canonical_text(self) -> None:
        for bad in ("", "carriage\rreturn"):
            with self.subTest(text=bad):
                with self.assertRaises(ValidationError):
                    commands.CreateProduction(
                        operation_id=OperationId(uid(1)),
                        actor=self.context(),
                        intended_deliverable=bad,
                    )


if __name__ == "__main__":
    unittest.main()
