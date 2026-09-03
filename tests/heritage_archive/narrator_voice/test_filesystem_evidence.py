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

from heritage_archive.kernel import (
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    ValidationError,
    canonical_json,
    parse_strict_json,
)
from heritage_archive.contexts.narrator_voice.application.schema_v1 import (
    decode_schema_v1,
    encode_schema_v1,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    PublishedArtifact,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
    SubmissionEvidence,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    BudgetReservationId,
    GenerationAttemptId,
    NarrationJobId,
    ProviderEventId,
)
from heritage_archive.contexts.narrator_voice.application.recovery import (
    BudgetRecoveryState,
    GenerationRecoveryTarget,
    RecoveryDisposition,
    RecoveryFacts,
    RecoveryStage,
    decide_target_recovery,
)
from heritage_archive.contexts.narrator_voice.domain.values import SafeRelativeArtifactPath
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemArtifactEvidenceVerifier,
    FilesystemArtifactStore,
    FilesystemAttemptWorkspaceStore,
    FilesystemAttemptWorkspaceVerifier,
    FilesystemProviderEventVerifier,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import (
    CanonicalWavInspector,
    encode_canonical_pcm16_wav,
)
from heritage_archive.contexts.narrator_voice.domain.values import CanonicalAudioFacts
from tests.heritage_archive.narrator_voice.fixtures import NOW, digest, uuid


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FilesystemEvidenceContracts(unittest.TestCase):
    def test_workspace_store_loads_legacy_record_missing_only_raw_timing_reference(self) -> None:
        with self._storage_root() as root:
            workspace = self._published_workspace(
                PublishedArtifact(
                    ArtifactRef(
                        ArtifactId(uuid(332)),
                        digest("legacy canonical audio"),
                        22,
                        "audio/wav",
                    ),
                    SafeRelativeArtifactPath("takes/legacy.wav"),
                    NOW,
                )
            )
            legacy = self._legacy_workspace_record(workspace)
            path = (
                root.attempts
                / workspace.attempt_kind.value
                / f"{workspace.attempt_id.value}.json"
            )
            path.parent.mkdir()
            path.write_bytes(legacy)

            with self.assertRaises(ValidationError):
                decode_schema_v1(legacy, AttemptWorkspaceEvidence)
            loaded = FilesystemAttemptWorkspaceStore(root).load(workspace.attempt_id)

            self.assertEqual(loaded, workspace)
            self.assertIsNone(loaded.raw_timing_reference)

    def test_workspace_store_legacy_read_migration_rejects_unknown_or_other_missing_fields(self) -> None:
        with self._storage_root() as root:
            publication = PublishedArtifact(
                ArtifactRef(
                    ArtifactId(uuid(333)),
                    digest("strict legacy canonical audio"),
                    29,
                    "audio/wav",
                ),
                SafeRelativeArtifactPath("takes/strict-legacy.wav"),
                NOW,
            )
            workspace = self._published_workspace(publication)
            path = (
                root.attempts
                / workspace.attempt_kind.value
                / f"{workspace.attempt_id.value}.json"
            )
            path.parent.mkdir()
            legacy_envelope = parse_strict_json(
                self._legacy_workspace_record(workspace)
            )
            unknown = dict(legacy_envelope)
            unknown_payload = dict(legacy_envelope["payload"])
            unknown_payload["unknown"] = True
            unknown["payload"] = unknown_payload
            missing = dict(legacy_envelope)
            missing_payload = dict(legacy_envelope["payload"])
            del missing_payload["state"]
            missing["payload"] = missing_payload

            for invalid in (unknown, missing):
                with self.subTest(payload_fields=sorted(invalid["payload"])):
                    path.write_bytes(canonical_json(invalid))
                    with self.assertRaises(ValidationError):
                        FilesystemAttemptWorkspaceStore(root).load(
                            workspace.attempt_id
                        )

    def test_provider_evidence_only_is_not_artifact_complete_or_recoverable(self) -> None:
        with self._storage_root() as root:
            evidence = FilesystemArtifactStore(
                root, _IdentifierSource([ArtifactId(uuid(326))])
            ).publish(
                SafeRelativeArtifactPath("evidence/provider-terminal.json"),
                b'{"type":"done"}',
                "application/json",
                NOW,
            )
            event = ProviderEventEvidence(
                ProviderEventId(uuid(327)),
                0,
                ProviderEventKind.TERMINAL,
                evidence.reference,
                evidence.reference.content_digest,
                NOW,
                "request",
                "response",
                None,
                None,
                "7",
                ProviderTerminalClass.SUCCESS,
            )
            workspace = AttemptWorkspaceEvidence(
                AttemptWorkspaceId(uuid(328)),
                AttemptKind.GENERATION,
                NarrationJobId(uuid(329)),
                GenerationAttemptId(uuid(330)),
                1,
                BudgetReservationId(uuid(331)),
                digest("preview"),
                digest("input"),
                digest("input"),
                SubmissionEvidence.COMPLETED,
                (event,),
                (evidence.reference,),
                (evidence,),
                (),
                AttemptState.UNKNOWN,
            )
            target = GenerationRecoveryTarget(
                workspace.aggregate_id,
                workspace.attempt_id,
                workspace.budget_reservation_id,
            )

            artifact = FilesystemArtifactEvidenceVerifier(root).verify(workspace)
            provider = FilesystemProviderEventVerifier().verify(workspace)
            verified_workspace = FilesystemAttemptWorkspaceVerifier().verify(
                workspace,
                target,
                AttemptState.UNKNOWN,
                1,
                digest("input"),
            )
            decision = decide_target_recovery(
                target,
                RecoveryFacts(
                    AttemptState.UNKNOWN,
                    verified_workspace.last_confirmed_stage,
                    verified_workspace.workspace_matches_attempt,
                    verified_workspace.frozen_plan_matches,
                    verified_workspace.submission,
                    provider.provider_terminal,
                    provider.events_sealed,
                    artifact.artifact_verified,
                    artifact.publication_verified,
                    True,
                    True,
                    BudgetRecoveryState.SETTLED,
                    artifact.artifact_observed,
                    artifact.publication_observed,
                ),
            )

            self.assertTrue(artifact.publication_verified)
            self.assertFalse(artifact.artifact_verified)
            self.assertEqual(
                verified_workspace.last_confirmed_stage,
                RecoveryStage.ARTIFACTS_STAGED,
            )
            self.assertIsNot(decision.disposition, RecoveryDisposition.COMPLETED)

    def test_multi_publication_workspace_recovers_exactly_one_requested_canonical_audio(self) -> None:
        with self._storage_root() as root:
            store = FilesystemArtifactStore(
                root,
                _IdentifierSource([
                    ArtifactId(uuid(323)), ArtifactId(uuid(324)), ArtifactId(uuid(325)),
                ]),
            )
            evidence = store.publish(
                SafeRelativeArtifactPath("evidence/event.json"), b"{}", "application/json", NOW
            )
            audio = store.publish(
                SafeRelativeArtifactPath("takes/canonical.wav"),
                encode_canonical_pcm16_wav(b"\x01\x00\x02\x00", CanonicalAudioFacts()),
                "audio/wav", NOW,
            )
            other_audio = store.publish(
                SafeRelativeArtifactPath("takes/other.wav"),
                encode_canonical_pcm16_wav(b"\x03\x00\x04\x00", CanonicalAudioFacts()),
                "audio/wav", NOW,
            )
            workspace = self._published_workspace(
                audio,
                publications=(evidence, audio),
            )
            verifier = FilesystemArtifactEvidenceVerifier(root, CanonicalWavInspector())

            facts = verifier.verify(workspace)
            media = verifier.recover_media(workspace, audio)

            self.assertTrue(facts.artifact_verified and facts.publication_verified)
            self.assertEqual(media.sample_count, 2)
            self.assertTrue(workspace.matches_completion_binding(
                attempt_kind=workspace.attempt_kind,
                aggregate_id=workspace.aggregate_id,
                attempt_id=workspace.attempt_id,
                reservation_revision=workspace.reservation_revision,
                artifact=audio,
                budget_reservation_id=workspace.budget_reservation_id,
                preview_digest=workspace.preview_digest,
                effective_input_digest=workspace.effective_input_digest,
                frozen_plan_digest=workspace.frozen_plan_digest,
            ))

            missing = self._published_workspace(audio, publications=(evidence,))
            duplicate = self._published_workspace(audio, publications=(evidence, audio, audio))
            competing = self._published_workspace(
                audio, publications=(evidence, audio, other_audio)
            )
            with self.assertRaises(ValidationError):
                verifier.recover_media(missing, audio)
            with self.assertRaises(ValidationError):
                verifier.recover_media(duplicate, audio)
            with self.assertRaises(ValidationError):
                verifier.recover_media(competing, audio)
            self.assertFalse(competing.matches_completion_binding(
                attempt_kind=competing.attempt_kind,
                aggregate_id=competing.aggregate_id,
                attempt_id=competing.attempt_id,
                reservation_revision=competing.reservation_revision,
                artifact=audio,
                budget_reservation_id=competing.budget_reservation_id,
                preview_digest=competing.preview_digest,
                effective_input_digest=competing.effective_input_digest,
                frozen_plan_digest=competing.frozen_plan_digest,
            ))

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

    def test_read_verified_bytes_returns_only_the_exact_immutable_payload(self) -> None:
        """Audio assembly must not accept a safe path without its byte evidence."""
        payload = b"verified local PCM container"
        with self._storage_root() as root:
            publication = FilesystemArtifactStore(root, _IdentifierSource([ArtifactId(uuid(321))])).publish(
                SafeRelativeArtifactPath("takes/verified.wav"), payload, "audio/wav", NOW
            )
            verifier = FilesystemArtifactEvidenceVerifier(root)

            self.assertEqual(verifier.read_verified_bytes(publication), payload)

            (root.artifacts / "takes" / "verified.wav").write_bytes(b"tampered")
            with self.assertRaises(ValidationError):
                verifier.read_verified_bytes(publication)

    def test_read_verified_bytes_refuses_reparse_paths_and_non_publication_values(self) -> None:
        """A direct byte reader must preserve the same local-path boundary as publication."""
        payload = b"immutable verifier path boundary"
        with self._storage_root() as root:
            publication = FilesystemArtifactStore(root, _IdentifierSource([ArtifactId(uuid(322))])).publish(
                SafeRelativeArtifactPath("takes/reparse.wav"), payload, "audio/wav", NOW
            )
            verifier = FilesystemArtifactEvidenceVerifier(root)
            with self.assertRaises(ValidationError):
                verifier.read_verified_bytes(object())  # type: ignore[arg-type]
            with patch(
                "heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence._is_reparse_point",
                side_effect=lambda path: path == root.artifacts / "takes" / "reparse.wav",
            ):
                with self.assertRaisesRegex(ValidationError, "reparse"):
                    verifier.read_verified_bytes(publication)

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
        publications: tuple[PublishedArtifact, ...] | None = None,
    ) -> AttemptWorkspaceEvidence:
        exact_publications = (publication,) if publications is None else publications
        return AttemptWorkspaceEvidence(
            AttemptWorkspaceId(uuid(310)),
            AttemptKind.GENERATION,
            NarrationJobId(uuid(311)),
            GenerationAttemptId(uuid(312)),
            1,
            BudgetReservationId(uuid(313)),
            digest("preview"),
            digest("input"),
            digest("input"),
            SubmissionEvidence.COMPLETED,
            (),
            tuple(item.reference for item in exact_publications) if staged_artifacts is None else staged_artifacts,
            exact_publications,
            (),
            AttemptState.ARTIFACTS_PUBLISHED,
        )

    @staticmethod
    def _legacy_workspace_record(workspace: AttemptWorkspaceEvidence) -> bytes:
        envelope = parse_strict_json(encode_schema_v1(workspace))
        payload = dict(envelope["payload"])
        del payload["raw_timing_reference"]
        envelope["payload"] = payload
        return canonical_json(envelope)

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
