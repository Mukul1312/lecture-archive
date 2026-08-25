"""Command-input manifests: the semantic idempotency key of design 9.4.

The manifest is a mechanical walk of every command field — operation id,
actor, and expected version included — so "identical replay" means an
identical command, never a convenient subset. These tests pin the label
grammar for all 27 commands, the encoder's type discipline, and that every
field (however deeply nested) reaches the digest.
"""

from __future__ import annotations

import dataclasses
import enum
import unittest

from heritage_production.application import commands
from heritage_production.application.idempotency import (
    command_input_digest,
    command_input_manifest,
    command_label,
    command_name,
    command_result_digest,
    manifest_value,
    result_label,
)
from heritage_production.domain.release import ReleasePolicyRules
from heritage_production.domain.review import FindingDecision
from heritage_production.domain.shared import (
    ActorId,
    OperationId,
    ReleasePolicyVersionId,
    ReviewFindingId,
    ValidationError,
    canonical_json,
)
from heritage_production.domain.release import SUPPORTED_EVALUATOR_REF

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    attested_credential,
    uid,
)


# Every design 9.2 command and its exact input-manifest label. A new command,
# a renamed command, or a changed kebab-case rule must amend this table.
EXPECTED_LABELS = {
    "CreateProduction": "heritage-command-create-production-v1",
    "AttachSourceRecording": "heritage-command-attach-source-recording-v1",
    "ImportProposalPackage": "heritage-command-import-proposal-package-v1",
    "CreateInitialTranscriptEdition": "heritage-command-create-initial-transcript-edition-v1",
    "SelectCandidateEdition": "heritage-command-select-candidate-edition-v1",
    "CreateReleasePolicyVersion": "heritage-command-create-release-policy-version-v1",
    "SelectReleasePolicyVersion": "heritage-command-select-release-policy-version-v1",
    "ConfigureExternalGates": "heritage-command-configure-external-gates-v1",
    "RegisterRubric": "heritage-command-register-rubric-v1",
    "RegisterActorCredential": "heritage-command-register-actor-credential-v1",
    "OpenReviewRound": "heritage-command-open-review-round-v1",
    "ExportReviewPackage": "heritage-command-export-review-package-v1",
    "ImportReviewSubmission": "heritage-command-import-review-submission-v1",
    "SubmitReviewFinding": "heritage-command-submit-review-finding-v1",
    "FinalizeReviewSubmission": "heritage-command-finalize-review-submission-v1",
    "DecideReviewFinding": "heritage-command-decide-review-finding-v1",
    "RecordReviewSignOff": "heritage-command-record-review-sign-off-v1",
    "CloseReviewRound": "heritage-command-close-review-round-v1",
    "CreateSuccessorTranscriptEdition": "heritage-command-create-successor-transcript-edition-v1",
    "AssembleReleaseContent": "heritage-command-assemble-release-content-v1",
    "RecordExternalSignOff": "heritage-command-record-external-sign-off-v1",
    "AssembleReleaseCandidate": "heritage-command-assemble-release-candidate-v1",
    "EvaluateReleaseEligibility": "heritage-command-evaluate-release-eligibility-v1",
    "ApproveReleaseCandidate": "heritage-command-approve-release-candidate-v1",
    "ExportApprovedRelease": "heritage-command-export-approved-release-v1",
    "RecordProductionAuthorityCutover": "heritage-command-record-production-authority-cutover-v1",
    "SupersedePreWriteCutover": "heritage-command-supersede-pre-write-cutover-v1",
}


def steward_context() -> commands.ActorContext:
    return commands.ActorContext(actor(20))


def create_production_command(
    suffix: int = 1, deliverable: str = "August 21 listening transcript"
) -> commands.CreateProduction:
    return commands.CreateProduction(
        operation_id=OperationId(uid(suffix)),
        actor=steward_context(),
        intended_deliverable=deliverable,
    )


def decide_finding_command(
    *,
    decision: FindingDecision = FindingDecision.REJECTED,
    rationale: str | None = "the cited span does not contain the quoted words",
    expected_version: int = 1,
) -> commands.DecideReviewFinding:
    return commands.DecideReviewFinding(
        operation_id=OperationId(uid(2)),
        actor=steward_context(),
        review_finding_id=ReviewFindingId(uid(3)),
        decision=decision,
        rationale=rationale,
        expected_version=expected_version,
    )


