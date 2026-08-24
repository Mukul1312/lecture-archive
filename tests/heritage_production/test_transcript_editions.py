from __future__ import annotations

import unittest

from heritage_production.domain.shared import (
    ActorId,
    ContentDigest,
    DomainEventId,
    ProductionId,
    ProposalItemId,
    ProposalSetId,
    SegmentId,
    SegmentRevisionId,
    SourceSpan,
    TranscriptEditionId,
    TranscriptScope,
    TranscriptText,
    ValidationError,
)
from heritage_production.domain.transcription import (
    CharacterSpan,
    EditionChange,
    EditionChangeManifest,
    ProposalItemRef,
    ProposalSetRef,
    GapDeclaration,
    RevisionLineage,
    SegmentRevision,
    TranscriptEdition,
    UncertaintyKind,
    UncertaintyMark,
)
from tests.heritage_production.test_transcription_proposals import (
    SOURCE,
    complete_proposal_set,
    uid,
)


def initial_revision() -> SegmentRevision:
    proposal_set = complete_proposal_set()
    proposal_ref = ProposalItemRef(
        proposal_set.ref,
        ProposalItemId(uid(10)),
    )
    return SegmentRevision.create(
        ordinal=0,
        segment_id=SegmentId(uid(100)),
        segment_revision_id=SegmentRevisionId(uid(101)),
        source_span=SourceSpan(SOURCE, 0, 10_000),
        text=TranscriptText("Namaste"),
        language="sa",
        speaker="speaker-1",
        uncertainty_marks=(),
        lineage=RevisionLineage.proposal_derived((proposal_ref,)),
    )


def initial_manifest(revision: SegmentRevision) -> EditionChangeManifest:
    return EditionChangeManifest(
        changes=(
            EditionChange.initial_proposal(
                proposal_inputs=revision.lineage.proposal_inputs,
                output_revisions=(revision.ref,),
            ),
        ),
        finding_mappings=(),
    )


def initial_values() -> dict[str, object]:
    proposal_set = complete_proposal_set()
    revision = initial_revision()
    return dict(
        transcript_edition_id=TranscriptEditionId(uid(110)),
        production_id=ProductionId(uid(111)),
        source_versions=(SOURCE,),
        transcript_scope=TranscriptScope(
            (SOURCE,),
            (SourceSpan(SOURCE, 0, 10_000),),
            (),
        ),
        proposal_set_refs=(proposal_set.ref,),
        revisions=(revision,),
        gaps=(),
        change_manifest=initial_manifest(revision),
        creation_actor_id=ActorId(uid(112)),
        created_at_us=500,
        event_id=DomainEventId(uid(113)),
        event_occurred_at_us=501,
    )


def seal_initial(**overrides: object) -> TranscriptEdition:
    values = initial_values()
    values.update(overrides)
    return TranscriptEdition.seal_initial(**values)  # type: ignore[arg-type]


