"""Confirmed fixture-only web generation and recovery boundaries."""

from __future__ import annotations

from itertools import count
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Barrier, Thread
from concurrent.futures import ThreadPoolExecutor
from secrets import compare_digest as secure_compare_digest
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.application import commands as c
from heritage_archive.contexts.narrator_voice.application.results import (
    GenerationEstimateResult,
    GenerationRunResult,
    NarrationMutationResult,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import AttemptState, SubmissionEvidence
from heritage_archive.contexts.narrator_voice.domain.errors import RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import (
    CommandId,
    GenerationAttemptId,
    NarrationJobId,
    PassageId,
    TakeId,
)
from heritage_archive.contexts.narrator_voice.domain.values import Lane, PassageText
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web import presenters
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.generation import (
    ConfirmationCapacityReached,
    ConfirmationTokenCreationFailed,
    ConfirmationUnavailable,
    ProcessGenerationControl,
)
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import AuthoringBindings, NarrationAuthoringRoutes
from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.security import ProcessSecurity
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_failures import FilesystemOperationalFailure
from heritage_archive.platform.web import WebRequest
from tests.heritage_archive.narrator_voice.fixtures import (
    make_contract,
    make_dictionary,
    make_preview,
    make_recipe,
    uuid,
)
from tests.heritage_archive.narrator_voice.test_web_security import CSRF, POST_HEADERS


SESSION = "a" * 64


class Monotonic:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def estimate(index: int = 100, *, revision: int = 4) -> GenerationEstimateResult:
    job_id = NarrationJobId(uuid(index))
    passage_id = PassageId(uuid(index + 1))
    text = PassageText(f"fixture estimate {index}")
    recipe = make_recipe(text, recipe_index=index + 2)
    preview = make_preview(
        job_id=job_id,
        base_revision=revision - 1,
        passage_id=passage_id,
        text=text,
        recipe=recipe,
        contract=make_contract(),
        preview_index=index + 3,
    )
    return GenerationEstimateResult(CommandId(uuid(index + 4)), job_id, revision, preview)


class ProcessGenerationControlTests(unittest.TestCase):
    def test_issue_returns_256_bit_lowercase_hex_and_consumes_exact_trusted_binding_once(self):
        clock = Monotonic()
        result = estimate()
        token = "01" * 32
        control = ProcessGenerationControl(SESSION, monotonic=clock, token_factory=lambda: token)

        issued = control.issue(result)
        binding = control.consume(issued, result.job_id)

        self.assertEqual(issued, token)
        self.assertRegex(issued, r"^[0-9a-f]{64}$")
        self.assertEqual(
            (binding.job_id, binding.preview_id, binding.expected_revision,
             binding.preview_digest, binding.estimated_usage),
            (result.job_id, result.preview.preview_id, result.revision,
             result.preview.preview_digest, result.preview.estimated_usage),
        )
        with self.assertRaises(ConfirmationUnavailable):
            control.consume(issued, result.job_id)
        self.assertNotIn(SESSION, repr(control))
        self.assertNotIn(token, repr(binding))

    def test_expiry_is_monotonic_at_exact_600_second_boundary_and_pruned_before_capacity(self):
        clock = Monotonic()
        tokens = (f"{value:064x}" for value in count(1))
        control = ProcessGenerationControl(SESSION, monotonic=clock, token_factory=lambda: next(tokens))
        first = estimate(110)
        first_token = control.issue(first)

        for index in range(127):
            control.issue(estimate(300 + index * 10))

        clock.value = 699.999
        with self.assertRaises(ConfirmationCapacityReached):
            control.issue(estimate(120))
        clock.value = 700.0
        second = estimate(130)
        second_token = control.issue(second)

        with self.assertRaises(ConfirmationUnavailable):
            control.consume(first_token, first.job_id)
        self.assertEqual(control.consume(second_token, second.job_id).job_id, second.job_id)

    def test_wrong_job_and_tampered_token_preserve_the_valid_confirmation(self):
        result = estimate(140)
        token = "ab" * 32
        control = ProcessGenerationControl(SESSION, token_factory=lambda: token)
        control.issue(result)

        with patch(
            "heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.generation.compare_digest",
            wraps=secure_compare_digest,
        ) as compare:
            for candidate, job_id in (("ac" * 32, result.job_id), (token, estimate(150).job_id)):
                with self.subTest(candidate=candidate, job_id=job_id), self.assertRaises(ConfirmationUnavailable):
                    control.consume(candidate, job_id)

        compared_pairs = tuple(call.args for call in compare.call_args_list)
        self.assertIn(("ac" * 32, token), compared_pairs)
        self.assertIn((SESSION, SESSION), compared_pairs)

        self.assertEqual(control.consume(token, result.job_id).expected_revision, result.revision)

    def test_restart_and_foreign_session_invalidate_without_removing_the_owner_record(self):
        result = estimate(160)
        token = "cd" * 32
        owner = ProcessGenerationControl(SESSION, token_factory=lambda: token)
        owner.issue(result)
        restarted = ProcessGenerationControl("b" * 64, token_factory=lambda: "ef" * 32)

        with self.assertRaises(ConfirmationUnavailable):
            restarted.consume(token, result.job_id)
        with self.assertRaises(ConfirmationUnavailable):
            owner._consume_for_session(token, "b" * 64, result.job_id)
        self.assertEqual(owner.consume(token, result.job_id).job_id, result.job_id)

    def test_live_capacity_never_evicts_and_collision_retry_is_bounded(self):
        first = estimate(180)
        values = iter(f"{value:064x}" for value in range(1, 130))
        control = ProcessGenerationControl(SESSION, token_factory=lambda: next(values))
        token = control.issue(first)
        for index in range(127):
            control.issue(estimate(2000 + index * 10))
        with self.assertRaises(ConfirmationCapacityReached):
            control.issue(estimate(190))
        self.assertEqual(control.consume(token, first.job_id).job_id, first.job_id)

        collision_calls = 0
        def same_token():
            nonlocal collision_calls
            collision_calls += 1
            return "22" * 32
        colliding = ProcessGenerationControl(SESSION, token_factory=same_token)
        colliding.issue(estimate(200))
        with self.assertRaises(ConfirmationTokenCreationFailed):
            colliding.issue(estimate(210))
        self.assertLess(collision_calls, 20)

    def test_atomic_concurrent_consume_has_exactly_one_winner(self):
        result = estimate(220)
        token = "33" * 32
        control = ProcessGenerationControl(SESSION, token_factory=lambda: token)
        control.issue(result)
        barrier = Barrier(3)
        outcomes: list[str] = []

        def consume() -> None:
            barrier.wait()
            try:
                control.consume(token, result.job_id)
            except ConfirmationUnavailable:
                outcomes.append("unavailable")
            else:
                outcomes.append("consumed")

        threads = [Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(5)

        self.assertEqual(sorted(outcomes), ["consumed", "unavailable"])

    def test_shared_gate_is_nonblocking_and_independent_from_confirmation_storage(self):
        result = estimate(240)
        token = "44" * 32
        control = ProcessGenerationControl(SESSION, token_factory=lambda: token)
        control.issue(result)

        self.assertTrue(control.acquire())
        self.assertTrue(control.busy)
        self.assertFalse(control.acquire())
        control.release()
        self.assertFalse(control.busy)
        self.assertEqual(control.consume(token, result.job_id).job_id, result.job_id)


class _Identifiers:
    def __init__(self) -> None:
        self._values = count(6000)

    def new_id(self, kind):
        return kind(uuid(next(self._values)))


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def replace_status(status, attempt_id, state):
    return SimpleNamespace(
        job_id=status.job_id,
        revision=9,
        generation_attempts=(SimpleNamespace(attempt_id=attempt_id, state=state),),
    )


class WebGenerationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        original_get = os.environ.get
        def guarded_get(key, default=None):
            if key == "CARTESIA_API_KEY":
                raise AssertionError("credential read forbidden")
            return original_get(key, default)
        self.enterContext(patch.object(os.environ, "get", side_effect=guarded_get))
        for target in (
            "socket.getaddrinfo", "socket.socket.connect", "socket.socket.connect_ex",
            "socket.socket.bind", "httpx.Client.send",
        ):
            self.enterContext(patch(target, side_effect=AssertionError("network forbidden")))
        self.ids = _Identifiers()
        self.clock = Monotonic()
        self.result = estimate(500)
        self.token = "55" * 32
        self.tokens = iter((self.token, "56" * 32, "57" * 32, "58" * 32))
        self.control = ProcessGenerationControl(
            SESSION, monotonic=self.clock, token_factory=lambda: next(self.tokens),
        )
        passage = SimpleNamespace(
            passage_id=self.result.preview.passage_id,
            recipes=(SimpleNamespace(recipe_id=self.result.preview.recipe_id, current=True, required=True),),
        )
        editor = SimpleNamespace(
            job_id=self.result.job_id,
            revision=self.result.preview.base_job_revision,
            lane=Lane.B,
            passages=(passage,),
        )
        self.estimate_commands = []
        self.generate_commands = []
        self.reconcile_commands = []
        self.status = SimpleNamespace(
            job_id=self.result.job_id,
            revision=9,
            generation_attempts=(),
        )

        def estimate_handler(command):
            self.estimate_commands.append(command)
            return self.result

        def generate_handler(command):
            self.generate_commands.append(command)
            return GenerationRunResult(
                command.command_id,
                command.job_id,
                9,
                GenerationAttemptId(uuid(560)),
                AttemptState.COMPLETED,
                TakeId(uuid(561)),
                "settled",
            )

        self.handlers = SimpleNamespace(
            discover=lambda command: SimpleNamespace(job_ids=(self.result.job_id,), episode_ids=()),
            show_editor=lambda command: editor,
            estimate=estimate_handler,
            generate=generate_handler,
            show_narration_status=lambda command: self.status,
            reconcile_generation=lambda command: self._reconcile(command),
        )
        self._build_app(self.handlers, self.control)

    def _reconcile(self, command):
        self.reconcile_commands.append(command)
        return NarrationMutationResult(command.command_id, command.job_id, self.status.revision + 1)

    def _build_app(self, handlers, control):
        bindings = AuthoringBindings(
            "fixture-principal",
            lambda lane: (_ for _ in ()).throw(AssertionError("authority lookup forbidden")),
            lambda *args: (_ for _ in ()).throw(AssertionError("scope lookup forbidden")),
            lambda lane: make_dictionary("lane-b") if lane is Lane.B else None,
        )
        routes = NarrationAuthoringRoutes(handlers, bindings, self.ids, control)
        self.app = NarratorWebApplication(
            ProcessSecurity(SESSION, CSRF), dispatch=routes, render_root=routes.render_root
        )

    def post(self, path: str, body: dict[str, object]):
        return self.app(WebRequest("POST", path, POST_HEADERS, json.dumps(body).encode("utf-8")))

    def test_estimate_maps_exact_overrides_and_generate_uses_post_estimate_revision_and_server_path(self):
        estimate_response = self.post(
            f"/api/v1/jobs/{self.result.job_id.value}/estimate",
            {
                "expectedRevision": self.result.preview.base_job_revision,
                "passageId": self.result.preview.passage_id.value,
                "recipeId": self.result.preview.recipe_id.value,
                "speedMode": "set",
                "speed": "1.10",
                "volumeMode": "inherit",
                "volume": None,
                "emotionMode": "omit",
                "emotion": None,
                "dictionaryMode": "set",
            },
        )
        self.assertEqual(estimate_response.status, 200, estimate_response.body)
        presented = _json(estimate_response)["result"]
        self.assertEqual(
            set(presented),
            {
                "jobId", "revision", "previewId", "baseJobRevision", "passageId", "recipeId",
                "canonicalProjection", "billableCharacters", "estimatedUsage", "issuedAt",
                "confirmationToken",
            },
        )
        self.assertEqual(
            (presented["canonicalProjection"], presented["billableCharacters"], presented["estimatedUsage"]),
            (self.result.preview.canonical_projection, self.result.preview.billable_characters,
             self.result.preview.estimated_usage),
        )
        command = self.estimate_commands[0]
        self.assertEqual(
            (
                command.settings_intent.speed.mode,
                command.settings_intent.speed.value,
                command.settings_intent.volume.mode,
                command.settings_intent.volume.value,
                command.settings_intent.emotion.mode,
                command.settings_intent.emotion.value,
                command.settings_intent.dictionary.mode,
                command.settings_intent.dictionary.value,
            ),
            (
                c.OverrideMode.SET,
                "1.10",
                c.OverrideMode.INHERIT,
                None,
                c.OverrideMode.OMIT,
                None,
                c.OverrideMode.SET,
                make_dictionary("lane-b"),
            ),
        )

        generate_response = self.post(
            f"/api/v1/jobs/{self.result.job_id.value}/generate",
            {"confirmationToken": presented["confirmationToken"]},
        )
        self.assertEqual(generate_response.status, 200, generate_response.body)
        generated = _json(generate_response)["result"]
        self.assertEqual(
            set(generated),
            {"jobId", "revision", "attemptId", "state", "takeId", "budgetDisposition"},
        )
        generate_command = self.generate_commands[0]
        self.assertEqual(generate_command.expected_revision, self.result.revision)
        self.assertNotEqual(generate_command.expected_revision, self.result.preview.base_job_revision)
        self.assertEqual(generate_command.preview_id, self.result.preview.preview_id)
        self.assertEqual(
            generate_command.artifact_location.value,
            f"studio/takes/{self.result.job_id.value}/{generate_command.command_id.value}.wav",
        )

    def test_confirmation_is_one_shot_and_generate_body_has_no_client_authority_fields(self):
        self.control.issue(self.result)
        path = f"/api/v1/jobs/{self.result.job_id.value}/generate"
        first = self.post(path, {"confirmationToken": self.token})
        second = self.post(path, {"confirmationToken": self.token})
        extra = self.post(path, {"confirmationToken": self.token, "expectedRevision": 4})

        self.assertEqual((first.status, second.status, extra.status), (200, 409, 400))
        self.assertEqual(_json(second)["error"]["code"], "confirmation_unavailable")
        self.assertEqual(_json(extra)["error"]["code"], "invalid_json")
        self.assertEqual(len(self.generate_commands), 1)

    def test_busy_refusal_is_responsive_and_preserves_a_distinct_confirmation(self):
        second_token = self.control.issue(self.result)
        first_token = self.control.issue(self.result)
        entered = Barrier(2)
        release = Barrier(2)
        calls = 0

        def held(command):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.wait(timeout=5)
                release.wait(timeout=5)
            return GenerationRunResult(command.command_id, command.job_id, 9,
                GenerationAttemptId(uuid(570 + calls)), AttemptState.BLOCKED, None, "released")

        self.handlers.generate = held
        path = f"/api/v1/jobs/{self.result.job_id.value}/generate"
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.post, path, {"confirmationToken": first_token})
            entered.wait(timeout=5)
            busy = self.post(path, {"confirmationToken": second_token})
            self.assertEqual((busy.status, _json(busy)["error"]["code"]), (409, "generation_busy"))
            self.assertFalse(first.done())
            release.wait(timeout=5)
            self.assertEqual(first.result(timeout=5).status, 200)

        retry = self.post(path, {"confirmationToken": second_token})
        self.assertEqual(retry.status, 200, retry.body)
        self.assertEqual(calls, 2)

    def test_stale_and_trusted_validation_faults_consume_once_and_release_the_gate(self):
        path = f"/api/v1/jobs/{self.result.job_id.value}/generate"
        for error, code in ((RevisionConflict(), "stale_revision"),
                            (ValidationError("private handler validation"), "internal_error"),
                            (FilesystemOperationalFailure("private storage"), "internal_error")):
            with self.subTest(error=type(error).__name__):
                token = self.control.issue(self.result)
                before = len(self.generate_commands)
                def fail(command, error=error):
                    self.generate_commands.append(command)
                    raise error
                self.handlers.generate = fail
                response = self.post(path, {"confirmationToken": token})
                self.assertEqual((_json(response)["error"]["code"], self.control.busy), (code, False))
                consumed = self.post(path, {"confirmationToken": token})
                self.assertEqual((consumed.status, _json(consumed)["error"]["code"]), (409, "confirmation_unavailable"))
                self.assertEqual(len(self.generate_commands), before + 1)

    def test_real_generation_handler_and_fake_gateway_surface_truthful_route_outcomes_once(self):
        from tests.heritage_archive.narrator_voice.test_application_generation import (
            GenerationApplicationTests,
        )

        outcomes = (
            ("success", AttemptState.COMPLETED, "settled"),
            ("failed", AttemptState.FAILED, "held"),
            ("ambiguous", AttemptState.UNKNOWN, "held"),
        )
        for offset, (mode, expected_state, expected_disposition) in enumerate(outcomes):
            with self.subTest(mode=mode):
                actual = GenerationApplicationTests(
                    "test_success_reserves_before_external_freezes_exact_preview_bytes_and_settles_usage"
                )
                actual.setUp()
                actual.gateway.mode = mode
                trusted_estimate = GenerationEstimateResult(
                    CommandId(uuid(590 + offset)), actual.job_id, 4, actual.preview,
                )
                confirmation = ProcessGenerationControl(
                    SESSION,
                    monotonic=self.clock,
                    token_factory=lambda offset=offset: f"{90 + offset:064x}",
                )
                token = confirmation.issue(trusted_estimate)
                handlers = SimpleNamespace(
                    discover=lambda command: SimpleNamespace(job_ids=(actual.job_id,), episode_ids=()),
                    show_editor=lambda command: (_ for _ in ()).throw(AssertionError("editor lookup forbidden")),
                    estimate=lambda command: (_ for _ in ()).throw(AssertionError("estimate replay forbidden")),
                    generate=actual.handler(),
                    show_narration_status=lambda command: (_ for _ in ()).throw(AssertionError("status lookup forbidden")),
                    reconcile_generation=lambda command: (_ for _ in ()).throw(AssertionError("reconcile forbidden")),
                )
                self._build_app(handlers, confirmation)

                response = self.post(
                    f"/api/v1/jobs/{actual.job_id.value}/generate",
                    {"confirmationToken": token},
                )
                value = _json(response)["result"]

                self.assertEqual(response.status, 200, response.body)
                self.assertEqual((value["state"], value["budgetDisposition"]),
                                 (expected_state.value, expected_disposition))
                self.assertEqual(len(actual.gateway.calls), 1)
                repeated = self.post(
                    f"/api/v1/jobs/{actual.job_id.value}/generate",
                    {"confirmationToken": token},
                )
                self.assertEqual(
                    (repeated.status, _json(repeated)["error"]["code"], len(actual.gateway.calls)),
                    (409, "confirmation_unavailable", 1),
                )

    def test_estimate_domain_validation_stays_422_and_capacity_is_after_handler_persistence(self):
        body = {
            "expectedRevision": self.result.preview.base_job_revision,
            "passageId": self.result.preview.passage_id.value,
            "recipeId": self.result.preview.recipe_id.value,
            "speedMode": "inherit", "speed": None,
            "volumeMode": "inherit", "volume": None,
            "emotionMode": "omit", "emotion": None,
            "dictionaryMode": "omit",
        }
        original = self.handlers.estimate
        self.handlers.estimate = lambda command: (_ for _ in ()).throw(ValidationError("valid domain refusal"))
        refused = self.post(f"/api/v1/jobs/{self.result.job_id.value}/estimate", body)
        self.assertEqual((refused.status, _json(refused)["error"]["code"]), (422, "validation_failed"))

        tokens = (f"{value:064x}" for value in count(1))
        full = ProcessGenerationControl(
            SESSION, monotonic=self.clock, token_factory=lambda: next(tokens),
        )
        for index in range(128):
            full.issue(estimate(1000 + index * 10))
        self.handlers.estimate = original
        self._build_app(self.handlers, full)
        before = len(self.estimate_commands)
        capacity = self.post(f"/api/v1/jobs/{self.result.job_id.value}/estimate", body)
        self.assertEqual((capacity.status, _json(capacity)["error"]["code"]), (409, "confirmation_capacity"))
        self.assertEqual(len(self.estimate_commands), before + 1)

    def test_reconcile_uses_current_revision_exact_eligibility_and_shared_gate_without_get_mutation(self):
        attempt_id = GenerationAttemptId(uuid(580))
        path = f"/api/v1/jobs/{self.result.job_id.value}/generation-attempts/{attempt_id.value}/reconcile"
        for state in (
            AttemptState.UNKNOWN, AttemptState.RESERVED, AttemptState.INPUT_FROZEN,
            AttemptState.EXTERNAL_WORK_STARTED, AttemptState.ARTIFACTS_STAGED,
            AttemptState.ARTIFACTS_PUBLISHED,
        ):
            with self.subTest(state=state):
                self.status = replace_status(self.status, attempt_id, state)
                response = self.post(path, {"expectedRevision": self.status.revision})
                self.assertEqual(response.status, 200, response.body)
                self.assertEqual(self.reconcile_commands[-1].expected_revision, self.status.revision)

        for attempts, expected_code in (
            ((), "not_found"),
            ((SimpleNamespace(attempt_id=attempt_id, state=AttemptState.COMPLETED),), "reconciliation_unavailable"),
        ):
            self.status = SimpleNamespace(job_id=self.result.job_id, revision=9, generation_attempts=attempts)
            response = self.post(path, {"expectedRevision": 9})
            self.assertEqual(_json(response)["error"]["code"], expected_code)

        self.status = replace_status(self.status, attempt_id, AttemptState.UNKNOWN)
        stale = self.post(path, {"expectedRevision": 8})
        self.assertEqual(_json(stale)["error"]["code"], "stale_revision")

        original_reconcile = self.handlers.reconcile_generation
        for error in (
            ValidationError("private reconciliation validation"),
            FilesystemOperationalFailure("private reconciliation storage"),
        ):
            with self.subTest(fault=type(error).__name__):
                self.handlers.reconcile_generation = (
                    lambda command, error=error: (_ for _ in ()).throw(error)
                )
                fault = self.post(path, {"expectedRevision": 9})
                self.assertEqual(
                    (fault.status, _json(fault)["error"]["code"], self.control.busy),
                    (500, "internal_error", False),
                )
        self.handlers.reconcile_generation = original_reconcile

        before = len(self.reconcile_commands)
        self.assertTrue(self.control.acquire())
        try:
            busy = self.post(path, {"expectedRevision": 9})
        finally:
            self.control.release()
        self.assertEqual(_json(busy)["error"]["code"], "generation_busy")
        get = self.app(WebRequest("GET", path, POST_HEADERS[:1] + (POST_HEADERS[3],)))
        self.assertEqual(get.status, 404)
        self.assertEqual(len(self.reconcile_commands), before)


class WebGenerationPresenterTests(unittest.TestCase):
    def test_generation_result_and_status_use_exact_truthful_allowlists(self):
        job_id = NarrationJobId(uuid(700))
        attempt_id = GenerationAttemptId(uuid(701))
        for state, disposition in (
            (AttemptState.COMPLETED, "settled"),
            (AttemptState.BLOCKED, "released"),
            (AttemptState.FAILED, "held"),
            (AttemptState.UNKNOWN, "unknown"),
            (AttemptState.QUARANTINED, "denied"),
        ):
            with self.subTest(state=state):
                result = GenerationRunResult(
                    CommandId(uuid(702)), job_id, 8, attempt_id, state,
                    TakeId(uuid(703)) if state is AttemptState.COMPLETED else None,
                    disposition,
                )
                value = presenters.generation_run(result)
                self.assertEqual(set(value), {"jobId", "revision", "attemptId", "state", "takeId", "budgetDisposition"})
                self.assertEqual((value["state"], value["budgetDisposition"]), (state.value, disposition))

        status = SimpleNamespace(
            job_id=job_id,
            revision=8,
            generation_attempts=(SimpleNamespace(
                attempt_id=attempt_id,
                passage_id=PassageId(uuid(704)),
                state=AttemptState.UNKNOWN,
                submission=SubmissionEvidence.AMBIGUOUS,
                terminal=True,
                needs_reconciliation=True,
                output_ready=False,
            ),),
        )
        value = presenters.generation_status(status, busy=False)
        self.assertEqual(set(value), {"jobId", "revision", "attempts"})
        self.assertEqual(
            set(value["attempts"][0]),
            {"attemptId", "passageId", "state", "submission", "terminal", "needsReconciliation", "outputReady", "reconciliationAvailable"},
        )
        self.assertTrue(value["attempts"][0]["reconciliationAvailable"])
        self.assertFalse(presenters.generation_status(status, busy=True)["attempts"][0]["reconciliationAvailable"])

        impossible = GenerationRunResult(
            CommandId(uuid(705)), job_id, 8, attempt_id, AttemptState.UNKNOWN,
            TakeId(uuid(706)), "held",
        )
        with self.assertRaises(ValueError):
            presenters.generation_run(impossible)

    def test_page_offers_estimate_ephemeral_generate_and_explicit_recovery_without_private_fields(self):
        job_id = NarrationJobId(uuid(710))
        passage_id = PassageId(uuid(711))
        attempt_id = GenerationAttemptId(uuid(712))
        job = {
            "jobId": job_id.value,
            "revision": 4,
            "lane": "lane_b",
            "defaults": {"speed": "0.90", "volume": "1.00", "emotion": "calm", "dictionaryConfigured": True},
            "passages": [{
                "passageId": passage_id.value,
                "order": 0,
                "text": "fixture text",
                "textRevision": 1,
                "recipes": [{
                    "recipeId": uuid(713), "revision": 1, "textRevision": 1,
                    "controls": [], "current": True, "required": True,
                }],
                "recipeRequired": True,
                "dictionaryRequired": False,
                "latestPreview": None,
            }],
        }
        status = {
            "jobId": job_id.value,
            "revision": 4,
            "attempts": [{
                "attemptId": attempt_id.value,
                "passageId": passage_id.value,
                "state": "unknown",
                "submission": "ambiguous",
                "terminal": True,
                "needsReconciliation": True,
                "outputReady": False,
                "reconciliationAvailable": True,
            }],
        }

        markup = presenters.page(
            CSRF,
            {"healthy": True, "checkedFileCount": 0, "issueCodes": [], "backupGuidance": "fixture"},
            None,
            [],
            [(job, status)],
        ).decode("utf-8")

        self.assertIn(f'action="/api/v1/jobs/{job_id.value}/estimate" data-kind="estimate"', markup)
        self.assertIn(f'action="/api/v1/jobs/{job_id.value}/generate" data-kind="generate" hidden', markup)
        self.assertIn(
            f'action="/api/v1/jobs/{job_id.value}/generation-attempts/{attempt_id.value}/reconcile"',
            markup,
        )
        self.assertIn("state unknown", markup)
        for private in ("preview_digest", "authority_record_id", "artifactLocation", "renderedTranscript", "workspacePath"):
            self.assertNotIn(private, markup)


class StudioJavascriptTests(unittest.TestCase):
    def test_estimate_uses_text_content_and_ephemeral_sibling_token_then_generate_reloads(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for packaged studio behavior checks")
        asset = Path(__file__).resolve().parents[3] / "src" / "heritage_archive" / "contexts" / "narrator_voice" / "infrastructure" / "loopback_web" / "assets" / "studio.js"
        script = r'''
const asset = process.argv[1];
const textNode = () => {
  const node = {textContent: ""};
  Object.defineProperty(node, "innerHTML", {set() { throw new Error("innerHTML forbidden"); }});
  return node;
};
const projection = textNode();
const billable = textNode();
const usage = textNode();
const estimateResult = {
  hidden: true,
  querySelector(selector) {
    return ({"[data-estimate-projection]": projection, "[data-estimate-billable]": billable,
             "[data-estimate-usage]": usage})[selector];
  }
};
const tokenInput = {value: ""};
const makeForm = (kind, values, action) => {
  const button = {disabled: false};
  return {dataset: {kind}, hidden: kind === "generate", button, listener: null,
    elements: {namedItem(name) { return values[name]; }},
    querySelectorAll() { return [button]; },
    addEventListener(type, listener) { if (type === "submit") this.listener = listener; },
    getAttribute(name) { return name === "action" ? action : null; },
    closest() { return panel; }};
};
const estimateValues = {
  expectedRevision: {value: "3"}, passageId: {value: "passage"}, recipeId: {value: "recipe"},
  speedMode: {value: "set"}, speed: {value: "1.10"}, volumeMode: {value: "inherit"}, volume: {value: "1.00"},
  emotionMode: {value: "omit"}, emotion: {value: "calm"}, dictionaryMode: {value: "set"}
};
const estimateForm = makeForm("estimate", estimateValues, "/estimate");
const generateForm = makeForm("generate", {confirmationToken: tokenInput}, "/generate");
const panel = {querySelector(selector) {
  if (selector === "[data-estimate-result]") return estimateResult;
  if (selector === 'form[data-kind="generate"]') return generateForm;
  throw new Error("unexpected selector " + selector);
}};
const message = textNode();
global.performance = {getEntriesByType() { return []; }};
global.window = {location: {reloads: 0, reload() { this.reloads += 1; }}};
global.localStorage = new Proxy({}, {get() { throw new Error("localStorage forbidden"); }});
global.sessionStorage = new Proxy({}, {get() { throw new Error("sessionStorage forbidden"); }});
global.document = {
  body: {hasAttribute() { return false; }},
  getElementById() { return message; },
  querySelector(selector) { if (selector === 'meta[name="narrator-csrf"]') return {content: "csrf"}; throw new Error(selector); },
  querySelectorAll() { return [estimateForm, generateForm]; }
};
Object.defineProperty(global.document, "cookie", {set() { throw new Error("cookie write forbidden"); }});
const calls = [];
global.fetch = async (url, options) => {
  calls.push({url, body: JSON.parse(options.body)});
  if (calls.length === 1) return {ok: true, json: async () => ({ok: true, result: {
    canonicalProjection: "<img src=x onerror=private>", billableCharacters: 17,
    estimatedUsage: "17", confirmationToken: "55".repeat(32)
  }})};
  return {ok: true, json: async () => ({ok: true, result: {state: "completed"}})};
};
require(asset);
(async () => {
  await estimateForm.listener({preventDefault() {}});
  const afterEstimate = {projection: projection.textContent, billable: billable.textContent,
    usage: usage.textContent, token: tokenInput.value, generateHidden: generateForm.hidden,
    reloads: window.location.reloads, firstBody: calls[0].body};
  await generateForm.listener({preventDefault() {}});
  process.stdout.write(JSON.stringify({afterEstimate, reloads: window.location.reloads,
    secondBody: calls[1].body, calls: calls.length}));
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
'''
        completed = subprocess.run(
            [node, "-e", script, str(asset)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertEqual(value["afterEstimate"], {
            "projection": "<img src=x onerror=private>",
            "billable": "17",
            "usage": "17",
            "token": "55" * 32,
            "generateHidden": False,
            "reloads": 0,
            "firstBody": {
                "expectedRevision": 3, "passageId": "passage", "recipeId": "recipe",
                "speedMode": "set", "speed": "1.10", "volumeMode": "inherit", "volume": None,
                "emotionMode": "omit", "emotion": None, "dictionaryMode": "set",
            },
        })
        self.assertEqual((value["reloads"], value["secondBody"], value["calls"]),
                         (1, {"confirmationToken": "55" * 32}, 2))


if __name__ == "__main__":
    unittest.main()
