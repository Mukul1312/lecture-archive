"""Evidence measured from sealed objects, not accepted from a caller.

These are the Task 5 residuals: `SelectedEditionEvidence` and
`IntegrityCheckResult` are inputs the Release module verifies but cannot
compute, because neither the edition nor the artifact store is visible from
there. The property that matters is that they are *measured* -- an assessment
handed over by the same caller who wants it to pass is not evidence, and the
digests these produce are what reach a sealed manifest's provenance and
integrity inputs.
"""

from __future__ import annotations

import unittest

from heritage_production.application.derivation import (
    assess_scope,
    check_object_digests,
    check_sealed_manifests,
    derive_edition_evidence,
    integrity_input_digests,
    observe_uncertainty,
)
from heritage_production.domain.release import (
    IntegrityCheckCode,
    IntegrityCheckResult,
)
from heritage_production.domain.shared import (
    ArtifactId,
    ContentDigest,
    SegmentId,
    SegmentRevisionId,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptScope,
    TranscriptText,
    ValidationError,
)
from heritage_production.domain.transcription import (
    CharacterSpan,
    GapDeclaration,
    ProposalItemRef,
    RevisionLineage,
    SegmentRevision,
    UncertaintyKind,
    UncertaintyMark,
)
from heritage_production.domain.shared import ProposalItemId

from tests.heritage_production.application_harness import ApplicationHarness
from tests.heritage_production.heritage_release_fixtures import uid
from tests.heritage_production.test_application_august21_walkthrough import (
    AUGUST_21,
    Walkthrough,
)
from tests.heritage_production.test_transcript_editions import initial_manifest


# Two halves of the one recording. The revision covers only the first, so a
# scope declaring both has something genuinely uncovered -- a span outside the
# source's declared duration would be refused by the domain, not measured.
FIRST_HALF = SourceSpan(AUGUST_21, 0, 300_000_000)
LATER_SPAN = SourceSpan(AUGUST_21, 300_000_000, 600_000_000)


def revision(
    proposal_set,
    *,
    identifier: int = 1101,
    span: SourceSpan = FIRST_HALF,
    marks: tuple = (),
) -> SegmentRevision:
    return SegmentRevision.create(
        segment_id=SegmentId(uid(identifier)),
        segment_revision_id=SegmentRevisionId(uid(identifier + 1000)),
        source_span=span,
        text=TranscriptText("om namo bhagavate"),
        language="sa",
        speaker=None,
        uncertainty_marks=marks,
        lineage=RevisionLineage.proposal_derived(
            (ProposalItemRef(proposal_set.ref, ProposalItemId(uid(1001))),)
        ),
    )


class EditionFixture:
    """A sealed edition whose scope and marks the tests vary."""

    def __init__(
        self, *, required=(FIRST_HALF,), excluded=(), marks=(), gaps=()
    ) -> None:
        self.walk = Walkthrough()
        harness = self.walk.harness
        self.production_id = harness.create(
            deliverable="August 21 1985 listening transcript"
        ).result.production_id
        harness.attach(self.production_id, AUGUST_21, expected_version=1)
        from tests.heritage_production.test_application_august21_walkthrough import (
            steward_attestation,
        )

        self.proposal_set = harness.import_package(
            self.walk.package, AUGUST_21, steward_attestation=steward_attestation()
        ).result
        self.revision = revision(self.proposal_set, marks=marks)
        self.edition = harness.create_initial_edition(
            self.production_id,
            source_versions=(AUGUST_21,),
            transcript_scope=TranscriptScope((AUGUST_21,), required, excluded),
            proposal_set_refs=(self.proposal_set.ref,),
            revisions=(self.revision,),
            gaps=gaps,
            change_manifest=initial_manifest(self.revision),
        ).result
        self.harness = harness


SECOND_SOURCE = SourceVersionRef(
    SourceVersionId(uid(1986)),
    SourceRecordingId(uid(822)),
    ContentDigest("sha256", "d4" * 32),
    600_000_000,
    "microseconds",
)
# Deliberately the same microseconds as FIRST_HALF, on a different recording.
SECOND_SOURCE_SPAN = SourceSpan(SECOND_SOURCE, 0, 300_000_000)


