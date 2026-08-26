"""Production creation, sources, selections, gates, sign-offs, and candidates."""

from __future__ import annotations

import unittest

from heritage_production.domain.production import (
    AttachedSource,
    EditionSelection,
    ExternalGateRequirement,
    ExternalGateSet,
    ExternalSignOff,
    ExternalSignOffTarget,
    Production,
)
from heritage_production.domain.shared import (
    ActorAssuranceEvidence,
    ActorId,
    AssuranceLevel,
    DomainEventId,
    EditionRef,
    ExternalGateSetId,
    GateCode,
    GateScope,
    InvariantError,
    ProductionId,
    ReleaseCandidateId,
    ReleasePolicyVersionId,
    RoleCode,
    SignatureProof,
    SignOffDecision,
    SignOffTargetKind,
    SignOffTargetRule,
    SourceRecordingRef,
    SourceVersionRef,
    StaleReferenceError,
    TranscriptEditionId,
    ValidationError,
)

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    default_edition_evidence,
    artifact,
    attested_credential,
    closed_review,
    digest,
    edition_ref,
    production_id,
    source_version,
    successor_edition_ref,
    uid,
    verified_credential,
)
from tests.heritage_production.test_production_gates import (
    FINGERPRINT,
    gate_set_id,
    verified_sign_off,
)
from heritage_production.domain.release import ReleaseMember
from heritage_production.domain.shared import ManifestMemberRole
from tests.heritage_production.test_release_content import seal_candidate, seal_content
from tests.heritage_production.test_release_policy import (
    EVALUATOR,
    empty_rules,
    seal_policy,
)
from heritage_production.domain.release import IntegrityCheckCode, ReleasePolicyRules
from heritage_production.domain.release import ReleasePolicyVersion


def alternate_policy() -> ReleasePolicyVersion:
    """A genuinely distinct sealed policy: different identity and rule set."""
    return ReleasePolicyVersion.seal(
        release_policy_version_id=ReleasePolicyVersionId(uid(95)),
        semantic_label="alternate-transcript-policy",
        policy_schema_version=1,
        policy_schema_code="heritage-transcript-policy-v1",
        evaluator_ref=EVALUATOR,
        rules=ReleasePolicyRules(
            required_integrity_checks=(IntegrityCheckCode("object-digests"),),
            uncertainty_allowances=(),
            blocking_finding_rules=(),
            review_coverage_requirements=(),
            review_signoff_requirements=(),
            external_signoff_requirements=(),
            required_release_members=(),
            maximum_unresolved_findings=0,
        ),
        author_actor_id=actor(20),
        created_at_us=1_700_000_000_000_030,
    )


STEWARD = actor(20)


def event_id(suffix: int) -> DomainEventId:
    return DomainEventId(uid(600 + suffix))


def new_production() -> Production:
    production = Production.create(
        production_id=production_id(),
        intended_deliverable="August 21 listening transcript",
        steward_actor_id=STEWARD,
        created_at_us=1_700_000_000_000_000,
        event_id=event_id(0),
        event_occurred_at_us=1_700_000_000_000_001,
    )
    production.pull_events()
    return production


def attached_source(
    version: SourceVersionRef | None = None, *, media_digest: str = "2"
) -> AttachedSource:
    resolved = version or source_version(character=media_digest)
    return AttachedSource(
        SourceRecordingRef(resolved.source_recording_id, {"title": "SSGGSM 1985-08-21"}),
        resolved,
        artifact(200, media_digest, "audio/mpeg"),
        STEWARD,
        1_700_000_000_000_002,
    )


def sourced_production() -> tuple[Production, AttachedSource]:
    production = new_production()
    source = attached_source()
    production.attach_source(
        attached_source=source,
        event_id=event_id(1),
        event_occurred_at_us=1_700_000_000_000_003,
    )
    production.pull_events()
    return production, source


def selection_for(
    source: AttachedSource, *, edition: EditionRef | None = None
) -> EditionSelection:
    return EditionSelection(
        production_id(), edition or edition_ref(), (source.source_version_ref,)
    )


def gate_set(requirements: tuple[ExternalGateRequirement, ...] = ()) -> ExternalGateSet:
    return ExternalGateSet.seal(
        external_gate_set_id=gate_set_id(),
        production_id=production_id(),
        requirements=requirements,
        configured_by=STEWARD,
        configured_at_us=1_700_000_000_000_004,
    )


