"""Evidence-bearing application failures for one synthesis invocation."""

from __future__ import annotations

from dataclasses import dataclass
import re

from heritage_archive.kernel import ArtifactRef, ValidationError

from ..domain.evidence import ProviderEventEvidence, PublishedArtifact, SubmissionEvidence
from ..domain.values import NonNegativeDecimal
from .ports import _validate_synthesis_evidence


_REASON_CODE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SynthesisFailureEvidence:
    submission: SubmissionEvidence
    events: tuple[ProviderEventEvidence, ...]
    publications: tuple[PublishedArtifact, ...]
    raw_timing_reference: ArtifactRef | None
    usage: NonNegativeDecimal | None
    reason_code: str

    def __post_init__(self) -> None:
        if type(self.submission) is not SubmissionEvidence:
            raise ValidationError("synthesis failure requires exact submission evidence")
        _validate_synthesis_evidence(
            self.events,
            self.publications,
            self.raw_timing_reference,
        )
        if self.usage is not None and type(self.usage) is not NonNegativeDecimal:
            raise ValidationError("synthesis failure usage must be authoritative usage or None")
        if (
            type(self.reason_code) is not str
            or len(self.reason_code) > 64
            or _REASON_CODE.fullmatch(self.reason_code) is None
        ):
            raise ValidationError("synthesis failure reason must be a sanitized lower-snake-case code")


class _SynthesisFailure(Exception):
    expected_submissions: frozenset[SubmissionEvidence] = frozenset()

    def __init__(self, evidence: SynthesisFailureEvidence) -> None:
        if type(evidence) is not SynthesisFailureEvidence:
            raise ValidationError("synthesis failure requires immutable failure evidence")
        if evidence.submission not in self.expected_submissions:
            raise ValidationError("synthesis failure category contradicts submission evidence")
        self.evidence = evidence
        super().__init__(evidence.reason_code)


class SynthesisPreSendFailure(_SynthesisFailure):
    """Evidence proves no provider request was sent."""

    expected_submissions = frozenset({SubmissionEvidence.DEFINITELY_NOT_SENT})


class SynthesisAmbiguousFailure(_SynthesisFailure):
    """Evidence cannot prove whether provider work completed."""

    expected_submissions = frozenset({SubmissionEvidence.AMBIGUOUS})


class SynthesisSubmittedFailure(_SynthesisFailure):
    """The submitted provider work definitively failed."""

    expected_submissions = frozenset({SubmissionEvidence.STARTED, SubmissionEvidence.COMPLETED})
