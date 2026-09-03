"""Reusable complete no-network source workflow fixture (not production infrastructure)."""

from __future__ import annotations

from heritage_archive.kernel import ActorId, ArtifactId, ArtifactRef
from heritage_archive.contexts.narrator_voice.application.commands import (
    AssembleNarrationMasterCommand,
    EstimateGenerationCommand,
    GenerateTakeCommand,
    IssueNarrationMasterSnapshotCommand,
    PrepareDiaryNarrationCommand,
    PrepareIntroNarrationCommand,
    RecordNarrationMasterListeningCommand,
    RecordReviewDecisionCommand,
    RequireRenderRecipeCommand,
    SelectWorkingTakeCommand,
    ValidateRenderRecipeCommand,
)
from heritage_archive.contexts.narrator_voice.application.handlers import (
    AssembleNarrationMasterHandler,
    EstimateGenerationHandler,
    GenerateTakeHandler,
    IssueNarrationMasterSnapshotHandler,
    PrepareDiaryNarrationHandler,
    PrepareIntroNarrationHandler,
    RecordNarrationMasterListeningHandler,
    RecordReviewDecisionHandler,
    RequireRenderRecipeHandler,
    SelectWorkingTakeHandler,
    ValidateRenderRecipeHandler,
)
from heritage_archive.contexts.narrator_voice.application.ports import ReleasePolicyResolution, SynthesisResult
from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    ListeningOutcome,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
    ReviewOutcome,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    BudgetReservationId,
    CommandId,
    GenerationAttemptId,
    GenerationPreviewId,
    MasterListeningDecisionId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    NarrationMasterSnapshotId,
    PassageId,
    PassageRenderRecipeId,
    ProviderEventId,
    ReviewDecisionId,
    SelectionDecisionId,
    TakeId,
)
from heritage_archive.contexts.narrator_voice.domain.narration_job import PassageDraft
from heritage_archive.contexts.narrator_voice.domain.values import (
    Lane,
    NonNegativeDecimal,
    PassageText,
    SafeRelativeArtifactPath,
)
from tests.heritage_archive.narrator_voice.fakes import (
    FakeActorResolver,
    FakeArtifactStore,
    FakeArtifactEvidenceVerifier,
    FakeAttemptWorkspaceVerifier,
    FakeAuthorizationRepository,
    FakeAuthorizationStatusReader,
    FakeBudgetLedger,
    FakeClock,
    FakeDiaryEpisodeRepository,
    FakeDryPcmAssembler,
    FakeIdentifierSource,
    FakeMediaInspector,
    FakeNarrationJobRepository,
    FakeRecipeCompiler,
    FakeReleasePolicyResolver,
    FakeSynthesisGateway,
    FakeProviderEventVerifier,
    FakeWorkspaceStore,
)
from tests.heritage_archive.narrator_voice.fixtures import (
    NOW,
    digest,
    make_contract,
    make_defaults,
    make_scope,
    make_recipe_authoring,
    make_settings_intent,
    uuid,
)