def rights_holder_gate() -> ExternalGateRequirement:
    return ExternalGateRequirement(
        GateCode("rights-holder-approval"),
        GateScope.EXTERNAL_RELEASE,
        RoleCode("rights-holder"),
        verified_credential(40, FINGERPRINT),
        AssuranceLevel.VERIFIED_SIGNATURE,
        SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
    )


def configured_production(
    *, requirements: tuple[ExternalGateRequirement, ...] = ()
) -> tuple[Production, object, object]:
    """Return a Production with an attached source, edition, policy, and gates."""
    production, source = sourced_production()
    production.select_candidate_edition(
        selection=selection_for(source),
        event_id=event_id(2),
        event_occurred_at_us=1_700_000_000_000_005,
    )
    policy = seal_policy(empty_rules())
    production.select_release_policy(
        policy=policy,
        event_id=event_id(3),
        event_occurred_at_us=1_700_000_000_000_006,
    )
    gates = gate_set(requirements)
    production.configure_external_gates(
        gate_set=gates,
        event_id=event_id(4),
        event_occurred_at_us=1_700_000_000_000_007,
    )
    production.pull_events()
    # Release content must seal the derived digest of the evidence the
    # evaluator will later be handed, or the snapshot refuses it.
    content = seal_content(
        policy_ref=policy.ref,
        gate_set_ref=gates.ref,
        provenance_input_digests=(default_edition_evidence().semantic_digest,),
        integrity_input_digests=(),
    )
    return production, policy, content


class ProductionCreationTests(unittest.TestCase):
    def test_create_binds_identity_steward_and_emits_its_fact(self) -> None:
        production = Production.create(
            production_id=production_id(),
            intended_deliverable="August 21 listening transcript",
            steward_actor_id=STEWARD,
            created_at_us=1_700_000_000_000_000,
            event_id=event_id(0),
            event_occurred_at_us=1_700_000_000_000_001,
        )

        events = production.pull_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ProductionCreated")
        self.assertEqual(
            events[0].payload,
            {
                "production_id": production_id().value,
                "steward_actor_id": STEWARD.value,
            },
        )
        self.assertIsNone(production.approval)
        self.assertEqual(production.sources, ())

    def test_intended_deliverable_must_be_nonempty_canonical_text(self) -> None:
        for description in ("", "carriage\rreturn"):
            with self.subTest(description=description):
                with self.assertRaises(ValidationError):
                    Production.create(
                        production_id=production_id(),
                        intended_deliverable=description,
                        steward_actor_id=STEWARD,
                        created_at_us=1,
                        event_id=event_id(0),
                        event_occurred_at_us=1,
                    )

    def test_state_is_behavior_only(self) -> None:
        production = new_production()

        with self.assertRaises(AttributeError):
            production.selected_edition_ref = edition_ref()  # type: ignore[misc]


class AttachSourceTests(unittest.TestCase):
    def test_attaching_a_source_records_it_and_emits_its_fact(self) -> None:
        production = new_production()
        source = attached_source()

        production.attach_source(
            attached_source=source,
            event_id=event_id(1),
            event_occurred_at_us=1_700_000_000_000_003,
        )

        events = production.pull_events()
        self.assertEqual(production.sources, (source,))
        self.assertEqual(events[0].event_type, "SourceRecordingAttached")
        self.assertEqual(
            events[0].payload["source_version_id"],
            source.source_version_ref.source_version_id.value,
        )

    def test_recording_identity_and_artifact_digest_must_agree(self) -> None:
        version = source_version()
        with self.assertRaises(ValidationError):
            AttachedSource(
                SourceRecordingRef(source_version(suffix=9).source_recording_id, {}),
                version,
                artifact(200, "2", "audio/mpeg"),
                STEWARD,
                1,
            )
        with self.assertRaises(ValidationError):
            AttachedSource(
                SourceRecordingRef(version.source_recording_id, {}),
                version,
                artifact(200, "9", "audio/mpeg"),
                STEWARD,
                1,
            )

    def test_exact_duplicate_attachment_is_a_silent_no_op(self) -> None:
        production, source = sourced_production()

        production.attach_source(
            attached_source=source,
            event_id=event_id(9),
            event_occurred_at_us=1_700_000_000_000_009,
        )

        self.assertEqual(production.sources, (source,))
        self.assertEqual(production.pull_events(), ())

    def test_same_identity_with_conflicting_content_is_rejected(self) -> None:
        production, source = sourced_production()
        conflicting = AttachedSource(
            source.source_recording_ref,
            SourceVersionRef(
                source.source_version_ref.source_version_id,
                source.source_version_ref.source_recording_id,
                digest("9"),
                60_000_000,
                "integer microseconds",
            ),
            artifact(200, "9", "audio/mpeg"),
            STEWARD,
            1_700_000_000_000_010,
        )

        with self.assertRaises(ValidationError):
            production.attach_source(
                attached_source=conflicting,
                event_id=event_id(10),
                event_occurred_at_us=1_700_000_000_000_011,
            )

        self.assertEqual(production.sources, (source,))
        self.assertEqual(production.pull_events(), ())