def empty_rules() -> ReleasePolicyRules:
    return ReleasePolicyRules(
        required_integrity_checks=(),
        uncertainty_allowances=(),
        blocking_finding_rules=(),
        review_coverage_requirements=(),
        review_signoff_requirements=(),
        external_signoff_requirements=(),
        required_release_members=(),
        maximum_unresolved_findings=0,
    )


def create_policy_command(rules: ReleasePolicyRules | None = None) -> commands.CreateReleasePolicyVersion:
    return commands.CreateReleasePolicyVersion(
        operation_id=OperationId(uid(4)),
        actor=steward_context(),
        release_policy_version_id=ReleasePolicyVersionId(uid(5)),
        semantic_label="pilot-transcript-policy",
        policy_schema_version=1,
        policy_schema_code="heritage-transcript-policy-v1",
        evaluator_ref=SUPPORTED_EVALUATOR_REF,
        rules=rules if rules is not None else empty_rules(),
    )


class CommandLabelTests(unittest.TestCase):
    def test_every_design_command_has_the_exact_expected_label(self) -> None:
        for name, expected in EXPECTED_LABELS.items():
            with self.subTest(command=name):
                self.assertEqual(command_label(getattr(commands, name)), expected)

    def test_the_label_table_covers_all_27_commands(self) -> None:
        self.assertEqual(len(EXPECTED_LABELS), 27)

    def test_result_labels_are_the_input_labels_with_a_result_marker(self) -> None:
        self.assertEqual(
            result_label(commands.CreateProduction),
            "heritage-command-create-production-result-v1",
        )
        self.assertEqual(
            result_label(commands.RecordReviewSignOff),
            "heritage-command-record-review-sign-off-result-v1",
        )

    def test_labels_accept_an_instance_as_well_as_a_class(self) -> None:
        command = create_production_command()

        self.assertEqual(command_label(command), EXPECTED_LABELS["CreateProduction"])
        self.assertEqual(command_name(command), "CreateProduction")

    def test_a_type_whose_name_is_not_camel_case_is_rejected(self) -> None:
        weird = type("bad_name", (object,), {})

        with self.assertRaises(ValidationError):
            command_label(weird)


class _Suit(enum.Enum):
    HEARTS = "hearts"
    SPADES = "spades"


class _Rank(enum.Enum):
    HEARTS = "hearts"


@dataclasses.dataclass(frozen=True, slots=True)
class _Point:
    x: int
    y: int


@dataclasses.dataclass(frozen=True, slots=True)
class _Spot:
    x: int
    y: int


@dataclasses.dataclass(frozen=True, slots=True)
class _Nested:
    label: str
    corners: tuple[_Point, ...]
    suit: _Suit


def encoded(value: object) -> bytes:
    return canonical_json(manifest_value(value))