class NoNetworkWorkflow:
    def __init__(self) -> None:
        self.jobs = FakeNarrationJobRepository()
        self.episodes = FakeDiaryEpisodeRepository()
        self.authorizations = FakeAuthorizationRepository()
        self.authority = FakeAuthorizationStatusReader(self.authorizations)
        self.clock = FakeClock(NOW)
        self.ids = FakeIdentifierSource({})
        self.compiler = FakeRecipeCompiler(["structured-fake", "advanced-fake"])
        self.policies = FakeReleasePolicyResolver()
        self.budget = FakeBudgetLedger()
        self.artifacts = FakeArtifactStore([ArtifactId(uuid(index)) for index in range(1200, 1230)])
        self.media = FakeMediaInspector(100)
        self.workspaces = FakeWorkspaceStore()
        self.workspace_verifier = FakeAttemptWorkspaceVerifier()
        self.provider_event_verifier = FakeProviderEventVerifier()
        self.artifact_verifier = FakeArtifactEvidenceVerifier()
        self.assembler = FakeDryPcmAssembler()
        self.actor = ActorId(uuid(1231))
        self.actors = FakeActorResolver({"fake-operator": self.actor})
        self.gateways = []

    def add(self, kind, *values) -> None:
        self.ids.values.setdefault(kind, []).extend(values)

    def produce_source(self, lane: Lane, *, episode_id=None, base: int):
        contract = make_contract(lane=lane, episode_id=episode_id)
        defaults = make_defaults(f"{base}")
        resolution = ReleasePolicyResolution(contract, defaults)
        if lane is Lane.C:
            self.policies.lane_c = resolution
        else:
            self.policies.lane_b = resolution
        scope = make_scope(lane=lane, episode_id=episode_id)
        record = AuthorizationRecord.register(
            contract.authority_record_id, self.actor, scope, digest(f"fake authority {base}"), NOW
        )
        if self.authorizations.load(contract.authority_record_id) is None:
            assert self.authorizations.save(record, None)
        job_id = NarrationJobId(uuid(base))
        passage_id = PassageId(uuid(base + 1))
        recipe_id = PassageRenderRecipeId(uuid(base + 2))
        preview_id = GenerationPreviewId(uuid(base + 3))
        attempt_id = GenerationAttemptId(uuid(base + 4))
        reservation_id = BudgetReservationId(uuid(base + 5))
        take_id = TakeId(uuid(base + 6))
        text = PassageText(
            "ଏହା ଏକ ନକଲି ପରିଚୟ ବାକ୍ୟ।" if lane is Lane.C
            else "ଏହା ଏକ ନକଲି ଦିନଲିପି ବାକ୍ୟ।"
        )
        self.add(NarrationJobId, job_id)
        prepare = (
            PrepareIntroNarrationHandler(
                self.jobs, self.episodes, self.policies, self.authority, self.clock, self.ids,
            )
            if lane is Lane.C
            else PrepareDiaryNarrationHandler(self.jobs, self.policies, self.authority, self.clock, self.ids)
        )
        prepare_command = (
            PrepareIntroNarrationCommand(
                CommandId(uuid(base + 7)), episode_id, self.episodes.load(episode_id).revision,
                (PassageDraft(passage_id, 0, text),),
            )
            if lane is Lane.C
            else PrepareDiaryNarrationCommand(CommandId(uuid(base + 7)), (PassageDraft(passage_id, 0, text),))
        )
        prepared = prepare(prepare_command)
        ValidateRenderRecipeHandler(self.jobs, self.compiler)(
            ValidateRenderRecipeCommand(
                CommandId(uuid(base + 8)), job_id, passage_id,
                make_recipe_authoring(recipe_index=base + 2), prepared.revision,
            )
        )
        required = RequireRenderRecipeHandler(self.jobs)(
            RequireRenderRecipeCommand(CommandId(uuid(base + 9)), job_id, passage_id, recipe_id, prepared.revision + 1)
        )
        self.add(GenerationPreviewId, preview_id)
        estimated = EstimateGenerationHandler(self.jobs, self.authority, self.compiler, self.clock, self.ids)(
            EstimateGenerationCommand(
                CommandId(uuid(base + 10)), job_id, passage_id, recipe_id,
                make_settings_intent(), required.revision,
            )
        )
        raw = ArtifactRef(ArtifactId(uuid(base + 11)), digest(f"fake event {base}"), 20, "application/json")
        timing = ArtifactRef(ArtifactId(uuid(base + 12)), digest(f"fake timing {base}"), 20, "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(uuid(base + 13)), 0, ProviderEventKind.TERMINAL,
            raw, raw.content_digest, NOW, f"fake-request-{base}", f"fake-response-{base}",
            None, timing, "42", ProviderTerminalClass.SUCCESS,
        )
        gateway = FakeSynthesisGateway(
            SynthesisResult((event,), f"RIFF-fake-source-{base}".encode(), (timing,), NonNegativeDecimal("42"))
        )
        self.gateways.append(gateway)
        self.add(GenerationAttemptId, attempt_id)
        self.add(BudgetReservationId, reservation_id)
        self.add(TakeId, take_id)
        self.add(AttemptWorkspaceId, AttemptWorkspaceId(uuid(base + 14)))
        generated = GenerateTakeHandler(
            self.jobs, self.authority, self.clock, self.ids, self.budget,
            gateway, self.artifacts, self.media, self.workspaces,
        )(
            GenerateTakeCommand(
                CommandId(uuid(base + 15)), job_id, preview_id, estimated.revision,
                SafeRelativeArtifactPath(f"fake/source-{base}.wav"),
            )
        )
        self.add(ReviewDecisionId, ReviewDecisionId(uuid(base + 16)))
        reviewed = RecordReviewDecisionHandler(self.jobs, self.actors, self.clock, self.ids)(
            RecordReviewDecisionCommand(
                CommandId(uuid(base + 17)), "fake-operator", job_id, generated.take_id,
                ReviewOutcome.ACCEPTED, "fake operational pass", generated.revision,
            )
        )
        self.add(SelectionDecisionId, SelectionDecisionId(uuid(base + 18)))
        selected = SelectWorkingTakeHandler(self.jobs, self.authority, self.actors, self.clock, self.ids)(
            SelectWorkingTakeCommand(
                CommandId(uuid(base + 19)), "fake-operator", job_id, passage_id,
                generated.take_id, "fake source selection", reviewed.revision,
            )
        )
        self.add(NarrationAssemblyAttemptId, NarrationAssemblyAttemptId(uuid(base + 20)))
        self.add(NarrationMasterId, NarrationMasterId(uuid(base + 21)))
        self.add(AttemptWorkspaceId, AttemptWorkspaceId(uuid(base + 22)))
        assembled = AssembleNarrationMasterHandler(
            self.jobs, self.authority, self.clock, self.ids, self.assembler,
            self.artifacts, self.workspaces,
        )(
            AssembleNarrationMasterCommand(
                CommandId(uuid(base + 23)), job_id, (), selected.revision,
                SafeRelativeArtifactPath(f"fake/master-{base}.wav"),
            )
        )
        self.add(MasterListeningDecisionId, MasterListeningDecisionId(uuid(base + 24)))
        listened = RecordNarrationMasterListeningHandler(self.jobs, self.actors, self.clock, self.ids)(
            RecordNarrationMasterListeningCommand(
                CommandId(uuid(base + 25)), "fake-operator", job_id, assembled.master_id,
                ListeningOutcome.PASSED, "fake whole source pass", assembled.revision,
            )
        )
        self.add(NarrationMasterSnapshotId, NarrationMasterSnapshotId(uuid(base + 26)))
        return IssueNarrationMasterSnapshotHandler(self.jobs, self.authority, self.clock, self.ids)(
            IssueNarrationMasterSnapshotCommand(
                CommandId(uuid(base + 27)), job_id, assembled.master_id, listened.revision,
            )
        ).snapshot
