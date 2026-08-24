from __future__ import annotations

from dataclasses import replace
import unittest

from heritage_production.domain.shared import (
    ActorId,
    ContentDigest,
    DomainEventId,
    EditionRef,
    ProductionId,
    ReviewFindingId,
    SegmentId,
    SegmentRevisionId,
    SourceSpan,
    TranscriptEditionId,
    TranscriptScope,
    TranscriptText,
    ValidationError,
)
from heritage_production.domain.transcription import (
    EditionChange,
    EditionChangeManifest,
    FindingChangeRef,
    FindingMapping,
    GapDeclaration,
    ParentEditionManifest,
    RevisionLineage,
    RevisionLineageKind,
    SegmentRevision,
    TranscriptEdition,
)
from tests.heritage_production.test_transcription_proposals import SOURCE, uid


PRODUCTION_ID = ProductionId(uid(300))
STEWARD_ID = ActorId(uid(301))


def parent_revision(ordinal: int) -> SegmentRevision:
    start = ordinal * 2_000
    return SegmentRevision.create(
        ordinal=ordinal,
        segment_id=SegmentId(uid(310 + ordinal)),
        segment_revision_id=SegmentRevisionId(uid(320 + ordinal)),
        source_span=SourceSpan(SOURCE, start, start + 2_000),
        text=TranscriptText(f"parent-{ordinal}"),
        language="en",
        speaker=None,
        uncertainty_marks=(),
        lineage=RevisionLineage.manual_initial(),
    )


def seal_parent() -> TranscriptEdition:
    revisions = tuple(parent_revision(ordinal) for ordinal in range(5))
    return TranscriptEdition.seal_initial(
        transcript_edition_id=TranscriptEditionId(uid(330)),
        production_id=PRODUCTION_ID,
        source_versions=(SOURCE,),
        transcript_scope=TranscriptScope(
            (SOURCE,),
            (SourceSpan(SOURCE, 0, 10_000),),
            (),
        ),
        proposal_set_refs=(),
        revisions=revisions,
        gaps=(),
        change_manifest=EditionChangeManifest(
            (
                EditionChange.initial_manual(
                    output_revisions=tuple(revision.ref for revision in revisions),
                    actor_id=STEWARD_ID,
                    reason="Direct parent transcription",
                ),
            ),
            (),
        ),
        creation_actor_id=STEWARD_ID,
        created_at_us=1_000,
        event_id=DomainEventId(uid(331)),
        event_occurred_at_us=1_001,
    )


def structural_successor() -> tuple[TranscriptEdition, ParentEditionManifest]:
    parent = seal_parent()
    parent_manifest = ParentEditionManifest.from_edition(parent)
    old = parent.revisions
    unchanged = old[0]
    correction = SegmentRevision.create(
        ordinal=1,
        segment_id=old[1].segment_id,
        segment_revision_id=SegmentRevisionId(uid(340)),
        source_span=old[1].source_span,
        text=TranscriptText("corrected"),
        language="en",
        speaker=None,
        uncertainty_marks=(),
        lineage=RevisionLineage.corrected_from(parent.ref, old[1].ref),
    )
    split_first = SegmentRevision.create(
        ordinal=2,
        segment_id=SegmentId(uid(341)),
        segment_revision_id=SegmentRevisionId(uid(342)),
        source_span=SourceSpan(SOURCE, 4_000, 5_000),
        text=TranscriptText("split-a"),
        language="en",
        speaker=None,
        uncertainty_marks=(),
        lineage=RevisionLineage.split_from(parent.ref, old[2].ref),
    )
    split_second = SegmentRevision.create(
        ordinal=3,
        segment_id=SegmentId(uid(343)),
        segment_revision_id=SegmentRevisionId(uid(344)),
        source_span=SourceSpan(SOURCE, 5_000, 6_000),
        text=TranscriptText("split-b"),
        language="en",
        speaker=None,
        uncertainty_marks=(),
        lineage=RevisionLineage.split_from(parent.ref, old[2].ref),
    )
    merged = SegmentRevision.create(
        ordinal=4,
        segment_id=SegmentId(uid(345)),
        segment_revision_id=SegmentRevisionId(uid(346)),
        source_span=SourceSpan(SOURCE, 6_000, 10_000),
        text=TranscriptText("merged"),
        language="en",
        speaker=None,
        uncertainty_marks=(),
        lineage=RevisionLineage.merged_from(parent.ref, (old[3].ref, old[4].ref)),
    )
    revisions = (unchanged, correction, split_first, split_second, merged)
    manual = {"actor_id": STEWARD_ID, "reason": "Steward source comparison"}
    manifest = EditionChangeManifest(
        (
            EditionChange.unchanged(old[0].ref, unchanged.ref),
            EditionChange.correction(old[1].ref, correction.ref, **manual),
            EditionChange.split(old[2].ref, (split_first.ref, split_second.ref), **manual),
            EditionChange.merge((old[3].ref, old[4].ref), merged.ref, **manual),
        ),
        (),
    )
    edition = TranscriptEdition.seal_successor(
        transcript_edition_id=TranscriptEditionId(uid(350)),
        production_id=PRODUCTION_ID,
        source_versions=(SOURCE,),
        transcript_scope=parent.transcript_scope,
        proposal_set_refs=(),
        parent_edition_ref=parent.ref,
        parent_manifest=parent_manifest,
        revisions=revisions,
        gaps=(),
        change_manifest=manifest,
        creation_actor_id=STEWARD_ID,
        created_at_us=2_000,
        event_id=DomainEventId(uid(351)),
        event_occurred_at_us=2_001,
    )
    return edition, parent_manifest


