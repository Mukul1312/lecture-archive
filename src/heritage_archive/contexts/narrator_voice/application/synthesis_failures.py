"""Evidence-bearing application failures for one synthesis invocation."""

from __future__ import annotations

from dataclasses import dataclass
import re

from heritage_archive.kernel import ArtifactRef, ContentDigest, ValidationError, canonical_json

from ..domain.evidence import ProviderEventEvidence, PublishedArtifact, SubmissionEvidence
from ..domain.values import NonNegativeDecimal
from .ports import _validate_synthesis_evidence


_REASON_CODE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class AuthoritativeUsageReceipt:
    """Exact provider-observed usage bound independently of artifact availability."""

    request_digest: ContentDigest
    response_evidence_digest: ContentDigest
    usage: NonNegativeDecimal

    def __post_init__(self) -> None:
        if type(self.request_digest) is not ContentDigest or type(self.response_evidence_digest) is not ContentDigest:
            raise ValidationError("authoritative usage requires exact request and response evidence digests")
        if type(self.usage) is not NonNegativeDecimal:
            raise ValidationError("authoritative usage receipt requires exact usage")


@dataclass(frozen=True, slots=True)
class SynthesisFailureEvidence:
    submission: SubmissionEvidence
    events: tuple[ProviderEventEvidence, ...]
    publications: tuple[PublishedArtifact, ...]
    raw_timing_reference: ArtifactRef | None
    usage: NonNegativeDecimal | None
    reason_code: str
    usage_receipt: AuthoritativeUsageReceipt | None = None

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
        if self.usage is None:
            if self.usage_receipt is not None:
                raise ValidationError("absent synthesis usage cannot carry an authoritative receipt")
        elif type(self.usage_receipt) is not AuthoritativeUsageReceipt or self.usage_receipt.usage != self.usage:
            raise ValidationError("synthesis failure usage requires its matching authoritative receipt")
        if self.submission is SubmissionEvidence.DEFINITELY_NOT_SENT and (
            self.usage is not None or any(event.usage is not None for event in self.events)
        ):
            raise ValidationError("definitely-not-sent failure cannot claim provider usage")
        if (
            type(self.reason_code) is not str
            or len(self.reason_code) > 64
            or _REASON_CODE.fullmatch(self.reason_code) is None
        ):
            raise ValidationError("synthesis failure reason must be a sanitized lower-snake-case code")

    @property
    def usage_recovery_fact(self) -> str | None:
        """Canonical sanitized fact for the existing workspace and budget hold log."""
        receipt = self.usage_receipt
        if receipt is None:
            return None
        return canonical_json({
            "schema": "narrator_voice.authoritative_usage_receipt",
            "schema_version": 1,
            "request_sha256": receipt.request_digest.hex_digest,
            "response_evidence_sha256": receipt.response_evidence_digest.hex_digest,
            "usage": receipt.usage.value,
            "reason_code": self.reason_code,
        }).decode("utf-8")


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
