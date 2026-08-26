"""CreateSuccessorTranscriptEdition — where accepted review becomes a successor.

Design 9.2 step 9: an accepted correction never alters an edition, it
justifies a new one. Step 10: prior review remains historical evidence but
cannot authorize the successor. Both are rules about two aggregates at once,
so the domain cannot enforce either -- `TranscriptEdition` sees finding
*references*, never findings.

This handler therefore refuses a successor justified by a finding that does
not exist, was rejected, was never decided, or was raised against a different
edition. It also binds the parent manifest to the parent that is actually
stored: the manifest self-verifies its content against its own EditionRef, so
it cannot misdescribe *some* edition -- but nothing in the domain says which
edition, and one describing an edition that was never sealed is well-formed.
"""

from __future__ import annotations

import dataclasses
import unittest

from heritage_production.domain.review import (
    FindingDecision,
    ReviewFinding,
    ReviewRound,
)
from heritage_production.domain.shared import (
    ActorId,
    ArtifactId,
    ContentDigest,
    DomainEventId,
    EditionRef,
    PolicyRefusalError,
    ProductionId,
    ReviewFindingId,
    SegmentRevisionId,
    StaleReferenceError,
    TranscriptEditionId,
    TranscriptText,
    ValidationError,
)
from heritage_production.domain.transcription import (
    EditionChange,
    EditionChangeManifest,
    FindingChangeRef,
    FindingMapping,
    ParentEditionManifest,
    RevisionLineage,
    SegmentRevision,
)

from tests.heritage_production.application_harness import ApplicationHarness
from tests.heritage_production.heritage_release_fixtures import (
    _disposition_digest,
    uid,
)
from tests.heritage_production.test_application_edition_handler import (
    revision_from,
)
from tests.heritage_production.test_application_import_handler import (
    PACKAGE_BYTES,
    complete_translation,
)
from tests.heritage_production.test_review_findings import submit_finding
from tests.heritage_production.test_review_rounds import make_target
from tests.heritage_production.test_transcript_editions import initial_manifest
from tests.heritage_production.test_transcription_proposals import SOURCE


STEWARD = ActorId(uid(40))


class Fixture:
    """A sealed parent edition plus one accepted finding raised against it."""

    def __init__(self) -> None:
        self.harness = ApplicationHarness()
        created = self.harness.create()
        self.production_id = created.result.production_id
        self.harness.attach(self.production_id, SOURCE)
        package = self.harness.artifacts.seed(ArtifactId(uid(310)), PACKAGE_BYTES)
        self.harness.translator.result = complete_translation(package)
        self.proposal_set = self.harness.import_package(package, SOURCE).result
        self.revision = revision_from(self.proposal_set)
        self.parent = self.harness.create_initial_edition(
            self.production_id,
            source_versions=(SOURCE,),
            transcript_scope=self.scope(),
            proposal_set_refs=(self.proposal_set.ref,),
            revisions=(self.revision,),
            gaps=(),
            change_manifest=initial_manifest(self.revision),
        ).result
        self.finding, self.change_ref = self.accepted_finding_on(self.parent)

    def scope(self):
        from heritage_production.domain.shared import SourceSpan, TranscriptScope

        return TranscriptScope((SOURCE,), (SourceSpan(SOURCE, 0, 10_000),), ())

    def accepted_finding_on(
        self,
        edition,
        *,
        decision: FindingDecision = FindingDecision.ACCEPTED,
        decide: bool = True,
        finding_suffix: int = 900,
    ) -> tuple[ReviewFinding, FindingChangeRef]:
        """Raise a finding against `edition` and decide it as the steward."""
        target = make_target(edition_ref=edition.ref)
        round_ = ReviewRound.open(
            review_round_id=target.review_round_id,
            production_id=target.production_id,
            edition_ref=target.edition_ref,
            target_manifest=target,
            rubric_ref=target.rubric_ref,
            package_schema_version=1,
            reviewer_assignments=(),
            sign_off_requirements=(),
            opened_by=ActorId(uid(21)),
            opened_at_us=1,
            event_id=DomainEventId(uid(22)),
            event_occurred_at_us=2,
        )
        round_.pull_events()
        finding = submit_finding(
            round_, review_finding_id=ReviewFindingId(uid(finding_suffix))
        )
        finding.pull_events()
        digest = ContentDigest("sha256", "0" * 64)
        if decide:
            digest = _disposition_digest(finding, decision, "Apply", STEWARD, 50)
            finding.record_disposition(
                context=round_.open_context(),
                decision=decision,
                rationale="Apply",
                steward_actor_id=STEWARD,
                decided_at_us=50,
                disposition_digest=digest,
                event_id=DomainEventId(uid(41)),
                event_occurred_at_us=51,
            )
            finding.pull_events()
        self.harness.store_finding(finding)
        return finding, FindingChangeRef(
            finding.review_finding_id, finding.finding_payload_digest, digest
        )

    def parent_manifest(self) -> ParentEditionManifest:
        return ParentEditionManifest.from_edition(self.parent, ())

    def corrected(self) -> SegmentRevision:
        old = self.parent.revisions[0]
        return SegmentRevision.create(
            segment_id=old.segment_id,
            segment_revision_id=SegmentRevisionId(uid(370)),
            source_span=old.source_span,
            text=TranscriptText("Namaste, corrected"),
            language="sa",
            speaker="speaker-1",
            uncertainty_marks=(),
            lineage=RevisionLineage.corrected_from(self.parent.ref, old.ref),
        )

    def successor(self, *, change_ref: FindingChangeRef | None = None, **overrides):
        corrected = self.corrected()
        ref = change_ref if change_ref is not None else self.change_ref
        values = dict(
            parent=self.parent_manifest(),
            source_versions=(SOURCE,),
            transcript_scope=self.scope(),
            proposal_set_refs=(),
            revisions=(corrected,),
            gaps=(),
            change_manifest=EditionChangeManifest(
                (EditionChange.correction(self.parent.revisions[0].ref, corrected.ref),),
                (FindingMapping.applied(ref, (corrected.ref,)),),
            ),
        )
        values.update(overrides)
        return self.harness.create_successor_edition(self.production_id, **values)


