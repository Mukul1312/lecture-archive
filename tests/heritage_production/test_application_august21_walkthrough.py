"""The August-21 pilot, sanitized, driven through to a selected edition.

Design 9.2 steps 1-5 in order: create the Production, attach the exact source
version, import the legacy ASR package through the anti-corruption adapter,
seal the first transcript edition, select it as the candidate, and select the
release policy and external gate set.

The package here is synthetic but shaped like the real one design 10.4
describes: an `asr-full.metadata.json` carrying absolute audio and model-cache
locators, an observed model name `small` with no pinned revision, and no
configuration digest. No real media, transcript, or path from the archive is
read or referenced -- the point is the *shape*, and a sanitized fixture is the
only kind that belongs in source control.

What this checkpoint is for is the joins. Each handler has its own tests; only
a walkthrough shows that the provenance actually chains -- that the edition
the steward selects can be traced back through the sealed edition, the
proposal set, the raw package, and the operator-bound source version, with
every link a digest rather than a name.
"""

from __future__ import annotations

import unittest

from heritage_production.application.errors import ReplayIntegrityError
from heritage_production.domain.production import EditionSelection
from heritage_production.domain.release import ExternalGateRequirement
from heritage_production.domain.shared import (
    ArtifactId,
    AssuranceLevel,
    ContentDigest,
    GateCode,
    GateScope,
    RoleCode,
    SignOffTargetKind,
    SignOffTargetRule,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptScope,
    ValidationError,
)
from heritage_production.domain.transcription import (
    ConfidenceEvidence,
    ConfigurationEvidence,
    EvidenceStatus,
    IdentityEvidence,
    ProposalItem,
    ProposalItemRef,
    ProvenanceStatus,
    RawRowLocator,
    RevisionLineage,
    SegmentRevision,
    StewardAttestation,
)
from heritage_production.domain.shared import (
    ProposalItemId,
    SegmentId,
    SegmentRevisionId,
    TranscriptText,
)

from heritage_production.application.ports.adapters import TranslatedProposal
from tests.heritage_production.application_harness import (
    STEWARD,
    ApplicationHarness,
)
from tests.heritage_production.heritage_release_fixtures import (
    uid,
    verified_credential,
)
from tests.heritage_production.test_transcript_editions import initial_manifest


# A sanitized stand-in for the pilot's asr-full.metadata.json. The absolute
# locators are the point: design 10.4 keeps them as non-authoritative observed
# evidence and refuses to dereference them as authority.
LEGACY_PACKAGE = (
    b'{"audio":"/Volumes/archive/ggsm/1985-08-21/source.mp3",'
    b'"model_cache":"/Users/operator/.cache/whisper",'
    b'"model":"small",'
    b'"segments":[{"start":0,"end":600000000,"text":"om namo bhagavate"}]}'
)

# The source version the *operator* selected and hashed, independently of
# anything the package says about its own audio.
AUGUST_21 = SourceVersionRef(
    SourceVersionId(uid(1985)),
    SourceRecordingId(uid(821)),
    ContentDigest("sha256", "a1" * 32),
    600_000_000,
    "microseconds",
)

SEGMENT_SPAN = SourceSpan(AUGUST_21, 0, 600_000_000)


def legacy_translation(raw_package) -> TranslatedProposal:
    """What the adapter may honestly conclude from that package.

    Observed, not verified: the package names a model but pins no revision and
    records no configuration. Design 10.4 forbids inferring a revision from
    the observed name, so those stay UNKNOWN and become warnings instead.
    """
    return TranslatedProposal(
        raw_package=raw_package,
        package_schema_version=1,
        tool_identity=IdentityEvidence(EvidenceStatus.OBSERVED, "whisper"),
        model_name=IdentityEvidence(EvidenceStatus.OBSERVED, "small"),
        model_revision=IdentityEvidence(EvidenceStatus.UNKNOWN, None),
        configuration=ConfigurationEvidence(EvidenceStatus.UNKNOWN, None),
        provenance_status=ProvenanceStatus.LEGACY_ATTESTED,
        missing_field_warnings=(
            "asr-full.metadata.json declares an absolute audio locator",
            "asr-full.metadata.json declares an absolute model-cache locator",
            "no pinned model revision is recorded for the observed model name",
        ),
        items=(
            ProposalItem(
                proposal_item_id=ProposalItemId(uid(1001)),
                source_span=SEGMENT_SPAN,
                proposed_text=TranscriptText("om namo bhagavate"),
                language="sa",
                speaker_hypothesis=None,
                confidence_evidence=(ConfidenceEvidence("posterior", "0.71"),),
                raw_row_locator=RawRowLocator("asr-full.metadata.json#segments=0"),
            ),
        ),
        quarantined=False,
        quarantine_reason=None,
    )


