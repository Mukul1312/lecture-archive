"""Composition root for offline operations and lazy local-studio serving."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import TypeVar
from uuid import uuid4

from heritage_archive.kernel import ActorId, ValidationError
from heritage_archive.contexts.narrator_voice.application.commands import (
    ReconcileEpisodeAssemblyAttemptCommand,
    ReconcileGenerationAttemptCommand,
    ReconcileNarrationAssemblyAttemptCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    ReconcileEpisodeAssemblyAttemptHandler,
    ReconcileGenerationAttemptHandler,
    ReconcileNarrationAssemblyAttemptHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import AuthorityObservation
from heritage_archive.contexts.narrator_voice.domain.ids import (
    CommandId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    GenerationAttemptId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
)
from heritage_archive.contexts.narrator_voice.infrastructure.cli import (
    CliConfigurationError,
    main as run_cli,
)
from heritage_archive.contexts.narrator_voice.infrastructure.budget_ledger import (
    FilesystemGenerationBudgetLedger,
)
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemArtifactEvidenceVerifier,
    FilesystemAttemptWorkspaceStore,
    FilesystemAttemptWorkspaceVerifier,
    FilesystemProviderEventVerifier,
)
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import (
    FilesystemAuthorizationRecordRepository,
    FilesystemDiaryEpisodeRepository,
    FilesystemNarrationJobRepository,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import CanonicalWavInspector


_T = TypeVar("_T")
_ROOT_VARIABLE = "CARTESIA_NARRATION_ROOT"


class _UtcClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _UuidIdentifiers:
    def new_id(self, kind: type[_T]) -> _T:
        return kind(str(uuid4()))


@dataclass(frozen=True, slots=True)
class _FilesystemAuthorizationStatusReader:
    repository: FilesystemAuthorizationRecordRepository

    def read(self, record_id, observed_at: datetime) -> AuthorityObservation:
        record = self.repository.load(record_id)
        if record is None:
            return AuthorityObservation(record_id, None, None)
        return AuthorityObservation(record_id, record.status_at(observed_at), record.observe(observed_at))


@dataclass(frozen=True, slots=True)
class _RecoveryWiring:
    generation: ReconcileGenerationAttemptHandler
    narration_assembly: ReconcileNarrationAssemblyAttemptHandler
    episode_assembly: ReconcileEpisodeAssemblyAttemptHandler


class _LocalOperationsFacade:
    def __init__(self, root: LocalNarrationRoot | None, forbidden_roots: tuple[Path, ...]) -> None:
        self._root = root
        self._forbidden_roots = forbidden_roots

    def serve(self) -> None:
        from heritage_archive.composition_root.narrator_voice_web import serve_narration

        serve_narration(self._require_root())

    def initialize(self, config_file: Path):
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import (
            initialize_local_studio,
            load_local_studio_initialization,
        )

        root = self._require_root()
        try:
            request = load_local_studio_initialization(
                config_file,
                (*self._forbidden_roots, root.path),
            )
        except (OSError, ValidationError) as error:
            raise CliConfigurationError("the initialization configuration is invalid") from error
        return initialize_local_studio(root, request, _UuidIdentifiers())

    def doctor(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import doctor

        return doctor(self._require_root())

    def backup(self, destination: Path):
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import backup

        return backup(self._require_root(), destination, self._forbidden_roots)

    def verify_backup(self, source: Path):
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import verify_backup

        return verify_backup(source, self._forbidden_roots)

    def restore(self, source: Path):
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import restore

        return restore(source, self._require_root().path, self._forbidden_roots)

    def reconcile_generation(
        self,
        job_id: NarrationJobId,
        attempt_id: GenerationAttemptId,
        expected_revision: int,
    ):
        command = ReconcileGenerationAttemptCommand(
            _UuidIdentifiers().new_id(CommandId), job_id, attempt_id, expected_revision
        )
        return self._wire_recovery().generation(command)

    def reconcile_narration_assembly(
        self,
        job_id: NarrationJobId,
        attempt_id: NarrationAssemblyAttemptId,
        expected_revision: int,
    ):
        command = ReconcileNarrationAssemblyAttemptCommand(
            _UuidIdentifiers().new_id(CommandId), job_id, attempt_id, expected_revision
        )
        return self._wire_recovery().narration_assembly(command)

    def reconcile_episode_assembly(
        self,
        episode_id: DiaryEpisodeId,
        attempt_id: EpisodeAssemblyAttemptId,
        expected_revision: int,
    ):
        command = ReconcileEpisodeAssemblyAttemptCommand(
            _UuidIdentifiers().new_id(CommandId), episode_id, attempt_id, expected_revision
        )
        return self._wire_recovery().episode_assembly(command)

    def _wire_recovery(self) -> _RecoveryWiring:
        from heritage_archive.contexts.narrator_voice.infrastructure.operations import (
            load_local_studio_configuration,
        )

        root = self._require_root()
        configuration = load_local_studio_configuration(root)
        authorizations = FilesystemAuthorizationRecordRepository(root)
        jobs = FilesystemNarrationJobRepository(root)
        episodes = FilesystemDiaryEpisodeRepository(root)
        authority = _FilesystemAuthorizationStatusReader(authorizations)
        clock = _UtcClock()
        identifiers = _UuidIdentifiers()
        workspaces = FilesystemAttemptWorkspaceStore(root)
        workspace_verifier = FilesystemAttemptWorkspaceVerifier()
        provider_events = FilesystemProviderEventVerifier()
        artifact_evidence = FilesystemArtifactEvidenceVerifier(root, CanonicalWavInspector())
        budget_config = configuration.budget
        budget = FilesystemGenerationBudgetLedger(
            root,
            project_id=budget_config.project_id,
            billing_cycle_id=budget_config.billing_cycle_id,
            usage_unit=budget_config.usage_unit,
            per_take_cap=budget_config.per_take_cap,
            per_run_cap=budget_config.per_run_cap,
            project_cap=budget_config.project_cap,
            billing_cycle_cap=budget_config.billing_cycle_cap,
        )
        return _RecoveryWiring(
            ReconcileGenerationAttemptHandler(
                jobs,
                authority,
                clock,
                workspaces,
                workspace_verifier,
                provider_events,
                artifact_evidence,
                budget,
                budget,
                identifiers,
            ),
            ReconcileNarrationAssemblyAttemptHandler(
                jobs,
                authority,
                clock,
                workspaces,
                workspace_verifier,
                provider_events,
                artifact_evidence,
                identifiers,
            ),
            ReconcileEpisodeAssemblyAttemptHandler(
                episodes,
                jobs,
                authority,
                clock,
                workspaces,
                workspace_verifier,
                provider_events,
                artifact_evidence,
                identifiers,
            ),
        )

    def _require_root(self) -> LocalNarrationRoot:
        if self._root is None:
            raise CliConfigurationError("this command requires the explicit live root")
        return self._root


def _source_checkout_roots() -> tuple[Path, ...]:
    checkout = Path(__file__).resolve().parents[3]
    candidates = [checkout]
    for ancestor in checkout.parents:
        if (ancestor / ".git").exists():
            candidates.append(ancestor)
    return tuple(dict.fromkeys(path.resolve(strict=False) for path in candidates))


def _build_facade(require_live_root: bool) -> _LocalOperationsFacade:
    forbidden_roots = _source_checkout_roots()
    if not require_live_root:
        return _LocalOperationsFacade(None, forbidden_roots)
    raw = os.environ.get(_ROOT_VARIABLE)
    if raw is None or not raw or raw != raw.strip():
        raise CliConfigurationError("the live root environment variable is missing or invalid")
    try:
        root = LocalNarrationRoot.open(Path(raw), forbidden_roots)
    except (OSError, ValueError) as error:
        raise CliConfigurationError("the live root environment variable is invalid") from error
    return _LocalOperationsFacade(root, forbidden_roots)


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv, facade_factory=_build_facade)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
