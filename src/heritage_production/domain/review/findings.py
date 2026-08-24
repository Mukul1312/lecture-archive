"""Immutable review findings and append-only steward dispositions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from heritage_production.domain.shared import (
    ActorId,
    AggregateEventRecorder,
    ContentDigest,
    DomainEvent,
    DomainEventId,
    EditionRef,
    ReviewFindingId,
    ReviewRoundId,
    ReviewSubmissionId,
    RubricRef,
    SegmentRevisionRef,
    SourceSpan,
    TranscriptText,
    ValidationError,
    semantic_digest,
)
from heritage_production.domain.shared.text import require_canonical_text

from .rounds import OpenReviewContext
from .targets import (
    FindingCategoryCode,
    FindingSeverityCode,
    ReviewTargetKey,
    ReviewTargetManifest,
    _digest_value,
    _source_value,
)


@dataclass(frozen=True, slots=True)
class ClientFindingNonce:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.value, field="client finding nonce", nonempty=True)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ReviewCharacterSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int:
            raise ValidationError("character-span boundaries must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValidationError("character span must be a nonempty half-open range")


@dataclass(frozen=True, slots=True)
class ReviewUncertaintyCode:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.value, field="uncertainty code", nonempty=True)


@dataclass(frozen=True, slots=True)
class ProposedUncertainty:
    code: ReviewUncertaintyCode
    source_span: SourceSpan
    character_span: ReviewCharacterSpan | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if type(self.code) is not ReviewUncertaintyCode:
            raise ValidationError("code must be an exact ReviewUncertaintyCode")
        if type(self.source_span) is not SourceSpan:
            raise ValidationError("source_span must be an exact SourceSpan")
        if self.character_span is not None and type(self.character_span) is not ReviewCharacterSpan:
            raise ValidationError("character_span must be an exact ReviewCharacterSpan")
        if self.note is not None:
            require_canonical_text(self.note, field="uncertainty note", nonempty=True)


class ProposedChangeKind(str, Enum):
    TEXT_REPLACEMENT = "text_replacement"
    SOURCE_BOUNDARY = "source_boundary"
    SPEAKER_SET = "speaker_set"
    SPEAKER_CLEAR = "speaker_clear"
    LANGUAGE_SET = "language_set"
    LANGUAGE_CLEAR = "language_clear"
    UNCERTAINTY_REPLACE = "uncertainty_replace"
    UNCERTAINTY_CLEAR = "uncertainty_clear"


class FindingDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ProposedChange:
    kind: ProposedChangeKind
    replacement_text: TranscriptText | None = None
    source_span: SourceSpan | None = None
    scalar_value: str | None = None
    uncertainty_marks: tuple[ProposedUncertainty, ...] = ()

    def __post_init__(self) -> None:
        if type(self.kind) is not ProposedChangeKind:
            raise ValidationError("proposed change kind must be a ProposedChangeKind")
        if self.replacement_text is not None and type(self.replacement_text) is not TranscriptText:
            raise ValidationError("replacement_text must be an exact TranscriptText")
        if self.source_span is not None and type(self.source_span) is not SourceSpan:
            raise ValidationError("source_span must be an exact SourceSpan")
        if self.scalar_value is not None:
            require_canonical_text(self.scalar_value, field="proposed scalar value", nonempty=True)
        if type(self.uncertainty_marks) is not tuple or not all(
            type(mark) is ProposedUncertainty for mark in self.uncertainty_marks
        ):
            raise ValidationError("uncertainty_marks must be a tuple of ProposedUncertainty")
        expected = {
            ProposedChangeKind.TEXT_REPLACEMENT: (True, False, False, False),
            ProposedChangeKind.SOURCE_BOUNDARY: (False, True, False, False),
            ProposedChangeKind.SPEAKER_SET: (False, False, True, False),
            ProposedChangeKind.SPEAKER_CLEAR: (False, False, False, False),
            ProposedChangeKind.LANGUAGE_SET: (False, False, True, False),
            ProposedChangeKind.LANGUAGE_CLEAR: (False, False, False, False),
            ProposedChangeKind.UNCERTAINTY_REPLACE: (False, False, False, True),
            ProposedChangeKind.UNCERTAINTY_CLEAR: (False, False, False, False),
        }[self.kind]
        actual = (
            self.replacement_text is not None,
            self.source_span is not None,
            self.scalar_value is not None,
            bool(self.uncertainty_marks),
        )
        if actual != expected:
            raise ValidationError("proposed change has required or forbidden fields")

    @classmethod
    def text_replacement(cls, value: str) -> ProposedChange:
        return cls(ProposedChangeKind.TEXT_REPLACEMENT, TranscriptText(value))

    @classmethod
    def source_boundary(cls, value: SourceSpan) -> ProposedChange:
        return cls(ProposedChangeKind.SOURCE_BOUNDARY, source_span=value)

    @classmethod
    def speaker_set(cls, value: str) -> ProposedChange:
        return cls(ProposedChangeKind.SPEAKER_SET, scalar_value=value)

    @classmethod
    def speaker_clear(cls) -> ProposedChange:
        return cls(ProposedChangeKind.SPEAKER_CLEAR)

    @classmethod
    def language_set(cls, value: str) -> ProposedChange:
        return cls(ProposedChangeKind.LANGUAGE_SET, scalar_value=value)

    @classmethod
    def language_clear(cls) -> ProposedChange:
        return cls(ProposedChangeKind.LANGUAGE_CLEAR)

    @classmethod
    def uncertainty_replace(cls, values: tuple[ProposedUncertainty, ...]) -> ProposedChange:
        return cls(ProposedChangeKind.UNCERTAINTY_REPLACE, uncertainty_marks=values)

    @classmethod
    def uncertainty_clear(cls) -> ProposedChange:
        return cls(ProposedChangeKind.UNCERTAINTY_CLEAR)


def _character_span_value(value: ReviewCharacterSpan | None) -> dict[str, int] | None:
    if value is None:
        return None
    return {"start": value.start, "end": value.end}


def _uncertainty_value(value: ProposedUncertainty) -> dict[str, object]:
    return {
        "code": value.code.value,
        "source_span": _source_value(value.source_span),
        "character_span": _character_span_value(value.character_span),
        "note": value.note,
    }


def _proposed_change_value(value: ProposedChange | None) -> dict[str, object] | None:
    if value is None:
        return None
    payload: dict[str, object] = {"kind": value.kind.value}
    if value.replacement_text is not None:
        payload["replacement_text"] = value.replacement_text.value
    if value.source_span is not None:
        payload["source_span"] = _source_value(value.source_span)
    if value.scalar_value is not None:
        payload["value"] = value.scalar_value
    if value.uncertainty_marks:
        payload["uncertainty_marks"] = [
            _uncertainty_value(mark) for mark in value.uncertainty_marks
        ]
    return payload


def _finding_payload(**values: object) -> dict[str, object]:
    edition: EditionRef = values["edition_ref"]  # type: ignore[assignment]
    rubric: RubricRef = values["rubric_ref"]  # type: ignore[assignment]
    revision: SegmentRevisionRef = values["segment_revision_ref"]  # type: ignore[assignment]
    return {
        "client_finding_nonce": values["client_finding_nonce"].value,
        "review_round_id": values["review_round_id"].value,
        "edition_ref": {
            "transcript_edition_id": edition.transcript_edition_id.value,
            "content_digest": _digest_value(edition.content_digest),
        },
        "rubric_ref": {
            "rubric_id": rubric.rubric_id.value,
            "schema_version": rubric.schema_version,
            "content_digest": _digest_value(rubric.content_digest),
        },
        "target_key": values["target_key"].value,
        "segment_revision_ref": {
            "segment_id": revision.segment_id.value,
            "segment_revision_id": revision.segment_revision_id.value,
            "revision_digest": _digest_value(revision.revision_digest),
        },
        "character_span": _character_span_value(values["character_span"]),
        "source_subspan": (
            _source_value(values["source_subspan"])
            if values["source_subspan"] is not None
            else None
        ),
        "category_code": values["category_code"].value,
        "severity_code": values["severity_code"].value,
        "observation": values["observation"],
        "proposed_change": _proposed_change_value(values["proposed_change"]),
        "author_actor_id": values["author_actor_id"].value,
    }


def _disposition_payload(
    review_finding_id: ReviewFindingId,
    finding_payload_digest: ContentDigest,
    decision: FindingDecision,
    rationale: str | None,
    steward_actor_id: ActorId,
    decided_at_us: int,
) -> dict[str, object]:
    return {
        "review_finding_id": review_finding_id.value,
        "finding_payload_digest": _digest_value(finding_payload_digest),
        "decision": decision.value,
        "rationale": rationale,
        "steward_actor_id": steward_actor_id.value,
        "decided_at_us": decided_at_us,
    }


def _revalidate_disposition_digest(
    value: object,
    *,
    field: str,
) -> ContentDigest:
    if type(value) is not ContentDigest:
        raise ValidationError(f"{field} must be an exact ContentDigest")
    try:
        return ContentDigest(value.algorithm, value.hex_digest)
    except AttributeError as error:
        raise ValidationError(f"{field} is incomplete") from error


def _revalidate_disposition_finding_id(value: object) -> ReviewFindingId:
    if type(value) is not ReviewFindingId:
        raise ValidationError("review_finding_id must be an exact ReviewFindingId")
    try:
        return ReviewFindingId(value.value)
    except AttributeError as error:
        raise ValidationError("review_finding_id is incomplete") from error


def _revalidate_disposition_actor_id(value: object) -> ActorId:
    if type(value) is not ActorId:
        raise ValidationError("steward_actor_id must be an exact ActorId")
    try:
        return ActorId(value.value)
    except AttributeError as error:
        raise ValidationError("steward_actor_id is incomplete") from error


@dataclass(frozen=True, slots=True)
class FindingDisposition:
    review_finding_id: ReviewFindingId
    finding_payload_digest: ContentDigest
    decision: FindingDecision
    rationale: str | None
    steward_actor_id: ActorId
    decided_at_us: int
    disposition_digest: ContentDigest

    def __post_init__(self) -> None:
        _revalidate_disposition_finding_id(self.review_finding_id)
        _revalidate_disposition_digest(
            self.finding_payload_digest,
            field="finding_payload_digest",
        )
        _revalidate_disposition_actor_id(self.steward_actor_id)
        _revalidate_disposition_digest(
            self.disposition_digest,
            field="disposition_digest",
        )
        for field_name, value, expected in (
            ("review_finding_id", self.review_finding_id, ReviewFindingId),
            ("finding_payload_digest", self.finding_payload_digest, ContentDigest),
            ("decision", self.decision, FindingDecision),
            ("steward_actor_id", self.steward_actor_id, ActorId),
            ("disposition_digest", self.disposition_digest, ContentDigest),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if type(self.decided_at_us) is not int or self.decided_at_us <= 0:
            raise ValidationError("decided_at_us must be a positive integer")
        if self.rationale is not None:
            require_canonical_text(self.rationale, field="disposition rationale", nonempty=True)
        if self.decision is FindingDecision.REJECTED and self.rationale is None:
            raise ValidationError("a rejected finding requires a nonempty reason")
        expected_digest = semantic_digest(
            "heritage-finding-disposition-v1",
            _disposition_payload(
                self.review_finding_id,
                self.finding_payload_digest,
                self.decision,
                self.rationale,
                self.steward_actor_id,
                self.decided_at_us,
            ),
        )
        if expected_digest != self.disposition_digest:
            raise ValidationError("finding-disposition digest does not match its decision")

    @classmethod
    def reconstitute(
        cls,
        *,
        review_finding_id: ReviewFindingId,
        finding_payload_digest: ContentDigest,
        decision: FindingDecision,
        rationale: str | None,
        steward_actor_id: ActorId,
        decided_at_us: int,
        disposition_digest: ContentDigest,
    ) -> FindingDisposition:
        return cls(
            _revalidate_disposition_finding_id(review_finding_id),
            _revalidate_disposition_digest(
                finding_payload_digest,
                field="finding_payload_digest",
            ),
            decision,
            rationale,
            _revalidate_disposition_actor_id(steward_actor_id),
            decided_at_us,
            _revalidate_disposition_digest(
                disposition_digest,
                field="disposition_digest",
            ),
        )

    def validated(self) -> FindingDisposition:
        return type(self).reconstitute(
            review_finding_id=self.review_finding_id,
            finding_payload_digest=self.finding_payload_digest,
            decision=self.decision,
            rationale=self.rationale,
            steward_actor_id=self.steward_actor_id,
            decided_at_us=self.decided_at_us,
            disposition_digest=self.disposition_digest,
        )


@dataclass(frozen=True, slots=True)
class ReviewFindingEvidence:
    review_finding_id: ReviewFindingId
    review_round_id: ReviewRoundId
    review_submission_id: ReviewSubmissionId
    target_key: ReviewTargetKey
    segment_revision_ref: SegmentRevisionRef
    category_code: FindingCategoryCode
    severity_code: FindingSeverityCode
    finding_payload_digest: ContentDigest
    disposition: FindingDisposition | None

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("review_finding_id", self.review_finding_id, ReviewFindingId),
            ("review_round_id", self.review_round_id, ReviewRoundId),
            ("review_submission_id", self.review_submission_id, ReviewSubmissionId),
            ("target_key", self.target_key, ReviewTargetKey),
            ("segment_revision_ref", self.segment_revision_ref, SegmentRevisionRef),
            ("category_code", self.category_code, FindingCategoryCode),
            ("severity_code", self.severity_code, FindingSeverityCode),
            ("finding_payload_digest", self.finding_payload_digest, ContentDigest),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        if self.disposition is not None:
            if type(self.disposition) is not FindingDisposition:
                raise ValidationError("disposition must be an exact FindingDisposition")
            validated_disposition = self.disposition.validated()
            if (
                validated_disposition.review_finding_id != self.review_finding_id
                or validated_disposition.finding_payload_digest != self.finding_payload_digest
            ):
                raise ValidationError("finding evidence disposition does not bind its body")
            object.__setattr__(self, "disposition", validated_disposition)


class ReviewFinding(AggregateEventRecorder):
    __slots__ = (
        "review_finding_id", "review_round_id", "review_submission_id",
        "client_finding_nonce", "edition_ref", "rubric_ref", "target_key",
        "segment_revision_ref", "character_span", "source_subspan", "category_code",
        "severity_code", "observation", "proposed_change", "author_actor_id",
        "finding_payload_digest", "_disposition", "_sealed",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("ReviewFinding body is immutable")
        object.__setattr__(self, name, value)

    @staticmethod
    def compute_payload_digest(
        *,
        client_finding_nonce: ClientFindingNonce,
        review_round_id: ReviewRoundId,
        edition_ref: EditionRef,
        rubric_ref: RubricRef,
        target_key: ReviewTargetKey,
        segment_revision_ref: SegmentRevisionRef,
        character_span: ReviewCharacterSpan | None,
        source_subspan: SourceSpan | None,
        category_code: FindingCategoryCode,
        severity_code: FindingSeverityCode,
        observation: str,
        proposed_change: ProposedChange | None,
        author_actor_id: ActorId,
    ) -> ContentDigest:
        return semantic_digest(
            "heritage-review-finding-payload-v1",
            _finding_payload(
                client_finding_nonce=client_finding_nonce,
                review_round_id=review_round_id,
                edition_ref=edition_ref,
                rubric_ref=rubric_ref,
                target_key=target_key,
                segment_revision_ref=segment_revision_ref,
                character_span=character_span,
                source_subspan=source_subspan,
                category_code=category_code,
                severity_code=severity_code,
                observation=observation,
                proposed_change=proposed_change,
                author_actor_id=author_actor_id,
            ),
        )

    @classmethod
    def _validated_values(cls, *, target_manifest: ReviewTargetManifest, **values: object) -> dict[str, object]:
        checks = (
            ("review_finding_id", ReviewFindingId),
            ("review_round_id", ReviewRoundId),
            ("review_submission_id", ReviewSubmissionId),
            ("client_finding_nonce", ClientFindingNonce),
            ("edition_ref", EditionRef),
            ("rubric_ref", RubricRef),
            ("target_key", ReviewTargetKey),
            ("segment_revision_ref", SegmentRevisionRef),
            ("category_code", FindingCategoryCode),
            ("severity_code", FindingSeverityCode),
            ("author_actor_id", ActorId),
            ("finding_payload_digest", ContentDigest),
        )
        for field_name, expected in checks:
            if type(values.get(field_name)) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        character_span = values.get("character_span")
        if character_span is not None and type(character_span) is not ReviewCharacterSpan:
            raise ValidationError("character_span must be an exact ReviewCharacterSpan")
        source_subspan = values.get("source_subspan")
        if source_subspan is not None and type(source_subspan) is not SourceSpan:
            raise ValidationError("source_subspan must be an exact SourceSpan")
        proposed_change = values.get("proposed_change")
        if proposed_change is not None and type(proposed_change) is not ProposedChange:
            raise ValidationError("proposed_change must be an exact ProposedChange")
        require_canonical_text(values.get("observation"), field="observation", nonempty=True)
        if type(target_manifest) is not ReviewTargetManifest:
            raise ValidationError("target_manifest must be an exact ReviewTargetManifest")
        if (
            values["review_round_id"] != target_manifest.review_round_id
            or values["edition_ref"] != target_manifest.edition_ref
            or values["rubric_ref"] != target_manifest.rubric_ref
        ):
            raise ValidationError("finding does not match target round, edition, or rubric")
        member = next(
            (item for item in target_manifest.members if item.target_key == values["target_key"]),
            None,
        )
        if member is None or member.segment_revision_ref != values["segment_revision_ref"]:
            raise ValidationError("finding target/revision is not exact manifest membership")
        if values["category_code"] not in member.allowed_category_codes:
            raise ValidationError("finding category is not allowed by the target rubric")
        if values["severity_code"] not in member.allowed_severity_codes:
            raise ValidationError("finding severity is not allowed by the target rubric")
        if character_span is not None and character_span.end > member.transcript_text.length:
            raise ValidationError("finding character span exceeds target transcript text")
        if source_subspan is not None and (
            source_subspan.source_version != member.source_span.source_version
            or source_subspan.start_us < member.source_span.start_us
            or source_subspan.end_us > member.source_span.end_us
        ):
            raise ValidationError("finding source subspan must be contained by the target")
        if proposed_change is not None:
            spans = tuple(
                span for span in (
                    proposed_change.source_span,
                    *(mark.source_span for mark in proposed_change.uncertainty_marks),
                ) if span is not None
            )
            if any(span.source_version != member.source_span.source_version for span in spans):
                raise ValidationError("proposed source values must bind the target source")
            if any(
                mark.character_span is not None
                and mark.character_span.end > member.transcript_text.length
                for mark in proposed_change.uncertainty_marks
            ):
                raise ValidationError("proposed uncertainty character span exceeds target text")
        expected = semantic_digest("heritage-review-finding-payload-v1", _finding_payload(**values))
        if expected != values["finding_payload_digest"]:
            raise ValidationError("finding-payload digest does not match its body")
        return values

    @classmethod
    def _build(cls, *, disposition: FindingDisposition | None, **values: object) -> ReviewFinding:
        finding = cls()
        for name, value in values.items():
            object.__setattr__(finding, name, value)
        object.__setattr__(finding, "_disposition", disposition)
        object.__setattr__(finding, "_sealed", True)
        return finding

    @classmethod
    def submit(cls, *, context: OpenReviewContext, event_id: DomainEventId, event_occurred_at_us: int, **values: object) -> ReviewFinding:
        if type(context) is not OpenReviewContext:
            raise ValidationError("context must be a real OpenReviewContext")
        context._require_open()
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if type(event_occurred_at_us) is not int or event_occurred_at_us <= 0:
            raise ValidationError("event_occurred_at_us must be a positive integer")
        checked = cls._validated_values(target_manifest=context._round.target_manifest, **values)
        finding = cls._build(disposition=None, **checked)
        finding._record_event(DomainEvent(
            event_id,
            event_occurred_at_us,
            "ReviewFindingSubmitted",
            {
                "review_finding_id": finding.review_finding_id.value,
                "review_round_id": finding.review_round_id.value,
                "review_submission_id": finding.review_submission_id.value,
                "target_key": finding.target_key.value,
                "segment_revision_digest": finding.segment_revision_ref.revision_digest.hex_digest,
                "finding_payload_digest": finding.finding_payload_digest.hex_digest,
            },
        ))
        return finding

    @classmethod
    def reconstitute(cls, *, target_manifest: ReviewTargetManifest, disposition: FindingDisposition | None, **values: object) -> ReviewFinding:
        checked = cls._validated_values(target_manifest=target_manifest, **values)
        if disposition is not None:
            if type(disposition) is not FindingDisposition:
                raise ValidationError("disposition must be an exact FindingDisposition")
            disposition = disposition.validated()
            if (
                disposition.review_finding_id != checked["review_finding_id"]
                or disposition.finding_payload_digest != checked["finding_payload_digest"]
            ):
                raise ValidationError("disposition does not bind the finding body")
        return cls._build(disposition=disposition, **checked)

    def record_disposition(
        self,
        *,
        context: OpenReviewContext,
        decision: FindingDecision,
        rationale: str | None,
        steward_actor_id: ActorId,
        decided_at_us: int,
        disposition_digest: ContentDigest,
        event_id: DomainEventId,
        event_occurred_at_us: int,
    ) -> FindingDisposition:
        if self._disposition is not None:
            raise ValidationError("finding already has a disposition")
        if type(context) is not OpenReviewContext:
            raise ValidationError("context must be a real OpenReviewContext")
        context._require_open()
        if context.review_round_id != self.review_round_id:
            raise ValidationError("disposition context belongs to another round")
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if type(event_occurred_at_us) is not int or event_occurred_at_us <= 0:
            raise ValidationError("event_occurred_at_us must be a positive integer")
        disposition = FindingDisposition(
            self.review_finding_id,
            self.finding_payload_digest,
            decision,
            rationale,
            steward_actor_id,
            decided_at_us,
            disposition_digest,
        )
        object.__setattr__(self, "_disposition", disposition)
        self._record_event(
            DomainEvent(
                event_id,
                event_occurred_at_us,
                "ReviewFindingDispositionRecorded",
                {
                    "review_finding_id": self.review_finding_id.value,
                    "finding_payload_digest": self.finding_payload_digest.hex_digest,
                    "decision": decision.value,
                    "disposition_digest": disposition_digest.hex_digest,
                },
            )
        )
        return disposition

    @property
    def disposition(self) -> FindingDisposition | None:
        return self._disposition

    def validated_evidence(
        self, *, target_manifest: ReviewTargetManifest
    ) -> ReviewFindingEvidence:
        validated = type(self).reconstitute(
            target_manifest=target_manifest,
            disposition=self._disposition,
            review_finding_id=self.review_finding_id,
            review_round_id=self.review_round_id,
            review_submission_id=self.review_submission_id,
            client_finding_nonce=self.client_finding_nonce,
            edition_ref=self.edition_ref,
            rubric_ref=self.rubric_ref,
            target_key=self.target_key,
            segment_revision_ref=self.segment_revision_ref,
            character_span=self.character_span,
            source_subspan=self.source_subspan,
            category_code=self.category_code,
            severity_code=self.severity_code,
            observation=self.observation,
            proposed_change=self.proposed_change,
            author_actor_id=self.author_actor_id,
            finding_payload_digest=self.finding_payload_digest,
        )
        return validated.evidence

    @property
    def evidence(self) -> ReviewFindingEvidence:
        return ReviewFindingEvidence(
            self.review_finding_id,
            self.review_round_id,
            self.review_submission_id,
            self.target_key,
            self.segment_revision_ref,
            self.category_code,
            self.severity_code,
            self.finding_payload_digest,
            self._disposition,
        )