class CreateSuccessorTranscriptEditionTests(unittest.TestCase):
    def test_it_seals_a_successor_bound_to_its_parent(self) -> None:
        fixture = Fixture()

        outcome = fixture.successor()

        stored = fixture.harness.editions.get(TranscriptEditionId(uid(790)))
        self.assertIs(outcome.result, stored)
        self.assertEqual(stored.parent_edition_ref, fixture.parent.ref)
        self.assertEqual(stored.production_id, fixture.production_id)

    def test_the_parent_edition_is_left_untouched(self) -> None:
        """An accepted correction never alters an edition (design 9.2 step 9)."""
        fixture = Fixture()
        before = fixture.parent.semantic_digest

        fixture.successor()

        parent = fixture.harness.editions.get(fixture.parent.transcript_edition_id)
        self.assertEqual(parent.semantic_digest, before)
        self.assertEqual(parent.revisions, (fixture.revision,))

    def test_it_publishes_a_creation_event_naming_the_parent(self) -> None:
        fixture = Fixture()

        outcome = fixture.successor()

        event = fixture.harness.events.events[-1]
        self.assertEqual(event.event_type, "TranscriptEditionCreated")
        self.assertEqual(
            event.payload["parent_edition_digest"],
            fixture.parent.semantic_digest.hex_digest,
        )
        self.assertEqual(
            event.payload["edition_digest"], outcome.result.semantic_digest.hex_digest
        )

    def test_a_replay_returns_the_original_successor(self) -> None:
        fixture = Fixture()
        first = fixture.successor()

        again = fixture.successor()

        self.assertTrue(again.replayed)
        self.assertIs(again.result, first.result)
        self.assertEqual(len(fixture.harness.editions.rows), 2)