class ManifestValueEncodingTests(unittest.TestCase):
    def test_primitives_pass_through_unchanged(self) -> None:
        self.assertIsNone(manifest_value(None))
        self.assertIs(manifest_value(True), True)
        self.assertEqual(manifest_value(7), 7)
        self.assertEqual(manifest_value("seven"), "seven")

    def test_a_bool_never_collides_with_the_matching_integer(self) -> None:
        self.assertNotEqual(encoded(True), encoded(1))
        self.assertNotEqual(encoded(False), encoded(0))

    def test_tuples_encode_in_order(self) -> None:
        self.assertEqual(manifest_value((1, 2)), [1, 2])
        self.assertNotEqual(encoded((1, 2)), encoded((2, 1)))

    def test_a_dataclass_encodes_its_type_and_every_field(self) -> None:
        self.assertEqual(
            manifest_value(_Point(1, 2)),
            {"kind": "value", "type": "_Point", "fields": {"x": 1, "y": 2}},
        )

    def test_same_shaped_dataclasses_of_different_types_never_collide(self) -> None:
        self.assertNotEqual(encoded(_Point(1, 2)), encoded(_Spot(1, 2)))

    def test_an_enum_encodes_its_type_and_member_name(self) -> None:
        self.assertEqual(
            manifest_value(_Suit.HEARTS),
            {"kind": "enum", "type": "_Suit", "member": "HEARTS"},
        )

    def test_same_named_members_of_different_enums_never_collide(self) -> None:
        self.assertNotEqual(encoded(_Suit.HEARTS), encoded(_Rank.HEARTS))

    def test_a_string_backed_enum_never_collides_with_its_string_value(self) -> None:
        # FindingDecision subclasses str; only exact-type checks keep the
        # enum member and the bare string "accepted" digest-distinct.
        self.assertNotEqual(encoded(FindingDecision.ACCEPTED), encoded("accepted"))

    def test_nesting_encodes_recursively(self) -> None:
        value = manifest_value(_Nested("cell", (_Point(1, 2),), _Suit.SPADES))

        self.assertEqual(value["fields"]["label"], "cell")
        self.assertEqual(value["fields"]["corners"][0]["fields"], {"x": 1, "y": 2})
        self.assertEqual(value["fields"]["suit"]["member"], "SPADES")

    def test_unsupported_values_are_rejected(self) -> None:
        for bad in (1.5, [1], {"a": 1}, {1, 2}, b"raw", object()):
            with self.subTest(value=bad):
                with self.assertRaises(ValidationError):
                    manifest_value(bad)


