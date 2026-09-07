"""Complete redacted read-model projections for narrator production status."""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass, replace
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.contexts.narrator_voice.application.commands import (
    BuildTimedNarrationPackageCommand,
    ShowAuthorizationStatusCommand,
    ShowEpisodeStatusCommand,
    ShowNarrationStatusCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    BuildTimedNarrationPackageHandler,
    ShowAuthorizationStatusHandler,
    ShowEpisodeStatusHandler,
    ShowNarrationStatusHandler,
)
from heritage_archive.contexts.narrator_voice.application.results import (
    AuthorizationStatusResult,
    EpisodeStatusResult,
    NarrationStatusResult,
)
from heritage_archive.contexts.narrator_voice.application.schema_v1 import (
    decode_schema_v1,
    encode_schema_v1,
)
from heritage_archive.contexts.narrator_voice.application.status import (
    AuthorityHistoryKind,
    project_authorization_history,
    project_episode_status,
    project_narration_status,
)
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationStatus
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode, EpisodeStatus
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptState,
    CueProvenance,
    ListeningOutcome,
    ReviewOutcome,
    TimingReviewStatus,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AuthorityChangeId,
    CommandId,
    CueId,
    DiaryEpisodeId,
    TimedNarrationPackageId,
)
from heritage_archive.contexts.narrator_voice.domain.values import (
    AuthorityOperation,
    ComponentRole,
    PassageText,
)
from tests.heritage_archive.narrator_voice.fixtures import NOW
from tests.heritage_archive.narrator_voice.fakes import FakeTimingNormalizer
from tests.heritage_archive.narrator_voice.fixtures import uuid
from tests.heritage_archive.narrator_voice import test_application_episode as episode_fixture


class _AdvancingClock:
    def __init__(self):
        self.calls = 0

    def now(self):
        value = NOW + timedelta(seconds=self.calls)
        self.calls += 1
        return value