class EditionSelectionTests(unittest.TestCase):
    def test_selection_must_name_this_production(self) -> None:
        production, source = sourced_production()
        foreign = EditionSelection(
            ProductionId(uid(555)), edition_ref(), (source.source_version_ref,)
        )

        with self.assertRaises(ValidationError):
            production.select_candidate_edition(
                selection=foreign,
                event_id=event_id(2),
                event_occurred_at_us=1,
            )

    def test_selection_must_use_only_attached_source_versions(self) -> None:
        production, _ = sourced_production()
        unattached = EditionSelection(
            production_id(), edition_ref(), (source_version(suffix=77, character="8"),)
        )

        with self.assertRaises(ValidationError):
            production.select_candidate_edition(
                selection=unattached,
                event_id=event_id(2),
                event_occurred_at_us=1,
            )

    def test_selecting_the_same_edition_again_is_a_no_op(self) -> None:
        production, source = sourced_production()
        selection = selection_for(source)
        production.select_candidate_edition(
            selection=selection, event_id=event_id(2), event_occurred_at_us=1
        )
        production.pull_events()

        production.select_candidate_edition(
            selection=selection, event_id=event_id(11), event_occurred_at_us=2
        )

        self.assertEqual(production.pull_events(), ())

    def test_same_edition_id_with_a_conflicting_digest_is_rejected(self) -> None:
        production, source = sourced_production()
        production.select_candidate_edition(
            selection=selection_for(source), event_id=event_id(2), event_occurred_at_us=1
        )
        production.pull_events()
        tampered = selection_for(
            source,
            edition=EditionRef(
                edition_ref().transcript_edition_id, digest("7")
            ),
        )

        with self.assertRaises(ValidationError):
            production.select_candidate_edition(
                selection=tampered, event_id=event_id(12), event_occurred_at_us=2
            )

    def test_changing_the_selection_clears_the_candidate_but_keeps_history(self) -> None:
        production, policy, content = configured_production()
        candidate = seal_candidate(content)
        production.assemble_candidate(
            candidate=candidate,
            content=content,
            event_id=event_id(5),
            event_occurred_at_us=1,
        )
        production.pull_events()
        self.assertEqual(production.active_candidate_ref, candidate.ref)

        successor = EditionSelection(
            production_id(),
            EditionRef(TranscriptEditionId(uid(999)), digest("7")),
            (production.sources[0].source_version_ref,),
        )
        production.select_candidate_edition(
            selection=successor, event_id=event_id(13), event_occurred_at_us=2
        )

        self.assertIsNone(production.active_candidate_ref)
        self.assertEqual(production.candidates, (candidate,))
        self.assertEqual(
            production.pull_events()[0].event_type, "CandidateEditionSelected"
        )


