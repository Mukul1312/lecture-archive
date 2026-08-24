"""Immutable transcript snapshots, segment revisions, and change manifests."""

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
    ProductionId,
    ProposalItemId,
    ReviewFindingId,
    SegmentId,
    SegmentRevisionId,
    SegmentRevisionRef,
    SourceSpan,
    SourceVersionRef,
    TranscriptEditionId,
    TranscriptScope,
    TranscriptText,
    ValidationError,
    semantic_digest as calculate_semantic_digest,
)
from heritage_production.domain.shared.text import require_canonical_text

from .proposal import ProposalSetRef, _digest_value, _source_value, _span_value


class UncertaintyKind(str, Enum):
    INAUDIBLE = "inaudible"
    UNCERTAIN_WORDING = "uncertain_wording"
    UNCERTAIN_SPEAKER = "uncertain_speaker"
    UNCERTAIN_LANGUAGE = "uncertain_language"


@dataclass(frozen=True, slots=True)
class CharacterSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int:
            raise ValidationError("character-span boundaries must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValidationError("character span must be a nonempty half-open range")


@dataclass(frozen=True, slots=True)
class UncertaintyMark:
    kind: UncertaintyKind
    source_span: SourceSpan
    character_span: CharacterSpan | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not UncertaintyKind:
            raise ValidationError("uncertainty kind must be an UncertaintyKind")
        if type(self.source_span) is not SourceSpan:
            raise ValidationError("uncertainty source_span must be an exact SourceSpan")
        if self.character_span is not None and type(self.character_span) is not CharacterSpan:
            raise ValidationError("character_span must be an exact CharacterSpan")
        if self.note is not None:
            require_canonical_text(self.note, field="uncertainty note", nonempty=True)


@dataclass(frozen=True, slots=True)
class GapDeclaration:
    source_span: SourceSpan
    reason: str

    def __post_init__(self) -> None:
        if type(self.source_span) is not SourceSpan:
            raise ValidationError("gap source_span must be an exact SourceSpan")
        require_canonical_text(self.reason, field="gap reason", nonempty=True)


@dataclass(frozen=True, slots=True)
class ProposalItemRef:
    proposal_set_ref: ProposalSetRef
    proposal_item_id: ProposalItemId

    def __post_init__(self) -> None:
        if type(self.proposal_set_ref) is not ProposalSetRef:
            raise ValidationError("proposal_set_ref must be an exact ProposalSetRef")
        if type(self.proposal_item_id) is not ProposalItemId:
            raise ValidationError("proposal_item_id must be a ProposalItemId")


class RevisionLineageKind(str, Enum):
    PROPOSAL_DERIVED = "proposal_derived"
    MANUAL_INITIAL = "manual_initial"
    CORRECTED_FROM = "corrected_from"
    SPLIT_FROM = "split_from"
    MERGED_FROM = "merged_from"
    MANUAL_NEW = "manual_new"


@dataclass(frozen=True, slots=True)
class RevisionLineage:
    kind: RevisionLineageKind
    parent_edition_ref: EditionRef | None
    parent_revisions: tuple[SegmentRevisionRef, ...]
    proposal_inputs: tuple[ProposalItemRef, ...]

    def __post_init__(self) -> None:
        if type(self.kind) is not RevisionLineageKind:
            raise ValidationError("lineage kind must be a RevisionLineageKind")
        if self.parent_edition_ref is not None and type(self.parent_edition_ref) is not EditionRef:
            raise ValidationError("parent_edition_ref must be an exact EditionRef")
        if type(self.parent_revisions) is not tuple or not all(
            type(value) is SegmentRevisionRef for value in self.parent_revisions
        ):
            raise ValidationError("parent_revisions must be a tuple of SegmentRevisionRef")
        if type(self.proposal_inputs) is not tuple or not all(
            type(value) is ProposalItemRef for value in self.proposal_inputs
        ):
            raise ValidationError("proposal_inputs must be a tuple of ProposalItemRef")
        if len(set(self.parent_revisions)) != len(self.parent_revisions):
            raise ValidationError("lineage parent revisions must be unique")
        if len(set(self.proposal_inputs)) != len(self.proposal_inputs):
            raise ValidationError("lineage proposal inputs must be unique")
        if self.kind is RevisionLineageKind.PROPOSAL_DERIVED:
            if self.parent_edition_ref is not None or self.parent_revisions or not self.proposal_inputs:
                raise ValidationError("proposal-derived lineage requires proposal inputs only")
        elif self.kind in (RevisionLineageKind.MANUAL_INITIAL, RevisionLineageKind.MANUAL_NEW):
            if self.parent_edition_ref is not None or self.parent_revisions or self.proposal_inputs:
                raise ValidationError("manual lineage must not claim parent or proposal inputs")
        elif self.kind in (
            RevisionLineageKind.CORRECTED_FROM,
            RevisionLineageKind.SPLIT_FROM,
        ):
            if self.parent_edition_ref is None or len(self.parent_revisions) != 1 or self.proposal_inputs:
                raise ValidationError("single-parent lineage requires one exact parent revision")
        elif self.kind is RevisionLineageKind.MERGED_FROM:
            if self.parent_edition_ref is None or len(self.parent_revisions) < 2 or self.proposal_inputs:
                raise ValidationError("merged lineage requires at least two exact parent revisions")

    @classmethod
    def proposal_derived(cls, inputs: tuple[ProposalItemRef, ...]) -> RevisionLineage:
        if not inputs:
            raise ValidationError("proposal-derived lineage requires proposal inputs")
        return cls(RevisionLineageKind.PROPOSAL_DERIVED, None, (), inputs)

    @classmethod
    def manual_initial(cls) -> RevisionLineage:
        return cls(RevisionLineageKind.MANUAL_INITIAL, None, (), ())

    @classmethod
    def corrected_from(
        cls, parent: EditionRef, revision: SegmentRevisionRef
    ) -> RevisionLineage:
        return cls(RevisionLineageKind.CORRECTED_FROM, parent, (revision,), ())

    @classmethod
    def split_from(
        cls, parent: EditionRef, revision: SegmentRevisionRef
    ) -> RevisionLineage:
        return cls(RevisionLineageKind.SPLIT_FROM, parent, (revision,), ())

    @classmethod
    def merged_from(
        cls, parent: EditionRef, revisions: tuple[SegmentRevisionRef, ...]
    ) -> RevisionLineage:
        if len(revisions) < 2:
            raise ValidationError("merged lineage requires at least two parent revisions")
        return cls(RevisionLineageKind.MERGED_FROM, parent, revisions, ())

    @classmethod
    def manual_new(cls) -> RevisionLineage:
        return cls(RevisionLineageKind.MANUAL_NEW, None, (), ())


def _proposal_ref_value(value: ProposalItemRef) -> dict[str, object]:
    return {
        "proposal_set_id": value.proposal_set_ref.proposal_set_id.value,
        "proposal_set_digest": _digest_value(value.proposal_set_ref.content_digest),
        "proposal_item_id": value.proposal_item_id.value,
    }


def _revision_ref_value(value: SegmentRevisionRef) -> dict[str, object]:
    return {
        "segment_id": value.segment_id.value,
        "segment_revision_id": value.segment_revision_id.value,
        "revision_digest": _digest_value(value.revision_digest),
    }


def _lineage_value(value: RevisionLineage) -> dict[str, object]:
    return {
        "kind": value.kind.value,
        "parent_edition_ref": (
            {
                "transcript_edition_id": value.parent_edition_ref.transcript_edition_id.value,
                "content_digest": _digest_value(value.parent_edition_ref.content_digest),
            }
            if value.parent_edition_ref is not None
            else None
        ),
        "parent_revisions": [_revision_ref_value(ref) for ref in value.parent_revisions],
        "proposal_inputs": [_proposal_ref_value(ref) for ref in value.proposal_inputs],
    }


def _uncertainty_value(value: UncertaintyMark) -> dict[str, object]:
    return {
        "kind": value.kind.value,
        "source_span": _span_value(value.source_span),
        "character_span": (
            {"start": value.character_span.start, "end": value.character_span.end}
            if value.character_span is not None
            else None
        ),
        "note": value.note,
    }


@dataclass(frozen=True, slots=True, init=False)
class SegmentRevision:
    ordinal: int
    segment_id: SegmentId
    segment_revision_id: SegmentRevisionId
    source_span: SourceSpan
    text: TranscriptText
    language: str
    speaker: str | None
    uncertainty_marks: tuple[UncertaintyMark, ...]
    lineage: RevisionLineage
    semantic_digest: ContentDigest

    @classmethod
    def create(cls, **values: object) -> SegmentRevision:
        checked = cls._validated_values(**values)
        cls._validate_content_values(checked)
        digest = calculate_semantic_digest(
            "heritage-segment-revision-v1", cls._semantic_payload(**checked)
        )
        return cls._build(**checked, semantic_digest=digest)

    @classmethod
    def reconstitute(
        cls,
        *,
        semantic_digest: ContentDigest,
        **values: object,
    ) -> SegmentRevision:
        if type(semantic_digest) is not ContentDigest:
            raise ValidationError("semantic_digest must be a ContentDigest")
        checked = cls._validated_values(**values)
        cls._validate_content_values(checked)
        expected = calculate_semantic_digest(
            "heritage-segment-revision-v1", cls._semantic_payload(**checked)
        )
        if expected != semantic_digest:
            raise ValidationError("segment-revision digest does not match its content")
        return cls._build(**checked, semantic_digest=semantic_digest)

    @classmethod
    def _validated_values(cls, **values: object) -> dict[str, object]:
        if type(values.get("ordinal")) is not int or values["ordinal"] < 0:
            raise ValidationError("revision ordinal must be a nonnegative integer")
        for field_name, expected in (
            ("segment_id", SegmentId),
            ("segment_revision_id", SegmentRevisionId),
            ("source_span", SourceSpan),
            ("text", TranscriptText),
            ("lineage", RevisionLineage),
        ):
            if type(values.get(field_name)) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        require_canonical_text(values.get("language"), field="revision language", nonempty=True)
        if values.get("speaker") is not None:
            require_canonical_text(values["speaker"], field="revision speaker", nonempty=True)
        marks = values.get("uncertainty_marks")
        if type(marks) is not tuple or not all(type(mark) is UncertaintyMark for mark in marks):
            raise ValidationError("uncertainty_marks must be a tuple of UncertaintyMark")
        return values

    @staticmethod
    def _validate_content_values(values: dict[str, object]) -> None:
        segment_span = values["source_span"]
        text = values["text"]
        marks = values["uncertainty_marks"]
        for mark in marks:
            mark_span = mark.source_span
            if (
                mark_span.source_version != segment_span.source_version
                or mark_span.start_us < segment_span.start_us
                or mark_span.end_us > segment_span.end_us
            ):
                raise ValidationError("uncertainty source span must lie within its segment")
            if mark.character_span is not None and mark.character_span.end > len(text):
                raise ValidationError("uncertainty character span exceeds transcript text bounds")
        if not text.value and not any(
            mark.kind is UncertaintyKind.INAUDIBLE
            and mark.source_span == segment_span
            and mark.character_span is None
            for mark in marks
        ):
            raise ValidationError(
                "empty transcript text requires a full-segment inaudible uncertainty"
            )

    @classmethod
    def verify_digest(cls, revision: SegmentRevision) -> None:
        checked = cls._validated_values(
            ordinal=revision.ordinal,
            segment_id=revision.segment_id,
            segment_revision_id=revision.segment_revision_id,
            source_span=revision.source_span,
            text=revision.text,
            language=revision.language,
            speaker=revision.speaker,
            uncertainty_marks=revision.uncertainty_marks,
            lineage=revision.lineage,
        )
        cls._validate_content_values(checked)
        expected = calculate_semantic_digest(
            "heritage-segment-revision-v1", cls._semantic_payload(**checked)
        )
        if expected != revision.semantic_digest:
            raise ValidationError("segment-revision digest does not match its content")

    @staticmethod
    def _semantic_payload(**values: object) -> dict[str, object]:
        return {
            "ordinal": values["ordinal"],
            "segment_id": values["segment_id"].value,
            "segment_revision_id": values["segment_revision_id"].value,
            "source_span": _span_value(values["source_span"]),
            "text": values["text"].value,
            "language": values["language"],
            "speaker": values["speaker"],
            "uncertainty_marks": [
                _uncertainty_value(mark) for mark in values["uncertainty_marks"]
            ],
            "lineage": _lineage_value(values["lineage"]),
        }

    @classmethod
    def _build(cls, **values: object) -> SegmentRevision:
        instance = object.__new__(cls)
        for field_name, value in values.items():
            object.__setattr__(instance, field_name, value)
        return instance

    @property
    def ref(self) -> SegmentRevisionRef:
        return SegmentRevisionRef(
            self.segment_id, self.segment_revision_id, self.semantic_digest
        )


class EditionChangeKind(str, Enum):
    INITIAL_PROPOSAL = "initial_proposal"
    INITIAL_MANUAL = "initial_manual"
    UNCHANGED = "unchanged"
    CORRECTION = "correction"
    SPLIT = "split"
    MERGE = "merge"
    MANUAL_NEW = "manual_new"


@dataclass(frozen=True, slots=True)
class EditionChange:
    kind: EditionChangeKind
    input_revisions: tuple[SegmentRevisionRef, ...]
    output_revisions: tuple[SegmentRevisionRef, ...]
    proposal_inputs: tuple[ProposalItemRef, ...] = ()
    manual_actor_id: ActorId | None = None
    manual_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not EditionChangeKind:
            raise ValidationError("change kind must be an EditionChangeKind")
        for field_name, values, expected in (
            ("input_revisions", self.input_revisions, SegmentRevisionRef),
            ("output_revisions", self.output_revisions, SegmentRevisionRef),
            ("proposal_inputs", self.proposal_inputs, ProposalItemRef),
        ):
            if type(values) is not tuple or not all(type(value) is expected for value in values):
                raise ValidationError(f"{field_name} must be a tuple of {expected.__name__}")
        if self.manual_actor_id is not None and type(self.manual_actor_id) is not ActorId:
            raise ValidationError("manual_actor_id must be an ActorId")
        if self.manual_reason is not None:
            require_canonical_text(self.manual_reason, field="manual change reason", nonempty=True)

    @classmethod
    def initial_proposal(
        cls,
        *,
        proposal_inputs: tuple[ProposalItemRef, ...],
        output_revisions: tuple[SegmentRevisionRef, ...],
    ) -> EditionChange:
        return cls(
            EditionChangeKind.INITIAL_PROPOSAL,
            (),
            output_revisions,
            proposal_inputs,
        )

    @classmethod
    def initial_manual(
        cls,
        *,
        output_revisions: tuple[SegmentRevisionRef, ...],
        actor_id: ActorId | None,
        reason: str,
    ) -> EditionChange:
        if type(actor_id) is not ActorId:
            raise ValidationError("manual initial change requires an exact ActorId")
        require_canonical_text(reason, field="manual change reason", nonempty=True)
        return cls(
            EditionChangeKind.INITIAL_MANUAL,
            (),
            output_revisions,
            (),
            actor_id,
            reason,
        )

    @classmethod
    def unchanged(
        cls, input_revision: SegmentRevisionRef, output_revision: SegmentRevisionRef
    ) -> EditionChange:
        return cls(
            EditionChangeKind.UNCHANGED,
            (input_revision,),
            (output_revision,),
        )

    @classmethod
    def correction(
        cls,
        input_revision: SegmentRevisionRef,
        output_revision: SegmentRevisionRef,
        *,
        actor_id: ActorId | None = None,
        reason: str | None = None,
    ) -> EditionChange:
        return cls._successor_change(
            EditionChangeKind.CORRECTION,
            (input_revision,),
            (output_revision,),
            actor_id,
            reason,
        )

    @classmethod
    def split(
        cls,
        input_revision: SegmentRevisionRef,
        output_revisions: tuple[SegmentRevisionRef, ...],
        *,
        actor_id: ActorId | None = None,
        reason: str | None = None,
    ) -> EditionChange:
        return cls._successor_change(
            EditionChangeKind.SPLIT,
            (input_revision,),
            output_revisions,
            actor_id,
            reason,
        )

    @classmethod
    def merge(
        cls,
        input_revisions: tuple[SegmentRevisionRef, ...],
        output_revision: SegmentRevisionRef,
        *,
        actor_id: ActorId | None = None,
        reason: str | None = None,
    ) -> EditionChange:
        return cls._successor_change(
            EditionChangeKind.MERGE,
            input_revisions,
            (output_revision,),
            actor_id,
            reason,
        )

    @classmethod
    def manual_new(
        cls,
        output_revision: SegmentRevisionRef,
        *,
        actor_id: ActorId,
        reason: str,
    ) -> EditionChange:
        return cls._successor_change(
            EditionChangeKind.MANUAL_NEW,
            (),
            (output_revision,),
            actor_id,
            reason,
        )

    @classmethod
    def _successor_change(
        cls,
        kind: EditionChangeKind,
        inputs: tuple[SegmentRevisionRef, ...],
        outputs: tuple[SegmentRevisionRef, ...],
        actor_id: ActorId | None,
        reason: str | None,
    ) -> EditionChange:
        if (actor_id is None) != (reason is None):
            raise ValidationError("manual change attribution requires both actor and reason")
        return cls(kind, inputs, outputs, (), actor_id, reason)


@dataclass(frozen=True, slots=True)
class FindingChangeRef:
    review_finding_id: ReviewFindingId
    finding_payload_digest: ContentDigest
    disposition_digest: ContentDigest

    def __post_init__(self) -> None:
        if type(self.review_finding_id) is not ReviewFindingId:
            raise ValidationError("review_finding_id must be a ReviewFindingId")
        if type(self.finding_payload_digest) is not ContentDigest:
            raise ValidationError("finding_payload_digest must be a ContentDigest")
        if type(self.disposition_digest) is not ContentDigest:
            raise ValidationError("disposition_digest must be a ContentDigest")


class FindingOutcome(str, Enum):
    APPLIED = "applied"
    NO_EDITION_CHANGE = "no_edition_change"


@dataclass(frozen=True, slots=True)
class FindingMapping:
    finding: FindingChangeRef
    outcome: FindingOutcome
    applied_revisions: tuple[SegmentRevisionRef, ...]
    no_change_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.finding) is not FindingChangeRef:
            raise ValidationError("finding must be an exact FindingChangeRef")
        if type(self.outcome) is not FindingOutcome:
            raise ValidationError("finding outcome must be a FindingOutcome")
        if type(self.applied_revisions) is not tuple or not all(
            type(ref) is SegmentRevisionRef for ref in self.applied_revisions
        ):
            raise ValidationError("applied_revisions must be a tuple of SegmentRevisionRef")
        if len(set(self.applied_revisions)) != len(self.applied_revisions):
            raise ValidationError("applied revision references must be unique")
        if self.outcome is FindingOutcome.APPLIED:
            if not self.applied_revisions or self.no_change_reason is not None:
                raise ValidationError("applied finding requires revisions and no no-change reason")
        else:
            if self.applied_revisions:
                raise ValidationError("no-edition-change finding must not claim revisions")
            require_canonical_text(
                self.no_change_reason,
                field="no-edition-change reason",
                nonempty=True,
            )

    @classmethod
    def applied(
        cls,
        finding: FindingChangeRef,
        revisions: tuple[SegmentRevisionRef, ...],
    ) -> FindingMapping:
        return cls(finding, FindingOutcome.APPLIED, revisions, None)

    @classmethod
    def no_edition_change(
        cls, finding: FindingChangeRef, reason: str
    ) -> FindingMapping:
        return cls(finding, FindingOutcome.NO_EDITION_CHANGE, (), reason)