class InitialTranscriptEditionTests(unittest.TestCase):
    def test_initial_edition_seals_full_snapshot_and_emits_created_fact(self) -> None:
        edition = seal_initial()

        self.assertEqual(edition.parent_edition_ref, None)
        self.assertEqual(edition.ref.content_digest, edition.semantic_digest)
        self.assertEqual(edition.revisions[0].ref, initial_revision().ref)
        events = edition.pull_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "TranscriptEditionCreated")
        self.assertEqual(events[0].payload["edition_digest"], edition.semantic_digest.hex_digest)
        self.assertEqual(edition.pull_events(), ())

    def test_named_gap_and_adjacent_segments_cover_scope_exactly(self) -> None:
        proposal_ref = initial_revision().lineage.proposal_inputs[0]
        first = SegmentRevision.create(
            ordinal=0,
            segment_id=SegmentId(uid(120)),
            segment_revision_id=SegmentRevisionId(uid(121)),
            source_span=SourceSpan(SOURCE, 0, 4_000),
            text=TranscriptText("First"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.proposal_derived((proposal_ref,)),
        )
        second = SegmentRevision.create(
            ordinal=1,
            segment_id=SegmentId(uid(122)),
            segment_revision_id=SegmentRevisionId(uid(123)),
            source_span=SourceSpan(SOURCE, 6_000, 10_000),
            text=TranscriptText("Second"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.proposal_derived((proposal_ref,)),
        )
        gap_span = SourceSpan(SOURCE, 4_000, 6_000)
        manifest = EditionChangeManifest(
            (
                EditionChange.initial_proposal(
                    proposal_inputs=(proposal_ref,),
                    output_revisions=(first.ref, second.ref),
                ),
            ),
            (),
        )
        edition = seal_initial(
            transcript_scope=TranscriptScope(
                (SOURCE,),
                (SourceSpan(SOURCE, 0, 10_000),),
                (gap_span,),
            ),
            revisions=(first, second),
            gaps=(GapDeclaration(gap_span, "Unrecoverable tape damage"),),
            change_manifest=manifest,
        )

        self.assertEqual(edition.gaps[0].reason, "Unrecoverable tape damage")

    def test_empty_text_requires_full_segment_inaudible_mark(self) -> None:
        proposal_ref = initial_revision().lineage.proposal_inputs[0]
        full_span = SourceSpan(SOURCE, 0, 10_000)
        valid = SegmentRevision.create(
            ordinal=0,
            segment_id=SegmentId(uid(130)),
            segment_revision_id=SegmentRevisionId(uid(131)),
            source_span=full_span,
            text=TranscriptText(""),
            language="und",
            speaker=None,
            uncertainty_marks=(UncertaintyMark(UncertaintyKind.INAUDIBLE, full_span),),
            lineage=RevisionLineage.proposal_derived((proposal_ref,)),
        )
        manifest = EditionChangeManifest(
            (EditionChange.initial_proposal(proposal_inputs=(proposal_ref,), output_revisions=(valid.ref,)),),
            (),
        )
        self.assertEqual(
            seal_initial(revisions=(valid,), change_manifest=manifest).revisions[0].text.value,
            "",
        )

        invalid_marks = (
            (),
            (UncertaintyMark(UncertaintyKind.UNCERTAIN_WORDING, full_span),),
            (
                UncertaintyMark(
                    UncertaintyKind.INAUDIBLE,
                    SourceSpan(SOURCE, 0, 9_999),
                ),
            ),
        )
        for marks in invalid_marks:
            with self.subTest(marks=marks):
                with self.assertRaises(ValidationError):
                    SegmentRevision.create(
                        ordinal=0,
                        segment_id=SegmentId(uid(130)),
                        segment_revision_id=SegmentRevisionId(uid(131)),
                        source_span=full_span,
                        text=TranscriptText(""),
                        language="und",
                        speaker=None,
                        uncertainty_marks=marks,
                        lineage=RevisionLineage.proposal_derived((proposal_ref,)),
                    )

    def test_uncertainty_must_lie_within_source_and_unicode_scalar_text_bounds(self) -> None:
        proposal_ref = initial_revision().lineage.proposal_inputs[0]
        full_span = SourceSpan(SOURCE, 0, 10_000)
        valid_mark = UncertaintyMark(
            UncertaintyKind.UNCERTAIN_WORDING,
            SourceSpan(SOURCE, 2_000, 4_000),
            CharacterSpan(1, 2),
            "vowel unclear",
        )
        valid = SegmentRevision.create(
            ordinal=0,
            segment_id=SegmentId(uid(140)),
            segment_revision_id=SegmentRevisionId(uid(141)),
            source_span=full_span,
            text=TranscriptText("A🧡B"),
            language="en",
            speaker=None,
            uncertainty_marks=(valid_mark,),
            lineage=RevisionLineage.proposal_derived((proposal_ref,)),
        )
        manifest = EditionChangeManifest(
            (EditionChange.initial_proposal(proposal_inputs=(proposal_ref,), output_revisions=(valid.ref,)),),
            (),
        )
        seal_initial(revisions=(valid,), change_manifest=manifest)

        invalid_marks = (
            UncertaintyMark(
                UncertaintyKind.UNCERTAIN_WORDING,
                SourceSpan(SOURCE, 9_000, 10_000),
                CharacterSpan(2, 4),
            ),
            UncertaintyMark(
                UncertaintyKind.UNCERTAIN_WORDING,
                SourceSpan(SOURCE, 0, 10_000),
                CharacterSpan(0, 4),
            ),
        )
        # The first becomes source-out-of-bounds after narrowing the segment.
        narrowed_span = SourceSpan(SOURCE, 0, 8_000)
        for mark in invalid_marks:
            with self.subTest(mark=mark):
                with self.assertRaises(ValidationError):
                    SegmentRevision.create(
                        ordinal=0,
                        segment_id=SegmentId(uid(142)),
                        segment_revision_id=SegmentRevisionId(uid(143)),
                        source_span=narrowed_span if mark is invalid_marks[0] else full_span,
                        text=TranscriptText("A🧡B"),
                        language="en",
                        speaker=None,
                        uncertainty_marks=(mark,),
                        lineage=RevisionLineage.proposal_derived((proposal_ref,)),
                    )

    def test_rejects_ordinal_identity_overlap_source_gap_and_coverage_errors(self) -> None:
        baseline = initial_revision()
        wrong_ordinal = SegmentRevision.create(
            ordinal=1,
            segment_id=baseline.segment_id,
            segment_revision_id=baseline.segment_revision_id,
            source_span=baseline.source_span,
            text=baseline.text,
            language=baseline.language,
            speaker=baseline.speaker,
            uncertainty_marks=baseline.uncertainty_marks,
            lineage=baseline.lineage,
        )
        duplicate_segment = SegmentRevision.create(
            ordinal=1,
            segment_id=baseline.segment_id,
            segment_revision_id=SegmentRevisionId(uid(151)),
            source_span=SourceSpan(SOURCE, 5_000, 10_000),
            text=TranscriptText("duplicate"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=baseline.lineage,
        )
        for overrides in (
            {"revisions": (wrong_ordinal,)},
            {"revisions": (baseline, duplicate_segment)},
            {
                "transcript_scope": TranscriptScope(
                    (SOURCE,),
                    (SourceSpan(SOURCE, 0, 10_000),),
                    (SourceSpan(SOURCE, 4_000, 5_000),),
                ),
                "gaps": (),
            },
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    seal_initial(**overrides)

    def test_initial_manifest_is_complete_exact_and_manual_edits_are_attributed(self) -> None:
        revision = initial_revision()
        missing = EditionChangeManifest((), ())
        duplicate = EditionChangeManifest(
            (
                EditionChange.initial_proposal(
                    proposal_inputs=revision.lineage.proposal_inputs,
                    output_revisions=(revision.ref, revision.ref),
                ),
            ),
            (),
        )
        for manifest in (missing, duplicate):
            with self.subTest(manifest=manifest):
                with self.assertRaises(ValidationError):
                    seal_initial(change_manifest=manifest)

        manual_revision = SegmentRevision.create(
            ordinal=0,
            segment_id=SegmentId(uid(160)),
            segment_revision_id=SegmentRevisionId(uid(161)),
            source_span=SourceSpan(SOURCE, 0, 10_000),
            text=TranscriptText("Steward transcript"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.manual_initial(),
        )
        manual_change = EditionChange.initial_manual(
            output_revisions=(manual_revision.ref,),
            actor_id=ActorId(uid(162)),
            reason="Directly transcribed from the source",
        )
        edition = seal_initial(
            proposal_set_refs=(),
            revisions=(manual_revision,),
            change_manifest=EditionChangeManifest((manual_change,), ()),
        )
        self.assertEqual(edition.change_manifest.changes[0].manual_actor_id, ActorId(uid(162)))

        with self.assertRaises(ValidationError):
            EditionChange.initial_manual(
                output_revisions=(manual_revision.ref,), actor_id=None, reason="missing actor"
            )
        with self.assertRaises(ValidationError):
            EditionChange.initial_manual(
                output_revisions=(manual_revision.ref,), actor_id=ActorId(uid(162)), reason=""
            )

    def test_edition_digest_excludes_root_id_and_creation_time_and_includes_content(self) -> None:
        baseline = seal_initial()
        same_content = seal_initial(
            transcript_edition_id=TranscriptEditionId(uid(170)),
            created_at_us=999,
            event_id=DomainEventId(uid(171)),
            event_occurred_at_us=999,
        )
        changed_revision = SegmentRevision.create(
            ordinal=0,
            segment_id=SegmentId(uid(100)),
            segment_revision_id=SegmentRevisionId(uid(101)),
            source_span=SourceSpan(SOURCE, 0, 10_000),
            text=TranscriptText("Namaste changed"),
            language="sa",
            speaker="speaker-1",
            uncertainty_marks=(),
            lineage=initial_revision().lineage,
        )
        changed_manifest = EditionChangeManifest(
            (
                EditionChange.initial_proposal(
                    proposal_inputs=changed_revision.lineage.proposal_inputs,
                    output_revisions=(changed_revision.ref,),
                ),
            ),
            (),
        )
        changed = seal_initial(revisions=(changed_revision,), change_manifest=changed_manifest)

        self.assertEqual(baseline.semantic_digest, same_content.semantic_digest)
        self.assertNotEqual(baseline.semantic_digest, changed.semantic_digest)

    def test_reconstitution_verifies_edition_and_revision_digests_without_events(self) -> None:
        created = seal_initial()
        values = initial_values()
        values.pop("event_id")
        values.pop("event_occurred_at_us")
        reconstituted = TranscriptEdition.reconstitute(
            **values, semantic_digest=created.semantic_digest  # type: ignore[arg-type]
        )
        self.assertEqual(reconstituted.ref, created.ref)
        self.assertEqual(reconstituted.pull_events(), ())
        with self.assertRaises(AttributeError):
            reconstituted.created_at_us = 1  # type: ignore[misc]
        with self.assertRaises(ValidationError):
            TranscriptEdition.reconstitute(
                **values,
                semantic_digest=ContentDigest("sha256", "f" * 64),  # type: ignore[arg-type]
            )

    def test_segment_revision_reconstitution_verifies_its_semantic_digest(self) -> None:
        created = initial_revision()
        values = dict(
            ordinal=created.ordinal,
            segment_id=created.segment_id,
            segment_revision_id=created.segment_revision_id,
            source_span=created.source_span,
            text=created.text,
            language=created.language,
            speaker=created.speaker,
            uncertainty_marks=created.uncertainty_marks,
            lineage=created.lineage,
        )
        restored = SegmentRevision.reconstitute(
            **values, semantic_digest=created.semantic_digest
        )
        self.assertEqual(restored, created)
        with self.assertRaises(ValidationError):
            SegmentRevision.reconstitute(
                **values, semantic_digest=ContentDigest("sha256", "0" * 64)
            )

    def test_exact_immutable_collections_and_proposal_refs_are_enforced(self) -> None:
        class MutableTuple(tuple):
            pass

        revision = initial_revision()
        with self.assertRaises(ValidationError):
            SegmentRevision.create(
                ordinal=revision.ordinal,
                segment_id=revision.segment_id,
                segment_revision_id=revision.segment_revision_id,
                source_span=revision.source_span,
                text=revision.text,
                language=revision.language,
                speaker=revision.speaker,
                uncertainty_marks=MutableTuple(()),
                lineage=revision.lineage,
            )
        proposal_ref = revision.lineage.proposal_inputs[0].proposal_set_ref
        with self.assertRaises(ValidationError):
            seal_initial(proposal_set_refs=(proposal_ref, proposal_ref))
        unused = ProposalSetRef(
            ProposalSetId(uid(190)),
            ContentDigest("sha256", "e" * 64),
        )
        with self.assertRaises(ValidationError):
            seal_initial(proposal_set_refs=(proposal_ref, unused))


if __name__ == "__main__":
    unittest.main()