class PolicyAndGateSelectionTests(unittest.TestCase):
    def test_policy_selection_emits_its_fact_and_is_idempotent(self) -> None:
        production, source = sourced_production()
        policy = seal_policy(empty_rules())

        production.select_release_policy(
            policy=policy, event_id=event_id(3), event_occurred_at_us=1
        )
        events = production.pull_events()
        self.assertEqual(events[0].event_type, "ReleasePolicyVersionSelected")
        self.assertEqual(production.selected_policy_ref, policy.ref)

        production.select_release_policy(
            policy=policy, event_id=event_id(14), event_occurred_at_us=2
        )
        self.assertEqual(production.pull_events(), ())

    def test_explicit_empty_gate_set_is_configurable(self) -> None:
        production, _, _ = configured_production()

        self.assertEqual(production.active_gate_set.requirements, ())
        self.assertEqual(len(production.gate_sets), 1)

    def test_configuring_gates_appends_and_never_rewrites_history(self) -> None:
        production, _, _ = configured_production()
        first = production.active_gate_set
        second = ExternalGateSet.seal(
            external_gate_set_id=ExternalGateSetId(uid(31)),
            production_id=production_id(),
            requirements=(rights_holder_gate(),),
            configured_by=STEWARD,
            configured_at_us=1_700_000_000_000_020,
        )

        production.configure_external_gates(
            gate_set=second, event_id=event_id(15), event_occurred_at_us=3
        )

        self.assertEqual(production.gate_sets, (first, second))
        self.assertEqual(production.active_gate_set_ref, second.ref)
        self.assertEqual(
            production.pull_events()[0].event_type, "ExternalGateSetConfigured"
        )

    def test_gate_set_must_belong_to_this_production(self) -> None:
        production, _ = sourced_production()
        foreign = ExternalGateSet.seal(
            external_gate_set_id=gate_set_id(),
            production_id=ProductionId(uid(555)),
            requirements=(),
            configured_by=STEWARD,
            configured_at_us=1,
        )

        with self.assertRaises(ValidationError):
            production.configure_external_gates(
                gate_set=foreign, event_id=event_id(16), event_occurred_at_us=1
            )


