"""Evidence the domain accepts as verified input but cannot compute itself.

Three Task 5 values arrive at the Release module already measured:
`SelectedEditionEvidence` describes a sealed `TranscriptEdition`,
`IntegrityCheckResult` describes stored artifacts, and both must be derived
from something the Release module cannot see. Release refuses to guess -- it
takes the evidence and checks its shape -- so measuring it belongs here, where
the aggregates and the artifact store are both reachable.

Everything in this module is a pure function of what it is handed. Nothing
writes, nothing decides eligibility, and nothing accepts a caller's summary of
an object it could measure instead. That is the whole point: an assessment
supplied by the same caller who wants it to pass is not evidence.
"""

from __future__ import annotations

from heritage_production.domain.release import (
    IntegrityCheckCode,
    IntegrityCheckResult,
    SelectedEditionEvidence,
    TranscriptScopeAssessment,
    UncertaintyObservation,
)
from heritage_production.domain.shared import (
    ContentDigest,
    SourceSpan,
    ValidationError,
)
from heritage_production.domain.transcription import TranscriptEdition, UncertaintyKind


def _overlaps(left: SourceSpan, right: SourceSpan) -> bool:
    """Two spans of the same source version that share any microsecond."""
    if left.source_version != right.source_version:
        return False
    return left.start_us < right.end_us and right.start_us < left.end_us


def assess_scope(edition: TranscriptEdition) -> TranscriptScopeAssessment:
    """Count how much of the declared scope the edition's revisions reach.

    A required span counts as covered when some revision of this edition
    actually spans part of it. Coverage is measured, never declared, so an
    edition cannot assert completeness it does not have.

    Declared gaps are counted separately rather than treated as coverage: a
    gap is an explicit statement that something is *not* transcribed, and
    folding it into the covered count would erase exactly that distinction.
    """
    if type(edition) is not TranscriptEdition:
        raise ValidationError("scope assessment requires an exact TranscriptEdition")
    required = edition.transcript_scope.required_spans
    covered = sum(
        1
        for span in required
        if any(_overlaps(span, revision.source_span) for revision in edition.revisions)
    )
    return TranscriptScopeAssessment(
        required_span_count=len(required),
        covered_span_count=covered,
        declared_gap_count=len(edition.gaps),
        uncovered_span_count=len(required) - covered,
    )


def observe_uncertainty(
    edition: TranscriptEdition,
) -> tuple[UncertaintyObservation, ...]:
    """Measure each kind of uncertainty mark the edition's revisions carry.

    One observation per kind that actually occurs, in canonical kind order.
    A kind with no marks is absent rather than reported as zero: the policy
    compares against allowances by kind, and an explicit zero would be a claim
    about a kind this edition never used.

    `character_count` sums only marks that carry a character span. A mark
    without one covers a source range rather than a text range, and inventing
    a character count for it would be exactly the guessed semantics design
    10.4 forbids elsewhere.
    """
    if type(edition) is not TranscriptEdition:
        raise ValidationError("uncertainty observation requires an exact TranscriptEdition")
    totals: dict[UncertaintyKind, list[int]] = {}
    for revision in edition.revisions:
        for mark in revision.uncertainty_marks:
            running = totals.setdefault(mark.kind, [0, 0, 0])
            running[0] += 1
            running[1] += mark.source_span.end_us - mark.source_span.start_us
            if mark.character_span is not None:
                running[2] += mark.character_span.end - mark.character_span.start
    return tuple(
        UncertaintyObservation(
            kind=kind,
            mark_count=totals[kind][0],
            source_duration_us=totals[kind][1],
            character_count=totals[kind][2],
        )
        for kind in sorted(totals, key=lambda value: value.value)
    )


