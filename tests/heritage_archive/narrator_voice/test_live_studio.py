"""Fixture-only construction of the complete shared local narration graph."""
from dataclasses import fields
import inspect
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from heritage_archive.composition_root import narrator_voice_live as live
from heritage_archive.contexts.narrator_voice.application import handlers as application_handlers
from heritage_archive.contexts.narrator_voice.application.commands import RegisterAuthorizationCommand
from heritage_archive.contexts.narrator_voice.domain.errors import AuthorizationDenied
from heritage_archive.contexts.narrator_voice.domain.ids import CommandId
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemArtifactEvidenceVerifier, FilesystemArtifactStore,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.operations import (
    DoctorResult, initialize_local_studio, load_local_studio_configuration,
)
from heritage_archive.kernel import ContentDigest
from tests.heritage_archive.narrator_voice.fixtures import make_scope, uuid
from tests.heritage_archive.narrator_voice.test_cartesia_gateway import Identifiers
from tests.heritage_archive.narrator_voice.test_cartesia_generation_integration import initialization


PRINCIPAL = "fixture-studio-process-principal"

# This route-derived inventory fixes the shared dependency identities, including
# the budget's two recovery roles and the reader's assembly/playback/recovery roles.
HANDLER_WIRING = (
    ("register_authorization", "RegisterAuthorizationHandler", "authorizations actors clock"),
    ("show_authorization_status", "ShowAuthorizationStatusHandler", "authorizations clock"),
    ("discover", "DiscoverStudioHandler", "jobs episodes"),
    ("show_editor", "ShowNarrationEditorHandler", "jobs"),
    ("show_narration_status", "ShowNarrationStatusHandler", "jobs authority clock"),
    ("show_episode_status", "ShowEpisodeStatusHandler", "episodes jobs authority clock"),
    ("prepare_diary", "PrepareDiaryNarrationHandler", "jobs policies authority clock identifiers"),
    ("prepare_intro", "PrepareIntroNarrationHandler", "jobs episodes policies authority clock identifiers"),
    ("revise_passage_text", "RevisePassageTextHandler", "jobs clock"),
    ("reorder_passages", "ReorderPassagesHandler", "jobs"),
    ("revise_defaults", "ReviseDeliveryDefaultsHandler", "jobs clock"),
    ("validate_recipe", "ValidateRenderRecipeHandler", "jobs compiler"),
    ("require_recipe", "RequireRenderRecipeHandler", "jobs"),
    ("require_dictionary", "RequireDictionaryHandler", "jobs"),
    ("estimate", "EstimateGenerationHandler", "jobs authority compiler clock identifiers"),
    ("generate", "GenerateTakeHandler", "jobs authority clock identifiers budget gateway artifact_store media workspaces"),
    ("reconcile_generation", "ReconcileGenerationAttemptHandler", "jobs authority clock workspaces workspace_verifier provider_events artifact_reader budget budget identifiers"),
    ("record_review", "RecordReviewDecisionHandler", "jobs actors clock identifiers"),
    ("select_take", "SelectWorkingTakeHandler", "jobs authority actors clock identifiers"),
    ("assemble_narration", "AssembleNarrationMasterHandler", "jobs authority clock identifiers assembler artifact_store workspaces"),
    ("record_narration_listening", "RecordNarrationMasterListeningHandler", "jobs actors clock identifiers"),
    ("issue_narration_snapshot", "IssueNarrationMasterSnapshotHandler", "jobs authority clock identifiers"),
    ("reconcile_narration_assembly", "ReconcileNarrationAssemblyAttemptHandler", "jobs authority clock workspaces workspace_verifier provider_events artifact_reader identifiers"),
    ("prepare_episode", "PrepareDiaryEpisodeHandler", "episodes clock identifiers"),
    ("attach_intro", "AttachIntroMasterHandler", "episodes jobs authority clock"),
    ("attach_diary", "AttachDiaryMasterHandler", "episodes jobs authority clock"),
    ("set_intro_diary_gap", "SetIntroDiaryGapHandler", "episodes clock"),
    ("assemble_episode", "AssembleEpisodeSpeechMasterHandler", "episodes jobs authority clock identifiers assembler artifact_store workspaces"),
    ("record_episode_listening", "RecordEpisodeListeningHandler", "episodes actors clock identifiers"),
    ("reconcile_episode_assembly", "ReconcileEpisodeAssemblyAttemptHandler", "episodes jobs authority clock workspaces workspace_verifier provider_events artifact_reader identifiers"),
    ("read_take_audio", "ReadTakeAudioHandler", "jobs artifact_reader media"),
    ("read_narration_master_audio", "ReadNarrationMasterAudioHandler", "jobs artifact_reader media"),
    ("read_episode_master_audio", "ReadEpisodeMasterAudioHandler", "episodes artifact_reader media"),
)