def steward_attestation() -> StewardAttestation:
    """Design 10.4: the steward binds source.mp3 the package cannot vouch for."""
    return StewardAttestation(
        STEWARD,
        "Legacy export predates model pinning; source bound and hashed by the steward",
        1_700_000_000_000_000,
        ContentDigest("sha256", "b2" * 32),
    )


def rights_holder_gate() -> ExternalGateRequirement:
    return ExternalGateRequirement(
        GateCode("rights-holder-approval"),
        GateScope.EXTERNAL_RELEASE,
        RoleCode("rights-holder"),
        verified_credential(40, ContentDigest("sha256", "c3" * 32)),
        AssuranceLevel.VERIFIED_SIGNATURE,
        SignOffTargetRule(SignOffTargetKind.RELEASE_CONTENT),
    )


class Walkthrough:
    """Design 9.2 steps 1-5, each step returning what the next one needs."""

    def __init__(self, harness: ApplicationHarness | None = None) -> None:
        self.harness = harness or ApplicationHarness()
        self.package = self.harness.artifacts.seed(
            ArtifactId(uid(1900)), LEGACY_PACKAGE
        )
        self.harness.translator.result = legacy_translation(self.package)

    def run(self) -> "Walkthrough":
        self.production = self.harness.create(
            deliverable="August 21 1985 listening transcript"
        ).result
        self.production_id = self.production.production_id

        self.attached = self.harness.attach(
            self.production_id, AUGUST_21, expected_version=1
        ).result

        self.proposal_set = self.harness.import_package(
            self.package,
            AUGUST_21,
            steward_attestation=steward_attestation(),
        ).result

        self.revision = SegmentRevision.create(
            segment_id=SegmentId(uid(1100)),
            segment_revision_id=SegmentRevisionId(uid(1101)),
            source_span=SEGMENT_SPAN,
            text=TranscriptText("om namo bhagavate"),
            language="sa",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.proposal_derived(
                (ProposalItemRef(self.proposal_set.ref, ProposalItemId(uid(1001))),)
            ),
        )
        self.scope = TranscriptScope((AUGUST_21,), (SEGMENT_SPAN,), ())
        self.edition = self.harness.create_initial_edition(
            self.production_id,
            source_versions=(AUGUST_21,),
            transcript_scope=self.scope,
            proposal_set_refs=(self.proposal_set.ref,),
            revisions=(self.revision,),
            gaps=(),
            change_manifest=initial_manifest(self.revision),
        ).result

        self.selected = self.harness.select_edition(
            self.production_id,
            EditionSelection(
                production_id=self.production_id,
                edition_ref=self.edition.ref,
                source_version_refs=(AUGUST_21,),
            ),
            expected_version=2,
        ).result

        self.policy = self.harness.create_policy().result
        self.harness.select_policy(
            self.production_id, self.policy.ref, expected_version=3
        )
        self.gate_set = self.harness.configure_gates(
            self.production_id, (rights_holder_gate(),), expected_version=4
        ).result
        return self

    def current(self):
        return self.harness.productions.rows[self.production_id]


