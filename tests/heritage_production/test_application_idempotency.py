"""Command-input manifests: the semantic idempotency key of design 9.4.

The manifest is a mechanical walk of every command field — operation id,
actor, and expected version included — so "identical replay" means an
identical command, never a convenient subset. These tests pin the label
grammar for all 27 commands, the encoder's type discipline, and that every
field (however deeply nested) reaches the digest.
"""

from __future__ import annotations

import collections
import dataclasses
import enum
import typing
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
    semantic_digest,
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
        for bad in (1.5, [1], {"a": 1}, {1, 2}, object()):
            with self.subTest(value=bad):
                with self.assertRaises(ValidationError):
                    manifest_value(bad)

    def test_bytes_encode_losslessly(self) -> None:
        """SourceRecordingRef stores canonical JSON bytes as a real field."""
        self.assertEqual(
            manifest_value(b"\x00\xffab"),
            {"kind": "bytes", "hex": "00ff6162"},
        )

    def test_different_bytes_never_collide(self) -> None:
        self.assertNotEqual(encoded(b"ab"), encoded(b"ba"))
        self.assertNotEqual(encoded(b""), encoded(b"\x00"))

    def test_bytes_never_collide_with_their_own_hex_text(self) -> None:
        """Tagging keeps b'\\xab' distinct from the string 'ab'."""
        self.assertNotEqual(encoded(b"\xab"), encoded("ab"))

    def test_a_tuple_subclass_is_not_treated_as_a_tuple(self) -> None:
        """A NamedTuple encoded as a bare list would lose its type identity."""
        Pair = collections.namedtuple("Pair", "x y")

        with self.assertRaises(ValidationError):
            manifest_value(Pair(1, 2))

    def test_a_dataclass_class_is_not_a_dataclass_value(self) -> None:
        """Nested, not just at the top level: a class carries no field values.

        `_Point` is slotted, so its class exposes slot descriptors and would
        be refused even without the type check -- passing for the wrong
        reason. An unslotted class with defaults encodes cleanly under a
        missing type check, so it is what actually pins the guard.
        """

        @dataclasses.dataclass(frozen=True)
        class DefaultedPoint:
            x: int = 1
            y: int = 2

        for candidate in (_Point, DefaultedPoint):
            with self.subTest(candidate=candidate.__name__):
                with self.assertRaises(ValidationError):
                    manifest_value(candidate)
                with self.assertRaises(ValidationError):
                    manifest_value((candidate,))


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

    def test_an_operation_id_subclass_is_not_an_exact_operation_id(self) -> None:
        """`isinstance` here would let a subclass with extra state through."""

        class SubtleOperationId(OperationId):
            __slots__ = ()

        @dataclasses.dataclass(frozen=True, slots=True)
        class SubclassEnvelopeCommand:
            operation_id: OperationId
            actor: commands.ActorContext

        with self.assertRaises(ValidationError):
            command_input_digest(
                SubclassEnvelopeCommand(SubtleOperationId(uid(1)), steward_context())
            )

    def test_an_actor_context_subclass_is_not_an_exact_actor_context(self) -> None:
        class SubtleContext(commands.ActorContext):
            __slots__ = ()

        @dataclasses.dataclass(frozen=True, slots=True)
        class SubclassActorCommand:
            operation_id: OperationId
            actor: commands.ActorContext

        with self.assertRaises(ValidationError):
            command_input_digest(
                SubclassActorCommand(OperationId(uid(1)), SubtleContext(actor(20)))
            )

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


