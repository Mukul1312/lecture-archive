"""Complete no-network source-master workflow through root-issued snapshot."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ArtifactId
from heritage_archive.contexts.narrator_voice.application.commands import (
    AssembleNarrationMasterCommand,
    IssueNarrationMasterSnapshotCommand,
    RecordNarrationMasterListeningCommand,
    RecordReviewDecisionCommand,
    SelectWorkingTakeCommand,
    ShowNarrationStatusCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    AssembleNarrationMasterHandler,
    IssueNarrationMasterSnapshotHandler,
    RecordNarrationMasterListeningHandler,
    RecordReviewDecisionHandler,
    SelectWorkingTakeHandler,
    ShowNarrationStatusHandler,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import ListeningOutcome, ReviewAuthority, ReviewOutcome
from heritage_archive.contexts.narrator_voice.domain.ids import (
    CommandId,
    MasterListeningDecisionId,
    NarrationAssemblyAttemptId,
    NarrationMasterId,
    NarrationMasterSnapshotId,
    ReviewDecisionId,
    SelectionDecisionId,
)
from heritage_archive.contexts.narrator_voice.domain.values import SafeRelativeArtifactPath
from tests.heritage_archive.narrator_voice.fakes import FakeActorResolver, FakeDryPcmAssembler
from tests.heritage_archive.narrator_voice.fixtures import uuid
from tests.heritage_archive.narrator_voice import test_application_generation as generation_fixture


class SourceWorkflowApplicationTests(unittest.TestCase):
    def test_generation_review_selection_dry_assembly_listening_and_snapshot(self) -> None:
        fixture = generation_fixture.GenerationApplicationTests("test_success_reserves_before_external_freezes_exact_preview_bytes_and_settles_usage")
        fixture.setUp()
        generated = fixture.handler()(fixture.command())
        actor = ActorId(uuid(930))
        actors = FakeActorResolver({"fake-reviewer": actor})
        fixture.ids.values[ReviewDecisionId] = [ReviewDecisionId(uuid(931))]
        fixture.ids.values[SelectionDecisionId] = [SelectionDecisionId(uuid(932))]
        fixture.ids.values[NarrationAssemblyAttemptId] = [NarrationAssemblyAttemptId(uuid(933))]
        fixture.ids.values[NarrationMasterId] = [NarrationMasterId(uuid(934))]
        fixture.ids.values[MasterListeningDecisionId] = [MasterListeningDecisionId(uuid(935))]
        fixture.ids.values[NarrationMasterSnapshotId] = [NarrationMasterSnapshotId(uuid(936))]
        from heritage_archive.contexts.narrator_voice.domain.ids import AttemptWorkspaceId
        fixture.ids.values[AttemptWorkspaceId] = [AttemptWorkspaceId(uuid(944))]

        reviewed = RecordReviewDecisionHandler(fixture.jobs, actors, fixture.clock, fixture.ids)(
            RecordReviewDecisionCommand(
                CommandId(uuid(937)), "fake-reviewer", fixture.job_id, generated.take_id,
                ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake operational pass", generated.revision,
            )
        )
        selected = SelectWorkingTakeHandler(fixture.jobs, fixture.reader, actors, fixture.clock, fixture.ids)(
            SelectWorkingTakeCommand(
                CommandId(uuid(938)), "fake-reviewer", fixture.job_id, fixture.passage_id,
                generated.take_id, "fake working selection", reviewed.revision,
            )
        )
        assembler = FakeDryPcmAssembler()
        fixture.store.artifact_ids.append(ArtifactId(uuid(939)))
        assembled = AssembleNarrationMasterHandler(
            fixture.jobs, fixture.reader, fixture.clock, fixture.ids, assembler, fixture.store, fixture.workspaces,
        )(
            AssembleNarrationMasterCommand(
                CommandId(uuid(940)), fixture.job_id, (), selected.revision,
                SafeRelativeArtifactPath("fake/diary-master.wav"),
            )
        )
        listened = RecordNarrationMasterListeningHandler(fixture.jobs, actors, fixture.clock, fixture.ids)(
            RecordNarrationMasterListeningCommand(
                CommandId(uuid(941)), "fake-reviewer", fixture.job_id, assembled.master_id,
                ListeningOutcome.PASSED, "fake whole-master pass", assembled.revision,
            )
        )
        issued = IssueNarrationMasterSnapshotHandler(fixture.jobs, fixture.reader, fixture.clock, fixture.ids)(
            IssueNarrationMasterSnapshotCommand(
                CommandId(uuid(942)), fixture.job_id, assembled.master_id, listened.revision,
            )
        )
        status = ShowNarrationStatusHandler(fixture.jobs)(ShowNarrationStatusCommand(CommandId(uuid(943)), fixture.job_id))
        self.assertEqual((issued.snapshot.source_master_id, status.master_count, status.snapshot_count), (assembled.master_id, 1, 1))
        self.assertEqual((len(assembler.narration_calls), issued.snapshot.passage_offsets[0].start_sample), (1, 0))
        self.assertEqual(actors.calls, ["fake-reviewer", "fake-reviewer", "fake-reviewer"])


if __name__ == "__main__":
    unittest.main()