class AcceptedFindingAuthorityTests(unittest.TestCase):
    """Step 10: prior review is evidence; only accepted findings authorize."""

    def test_a_rejected_finding_cannot_authorize_a_successor(self) -> None:
        fixture = Fixture()
        _, rejected = fixture.accepted_finding_on(
            fixture.parent,
            decision=FindingDecision.REJECTED,
            finding_suffix=901,
        )

        with self.assertRaises(PolicyRefusalError):
            fixture.successor(change_ref=rejected)

        self.assertEqual(len(fixture.harness.editions.rows), 1)

    def test_an_undecided_finding_cannot_authorize_a_successor(self) -> None:
        fixture = Fixture()
        _, undecided = fixture.accepted_finding_on(
            fixture.parent, decide=False, finding_suffix=902
        )

        with self.assertRaises(PolicyRefusalError):
            fixture.successor(change_ref=undecided)

        self.assertEqual(len(fixture.harness.editions.rows), 1)

    def test_a_finding_raised_against_another_edition_is_refused(self) -> None:
        """Review of a different edition is historical evidence, not authority."""
        fixture = Fixture()
        other = fixture.harness.create_initial_edition(
            fixture.production_id,
            edition_suffix=785,
            suffix=26,
            source_versions=(SOURCE,),
            transcript_scope=fixture.scope(),
            proposal_set_refs=(fixture.proposal_set.ref,),
            revisions=(fixture.revision,),
            gaps=(),
            change_manifest=initial_manifest(fixture.revision),
        ).result
        _, foreign = fixture.accepted_finding_on(other, finding_suffix=903)

        with self.assertRaises(PolicyRefusalError):
            fixture.successor(change_ref=foreign)

    def test_a_finding_that_was_never_stored_is_refused(self) -> None:
        fixture = Fixture()
        missing = FindingChangeRef(
            ReviewFindingId(uid(904)),
            fixture.finding.finding_payload_digest,
            fixture.change_ref.disposition_digest,
        )

        with self.assertRaises(StaleReferenceError):
            fixture.successor(change_ref=missing)

    def test_a_forged_payload_digest_is_refused(self) -> None:
        fixture = Fixture()
        forged = FindingChangeRef(
            fixture.finding.review_finding_id,
            ContentDigest("sha256", "e" * 64),
            fixture.change_ref.disposition_digest,
        )

        with self.assertRaises(StaleReferenceError):
            fixture.successor(change_ref=forged)

    def test_a_forged_disposition_digest_is_refused(self) -> None:
        fixture = Fixture()
        forged = FindingChangeRef(
            fixture.finding.review_finding_id,
            fixture.finding.finding_payload_digest,
            ContentDigest("sha256", "e" * 64),
        )

        with self.assertRaises(StaleReferenceError):
            fixture.successor(change_ref=forged)


