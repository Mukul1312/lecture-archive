from __future__ import annotations

from dataclasses import replace
import unittest

from heritage_production.domain.shared import (
    ActorId,
    ContentDigest,
    DomainEventId,
    EditionRef,
    ProductionId,
    ProposalSetId,
    ReviewFindingId,
    SegmentId,
    SegmentRevisionId,
    SourceSpan,
    SourceVersionId,
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
    ProposalSetRef,
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
    parent_manifest = ParentEditionManifest.from_edition(parent, ())
    old = parent.revisions
    unchanged = old[0]
    correction = SegmentRevision.create(
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
        accepted_findings=(),
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
        accepted_findings=(),
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

    def test_mid_list_split_retains_untouched_downstream_exact_refs(self) -> None:
        parent = seal_parent()
        old = parent.revisions
        split_first = SegmentRevision.create(
            segment_id=SegmentId(uid(480)),
            segment_revision_id=SegmentRevisionId(uid(481)),
            source_span=SourceSpan(SOURCE, 2_000, 3_000),
            text=TranscriptText("split first"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.split_from(parent.ref, old[1].ref),
        )
        split_second = SegmentRevision.create(
            segment_id=SegmentId(uid(482)),
            segment_revision_id=SegmentRevisionId(uid(483)),
            source_span=SourceSpan(SOURCE, 3_000, 4_000),
            text=TranscriptText("split second"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.split_from(parent.ref, old[1].ref),
        )
        revisions = (old[0], split_first, split_second, *old[2:])
        manifest = EditionChangeManifest(
            (
                EditionChange.unchanged(old[0].ref, old[0].ref),
                EditionChange.split(
                    old[1].ref,
                    (split_first.ref, split_second.ref),
                    actor_id=STEWARD_ID,
                    reason="Split a compound utterance",
                ),
                *(EditionChange.unchanged(value.ref, value.ref) for value in old[2:]),
            ),
            (),
        )

        successor = TranscriptEdition.seal_successor(
            transcript_edition_id=TranscriptEditionId(uid(484)),
            production_id=parent.production_id,
            source_versions=parent.source_versions,
            transcript_scope=parent.transcript_scope,
            proposal_set_refs=(),
            parent_edition_ref=parent.ref,
            parent_manifest=ParentEditionManifest.from_edition(parent, ()),
            accepted_findings=(),
            revisions=revisions,
            gaps=(),
            change_manifest=manifest,
            creation_actor_id=STEWARD_ID,
            created_at_us=4_800,
            event_id=DomainEventId(uid(485)),
            event_occurred_at_us=4_801,
        )

        self.assertEqual(
            tuple(revision.ref for revision in successor.revisions[3:]),
            tuple(revision.ref for revision in old[2:]),
        )

    def test_mid_list_merge_retains_untouched_downstream_exact_refs(self) -> None:
        parent = seal_parent()
        old = parent.revisions
        merged = SegmentRevision.create(
            segment_id=SegmentId(uid(486)),
            segment_revision_id=SegmentRevisionId(uid(487)),
            source_span=SourceSpan(SOURCE, 2_000, 6_000),
            text=TranscriptText("merged utterance"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.merged_from(
                parent.ref,
                (old[1].ref, old[2].ref),
            ),
        )
        revisions = (old[0], merged, *old[3:])
        manifest = EditionChangeManifest(
            (
                EditionChange.unchanged(old[0].ref, old[0].ref),
                EditionChange.merge(
                    (old[1].ref, old[2].ref),
                    merged.ref,
                    actor_id=STEWARD_ID,
                    reason="Merge one utterance split across rows",
                ),
                *(EditionChange.unchanged(value.ref, value.ref) for value in old[3:]),
            ),
            (),
        )

        successor = TranscriptEdition.seal_successor(
            transcript_edition_id=TranscriptEditionId(uid(488)),
            production_id=parent.production_id,
            source_versions=parent.source_versions,
            transcript_scope=parent.transcript_scope,
            proposal_set_refs=(),
            parent_edition_ref=parent.ref,
            parent_manifest=ParentEditionManifest.from_edition(parent, ()),
            accepted_findings=(),
            revisions=revisions,
            gaps=(),
            change_manifest=manifest,
            creation_actor_id=STEWARD_ID,
            created_at_us=4_900,
            event_id=DomainEventId(uid(489)),
            event_occurred_at_us=4_901,
        )

        self.assertEqual(
            tuple(revision.ref for revision in successor.revisions[2:]),
            tuple(revision.ref for revision in old[3:]),
        )

    def test_accepted_findings_map_to_applied_revision_or_justified_no_change(self) -> None:
        parent = seal_parent()
        old = parent.revisions
        corrected = SegmentRevision.create(
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
        successor_values: dict[str, object] = dict(
            transcript_edition_id=TranscriptEditionId(uid(373)),
            production_id=PRODUCTION_ID,
            source_versions=(SOURCE,),
            transcript_scope=parent.transcript_scope,
            proposal_set_refs=(),
            parent_edition_ref=parent.ref,
            parent_manifest=ParentEditionManifest.from_edition(parent, ()),
            revisions=revisions,
            gaps=(),
            change_manifest=manifest,
            creation_actor_id=STEWARD_ID,
            created_at_us=3_000,
            event_id=DomainEventId(uid(374)),
            event_occurred_at_us=3_001,
        )

        with self.assertRaises(ValidationError):
            TranscriptEdition.seal_successor(**successor_values)  # type: ignore[arg-type]

        edition = TranscriptEdition.seal_successor(
            accepted_findings=(applied, no_change),
            **successor_values,  # type: ignore[arg-type]
        )

        self.assertEqual(edition.change_manifest.finding_mappings, manifest.finding_mappings)
        self.assertFalse(hasattr(edition, "accepted_findings"))

        missing_mapping = EditionChangeManifest(
            manifest.changes,
            (manifest.finding_mappings[0],),
        )
        invalid_inputs = (
            (missing_mapping, (applied, no_change)),
            (manifest, (applied,)),
            (manifest, (applied, applied, no_change)),
            (
                manifest,
                (
                    FindingChangeRef(
                        applied.review_finding_id,
                        ContentDigest("sha256", "7" * 64),
                        applied.disposition_digest,
                    ),
                    no_change,
                ),
            ),
            (manifest, (no_change, applied)),
            (manifest, [applied, no_change]),
        )
        for invalid_manifest, accepted_findings in invalid_inputs:
            with self.subTest(
                manifest=invalid_manifest,
                accepted_findings=accepted_findings,
            ):
                with self.assertRaises(ValidationError):
                    TranscriptEdition.seal_successor(
                        accepted_findings=accepted_findings,
                        **{
                            **successor_values,
                            "change_manifest": invalid_manifest,
                        },  # type: ignore[arg-type]
                    )

    def test_steward_can_fill_a_parent_gap_with_attributed_manual_new_revision(self) -> None:
        first = parent_revision(0)
        first = SegmentRevision.create(
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
            parent_manifest=ParentEditionManifest.from_edition(parent, ()),
            accepted_findings=(),
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

    def test_finding_mappings_require_unique_canonical_finding_keys(self) -> None:
        first = FindingChangeRef(
            ReviewFindingId(uid(386)),
            ContentDigest("sha256", "1" * 64),
            ContentDigest("sha256", "2" * 64),
        )
        second = FindingChangeRef(
            ReviewFindingId(uid(387)),
            ContentDigest("sha256", "3" * 64),
            ContentDigest("sha256", "4" * 64),
        )
        same_id_different_digest = FindingChangeRef(
            first.review_finding_id,
            ContentDigest("sha256", "5" * 64),
            ContentDigest("sha256", "6" * 64),
        )
        first_mapping = FindingMapping.no_edition_change(first, "No transcript change")
        second_mapping = FindingMapping.no_edition_change(second, "No transcript change")
        conflicting_mapping = FindingMapping.no_edition_change(
            same_id_different_digest,
            "Conflicting immutable evidence",
        )

        canonical = EditionChangeManifest((), (first_mapping, second_mapping))
        self.assertEqual(canonical.finding_mappings, (first_mapping, second_mapping))
        for mappings in (
            (second_mapping, first_mapping),
            (first_mapping, first_mapping),
            (first_mapping, conflicting_mapping),
        ):
            with self.subTest(mappings=mappings):
                with self.assertRaises(ValidationError):
                    EditionChangeManifest((), mappings)

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

    def test_changed_outputs_cannot_reuse_any_parent_revision_identity(self) -> None:
        edition, parent_manifest = structural_successor()
        parent_revisions = parent_manifest.revisions

        def with_revision_id(
            revision: SegmentRevision,
            revision_id: SegmentRevisionId,
        ) -> SegmentRevision:
            return SegmentRevision.create(
                segment_id=revision.segment_id,
                segment_revision_id=revision_id,
                source_span=revision.source_span,
                text=revision.text,
                language=revision.language,
                speaker=revision.speaker,
                uncertainty_marks=revision.uncertainty_marks,
                lineage=revision.lineage,
            )

        invalid_structural_cases: list[
            tuple[tuple[SegmentRevision, ...], EditionChangeManifest]
        ] = []
        for revision_index, change_index, reused_parent_index in (
            (1, 1, 4),  # correction
            (2, 2, 4),  # split
            (4, 3, 2),  # merge
        ):
            revisions = list(edition.revisions)
            forged = with_revision_id(
                revisions[revision_index],
                parent_revisions[reused_parent_index].segment_revision_id,
            )
            revisions[revision_index] = forged
            changes = list(edition.change_manifest.changes)
            change = changes[change_index]
            outputs = list(change.output_revisions)
            outputs[0] = forged.ref
            changes[change_index] = EditionChange(
                change.kind,
                change.input_revisions,
                tuple(outputs),
                change.proposal_inputs,
                change.manual_actor_id,
                change.manual_reason,
            )
            invalid_structural_cases.append(
                (tuple(revisions), EditionChangeManifest(tuple(changes), ()))
            )

        for revisions, manifest in invalid_structural_cases:
            with self.subTest(change=manifest.changes):
                with self.assertRaises(ValidationError):
                    reseal_successor(
                        edition,
                        parent_manifest,
                        revisions=revisions,
                        change_manifest=manifest,
                    )

        retained = SegmentRevision.create(
            segment_id=SegmentId(uid(420)),
            segment_revision_id=SegmentRevisionId(uid(421)),
            source_span=SourceSpan(SOURCE, 0, 5_000),
            text=TranscriptText("partial parent"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.manual_initial(),
        )
        gap = SourceSpan(SOURCE, 5_000, 10_000)
        gap_parent = TranscriptEdition.seal_initial(
            transcript_edition_id=TranscriptEditionId(uid(422)),
            production_id=PRODUCTION_ID,
            source_versions=(SOURCE,),
            transcript_scope=TranscriptScope(
                (SOURCE,),
                (SourceSpan(SOURCE, 0, 10_000),),
                (gap,),
            ),
            proposal_set_refs=(),
            revisions=(retained,),
            gaps=(GapDeclaration(gap, "Pending recovery"),),
            change_manifest=EditionChangeManifest(
                (
                    EditionChange.initial_manual(
                        output_revisions=(retained.ref,),
                        actor_id=STEWARD_ID,
                        reason="Partial source transcription",
                    ),
                ),
                (),
            ),
            creation_actor_id=STEWARD_ID,
            created_at_us=1,
            event_id=DomainEventId(uid(423)),
            event_occurred_at_us=2,
        )
        corrected = SegmentRevision.create(
            segment_id=retained.segment_id,
            segment_revision_id=SegmentRevisionId(uid(424)),
            source_span=retained.source_span,
            text=TranscriptText("corrected parent content"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.corrected_from(gap_parent.ref, retained.ref),
        )
        manual_new = SegmentRevision.create(
            segment_id=SegmentId(uid(425)),
            segment_revision_id=retained.segment_revision_id,
            source_span=gap,
            text=TranscriptText("recovered gap"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.manual_new(),
        )
        with self.assertRaises(ValidationError):
            TranscriptEdition.seal_successor(
                transcript_edition_id=TranscriptEditionId(uid(426)),
                production_id=PRODUCTION_ID,
                source_versions=(SOURCE,),
                transcript_scope=TranscriptScope(
                    (SOURCE,),
                    (SourceSpan(SOURCE, 0, 10_000),),
                    (),
                ),
                proposal_set_refs=(),
                parent_edition_ref=gap_parent.ref,
                parent_manifest=ParentEditionManifest.from_edition(gap_parent, ()),
                accepted_findings=(),
                revisions=(corrected, manual_new),
                gaps=(),
                change_manifest=EditionChangeManifest(
                    (
                        EditionChange.correction(
                            retained.ref,
                            corrected.ref,
                            actor_id=STEWARD_ID,
                            reason="Corrected during gap recovery",
                        ),
                        EditionChange.manual_new(
                            manual_new.ref,
                            actor_id=STEWARD_ID,
                            reason="Recovered missing source region",
                        ),
                    ),
                    (),
                ),
                creation_actor_id=STEWARD_ID,
                created_at_us=3,
                event_id=DomainEventId(uid(427)),
                event_occurred_at_us=4,
            )

    def test_split_and_merge_cannot_exchange_parent_source_regions(self) -> None:
        edition, parent_manifest = structural_successor()

        def with_span(revision: SegmentRevision, span: SourceSpan) -> SegmentRevision:
            return SegmentRevision.create(
                segment_id=revision.segment_id,
                segment_revision_id=revision.segment_revision_id,
                source_span=span,
                text=revision.text,
                language=revision.language,
                speaker=revision.speaker,
                uncertainty_marks=revision.uncertainty_marks,
                lineage=revision.lineage,
            )

        revisions = list(edition.revisions)
        revisions[2] = with_span(revisions[2], SourceSpan(SOURCE, 6_000, 8_000))
        revisions[3] = with_span(revisions[3], SourceSpan(SOURCE, 8_000, 10_000))
        revisions[4] = with_span(revisions[4], SourceSpan(SOURCE, 4_000, 6_000))
        changes = list(edition.change_manifest.changes)
        changes[2] = EditionChange.split(
            changes[2].input_revisions[0],
            (revisions[2].ref, revisions[3].ref),
            actor_id=STEWARD_ID,
            reason="Invalid exchanged split region",
        )
        changes[3] = EditionChange.merge(
            changes[3].input_revisions,
            revisions[4].ref,
            actor_id=STEWARD_ID,
            reason="Invalid exchanged merge region",
        )

        with self.assertRaises(ValidationError):
            reseal_successor(
                edition,
                parent_manifest,
                revisions=tuple(revisions),
                change_manifest=EditionChangeManifest(tuple(changes), ()),
            )

    def test_split_and_merge_reject_noncanonical_or_inexact_geometry(self) -> None:
        edition, parent_manifest = structural_successor()
        other_source = replace(
            SOURCE,
            source_version_id=SourceVersionId(uid(490)),
        )

        def with_span(
            revision: SegmentRevision,
            span: SourceSpan,
            *,
            lineage: RevisionLineage | None = None,
        ) -> SegmentRevision:
            return SegmentRevision.create(
                segment_id=revision.segment_id,
                segment_revision_id=revision.segment_revision_id,
                source_span=span,
                text=revision.text,
                language=revision.language,
                speaker=revision.speaker,
                uncertainty_marks=revision.uncertainty_marks,
                lineage=lineage or revision.lineage,
            )

        def split_case(
            first_span: SourceSpan,
            second_span: SourceSpan,
            *,
            reverse_outputs: bool = False,
        ) -> tuple[tuple[SegmentRevision, ...], EditionChangeManifest]:
            revisions = list(edition.revisions)
            revisions[2] = with_span(revisions[2], first_span)
            revisions[3] = with_span(revisions[3], second_span)
            output_refs = (revisions[2].ref, revisions[3].ref)
            if reverse_outputs:
                output_refs = tuple(reversed(output_refs))
            changes = list(edition.change_manifest.changes)
            changes[2] = EditionChange.split(
                changes[2].input_revisions[0],
                output_refs,
                actor_id=STEWARD_ID,
                reason="Adversarial split geometry",
            )
            return tuple(revisions), EditionChangeManifest(tuple(changes), ())

        split_cases = (
            split_case(
                SourceSpan(SOURCE, 4_000, 5_000),
                SourceSpan(SOURCE, 5_000, 6_000),
                reverse_outputs=True,
            ),
            split_case(
                SourceSpan(SOURCE, 4_000, 4_900),
                SourceSpan(SOURCE, 5_000, 6_000),
            ),
            split_case(
                SourceSpan(SOURCE, 4_000, 5_100),
                SourceSpan(SOURCE, 5_000, 6_000),
            ),
            split_case(
                SourceSpan(other_source, 4_000, 5_000),
                SourceSpan(SOURCE, 5_000, 6_000),
            ),
            split_case(
                SourceSpan(SOURCE, 4_100, 5_000),
                SourceSpan(SOURCE, 5_000, 6_000),
            ),
        )
        for revisions, manifest in split_cases:
            with self.subTest(split=manifest.changes[2]):
                with self.assertRaises(ValidationError):
                    reseal_successor(
                        edition,
                        parent_manifest,
                        revisions=revisions,
                        change_manifest=manifest,
                    )

        def merge_case(
            span: SourceSpan,
            *,
            reverse_inputs: bool = False,
        ) -> tuple[tuple[SegmentRevision, ...], EditionChangeManifest]:
            revisions = list(edition.revisions)
            changes = list(edition.change_manifest.changes)
            input_refs = changes[3].input_revisions
            if reverse_inputs:
                input_refs = tuple(reversed(input_refs))
            lineage = RevisionLineage.merged_from(parent_manifest.edition_ref, input_refs)
            revisions[4] = with_span(revisions[4], span, lineage=lineage)
            changes[3] = EditionChange.merge(
                input_refs,
                revisions[4].ref,
                actor_id=STEWARD_ID,
                reason="Adversarial merge geometry",
            )
            return tuple(revisions), EditionChangeManifest(tuple(changes), ())

        merge_cases = (
            merge_case(SourceSpan(SOURCE, 6_000, 10_000), reverse_inputs=True),
            merge_case(SourceSpan(SOURCE, 6_100, 10_000)),
            merge_case(SourceSpan(SOURCE, 6_000, 9_900)),
            merge_case(SourceSpan(other_source, 6_000, 10_000)),
        )
        for revisions, manifest in merge_cases:
            with self.subTest(merge=manifest.changes[3]):
                with self.assertRaises(ValidationError):
                    reseal_successor(
                        edition,
                        parent_manifest,
                        revisions=revisions,
                        change_manifest=manifest,
                    )

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

    def test_merge_rejects_parent_inputs_separated_by_out_of_scope_time(self) -> None:
        first = SegmentRevision.create(
            segment_id=SegmentId(uid(491)),
            segment_revision_id=SegmentRevisionId(uid(492)),
            source_span=SourceSpan(SOURCE, 0, 2_000),
            text=TranscriptText("first region"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.manual_initial(),
        )
        second = SegmentRevision.create(
            segment_id=SegmentId(uid(493)),
            segment_revision_id=SegmentRevisionId(uid(494)),
            source_span=SourceSpan(SOURCE, 4_000, 6_000),
            text=TranscriptText("second region"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.manual_initial(),
        )
        parent = TranscriptEdition.seal_initial(
            transcript_edition_id=TranscriptEditionId(uid(495)),
            production_id=PRODUCTION_ID,
            source_versions=(SOURCE,),
            transcript_scope=TranscriptScope(
                (SOURCE,),
                (
                    first.source_span,
                    second.source_span,
                ),
                (),
            ),
            proposal_set_refs=(),
            revisions=(first, second),
            gaps=(),
            change_manifest=EditionChangeManifest(
                (
                    EditionChange.initial_manual(
                        output_revisions=(first.ref, second.ref),
                        actor_id=STEWARD_ID,
                        reason="Disjoint required source regions",
                    ),
                ),
                (),
            ),
            creation_actor_id=STEWARD_ID,
            created_at_us=4_950,
            event_id=DomainEventId(uid(496)),
            event_occurred_at_us=4_951,
        )
        merged = SegmentRevision.create(
            segment_id=SegmentId(uid(497)),
            segment_revision_id=SegmentRevisionId(uid(498)),
            source_span=SourceSpan(SOURCE, 0, 6_000),
            text=TranscriptText("invalid merge across omitted source time"),
            language="en",
            speaker=None,
            uncertainty_marks=(),
            lineage=RevisionLineage.merged_from(
                parent.ref,
                (first.ref, second.ref),
            ),
        )

        with self.assertRaises(ValidationError):
            TranscriptEdition.seal_successor(
                transcript_edition_id=TranscriptEditionId(uid(499)),
                production_id=PRODUCTION_ID,
                source_versions=(SOURCE,),
                transcript_scope=TranscriptScope(
                    (SOURCE,),
                    (merged.source_span,),
                    (),
                ),
                proposal_set_refs=(),
                parent_edition_ref=parent.ref,
                parent_manifest=ParentEditionManifest.from_edition(parent, ()),
                accepted_findings=(),
                revisions=(merged,),
                gaps=(),
                change_manifest=EditionChangeManifest(
                    (
                        EditionChange.merge(
                            (first.ref, second.ref),
                            merged.ref,
                            actor_id=STEWARD_ID,
                            reason="Invalid noncontiguous merge",
                        ),
                    ),
                    (),
                ),
                creation_actor_id=STEWARD_ID,
                created_at_us=4_952,
                event_id=DomainEventId(uid(500)),
                event_occurred_at_us=4_953,
            )

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

    def test_complete_ancestry_rejects_parent_and_deeper_edition_id_reuse(self) -> None:
        first = seal_parent()

        def seal_unchanged(
            parent: TranscriptEdition,
            parent_manifest: ParentEditionManifest,
            edition_id: TranscriptEditionId,
            event_suffix: int,
        ) -> TranscriptEdition:
            return TranscriptEdition.seal_successor(
                transcript_edition_id=edition_id,
                production_id=parent.production_id,
                source_versions=parent.source_versions,
                transcript_scope=parent.transcript_scope,
                proposal_set_refs=parent.proposal_set_refs,
                parent_edition_ref=parent.ref,
                parent_manifest=parent_manifest,
                accepted_findings=(),
                revisions=parent.revisions,
                gaps=parent.gaps,
                change_manifest=EditionChangeManifest(
                    tuple(
                        EditionChange.unchanged(revision.ref, revision.ref)
                        for revision in parent.revisions
                    ),
                    (),
                ),
                creation_actor_id=STEWARD_ID,
                created_at_us=event_suffix,
                event_id=DomainEventId(uid(event_suffix)),
                event_occurred_at_us=event_suffix + 1,
            )

        first_manifest = ParentEditionManifest.from_edition(first, ())
        second = seal_unchanged(
            first,
            first_manifest,
            TranscriptEditionId(uid(440)),
            441,
        )
        second_manifest = ParentEditionManifest.from_edition(second, (first.ref,))

        with self.assertRaises(ValidationError):
            seal_unchanged(
                second,
                second_manifest,
                first.transcript_edition_id,
                442,
            )

        third = seal_unchanged(
            second,
            second_manifest,
            TranscriptEditionId(uid(444)),
            445,
        )
        third_manifest = ParentEditionManifest.from_edition(
            third,
            (second.ref, first.ref),
        )
        with self.assertRaises(ValidationError):
            seal_unchanged(
                third,
                third_manifest,
                first.transcript_edition_id,
                446,
            )

        with self.assertRaises(ValidationError):
            ParentEditionManifest.from_edition(second, ())
        with self.assertRaises(ValidationError):
            ParentEditionManifest.from_edition(second, (second.ref,))
        with self.assertRaises(ValidationError):
            ParentEditionManifest.from_edition(
                third,
                (second.ref, first.ref, first.ref),
            )
        with self.assertRaises(ValidationError):
            ParentEditionManifest.from_edition(first, ("not-an-edition-ref",))  # type: ignore[arg-type]

    def test_parent_manifest_rejects_a_forged_edition_digest(self) -> None:
        parent_manifest = ParentEditionManifest.from_edition(seal_parent(), ())
        forged_ref = EditionRef(
            parent_manifest.edition_ref.transcript_edition_id,
            ContentDigest("sha256", "8" * 64),
        )
        with self.assertRaises(ValidationError):
            replace(parent_manifest, edition_ref=forged_ref)

    def test_parent_manifest_reuses_snapshot_invariants_for_proposal_bindings(self) -> None:
        from tests.heritage_production.test_transcript_editions import seal_initial

        parent = seal_initial()
        parent_manifest = ParentEditionManifest.from_edition(parent, ())
        injected = ProposalSetRef(
            ProposalSetId(uid(470)),
            ContentDigest("sha256", "7" * 64),
        )

        for forged_proposal_refs in (
            (),
            (*parent.proposal_set_refs, injected),
        ):
            with self.subTest(proposal_set_refs=forged_proposal_refs):
                with self.assertRaises(ValidationError):
                    replace(
                        parent_manifest,
                        proposal_set_refs=forged_proposal_refs,
                    )


if __name__ == "__main__":
    unittest.main()
