"""NarrationJob generation-attempt state machine and recovery tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ArtifactId, ArtifactRef, ValidationError
from heritage_archive.contexts.narrator_voice.application.schema_v1 import decode_schema_v1, encode_schema_v1
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    DecodedMediaFacts,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
    SubmissionEvidence,
)
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, DomainInvariantError, RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    BudgetReservationId,
    GenerationAttemptId,
    NarrationJobId,
    PassageId,
    ProviderEventId,
)
from heritage_archive.contexts.narrator_voice.domain.narration_job import (
    NarrationJob,
    NarrationJobSnapshot,
    PassageDraft,
    prepare_lane_b_diary_job,
)
from heritage_archive.contexts.narrator_voice.domain.values import Lane, PassageText
from tests.heritage_archive.narrator_voice.fixtures import (
    NOW,
    digest,
    make_contract,
    make_defaults,
    make_esi,
    make_preview,
    make_recipe,
    make_take,
    uuid,
)


class NarrationJobAttemptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job_id = NarrationJobId(uuid(200))
        self.passage_id = PassageId(uuid(201))
        self.text = PassageText("ଅଆ")
        self.contract = make_contract(lane=Lane.B)
        self.job = prepare_lane_b_diary_job(
            self.job_id, self.contract, make_defaults(),
            (PassageDraft(self.passage_id, 0, self.text),), NOW,
        )
        self.recipe = make_recipe(self.text, recipe_index=202)
        self.job.record_render_recipe(self.passage_id, self.recipe, expected_revision=1)
        self.preview = make_preview(
            job_id=self.job_id, base_revision=2, passage_id=self.passage_id,
            text=self.text, recipe=self.recipe, contract=self.contract, preview_index=203,
        )
        self.job.issue_generation_preview(self.preview, expected_revision=2)
        self.attempt_id = GenerationAttemptId(uuid(204))
        self.budget_id = BudgetReservationId(uuid(205))

    def reserve(self) -> None:
        self.job.reserve_generation_attempt(
            self.attempt_id, self.budget_id, self.preview.preview_id, NOW,
            expected_revision=3,
        )

    def test_every_attempt_stage_increments_revision_and_stale_revision_has_no_mutation(self) -> None:
        self.reserve()
        self.assertEqual((self.job.revision, self.job.generation_attempts[0].state), (4, AttemptState.RESERVED))
        before = self.job.to_snapshot()
        with self.assertRaises(RevisionConflict):
            self.job.freeze_generation_input(self.attempt_id, make_esi(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract), expected_revision=3)
        self.assertEqual(self.job.to_snapshot(), before)

    def test_INV_NJ_2_and_INV_NJ_12_completed_take_binds_exact_attempt_text_recipe_settings_authority_input_and_artifact(self) -> None:
        self.reserve()
        esi = make_esi(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract)
        self.job.freeze_generation_input(self.attempt_id, esi, expected_revision=4)
        self.job.mark_generation_external_work_started(self.attempt_id, NOW, expected_revision=5)
        raw = ArtifactRef(ArtifactId(uuid(206)), digest("fake-event"), 12, "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(uuid(207)), 0, ProviderEventKind.TERMINAL, raw,
            raw.content_digest, NOW, "fake-request", "fake-response", None, None,
            "15", ProviderTerminalClass.SUCCESS,
        )
        take = make_take(
            job_id=self.job_id, passage_id=self.passage_id, text=self.text,
            recipe=self.recipe, contract=self.contract, take_index=208, attempt_index=204,
        )
        self.job.stage_generation_artifacts(self.attempt_id, (event,), take.artifact, take.media, expected_revision=6)
        self.job.mark_generation_artifacts_published(self.attempt_id, expected_revision=7)
        self.job.complete_generation_attempt(self.attempt_id, take, NOW, expected_revision=8)
        attempt = self.job.generation_attempts[0]
        self.assertEqual((self.job.revision, attempt.state, attempt.submission, attempt.take_id), (9, AttemptState.COMPLETED, SubmissionEvidence.COMPLETED, take.take_id))
        self.assertEqual(self.job.takes, (take,))
        self.assertEqual(take.effective_input.request_digest, esi.request_digest)

    def test_generation_staging_rejects_silence_and_non_success_terminal_streams(self) -> None:
        self.reserve()
        esi = make_esi(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract)
        self.job.freeze_generation_input(self.attempt_id, esi, expected_revision=4)
        self.job.mark_generation_external_work_started(self.attempt_id, NOW, expected_revision=5)
        raw = ArtifactRef(ArtifactId(uuid(210)), digest("fake-failed-event"), 12, "application/json")
        failed = ProviderEventEvidence(
            ProviderEventId(uuid(211)), 0, ProviderEventKind.ERROR, raw,
            raw.content_digest, NOW, "fake-request", None, None, None, None,
            ProviderTerminalClass.FAILURE,
        )
        take = make_take(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract, take_index=212, attempt_index=204)
        silent = DecodedMediaFacts(take.media.audio, take.media.sample_count, take.media.duration_ms, True)
        with self.assertRaises(ValidationError):
            self.job.stage_generation_artifacts(self.attempt_id, (failed,), take.artifact, take.media, expected_revision=6)
        with self.assertRaises(ValidationError):
            self.job.stage_generation_artifacts(self.attempt_id, (), take.artifact, silent, expected_revision=6)

    def test_rehydration_rejects_completed_attempt_without_its_exact_take(self) -> None:
        self.reserve()
        esi = make_esi(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract)
        self.job.freeze_generation_input(self.attempt_id, esi, expected_revision=4)
        self.job.mark_generation_external_work_started(self.attempt_id, NOW, expected_revision=5)
        raw = ArtifactRef(ArtifactId(uuid(213)), digest("fake-success-event"), 12, "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(uuid(214)), 0, ProviderEventKind.TERMINAL, raw,
            raw.content_digest, NOW, "fake-request", "fake-response", None, None,
            "15", ProviderTerminalClass.SUCCESS,
        )
        take = make_take(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract, take_index=215, attempt_index=204)
        self.job.stage_generation_artifacts(self.attempt_id, (event,), take.artifact, take.media, expected_revision=6)
        self.job.mark_generation_artifacts_published(self.attempt_id, expected_revision=7)
        self.job.complete_generation_attempt(self.attempt_id, take, NOW, expected_revision=8)
        with self.assertRaises(ValidationError):
            NarrationJob.from_snapshot(replace(self.job.to_snapshot(), takes=()))

    def test_INV_NJ_3_take_and_terminal_attempt_history_are_immutable(self) -> None:
        self.reserve()
        self.job.finalize_generation_outcome(
            self.attempt_id, AttemptState.BLOCKED, SubmissionEvidence.DEFINITELY_NOT_SENT,
            "fake authority unavailable", NOW, expected_revision=4,
        )
        attempt = self.job.generation_attempts[0]
        with self.assertRaises(FrozenInstanceError):
            attempt.reason = "rewrite"  # type: ignore[misc]
        with self.assertRaises(DomainInvariantError):
            self.job.finalize_generation_outcome(
                self.attempt_id, AttemptState.FAILED, SubmissionEvidence.DEFINITELY_NOT_SENT,
                "rewrite terminal", NOW, expected_revision=5,
            )
        self.assertEqual(self.job.generation_attempts[0], attempt)

    def test_attempt_order_and_exact_preview_transmitted_bytes_are_enforced(self) -> None:
        self.reserve()
        with self.assertRaises(DomainInvariantError):
            self.job.mark_generation_external_work_started(self.attempt_id, NOW, expected_revision=4)
        other_text = PassageText("ଇ")
        other_recipe = make_recipe(other_text, recipe_index=209)
        mismatched = make_esi(job_id=self.job_id, passage_id=self.passage_id, text=other_text, recipe=other_recipe, contract=self.contract)
        with self.assertRaises(ValidationError):
            self.job.freeze_generation_input(self.attempt_id, mismatched, expected_revision=4)
        exact = make_esi(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract)
        self.job.freeze_generation_input(self.attempt_id, exact, expected_revision=4)
        self.assertEqual(exact.rendered_transcript_bytes, self.preview.rendered_transcript_bytes)

    def test_unknown_attempt_reconciliation_moves_only_from_recorded_evidence_to_terminal(self) -> None:
        self.reserve()
        self.job.freeze_generation_input(self.attempt_id, make_esi(job_id=self.job_id, passage_id=self.passage_id, text=self.text, recipe=self.recipe, contract=self.contract), expected_revision=4)
        self.job.mark_generation_external_work_started(self.attempt_id, NOW, expected_revision=5)
        self.job.finalize_generation_outcome(
            self.attempt_id, AttemptState.UNKNOWN, SubmissionEvidence.AMBIGUOUS,
            "fake ambiguous outcome", NOW, expected_revision=6,
        )
        with self.assertRaises(DomainInvariantError):
            self.job.finalize_generation_outcome(
                self.attempt_id, AttemptState.FAILED, SubmissionEvidence.COMPLETED,
                "cannot bypass reconciliation", NOW, expected_revision=7,
            )
        self.job.reconcile_generation_attempt(
            self.attempt_id, AttemptState.QUARANTINED, "recorded fake provider evidence",
            NOW, expected_revision=7,
        )
        self.assertEqual((self.job.revision, self.job.generation_attempts[0].state), (8, AttemptState.QUARANTINED))
        with self.assertRaises(DomainInvariantError):
            self.job.reconcile_generation_attempt(
                self.attempt_id, AttemptState.COMPLETED, "cannot rewrite terminal",
                NOW, expected_revision=8,
            )

    def test_unknown_generation_recovers_exact_completed_take_once_from_workspace_evidence(self) -> None:
        self.reserve()
        esi = make_esi(
            job_id=self.job_id, passage_id=self.passage_id, text=self.text,
            recipe=self.recipe, contract=self.contract,
        )
        self.job.freeze_generation_input(self.attempt_id, esi, expected_revision=4)
        self.job.mark_generation_external_work_started(self.attempt_id, NOW, expected_revision=5)
        self.job.finalize_generation_outcome(
            self.attempt_id, AttemptState.UNKNOWN, SubmissionEvidence.AMBIGUOUS,
            "fake aggregate finalization ambiguity", NOW, expected_revision=6,
        )
        raw = ArtifactRef(ArtifactId(uuid(216)), digest("recovered-event"), 12, "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(uuid(217)), 0, ProviderEventKind.TERMINAL, raw,
            raw.content_digest, NOW, "fake-request", "fake-response", None, None,
            "15", ProviderTerminalClass.SUCCESS,
        )
        take = make_take(
            job_id=self.job_id, passage_id=self.passage_id, text=self.text,
            recipe=self.recipe, contract=self.contract, take_index=218, attempt_index=204,
        )
        attempt = self.job.generation_attempt(self.attempt_id)
        workspace = AttemptWorkspaceEvidence(
            AttemptWorkspaceId(uuid(219)), AttemptKind.GENERATION, self.job_id,
            self.attempt_id, attempt.reservation_revision, self.budget_id,
            self.preview.preview_digest, esi.request_digest, esi.request_digest,
            SubmissionEvidence.COMPLETED,
            (event,), (take.artifact.reference,), (take.artifact,),
            ("fake verifier sealed exact workspace evidence",), AttemptState.COMPLETED,
        )

        before = self.job.to_snapshot()
        with self.assertRaises(AuthorizationDenied):
            self.job.recover_generation_completion(
                self.attempt_id, workspace, take, False, NOW,
                expected_revision=self.job.revision,
            )
        with self.assertRaises(ValidationError):
            self.job.recover_generation_completion(
                self.attempt_id, replace(workspace, effective_input_digest=digest("wrong")),
                take, True, NOW, expected_revision=self.job.revision,
            )
        self.assertEqual(self.job.to_snapshot(), before)

        recovered = self.job.recover_generation_completion(
            self.attempt_id, workspace, take, True, NOW,
            expected_revision=self.job.revision,
        )
        completed_revision = self.job.revision
        again = self.job.recover_generation_completion(
            self.attempt_id, workspace, take, True, NOW,
            expected_revision=completed_revision,
        )
        self.assertEqual((recovered, again), (take, take))
        self.assertEqual((self.job.revision, self.job.takes), (completed_revision, (take,)))
        self.assertEqual(self.job.generation_attempt(self.attempt_id).state, AttemptState.COMPLETED)

    def test_schema_v1_round_trip_freezes_job_attempt_preview_esi_event_and_take_histories(self) -> None:
        self.reserve()
        self.job.finalize_generation_outcome(
            self.attempt_id, AttemptState.BLOCKED, SubmissionEvidence.DEFINITELY_NOT_SENT,
            "fake blocked", NOW, expected_revision=4,
        )
        snapshot = self.job.to_snapshot()
        raw = encode_schema_v1(snapshot)
        restored = NarrationJob.from_snapshot(decode_schema_v1(raw, NarrationJobSnapshot))
        self.assertEqual(restored.to_snapshot(), snapshot)
        self.assertEqual(encode_schema_v1(restored.to_snapshot()), raw)


if __name__ == "__main__":
    unittest.main()