@dataclass(frozen=True, slots=True)
class EditionChangeManifest:
    changes: tuple[EditionChange, ...]
    finding_mappings: tuple[FindingMapping, ...]

    def __post_init__(self) -> None:
        if type(self.changes) is not tuple or not all(
            type(value) is EditionChange for value in self.changes
        ):
            raise ValidationError("changes must be a tuple of EditionChange")
        if type(self.finding_mappings) is not tuple or not all(
            type(value) is FindingMapping for value in self.finding_mappings
        ):
            raise ValidationError("finding_mappings must be a tuple of FindingMapping")


@dataclass(frozen=True, slots=True)
class ParentEditionManifest:
    edition_ref: EditionRef
    production_id: ProductionId
    source_versions: tuple[SourceVersionRef, ...]
    transcript_scope: TranscriptScope
    proposal_set_refs: tuple[ProposalSetRef, ...]
    parent_edition_ref: EditionRef | None
    revisions: tuple[SegmentRevision, ...]
    gaps: tuple[GapDeclaration, ...]
    change_manifest: EditionChangeManifest

    def __post_init__(self) -> None:
        if type(self.edition_ref) is not EditionRef:
            raise ValidationError("parent edition_ref must be an exact EditionRef")
        if type(self.production_id) is not ProductionId:
            raise ValidationError("parent production_id must be a ProductionId")
        if type(self.source_versions) is not tuple or not self.source_versions or not all(
            type(source) is SourceVersionRef for source in self.source_versions
        ):
            raise ValidationError("parent source_versions must be a nonempty tuple")
        if type(self.transcript_scope) is not TranscriptScope:
            raise ValidationError("parent transcript_scope must be a TranscriptScope")
        if type(self.proposal_set_refs) is not tuple or not all(
            type(ref) is ProposalSetRef for ref in self.proposal_set_refs
        ):
            raise ValidationError("parent proposal_set_refs must be a tuple")
        if self.parent_edition_ref is not None and type(self.parent_edition_ref) is not EditionRef:
            raise ValidationError("parent's parent_edition_ref must be an EditionRef")
        if type(self.revisions) is not tuple or not self.revisions or not all(
            type(revision) is SegmentRevision for revision in self.revisions
        ):
            raise ValidationError("parent revisions must be a nonempty tuple")
        if type(self.gaps) is not tuple or not all(
            type(gap) is GapDeclaration for gap in self.gaps
        ):
            raise ValidationError("parent gaps must be a tuple of GapDeclaration")
        if type(self.change_manifest) is not EditionChangeManifest:
            raise ValidationError("parent change_manifest must be an EditionChangeManifest")
        if len({revision.ref for revision in self.revisions}) != len(self.revisions):
            raise ValidationError("parent revision references must be unique")
        for revision in self.revisions:
            SegmentRevision.verify_digest(revision)
        expected = calculate_semantic_digest(
            "heritage-transcript-edition-v1",
            TranscriptEdition._semantic_payload(
                production_id=self.production_id,
                source_versions=self.source_versions,
                transcript_scope=self.transcript_scope,
                proposal_set_refs=self.proposal_set_refs,
                parent_edition_ref=self.parent_edition_ref,
                revisions=self.revisions,
                gaps=self.gaps,
                change_manifest=self.change_manifest,
            ),
        )
        if expected != self.edition_ref.content_digest:
            raise ValidationError("parent manifest content does not match its EditionRef digest")

    @classmethod
    def from_edition(cls, edition: TranscriptEdition) -> ParentEditionManifest:
        if type(edition) is not TranscriptEdition:
            raise ValidationError("parent must be an exact TranscriptEdition")
        return cls(
            edition.ref,
            edition.production_id,
            edition.source_versions,
            edition.transcript_scope,
            edition.proposal_set_refs,
            edition.parent_edition_ref,
            edition.revisions,
            edition.gaps,
            edition.change_manifest,
        )


