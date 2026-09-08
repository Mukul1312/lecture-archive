"""Persisted local authoring only: no key, network or listening socket."""
from dataclasses import replace
from importlib.util import find_spec
from html import escape, unescape
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from heritage_archive.composition_root import narrator_voice_live as live
from heritage_archive.composition_root import narrator_voice_web as web
from heritage_archive.contexts.narrator_voice.application.commands import DiscoverStudioCommand, ShowNarrationEditorCommand
from heritage_archive.contexts.narrator_voice.domain.ids import CommandId, NarrationJobId
from heritage_archive.contexts.narrator_voice.domain.values import AuthorityOperation, Lane
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import FilesystemAuthorizationRecordRepository
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.operations import initialize_local_studio
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.generation import ProcessGenerationControl
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity
from heritage_archive.platform.web import WebRequest
from tests.heritage_archive.narrator_voice.test_cartesia_gateway import Identifiers
from tests.heritage_archive.narrator_voice.test_cartesia_generation_integration import initialization
from tests.heritage_archive.narrator_voice.test_web_security import SESSION, CSRF, HOST, POST_HEADERS

PRINCIPAL = "fixture-server-only-principal"
TEXT = '\u0b13\u0b21\u0b3c\u0b3f\u0b06 & "fixture"\nAB CD'
AUTHORITY = {"evidenceDigest": "d" * 64, "validFrom": "2020-01-01T00:00:00Z", "validUntil": "2099-01-01T00:00:00+00:00"}


def textarea_value(markup, name):
    """Model only textarea RCDATA decoding and HTML's one-initial-LF removal.

    This focused extractor is not a browser parser. It accepts the presenter's
    escaped textarea content, decodes character references, and explicitly applies
    the browser rule that ignores one LF immediately after an opening textarea.
    """
    match = re.search(r'<textarea name="' + re.escape(name) + r'">(.*?)</textarea>', markup, re.DOTALL)
    if match is None:
        raise AssertionError("expected textarea was not rendered")
    value = unescape(match[1].replace("\r\n", "\n").replace("\r", "\n"))
    return value[1:] if value.startswith("\n") else value


class WebAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(find_spec("heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes"), "authoring routes are missing")
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import NarrationAuthoringRoutes
        original_get = os.environ.get
        def guarded_get(key, default=None):
            if key == "CARTESIA_API_KEY":
                raise AssertionError("credential read forbidden")
            return original_get(key, default)
        self.enterContext(patch.object(os.environ, "get", side_effect=guarded_get))
        for target in ("socket.getaddrinfo", "socket.socket.connect", "socket.socket.connect_ex", "socket.socket.bind", "httpx.Client.send"):
            self.enterContext(patch(target, side_effect=AssertionError("network forbidden")))
        directory = self.enterContext(TemporaryDirectory(prefix="web-authoring-fixture-"))
        self.root = LocalNarrationRoot.open(Path(directory), (Path(__file__).resolve().parents[3],))
        configuration = initialization()
        configuration = replace(configuration, lane_c=replace(configuration.lane_c, initial_emotion="calm"))
        initialize_local_studio(self.root, configuration, Identifiers())
        self.ids = Identifiers()
        self.studio = live.build_live_narration(self.root, process_principal=PRINCIPAL, identifiers=self.ids)
        self.addCleanup(self.studio.close)
        self.bindings = web.build_authoring_bindings(self.studio.policies, PRINCIPAL)
        self.generation = ProcessGenerationControl(SESSION)
        self.routes = NarrationAuthoringRoutes(self.studio.handlers, self.bindings, self.ids, self.generation)
        self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=self.routes, render_root=self.routes.render_root)

    def post(self, path, body, status=200, code=None):
        response = self.app(WebRequest("POST", path, POST_HEADERS, json.dumps(body).encode()))
        self.assertEqual(response.status, status, response.body)
        value = json.loads(response.body)
        self.assertEqual(dict(response.headers)[b"cache-control"], b"no-store")
        if code:
            self.assertEqual(value, {"ok": False, "error": {"code": code, "message": "The request could not be completed."}})
        self.assert_private_absent(response.body)
        return value.get("result")

    def assert_private_absent(self, body):
        for secret in (PRINCIPAL, "opaque-fake-voice", "fake-speaker", "dictionaryDigest", "authority_record_id", str(self.root.path), "d" * 64):
            self.assertNotIn(secret.encode(), body)
        for profile in (self.studio.policies.lane_b, self.studio.policies.lane_c):
            for secret in (profile.authorization_record_id.value, profile.dictionary_binding.opaque_reference,
                           profile.dictionary_binding.content_digest.hex_digest):
                self.assertNotIn(secret.encode(), body)

    def page(self):
        response = self.app(WebRequest("GET", "/", (HOST, POST_HEADERS[3])))
        self.assertEqual(response.status, 200, response.body)
        self.assert_private_absent(response.body)
        return response.body.decode()

    def editor(self, job):
        return self.studio.handlers.show_editor(ShowNarrationEditorCommand(self.ids.new_id(CommandId), NarrationJobId(job)))

    def diary(self, passages=None):
        self.post("/api/v1/authority/lane_b", AUTHORITY)
        return self.post("/api/v1/jobs/diary", {"passages": passages or [{"text": TEXT}]})

    def test_leading_lf_in_stored_passage_survives_textarea_and_unchanged_submission(self):
        text = '\nAB & "fixture"\n'
        job = self.diary([{"text": text}])["jobId"]
        current = self.editor(job)
        submitted = textarea_value(self.page(), "text")
        self.assertEqual(submitted, text)
        self.post("/api/v1/jobs/" + job + "/passages/" + current.passages[0].passage_id.value + "/text",
                  {"expectedRevision": 1, "text": submitted}, 422, "validation_failed")
        self.assertEqual(self.editor(job).revision, 1)
        self.assertEqual(self.editor(job).passages[0].text, text)

    def test_shared_textarea_renderer_preserves_canonical_values_after_html_lf_rule(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web import presenters
        # Literal independent examples make the extractor's narrow standards rule
        # explicit; it must remove exactly one LF, never strip all whitespace.
        self.assertEqual(textarea_value('<textarea name="text">\nAB</textarea>', "text"), "AB")
        self.assertEqual(textarea_value('<textarea name="text">\n\nAB</textarea>', "text"), "\nAB")
        for name in ("text", "passages", "advancedSource", "structuredControls", "orderedPassageIds"):
            for value in ("", "AB \ufffd \u0b06", "\nAB", '\n\n<spell>AB & "fixture"</spell>\n'):
                with self.subTest(name=name, value=value):
                    rendered = presenters.field(name, "Fixture", value, textarea=True)
                    self.assertEqual(textarea_value(rendered, name), value)

    def test_nul_input_is_rejected_before_textarea_backed_authoring_handlers(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import NarrationAuthoringRoutes
        job = self.diary()["jobId"]
        passage = self.editor(job).passages[0].passage_id.value
        def forbidden(command):
            self.fail("NUL input reached an authoring handler")
        handlers = replace(self.studio.handlers, prepare_diary=forbidden, revise_passage_text=forbidden, validate_recipe=forbidden)
        routes = NarrationAuthoringRoutes(handlers, self.bindings, self.ids, self.generation)
        self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=routes)
        path = "/api/v1/jobs/" + job + "/passages/" + passage
        cases = (("/api/v1/jobs/diary", {"passages": [{"text": "AB\0CD"}]}),
                 (path + "/text", {"expectedRevision": 1, "text": "AB\0CD"}),
                 (path + "/recipes/validate", {"expectedRevision": 1, "mode": "advanced",
                                               "structuredControls": [], "advancedSource": "AB\0CD"}))
        for url, body in cases:
            with self.subTest(url=url):
                self.post(url, body, 400, "invalid_input")
        self.assertEqual(self.editor(job).revision, 1)

    def test_existing_nul_passage_fails_closed_in_editor_and_shared_textarea_helper(self):
        from heritage_archive.contexts.narrator_voice.application.commands import RevisePassageTextCommand
        from heritage_archive.contexts.narrator_voice.domain.values import PassageText
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web import presenters
        job = self.diary()["jobId"]
        current = self.editor(job)
        # Seed legacy data through the existing application; the web boundary must
        # not silently display HTML's U+FFFD replacement as the stored text.
        self.studio.handlers.revise_passage_text(RevisePassageTextCommand(
            self.ids.new_id(CommandId), current.job_id, current.passages[0].passage_id,
            PassageText("NUL-fixture\0AB"), 1))
        page = self.page()
        self.assertIn("Authoring is disabled", page)
        self.assertNotIn("NUL-fixture", page)
        self.assertNotIn("<textarea", page)
        for name in ("text", "passages", "advancedSource"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                presenters.field(name, "Fixture", "AB\0CD", textarea=True)

    def test_empty_page_episode_and_configured_authorities_use_exact_private_bindings(self):
        page = self.page()
        self.post("/api/v1/jobs/intro", {"expectedEpisodeRevision": 1, "passages": [{"text": "fixture"}]}, 404, "not_found")
        self.assertIn("backup history is not persisted; use CLI backup and verify-backup", page)
        self.assertIn('action="/api/v1/episode"', page)
        self.assertIn("not registered", page)
        episode = self.post("/api/v1/episode", {})
        self.assertEqual(set(episode), {"episodeId", "revision"})
        self.post("/api/v1/jobs/intro", {"expectedEpisodeRevision": 2, "passages": [{"text": "fixture"}]}, 409, "stale_revision")
        for lane in (Lane.B, Lane.C):
            result = self.post("/api/v1/authority/" + lane.value, AUTHORITY)
            self.assertEqual(result, {"lane": lane.value, "revision": 1, "status": "active"})
            profile = self.studio.policies.lane_b if lane is Lane.B else self.studio.policies.lane_c
            record = FilesystemAuthorizationRecordRepository(self.root).load(profile.authorization_record_id)
            self.assertEqual(record.current_scope.operations, frozenset(AuthorityOperation))
            self.assertEqual(record.current_scope.voice_binding, profile.voice_binding)
            self.assertEqual(record.current_scope.language, "or")
            self.assertEqual(None if record.current_scope.intended_episode_id is None else record.current_scope.intended_episode_id.value,
                             None if lane is Lane.B else episode["episodeId"])
            self.post("/api/v1/authority/" + lane.value, AUTHORITY, 409, "authority_exists")
        self.post("/api/v1/episode", {}, 409, "episode_exists")
        intro = self.post("/api/v1/jobs/intro", {"expectedEpisodeRevision": 1, "passages": [{"text": "Intro fixture"}]})
        self.assertEqual(set(intro), {"jobId", "revision", "lane"})
        self.assertEqual(intro["lane"], "lane_c")
        self.assertNotIn('action="/api/v1/episode"', self.page())

    def test_odia_text_is_escaped_only_in_current_session_editor_and_survives_restart(self):
        prepared = self.diary()
        job = prepared["jobId"]
        self.assertEqual(set(prepared), {"jobId", "revision", "lane"})
        page = self.page()
        self.assertIn(escape(TEXT, quote=True), page)
        self.assertNotIn(TEXT, page)
        self.assertEqual(self.editor(job).passages[0].text, TEXT)
        for session in (None, "c" * 64):
            headers = (HOST,) if session is None else (HOST, (b"cookie", ("narrator_session=" + session).encode()))
            response = self.app(WebRequest("GET", "/", headers))
            self.assertNotIn(escape(TEXT, quote=True).encode(), response.body)
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import NarrationAuthoringRoutes
        restarted = live.build_live_narration(self.root, process_principal="new-fixture-principal", identifiers=Identifiers())
        self.addCleanup(restarted.close)
        routes = NarrationAuthoringRoutes(restarted.handlers, web.build_authoring_bindings(restarted.policies, "new-fixture-principal"), Identifiers(), ProcessGenerationControl("c" * 64))
        app = NarratorWebApplication(ProcessSecurity("c" * 64, "e" * 64), dispatch=routes, render_root=routes.render_root)
        self.assertNotIn(escape(TEXT, quote=True).encode(), app(WebRequest("GET", "/", (HOST, POST_HEADERS[3]))).body)
        current = app(WebRequest("GET", "/", (HOST, (b"cookie", b"narrator_session=" + b"c" * 64))))
        self.assertIn(escape(TEXT, quote=True).encode(), current.body)

    def test_text_order_defaults_and_dictionary_persist_exact_revisions(self):
        job = self.diary([{"text": TEXT}, {"text": "Second fixture"}])["jobId"]
        first, second = self.editor(job).passages
        base = "/api/v1/jobs/" + job
        result = self.post(base + "/passages/" + first.passage_id.value + "/text", {"expectedRevision": 1, "text": TEXT + " edited"})
        self.assertEqual(result, {"jobId": job, "revision": 2})
        self.post(base + "/order", {"expectedRevision": 2, "orderedPassageIds": [second.passage_id.value, first.passage_id.value]})
        self.post(base + "/defaults", {"expectedRevision": 3, "speed": "1.00", "volume": "1.10", "emotion": None})
        require = base + "/passages/" + first.passage_id.value + "/dictionary/require"
        self.post(require, {"expectedRevision": 4})
        self.post(require, {"expectedRevision": 5}, 422, "validation_failed")
        current = self.editor(job)
        self.assertEqual(current.revision, 5)
        self.assertEqual(current.passages[1].text, TEXT + " edited")
        self.assertTrue(current.passages[1].dictionary_required)
        self.assertTrue(current.defaults.dictionary_configured)
        self.assertEqual(current.defaults.speed, "1.00")
        from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import FilesystemNarrationJobRepository
        stored = FilesystemNarrationJobRepository(self.root).load(NarrationJobId(job))
        self.assertEqual(stored.defaults.dictionary, self.studio.policies.lane_b.dictionary_binding)
        self.assertEqual(stored.passages[1].required_dictionary_digest, self.studio.policies.lane_b.dictionary_binding.content_digest)
        page = self.page()
        for action in (base + "/order", base + "/defaults", require):
            self.assertIn('action="' + action + '"', page)

    def test_structured_and_advanced_compiler_recipes_are_owned_current_and_required(self):
        job = self.diary([{"text": "AB CD EF"}, {"text": "Other fixture"}])["jobId"]
        passage, other = self.editor(job).passages
        base = "/api/v1/jobs/" + job + "/passages/" + passage.passage_id.value
        controls = [{"kind": "break", "boundary": 2, "durationMs": 250},
                    {"kind": "speed", "start": 0, "end": 2, "value": "0.90"},
                    {"kind": "volume", "start": 3, "end": 5, "value": "1.10"},
                    {"kind": "spelling", "start": 6, "end": 8, "spelling": "EF"}]
        recipe = self.post(base + "/recipes/validate", {"expectedRevision": 1, "mode": "structured", "structuredControls": controls, "advancedSource": None})
        self.assertEqual(set(recipe), {"jobId", "revision", "recipeId", "recipeRevision", "textRevision"})
        self.assertEqual((recipe["revision"], recipe["recipeRevision"], recipe["textRevision"]), (2, 1, 1))
        self.post(base + "/recipes/require", {"expectedRevision": 2, "recipeId": recipe["recipeId"]})
        self.post(base + "/recipes/require", {"expectedRevision": 3, "recipeId": recipe["recipeId"]}, 409, "already_required")
        self.post(base + "/recipes/require", {"expectedRevision": 2, "recipeId": recipe["recipeId"]}, 409, "stale_revision")
        foreign = "/api/v1/jobs/" + job + "/passages/" + other.passage_id.value + "/recipes/require"
        self.post(foreign, {"expectedRevision": 3, "recipeId": recipe["recipeId"]}, 404, "not_found")
        advanced = '<speed ratio="0.90">AB</speed><break time="250ms"/> <volume ratio="1.10">CD</volume> <spell>EF</spell>'
        result = self.post(base + "/recipes/validate", {"expectedRevision": 3, "mode": "advanced", "structuredControls": [], "advancedSource": advanced})
        current = self.editor(job).passages[0]
        self.assertEqual(current.recipes[0].controls, current.recipes[1].controls)
        self.assertEqual(result["recipeRevision"], 1)
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web import presenters
        rendered = presenters.editor(self.editor(job))
        self.assertEqual(rendered["passages"][0]["recipes"][0]["controls"], [controls[1], controls[0], controls[2], controls[3]])
        self.assertIn(recipe["recipeId"], self.page())
        self.post(base + "/text", {"expectedRevision": 4, "text": "Changed fixture"})
        self.post(base + "/recipes/require", {"expectedRevision": 5, "recipeId": recipe["recipeId"]}, 422, "validation_failed")
        current = self.editor(job).passages[0]
        self.assertFalse(current.recipe_required)
        self.assertFalse(current.recipes[0].current)

    def test_strict_input_and_private_field_rejection_leave_store_unchanged(self):
        job = self.diary()["jobId"]
        passage = self.editor(job).passages[0].passage_id.value
        base = "/api/v1/jobs/" + job
        for text in ("e\u0301", "line\r\n", "\ud800", "x" * 8001, "<script>", ""):
            self.post(base + "/passages/" + passage + "/text", {"expectedRevision": 1, "text": text}, 400, "invalid_input")
        for revision in (True, 1.0, "1", 0):
            self.post(base + "/defaults", {"expectedRevision": revision, "speed": "1.00", "volume": "1.00", "emotion": None}, 400, "invalid_input")
        for key, value in (("speed", 1), ("speed", "1.0"), ("speed", "1.51"), ("volume", "0.49"), ("emotion", "angry"), ("emotion", {})):
            body = {"expectedRevision": 1, "speed": "1.00", "volume": "1.00", "emotion": None}
            body[key] = value
            self.post(base + "/defaults", body, 400, "invalid_input")
        for control in ({"kind": "break", "boundary": True, "durationMs": 250},
                        {"kind": "break", "boundary": 0, "duration_ms": 250},
                        {"kind": "spelling", "start": 0, "end": 2, "spelling": "AB", "path": "private"},
                        {"kind": "speed", "start": 2, "end": 1, "value": "1.00"}):
            self.post(base + "/passages/" + passage + "/recipes/validate", {"expectedRevision": 1, "mode": "structured", "structuredControls": [control], "advancedSource": None}, 400, "invalid_input")
        for key in ("actorId", "principal", "recordId", "scope", "voiceId", "providerId", "dictionaryId", "path", "artifactLocation"):
            self.post("/api/v1/authority/lane_b", {**AUTHORITY, key: "private"}, 400, "invalid_json")
        for value in ("2020-01-01", "2020-01-01T00:00Z", "2020-01-01T00:00:00+01:00", "2020-01-01T00:00:00.1234567Z"):
            self.post("/api/v1/authority/lane_c", {**AUTHORITY, "validFrom": value}, 400, "invalid_input")
        for path in ("/api/v1/authority/lane_a", base + "/passages/" + passage + "/defaults"):
            self.post(path, {}, 404, "not_found")
        self.assertEqual(self.editor(job).revision, 1)

    def test_single_episode_creation_is_nonblocking_and_rediscovers_under_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import NarrationAuthoringRoutes
        entered, release = Event(), Event()
        real = self.studio.handlers.prepare_episode
        def held(command):
            entered.set()
            if not release.wait(5):
                raise AssertionError("fixture release missing")
            return real(command)
        handlers = replace(self.studio.handlers, prepare_episode=held)
        routes = NarrationAuthoringRoutes(handlers, self.bindings, self.ids, self.generation)
        self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=routes)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.post, "/api/v1/episode", {})
            try:
                self.assertTrue(entered.wait(5))
                self.post("/api/v1/episode", {}, 409, "studio_busy")
            finally:
                release.set()
            first.result(timeout=5)
        self.post("/api/v1/episode", {}, 409, "episode_exists")
        self.assertEqual(len(self.studio.handlers.discover(DiscoverStudioCommand(self.ids.new_id(CommandId))).episode_ids), 1)

    def test_storage_faults_and_unsupported_discovery_fail_closed(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import NarrationAuthoringRoutes
        from heritage_archive.contexts.narrator_voice.infrastructure import filesystem_repositories as fs
        from heritage_archive.contexts.narrator_voice.application.commands import PrepareDiaryEpisodeCommand
        job = self.diary()["jobId"]
        passage = self.editor(job).passages[0].passage_id.value
        with patch.object(fs, "publish_bytes_no_clobber", side_effect=OSError("SENTINEL-private-publication")):
            self.post("/api/v1/jobs/" + job + "/passages/" + passage + "/text", {"expectedRevision": 1, "text": "Changed fixture"}, 500, "internal_error")
        self.assertEqual(self.editor(job).revision, 1)
        for _ in range(2):
            self.studio.handlers.prepare_episode(PrepareDiaryEpisodeCommand(self.ids.new_id(CommandId)))
        self.assertIn("Authoring is disabled", self.page())
        self.post("/api/v1/episode", {}, 409, "unsupported_state")
        self.post("/api/v1/jobs/diary", {"passages": [{"text": "fixture"}]}, 409, "unsupported_state")
        directory = self.root.aggregates / "narration-jobs" / "invalid-id"
        directory.mkdir()
        self.assertIn("Authoring is disabled", self.page())
        self.post("/api/v1/jobs/diary", {"passages": [{"text": "fixture"}]}, 500, "internal_error")

    def test_composed_application_has_real_packaged_assets_and_private_editor_wiring(self):
        from importlib.resources import files
        package = files("heritage_archive.contexts.narrator_voice.infrastructure.loopback_web")
        for name in ("studio.css", "studio.js"):
            self.assertTrue(package.joinpath("assets", name).is_file(), "missing packaged local asset")
        captured = []
        with patch.object(web, "serve_loopback", side_effect=captured.append):
            web.serve_narration(self.root)
        app = captured[0]
        bootstrap = app(WebRequest("GET", "/", (HOST,)))
        cookie = dict(bootstrap.headers)[b"set-cookie"].split(b";")[0]
        current = app(WebRequest("GET", "/", (HOST, (b"cookie", cookie))))
        self.assertIn(b"Storage readiness", current.body)
        for name, content_type in (("studio.css", b"text/css; charset=utf-8"), ("studio.js", b"text/javascript; charset=utf-8")):
            path = "/assets/" + name
            response = app(WebRequest("GET", path, (HOST,)))
            self.assertEqual(response.status, 200)
            self.assertEqual(response.body, package.joinpath("assets", name).read_bytes())
            self.assertEqual(dict(response.headers)[b"content-type"], content_type)
            self.assertEqual(dict(response.headers)[b"cache-control"], b"no-cache")
            self.assertGreater(len(response.body), 100)
            head = app(WebRequest("HEAD", path, (HOST,)))
            self.assertEqual(head.body, b"")
            self.assertEqual(head.headers, response.headers)
        self.assertIs(app._dispatch._identifiers, app._dispatch._handlers.prepare_diary.identifiers)

    def test_presenter_allowlists_redact_unknown_readiness_and_raw_result_fields(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web import presenters
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import DoctorResult
        result = presenters.readiness(DoctorResult(False, 3, ("json_invalid", "SENTINEL-private-code")))
        self.assertEqual(result, {"healthy": False, "checkedFileCount": 3, "issueCodes": ["json_invalid", "storage_issue"],
                                 "backupGuidance": "backup history is not persisted; use CLI backup and verify-backup"})
        self.assertEqual(presenters.authority(Lane.C, None), {"lane": "lane_c", "present": False, "revision": None,
            "status": None, "withdrawn": False, "validFrom": None, "validUntil": None, "coveredOperations": []})
        job = self.diary()["jobId"]
        value = presenters.editor(self.editor(job))
        self.assertEqual(set(value), {"jobId", "revision", "lane", "defaults", "passages"})
        self.assertEqual(set(value["defaults"]), {"speed", "volume", "emotion", "dictionaryConfigured"})
        self.assertEqual(set(value["passages"][0]), {"passageId", "order", "text", "textRevision", "recipes", "recipeRequired", "dictionaryRequired", "latestPreview"})

    def test_valid_authoring_failures_stay_distinct_from_local_syntax_and_unexpected_faults(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import NarrationAuthoringRoutes
        from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, DomainInvariantError, RevisionConflict
        from heritage_archive.kernel import ValidationError
        self.post("/api/v1/jobs/diary", {"passages": [{"text": "fixture"}]}, 403, "authority_denied")
        job = self.diary()["jobId"]
        passage = self.editor(job).passages[0].passage_id.value
        path = "/api/v1/jobs/" + job + "/passages/" + passage
        self.post(path + "/text", {"expectedRevision": 1, "text": TEXT}, 422, "validation_failed")
        for error, status, code in ((RevisionConflict(), 409, "stale_revision"),
                                     (AuthorizationDenied(), 403, "authority_denied"),
                                     (DomainInvariantError(), 422, "validation_failed"),
                                     (ValidationError("fixture"), 422, "validation_failed"),
                                     (ValueError("private"), 500, "internal_error"),
                                     (KeyError("private"), 500, "internal_error")):
            def fail(command):
                raise error
            routes = NarrationAuthoringRoutes(replace(self.studio.handlers, revise_passage_text=fail), self.bindings, self.ids, self.generation)
            self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=routes)
            self.post(path + "/text", {"expectedRevision": 1, "text": "Changed fixture"}, status, code)
        routes = NarrationAuthoringRoutes(self.studio.handlers, replace(self.bindings, dictionary=lambda lane: None), self.ids, self.generation)
        self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=routes)
        self.post(path + "/dictionary/require", {"expectedRevision": 1}, 422, "dictionary_unavailable")

    def test_corrupt_configured_authority_is_storage_failure_when_preparing_a_job(self):
        self.post("/api/v1/authority/lane_b", AUTHORITY)
        path = self.root.aggregates / "authorization-records" / self.studio.policies.lane_b.authorization_record_id.value / "revisions" / "00000000000000000001.json"
        path.write_bytes(b"corrupt fixture authority")
        self.post("/api/v1/jobs/diary", {"passages": [{"text": "fixture"}]}, 500, "internal_error")

    def test_compiler_limits_remain_authoritative_and_malformed_ids_do_not_reach_handlers(self):
        job = self.diary([{"text": "AB CD"}])["jobId"]
        passage = self.editor(job).passages[0].passage_id.value
        path = "/api/v1/jobs/" + job + "/passages/" + passage + "/recipes/validate"
        for source, status, code in (("x" * 16385, 400, "invalid_input"),
                                      ("\u0b06" * 5500, 400, "invalid_input"),
                                      ("<script>AB CD</script>", 422, "validation_failed"),
                                      ("Different fixture", 422, "validation_failed")):
            self.post(path, {"expectedRevision": 1, "mode": "advanced", "structuredControls": [], "advancedSource": source}, status, code)
        for controls in ([{"kind": "speed", "start": 0, "end": 2, "value": "1.51"}],
                         [{"kind": "speed", "start": 0, "end": 4, "value": "0.90"}, {"kind": "volume", "start": 2, "end": 5, "value": "1.00"}],
                         [{"kind": "break", "boundary": 6, "durationMs": 250}],
                         [{"kind": "break", "boundary": 0, "durationMs": 250}] * 65):
            self.post(path, {"expectedRevision": 1, "mode": "structured", "structuredControls": controls, "advancedSource": None}, 422, "validation_failed")
        self.post("/api/v1/jobs/not-a-uuid/order", {"expectedRevision": 1, "orderedPassageIds": [passage]}, 400, "invalid_input")
        self.post("/api/v1/jobs/" + job + "/order", {"expectedRevision": 1, "orderedPassageIds": [True]}, 400, "invalid_input")
        self.post("/api/v1/jobs/" + job + "/order", {"expectedRevision": 1, "orderedPassageIds": []}, 422, "validation_failed")
        self.assertEqual(self.editor(job).revision, 1)

    def test_future_authority_interval_is_truthful_and_invalid_interval_does_not_register(self):
        invalid = {**AUTHORITY, "validFrom": "2099-01-01T00:00:00Z", "validUntil": "2020-01-01T00:00:00Z"}
        self.post("/api/v1/authority/lane_b", invalid, 422, "validation_failed")
        self.post("/api/v1/authority/lane_b", {**AUTHORITY, "evidenceDigest": "D" * 64}, 400, "invalid_input")
        result = self.post("/api/v1/authority/lane_b", {**AUTHORITY, "validFrom": "2098-01-01T00:00:00.123456Z"})
        self.assertEqual(result["status"], "not_yet_valid")
        self.assertIn("not_yet_valid", self.page())
        self.post("/api/v1/jobs/diary", {"passages": [{"text": "fixture"}]}, 403, "authority_denied")


class WebAuthoringAsgiTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_editor_and_packaged_assets_through_socket_free_asgi(self):
        import httpx
        from heritage_archive.platform.web.loopback import build_asgi
        fixture = WebAuthoringTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        captured = []
        with patch.object(web, "serve_loopback", side_effect=captured.append):
            web.serve_narration(fixture.root)
        app = captured[0]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_asgi(app)), base_url="http://127.0.0.1:8765") as client:
            bootstrap = await client.get("/")
            self.assertIn("data-narrator-bootstrap", bootstrap.text)
            self.assertNotIn("Storage readiness", bootstrap.text)
            current = await client.get("/")
            self.assertIn("Storage readiness", current.text)
            self.assertEqual(current.headers["cache-control"], "no-store")
            for name in ("studio.css", "studio.js"):
                response = await client.get("/assets/" + name)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-cache")
                head = await client.head("/assets/" + name)
                self.assertEqual(head.content, b"")
                self.assertEqual(head.headers["content-length"], str(len(response.content)))
                self.assertEqual(head.headers["etag"], response.headers["etag"])
                cached = await client.get("/assets/" + name, headers={"If-None-Match": response.headers["etag"]})
                self.assertEqual(cached.status_code, 304)
