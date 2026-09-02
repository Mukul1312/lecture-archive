"""NarrationJob passage, recipe, defaults and preview invariant tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.domain.evidence import EligibilityFacts
from heritage_archive.contexts.narrator_voice.domain.errors import RevisionConflict
from heritage_archive.contexts.narrator_voice.domain.ids import NarrationJobId, PassageId
from heritage_archive.contexts.narrator_voice.domain.narration_job import (
    NarrationJob,
    PassageDraft,
    prepare_lane_b_diary_job,
    prepare_lane_c_intro_job,
)
from heritage_archive.contexts.narrator_voice.domain.values import Lane, PassageText
from tests.heritage_archive.narrator_voice.fixtures import (
    NOW,
    digest,
    make_contract,
    make_defaults,
    make_preview,
    make_recipe,
    make_settings,
    make_take,
    uuid,
)


class NarrationJobPassageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job_id = NarrationJobId(uuid(100))
        self.passage_a = PassageId(uuid(101))
        self.passage_b = PassageId(uuid(102))
        self.text_a = PassageText("ଅଆ")
        self.text_b = PassageText("ଇଈ")
        self.contract = make_contract(lane=Lane.B)
        self.job = prepare_lane_b_diary_job(
            self.job_id,
            self.contract,
            make_defaults(),
            (PassageDraft(self.passage_a, 0, self.text_a), PassageDraft(self.passage_b, 1, self.text_b)),
            NOW,
        )

    def test_INV_NJ_1_passage_ids_and_explicit_order_are_unique(self) -> None:
        for passages in (
            (PassageDraft(self.passage_a, 0, self.text_a), PassageDraft(self.passage_a, 1, self.text_b)),
            (PassageDraft(self.passage_a, 0, self.text_a), PassageDraft(self.passage_b, 0, self.text_b)),
        ):
            with self.subTest(passages=passages):
                with self.assertRaises(ValidationError):
                    prepare_lane_b_diary_job(NarrationJobId(uuid(103)), self.contract, make_defaults(), passages, NOW)
        with self.assertRaises(ValidationError):
            self.job.reorder_passages((self.passage_a, self.passage_a), expected_revision=1)

    def test_INV_NJ_4_text_revision_preserves_takes_and_makes_only_text_stale(self) -> None:
        recipe = make_recipe(self.text_a)
        self.job.record_render_recipe(self.passage_a, recipe, expected_revision=1)
        take = make_take(job_id=self.job_id, passage_id=self.passage_a, text=self.text_a, recipe=recipe, contract=self.contract)
        self.job.record_take(take, expected_revision=2)
        self.job.revise_passage_text(self.passage_a, PassageText("ଅଆଇ"), NOW, expected_revision=3)
        self.assertEqual(len(self.job.passage(self.passage_a).text_revisions), 2)
        self.assertEqual(self.job.takes, (take,))
        self.assertEqual(self.job.eligibility_for(take, authority_eligible=True), EligibilityFacts(True, False, False, False, False))

    def test_INV_NJ_8_and_INV_NJ_10_lane_contract_and_authority_binding_are_fixed(self) -> None:
        lane_c_contract = make_contract(lane=Lane.C)
        lane_c = prepare_lane_c_intro_job(
            NarrationJobId(uuid(104)), lane_c_contract, make_defaults("c"),
            (PassageDraft(PassageId(uuid(105)), 0, PassageText("ଅ")),), NOW,
        )
        self.assertEqual((self.job.lane, lane_c.lane), (Lane.B, Lane.C))
        self.assertNotEqual(self.job.contract.authority_record_id, lane_c.contract.authority_record_id)
        with self.assertRaises(ValidationError):
            prepare_lane_b_diary_job(NarrationJobId(uuid(106)), lane_c_contract, make_defaults(), (PassageDraft(self.passage_a, 0, self.text_a),), NOW)

    def test_INV_NJ_11_and_INV_NJ_15_recipe_binds_text_and_cannot_override_contract(self) -> None:
        recipe = make_recipe(self.text_a)
        self.job.record_render_recipe(self.passage_a, recipe, expected_revision=1)
        self.assertEqual(self.job.passage(self.passage_a).recipes, (recipe,))
        wrong_text_recipe = replace(recipe, text_digest=self.text_b.digest)
        with self.assertRaises(ValidationError):
            self.job.record_render_recipe(self.passage_a, wrong_text_recipe, expected_revision=2)
        self.assertEqual(self.job.contract, self.contract)

    def test_INV_NJ_16_recipe_dictionary_contract_and_authority_ineligibility_are_distinct(self) -> None:
        recipe_a = make_recipe(self.text_a, recipe_index=110)
        recipe_b = make_recipe(self.text_a, recipe_index=111, revision=2)
        self.job.record_render_recipe(self.passage_a, recipe_a, expected_revision=1)
        self.job.record_render_recipe(self.passage_a, recipe_b, expected_revision=2)
        take = make_take(job_id=self.job_id, passage_id=self.passage_a, text=self.text_a, recipe=recipe_a, contract=self.contract)
        self.job.record_take(take, expected_revision=3)
        self.job.require_render_recipe(self.passage_a, recipe_b.recipe_id, expected_revision=4)
        self.assertEqual(self.job.eligibility_for(take, authority_eligible=True), EligibilityFacts(False, True, False, False, False))
        self.job.require_dictionary_digest(self.passage_a, digest("different-dictionary"), expected_revision=5)
        self.assertEqual(self.job.eligibility_for(take, authority_eligible=False), EligibilityFacts(False, True, True, False, True))
        other_contract_take = replace(take, contract_digest=digest("other-contract"), effective_input=replace(take.effective_input, contract_digest=digest("other-contract")))
        self.assertTrue(self.job.eligibility_for(other_contract_take, authority_eligible=True).contract_ineligible)

    def test_INV_NJ_14_preview_is_append_only_revision_bound_and_freezes_exact_bytes(self) -> None:
        recipe = make_recipe(self.text_a)
        self.job.record_render_recipe(self.passage_a, recipe, expected_revision=1)
        value = make_preview(job_id=self.job_id, base_revision=2, passage_id=self.passage_a, text=self.text_a, recipe=recipe, contract=self.contract)
        self.job.issue_generation_preview(value, expected_revision=2)
        self.assertEqual((self.job.revision, self.job.previews), (3, (value,)))
        self.assertEqual(value.rendered_transcript_bytes, f"<fake>{self.text_a.value}</fake>".encode("utf-8"))
        with self.assertRaises(RevisionConflict):
            self.job.issue_generation_preview(value, expected_revision=2)
        stale = make_preview(job_id=self.job_id, base_revision=2, passage_id=self.passage_a, text=self.text_a, recipe=recipe, contract=self.contract, preview_index=112)
        with self.assertRaises(ValidationError):
            self.job.issue_generation_preview(stale, expected_revision=3)


if __name__ == "__main__":
    unittest.main()
