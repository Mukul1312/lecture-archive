"""CreateInitialTranscriptEdition — a sealed root that still emits an event.

`ReleasePolicyVersion` is sealed and silent; `TranscriptEdition` is sealed and
records `TranscriptEditionCreated` (design 9.6). Immutable is not the same as
uninteresting, so this handler drains events like a mutable one.

The application owns two checks neither aggregate can make. A sealed edition
has no delete path, so an edition naming a Production that does not exist
would be permanent orphan evidence; and an edition built from proposal sets
imported for a recording it does not declare has incoherent provenance that
only something seeing both aggregates can notice.
"""

from __future__ import annotations

import dataclasses
import unittest

from heritage_production.application import commands
from heritage_production.application.errors import (
    OperationConflictError,
    ReplayIntegrityError,
)
from heritage_production.application.idempotency import command_result_digest
from heritage_production.domain.shared import (
    ArtifactId,
    OperationId,
    ProductionId,
    ProposalItemId,
    SegmentId,
    SegmentRevisionId,
    SourceSpan,
    StaleReferenceError,
    TranscriptEditionId,
    TranscriptText,
    ValidationError,
)
from heritage_production.domain.shared import TranscriptScope
from heritage_production.domain.transcription import (
    ConfidenceEvidence,
    ProposalItem,
    ProposalItemRef,
    RawRowLocator,
    ProposalSetRef,
    RevisionLineage,
    SegmentRevision,
)

from tests.heritage_production.application_harness import ApplicationHarness
from tests.heritage_production.heritage_release_fixtures import uid
from tests.heritage_production.test_application_import_handler import (
    PACKAGE_BYTES,
    complete_translation,
)
from tests.heritage_production.test_transcript_editions import initial_manifest
from tests.heritage_production.test_transcription_proposals import SOURCE


def item_on(source) -> ProposalItem:
    """One proposal item spanning the given recording."""
    return ProposalItem(
        proposal_item_id=ProposalItemId(uid(801)),
        source_span=SourceSpan(source, 0, 10_000),
        proposed_text=TranscriptText("Namaste"),
        language="sa",
        speaker_hypothesis="speaker-1",
        confidence_evidence=(ConfidenceEvidence("posterior", "0.9"),),
        raw_row_locator=RawRowLocator("segments.jsonl#row=1"),
    )


def revision_from(proposal_set) -> "SegmentRevision":
    """A revision derived from *this* imported set.

    The domain requires `proposal_set_refs` to match the revision lineage
    exactly, so a fixture revision bound to some other proposal set would be
    refused -- correctly, and for a reason worth keeping visible.
    """
    return SegmentRevision.create(
        segment_id=SegmentId(uid(100)),
        segment_revision_id=SegmentRevisionId(uid(101)),
        source_span=SourceSpan(SOURCE, 0, 10_000),
        text=TranscriptText("Namaste"),
        language="sa",
        speaker="speaker-1",
        uncertainty_marks=(),
        lineage=RevisionLineage.proposal_derived(
            (ProposalItemRef(proposal_set.ref, ProposalItemId(uid(800))),)
        ),
    )


class Fixture:
    """A Production with SOURCE attached and one imported proposal set."""

    def __init__(self) -> None:
        self.harness = ApplicationHarness()
        created = self.harness.create()
        self.production_id = created.result.production_id
        self.harness.attach(self.production_id, SOURCE)
        self.package = self.harness.artifacts.seed(ArtifactId(uid(310)), PACKAGE_BYTES)
        self.harness.translator.result = complete_translation(self.package)
        self.proposal_set = self.harness.import_package(
            self.package, SOURCE
        ).result
        self.revision = revision_from(self.proposal_set)

    def scope(self) -> TranscriptScope:
        return TranscriptScope((SOURCE,), (SourceSpan(SOURCE, 0, 10_000),), ())

    def create(self, **overrides):
        values = dict(
            source_versions=(SOURCE,),
            transcript_scope=self.scope(),
            proposal_set_refs=(self.proposal_set.ref,),
            revisions=(self.revision,),
            gaps=(),
            change_manifest=initial_manifest(self.revision),
        )
        values.update(overrides)
        return self.harness.create_initial_edition(self.production_id, **values)


