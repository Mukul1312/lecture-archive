"""Episode application two-source rechecks, exact assembly, timing and handoff tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ArtifactId
from heritage_archive.contexts.narrator_voice.application.commands import (
    AssembleEpisodeSpeechMasterCommand,
    AttachDiaryMasterCommand,
    AttachIntroMasterCommand,
    BuildTimedNarrationPackageCommand,
    ExportPresentationHandoffCommand,
    PrepareDiaryEpisodeCommand,
    RecordEpisodeListeningCommand,
    RecordTimingCorrectionCommand,
    ReconcileEpisodeAssemblyAttemptCommand,
    SetIntroDiaryGapCommand,
    ShowEpisodeStatusCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    AssembleEpisodeSpeechMasterHandler,
    AttachDiaryMasterHandler,
    AttachIntroMasterHandler,
    BuildTimedNarrationPackageHandler,
    ExportPresentationHandoffHandler,
    PrepareDiaryEpisodeHandler,
    RecordEpisodeListeningHandler,
    RecordTimingCorrectionHandler,
    ReconcileEpisodeAssemblyAttemptHandler,
    SetIntroDiaryGapHandler,
    ShowEpisodeStatusHandler,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptState,
    CueProvenance,
    ListeningOutcome,
    TimingReviewStatus,
)
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    CommandId,
    CueId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeListeningDecisionId,
    EpisodeSpeechMasterId,
    TimedNarrationPackageId,
)
from heritage_archive.contexts.narrator_voice.domain.values import Lane, PassageText, SafeRelativeArtifactPath
from tests.heritage_archive.narrator_voice.fakes import FakeTimingNormalizer
from tests.heritage_archive.narrator_voice.fixtures import uuid
from tests.heritage_archive.narrator_voice.workflow import NoNetworkWorkflow


class EpisodeApplicationTests(unittest.TestCase):
    def configured(self):
        flow = NoNetworkWorkflow()
        episode_id = DiaryEpisodeId(uuid(1300))
        flow.add(DiaryEpisodeId, episode_id)
        prepared = PrepareDiaryEpisodeHandler(flow.episodes, flow.clock, flow.ids)(
            PrepareDiaryEpisodeCommand(CommandId(uuid(1301)))
        )
        intro = flow.produce_source(Lane.C, episode_id=episode_id, base=1310)
        diary = flow.produce_source(Lane.B, base=1350)
        attached_intro = AttachIntroMasterHandler(flow.episodes, flow.jobs, flow.authority, flow.clock)(
            AttachIntroMasterCommand(CommandId(uuid(1302)), episode_id, intro, prepared.revision)
        )
        attached_diary = AttachDiaryMasterHandler(flow.episodes, flow.jobs, flow.authority, flow.clock)(
            AttachDiaryMasterCommand(CommandId(uuid(1303)), episode_id, diary, attached_intro.revision)
        )
        configured = SetIntroDiaryGapHandler(flow.episodes, flow.clock)(
            SetIntroDiaryGapCommand(CommandId(uuid(1304)), episode_id, 50, attached_diary.revision)
        )
        return flow, episode_id, intro, diary, configured

    def assembled_and_listened(self):
        flow, episode_id, intro, diary, configured = self.configured()
        flow.add(EpisodeAssemblyAttemptId, EpisodeAssemblyAttemptId(uuid(1305)))
        flow.add(EpisodeSpeechMasterId, EpisodeSpeechMasterId(uuid(1306)))
        flow.add(AttemptWorkspaceId, AttemptWorkspaceId(uuid(1307)))
        assembled = AssembleEpisodeSpeechMasterHandler(
            flow.episodes, flow.jobs, flow.authority, flow.clock, flow.ids,
            flow.assembler, flow.artifacts, flow.workspaces,
        )(
            AssembleEpisodeSpeechMasterCommand(
                CommandId(uuid(1308)), episode_id, configured.revision,
                SafeRelativeArtifactPath("fake/episode-master.wav"),
            )
        )
        flow.add(EpisodeListeningDecisionId, EpisodeListeningDecisionId(uuid(1309)))
        listened = RecordEpisodeListeningHandler(flow.episodes, flow.actors, flow.clock, flow.ids)(
            RecordEpisodeListeningCommand(
                CommandId(uuid(1378)), "fake-operator", episode_id, assembled.master_id,
                ListeningOutcome.PASSED, "fake episode pass", assembled.revision,
            )
        )
        return flow, episode_id, intro, diary, assembled, listened

    def test_complete_exact_episode_timing_fallback_correction_and_presentation_handoff(self) -> None:
        flow, episode_id, intro, diary, assembled, listened = self.assembled_and_listened()
        flow.add(TimedNarrationPackageId, TimedNarrationPackageId(uuid(1379)), TimedNarrationPackageId(uuid(1380)))
        normalizer = FakeTimingNormalizer([CueId(uuid(1381)), CueId(uuid(1382))])
        timed = BuildTimedNarrationPackageHandler(
            flow.episodes, flow.jobs, flow.authority, flow.clock, flow.ids, normalizer,
        )(
            BuildTimedNarrationPackageCommand(
                CommandId(uuid(1383)), episode_id, assembled.master_id, (), listened.revision,
            )
        )
        first = flow.episodes.load(episode_id).timing_packages[-1]
        corrected_cues = (
            first.cues[0],
            replace(
                first.cues[1], cue_id=CueId(uuid(1384)),
                start_sample=first.cues[1].start_sample + 1,
                provenance=CueProvenance.MANUAL_CORRECTION,
                source="fake manual correction", source_version="v2",
                review_status=TimingReviewStatus.HUMAN_REVIEWED,
            ),
        )
        corrected = RecordTimingCorrectionHandler(
            flow.episodes, flow.jobs, flow.authority, flow.actors, flow.clock, flow.ids
        )(
            RecordTimingCorrectionCommand(
                CommandId(uuid(1385)), "fake-operator", episode_id, timed.package_id,
                corrected_cues, "fake qualified timing correction",
                TimingReviewStatus.HUMAN_REVIEWED, timed.revision,
            )
        )
        handoff = ExportPresentationHandoffHandler(flow.episodes, flow.jobs, flow.authority, flow.clock)(
            ExportPresentationHandoffCommand(CommandId(uuid(1386)), episode_id, corrected.package_id)
        )
        status = ShowEpisodeStatusHandler(flow.episodes)(
            ShowEpisodeStatusCommand(CommandId(uuid(1387)), episode_id)
        )
        episode = flow.episodes.load(episode_id)
        master = episode.speech_masters[-1]
        self.assertEqual((master.gap_samples, master.media.sample_count), (50, 250))
        self.assertEqual((handoff.cue_count, status.timing_versions, corrected.version), (2, 2, 2))
        self.assertEqual((len(flow.assembler.episode_calls), handoff.episode_master_id), (1, master.master_id))
        self.assertEqual(len(flow.gateways), 2)

    def test_stale_source_job_or_episode_CAS_refusal_prevents_dry_assembly_and_publication(self) -> None:
        flow, episode_id, intro, diary, configured = self.configured()
        source = flow.jobs.load(diary.issuing_job_id)
        source.revise_passage_text(
            source.passages[0].passage_id, PassageText("ଏହା ପରବର୍ତ୍ତୀ ନକଲି ସଂଶୋଧନ।"),
            flow.clock.now(), expected_revision=source.revision,
        )
        self.assertTrue(flow.jobs.save(source, source.revision - 1))
        before_artifacts = len(flow.artifacts.calls)
        with self.assertRaises(AuthorizationDenied):
            AssembleEpisodeSpeechMasterHandler(
                flow.episodes, flow.jobs, flow.authority, flow.clock, flow.ids,
                flow.assembler, flow.artifacts, flow.workspaces,
            )(
                AssembleEpisodeSpeechMasterCommand(
                    CommandId(uuid(1388)), episode_id, configured.revision,
                    SafeRelativeArtifactPath("fake/stale-episode.wav"),
                )
            )
        self.assertEqual((flow.assembler.episode_calls, len(flow.artifacts.calls)), ([], before_artifacts))

    def test_unknown_episode_attempt_uses_explicit_reconciliation_handler_once(self) -> None:
        flow, episode_id, intro, diary, configured = self.configured()
        attempt_id = EpisodeAssemblyAttemptId(uuid(1389))
        episode = flow.episodes.load(episode_id)
        episode.reserve_episode_assembly(attempt_id, True, flow.clock.now(), expected_revision=configured.revision)
        episode.finalize_episode_assembly_outcome(
            attempt_id, AttemptState.UNKNOWN, "fake ambiguous episode assembly",
            flow.clock.now(), expected_revision=episode.revision,
        )
        self.assertTrue(flow.episodes.save(episode, configured.revision))
        result = ReconcileEpisodeAssemblyAttemptHandler(flow.episodes, flow.clock)(
            ReconcileEpisodeAssemblyAttemptCommand(
                CommandId(uuid(1390)), episode_id, attempt_id, AttemptState.QUARANTINED,
                "fake recovered workspace evidence", episode.revision,
            )
        )
        self.assertEqual((result.revision, flow.episodes.load(episode_id).assembly_attempts[-1].state), (episode.revision + 1, AttemptState.QUARANTINED))


if __name__ == "__main__":
    unittest.main()
