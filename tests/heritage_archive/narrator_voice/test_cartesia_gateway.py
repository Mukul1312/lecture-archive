"""Real gateway against HTTPX's fixture boundary; no network or provider credentials."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import json
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import httpx

from heritage_archive.kernel import ContentDigest
from heritage_archive.platform.cartesia.transport import CartesiaSseTransport
from heritage_archive.contexts.narrator_voice.application.ports import RecipeAuthoringRequest, RecipeCompileRequest, SynthesisInvocation
from heritage_archive.contexts.narrator_voice.application.synthesis_failures import SynthesisSubmittedFailure, SynthesisAmbiguousFailure, SynthesisPreSendFailure
from heritage_archive.contexts.narrator_voice.domain.ids import GenerationAttemptId, NarrationJobId, PassageId, PassageRenderRecipeId
from heritage_archive.contexts.narrator_voice.domain.values import EffectiveSynthesisInput, ControlProvenance, Lane, PassageText, NonNegativeDecimal, ResolvedControl
from heritage_archive.contexts.narrator_voice.domain.evidence import ProviderEventKind, ProviderTerminalClass, SubmissionEvidence
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_policy import ConfiguredNarrationReleasePolicyResolver
from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_recipe import CartesiaRecipeCompiler
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import FilesystemArtifactStore
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from tests.heritage_archive.narrator_voice.fixtures import NOW, make_authority, make_settings, uuid
from tests.heritage_archive.narrator_voice.test_cartesia_policy import profile


class Identifiers:
    def new_id(self, kind):
        return kind(str(uuid4()))


class Clock:
    def now(self):
        return NOW


class Credentials:
    def read_for_transmission(self):
        return "fixture-not-a-real-key"


def policies():
    return ConfiguredNarrationReleasePolicyResolver(profile(), profile(Lane.C))


def invocation(lane=Lane.B):
    policy = policies()
    contract = policy.resolve_lane_b_diary().contract if lane is Lane.B else policy.resolve_lane_c_intro(make_authority(lane=lane).scope.intended_episode_id).contract
    text = PassageText("ଓଡ଼ିଆ & fixture")
    job = NarrationJobId(uuid(10))
    passage = PassageId(uuid(11))
    compiler = CartesiaRecipeCompiler()
    recipe = compiler.compile_recipe(RecipeAuthoringRequest(job, passage, 1, text, PassageRenderRecipeId(uuid(12)), 1, (), None, contract)).recipe
    settings = make_settings(lane.value)
    authority = make_authority(lane=lane)
    preview = compiler.compile(RecipeCompileRequest(job, 1, text, recipe, settings, contract, authority))
    effective = EffectiveSynthesisInput.create(
        job_id=job, lane=lane, passage_id=passage, text_revision=1, text=text,
        recipe_id=recipe.recipe_id, recipe_revision=1, recipe_digest=recipe.digest,
        compiler_version=preview.compiler_version, settings=settings, contract_digest=contract.digest,
        authority_scope=authority.scope, authority_revision=authority.record_revision,
        authority_digest=authority.record_digest, authority_observed_at=NOW,
        endpoint=preview.endpoint, api_schema=contract.api_schema, capability_snapshot=contract.capability_snapshot,
        rendered_transcript=preview.rendered_transcript, canonical_projection=text.value,
        timestamps_requested=True, normalization="off", output_audio=contract.audio,
        billable_rule=preview.billable_rule, billable_characters=preview.billable_characters,
    )
    return SynthesisInvocation(GenerationAttemptId(uuid(13)), contract, effective)


def sse(*frames):
    return b"".join(b"data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode() + b"\n\n" for frame in frames)


def chunk(raw=b"\x01\x00\xfe\xff"):
    return {"type": "chunk", "done": False, "data": base64.b64encode(raw).decode(), "step_time": 0.2, "status_code": 206}


DONE = {"type": "done", "done": True, "status_code": 200}
TIMING = {"type": "timestamps", "done": False, "status_code": 206, "word_timestamps": {"words": ["fixture-private-word"], "start": [0.0], "end": [0.1]}}


class CartesiaGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="cartesia-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = LocalNarrationRoot.open(Path(self.temp.name), (Path(__file__).resolve().parents[3],))
        self.root.initialize_layout()
        self.identifiers = Identifiers()
        self.artifacts = FilesystemArtifactStore(self.root, self.identifiers)
        self.requests = []

    def gateway(self, body, status=200, **kwargs):
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaSynthesisGateway
        def respond(request):
            self.requests.append(request.content)
            return httpx.Response(status, content=body, headers={"Content-Type": "text/event-stream"})
        transport = CartesiaSseTransport(http_transport=httpx.MockTransport(respond), sleep=lambda _: None)
        self.addCleanup(transport.close)
        return CartesiaSynthesisGateway(transport=transport, credentials=Credentials(), policies=policies(), artifacts=self.artifacts, clock=Clock(), identifiers=self.identifiers, **kwargs)

    def test_exact_utf8_request_and_done_without_usage_holds_completed_evidence(self):
        call = invocation()
        gateway = self.gateway(sse(chunk(), TIMING, DONE))
        with self.assertRaises(SynthesisSubmittedFailure) as caught:
            gateway.synthesize(call)
        evidence = caught.exception.evidence
        self.assertEqual(evidence.submission, SubmissionEvidence.COMPLETED)
        self.assertEqual(evidence.reason_code, "authoritative_usage_unavailable")
        self.assertIsNone(evidence.usage)
        expected = ('{"model_id":"sonic-3.6-2026-08-27","transcript":"ଓଡ଼ିଆ &amp; fixture",'
            '"voice":"opaque-fake-voice-lane_b","output_format":{"container":"raw","encoding":"pcm_s16le","sample_rate":44100},'
            '"language":"or","normalization":"off","add_timestamps":true,"add_phoneme_timestamps":false,'
            '"use_normalized_timestamps":false,"pronunciation_dict_id":"fake-dictionary-lane_b",'
            '"generation_config":{"volume":1.0,"speed":0.9,"emotion":"calm"},'
            '"context_id":"123e4567-e89b-42d3-a456-426614190013"}').encode()
        self.assertEqual(self.requests, [expected])
        self.assertEqual([event.kind for event in evidence.events], [ProviderEventKind.REQUEST, ProviderEventKind.AUDIO, ProviderEventKind.TIMING, ProviderEventKind.TERMINAL])
        self.assertEqual(evidence.events[-1].terminal_classification, ProviderTerminalClass.FAILURE)
        self.assertEqual(len(evidence.publications), 2)
        self.assertIsNotNone(evidence.raw_timing_reference)
        sanitized = (self.root.artifacts / "evidence/cartesia" / call.attempt_id.value / "sanitized.json").read_bytes()
        for forbidden in (b"fixture-not-a-real-key", b"opaque-fake-voice", b"fake-dictionary", b"fixture-private-word", b"&amp;", b"AQD+/w=="):
            self.assertNotIn(forbidden, sanitized)
        timing = (self.root.artifacts / "evidence/cartesia" / call.attempt_id.value / "timestamps.json").read_bytes()
        self.assertEqual(json.loads(timing), [TIMING])

    def test_cross_lane_dictionary_and_wrong_contract_fail_before_transmission(self):
        call = invocation()
        cases = [replace(call.effective_input.settings, dictionary=profile(Lane.C).dictionary_binding)]
        for settings in cases:
            effective = rebuild(call.effective_input, settings=settings)
            gateway = self.gateway(sse(DONE))
            with self.assertRaises(SynthesisPreSendFailure) as caught:
                gateway.synthesize(replace(call, effective_input=effective))
            self.assertEqual(caught.exception.evidence.submission, SubmissionEvidence.DEFINITELY_NOT_SENT)
        self.assertEqual(self.requests, [])

    def test_malformed_stream_preserves_partial_pcm_and_one_final_terminal(self):
        gateway = self.gateway(sse(chunk()) + b'data: {"type":"done","type":"error"}\n\n')
        with self.assertRaises(SynthesisAmbiguousFailure) as caught:
            gateway.synthesize(invocation())
        evidence = caught.exception.evidence
        self.assertEqual(evidence.events[-1].kind, ProviderEventKind.TERMINAL)
        self.assertEqual(evidence.events[-1].terminal_classification, ProviderTerminalClass.AMBIGUOUS)
        self.assertEqual(sum(e.kind is ProviderEventKind.TERMINAL for e in evidence.events), 1)
        self.assertEqual((self.root.artifacts / "evidence/cartesia" / invocation().attempt_id.value / "partial.pcm").read_bytes(), b"\x01\x00\xfe\xff")
        self.assertEqual(len(evidence.publications), 2)

    def test_invalid_boundary_value_is_classified_without_any_io(self):
        with self.assertRaises(SynthesisPreSendFailure) as caught:
            self.gateway(sse(DONE)).synthesize(None)
        self.assertEqual(caught.exception.evidence.publications, ())
        self.assertEqual(self.requests, [])

    def test_transport_with_another_endpoint_is_rejected_before_transmission(self):
        from heritage_archive.platform.cartesia.contract import CARTESIA_TRANSPORT_CONTRACT
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaSynthesisGateway
        calls = []
        with CartesiaSseTransport(contract=replace(CARTESIA_TRANSPORT_CONTRACT, origin="https://fixture.invalid"),
                http_transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, content=sse(chunk(), DONE)))) as transport:
            gateway = CartesiaSynthesisGateway(transport=transport, credentials=Credentials(), policies=policies(),
                artifacts=self.artifacts, clock=Clock(), identifiers=self.identifiers)
            with self.assertRaises(SynthesisPreSendFailure):
                gateway.synthesize(invocation())
        self.assertEqual(calls, [])

    def test_digest_bound_usage_success_wraps_exact_pcm_once(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaAuthoritativeUsage
        from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import CanonicalWavInspector, encode_canonical_pcm16_wav
        body = sse(chunk(b"\x01\x00"), TIMING, TIMING, chunk(b"\xfe\xff"), DONE)
        record = bound_usage(invocation(), body)
        class Usage:
            def lookup(self, request_digest, response_digest):
                return record
        with patch("heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway.encode_canonical_pcm16_wav", wraps=encode_canonical_pcm16_wav) as encoder:
            result = self.gateway(body, usage_source=Usage()).synthesize(invocation())
        self.assertEqual(encoder.call_count, 1)
        self.assertEqual(result.canonical_wav_bytes[44:], b"\x01\x00\xfe\xff")
        self.assertEqual(CanonicalWavInspector().inspect_canonical_wav(result.canonical_wav_bytes).sample_count, 2)
        self.assertEqual(result.usage, NonNegativeDecimal("7"))
        self.assertEqual(result.events[-2].kind, ProviderEventKind.USAGE)
        self.assertEqual(result.events[-1].terminal_classification, ProviderTerminalClass.SUCCESS)
        self.assertEqual(len(result.evidence_publications), 2)
        self.assertEqual(sum(e.kind is ProviderEventKind.TERMINAL for e in result.events), 1)
        self.assertEqual(json.loads((self.root.artifacts / result.evidence_publications[1].relative_location.value).read_bytes()), [TIMING, TIMING])
        for publication in result.evidence_publications:
            self.assertEqual(ContentDigest.from_bytes((self.root.artifacts / publication.relative_location.value).read_bytes()), publication.reference.content_digest)

    def test_usage_with_wrong_request_or_response_digest_never_completes(self):
        body = sse(chunk(), DONE)
        for field in ("request_body_digest", "response_evidence_digest"):
            with self.subTest(field=field):
                call = replace(invocation(), attempt_id=GenerationAttemptId(str(uuid4())))
                record = bound_usage(call, body)
                wrong = replace(record, **{field: ContentDigest.from_bytes(b"wrong")})
                class Usage:
                    def lookup(self, request_digest, response_digest):
                        return wrong
                with self.assertRaises(SynthesisSubmittedFailure) as caught:
                    self.gateway(body, usage_source=Usage()).synthesize(call)
                self.assertIsNone(caught.exception.evidence.usage)
                self.assertEqual(caught.exception.evidence.reason_code, "authoritative_usage_unavailable")

    def test_provider_protocol_failure_matrix_is_ambiguous_with_one_final_terminal(self):
        bad_frames = [
            sse(DONE, DONE), sse(DONE, chunk()), sse(dict(chunk(), done=True)),
            sse(dict(chunk(), status_code=True)), sse(dict(chunk(), step_time=True)),
            sse(dict(chunk(), data="not-base64!")), sse(dict(chunk(), context_id="wrong-private-context")),
            sse(dict(DONE, unused=True)), sse(dict(DONE, status_code=206)),
            sse(dict(TIMING, word_timestamps={"words": ["private"], "start": [False], "end": [1.0]})),
            sse(dict(TIMING, word_timestamps={"words": ["private"], "start": [], "end": [1.0]})),
            b'event: chunk\ndata: {}\n\n', b'data: {"type":"chunk","step_time":NaN}\n\n',
            b'data: {"type":"done","done":true,"status_code":200,"unknown":null}\n\n',
            sse(chunk(b"x"), DONE), sse(chunk(b""), DONE), sse(chunk()),
        ]
        for body in bad_frames:
            with self.subTest(body=body[:60]):
                call = replace(invocation(), attempt_id=GenerationAttemptId(str(uuid4())))
                with self.assertRaises(SynthesisAmbiguousFailure) as caught:
                    self.gateway(body).synthesize(call)
                self.assertEqual(caught.exception.evidence.events[-1].terminal_classification, ProviderTerminalClass.AMBIGUOUS)
                self.assertEqual(sum(e.kind is ProviderEventKind.TERMINAL for e in caught.exception.evidence.events), 1)

    def test_http_certainty_is_not_weakened_by_error_body(self):
        error = {"type": "error", "done": True, "message": "fixture-private-error", "request_id": "fixture-private-request", "status_code": 400, "title": "fixture-private-title"}
        for status, failure, submission in ((302, SynthesisSubmittedFailure, SubmissionEvidence.STARTED), (401, SynthesisSubmittedFailure, SubmissionEvidence.STARTED), (429, SynthesisAmbiguousFailure, SubmissionEvidence.AMBIGUOUS), (503, SynthesisAmbiguousFailure, SubmissionEvidence.AMBIGUOUS), (200, SynthesisSubmittedFailure, SubmissionEvidence.COMPLETED)):
            with self.subTest(status=status):
                call = replace(invocation(), attempt_id=GenerationAttemptId(str(uuid4())))
                with self.assertRaises(failure) as caught:
                    self.gateway(sse(error), status=status).synthesize(call)
                evidence = caught.exception.evidence
                self.assertEqual(evidence.submission, submission)
                self.assertEqual([event.kind for event in evidence.events], [ProviderEventKind.REQUEST, ProviderEventKind.ERROR, ProviderEventKind.TERMINAL])
                sanitized = (self.root.artifacts / evidence.publications[0].relative_location.value).read_bytes()
                self.assertNotIn(b"fixture-private", sanitized)

    def test_explicit_omissions_are_omitted_and_lane_c_uses_its_own_voice(self):
        call = invocation(Lane.C)
        settings = replace(call.effective_input.settings,
            dictionary=None, dictionary_provenance=ControlProvenance.EXPLICITLY_OMITTED,
            emotion=ResolvedControl(ControlProvenance.EXPLICITLY_OMITTED, None))
        call = replace(call, effective_input=rebuild(call.effective_input, settings=settings))
        with self.assertRaises(SynthesisSubmittedFailure):
            self.gateway(sse(chunk(), DONE)).synthesize(call)
        request = json.loads(self.requests[0])
        self.assertNotIn("pronunciation_dict_id", request)
        self.assertNotIn("emotion", request["generation_config"])
        self.assertEqual(request["voice"], "opaque-fake-voice-lane_c")
        self.assertNotIn("locale", request)
        self.assertNotIn("accent", request)

    def test_publication_conflicts_keep_every_successful_publication_referenced(self):
        for blocked in ("sanitized.json", "timestamps.json", "partial.pcm"):
            with self.subTest(blocked=blocked):
                call = replace(invocation(), attempt_id=GenerationAttemptId(str(uuid4())))
                path = self.root.artifacts / "evidence/cartesia" / call.attempt_id.value / blocked
                path.parent.mkdir(parents=True)
                path.write_bytes(b"fixture-preexisting-evidence")
                with self.assertRaises(SynthesisAmbiguousFailure) as caught:
                    self.gateway(sse(chunk(), TIMING)).synthesize(call)
                evidence = caught.exception.evidence
                self.assertEqual(evidence.reason_code, "evidence_publication_failed")
                self.assertEqual(path.read_bytes(), b"fixture-preexisting-evidence")
                refs = {ref for event in evidence.events for ref in (event.sanitized_raw_reference, event.timing_reference, event.pcm_reference) if ref}
                if evidence.raw_timing_reference:
                    refs.add(evidence.raw_timing_reference)
                self.assertEqual(refs, {p.reference for p in evidence.publications})
                self.assertEqual(len(refs), len(evidence.publications))

    def test_requested_off_phonemes_are_private_evidence_and_ambiguous(self):
        frame = {"type": "phoneme_timestamps", "done": False, "status_code": 206, "phoneme_timestamps": {"phonemes": ["fixture-private-phoneme"], "start": [0.0], "end": [0.1]}}
        with self.assertRaises(SynthesisAmbiguousFailure) as caught:
            self.gateway(sse(chunk(), frame, DONE)).synthesize(invocation())
        evidence = caught.exception.evidence
        self.assertEqual(evidence.reason_code, "unexpected_phoneme_timestamps")
        self.assertIsNotNone(evidence.raw_timing_reference)
        self.assertNotIn(b"fixture-private-phoneme", (self.root.artifacts / evidence.publications[0].relative_location.value).read_bytes())

    def test_fixed_contract_controls_endpoint_and_frozen_byte_tampering_never_transmit(self):
        for field, value in (("provider", "other"), ("model_snapshot", "other"), ("api_schema", "other"),
                ("capability_snapshot", "other"), ("opaque_provider_voice_ref", "other-private-voice"),
                ("voice_binding", "other-binding"), ("speaker_binding", "other-speaker"),
                ("purpose", "other-purpose"), ("authority_record_id", profile(Lane.C).authorization_record_id)):
            with self.subTest(contract_field=field):
                original = invocation()
                contract = replace(original.contract, **{field: value})
                call = SynthesisInvocation(GenerationAttemptId(str(uuid4())), contract, rebuild(original.effective_input, contract_digest=contract.digest))
                with self.assertRaises(SynthesisPreSendFailure):
                    self.gateway(sse(chunk(), DONE)).synthesize(call)
        for field, value in (("endpoint", "https://fixture.invalid"), ("timestamps_requested", False),
                ("normalization", "on"), ("api_schema", "other"), ("compiler_version", "other")):
            with self.subTest(effective_field=field):
                call = invocation()
                call = replace(call, attempt_id=GenerationAttemptId(str(uuid4())), effective_input=rebuild(call.effective_input, **{field: value}))
                with self.assertRaises(SynthesisPreSendFailure):
                    self.gateway(sse(chunk(), DONE)).synthesize(call)
        for field, value in (("rendered_transcript_byte_length", 1), ("rendered_transcript_digest", ContentDigest.from_bytes(b"wrong")), ("request_digest", ContentDigest.from_bytes(b"wrong"))):
            call = replace(invocation(), attempt_id=GenerationAttemptId(str(uuid4())))
            object.__setattr__(call.effective_input, field, value)
            with self.assertRaises(SynthesisPreSendFailure):
                self.gateway(sse(chunk(), DONE)).synthesize(call)
        for field, value in (("speed", "0.59"), ("speed", "1.51"), ("volume", "0.49"), ("volume", "2.01"), ("emotion", "excited")):
            call = invocation()
            settings = replace(call.effective_input.settings, **{field: ResolvedControl(ControlProvenance.EXPLICITLY_SET, value)})
            call = replace(call, attempt_id=GenerationAttemptId(str(uuid4())), effective_input=rebuild(call.effective_input, settings=settings))
            with self.assertRaises(SynthesisPreSendFailure):
                self.gateway(sse(chunk(), DONE)).synthesize(call)
        self.assertEqual(self.requests, [])

    def test_transport_and_credential_failures_have_conservative_categories(self):
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaSynthesisGateway, CartesiaCredentialUnavailable
        cases = [(httpx.ConnectTimeout, SynthesisPreSendFailure), (httpx.ReadTimeout, SynthesisAmbiguousFailure),
            (httpx.WriteError, SynthesisAmbiguousFailure), (RuntimeError, SynthesisAmbiguousFailure)]
        for error_type, failure_type in cases:
            with self.subTest(error_type=error_type):
                transmissions = []
                def fail(request):
                    transmissions.append(request.content)
                    raise error_type("fixture-private-error")
                with CartesiaSseTransport(http_transport=httpx.MockTransport(fail), sleep=lambda _: None) as transport:
                    gateway = CartesiaSynthesisGateway(transport=transport, credentials=Credentials(), policies=policies(),
                        artifacts=self.artifacts, clock=Clock(), identifiers=self.identifiers)
                    call = replace(invocation(), attempt_id=GenerationAttemptId(str(uuid4())))
                    with self.assertRaises(failure_type) as caught:
                        gateway.synthesize(call)
                    self.assertNotIn("fixture-private-error", str(caught.exception))
                    self.assertEqual(len(transmissions), 3 if error_type is httpx.ConnectTimeout else 1)
        class MissingCredential:
            def read_for_transmission(self):
                raise CartesiaCredentialUnavailable("fixture-private-error")
        with CartesiaSseTransport(http_transport=httpx.MockTransport(lambda _: self.fail("transmitted without credentials"))) as transport:
            gateway = CartesiaSynthesisGateway(transport=transport, credentials=MissingCredential(), policies=policies(),
                artifacts=self.artifacts, clock=Clock(), identifiers=self.identifiers)
            with self.assertRaises(SynthesisPreSendFailure) as caught:
                gateway.synthesize(invocation())
            self.assertEqual(caught.exception.evidence.reason_code, "credential_unavailable")

    def test_read_timeout_after_audio_preserves_observed_pcm(self):
        class Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield sse(chunk())
                raise httpx.ReadTimeout("fixture-private-timeout")
        from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaSynthesisGateway
        with CartesiaSseTransport(http_transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream()))) as transport:
            gateway = CartesiaSynthesisGateway(transport=transport, credentials=Credentials(), policies=policies(),
                artifacts=self.artifacts, clock=Clock(), identifiers=self.identifiers)
            with self.assertRaises(SynthesisAmbiguousFailure) as caught:
                gateway.synthesize(invocation())
        self.assertEqual(caught.exception.evidence.reason_code, "read_timeout")
        partial = caught.exception.evidence.publications[-1]
        self.assertEqual((self.root.artifacts / partial.relative_location.value).read_bytes(), b"\x01\x00\xfe\xff")

    def test_decoded_pcm_limit_keeps_exact_accumulated_prefix(self):
        raw = b"\x01\x00" * (128 * 1024)
        body = sse(*(chunk(raw) for _ in range(65)), DONE)
        with self.assertRaises(SynthesisAmbiguousFailure) as caught:
            self.gateway(body).synthesize(invocation())
        self.assertEqual(caught.exception.evidence.reason_code, "decoded_pcm_limit")
        partial = caught.exception.evidence.publications[-1]
        self.assertEqual(partial.reference.byte_size, 16 * 1024 * 1024)
        self.assertEqual((self.root.artifacts / partial.relative_location.value).read_bytes(), raw * 64)

    def test_wav_encoding_failure_keeps_usage_and_partial_pcm_evidence(self):
        body = sse(chunk(), DONE)
        record = bound_usage(invocation(), body)
        class Usage:
            def lookup(self, request_digest, response_digest):
                return record
        with patch("heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway.encode_canonical_pcm16_wav", side_effect=ValueError("fixture-private-encoding")):
            with self.assertRaises(SynthesisAmbiguousFailure) as caught:
                self.gateway(body, usage_source=Usage()).synthesize(invocation())
        self.assertEqual(caught.exception.evidence.usage, NonNegativeDecimal("7"))
        self.assertEqual(caught.exception.evidence.reason_code, "provider_completion_encoding_failed")
        self.assertEqual(caught.exception.evidence.publications[-1].reference.byte_size, 4)


def rebuild(effective, **changes):
    computed = {"rendered_transcript_byte_length", "rendered_transcript_digest", "canonical_projection_digest", "request_digest"}
    values = {name: getattr(effective, name) for name in effective.__dataclass_fields__ if name not in computed}
    return EffectiveSynthesisInput.create(**(values | changes))


def bound_usage(call, body):
    """Independent fixture ledger record; bind ordered frame evidence and exact request."""
    import hashlib
    from heritage_archive.contexts.narrator_voice.infrastructure.cartesia_gateway import CartesiaAuthoritativeUsage
    # This independently authored fixture wire shape mirrors the pinned provider contract.
    settings = call.effective_input.settings
    request = {"model_id": "sonic-3.6-2026-08-27", "transcript": call.effective_input.rendered_transcript,
        "voice": call.contract.opaque_provider_voice_ref,
        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 44100},
        "language": "or", "normalization": "off", "add_timestamps": True, "add_phoneme_timestamps": False,
        "use_normalized_timestamps": False}
    if settings.dictionary is not None:
        request["pronunciation_dict_id"] = settings.dictionary.opaque_reference
    request["generation_config"] = {"volume": float(settings.volume.value), "speed": float(settings.speed.value)}
    if settings.emotion.value is not None:
        request["generation_config"]["emotion"] = settings.emotion.value
    request["context_id"] = call.attempt_id.value
    digest = hashlib.sha256(b"cartesia.response-evidence.v1\x00")
    parts = [b"200", b"1"]
    for frame in body.split(b"\n\n"):
        if frame:
            assert frame.startswith(b"data: ")
            parts.extend([b"0", frame[6:]])
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return CartesiaAuthoritativeUsage(ContentDigest.from_bytes(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()), ContentDigest("sha256", digest.hexdigest()), NonNegativeDecimal("7"))
