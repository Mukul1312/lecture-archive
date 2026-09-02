"""NarrationJob review, selection, mastering, listening and snapshot tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ValidationError
from heritage_archive.contexts.narrator_voice.application.schema_v1 import decode_schema_v1, encode_schema_v1
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptState,
    ListeningOutcome,
    PassageOffset,
    ReviewAuthority,
    ReviewOutcome,
)
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, DomainInvariantError
from heritage_archive.contexts.narrator_voice.domain.ids import (
    MasterListeningDecisionId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    NarrationMasterSnapshotId,
    PassageId,
    ReviewDecisionId,
    SelectionDecisionId,
)
from heritage_archive.contexts.narrator_voice.domain.narration_job import (
    NarrationJob,
    NarrationJobSnapshot,
    PassageDraft,
    prepare_lane_b_diary_job,
)
from heritage_archive.contexts.narrator_voice.domain.values import ComponentRole, Lane, PassageText
from tests.heritage_archive.narrator_voice.fixtures import (
    NOW,
    make_artifact,
    make_authority,
    make_contract,
    make_defaults,
    make_recipe,
    make_take,
    uuid,
)


class NarrationJobMasteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = ActorId(uuid(300))
        self.job_id = NarrationJobId(uuid(301))
        self.passage_a = PassageId(uuid(302))
        self.passage_b = PassageId(uuid(303))
        self.text_a = PassageText("ଅଆ")
        self.text_b = PassageText("ଇଈଉ")
        self.contract = make_contract(lane=Lane.B)
        self.job = prepare_lane_b_diary_job(
            self.job_id, self.contract, make_defaults(),
            (PassageDraft(self.passage_a, 0, self.text_a), PassageDraft(self.passage_b, 1, self.text_b)), NOW,
        )
        self.recipe_a = make_recipe(self.text_a, recipe_index=304)
        self.recipe_b = make_recipe(self.text_b, recipe_index=305)
        self.job.record_render_recipe(self.passage_a, self.recipe_a, expected_revision=1)
        self.job.record_render_recipe(self.passage_b, self.recipe_b, expected_revision=2)
        self.take_a = make_take(job_id=self.job_id, passage_id=self.passage_a, text=self.text_a, recipe=self.recipe_a, contract=self.contract, take_index=306, attempt_index=307)
        self.take_b = make_take(job_id=self.job_id, passage_id=self.passage_b, text=self.text_b, recipe=self.recipe_b, contract=self.contract, take_index=308, attempt_index=309)
        self.job.record_take(self.take_a, expected_revision=3)
        self.job.record_take(self.take_b, expected_revision=4)

    def accept_and_select(self) -> None:
        self.job.record_review_decision(ReviewDecisionId(uuid(310)), self.take_a.take_id, self.actor, ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake accepted a", NOW, expected_revision=5)
        self.job.record_review_decision(ReviewDecisionId(uuid(311)), self.take_b.take_id, self.actor, ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake accepted b", NOW, expected_revision=6)
        self.job.select_working_take(SelectionDecisionId(uuid(312)), self.passage_a, self.take_a.take_id, self.actor, True, NOW, expected_revision=7)
        self.job.select_working_take(SelectionDecisionId(uuid(313)), self.passage_b, self.take_b.take_id, self.actor, True, NOW, expected_revision=8)

    def assemble(self) -> None:
        self.accept_and_select()
        attempt_id = NarrationAssemblyAttemptId(uuid(314))
        self.job.reserve_narration_assembly(attempt_id, (25,), True, NOW, expected_revision=9)
        self.job.freeze_narration_assembly_input(attempt_id, expected_revision=10)
        self.job.mark_narration_assembly_work_started(attempt_id, expected_revision=11)
        artifact, media = make_artifact(315, "narration-master", samples=self.take_a.media.sample_count + 25 + self.take_b.media.sample_count)
        offsets = (
            PassageOffset(self.passage_a, 1, self.text_a.digest, 0, self.take_a.media.sample_count),
            PassageOffset(self.passage_b, 1, self.text_b.digest, self.take_a.media.sample_count + 25, media.sample_count),
        )
        self.job.stage_narration_master(attempt_id, artifact, media, offsets, expected_revision=12)
        self.job.mark_narration_master_published(attempt_id, expected_revision=13)
        self.job.complete_narration_assembly(attempt_id, NarrationMasterId(uuid(316)), NOW, expected_revision=14)

    def test_INV_NJ_5_review_and_selection_are_append_only_and_only_current_accepted_eligible_take_can_be_selected(self) -> None:
        with self.assertRaises(DomainInvariantError):
            self.job.select_working_take(SelectionDecisionId(uuid(312)), self.passage_a, self.take_a.take_id, self.actor, True, NOW, expected_revision=5)
        self.job.record_review_decision(ReviewDecisionId(uuid(310)), self.take_a.take_id, self.actor, ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake accepted", NOW, expected_revision=5)
        self.job.select_working_take(SelectionDecisionId(uuid(312)), self.passage_a, self.take_a.take_id, self.actor, True, NOW, expected_revision=6)
        first = self.job.selections[0]
        self.job.record_review_decision(ReviewDecisionId(uuid(311)), self.take_a.take_id, self.actor, ReviewAuthority.OPERATIONAL, ReviewOutcome.REJECTED, "fake later reject", NOW, expected_revision=7)
        with self.assertRaises(DomainInvariantError):
            self.job.select_working_take(SelectionDecisionId(uuid(313)), self.passage_a, self.take_a.take_id, self.actor, True, NOW, expected_revision=8)
        self.assertEqual(self.job.selections, (first,))
        with self.assertRaises(FrozenInstanceError):
            first.take_id = self.take_b.take_id  # type: ignore[misc]

    def test_INV_NJ_6_and_INV_NJ_7_master_requires_one_selected_current_eligible_take_per_passage_and_current_authority(self) -> None:
        self.job.record_review_decision(ReviewDecisionId(uuid(310)), self.take_a.take_id, self.actor, ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake accepted", NOW, expected_revision=5)
        self.job.select_working_take(SelectionDecisionId(uuid(312)), self.passage_a, self.take_a.take_id, self.actor, True, NOW, expected_revision=6)
        with self.assertRaises(DomainInvariantError):
            self.job.reserve_narration_assembly(NarrationAssemblyAttemptId(uuid(314)), (25,), True, NOW, expected_revision=7)
        self.job.record_review_decision(ReviewDecisionId(uuid(311)), self.take_b.take_id, self.actor, ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake accepted b", NOW, expected_revision=7)
        self.job.select_working_take(SelectionDecisionId(uuid(313)), self.passage_b, self.take_b.take_id, self.actor, True, NOW, expected_revision=8)
        with self.assertRaises(AuthorizationDenied):
            self.job.reserve_narration_assembly(NarrationAssemblyAttemptId(uuid(314)), (25,), False, NOW, expected_revision=9)
        self.assertEqual(self.job.revision, 9)

    def test_INV_NJ_9_human_decisions_require_exact_server_resolved_actor_id(self) -> None:
        with self.assertRaises(ValidationError):
            self.job.record_review_decision(ReviewDecisionId(uuid(310)), self.take_a.take_id, uuid(300), ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake", NOW, expected_revision=5)  # type: ignore[arg-type]
        self.assertEqual(self.job.reviews, ())

    def test_INV_NJ_17_snapshot_requires_current_master_passing_operational_listening_and_current_authority(self) -> None:
        self.assemble()
        master = self.job.masters[0]
        with self.assertRaises(DomainInvariantError):
            self.job.issue_narration_master_snapshot(NarrationMasterSnapshotId(uuid(317)), master.master_id, make_authority(), True, NOW, expected_revision=15)
        self.job.record_narration_master_listening(MasterListeningDecisionId(uuid(318)), master.master_id, self.actor, ListeningOutcome.PASSED, "fake whole-master pass", NOW, expected_revision=15)
        with self.assertRaises(AuthorizationDenied):
            self.job.issue_narration_master_snapshot(NarrationMasterSnapshotId(uuid(317)), master.master_id, make_authority(), False, NOW, expected_revision=16)
        snapshot = self.job.issue_narration_master_snapshot(NarrationMasterSnapshotId(uuid(317)), master.master_id, make_authority(), True, NOW, expected_revision=16)
        self.assertEqual((snapshot.source_master_id, snapshot.listening_decision.master_id, snapshot.role), (master.master_id, master.master_id, ComponentRole.DIARY))

    def test_INV_NJ_18_master_and_issued_snapshot_preserve_explicit_gaps_and_sample_accurate_offsets(self) -> None:
        self.assemble()
        master = self.job.masters[0]
        self.job.record_narration_master_listening(MasterListeningDecisionId(uuid(318)), master.master_id, self.actor, ListeningOutcome.PASSED, "fake pass", NOW, expected_revision=15)
        snapshot = self.job.issue_narration_master_snapshot(NarrationMasterSnapshotId(uuid(317)), master.master_id, make_authority(), True, NOW, expected_revision=16)
        self.assertEqual(master.gaps_samples, (25,))
        self.assertEqual(master.passage_offsets[1].start_sample, self.take_a.media.sample_count + 25)
        self.assertEqual((snapshot.gaps_samples, snapshot.passage_offsets), (master.gaps_samples, master.passage_offsets))

    def test_narration_assembly_attempts_reconcile_conservatively_and_snapshot_schema_round_trips(self) -> None:
        self.assemble()
        master = self.job.masters[0]
        self.job.record_narration_master_listening(MasterListeningDecisionId(uuid(318)), master.master_id, self.actor, ListeningOutcome.PASSED, "fake pass", NOW, expected_revision=15)
        self.job.issue_narration_master_snapshot(NarrationMasterSnapshotId(uuid(317)), master.master_id, make_authority(), True, NOW, expected_revision=16)
        raw = encode_schema_v1(self.job.to_snapshot())
        restored = NarrationJob.from_snapshot(decode_schema_v1(raw, NarrationJobSnapshot))
        self.assertEqual(restored.to_snapshot(), self.job.to_snapshot())
        self.assertEqual(encode_schema_v1(restored.to_snapshot()), raw)

    def test_unknown_narration_assembly_reconciles_once_to_conservative_terminal_evidence(self) -> None:
        self.accept_and_select()
        attempt_id = NarrationAssemblyAttemptId(uuid(319))
        self.job.reserve_narration_assembly(attempt_id, (25,), True, NOW, expected_revision=9)
        self.job.finalize_narration_assembly_outcome(
            attempt_id, AttemptState.UNKNOWN, "fake ambiguous dry assembly", NOW, expected_revision=10,
        )
        self.job.reconcile_narration_assembly(
            attempt_id, AttemptState.QUARANTINED, "fake workspace digest mismatch", NOW, expected_revision=11,
        )
        self.assertEqual(self.job.assembly_attempts[-1].state, AttemptState.QUARANTINED)
        with self.assertRaises(DomainInvariantError):
            self.job.reconcile_narration_assembly(
                attempt_id, AttemptState.FAILED, "cannot rewrite terminal", NOW, expected_revision=12,
            )


if __name__ == "__main__":
    unittest.main()
