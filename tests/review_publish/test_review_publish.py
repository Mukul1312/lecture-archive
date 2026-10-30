"""What must be true before a review package goes where reviewers will open it.

An answer names its package by the SHA-256 of its bytes, so a published package can never be
changed: a second upload under the same name would leave every answer pointing at bytes nobody
can fetch. A package built from uncommitted code names a commit that does not hold that code.
And a package whose audio is not in the bucket gives the reviewer a stop with nothing to play.
These tests use a bucket held in memory; nothing here reaches the cloud.
"""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.review_publish import object_name, publish

EXAMPLE = Path("contracts/review/examples/valid/package-bg-3-37-brisbane.json")


class MemoryBucket:
    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})
        self.created: list[str] = []

    def exists(self, name: str) -> bool:
        return name in self.objects

    def read(self, name: str) -> bytes | None:
        return self.objects.get(name)

    def create(self, name: str, data: bytes) -> None:
        if name in self.objects:
            raise FileExistsError(name)
        self.objects[name] = data
        self.created.append(name)


def write(package: dict, folder: Path) -> Path:
    path = folder / "v1.json"
    path.write_bytes((json.dumps(package, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return path


def bucket_with_audio(package: dict) -> MemoryBucket:
    audio = package["audio"]
    return MemoryBucket({audio["original"]["object"]: b"original",
                         audio["listening_copy"]["object"]: b"copy"})


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.package = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.package["producer"]["notes"] = "Built for the test."
        self.folder = Path(tempfile.mkdtemp())

    def test_a_package_is_uploaded_under_its_own_name_and_read_back(self):
        path = write(self.package, self.folder)
        bucket = bucket_with_audio(self.package)
        name = publish(path, bucket)
        self.assertEqual(name, "packages/bg-3-37-the-duty-of-a-human-being-brisbane/v1.json")
        self.assertEqual(bucket.created, [name])
        self.assertEqual(bucket.objects[name], path.read_bytes())

    def test_a_draft_is_refused_and_nothing_is_uploaded(self):
        self.package["producer"]["notes"] = "DRAFT, not for publishing: the producer code ..."
        bucket = bucket_with_audio(self.package)
        with self.assertRaisesRegex(ValueError, "DRAFT"):
            publish(write(self.package, self.folder), bucket)
        self.assertEqual(bucket.created, [])

    def test_a_package_that_breaks_a_rule_is_refused(self):
        broken = copy.deepcopy(self.package)
        broken["stops"].reverse()                       # P4: stops out of timeline order
        bucket = bucket_with_audio(broken)
        with self.assertRaisesRegex(ValueError, "P4"):
            publish(write(broken, self.folder), bucket)
        self.assertEqual(bucket.created, [])

    def test_a_package_whose_audio_is_not_in_the_bucket_is_refused(self):
        bucket = MemoryBucket()
        with self.assertRaisesRegex(ValueError, "not in the bucket"):
            publish(write(self.package, self.folder), bucket)
        self.assertEqual(bucket.created, [])

    def test_a_published_package_is_never_replaced_by_different_bytes(self):
        path = write(self.package, self.folder)
        bucket = bucket_with_audio(self.package)
        bucket.objects[object_name(self.package)] = b"the bytes reviewers already answered"
        with self.assertRaisesRegex(ValueError, "already published with different bytes"):
            publish(path, bucket)
        self.assertEqual(bucket.objects[object_name(self.package)],
                         b"the bytes reviewers already answered")

    def test_publishing_the_same_bytes_twice_is_harmless(self):
        path = write(self.package, self.folder)
        bucket = bucket_with_audio(self.package)
        publish(path, bucket)
        publish(path, bucket)
        self.assertEqual(len(bucket.created), 1)

    def test_a_file_with_crlf_line_endings_is_refused(self):
        # The SHA-256 is of the bytes as written; a checkout that turned LF into CRLF would
        # publish a file whose hash no local record knows.
        path = write(self.package, self.folder)
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(ValueError, "CR"):
            publish(path, bucket_with_audio(self.package))

    def test_the_upload_is_checked_by_reading_it_back(self):
        class Corrupting(MemoryBucket):
            def create(self, name, data):
                super().create(name, data[:-1])
        path = write(self.package, self.folder)
        bucket = Corrupting(bucket_with_audio(self.package).objects)
        with self.assertRaisesRegex(ValueError, "read back"):
            publish(path, bucket)
        self.assertNotEqual(hashlib.sha256(bucket.objects[object_name(self.package)]).hexdigest(),
                            hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