class LiveNarrationStudioTests(unittest.TestCase):
    def test_injected_identifier_source_is_shared_by_handlers_gateway_and_artifact_writer(self):
        identifiers = Identifiers()
        studio = self.build_studio(process_principal=PRINCIPAL, identifiers=identifiers)
        self.assertIs(studio.handlers.prepare_diary.identifiers, identifiers)
        self.assertIs(studio.handlers.prepare_episode.identifiers, identifiers)
        self.assertIs(studio.handlers.estimate.identifiers, identifiers)
        self.assertIs(studio.gateway._identifiers, identifiers)
        self.assertIs(studio.handlers.generate.artifacts._identifiers, identifiers)
        self.assertFalse(hasattr(studio.handlers, "identifiers"))

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix="local-studio-graph-fixture-"))
        self.root = LocalNarrationRoot.open(Path(directory), (Path(__file__).resolve().parents[3],))
        initialize_local_studio(self.root, initialization(), Identifiers())
        self.configuration = load_local_studio_configuration(self.root)

    def build_studio(self, **kwargs):
        self.assertIn("process_principal", inspect.signature(live.build_live_narration).parameters)
        studio = live.build_live_narration(self.root, **kwargs)
        self.addCleanup(studio.close)
        return studio

    def test_every_route_handler_uses_the_same_required_adapter_instances(self):
        studio = self.build_studio(process_principal=PRINCIPAL)
        h = studio.handlers
        shared = {
            "authorizations": h.register_authorization.repository,
            "jobs": h.generate.repository,
            "episodes": h.prepare_episode.repository,
            "authority": h.generate.authority,
            "actors": h.register_authorization.actors,
            "clock": h.generate.clock,
            "identifiers": h.generate.identifiers,
            "policies": studio.policies,
            "compiler": h.validate_recipe.compiler,
            "budget": h.generate.budget,
            "gateway": studio.gateway,
            "artifact_store": h.generate.artifacts,
            "media": h.generate.media,
            "workspaces": h.generate.workspaces,
            "workspace_verifier": h.reconcile_generation.workspace_verifier,
            "provider_events": h.reconcile_generation.provider_events,
            "artifact_reader": h.read_take_audio.artifacts,
            "assembler": h.assemble_narration.assembler,
        }
        for name, handler_type, dependencies in HANDLER_WIRING:
            with self.subTest(handler=name):
                handler = getattr(h, name)
                self.assertIs(type(handler), getattr(application_handlers, handler_type))
                for dependency, logical_name in zip(fields(handler), dependencies.split(), strict=True):
                    self.assertIs(getattr(handler, dependency.name), shared[logical_name], dependency.name)
        self.assertIs(shared["authority"].repository, shared["authorizations"])
        self.assertIs(type(shared["artifact_store"]), FilesystemArtifactStore)
        self.assertIs(type(shared["artifact_reader"]), FilesystemArtifactEvidenceVerifier)
        self.assertIsNot(shared["artifact_store"], shared["artifact_reader"])
        self.assertIs(shared["artifact_reader"]._media_inspector, shared["media"])
        self.assertIs(shared["artifact_store"]._identifiers, shared["identifiers"])
        self.assertIs(shared["assembler"]._artifacts, shared["artifact_reader"])
        self.assertIs(studio.gateway._artifacts, shared["artifact_store"])
        self.assertIs(studio.gateway._clock, shared["clock"])
        self.assertIs(studio.gateway._identifiers, shared["identifiers"])
        self.assertIs(studio.gateway._policies, studio.policies)
        self.assertIs(studio.gateway._transport, studio.transport)
        self.assertIsNone(studio.gateway._usage_source)

        # The future route owner receives this explicit surface, not the live owner.
        self.assertEqual({field.name for field in fields(h)}, {row[0] for row in HANDLER_WIRING} | {"readiness"})
        for name in ("root", "repositories", "jobs", "episodes", "authorizations"):
            self.assertFalse(hasattr(studio, name))
            self.assertFalse(hasattr(h, name))
        for name in ("policies", "gateway", "transport", "actors"):
            self.assertFalse(hasattr(h, name))
        for name in ("prepare_diary", "prepare_intro", "validate_recipe", "require_recipe", "estimate", "generate"):
            self.assertIs(getattr(studio, name), getattr(h, name))

    def test_construction_does_not_read_credentials_or_send_and_one_close_closes_transport_once(self):
        self.assertIn("process_principal", inspect.signature(live.build_live_narration).parameters)
        original_get = os.environ.get

        def guarded_get(key, default=None):
            if key == "CARTESIA_API_KEY":
                raise AssertionError("construction read a credential")
            return original_get(key, default)

        with (
            patch.object(os.environ, "get", side_effect=guarded_get),
            patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")),
            patch("socket.socket.connect", side_effect=AssertionError("socket connect forbidden")),
            patch("socket.socket.connect_ex", side_effect=AssertionError("socket connect_ex forbidden")),
            patch("httpx.Client.send", side_effect=AssertionError("HTTP send forbidden")),
        ):
            studio = live.build_live_narration(self.root, process_principal=PRINCIPAL)
            with patch.object(studio.transport, "close", wraps=studio.transport.close) as close:
                try:
                    result = studio.handlers.readiness()
                    self.assertIs(type(result), DoctorResult)
                    self.assertTrue(result.healthy)
                finally:
                    studio.close()
                close.assert_called_once_with()

    def test_readiness_is_a_zero_argument_read_only_current_doctor_result(self):
        studio = self.build_studio(process_principal=PRINCIPAL)
        readiness = studio.handlers.readiness
        self.assertEqual(tuple(inspect.signature(readiness).parameters), ())
        before = self.root_bytes()
        result = readiness()
        self.assertIs(type(result), DoctorResult)
        self.assertTrue(result.healthy)
        self.assertGreaterEqual(result.checked_file_count, 1)
        self.assertEqual(result.issue_codes, ())
        self.assertEqual(self.root_bytes(), before)
        (self.root.staging / "fixture-unfinished").write_bytes(b"fixture")
        before = self.root_bytes()
        unhealthy = readiness()
        self.assertIs(type(unhealthy), DoctorResult)
        self.assertFalse(unhealthy.healthy)
        self.assertIn("staging_nonempty", unhealthy.issue_codes)
        self.assertEqual(self.root_bytes(), before)

    def test_rebuilding_preserves_configured_actor_with_fresh_default_principals(self):
        signature = inspect.signature(live.build_live_narration).parameters.get("process_principal")
        self.assertIsNotNone(signature, "builder needs an optional process principal")
        self.assertIs(signature.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(signature.default)
        first = self.build_studio()
        second = self.build_studio()
        first_actors = first.handlers.register_authorization.actors
        second_actors = second.handlers.register_authorization.actors
        for actors in (first_actors, second_actors):
            # 32 random bytes are represented by a 64-character ASCII hex token.
            self.assertEqual(len(bytes.fromhex(actors.process_principal)), 32)
            self.assertTrue(actors.process_principal.isascii())
            self.assertEqual(actors.resolve_principal(actors.process_principal).actor_id, self.configuration.actor_id)
        self.assertNotEqual(first_actors.process_principal, second_actors.process_principal)
        with self.assertRaises(AuthorizationDenied):
            second_actors.resolve_principal(first_actors.process_principal)

    def test_denied_principal_cannot_persist_authority_at_the_handler_boundary(self):
        studio = self.build_studio(process_principal=PRINCIPAL)
        handler = studio.handlers.register_authorization
        self.assertEqual(handler.actors.resolve_principal(PRINCIPAL).actor_id, self.configuration.actor_id)
        record_id = self.configuration.lane_b.authorization_record_id
        before = self.root_bytes()
        with self.assertRaisesRegex(AuthorizationDenied, "^principal_not_authorized$"):
            handler(RegisterAuthorizationCommand(
                CommandId(uuid(802)), "fixture-unknown-principal", record_id,
                make_scope(), ContentDigest.from_bytes(b"fixture authority evidence"),
            ))
        self.assertIsNone(handler.repository.load(record_id))
        self.assertEqual(self.root_bytes(), before)

    def root_bytes(self):
        return {path.relative_to(self.root.path): path.read_bytes()
                for path in self.root.path.rglob("*") if path.is_file()}


if __name__ == "__main__":
    unittest.main()