class ApplicationStatusProjectionTests(unittest.TestCase):
    def _studio_repositories(self, filesystem):
        from tests.heritage_archive.narrator_voice.fakes import FakeDiaryEpisodeRepository, FakeNarrationJobRepository
        from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import FilesystemDiaryEpisodeRepository, FilesystemNarrationJobRepository
        from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot

        if not filesystem:
            return FakeNarrationJobRepository(), FakeDiaryEpisodeRepository(), None
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = LocalNarrationRoot.open(Path(temporary.name), (SOURCE_ROOT.parent,))
        root.initialize_layout()
        return FilesystemNarrationJobRepository(root), FilesystemDiaryEpisodeRepository(root), root

    def test_studio_discovery_returns_only_opaque_sorted_ids_from_fake_and_reopened_filesystem(self):
        from heritage_archive.contexts.narrator_voice.application.commands import DiscoverStudioCommand
        from heritage_archive.contexts.narrator_voice.application.handlers import DiscoverStudioHandler
        from heritage_archive.contexts.narrator_voice.domain.ids import NarrationJobId, PassageId
        from heritage_archive.contexts.narrator_voice.domain.narration_job import PassageDraft, prepare_lane_b_diary_job
        from tests.heritage_archive.narrator_voice.fixtures import make_contract, make_defaults

        for filesystem in (False, True):
            with self.subTest(filesystem=filesystem):
                jobs, episodes, root = self._studio_repositories(filesystem)
                command = DiscoverStudioCommand(CommandId(uuid(1600)))
                empty = DiscoverStudioHandler(jobs, episodes)(command)
                self.assertEqual((empty.job_ids, empty.episode_ids), ((), ()))
                for index in (1602, 1601):
                    jobs.save(prepare_lane_b_diary_job(NarrationJobId(uuid(index)), make_contract(), make_defaults(),
                        (PassageDraft(PassageId(uuid(index + 100)), 0, PassageText("operator text")),), NOW), None)
                    episodes.save(DiaryEpisode.prepare(DiaryEpisodeId(uuid(index + 10)), NOW), None)
                if root is not None:
                    jobs, episodes = type(jobs)(root), type(episodes)(root)
                discovery = DiscoverStudioHandler(jobs, episodes)(command)
                self.assertEqual(discovery.job_ids, (NarrationJobId(uuid(1601)), NarrationJobId(uuid(1602))))
                self.assertEqual(discovery.episode_ids, (DiaryEpisodeId(uuid(1611)), DiaryEpisodeId(uuid(1612))))
                self.assertEqual({field.name for field in fields(discovery)}, {"job_ids", "episode_ids"})
                self.assertTrue(type(discovery).__dataclass_params__.frozen)

    def test_editor_restores_ordered_text_controls_recipes_and_view_only_preview(self):
        from heritage_archive.contexts.narrator_voice.application.commands import ShowNarrationEditorCommand
        from heritage_archive.contexts.narrator_voice.application.handlers import ShowNarrationEditorHandler
        from heritage_archive.contexts.narrator_voice.domain.ids import NarrationJobId, PassageId
        from heritage_archive.contexts.narrator_voice.domain.narration_job import PassageDraft, prepare_lane_b_diary_job
        from heritage_archive.contexts.narrator_voice.domain.values import BreakControl
        from tests.heritage_archive.narrator_voice.fixtures import make_contract, make_defaults, make_recipe, make_preview

        for filesystem in (False, True):
            with self.subTest(filesystem=filesystem):
                jobs, _, root = self._studio_repositories(filesystem)
                first, second = PassageId(uuid(1621)), PassageId(uuid(1622))
                job = prepare_lane_b_diary_job(NarrationJobId(uuid(1620)), make_contract(), make_defaults(), (
                    PassageDraft(first, 0, PassageText("old text")), PassageDraft(second, 1, PassageText("second")),
                ), NOW)
                jobs.save(job, None)

                def persist(action):
                    before = job.revision
                    action(before)
                    self.assertTrue(jobs.save(job, before))

                persist(lambda rev: job.revise_passage_text(first, PassageText("current operator text"), NOW, expected_revision=rev))
                persist(lambda rev: job.reorder_passages((second, first), expected_revision=rev))
                recipe = replace(make_recipe(PassageText("current operator text"), recipe_index=1623, text_revision=2), controls=(BreakControl(7, 100),))
                persist(lambda rev: job.record_render_recipe(first, recipe, expected_revision=rev))
                persist(lambda rev: job.require_render_recipe(first, recipe.recipe_id, expected_revision=rev))
                persist(lambda rev: job.require_dictionary_digest(first, job.defaults.dictionary.content_digest, expected_revision=rev))
                preview = make_preview(job_id=job.job_id, base_revision=6, passage_id=first,
                    text=PassageText("current operator text"), recipe=recipe, contract=job.contract, preview_index=1624)
                persist(lambda rev: job.issue_generation_preview(preview, expected_revision=rev))
                if root is not None:
                    jobs = type(jobs)(root)
                command = ShowNarrationEditorCommand(CommandId(uuid(1625)), job.job_id)
                editor = ShowNarrationEditorHandler(jobs)(command)
                self.assertEqual((editor.job_id, editor.revision, editor.lane), (job.job_id, 7, job.lane))
                self.assertEqual(asdict(editor.defaults), {"speed": "0.90", "volume": "1.00", "emotion": "calm", "dictionary_configured": True})
                self.assertEqual(tuple((p.passage_id, p.order, p.text, p.text_revision) for p in editor.passages), (
                    (second, 0, "second", 1), (first, 1, "current operator text", 2)))
                self.assertEqual((editor.passages[0].recipe_required, editor.passages[0].dictionary_required, editor.passages[0].latest_preview), (False, False, None))
                passage = editor.passages[1]
                self.assertTrue(passage.recipe_required)
                self.assertTrue(passage.dictionary_required)
                projected_recipe = passage.recipes[0]
                self.assertEqual((projected_recipe.recipe_id, projected_recipe.revision, projected_recipe.text_revision,
                    projected_recipe.controls, projected_recipe.current, projected_recipe.required),
                    (recipe.recipe_id, 1, 2, (BreakControl(7, 100),), True, True))
                self.assertEqual(asdict(passage.latest_preview), {
                    "preview_id": {"value": uuid(1624)}, "base_job_revision": 6,
                    "canonical_projection": "current operator text", "billable_characters": 34,
                    "estimated_usage": "34", "issued_at": NOW,
                })
                forbidden = {"settings", "authority_snapshot", "record_id", "endpoint", "contract", "contract_digest",
                    "dictionary", "opaque_reference", "capability_snapshot", "provider", "voice_binding", "preview_digest", "confirmation_token"}

                def check_safe(value):
                    if is_dataclass(value):
                        self.assertTrue(type(value).__dataclass_params__.frozen)
                        self.assertFalse(forbidden & {field.name for field in fields(value)})
                        for field in fields(value):
                            check_safe(getattr(value, field.name))
                    elif isinstance(value, tuple):
                        for item in value:
                            check_safe(item)

                check_safe(editor)
                serialized = repr(asdict(editor))
                for secret in ("fake://no-network", "fake-dictionary-a", job.contract.authority_record_id.value, "capability-a"):
                    self.assertNotIn(secret, serialized)
                self.assertEqual(jobs.load(job.job_id).to_snapshot(), job.to_snapshot())
                persist(lambda rev: job.revise_passage_text(first, PassageText("newer text"), NOW, expected_revision=rev))
                stale = ShowNarrationEditorHandler(jobs)(command).passages[1]
                self.assertFalse(stale.recipe_required)
                self.assertFalse(stale.recipes[0].current)
                self.assertEqual(stale.latest_preview, passage.latest_preview)

    def test_editor_missing_job_is_not_found(self):
        from heritage_archive.contexts.narrator_voice.application.commands import ShowNarrationEditorCommand
        from heritage_archive.contexts.narrator_voice.application.handlers import ShowNarrationEditorHandler
        from heritage_archive.contexts.narrator_voice.domain.errors import NotFound
        from heritage_archive.contexts.narrator_voice.domain.ids import NarrationJobId

        for filesystem in (False, True):
            jobs, _, _ = self._studio_repositories(filesystem)
            with self.assertRaises(NotFound):
                ShowNarrationEditorHandler(jobs)(ShowNarrationEditorCommand(CommandId(uuid(1630)), NarrationJobId(uuid(1631))))

    def _completed_flow(self):
        fixture = episode_fixture.EpisodeApplicationTests(
            "test_complete_exact_episode_timing_fallback_correction_and_presentation_handoff"
        )
        flow, episode_id, intro, diary, assembled, listened = fixture.assembled_and_listened()
        flow.add(TimedNarrationPackageId, TimedNarrationPackageId(uuid(1500)))
        normalizer = FakeTimingNormalizer([CueId(uuid(1501)), CueId(uuid(1502))])
        BuildTimedNarrationPackageHandler(
            flow.episodes, flow.jobs, flow.authority, flow.clock, flow.ids, normalizer,
        )(
            BuildTimedNarrationPackageCommand(
                CommandId(uuid(1503)), episode_id, assembled.master_id, listened.revision,
            )
        )

        diary_job = flow.jobs.load(diary.issuing_job_id)
        record_id = diary_job.contract.authority_record_id
        authority = flow.authorizations.load(record_id)
        narrowed = replace(
            authority.current_scope,
            operations=frozenset(
                operation
                for operation in authority.current_scope.operations
                if operation is not AuthorityOperation.DELIVER
            ),
        )
        authority.narrow(
            AuthorityChangeId(uuid(1504)),
            flow.actor,
            narrowed,
            "private authority rationale",
            flow.clock.now(),
            expected_revision=authority.revision,
        )
        self.assertTrue(flow.authorizations.save(authority, 1))
        return flow, episode_id, intro, diary

    def _projections(self):
        flow, episode_id, intro, diary = self._completed_flow()
        episode = flow.episodes.load(episode_id)
        intro_job = flow.jobs.load(intro.issuing_job_id)
        diary_job = flow.jobs.load(diary.issuing_job_id)
        observations = tuple(
            flow.authority.read(job.contract.authority_record_id, flow.clock.now())
            for job in (intro_job, diary_job)
        )
        authority = flow.authorizations.load(diary_job.contract.authority_record_id)
        return (
            flow,
            project_authorization_history(authority, flow.clock.now()),
            project_narration_status(diary_job, observations[1], flow.clock.now()),
            project_episode_status(
                episode,
                (intro_job, diary_job),
                observations,
                flow.clock.now(),
            ),
        )

    def test_projects_complete_current_operational_status_without_private_evidence(self) -> None:
        _, authority, narration, episode = self._projections()

        self.assertEqual((authority.status, authority.revision, authority.withdrawn), (AuthorizationStatus.ACTIVE, 2, False))
        self.assertEqual(
            tuple((change.kind, change.resulting_revision) for change in authority.history),
            (
                (AuthorityHistoryKind.ATTESTED, 1),
                (AuthorityHistoryKind.NARROWED, 2),
            ),
        )
        self.assertNotIn(AuthorityOperation.DELIVER, authority.covered_operations)

        self.assertEqual(narration.current_authority.status, AuthorizationStatus.ACTIVE)
        self.assertIn(AuthorityOperation.GENERATE, narration.current_authority.covered_operations)
        self.assertEqual(len(narration.passages), 1)
        passage = narration.passages[0]
        take = passage.takes[0]
        self.assertEqual((passage.order, passage.current_text_revision, passage.ready_for_assembly), (0, 1, True))
        self.assertEqual(
            (take.eligible, take.ineligibility_reasons, take.latest_operational_review, take.selected),
            (True, (), ReviewOutcome.ACCEPTED, True),
        )
        self.assertEqual(narration.generation_attempts[0].state, AttemptState.COMPLETED)
        self.assertTrue(narration.generation_attempts[0].output_ready)
        self.assertEqual(narration.assembly_attempts[0].state, AttemptState.COMPLETED)
        self.assertTrue(narration.masters[0].current)
        self.assertEqual(narration.masters[0].latest_listening, ListeningOutcome.PASSED)

        self.assertEqual(tuple(component.role for component in episode.components), (ComponentRole.INTRO, ComponentRole.DIARY))
        self.assertEqual(tuple(component.source_current for component in episode.components), (True, True))
        self.assertEqual(episode.components[1].source_authority.status, AuthorizationStatus.ACTIVE)
        self.assertNotIn(AuthorityOperation.DELIVER, episode.components[1].source_authority.covered_operations)
        self.assertEqual(episode.assembly_attempts[0].state, AttemptState.COMPLETED)
        self.assertTrue(episode.masters[0].current)
        self.assertEqual(episode.listening[-1].outcome, ListeningOutcome.PASSED)
        timing = episode.timing[-1]
        self.assertEqual((timing.confidence, timing.cue_count, timing.is_latest), (TimingReviewStatus.VALIDATED, 2, True))
        self.assertTrue(timing.current)
        self.assertEqual(timing.provenance_counts, ((CueProvenance.DETERMINISTIC_ASSEMBLY, 2),))
        self.assertFalse(episode.delivery_ready)

    def test_projection_shape_and_payload_redact_private_text_provider_artifacts_and_authority_evidence(self) -> None:
        flow, authority, narration, episode = self._projections()
        projections = (authority, narration, episode)

        def field_names(value):
            if not is_dataclass(value):
                return set()
            names = {field.name for field in fields(value)}
            for field in fields(value):
                child = getattr(value, field.name)
                if isinstance(child, tuple):
                    for item in child:
                        names.update(field_names(item))
                else:
                    names.update(field_names(child))
            return names

        forbidden_fields = {
            "actor_id", "steward_actor_id", "reason", "notes", "scope",
            "evidence_digest", "snapshot_digest", "contract_digest", "artifact",
            "media", "events", "relative_location", "display_text", "canonical_projection",
            "raw_timing_artifacts", "component_offsets", "passage_offsets", "settings",
            "effective_input", "timing_reference", "provider_request_id", "provider_response_id",
        }
        self.assertTrue(all(not (field_names(value) & forbidden_fields) for value in projections))

        payload = repr(tuple(asdict(value) for value in projections))
        private_values = {
            "private authority rationale",
            "fake operational pass",
            "fake source selection",
            "fake-request-",
            "fake-response-",
            "fake://no-network",
            "fake/source-",
        }
        private_values.update(
            revision.text.value
            for job in flow.jobs.values.values()
            for passage in job.passages
            for revision in passage.text_revisions
        )
        self.assertTrue(all(value not in payload for value in private_values))

    def test_draft_episode_projects_both_missing_component_slots_and_no_false_readiness(self) -> None:
        episode = DiaryEpisode.prepare(DiaryEpisodeId(uuid(1510)), NOW)

        status = project_episode_status(episode, (), (), NOW)

        self.assertEqual(status.status, EpisodeStatus.DRAFT)
        self.assertEqual(tuple(component.role for component in status.components), (ComponentRole.INTRO, ComponentRole.DIARY))
        self.assertTrue(all(not component.attached and component.source_authority is None for component in status.components))
        self.assertFalse(status.assembly_ready)
        self.assertFalse(status.delivery_ready)

    def test_status_recomputes_stale_take_and_withdrawn_authority_without_leaking_reasons(self) -> None:
        flow, _, _, diary = self._completed_flow()
        job = flow.jobs.load(diary.issuing_job_id)
        unavailable = project_narration_status(job, None, flow.clock.now())
        self.assertIsNone(unavailable.current_authority.status)
        self.assertEqual(
            unavailable.passages[0].takes[0].ineligibility_reasons,
            ("authority_ineligible",),
        )
        observation = flow.authority.read(job.contract.authority_record_id, flow.clock.now())
        passage = job.passages[0]
        job.revise_passage_text(
            passage.passage_id,
            PassageText("ଏହା ଏକ ପରବର୍ତ୍ତୀ ଗୋପନୀୟ ସଂଶୋଧନ।"),
            flow.clock.now(),
            expected_revision=job.revision,
        )

        narration = project_narration_status(job, observation, flow.clock.now())

        take = narration.passages[0].takes[0]
        self.assertFalse(take.eligible)
        self.assertEqual(take.ineligibility_reasons, ("text_stale",))
        self.assertFalse(narration.passages[0].ready_for_assembly)
        self.assertFalse(narration.assembly_ready)

        record = flow.authorizations.load(job.contract.authority_record_id)
        record.withdraw(
            AuthorityChangeId(uuid(1511)),
            flow.actor,
            "second private authority rationale",
            flow.clock.now(),
            expected_revision=record.revision,
        )
        authority = project_authorization_history(record, flow.clock.now())
        self.assertEqual(authority.status, AuthorizationStatus.WITHDRAWN)
        self.assertEqual(authority.covered_operations, ())
        self.assertEqual(authority.history[-1].kind, AuthorityHistoryKind.WITHDRAWN)
        self.assertNotIn("private authority rationale", repr(asdict(authority)))

    def test_status_handlers_load_trusted_roots_and_observe_authority_at_one_instant(self) -> None:
        flow, episode_id, intro, diary = self._completed_flow()
        intro_job = flow.jobs.load(intro.issuing_job_id)
        diary_job = flow.jobs.load(diary.issuing_job_id)

        authorization_clock = _AdvancingClock()
        authorization = ShowAuthorizationStatusHandler(
            flow.authorizations, authorization_clock,
        )(
            ShowAuthorizationStatusCommand(
                CommandId(uuid(1520)), diary_job.contract.authority_record_id,
            )
        )
        self.assertIsInstance(authorization, AuthorizationStatusResult)
        self.assertEqual(
            (authorization.revision, tuple(change.kind for change in authorization.history)),
            (2, (AuthorityHistoryKind.ATTESTED, AuthorityHistoryKind.NARROWED)),
        )
        self.assertEqual(authorization_clock.calls, 1)

        narration_clock = _AdvancingClock()
        flow.authority.calls.clear()
        narration = ShowNarrationStatusHandler(
            flow.jobs, flow.authority, narration_clock,
        )(
            ShowNarrationStatusCommand(CommandId(uuid(1521)), diary_job.job_id)
        )
        self.assertIsInstance(narration, NarrationStatusResult)
        self.assertEqual(narration.job_id, diary_job.job_id)
        self.assertEqual(
            flow.authority.calls,
            [(diary_job.contract.authority_record_id, NOW)],
        )
        self.assertEqual(narration_clock.calls, 1)

        episode_clock = _AdvancingClock()
        flow.authority.calls.clear()
        episode = ShowEpisodeStatusHandler(
            flow.episodes, flow.jobs, flow.authority, episode_clock,
        )(
            ShowEpisodeStatusCommand(CommandId(uuid(1522)), episode_id)
        )
        self.assertIsInstance(episode, EpisodeStatusResult)
        self.assertEqual(
            tuple(component.source_job_id for component in episode.components),
            (intro_job.job_id, diary_job.job_id),
        )
        self.assertEqual(
            flow.authority.calls,
            [
                (intro_job.contract.authority_record_id, NOW),
                (diary_job.contract.authority_record_id, NOW),
            ],
        )
        self.assertEqual(episode_clock.calls, 1)

    def test_status_handlers_fail_closed_when_current_authority_is_unavailable(self) -> None:
        flow, episode_id, _, diary = self._completed_flow()
        diary_job = flow.jobs.load(diary.issuing_job_id)
        flow.authority.outage = True

        narration = ShowNarrationStatusHandler(
            flow.jobs, flow.authority, flow.clock,
        )(
            ShowNarrationStatusCommand(CommandId(uuid(1523)), diary_job.job_id)
        )
        episode = ShowEpisodeStatusHandler(
            flow.episodes, flow.jobs, flow.authority, flow.clock,
        )(
            ShowEpisodeStatusCommand(CommandId(uuid(1524)), episode_id)
        )

        self.assertIsNone(narration.current_authority.status)
        self.assertFalse(narration.assembly_ready)
        self.assertTrue(all(not component.source_current for component in episode.components))
        self.assertFalse(episode.assembly_ready)
        self.assertFalse(episode.delivery_ready)

    def test_status_results_round_trip_through_strict_schema_without_expanding_roots(self) -> None:
        flow, episode_id, _, diary = self._completed_flow()
        diary_job = flow.jobs.load(diary.issuing_job_id)
        values = (
            ShowAuthorizationStatusHandler(flow.authorizations, flow.clock)(
                ShowAuthorizationStatusCommand(
                    CommandId(uuid(1525)), diary_job.contract.authority_record_id,
                )
            ),
            ShowNarrationStatusHandler(flow.jobs, flow.authority, flow.clock)(
                ShowNarrationStatusCommand(CommandId(uuid(1526)), diary_job.job_id)
            ),
            ShowEpisodeStatusHandler(flow.episodes, flow.jobs, flow.authority, flow.clock)(
                ShowEpisodeStatusCommand(CommandId(uuid(1527)), episode_id)
            ),
        )

        for value in values:
            encoded = encode_schema_v1(value)
            self.assertEqual(decode_schema_v1(encoded, type(value)), value)
            self.assertNotIn(b"private authority rationale", encoded)
            self.assertNotIn(b"fake://no-network", encoded)


if __name__ == "__main__":
    unittest.main()
