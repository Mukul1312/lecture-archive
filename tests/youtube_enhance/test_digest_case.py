"""One canonical digest string across both content stores.

``scripts/ggsm_transcription/store.py`` records lowercase SHA-256 and rejects
anything else (``_SHA256 = re.compile(r"^[0-9a-f]{64}$")``, enforced in
``_validate_state``).  ``scripts/youtube_enhance/`` used to record uppercase.
The same lecture bytes therefore carried two different string identities and
the transcription and enhancement flows could not cross-reference each other
at all.

Lowercase is the canonical form.  It is what ``hashlib.hexdigest()`` returns
unmodified, what ``manifest.py::cache_key`` and all three fingerprints already
produced, and what the transcription store requires.  These tests pin that
form so it cannot drift back.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tempfile
import unittest

from scripts.ggsm_transcription import store as transcription_store
from scripts.youtube_enhance import local_d30
from scripts.youtube_enhance.source import sha256_file


ENHANCEMENT_PACKAGE = Path(__file__).resolve().parents[2] / "scripts" / "youtube_enhance"
LOWERCASE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _module_sources() -> dict[str, str]:
    return {
        module.name: module.read_text(encoding="utf-8")
        for module in sorted(ENHANCEMENT_PACKAGE.glob("*.py"))
    }


class CanonicalDigestCaseTests(unittest.TestCase):
    def test_both_stores_produce_the_same_identity_for_the_same_bytes(self):
        payload = b"one lecture, two flows, one identity"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "lecture.bin"
            source.write_bytes(payload)

            enhancement_digest = sha256_file(source)
            transcription_digest, _size = transcription_store._hash_file(source)

        self.assertEqual(enhancement_digest, transcription_digest)
        self.assertEqual(enhancement_digest, hashlib.sha256(payload).hexdigest())

    def test_a_transcription_job_id_accepts_an_enhancement_digest(self):
        payload = b"the cross-reference that could not be made"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "lecture.bin"
            source.write_bytes(payload)
            digest = sha256_file(source)

        # make_job_id raises JobValidationError on anything but lowercase.
        job_id = transcription_store.make_job_id("ssggsm-1985-08-08", digest)
        self.assertTrue(job_id.endswith(f"-{digest[:8]}"))

    def test_no_enhancement_module_uppercases_a_digest(self):
        for name, text in _module_sources().items():
            with self.subTest(module=name):
                self.assertNotIn("hexdigest().upper()", text)

    def test_no_enhancement_module_validates_an_uppercase_digest(self):
        for name, text in _module_sources().items():
            with self.subTest(module=name):
                self.assertNotIn("0-9A-F", text)
                self.assertNotIn("0123456789ABCDEF", text)

    def test_authoritative_local_d30_digests_are_canonical_lowercase(self):
        for label, digest in (
            ("source", local_d30.AUTHORITATIVE_SOURCE_SHA256),
            ("original mid", local_d30.AUTHORITATIVE_ORIGINAL_MID_SHA256),
        ):
            with self.subTest(digest=label):
                self.assertRegex(digest, LOWERCASE_SHA256)


if __name__ == "__main__":
    unittest.main()