class AugustTwentyFirstWalkthroughTests(unittest.TestCase):
    def test_the_pilot_reaches_a_selected_candidate_edition(self) -> None:
        walk = Walkthrough().run()

        (production, version) = walk.current()
        self.assertEqual(production.lifecycle_phase, "TRANSCRIPT_SELECTED")
        self.assertEqual(version, 5)
        self.assertEqual(production.selected_edition_ref, walk.edition.ref)
        self.assertEqual(production.selected_policy_ref, walk.policy.ref)
        self.assertEqual(production.active_gate_set_ref, walk.gate_set)

    def test_provenance_chains_by_digest_from_edition_back_to_source(self) -> None:
        """Every link is a digest, so none of them is a name that can drift."""
        walk = Walkthrough().run()

        # Selected edition -> sealed edition
        self.assertEqual(walk.selected.content_digest, walk.edition.semantic_digest)
        # Edition -> proposal set
        self.assertEqual(walk.edition.proposal_set_refs, (walk.proposal_set.ref,))
        self.assertEqual(
            walk.proposal_set.ref.content_digest, walk.proposal_set.semantic_digest
        )
        # Proposal set -> raw package bytes
        self.assertEqual(walk.proposal_set.raw_artifact, walk.package)
        self.assertEqual(
            walk.proposal_set.package_digest, walk.package.content_digest
        )
        # Proposal set -> the source the operator bound, not the one claimed
        self.assertEqual(walk.proposal_set.source_version, AUGUST_21)
        self.assertEqual(walk.attached.source_version_ref, AUGUST_21)
        self.assertEqual(
            walk.attached.artifact.content_digest, AUGUST_21.artifact_digest
        )

    def test_the_import_stays_attested_rather_than_complete(self) -> None:
        walk = Walkthrough().run()

        self.assertEqual(
            walk.proposal_set.provenance_status, ProvenanceStatus.LEGACY_ATTESTED
        )
        self.assertIsNotNone(walk.proposal_set.steward_attestation)
        self.assertEqual(walk.proposal_set.steward_attestation.actor_id, STEWARD)
        self.assertEqual(len(walk.proposal_set.missing_field_warnings), 3)

    def test_the_observed_model_never_becomes_a_pinned_revision(self) -> None:
        """The specific inference design 10.4 forbids by name."""
        walk = Walkthrough().run()

        self.assertEqual(walk.proposal_set.model_name.status, EvidenceStatus.OBSERVED)
        self.assertEqual(walk.proposal_set.model_name.value, "small")
        self.assertEqual(
            walk.proposal_set.model_revision.status, EvidenceStatus.UNKNOWN
        )
        self.assertIsNone(walk.proposal_set.model_revision.value)
        self.assertEqual(
            walk.proposal_set.configuration.status, EvidenceStatus.UNKNOWN
        )

    def test_the_absolute_locators_survive_only_as_raw_evidence(self) -> None:
        """The package is kept verbatim; nothing dereferences its paths."""
        walk = Walkthrough().run()

        stored = walk.harness.artifacts.open(walk.package.artifact_id)
        self.assertIn(b"/Volumes/archive", stored)
        self.assertEqual(walk.proposal_set.raw_artifact.content_digest,
                         ContentDigest.from_bytes(LEGACY_PACKAGE))
        # ...and none of it reached the bound source version.
        self.assertEqual(walk.proposal_set.source_version.artifact_digest,
                         AUGUST_21.artifact_digest)

    def test_the_gate_set_is_explicitly_chosen_and_not_empty(self) -> None:
        """A Task 5 residual: the pilot must never quietly select no gates."""
        walk = Walkthrough().run()

        (production, _) = walk.current()
        active = [
            gate_set
            for gate_set in production.gate_sets
            if gate_set.ref == production.active_gate_set_ref
        ]
        self.assertEqual(len(active), 1)
        self.assertEqual(len(active[0].requirements), 1)
        self.assertEqual(
            active[0].requirements[0].role, RoleCode("rights-holder")
        )


class WalkthroughTransactionTests(unittest.TestCase):
    def test_every_transaction_wrote_at_most_one_aggregate_root(self) -> None:
        """Design 9.3, asserted across the whole sequence rather than per call."""
        walk = Walkthrough().run()

        for index, unit in enumerate(walk.harness.units):
            with self.subTest(transaction=index):
                self.assertLessEqual(len(unit._root_writes), 1)

    def test_every_step_committed_exactly_once(self) -> None:
        walk = Walkthrough().run()

        for index, unit in enumerate(walk.harness.units):
            with self.subTest(transaction=index):
                self.assertEqual(unit.commits, 1)
                self.assertEqual(unit.rollbacks, 0)

    def test_the_operation_log_records_every_content_producing_step(self) -> None:
        walk = Walkthrough().run()

        recorded = sorted(
            record.command_name for record in walk.harness.recorder.records.values()
        )
        self.assertEqual(
            recorded,
            [
                "AttachSourceRecording",
                "ConfigureExternalGates",
                "CreateInitialTranscriptEdition",
                "CreateProduction",
                "CreateReleasePolicyVersion",
                "ImportProposalPackage",
                "SelectCandidateEdition",
                "SelectReleasePolicyVersion",
            ],
        )

    def test_the_event_stream_matches_the_required_sequence(self) -> None:
        walk = Walkthrough().run()

        self.assertEqual(
            walk.harness.events.names(),
            (
                "ProductionCreated",
                "SourceRecordingAttached",
                "TranscriptEditionCreated",
                "CandidateEditionSelected",
                "ReleasePolicyVersionSelected",
                "ExternalGateSetConfigured",
            ),
        )


