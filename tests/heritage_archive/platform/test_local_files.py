"""Focused contracts for durable local file publication."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.platform.storage.local_files import (
    PublicationEvidenceMismatch,
    SingleWriterFileLock,
    WriterLockUnavailable,
    publish_bytes_no_clobber,
    replace_bytes_atomically,
)


class LocalFilePublicationTests(unittest.TestCase):
    def test_second_writer_is_refused_while_application_lock_is_held(self) -> None:
        """Removing non-blocking exclusion would allow two application writers."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / ".writer.lock"
            with SingleWriterFileLock(lock_path):
                with self.assertRaises(WriterLockUnavailable):
                    with SingleWriterFileLock(lock_path):
                        pass

    def test_no_clobber_publication_reports_and_writes_the_exact_payload(self) -> None:
        """Returning invented evidence or writing altered bytes must be observable."""
        payload = b"immutable narration evidence\x00\xff"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "artifacts" / "narration.wav"

            published = publish_bytes_no_clobber(root / "staging", destination, payload)

            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(published.sha256_hex, hashlib.sha256(payload).hexdigest())
            self.assertEqual(published.byte_length, len(payload))

    def test_no_clobber_publication_preserves_an_existing_immutable_destination(self) -> None:
        """Replacing an already published immutable file would destroy evidence."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging = root / "staging"
            destination = root / "artifacts" / "narration.wav"
            publish_bytes_no_clobber(staging, destination, b"first immutable bytes")

            with self.assertRaises(FileExistsError):
                publish_bytes_no_clobber(staging, destination, b"replacement bytes")

            self.assertEqual(destination.read_bytes(), b"first immutable bytes")
            self.assertEqual(len(list(staging.iterdir())), 1)

    def test_no_clobber_publication_preserves_a_caller_selected_json_stage_on_interruption(self) -> None:
        """Ignoring a requested suffix would make aggregate staging violate its durable layout."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging = root / "staging"
            destination = root / "aggregates" / "record.json"

            with patch.object(Path, "rename", side_effect=OSError("interrupted publication")):
                with self.assertRaises(OSError):
                    publish_bytes_no_clobber(staging, destination, b"canonical record", staging_suffix=".json")

            self.assertEqual(tuple(path.suffix for path in staging.iterdir()), (".json",))

    def test_publication_preserves_staging_when_reread_evidence_differs_from_payload(self) -> None:
        """Skipping reread verification would publish a file whose evidence is unproven."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            staging = root / "staging"
            destination = root / "artifacts" / "narration.wav"

            with patch.object(Path, "read_bytes", return_value=b"changed after fsync"):
                with self.assertRaises(PublicationEvidenceMismatch):
                    publish_bytes_no_clobber(staging, destination, b"expected payload")

            self.assertFalse(destination.exists())
            self.assertEqual(len(list(staging.iterdir())), 1)

    def test_atomic_replacement_exchanges_an_explicitly_mutable_file(self) -> None:
        """Using no-clobber for mutable operational data would leave it stale."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "operations" / "budget-ledger.json"
            destination.parent.mkdir()
            destination.write_bytes(b"old ledger")

            published = replace_bytes_atomically(
                root / "staging", destination, b"new ledger"
            )

            self.assertEqual(destination.read_bytes(), b"new ledger")
            self.assertEqual(published.byte_length, len(b"new ledger"))
