"""Focused contracts for the explicit Narrator Voice local root."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LocalNarrationRootTests(unittest.TestCase):
    def test_open_rejects_relative_and_missing_roots(self) -> None:
        """Accepting implicit or absent roots could write into an unsafe location."""
        with self.assertRaises(ValueError):
            LocalNarrationRoot.open("narration-root", ())
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaises(ValueError):
                LocalNarrationRoot.open(Path(temporary_directory) / "missing", ())

    def test_open_rejects_a_root_inside_the_repository_or_worktree(self) -> None:
        """A repository descendant must never be accepted as durable external storage."""
        with self.assertRaises(ValueError):
            LocalNarrationRoot.open(PROJECT_ROOT, (PROJECT_ROOT,))

    def test_open_accepts_an_existing_external_root_and_initializes_only_safe_layout(self) -> None:
        """Changing a safe child name would make later durable adapters write elsewhere."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = LocalNarrationRoot.open(Path(temporary_directory), (PROJECT_ROOT,))

            root.initialize_layout()

            self.assertEqual(root.path, Path(temporary_directory).resolve())
            self.assertEqual(
                {child.name for child in root.path.iterdir()},
                {"aggregates", "staging", "artifacts", "attempts", "operations"},
            )
            self.assertEqual(root.writer_lock, root.path / ".writer.lock")
            self.assertTrue(all(directory.is_dir() for directory in root.layout_directories))

    def test_open_rejects_filesystem_root_and_regular_files(self) -> None:
        """A filesystem root or plain file is not a dedicated durable storage root."""
        with self.assertRaises(ValueError):
            LocalNarrationRoot.open(Path(Path.cwd().anchor), ())
        with tempfile.TemporaryDirectory() as temporary_directory:
            regular_file = Path(temporary_directory) / "not-a-directory"
            regular_file.write_text("not a root", encoding="utf-8")
            with self.assertRaises(ValueError):
                LocalNarrationRoot.open(regular_file, ())
