"""Fixture-only review, attachment and dry-mastering route contracts."""

from __future__ import annotations

from itertools import count
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.application import commands as c, results as r
from heritage_archive.contexts.narrator_voice.domain.evidence import AttemptState, ListeningOutcome, ReviewOutcome
from heritage_archive.contexts.narrator_voice.domain.errors import DomainInvariantError, RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import (
    CommandId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeSpeechMasterId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    PassageId,
    TakeId,
)
from heritage_archive.contexts.narrator_voice.domain.values import ComponentRole, Lane, SafeRelativeArtifactPath
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web import presenters
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.generation import ProcessGenerationControl
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import AuthoringBindings, NarrationAuthoringRoutes
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity
from heritage_archive.platform.web import WebRequest
from tests.heritage_archive.narrator_voice import test_application_episode as episode_fixture
from tests.heritage_archive.narrator_voice import test_application_status as status_fixture
from tests.heritage_archive.narrator_voice.fixtures import uuid
from tests.heritage_archive.narrator_voice.test_web_security import CSRF, POST_HEADERS, SESSION


class _Identifiers:
    def __init__(self):
        self._values = count(8000)

    def new_id(self, kind):
        return kind(uuid(next(self._values)))


def _narration_status(
    job_id, lane, *, revision=11, passages=2, masters=(), attempts=(), ready=True,
    intended_episode_id=None,
):
    return SimpleNamespace(
        job_id=job_id,
        revision=revision,
        lane=lane,
        intended_episode_id=intended_episode_id,
        passages=tuple(
            SimpleNamespace(passage_id=PassageId(uuid(8200 + index)))
            for index in range(passages)
        ),
        masters=tuple(masters),
        assembly_attempts=tuple(attempts),
        assembly_ready=ready,
    )


def _episode_status(episode_id, *, revision=17, ready=True, attempts=()):
    return SimpleNamespace(
        episode_id=episode_id,
        revision=revision,
        assembly_ready=ready,
        assembly_attempts=tuple(attempts),
    )


