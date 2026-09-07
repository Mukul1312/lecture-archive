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
from ...domain.ids import AuthorizationRecordId, CommandId, DiaryEpisodeId, NarrationJobId, PassageId, PassageRenderRecipeId
from ...domain.narration_job import PassageDraft
from ...domain.values import (AuthorityScope, BreakControl, DeliveryControlDefaults, DictionaryBinding,
                             FixedTwoDecimal, Lane, PassageText, SpeedControl, SpellingControl, TextSpan, VolumeControl)
from ..filesystem_repositories import FilesystemRepositoryFailure
from ..operations import DoctorResult
from . import presenters
from .security import WebInputError, json_error, json_success, parse_json_object


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
    def __init__(self, handlers: AuthoringHandlers, bindings: AuthoringBindings, identifiers: IdentifierSource):
        self._handlers = handlers
        self._bindings = bindings
        self._identifiers = identifiers
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
            episode = None if not discovery.episode_ids else presenters.episode(self._handlers.show_episode_status(
                c.ShowEpisodeStatusCommand(self._command_id(), discovery.episode_ids[0])))
            authorities = []
            for lane in Lane:
                try:
                    status = self._handlers.show_authorization_status(c.ShowAuthorizationStatusCommand(
                        self._command_id(), self._bindings.record_id(lane)))
                except NotFound:
                    status = None
                authorities.append(presenters.authority(lane, status))
            jobs = [presenters.editor(self._handlers.show_editor(c.ShowNarrationEditorCommand(self._command_id(), job)))
                    for job in discovery.job_ids]
            return presenters.page(csrf_token, readiness, episode, authorities, jobs)
        except Exception:
            return presenters.unavailable_page(csrf_token)

    def __call__(self, request: WebRequest) -> WebResponse:
        try:
            return self._dispatch(request)
        except FilesystemRepositoryFailure:
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
        return self._edit(request)

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