class CommandTypeReachabilityTests(unittest.TestCase):
    """Every type reachable from a command field must be encodable.

    `command_input_digest` runs before anything else in `run_operation`, so a
    command whose field graph contains a type the encoder rejects cannot enter
    the idempotent path at all -- it is unusable, not merely unhashable. This
    walks the annotations statically, so a command or domain value that grows
    an unencodable field fails here rather than at the first real call.
    """

    # Fields annotated exactly `object` hold validated domain values whose
    # concrete type the annotation does not name, so static walking cannot
    # clear them. Each is listed deliberately; a NEW one must be added here
    # only after checking the runtime value is encodable.
    KNOWN_OBJECT_FIELDS = {
        ("ClosedReviewEvidence", "findings"),
        ("ImportedFindingRef", "client_finding_nonce"),
        ("ImportedFindingRef", "review_finding_id"),
        ("ReviewClosureSnapshot", "findings"),
        ("ReviewSubmissionSummary", "raw_result_artifact"),
    }

    ENCODABLE_SCALARS = {bool, int, str, bytes, type(None)}

    def concrete_types(self, annotation) -> set:
        origin = typing.get_origin(annotation)
        if origin is None:
            return {annotation} if isinstance(annotation, type) else set()
        found: set = set()
        for arg in typing.get_args(annotation):
            if arg is not Ellipsis:
                found |= self.concrete_types(arg)
        return found

    def walk(self, tp: type, seen: dict, object_fields: set) -> None:
        if tp in seen:
            return
        if tp in self.ENCODABLE_SCALARS:
            seen[tp] = "scalar"
            return
        if isinstance(tp, type) and issubclass(tp, enum.Enum):
            seen[tp] = "enum"
            return
        if tp is object:
            seen[tp] = "object"
            return
        if not dataclasses.is_dataclass(tp):
            seen[tp] = "UNENCODABLE"
            return
        seen[tp] = "dataclass"
        hints = typing.get_type_hints(tp)
        for field in dataclasses.fields(tp):
            annotation = hints.get(field.name, field.type)
            concrete = self.concrete_types(annotation)
            if object in concrete:
                object_fields.add((tp.__name__, field.name))
            for member in concrete:
                self.walk(member, seen, object_fields)

    def analyse(self) -> tuple[dict, set]:
        seen: dict = {}
        object_fields: set = set()
        for name in EXPECTED_LABELS:
            command = getattr(commands, name)
            hints = typing.get_type_hints(command)
            for field in dataclasses.fields(command):
                annotation = hints.get(field.name, field.type)
                for member in self.concrete_types(annotation):
                    self.walk(member, seen, object_fields)
        return seen, object_fields

    def test_no_command_reaches_an_unencodable_type(self) -> None:
        seen, _ = self.analyse()
        unencodable = sorted(
            f"{tp.__module__}.{tp.__name__}"
            for tp, kind in seen.items()
            if kind == "UNENCODABLE"
        )

        self.assertEqual(unencodable, [], f"unencodable types reachable: {unencodable}")

    def test_the_reachable_graph_is_actually_walked(self) -> None:
        """Guards the guard: a walk that reached nothing would pass vacuously."""
        seen, _ = self.analyse()

        self.assertGreater(len(seen), 100)
        self.assertIn(bytes, seen)

    def test_object_annotated_fields_are_the_known_set(self) -> None:
        _, object_fields = self.analyse()

        self.assertEqual(object_fields, self.KNOWN_OBJECT_FIELDS)


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


class LabelDomainSeparationTests(unittest.TestCase):
    """The digest functions must use their own label, not merely define one.

    Asserting `command_label()` and `result_label()` as pure functions leaves
    which label each digest actually *uses* untested -- so an input digest
    computed under the result label, or the reverse, would go unnoticed and
    collapse the separation that keeps a result from replaying as an input.
    """

    def test_the_input_digest_is_computed_under_the_input_label(self) -> None:
        command = create_production_command()

        self.assertEqual(
            command_input_digest(command),
            semantic_digest(command_label(command), command_input_manifest(command)),
        )

    def test_the_result_digest_is_computed_under_the_result_label(self) -> None:
        payload = {"production_id": uid(9)}

        self.assertEqual(
            command_result_digest(commands.CreateProduction, payload),
            semantic_digest(result_label(commands.CreateProduction), payload),
        )

    def test_a_result_payload_shaped_like_an_input_manifest_never_collides(self) -> None:
        """The one property the labels exist to guarantee."""
        command = create_production_command()
        manifest = command_input_manifest(command)

        self.assertNotEqual(
            command_result_digest(command, manifest),
            command_input_digest(command),
        )


if __name__ == "__main__":
    unittest.main()