class ExternalSignOffTests(unittest.TestCase):
    def content_sign_off(
        self, content: object, *, decision: SignOffDecision = SignOffDecision.APPROVED
    ) -> ExternalSignOff:
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        return verified_sign_off(target=target, decision=decision)

    def test_recording_a_gate_bound_sign_off_emits_its_fact(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        sign_off = self.content_sign_off(content)

        production.record_external_sign_off(
            sign_off=sign_off,
            content=content,
            event_id=event_id(6),
            event_occurred_at_us=1,
        )

        self.assertEqual(production.external_sign_offs, (sign_off,))
        self.assertEqual(
            production.pull_events()[0].event_type, "ExternalSignOffRecorded"
        )

    def test_a_declined_sign_off_is_retained_as_evidence(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        declined = self.content_sign_off(content, decision=SignOffDecision.DECLINED)

        production.record_external_sign_off(
            sign_off=declined,
            content=content,
            event_id=event_id(6),
            event_occurred_at_us=1,
        )

        self.assertEqual(production.external_sign_offs, (declined,))

    def test_sign_off_without_a_matching_active_gate_is_rejected(self) -> None:
        production, _, content = configured_production()
        sign_off = self.content_sign_off(content)

        with self.assertRaises(ValidationError):
            production.record_external_sign_off(
                sign_off=sign_off,
                content=content,
                event_id=event_id(6),
                event_occurred_at_us=1,
            )
        self.assertEqual(production.external_sign_offs, ())
        self.assertEqual(production.pull_events(), ())

    def test_sign_off_for_other_release_content_is_rejected(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        foreign_content = seal_content(
            evidence=closed_review(),
            policy_ref=production.selected_policy_ref,
            gate_set_ref=production.active_gate_set_ref,
            release_members=(
                ReleaseMember(ManifestMemberRole("transcript-json"), artifact(80, "1")),
            ),
        )
        self.assertNotEqual(
            foreign_content.content_manifest_ref, content.content_manifest_ref
        )
        sign_off = self.content_sign_off(foreign_content)

        with self.assertRaises(ValidationError):
            production.record_external_sign_off(
                sign_off=sign_off,
                content=content,
                event_id=event_id(6),
                event_occurred_at_us=1,
            )

    def test_exact_duplicate_sign_off_is_a_no_op(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        sign_off = self.content_sign_off(content)
        production.record_external_sign_off(
            sign_off=sign_off, content=content, event_id=event_id(6), event_occurred_at_us=1
        )
        production.pull_events()

        production.record_external_sign_off(
            sign_off=sign_off,
            content=content,
            event_id=event_id(17),
            event_occurred_at_us=2,
        )

        self.assertEqual(production.external_sign_offs, (sign_off,))
        self.assertEqual(production.pull_events(), ())

    def test_foreign_production_sign_off_is_rejected(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        target = ExternalSignOffTarget(
            SignOffTargetKind.RELEASE_CONTENT, content.content_manifest_ref, None, None
        )
        foreign = verified_sign_off(target=target, owner=ProductionId(uid(555)))

        with self.assertRaises(ValidationError):
            production.record_external_sign_off(
                sign_off=foreign,
                content=content,
                event_id=event_id(6),
                event_occurred_at_us=1,
            )


class CandidateAssemblyTests(unittest.TestCase):
    def test_assembly_appends_selects_and_emits_its_fact(self) -> None:
        production, _, content = configured_production()
        candidate = seal_candidate(content)

        production.assemble_candidate(
            candidate=candidate,
            content=content,
            event_id=event_id(5),
            event_occurred_at_us=1,
        )

        self.assertEqual(production.candidates, (candidate,))
        self.assertEqual(production.active_candidate_ref, candidate.ref)
        self.assertEqual(
            production.pull_events()[0].event_type, "ReleaseCandidateAssembled"
        )

    def test_incomplete_sign_off_set_is_representable(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        candidate = seal_candidate(content)

        production.assemble_candidate(
            candidate=candidate,
            content=content,
            event_id=event_id(5),
            event_occurred_at_us=1,
        )

        self.assertEqual(candidate.included_sign_off_digests, ())
        self.assertEqual(production.active_candidate_ref, candidate.ref)

    def test_semantically_identical_reassembly_reuses_the_snapshot(self) -> None:
        production, _, content = configured_production()
        candidate = seal_candidate(content)
        production.assemble_candidate(
            candidate=candidate, content=content, event_id=event_id(5), event_occurred_at_us=1
        )
        production.pull_events()

        replay = seal_candidate(content, candidate_id=ReleaseCandidateId(uid(52)))
        production.assemble_candidate(
            candidate=replay, content=content, event_id=event_id(18), event_occurred_at_us=2
        )

        self.assertEqual(production.candidates, (candidate,))
        self.assertEqual(production.active_candidate_ref, candidate.ref)
        self.assertEqual(production.pull_events(), ())

    def test_changed_sign_offs_append_a_new_snapshot_and_retain_the_old(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        first = seal_candidate(content)
        production.assemble_candidate(
            candidate=first, content=content, event_id=event_id(5), event_occurred_at_us=1
        )
        sign_off = ExternalSignOffTests().content_sign_off(content)
        production.record_external_sign_off(
            sign_off=sign_off, content=content, event_id=event_id(6), event_occurred_at_us=2
        )
        production.pull_events()

        second = seal_candidate(
            content,
            sign_off_digests=(sign_off.sign_off_digest,),
            candidate_id=ReleaseCandidateId(uid(53)),
        )
        production.assemble_candidate(
            candidate=second, content=content, event_id=event_id(19), event_occurred_at_us=3
        )

        self.assertEqual(production.candidates, (first, second))
        self.assertEqual(production.active_candidate_ref, second.ref)

    def test_candidate_must_bind_the_currently_selected_graph(self) -> None:
        production, policy, content = configured_production()
        stale_content = seal_content(
            policy_ref=policy.ref,
            gate_set_ref=production.active_gate_set_ref,
        )
        production.select_release_policy(
            policy=alternate_policy(),
            event_id=event_id(20),
            event_occurred_at_us=4,
        )
        production.pull_events()
        other_gate_set = ExternalGateSet.seal(
            external_gate_set_id=ExternalGateSetId(uid(31)),
            production_id=production_id(),
            requirements=(rights_holder_gate(),),
            configured_by=STEWARD,
            configured_at_us=5,
        )
        production.configure_external_gates(
            gate_set=other_gate_set, event_id=event_id(21), event_occurred_at_us=5
        )
        production.pull_events()

        with self.assertRaises(StaleReferenceError):
            production.assemble_candidate(
                candidate=seal_candidate(stale_content),
                content=stale_content,
                event_id=event_id(22),
                event_occurred_at_us=6,
            )
        self.assertEqual(production.candidates, ())
        self.assertEqual(production.pull_events(), ())

    def test_candidate_sign_offs_must_already_exist_on_this_production(self) -> None:
        production, _, content = configured_production(
            requirements=(rights_holder_gate(),)
        )
        sign_off = ExternalSignOffTests().content_sign_off(content)
        candidate = seal_candidate(content, sign_off_digests=(sign_off.sign_off_digest,))

        with self.assertRaises(ValidationError):
            production.assemble_candidate(
                candidate=candidate,
                content=content,
                event_id=event_id(5),
                event_occurred_at_us=1,
            )

    def test_assembly_requires_an_explicit_active_gate_set(self) -> None:
        production, source = sourced_production()
        production.select_candidate_edition(
            selection=selection_for(source), event_id=event_id(2), event_occurred_at_us=1
        )
        policy = seal_policy(empty_rules())
        production.select_release_policy(
            policy=policy, event_id=event_id(3), event_occurred_at_us=2
        )
        production.pull_events()
        content = seal_content(policy_ref=policy.ref)

        with self.assertRaises(InvariantError):
            production.assemble_candidate(
                candidate=seal_candidate(content),
                content=content,
                event_id=event_id(5),
                event_occurred_at_us=3,
            )


class ProductionReconstitutionTests(unittest.TestCase):
    def test_reconstitute_restores_state_without_emitting_events(self) -> None:
        production, _, content = configured_production()
        candidate = seal_candidate(content)
        production.assemble_candidate(
            candidate=candidate, content=content, event_id=event_id(5), event_occurred_at_us=1
        )
        production.pull_events()

        restored = Production.reconstitute(
            production_id=production.production_id,
            intended_deliverable=production.intended_deliverable,
            steward_actor_id=production.steward_actor_id,
            created_at_us=production.created_at_us,
            sources=production.sources,
            edition_selection=production.edition_selection,
            selected_policy_ref=production.selected_policy_ref,
            gate_sets=production.gate_sets,
            active_gate_set_ref=production.active_gate_set_ref,
            external_sign_offs=production.external_sign_offs,
            candidates=production.candidates,
            active_candidate_ref=production.active_candidate_ref,
            approval=None,
        )

        self.assertEqual(restored.pull_events(), ())
        self.assertEqual(restored.active_candidate_ref, candidate.ref)
        self.assertEqual(restored.candidates, (candidate,))

    def test_reconstitute_rejects_an_active_ref_without_its_record(self) -> None:
        production, _, content = configured_production()
        candidate = seal_candidate(content)

        with self.assertRaises(ValidationError):
            Production.reconstitute(
                production_id=production.production_id,
                intended_deliverable=production.intended_deliverable,
                steward_actor_id=production.steward_actor_id,
                created_at_us=production.created_at_us,
                sources=production.sources,
                edition_selection=production.edition_selection,
                selected_policy_ref=production.selected_policy_ref,
                gate_sets=production.gate_sets,
                active_gate_set_ref=production.active_gate_set_ref,
                external_sign_offs=production.external_sign_offs,
                candidates=(),
                active_candidate_ref=candidate.ref,
                approval=None,
            )

    def test_reconstitute_rejects_duplicate_child_identities(self) -> None:
        production, source = sourced_production()

        with self.assertRaises(ValidationError):
            Production.reconstitute(
                production_id=production.production_id,
                intended_deliverable=production.intended_deliverable,
                steward_actor_id=production.steward_actor_id,
                created_at_us=production.created_at_us,
                sources=(source, source),
                edition_selection=None,
                selected_policy_ref=None,
                gate_sets=(),
                active_gate_set_ref=None,
                external_sign_offs=(),
                candidates=(),
                active_candidate_ref=None,
                approval=None,
            )

    def test_lifecycle_phase_is_a_projection_not_a_status_field(self) -> None:
        production, _, content = configured_production()

        self.assertEqual(production.lifecycle_phase, "TRANSCRIPT_SELECTED")
        self.assertFalse(hasattr(production, "status"))

        production.assemble_candidate(
            candidate=seal_candidate(content),
            content=content,
            event_id=event_id(5),
            event_occurred_at_us=1,
        )
        production.pull_events()
        self.assertEqual(production.lifecycle_phase, "CANDIDATE_ASSEMBLED")


if __name__ == "__main__":
    unittest.main()