def _change_value(value: EditionChange) -> dict[str, object]:
    return {
        "kind": value.kind.value,
        "input_revisions": [_revision_ref_value(ref) for ref in value.input_revisions],
        "output_revisions": [_revision_ref_value(ref) for ref in value.output_revisions],
        "proposal_inputs": [_proposal_ref_value(ref) for ref in value.proposal_inputs],
        "manual_actor_id": (
            value.manual_actor_id.value if value.manual_actor_id is not None else None
        ),
        "manual_reason": value.manual_reason,
    }


def _manifest_value(value: EditionChangeManifest) -> dict[str, object]:
    return {
        "changes": [_change_value(change) for change in value.changes],
        "finding_mappings": [
            {
                "finding": {
                    "review_finding_id": mapping.finding.review_finding_id.value,
                    "finding_payload_digest": _digest_value(
                        mapping.finding.finding_payload_digest
                    ),
                    "disposition_digest": _digest_value(
                        mapping.finding.disposition_digest
                    ),
                },
                "outcome": mapping.outcome.value,
                "applied_revisions": [
                    _revision_ref_value(ref) for ref in mapping.applied_revisions
                ],
                "no_change_reason": mapping.no_change_reason,
            }
            for mapping in value.finding_mappings
        ],
    }


def _scope_value(value: TranscriptScope) -> dict[str, object]:
    return {
        "source_versions": [_source_value(source) for source in value.source_versions],
        "required_spans": [_span_value(span) for span in value.required_spans],
        "excluded_gap_spans": [
            _span_value(span) for span in value.excluded_gap_spans
        ],
    }


