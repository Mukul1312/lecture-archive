"""Budgeted generation orchestration, authority races and recovery tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys
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
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptState,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
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
        timing = ArtifactRef(ArtifactId(uuid(917)), digest("fake timing"), 12, "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(uuid(918)), 0, ProviderEventKind.TERMINAL, raw, raw.content_digest, NOW,
            "fake-request", "fake-response", None, timing, "42", ProviderTerminalClass.SUCCESS,
        )
        self.synthesis_result = SynthesisResult((event,), b"RIFF-fake-canonical-wav", (timing,), NonNegativeDecimal("42"))
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
        result = self.handler()(self.command())
        stored = self.jobs.load(self.job_id)
        take = stored.takes[0]
        self.assertEqual((result.state, result.take_id, take.effective_input.rendered_transcript_bytes), (AttemptState.COMPLETED, self.take_id, self.preview.rendered_transcript_bytes))
        self.assertEqual(self.gateway.calls[0].rendered_transcript_bytes, self.preview.rendered_transcript_bytes)
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "settle"])
        self.assertGreaterEqual(len(self.workspaces.saves), 2)

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
            (), b"RIFF-invalid-event-stream", (), NonNegativeDecimal("42")
        )

        result = self.handler()(self.command())

        self.assertEqual((result.state, result.take_id, result.budget_disposition), (AttemptState.FAILED, None, "settled"))
        self.assertEqual([action[0] for action in self.budget.actions], ["reserve", "settle"])
        self.assertEqual(self.store.calls, [])

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

    def test_authority_withdrawal_racing_after_provider_quarantines_artifact_and_settles_actual_usage(self) -> None:
        def withdraw() -> None:
            record = self.auth_repo.load(self.contract.authority_record_id)
            record.withdraw(AuthorityChangeId(uuid(921)), self.steward, "fake racing withdrawal", NOW, expected_revision=1)
            self.assertTrue(self.auth_repo.save(record, 1))

        self.gateway.after_call = withdraw
        result = self.handler()(self.command())
        self.assertEqual((result.state, result.take_id, result.budget_disposition), (AttemptState.QUARANTINED, None, "settled"))
        self.assertEqual((len(self.store.calls), len(self.jobs.load(self.job_id).takes)), (1, 0))

    def test_post_provider_CAS_conflict_is_recorded_unknown_held_and_reconcilable_without_retry(self) -> None:
        # Four setup saves, then reservation/freeze/start; refuse the stage save after one provider call.
        self.jobs.reject_on_save_calls.add(8)
        result = self.handler()(self.command())
        attempt = self.jobs.load(self.job_id).generation_attempts[-1]
        workspace = self.workspaces.load(self.attempt_id)
        self.assertEqual((result.state, attempt.state, workspace.state), (AttemptState.UNKNOWN, AttemptState.UNKNOWN, AttemptState.UNKNOWN))
        self.assertEqual((len(self.gateway.calls), self.budget.actions[-1][0]), (1, "hold"))


if __name__ == "__main__":
    unittest.main()