class TwoSourceFixture:
    """One edition over two recordings, only one of which is transcribed."""

    def __init__(self) -> None:
        walk = Walkthrough()
        harness = walk.harness
        self.production_id = harness.create(
            deliverable="August 21 1985 listening transcript"
        ).result.production_id
        harness.attach(self.production_id, AUGUST_21, expected_version=1)
        from tests.heritage_production.test_application_august21_walkthrough import (
            steward_attestation,
        )

        self.proposal_set = harness.import_package(
            walk.package, AUGUST_21, steward_attestation=steward_attestation()
        ).result
        self.revision = revision(self.proposal_set)
        self.edition = harness.create_initial_edition(
            self.production_id,
            source_versions=(AUGUST_21, SECOND_SOURCE),
            transcript_scope=TranscriptScope(
                (AUGUST_21, SECOND_SOURCE),
                (FIRST_HALF, SECOND_SOURCE_SPAN),
                (SECOND_SOURCE_SPAN,),
            ),
            proposal_set_refs=(self.proposal_set.ref,),
            revisions=(self.revision,),
            gaps=(GapDeclaration(SECOND_SOURCE_SPAN, "second recording not yet transcribed"),),
            change_manifest=initial_manifest(self.revision),
        ).result
        self.harness = harness


class ScopeAssessmentTests(unittest.TestCase):
    def test_a_fully_covered_scope_reports_no_uncovered_span(self) -> None:
        fixture = EditionFixture()

        assessment = assess_scope(fixture.edition)

        self.assertEqual(assessment.required_span_count, 1)
        self.assertEqual(assessment.covered_span_count, 1)
        self.assertEqual(assessment.uncovered_span_count, 0)
        self.assertEqual(assessment.declared_gap_count, 0)

    def test_a_required_span_reachable_by_no_revision_cannot_be_sealed(self) -> None:
        """The domain is stricter than the assessment needed to assume.

        An edition's revisions and gaps must cover the required scope exactly,
        so a span nothing reaches cannot be sealed at all -- it must be
        declared a gap first. The assessment therefore never sees a silently
        missing span; what it distinguishes is transcribed from gap-declared.
        """
        with self.assertRaises(ValidationError):
            EditionFixture(required=(FIRST_HALF, LATER_SPAN))

    def test_a_declared_gap_is_counted_but_never_counted_as_coverage(self) -> None:
        """A gap says something is *not* transcribed; folding it into
        coverage would erase exactly that statement."""
        fixture = EditionFixture(
            required=(FIRST_HALF, LATER_SPAN),
            excluded=(LATER_SPAN,),
            gaps=(GapDeclaration(LATER_SPAN, "recording ends mid-sentence"),),
        )

        assessment = assess_scope(fixture.edition)

        self.assertEqual(assessment.required_span_count, 2)
        self.assertEqual(assessment.declared_gap_count, 1)
        self.assertEqual(assessment.covered_span_count, 1)
        # The gap-declared half is not transcribed, so it is not coverage.
        self.assertEqual(assessment.uncovered_span_count, 1)

    def test_a_revision_of_another_source_never_covers_this_one(self) -> None:
        """Two recordings can share a time range without sharing content.

        Matching spans by microseconds alone would let a revision of one
        recording report coverage of another -- the assessment would be
        internally consistent and simply untrue.
        """
        fixture = TwoSourceFixture()

        assessment = assess_scope(fixture.edition)

        self.assertEqual(assessment.required_span_count, 2)
        self.assertEqual(assessment.covered_span_count, 1)
        self.assertEqual(assessment.uncovered_span_count, 1)
        self.assertEqual(assessment.declared_gap_count, 1)

    def test_it_refuses_anything_that_is_not_a_sealed_edition(self) -> None:
        for bad in (None, "edition", 7):
            with self.subTest(value=bad):
                with self.assertRaises(ValidationError):
                    assess_scope(bad)