class CreateInitialTranscriptEditionTests(unittest.TestCase):
    def test_it_seals_an_edition_bound_to_its_production(self) -> None:
        fixture = Fixture()

        outcome = fixture.create()

        stored = fixture.harness.editions.get(TranscriptEditionId(uid(780)))
        self.assertIs(outcome.result, stored)
        self.assertEqual(stored.production_id, fixture.production_id)
        self.assertEqual(stored.source_versions, (SOURCE,))

    def test_the_commanding_actor_becomes_the_creator(self) -> None:
        fixture = Fixture()

        outcome = fixture.create()

        self.assertEqual(
            outcome.result.creation_actor_id, fixture.harness.context().actor_id
        )

    def test_a_sealed_edition_still_publishes_its_creation_event(self) -> None:
        """Design 9.6 lists TranscriptEditionCreated; sealed is not silent."""
        fixture = Fixture()

        outcome = fixture.create()

        self.assertEqual(fixture.harness.events.names()[-1], "TranscriptEditionCreated")
        self.assertEqual(
            fixture.harness.events.events[-1].payload["edition_digest"],
            outcome.result.semantic_digest.hex_digest,
        )

    def test_the_aggregate_keeps_no_unpublished_events(self) -> None:
        fixture = Fixture()

        outcome = fixture.create()

        self.assertEqual(outcome.result.pull_events(), ())

    def test_the_payload_pins_the_edition_digest(self) -> None:
        fixture = Fixture()

        outcome = fixture.create()

        self.assertEqual(
            outcome.record.result_payload,
            {
                "transcript_edition_id": uid(780),
                "production_id": fixture.production_id.value,
                "content_digest": outcome.result.semantic_digest.hex_digest,
                "revision_count": 1,
                "gap_count": 0,
            },
        )

    def test_a_replay_returns_the_original_sealed_edition(self) -> None:
        fixture = Fixture()
        first = fixture.create()

        again = fixture.create()

        self.assertTrue(again.replayed)
        self.assertIs(again.result, first.result)
        self.assertEqual(len(fixture.harness.editions.rows), 1)

    def test_a_replay_publishes_no_second_event(self) -> None:
        fixture = Fixture()
        fixture.create()
        after_first = fixture.harness.events.names()

        fixture.create()

        self.assertEqual(fixture.harness.events.names(), after_first)

    def test_a_changed_edition_id_under_one_operation_id_conflicts(self) -> None:
        """Same operation, different edition: a conflict, never a replay."""
        fixture = Fixture()
        fixture.create()

        with self.assertRaises(OperationConflictError):
            fixture.create(edition_suffix=781)

        self.assertEqual(len(fixture.harness.editions.rows), 1)

    def test_the_created_edition_can_then_be_selected(self) -> None:
        """Design 9.2 steps 3 and 4 meet."""
        from heritage_production.domain.production import EditionSelection

        fixture = Fixture()
        edition = fixture.create().result

        outcome = fixture.harness.select_edition(
            fixture.production_id,
            EditionSelection(
                production_id=fixture.production_id,
                edition_ref=edition.ref,
                source_version_refs=(SOURCE,),
            ),
            expected_version=2,
        )

        self.assertEqual(outcome.result, edition.ref)


