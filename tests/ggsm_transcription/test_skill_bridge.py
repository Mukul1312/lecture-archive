"""Contracts for the explicit GGSM transcription skill and Claude bridge."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SKILL = REPOSITORY_ROOT / ".agents" / "skills" / "transcribing-ggsm-lecture"
CLAUDE_BRIDGE = (
    REPOSITORY_ROOT
    / ".claude"
    / "skills"
    / "transcribing-ggsm-lecture"
    / "SKILL.md"
)


class GgsmTranscriptionSkillContractTests(unittest.TestCase):
    def _read(self, path: Path) -> str:
        self.assertTrue(path.is_file(), f"required file is missing: {path.relative_to(REPOSITORY_ROOT)}")
        return path.read_text(encoding="utf-8")

    def test_canonical_skill_is_explicit_only_and_preserves_workflow_boundaries(self) -> None:
        skill = self._read(CANONICAL_SKILL / "SKILL.md")
        metadata = self._read(CANONICAL_SKILL / "agents" / "openai.yaml")
        workflow = self._read(CANONICAL_SKILL / "references" / "workflow.md")
        editorial_rules = self._read(CANONICAL_SKILL / "references" / "editorial-rules.md")

        self.assertRegex(skill, r"(?s)^---\s*\nname: transcribing-ggsm-lecture\s*\n")
        self.assertRegex(skill, r"(?m)^description: Use when .+English SSGGSM archive lecture")
        self.assertIn("$transcribing-ggsm-lecture <URL>", skill)
        self.assertIn("only explicit invocation", skill)
        self.assertIn("references/workflow.md", skill)
        self.assertIn("references/editorial-rules.md", skill)

        self.assertRegex(metadata, r'(?m)^\s*display_name: "[^"]+"$')
        short_description = re.search(r'(?m)^\s*short_description: "([^"]+)"$', metadata)
        self.assertIsNotNone(short_description)
        assert short_description is not None
        self.assertGreaterEqual(len(short_description.group(1)), 25)
        self.assertLessEqual(len(short_description.group(1)), 64)
        self.assertRegex(
            metadata,
            r'(?m)^\s*default_prompt: "[^"\n]*\$transcribing-ggsm-lecture[^"\n]*"$',
        )
        self.assertIn("policy:\n  allow_implicit_invocation: false", metadata)

        self.assertIn("python -m scripts.ggsm_transcription intake --url <https-url>", workflow)
        self.assertIn("SHA-256", workflow)
        self.assertRegex(
            workflow,
            r"never the URL, filename,\s*duration, chat memory",
        )
        self.assertIn("matching partial job", workflow)
        self.assertIn("intake, local full ASR, inspection", workflow)
        self.assertIn("whole-timeline listening/editing", workflow)
        self.assertIn("local-only", workflow)
        self.assertIn("RunPod", workflow)
        self.assertIn("OneNote", workflow)

        self.assertIn("source audio", editorial_rules)
        self.assertIn("whole timeline", editorial_rules)
        self.assertIn("ASR-uncovered", editorial_rules)
        self.assertIn("secondary evidence", editorial_rules)
        self.assertIn("locally captured", editorial_rules)
        self.assertIn("register-reference", editorial_rules)
        self.assertIn("[Non-English interpretation omitted, HH:MM:SS-HH:MM:SS]", editorial_rules)
        self.assertIn("[Recording silence, HH:MM:SS-HH:MM:SS]", editorial_rules)
        self.assertIn("[Indistinct English speech, HH:MM:SS-HH:MM:SS]", editorial_rules)
        self.assertIn("audio", editorial_rules)
        self.assertIn("Status: Listening draft", editorial_rules)
        self.assertIn("manual OneNote", editorial_rules)
        self.assertIn("five minutes", editorial_rules)
        self.assertIn("hashes and diagnostics", editorial_rules)

    def test_claude_bridge_is_minimal_non_symlink_delegation_to_the_canonical_skill(self) -> None:
        bridge = self._read(CLAUDE_BRIDGE)

        self.assertFalse(CLAUDE_BRIDGE.is_symlink())
        self.assertIn("/transcribing-ggsm-lecture <URL>", bridge)
        self.assertIn(".agents/skills/transcribing-ggsm-lecture/SKILL.md", bridge)
        self.assertIn("python -m scripts.ggsm_transcription", bridge)
        self.assertIn("canonical", bridge.casefold())
        self.assertIn("canonical instructions win", bridge.casefold())
        self.assertLessEqual(len(bridge.split()), 180)
        for detailed_rule in (
            "[Non-English interpretation omitted",
            "[Recording silence",
            "[Indistinct English speech",
            "record-review",
            "register-reference",
        ):
            self.assertNotIn(detailed_rule, bridge)

    def test_gitignore_tracks_the_bridge_but_ignores_claude_siblings_and_cache_artifacts(self) -> None:
        tracked_bridge = ".claude/skills/transcribing-ggsm-lecture/SKILL.md"
        ignored_sibling = ".claude/skills/transcribing-ggsm-lecture/local-cache.json"
        ignored_cache = ".claude/skills/another-local-skill/SKILL.md"

        for path, expected_returncode in (
            (tracked_bridge, 1),
            (ignored_sibling, 0),
            (ignored_cache, 0),
        ):
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "check-ignore", "-q", "--no-index", path],
                    cwd=REPOSITORY_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    result.returncode,
                    expected_returncode,
                    result.stderr,
                )
