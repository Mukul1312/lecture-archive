"""Fixture-only composition and durable preview-to-take integration."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from heritage_archive.kernel import ActorId, ContentDigest, ValidationError
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.operations import (
    LocalStudioInitialization, LocalStudioBudgetConfiguration, initialize_local_studio,
)
from heritage_archive.contexts.narrator_voice.domain.values import Lane, NonNegativeDecimal, PassageText, SafeRelativeArtifactPath
from tests.heritage_archive.narrator_voice.test_cartesia_gateway import Identifiers, Clock, Credentials, invocation, bound_usage, sse, chunk, TIMING, DONE
from tests.heritage_archive.narrator_voice.test_cartesia_policy import profile
from tests.heritage_archive.narrator_voice.fixtures import NOW, make_scope, make_recipe_authoring, make_settings_intent, uuid


class CartesiaCompositionTests(unittest.TestCase):
    def test_real_preview_reservation_gateway_wav_publication_and_completed_take(self):
        self._run_generation(with_usage=True)

    def test_real_completed_provider_without_usage_keeps_budget_held(self):
        self._run_generation(with_usage=False)

    def test_known_usage_survives_first_publication_failure_in_workspace_and_hold(self):
        self._run_generation(with_usage=True, publication_collision=True)

    def _run_generation(self, *, with_usage, publication_collision=False):
        import httpx
        from heritage_archive.composition_root.narrator_voice_live import build_live_narration
        from heritage_archive.platform.cartesia.transport import CartesiaSseTransport
        from heritage_archive.contexts.narrator_voice.application.commands import PrepareDiaryNarrationCommand, ValidateRenderRecipeCommand, RequireRenderRecipeCommand, EstimateGenerationCommand, GenerateTakeCommand
        from heritage_archive.contexts.narrator_voice.application.recovery import BudgetRecoveryState
        from heritage_archive.contexts.narrator_voice.domain.authorization import AuthorizationRecord
        from heritage_archive.contexts.narrator_voice.domain.evidence import AttemptState, SubmissionEvidence
        from heritage_archive.contexts.narrator_voice.domain.ids import CommandId, GenerationAttemptId, PassageId, PassageRenderRecipeId
        from heritage_archive.contexts.narrator_voice.domain.narration_job import PassageDraft
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaSynthesisGateway
        from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_repositories import FilesystemAuthorizationRecordRepository, FilesystemNarrationJobRepository
        from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import FilesystemAttemptWorkspaceStore
        class FixtureIdentifiers(Identifiers):
            def new_id(self, kind):
                return GenerationAttemptId(uuid(13)) if kind is GenerationAttemptId else super().new_id(kind)
        body = sse(chunk(), TIMING, DONE)
        usage_record = bound_usage(invocation(), body)
        class Usage:
            def lookup(self, request_digest, response_digest):
                return usage_record
        with TemporaryDirectory(prefix="cartesia-durable-fixture-") as directory, patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")), patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            root = LocalNarrationRoot.open(Path(directory), (Path(__file__).resolve().parents[3],))
            initialize_local_studio(root, initialization(), Identifiers())
            studio = build_live_narration(root)
            studio.close()
            clock, ids = Clock(), FixtureIdentifiers()
            contract = studio.policies.resolve_lane_b_diary().contract
            record = AuthorizationRecord.register(contract.authority_record_id, ActorId(uuid(22)), make_scope(), ContentDigest.from_bytes(b"fixture authority"), NOW)
            self.assertTrue(FilesystemAuthorizationRecordRepository(root).save(record, None))
            prepared = replace(studio.prepare_diary, clock=clock, identifiers=ids)(
                PrepareDiaryNarrationCommand(CommandId(uuid(23)), (PassageDraft(PassageId(uuid(11)), 0, PassageText("ଓଡ଼ିଆ & fixture")),)))
            studio.validate_recipe(ValidateRenderRecipeCommand(CommandId(uuid(24)), prepared.job_id, PassageId(uuid(11)), make_recipe_authoring(recipe_index=12), 1))
            studio.require_recipe(RequireRenderRecipeCommand(CommandId(uuid(25)), prepared.job_id, PassageId(uuid(11)), PassageRenderRecipeId(uuid(12)), 2))
            preview = replace(studio.estimate, clock=clock, identifiers=ids)(
                EstimateGenerationCommand(CommandId(uuid(26)), prepared.job_id, PassageId(uuid(11)), PassageRenderRecipeId(uuid(12)), make_settings_intent(), 3)).preview
            if publication_collision:
                collision = root.artifacts / "evidence/cartesia" / uuid(13) / "sanitized.json"
                collision.parent.mkdir(parents=True)
                collision.write_bytes(b"fixture-existing-evidence")
            calls = []
            def respond(request):
                job = FilesystemNarrationJobRepository(root).load(prepared.job_id)
                attempt = job.generation_attempt(GenerationAttemptId(uuid(13)))
                self.assertEqual(studio.generate.budget.read(attempt.budget_reservation_id), BudgetRecoveryState.RESERVED)
                self.assertEqual(attempt.effective_input.rendered_transcript_bytes, preview.rendered_transcript_bytes)
                calls.append(request.content)
                return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})
            with CartesiaSseTransport(http_transport=httpx.MockTransport(respond)) as transport:
                gateway = CartesiaSynthesisGateway(transport=transport, credentials=Credentials(), policies=studio.policies,
                    artifacts=studio.generate.artifacts, clock=clock, identifiers=ids, usage_source=Usage() if with_usage else None)
                result = replace(studio.generate, clock=clock, identifiers=ids, gateway=gateway)(
                    GenerateTakeCommand(CommandId(uuid(27)), prepared.job_id, preview.preview_id, 4, SafeRelativeArtifactPath("takes/fixture.wav")))
            self.assertEqual(len(calls), 1)
            stored = FilesystemNarrationJobRepository(root).load(prepared.job_id)
            attempt = stored.generation_attempt(GenerationAttemptId(uuid(13)))
            workspace = FilesystemAttemptWorkspaceStore(root).load(attempt.attempt_id)
            if publication_collision:
                self.assertEqual(workspace.submission, SubmissionEvidence.AMBIGUOUS)
                self.assertEqual(result.state, AttemptState.UNKNOWN)
                self.assertEqual(result.budget_disposition, "held")
                self.assertEqual(studio.generate.budget.read(attempt.budget_reservation_id), BudgetRecoveryState.UNKNOWN)
                self.assertEqual(workspace.events, ())
                self.assertEqual(workspace.published_artifacts, ())
                self.assertEqual(stored.takes, ())
                self.assertFalse((root.artifacts / "takes/fixture.wav").exists())
                self.assertEqual(workspace.recovery_evidence[0], "evidence_publication_failed")
                self.assertEqual(len(workspace.recovery_evidence), 2, "durable workspace lost authoritative usage")
                fact = workspace.recovery_evidence[1]
                expected = {
                    "schema": "narrator_voice.authoritative_usage_receipt", "schema_version": 1,
                    "request_sha256": usage_record.request_body_digest.hex_digest,
                    "response_evidence_sha256": usage_record.response_evidence_digest.hex_digest,
                    "usage": "7", "reason_code": "evidence_publication_failed",
                }
                from heritage_archive.kernel import canonical_json
                self.assertEqual(fact, canonical_json(expected).decode("utf-8"))
                ledger_documents = [json.loads(path.read_bytes()) for path in root.operations.glob("*.json")
                    if path.name != "studio-config.json"]
                ledger = next(doc for doc in ledger_documents if doc.get("schema") == "narrator_voice.generation_budget_ledger")
                self.assertEqual([entry["kind"] for entry in ledger["facts"]], ["reserve", "hold"])
                self.assertIn(fact, ledger["facts"][-1].values())
                self.assertEqual(collision.read_bytes(), b"fixture-existing-evidence")
                for private in ("opaque-fake-voice", "fixture-private-word", "fixture-not-a-real-key", "ଓଡ଼ିଆ"):
                    self.assertNotIn(private, fact)
                with self.assertRaises(ValidationError):
                    studio.generate(GenerateTakeCommand(CommandId(uuid(28)), prepared.job_id, preview.preview_id, stored.revision, SafeRelativeArtifactPath("takes/fixture.wav")))
                return
            self.assertEqual(workspace.submission, SubmissionEvidence.COMPLETED)
            if with_usage:
                self.assertEqual(result.state, AttemptState.COMPLETED)
                self.assertEqual(result.budget_disposition, "settled")
                self.assertEqual(studio.generate.budget.read(attempt.budget_reservation_id), BudgetRecoveryState.SETTLED)
                take = stored.takes[0]
                self.assertEqual(take.effective_input.rendered_transcript_bytes, preview.rendered_transcript_bytes)
                wav = (root.artifacts / "takes/fixture.wav").read_bytes()
                self.assertEqual(wav[44:], b"\x01\x00\xfe\xff")
                self.assertEqual(studio.generate.media.inspect_canonical_wav(wav).sample_count, 2)
                self.assertEqual(ContentDigest.from_bytes(wav), take.artifact.reference.content_digest)
                self.assertEqual(len(workspace.published_artifacts), 3)
                # Replaying the consumed preview cannot produce another provider request or overwrite WAV.
                with self.assertRaises(ValidationError):
                    studio.generate(GenerateTakeCommand(CommandId(uuid(28)), prepared.job_id, preview.preview_id, stored.revision, SafeRelativeArtifactPath("takes/fixture.wav")))
                self.assertEqual((root.artifacts / "takes/fixture.wav").read_bytes(), wav)
            else:
                self.assertEqual(result.state, AttemptState.FAILED)
                self.assertEqual(result.budget_disposition, "held")
                self.assertEqual(studio.generate.budget.read(attempt.budget_reservation_id), BudgetRecoveryState.UNKNOWN)
                self.assertEqual(stored.takes, ())
                self.assertFalse((root.artifacts / "takes/fixture.wav").exists())

    def test_live_construction_never_reads_key_or_contacts_network(self):
        from heritage_archive.composition_root.narrator_voice_live import build_live_narration
        with TemporaryDirectory(prefix="cartesia-live-fixture-") as directory:
            root = LocalNarrationRoot.open(Path(directory), (Path(__file__).resolve().parents[3],))
            initialize_local_studio(root, initialization(), Identifiers())
            original_get = os.environ.get
            def guarded_get(key, default=None):
                if key == "CARTESIA_API_KEY":
                    raise AssertionError("construction read a credential")
                return original_get(key, default)
            with patch.object(os.environ, "get", side_effect=guarded_get), patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")), patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
                studio = build_live_narration(root)
                studio.close()
            self.assertEqual(studio.policies.resolve_lane_b_diary().contract.voice_binding, "fake-voice-lane_b")
            self.assertIsNone(studio.gateway._usage_source)

    def test_environment_supplier_reads_only_for_transmission_and_never_caches(self):
        from heritage_archive.composition_root.narrator_voice_live import EnvironmentCartesiaCredentialSupplier
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaCredentialUnavailable
        supplier = EnvironmentCartesiaCredentialSupplier()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CartesiaCredentialUnavailable):
                supplier.read_for_transmission()
            os.environ["CARTESIA_API_KEY"] = "fixture-first"
            self.assertEqual(supplier.read_for_transmission(), "fixture-first")
            os.environ["CARTESIA_API_KEY"] = "fixture-second"
            self.assertEqual(supplier.read_for_transmission(), "fixture-second")
        self.assertEqual(vars(supplier), {})


def initialization():
    return LocalStudioInitialization(
        "Fixture operator", profile(), profile(Lane.C),
        LocalStudioBudgetConfiguration("fixture-project", "fixture-cycle", "characters",
            NonNegativeDecimal("1000"), NonNegativeDecimal("1000"), NonNegativeDecimal("10000"), NonNegativeDecimal("10000")),
        4410, 8820,
    )
