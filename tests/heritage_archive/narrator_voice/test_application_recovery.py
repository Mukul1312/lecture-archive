"""Pure recovery decision tests; no storage or provider adapter is involved."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.contexts.narrator_voice.application.recovery import (
    BudgetDisposition,
    BudgetRecoveryState,
    GenerationRecoveryTarget,
    NarrationAssemblyRecoveryTarget,
    RecoveryDisposition,
    RecoveryFacts,
    RecoveryReason,
    RecoveryStage,
    decide_target_recovery,
    decide_recovery,
)
from heritage_archive.contexts.narrator_voice.application.handlers import _recovery_transition_required
from heritage_archive.contexts.narrator_voice.application.ports import (
    ArtifactEvidenceVerifier,
    BudgetReservationStatusReader,
    ProviderEventVerifier,
    AttemptWorkspaceVerifier,
)
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemAttemptWorkspaceVerifier,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptState,
    DecodedMediaFacts,
    ProviderTerminalClass,
    SubmissionEvidence,
    narration_assembly_plan_digest,
)
from heritage_archive.kernel import ActorId, ArtifactId, ValidationError
from heritage_archive.contexts.narrator_voice.domain.ids import (
    BudgetReservationId,
    CommandId,
    GenerationAttemptId,
    EpisodeAssemblyAttemptId,
    EpisodeSpeechMasterId,
    NarrationAssemblyAttemptId,
    NarrationMasterId,
    NarrationJobId,
    ReviewDecisionId,
    SelectionDecisionId,
    TakeId,
    AttemptWorkspaceId,
)
from tests.heritage_archive.narrator_voice.fixtures import uuid
from tests.heritage_archive.narrator_voice.fakes import (
    FakeActorResolver,
    FakeArtifactEvidenceVerifier,
    FakeAttemptWorkspaceVerifier,
    FakeDryPcmAssembler,
    FakeProviderEventVerifier,
)
from tests.heritage_archive.narrator_voice import test_application_generation as generation_fixture
from tests.heritage_archive.narrator_voice import test_application_episode as episode_fixture
from heritage_archive.contexts.narrator_voice.application.commands import (
    AssembleNarrationMasterCommand,
    AssembleEpisodeSpeechMasterCommand,
    RecordReviewDecisionCommand,
    SelectWorkingTakeCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    AssembleNarrationMasterHandler,
    AssembleEpisodeSpeechMasterHandler,
    ReconcileEpisodeAssemblyAttemptHandler,
    ReconcileGenerationAttemptHandler,
    ReconcileNarrationAssemblyAttemptHandler,
    RecordReviewDecisionHandler,
    SelectWorkingTakeHandler,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import ReviewOutcome
from heritage_archive.contexts.narrator_voice.domain.values import SafeRelativeArtifactPath
from heritage_archive.contexts.narrator_voice.domain.values import CanonicalAudioFacts
from heritage_archive.contexts.narrator_voice.application.commands import (
    ReconcileEpisodeAssemblyAttemptCommand,
    ReconcileGenerationAttemptCommand,
    ReconcileNarrationAssemblyAttemptCommand,
)


class RecoveryArtifactEvidence(FakeArtifactEvidenceVerifier):
    def __init__(self, media: DecodedMediaFacts) -> None:
        super().__init__(media)


def facts(**changes: object) -> RecoveryFacts:
    values: dict[str, object] = {
        "attempt_state": AttemptState.EXTERNAL_WORK_STARTED,
        "last_confirmed_stage": RecoveryStage.EXTERNAL_WORK_STARTED,
        "workspace_matches_attempt": True,
        "frozen_plan_matches": True,
        "submission": SubmissionEvidence.STARTED,
        "provider_terminal": ProviderTerminalClass.SUCCESS,
        "events_sealed": True,
        "artifact_verified": True,
        "publication_verified": True,
        "authority_covers_completion": True,
        "requires_budget": True,
        "budget_state": BudgetRecoveryState.SETTLED,
    }
    values.update(changes)
    return RecoveryFacts(**values)  # type: ignore[arg-type]


class RecoveryDecisionTests(unittest.TestCase):
    def test_explicit_pre_call_workspace_is_external_started_even_before_submission(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests(
            "test_input_and_external_boundaries_are_durable_before_the_gateway_call"
        )
        fixture.setUp()
        fixture.handler()(fixture.command())
        workspace = fixture.workspaces.saves[2]
        attempt = fixture.jobs.load(fixture.job_id).generation_attempt(fixture.attempt_id)

        verified = FilesystemAttemptWorkspaceVerifier().verify(
            workspace,
            GenerationRecoveryTarget(fixture.job_id, fixture.attempt_id, fixture.reservation_id),
            AttemptState.EXTERNAL_WORK_STARTED,
            attempt.reservation_revision,
            attempt.effective_input.request_digest,
        )

        self.assertEqual(workspace.submission, SubmissionEvidence.NOT_STARTED)
        self.assertEqual(verified.last_confirmed_stage, RecoveryStage.EXTERNAL_WORK_STARTED)

    def test_recovery_requires_separate_trusted_workspace_provider_artifact_and_budget_ports(self) -> None:
        for port in (
            AttemptWorkspaceVerifier,
            ProviderEventVerifier,
            ArtifactEvidenceVerifier,
            BudgetReservationStatusReader,
        ):
            self.assertTrue(hasattr(port, "verify") or hasattr(port, "read"))

    def test_recovery_targets_preserve_nominal_root_attempt_and_budget_ids(self) -> None:
        generation = GenerationRecoveryTarget(
            NarrationJobId(uuid(800)), GenerationAttemptId(uuid(801)), BudgetReservationId(uuid(802))
        )
        assembly = NarrationAssemblyRecoveryTarget(
            NarrationJobId(uuid(803)), NarrationAssemblyAttemptId(uuid(804))
        )

        self.assertEqual(generation.job_id, NarrationJobId(uuid(800)))
        self.assertEqual(assembly.attempt_id, NarrationAssemblyAttemptId(uuid(804)))

    def test_target_contract_rejects_a_budgeted_dry_assembly_recovery(self) -> None:
        assembly = NarrationAssemblyRecoveryTarget(
            NarrationJobId(uuid(805)), NarrationAssemblyAttemptId(uuid(806))
        )

        with self.assertRaises(ValidationError):
            decide_target_recovery(assembly, facts())

    def test_evidence_proven_post_external_cas_failure_completes_without_a_repeat(self) -> None:
        decision = decide_recovery(facts())

        self.assertEqual(decision.disposition, RecoveryDisposition.COMPLETED)
        self.assertEqual(decision.budget, BudgetDisposition.SETTLED)
        self.assertFalse(decision.may_start_external_work)

    def test_ambiguous_submitted_provider_call_is_unknown_and_holds_budget(self) -> None:
        decision = decide_recovery(facts(
            provider_terminal=ProviderTerminalClass.AMBIGUOUS,
            events_sealed=False,
            artifact_verified=False,
            publication_verified=False,
            budget_state=BudgetRecoveryState.RESERVED,
        ))

        self.assertEqual(decision.disposition, RecoveryDisposition.UNKNOWN)
        self.assertEqual(decision.budget, BudgetDisposition.HOLD)
        self.assertFalse(decision.may_start_external_work)

    def test_authority_withdrawal_after_success_quarantines_but_settles_charge(self) -> None:
        decision = decide_recovery(facts(authority_covers_completion=False))

        self.assertEqual(decision.disposition, RecoveryDisposition.QUARANTINED)
        self.assertEqual(decision.budget, BudgetDisposition.SETTLED)

    def test_artifact_digest_failure_quarantines_without_replaying_provider_work(self) -> None:
        decision = decide_recovery(facts(artifact_verified=False))

        self.assertEqual(decision.disposition, RecoveryDisposition.QUARANTINED)
        self.assertEqual(decision.budget, BudgetDisposition.SETTLED)
        self.assertFalse(decision.may_start_external_work)

    def test_provider_success_without_trusted_budget_settlement_stays_unknown(self) -> None:
        decision = decide_recovery(facts(budget_state=BudgetRecoveryState.UNKNOWN))

        self.assertEqual(decision.disposition, RecoveryDisposition.UNKNOWN)
        self.assertEqual(decision.budget, BudgetDisposition.HOLD)

    def test_definite_pre_send_failure_blocks_and_releases_budget(self) -> None:
        decision = decide_recovery(facts(
            attempt_state=AttemptState.INPUT_FROZEN,
            last_confirmed_stage=RecoveryStage.INPUT_FROZEN,
            submission=SubmissionEvidence.DEFINITELY_NOT_SENT,
            provider_terminal=ProviderTerminalClass.DEFINITE_PRE_SEND_FAILURE,
            events_sealed=False,
            artifact_verified=False,
            publication_verified=False,
            budget_state=BudgetRecoveryState.RESERVED,
        ))

        self.assertEqual(decision.disposition, RecoveryDisposition.BLOCKED)
        self.assertEqual(decision.budget, BudgetDisposition.RELEASE)
        self.assertFalse(decision.may_start_external_work)

    def test_unbudgeted_dry_assembly_can_complete_from_exact_artifact_facts(self) -> None:
        decision = decide_recovery(facts(
            requires_budget=False,
            budget_state=BudgetRecoveryState.NOT_APPLICABLE,
            provider_terminal=None,
        ))

        self.assertEqual(decision.disposition, RecoveryDisposition.COMPLETED)
        self.assertEqual(decision.budget, BudgetDisposition.NOT_APPLICABLE)

    def test_workspace_or_plan_mismatch_is_never_completed(self) -> None:
        decision = decide_recovery(facts(frozen_plan_matches=False))

        self.assertEqual(decision.disposition, RecoveryDisposition.QUARANTINED)
        self.assertEqual(decision.budget, BudgetDisposition.SETTLED)

    def test_unknown_attempt_can_reconcile_only_to_a_trusted_conservative_terminal(self) -> None:
        decision = decide_recovery(facts(
            attempt_state=AttemptState.UNKNOWN,
            provider_terminal=None,
            events_sealed=False,
            artifact_observed=False,
            publication_observed=False,
            authority_covers_completion=False,
        ))

        self.assertEqual(decision.disposition, RecoveryDisposition.UNKNOWN)
        self.assertFalse(_recovery_transition_required(decision, AttemptState.UNKNOWN))
        self.assertTrue(_recovery_transition_required(
            type(decision)(RecoveryDisposition.QUARANTINED, BudgetDisposition.SETTLED, RecoveryReason.ARTIFACT_EVIDENCE_MISMATCH),
            AttemptState.UNKNOWN,
        ))

    def test_post_artifact_cas_refusal_preserves_narration_workspace_before_recovery(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests(
            "test_success_reserves_before_external_freezes_exact_preview_bytes_and_settles_usage"
        )
        fixture.setUp()
        generated = fixture.handler()(fixture.command())
        actor = ActorId(uuid(980))
        actors = FakeActorResolver({"operator": actor})
        fixture.ids.values[ReviewDecisionId] = [ReviewDecisionId(uuid(981))]
        fixture.ids.values[SelectionDecisionId] = [SelectionDecisionId(uuid(982))]
        fixture.ids.values[NarrationAssemblyAttemptId] = [NarrationAssemblyAttemptId(uuid(983))]
        fixture.ids.values[NarrationMasterId] = [NarrationMasterId(uuid(984))]
        fixture.ids.values[AttemptWorkspaceId] = [AttemptWorkspaceId(uuid(985))]
        reviewed = RecordReviewDecisionHandler(fixture.jobs, actors, fixture.clock, fixture.ids)(
            RecordReviewDecisionCommand(
                CommandId(uuid(986)), "operator", fixture.job_id, generated.take_id,
                ReviewOutcome.ACCEPTED, "accepted", generated.revision,
            )
        )
        selected = SelectWorkingTakeHandler(fixture.jobs, fixture.reader, actors, fixture.clock, fixture.ids)(
            SelectWorkingTakeCommand(
                CommandId(uuid(987)), "operator", fixture.job_id, fixture.passage_id,
                generated.take_id, "selected", reviewed.revision,
            )
        )
        fixture.store.artifact_ids.append(ArtifactId(uuid(988)))
        fixture.jobs.reject_on_save_calls.add(fixture.jobs.save_calls + 4)
        assembler = FakeDryPcmAssembler()

        recovered = AssembleNarrationMasterHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.ids, assembler, fixture.store, fixture.workspaces,
        )(
            AssembleNarrationMasterCommand(
                CommandId(uuid(989)), fixture.job_id, (), selected.revision,
                SafeRelativeArtifactPath("fake/recovery-master.wav"),
            )
        )

        self.assertEqual(recovered.state, AttemptState.UNKNOWN)
        self.assertEqual(len(assembler.narration_calls), 1)
        self.assertEqual(len(fixture.store.calls), 2)
        workspace = fixture.workspaces.load(recovered.attempt_id)
        self.assertEqual(workspace.state, AttemptState.ARTIFACTS_PUBLISHED)
        self.assertEqual(
            fixture.jobs.load(fixture.job_id).narration_assembly_attempt(recovered.attempt_id).state,
            AttemptState.EXTERNAL_WORK_STARTED,
        )

    def test_generation_post_provider_workspace_binds_the_attempt_reservation_revision(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests(
            "test_post_provider_CAS_conflict_preserves_published_evidence_and_settled_usage_without_second_CAS"
        )
        fixture.setUp()
        fixture.jobs.reject_on_save_calls.add(8)

        fixture.handler()(fixture.command())

        attempt = fixture.jobs.load(fixture.job_id).generation_attempts[-1]
        workspace = fixture.workspaces.load(fixture.attempt_id)
        self.assertEqual(workspace.reservation_revision, attempt.reservation_revision)

    def test_generation_unknown_completion_recovers_once_from_verified_workspace_without_provider_replay(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests(
            "test_post_provider_CAS_conflict_preserves_published_evidence_and_settled_usage_without_second_CAS"
        )
        fixture.setUp()
        fixture.jobs.reject_on_save_calls.add(8)
        unknown = fixture.handler()(fixture.command())
        verifier = RecoveryArtifactEvidence(fixture.inspector.inspect_canonical_wav(b"recovered"))
        handler = ReconcileGenerationAttemptHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.workspaces,
            FakeAttemptWorkspaceVerifier(), FakeProviderEventVerifier(), verifier,
            fixture.budget, fixture.budget, fixture.ids,
        )

        completed = handler(
            ReconcileGenerationAttemptCommand(CommandId(uuid(990)), fixture.job_id, fixture.attempt_id, unknown.revision)
        )
        replay = handler(
            ReconcileGenerationAttemptCommand(CommandId(uuid(991)), fixture.job_id, fixture.attempt_id, completed.revision)
        )

        job = fixture.jobs.load(fixture.job_id)
        self.assertEqual((job.generation_attempts[-1].state, len(job.takes), replay.revision), (AttemptState.COMPLETED, 1, completed.revision))
        self.assertEqual((len(fixture.gateway.calls), len(fixture.store.calls)), (1, 1))

    def test_narration_unknown_completion_recovers_once_from_verified_workspace_without_assembly_replay(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests(
            "test_success_reserves_before_external_freezes_exact_preview_bytes_and_settles_usage"
        )
        fixture.setUp()
        generated = fixture.handler()(fixture.command())
        actors = FakeActorResolver({"operator": ActorId(uuid(992))})
        fixture.ids.values[ReviewDecisionId] = [ReviewDecisionId(uuid(993))]
        fixture.ids.values[SelectionDecisionId] = [SelectionDecisionId(uuid(994))]
        fixture.ids.values[NarrationAssemblyAttemptId] = [NarrationAssemblyAttemptId(uuid(995))]
        fixture.ids.values[NarrationMasterId] = [NarrationMasterId(uuid(996))]
        fixture.ids.values[AttemptWorkspaceId] = [AttemptWorkspaceId(uuid(997))]
        reviewed = RecordReviewDecisionHandler(fixture.jobs, actors, fixture.clock, fixture.ids)(
            RecordReviewDecisionCommand(CommandId(uuid(998)), "operator", fixture.job_id, generated.take_id, ReviewOutcome.ACCEPTED, "accepted", generated.revision)
        )
        selected = SelectWorkingTakeHandler(fixture.jobs, fixture.reader, actors, fixture.clock, fixture.ids)(
            SelectWorkingTakeCommand(CommandId(uuid(999)), "operator", fixture.job_id, fixture.passage_id, generated.take_id, "selected", reviewed.revision)
        )
        fixture.store.artifact_ids.append(ArtifactId(uuid(1000)))
        fixture.jobs.reject_on_save_calls.add(fixture.jobs.save_calls + 4)
        assembler = FakeDryPcmAssembler()
        unknown = AssembleNarrationMasterHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.ids, assembler, fixture.store, fixture.workspaces,
        )(
            AssembleNarrationMasterCommand(CommandId(uuid(1001)), fixture.job_id, (), selected.revision, SafeRelativeArtifactPath("fake/recover-narration.wav"))
        )
        verifier = RecoveryArtifactEvidence(DecodedMediaFacts(CanonicalAudioFacts(), 100, 2, False))
        handler = ReconcileNarrationAssemblyAttemptHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.workspaces,
            FakeAttemptWorkspaceVerifier(), FakeProviderEventVerifier(), verifier, fixture.ids,
        )

        completed = handler(
            ReconcileNarrationAssemblyAttemptCommand(CommandId(uuid(1002)), fixture.job_id, unknown.attempt_id, unknown.revision)
        )
        replay = handler(
            ReconcileNarrationAssemblyAttemptCommand(CommandId(uuid(1003)), fixture.job_id, unknown.attempt_id, completed.revision)
        )

        job = fixture.jobs.load(fixture.job_id)
        self.assertEqual((job.assembly_attempts[-1].state, len(job.masters), replay.revision), (AttemptState.COMPLETED, 1, completed.revision))
        self.assertEqual((len(assembler.narration_calls), len(fixture.store.calls)), (1, 2))

    def test_narration_post_artifact_workspace_save_failure_never_stages_the_aggregate(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests(
            "test_success_reserves_before_external_freezes_exact_preview_bytes_and_settles_usage"
        )
        fixture.setUp()
        generated = fixture.handler()(fixture.command())
        actors = FakeActorResolver({"operator": ActorId(uuid(1010))})
        fixture.ids.values[ReviewDecisionId] = [ReviewDecisionId(uuid(1011))]
        fixture.ids.values[SelectionDecisionId] = [SelectionDecisionId(uuid(1012))]
        fixture.ids.values[NarrationAssemblyAttemptId] = [NarrationAssemblyAttemptId(uuid(1013))]
        fixture.ids.values[AttemptWorkspaceId] = [AttemptWorkspaceId(uuid(1014))]
        reviewed = RecordReviewDecisionHandler(fixture.jobs, actors, fixture.clock, fixture.ids)(
            RecordReviewDecisionCommand(CommandId(uuid(1015)), "operator", fixture.job_id, generated.take_id, ReviewOutcome.ACCEPTED, "accepted", generated.revision)
        )
        selected = SelectWorkingTakeHandler(fixture.jobs, fixture.reader, actors, fixture.clock, fixture.ids)(
            SelectWorkingTakeCommand(CommandId(uuid(1016)), "operator", fixture.job_id, fixture.passage_id, generated.take_id, "selected", reviewed.revision)
        )
        fixture.store.artifact_ids.append(ArtifactId(uuid(1017)))
        original_save = fixture.workspaces.save

        def fail_after_publication(workspace) -> None:
            if workspace.state is AttemptState.ARTIFACTS_PUBLISHED:
                raise RuntimeError("fake post-artifact workspace failure")
            original_save(workspace)

        fixture.workspaces.save = fail_after_publication
        assembler = FakeDryPcmAssembler()
        result = AssembleNarrationMasterHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.ids, assembler, fixture.store, fixture.workspaces,
        )(
            AssembleNarrationMasterCommand(CommandId(uuid(1018)), fixture.job_id, (), selected.revision, SafeRelativeArtifactPath("fake/narration-workspace-failure.wav"))
        )

        attempt = fixture.jobs.load(fixture.job_id).narration_assembly_attempt(result.attempt_id)
        self.assertEqual((result.state, attempt.state), (AttemptState.UNKNOWN, AttemptState.EXTERNAL_WORK_STARTED))
        self.assertEqual((len(assembler.narration_calls), len(fixture.store.calls)), (1, 2))
        reconciled = ReconcileNarrationAssemblyAttemptHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.workspaces,
            FakeAttemptWorkspaceVerifier(), FakeProviderEventVerifier(),
            RecoveryArtifactEvidence(DecodedMediaFacts(CanonicalAudioFacts(), 100, 2, False)), fixture.ids,
        )(
            ReconcileNarrationAssemblyAttemptCommand(CommandId(uuid(1019)), fixture.job_id, result.attempt_id, result.revision)
        )
        self.assertEqual(fixture.jobs.load(fixture.job_id).narration_assembly_attempt(result.attempt_id).state, AttemptState.UNKNOWN)
        self.assertEqual((reconciled.revision, len(assembler.narration_calls), len(fixture.store.calls)), (result.revision + 1, 1, 2))

    def test_tampered_narration_assembly_plan_is_quarantined_without_reassembly(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests(
            "test_success_reserves_before_external_freezes_exact_preview_bytes_and_settles_usage"
        )
        fixture.setUp()
        generated = fixture.handler()(fixture.command())
        actors = FakeActorResolver({"operator": ActorId(uuid(1020))})
        fixture.ids.values[ReviewDecisionId] = [ReviewDecisionId(uuid(1021))]
        fixture.ids.values[SelectionDecisionId] = [SelectionDecisionId(uuid(1022))]
        fixture.ids.values[NarrationAssemblyAttemptId] = [NarrationAssemblyAttemptId(uuid(1023))]
        fixture.ids.values[NarrationMasterId] = [NarrationMasterId(uuid(1024))]
        fixture.ids.values[AttemptWorkspaceId] = [AttemptWorkspaceId(uuid(1025))]
        reviewed = RecordReviewDecisionHandler(fixture.jobs, actors, fixture.clock, fixture.ids)(
            RecordReviewDecisionCommand(CommandId(uuid(1026)), "operator", fixture.job_id, generated.take_id, ReviewOutcome.ACCEPTED, "accepted", generated.revision)
        )
        selected = SelectWorkingTakeHandler(fixture.jobs, fixture.reader, actors, fixture.clock, fixture.ids)(
            SelectWorkingTakeCommand(CommandId(uuid(1027)), "operator", fixture.job_id, fixture.passage_id, generated.take_id, "selected", reviewed.revision)
        )
        fixture.store.artifact_ids.append(ArtifactId(uuid(1028)))
        fixture.jobs.reject_on_save_calls.add(fixture.jobs.save_calls + 4)
        assembler = FakeDryPcmAssembler()
        unknown = AssembleNarrationMasterHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.ids, assembler, fixture.store, fixture.workspaces,
        )(
            AssembleNarrationMasterCommand(CommandId(uuid(1029)), fixture.job_id, (), selected.revision, SafeRelativeArtifactPath("fake/tampered-narration-plan.wav"))
        )
        workspace = fixture.workspaces.load(unknown.attempt_id)
        fixture.workspaces.values[unknown.attempt_id] = replace(
            workspace,
            frozen_plan_digest=narration_assembly_plan_digest((TakeId(uuid(1030)),), ()),
        )
        reconciled = ReconcileNarrationAssemblyAttemptHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.workspaces,
            FakeAttemptWorkspaceVerifier(), FakeProviderEventVerifier(),
            RecoveryArtifactEvidence(DecodedMediaFacts(CanonicalAudioFacts(), 100, 2, False)), fixture.ids,
        )(
            ReconcileNarrationAssemblyAttemptCommand(CommandId(uuid(1031)), fixture.job_id, unknown.attempt_id, unknown.revision)
        )

        self.assertEqual(fixture.jobs.load(fixture.job_id).narration_assembly_attempt(unknown.attempt_id).state, AttemptState.QUARANTINED)
        self.assertEqual((reconciled.revision, len(assembler.narration_calls), len(fixture.store.calls)), (unknown.revision + 1, 1, 2))

    def test_episode_unknown_completion_recovers_once_from_verified_workspace_without_assembly_replay(self) -> None:
        case = episode_fixture.EpisodeApplicationTests("test_complete_exact_episode_timing_fallback_correction_and_presentation_handoff")
        flow, episode_id, _, _, configured = case.configured()
        attempt_id = EpisodeAssemblyAttemptId(uuid(1004))
        flow.add(EpisodeAssemblyAttemptId, attempt_id)
        flow.add(EpisodeSpeechMasterId, EpisodeSpeechMasterId(uuid(1005)))
        flow.add(AttemptWorkspaceId, AttemptWorkspaceId(uuid(1006)))
        flow.episodes.reject_on_save_calls.add(flow.episodes.save_calls + 4)
        unknown = AssembleEpisodeSpeechMasterHandler(
            flow.episodes, flow.jobs, flow.authority, flow.clock, flow.ids,
            flow.assembler, flow.artifacts, flow.workspaces,
        )(
            AssembleEpisodeSpeechMasterCommand(CommandId(uuid(1007)), episode_id, configured.revision, SafeRelativeArtifactPath("fake/recover-episode.wav"))
        )
        artifact_calls_before_recovery = len(flow.artifacts.calls)
        verifier = RecoveryArtifactEvidence(DecodedMediaFacts(CanonicalAudioFacts(), 250, 5, False))
        handler = ReconcileEpisodeAssemblyAttemptHandler(
            flow.episodes, flow.jobs, flow.authority, flow.clock, flow.workspaces,
            FakeAttemptWorkspaceVerifier(), FakeProviderEventVerifier(), verifier, flow.ids,
        )

        completed = handler(
            ReconcileEpisodeAssemblyAttemptCommand(CommandId(uuid(1008)), episode_id, attempt_id, unknown.revision)
        )
        replay = handler(
            ReconcileEpisodeAssemblyAttemptCommand(CommandId(uuid(1009)), episode_id, attempt_id, completed.revision)
        )

        episode = flow.episodes.load(episode_id)
        self.assertEqual((episode.assembly_attempts[-1].state, len(episode.speech_masters), replay.revision), (AttemptState.COMPLETED, 1, completed.revision))
        self.assertEqual((len(flow.assembler.episode_calls), len(flow.artifacts.calls)), (1, artifact_calls_before_recovery))
        self.assertEqual(flow.workspaces.load(attempt_id).state, AttemptState.ARTIFACTS_PUBLISHED)


if __name__ == "__main__":
    unittest.main()