def reseal_successor(
    edition: TranscriptEdition,
    parent_manifest: ParentEditionManifest,
    **overrides: object,
) -> TranscriptEdition:
    values: dict[str, object] = dict(
        transcript_edition_id=TranscriptEditionId(uid(360)),
        production_id=edition.production_id,
        source_versions=edition.source_versions,
        transcript_scope=edition.transcript_scope,
        proposal_set_refs=edition.proposal_set_refs,
        parent_edition_ref=edition.parent_edition_ref,
        parent_manifest=parent_manifest,
        revisions=edition.revisions,
        gaps=edition.gaps,
        change_manifest=edition.change_manifest,
        creation_actor_id=edition.creation_actor_id,
        created_at_us=2_100,
        event_id=DomainEventId(uid(361)),
        event_occurred_at_us=2_101,
    )
    values.update(overrides)
    return TranscriptEdition.seal_successor(**values)  # type: ignore[arg-type]


class SuccessorTranscriptEditionTests(unittest.TestCase):
    def test_successor_supports_unchanged_correction_split_and_merge(self) -> None:
        edition, parent_manifest = structural_successor()

        self.assertEqual(edition.parent_edition_ref, parent_manifest.edition_ref)
        self.assertEqual(edition.revisions[0].segment_id, parent_manifest.revisions[0].segment_id)
        self.assertEqual(
            edition.revisions[0].segment_revision_id,
            parent_manifest.revisions[0].segment_revision_id,
        )
        self.assertEqual(len(edition.change_manifest.changes), 4)
        self.assertEqual(edition.pull_events()[0].event_type, "TranscriptEditionCreated")

    def test_accepted_findings_map_to_applied_revision_or_justified_no_change(self) -> None:
        parent = seal_parent()
        old = parent.revisions
        corrected = SegmentRevision.create(
            ordinal=0,
            segment_id=old[0].segment_id,
            segment_revision_id=SegmentRevisionId(uid(370)),
            source_span=old[0].source_span,
            text=TranscriptText("finding correction"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.corrected_from(parent.ref, old[0].ref),
        )
        revisions = (corrected, *old[1:])
        applied = FindingChangeRef(
            ReviewFindingId(uid(371)),
            ContentDigest("sha256", "1" * 64),
            ContentDigest("sha256", "2" * 64),
        )
        no_change = FindingChangeRef(
            ReviewFindingId(uid(372)),
            ContentDigest("sha256", "3" * 64),
            ContentDigest("sha256", "4" * 64),
        )
        manifest = EditionChangeManifest(
            (
                EditionChange.correction(old[0].ref, corrected.ref),
                *(EditionChange.unchanged(value.ref, value.ref) for value in old[1:]),
            ),
            (
                FindingMapping.applied(applied, (corrected.ref,)),
                FindingMapping.no_edition_change(
                    no_change,
                    "Observation was valid but policy requires retaining the literal wording",
                ),
            ),
        )
        edition = TranscriptEdition.seal_successor(
            transcript_edition_id=TranscriptEditionId(uid(373)),
            production_id=PRODUCTION_ID,
            source_versions=(SOURCE,),
            transcript_scope=parent.transcript_scope,
            proposal_set_refs=(),
            parent_edition_ref=parent.ref,
            parent_manifest=ParentEditionManifest.from_edition(parent),
            revisions=revisions,
            gaps=(),
            change_manifest=manifest,
            creation_actor_id=STEWARD_ID,
            created_at_us=3_000,
            event_id=DomainEventId(uid(374)),
            event_occurred_at_us=3_001,
        )

        self.assertEqual(edition.change_manifest.finding_mappings, manifest.finding_mappings)

    def test_steward_can_fill_a_parent_gap_with_attributed_manual_new_revision(self) -> None:
        first = parent_revision(0)
        first = SegmentRevision.create(
            ordinal=0,
            segment_id=first.segment_id,
            segment_revision_id=first.segment_revision_id,
            source_span=SourceSpan(SOURCE, 0, 5_000),
            text=first.text,
            language=first.language,
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.manual_initial(),
        )
        gap = SourceSpan(SOURCE, 5_000, 10_000)
        parent = TranscriptEdition.seal_initial(
            transcript_edition_id=TranscriptEditionId(uid(380)),
            production_id=PRODUCTION_ID,
            source_versions=(SOURCE,),
            transcript_scope=TranscriptScope((SOURCE,), (SourceSpan(SOURCE, 0, 10_000),), (gap,)),
            proposal_set_refs=(),
            revisions=(first,),
            gaps=(GapDeclaration(gap, "Not yet transcribed"),),
            change_manifest=EditionChangeManifest(
                (EditionChange.initial_manual(output_revisions=(first.ref,), actor_id=STEWARD_ID, reason="Initial partial transcript"),),
                (),
            ),
            creation_actor_id=STEWARD_ID,
            created_at_us=1,
            event_id=DomainEventId(uid(381)),
            event_occurred_at_us=2,
        )
        new = SegmentRevision.create(
            ordinal=1,
            segment_id=SegmentId(uid(382)),
            segment_revision_id=SegmentRevisionId(uid(383)),
            source_span=gap,
            text=TranscriptText("newly recovered"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.manual_new(),
        )
        successor = TranscriptEdition.seal_successor(
            transcript_edition_id=TranscriptEditionId(uid(384)),
            production_id=PRODUCTION_ID,
            source_versions=(SOURCE,),
            transcript_scope=TranscriptScope((SOURCE,), (SourceSpan(SOURCE, 0, 10_000),), ()),
            proposal_set_refs=(),
            parent_edition_ref=parent.ref,
            parent_manifest=ParentEditionManifest.from_edition(parent),
            revisions=(first, new),
            gaps=(),
            change_manifest=EditionChangeManifest(
                (
                    EditionChange.unchanged(first.ref, first.ref),
                    EditionChange.manual_new(
                        new.ref,
                        actor_id=STEWARD_ID,
                        reason="Recovered by repeated source listening",
                    ),
                ),
                (),
            ),
            creation_actor_id=STEWARD_ID,
            created_at_us=2,
            event_id=DomainEventId(uid(385)),
            event_occurred_at_us=3,
        )
        self.assertEqual(successor.revisions[-1].text.value, "newly recovered")

    def test_rejects_wrong_parent_cycle_missing_ambiguous_and_claimed_output_lineage(self) -> None:
        edition, parent_manifest = structural_successor()
        changes = edition.change_manifest.changes
        fake_parent = EditionRef(
            parent_manifest.edition_ref.transcript_edition_id,
            ContentDigest("sha256", "9" * 64),
        )
        fake_output = replace(
            edition.revisions[1].ref,
            segment_revision_id=SegmentRevisionId(uid(390)),
        )
        invalid_cases = (
            {"parent_edition_ref": fake_parent},
            {"transcript_edition_id": parent_manifest.edition_ref.transcript_edition_id},
            {"change_manifest": EditionChangeManifest(changes[:-1], ())},
            {"change_manifest": EditionChangeManifest((changes[0], changes[0], *changes[1:]), ())},
            {
                "change_manifest": EditionChangeManifest(
                    (
                        changes[0],
                        EditionChange.correction(
                            changes[1].input_revisions[0],
                            fake_output,
                            actor_id=STEWARD_ID,
                            reason="Claims an absent output",
                        ),
                        *changes[2:],
                    ),
                    (),
                )
            },
        )
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    reseal_successor(edition, parent_manifest, **overrides)

    def test_rejects_unjustified_changes_and_invalid_finding_outcomes(self) -> None:
        edition, parent_manifest = structural_successor()
        changes = list(edition.change_manifest.changes)
        correction = changes[1]
        changes[1] = EditionChange.correction(
            correction.input_revisions[0], correction.output_revisions[0]
        )
        with self.assertRaises(ValidationError):
            reseal_successor(
                edition,
                parent_manifest,
                change_manifest=EditionChangeManifest(tuple(changes), ()),
            )

        finding = FindingChangeRef(
            ReviewFindingId(uid(395)),
            ContentDigest("sha256", "5" * 64),
            ContentDigest("sha256", "6" * 64),
        )
        with self.assertRaises(ValidationError):
            FindingMapping.applied(finding, ())
        with self.assertRaises(ValidationError):
            FindingMapping.no_edition_change(finding, "")

    def test_successor_reconstitution_uses_parent_manifest_and_emits_no_event(self) -> None:
        edition, parent_manifest = structural_successor()
        reconstituted = TranscriptEdition.reconstitute(
            transcript_edition_id=edition.transcript_edition_id,
            production_id=edition.production_id,
            source_versions=edition.source_versions,
            transcript_scope=edition.transcript_scope,
            proposal_set_refs=edition.proposal_set_refs,
            parent_edition_ref=edition.parent_edition_ref,
            parent_manifest=parent_manifest,
            revisions=edition.revisions,
            gaps=edition.gaps,
            change_manifest=edition.change_manifest,
            creation_actor_id=edition.creation_actor_id,
            created_at_us=edition.created_at_us,
            semantic_digest=edition.semantic_digest,
        )
        self.assertEqual(reconstituted.ref, edition.ref)
        self.assertEqual(reconstituted.pull_events(), ())

    def test_lineage_values_reject_cyclic_ambiguous_and_contradictory_shapes(self) -> None:
        parent = seal_parent()
        old = parent.revisions
        invalid = (
            RevisionLineageKind.CORRECTED_FROM,
            RevisionLineageKind.SPLIT_FROM,
            RevisionLineageKind.MERGED_FROM,
        )
        for kind in invalid:
            with self.subTest(kind=kind):
                with self.assertRaises(ValidationError):
                    RevisionLineage(kind, None, (old[0].ref,), ())
        with self.assertRaises(ValidationError):
            RevisionLineage(
                RevisionLineageKind.MERGED_FROM,
                parent.ref,
                (old[0].ref,),
                (),
            )
        with self.assertRaises(ValidationError):
            RevisionLineage(
                RevisionLineageKind.MANUAL_NEW,
                parent.ref,
                (old[0].ref,),
                (),
            )

    def test_parent_manifest_rejects_a_forged_edition_digest(self) -> None:
        parent_manifest = ParentEditionManifest.from_edition(seal_parent())
        forged_ref = EditionRef(
            parent_manifest.edition_ref.transcript_edition_id,
            ContentDigest("sha256", "8" * 64),
        )
        with self.assertRaises(ValidationError):
            replace(parent_manifest, edition_ref=forged_ref)


if __name__ == "__main__":
    unittest.main()
