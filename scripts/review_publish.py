"""Publish a lecture's review package to the bucket the review app reads.

    .venv/Scripts/python.exe -m scripts.review_publish bg-3-37-the-duty-of-a-human-being-brisbane

Uploads `data/reference/review/packages/<lecture>/v1.json` to
`gs://ssggsm-seva-media/packages/<lecture>/v1.json`, the place the review app's design gives
packages, with this repository as their only writer. Mukul gave the go-ahead on 30 October 2026.

A published package is never changed. Every answer names its package by the SHA-256 of its
bytes, so replacing one would leave answers pointing at bytes nobody can fetch; a changed
package is a new version. So before anything is sent the package must:

- be the bytes the builder wrote (LF only, since CRLF bytes have a hash no record knows);
- pass the schema and rules P1-P10 again, since a file on disk can be edited after it is built;
- not be a DRAFT, which names a commit that does not hold the code that built it;
- name audio that is in the bucket, or the reviewer gets a stop with nothing to play.

An object already at the name with the same bytes is left alone. One with different bytes is a
refusal, never an overwrite: the upload itself only creates, and fails if the name is taken.
Afterwards the object is read back and compared, byte for byte.

A later version (`--version 2`) also waits for the review app. Until it carries answers over by
stop id, a version 2 would ask reviewers version 1's questions again. So the app's own record of
the contract it understands, `review-assistance/contracts/review.pin.json`, must name a commit
holding the republished example (the change order under "Versioning" in the contract).
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.review_contract import package_rules, schema_errors
from scripts.review_package import OUT, REPO

BUCKET = "gs://ssggsm-seva-media"
APP_PIN = REPO.parent / "review-assistance/contracts/review.pin.json"
REPUBLISHED_EXAMPLE = "contracts/review/examples/valid/package-bg-3-37-brisbane-v2.json"


def object_name(package: dict) -> str:
    lecture, version = package["lecture"]["id"], package["package"]["version"]
    return f"packages/{lecture}/v{version}.json"


def app_takes_republished(pin: Path = APP_PIN) -> bool:
    """Has the review app pinned a contract that holds the republished example?"""
    if not pin.exists():
        return False
    commit = json.loads(pin.read_text(encoding="utf-8"))["source"]["commit"]
    return subprocess.run(["git", "cat-file", "-e", f"{commit}:{REPUBLISHED_EXAMPLE}"], cwd=REPO,
                          capture_output=True).returncode == 0


def publish(path: Path, bucket, app_ready=app_takes_republished) -> str:
    """Upload one package file; return its object name. Refuses rather than overwrites."""
    data = path.read_bytes()
    if b"\r" in data:
        raise ValueError(f"{path} has CR bytes: it is not the file the builder wrote")
    package = json.loads(data.decode("utf-8"))
    errors = schema_errors("lecture-review-package", package)
    broken = package_rules(package)
    if errors or broken:
        lines = errors[:5] + [f"{b.rule}: {b.message}" for b in broken[:5]]
        raise ValueError("refused - the package fails its checks:\n  " + "\n  ".join(lines))
    if package["producer"]["notes"].startswith("DRAFT"):
        raise ValueError("refused - a DRAFT package was built from uncommitted code; commit, "
                         "rebuild, then publish")
    if package["package"]["id"] != f"{package['lecture']['id']}/v{package['package']['version']}":
        raise ValueError(f"the package id {package['package']['id']} does not name its lecture "
                         f"and version")
    if package["package"]["version"] > 1 and not app_ready():
        raise ValueError(f"refused - the review app's pin ({APP_PIN}) does not yet hold the "
                         f"republished example, so it cannot carry answers over to version "
                         f"{package['package']['version']}")
    audio = package["audio"]
    for media in (audio["original"], audio.get("listening_copy")):
        if media and not bucket.exists(media["object"]):
            raise ValueError(f"{media['object']} is not in the bucket, so its stops could not "
                             f"be played")

    name = object_name(package)
    existing = bucket.read(name)
    if existing is not None:
        if existing == data:
            return name
        raise ValueError(f"{name} is already published with different bytes (SHA-256 "
                         f"{hashlib.sha256(existing).hexdigest()}); answers may name it, so a "
                         f"changed package must be a new version")
    bucket.create(name, data)
    if bucket.read(name) != data:
        raise ValueError(f"{name} did not read back as the bytes uploaded")
    return name


class GcloudBucket:
    """The bucket through the `gcloud storage` command, signed in as the person running it."""

    def __init__(self, url: str = BUCKET):
        self.url = url.rstrip("/")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["gcloud", "storage", *args], capture_output=True, text=True,
                              encoding="utf-8", shell=sys.platform == "win32")

    def exists(self, name: str) -> bool:
        return self._run("objects", "describe", f"{self.url}/{name}").returncode == 0

    def read(self, name: str) -> bytes | None:
        if not self.exists(name):
            return None
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "object"
            done = self._run("cp", f"{self.url}/{name}", str(local))
            if done.returncode != 0:
                raise RuntimeError(f"could not read {name}: {done.stderr.strip()[-500:]}")
            return local.read_bytes()

    def create(self, name: str, data: bytes) -> None:
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "v.json"
            local.write_bytes(data)
            # Generation 0 means "only if no object has this name": the upload cannot overwrite.
            done = self._run("cp", "--if-generation-match=0", "--content-type=application/json",
                             str(local), f"{self.url}/{name}")
            if done.returncode != 0:
                raise RuntimeError(f"could not upload {name}: {done.stderr.strip()[-500:]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("lectures", nargs="+", help="lecture slugs whose local package to publish")
    parser.add_argument("--version", type=int, default=1,
                        help="which local version to publish (default 1)")
    args = parser.parse_args(argv)
    bucket = GcloudBucket()
    for lecture in args.lectures:
        path = OUT / lecture / f"v{args.version}.json"
        name = publish(path, bucket)
        print(f"{BUCKET}/{name}  SHA-256 {hashlib.sha256(path.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
