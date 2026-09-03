"""Contract tests for immutable Narrator Voice artifact evidence on disk."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ArtifactId, ArtifactRef, ContentDigest, ValidationError
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    PublishedArtifact,
    SubmissionEvidence,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    BudgetReservationId,
    GenerationAttemptId,
    NarrationJobId,
)
from heritage_archive.contexts.narrator_voice.domain.values import SafeRelativeArtifactPath
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemArtifactEvidenceVerifier,
    FilesystemArtifactStore,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from tests.heritage_archive.narrator_voice.fixtures import NOW, digest, uuid


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FilesystemEvidenceContracts(unittest.TestCase):
    def test_publish_binds_exact_bytes_to_safe_location_and_delays_identity_until_available(self) -> None:
        """Issuing an ID before no-clobber availability can orphan an artifact identity."""
        payload = b"RIFF exact immutable narration bytes"
        identifier = _IdentifierSource([ArtifactId(uuid(300))])
        with self._storage_root() as root:
            publication = FilesystemArtifactStore(root, identifier).publish(
                SafeRelativeArtifactPath("takes/first.wav"), payload, "audio/wav", NOW
            )

            self.assertEqual((root.artifacts / "takes" / "first.wav").read_bytes(), payload)
            self.assertEqual(publication.reference.artifact_id, ArtifactId(uuid(300)))
            self.assertEqual(publication.reference.content_digest, ContentDigest.from_bytes(payload))
            self.assertEqual(publication.reference.byte_size, len(payload))
            self.assertEqual(publication.reference.media_type, "audio/wav")
            self.assertEqual(publication.relative_location, SafeRelativeArtifactPath("takes/first.wav"))
            self.assertEqual(publication.published_at, NOW)
            self.assertEqual(identifier.calls, [ArtifactId])

    def test_publish_refuses_conflicting_existing_location_without_consuming_another_id(self) -> None:
        """Allowing a repeat publish would make a path bind two immutable artifact IDs."""
        payload = b"same exact immutable bytes"
        identifier = _IdentifierSource([ArtifactId(uuid(301)), ArtifactId(uuid(302))])
        with self._storage_root() as root:
            store = FilesystemArtifactStore(root, identifier)
            store.publish(SafeRelativeArtifactPath("takes/occupied.wav"), payload, "audio/wav", NOW)

            with self.assertRaisesRegex(ValidationError, "occupied"):
                store.publish(SafeRelativeArtifactPath("takes/occupied.wav"), payload, "audio/wav", NOW)

            self.assertEqual((root.artifacts / "takes" / "occupied.wav").read_bytes(), payload)
            self.assertEqual(identifier.calls, [ArtifactId])

    def test_publish_rejects_invalid_publication_time_before_mutating_disk(self) -> None:
        """Writing before time validation could leave bytes without valid publication evidence."""
        identifier = _IdentifierSource([ArtifactId(uuid(306))])
        with self._storage_root() as root:
            with self.assertRaises(ValidationError):
                FilesystemArtifactStore(root, identifier).publish(
                    SafeRelativeArtifactPath("takes/invalid-time.wav"), b"payload", "audio/wav", NOW.replace(tzinfo=None)
                )

            self.assertFalse((root.artifacts / "takes" / "invalid-time.wav").exists())
            self.assertEqual(identifier.calls, [])

    def test_publish_rejects_a_regular_file_ancestor_before_requesting_an_artifact_id(self) -> None:
        """A non-directory parent would make the destination unavailable after an ID was consumed."""
        identifier = _IdentifierSource([ArtifactId(uuid(307))])
        with self._storage_root() as root:
            (root.artifacts / "takes").write_bytes(b"not a directory")

            with self.assertRaises(ValidationError):
                FilesystemArtifactStore(root, identifier).publish(
                    SafeRelativeArtifactPath("takes/x.wav"), b"payload", "audio/wav", NOW
                )

            self.assertFalse((root.artifacts / "takes" / "x.wav").exists())
            self.assertEqual(identifier.calls, [])

    def test_publish_rejects_traversal_and_reparse_path_components(self) -> None:
        """Resolving a traversal or junction could publish evidence outside the dedicated root."""
        identifier = _IdentifierSource([ArtifactId(uuid(303))])
        with self._storage_root() as root:
            store = FilesystemArtifactStore(root, identifier)
            (root.artifacts / "linked").mkdir()
            with self.assertRaises(ValidationError):
                SafeRelativeArtifactPath("../escape.wav")
            with patch(
                "heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence._is_reparse_point",
                side_effect=lambda path: path == root.artifacts / "linked",
            ):
                with self.assertRaisesRegex(ValidationError, "reparse"):
                    store.publish(SafeRelativeArtifactPath("linked/escape.wav"), b"payload", "audio/wav", NOW)

            self.assertEqual(identifier.calls, [])

    def test_verifier_accepts_repeated_same_byte_observation(self) -> None:
        """A verifier that changes trusted facts on reread cannot support restart recovery."""
        payload = b"stable artifact evidence"
        with self._storage_root() as root:
            publication = FilesystemArtifactStore(root, _IdentifierSource([ArtifactId(uuid(304))])).publish(
                SafeRelativeArtifactPath("takes/stable.wav"), payload, "audio/wav", NOW
            )
            workspace = self._published_workspace(publication)
            verifier = FilesystemArtifactEvidenceVerifier(root)

            first = verifier.verify(workspace)
            second = verifier.verify(workspace)

            self.assertEqual(first, second)
            self.assertEqual((first.artifact_observed, first.artifact_verified), (True, True))
            self.assertEqual((first.publication_observed, first.publication_verified), (True, True))

    def test_verifier_refuses_tampered_bytes_or_wrong_length(self) -> None:
        """Trusting an existing pathname without its exact byte evidence would accept altered audio."""
        payload = b"unaltered bytes"
        with self._storage_root() as root:
            publication = FilesystemArtifactStore(root, _IdentifierSource([ArtifactId(uuid(305))])).publish(
                SafeRelativeArtifactPath("takes/tampered.wav"), payload, "audio/wav", NOW
            )
            (root.artifacts / "takes" / "tampered.wav").write_bytes(b"tampered and longer")

            facts = FilesystemArtifactEvidenceVerifier(root).verify(self._published_workspace(publication))

            self.assertEqual((facts.artifact_observed, facts.artifact_verified), (True, False))
            self.assertEqual((facts.publication_observed, facts.publication_verified), (True, False))

    def test_verifier_refuses_an_extra_unpublished_staged_artifact(self) -> None:
        """Treating staged containment as enough would accept an unpaired artifact in recovery evidence."""
        payload = b"paired artifact bytes"
        with self._storage_root() as root:
            publication = FilesystemArtifactStore(root, _IdentifierSource([ArtifactId(uuid(308))])).publish(
                SafeRelativeArtifactPath("takes/paired.wav"), payload, "audio/wav", NOW
            )
            extra = ArtifactRef(ArtifactId(uuid(309)), digest("unpaired"), 8, "audio/wav")
            workspace = self._published_workspace(publication, (publication.reference, extra))

            facts = FilesystemArtifactEvidenceVerifier(root).verify(workspace)

            self.assertEqual((facts.artifact_observed, facts.artifact_verified), (True, False))
            self.assertEqual((facts.publication_observed, facts.publication_verified), (True, False))

    def test_verifier_refuses_a_duplicate_staged_reference_for_one_publication(self) -> None:
        """Ignoring multiplicity would allow one publication to satisfy two staged artifact claims."""
        payload = b"one publication only"
        with self._storage_root() as root:
            publication = FilesystemArtifactStore(root, _IdentifierSource([ArtifactId(uuid(320))])).publish(
                SafeRelativeArtifactPath("takes/duplicated.wav"), payload, "audio/wav", NOW
            )
            workspace = self._published_workspace(publication, (publication.reference, publication.reference))

            facts = FilesystemArtifactEvidenceVerifier(root).verify(workspace)

            self.assertEqual((facts.artifact_observed, facts.artifact_verified), (True, False))
            self.assertEqual((facts.publication_observed, facts.publication_verified), (True, False))

    @staticmethod
    def _published_workspace(
        publication: PublishedArtifact,
        staged_artifacts: tuple[ArtifactRef, ...] | None = None,
    ) -> AttemptWorkspaceEvidence:
        return AttemptWorkspaceEvidence(
            AttemptWorkspaceId(uuid(310)),
            AttemptKind.GENERATION,
            NarrationJobId(uuid(311)),
            GenerationAttemptId(uuid(312)),
            1,
            BudgetReservationId(uuid(313)),
            digest("preview"),
            digest("input"),
            SubmissionEvidence.COMPLETED,
            (),
            (publication.reference,) if staged_artifacts is None else staged_artifacts,
            (publication,),
            (),
            AttemptState.ARTIFACTS_PUBLISHED,
        )

    def _storage_root(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = LocalNarrationRoot.open(Path(temporary_directory.name), (PROJECT_ROOT,))
        root.initialize_layout()
        return _StorageRootContext(root)


class _IdentifierSource:
    def __init__(self, values: list[ArtifactId]) -> None:
        self._values = list(values)
        self.calls: list[type[object]] = []

    def new_id(self, kind):
        self.calls.append(kind)
        return self._values.pop(0)


class _StorageRootContext:
    def __init__(self, root: LocalNarrationRoot) -> None:
        self._root = root

    def __enter__(self) -> LocalNarrationRoot:
        return self._root

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
