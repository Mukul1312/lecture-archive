"""NarrationJob aggregate for fixed-contract Lane-B and Lane-C production."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from heritage_archive.kernel import ActorId, ContentDigest, ValidationError

from .errors import AuthorizationDenied, DomainInvariantError, NotFound, RevisionConflict
from .evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    AuthoritySnapshot,
    ListeningOutcome,
    PassageOffset,
    EligibilityFacts,
    GenerationAttempt,
    GenerationPreview,
    NarrationAssemblyAttempt,
    NarrationMaster,
    NarrationMasterListeningDecision,
    NarrationMasterSnapshot,
    NarrationTake,
    ReviewDecision,
    ReviewAuthority,
    ReviewOutcome,
    SelectionDecision,
    narration_assembly_plan_digest,
    SubmissionEvidence,
)
from .ids import (
    BudgetReservationId,
    GenerationAttemptId,
    GenerationPreviewId,
    MasterListeningDecisionId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    NarrationMasterSnapshotId,
    PassageId,
    PassageRenderRecipeId,
    ReviewDecisionId,
    SelectionDecisionId,
    TakeId,
)
from .values import (
    AuthorityOperation,
    ControlProvenance,
    DeliveryControlDefaults,
    ComponentRole,
    Lane,
    PassageRenderRecipe,
    PassageText,
    ReleaseSynthesisContract,
)


def _utc(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f"{field} must be an aware UTC datetime")
    return value


@dataclass(frozen=True, slots=True)
class PassageDraft:
    passage_id: PassageId
    order: int
    text: PassageText

    def __post_init__(self) -> None:
        if type(self.passage_id) is not PassageId or type(self.order) is not int or self.order < 0 or type(self.text) is not PassageText:
            raise ValidationError("passage draft requires an ID, nonnegative order and PassageText")


@dataclass(frozen=True, slots=True)
class PassageTextRevision:
    revision: int
    text: PassageText
    revised_at: datetime

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 1 or type(self.text) is not PassageText:
            raise ValidationError("passage text revision is invalid")
        _utc(self.revised_at, "passage text revision time")


@dataclass(frozen=True, slots=True)
class PassageOrderRevision:
    revision: int
    ordered_passage_ids: tuple[PassageId, ...]


@dataclass(frozen=True, slots=True)
class DeliveryDefaultsRevision:
    revision: int
    defaults: DeliveryControlDefaults
    revised_at: datetime


@dataclass(frozen=True, slots=True)
class PassageState:
    passage_id: PassageId
    order: int
    text_revisions: tuple[PassageTextRevision, ...]
    recipes: tuple[PassageRenderRecipe, ...]
    required_recipe_id: PassageRenderRecipeId | None
    required_dictionary_digest: ContentDigest | None

    @property
    def current_text_revision(self) -> PassageTextRevision:
        return self.text_revisions[-1]

    def recipe(self, recipe_id: PassageRenderRecipeId) -> PassageRenderRecipe:
        for value in self.recipes:
            if value.recipe_id == recipe_id:
                return value
        raise NotFound(f"render recipe {recipe_id} is not part of passage {self.passage_id}")


@dataclass(frozen=True, slots=True)
class NarrationJobSnapshot:
    job_id: NarrationJobId
    revision: int
    lane: Lane
    contract: ReleaseSynthesisContract
    defaults_history: tuple[DeliveryDefaultsRevision, ...]
    passages: tuple[PassageState, ...]
    order_history: tuple[PassageOrderRevision, ...]
    previews: tuple[GenerationPreview, ...]
    generation_attempts: tuple[GenerationAttempt, ...]
    takes: tuple[NarrationTake, ...]
    reviews: tuple[ReviewDecision, ...]
    selections: tuple[SelectionDecision, ...]
    assembly_attempts: tuple[NarrationAssemblyAttempt, ...]
    masters: tuple[NarrationMaster, ...]
    master_listening: tuple[NarrationMasterListeningDecision, ...]
    issued_snapshots: tuple[NarrationMasterSnapshot, ...]
    prepared_at: datetime


class NarrationJob:
    """One fixed lane, speaker, voice, language and release contract."""

    __slots__ = tuple(f"_{field.name}" for field in NarrationJobSnapshot.__dataclass_fields__.values())

    def __init__(self, snapshot: NarrationJobSnapshot) -> None:
        if type(snapshot) is not NarrationJobSnapshot:
            raise ValidationError("narration root requires a NarrationJobSnapshot")
        if type(snapshot.job_id) is not NarrationJobId or type(snapshot.revision) is not int or snapshot.revision < 1:
            raise ValidationError("narration job identity or revision is invalid")
        if type(snapshot.lane) is not Lane or type(snapshot.contract) is not ReleaseSynthesisContract or snapshot.contract.lane is not snapshot.lane:
            raise ValidationError("narration job lane and fixed contract must match")
        if type(snapshot.defaults_history) is not tuple or not snapshot.defaults_history:
            raise ValidationError("narration job requires immutable delivery-default history")
        if type(snapshot.passages) is not tuple or not snapshot.passages:
            raise ValidationError("narration job requires at least one passage")
        self._validate_passages(snapshot.passages)
        if type(snapshot.order_history) is not tuple or not snapshot.order_history:
            raise ValidationError("narration job requires passage-order history")
        self._validate_revision_histories(snapshot)
        self._validate_attempt_take_history(snapshot)
        _utc(snapshot.prepared_at, "narration job preparation time")
        for field in NarrationJobSnapshot.__dataclass_fields__:
            object.__setattr__(self, f"_{field}", getattr(snapshot, field))

    @staticmethod
    def _validate_passages(passages: tuple[PassageState, ...]) -> None:
        # INV-NJ-1: passage identities and explicit order are unique and contiguous.
        if any(type(value) is not PassageState for value in passages):
            raise ValidationError("job passages must be PassageState values")
        ids = tuple(value.passage_id for value in passages)
        orders = tuple(value.order for value in passages)
        if len(set(ids)) != len(ids) or len(set(orders)) != len(orders) or tuple(sorted(orders)) != tuple(range(len(passages))):
            raise ValidationError("passage IDs and explicit contiguous order must be unique")
        for passage in passages:
            if type(passage.passage_id) is not PassageId or type(passage.order) is not int:
                raise ValidationError("passage identity and order must be typed")
            if type(passage.text_revisions) is not tuple or not passage.text_revisions:
                raise ValidationError("each passage requires text revision history")
            if any(type(item) is not PassageTextRevision for item in passage.text_revisions):
                raise ValidationError("passage text history must contain typed revisions")
            if tuple(item.revision for item in passage.text_revisions) != tuple(range(1, len(passage.text_revisions) + 1)):
                raise ValidationError("passage text revisions must be contiguous")
            for item in passage.text_revisions:
                if type(item.text) is not PassageText:
                    raise ValidationError("passage text history requires canonical PassageText")
                _utc(item.revised_at, "passage text revision time")
            if type(passage.recipes) is not tuple:
                raise ValidationError("passage recipe history must be immutable")
            if any(type(item) is not PassageRenderRecipe for item in passage.recipes):
                raise ValidationError("passage recipe history must contain typed recipes")
            if len({item.recipe_id for item in passage.recipes}) != len(passage.recipes):
                raise ValidationError("passage recipe identities must be unique")
            revisions = {item.revision: item for item in passage.text_revisions}
            if any(
                recipe.text_revision not in revisions
                or recipe.text_digest != revisions[recipe.text_revision].text.digest
                for recipe in passage.recipes
            ):
                raise ValidationError("every render recipe must bind one exact passage text revision")
            if passage.required_recipe_id is not None and (
                type(passage.required_recipe_id) is not PassageRenderRecipeId
                or passage.required_recipe_id not in {recipe.recipe_id for recipe in passage.recipes}
            ):
                raise ValidationError("required recipe must belong to its passage history")
            if passage.required_dictionary_digest is not None and type(passage.required_dictionary_digest) is not ContentDigest:
                raise ValidationError("required dictionary digest is invalid")

    @staticmethod
    def _validate_revision_histories(snapshot: NarrationJobSnapshot) -> None:
        defaults = snapshot.defaults_history
        if any(type(value) is not DeliveryDefaultsRevision for value in defaults):
            raise ValidationError("delivery-default history must contain typed revisions")
        default_revisions = tuple(value.revision for value in defaults)
        if default_revisions[0] != 1 or tuple(sorted(set(default_revisions))) != default_revisions or default_revisions[-1] > snapshot.revision:
            raise ValidationError("delivery-default revisions must be strictly increasing within the job revision")
        for index, value in enumerate(defaults):
            if type(value.defaults) is not DeliveryControlDefaults:
                raise ValidationError("delivery-default revision requires complete typed defaults")
            _utc(value.revised_at, "delivery defaults revision time")
            if index and value.defaults == defaults[index - 1].defaults:
                raise ValidationError("delivery-default history cannot append an unchanged value")

        orders = snapshot.order_history
        if any(type(value) is not PassageOrderRevision for value in orders):
            raise ValidationError("passage-order history must contain typed revisions")
        order_revisions = tuple(value.revision for value in orders)
        if order_revisions[0] != 1 or tuple(sorted(set(order_revisions))) != order_revisions or order_revisions[-1] > snapshot.revision:
            raise ValidationError("passage-order revisions must be strictly increasing within the job revision")
        passage_ids = {value.passage_id for value in snapshot.passages}
        for index, value in enumerate(orders):
            if (
                type(value.ordered_passage_ids) is not tuple
                or len(value.ordered_passage_ids) != len(passage_ids)
                or set(value.ordered_passage_ids) != passage_ids
                or any(type(identity) is not PassageId for identity in value.ordered_passage_ids)
                or (index and value.ordered_passage_ids == orders[index - 1].ordered_passage_ids)
            ):
                raise ValidationError("every order revision must be a changed exact permutation of job passages")
        current_order = tuple(value.passage_id for value in sorted(snapshot.passages, key=lambda value: value.order))
        if orders[-1].ordered_passage_ids != current_order:
            raise ValidationError("current passage order must equal the latest order revision")

    @staticmethod
    def _order_at(snapshot: NarrationJobSnapshot, revision: int) -> tuple[PassageId, ...] | None:
        matching = tuple(value for value in snapshot.order_history if value.revision <= revision)
        return None if not matching else matching[-1].ordered_passage_ids

    @staticmethod
    def _input_matches_preview(snapshot: NarrationJobSnapshot, attempt: GenerationAttempt, preview: GenerationPreview) -> bool:
        value = attempt.effective_input
        if value is None:
            return True
        return (
            value.job_id == snapshot.job_id
            and value.lane is snapshot.lane
            and value.passage_id == preview.passage_id
            and value.text_revision == preview.text_revision
            and value.text.digest == preview.text_digest
            and value.recipe_id == preview.recipe_id
            and value.recipe_revision == preview.recipe_revision
            and value.recipe_digest == preview.recipe_digest
            and value.settings == preview.settings
            and value.contract_digest == preview.contract_digest
            and value.authority_scope == preview.authority_snapshot.scope
            and value.authority_revision == preview.authority_snapshot.record_revision
            and value.authority_digest == preview.authority_snapshot.record_digest
            and value.authority_observed_at == preview.authority_snapshot.observed_at
            and value.capability_snapshot == preview.capability_snapshot
            and value.api_schema == snapshot.contract.api_schema
            and value.endpoint == preview.endpoint
            and value.rendered_transcript_bytes == preview.rendered_transcript_bytes
            and value.canonical_projection_digest == preview.canonical_projection_digest
            and value.timestamps_requested == preview.timestamps_requested
            and value.normalization == preview.normalization
            and value.output_audio == preview.output_audio
            and value.billable_rule == preview.billable_rule
            and value.billable_characters == preview.billable_characters
        )

    @staticmethod
    def _validate_attempt_take_history(snapshot: NarrationJobSnapshot) -> None:
        passages = {value.passage_id: value for value in snapshot.passages}
        if type(snapshot.previews) is not tuple or any(type(value) is not GenerationPreview for value in snapshot.previews):
            raise ValidationError("generation preview history must be immutable and typed")
        previews = {value.preview_id: value for value in snapshot.previews}
        if len(previews) != len(snapshot.previews):
            raise ValidationError("generation preview identities must be unique")
        for preview in snapshot.previews:
            passage = passages.get(preview.passage_id)
            recipe = None if passage is None else next((value for value in passage.recipes if value.recipe_id == preview.recipe_id), None)
            text = None if passage is None else next((value for value in passage.text_revisions if value.revision == preview.text_revision), None)
            scope = preview.authority_snapshot.scope
            if (
                passage is None
                or recipe is None
                or text is None
                or preview.base_job_revision >= snapshot.revision
                or preview.recipe_revision != recipe.revision
                or preview.recipe_digest != recipe.digest
                or preview.text_digest != text.text.digest
                or preview.canonical_projection != text.text.value
                or preview.contract_digest != snapshot.contract.digest
                or preview.capability_snapshot != snapshot.contract.capability_snapshot
                or preview.output_audio != snapshot.contract.audio
                or preview.authority_snapshot.record_id != snapshot.contract.authority_record_id
                or scope.speaker_binding != snapshot.contract.speaker_binding
                or scope.voice_binding != snapshot.contract.voice_binding
                or scope.language != snapshot.contract.language
                or scope.purpose != snapshot.contract.purpose
                or scope.intended_episode_id != snapshot.contract.intended_episode_id
                or not scope.covers(AuthorityOperation.GENERATE, preview.authority_snapshot.observed_at)
            ):
                raise ValidationError("generation preview must bind exact historical job, text, recipe, contract and authority facts")
        if type(snapshot.generation_attempts) is not tuple or any(type(value) is not GenerationAttempt for value in snapshot.generation_attempts):
            raise ValidationError("generation attempt history must be immutable and typed")
        if type(snapshot.takes) is not tuple or any(type(value) is not NarrationTake for value in snapshot.takes):
            raise ValidationError("take history must be immutable and typed")
        attempts = {value.attempt_id: value for value in snapshot.generation_attempts}
        takes = {value.take_id: value for value in snapshot.takes}
        if len(attempts) != len(snapshot.generation_attempts) or len(takes) != len(snapshot.takes):
            raise ValidationError("generation attempt and take identities must be unique")
        if len({value.preview_id for value in snapshot.generation_attempts}) != len(snapshot.generation_attempts):
            raise ValidationError("each generation preview may own only one attempt")
        for attempt in snapshot.generation_attempts:
            preview = previews.get(attempt.preview_id)
            if (
                attempt.reservation_revision >= snapshot.revision
                or preview is None
                or attempt.passage_id != preview.passage_id
                or attempt.preview_digest != preview.preview_digest
                or not NarrationJob._input_matches_preview(snapshot, attempt, preview)
            ):
                raise ValidationError("generation attempt must reference its exact owned preview and frozen input")
            matching = None if attempt.take_id is None else takes.get(attempt.take_id)
            if attempt.state is AttemptState.COMPLETED:
                if (
                    matching is None
                    or matching.attempt_id != attempt.attempt_id
                    or matching.job_id != snapshot.job_id
                    or matching.lane is not snapshot.lane
                    or matching.passage_id != attempt.passage_id
                    or matching.effective_input != attempt.effective_input
                    or matching.artifact != attempt.artifact
                    or matching.media != attempt.media
                ):
                    raise ValidationError("completed generation attempt must link its exact immutable take")
            elif matching is not None:
                raise ValidationError("only completed generation attempts may link takes")
        for take in snapshot.takes:
            attempt = attempts.get(take.attempt_id)
            passage = passages.get(take.passage_id)
            recipe = None if passage is None else next((value for value in passage.recipes if value.recipe_id == take.recipe_id), None)
            text = None if passage is None else next((value for value in passage.text_revisions if value.revision == take.text_revision), None)
            if (
                attempt is None
                or attempt.state is not AttemptState.COMPLETED
                or attempt.take_id != take.take_id
                or take.job_id != snapshot.job_id
                or take.lane is not snapshot.lane
                or take.contract_digest != snapshot.contract.digest
                or take.authority_snapshot.record_id != snapshot.contract.authority_record_id
                or recipe is None
                or text is None
                or take.recipe_revision != recipe.revision
                or take.recipe_digest != recipe.digest
                or take.text_digest != text.text.digest
            ):
                raise ValidationError("every take must be owned by one exact completed generation attempt")

        if type(snapshot.reviews) is not tuple or any(type(value) is not ReviewDecision for value in snapshot.reviews):
            raise ValidationError("review history must be immutable and typed")
        if len({value.decision_id for value in snapshot.reviews}) != len(snapshot.reviews) or any(value.take_id not in takes for value in snapshot.reviews):
            raise ValidationError("review identities must be unique and reference owned takes")

        if type(snapshot.selections) is not tuple or any(type(value) is not SelectionDecision for value in snapshot.selections):
            raise ValidationError("selection history must be immutable and typed")
        if len({value.decision_id for value in snapshot.selections}) != len(snapshot.selections):
            raise ValidationError("selection decision identities must be unique")
        for selection in snapshot.selections:
            take = takes.get(selection.take_id)
            latest_operational_review = next(
                (
                    review
                    for review in reversed(snapshot.reviews)
                    if review.take_id == selection.take_id
                    and review.authority is ReviewAuthority.OPERATIONAL
                    and review.decided_at <= selection.decided_at
                ),
                None,
            )
            if (
                take is None
                or selection.passage_id != take.passage_id
                or selection.passage_id not in passages
                or latest_operational_review is None
                or latest_operational_review.outcome is not ReviewOutcome.ACCEPTED
            ):
                raise ValidationError("selection must reference an owned passage take with prior operational acceptance")

        if type(snapshot.assembly_attempts) is not tuple or any(type(value) is not NarrationAssemblyAttempt for value in snapshot.assembly_attempts):
            raise ValidationError("narration assembly history must be immutable and typed")
        if type(snapshot.masters) is not tuple or any(type(value) is not NarrationMaster for value in snapshot.masters):
            raise ValidationError("narration master history must be immutable and typed")
        assembly_attempts = {value.attempt_id: value for value in snapshot.assembly_attempts}
        masters = {value.master_id: value for value in snapshot.masters}
        if len(assembly_attempts) != len(snapshot.assembly_attempts) or len(masters) != len(snapshot.masters):
            raise ValidationError("narration assembly and master identities must be unique")
        for attempt in snapshot.assembly_attempts:
            order = NarrationJob._order_at(snapshot, attempt.reservation_revision)
            selected = tuple(takes.get(identity) for identity in attempt.selected_take_ids)
            selected_before_reservation = all(
                take is not None and any(
                    decision.passage_id == take.passage_id
                    and decision.take_id == take.take_id
                    and decision.decided_at <= attempt.created_at
                    for decision in snapshot.selections
                )
                for take in selected
            )
            if (
                attempt.reservation_revision >= snapshot.revision
                or order is None
                or any(take is None for take in selected)
                or tuple(take.passage_id for take in selected if take is not None) != order
                or not selected_before_reservation
            ):
                raise ValidationError("narration assembly must bind exact historical ordered working selections")
            if attempt.artifact is not None:
                expected_start = 0
                for index, (take, offset) in enumerate(zip(selected, attempt.passage_offsets)):
                    if (
                        take is None
                        or offset.passage_id != take.passage_id
                        or offset.text_revision != take.text_revision
                        or offset.text_digest != take.text_digest
                        or offset.start_sample != expected_start
                        or offset.end_sample - offset.start_sample != take.media.sample_count
                    ):
                        raise ValidationError("narration assembly offsets must exactly place selected take media")
                    expected_start = offset.end_sample + (attempt.gaps_samples[index] if index < len(attempt.gaps_samples) else 0)
                if attempt.media is None or expected_start != attempt.media.sample_count:
                    raise ValidationError("narration assembly offsets must exactly cover staged media")
            master = None if attempt.master_id is None else masters.get(attempt.master_id)
            if attempt.state is AttemptState.COMPLETED:
                timing = tuple(take.timing_reference for take in selected if take is not None)
                if (
                    master is None
                    or master.job_id != snapshot.job_id
                    or master.lane is not snapshot.lane
                    or master.contract_digest != snapshot.contract.digest
                    or master.selected_take_ids != attempt.selected_take_ids
                    or master.gaps_samples != attempt.gaps_samples
                    or master.passage_offsets != attempt.passage_offsets
                    or master.timing_references != timing
                    or master.artifact != attempt.artifact
                    or master.media != attempt.media
                ):
                    raise ValidationError("completed narration assembly must link its exact immutable master")
            elif master is not None:
                raise ValidationError("only completed narration assembly may link a master")
        completed_master_ids = {value.master_id for value in snapshot.assembly_attempts if value.state is AttemptState.COMPLETED}
        if set(masters) != completed_master_ids:
            raise ValidationError("every narration master must be owned by one completed assembly attempt")

        if type(snapshot.master_listening) is not tuple or any(type(value) is not NarrationMasterListeningDecision for value in snapshot.master_listening):
            raise ValidationError("master-listening history must be immutable and typed")
        if (
            len({value.decision_id for value in snapshot.master_listening}) != len(snapshot.master_listening)
            or any(value.master_id not in masters for value in snapshot.master_listening)
        ):
            raise ValidationError("master-listening decisions must be unique and reference owned masters")

        if type(snapshot.issued_snapshots) is not tuple or any(type(value) is not NarrationMasterSnapshot for value in snapshot.issued_snapshots):
            raise ValidationError("issued snapshot history must be immutable and typed")
        if len({value.snapshot_id for value in snapshot.issued_snapshots}) != len(snapshot.issued_snapshots):
            raise ValidationError("issued narration snapshot identities must be unique")
        for issued in snapshot.issued_snapshots:
            master = masters.get(issued.source_master_id)
            order = NarrationJob._order_at(snapshot, issued.issuing_job_revision)
            scope = issued.authority_snapshot.scope
            if (
                master is None
                or issued.issuing_job_id != snapshot.job_id
                or issued.issuing_job_revision >= snapshot.revision
                or issued.listening_decision not in snapshot.master_listening
                or issued.listening_decision.master_id != master.master_id
                or issued.listening_decision.outcome is not ListeningOutcome.PASSED
                or issued.lane is not snapshot.lane
                or issued.role.value != snapshot.contract.permitted_role
                or issued.contract_digest != snapshot.contract.digest
                or issued.intended_episode_id != snapshot.contract.intended_episode_id
                or issued.authority_snapshot.record_id != snapshot.contract.authority_record_id
                or scope.speaker_binding != snapshot.contract.speaker_binding
                or scope.voice_binding != snapshot.contract.voice_binding
                or scope.language != snapshot.contract.language
                or scope.purpose != snapshot.contract.purpose
                or scope.intended_episode_id != snapshot.contract.intended_episode_id
                or not scope.covers(AuthorityOperation.ATTACH, issued.authority_snapshot.observed_at)
                or issued.ordered_passage_ids != order
                or issued.selected_take_ids != master.selected_take_ids
                or issued.gaps_samples != master.gaps_samples
                or issued.passage_offsets != master.passage_offsets
                or issued.timing_references != master.timing_references
                or issued.artifact != master.artifact
                or issued.media != master.media
            ):
                raise ValidationError("issued snapshot must be exact eligible by-value evidence from its source job graph")

    @classmethod
    def from_snapshot(cls, snapshot: NarrationJobSnapshot) -> NarrationJob:
        return cls(snapshot)

    def to_snapshot(self) -> NarrationJobSnapshot:
        return NarrationJobSnapshot(**{field: getattr(self, f"_{field}") for field in NarrationJobSnapshot.__dataclass_fields__})

    @property
    def job_id(self) -> NarrationJobId:
        return self._job_id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def lane(self) -> Lane:
        return self._lane

    @property
    def contract(self) -> ReleaseSynthesisContract:
        return self._contract

    @property
    def defaults(self) -> DeliveryControlDefaults:
        return self._defaults_history[-1].defaults

    @property
    def passages(self) -> tuple[PassageState, ...]:
        return tuple(sorted(self._passages, key=lambda value: value.order))

    @property
    def previews(self) -> tuple[GenerationPreview, ...]:
        return self._previews

    @property
    def generation_attempts(self) -> tuple[GenerationAttempt, ...]:
        return self._generation_attempts

    @property
    def takes(self) -> tuple[NarrationTake, ...]:
        return self._takes

    @property
    def reviews(self) -> tuple[ReviewDecision, ...]:
        return self._reviews

    @property
    def selections(self) -> tuple[SelectionDecision, ...]:
        return self._selections

    @property
    def assembly_attempts(self) -> tuple[NarrationAssemblyAttempt, ...]:
        return self._assembly_attempts

    @property
    def masters(self) -> tuple[NarrationMaster, ...]:
        return self._masters

    @property
    def master_listening(self) -> tuple[NarrationMasterListeningDecision, ...]:
        return self._master_listening

    @property
    def issued_snapshots(self) -> tuple[NarrationMasterSnapshot, ...]:
        return self._issued_snapshots

    def passage(self, passage_id: PassageId) -> PassageState:
        if type(passage_id) is not PassageId:
            raise NotFound("passage identity is invalid")
        for passage in self._passages:
            if passage.passage_id == passage_id:
                return passage
        raise NotFound(f"passage {passage_id} is not part of job {self._job_id}")

    def _check_revision(self, expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision != self._revision:
            raise RevisionConflict(f"expected job revision {expected_revision!r}, current is {self._revision}")

    def _replace_passage(self, updated: PassageState) -> None:
        self._passages = tuple(updated if item.passage_id == updated.passage_id else item for item in self._passages)

    def revise_passage_text(self, passage_id: PassageId, text: PassageText, revised_at: datetime, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        passage = self.passage(passage_id)
        if type(text) is not PassageText or text == passage.current_text_revision.text:
            raise ValidationError("new passage revision must contain changed canonical PassageText")
        _utc(revised_at, "passage text revision time")
        # INV-NJ-4: append text; prior takes/history remain untouched and compute stale.
        revision = PassageTextRevision(len(passage.text_revisions) + 1, text, revised_at)
        self._replace_passage(replace(passage, text_revisions=(*passage.text_revisions, revision), required_recipe_id=None))
        self._revision += 1

    def reorder_passages(self, ordered_passage_ids: tuple[PassageId, ...], *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        if type(ordered_passage_ids) is not tuple or len(set(ordered_passage_ids)) != len(ordered_passage_ids) or set(ordered_passage_ids) != {item.passage_id for item in self._passages}:
            raise ValidationError("new passage order must contain every unique passage exactly once")
        by_id = {item.passage_id: item for item in self._passages}
        self._passages = tuple(replace(by_id[identity], order=index) for index, identity in enumerate(ordered_passage_ids))
        self._revision += 1
        self._order_history = (*self._order_history, PassageOrderRevision(self._revision, ordered_passage_ids))

    def revise_delivery_defaults(self, defaults: DeliveryControlDefaults, revised_at: datetime, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        if type(defaults) is not DeliveryControlDefaults or defaults == self.defaults:
            raise ValidationError("delivery defaults revision must contain changed complete defaults")
        _utc(revised_at, "delivery defaults revision time")
        self._revision += 1
        self._defaults_history = (*self._defaults_history, DeliveryDefaultsRevision(self._revision, defaults, revised_at))

    def record_render_recipe(self, passage_id: PassageId, recipe: PassageRenderRecipe, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        passage = self.passage(passage_id)
        if type(recipe) is not PassageRenderRecipe:
            raise ValidationError("render recipe must be a PassageRenderRecipe")
        current = passage.current_text_revision
        # INV-NJ-15: a provider-neutral recipe can bind only current lexical text.
        if recipe.text_revision != current.revision:
            raise ValidationError("render recipe text revision is not current")
        recipe.validate_for(current.text)
        if any(value.recipe_id == recipe.recipe_id for value in passage.recipes):
            raise ValidationError("render recipe identity already exists")
        self._replace_passage(replace(passage, recipes=(*passage.recipes, recipe)))
        self._revision += 1

    def require_render_recipe(self, passage_id: PassageId, recipe_id: PassageRenderRecipeId, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        passage = self.passage(passage_id)
        recipe = passage.recipe(recipe_id)
        current = passage.current_text_revision
        if recipe.text_revision != current.revision or recipe.text_digest != current.text.digest:
            raise ValidationError("required recipe must bind current passage text")
        if passage.required_recipe_id == recipe_id:
            raise ValidationError("recipe is already required")
        self._replace_passage(replace(passage, required_recipe_id=recipe_id))
        self._revision += 1

    def require_dictionary_digest(self, passage_id: PassageId, dictionary_digest: ContentDigest, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        passage = self.passage(passage_id)
        if type(dictionary_digest) is not ContentDigest or passage.required_dictionary_digest == dictionary_digest:
            raise ValidationError("dictionary requirement must be a changed ContentDigest")
        self._replace_passage(replace(passage, required_dictionary_digest=dictionary_digest))
        self._revision += 1

    def issue_generation_preview(self, preview: GenerationPreview, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        if type(preview) is not GenerationPreview or preview.base_job_revision != self._revision:
            raise ValidationError("generation preview must bind the exact pre-save job revision")
        passage = self.passage(preview.passage_id)
        current = passage.current_text_revision
        recipe = passage.recipe(preview.recipe_id)
        if (
            preview.text_revision != current.revision
            or preview.text_digest != current.text.digest
            or preview.canonical_projection != current.text.value
            or preview.recipe_revision != recipe.revision
            or preview.recipe_digest != recipe.digest
            or preview.contract_digest != self._contract.digest
            or preview.authority_snapshot.record_id != self._contract.authority_record_id
            or preview.capability_snapshot != self._contract.capability_snapshot
            or preview.output_audio != self._contract.audio
        ):
            raise ValidationError("generation preview constituent facts are stale or mismatched")
        if any(item.preview_id == preview.preview_id for item in self._previews):
            raise ValidationError("generation preview identity already exists")
        self._previews = (*self._previews, preview)
        self._revision += 1

    def record_take(self, take: NarrationTake, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        raise DomainInvariantError("takes may be recorded only by completing their reserved generation attempt")

    def _preview_is_current(self, preview: GenerationPreview) -> bool:
        try:
            passage = self.passage(preview.passage_id)
            recipe = passage.recipe(preview.recipe_id)
        except NotFound:
            return False
        current = passage.current_text_revision
        scope = preview.authority_snapshot.scope
        defaults = self.defaults
        settings = preview.settings
        inherited_controls_match = all((
            settings.speed.provenance is not ControlProvenance.INHERITED or settings.speed.value == defaults.speed.value,
            settings.volume.provenance is not ControlProvenance.INHERITED or settings.volume.value == defaults.volume.value,
            settings.emotion.provenance is not ControlProvenance.INHERITED or settings.emotion.value == defaults.emotion,
            settings.dictionary_provenance is not ControlProvenance.INHERITED or settings.dictionary == defaults.dictionary,
        ))
        dictionary_digest = None if settings.dictionary is None else settings.dictionary.content_digest
        return all((
            preview.text_revision == current.revision,
            preview.text_digest == current.text.digest,
            preview.canonical_projection == current.text.value,
            preview.canonical_projection_digest == current.text.digest,
            recipe.text_revision == current.revision,
            recipe.text_digest == current.text.digest,
            preview.recipe_revision == recipe.revision,
            preview.recipe_digest == recipe.digest,
            passage.required_recipe_id is None or preview.recipe_id == passage.required_recipe_id,
            passage.required_dictionary_digest is None or dictionary_digest == passage.required_dictionary_digest,
            preview.contract_digest == self._contract.digest,
            preview.capability_snapshot == self._contract.capability_snapshot,
            preview.output_audio == self._contract.audio,
            preview.authority_snapshot.record_id == self._contract.authority_record_id,
            scope.speaker_binding == self._contract.speaker_binding,
            scope.voice_binding == self._contract.voice_binding,
            scope.language == self._contract.language,
            scope.purpose == self._contract.purpose,
            scope.intended_episode_id == self._contract.intended_episode_id,
            scope.covers(AuthorityOperation.GENERATE, preview.authority_snapshot.observed_at),
            inherited_controls_match,
        ))

    def generation_attempt(self, attempt_id: GenerationAttemptId) -> GenerationAttempt:
        for attempt in self._generation_attempts:
            if attempt.attempt_id == attempt_id:
                return attempt
        raise NotFound(f"generation attempt {attempt_id} is not part of job {self._job_id}")

    def _replace_generation_attempt(self, updated: GenerationAttempt) -> None:
        self._generation_attempts = tuple(
            updated if value.attempt_id == updated.attempt_id else value
            for value in self._generation_attempts
        )

    def reserve_generation_attempt(
        self,
        attempt_id: GenerationAttemptId,
        budget_reservation_id: BudgetReservationId,
        preview_id: GenerationPreviewId,
        reserved_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        self._check_revision(expected_revision)
        if type(attempt_id) is not GenerationAttemptId or type(budget_reservation_id) is not BudgetReservationId or type(preview_id) is not GenerationPreviewId:
            raise ValidationError("generation reservation identities are invalid")
        _utc(reserved_at, "generation reservation time")
        if any(value.attempt_id == attempt_id for value in self._generation_attempts):
            raise ValidationError("generation attempt identity already exists")
        if any(value.preview_id == preview_id for value in self._generation_attempts):
            raise ValidationError("a confirmed preview may reserve only one immutable attempt")
        preview = next((value for value in self._previews if value.preview_id == preview_id), None)
        if preview is None:
            raise NotFound(f"generation preview {preview_id} is not part of job {self._job_id}")
        # Preview issuance increments once; confirmation names that preview and current revision.
        if not self._preview_is_current(preview):
            raise ValidationError("generation preview is stale at reservation")
        attempt = GenerationAttempt(
            attempt_id,
            preview.passage_id,
            self._revision,
            budget_reservation_id,
            preview.preview_id,
            preview.preview_digest,
            AttemptState.RESERVED,
            SubmissionEvidence.NOT_STARTED,
            None,
            (),
            None,
            None,
            None,
            None,
            reserved_at,
            reserved_at,
        )
        self._generation_attempts = (*self._generation_attempts, attempt)
        self._revision += 1

    def freeze_generation_input(
        self,
        attempt_id: GenerationAttemptId,
        effective_input,
        *,
        expected_revision: int,
    ) -> None:
        from .values import EffectiveSynthesisInput

        self._check_revision(expected_revision)
        attempt = self.generation_attempt(attempt_id)
        if attempt.state is not AttemptState.RESERVED:
            raise DomainInvariantError("generation input may be frozen only from reserved")
        if type(effective_input) is not EffectiveSynthesisInput:
            raise ValidationError("generation input must be an EffectiveSynthesisInput")
        preview = next(value for value in self._previews if value.preview_id == attempt.preview_id)
        if (
            effective_input.job_id != self._job_id
            or effective_input.lane is not self._lane
            or effective_input.passage_id != preview.passage_id
            or effective_input.text_revision != preview.text_revision
            or effective_input.text.digest != preview.text_digest
            or effective_input.recipe_id != preview.recipe_id
            or effective_input.recipe_revision != preview.recipe_revision
            or effective_input.recipe_digest != preview.recipe_digest
            or effective_input.settings != preview.settings
            or effective_input.contract_digest != preview.contract_digest
            or effective_input.authority_scope != preview.authority_snapshot.scope
            or effective_input.authority_revision != preview.authority_snapshot.record_revision
            or effective_input.authority_digest != preview.authority_snapshot.record_digest
            or effective_input.authority_observed_at != preview.authority_snapshot.observed_at
            or effective_input.capability_snapshot != preview.capability_snapshot
            or effective_input.api_schema != self._contract.api_schema
            or effective_input.endpoint != preview.endpoint
            or effective_input.rendered_transcript_bytes != preview.rendered_transcript_bytes
            or effective_input.canonical_projection_digest != preview.canonical_projection_digest
            or effective_input.timestamps_requested != preview.timestamps_requested
            or effective_input.normalization != preview.normalization
            or effective_input.output_audio != preview.output_audio
            or effective_input.billable_rule != preview.billable_rule
            or effective_input.billable_characters != preview.billable_characters
        ):
            raise ValidationError("EffectiveSynthesisInput must exactly match the confirmed preview")
        self._replace_generation_attempt(
            replace(
                attempt,
                state=AttemptState.INPUT_FROZEN,
                effective_input=effective_input,
                updated_at=effective_input.authority_observed_at,
            )
        )
        self._revision += 1

    def mark_generation_external_work_started(
        self,
        attempt_id: GenerationAttemptId,
        started_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        self._check_revision(expected_revision)
        attempt = self.generation_attempt(attempt_id)
        if attempt.state is not AttemptState.INPUT_FROZEN:
            raise DomainInvariantError("external work may start only after exact input is frozen")
        _utc(started_at, "generation external-work start time")
        self._replace_generation_attempt(
            replace(
                attempt,
                state=AttemptState.EXTERNAL_WORK_STARTED,
                submission=SubmissionEvidence.STARTED,
                updated_at=started_at,
            )
        )
        self._revision += 1

    def stage_generation_artifacts(
        self,
        attempt_id: GenerationAttemptId,
        events,
        artifact,
        media,
        *,
        expected_revision: int,
    ) -> None:
        from .evidence import DecodedMediaFacts, ProviderEventEvidence, PublishedArtifact

        self._check_revision(expected_revision)
        attempt = self.generation_attempt(attempt_id)
        if attempt.state is not AttemptState.EXTERNAL_WORK_STARTED:
            raise DomainInvariantError("generation artifacts may be staged only after external work starts")
        if type(events) is not tuple or tuple(value.sequence for value in events) != tuple(range(len(events))) or any(type(value) is not ProviderEventEvidence for value in events):
            raise ValidationError("generation provider events must be a contiguous immutable sequence")
        if type(artifact) is not PublishedArtifact or type(media) is not DecodedMediaFacts:
            raise ValidationError("generation staging requires immutable artifact and media facts")
        self._replace_generation_attempt(
            replace(
                attempt,
                state=AttemptState.ARTIFACTS_STAGED,
                submission=SubmissionEvidence.COMPLETED,
                events=events,
                artifact=artifact,
                media=media,
                updated_at=events[-1].observed_at if events else attempt.updated_at,
            )
        )
        self._revision += 1

    def mark_generation_artifacts_published(self, attempt_id: GenerationAttemptId, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        attempt = self.generation_attempt(attempt_id)
        if attempt.state is not AttemptState.ARTIFACTS_STAGED or attempt.artifact is None or attempt.media is None:
            raise DomainInvariantError("generation artifacts may be published only from complete staged evidence")
        self._replace_generation_attempt(replace(attempt, state=AttemptState.ARTIFACTS_PUBLISHED))
        self._revision += 1

    def complete_generation_attempt(
        self,
        attempt_id: GenerationAttemptId,
        take: NarrationTake,
        completed_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        self._check_revision(expected_revision)
        attempt = self.generation_attempt(attempt_id)
        if attempt.state is not AttemptState.ARTIFACTS_PUBLISHED:
            raise DomainInvariantError("generation may complete only after artifact publication")
        _utc(completed_at, "generation completion time")
        if (
            type(take) is not NarrationTake
            or take.attempt_id != attempt.attempt_id
            or attempt.effective_input is None
            or take.effective_input != attempt.effective_input
            or take.artifact != attempt.artifact
            or take.media != attempt.media
            or take.job_id != self._job_id
        ):
            raise ValidationError("completed take must exactly match its attempt/input/artifacts")
        if any(value.take_id == take.take_id for value in self._takes):
            raise ValidationError("take identity already exists")
        self._replace_generation_attempt(
            replace(
                attempt,
                state=AttemptState.COMPLETED,
                submission=SubmissionEvidence.COMPLETED,
                take_id=take.take_id,
                updated_at=completed_at,
            )
        )
        self._takes = (*self._takes, take)
        self._revision += 1

    def finalize_generation_outcome(
        self,
        attempt_id: GenerationAttemptId,
        outcome: AttemptState,
        submission: SubmissionEvidence,
        reason: str,
        finalized_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        from heritage_archive.kernel import require_canonical_text

        self._check_revision(expected_revision)
        attempt = self.generation_attempt(attempt_id)
        if attempt.state.terminal:
            raise DomainInvariantError("terminal generation history is immutable")
        if outcome not in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.UNKNOWN, AttemptState.QUARANTINED}:
            raise ValidationError("generation outcome must be blocked, failed, unknown or quarantined")
        if type(submission) is not SubmissionEvidence:
            raise ValidationError("generation submission evidence is invalid")
        if outcome is AttemptState.UNKNOWN and submission is not SubmissionEvidence.AMBIGUOUS:
            raise ValidationError("unknown generation requires ambiguous submission evidence")
        if outcome is AttemptState.BLOCKED and submission not in {SubmissionEvidence.NOT_STARTED, SubmissionEvidence.DEFINITELY_NOT_SENT}:
            raise ValidationError("blocked generation must be pre-send")
        require_canonical_text(reason, field="generation outcome reason", nonempty=True)
        _utc(finalized_at, "generation outcome time")
        self._replace_generation_attempt(
            replace(attempt, state=outcome, submission=submission, reason=reason, updated_at=finalized_at)
        )
        self._revision += 1

    def reconcile_generation_attempt(
        self,
        attempt_id: GenerationAttemptId,
        outcome: AttemptState,
        recorded_evidence: str,
        reconciled_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        from heritage_archive.kernel import require_canonical_text

        self._check_revision(expected_revision)
        attempt = self.generation_attempt(attempt_id)
        if attempt.state is not AttemptState.UNKNOWN:
            raise DomainInvariantError("only unknown generation attempts may be reconciled")
        if outcome not in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.QUARANTINED}:
            raise DomainInvariantError("recorded recovery evidence may resolve unknown only to a conservative terminal outcome")
        require_canonical_text(recorded_evidence, field="generation reconciliation evidence", nonempty=True)
        _utc(reconciled_at, "generation reconciliation time")
        self._replace_generation_attempt(
            replace(
                attempt,
                state=outcome,
                reason=f"{attempt.reason}; reconciliation: {recorded_evidence}",
                updated_at=reconciled_at,
            )
        )
        self._revision += 1

    def recover_generation_completion(
        self,
        attempt_id: GenerationAttemptId,
        workspace: AttemptWorkspaceEvidence,
        take: NarrationTake,
        authority_eligible: bool,
        recovered_at: datetime,
        *,
        expected_revision: int,
    ) -> NarrationTake:
        """Bind an exact take from verified durable evidence without provider I/O."""

        self._check_revision(expected_revision)
        _utc(recovered_at, "generation recovery completion time")
        if authority_eligible is not True:
            raise AuthorizationDenied("current authority is required for recovered generation completion")
        attempt = self.generation_attempt(attempt_id)
        if type(workspace) is not AttemptWorkspaceEvidence or type(take) is not NarrationTake:
            raise ValidationError("generation recovery requires typed workspace and take evidence")
        if attempt.effective_input is None or not workspace.matches_completion_binding(
            attempt_kind=AttemptKind.GENERATION,
            aggregate_id=self._job_id,
            attempt_id=attempt.attempt_id,
            reservation_revision=attempt.reservation_revision,
            artifact=take.artifact,
            budget_reservation_id=attempt.budget_reservation_id,
            preview_digest=attempt.preview_digest,
            effective_input_digest=attempt.effective_input.request_digest,
            frozen_plan_digest=attempt.effective_input.request_digest,
        ):
            raise ValidationError("generation workspace does not prove the exact frozen attempt and publication")
        if (
            take.attempt_id != attempt.attempt_id
            or take.job_id != self._job_id
            or take.lane is not self._lane
            or take.passage_id != attempt.passage_id
            or take.effective_input != attempt.effective_input
            or (attempt.events and attempt.events != workspace.events)
            or (attempt.artifact is not None and attempt.artifact != take.artifact)
            or (attempt.media is not None and attempt.media != take.media)
        ):
            raise ValidationError("recovered take does not exactly match attempt-owned evidence")
        if attempt.state is AttemptState.COMPLETED:
            assert attempt.take_id is not None
            existing = self.take(attempt.take_id)
            if existing != take:
                raise ValidationError("completed generation recovery replay must name the exact existing take")
            return existing
        if attempt.state not in {
            AttemptState.EXTERNAL_WORK_STARTED,
            AttemptState.ARTIFACTS_STAGED,
            AttemptState.ARTIFACTS_PUBLISHED,
            AttemptState.UNKNOWN,
        }:
            raise DomainInvariantError("only post-external generation evidence may complete from recovery")
        if any(value.take_id == take.take_id for value in self._takes):
            raise ValidationError("recovered take identity already belongs to another attempt")
        completed = replace(
            attempt,
            state=AttemptState.COMPLETED,
            submission=SubmissionEvidence.COMPLETED,
            events=workspace.events,
            artifact=take.artifact,
            media=take.media,
            take_id=take.take_id,
            reason=None,
            updated_at=recovered_at,
        )
        self._replace_generation_attempt(completed)
        self._takes = (*self._takes, take)
        self._revision += 1
        return take

    def take(self, take_id: TakeId) -> NarrationTake:
        for take in self._takes:
            if take.take_id == take_id:
                return take
        raise NotFound(f"take {take_id} is not part of job {self._job_id}")

    def record_review_decision(
        self,
        decision_id: ReviewDecisionId,
        take_id: TakeId,
        actor_id: ActorId,
        authority: ReviewAuthority,
        outcome: ReviewOutcome,
        notes: str,
        decided_at: datetime,
        *,
        expected_revision: int,
    ) -> ReviewDecision:
        self._check_revision(expected_revision)
        take = self.take(take_id)
        if any(value.decision_id == decision_id for value in self._reviews):
            raise ValidationError("review decision identity already exists")
        # INV-NJ-9: exact ActorId is supplied by the server-side actor resolver.
        decision = ReviewDecision(decision_id, take.take_id, actor_id, authority, outcome, notes, decided_at)
        self._reviews = (*self._reviews, decision)
        self._revision += 1
        return decision

    def _latest_operational_review(self, take_id: TakeId) -> ReviewDecision | None:
        matching = [
            value
            for value in self._reviews
            if value.take_id == take_id and value.authority is ReviewAuthority.OPERATIONAL
        ]
        return matching[-1] if matching else None

    def _latest_selection(self, passage_id: PassageId) -> SelectionDecision | None:
        matching = [value for value in self._selections if value.passage_id == passage_id]
        return matching[-1] if matching else None

    def select_working_take(
        self,
        decision_id: SelectionDecisionId,
        passage_id: PassageId,
        take_id: TakeId,
        actor_id: ActorId,
        authority_eligible: bool,
        reason: str,
        decided_at: datetime,
        *,
        expected_revision: int,
    ) -> SelectionDecision:
        self._check_revision(expected_revision)
        if any(value.decision_id == decision_id for value in self._selections):
            raise ValidationError("selection decision identity already exists")
        take = self.take(take_id)
        if take.passage_id != passage_id:
            raise DomainInvariantError("working selection must target the take's exact passage")
        review = self._latest_operational_review(take_id)
        if review is None or review.outcome is not ReviewOutcome.ACCEPTED:
            raise DomainInvariantError("working selection requires the latest operational review to accept the take")
        eligibility = self.eligibility_for(take, authority_eligible=authority_eligible)
        if not eligibility.eligible:
            raise DomainInvariantError("working selection requires a current eligible take")
        decision = SelectionDecision(decision_id, passage_id, take_id, actor_id, eligibility, reason, decided_at)
        self._selections = (*self._selections, decision)
        self._revision += 1
        return decision

    def _current_selected_takes(self, *, authority_eligible: bool) -> tuple[NarrationTake, ...]:
        selected: list[NarrationTake] = []
        for passage in self.passages:
            decision = self._latest_selection(passage.passage_id)
            if decision is None:
                raise DomainInvariantError("narration assembly requires one working selection per passage")
            take = self.take(decision.take_id)
            review = self._latest_operational_review(take.take_id)
            if review is None or review.outcome is not ReviewOutcome.ACCEPTED:
                raise DomainInvariantError("selected take no longer has passing operational review")
            if not self.eligibility_for(take, authority_eligible=authority_eligible).eligible:
                raise DomainInvariantError("selected take is no longer current and eligible")
            selected.append(take)
        return tuple(selected)

    def narration_assembly_attempt(self, attempt_id: NarrationAssemblyAttemptId) -> NarrationAssemblyAttempt:
        for attempt in self._assembly_attempts:
            if attempt.attempt_id == attempt_id:
                return attempt
        raise NotFound(f"narration assembly attempt {attempt_id} is not part of job {self._job_id}")

    def _replace_assembly_attempt(self, updated: NarrationAssemblyAttempt) -> None:
        self._assembly_attempts = tuple(
            updated if value.attempt_id == updated.attempt_id else value
            for value in self._assembly_attempts
        )

    def reserve_narration_assembly(
        self,
        attempt_id: NarrationAssemblyAttemptId,
        gaps_samples: tuple[int, ...],
        authority_eligible: bool,
        reserved_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        self._check_revision(expected_revision)
        if authority_eligible is not True:
            # INV-NJ-7: protected assembly fails closed on current authority.
            raise AuthorizationDenied("current readable authority is required for narration assembly")
        selected = self._current_selected_takes(authority_eligible=True)
        if type(attempt_id) is not NarrationAssemblyAttemptId or any(value.attempt_id == attempt_id for value in self._assembly_attempts):
            raise ValidationError("narration assembly attempt identity is invalid or duplicated")
        if type(gaps_samples) is not tuple or len(gaps_samples) != max(0, len(selected) - 1) or any(type(value) is not int or value < 0 for value in gaps_samples):
            raise ValidationError("narration assembly requires one explicit nonnegative sample gap between passages")
        _utc(reserved_at, "narration assembly reservation time")
        attempt = NarrationAssemblyAttempt(
            attempt_id,
            self._revision,
            tuple(value.take_id for value in selected),
            gaps_samples,
            AttemptState.RESERVED,
            None,
            None,
            (),
            None,
            None,
            reserved_at,
            reserved_at,
        )
        self._assembly_attempts = (*self._assembly_attempts, attempt)
        self._revision += 1

    def freeze_narration_assembly_input(self, attempt_id: NarrationAssemblyAttemptId, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        attempt = self.narration_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.RESERVED:
            raise DomainInvariantError("narration assembly input may freeze only from reserved")
        current = tuple(value.take_id for value in self._current_selected_takes(authority_eligible=True))
        if current != attempt.selected_take_ids:
            raise DomainInvariantError("narration assembly selection changed before input freeze")
        self._replace_assembly_attempt(replace(attempt, state=AttemptState.INPUT_FROZEN))
        self._revision += 1

    def mark_narration_assembly_work_started(self, attempt_id: NarrationAssemblyAttemptId, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        attempt = self.narration_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.INPUT_FROZEN:
            raise DomainInvariantError("narration assembly work starts only after input freeze")
        self._replace_assembly_attempt(replace(attempt, state=AttemptState.EXTERNAL_WORK_STARTED))
        self._revision += 1

    def stage_narration_master(
        self,
        attempt_id: NarrationAssemblyAttemptId,
        artifact,
        media,
        passage_offsets: tuple[PassageOffset, ...],
        *,
        expected_revision: int,
    ) -> None:
        from .evidence import DecodedMediaFacts, PublishedArtifact

        self._check_revision(expected_revision)
        attempt = self.narration_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.EXTERNAL_WORK_STARTED:
            raise DomainInvariantError("narration master may stage only after assembly work starts")
        if type(artifact) is not PublishedArtifact or type(media) is not DecodedMediaFacts:
            raise ValidationError("narration master staging requires immutable artifact/media evidence")
        if type(passage_offsets) is not tuple or len(passage_offsets) != len(attempt.selected_take_ids):
            raise ValidationError("narration master requires one passage offset per selected take")
        expected_start = 0
        for index, (passage, take_id, offset) in enumerate(zip(self.passages, attempt.selected_take_ids, passage_offsets)):
            take = self.take(take_id)
            if (
                type(offset) is not PassageOffset
                or offset.passage_id != passage.passage_id
                or offset.text_revision != passage.current_text_revision.revision
                or offset.text_digest != passage.current_text_revision.text.digest
                or offset.start_sample != expected_start
                or offset.end_sample - offset.start_sample != take.media.sample_count
            ):
                raise ValidationError("narration passage offsets must exactly match selected takes and current text")
            expected_start = offset.end_sample
            if index < len(attempt.gaps_samples):
                expected_start += attempt.gaps_samples[index]
        if expected_start != media.sample_count:
            raise ValidationError("narration master media sample count does not match takes plus explicit gaps")
        self._replace_assembly_attempt(
            replace(attempt, state=AttemptState.ARTIFACTS_STAGED, artifact=artifact, media=media, passage_offsets=passage_offsets)
        )
        self._revision += 1

    def mark_narration_master_published(self, attempt_id: NarrationAssemblyAttemptId, *, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        attempt = self.narration_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.ARTIFACTS_STAGED:
            raise DomainInvariantError("narration master publication requires staged evidence")
        self._replace_assembly_attempt(replace(attempt, state=AttemptState.ARTIFACTS_PUBLISHED))
        self._revision += 1

    def complete_narration_assembly(
        self,
        attempt_id: NarrationAssemblyAttemptId,
        master_id: NarrationMasterId,
        completed_at: datetime,
        *,
        expected_revision: int,
    ) -> NarrationMaster:
        self._check_revision(expected_revision)
        attempt = self.narration_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.ARTIFACTS_PUBLISHED or attempt.artifact is None or attempt.media is None:
            raise DomainInvariantError("narration assembly completes only after publication")
        if type(master_id) is not NarrationMasterId or any(value.master_id == master_id for value in self._masters):
            raise ValidationError("narration master identity is invalid or duplicated")
        _utc(completed_at, "narration assembly completion time")
        master = NarrationMaster(
            master_id,
            self._job_id,
            self._lane,
            self._contract.digest,
            attempt.selected_take_ids,
            attempt.gaps_samples,
            attempt.passage_offsets,
            tuple(self.take(take_id).timing_reference for take_id in attempt.selected_take_ids),
            attempt.artifact,
            attempt.media,
            completed_at,
        )
        self._replace_assembly_attempt(replace(attempt, state=AttemptState.COMPLETED, master_id=master_id, updated_at=completed_at))
        self._masters = (*self._masters, master)
        self._revision += 1
        return master

    def finalize_narration_assembly_outcome(
        self,
        attempt_id: NarrationAssemblyAttemptId,
        outcome: AttemptState,
        reason: str,
        finalized_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        from heritage_archive.kernel import require_canonical_text

        self._check_revision(expected_revision)
        attempt = self.narration_assembly_attempt(attempt_id)
        if attempt.state.terminal:
            raise DomainInvariantError("terminal narration assembly history is immutable")
        if outcome not in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.UNKNOWN, AttemptState.QUARANTINED}:
            raise ValidationError("narration assembly outcome is invalid")
        require_canonical_text(reason, field="narration assembly outcome reason", nonempty=True)
        _utc(finalized_at, "narration assembly outcome time")
        self._replace_assembly_attempt(
            replace(attempt, state=outcome, reason=reason, updated_at=finalized_at)
        )
        self._revision += 1

    def reconcile_narration_assembly(
        self,
        attempt_id: NarrationAssemblyAttemptId,
        outcome: AttemptState,
        recorded_evidence: str,
        reconciled_at: datetime,
        *,
        expected_revision: int,
    ) -> None:
        from heritage_archive.kernel import require_canonical_text

        self._check_revision(expected_revision)
        attempt = self.narration_assembly_attempt(attempt_id)
        if attempt.state is not AttemptState.UNKNOWN:
            raise DomainInvariantError("only unknown narration assembly attempts may be reconciled")
        if outcome not in {AttemptState.BLOCKED, AttemptState.FAILED, AttemptState.QUARANTINED}:
            raise DomainInvariantError("narration assembly recovery must resolve to a conservative terminal outcome")
        require_canonical_text(recorded_evidence, field="narration assembly reconciliation evidence", nonempty=True)
        _utc(reconciled_at, "narration assembly reconciliation time")
        self._replace_assembly_attempt(
            replace(
                attempt,
                state=outcome,
                reason=f"{attempt.reason}; reconciliation: {recorded_evidence}",
                updated_at=reconciled_at,
            )
        )
        self._revision += 1

    def recover_narration_assembly_completion(
        self,
        attempt_id: NarrationAssemblyAttemptId,
        workspace: AttemptWorkspaceEvidence,
        master: NarrationMaster,
        authority_eligible: bool,
        recovered_at: datetime,
        *,
        expected_revision: int,
    ) -> NarrationMaster:
        """Bind an exact dry narration master from verified workspace evidence."""

        self._check_revision(expected_revision)
        _utc(recovered_at, "narration assembly recovery completion time")
        if authority_eligible is not True:
            raise AuthorizationDenied("current authority is required for recovered narration assembly")
        attempt = self.narration_assembly_attempt(attempt_id)
        if type(workspace) is not AttemptWorkspaceEvidence or type(master) is not NarrationMaster:
            raise ValidationError("narration recovery requires typed workspace and master evidence")
        if not workspace.matches_completion_binding(
            attempt_kind=AttemptKind.NARRATION_ASSEMBLY,
            aggregate_id=self._job_id,
            attempt_id=attempt.attempt_id,
            reservation_revision=attempt.reservation_revision,
            artifact=master.artifact,
            budget_reservation_id=None,
            preview_digest=None,
            effective_input_digest=None,
            frozen_plan_digest=narration_assembly_plan_digest(
                attempt.selected_take_ids, attempt.gaps_samples
            ),
        ) or workspace.events:
            raise ValidationError("narration workspace does not prove the exact assembly publication")
        takes = tuple(self.take(value) for value in attempt.selected_take_ids)
        expected_timing = tuple(value.timing_reference for value in takes)
        expected_start = 0
        for index, (take_value, offset) in enumerate(zip(takes, master.passage_offsets)):
            if (
                offset.passage_id != take_value.passage_id
                or offset.text_revision != take_value.text_revision
                or offset.text_digest != take_value.text_digest
                or offset.start_sample != expected_start
                or offset.end_sample - offset.start_sample != take_value.media.sample_count
            ):
                raise ValidationError("recovered narration offsets do not exactly bind selected takes")
            expected_start = offset.end_sample
            if index < len(attempt.gaps_samples):
                expected_start += attempt.gaps_samples[index]
        if (
            master.job_id != self._job_id
            or master.lane is not self._lane
            or master.contract_digest != self._contract.digest
            or master.selected_take_ids != attempt.selected_take_ids
            or master.gaps_samples != attempt.gaps_samples
            or master.timing_references != expected_timing
            or expected_start != master.media.sample_count
            or (attempt.artifact is not None and attempt.artifact != master.artifact)
            or (attempt.media is not None and attempt.media != master.media)
            or (attempt.passage_offsets and attempt.passage_offsets != master.passage_offsets)
        ):
            raise ValidationError("recovered narration master does not exactly match attempt-owned evidence")
        if attempt.state is AttemptState.COMPLETED:
            assert attempt.master_id is not None
            existing = self.master(attempt.master_id)
            if existing != master:
                raise ValidationError("completed narration recovery replay must name the exact existing master")
            return existing
        if attempt.state not in {
            AttemptState.EXTERNAL_WORK_STARTED,
            AttemptState.ARTIFACTS_STAGED,
            AttemptState.ARTIFACTS_PUBLISHED,
            AttemptState.UNKNOWN,
        }:
            raise DomainInvariantError("narration assembly state cannot complete from recovery evidence")
        if any(value.master_id == master.master_id for value in self._masters):
            raise ValidationError("recovered narration master identity belongs to another attempt")
        completed = replace(
            attempt,
            state=AttemptState.COMPLETED,
            artifact=master.artifact,
            media=master.media,
            passage_offsets=master.passage_offsets,
            master_id=master.master_id,
            reason=None,
            updated_at=recovered_at,
        )
        self._replace_assembly_attempt(completed)
        self._masters = (*self._masters, master)
        self._revision += 1
        return master

    def master(self, master_id: NarrationMasterId) -> NarrationMaster:
        for master in self._masters:
            if master.master_id == master_id:
                return master
        raise NotFound(f"narration master {master_id} is not part of job {self._job_id}")

    def record_narration_master_listening(
        self,
        decision_id: MasterListeningDecisionId,
        master_id: NarrationMasterId,
        actor_id: ActorId,
        outcome: ListeningOutcome,
        notes: str,
        decided_at: datetime,
        *,
        expected_revision: int,
    ) -> NarrationMasterListeningDecision:
        self._check_revision(expected_revision)
        self.master(master_id)
        if any(value.decision_id == decision_id for value in self._master_listening):
            raise ValidationError("master listening decision identity already exists")
        decision = NarrationMasterListeningDecision(decision_id, master_id, actor_id, outcome, notes, decided_at)
        self._master_listening = (*self._master_listening, decision)
        self._revision += 1
        return decision

    def _current_master(self, master: NarrationMaster, *, authority_eligible: bool) -> bool:
        try:
            selected = self._current_selected_takes(authority_eligible=authority_eligible)
        except DomainInvariantError:
            return False
        return (
            master.job_id == self._job_id
            and master.lane is self._lane
            and master.contract_digest == self._contract.digest
            and master.selected_take_ids == tuple(value.take_id for value in selected)
            and tuple(value.passage_id for value in master.passage_offsets) == tuple(value.passage_id for value in self.passages)
        )

    def issue_narration_master_snapshot(
        self,
        snapshot_id: NarrationMasterSnapshotId,
        master_id: NarrationMasterId,
        authority_snapshot: AuthoritySnapshot,
        authority_eligible: bool,
        issued_at: datetime,
        *,
        expected_revision: int,
    ) -> NarrationMasterSnapshot:
        self._check_revision(expected_revision)
        if authority_eligible is not True:
            raise AuthorizationDenied("current readable authority is required for snapshot issuance")
        if type(authority_snapshot) is not AuthoritySnapshot or authority_snapshot.record_id != self._contract.authority_record_id:
            raise AuthorizationDenied("snapshot authority record does not match fixed job binding")
        master = self.master(master_id)
        if not self._current_master(master, authority_eligible=True):
            raise DomainInvariantError("only a current eligible narration master may issue a snapshot")
        matching = [value for value in self._master_listening if value.master_id == master_id]
        if not matching or matching[-1].outcome is not ListeningOutcome.PASSED:
            # INV-NJ-17: operational whole-master listening must currently pass.
            raise DomainInvariantError("snapshot issuance requires passing whole-master listening")
        if any(value.snapshot_id == snapshot_id for value in self._issued_snapshots):
            raise ValidationError("narration master snapshot identity already exists")
        role = ComponentRole(self._contract.permitted_role)
        snapshot = NarrationMasterSnapshot.create(
            snapshot_id=snapshot_id,
            issuing_job_id=self._job_id,
            issuing_job_revision=self._revision,
            source_master=master,
            listening_decision=matching[-1],
            authority_snapshot=authority_snapshot,
            role=role,
            intended_episode_id=self._contract.intended_episode_id,
            ordered_passage_ids=tuple(value.passage_id for value in self.passages),
            selected_take_ids=master.selected_take_ids,
            issued_at=issued_at,
        )
        self._issued_snapshots = (*self._issued_snapshots, snapshot)
        self._revision += 1
        return snapshot

    def is_snapshot_current(self, snapshot: NarrationMasterSnapshot, *, authority_eligible: bool) -> bool:
        if type(snapshot) is not NarrationMasterSnapshot or type(authority_eligible) is not bool or not authority_eligible:
            return False
        issued = next((value for value in self._issued_snapshots if value.snapshot_id == snapshot.snapshot_id), None)
        if issued != snapshot:
            return False
        if snapshot.issuing_job_id != self._job_id or snapshot.contract_digest != self._contract.digest:
            return False
        if snapshot.lane is not self._lane or snapshot.role.value != self._contract.permitted_role:
            return False
        if snapshot.intended_episode_id != self._contract.intended_episode_id:
            return False
        try:
            master = self.master(snapshot.source_master_id)
        except NotFound:
            return False
        if not self._current_master(master, authority_eligible=True):
            return False
        matching = tuple(value for value in self._master_listening if value.master_id == master.master_id)
        if not matching or matching[-1].outcome is not ListeningOutcome.PASSED:
            return False
        return (
            snapshot.listening_decision == matching[-1]
            and snapshot.selected_take_ids == master.selected_take_ids
            and snapshot.gaps_samples == master.gaps_samples
            and snapshot.passage_offsets == master.passage_offsets
            and snapshot.timing_references == master.timing_references
            and snapshot.artifact == master.artifact
            and snapshot.media == master.media
            and snapshot.authority_snapshot.record_id == self._contract.authority_record_id
        )

    def eligibility_for(self, take: NarrationTake, *, authority_eligible: bool) -> EligibilityFacts:
        if type(take) is not NarrationTake:
            raise ValidationError("eligibility requires a NarrationTake")
        passage = self.passage(take.passage_id)
        current = passage.current_text_revision
        dictionary_digest = None if take.settings.dictionary is None else take.settings.dictionary.content_digest
        # Text-stale is intentionally distinct from every other eligibility reason.
        return EligibilityFacts(
            text_stale=(take.text_revision != current.revision or take.text_digest != current.text.digest),
            recipe_ineligible=(passage.required_recipe_id is not None and take.recipe_id != passage.required_recipe_id),
            dictionary_ineligible=(passage.required_dictionary_digest is not None and dictionary_digest != passage.required_dictionary_digest),
            contract_ineligible=(take.job_id != self._job_id or take.lane is not self._lane or take.contract_digest != self._contract.digest),
            authority_ineligible=(type(authority_eligible) is not bool or not authority_eligible or take.authority_snapshot.record_id != self._contract.authority_record_id),
        )


def _prepare_job(
    job_id: NarrationJobId,
    expected_lane: Lane,
    contract: ReleaseSynthesisContract,
    defaults: DeliveryControlDefaults,
    passages: tuple[PassageDraft, ...],
    prepared_at: datetime,
) -> NarrationJob:
    if type(job_id) is not NarrationJobId or type(contract) is not ReleaseSynthesisContract or contract.lane is not expected_lane:
        raise ValidationError("lane policy factory requires its exact fixed-lane contract")
    if type(defaults) is not DeliveryControlDefaults:
        raise ValidationError("lane policy factory requires complete delivery defaults")
    if expected_lane is Lane.C and (defaults.emotion is None or defaults.dictionary is None):
        raise ValidationError("Lane C requires every delivery-default and dictionary input explicitly")
    if type(passages) is not tuple or not passages or any(type(value) is not PassageDraft for value in passages):
        raise ValidationError("lane policy factory requires an immutable nonempty passage tuple")
    _utc(prepared_at, "narration job preparation time")
    states = tuple(
        PassageState(value.passage_id, value.order, (PassageTextRevision(1, value.text, prepared_at),), (), None, None)
        for value in passages
    )
    ordered = tuple(value.passage_id for value in sorted(states, key=lambda item: item.order))
    return NarrationJob(
        NarrationJobSnapshot(
            job_id,
            1,
            expected_lane,
            contract,
            (DeliveryDefaultsRevision(1, defaults, prepared_at),),
            states,
            (PassageOrderRevision(1, ordered),),
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            (),
            prepared_at,
        )
    )


def prepare_lane_b_diary_job(
    job_id: NarrationJobId,
    contract: ReleaseSynthesisContract,
    defaults: DeliveryControlDefaults,
    passages: tuple[PassageDraft, ...],
    prepared_at: datetime,
) -> NarrationJob:
    """Distinct Lane-B policy factory; never selected by a generic lane flag."""

    return _prepare_job(job_id, Lane.B, contract, defaults, passages, prepared_at)


def prepare_lane_c_intro_job(
    job_id: NarrationJobId,
    contract: ReleaseSynthesisContract,
    defaults: DeliveryControlDefaults,
    passages: tuple[PassageDraft, ...],
    prepared_at: datetime,
) -> NarrationJob:
    """Distinct narrow Lane-C policy factory with mandatory explicit inputs."""

    return _prepare_job(job_id, Lane.C, contract, defaults, passages, prepared_at)