class CrossAggregateRefusalTests(unittest.TestCase):
    def test_an_edition_for_an_unknown_production_is_refused(self) -> None:
        """A sealed edition cannot be deleted, so an orphan is permanent."""
        fixture = Fixture()
        before = dict(fixture.harness.editions.rows)

        with self.assertRaises(StaleReferenceError):
            fixture.harness.create_initial_edition(
                ProductionId(uid(999)),
                source_versions=(SOURCE,),
                transcript_scope=fixture.scope(),
                proposal_set_refs=(fixture.proposal_set.ref,),
                revisions=(fixture.revision,),
                gaps=(),
                change_manifest=initial_manifest(fixture.revision),
            )

        self.assertEqual(fixture.harness.editions.rows, before)

    def test_a_proposal_set_that_was_never_imported_is_refused(self) -> None:
        fixture = Fixture()
        from heritage_production.domain.shared import ProposalSetId

        missing = ProposalSetRef(
            ProposalSetId(uid(888)), fixture.proposal_set.semantic_digest
        )

        with self.assertRaises(StaleReferenceError):
            fixture.create(proposal_set_refs=(missing,))

        self.assertEqual(fixture.harness.editions.rows, {})

    def test_a_proposal_set_reference_with_the_wrong_digest_is_refused(self) -> None:
        fixture = Fixture()
        from heritage_production.domain.shared import ContentDigest

        forged = ProposalSetRef(
            fixture.proposal_set.proposal_set_id, ContentDigest("sha256", "f" * 64)
        )

        with self.assertRaises(StaleReferenceError):
            fixture.create(proposal_set_refs=(forged,))

        self.assertEqual(fixture.harness.editions.rows, {})

    def test_a_proposal_set_for_an_undeclared_source_is_refused(self) -> None:
        """Incoherent provenance only something seeing both roots can notice.

        The reference is genuine and its digest matches; the proposal set was
        simply imported for a recording this edition never declares.
        """
        fixture = Fixture()
        foreign_source = _source_for(2)
        other_package = fixture.harness.artifacts.seed(
            ArtifactId(uid(312)), b"a package for another recording"
        )
        fixture.harness.translator.result = complete_translation(
            other_package, items=(item_on(foreign_source),)
        )
        imported = fixture.harness.import_package(
            other_package, foreign_source, proposal_suffix=761, suffix=22
        ).result
        # The revision is derived from the *foreign* set, so the domain's own
        # "refs must match the revision lineage" rule is satisfied and only
        # the source check can refuse this.
        revision = revision_from(imported)

        with self.assertRaises(ValidationError):
            fixture.create(
                proposal_set_refs=(imported.ref,),
                revisions=(revision,),
                change_manifest=initial_manifest(revision),
            )

        self.assertEqual(fixture.harness.editions.rows, {})


def _source_for(suffix: int):
    from heritage_production.domain.shared import (
        ContentDigest,
        SourceRecordingId,
        SourceVersionId,
        SourceVersionRef,
    )

    return SourceVersionRef(
        SourceVersionId(uid(400 + suffix)),
        SourceRecordingId(uid(500 + suffix)),
        ContentDigest("sha256", str(suffix) * 64),
        10_000,
        "microseconds",
    )


class ReplaySteeringTests(unittest.TestCase):
    """A stored payload must not choose which root a replay loads."""

    def test_a_tampered_payload_cannot_redirect_the_reload(self) -> None:
        fixture = Fixture()
        first = fixture.create()
        other = fixture.harness.create_initial_edition(
            fixture.production_id,
            edition_suffix=782,
            suffix=23,
            source_versions=(SOURCE,),
            transcript_scope=fixture.scope(),
            proposal_set_refs=(fixture.proposal_set.ref,),
            revisions=(fixture.revision,),
            gaps=(),
            change_manifest=initial_manifest(fixture.revision),
        ).result
        # Point the record at a different, genuinely stored edition and
        # re-digest so the record stays self-consistent.
        command_payload = dict(first.record.result_payload)
        command_payload["transcript_edition_id"] = other.transcript_edition_id.value
        command_payload["content_digest"] = other.semantic_digest.hex_digest
        operation_id = first.record.operation_id
        fixture.harness.recorder.records[operation_id] = dataclasses.replace(
            first.record,
            result_payload=command_payload,
            result_digest=command_result_digest(
                _replayed_command(fixture), command_payload
            ),
        )

        with self.assertRaises(ReplayIntegrityError):
            fixture.create()


def _replayed_command(fixture: "Fixture"):
    return commands.CreateInitialTranscriptEdition(
        operation_id=OperationId(uid(21)),
        actor=fixture.harness.context(),
        production_id=fixture.production_id,
        transcript_edition_id=TranscriptEditionId(uid(780)),
        source_versions=(SOURCE,),
        transcript_scope=fixture.scope(),
        proposal_set_refs=(fixture.proposal_set.ref,),
        revisions=(fixture.revision,),
        gaps=(),
        change_manifest=initial_manifest(fixture.revision),
    )


if __name__ == "__main__":
    unittest.main()