def derive_edition_evidence(edition: TranscriptEdition) -> SelectedEditionEvidence:
    """Measure a sealed edition into the evidence Release will evaluate.

    The edition ref is taken from the edition itself rather than accepted
    alongside it, so the evidence cannot describe one edition while naming
    another. `SelectedEditionEvidence` carries a derived
    `heritage-edition-evidence-v1` digest, and that digest is what must reach
    the sealed release content's `provenance_input_digests`.
    """
    # No reconstruct-and-compare here. The aggregates use it because they
    # accept values a caller supplied; this builds every part itself from a
    # sealed edition, so there is no forged child for it to catch. A guard no
    # input can reach reads as coverage without being any.
    return SelectedEditionEvidence(
        production_id=edition.production_id,
        edition_ref=edition.ref,
        scope_assessment=assess_scope(edition),
        uncertainty_observations=observe_uncertainty(edition),
    )


def check_object_digests(
    artifacts,
    declared: tuple,
) -> IntegrityCheckResult:
    """Confirm every declared artifact still matches its recorded digest.

    The store is re-read rather than trusted, so this fails when bytes have
    changed underneath a reference that still looks correct.
    """
    missing = tuple(
        artifact for artifact in declared if not artifacts.verify(artifact)
    )
    if missing:
        return IntegrityCheckResult(
            IntegrityCheckCode("object-digests"),
            False,
            f"{len(missing)} of {len(declared)} declared artifacts "
            f"do not match their stored bytes",
        )
    return IntegrityCheckResult(
        IntegrityCheckCode("object-digests"),
        True,
        f"all {len(declared)} declared artifacts match their stored bytes",
    )


def check_sealed_manifests(reloaded: tuple) -> IntegrityCheckResult:
    """Confirm storage still holds the sealed objects a manifest pins.

    Each entry is `(expected_ref, reloaded_root_or_None)`. The caller does the
    loading because only it knows which repository each root belongs to; this
    measures what came back.

    Note what is deliberately *not* checked here: whether a root hashes to its
    own recorded digest. Every sealed root derives `ref` from
    `semantic_digest`, so comparing the two in memory is a tautology that can
    never fail -- an integrity check that always passes is worse than none,
    because it reads as coverage. Recomputation happens where it can actually
    fail: the repository reconstitutes a sealed root on load and refuses one
    whose stored content no longer matches its stored digest (design 11.6).
    What this adds is the other half -- that storage still returns the object
    the manifest names, rather than some other object under the same id.
    """
    drifted = 0
    for entry in reloaded:
        if type(entry) is not tuple or len(entry) != 2:
            raise ValidationError(
                "sealed-manifest inputs must be (expected_ref, root_or_None) pairs"
            )
        expected_ref, root = entry
        if root is None or getattr(root, "ref", None) != expected_ref:
            drifted += 1
    if drifted:
        return IntegrityCheckResult(
            IntegrityCheckCode("sealed-manifests"),
            False,
            f"{drifted} of {len(reloaded)} sealed manifests are missing or "
            f"no longer match the reference that pins them",
        )
    return IntegrityCheckResult(
        IntegrityCheckCode("sealed-manifests"),
        True,
        f"all {len(reloaded)} sealed manifests match the references that pin them",
    )


def integrity_input_digests(results: tuple) -> tuple[ContentDigest, ...]:
    """The digests that must reach a sealed manifest's integrity inputs.

    Order follows the check codes so the manifest's input list is canonical
    rather than dependent on the order checks happened to run in.
    """
    for result in results:
        if type(result) is not IntegrityCheckResult:
            raise ValidationError(
                "integrity inputs must be a tuple of IntegrityCheckResult"
            )
    codes = tuple(result.check_code.value for result in results)
    if len(set(codes)) != len(codes):
        raise ValidationError("integrity results must be unique by check code")
    return tuple(
        result.semantic_digest
        for result in sorted(results, key=lambda value: value.check_code.value)
    )


__all__ = [
    "assess_scope",
    "check_object_digests",
    "check_sealed_manifests",
    "derive_edition_evidence",
    "integrity_input_digests",
    "observe_uncertainty",
]