def _revision_value(value: SegmentRevision) -> dict[str, object]:
    payload = SegmentRevision._semantic_payload(
        ordinal=value.ordinal,
        segment_id=value.segment_id,
        segment_revision_id=value.segment_revision_id,
        source_span=value.source_span,
        text=value.text,
        language=value.language,
        speaker=value.speaker,
        uncertainty_marks=value.uncertainty_marks,
        lineage=value.lineage,
    )
    return {**payload, "revision_digest": _digest_value(value.semantic_digest)}


class TranscriptEdition(AggregateEventRecorder):
    """A sealed full transcript snapshot with drainable creation facts."""

    __slots__ = (
        "transcript_edition_id",
        "production_id",
        "source_versions",
        "transcript_scope",
        "proposal_set_refs",
        "parent_edition_ref",
        "revisions",
        "gaps",
        "change_manifest",
        "creation_actor_id",
        "created_at_us",
        "semantic_digest",
        "_sealed",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("TranscriptEdition is sealed")
        object.__setattr__(self, name, value)

    @classmethod
    def seal_initial(cls, **values: object) -> TranscriptEdition:
        event_id = values.pop("event_id", None)
        event_time = values.pop("event_occurred_at_us", None)
        checked = cls._validate_common(parent_edition_ref=None, **values)
        cls._validate_initial_manifest(checked)
        digest = calculate_semantic_digest(
            "heritage-transcript-edition-v1", cls._semantic_payload(**checked)
        )
        edition = cls._build(**checked, semantic_digest=digest)
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if type(event_time) is not int or event_time <= 0:
            raise ValidationError("event_occurred_at_us must be a positive integer")
        edition._record_event(
            DomainEvent(
                event_id,
                event_time,
                "TranscriptEditionCreated",
                {
                    "transcript_edition_id": edition.transcript_edition_id.value,
                    "production_id": edition.production_id.value,
                    "edition_digest": edition.semantic_digest.hex_digest,
                    "parent_edition_digest": None,
                },
            )
        )
        return edition

    @classmethod
    def seal_successor(cls, **values: object) -> TranscriptEdition:
        event_id = values.pop("event_id", None)
        event_time = values.pop("event_occurred_at_us", None)
        parent_manifest = values.pop("parent_manifest", None)
        if type(parent_manifest) is not ParentEditionManifest:
            raise ValidationError("parent_manifest must be an exact ParentEditionManifest")
        checked = cls._validate_common(**values)
        cls._validate_successor_manifest(checked, parent_manifest)
        digest = calculate_semantic_digest(
            "heritage-transcript-edition-v1", cls._semantic_payload(**checked)
        )
        edition = cls._build(**checked, semantic_digest=digest)
        if type(event_id) is not DomainEventId:
            raise ValidationError("event_id must be a DomainEventId")
        if type(event_time) is not int or event_time <= 0:
            raise ValidationError("event_occurred_at_us must be a positive integer")
        edition._record_event(
            DomainEvent(
                event_id,
                event_time,
                "TranscriptEditionCreated",
                {
                    "transcript_edition_id": edition.transcript_edition_id.value,
                    "production_id": edition.production_id.value,
                    "edition_digest": edition.semantic_digest.hex_digest,
                    "parent_edition_digest": edition.parent_edition_ref.content_digest.hex_digest,
                },
            )
        )
        return edition

    @classmethod
    def reconstitute(
        cls,
        *,
        semantic_digest: ContentDigest,
        **values: object,
    ) -> TranscriptEdition:
        if type(semantic_digest) is not ContentDigest:
            raise ValidationError("semantic_digest must be a ContentDigest")
        parent_manifest = values.pop("parent_manifest", None)
        checked = cls._validate_common(**values)
        if checked["parent_edition_ref"] is None:
            cls._validate_initial_manifest(checked)
        else:
            if type(parent_manifest) is not ParentEditionManifest:
                raise ValidationError(
                    "successor reconstitution requires an exact ParentEditionManifest"
                )
            cls._validate_successor_manifest(checked, parent_manifest)
        expected = calculate_semantic_digest(
            "heritage-transcript-edition-v1", cls._semantic_payload(**checked)
        )
        if expected != semantic_digest:
            raise ValidationError("transcript-edition digest does not match its content")
        return cls._build(**checked, semantic_digest=semantic_digest)

    @classmethod
    def _validate_common(cls, **values: object) -> dict[str, object]:
        values.setdefault("parent_edition_ref", None)
        for field_name, expected in (
            ("transcript_edition_id", TranscriptEditionId),
            ("production_id", ProductionId),
            ("transcript_scope", TranscriptScope),
            ("change_manifest", EditionChangeManifest),
            ("creation_actor_id", ActorId),
        ):
            if type(values.get(field_name)) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        sources = values.get("source_versions")
        if type(sources) is not tuple or not sources or not all(
            type(source) is SourceVersionRef for source in sources
        ):
            raise ValidationError("source_versions must be a nonempty tuple of SourceVersionRef")
        if values["transcript_scope"].source_versions != sources:
            raise ValidationError("transcript scope must bind the edition's exact source versions")
        proposals = values.get("proposal_set_refs")
        if type(proposals) is not tuple or not all(
            type(ref) is ProposalSetRef for ref in proposals
        ):
            raise ValidationError("proposal_set_refs must be a tuple of ProposalSetRef")
        if len(set(proposals)) != len(proposals):
            raise ValidationError("proposal_set_refs must be unique exact references")
        if proposals != tuple(
            sorted(
                proposals,
                key=lambda ref: (
                    ref.proposal_set_id.value,
                    ref.content_digest.hex_digest,
                ),
            )
        ):
            raise ValidationError("proposal_set_refs must be in canonical identity order")
        revisions = values.get("revisions")
        if type(revisions) is not tuple or not revisions or not all(
            type(revision) is SegmentRevision for revision in revisions
        ):
            raise ValidationError("revisions must be a nonempty tuple of SegmentRevision")
        gaps = values.get("gaps")
        if type(gaps) is not tuple or not all(type(gap) is GapDeclaration for gap in gaps):
            raise ValidationError("gaps must be a tuple of GapDeclaration")
        if type(values.get("created_at_us")) is not int or values["created_at_us"] <= 0:
            raise ValidationError("created_at_us must be a positive integer")
        if values.get("parent_edition_ref") is not None and type(values["parent_edition_ref"]) is not EditionRef:
            raise ValidationError("parent_edition_ref must be an exact EditionRef")

        if tuple(revision.ordinal for revision in revisions) != tuple(range(len(revisions))):
            raise ValidationError("revision ordinals must be contiguous and zero based")
        if len({revision.segment_id for revision in revisions}) != len(revisions):
            raise ValidationError("segment identities must be unique within the edition")
        if len({revision.segment_revision_id for revision in revisions}) != len(revisions):
            raise ValidationError("segment revision identities must be unique within the edition")
        for revision in revisions:
            SegmentRevision.verify_digest(revision)
            if revision.source_span.source_version not in sources:
                raise ValidationError("revision source must be an exact declared source version")
        used_proposal_sets = {
            proposal.proposal_set_ref
            for revision in revisions
            for proposal in revision.lineage.proposal_inputs
        }
        used_proposal_sets.update(
            proposal.proposal_set_ref
            for change in values["change_manifest"].changes
            for proposal in change.proposal_inputs
        )
        if set(proposals) != used_proposal_sets:
            raise ValidationError(
                "proposal_set_refs must exactly match revision and manifest proposal bindings"
            )
        cls._validate_coverage(values["transcript_scope"], revisions, gaps)
        return values

    @staticmethod
    def _validate_coverage(
        scope: TranscriptScope,
        revisions: tuple[SegmentRevision, ...],
        gaps: tuple[GapDeclaration, ...],
    ) -> None:
        if tuple(gap.source_span for gap in gaps) != scope.excluded_gap_spans:
            raise ValidationError("every excluded gap span requires exactly one ordered reason")
        actual = [revision.source_span for revision in revisions] + [gap.source_span for gap in gaps]
        source_order = {source.source_version_id: index for index, source in enumerate(scope.source_versions)}
        actual.sort(key=lambda span: (source_order[span.source_version.source_version_id], span.start_us, span.end_us))
        required = list(scope.required_spans)
        for source in scope.source_versions:
            target = [span for span in required if span.source_version == source]
            coverage = [span for span in actual if span.source_version == source]
            target_index = 0
            cursor = target[0].start_us if target else None
            for span in coverage:
                while target_index < len(target) and cursor == target[target_index].end_us:
                    target_index += 1
                    cursor = target[target_index].start_us if target_index < len(target) else None
                if target_index >= len(target) or span.start_us != cursor or span.end_us > target[target_index].end_us:
                    raise ValidationError("segments and gaps must cover required scope exactly without overlap")
                cursor = span.end_us
            if target:
                while target_index < len(target) and cursor == target[target_index].end_us:
                    target_index += 1
                    cursor = target[target_index].start_us if target_index < len(target) else None
                if target_index != len(target):
                    raise ValidationError("segments and gaps must cover required scope exactly without omission")
            elif coverage:
                raise ValidationError("edition contains out-of-scope content")

    @staticmethod
    def _validate_initial_manifest(values: dict[str, object]) -> None:
        manifest = values["change_manifest"]
        revisions = values["revisions"]
        proposal_sets = set(values["proposal_set_refs"])
        used_proposal_sets: set[ProposalSetRef] = set()
        output_refs: list[SegmentRevisionRef] = []
        for change in manifest.changes:
            if change.kind not in (
                EditionChangeKind.INITIAL_PROPOSAL,
                EditionChangeKind.INITIAL_MANUAL,
            ):
                raise ValidationError("initial manifest contains a successor-only change")
            if change.input_revisions:
                raise ValidationError("initial changes must not reference parent revisions")
            for proposal in change.proposal_inputs:
                if proposal.proposal_set_ref not in proposal_sets:
                    raise ValidationError("manifest proposal input is not an exact declared proposal set")
                used_proposal_sets.add(proposal.proposal_set_ref)
            if change.kind is EditionChangeKind.INITIAL_PROPOSAL:
                if not change.proposal_inputs or change.manual_actor_id is not None or change.manual_reason is not None:
                    raise ValidationError("proposal initial changes require proposal inputs only")
            else:
                if change.proposal_inputs or change.manual_actor_id is None or not change.manual_reason:
                    raise ValidationError("manual initial changes require actor and reason only")
            output_refs.extend(change.output_revisions)
        if tuple(output_refs) != tuple(revision.ref for revision in revisions):
            raise ValidationError("initial manifest must account for every revision exactly once")
        if manifest.finding_mappings:
            raise ValidationError("an initial edition cannot apply review findings")
        if used_proposal_sets != proposal_sets:
            raise ValidationError("every declared proposal set must be bound by the initial manifest")

        change_for_output = {
            output: change for change in manifest.changes for output in change.output_revisions
        }
        for revision in revisions:
            change = change_for_output[revision.ref]
            if change.kind is EditionChangeKind.INITIAL_PROPOSAL:
                if (
                    revision.lineage.kind is not RevisionLineageKind.PROPOSAL_DERIVED
                    or revision.lineage.proposal_inputs != change.proposal_inputs
                ):
                    raise ValidationError("proposal revision lineage must match its manifest input")
            elif revision.lineage.kind is not RevisionLineageKind.MANUAL_INITIAL:
                raise ValidationError("manual initial revision requires manual-initial lineage")

    @staticmethod
    def _validate_successor_manifest(
        values: dict[str, object], parent: ParentEditionManifest
    ) -> None:
        parent_ref = values["parent_edition_ref"]
        if parent_ref is None or parent_ref != parent.edition_ref:
            raise ValidationError("successor must bind the exact supplied parent edition")
        if values["transcript_edition_id"] == parent_ref.transcript_edition_id:
            raise ValidationError("an edition cannot be its own parent")
        if values["production_id"] != parent.production_id:
            raise ValidationError("successor and parent must belong to the same Production")
        if not all(source in values["source_versions"] for source in parent.source_versions):
            raise ValidationError("successor must retain every exact parent source version")

        manifest = values["change_manifest"]
        current_by_ref = {revision.ref: revision for revision in values["revisions"]}
        parent_by_ref = {revision.ref: revision for revision in parent.revisions}
        parent_segment_ids = {revision.segment_id for revision in parent.revisions}
        seen_inputs: set[SegmentRevisionRef] = set()
        seen_outputs: set[SegmentRevisionRef] = set()
        finding_ids: set[ReviewFindingId] = set()
        applied_refs: set[SegmentRevisionRef] = set()
        for mapping in manifest.finding_mappings:
            finding_id = mapping.finding.review_finding_id
            if finding_id in finding_ids:
                raise ValidationError("accepted finding is mapped more than once")
            finding_ids.add(finding_id)
            if any(ref not in current_by_ref for ref in mapping.applied_revisions):
                raise ValidationError("accepted finding claims a revision absent from the edition")
            applied_refs.update(mapping.applied_revisions)

        for change in manifest.changes:
            if change.kind in (
                EditionChangeKind.INITIAL_PROPOSAL,
                EditionChangeKind.INITIAL_MANUAL,
            ):
                raise ValidationError("successor manifest contains an initial-only change")
            if any(ref not in parent_by_ref for ref in change.input_revisions):
                raise ValidationError("change input is not in the immediate exact parent edition")
            if any(ref not in current_by_ref for ref in change.output_revisions):
                raise ValidationError("change claims an output not present in the successor edition")
            if any(ref in seen_inputs for ref in change.input_revisions):
                raise ValidationError("parent revision has ambiguous successor lineage")
            if any(ref in seen_outputs for ref in change.output_revisions):
                raise ValidationError("successor revision is claimed by multiple changes")
            seen_inputs.update(change.input_revisions)
            seen_outputs.update(change.output_revisions)

            if change.proposal_inputs:
                raise ValidationError("successor structural changes cannot claim proposal inputs")
            manual = change.manual_actor_id is not None and change.manual_reason is not None
            if change.kind is EditionChangeKind.UNCHANGED:
                if (
                    len(change.input_revisions) != 1
                    or len(change.output_revisions) != 1
                    or change.input_revisions[0] != change.output_revisions[0]
                    or manual
                ):
                    raise ValidationError("unchanged change must reuse one exact revision reference")
            elif change.kind is EditionChangeKind.CORRECTION:
                if len(change.input_revisions) != 1 or len(change.output_revisions) != 1:
                    raise ValidationError("correction requires one input and one output")
                before = parent_by_ref[change.input_revisions[0]]
                after = current_by_ref[change.output_revisions[0]]
                if before.segment_id != after.segment_id or before.segment_revision_id == after.segment_revision_id:
                    raise ValidationError("correction must reuse SegmentId and allocate a revision ID")
                TranscriptEdition._require_lineage(
                    after,
                    RevisionLineageKind.CORRECTED_FROM,
                    parent_ref,
                    change.input_revisions,
                )
            elif change.kind is EditionChangeKind.SPLIT:
                if len(change.input_revisions) != 1 or len(change.output_revisions) < 2:
                    raise ValidationError("split requires one input and at least two outputs")
                outputs = [current_by_ref[ref] for ref in change.output_revisions]
                if any(output.segment_id in parent_segment_ids for output in outputs):
                    raise ValidationError("split outputs must allocate new segment identities")
                for output in outputs:
                    TranscriptEdition._require_lineage(
                        output,
                        RevisionLineageKind.SPLIT_FROM,
                        parent_ref,
                        change.input_revisions,
                    )
            elif change.kind is EditionChangeKind.MERGE:
                if len(change.input_revisions) < 2 or len(change.output_revisions) != 1:
                    raise ValidationError("merge requires at least two inputs and one output")
                output = current_by_ref[change.output_revisions[0]]
                if output.segment_id in parent_segment_ids:
                    raise ValidationError("merge output must allocate a new segment identity")
                TranscriptEdition._require_lineage(
                    output,
                    RevisionLineageKind.MERGED_FROM,
                    parent_ref,
                    change.input_revisions,
                )
            elif change.kind is EditionChangeKind.MANUAL_NEW:
                if change.input_revisions or len(change.output_revisions) != 1 or not manual:
                    raise ValidationError("manual-new change requires one attributed new output")
                output = current_by_ref[change.output_revisions[0]]
                if output.segment_id in parent_segment_ids or output.lineage.kind is not RevisionLineageKind.MANUAL_NEW:
                    raise ValidationError("manual-new output requires a new identity and lineage")
            else:
                raise ValidationError("unsupported successor change kind")

            changed_outputs = set(change.output_revisions)
            if change.kind is EditionChangeKind.UNCHANGED:
                if changed_outputs & applied_refs:
                    raise ValidationError("finding application cannot claim an unchanged revision")
            elif manual:
                if changed_outputs & applied_refs:
                    raise ValidationError("change cannot be both manual and finding-applied")
            elif not changed_outputs <= applied_refs:
                raise ValidationError(
                    "every changed revision requires manual or accepted-finding justification"
                )

        if seen_inputs != set(parent_by_ref):
            raise ValidationError("successor manifest must account for every parent revision")
        if seen_outputs != set(current_by_ref):
            raise ValidationError("successor manifest must account for every current revision")

    @staticmethod
    def _require_lineage(
        revision: SegmentRevision,
        kind: RevisionLineageKind,
        parent_ref: EditionRef,
        parent_revisions: tuple[SegmentRevisionRef, ...],
    ) -> None:
        lineage = revision.lineage
        if (
            lineage.kind is not kind
            or lineage.parent_edition_ref != parent_ref
            or lineage.parent_revisions != parent_revisions
            or lineage.proposal_inputs
        ):
            raise ValidationError("revision lineage does not match its immediate-parent change")

    @staticmethod
    def _semantic_payload(**values: object) -> dict[str, object]:
        return {
            "production_id": values["production_id"].value,
            "source_versions": [_source_value(source) for source in values["source_versions"]],
            "transcript_scope": _scope_value(values["transcript_scope"]),
            "parent_edition_digest": (
                _digest_value(values["parent_edition_ref"].content_digest)
                if values["parent_edition_ref"] is not None
                else None
            ),
            "revisions": [_revision_value(revision) for revision in values["revisions"]],
            "gaps": [
                {"source_span": _span_value(gap.source_span), "reason": gap.reason}
                for gap in values["gaps"]
            ],
            "change_manifest": _manifest_value(values["change_manifest"]),
        }

    @classmethod
    def _build(cls, **values: object) -> TranscriptEdition:
        instance = cls.__new__(cls)
        AggregateEventRecorder.__init__(instance)
        for field_name, value in values.items():
            object.__setattr__(instance, field_name, value)
        object.__setattr__(instance, "_sealed", True)
        return instance

    @property
    def ref(self) -> EditionRef:
        return EditionRef(self.transcript_edition_id, self.semantic_digest)