class UncertaintyObservationTests(unittest.TestCase):
    def marks(self) -> tuple:
        """Deliberately not in canonical order.

        `uncertain_wording` sorts after `inaudible`, so listing it first is
        what makes the ordering assertion able to fail.
        """
        return (
            UncertaintyMark(
                UncertaintyKind.UNCERTAIN_WORDING,
                SourceSpan(AUGUST_21, 9_000_000, 12_000_000),
            ),
            UncertaintyMark(
                UncertaintyKind.INAUDIBLE,
                SourceSpan(AUGUST_21, 0, 2_000_000),
                CharacterSpan(0, 4),
            ),
            UncertaintyMark(
                UncertaintyKind.INAUDIBLE,
                SourceSpan(AUGUST_21, 5_000_000, 6_000_000),
                CharacterSpan(10, 13),
            ),
        )

    def test_each_kind_is_summed_separately(self) -> None:
        fixture = EditionFixture(marks=self.marks())

        observations = observe_uncertainty(fixture.edition)

        by_kind = {value.kind: value for value in observations}
        inaudible = by_kind[UncertaintyKind.INAUDIBLE]
        self.assertEqual(inaudible.mark_count, 2)
        self.assertEqual(inaudible.source_duration_us, 3_000_000)
        self.assertEqual(inaudible.character_count, 7)

    def test_a_mark_without_a_character_span_adds_no_character_count(self) -> None:
        """Inventing a character count would be a guessed semantic."""
        fixture = EditionFixture(marks=self.marks())

        observations = observe_uncertainty(fixture.edition)

        wording = {value.kind: value for value in observations}[
            UncertaintyKind.UNCERTAIN_WORDING
        ]
        self.assertEqual(wording.mark_count, 1)
        self.assertEqual(wording.source_duration_us, 3_000_000)
        self.assertEqual(wording.character_count, 0)

    def test_observations_are_in_canonical_kind_order(self) -> None:
        fixture = EditionFixture(marks=self.marks())

        observations = observe_uncertainty(fixture.edition)

        kinds = [value.kind.value for value in observations]
        self.assertEqual(kinds, sorted(kinds))

    def test_a_kind_with_no_marks_is_absent_rather_than_zero(self) -> None:
        """An explicit zero would assert something about a kind never used."""
        fixture = EditionFixture(marks=self.marks()[1:])

        observations = observe_uncertainty(fixture.edition)

        self.assertEqual(
            [value.kind for value in observations], [UncertaintyKind.INAUDIBLE]
        )

    def test_an_edition_with_no_marks_observes_nothing(self) -> None:
        fixture = EditionFixture()

        self.assertEqual(observe_uncertainty(fixture.edition), ())


class EditionEvidenceTests(unittest.TestCase):
    def test_the_evidence_names_the_edition_it_measured(self) -> None:
        """Taken from the edition, so it cannot describe one and name another."""
        fixture = EditionFixture()

        evidence = derive_edition_evidence(fixture.edition)

        self.assertEqual(evidence.edition_ref, fixture.edition.ref)
        self.assertEqual(evidence.production_id, fixture.production_id)

    def test_the_digest_is_derived_and_reproducible(self) -> None:
        fixture = EditionFixture()

        first = derive_edition_evidence(fixture.edition)
        second = derive_edition_evidence(fixture.edition)

        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertEqual(first, second)

    def test_a_different_edition_yields_a_different_digest(self) -> None:
        """The digest that must reach provenance_input_digests distinguishes."""
        covered = EditionFixture()
        partial = EditionFixture(
            required=(FIRST_HALF, LATER_SPAN),
            excluded=(LATER_SPAN,),
            gaps=(GapDeclaration(LATER_SPAN, "recording ends mid-sentence"),),
        )

        self.assertNotEqual(
            derive_edition_evidence(covered.edition).semantic_digest,
            derive_edition_evidence(partial.edition).semantic_digest,
        )

    def test_evidence_names_a_successor_by_its_own_reference(self) -> None:
        """Not its parent: an initial edition cannot tell the two apart."""
        from tests.heritage_production.test_application_successor_handler import (
            Fixture as SuccessorFixture,
        )

        fixture = SuccessorFixture()
        successor = fixture.successor().result

        evidence = derive_edition_evidence(successor)

        self.assertEqual(evidence.edition_ref, successor.ref)
        self.assertNotEqual(evidence.edition_ref, fixture.parent.ref)

    def test_uncertainty_changes_the_digest(self) -> None:
        plain = EditionFixture()
        marked = EditionFixture(
            marks=(
                UncertaintyMark(
                    UncertaintyKind.INAUDIBLE, SourceSpan(AUGUST_21, 0, 2_000_000)
                ),
            )
        )

        self.assertNotEqual(
            derive_edition_evidence(plain.edition).semantic_digest,
            derive_edition_evidence(marked.edition).semantic_digest,
        )


