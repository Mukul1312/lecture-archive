"""Explicit live construction for future authorized generation; no CLI entry point."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from uuid import uuid4

from heritage_archive.platform.cartesia.transport import CartesiaSseTransport
from heritage_archive.contexts.narrator_voice.application.handlers import (
    EstimateGenerationHandler, GenerateTakeHandler, PrepareDiaryNarrationHandler,
    PrepareIntroNarrationHandler, RequireRenderRecipeHandler, ValidateRenderRecipeHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import AuthorityObservation
from heritage_archive.contexts.narrator_voice.infrastructure.budget_ledger import FilesystemGenerationBudgetLedger
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaCredentialUnavailable, CartesiaSynthesisGateway
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_policy import ConfiguredNarrationReleasePolicyResolver
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_recipe import CartesiaRecipeCompiler
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import FilesystemArtifactStore, FilesystemAttemptWorkspaceStore
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import (
    FilesystemAuthorizationRecordRepository, FilesystemDiaryEpisodeRepository, FilesystemNarrationJobRepository,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.operations import load_local_studio_configuration
from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import CanonicalWavInspector


class EnvironmentCartesiaCredentialSupplier:
    def read_for_transmission(self) -> str:
        value = os.environ.get("CARTESIA_API_KEY")
        if value is None or not value or value != value.strip() or any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise CartesiaCredentialUnavailable("credential_unavailable")
        return value


class _UtcClock:
    def now(self):
        return datetime.now(timezone.utc)


class _Identifiers:
    def new_id(self, kind):
        return kind(str(uuid4()))


@dataclass(frozen=True, slots=True)
class FilesystemAuthorizationStatusReader:
    repository: FilesystemAuthorizationRecordRepository

    def read(self, record_id, observed_at):
        record = self.repository.load(record_id)
        if record is None:
            return AuthorityObservation(record_id, None, None)
        return AuthorityObservation(record_id, record.status_at(observed_at), record.observe(observed_at))


@dataclass(frozen=True, slots=True)
class LiveNarrationStudio:
    policies: ConfiguredNarrationReleasePolicyResolver
    gateway: CartesiaSynthesisGateway
    prepare_diary: PrepareDiaryNarrationHandler
    prepare_intro: PrepareIntroNarrationHandler
    validate_recipe: ValidateRenderRecipeHandler
    require_recipe: RequireRenderRecipeHandler
    estimate: EstimateGenerationHandler
    generate: GenerateTakeHandler
    transport: CartesiaSseTransport

    def close(self):
        self.transport.close()


def build_live_narration(root: LocalNarrationRoot) -> LiveNarrationStudio:
    """Construct durable generation adapters without reading a key or transmitting."""
    configuration = load_local_studio_configuration(root)
    policies = ConfiguredNarrationReleasePolicyResolver(configuration.lane_b, configuration.lane_c)
    jobs = FilesystemNarrationJobRepository(root)
    episodes = FilesystemDiaryEpisodeRepository(root)
    authority = FilesystemAuthorizationStatusReader(FilesystemAuthorizationRecordRepository(root))
    clock, identifiers = _UtcClock(), _Identifiers()
    artifacts = FilesystemArtifactStore(root, identifiers)
    workspaces = FilesystemAttemptWorkspaceStore(root)
    compiler = CartesiaRecipeCompiler()
    budget_configuration = configuration.budget
    budget = FilesystemGenerationBudgetLedger(
        root, project_id=budget_configuration.project_id, billing_cycle_id=budget_configuration.billing_cycle_id,
        usage_unit=budget_configuration.usage_unit, per_take_cap=budget_configuration.per_take_cap,
        per_run_cap=budget_configuration.per_run_cap, project_cap=budget_configuration.project_cap,
        billing_cycle_cap=budget_configuration.billing_cycle_cap,
    )
    transport = CartesiaSseTransport()
    gateway = CartesiaSynthesisGateway(
        transport=transport, credentials=EnvironmentCartesiaCredentialSupplier(),
        policies=policies, artifacts=artifacts, clock=clock, identifiers=identifiers,
    )
    return LiveNarrationStudio(
        policies, gateway,
        PrepareDiaryNarrationHandler(jobs, policies, authority, clock, identifiers),
        PrepareIntroNarrationHandler(jobs, episodes, policies, authority, clock, identifiers),
        ValidateRenderRecipeHandler(jobs, compiler), RequireRenderRecipeHandler(jobs),
        EstimateGenerationHandler(jobs, authority, compiler, clock, identifiers),
        GenerateTakeHandler(jobs, authority, clock, identifiers, budget, gateway, artifacts, CanonicalWavInspector(), workspaces),
        transport,
    )
