import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

LEGACY_SCRIPTS = (
    "scripts/calibrate_gate.py",
    "scripts/calibrate_gate2.py",
    "scripts/predictiveness.py",
    "scripts/predictiveness2.py",
    "scripts/cut_hi_final.py",
    "scripts/hi/analyze_diary.py",
    "scripts/hi/expressive_refs.py",
    "scripts/hi/funnel_diary.py",
    "scripts/hi/funnel_v3.py",
    "scripts/hi/reconcat_diary.py",
    "scripts/hi/refsweep_score.py",
    "scripts/hi/ref_shortlist.py",
    "scripts/hi/score_comb.py",
    "scripts/hi/score_expr.py",
    "scripts/hi/score_hi_clones.py",
    "scripts/hi/score_v1.py",
)


class LegacyScriptPathTests(unittest.TestCase):
    def test_repository_and_data_roots_resolve_from_every_script_location(self):
        try:
            from scripts.repo_paths import data_root, repository_root
        except ImportError as exc:
            self.fail(f"portable repository path helper is unavailable: {exc}")

        for relative_path in LEGACY_SCRIPTS:
            with self.subTest(script=relative_path):
                script = REPOSITORY_ROOT / relative_path
                self.assertEqual(repository_root(script), REPOSITORY_ROOT)
                self.assertEqual(data_root(script), REPOSITORY_ROOT / "data")

    def test_cut_manifest_default_is_repository_relative(self):
        from scripts import cut_hi_final

        if not hasattr(cut_hi_final, "default_review_manifest"):
            self.fail("cut_hi_final does not expose a portable default review manifest")

        expected = REPOSITORY_ROOT / "data" / "hi" / "train_hi_final.jsonl"
        self.assertEqual(cut_hi_final.default_review_manifest(), expected)


if __name__ == "__main__":
    unittest.main()