class WebMasteringRouteTests(unittest.TestCase):
    def setUp(self):
        self.identifiers = _Identifiers()
        self.control = ProcessGenerationControl(SESSION)
        self.job_id = NarrationJobId(uuid(8100))
        self.take_id = TakeId(uuid(8101))
        self.passage_id = PassageId(uuid(8102))
        self.master_id = NarrationMasterId(uuid(8103))
        self.narration_attempt_id = NarrationAssemblyAttemptId(uuid(8104))
        self.episode_id = DiaryEpisodeId(uuid(8110))
        self.episode_master_id = EpisodeSpeechMasterId(uuid(8111))
        self.episode_attempt_id = EpisodeAssemblyAttemptId(uuid(8112))
        self.narration_status = _narration_status(self.job_id, Lane.B)
        self.episode_status = _episode_status(self.episode_id)
        self.commands = []

        def capture(name, result):
            def handler(command):
                self.commands.append((name, command))
                return result(command) if callable(result) else result
            return handler

        self.handlers = SimpleNamespace(
            discover=lambda command: SimpleNamespace(job_ids=(self.job_id,), episode_ids=(self.episode_id,)),
            show_narration_status=lambda command: self.narration_status,
            show_episode_status=lambda command: self.episode_status,
            record_review=capture("review", lambda command: r.NarrationMutationResult(command.command_id, command.job_id, 12)),
            select_take=capture("select", lambda command: r.NarrationMutationResult(command.command_id, command.job_id, 13)),
            assemble_narration=capture("assemble-narration", lambda command: r.NarrationAssemblyResult(
                command.command_id, command.job_id, 14, self.narration_attempt_id,
                AttemptState.COMPLETED, self.master_id,
            )),
            record_narration_listening=capture("listen-narration", lambda command: r.NarrationMutationResult(
                command.command_id, command.job_id, 15,
            )),
            reconcile_narration_assembly=capture("reconcile-narration", lambda command: r.NarrationMutationResult(
                command.command_id, command.job_id, 16,
            )),
            set_intro_diary_gap=capture("gap", lambda command: r.EpisodeMutationResult(
                command.command_id, command.episode_id, 18,
            )),
            assemble_episode=capture("assemble-episode", lambda command: r.EpisodeAssemblyResult(
                command.command_id, command.episode_id, 19, self.episode_attempt_id,
                AttemptState.COMPLETED, self.episode_master_id,
            )),
            record_episode_listening=capture("listen-episode", lambda command: r.EpisodeMutationResult(
                command.command_id, command.episode_id, 20,
            )),
            reconcile_episode_assembly=capture("reconcile-episode", lambda command: r.EpisodeMutationResult(
                command.command_id, command.episode_id, 21,
            )),
        )
        self.build_app()

    def build_app(self):
        bindings = AuthoringBindings(
            "process-principal",
            lambda lane: (_ for _ in ()).throw(AssertionError("authority lookup forbidden")),
            lambda *args: (_ for _ in ()).throw(AssertionError("scope lookup forbidden")),
            lambda lane: (_ for _ in ()).throw(AssertionError("dictionary lookup forbidden")),
        )
        routes = NarrationAuthoringRoutes(self.handlers, bindings, self.identifiers, self.control)
        self.app = NarratorWebApplication(ProcessSecurity(SESSION, CSRF), dispatch=routes)

    def post(self, path, body):
        return self.app(WebRequest("POST", path, POST_HEADERS, json.dumps(body).encode("utf-8")))

    def post_raw(self, path, body):
        return self.app(WebRequest("POST", path, POST_HEADERS, body.encode("utf-8")))

    @staticmethod
    def payload(response):
        return json.loads(response.body.decode("utf-8"))

    def assert_result(self, response, keys):
        payload = self.payload(response)
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(set(payload["result"]), set(keys))
        return payload["result"]

    def test_review_selection_gap_and_listening_map_exact_decisions_text_and_revisions(self):
        review = self.assert_result(self.post(
            f"/api/v1/jobs/{self.job_id.value}/takes/{self.take_id.value}/review",
            {"expectedRevision": 11, "outcome": "accepted", "notes": "  exact notes  \n"},
        ), {"jobId", "revision"})
        selected = self.assert_result(self.post(
            f"/api/v1/jobs/{self.job_id.value}/takes/{self.take_id.value}/select",
            {"expectedRevision": 12, "passageId": self.passage_id.value, "reason": "exact reason"},
        ), {"jobId", "revision"})
        narration_listened = self.assert_result(self.post(
            f"/api/v1/jobs/{self.job_id.value}/narration-masters/{self.master_id.value}/listen",
            {"expectedRevision": 13, "outcome": "failed", "notes": "exact failure"},
        ), {"jobId", "revision"})
        gap = self.assert_result(self.post(
            f"/api/v1/episodes/{self.episode_id.value}/gap",
            {"expectedRevision": 17, "gapSamples": 0},
        ), {"episodeId", "revision"})
        episode_listened = self.assert_result(self.post(
            f"/api/v1/episodes/{self.episode_id.value}/speech-masters/{self.episode_master_id.value}/listen",
            {"expectedRevision": 18, "outcome": "passed", "notes": "exact pass"},
        ), {"episodeId", "revision"})

        self.assertEqual((review["revision"], selected["revision"], narration_listened["revision"], gap["revision"], episode_listened["revision"]),
                         (12, 13, 15, 18, 20))
        commands = {name: command for name, command in self.commands}
        self.assertEqual(
            (commands["review"].principal, commands["review"].outcome, commands["review"].notes, commands["review"].expected_revision),
            ("process-principal", ReviewOutcome.ACCEPTED, "  exact notes  \n", 11),
        )
        self.assertEqual(
            (commands["select"].principal, commands["select"].passage_id, commands["select"].reason, commands["select"].expected_revision),
            ("process-principal", self.passage_id, "exact reason", 12),
        )
        self.assertEqual(
            (commands["listen-narration"].principal, commands["listen-narration"].outcome),
            ("process-principal", ListeningOutcome.FAILED),
        )
        self.assertEqual((commands["gap"].gap_samples, commands["gap"].expected_revision), (0, 17))
        self.assertEqual(
            (commands["listen-episode"].principal, commands["listen-episode"].outcome),
            ("process-principal", ListeningOutcome.PASSED),
        )
        command_ids = [command.command_id for _, command in self.commands]
        self.assertEqual(len(set(command_ids)), len(command_ids))

    def test_exact_bodies_revisions_enums_and_bounded_text_fail_before_handlers(self):
        review_path = f"/api/v1/jobs/{self.job_id.value}/takes/{self.take_id.value}/review"
        invalid_review_bodies = (
            ({"expectedRevision": 11, "outcome": "accepted"}, 400, "invalid_json"),
            ({"expectedRevision": 11, "outcome": "accepted", "notes": "ok", "extra": 1}, 400, "invalid_json"),
            ({"expectedRevision": True, "outcome": "accepted", "notes": "ok"}, 400, "invalid_input"),
            ({"expectedRevision": 1.0, "outcome": "accepted", "notes": "ok"}, 400, "invalid_input"),
            ({"expectedRevision": "11", "outcome": "accepted", "notes": "ok"}, 400, "invalid_input"),
            ({"expectedRevision": None, "outcome": "accepted", "notes": "ok"}, 400, "invalid_input"),
            ({"expectedRevision": 0, "outcome": "accepted", "notes": "ok"}, 400, "invalid_input"),
            ({"expectedRevision": 11, "outcome": "accept", "notes": "ok"}, 400, "invalid_input"),
            ({"expectedRevision": 11, "outcome": "accepted", "notes": ""}, 400, "invalid_input"),
            ({"expectedRevision": 11, "outcome": "accepted", "notes": "e\u0301"}, 400, "invalid_input"),
            ({"expectedRevision": 11, "outcome": "accepted", "notes": "line\r\n"}, 400, "invalid_input"),
            ({"expectedRevision": 11, "outcome": "accepted", "notes": "nul\0"}, 400, "invalid_input"),
            ({"expectedRevision": 11, "outcome": "accepted", "notes": "x" * 2_001}, 400, "invalid_input"),
        )
        for body, status, code in invalid_review_bodies:
            with self.subTest(body=repr(body)[:80]):
                response = self.post(review_path, body)
                self.assertEqual((response.status, self.payload(response)["error"]["code"]), (status, code))
        duplicate = self.post_raw(
            review_path,
            '{"expectedRevision":11,"expectedRevision":12,"outcome":"accepted","notes":"ok"}',
        )
        self.assertEqual((duplicate.status, self.payload(duplicate)["error"]["code"]), (400, "invalid_json"))

        select = self.post(
            f"/api/v1/jobs/{self.job_id.value}/takes/{self.take_id.value}/select",
            {"expectedRevision": 11, "passageId": self.passage_id.value, "reason": ""},
        )
        listen = self.post(
            f"/api/v1/episodes/{self.episode_id.value}/speech-masters/{self.episode_master_id.value}/listen",
            {"expectedRevision": 17, "outcome": "pass", "notes": "ok"},
        )
        self.assertEqual((select.status, self.payload(select)["error"]["code"]), (400, "invalid_input"))
        self.assertEqual((listen.status, self.payload(listen)["error"]["code"]), (400, "invalid_input"))
        self.assertEqual(self.commands, [])

    def test_episode_gap_uses_the_same_actual_integer_allocation_boundary(self):
        path = f"/api/v1/episodes/{self.episode_id.value}/gap"
        for value, status, code in (
            (True, 400, "invalid_input"),
            (1.0, 400, "invalid_input"),
            ("1", 400, "invalid_input"),
            (None, 400, "invalid_input"),
            (-1, 400, "invalid_input"),
            (220_501, 422, "validation_failed"),
        ):
            with self.subTest(value=value):
                response = self.post(path, {"expectedRevision": 17, "gapSamples": value})
                self.assertEqual((response.status, self.payload(response)["error"]["code"]), (status, code))
        self.assertEqual(self.commands, [])

    def test_narration_and_episode_assembly_use_explicit_bounded_gaps_command_paths_and_shared_gate(self):
        narration = self.assert_result(self.post(
            f"/api/v1/jobs/{self.job_id.value}/narration-masters",
            {"expectedRevision": 11, "gapsSamples": [0]},
        ), {"jobId", "revision", "attemptId", "state", "masterId"})
        episode = self.assert_result(self.post(
            f"/api/v1/episodes/{self.episode_id.value}/speech-masters",
            {"expectedRevision": 17},
        ), {"episodeId", "revision", "attemptId", "state", "masterId"})
        self.assertEqual((narration["state"], narration["masterId"]), ("completed", self.master_id.value))
        self.assertEqual((episode["state"], episode["masterId"]), ("completed", self.episode_master_id.value))
        commands = {name: command for name, command in self.commands}
        narration_command = commands["assemble-narration"]
        episode_command = commands["assemble-episode"]
        self.assertEqual(narration_command.gaps_samples, (0,))
        self.assertEqual(
            narration_command.artifact_location.value,
            f"studio/narration-masters/{self.job_id.value}/{narration_command.command_id.value}.wav",
        )
        self.assertEqual(
            episode_command.artifact_location.value,
            f"studio/episode-masters/{self.episode_id.value}/{episode_command.command_id.value}.wav",
        )
        self.assertFalse(self.control.busy)

        before = len(self.commands)
        for gaps, status, code in (([], 422, "validation_failed"), ([220_501], 422, "validation_failed"), ([-1], 400, "invalid_input"), ([True], 400, "invalid_input"), ([1.0], 400, "invalid_input")):
            with self.subTest(gaps=gaps):
                response = self.post(
                    f"/api/v1/jobs/{self.job_id.value}/narration-masters",
                    {"expectedRevision": 11, "gapsSamples": gaps},
                )
                self.assertEqual((response.status, self.payload(response)["error"]["code"]), (status, code))
        self.assertEqual(len(self.commands), before)

        self.assertTrue(self.control.acquire())
        try:
            response = self.post(
                f"/api/v1/episodes/{self.episode_id.value}/speech-masters",
                {"expectedRevision": 17},
            )
            self.assertEqual((response.status, self.payload(response)["error"]["code"]), (409, "assembly_busy"))
        finally:
            self.control.release()

    def test_assembly_fault_mapping_and_presenter_failures_always_release_shared_gate(self):
        path = f"/api/v1/jobs/{self.job_id.value}/narration-masters"
        body = {"expectedRevision": 11, "gapsSamples": [0]}
        for error, status, code in (
            (ValidationError("stored media"), 500, "internal_error"),
            (DomainInvariantError("domain"), 422, "validation_failed"),
            (RevisionConflict(), 409, "stale_revision"),
        ):
            def fail(command, error=error):
                raise error
            self.handlers.assemble_narration = fail
            response = self.post(path, body)
            self.assertEqual((response.status, self.payload(response)["error"]["code"]), (status, code))
            self.assertFalse(self.control.busy)
        self.handlers.assemble_narration = lambda command: r.NarrationAssemblyResult(
            command.command_id, command.job_id, 12, self.narration_attempt_id,
            AttemptState.FAILED, None,
        )
        response = self.post(path, body)
        self.assertEqual((response.status, self.payload(response)["error"]["code"]), (500, "internal_error"))
        self.assertFalse(self.control.busy)

    def test_assembly_rejects_structural_impostors_before_presenting_them(self):
        for state in (AttemptState.BLOCKED, AttemptState.QUARANTINED, AttemptState.UNKNOWN):
            self.handlers.assemble_narration = lambda command, state=state: r.NarrationAssemblyResult(
                command.command_id, command.job_id, 12, self.narration_attempt_id, state, None,
            )
            response = self.post(
                f"/api/v1/jobs/{self.job_id.value}/narration-masters",
                {"expectedRevision": 11, "gapsSamples": [0]},
            )
            result = self.assert_result(response, {"jobId", "revision", "attemptId", "state", "masterId"})
            self.assertEqual((result["state"], result["masterId"]), (state.value, None))
            self.assertFalse(self.control.busy)

        for state, master_id in (
            (AttemptState.COMPLETED, None),
            (AttemptState.BLOCKED, self.master_id),
        ):
            self.handlers.assemble_narration = lambda command, state=state, master_id=master_id: r.NarrationAssemblyResult(
                command.command_id, command.job_id, 12, self.narration_attempt_id, state, master_id,
            )
            response = self.post(
                f"/api/v1/jobs/{self.job_id.value}/narration-masters",
                {"expectedRevision": 11, "gapsSamples": [0]},
            )
            self.assertEqual((response.status, self.payload(response)["error"]["code"]), (500, "internal_error"))
            self.assertFalse(self.control.busy)

        self.handlers.assemble_narration = lambda command: SimpleNamespace(
            command_id=command.command_id,
            job_id=command.job_id,
            revision=12,
            attempt_id=self.narration_attempt_id,
            state=AttemptState.COMPLETED,
            master_id=self.master_id,
        )
        response = self.post(
            f"/api/v1/jobs/{self.job_id.value}/narration-masters",
            {"expectedRevision": 11, "gapsSamples": [0]},
        )
        self.assertEqual((response.status, self.payload(response)["error"]["code"]), (500, "internal_error"))
        self.assertFalse(self.control.busy)

    def test_assembly_rejects_wrong_nominal_ids_path_values_and_enum_impostors(self):
        private_path = SafeRelativeArtifactPath("private/synthetic-output.wav")
        narration_factories = (
            lambda command: r.NarrationAssemblyResult(
                command.command_id, command.job_id, 12, private_path,
                AttemptState.COMPLETED, private_path,
            ),
            lambda command: r.NarrationAssemblyResult(
                command.command_id, command.job_id, 12, self.master_id,
                AttemptState.COMPLETED, self.narration_attempt_id,
            ),
            lambda command: r.NarrationAssemblyResult(
                command.command_id, command.job_id, 12, self.narration_attempt_id,
                SimpleNamespace(value="completed"), self.master_id,
            ),
        )
        episode_factories = (
            lambda command: r.EpisodeAssemblyResult(
                command.command_id, command.episode_id, 18, private_path,
                AttemptState.COMPLETED, private_path,
            ),
            lambda command: r.EpisodeAssemblyResult(
                command.command_id, command.episode_id, 18, self.episode_master_id,
                AttemptState.COMPLETED, self.episode_attempt_id,
            ),
            lambda command: r.EpisodeAssemblyResult(
                command.command_id, command.episode_id, 18, self.episode_attempt_id,
                SimpleNamespace(value="completed"), self.episode_master_id,
            ),
        )
        cases = (
            (
                f"/api/v1/jobs/{self.job_id.value}/narration-masters",
                {"expectedRevision": 11, "gapsSamples": [0]},
                "assemble_narration",
                narration_factories,
            ),
            (
                f"/api/v1/episodes/{self.episode_id.value}/speech-masters",
                {"expectedRevision": 17},
                "assemble_episode",
                episode_factories,
            ),
        )
        for path, body, handler_name, factories in cases:
            for index, factory in enumerate(factories):
                with self.subTest(handler=handler_name, factory=index):
                    setattr(self.handlers, handler_name, factory)
                    response = self.post(path, body)
                    self.assertEqual(response.status, 500)
                    self.assertEqual(self.payload(response)["error"]["code"], "internal_error")
                    self.assertNotIn(private_path.value.encode(), response.body)
                    self.assertFalse(self.control.busy)

    def test_assembly_gate_wraps_status_preflight_and_refuses_stale_or_unready_without_dispatch(self):
        narration_path = f"/api/v1/jobs/{self.job_id.value}/narration-masters"
        self.narration_status = _narration_status(self.job_id, Lane.B, revision=10)
        stale = self.post(narration_path, {"expectedRevision": 11, "gapsSamples": [0]})
        self.assertEqual((stale.status, self.payload(stale)["error"]["code"]), (409, "stale_revision"))
        self.assertFalse(self.control.busy)

        self.narration_status = _narration_status(self.job_id, Lane.B, ready=False)
        unready = self.post(narration_path, {"expectedRevision": 11, "gapsSamples": [0]})
        self.assertEqual((unready.status, self.payload(unready)["error"]["code"]), (422, "validation_failed"))
        self.assertFalse(self.control.busy)
        self.assertFalse(any(name == "assemble-narration" for name, _ in self.commands))

        episode_path = f"/api/v1/episodes/{self.episode_id.value}/speech-masters"
        self.assertTrue(self.control.acquire())
        original_status = self.handlers.show_episode_status
        self.handlers.show_episode_status = lambda command: (_ for _ in ()).throw(
            AssertionError("busy request reached status preflight")
        )
        try:
            busy = self.post(episode_path, {"expectedRevision": 17})
            malformed = self.post(episode_path, {"expectedRevision": "17"})
        finally:
            self.handlers.show_episode_status = original_status
            self.control.release()
        self.assertEqual((busy.status, self.payload(busy)["error"]["code"]), (409, "assembly_busy"))
        self.assertEqual((malformed.status, self.payload(malformed)["error"]["code"]), (400, "invalid_input"))

        self.handlers.assemble_episode = lambda command: SimpleNamespace(
            command_id=command.command_id,
            episode_id=command.episode_id,
            revision=18,
            attempt_id=self.episode_attempt_id,
            state=AttemptState.COMPLETED,
            master_id=self.episode_master_id,
        )
        response = self.post(
            f"/api/v1/episodes/{self.episode_id.value}/speech-masters",
            {"expectedRevision": 17},
        )
        self.assertEqual((response.status, self.payload(response)["error"]["code"]), (500, "internal_error"))
        self.assertFalse(self.control.busy)

    def test_six_inactive_attempt_states_reconcile_explicitly_and_terminal_attempts_do_not(self):
        eligible = (
            AttemptState.UNKNOWN, AttemptState.RESERVED, AttemptState.INPUT_FROZEN,
            AttemptState.EXTERNAL_WORK_STARTED, AttemptState.ARTIFACTS_STAGED,
            AttemptState.ARTIFACTS_PUBLISHED,
        )
        for index, state in enumerate(eligible):
            attempt_id = NarrationAssemblyAttemptId(uuid(8300 + index))
            self.narration_status = _narration_status(
                self.job_id, Lane.B, attempts=(SimpleNamespace(attempt_id=attempt_id, state=state),),
            )
            result = self.assert_result(self.post(
                f"/api/v1/jobs/{self.job_id.value}/narration-assembly-attempts/{attempt_id.value}/reconcile",
                {"expectedRevision": 11},
            ), {"jobId", "revision"})
            self.assertEqual(result["jobId"], self.job_id.value)
            self.assertFalse(self.control.busy)
        terminal = NarrationAssemblyAttemptId(uuid(8310))
        self.narration_status = _narration_status(
            self.job_id, Lane.B, attempts=(SimpleNamespace(attempt_id=terminal, state=AttemptState.COMPLETED),),
        )
        response = self.post(
            f"/api/v1/jobs/{self.job_id.value}/narration-assembly-attempts/{terminal.value}/reconcile",
            {"expectedRevision": 11},
        )
        self.assertEqual((response.status, self.payload(response)["error"]["code"]), (409, "reconciliation_unavailable"))

        for index, state in enumerate(eligible):
            attempt_id = EpisodeAssemblyAttemptId(uuid(8320 + index))
            self.episode_status = _episode_status(
                self.episode_id,
                attempts=(SimpleNamespace(attempt_id=attempt_id, state=state),),
            )
            episode = self.assert_result(self.post(
                f"/api/v1/episodes/{self.episode_id.value}/assembly-attempts/{attempt_id.value}/reconcile",
                {"expectedRevision": 17},
            ), {"episodeId", "revision"})
            self.assertEqual(episode["episodeId"], self.episode_id.value)
            self.assertFalse(self.control.busy)

    def test_issue_then_attach_passes_exact_returned_snapshot_and_preserves_partial_truth(self):
        fixture = episode_fixture.EpisodeApplicationTests()
        flow, episode_id, intro, diary, configured = fixture.configured()
        source_statuses = {
            intro.issuing_job_id: _narration_status(
                intro.issuing_job_id, Lane.C, revision=31,
                masters=(SimpleNamespace(master_id=intro.source_master_id, attach_ready=True),),
                intended_episode_id=episode_id,
            ),
            diary.issuing_job_id: _narration_status(
                diary.issuing_job_id, Lane.B, revision=41,
                masters=(SimpleNamespace(master_id=diary.source_master_id, attach_ready=True),),
            ),
        }
        snapshots = {intro.issuing_job_id: intro, diary.issuing_job_id: diary}
        issued_commands = []
        attach_commands = []
        durable_issues = []

        def issue(command):
            issued_commands.append(command)
            snapshot = snapshots[command.job_id]
            durable_issues.append(snapshot.snapshot_id)
            return r.SnapshotIssuedResult(command.command_id, command.job_id, command.expected_revision + 3, snapshot)

        def attach(command):
            attach_commands.append(command)
            return r.EpisodeMutationResult(command.command_id, command.episode_id, command.expected_revision + 4)

        self.handlers.discover = lambda command: SimpleNamespace(
            job_ids=tuple(source_statuses), episode_ids=(episode_id,),
        )
        self.handlers.show_narration_status = lambda command: source_statuses[command.job_id]
        self.handlers.show_episode_status = lambda command: _episode_status(
            episode_id, revision=configured.revision,
        )
        self.handlers.issue_narration_snapshot = issue
        self.handlers.attach_intro = attach
        self.handlers.attach_diary = attach
        self.build_app()

        self.handlers.discover = lambda command: SimpleNamespace(job_ids=(), episode_ids=(episode_id,))
        response = self.post(
            f"/api/v1/jobs/{intro.issuing_job_id.value}/narration-masters/{intro.source_master_id.value}/attach/intro",
            {"sourceExpectedRevision": 31, "episodeId": episode_id.value,
             "episodeExpectedRevision": configured.revision},
        )
        self.assertEqual((response.status, self.payload(response)["error"]["code"]), (404, "not_found"))
        self.assertEqual(issued_commands, [])
        self.handlers.discover = lambda command: SimpleNamespace(
            job_ids=tuple(source_statuses), episode_ids=(episode_id,),
        )

        correct_intro_status = source_statuses[intro.issuing_job_id]
        source_statuses[intro.issuing_job_id] = _narration_status(
            intro.issuing_job_id,
            Lane.C,
            revision=31,
            masters=(SimpleNamespace(master_id=intro.source_master_id, attach_ready=True),),
            intended_episode_id=DiaryEpisodeId(uuid(8490)),
        )
        response = self.post(
            f"/api/v1/jobs/{intro.issuing_job_id.value}/narration-masters/{intro.source_master_id.value}/attach/intro",
            {"sourceExpectedRevision": 31, "episodeId": episode_id.value,
             "episodeExpectedRevision": configured.revision},
        )
        self.assertEqual(response.status, 422)
        self.assertEqual(self.payload(response)["error"]["code"], "validation_failed")
        self.assertEqual(issued_commands, [])
        source_statuses[intro.issuing_job_id] = correct_intro_status

        for role, snapshot, source_revision in (("intro", intro, 31), ("diary", diary, 41)):
            response = self.post(
                f"/api/v1/jobs/{snapshot.issuing_job_id.value}/narration-masters/{snapshot.source_master_id.value}/attach/{role}",
                {"sourceExpectedRevision": source_revision, "episodeId": episode_id.value,
                 "episodeExpectedRevision": configured.revision},
            )
            result = self.assert_result(response, {
                "jobId", "sourceRevision", "episodeId", "episodeRevision", "masterId", "role",
            })
            self.assertEqual((result["sourceRevision"], result["episodeRevision"], result["role"]),
                             (source_revision + 3, configured.revision + 4, role))
            self.assertIs(attach_commands[-1].snapshot, snapshots[snapshot.issuing_job_id])
            self.assertNotEqual(issued_commands[-1].command_id, attach_commands[-1].command_id)

        before = len(durable_issues)
        def conflict(command):
            attach_commands.append(command)
            raise RevisionConflict()
        self.handlers.attach_diary = conflict
        response = self.post(
            f"/api/v1/jobs/{diary.issuing_job_id.value}/narration-masters/{diary.source_master_id.value}/attach/diary",
            {"sourceExpectedRevision": 41, "episodeId": episode_id.value,
             "episodeExpectedRevision": configured.revision},
        )
        self.assertEqual((response.status, self.payload(response)["error"]["code"]), (409, "stale_revision"))
        self.assertEqual(len(durable_issues), before + 1)


