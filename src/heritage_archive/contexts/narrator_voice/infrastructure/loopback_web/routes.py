"""Exact local authoring routes over structural application dependencies."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import re
from threading import Lock
from typing import Protocol
import unicodedata

from heritage_archive.kernel import ContentDigest, ValidationError
from heritage_archive.platform.storage.local_files import WriterLockUnavailable
from heritage_archive.platform.web import WebRequest, WebResponse
from ...application import commands as c, results as r
from ...application.ports import IdentifierSource
from ...domain.errors import AuthorizationDenied, DomainInvariantError, NotFound, RevisionConflict
from ...domain.evidence import AttemptState, ListeningOutcome, NarrationMasterSnapshot, ReviewOutcome
from ...domain.ids import (AuthorizationRecordId, CommandId, DiaryEpisodeId, EpisodeAssemblyAttemptId,
                          EpisodeSpeechMasterId, GenerationAttemptId, NarrationAssemblyAttemptId,
                          NarrationJobId, NarrationMasterId, PassageId, PassageRenderRecipeId, TakeId)
from ...domain.narration_job import PassageDraft
from ...domain.values import (AuthorityScope, BreakControl, ComponentRole, DeliveryControlDefaults,
                             DictionaryBinding, FixedTwoDecimal, Lane, PassageText,
                             SafeRelativeArtifactPath, SpeedControl, SpellingControl, TextSpan,
                             VolumeControl)
from ..filesystem_failures import FilesystemOperationalFailure
from ..operations import DoctorResult
from . import presenters
from .generation import (ConfirmationCapacityReached, ConfirmationUnavailable,
                         ProcessGenerationControl, RECONCILABLE_GENERATION_STATES)
from .security import WebInputError, json_error, json_success, parse_json_object


MAX_GAP_SAMPLES = 220_500
RECONCILABLE_ASSEMBLY_STATES = frozenset({
    AttemptState.UNKNOWN,
    AttemptState.RESERVED,
    AttemptState.INPUT_FROZEN,
    AttemptState.EXTERNAL_WORK_STARTED,
    AttemptState.ARTIFACTS_STAGED,
    AttemptState.ARTIFACTS_PUBLISHED,
})


class AuthoringHandlers(Protocol):
    readiness: Callable[[], DoctorResult]
    discover: Callable[[c.DiscoverStudioCommand], r.StudioDiscoveryResult]
    show_editor: Callable[[c.ShowNarrationEditorCommand], r.NarrationEditorResult]
    show_authorization_status: Callable[[c.ShowAuthorizationStatusCommand], r.AuthorizationStatusResult]
    show_episode_status: Callable[[c.ShowEpisodeStatusCommand], r.EpisodeStatusResult]
    prepare_episode: Callable[[c.PrepareDiaryEpisodeCommand], r.EpisodeMutationResult]
    register_authorization: Callable[[c.RegisterAuthorizationCommand], r.AuthorizationResult]
    prepare_diary: Callable[[c.PrepareDiaryNarrationCommand], r.NarrationPreparedResult]
    prepare_intro: Callable[[c.PrepareIntroNarrationCommand], r.NarrationPreparedResult]
    revise_passage_text: Callable[[c.RevisePassageTextCommand], r.NarrationMutationResult]
    reorder_passages: Callable[[c.ReorderPassagesCommand], r.NarrationMutationResult]
    revise_defaults: Callable[[c.ReviseDeliveryDefaultsCommand], r.NarrationMutationResult]
    validate_recipe: Callable[[c.ValidateRenderRecipeCommand], r.RenderRecipeValidatedResult]
    require_recipe: Callable[[c.RequireRenderRecipeCommand], r.NarrationMutationResult]
    require_dictionary: Callable[[c.RequireDictionaryCommand], r.NarrationMutationResult]
    show_narration_status: Callable[[c.ShowNarrationStatusCommand], r.NarrationStatusResult]
    estimate: Callable[[c.EstimateGenerationCommand], r.GenerationEstimateResult]
    generate: Callable[[c.GenerateTakeCommand], r.GenerationRunResult]
    reconcile_generation: Callable[[c.ReconcileGenerationAttemptCommand], r.NarrationMutationResult]
    record_review: Callable[[c.RecordReviewDecisionCommand], r.NarrationMutationResult]
    select_take: Callable[[c.SelectWorkingTakeCommand], r.NarrationMutationResult]
    assemble_narration: Callable[[c.AssembleNarrationMasterCommand], r.NarrationAssemblyResult]
    record_narration_listening: Callable[[c.RecordNarrationMasterListeningCommand], r.NarrationMutationResult]
    issue_narration_snapshot: Callable[[c.IssueNarrationMasterSnapshotCommand], r.SnapshotIssuedResult]
    reconcile_narration_assembly: Callable[[c.ReconcileNarrationAssemblyAttemptCommand], r.NarrationMutationResult]
    attach_intro: Callable[[c.AttachIntroMasterCommand], r.EpisodeMutationResult]
    attach_diary: Callable[[c.AttachDiaryMasterCommand], r.EpisodeMutationResult]
    set_intro_diary_gap: Callable[[c.SetIntroDiaryGapCommand], r.EpisodeMutationResult]
    assemble_episode: Callable[[c.AssembleEpisodeSpeechMasterCommand], r.EpisodeAssemblyResult]
    record_episode_listening: Callable[[c.RecordEpisodeListeningCommand], r.EpisodeMutationResult]
    reconcile_episode_assembly: Callable[[c.ReconcileEpisodeAssemblyAttemptCommand], r.EpisodeMutationResult]
    read_take_audio: Callable[[c.ReadTakeAudioCommand], r.AudioPlaybackResult]
    read_narration_master_audio: Callable[[c.ReadNarrationMasterAudioCommand], r.AudioPlaybackResult]
    read_episode_master_audio: Callable[[c.ReadEpisodeMasterAudioCommand], r.AudioPlaybackResult]


@dataclass(frozen=True, slots=True)
class AuthoringBindings:
    principal: str = field(repr=False)
    record_id: Callable[[Lane], AuthorizationRecordId] = field(repr=False)
    scope: Callable[[Lane, DiaryEpisodeId | None, datetime, datetime], AuthorityScope] = field(repr=False)
    dictionary: Callable[[Lane], DictionaryBinding | None] = field(repr=False)


def invalid_input():
    raise WebInputError(400, "invalid_input")


def integer(value, minimum=1):
    if type(value) is not int or value < minimum:
        invalid_input()
    return value


def canonical_text(value, *, scalars=8000, byte_limit=32000):
    if (type(value) is not str or not value or len(value) > scalars or "\r" in value or "\0" in value
            or unicodedata.normalize("NFC", value) != value):
        invalid_input()
    try:
        if len(value.encode("utf-8")) > byte_limit:
            invalid_input()
    except UnicodeError:
        invalid_input()
    return value


def convert(constructor, *values):
    """Catch conversion errors locally, never around application or storage calls."""
    try:
        return constructor(*values)
    except (ValidationError, ValueError, TypeError):
        invalid_input()


def utc(value):
    if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value) is None:
        invalid_input()
    return convert(datetime.fromisoformat, value.replace("Z", "+00:00"))


def control(value):
    if type(value) is not dict or type(value.get("kind")) is not str:
        invalid_input()
    kind = value["kind"]
    shapes = {"break": {"kind", "boundary", "durationMs"},
              "speed": {"kind", "start", "end", "value"}, "volume": {"kind", "start", "end", "value"},
              "spelling": {"kind", "start", "end", "spelling"}}
    if kind not in shapes or value.keys() != shapes[kind]:
        invalid_input()
    if kind == "break":
        return convert(BreakControl, integer(value["boundary"], 0), integer(value["durationMs"]))
    span = convert(TextSpan, integer(value["start"], 0), integer(value["end"], 0))
    if kind == "spelling":
        return convert(SpellingControl, span, canonical_text(value["spelling"], scalars=64, byte_limit=256))
    return convert(SpeedControl if kind == "speed" else VolumeControl, span, convert(FixedTwoDecimal, value["value"]))


class NarrationAuthoringRoutes:
    def __init__(self, handlers: AuthoringHandlers, bindings: AuthoringBindings, identifiers: IdentifierSource,
                 generation: ProcessGenerationControl):
        self._handlers = handlers
        self._bindings = bindings
        self._identifiers = identifiers
        self._generation = generation
        self._episode_lock = Lock()

    def _command_id(self):
        return self._identifiers.new_id(CommandId)

    def _discover(self):
        discovery = self._handlers.discover(c.DiscoverStudioCommand(self._command_id()))
        if len(discovery.episode_ids) > 1:
            raise WebInputError(409, "unsupported_state")
        return discovery

    def render_root(self, csrf_token: str) -> bytes:
        try:
            readiness = presenters.readiness(self._handlers.readiness())
            discovery = self._discover()
            episode = None if not discovery.episode_ids else presenters.episode(
                self._show_episode_status(discovery.episode_ids[0]), busy=self._generation.busy,
            )
            authorities = []
            for lane in Lane:
                try:
                    status = self._handlers.show_authorization_status(c.ShowAuthorizationStatusCommand(
                        self._command_id(), self._bindings.record_id(lane)))
                except NotFound:
                    status = None
                authorities.append(presenters.authority(lane, status))
            jobs = []
            for job_id in discovery.job_ids:
                editor_result = self._handlers.show_editor(c.ShowNarrationEditorCommand(self._command_id(), job_id))
                status_result = self._handlers.show_narration_status(c.ShowNarrationStatusCommand(self._command_id(), job_id))
                if (editor_result.job_id != job_id or status_result.job_id != job_id
                        or editor_result.revision != status_result.revision):
                    raise ValueError("narration read model identity mismatch")
                jobs.append((presenters.editor(editor_result),
                             presenters.generation_status(status_result, busy=self._generation.busy),
                             presenters.narration_status(status_result, busy=self._generation.busy)))
            return presenters.page(csrf_token, readiness, episode, authorities, jobs)
        except Exception:
            return presenters.unavailable_page(csrf_token)

    def __call__(self, request: WebRequest) -> WebResponse:
        try:
            return self._dispatch(request)
        except FilesystemOperationalFailure:
            return json_error(500, "internal_error")
        except AuthorizationDenied:
            return json_error(403, "authority_denied")
        except NotFound:
            return json_error(404, "not_found")
        except RevisionConflict:
            return json_error(409, "stale_revision")
        except WriterLockUnavailable:
            return json_error(409, "studio_busy")
        except (ValidationError, DomainInvariantError):
            return json_error(422, "validation_failed")

    def _passages(self, value):
        if type(value) is not list or not 1 <= len(value) <= 128:
            invalid_input()
        drafts = []
        for order, passage in enumerate(value):
            if type(passage) is not dict or passage.keys() != {"text"}:
                invalid_input()
            text = convert(PassageText, canonical_text(passage["text"]))
            drafts.append(PassageDraft(self._identifiers.new_id(PassageId), order, text))
        return tuple(drafts)

    def _dispatch(self, request):
        media = self._media(request)
        if media is not None:
            return media
        if request.method != "POST":
            raise NotFound()
        if request.path == "/api/v1/episode":
            parse_json_object(request, frozenset())
            if not self._episode_lock.acquire(blocking=False):
                raise WebInputError(409, "studio_busy")
            try:
                if self._discover().episode_ids:
                    raise WebInputError(409, "episode_exists")
                result = self._handlers.prepare_episode(c.PrepareDiaryEpisodeCommand(self._command_id()))
                return json_success({"episodeId": result.episode_id.value, "revision": result.revision})
            finally:
                self._episode_lock.release()
        authority = re.fullmatch(r"/api/v1/authority/(lane_b|lane_c)", request.path)
        if authority:
            body = parse_json_object(request, frozenset({"evidenceDigest", "validFrom", "validUntil"}))
            lane = Lane(authority[1])
            digest = body["evidenceDigest"]
            if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                invalid_input()
            valid_from, valid_until = utc(body["validFrom"]), utc(body["validUntil"])
            discovery = self._discover()
            episode_id = discovery.episode_ids[0] if discovery.episode_ids else None
            if lane is Lane.C and episode_id is None:
                raise NotFound()
            scope = self._bindings.scope(lane, episode_id, valid_from, valid_until)
            try:
                result = self._handlers.register_authorization(c.RegisterAuthorizationCommand(
                    self._command_id(), self._bindings.principal, self._bindings.record_id(lane),
                    scope, ContentDigest("sha256", digest)))
            except RevisionConflict:
                raise WebInputError(409, "authority_exists") from None
            return json_success({"lane": lane.value, "revision": result.revision, "status": result.status.value})
        if request.path in {"/api/v1/jobs/diary", "/api/v1/jobs/intro"}:
            intro = request.path.endswith("/intro")
            body = parse_json_object(request, frozenset({"passages", "expectedEpisodeRevision"} if intro else {"passages"}))
            passages = self._passages(body["passages"])
            expected = integer(body["expectedEpisodeRevision"]) if intro else None
            discovery = self._discover()
            if intro and not discovery.episode_ids:
                raise NotFound()
            try:
                if intro:
                    result = self._handlers.prepare_intro(c.PrepareIntroNarrationCommand(
                        self._command_id(), discovery.episode_ids[0], expected, passages))
                else:
                    result = self._handlers.prepare_diary(c.PrepareDiaryNarrationCommand(self._command_id(), passages))
            except AuthorizationDenied:
                # The application deliberately collapses authority reader faults
                # into denial. Preserve its revision checks first, then distinguish
                # missing/invalid authority from a typed storage evidence failure.
                try:
                    self._handlers.show_authorization_status(c.ShowAuthorizationStatusCommand(
                        self._command_id(), self._bindings.record_id(Lane.C if intro else Lane.B)))
                except NotFound:
                    pass
                raise
            return json_success({"jobId": result.job_id.value, "revision": result.revision, "lane": result.lane.value})
        generation = self._generation_route(request)
        if generation is not None:
            return generation
        mastering = self._mastering_route(request)
        if mastering is not None:
            return mastering
        return self._edit(request)

    def _media(self, request):
        if request.method != "GET":
            return None
        routes = (
            (
                re.fullmatch(r"/audio/jobs/([^/]+)/takes/([^/]+)\.wav", request.path),
                NarrationJobId,
                TakeId,
                c.ReadTakeAudioCommand,
                "read_take_audio",
            ),
            (
                re.fullmatch(r"/audio/jobs/([^/]+)/masters/([^/]+)\.wav", request.path),
                NarrationJobId,
                NarrationMasterId,
                c.ReadNarrationMasterAudioCommand,
                "read_narration_master_audio",
            ),
            (
                re.fullmatch(r"/audio/episodes/([^/]+)/masters/([^/]+)\.wav", request.path),
                DiaryEpisodeId,
                EpisodeSpeechMasterId,
                c.ReadEpisodeMasterAudioCommand,
                "read_episode_master_audio",
            ),
        )
        selected = next((route for route in routes if route[0] is not None), None)
        if selected is None:
            return None
        matched, parent_type, child_type, command_type, handler_name = selected
        parent_id = convert(parent_type, matched[1])
        child_id = convert(child_type, matched[2])
        command_id = self._command_id()
        command = command_type(
            command_id,
            parent_id,
            child_id,
        )
        try:
            result = getattr(self._handlers, handler_name)(command)
        except (FilesystemOperationalFailure, NotFound):
            raise
        except ValidationError:
            raise WebInputError(500, "internal_error") from None
        if (
            type(result) is not r.AudioPlaybackResult
            or result.command_id != command_id
            or result.media_type != "audio/wav"
            or type(result.payload) is not bytes
            or type(result.byte_size) is not int
            or result.byte_size != len(result.payload)
            or ContentDigest.from_bytes(result.payload) != result.content_digest
        ):
            raise ValueError("invalid audio playback result")
        return WebResponse(
            200,
            result.payload,
            (
                (b"content-type", b"audio/wav"),
                (b"content-length", str(result.byte_size).encode()),
                (b"etag", ('"' + result.content_digest.hex_digest + '"').encode()),
            ),
        )

    def _show_narration_status(self, job_id):
        status = self._handlers.show_narration_status(
            c.ShowNarrationStatusCommand(self._command_id(), job_id)
        )
        if status.job_id != job_id:
            raise ValueError("narration status identity mismatch")
        return status

    def _show_episode_status(self, episode_id):
        status = self._handlers.show_episode_status(
            c.ShowEpisodeStatusCommand(self._command_id(), episode_id)
        )
        if status.episode_id != episode_id:
            raise ValueError("episode status identity mismatch")
        return status

    @staticmethod
    def _narration_mutation(result, command_id, job_id):
        if (
            type(result) is not r.NarrationMutationResult
            or result.command_id != command_id
            or result.job_id != job_id
            or type(result.revision) is not int
            or result.revision < 1
        ):
            raise ValueError("narration mutation result mismatch")
        return {"jobId": result.job_id.value, "revision": result.revision}

    @staticmethod
    def _episode_mutation(result, command_id, episode_id):
        if (
            type(result) is not r.EpisodeMutationResult
            or result.command_id != command_id
            or result.episode_id != episode_id
            or type(result.revision) is not int
            or result.revision < 1
        ):
            raise ValueError("episode mutation result mismatch")
        return {"episodeId": result.episode_id.value, "revision": result.revision}

    def _mastering_route(self, request):
        review = re.fullmatch(r"/api/v1/jobs/([^/]+)/takes/([^/]+)/review", request.path)
        select = re.fullmatch(r"/api/v1/jobs/([^/]+)/takes/([^/]+)/select", request.path)
        narration_assemble = re.fullmatch(r"/api/v1/jobs/([^/]+)/narration-masters", request.path)
        narration_listen = re.fullmatch(
            r"/api/v1/jobs/([^/]+)/narration-masters/([^/]+)/listen", request.path
        )
        attach = re.fullmatch(
            r"/api/v1/jobs/([^/]+)/narration-masters/([^/]+)/attach/([^/]+)", request.path
        )
        narration_reconcile = re.fullmatch(
            r"/api/v1/jobs/([^/]+)/narration-assembly-attempts/([^/]+)/reconcile", request.path
        )
        episode_gap = re.fullmatch(r"/api/v1/episodes/([^/]+)/gap", request.path)
        episode_assemble = re.fullmatch(r"/api/v1/episodes/([^/]+)/speech-masters", request.path)
        episode_listen = re.fullmatch(
            r"/api/v1/episodes/([^/]+)/speech-masters/([^/]+)/listen", request.path
        )
        episode_reconcile = re.fullmatch(
            r"/api/v1/episodes/([^/]+)/assembly-attempts/([^/]+)/reconcile", request.path
        )
        if review:
            return self._review(convert(NarrationJobId, review[1]), convert(TakeId, review[2]), request)
        if select:
            return self._select(convert(NarrationJobId, select[1]), convert(TakeId, select[2]), request)
        if narration_assemble:
            return self._assemble_narration(convert(NarrationJobId, narration_assemble[1]), request)
        if narration_listen:
            return self._listen_narration(
                convert(NarrationJobId, narration_listen[1]),
                convert(NarrationMasterId, narration_listen[2]),
                request,
            )
        if attach:
            if attach[3] not in {"intro", "diary"}:
                invalid_input()
            return self._attach(
                convert(NarrationJobId, attach[1]),
                convert(NarrationMasterId, attach[2]),
                ComponentRole(attach[3]),
                request,
            )
        if narration_reconcile:
            return self._reconcile_narration_assembly(
                convert(NarrationJobId, narration_reconcile[1]),
                convert(NarrationAssemblyAttemptId, narration_reconcile[2]),
                request,
            )
        if episode_gap:
            return self._set_gap(convert(DiaryEpisodeId, episode_gap[1]), request)
        if episode_assemble:
            return self._assemble_episode(convert(DiaryEpisodeId, episode_assemble[1]), request)
        if episode_listen:
            return self._listen_episode(
                convert(DiaryEpisodeId, episode_listen[1]),
                convert(EpisodeSpeechMasterId, episode_listen[2]),
                request,
            )
        if episode_reconcile:
            return self._reconcile_episode_assembly(
                convert(DiaryEpisodeId, episode_reconcile[1]),
                convert(EpisodeAssemblyAttemptId, episode_reconcile[2]),
                request,
            )
        return None

    def _review(self, job_id, take_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision", "outcome", "notes"}))
        expected = integer(body["expectedRevision"])
        outcome = convert(ReviewOutcome, body["outcome"])
        notes = canonical_text(body["notes"], scalars=2_000, byte_limit=8_192)
        command_id = self._command_id()
        result = self._handlers.record_review(c.RecordReviewDecisionCommand(
            command_id, self._bindings.principal, job_id, take_id, outcome, notes, expected,
        ))
        return json_success(self._narration_mutation(result, command_id, job_id))

    def _select(self, job_id, take_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision", "passageId", "reason"}))
        expected = integer(body["expectedRevision"])
        passage_id = convert(PassageId, body["passageId"])
        reason = canonical_text(body["reason"], scalars=2_000, byte_limit=8_192)
        command_id = self._command_id()
        result = self._handlers.select_take(c.SelectWorkingTakeCommand(
            command_id, self._bindings.principal, job_id, passage_id, take_id, reason, expected,
        ))
        return json_success(self._narration_mutation(result, command_id, job_id))

    def _listen_narration(self, job_id, master_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision", "outcome", "notes"}))
        expected = integer(body["expectedRevision"])
        outcome = convert(ListeningOutcome, body["outcome"])
        notes = canonical_text(body["notes"], scalars=2_000, byte_limit=8_192)
        command_id = self._command_id()
        result = self._handlers.record_narration_listening(c.RecordNarrationMasterListeningCommand(
            command_id, self._bindings.principal, job_id, master_id, outcome, notes, expected,
        ))
        return json_success(self._narration_mutation(result, command_id, job_id))

    def _listen_episode(self, episode_id, master_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision", "outcome", "notes"}))
        expected = integer(body["expectedRevision"])
        outcome = convert(ListeningOutcome, body["outcome"])
        notes = canonical_text(body["notes"], scalars=2_000, byte_limit=8_192)
        command_id = self._command_id()
        result = self._handlers.record_episode_listening(c.RecordEpisodeListeningCommand(
            command_id, self._bindings.principal, episode_id, master_id, outcome, notes, expected,
        ))
        return json_success(self._episode_mutation(result, command_id, episode_id))

    def _set_gap(self, episode_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision", "gapSamples"}))
        expected = integer(body["expectedRevision"])
        gap = integer(body["gapSamples"], 0)
        if gap > MAX_GAP_SAMPLES:
            raise WebInputError(422, "validation_failed")
        command_id = self._command_id()
        result = self._handlers.set_intro_diary_gap(c.SetIntroDiaryGapCommand(
            command_id, episode_id, gap, expected,
        ))
        return json_success(self._episode_mutation(result, command_id, episode_id))

    def _assemble_narration(self, job_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision", "gapsSamples"}))
        expected = integer(body["expectedRevision"])
        if type(body["gapsSamples"]) is not list:
            invalid_input()
        gaps = tuple(integer(value, 0) for value in body["gapsSamples"])
        if any(value > MAX_GAP_SAMPLES for value in gaps):
            raise WebInputError(422, "validation_failed")
        command_id = self._command_id()
        location = SafeRelativeArtifactPath(
            f"studio/narration-masters/{job_id.value}/{command_id.value}.wav"
        )
        if not self._generation.acquire():
            raise WebInputError(409, "assembly_busy")
        try:
            status = self._show_narration_status(job_id)
            if status.revision != expected:
                raise RevisionConflict()
            if len(gaps) != max(0, len(status.passages) - 1) or status.assembly_ready is not True:
                raise WebInputError(422, "validation_failed")
            try:
                result = self._handlers.assemble_narration(c.AssembleNarrationMasterCommand(
                    command_id, job_id, gaps, expected, location,
                ))
            except FilesystemOperationalFailure:
                raise
            except ValidationError:
                raise WebInputError(500, "internal_error") from None
            if (
                type(result) is not r.NarrationAssemblyResult
                or result.command_id != command_id
                or result.job_id != job_id
                or type(result.revision) is not int
                or result.revision < 1
            ):
                raise ValueError("narration assembly result identity mismatch")
            return json_success(presenters.narration_assembly(result))
        finally:
            self._generation.release()

    def _assemble_episode(self, episode_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision"}))
        expected = integer(body["expectedRevision"])
        command_id = self._command_id()
        location = SafeRelativeArtifactPath(
            f"studio/episode-masters/{episode_id.value}/{command_id.value}.wav"
        )
        if not self._generation.acquire():
            raise WebInputError(409, "assembly_busy")
        try:
            status = self._show_episode_status(episode_id)
            if status.revision != expected:
                raise RevisionConflict()
            if status.assembly_ready is not True:
                raise WebInputError(422, "validation_failed")
            try:
                result = self._handlers.assemble_episode(c.AssembleEpisodeSpeechMasterCommand(
                    command_id, episode_id, expected, location,
                ))
            except FilesystemOperationalFailure:
                raise
            except ValidationError:
                raise WebInputError(500, "internal_error") from None
            if (
                type(result) is not r.EpisodeAssemblyResult
                or result.command_id != command_id
                or result.episode_id != episode_id
                or type(result.revision) is not int
                or result.revision < 1
            ):
                raise ValueError("episode assembly result identity mismatch")
            return json_success(presenters.episode_assembly(result))
        finally:
            self._generation.release()

    def _reconcile_narration_assembly(self, job_id, attempt_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision"}))
        expected = integer(body["expectedRevision"])
        command_id = self._command_id()
        if not self._generation.acquire():
            raise WebInputError(409, "assembly_busy")
        try:
            status = self._show_narration_status(job_id)
            if status.revision != expected:
                raise RevisionConflict()
            attempt = next((value for value in status.assembly_attempts if value.attempt_id == attempt_id), None)
            if attempt is None:
                raise NotFound()
            if attempt.state not in RECONCILABLE_ASSEMBLY_STATES:
                raise WebInputError(409, "reconciliation_unavailable")
            try:
                result = self._handlers.reconcile_narration_assembly(
                    c.ReconcileNarrationAssemblyAttemptCommand(
                        command_id, job_id, attempt_id, expected,
                    )
                )
            except FilesystemOperationalFailure:
                raise
            except ValidationError:
                raise WebInputError(500, "internal_error") from None
            return json_success(self._narration_mutation(result, command_id, job_id))
        finally:
            self._generation.release()

    def _reconcile_episode_assembly(self, episode_id, attempt_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision"}))
        expected = integer(body["expectedRevision"])
        command_id = self._command_id()
        if not self._generation.acquire():
            raise WebInputError(409, "assembly_busy")
        try:
            status = self._show_episode_status(episode_id)
            if status.revision != expected:
                raise RevisionConflict()
            attempt = next((value for value in status.assembly_attempts if value.attempt_id == attempt_id), None)
            if attempt is None:
                raise NotFound()
            if attempt.state not in RECONCILABLE_ASSEMBLY_STATES:
                raise WebInputError(409, "reconciliation_unavailable")
            try:
                result = self._handlers.reconcile_episode_assembly(
                    c.ReconcileEpisodeAssemblyAttemptCommand(
                        command_id, episode_id, attempt_id, expected,
                    )
                )
            except FilesystemOperationalFailure:
                raise
            except ValidationError:
                raise WebInputError(500, "internal_error") from None
            return json_success(self._episode_mutation(result, command_id, episode_id))
        finally:
            self._generation.release()

    def _attach(self, job_id, master_id, role, request):
        body = parse_json_object(
            request,
            frozenset({"sourceExpectedRevision", "episodeId", "episodeExpectedRevision"}),
        )
        source_expected = integer(body["sourceExpectedRevision"])
        episode_id = convert(DiaryEpisodeId, body["episodeId"])
        episode_expected = integer(body["episodeExpectedRevision"])
        discovery = self._discover()
        if discovery.episode_ids != (episode_id,) or job_id not in discovery.job_ids:
            raise NotFound()
        source_status = self._show_narration_status(job_id)
        episode_status = self._show_episode_status(episode_id)
        if source_status.revision != source_expected or episode_status.revision != episode_expected:
            raise RevisionConflict()
        master = next((value for value in source_status.masters if value.master_id == master_id), None)
        if master is None:
            raise NotFound()
        expected_lane = Lane.C if role is ComponentRole.INTRO else Lane.B
        if master.attach_ready is not True or source_status.lane is not expected_lane:
            raise WebInputError(422, "validation_failed")

        issue_command_id = self._command_id()
        issued = self._handlers.issue_narration_snapshot(c.IssueNarrationMasterSnapshotCommand(
            issue_command_id, job_id, master_id, source_expected,
        ))
        snapshot = getattr(issued, "snapshot", None)
        expected_episode = episode_id if role is ComponentRole.INTRO else None
        if (
            type(issued) is not r.SnapshotIssuedResult
            or issued.command_id != issue_command_id
            or issued.job_id != job_id
            or type(issued.revision) is not int
            or issued.revision < 1
            or type(snapshot) is not NarrationMasterSnapshot
            or snapshot.issuing_job_id != job_id
            or snapshot.source_master_id != master_id
            or snapshot.role is not role
            or snapshot.lane is not expected_lane
            or snapshot.intended_episode_id != expected_episode
        ):
            raise ValueError("snapshot issuance result identity mismatch")

        attach_command_id = self._command_id()
        command_type = c.AttachIntroMasterCommand if role is ComponentRole.INTRO else c.AttachDiaryMasterCommand
        handler = self._handlers.attach_intro if role is ComponentRole.INTRO else self._handlers.attach_diary
        attached = handler(command_type(
            attach_command_id, episode_id, snapshot, episode_expected,
        ))
        self._episode_mutation(attached, attach_command_id, episode_id)
        return json_success({
            "jobId": issued.job_id.value,
            "sourceRevision": issued.revision,
            "episodeId": attached.episode_id.value,
            "episodeRevision": attached.revision,
            "masterId": master_id.value,
            "role": role.value,
        })

    def _generation_route(self, request):
        estimate_route = re.fullmatch(r"/api/v1/jobs/([^/]+)/estimate", request.path)
        generate_route = re.fullmatch(r"/api/v1/jobs/([^/]+)/generate", request.path)
        reconcile_route = re.fullmatch(
            r"/api/v1/jobs/([^/]+)/generation-attempts/([^/]+)/reconcile", request.path
        )
        if estimate_route:
            return self._estimate(convert(NarrationJobId, estimate_route[1]), request)
        if generate_route:
            return self._generate(convert(NarrationJobId, generate_route[1]), request)
        if reconcile_route:
            return self._reconcile(
                convert(NarrationJobId, reconcile_route[1]),
                convert(GenerationAttemptId, reconcile_route[2]),
                request,
            )
        return None

    @staticmethod
    def _text_override(mode_value, value, *, fixed_decimal: bool):
        mode = convert(c.OverrideMode, mode_value)
        if mode in {c.OverrideMode.INHERIT, c.OverrideMode.OMIT}:
            if value is not None:
                invalid_input()
            return c.TextControlOverride(mode)
        if fixed_decimal:
            return c.TextControlOverride(mode, convert(FixedTwoDecimal, value).value)
        return c.TextControlOverride(mode, canonical_text(value, scalars=64, byte_limit=256))

    def _estimate(self, job_id, request):
        keys = frozenset({
            "expectedRevision", "passageId", "recipeId", "speedMode", "speed",
            "volumeMode", "volume", "emotionMode", "emotion", "dictionaryMode",
        })
        body = parse_json_object(request, keys)
        expected = integer(body["expectedRevision"])
        passage_id = convert(PassageId, body["passageId"])
        recipe_id = convert(PassageRenderRecipeId, body["recipeId"])
        speed = self._text_override(body["speedMode"], body["speed"], fixed_decimal=True)
        volume = self._text_override(body["volumeMode"], body["volume"], fixed_decimal=True)
        emotion = self._text_override(body["emotionMode"], body["emotion"], fixed_decimal=False)
        dictionary_mode = convert(c.OverrideMode, body["dictionaryMode"])

        self._discover()
        editor = self._handlers.show_editor(c.ShowNarrationEditorCommand(self._command_id(), job_id))
        if editor.job_id != job_id:
            raise ValueError("narration editor identity mismatch")
        if editor.revision != expected:
            raise RevisionConflict()
        passage = next((item for item in editor.passages if item.passage_id == passage_id), None)
        if passage is None:
            raise NotFound()
        recipe = next((item for item in passage.recipes if item.recipe_id == recipe_id), None)
        if recipe is None or not recipe.current:
            raise NotFound()
        dictionary = None
        if dictionary_mode is c.OverrideMode.SET:
            dictionary = self._bindings.dictionary(editor.lane)
            if dictionary is None:
                raise WebInputError(422, "dictionary_unavailable")
        settings = c.TakeSettingsIntent(speed, volume, emotion, c.DictionaryOverride(dictionary_mode, dictionary))
        result = self._handlers.estimate(c.EstimateGenerationCommand(
            self._command_id(), job_id, passage_id, recipe_id, settings, expected
        ))
        if result.job_id != job_id:
            raise ValueError("generation estimate identity mismatch")
        try:
            token = self._generation.issue(result)
        except ConfirmationCapacityReached:
            raise WebInputError(409, "confirmation_capacity") from None
        return json_success(presenters.generation_estimate(result, token))

    def _generate(self, job_id, request):
        body = parse_json_object(request, frozenset({"confirmationToken"}))
        token = body["confirmationToken"]
        if type(token) is not str or re.fullmatch(r"[0-9a-f]{64}", token) is None:
            invalid_input()
        command_id = self._command_id()
        location = SafeRelativeArtifactPath(f"studio/takes/{job_id.value}/{command_id.value}.wav")
        if not self._generation.acquire():
            raise WebInputError(409, "generation_busy")
        try:
            try:
                confirmation = self._generation.consume(token, job_id)
            except ConfirmationUnavailable:
                raise WebInputError(409, "confirmation_unavailable") from None
            try:
                result = self._handlers.generate(c.GenerateTakeCommand(
                    command_id, confirmation.job_id, confirmation.preview_id,
                    confirmation.expected_revision, location,
                ))
            except FilesystemOperationalFailure:
                raise
            except ValidationError:
                raise WebInputError(500, "internal_error") from None
            if result.job_id != confirmation.job_id:
                raise ValueError("generation result identity mismatch")
            return json_success(presenters.generation_run(result))
        finally:
            self._generation.release()

    def _reconcile(self, job_id, attempt_id, request):
        body = parse_json_object(request, frozenset({"expectedRevision"}))
        expected = integer(body["expectedRevision"])
        command_id = self._command_id()
        if not self._generation.acquire():
            raise WebInputError(409, "generation_busy")
        try:
            try:
                status = self._handlers.show_narration_status(
                    c.ShowNarrationStatusCommand(self._command_id(), job_id)
                )
                if status.job_id != job_id:
                    raise ValueError("narration status identity mismatch")
                if status.revision != expected:
                    raise RevisionConflict()
                attempt = next((item for item in status.generation_attempts if item.attempt_id == attempt_id), None)
                if attempt is None:
                    raise NotFound()
                if attempt.state not in RECONCILABLE_GENERATION_STATES:
                    raise WebInputError(409, "reconciliation_unavailable")
                result = self._handlers.reconcile_generation(c.ReconcileGenerationAttemptCommand(
                    command_id, job_id, attempt_id, expected
                ))
            except FilesystemOperationalFailure:
                raise
            except ValidationError:
                raise WebInputError(500, "internal_error") from None
            if result.job_id != job_id:
                raise ValueError("generation reconciliation identity mismatch")
            return json_success({"jobId": result.job_id.value, "revision": result.revision})
        finally:
            self._generation.release()

    def _edit(self, request):
        job_route = re.fullmatch(r"/api/v1/jobs/([^/]+)/(order|defaults)", request.path)
        passage_route = re.fullmatch(r"/api/v1/jobs/([^/]+)/passages/([^/]+)/(text|recipes/validate|recipes/require|dictionary/require)", request.path)
        if job_route:
            raw_job, action = job_route.groups()
            passage_id = None
        elif passage_route:
            raw_job, raw_passage, action = passage_route.groups()
            passage_id = convert(PassageId, raw_passage)
        else:
            raise NotFound()
        job_id = convert(NarrationJobId, raw_job)
        keys = {"text": {"text"}, "order": {"orderedPassageIds"}, "defaults": {"speed", "volume", "emotion"},
                "recipes/validate": {"mode", "structuredControls", "advancedSource"}, "recipes/require": {"recipeId"},
                "dictionary/require": set()}
        body = parse_json_object(request, frozenset({"expectedRevision"} | keys[action]))
        expected = integer(body["expectedRevision"])
        # Finish lexical conversion before invoking any authoring handler.
        if action == "text":
            value = convert(PassageText, canonical_text(body["text"]))
        elif action == "order":
            if type(body["orderedPassageIds"]) is not list:
                invalid_input()
            value = tuple(convert(PassageId, item) for item in body["orderedPassageIds"])
        elif action == "defaults":
            speed, volume = convert(FixedTwoDecimal, body["speed"]), convert(FixedTwoDecimal, body["volume"])
            emotion = body["emotion"]
            if (not Decimal("0.60") <= Decimal(speed.value) <= Decimal("1.50")
                    or not Decimal("0.50") <= Decimal(volume.value) <= Decimal("2.00")
                    or (emotion is not None and (type(emotion) is not str or emotion != "calm"))):
                invalid_input()
        elif action == "recipes/require":
            value = convert(PassageRenderRecipeId, body["recipeId"])
        elif action == "recipes/validate":
            mode = convert(c.RecipeAuthoringMode, body["mode"])
            if type(body["structuredControls"]) is not list:
                invalid_input()
            if mode is c.RecipeAuthoringMode.STRUCTURED:
                if body["advancedSource"] is not None:
                    invalid_input()
                controls = tuple(control(item) for item in body["structuredControls"])
                source = None
            else:
                if body["structuredControls"]:
                    invalid_input()
                controls = ()
                source = canonical_text(body["advancedSource"], scalars=16384, byte_limit=16384)
            value = c.RecipeAuthoringIntent(self._identifiers.new_id(PassageRenderRecipeId), 1, mode, controls, source)
        self._discover()
        editor = self._handlers.show_editor(c.ShowNarrationEditorCommand(self._command_id(), job_id))
        if editor.revision != expected:
            raise RevisionConflict()
        if passage_id is not None:
            passage = next((item for item in editor.passages if item.passage_id == passage_id), None)
            if passage is None:
                raise NotFound()
        command_id = self._command_id()
        if action == "text":
            result = self._handlers.revise_passage_text(c.RevisePassageTextCommand(command_id, job_id, passage_id, value, expected))
        elif action == "order":
            result = self._handlers.reorder_passages(c.ReorderPassagesCommand(command_id, job_id, value, expected))
        elif action == "defaults":
            defaults = DeliveryControlDefaults(speed, volume, emotion, self._bindings.dictionary(editor.lane))
            result = self._handlers.revise_defaults(c.ReviseDeliveryDefaultsCommand(command_id, job_id, defaults, expected))
        elif action == "recipes/validate":
            result = self._handlers.validate_recipe(c.ValidateRenderRecipeCommand(command_id, job_id, passage_id, value, expected))
            return json_success({"jobId": result.job_id.value, "revision": result.revision,
                "recipeId": result.recipe.recipe_id.value, "recipeRevision": result.recipe.revision, "textRevision": result.recipe.text_revision})
        elif action == "recipes/require":
            recipe = next((item for item in passage.recipes if item.recipe_id == value), None)
            if recipe is None:
                raise NotFound()
            if recipe.required:
                raise WebInputError(409, "already_required")
            result = self._handlers.require_recipe(c.RequireRenderRecipeCommand(command_id, job_id, passage_id, value, expected))
        else:
            dictionary = self._bindings.dictionary(editor.lane)
            if dictionary is None:
                raise WebInputError(422, "dictionary_unavailable")
            result = self._handlers.require_dictionary(c.RequireDictionaryCommand(command_id, job_id, passage_id, dictionary.content_digest, expected))
        return json_success({"jobId": result.job_id.value, "revision": result.revision})