class CommandInputManifestTests(unittest.TestCase):
    def test_the_manifest_names_the_command_and_lists_every_field(self) -> None:
        for command in (
            create_production_command(),
            decide_finding_command(),
            create_policy_command(),
            commands.RegisterActorCredential(
                operation_id=OperationId(uid(6)),
                actor=steward_context(),
                credential=attested_credential(3),
            ),
        ):
            with self.subTest(command=type(command).__name__):
                manifest = command_input_manifest(command)

                self.assertEqual(manifest["command"], type(command).__name__)
                self.assertEqual(
                    set(manifest["inputs"]),
                    {field.name for field in dataclasses.fields(command)},
                )

    def test_the_digest_is_deterministic_for_equal_commands(self) -> None:
        self.assertEqual(
            command_input_digest(create_production_command()),
            command_input_digest(create_production_command()),
        )

    def test_the_operation_id_reaches_the_digest(self) -> None:
        self.assertNotEqual(
            command_input_digest(create_production_command(suffix=1)),
            command_input_digest(create_production_command(suffix=7)),
        )

    def test_the_actor_reaches_the_digest(self) -> None:
        command = create_production_command()
        other = dataclasses.replace(command, actor=commands.ActorContext(actor(21)))

        self.assertNotEqual(command_input_digest(command), command_input_digest(other))

    def test_the_expected_version_reaches_the_digest(self) -> None:
        self.assertNotEqual(
            command_input_digest(decide_finding_command(expected_version=1)),
            command_input_digest(decide_finding_command(expected_version=2)),
        )

    def test_an_enum_field_reaches_the_digest(self) -> None:
        self.assertNotEqual(
            command_input_digest(decide_finding_command(decision=FindingDecision.REJECTED)),
            command_input_digest(
                decide_finding_command(decision=FindingDecision.ACCEPTED)
            ),
        )

    def test_an_optional_field_reaches_the_digest(self) -> None:
        self.assertNotEqual(
            command_input_digest(
                decide_finding_command(
                    decision=FindingDecision.ACCEPTED, rationale=None
                )
            ),
            command_input_digest(
                decide_finding_command(
                    decision=FindingDecision.ACCEPTED, rationale="minor wording"
                )
            ),
        )

    def test_a_deeply_nested_field_reaches_the_digest(self) -> None:
        """One integer at the bottom of the policy rules changes the key."""
        deep = dataclasses.replace(empty_rules(), maximum_unresolved_findings=1)

        self.assertNotEqual(
            command_input_digest(create_policy_command(empty_rules())),
            command_input_digest(create_policy_command(deep)),
        )

    def test_commands_with_identical_inputs_still_get_distinct_digests(self) -> None:
        """The command name separates otherwise identical manifests."""

        @dataclasses.dataclass(frozen=True, slots=True)
        class AlphaCommand:
            operation_id: OperationId
            actor: commands.ActorContext

        @dataclasses.dataclass(frozen=True, slots=True)
        class BravoCommand:
            operation_id: OperationId
            actor: commands.ActorContext

        self.assertNotEqual(
            command_input_digest(AlphaCommand(OperationId(uid(8)), steward_context())),
            command_input_digest(BravoCommand(OperationId(uid(8)), steward_context())),
        )

    def test_a_non_command_value_is_rejected(self) -> None:
        for bad in (_Point(1, 2), "CreateProduction", None):
            with self.subTest(value=bad):
                with self.assertRaises(ValidationError):
                    command_input_digest(bad)

    # These helper classes are named in plain CamelCase on purpose. A leading
    # underscore would fail the label grammar first, and the envelope guard
    # under test would never run -- the test would pass for the wrong reason.

    def test_a_command_shaped_value_with_a_loose_operation_id_is_rejected(self) -> None:
        """Everything else is valid, so only the operation-id guard can catch it."""

        @dataclasses.dataclass(frozen=True, slots=True)
        class LooseOperationIdCommand:
            operation_id: str
            actor: commands.ActorContext

        with self.assertRaises(ValidationError):
            command_input_digest(LooseOperationIdCommand(uid(1), steward_context()))

    def test_a_command_shaped_value_with_a_loose_actor_is_rejected(self) -> None:
        """Everything else is valid, so only the actor guard can catch it."""

        @dataclasses.dataclass(frozen=True, slots=True)
        class LooseActorCommand:
            operation_id: OperationId
            actor: ActorId

        with self.assertRaises(ValidationError):
            command_input_digest(LooseActorCommand(OperationId(uid(1)), actor(20)))

    def test_a_non_dataclass_carrying_a_valid_envelope_is_rejected(self) -> None:
        """A well-named object with a good envelope still has no fields to walk."""

        class WellNamedCommand:
            def __init__(self) -> None:
                self.operation_id = OperationId(uid(1))
                self.actor = steward_context()

        with self.assertRaises(ValidationError):
            command_input_digest(WellNamedCommand())

    def test_a_command_class_is_not_a_command_instance(self) -> None:
        """Hashing the class would key every replay of it to one digest."""
        with self.assertRaises(ValidationError):
            command_input_digest(commands.CreateProduction)

    def test_a_class_whose_defaults_form_a_valid_envelope_is_rejected(self) -> None:
        """Class-level defaults must never stand in for a real command.

        Every real command is slotted, so its class exposes slot descriptors
        rather than values and the envelope guards would catch it anyway. An
        unslotted class with defaults is the case where rejecting a *type* is
        the only thing between class defaults and a valid-looking digest.
        """
        context = steward_context()

        @dataclasses.dataclass(frozen=True)
        class DefaultedCommand:
            operation_id: OperationId = OperationId(uid(1))
            actor: commands.ActorContext = context

        with self.assertRaises(ValidationError):
            command_input_digest(DefaultedCommand)


class CommandResultDigestTests(unittest.TestCase):
    def test_a_result_digest_is_deterministic(self) -> None:
        command = create_production_command()

        self.assertEqual(
            command_result_digest(command, {"production_id": uid(9)}),
            command_result_digest(command, {"production_id": uid(9)}),
        )

    def test_the_result_label_separates_commands(self) -> None:
        payload = {"outcome": "sealed"}

        self.assertNotEqual(
            command_result_digest(commands.CreateProduction, payload),
            command_result_digest(commands.RegisterRubric, payload),
        )

    def test_a_result_payload_must_be_a_json_object(self) -> None:
        for bad in (None, "done", 7, [1]):
            with self.subTest(payload=bad):
                with self.assertRaises(ValidationError):
                    command_result_digest(commands.CreateProduction, bad)

    def test_a_result_payload_never_carries_a_self_digest(self) -> None:
        with self.assertRaises(ValidationError):
            command_result_digest(commands.CreateProduction, {"digest": "sha256"})


if __name__ == "__main__":
    unittest.main()