class ParentManifestTests(unittest.TestCase):
    """The manifest restates the parent, so it is rebuilt rather than believed."""

    def test_a_parent_that_was_never_sealed_is_refused(self) -> None:
        fixture = Fixture()
        phantom = dataclasses.replace(
            fixture.parent_manifest(),
            edition_ref=EditionRef(
                TranscriptEditionId(uid(997)), fixture.parent.semantic_digest
            ),
        )

        with self.assertRaises(StaleReferenceError):
            fixture.successor(parent=phantom)

        self.assertEqual(len(fixture.harness.editions.rows), 1)

    def test_a_manifest_cannot_misdescribe_the_edition_it_names(self) -> None:
        """A domain guarantee this handler leans on, so it is pinned here.

        `ParentEditionManifest` recomputes its content digest and refuses to
        exist unless it equals its own `EditionRef`. That is why the handler
        checks only *which* edition the manifest names, and does not re-verify
        field by field what it says about it.
        """
        fixture = Fixture()

        for field, value in (
            ("production_id", ProductionId(uid(998))),
            ("source_versions", ()),
            ("revisions", ()),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    dataclasses.replace(fixture.parent_manifest(), **{field: value})

    def test_a_parent_belonging_to_another_production_is_refused(self) -> None:
        """Both Productions exist, so only the comparison can refuse this."""
        fixture = Fixture()
        second = fixture.harness.create(suffix=30).result
        corrected = fixture.corrected()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.create_successor_edition(
                second.production_id,
                fixture.parent_manifest(),
                source_versions=(SOURCE,),
                transcript_scope=fixture.scope(),
                proposal_set_refs=(),
                revisions=(corrected,),
                gaps=(),
                change_manifest=EditionChangeManifest(
                    (
                        EditionChange.correction(
                            fixture.parent.revisions[0].ref, corrected.ref
                        ),
                    ),
                    (FindingMapping.applied(fixture.change_ref, (corrected.ref,)),),
                ),
            )

        self.assertEqual(len(fixture.harness.editions.rows), 1)

    def test_storage_holding_a_different_edition_under_that_id_is_refused(self) -> None:
        """A corruption guard: the manifest pins content, storage pins reality.

        The manifest cannot misdescribe the edition it names, so this can only
        fire when storage holds something other than what the ref describes.
        """
        fixture = Fixture()
        other = fixture.harness.create_initial_edition(
            fixture.production_id,
            edition_suffix=786,
            suffix=27,
            source_versions=(SOURCE,),
            transcript_scope=fixture.scope(),
            proposal_set_refs=(fixture.proposal_set.ref,),
            revisions=(fixture.revision,),
            gaps=(),
            change_manifest=initial_manifest(fixture.revision),
        ).result
        manifest = fixture.parent_manifest()
        fixture.harness.editions.rows[fixture.parent.transcript_edition_id] = other

        with self.assertRaises(StaleReferenceError):
            fixture.successor(parent=manifest)

    def test_a_successor_for_an_unknown_production_is_refused(self) -> None:
        fixture = Fixture()
        corrected = fixture.corrected()

        with self.assertRaises(StaleReferenceError):
            fixture.harness.create_successor_edition(
                ProductionId(uid(999)),
                fixture.parent_manifest(),
                source_versions=(SOURCE,),
                transcript_scope=fixture.scope(),
                proposal_set_refs=(),
                revisions=(corrected,),
                gaps=(),
                change_manifest=EditionChangeManifest(
                    (
                        EditionChange.correction(
                            fixture.parent.revisions[0].ref, corrected.ref
                        ),
                    ),
                    (FindingMapping.applied(fixture.change_ref, (corrected.ref,)),),
                ),
            )

        self.assertEqual(len(fixture.harness.editions.rows), 1)


class AncestryTests(unittest.TestCase):
    """A three-generation chain is the only place ancestry is asserted.

    The domain pins `ancestor_edition_refs[0]` to the parent's own parent, so
    the first step of the chain is never the caller's word. Everything beyond
    it is, which is why the handler walks storage instead.
    """

    def chain(self) -> tuple:
        """grandparent -> parent -> (a successor of that successor)."""
        fixture = Fixture()
        middle = fixture.successor().result
        return fixture, middle

    def test_a_grandchild_derives_its_ancestry_from_storage(self) -> None:
        fixture, middle = self.chain()
        _, change_ref = fixture.accepted_finding_on(middle, finding_suffix=910)
        old = middle.revisions[0]
        corrected = SegmentRevision.create(
            segment_id=old.segment_id,
            segment_revision_id=SegmentRevisionId(uid(371)),
            source_span=old.source_span,
            text=TranscriptText("Namaste, corrected twice"),
            language="sa",
            speaker="speaker-1",
            uncertainty_marks=(),
            lineage=RevisionLineage.corrected_from(middle.ref, old.ref),
        )

        outcome = fixture.harness.create_successor_edition(
            fixture.production_id,
            ParentEditionManifest.from_edition(middle, (fixture.parent.ref,)),
            edition_suffix=791,
            suffix=28,
            source_versions=(SOURCE,),
            transcript_scope=fixture.scope(),
            proposal_set_refs=(),
            revisions=(corrected,),
            gaps=(),
            change_manifest=EditionChangeManifest(
                (EditionChange.correction(old.ref, corrected.ref),),
                (FindingMapping.applied(change_ref, (corrected.ref,)),),
            ),
        )

        self.assertEqual(outcome.result.parent_edition_ref, middle.ref)

    def test_an_ancestor_that_storage_does_not_confirm_is_refused(self) -> None:
        """Only reachable once a chain is deep enough to have an ancestry."""
        fixture, middle = self.chain()
        _, change_ref = fixture.accepted_finding_on(middle, finding_suffix=911)
        old = middle.revisions[0]
        corrected = SegmentRevision.create(
            segment_id=old.segment_id,
            segment_revision_id=SegmentRevisionId(uid(372)),
            source_span=old.source_span,
            text=TranscriptText("Namaste, corrected twice"),
            language="sa",
            speaker="speaker-1",
            uncertainty_marks=(),
            lineage=RevisionLineage.corrected_from(middle.ref, old.ref),
        )
        replacement = fixture.harness.create_initial_edition(
            fixture.production_id,
            edition_suffix=787,
            suffix=29,
            source_versions=(SOURCE,),
            transcript_scope=fixture.scope(),
            proposal_set_refs=(fixture.proposal_set.ref,),
            revisions=(fixture.revision,),
            gaps=(),
            change_manifest=initial_manifest(fixture.revision),
        ).result
        # Storage now holds a different edition where the grandparent was.
        fixture.harness.editions.rows[fixture.parent.transcript_edition_id] = replacement

        with self.assertRaises(StaleReferenceError):
            fixture.harness.create_successor_edition(
                fixture.production_id,
                ParentEditionManifest.from_edition(middle, (fixture.parent.ref,)),
                edition_suffix=792,
                suffix=31,
                source_versions=(SOURCE,),
                transcript_scope=fixture.scope(),
                proposal_set_refs=(),
                revisions=(corrected,),
                gaps=(),
                change_manifest=EditionChangeManifest(
                    (EditionChange.correction(old.ref, corrected.ref),),
                    (FindingMapping.applied(change_ref, (corrected.ref,)),),
                ),
            )


if __name__ == "__main__":
    unittest.main()
