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
    EstimateGenerationCommand,
    PrepareDiaryNarrationCommand,
    PrepareIntroNarrationCommand,
    RequireRenderRecipeCommand,
    ValidateRenderRecipeCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    EstimateGenerationHandler,
    PrepareDiaryNarrationHandler,
    PrepareIntroNarrationHandler,
    RequireRenderRecipeHandler,
    ValidateRenderRecipeHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import PreviewCompilerResult
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied, RevisionConflict
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
    Lane,
    PassageRenderRecipe,
    PassageText,
    NonNegativeDecimal,
)
from tests.heritage_archive.narrator_voice.fakes import (
    FakeAuthorizationRepository,
    FakeAuthorizationStatusReader,
    FakeClock,
    FakeIdentifierSource,
    FakeNarrationJobRepository,
    FakeRecipeCompiler,
)
from tests.heritage_archive.narrator_voice.fixtures import NOW, digest, make_contract, make_defaults, make_settings, uuid


class NarrationPreviewApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority_repo = FakeAuthorizationRepository()
        self.reader = FakeAuthorizationStatusReader(self.authority_repo)
        self.jobs = FakeNarrationJobRepository()
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

    def prepare_diary(self):
        return PrepareDiaryNarrationHandler(self.jobs, self.reader, self.clock, self.ids)(
            PrepareDiaryNarrationCommand(
                CommandId(uuid(806)), self.contract, make_defaults(), (PassageDraft(self.passage_id, 0, self.text),),
            )
        )

    def test_distinct_lane_handlers_prepare_only_their_explicit_policy_factory(self) -> None:
        result = self.prepare_diary()
        self.assertEqual((result.lane, self.jobs.load(self.job_id).lane), (Lane.B, Lane.B))
        episode_id = DiaryEpisodeId(uuid(807))
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
        intro = PrepareIntroNarrationHandler(self.jobs, self.reader, self.clock, self.ids)(
            PrepareIntroNarrationCommand(
                CommandId(uuid(810)), intro_contract, make_defaults(),
                (PassageDraft(PassageId(uuid(811)), 0, PassageText("ଏହା ଏକ ନକଲି ପରିଚୟ।")),),
            )
        )
        self.assertEqual((intro.lane, self.jobs.load(intro_job_id).lane), (Lane.C, Lane.C))

    def test_prepare_fails_closed_on_authority_outage_or_noncovering_scope(self) -> None:
        self.reader.outage = True
        with self.assertRaises(AuthorizationDenied):
            self.prepare_diary()
        self.assertIsNone(self.jobs.load(self.job_id))

    def test_recipe_record_require_and_preview_are_CAS_bound_and_make_no_synthesis_call(self) -> None:
        self.prepare_diary()
        recipe = PassageRenderRecipe(self.recipe_id, 1, 1, self.text.digest, "fake-compiler-v1", ())
        validated = ValidateRenderRecipeHandler(self.jobs)(
            ValidateRenderRecipeCommand(CommandId(uuid(812)), self.job_id, self.passage_id, recipe, 1)
        )
        required = RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(813)), self.job_id, self.passage_id, self.recipe_id, validated.revision)
        )
        estimate = EstimateGenerationHandler(self.jobs, self.reader, self.compiler, self.clock, self.ids)(
            EstimateGenerationCommand(
                CommandId(uuid(814)), self.job_id, self.passage_id, self.recipe_id, make_settings(), required.revision,
            )
        )
        self.assertEqual(estimate.preview.rendered_transcript_bytes, f"<fake>{self.text.value}</fake>".encode("utf-8"))
        self.assertEqual((len(self.compiler.calls), self.jobs.load(self.job_id).revision), (1, 4))

    def test_preview_CAS_refusal_leaves_no_preview_history(self) -> None:
        self.prepare_diary()
        recipe = PassageRenderRecipe(self.recipe_id, 1, 1, self.text.digest, "fake-compiler-v1", ())
        ValidateRenderRecipeHandler(self.jobs)(
            ValidateRenderRecipeCommand(CommandId(uuid(815)), self.job_id, self.passage_id, recipe, 1)
        )
        RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(816)), self.job_id, self.passage_id, self.recipe_id, 2)
        )
        self.jobs.reject_next_save = True
        with self.assertRaises(RevisionConflict):
            EstimateGenerationHandler(self.jobs, self.reader, self.compiler, self.clock, self.ids)(
                EstimateGenerationCommand(CommandId(uuid(817)), self.job_id, self.passage_id, self.recipe_id, make_settings(), 3)
            )
        self.assertEqual(self.jobs.load(self.job_id).previews, ())

    def test_advanced_compiler_output_over_16384_utf8_bytes_is_rejected_before_preview_save(self) -> None:
        self.prepare_diary()
        recipe = PassageRenderRecipe(self.recipe_id, 1, 1, self.text.digest, "fake-compiler-v1", ())
        ValidateRenderRecipeHandler(self.jobs)(
            ValidateRenderRecipeCommand(CommandId(uuid(818)), self.job_id, self.passage_id, recipe, 1)
        )
        RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(819)), self.job_id, self.passage_id, self.recipe_id, 2)
        )
        self.compiler.compile = lambda request: PreviewCompilerResult(  # type: ignore[method-assign]
            "fake-compiler-v1", "fake://no-network", "x" * 16_385,
            request.text.value, True, "off", "fake-billing-v1", NonNegativeDecimal("1"),
        )
        with self.assertRaisesRegex(ValidationError, "16,384"):
            EstimateGenerationHandler(self.jobs, self.reader, self.compiler, self.clock, self.ids)(
                EstimateGenerationCommand(CommandId(uuid(820)), self.job_id, self.passage_id, self.recipe_id, make_settings(), 3)
            )
        self.assertEqual(self.jobs.load(self.job_id).previews, ())


if __name__ == "__main__":
    unittest.main()