class WalkthroughIdempotencyTests(unittest.TestCase):
    """Replay is stable for sealed roots and current-state-bound for mutable ones.

    A sealed root cannot drift, so its recorded result describes it forever and
    a replay returns it whenever it is asked. A mutable root's result payload
    projects the state that operation produced, so once later operations have
    advanced the root, an *earlier* operation can no longer reproduce what it
    recorded -- and says so instead of handing back a stale answer.

    That is a deliberate reading of design 9.4's "an identical replay returns
    the original result", and the C5 review should confirm it: the literal
    reading would have replay always succeed, which is only reachable by
    projecting so little state that replay verifies almost nothing. Failing
    closed never returns a wrong answer; the cost is that re-running an old
    script raises rather than reporting "already done".
    """

    def test_replaying_the_most_recent_step_is_a_no_op(self) -> None:
        """The real retry case: a step reissued before anything else moves."""
        walk = Walkthrough().run()
        before = walk.current()

        again = walk.harness.configure_gates(
            walk.production_id, (rights_holder_gate(),), expected_version=4
        )

        self.assertTrue(again.replayed)
        self.assertEqual(again.result, walk.gate_set)
        self.assertEqual(walk.current(), before)
        self.assertEqual(len(walk.harness.events.events), 6)

    def test_replaying_a_sealed_root_step_stays_stable_afterwards(self) -> None:
        """Sealed roots never drift, so their replays keep working."""
        walk = Walkthrough().run()

        imported = walk.harness.import_package(
            walk.package, AUGUST_21, steward_attestation=steward_attestation()
        )
        edition = walk.harness.create_initial_edition(
            walk.production_id,
            source_versions=(AUGUST_21,),
            transcript_scope=walk.scope,
            proposal_set_refs=(walk.proposal_set.ref,),
            revisions=(walk.revision,),
            gaps=(),
            change_manifest=initial_manifest(walk.revision),
        )
        policy = walk.harness.create_policy()

        for name, outcome, expected in (
            ("proposal set", imported, walk.proposal_set),
            ("edition", edition, walk.edition),
            ("policy", policy, walk.policy),
        ):
            with self.subTest(root=name):
                self.assertTrue(outcome.replayed)
                self.assertIs(outcome.result, expected)
        self.assertEqual(len(walk.harness.proposals.rows), 1)
        self.assertEqual(len(walk.harness.editions.rows), 1)
        self.assertEqual(len(walk.harness.policies.rows), 1)

    def test_replaying_an_earlier_mutable_step_fails_closed(self) -> None:
        """The Production has moved on, so step 1's result no longer holds."""
        walk = Walkthrough().run()

        with self.assertRaises(ReplayIntegrityError):
            walk.harness.create(deliverable="August 21 1985 listening transcript")

        self.assertEqual(walk.current()[1], 5)
        self.assertEqual(len(walk.harness.productions.rows), 1)

    def test_a_failed_replay_writes_nothing(self) -> None:
        """Failing closed must stay a refusal, not a partial second run."""
        walk = Walkthrough().run()
        before = (
            dict(walk.harness.productions.rows),
            len(walk.harness.recorder.records),
            len(walk.harness.events.events),
        )

        with self.assertRaises(ReplayIntegrityError):
            walk.harness.create(deliverable="August 21 1985 listening transcript")

        self.assertEqual(
            (
                dict(walk.harness.productions.rows),
                len(walk.harness.recorder.records),
                len(walk.harness.events.events),
            ),
            before,
        )

    def test_a_second_import_of_the_same_package_under_a_new_operation(self) -> None:
        """A different operation id is a different import, not a replay."""
        walk = Walkthrough().run()

        with self.assertRaises(Exception) as caught:
            walk.harness.import_package(
                walk.package,
                AUGUST_21,
                suffix=40,
                steward_attestation=steward_attestation(),
            )

        # The proposal-set id is unchanged, and sealed roots are add-once.
        self.assertIn(
            type(caught.exception).__name__,
            {"InvariantError", "OperationConflictError"},
        )
        self.assertEqual(len(walk.harness.proposals.rows), 1)


class WalkthroughRefusalTests(unittest.TestCase):
    def test_a_quarantined_import_stops_the_pilot_before_any_edition(self) -> None:
        harness = ApplicationHarness()
        walk = Walkthrough(harness)
        translation = legacy_translation(walk.package)
        harness.translator.result = type(translation)(
            **{
                **{f: getattr(translation, f) for f in translation.__slots__},
                "quarantined": True,
                "quarantine_reason": "the operator supplied no independently bound source",
            }
        )
        harness.create(deliverable="August 21 1985 listening transcript")
        production_id = next(iter(harness.productions.rows))
        harness.attach(production_id, AUGUST_21, expected_version=1)

        with self.assertRaises(Exception):
            harness.import_package(
                walk.package, AUGUST_21, steward_attestation=steward_attestation()
            )

        self.assertEqual(harness.proposals.rows, {})
        self.assertEqual(harness.editions.rows, {})

    def test_a_legacy_import_without_the_steward_attestation_stops_the_pilot(self) -> None:
        harness = ApplicationHarness()
        walk = Walkthrough(harness)
        harness.create(deliverable="August 21 1985 listening transcript")
        production_id = next(iter(harness.productions.rows))
        harness.attach(production_id, AUGUST_21, expected_version=1)

        with self.assertRaises(ValidationError):
            harness.import_package(walk.package, AUGUST_21)

        self.assertEqual(harness.proposals.rows, {})
        self.assertEqual(harness.editions.rows, {})
        self.assertEqual(len(harness.recorder.records), 2)


if __name__ == "__main__":
    unittest.main()
