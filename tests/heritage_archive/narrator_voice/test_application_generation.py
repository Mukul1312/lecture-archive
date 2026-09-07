"""Budgeted generation orchestration, authority races and recovery tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ArtifactId, ArtifactRef, ValidationError
from heritage_archive.contexts.narrator_voice.application.commands import (
    EstimateGenerationCommand,
    GeneratePendingPassagesCommand,
    GenerateTakeCommand,
    PrepareDiaryNarrationCommand,
    ReconcileGenerationAttemptCommand,
    RequireRenderRecipeCommand,
    ValidateRenderRecipeCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    EstimateGenerationHandler,
    GeneratePendingPassagesHandler,
    GenerateTakeHandler,
    PrepareDiaryNarrationHandler,
    ReconcileGenerationAttemptHandler,
    RequireRenderRecipeHandler,
    ValidateRenderRecipeHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import ReleasePolicyResolution, SynthesisResult
from heritage_archive.contexts.narrator_voice.application.synthesis_failures import (
    SynthesisAmbiguousFailure,
    SynthesisFailureEvidence,
    SynthesisPreSendFailure,
    SynthesisSubmittedFailure,
)
from heritage_archive.contexts.narrator_voice.application.recovery import BudgetRecoveryState
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptState,
    PublishedArtifact,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
    SubmissionEvidence,
)
from heritage_archive.contexts.narrator_voice.domain.errors import RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    AuthorityChangeId,
    BudgetReservationId,
    CommandId,
    GenerationAttemptId,
    GenerationPreviewId,
    NarrationJobId,
    PassageId,
    PassageRenderRecipeId,
    ProviderEventId,
    TakeId,
)
from heritage_archive.contexts.narrator_voice.domain.narration_job import PassageDraft
from heritage_archive.contexts.narrator_voice.domain.values import (
    AuthorityOperation,
    AuthorityScope,
    Lane,
    NonNegativeDecimal,
    PassageText,
    SafeRelativeArtifactPath,
)
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemAttemptWorkspaceStore,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from tests.heritage_archive.narrator_voice.fakes import (
    FakeArtifactStore,
    FakeArtifactEvidenceVerifier,
    FakeAttemptWorkspaceVerifier,
    FakeAuthorizationRepository,
    FakeAuthorizationStatusReader,
    FakeBudgetLedger,
    FakeClock,
    FakeIdentifierSource,
    FakeMediaInspector,
    FakeNarrationJobRepository,
    FakeRecipeCompiler,
    FakeReleasePolicyResolver,
    FakeSynthesisGateway,
    FakeProviderEventVerifier,
    FakeWorkspaceStore,
)
from tests.heritage_archive.narrator_voice.fixtures import (
    NOW,
    digest,
    make_contract,
    make_defaults,
    make_recipe_authoring,
    make_settings_intent,
    uuid,
)


class GenerationApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = FakeNarrationJobRepository()
        self.auth_repo = FakeAuthorizationRepository()
        self.reader = FakeAuthorizationStatusReader(self.auth_repo)
        self.clock = FakeClock(NOW)
        self.compiler = FakeRecipeCompiler()
        self.budget = FakeBudgetLedger()
        self.store = FakeArtifactStore([ArtifactId(uuid(900)), ArtifactId(uuid(901)), ArtifactId(uuid(902))])
        self.inspector = FakeMediaInspector(100)
        self.workspaces = FakeWorkspaceStore()
        self.workspace_verifier = FakeAttemptWorkspaceVerifier(force_workspace_match=False)
        self.provider_event_verifier = FakeProviderEventVerifier()
        self.artifact_verifier = FakeArtifactEvidenceVerifier()
        self.contract = make_contract(lane=Lane.B)
        self.policies = FakeReleasePolicyResolver(
            lane_b=ReleasePolicyResolution(self.contract, make_defaults()),
        )
        self.steward = ActorId(uuid(903))
        scope = AuthorityScope(
            self.contract.speaker_binding, self.contract.voice_binding, "or", self.contract.purpose, None,
            frozenset(AuthorityOperation), NOW - timedelta(days=1), NOW + timedelta(days=1),
        )
        self.record = AuthorizationRecord.register(
            self.contract.authority_record_id, self.steward, scope, digest("fake generation authority"), NOW
        )
        self.assertTrue(self.auth_repo.save(self.record, None))
        self.job_id = NarrationJobId(uuid(904))
        self.passage_id = PassageId(uuid(905))
        self.recipe_id = PassageRenderRecipeId(uuid(906))
        self.preview_id = GenerationPreviewId(uuid(907))
        self.attempt_id = GenerationAttemptId(uuid(908))
        self.reservation_id = BudgetReservationId(uuid(909))
        self.take_id = TakeId(uuid(910))
        self.workspace_id = AttemptWorkspaceId(uuid(911))
        self.ids = FakeIdentifierSource({
            NarrationJobId: [self.job_id], GenerationPreviewId: [self.preview_id],
            GenerationAttemptId: [self.attempt_id], BudgetReservationId: [self.reservation_id],
            TakeId: [self.take_id], AttemptWorkspaceId: [self.workspace_id],
        })
        text = PassageText("ଏହା ନେଟୱର୍କ ବିହୀନ ନକଲି ଉତ୍ପାଦନ।")
        PrepareDiaryNarrationHandler(self.jobs, self.policies, self.reader, self.clock, self.ids)(
            PrepareDiaryNarrationCommand(CommandId(uuid(912)), (PassageDraft(self.passage_id, 0, text),))
        )
        ValidateRenderRecipeHandler(self.jobs, self.compiler)(
            ValidateRenderRecipeCommand(
                CommandId(uuid(913)), self.job_id, self.passage_id,
                make_recipe_authoring(recipe_index=906), 1,
            )
        )
        RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(914)), self.job_id, self.passage_id, self.recipe_id, 2)
        )
        self.preview = EstimateGenerationHandler(self.jobs, self.reader, self.compiler, self.clock, self.ids)(
            EstimateGenerationCommand(
                CommandId(uuid(915)), self.job_id, self.passage_id,
                self.recipe_id, make_settings_intent(), 3,
            )
        ).preview
        raw = ArtifactRef(ArtifactId(uuid(916)), digest("fake sanitized event"), 20, "application/json")
        timing = ArtifactRef(ArtifactId(uuid(917)), digest("fake timing"), len(b"fake timing"), "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(uuid(918)), 0, ProviderEventKind.TERMINAL, raw, raw.content_digest, NOW,
            "fake-request", "fake-response", None, timing, "42", ProviderTerminalClass.SUCCESS,
        )
        self.evidence_publications = (
            PublishedArtifact(raw, SafeRelativeArtifactPath("evidence/event.json"), NOW),
            PublishedArtifact(timing, SafeRelativeArtifactPath("evidence/timing.json"), NOW),
        )
        self.synthesis_result = SynthesisResult(
            (event,), b"RIFF-fake-canonical-wav", self.evidence_publications,
            timing, NonNegativeDecimal("42"),
        )
        self.gateway = FakeSynthesisGateway(self.synthesis_result)

    def handler(self):
        return GenerateTakeHandler(
            self.jobs, self.reader, self.clock, self.ids, self.budget,
            self.gateway, self.store, self.inspector, self.workspaces,
        )

    def command(self):
        return GenerateTakeCommand(
            CommandId(uuid(919)), self.job_id, self.preview_id, 4,
            SafeRelativeArtifactPath("fake/take.wav"),
        )

    def test_success_reserves_before_external_freezes_exact_preview_bytes_and_settles_usage(self) -> None:
        command = self.command()
        self.gateway.after_call = lambda: self.assertEqual(
            self.budget.read(self.reservation_id), BudgetRecoveryState.RESERVED
        )

        result = self.handler()(command)
        stored = self.jobs.load(self.job_id)
        take = stored.takes[0]
        self.assertEqual((result.state, result.take_id, take.effective_input.rendered_transcript_bytes), (AttemptState.COMPLETED, self.take_id, self.preview.rendered_transcript_bytes))
        self.assertEqual(
            self.gateway.calls[0].effective_input.rendered_transcript_bytes,
            self.preview.rendered_transcript_bytes,
        )
        self.assertEqual(
            self.budget.actions[0],
            (
                "reserve",
                self.reservation_id,
                command.command_id,
                NonNegativeDecimal(self.preview.estimated_usage),
            ),
        )
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "settle"])
        self.assertGreaterEqual(len(self.workspaces.saves), 2)

    def test_input_and_external_boundaries_are_durable_before_the_gateway_call(self) -> None:
        def assert_pre_call_boundary() -> None:
            workspace = self.workspaces.load(self.attempt_id)
            self.assertEqual(
                (workspace.state, workspace.submission),
                (AttemptState.EXTERNAL_WORK_STARTED, SubmissionEvidence.NOT_STARTED),
            )

        self.gateway.after_call = assert_pre_call_boundary

        self.handler()(self.command())

        self.assertEqual(
            tuple(workspace.state for workspace in self.workspaces.saves[:4]),
            (
                AttemptState.RESERVED,
                AttemptState.INPUT_FROZEN,
                AttemptState.EXTERNAL_WORK_STARTED,
                AttemptState.ARTIFACTS_PUBLISHED,
            ),
        )

    def test_gateway_invocation_binds_attempt_complete_contract_and_frozen_input(self) -> None:
        from heritage_archive.contexts.narrator_voice.application.ports import SynthesisInvocation

        self.handler()(self.command())

        invocation = self.gateway.calls[0]
        self.assertIs(type(invocation), SynthesisInvocation)
        self.assertEqual(
            (invocation.attempt_id, invocation.contract, invocation.effective_input),
            (
                self.attempt_id,
                self.jobs.load(self.job_id).contract,
                self.jobs.load(self.job_id).generation_attempt(self.attempt_id).effective_input,
            ),
        )
        mismatched_contract = replace(invocation.contract, model_snapshot="different-model")
        calls_before_rejection = len(self.gateway.calls)
        with self.assertRaises(ValidationError):
            SynthesisInvocation(
                invocation.attempt_id,
                mismatched_contract,
                invocation.effective_input,
            )
        self.assertEqual(len(self.gateway.calls), calls_before_rejection)

    def test_batch_rejects_exact_billable_character_total_above_caller_accepted_cap_before_side_effects(self) -> None:
        command = GeneratePendingPassagesCommand(
            CommandId(uuid(922)),
            self.job_id,
            (self.preview_id,),
            4,
            (SafeRelativeArtifactPath("fake/batch.wav"),),
            self.preview.billable_characters - 1,
        )

        with self.assertRaises(ValidationError):
            GeneratePendingPassagesHandler(self.handler())(command)

        self.assertEqual((self.budget.actions, self.gateway.calls, self.store.calls), ([], [], []))

    def test_provider_response_without_one_final_success_event_fails_and_settles_without_publishing(self) -> None:
        self.gateway.result = SynthesisResult(
            (), b"RIFF-invalid-event-stream", (), None, NonNegativeDecimal("42")
        )

        result = self.handler()(self.command())

        self.assertEqual((result.state, result.take_id, result.budget_disposition), (AttemptState.FAILED, None, "settled"))
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "settle"])
        self.assertEqual(self.store.calls, [])

    def test_invalid_partial_provider_events_are_discarded_but_a_sealed_failure_terminal_is_retained(self) -> None:
        partial = replace(
            self.synthesis_result.events[0],
            kind=ProviderEventKind.AUDIO,
            terminal_classification=None,
        )
        self.gateway.result = SynthesisResult(
            (partial,), b"RIFF-invalid-event-stream", self.evidence_publications,
            self.synthesis_result.raw_timing_reference, NonNegativeDecimal("42"),
        )

        self.handler()(self.command())

        self.assertEqual(self.workspaces.load(self.attempt_id).events, ())

    def test_invalid_sealed_failure_terminal_is_retained_as_independent_evidence(self) -> None:
        failure_terminal = replace(
            self.synthesis_result.events[0], terminal_classification=ProviderTerminalClass.FAILURE,
        )
        self.gateway.result = SynthesisResult(
            (failure_terminal,), b"RIFF-invalid-event-stream", self.evidence_publications,
            self.synthesis_result.raw_timing_reference, NonNegativeDecimal("42"),
        )

        self.handler()(self.command())

        self.assertEqual(self.workspaces.load(self.attempt_id).events, (failure_terminal,))

    def test_returned_adapter_failures_persist_failed_evidence_and_settle_without_replay(self) -> None:
        self.inspector.fail_next_inspection = True
        result = self.handler()(self.command())

        workspace = self.workspaces.load(self.attempt_id)
        self.assertEqual((result.state, workspace.state, workspace.submission, self.budget.read(self.reservation_id).value), (AttemptState.FAILED, AttemptState.FAILED, "completed", "settled"))
        self.assertEqual((len(self.gateway.calls), len(self.inspector.calls), len(self.store.calls)), (1, 1, 0))

    def test_artifact_publish_failure_persists_failed_evidence_and_settles_without_replay(self) -> None:
        self.store.fail_next_publish = True
        result = self.handler()(self.command())

        workspace = self.workspaces.load(self.attempt_id)
        self.assertEqual(
            (
                result.state,
                workspace.state,
                workspace.published_artifacts,
                self.budget.read(self.reservation_id).value,
            ),
            (
                AttemptState.FAILED,
                AttemptState.FAILED,
                self.evidence_publications,
                "settled",
            ),
        )
        self.assertEqual((len(self.gateway.calls), len(self.store.calls)), (1, 1))

    def test_budget_commit_then_raise_reports_unknown_without_a_downgrade(self) -> None:
        self.budget.commit_then_raise_next_finalization = True
        result = self.handler()(self.command())

        self.assertEqual((result.state, result.budget_disposition, self.budget.read(self.reservation_id).value), (AttemptState.UNKNOWN, "unknown", "settled"))

    def test_fake_budget_finalization_is_idempotent_only_for_exact_terminal_facts(self) -> None:
        self.budget.reserve(self.reservation_id, CommandId(uuid(932)), NonNegativeDecimal("42"))
        self.budget.settle(self.reservation_id, NonNegativeDecimal("42"))
        self.budget.settle(self.reservation_id, NonNegativeDecimal("42"))

        with self.assertRaises(ValidationError):
            self.budget.settle(self.reservation_id, NonNegativeDecimal("43"))
        with self.assertRaises(ValidationError):
            self.budget.hold(self.reservation_id, "would downgrade settled usage")

    def test_fake_budget_release_and_hold_require_their_exact_original_reason(self) -> None:
        released = BudgetReservationId(uuid(930))
        held = BudgetReservationId(uuid(931))
        self.budget.reserve(released, CommandId(uuid(932)), NonNegativeDecimal("1"))
        self.budget.release(released, "not sent")
        self.budget.release(released, "not sent")
        self.budget.reserve(held, CommandId(uuid(933)), NonNegativeDecimal("1"))
        self.budget.hold(held, "ambiguous")
        self.budget.hold(held, "ambiguous")

        with self.assertRaises(ValidationError):
            self.budget.release(released, "different reason")
        with self.assertRaises(ValidationError):
            self.budget.hold(held, "different reason")

    def test_invalid_provider_result_CAS_refusal_preserves_failed_workspace_and_settled_usage(self) -> None:
        self.gateway.result = SynthesisResult(
            (), b"RIFF-invalid-event-stream", (), None, NonNegativeDecimal("42")
        )
        self.jobs.reject_on_save_calls.add(8)

        result = self.handler()(self.command())

        workspace = self.workspaces.load(self.attempt_id)
        self.assertEqual((result.state, workspace.state, self.budget.read(self.reservation_id).value), (AttemptState.UNKNOWN, AttemptState.FAILED, "settled"))
        self.assertEqual((len(self.gateway.calls), len(self.store.calls)), (1, 0))

    def test_digitally_silent_media_fails_and_settles_without_publishing(self) -> None:
        self.inspector.all_digital_silence = True

        result = self.handler()(self.command())

        self.assertEqual((result.state, result.take_id, result.budget_disposition), (AttemptState.FAILED, None, "settled"))
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "settle"])
        self.assertEqual(self.store.calls, [])

    def test_initial_CAS_refusal_performs_no_budget_provider_or_artifact_action(self) -> None:
        self.jobs.reject_next_save = True
        with self.assertRaises(RevisionConflict):
            self.handler()(self.command())
        self.assertEqual((self.budget.actions, self.gateway.calls, self.store.calls), ([], [], []))
        self.assertEqual(self.jobs.load(self.job_id).generation_attempts, ())

    def test_definite_pre_send_failure_releases_budget_and_records_blocked_terminal(self) -> None:
        self.gateway.mode = "pre_send"
        result = self.handler()(self.command())
        self.assertEqual((result.state, result.budget_disposition), (AttemptState.BLOCKED, "released"))
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "release"])

    def test_real_workspace_store_allows_definite_pre_send_terminal_after_external_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = LocalNarrationRoot.open(
                Path(temporary_directory), (Path(__file__).resolve().parents[3],)
            )
            root.initialize_layout()
            self.workspaces = FilesystemAttemptWorkspaceStore(root)
            self.gateway.mode = "pre_send"

            result = self.handler()(self.command())
            workspace = self.workspaces.load(self.attempt_id)

        self.assertEqual(
            (result.state, result.budget_disposition, workspace.state, workspace.submission),
            (
                AttemptState.BLOCKED,
                "released",
                AttemptState.BLOCKED,
                SubmissionEvidence.DEFINITELY_NOT_SENT,
            ),
        )
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "release"])

    def test_ambiguous_failure_holds_budget_until_explicit_conservative_reconciliation(self) -> None:
        self.gateway.mode = "ambiguous"
        result = self.handler()(self.command())
        self.assertEqual((result.state, result.budget_disposition), (AttemptState.UNKNOWN, "held"))
        reconciled = ReconcileGenerationAttemptHandler(
            self.jobs,
            self.reader,
            self.clock,
            self.workspaces,
            self.workspace_verifier,
            self.provider_event_verifier,
            self.artifact_verifier,
            self.budget,
            self.budget,
        )(
            ReconcileGenerationAttemptCommand(
                CommandId(uuid(920)), self.job_id, self.attempt_id, result.revision,
            )
        )
        self.assertEqual((reconciled.revision, self.jobs.load(self.job_id).generation_attempts[0].state), (result.revision + 1, AttemptState.QUARANTINED))

    def test_evidence_bearing_failures_persist_before_their_explicit_budget_disposition(self) -> None:
        cases = (
            (
                SynthesisPreSendFailure,
                SubmissionEvidence.DEFINITELY_NOT_SENT,
                ProviderTerminalClass.DEFINITE_PRE_SEND_FAILURE,
                NonNegativeDecimal("3"),
                AttemptState.BLOCKED,
                "release",
            ),
            (
                SynthesisAmbiguousFailure,
                SubmissionEvidence.AMBIGUOUS,
                ProviderTerminalClass.AMBIGUOUS,
                None,
                AttemptState.UNKNOWN,
                "hold",
            ),
            (
                SynthesisSubmittedFailure,
                SubmissionEvidence.COMPLETED,
                ProviderTerminalClass.FAILURE,
                NonNegativeDecimal("3"),
                AttemptState.FAILED,
                "settle",
            ),
        )
        for failure_type, submission, terminal, usage, state, budget_action in cases:
            with self.subTest(failure_type=failure_type.__name__):
                self.setUp()
                event = replace(self.synthesis_result.events[0], terminal_classification=terminal)
                evidence = SynthesisFailureEvidence(
                    submission, (event,), self.evidence_publications,
                    self.synthesis_result.raw_timing_reference, usage,
                    "fixture_provider_failure",
                )
                self.gateway.failure = failure_type(evidence)

                result = self.handler()(self.command())
                workspace = self.workspaces.load(self.attempt_id)

                self.assertEqual((result.state, workspace.state), (state, state))
                self.assertEqual(
                    (workspace.events, workspace.published_artifacts, workspace.recovery_evidence),
                    ((event,), self.evidence_publications, ("fixture_provider_failure",)),
                )
                self.assertEqual(self.budget.actions[-1][0], budget_action)

    def test_submitted_failure_without_authoritative_usage_holds_failed_attempt_for_reconciliation(self) -> None:
        event = replace(
            self.synthesis_result.events[0], terminal_classification=ProviderTerminalClass.FAILURE
        )
        self.gateway.failure = SynthesisSubmittedFailure(SynthesisFailureEvidence(
            SubmissionEvidence.COMPLETED, (event,), self.evidence_publications,
            self.synthesis_result.raw_timing_reference, None, "usage_unavailable",
        ))

        result = self.handler()(self.command())

        self.assertEqual((result.state, result.budget_disposition), (AttemptState.FAILED, "held"))
        self.assertEqual(self.budget.actions[-1][0], "hold")

    def test_unexpected_post_boundary_exception_is_sanitized_unknown_and_holds_budget(self) -> None:
        self.gateway.mode = "unexpected"

        result = self.handler()(self.command())
        workspace = self.workspaces.load(self.attempt_id)

        self.assertEqual((result.state, workspace.state), (AttemptState.UNKNOWN, AttemptState.UNKNOWN))
        self.assertEqual(workspace.submission, SubmissionEvidence.AMBIGUOUS)
        self.assertEqual(workspace.recovery_evidence, ("unexpected_synthesis_failure",))
        self.assertNotIn("private provider exception text", repr(workspace))
        self.assertEqual(self.budget.actions[-1][0], "hold")

    def test_authority_withdrawal_racing_after_provider_quarantines_artifact_and_settles_actual_usage(self) -> None:
        def withdraw() -> None:
            record = self.auth_repo.load(self.contract.authority_record_id)
            record.withdraw(AuthorityChangeId(uuid(921)), self.steward, "fake racing withdrawal", NOW, expected_revision=1)
            self.assertTrue(self.auth_repo.save(record, 1))

        self.gateway.after_call = withdraw
        result = self.handler()(self.command())
        self.assertEqual((result.state, result.take_id, result.budget_disposition), (AttemptState.QUARANTINED, None, "settled"))
        self.assertEqual((len(self.store.calls), len(self.jobs.load(self.job_id).takes)), (1, 0))

    def test_post_provider_CAS_conflict_preserves_published_evidence_and_settled_usage_without_second_CAS(self) -> None:
        # Four setup saves, then reservation/freeze/start; refuse the stage save after one provider call.
        self.jobs.reject_on_save_calls.add(8)
        result = self.handler()(self.command())
        attempt = self.jobs.load(self.job_id).generation_attempts[-1]
        workspace = self.workspaces.load(self.attempt_id)
        self.assertEqual((result.state, attempt.state, workspace.state), (AttemptState.UNKNOWN, AttemptState.EXTERNAL_WORK_STARTED, AttemptState.ARTIFACTS_PUBLISHED))
        self.assertEqual((len(self.gateway.calls), len(self.store.calls), self.budget.actions[-1][0]), (1, 1, "settle"))

    def test_final_completion_CAS_refusal_leaves_published_attempt_for_reconciliation(self) -> None:
        self.jobs.reject_on_save_calls.add(10)

        result = self.handler()(self.command())

        attempt = self.jobs.load(self.job_id).generation_attempts[-1]
        self.assertEqual((result.state, attempt.state, self.workspaces.load(self.attempt_id).state), (AttemptState.UNKNOWN, AttemptState.ARTIFACTS_PUBLISHED, AttemptState.ARTIFACTS_PUBLISHED))
        self.assertEqual((len(self.gateway.calls), len(self.store.calls), self.budget.read(self.reservation_id).value), (1, 1, "settled"))

    def test_two_CAS_refusals_preserve_evidence_until_a_fresh_reconciliation_completes_once(self) -> None:
        self.jobs.reject_on_save_calls.update({8, 9})
        unknown = self.handler()(self.command())
        self.ids.values[TakeId] = [self.take_id, TakeId(uuid(920))]
        reconciler = ReconcileGenerationAttemptHandler(
            self.jobs, self.reader, self.clock, self.workspaces,
            FakeAttemptWorkspaceVerifier(), FakeProviderEventVerifier(),
            FakeArtifactEvidenceVerifier(self.inspector.inspect_canonical_wav(b"recovered")),
            self.budget, self.budget, self.ids,
        )

        with self.assertRaises(RevisionConflict):
            reconciler(ReconcileGenerationAttemptCommand(CommandId(uuid(921)), self.job_id, self.attempt_id, unknown.revision))
        completed = reconciler(
            ReconcileGenerationAttemptCommand(CommandId(uuid(922)), self.job_id, self.attempt_id, unknown.revision)
        )

        self.assertEqual(self.jobs.load(self.job_id).generation_attempts[-1].state, AttemptState.COMPLETED)
        self.assertEqual((len(self.gateway.calls), len(self.store.calls), completed.revision), (1, 1, unknown.revision + 1))

    def test_post_provider_workspace_save_failure_holds_without_aggregate_CAS_or_provider_replay(self) -> None:
        self.workspaces.fail_next_save = False
        # Reserved, input-frozen and pre-call boundary workspaces precede provider evidence.
        original_save = self.workspaces.save
        saves = 0

        def fail_on_second_save(workspace):
            nonlocal saves
            saves += 1
            if saves == 4:
                self.workspaces.fail_next_save = True
            return original_save(workspace)

        self.workspaces.save = fail_on_second_save
        result = self.handler()(self.command())
        attempt = self.jobs.load(self.job_id).generation_attempts[-1]
        self.assertEqual((result.state, attempt.state, len(self.gateway.calls), len(self.store.calls)), (AttemptState.UNKNOWN, AttemptState.EXTERNAL_WORK_STARTED, 1, 1))
        self.assertEqual(self.budget.read(self.reservation_id).value, "unknown")

    def test_budget_settlement_failure_preserves_published_workspace_without_completion_CAS(self) -> None:
        self.budget.fail_next_finalization = True
        result = self.handler()(self.command())

        workspace = self.workspaces.load(self.attempt_id)
        attempt = self.jobs.load(self.job_id).generation_attempts[-1]
        self.assertEqual((result.state, workspace.state, attempt.state), (AttemptState.UNKNOWN, AttemptState.ARTIFACTS_PUBLISHED, AttemptState.EXTERNAL_WORK_STARTED))
        self.assertEqual((len(self.gateway.calls), len(self.store.calls)), (1, 1))
        self.assertEqual((result.budget_disposition, self.budget.read(self.reservation_id).value), ("unknown", "reserved"))
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "settle"])


class SynthesisEvidenceContractTests(unittest.TestCase):
    def evidence(self):
        raw = ArtifactRef(ArtifactId(uuid(940)), digest("raw provider event"), 18, "application/json")
        pcm = ArtifactRef(ArtifactId(uuid(941)), digest("partial pcm"), 10, "audio/pcm")
        timing = ArtifactRef(ArtifactId(uuid(942)), digest("combined timing"), 16, "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(uuid(943)), 0, ProviderEventKind.TERMINAL,
            raw, raw.content_digest, NOW, "request", "response", pcm, timing,
            "7", ProviderTerminalClass.SUCCESS,
        )
        publications = (
            PublishedArtifact(raw, SafeRelativeArtifactPath("evidence/raw.json"), NOW),
            PublishedArtifact(pcm, SafeRelativeArtifactPath("evidence/audio.pcm"), NOW),
            PublishedArtifact(timing, SafeRelativeArtifactPath("evidence/timing.json"), NOW),
        )
        return event, publications, timing

    def test_result_has_no_public_four_argument_evidence_bypass(self) -> None:
        event, _, timing = self.evidence()

        with self.assertRaises(TypeError):
            SynthesisResult(
                (event,), b"RIFF fixture", (timing,), NonNegativeDecimal("7")
            )

    def test_result_retains_contiguous_events_publications_timing_and_usage(self) -> None:
        event, publications, timing = self.evidence()

        result = SynthesisResult(
            (event,), b"RIFF fixture", publications, timing, NonNegativeDecimal("7")
        )

        self.assertEqual(
            (result.events, result.evidence_publications, result.raw_timing_reference, result.usage),
            ((event,), publications, timing, NonNegativeDecimal("7")),
        )
        with self.assertRaises(ValidationError):
            replace(result, evidence_publications=publications[1:])
        with self.assertRaises(ValidationError):
            replace(result, events=(replace(event, sequence=1),))
        for changed_reference in (
            ArtifactRef(
                event.sanitized_raw_reference.artifact_id,
                digest("different bytes"),
                event.sanitized_raw_reference.byte_size,
                event.sanitized_raw_reference.media_type,
            ),
            ArtifactRef(
                event.sanitized_raw_reference.artifact_id,
                event.sanitized_raw_reference.content_digest,
                event.sanitized_raw_reference.byte_size + 1,
                event.sanitized_raw_reference.media_type,
            ),
            ArtifactRef(
                event.sanitized_raw_reference.artifact_id,
                event.sanitized_raw_reference.content_digest,
                event.sanitized_raw_reference.byte_size,
                "text/plain",
            ),
        ):
            with self.subTest(changed_reference=changed_reference):
                mismatched = PublishedArtifact(
                    changed_reference,
                    publications[0].relative_location,
                    publications[0].published_at,
                )
                with self.assertRaises(ValidationError):
                    replace(result, evidence_publications=(mismatched, *publications[1:]))

    def test_each_failure_category_carries_validated_immutable_sanitized_evidence(self) -> None:
        event, publications, timing = self.evidence()
        cases = (
            (SynthesisPreSendFailure, SubmissionEvidence.DEFINITELY_NOT_SENT),
            (SynthesisAmbiguousFailure, SubmissionEvidence.AMBIGUOUS),
            (SynthesisSubmittedFailure, SubmissionEvidence.COMPLETED),
        )
        for failure_type, submission in cases:
            with self.subTest(failure_type=failure_type.__name__):
                evidence = SynthesisFailureEvidence(
                    submission, (event,), publications, timing,
                    NonNegativeDecimal("7"), "provider_terminal_failure",
                )
                failure = failure_type(evidence)
                self.assertIs(failure.evidence, evidence)
                self.assertEqual(str(failure), "provider_terminal_failure")

        with self.assertRaises(ValidationError):
            SynthesisFailureEvidence(
                SubmissionEvidence.AMBIGUOUS, (event,), publications, timing,
                None, "timeout: secret provider detail",
            )


if __name__ == "__main__":
    unittest.main()
