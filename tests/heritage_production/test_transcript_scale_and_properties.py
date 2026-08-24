from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from hypothesis import given, settings, strategies as st

from heritage_production.domain.shared import (
    ActorId,
    ContentDigest,
    DomainEventId,
    ProductionId,
    SegmentId,
    SegmentRevisionId,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptEditionId,
    TranscriptScope,
    TranscriptText,
)
from heritage_production.domain.transcription import (
    EditionChange,
    EditionChangeManifest,
    ParentEditionManifest,
    RevisionLineage,
    SegmentRevision,
    TranscriptEdition,
)
from tests.heritage_production.test_transcription_proposals import uid


ACTOR = ActorId(uid(600))
PRODUCTION = ProductionId(uid(601))


def source(duration_us: int, suffix: int) -> SourceVersionRef:
    return SourceVersionRef(
        SourceVersionId(uid(suffix)),
        SourceRecordingId(uid(suffix + 1)),
        ContentDigest("sha256", "7" * 64),
        duration_us,
        "microseconds",
    )


def revisions_for(source_version: SourceVersionRef, count: int, id_base: int) -> tuple[SegmentRevision, ...]:
    revisions: list[SegmentRevision] = []
    for ordinal in range(count):
        start = ordinal * source_version.duration_us // count
        end = (ordinal + 1) * source_version.duration_us // count
        revisions.append(
            SegmentRevision.create(
                ordinal=ordinal,
                segment_id=SegmentId(uid(id_base + ordinal)),
                segment_revision_id=SegmentRevisionId(uid(id_base + count + ordinal)),
                source_span=SourceSpan(source_version, start, end),
                text=TranscriptText(f"segment-{ordinal}"),
                language="en",
                speaker=None,
                uncertainty_marks=(),
                lineage=RevisionLineage.manual_initial(),
            )
        )
    return tuple(revisions)


def initial_edition(count: int, *, id_base: int = 1_000) -> TranscriptEdition:
    source_version = source(10_000, 610)
    revisions = revisions_for(source_version, count, id_base)
    return TranscriptEdition.seal_initial(
        transcript_edition_id=TranscriptEditionId(uid(620)),
        production_id=PRODUCTION,
        source_versions=(source_version,),
        transcript_scope=TranscriptScope(
            (source_version,),
            (SourceSpan(source_version, 0, source_version.duration_us),),
            (),
        ),
        proposal_set_refs=(),
        revisions=revisions,
        gaps=(),
        change_manifest=EditionChangeManifest(
            (
                EditionChange.initial_manual(
                    output_revisions=tuple(revision.ref for revision in revisions),
                    actor_id=ACTOR,
                    reason="Synthetic deterministic transcript",
                ),
            ),
            (),
        ),
        creation_actor_id=ACTOR,
        created_at_us=1,
        event_id=DomainEventId(uid(621)),
        event_occurred_at_us=2,
    )


class GeneratedLineageTests(unittest.TestCase):
    @settings(max_examples=12, deadline=None, derandomize=True)
    @given(st.integers(min_value=1, max_value=25))
    def test_generated_unchanged_successors_preserve_exact_revision_refs(self, count: int) -> None:
        parent = initial_edition(count)
        parent_manifest = ParentEditionManifest.from_edition(parent)
        successor = TranscriptEdition.seal_successor(
            transcript_edition_id=TranscriptEditionId(uid(622)),
            production_id=PRODUCTION,
            source_versions=parent.source_versions,
            transcript_scope=parent.transcript_scope,
            proposal_set_refs=(),
            parent_edition_ref=parent.ref,
            parent_manifest=parent_manifest,
            revisions=parent.revisions,
            gaps=(),
            change_manifest=EditionChangeManifest(
                tuple(
                    EditionChange.unchanged(revision.ref, revision.ref)
                    for revision in parent.revisions
                ),
                (),
            ),
            creation_actor_id=ACTOR,
            created_at_us=3,
            event_id=DomainEventId(uid(623)),
            event_occurred_at_us=4,
        )

        self.assertEqual(
            tuple(revision.ref for revision in successor.revisions),
            tuple(revision.ref for revision in parent.revisions),
        )


class LargeSyntheticEditionTests(unittest.TestCase):
    def test_two_thousand_segment_manifest_seals_and_reconstitutes_digest_identically(self) -> None:
        source_version = source(2_000, 700)
        revisions = revisions_for(source_version, 2_000, 10_000)
        manifest = EditionChangeManifest(
            (
                EditionChange.initial_manual(
                    output_revisions=tuple(revision.ref for revision in revisions),
                    actor_id=ACTOR,
                    reason="Two-thousand-segment deterministic fixture",
                ),
            ),
            (),
        )
        scope = TranscriptScope(
            (source_version,),
            (SourceSpan(source_version, 0, 2_000),),
            (),
        )
        created = TranscriptEdition.seal_initial(
            transcript_edition_id=TranscriptEditionId(uid(702)),
            production_id=PRODUCTION,
            source_versions=(source_version,),
            transcript_scope=scope,
            proposal_set_refs=(),
            revisions=revisions,
            gaps=(),
            change_manifest=manifest,
            creation_actor_id=ACTOR,
            created_at_us=10,
            event_id=DomainEventId(uid(703)),
            event_occurred_at_us=11,
        )
        reconstituted = TranscriptEdition.reconstitute(
            transcript_edition_id=created.transcript_edition_id,
            production_id=created.production_id,
            source_versions=created.source_versions,
            transcript_scope=created.transcript_scope,
            proposal_set_refs=created.proposal_set_refs,
            revisions=created.revisions,
            gaps=created.gaps,
            change_manifest=created.change_manifest,
            creation_actor_id=created.creation_actor_id,
            created_at_us=created.created_at_us,
            semantic_digest=created.semantic_digest,
        )

        self.assertEqual(len(reconstituted.revisions), 2_000)
        self.assertEqual(reconstituted.change_manifest, manifest)
        self.assertEqual(reconstituted.semantic_digest, created.semantic_digest)
        self.assertEqual(reconstituted.pull_events(), ())
        with self.assertRaises(FrozenInstanceError):
            manifest.changes = ()  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
