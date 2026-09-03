"""Focused contracts for durable attempt evidence and local recovery verification."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ArtifactId, ArtifactRef, ContentDigest, ValidationError
from heritage_archive.contexts.narrator_voice.application.recovery import (
    GenerationRecoveryTarget,
    RecoveryStage,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    ReconcileGenerationAttemptCommand,
    ReconcileGenerationAttemptHandler,
)
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    DecodedMediaFacts,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
    PublishedArtifact,
    SubmissionEvidence,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    BudgetReservationId,
    GenerationAttemptId,
    CommandId,
    NarrationAssemblyAttemptId,
    TakeId,
    NarrationJobId,
    ProviderEventId,
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
from tests.heritage_archive.narrator_voice.fixtures import NOW, digest, uuid
from tests.heritage_archive.narrator_voice.fakes import FakeIdentifierSource
from tests.heritage_archive.narrator_voice import test_application_generation as generation_tests


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class DurableAttemptEvidenceTests(unittest.TestCase):
    def test_workspace_reloads_exactly_and_repeated_save_does_not_rewrite(self) -> None:
        """A restart must recover byte-identical evidence without an unnecessary rewrite."""
        with self._root() as root:
            workspace = self._reserved_workspace()
            store = FilesystemAttemptWorkspaceStore(root)
            store.save(workspace)
            path = root.attempts / "generation" / f"{workspace.attempt_id.value}.json"
            before = path.stat().st_mtime_ns

            store.save(workspace)

            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertEqual(FilesystemAttemptWorkspaceStore(root).load(workspace.attempt_id), workspace)

    def test_workspace_allows_only_monotonic_frozen_started_and_published_evidence(self) -> None:
        """Persisted recovery evidence may strengthen but cannot be rewritten or regressed."""
        with self._root() as root:
            store = FilesystemAttemptWorkspaceStore(root)
            reserved = self._reserved_workspace()
            frozen = replace(
                reserved,
                effective_input_digest=digest("input"),
                frozen_plan_digest=digest("input"),
                state=AttemptState.INPUT_FROZEN,
            )
            started = replace(frozen, submission=SubmissionEvidence.STARTED, state=AttemptState.EXTERNAL_WORK_STARTED)
            publication = self._publication(root)
            published = replace(
                started,
                submission=SubmissionEvidence.COMPLETED,
                events=(self._terminal_event(),),
                staged_artifacts=(publication.reference,),
                published_artifacts=(publication,),
                state=AttemptState.ARTIFACTS_PUBLISHED,
            )

            for evidence in (reserved, frozen, started, published):
                store.save(evidence)

            self.assertEqual(FilesystemAttemptWorkspaceStore(root).load(reserved.attempt_id), published)
            with self.assertRaises(ValidationError):
                store.save(replace(published, state=AttemptState.EXTERNAL_WORK_STARTED))
            with self.assertRaises(ValidationError):
                store.save(replace(published, frozen_plan_digest=digest("different")))
            with self.assertRaises(ValidationError):
                store.save(replace(published, preview_digest=digest("other-preview")))
            with self.assertRaises(ValidationError):
                store.save(replace(published, events=published.events + (
                    replace(self._terminal_event(), sequence=1, kind=ProviderEventKind.AUDIO, terminal_classification=None),
                )))

    def test_workspace_and_provider_verifiers_accept_only_sealed_matching_generation_evidence(self) -> None:
        """Local structural proof never pretends a provider authenticated the request."""
        with self._root() as root:
            workspace = self._reserved_workspace()
            workspace = replace(
                workspace,
                effective_input_digest=digest("input"),
                frozen_plan_digest=digest("input"),
                submission=SubmissionEvidence.COMPLETED,
                events=(self._terminal_event(),),
                state=AttemptState.ARTIFACTS_PUBLISHED,
            )
            FilesystemAttemptWorkspaceStore(root).save(workspace)
            target = GenerationRecoveryTarget(
                workspace.aggregate_id, workspace.attempt_id, workspace.budget_reservation_id
            )

            facts = FilesystemAttemptWorkspaceVerifier().verify(
                FilesystemAttemptWorkspaceStore(root).load(workspace.attempt_id),
                target,
                AttemptState.EXTERNAL_WORK_STARTED,
                workspace.reservation_revision,
                workspace.frozen_plan_digest,
            )
            provider = FilesystemProviderEventVerifier().verify(workspace)

            self.assertEqual((facts.workspace_matches_attempt, facts.frozen_plan_matches), (True, True))
            self.assertEqual(facts.last_confirmed_stage, RecoveryStage.EXTERNAL_WORK_STARTED)
            self.assertEqual((provider.provider_terminal, provider.events_sealed), (ProviderTerminalClass.SUCCESS, True))
            mismatch = FilesystemAttemptWorkspaceVerifier().verify(
                workspace, target, AttemptState.EXTERNAL_WORK_STARTED, workspace.reservation_revision, digest("wrong")
            )
            self.assertFalse(mismatch.frozen_plan_matches)

    def test_provider_verifier_requires_no_events_for_dry_assembly(self) -> None:
        """Dry local assembly records no provider claim, while generation needs a sealed terminal."""
        workspace = AttemptWorkspaceEvidence(
            AttemptWorkspaceId(uuid(758)), AttemptKind.NARRATION_ASSEMBLY, NarrationJobId(uuid(759)),
            NarrationAssemblyAttemptId(uuid(760)), 3, None, None, None, digest("assembly-plan"),
            SubmissionEvidence.NOT_STARTED, (), (), (), (), AttemptState.RESERVED,
        )
        verifier = FilesystemProviderEventVerifier()

        self.assertEqual(verifier.verify(workspace).events_sealed, True)
        invalid = replace(workspace, events=(self._terminal_event(),))
        self.assertEqual(verifier.verify(invalid).events_sealed, False)

    def test_workspace_load_fails_closed_for_corrupt_canonical_evidence(self) -> None:
        """Malformed restart evidence must not be treated as an absent attempt."""
        with self._root() as root:
            workspace = self._reserved_workspace()
            path = root.attempts / "generation" / f"{workspace.attempt_id.value}.json"
            path.parent.mkdir()
            path.write_text('{"not":"canonical"}', encoding="utf-8")

            with self.assertRaises(ValidationError):
                FilesystemAttemptWorkspaceStore(root).load(workspace.attempt_id)

    def test_artifact_media_recovery_requires_exact_non_silent_workspace_publication(self) -> None:
        """A valid pathname alone cannot become trusted completion media."""
        payload = b"verified dry PCM container"
        with self._root() as root:
            publication = FilesystemArtifactStore(root, _Ids([ArtifactId(uuid(761))])).publish(
                SafeRelativeArtifactPath("takes/recovered.wav"), payload, "audio/wav", NOW
            )
            workspace = replace(
                self._reserved_workspace(),
                effective_input_digest=digest("input"),
                frozen_plan_digest=digest("input"),
                submission=SubmissionEvidence.COMPLETED,
                events=(self._terminal_event(),),
                staged_artifacts=(publication.reference,),
                published_artifacts=(publication,),
                state=AttemptState.ARTIFACTS_PUBLISHED,
            )
            inspector = _Inspector(_media(False))
            verifier = FilesystemArtifactEvidenceVerifier(root, inspector)

            self.assertEqual(verifier.recover_media(workspace, publication), inspector.media)
            with self.assertRaises(ValidationError):
                verifier.recover_media(workspace, replace(publication, relative_location=SafeRelativeArtifactPath("takes/other.wav")))
            inspector.media = _media(True)
            with self.assertRaises(ValidationError):
                verifier.recover_media(workspace, publication)

    def test_generation_reconciliation_uses_reloaded_durable_evidence_without_replay(self) -> None:
        """Recovery completes an existing unknown generation from disk and is exactly repeatable."""
        fixture = generation_tests.GenerationApplicationTests(
            "test_post_provider_CAS_conflict_preserves_published_evidence_and_settled_usage_without_second_CAS"
        )
        fixture.setUp()
        fixture.jobs.reject_on_save_calls.add(8)
        unknown = fixture.handler()(fixture.command())
        workspace = fixture.workspaces.load(fixture.attempt_id)
        publication = workspace.published_artifacts[0]
        with self._root() as root:
            artifact_path = root.artifacts / publication.relative_location.value
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_bytes(fixture.synthesis_result.canonical_wav_bytes)
            workspaces = FilesystemAttemptWorkspaceStore(root)
            workspaces.save(workspace)
            recovery_ids = FakeIdentifierSource({TakeId: [TakeId(uuid(762))]})
            handler = ReconcileGenerationAttemptHandler(
                fixture.jobs,
                fixture.reader,
                fixture.clock,
                workspaces,
                FilesystemAttemptWorkspaceVerifier(),
                FilesystemProviderEventVerifier(),
                FilesystemArtifactEvidenceVerifier(root, _Inspector(_media(False))),
                fixture.budget,
                fixture.budget,
                recovery_ids,
            )

            completed = handler(
                ReconcileGenerationAttemptCommand(CommandId(uuid(763)), fixture.job_id, fixture.attempt_id, unknown.revision)
            )
            replay = handler(
                ReconcileGenerationAttemptCommand(CommandId(uuid(764)), fixture.job_id, fixture.attempt_id, completed.revision)
            )

            job = fixture.jobs.load(fixture.job_id)
            self.assertEqual((job.generation_attempts[-1].state, len(job.takes)), (AttemptState.COMPLETED, 1))
            self.assertEqual(replay.revision, completed.revision)
            self.assertEqual((len(fixture.gateway.calls), len(fixture.store.calls)), (1, 1))

    def _reserved_workspace(self) -> AttemptWorkspaceEvidence:
        return AttemptWorkspaceEvidence(
            AttemptWorkspaceId(uuid(751)), AttemptKind.GENERATION, NarrationJobId(uuid(752)),
            GenerationAttemptId(uuid(753)), 4, BudgetReservationId(uuid(754)), digest("preview"),
            None, None, SubmissionEvidence.NOT_STARTED, (), (), (), (), AttemptState.RESERVED,
        )

    def _publication(self, root: LocalNarrationRoot) -> PublishedArtifact:
        return FilesystemArtifactStore(root, _Ids([ArtifactId(uuid(755))])).publish(
            SafeRelativeArtifactPath("takes/published.wav"), b"published bytes", "audio/wav", NOW
        )

    @staticmethod
    def _terminal_event() -> ProviderEventEvidence:
        raw = ArtifactRef(ArtifactId(uuid(756)), digest("sealed-event"), 4, "application/json")
        return ProviderEventEvidence(
            ProviderEventId(uuid(757)), 0, ProviderEventKind.TERMINAL, raw, raw.content_digest, NOW,
            "request", "response", None, None, "1", ProviderTerminalClass.SUCCESS,
        )

    def _root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = LocalNarrationRoot.open(Path(temporary.name), (PROJECT_ROOT,))
        root.initialize_layout()
        return _RootContext(root)


def _media(silent: bool):
    from heritage_archive.contexts.narrator_voice.domain.values import CanonicalAudioFacts

    return DecodedMediaFacts(CanonicalAudioFacts(), 2, 1, silent)


class _Ids:
    def __init__(self, values) -> None:
        self.values = list(values)

    def new_id(self, kind):
        return self.values.pop(0)


class _Inspector:
    def __init__(self, media) -> None:
        self.media = media
        self.payloads = []

    def inspect_canonical_wav(self, payload):
        self.payloads.append(payload)
        return self.media


class _RootContext:
    def __init__(self, root) -> None:
        self.root = root

    def __enter__(self):
        return self.root

    def __exit__(self, exc_type, exc_value, traceback):
        return None


if __name__ == "__main__":
    unittest.main()
