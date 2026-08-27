from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.youtube_enhance.legacy_guard import (
    hash_external_artifacts,
    inventory_tree,
    write_baseline,
)


class LegacyGuardTests(unittest.TestCase):
    def test_inventory_is_sorted_and_does_not_change_the_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "cache").mkdir()
            artifact = root / "cache" / "chunk.bin"
            artifact.write_bytes(b"validated")
            before = artifact.stat()

            result = inventory_tree(root)

            self.assertEqual([row["path"] for row in result["entries"]], ["cache/chunk.bin"])
            after = artifact.stat()
            self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))

    def test_external_hashes_accept_only_explicit_regular_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = Path(folder) / "source.bin"
            artifact.write_bytes(b"validated")
            expected = hashlib.sha256(b"validated").hexdigest()
            result = hash_external_artifacts({artifact: expected})
            self.assertTrue(result[str(artifact.resolve())]["matches"])

    def test_inventory_rejects_a_missing_root(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                inventory_tree(Path(folder) / "missing")

    def test_external_hashes_reject_a_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                hash_external_artifacts({Path(folder): "A" * 64})

    def test_external_hashes_reject_a_filesystem_root(self):
        filesystem_root = Path(Path.cwd().anchor)

        with self.assertRaises(ValueError):
            hash_external_artifacts({filesystem_root: "A" * 64})

    def test_external_hashes_reject_non_normalized_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "nested").mkdir()
            artifact = root / "source.bin"
            artifact.write_bytes(b"validated")
            alias = root / "nested" / ".." / "source.bin"

            with self.assertRaises(ValueError):
                hash_external_artifacts({alias: hashlib.sha256(b"validated").hexdigest()})

    def test_external_hashes_reject_reparse_ancestors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "target"
            target.mkdir()
            artifact = target / "source.bin"
            artifact.write_bytes(b"validated")
            linked = root / "linked"
            try:
                os.symlink(target, linked, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with self.assertRaises(ValueError):
                hash_external_artifacts(
                    {linked / "source.bin": hashlib.sha256(b"validated").hexdigest()}
                )

    def test_inventory_rejects_reparse_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "root"
            target = Path(folder) / "target"
            root.mkdir()
            target.mkdir()
            try:
                os.symlink(target, root / "linked", target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with self.assertRaises(ValueError):
                inventory_tree(root)

    def test_external_hashes_reject_reparse_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "target.bin"
            target.write_bytes(b"validated")
            linked = root / "linked.bin"
            try:
                os.symlink(target, linked)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with self.assertRaises(ValueError):
                hash_external_artifacts({linked: "A" * 64})

    def test_write_baseline_preserves_the_protected_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            root = workspace / "protected"
            root.mkdir()
            protected = root / "cache.bin"
            protected.write_bytes(b"protected")
            before = protected.stat()
            external = workspace / "source.bin"
            external.write_bytes(b"validated")
            destination = workspace / "evidence" / "baseline.json"

            write_baseline(
                root,
                destination,
                {external: hashlib.sha256(b"validated").hexdigest()},
            )

            after = protected.stat()
            self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))
            baseline = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(baseline["root"], str(root.resolve()))
            self.assertTrue(baseline["external_artifacts"][str(external.resolve())]["matches"])

    def test_write_baseline_rejects_mismatched_hash_without_creating_output(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            root = workspace / "protected"
            root.mkdir()
            external = workspace / "source.bin"
            external.write_bytes(b"validated")
            destination = workspace / "evidence" / "baseline.json"

            with self.assertRaises(ValueError):
                write_baseline(root, destination, {external: "A" * 64})

            self.assertFalse(destination.exists())

    @unittest.skipUnless(os.name == "nt", "Windows long-path regression")
    def test_inventory_reads_a_file_beyond_windows_max_path(self):
        folder = tempfile.mkdtemp()
        try:
            root = Path(folder) / "protected"
            deep = root
            while len(str(deep / "chunk.bin")) <= 260:
                deep /= "x"
            extended_deep = "\\\\?\\" + str(deep.resolve())
            os.makedirs(extended_deep)
            artifact = deep / "chunk.bin"
            descriptor = os.open("\\\\?\\" + str(artifact), os.O_WRONLY | os.O_CREAT)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(b"validated")

            try:
                result = inventory_tree(root)
            except FileNotFoundError as error:
                self.fail(f"long Windows path inventory failed: {error}")

            self.assertEqual(result["entries"][-1]["path"], artifact.relative_to(root).as_posix())
        finally:
            shutil.rmtree("\\\\?\\" + folder)
