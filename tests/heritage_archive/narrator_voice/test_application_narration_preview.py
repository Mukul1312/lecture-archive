"""Narration preparation, mutation and pure preview application tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ValidationError
from heritage_archive.contexts.narrator_voice.application.commands import (
    DictionaryOverride,
    EstimateGenerationCommand,
    OverrideMode,
    PrepareDiaryNarrationCommand,
    PrepareIntroNarrationCommand,
    RequireRenderRecipeCommand,
    TakeSettingsIntent,
    TextControlOverride,
    ValidateRenderRecipeCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    EstimateGenerationHandler,
    PrepareDiaryNarrationHandler,
    PrepareIntroNarrationHandler,
    RequireRenderRecipeHandler,
    ValidateRenderRecipeHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import PreviewCompilerResult, ReleasePolicyResolution
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, NotFound, RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AuthorizationRecordId,
    CommandId,
    DiaryEpisodeId,
    GenerationPreviewId,
    NarrationJobId,
    PassageId,
    PassageRenderRecipeId,
)
from heritage_archive.contexts.narrator_voice.domain.narration_job import PassageDraft
from heritage_archive.contexts.narrator_voice.domain.values import (
    AuthorityOperation,
    AuthorityScope,
    ControlProvenance,
    Lane,
    PassageText,
    NonNegativeDecimal,
)
from tests.heritage_archive.narrator_voice.fakes import (
    FakeAuthorizationRepository,
    FakeAuthorizationStatusReader,
    FakeClock,
    FakeDiaryEpisodeRepository,
    FakeIdentifierSource,
    FakeNarrationJobRepository,
    FakeRecipeCompiler,
    FakeReleasePolicyResolver,
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


class NarrationPreviewApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority_repo = FakeAuthorizationRepository()
        self.reader = FakeAuthorizationStatusReader(self.authority_repo)
        self.jobs = FakeNarrationJobRepository()
        self.episodes = FakeDiaryEpisodeRepository()
        self.clock = FakeClock(NOW)
        self.compiler = FakeRecipeCompiler()
        self.contract = make_contract(lane=Lane.B)
        self.authority_id = self.contract.authority_record_id
        self.job_id = NarrationJobId(uuid(801))
        self.passage_id = PassageId(uuid(802))
        self.recipe_id = PassageRenderRecipeId(uuid(803))
        self.preview_id = GenerationPreviewId(uuid(804))
        self.text = PassageText("ଏହା ଏକ ସାଧାରଣ ପରୀକ୍ଷା ବାକ୍ୟ।")
        # Contract fields are the authority identity truth.
        aligned = AuthorityScope(
            self.contract.speaker_binding, self.contract.voice_binding, self.contract.language,
            self.contract.purpose, None, frozenset(AuthorityOperation),
            NOW - timedelta(days=1), NOW + timedelta(days=1),
        )
        aligned_record = AuthorizationRecord.register(self.authority_id, ActorId(uuid(805)), aligned, digest("fake auth"), NOW)
        self.authority_repo.values[self.authority_id] = aligned_record
        self.authority_repo.revisions[self.authority_id] = 1
        self.ids = FakeIdentifierSource({NarrationJobId: [self.job_id], GenerationPreviewId: [self.preview_id]})
        self.policies = FakeReleasePolicyResolver(
            lane_b=ReleasePolicyResolution(self.contract, make_defaults()),
        )

    def prepare_diary(self):
        return PrepareDiaryNarrationHandler(self.jobs, self.policies, self.reader, self.clock, self.ids)(
            PrepareDiaryNarrationCommand(
                CommandId(uuid(806)), (PassageDraft(self.passage_id, 0, self.text),),
            )
        )

    def test_distinct_lane_handlers_prepare_only_their_trusted_policy_resolution(self) -> None:
        try:
            result = self.prepare_diary()
        except Exception as error:
            self.fail(f"diary preparation did not use the trusted release policy: {error!r}")
        stored_diary = self.jobs.load(self.job_id)
        self.assertEqual((result.lane, stored_diary.lane, stored_diary.contract), (Lane.B, Lane.B, self.contract))
        self.assertEqual(self.policies.calls, [("lane_b", None)])
        episode_id = DiaryEpisodeId(uuid(807))
        episode = DiaryEpisode.prepare(episode_id, NOW)
        self.assertTrue(self.episodes.save(episode, None))
        intro_contract = make_contract(lane=Lane.C, episode_id=episode_id)
        intro_scope = AuthorityScope(
            intro_contract.speaker_binding, intro_contract.voice_binding, "or", intro_contract.purpose,
            episode_id, frozenset(AuthorityOperation), NOW - timedelta(days=1), NOW + timedelta(days=1),
        )
        intro_auth_id = intro_contract.authority_record_id
        intro_record = AuthorizationRecord.register(intro_auth_id, ActorId(uuid(808)), intro_scope, digest("fake intro auth"), NOW)
        self.assertTrue(self.authority_repo.save(intro_record, None))
        intro_job_id = NarrationJobId(uuid(809))
        self.ids.values[NarrationJobId].append(intro_job_id)
        self.policies.lane_c = ReleasePolicyResolution(intro_contract, make_defaults("intro"))
        intro = PrepareIntroNarrationHandler(
            self.jobs, self.episodes, self.policies, self.reader, self.clock, self.ids,
        )(
            PrepareIntroNarrationCommand(
                CommandId(uuid(810)), episode_id, episode.revision,
                (PassageDraft(PassageId(uuid(811)), 0, PassageText("ଏହା ଏକ ନକଲି ପରିଚୟ।")),),
            )
        )
        stored_intro = self.jobs.load(intro_job_id)
        self.assertEqual((intro.lane, stored_intro.lane, stored_intro.contract), (Lane.C, Lane.C, intro_contract))
        self.assertEqual(self.policies.calls[-1], ("lane_c", episode_id))

    def test_intro_preparation_rejects_missing_or_stale_episode_before_policy_or_job_creation(self) -> None:
        episode_id = DiaryEpisodeId(uuid(821))
        command = PrepareIntroNarrationCommand(
            CommandId(uuid(822)), episode_id, 1,
            (PassageDraft(PassageId(uuid(823)), 0, self.text),),
        )
        try:
            handler = PrepareIntroNarrationHandler(
                self.jobs, self.episodes, self.policies, self.reader, self.clock, self.ids,
            )
        except Exception as error:
            self.fail(f"intro handler does not expose the draft-episode policy boundary: {error!r}")
        with self.assertRaises(NotFound):
            handler(command)

        episode = DiaryEpisode.prepare(episode_id, NOW)
        self.assertTrue(self.episodes.save(episode, None))
        with self.assertRaises(RevisionConflict):
            handler(PrepareIntroNarrationCommand(command.command_id, episode_id, 0, command.passages))

        self.assertEqual((self.policies.calls, self.jobs.values), ([], {}))

    def test_prepare_fails_closed_on_authority_outage_or_noncovering_scope(self) -> None:
        self.reader.outage = True
        with self.assertRaises(AuthorizationDenied):
            self.prepare_diary()
        self.assertIsNone(self.jobs.load(self.job_id))

    def test_recipe_record_require_and_preview_are_CAS_bound_and_make_no_synthesis_call(self) -> None:
        self.prepare_diary()
        validated = ValidateRenderRecipeHandler(self.jobs, self.compiler)(
            ValidateRenderRecipeCommand(
                CommandId(uuid(812)), self.job_id, self.passage_id,
                make_recipe_authoring(recipe_index=803), 1,
            )
        )
        required = RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(813)), self.job_id, self.passage_id, self.recipe_id, validated.revision)
        )
        estimate = EstimateGenerationHandler(self.jobs, self.reader, self.compiler, self.clock, self.ids)(
            EstimateGenerationCommand(
                CommandId(uuid(814)), self.job_id, self.passage_id, self.recipe_id,
                make_settings_intent(), required.revision,
            )
        )
        self.assertEqual(estimate.preview.rendered_transcript_bytes, f"<fake>{self.text.value}</fake>".encode("utf-8"))
        self.assertEqual((len(self.compiler.recipe_calls), len(self.compiler.calls), self.jobs.load(self.job_id).revision), (1, 1, 4))

    def test_structured_and_advanced_authoring_compile_to_equivalent_server_owned_recipes(self) -> None:
        self.prepare_diary()
        advanced = "<fake-advanced>same lexical text</fake-advanced>"
        self.compiler.advanced_controls[advanced] = ()
        try:
            structured = ValidateRenderRecipeHandler(self.jobs, self.compiler)(
                ValidateRenderRecipeCommand(
                    CommandId(uuid(824)), self.job_id, self.passage_id,
                    make_recipe_authoring(recipe_index=825), 1,
                )
            )
            advanced_result = ValidateRenderRecipeHandler(self.jobs, self.compiler)(
                ValidateRenderRecipeCommand(
                    CommandId(uuid(826)), self.job_id, self.passage_id,
                    make_recipe_authoring(recipe_index=827, advanced_source=advanced), structured.revision,
                )
            )
        except Exception as error:
            self.fail(f"server-side structured/advanced recipe compilation was not applied: {error!r}")
        self.assertEqual(
            (
                structured.recipe.controls,
                advanced_result.recipe.controls,
                structured.canonical_projection,
                advanced_result.canonical_projection,
            ),
            ((), (), self.text.value, self.text.value),
        )

    def test_generation_settings_intent_is_resolved_against_current_job_defaults(self) -> None:
        self.prepare_diary()
        intent = TakeSettingsIntent(
            TextControlOverride(OverrideMode.INHERIT),
            TextControlOverride(OverrideMode.SET, "0.95"),
            TextControlOverride(OverrideMode.OMIT),
            DictionaryOverride(OverrideMode.INHERIT),
        )
        try:
            validated = ValidateRenderRecipeHandler(self.jobs, self.compiler)(
                ValidateRenderRecipeCommand(
                    CommandId(uuid(828)), self.job_id, self.passage_id,
                    make_recipe_authoring(recipe_index=803), 1,
                )
            )
            required = RequireRenderRecipeHandler(self.jobs)(
                RequireRenderRecipeCommand(
                    CommandId(uuid(829)), self.job_id, self.passage_id, self.recipe_id, validated.revision,
                )
            )
            preview = EstimateGenerationHandler(
                self.jobs, self.reader, self.compiler, self.clock, self.ids,
            )(
                EstimateGenerationCommand(
                    CommandId(uuid(830)), self.job_id, self.passage_id,
                    self.recipe_id, intent, required.revision,
                )
            ).preview
        except Exception as error:
            self.fail(f"settings intent was not resolved server-side: {error!r}")
        self.assertEqual(
            (
                preview.settings.speed.provenance,
                preview.settings.speed.value,
                preview.settings.volume.provenance,
                preview.settings.volume.value,
                preview.settings.emotion.provenance,
                preview.settings.emotion.value,
                preview.settings.dictionary,
            ),
            (
                ControlProvenance.INHERITED,
                "0.90",
                ControlProvenance.EXPLICITLY_SET,
                "0.95",
                ControlProvenance.EXPLICITLY_OMITTED,
                None,
                make_defaults().dictionary,
            ),
        )

    def test_preview_CAS_refusal_leaves_no_preview_history(self) -> None:
        self.prepare_diary()
        ValidateRenderRecipeHandler(self.jobs, self.compiler)(
            ValidateRenderRecipeCommand(
                CommandId(uuid(815)), self.job_id, self.passage_id,
                make_recipe_authoring(recipe_index=803), 1,
            )
        )
        RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(816)), self.job_id, self.passage_id, self.recipe_id, 2)
        )
        self.jobs.reject_next_save = True
        with self.assertRaises(RevisionConflict):
            EstimateGenerationHandler(self.jobs, self.reader, self.compiler, self.clock, self.ids)(
                EstimateGenerationCommand(
                    CommandId(uuid(817)), self.job_id, self.passage_id,
                    self.recipe_id, make_settings_intent(), 3,
                )
            )
        self.assertEqual(self.jobs.load(self.job_id).previews, ())

    def test_advanced_compiler_output_over_16384_utf8_bytes_is_rejected_before_preview_save(self) -> None:
        self.prepare_diary()
        ValidateRenderRecipeHandler(self.jobs, self.compiler)(
            ValidateRenderRecipeCommand(
                CommandId(uuid(818)), self.job_id, self.passage_id,
                make_recipe_authoring(recipe_index=803), 1,
            )
        )
        RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(819)), self.job_id, self.passage_id, self.recipe_id, 2)
        )
        self.compiler.compile = lambda request: PreviewCompilerResult(  # type: ignore[method-assign]
            "fake-compiler-v1", "fake://no-network", "x" * 16_385,
            request.text.value, True, "off", "fake-billing-v1", 1, NonNegativeDecimal("1"),
        )
        with self.assertRaisesRegex(ValidationError, "16,384"):
            EstimateGenerationHandler(self.jobs, self.reader, self.compiler, self.clock, self.ids)(
                EstimateGenerationCommand(
                    CommandId(uuid(820)), self.job_id, self.passage_id,
                    self.recipe_id, make_settings_intent(), 3,
                )
            )
        self.assertEqual(self.jobs.load(self.job_id).previews, ())


if __name__ == "__main__":
    unittest.main()