class IntegrityCheckTests(unittest.TestCase):
    def store(self) -> ApplicationHarness:
        return ApplicationHarness()

    def test_matching_artifacts_pass(self) -> None:
        harness = self.store()
        one = harness.artifacts.seed(ArtifactId(uid(2001)), b"first")
        two = harness.artifacts.seed(ArtifactId(uid(2002)), b"second")

        result = check_object_digests(harness.artifacts, (one, two))

        self.assertTrue(result.passed)
        self.assertEqual(result.check_code, IntegrityCheckCode("object-digests"))

    def test_bytes_changed_under_a_valid_looking_reference_fail(self) -> None:
        """The store is re-read, so a reference that still looks right fails."""
        harness = self.store()
        one = harness.artifacts.seed(ArtifactId(uid(2001)), b"first")
        harness.artifacts.corrupt(one, b"something else")

        result = check_object_digests(harness.artifacts, (one,))

        self.assertFalse(result.passed)
        self.assertIn("do not match", result.detail)

    def test_an_absent_artifact_fails(self) -> None:
        harness = self.store()
        absent = harness.artifacts.seed(ArtifactId(uid(2003)), b"gone")
        harness.artifacts.blobs.clear()

        self.assertFalse(check_object_digests(harness.artifacts, (absent,)).passed)

    def test_sealed_manifests_present_and_matching_pass(self) -> None:
        fixture = EditionFixture()
        edition = fixture.edition

        result = check_sealed_manifests(((edition.ref, edition),))

        self.assertTrue(result.passed)

    def test_a_missing_sealed_manifest_fails(self) -> None:
        fixture = EditionFixture()

        result = check_sealed_manifests(((fixture.edition.ref, None),))

        self.assertFalse(result.passed)
        self.assertIn("missing", result.detail)

    def test_storage_returning_another_object_fails(self) -> None:
        """The half an in-memory digest comparison could never catch."""
        covered = EditionFixture()
        other = EditionFixture(
            required=(FIRST_HALF, LATER_SPAN),
            excluded=(LATER_SPAN,),
            gaps=(GapDeclaration(LATER_SPAN, "recording ends mid-sentence"),),
        )

        result = check_sealed_manifests(((covered.edition.ref, other.edition),))

        self.assertFalse(result.passed)

    def test_malformed_pairs_are_refused(self) -> None:
        for bad in ((None,), ("ref",), (1, 2, 3)):
            with self.subTest(entry=bad):
                with self.assertRaises(ValidationError):
                    check_sealed_manifests((bad,))


class IntegrityInputDigestTests(unittest.TestCase):
    def results(self) -> tuple:
        return (
            IntegrityCheckResult(IntegrityCheckCode("sealed-manifests"), True, "ok"),
            IntegrityCheckResult(IntegrityCheckCode("object-digests"), True, "ok"),
        )

    def test_digests_are_ordered_by_check_code(self) -> None:
        """Canonical, so a manifest's inputs do not depend on run order."""
        results = self.results()

        digests = integrity_input_digests(results)

        self.assertEqual(
            digests,
            (
                IntegrityCheckResult(
                    IntegrityCheckCode("object-digests"), True, "ok"
                ).semantic_digest,
                IntegrityCheckResult(
                    IntegrityCheckCode("sealed-manifests"), True, "ok"
                ).semantic_digest,
            ),
        )

    def test_the_order_results_arrive_in_does_not_matter(self) -> None:
        forward = integrity_input_digests(self.results())
        reversed_ = integrity_input_digests(tuple(reversed(self.results())))

        self.assertEqual(forward, reversed_)

    def test_a_failed_check_digests_differently_from_a_passed_one(self) -> None:
        passed = IntegrityCheckResult(IntegrityCheckCode("object-digests"), True, "ok")
        failed = IntegrityCheckResult(IntegrityCheckCode("object-digests"), False, "ok")

        self.assertNotEqual(passed.semantic_digest, failed.semantic_digest)

    def test_duplicate_check_codes_are_refused(self) -> None:
        duplicate = IntegrityCheckResult(
            IntegrityCheckCode("object-digests"), True, "again"
        )

        with self.assertRaises(ValidationError):
            integrity_input_digests((*self.results(), duplicate))

    def test_only_integrity_results_are_accepted(self) -> None:
        with self.assertRaises(ValidationError):
            integrity_input_digests((ContentDigest("sha256", "a" * 64),))


if __name__ == "__main__":
    unittest.main()
