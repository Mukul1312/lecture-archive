"""Complete Task-2 no-network Lane-C + Lane-B + episode acceptance walkthrough."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.application.commands import (
    BuildTimedNarrationPackageCommand,
    ExportPresentationHandoffCommand,
    GenerateTakeCommand,
    RecordTimingCorrectionCommand,
    ReconcileGenerationAttemptCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    BuildTimedNarrationPackageHandler,
    ExportPresentationHandoffHandler,
    GenerateTakeHandler,
    RecordTimingCorrectionHandler,
    ReconcileGenerationAttemptHandler,
)
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationStatus
from heritage_archive.contexts.narrator_voice.domain.evidence import AttemptState, CueProvenance, TimingReviewStatus
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, DomainInvariantError, RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    BudgetReservationId,
    AuthorityChangeId,
    CommandId,
    CueId,
    GenerationAttemptId,
    PassageRenderRecipeId,
    SelectionDecisionId,
    TimedNarrationPackageId,
)
from heritage_archive.contexts.narrator_voice.domain.values import Lane, PassageRenderRecipe, SafeRelativeArtifactPath
from tests.heritage_archive.narrator_voice import test_application_episode as episode_fixture
from tests.heritage_archive.narrator_voice import test_application_generation as generation_fixture
from tests.heritage_archive.narrator_voice.fakes import FakeTimingNormalizer
from tests.heritage_archive.narrator_voice.fixtures import uuid
from tests.heritage_archive.narrator_voice.fixtures import digest


class CompleteNoNetworkAcceptanceTests(unittest.TestCase):
    def test_lane_c_lane_b_episode_walkthrough_and_all_safety_evidence(self) -> None:
        episode_case = episode_fixture.EpisodeApplicationTests(
            "test_complete_exact_episode_timing_fallback_correction_and_presentation_handoff"
        )
        flow, episode_id, intro, diary, assembled, listened = episode_case.assembled_and_listened()
        flow.add(TimedNarrationPackageId, TimedNarrationPackageId(uuid(1400)), TimedNarrationPackageId(uuid(1401)))
        normalizer = FakeTimingNormalizer([CueId(uuid(1402)), CueId(uuid(1403))])
        timed = BuildTimedNarrationPackageHandler(
            flow.episodes, flow.jobs, flow.authority, flow.clock, flow.ids, normalizer,
        )(
            BuildTimedNarrationPackageCommand(
                CommandId(uuid(1404)), episode_id, assembled.master_id, (), listened.revision,
            )
        )
        first = flow.episodes.load(episode_id).timing_packages[-1]
        corrected_cues = (
            first.cues[0],
            replace(
                first.cues[1], cue_id=CueId(uuid(1405)),
                start_sample=first.cues[1].start_sample + 1,
                provenance=CueProvenance.MANUAL_CORRECTION,
                source="fake qualified manual correction", source_version="v2",
                review_status=TimingReviewStatus.HUMAN_REVIEWED,
            ),
        )
        corrected = RecordTimingCorrectionHandler(
            flow.episodes, flow.jobs, flow.authority, flow.actors, flow.clock, flow.ids
        )(
            RecordTimingCorrectionCommand(
                CommandId(uuid(1406)), "fake-operator", episode_id, timed.package_id,
                corrected_cues, "fake qualified correction", TimingReviewStatus.HUMAN_REVIEWED,
                timed.revision,
            )
        )
        handoff = ExportPresentationHandoffHandler(flow.episodes, flow.jobs, flow.authority, flow.clock)(
            ExportPresentationHandoffCommand(CommandId(uuid(1407)), episode_id, corrected.package_id)
        )

        # Two distinct current authorizations and two genuinely distinct source policies.
        self.assertEqual(len(flow.authorizations.values), 2)
        self.assertTrue(all(
            record.status_at(flow.clock.now()) is AuthorizationStatus.ACTIVE
            for record in flow.authorizations.values.values()
        ))
        self.assertEqual((intro.lane, diary.lane, intro.intended_episode_id, diary.intended_episode_id), (Lane.C, Lane.B, episode_id, None))
        episode = flow.episodes.load(episode_id)
        self.assertEqual(tuple(item.resulting_revision for item in episode.component_history), (2, 3))

        # Structured and Advanced fake compilers have equivalent canonical projection,
        # while the exact preview bytes are the exact frozen gateway bytes.
        source_jobs = (flow.jobs.load(intro.issuing_job_id), flow.jobs.load(diary.issuing_job_id))
        rendered = tuple(job.previews[0].rendered_transcript for job in source_jobs)
        self.assertTrue(rendered[0].startswith("<structured-fake>"))
        self.assertTrue(rendered[1].startswith("<advanced-fake>"))
        self.assertEqual(
            tuple(job.previews[0].canonical_projection for job in source_jobs),
            tuple(job.passages[0].current_text_revision.text.value for job in source_jobs),
        )
        self.assertEqual(
            tuple(gateway.calls[0].rendered_transcript_bytes for gateway in flow.gateways),
            tuple(job.previews[0].rendered_transcript_bytes for job in source_jobs),
        )

        # Success settled both reservations; all publications are fake-safe dry evidence.
        self.assertEqual([item[0] for item in flow.budget.actions], ["reserve", "settle", "reserve", "settle"])
        self.assertTrue(all(call[0].value.startswith("fake/") for call in flow.artifacts.calls))
        self.assertEqual((handoff.cue_count, len(episode.timing_packages), episode.speech_masters[-1].gap_samples), (2, 2, 50))
        self.assertFalse(any(hasattr(gateway, name) for gateway in flow.gateways for name in ("session", "client", "urlopen", "request")))

        # Duplicate/stale confirmation cannot call provider, reserve budget or publish.
        source = source_jobs[0]
        calls_before = (len(flow.gateways[0].calls), len(flow.budget.actions), len(flow.artifacts.calls))
        flow.add(GenerationAttemptId, GenerationAttemptId(uuid(1408)))
        flow.add(BudgetReservationId, BudgetReservationId(uuid(1409)))
        flow.add(AttemptWorkspaceId, AttemptWorkspaceId(uuid(1410)))
        with self.assertRaises(ValidationError):
            GenerateTakeHandler(
                flow.jobs, flow.authority, flow.clock, flow.ids, flow.budget,
                flow.gateways[0], flow.artifacts, flow.media, flow.workspaces,
            )(
                GenerateTakeCommand(
                    CommandId(uuid(1411)), source.job_id, source.previews[0].preview_id,
                    source.revision, SafeRelativeArtifactPath("fake/duplicate.wav"),
                )
            )
        self.assertEqual(
            (len(flow.gateways[0].calls), len(flow.budget.actions), len(flow.artifacts.calls)), calls_before
        )
        flow.add(GenerationAttemptId, GenerationAttemptId(uuid(1414)))
        flow.add(BudgetReservationId, BudgetReservationId(uuid(1415)))
        flow.add(AttemptWorkspaceId, AttemptWorkspaceId(uuid(1416)))
        with self.assertRaises(RevisionConflict):
            GenerateTakeHandler(
                flow.jobs, flow.authority, flow.clock, flow.ids, flow.budget,
                flow.gateways[0], flow.artifacts, flow.media, flow.workspaces,
            )(
                GenerateTakeCommand(
                    CommandId(uuid(1417)), source.job_id, source.previews[0].preview_id,
                    source.revision - 1, SafeRelativeArtifactPath("fake/stale.wav"),
                )
            )
        self.assertEqual(
            (len(flow.gateways[0].calls), len(flow.budget.actions), len(flow.artifacts.calls)), calls_before
        )

        # Authority-reader outage fails export closed without changing immutable output history.
        revision_before = flow.episodes.load(episode_id).revision
        flow.authority.outage = True
        with self.assertRaises(AuthorizationDenied):
            ExportPresentationHandoffHandler(flow.episodes, flow.jobs, flow.authority, flow.clock)(
                ExportPresentationHandoffCommand(CommandId(uuid(1412)), episode_id, corrected.package_id)
            )
        self.assertEqual(flow.episodes.load(episode_id).revision, revision_before)
        flow.authority.outage = False

        # Recipe and dictionary ineligibility stay separate and block a new selection
        # without deleting the historical take or previous selection.
        diary_job = flow.jobs.load(diary.issuing_job_id)
        original_revision = diary_job.revision
        passage = diary_job.passages[0]
        replacement_recipe_id = PassageRenderRecipeId(uuid(1418))
        replacement = PassageRenderRecipe(
            replacement_recipe_id, 1, passage.current_text_revision.revision,
            passage.current_text_revision.text.digest, "fake-compiler-v1", (),
        )
        diary_job.record_render_recipe(passage.passage_id, replacement, expected_revision=diary_job.revision)
        diary_job.require_render_recipe(passage.passage_id, replacement_recipe_id, expected_revision=diary_job.revision)
        diary_job.require_dictionary_digest(passage.passage_id, digest("fake different dictionary"), expected_revision=diary_job.revision)
        take = diary_job.takes[-1]
        eligibility = diary_job.eligibility_for(take, authority_eligible=True)
        self.assertEqual((eligibility.recipe_ineligible, eligibility.dictionary_ineligible), (True, True))
        self.assertTrue(flow.jobs.save(diary_job, original_revision))
        from heritage_archive.contexts.narrator_voice.application.commands import SelectWorkingTakeCommand
        from heritage_archive.contexts.narrator_voice.application.handlers import SelectWorkingTakeHandler
        flow.add(SelectionDecisionId, SelectionDecisionId(uuid(1419)))
        with self.assertRaises(DomainInvariantError):
            SelectWorkingTakeHandler(flow.jobs, flow.authority, flow.actors, flow.clock, flow.ids)(
                SelectWorkingTakeCommand(
                    CommandId(uuid(1420)), "fake-operator", diary_job.job_id,
                    passage.passage_id, take.take_id, "fake unsafe reselection", diary_job.revision,
                )
            )
        self.assertEqual(len(flow.jobs.load(diary_job.job_id).takes), 1)

        # Irreversible withdrawal is current truth and closes protected export.
        intro_record = flow.authorizations.load(intro.authority_snapshot.record_id)
        intro_record.withdraw(
            AuthorityChangeId(uuid(1421)), flow.actor, "fake final withdrawal",
            flow.clock.now(), expected_revision=intro_record.revision,
        )
        self.assertTrue(flow.authorizations.save(intro_record, intro_record.revision - 1))
        self.assertEqual(intro_record.status_at(flow.clock.now()), AuthorizationStatus.WITHDRAWN)
        with self.assertRaises(AuthorizationDenied):
            ExportPresentationHandoffHandler(flow.episodes, flow.jobs, flow.authority, flow.clock)(
                ExportPresentationHandoffCommand(CommandId(uuid(1422)), episode_id, corrected.package_id)
            )

        # A separate ambiguous provider run is held, then only explicit recorded evidence
        # reconciles it to a conservative immutable terminal outcome.
        ambiguous = generation_fixture.GenerationApplicationTests(
            "test_ambiguous_failure_holds_budget_until_explicit_conservative_reconciliation"
        )
        ambiguous.setUp()
        ambiguous.gateway.mode = "ambiguous"
        unknown = ambiguous.handler()(ambiguous.command())
        self.assertEqual((unknown.state, ambiguous.budget.actions[-1][0]), (AttemptState.UNKNOWN, "hold"))
        reconciled = ReconcileGenerationAttemptHandler(ambiguous.jobs, ambiguous.clock)(
            ReconcileGenerationAttemptCommand(
                CommandId(uuid(1413)), ambiguous.job_id, ambiguous.attempt_id,
                AttemptState.QUARANTINED, "fake recovery evidence", unknown.revision,
            )
        )
        self.assertEqual(ambiguous.jobs.load(ambiguous.job_id).generation_attempts[-1].state, AttemptState.QUARANTINED)
        self.assertEqual(reconciled.revision, unknown.revision + 1)


if __name__ == "__main__":
    unittest.main()
