"""Reusable complete no-network source workflow fixture (not production infrastructure)."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import replace
from importlib.resources import files
import json
import os
from unittest.mock import patch

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
    PublishedArtifact,
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
            SynthesisResult(
                (event,),
                f"RIFF-fake-source-{base}".encode(),
                (
                    PublishedArtifact(
                        raw,
                        SafeRelativeArtifactPath(f"evidence/source-{base}-event.json"),
                        NOW,
                    ),
                    PublishedArtifact(
                        timing,
                        SafeRelativeArtifactPath(f"evidence/source-{base}-timing.json"),
                        NOW,
                    ),
                ),
                timing,
                NonNegativeDecimal("42"),
            )
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


@contextmanager
def forbid_web_external_io():
    """Fail positively on credential reads or any network seam, including cleanup."""
    original_getitem = type(os.environ).__getitem__
    credential_reads = []

    def guarded_getitem(environment, key):
        if key.upper() == "CARTESIA_API_KEY":
            credential_reads.append(key)
            raise AssertionError("credential lookup forbidden in durable web fixture")
        return original_getitem(environment, key)

    with ExitStack() as stack:
        stack.enter_context(patch.object(type(os.environ), "__getitem__", guarded_getitem))
        guards = [stack.enter_context(patch(target, side_effect=AssertionError(target + " forbidden")))
                  for target in (
                      "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
                      "socket.socket", "socket.socketpair", "socket.create_connection",
                      "httpx.Client.send", "httpx.AsyncClient.send",
                      "http.client.HTTPConnection.request", "urllib.request.urlopen",
                      "heritage_archive.platform.cartesia.transport.CartesiaSseTransport.stream",
                      "heritage_archive.composition_root.narrator_voice_live.EnvironmentCartesiaCredentialSupplier.read_for_transmission",
                      "heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway.CartesiaSynthesisGateway.synthesize",
                  )]
        yield
        # Application error redaction can catch an AssertionError; call counts also
        # make such swallowed attempts fail this fixture's outer boundary.
        for guard in guards:
            guard.assert_not_called()
        if credential_reads:
            raise AssertionError("credential lookup was swallowed by an application boundary")


class DurableFixtureGateway:
    """Only the provider port is fake; referenced evidence is really published."""

    def __init__(self, artifacts, identifiers, clock):
        self.artifacts, self.identifiers, self.clock = artifacts, identifiers, clock
        self.calls = []
        self.pcm_by_passage = {}

    def synthesize(self, invocation):
        from heritage_archive.contexts.narrator_voice.domain.values import CanonicalAudioFacts
        from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import encode_canonical_pcm16_wav
        self.calls.append(invocation)
        # Distinct, non-silent, deterministic PCM makes concatenation/order visible.
        ordinal = len(self.calls)
        pcm = ordinal.to_bytes(2, "little", signed=True) + (-ordinal).to_bytes(2, "little", signed=True)
        self.pcm_by_passage[invocation.effective_input.passage_id.value] = pcm
        observed = self.clock.now()
        publication = self.artifacts.publish(
            SafeRelativeArtifactPath(f"evidence/fixture/{invocation.attempt_id.value}/sanitized.json"),
            b'{"fixture":true,"terminal":"success","usage":"1"}',
            "application/json", observed,
        )
        event = ProviderEventEvidence(
            self.identifiers.new_id(ProviderEventId), 0, ProviderEventKind.TERMINAL,
            publication.reference, publication.reference.content_digest, observed,
            None, None, None, None, "1", ProviderTerminalClass.SUCCESS,
        )
        return SynthesisResult((event,), encode_canonical_pcm16_wav(pcm, CanonicalAudioFacts()),
                               (publication,), None, NonNegativeDecimal("1"))


class DurableWebWorkflow:
    """Build the persisted studio and expose requests without a browser or socket."""

    def __init__(self, root, *, security, principal):
        from heritage_archive.composition_root.narrator_voice_live import build_live_narration
        from heritage_archive.composition_root.narrator_voice_web import build_authoring_bindings
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.app import NarratorWebApplication
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.generation import ProcessGenerationControl
        from heritage_archive.contexts.narrator_voice.infrastructure.loopback_web.routes import NarrationAuthoringRoutes
        from tests.heritage_archive.narrator_voice.test_cartesia_gateway import Identifiers
        self.ids, self.security = Identifiers(), security
        self.studio = build_live_narration(root, process_principal=principal, identifiers=self.ids)
        original = self.studio.handlers.generate
        self.gateway = DurableFixtureGateway(original.artifacts, self.ids, original.clock)
        self.handlers = replace(self.studio.handlers, generate=replace(original, gateway=self.gateway))
        self.control = ProcessGenerationControl(security.session_token)
        routes = NarrationAuthoringRoutes(
            self.handlers, build_authoring_bindings(self.studio.policies, principal), self.ids, self.control,
        )
        package = files("heritage_archive.contexts.narrator_voice.infrastructure.loopback_web")
        self.assets = {f"/assets/studio.{suffix}": package.joinpath("assets", f"studio.{suffix}").read_bytes()
                       for suffix in ("css", "js")}
        self.app = NarratorWebApplication(security, dispatch=routes, render_root=routes.render_root, assets=self.assets)

    def close(self):
        self.studio.close()

    def headers(self, mutation=False):
        values = ((b"host", b"127.0.0.1:8765"),
                  (b"cookie", ("narrator_session=" + self.security.session_token).encode()))
        if mutation:
            values += ((b"origin", b"http://127.0.0.1:8765"), (b"sec-fetch-site", b"same-origin"),
                       (b"content-type", b"application/json"),
                       (b"x-narrator-csrf", self.security.csrf_token.encode()))
        return values

    def request(self, method, path, body=None):
        from heritage_archive.platform.web import WebRequest
        return self.app(WebRequest(method, path, self.headers(method == "POST"),
                                   b"" if body is None else json.dumps(body).encode("utf-8")))

    def editor(self, job_id):
        from heritage_archive.contexts.narrator_voice.application.commands import ShowNarrationEditorCommand
        return self.handlers.show_editor(ShowNarrationEditorCommand(self.ids.new_id(CommandId), NarrationJobId(job_id)))

    def raw_asgi_get(self, path):
        """Drive real ASGI translation inline; asyncio's wakeup socket is forbidden."""
        from heritage_archive.platform.web.loopback import build_asgi
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        async def inline(call, *args):
            return call(*args)

        scope = {"type": "http", "http_version": "1.1", "method": "GET", "path": path,
                 "raw_path": path.encode(), "query_string": b"", "headers": list(self.headers()),
                 "scheme": "http", "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1)}
        with patch("heritage_archive.platform.web.loopback.run_in_threadpool", inline):
            coroutine = build_asgi(self.app)(scope, receive, send)
            try:
                coroutine.send(None)
            except StopIteration:
                pass
            else:
                raise AssertionError("raw ASGI driver unexpectedly suspended")
            finally:
                coroutine.close()
        return messages[0], b"".join(message.get("body", b"") for message in messages[1:])