class WebMasteringPresenterTests(unittest.TestCase):
    def setUp(self):
        fixture = status_fixture.ApplicationStatusProjectionTests()
        _, _, self.narration, self.episode = fixture._projections()

    def test_status_presenters_expose_only_review_mastering_and_recovery_facts(self):
        narration = presenters.narration_status(self.narration, busy=False)
        self.assertEqual(set(narration), {
            "jobId", "revision", "lane", "assemblyReady", "passages", "masters", "assemblyAttempts",
        })
        self.assertEqual(set(narration["passages"][0]), {
            "passageId", "order", "currentTextRevision", "selectedTakeId", "readyForAssembly", "takes",
        })
        self.assertEqual(set(narration["passages"][0]["takes"][0]), {
            "takeId", "attemptId", "textRevision", "eligible", "ineligibilityReasons",
            "latestOperationalReview", "selected", "audioUrl",
        })
        self.assertEqual(set(narration["masters"][0]), {
            "masterId", "selectedTakeCount", "current", "attachReady", "latestListening",
            "issuedSnapshotCount", "audioUrl",
        })
        self.assertEqual(set(narration["assemblyAttempts"][0]), {
            "attemptId", "state", "terminal", "needsReconciliation", "selectedTakeCount",
            "outputReady", "reconciliationAvailable",
        })

        episode = presenters.episode(self.episode, busy=False)
        self.assertEqual(set(episode), {
            "episodeId", "revision", "status", "assemblyReady", "gapSamples", "gapConfigured",
            "components", "masters", "assemblyAttempts",
        })
        self.assertEqual([component["role"] for component in episode["components"]], ["intro", "diary"])
        self.assertEqual(set(episode["components"][0]), {
            "role", "attached", "sourceJobId", "sourceMasterId", "attachedRevision",
            "passageCount", "sourceCurrent", "eligibleOperations", "sourceAuthority",
        })
        self.assertEqual(set(episode["components"][0]["sourceAuthority"]), {
            "status", "active", "coveredOperations",
        })
        self.assertEqual(set(episode["masters"][0]), {
            "masterId", "componentCount", "current", "gapConfigured", "latestListening", "audioUrl",
        })
        self.assertEqual(set(episode["assemblyAttempts"][0]), {
            "attemptId", "state", "terminal", "needsReconciliation", "componentCount",
            "gapConfigured", "outputReady", "reconciliationAvailable",
        })
        redacted = repr((narration, episode))
        for forbidden in (
            "latestQualifiedReview", "recordId", "deliveryReady", "timing", "sourceTiming",
            "relativeLocation", "snapshot", "notes", "provider",
        ):
            self.assertNotIn(forbidden, redacted)

        zero = presenters.episode(
            SimpleNamespace(**{
                name: (0 if name == "gap_samples" else getattr(self.episode, name))
                for name in self.episode.__dataclass_fields__
            }),
            busy=False,
        )
        self.assertEqual((zero["gapSamples"], zero["gapConfigured"]), (0, True))

    def test_page_and_javascript_offer_explicit_forms_without_private_or_retry_state(self):
        narration = presenters.narration_status(self.narration, busy=False)
        narration["passages"][0]["selectedTakeId"] = None
        narration["passages"][0]["takes"][0]["selected"] = False
        episode = presenters.episode(self.episode, busy=False)
        editor = {
            "jobId": narration["jobId"], "revision": narration["revision"], "lane": narration["lane"],
            "defaults": {"speed": "1.00", "volume": "1.00", "emotion": None, "dictionaryConfigured": False},
            "passages": [],
        }
        generation = {"jobId": narration["jobId"], "revision": narration["revision"], "attempts": []}
        markup = presenters.page(
            CSRF,
            {"healthy": True, "checkedFileCount": 0, "issueCodes": []},
            episode,
            [],
            [(editor, generation, narration)],
        ).decode("utf-8")
        for kind in (
            "review", "select", "narration-assembly", "narration-listen", "attach",
            "episode-gap", "episode-assembly", "episode-listen",
        ):
            self.assertIn(f'data-kind="{kind}"', markup)
        self.assertIn(narration["masters"][0]["audioUrl"], markup)
        self.assertIn(episode["masters"][0]["audioUrl"], markup)
        for forbidden in ("qualified", "recordId", "deliveryReady", "sourceTiming", "snapshotId", "snapshotDigest"):
            self.assertNotIn(forbidden, markup)

        from importlib.resources import files
        script = files("heritage_archive.contexts.narrator_voice.infrastructure.loopback_web").joinpath(
            "assets", "studio.js",
        ).read_text("utf-8")
        self.assertIn(
            "A source snapshot may have been issued even though attachment did not complete. "
            "Reload and inspect both source and episode state before retrying.",
            script,
        )
        for kind in (
            "review", "select", "narration-assembly", "narration-listen", "attach",
            "narration-reconcile", "episode-gap", "episode-assembly", "episode-listen",
            "episode-reconcile",
        ):
            self.assertIn(f'case "{kind}":', script)
        self.assertNotIn(".trim(", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertEqual(script.count("fetch("), 1)

    def test_javascript_builds_exact_task_8_bodies_and_never_retries_failed_or_lost_attach(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for packaged studio behavior checks")
        asset = (
            Path(__file__).resolve().parents[3]
            / "src" / "heritage_archive" / "contexts" / "narrator_voice"
            / "infrastructure" / "loopback_web" / "assets" / "studio.js"
        )
        script = r'''
const asset = process.argv[1];
const message = {textContent: ""};
const makeForm = (kind, values) => {
  const button = {disabled: false};
  return {dataset: {kind}, button, listener: null,
    elements: {namedItem(name) { if (!(name in values)) throw new Error(`missing ${kind}.${name}`); return {value: values[name]}; }},
    querySelectorAll() { return [button]; },
    addEventListener(type, listener) { if (type === "submit") this.listener = listener; },
    getAttribute() { return `/${kind}`; }};
};
const forms = [
  makeForm("review", {expectedRevision: "1", outcome: "rejected", notes: " exact\r\nnotes "}),
  makeForm("select", {expectedRevision: "2", passageId: "passage", reason: " reason "}),
  makeForm("narration-assembly", {expectedRevision: "3", gapsSamples: "0\r\n220500"}),
  makeForm("narration-listen", {expectedRevision: "4", outcome: "passed", notes: "heard"}),
  makeForm("attach", {sourceExpectedRevision: "5", episodeId: "episode", episodeExpectedRevision: "6"}),
  makeForm("narration-reconcile", {expectedRevision: "7"}),
  makeForm("episode-gap", {expectedRevision: "8", gapSamples: "0"}),
  makeForm("episode-assembly", {expectedRevision: "9"}),
  makeForm("episode-listen", {expectedRevision: "10", outcome: "failed", notes: "noise"}),
  makeForm("episode-reconcile", {expectedRevision: "11"})
];
global.performance = {getEntriesByType() { return []; }};
global.window = {location: {reload() { throw new Error("failed mutations must not reload"); }}};
global.document = {
  body: {hasAttribute() { return false; }},
  getElementById() { return message; },
  querySelector() { return {content: "csrf"}; },
  querySelectorAll() { return forms; }
};
const calls = [];
let lose = false;
global.fetch = async (url, options) => {
  calls.push({url, body: JSON.parse(options.body)});
  if (lose) throw new Error("lost");
  return {ok: false, json: async () => ({ok: false, error: {code: "stale_revision"}})};
};
require(asset);
(async () => {
  let failedGuidance = "";
  for (const form of forms) {
    await form.listener({preventDefault() {}});
    if (form.dataset.kind === "attach") failedGuidance = message.textContent;
  }
  lose = true;
  await forms[4].listener({preventDefault() {}});
  process.stdout.write(JSON.stringify({calls, failedGuidance, lostGuidance: message.textContent,
    attachDisabled: forms[4].button.disabled}));
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
'''
        completed = subprocess.run(
            [node, "-e", script, str(asset)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertEqual([call["body"] for call in value["calls"][:10]], [
            {"expectedRevision": 1, "outcome": "rejected", "notes": " exact\nnotes "},
            {"expectedRevision": 2, "passageId": "passage", "reason": " reason "},
            {"expectedRevision": 3, "gapsSamples": [0, 220_500]},
            {"expectedRevision": 4, "outcome": "passed", "notes": "heard"},
            {"sourceExpectedRevision": 5, "episodeId": "episode", "episodeExpectedRevision": 6},
            {"expectedRevision": 7},
            {"expectedRevision": 8, "gapSamples": 0},
            {"expectedRevision": 9},
            {"expectedRevision": 10, "outcome": "failed", "notes": "noise"},
            {"expectedRevision": 11},
        ])
        self.assertEqual(len(value["calls"]), 11)
        guidance = (
            "A source snapshot may have been issued even though attachment did not complete. "
            "Reload and inspect both source and episode state before retrying."
        )
        self.assertIn(guidance, value["failedGuidance"])
        self.assertIn(guidance, value["lostGuidance"])
        self.assertFalse(value["attachDisabled"])


if __name__ == "__main__":
    unittest.main()
