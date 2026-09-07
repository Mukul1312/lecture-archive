"""Cartesia anti-corruption adapter: exact requests and immutable private evidence."""
from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
import json
import math
from typing import Protocol

from heritage_archive.kernel import ContentDigest, ValidationError
from heritage_archive.platform.cartesia.contract import CARTESIA_TRANSPORT_CONTRACT
from heritage_archive.platform.cartesia.transport import (
    CartesiaCredentialSupplier, CartesiaSseTransport, CartesiaTransportOutcome,
    TransportSubmissionCertainty,
)

from ..application.ports import Clock, IdentifierSource, SynthesisInvocation, SynthesisResult
from ..application.synthesis_failures import (
    AuthoritativeUsageReceipt, SynthesisFailureEvidence, SynthesisPreSendFailure, SynthesisAmbiguousFailure,
    SynthesisSubmittedFailure,
)
from ..domain.evidence import ProviderEventEvidence, ProviderEventKind, ProviderTerminalClass, SubmissionEvidence
from ..domain.ids import ProviderEventId
from ..domain.values import FixedTwoDecimal, Lane, NonNegativeDecimal, SafeRelativeArtifactPath
from .cartesia_policy import ConfiguredNarrationReleasePolicyResolver
from .cartesia_recipe import CARTESIA_RECIPE_COMPILER_VERSION, CARTESIA_BILLABLE_RULE
from .filesystem_evidence import FilesystemArtifactStore
from .pcm_audio import encode_canonical_pcm16_wav


class CartesiaCredentialUnavailable(Exception):
    """A supplier could not provide a credential before any transmission."""


@dataclass(frozen=True, slots=True)
class CartesiaAuthoritativeUsage:
    request_body_digest: ContentDigest
    response_evidence_digest: ContentDigest
    usage: NonNegativeDecimal


class CartesiaUsageEvidenceSource(Protocol):
    def lookup(self, request_body_digest: ContentDigest, response_evidence_digest: ContentDigest) -> CartesiaAuthoritativeUsage | None: ...


def response_evidence_digest(outcome: CartesiaTransportOutcome) -> ContentDigest:
    """Hash framed evidence, explicitly not the raw HTTP wire body.

    SHA-256 starts with the ASCII domain and NUL below. Each subsequent field
    has an unsigned 8-byte big-endian byte length, then its exact bytes:
    ASCII status (or None), ASCII completion 1/0, then each ordered frame's
    event (0 for absent, otherwise 1 plus UTF-8 name) and exact data bytes.
    Only semantic success from a complete stream can authorize usage lookup.
    """
    digest = hashlib.sha256(b"cartesia.response-evidence.v1\x00")
    pieces = [str(outcome.http_status).encode("ascii"), b"1" if outcome.stream_complete else b"0"]
    for frame in outcome.frames:
        pieces.extend((b"0" if frame.event is None else b"1" + frame.event.encode("utf-8"), frame.data))
    for piece in pieces:
        digest.update(len(piece).to_bytes(8, "big"))
        digest.update(piece)
    return ContentDigest("sha256", digest.hexdigest())


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


class _ProtocolFailure(ValueError):
    pass


def _invalid():
    raise _ProtocolFailure("provider_protocol_invalid")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _parse_frame(frame, attempt_id):
    if frame.event is not None:
        _invalid()
    value = json.loads(frame.data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=lambda _: _invalid())
    if type(value) is not dict or type(value.get("type")) is not str:
        _invalid()
    kind = value["type"]
    required = {
        "chunk": {"type", "done", "data", "step_time", "status_code"},
        "timestamps": {"type", "done", "status_code", "word_timestamps"},
        "phoneme_timestamps": {"type", "done", "status_code", "phoneme_timestamps"},
        "done": {"type", "done", "status_code"},
        "error": {"type", "done", "message", "request_id", "status_code", "title"},
    }.get(kind)
    if required is None:
        _invalid()
    optional = {"doc_url", "error_code"} if kind == "error" else {"context_id"}
    if not required <= value.keys() or value.keys() - required - optional:
        _invalid()
    if type(value["done"]) is not bool or type(value["status_code"]) is not int:
        _invalid()
    if kind == "error":
        if any(type(value[key]) is not str for key in ("message", "request_id", "title") + tuple(value.keys() & optional)):
            _invalid()
        if not 400 <= value["status_code"] <= 599:
            _invalid()
    else:
        if value.get("context_id") is not None and (type(value["context_id"]) is not str or value["context_id"] != attempt_id):
            _invalid()
        if value["done"] is not (kind == "done") or value["status_code"] != (200 if kind == "done" else 206):
            _invalid()
    if kind == "chunk":
        if type(value["data"]) is not str or not _finite_number(value["step_time"]):
            _invalid()
    if kind in ("timestamps", "phoneme_timestamps"):
        timing = value["word_timestamps" if kind == "timestamps" else "phoneme_timestamps"]
        words = "words" if kind == "timestamps" else "phonemes"
        if type(timing) is not dict or set(timing) != {words, "start", "end"}:
            _invalid()
        if any(type(timing[key]) is not list for key in timing):
            _invalid()
        if not len(timing[words]) == len(timing["start"]) == len(timing["end"]):
            _invalid()
        if any(type(word) is not str for word in timing[words]) or any(not _finite_number(number) for key in ("start", "end") for number in timing[key]):
            _invalid()
    return value


class CartesiaSynthesisGateway:
    def __init__(
        self, *, transport: CartesiaSseTransport, credentials: CartesiaCredentialSupplier,
        policies: ConfiguredNarrationReleasePolicyResolver, artifacts: FilesystemArtifactStore,
        clock: Clock, identifiers: IdentifierSource, usage_source: CartesiaUsageEvidenceSource | None = None,
    ):
        self._transport = transport
        self._credentials = credentials
        self._policies = policies
        self._artifacts = artifacts
        self._clock = clock
        self._identifiers = identifiers
        self._usage_source = usage_source

    def _request(self, invocation):
        if type(invocation) is not SynthesisInvocation:
            raise ValidationError("invalid invocation")
        # This concrete Task 4 transport has no public contract accessor. Verify
        # its frozen configuration so injected fixtures cannot silently retarget
        # a request whose application-owned endpoint and digest were validated.
        if type(self._transport) is not CartesiaSseTransport or self._transport._contract != CARTESIA_TRANSPORT_CONTRACT:
            raise ValidationError("transport differs from the fixed Cartesia contract")
        # Re-run frozen DTO checks, including the semantic request/settings digest.
        replace(invocation.effective_input)
        replace(invocation)
        contract, effective = invocation.contract, invocation.effective_input
        fixed = (self._policies.resolve_lane_b_diary() if contract.lane is Lane.B else
                 self._policies.resolve_lane_c_intro(contract.intended_episode_id))
        if contract != fixed.contract or effective.contract_digest != fixed.contract.digest:
            raise ValidationError("invocation differs from fixed release policy")
        transport = CARTESIA_TRANSPORT_CONTRACT
        if (effective.lane != contract.lane or effective.api_schema != contract.api_schema or
            effective.capability_snapshot != contract.capability_snapshot or
            effective.endpoint != transport.origin + transport.sse_path or
            effective.output_audio != contract.audio or effective.timestamps_requested is not True or
            effective.normalization != "off" or effective.compiler_version != CARTESIA_RECIPE_COMPILER_VERSION or
            effective.billable_rule != CARTESIA_BILLABLE_RULE or
            effective.billable_characters != len(effective.rendered_transcript)):
            raise ValidationError("effective input differs from fixed provider capabilities")
        scope = effective.authority_scope
        if (scope.speaker_binding, scope.voice_binding, scope.language, scope.purpose, scope.intended_episode_id) != (
            contract.speaker_binding, contract.voice_binding, contract.language, contract.purpose, contract.intended_episode_id
        ):
            raise ValidationError("frozen authority scope differs from fixed policy")
        settings = effective.settings
        if settings.dictionary is not None and settings.dictionary != fixed.initial_defaults.dictionary:
            raise ValidationError("effective dictionary differs from configured lane")
        speed, volume = FixedTwoDecimal(settings.speed.value), FixedTwoDecimal(settings.volume.value)
        if not Decimal("0.60") <= Decimal(speed.value) <= Decimal("1.50") or not Decimal("0.50") <= Decimal(volume.value) <= Decimal("2.00") or settings.emotion.value not in (None, "calm"):
            raise ValidationError("effective controls are outside verified capabilities")
        body = {
            "model_id": contract.model_snapshot,
            "transcript": effective.rendered_transcript,
            "voice": contract.opaque_provider_voice_ref,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 44100},
            "language": "or", "normalization": "off",
            "add_timestamps": True, "add_phoneme_timestamps": False, "use_normalized_timestamps": False,
        }
        if settings.dictionary is not None:
            body["pronunciation_dict_id"] = settings.dictionary.opaque_reference
        body["generation_config"] = {"volume": float(volume.value), "speed": float(speed.value)}
        if settings.emotion.value is not None:
            body["generation_config"]["emotion"] = settings.emotion.value
        body["context_id"] = invocation.attempt_id.value
        raw = _json_bytes(body)
        sanitized = dict(body)
        sanitized["transcript"] = {"sha256": effective.rendered_transcript_digest.hex_digest, "byte_length": effective.rendered_transcript_byte_length}
        sanitized["voice"] = {"binding": contract.voice_binding}
        if settings.dictionary is not None:
            dictionary = settings.dictionary
            sanitized["pronunciation_dict_id"] = {
                "sha256": dictionary.content_digest.hex_digest, "revision": dictionary.revision,
                "capability_identity": dictionary.capability_identity,
                "binding_digest": settings.digest.hex_digest,
            }
        projection = {
            "method": "POST", "url": effective.endpoint,
            "headers": {"Accept": "text/event-stream", "Accept-Encoding": "identity", "Content-Type": "application/json", transport.api_version_header: transport.api_version},
            "authentication_omitted": True, "body": sanitized,
            "request_body_sha256": ContentDigest.from_bytes(raw).hex_digest, "request_body_byte_length": len(raw),
        }
        return raw, {"application_controlled_request": projection, "sanitized_request_sha256": ContentDigest.from_bytes(_json_bytes(projection)).hex_digest}

    def synthesize(self, invocation: SynthesisInvocation) -> SynthesisResult:
        if type(invocation) is not SynthesisInvocation:
            raise SynthesisPreSendFailure(SynthesisFailureEvidence(
                SubmissionEvidence.DEFINITELY_NOT_SENT, (), (), None, None, "invocation_invalid"
            ))
        submission, reason = SubmissionEvidence.DEFINITELY_NOT_SENT, None
        bundle, response_digest, request_digest = {}, None, None
        event_kinds, summaries, timings, pcm = [], [], [], bytearray()
        usage, usage_receipt, wav = None, None, None
        try:
            raw, bundle = self._request(invocation)
            request_digest = ContentDigest.from_bytes(raw)
        except Exception:
            reason = "invocation_invalid"
        if reason is None:
            event_kinds.append(ProviderEventKind.REQUEST)
            try:
                outcome = self._transport.stream(request_body=raw, credentials=self._credentials)
            except CartesiaCredentialUnavailable:
                reason = "credential_unavailable"
            except Exception:
                submission, reason = SubmissionEvidence.AMBIGUOUS, "provider_transport_exception"
            else:
                response_digest = response_evidence_digest(outcome)
                bundle.update(http_status=outcome.http_status, stream_complete=outcome.stream_complete,
                              response_evidence_sha256=response_digest.hex_digest)
                if outcome.submission is TransportSubmissionCertainty.DEFINITELY_NOT_SENT:
                    submission = SubmissionEvidence.DEFINITELY_NOT_SENT
                elif outcome.reason_code in ("http_redirect", "http_client_error"):
                    submission = SubmissionEvidence.STARTED
                else:
                    submission = SubmissionEvidence.AMBIGUOUS
                reason = outcome.reason_code
                terminator = None
                try:
                    for frame in outcome.frames:
                        summary = {"byte_length": len(frame.data), "sha256": ContentDigest.from_bytes(frame.data).hex_digest}
                        summaries.append(summary)
                        if terminator is not None:
                            _invalid()
                        value = _parse_frame(frame, invocation.attempt_id.value)
                        kind = value["type"]
                        summary.update(type=kind, status_code=value["status_code"])
                        if "context_id" in value:
                            summary["context_matches"] = value["context_id"] == invocation.attempt_id.value if value["context_id"] is not None else None
                        if kind == "chunk":
                            decoded = base64.b64decode(value["data"], validate=True)
                            if len(pcm) + len(decoded) > CARTESIA_TRANSPORT_CONTRACT.maximum_decoded_pcm_bytes:
                                raise _ProtocolFailure("decoded_pcm_limit")
                            pcm.extend(decoded)
                            summary["decoded_byte_length"] = len(decoded)
                            event_kinds.append(ProviderEventKind.AUDIO)
                        elif kind in ("timestamps", "phoneme_timestamps"):
                            timings.append(value)
                            event_kinds.append(ProviderEventKind.TIMING)
                            if kind == "phoneme_timestamps":
                                raise _ProtocolFailure("unexpected_phoneme_timestamps")
                        else:
                            terminator = kind
                            if kind == "error":
                                event_kinds.append(ProviderEventKind.ERROR)
                    if reason is None:
                        if not outcome.stream_complete or terminator is None:
                            raise _ProtocolFailure("provider_terminal_missing")
                        if terminator == "error":
                            submission, reason = SubmissionEvidence.COMPLETED, "provider_terminal_error"
                        elif not pcm or len(pcm) % 2:
                            raise _ProtocolFailure("invalid_pcm_samples")
                        else:
                            submission = SubmissionEvidence.COMPLETED
                except _ProtocolFailure as error:
                    if reason is None:
                        submission, reason = SubmissionEvidence.AMBIGUOUS, str(error)
                except Exception:
                    if reason is None:
                        submission, reason = SubmissionEvidence.AMBIGUOUS, "provider_payload_invalid"
                if reason is None:
                    try:
                        record = None if self._usage_source is None else self._usage_source.lookup(request_digest, response_digest)
                        if (type(record) is CartesiaAuthoritativeUsage and record.request_body_digest == request_digest and
                            record.response_evidence_digest == response_digest and type(record.usage) is NonNegativeDecimal):
                            usage = record.usage
                            usage_receipt = AuthoritativeUsageReceipt(
                                record.request_body_digest, record.response_evidence_digest, record.usage
                            )
                        if usage is None:
                            reason = "authoritative_usage_unavailable"
                        else:
                            event_kinds.append(ProviderEventKind.USAGE)
                            wav = encode_canonical_pcm16_wav(bytes(pcm), invocation.contract.audio)
                    except Exception:
                        submission, reason = SubmissionEvidence.AMBIGUOUS, "provider_completion_encoding_failed"
        bundle["provider_frames"] = summaries
        return self._publish_outcome(invocation, bundle, event_kinds, timings, bytes(pcm),
                                     submission, reason, usage, wav, request_digest, response_digest, usage_receipt)

    def _publish_outcome(self, invocation, bundle, kinds, timings, pcm, submission, reason, usage, wav, request_digest, response_digest, usage_receipt):
        publications = []
        sanitized = timing = partial = None
        observed = self._clock.now()
        prefix = f"evidence/cartesia/{invocation.attempt_id.value}/"
        try:
            sanitized = self._artifacts.publish(SafeRelativeArtifactPath(prefix + "sanitized.json"), _json_bytes(bundle), "application/json", observed)
            publications.append(sanitized)
            if timings:
                timing = self._artifacts.publish(SafeRelativeArtifactPath(prefix + "timestamps.json"), _json_bytes(timings), "application/json", observed)
                publications.append(timing)
        except Exception:
            reason = "evidence_publication_failed"
            if submission is not SubmissionEvidence.DEFINITELY_NOT_SENT:
                submission = SubmissionEvidence.AMBIGUOUS
        if sanitized is not None and submission is SubmissionEvidence.AMBIGUOUS and pcm:
            try:
                partial = self._artifacts.publish(SafeRelativeArtifactPath(prefix + "partial.pcm"), pcm, "audio/pcm", observed)
                publications.append(partial)
            except Exception:
                reason = "evidence_publication_failed"
        terminal = (ProviderTerminalClass.SUCCESS if reason is None else
                    ProviderTerminalClass.DEFINITE_PRE_SEND_FAILURE if submission is SubmissionEvidence.DEFINITELY_NOT_SENT else
                    ProviderTerminalClass.AMBIGUOUS if submission is SubmissionEvidence.AMBIGUOUS else ProviderTerminalClass.FAILURE)
        events = []
        if sanitized is not None:
            for kind in [*kinds, ProviderEventKind.TERMINAL]:
                events.append(ProviderEventEvidence(
                    self._identifiers.new_id(ProviderEventId), len(events), kind, sanitized.reference, sanitized.reference.content_digest, observed,
                    None if request_digest is None else request_digest.hex_digest,
                    None if response_digest is None else response_digest.hex_digest,
                    partial.reference if partial is not None and kind is ProviderEventKind.TERMINAL else None,
                    timing.reference if timing is not None and kind is ProviderEventKind.TIMING else None,
                    usage.value if usage is not None and kind is ProviderEventKind.USAGE else None,
                    terminal if kind in (ProviderEventKind.TERMINAL, ProviderEventKind.ERROR) else None,
                ))
        timing_ref = None if timing is None else timing.reference
        if reason is None:
            return SynthesisResult(tuple(events), wav, tuple(publications), timing_ref, usage)
        failure = (SynthesisPreSendFailure if submission is SubmissionEvidence.DEFINITELY_NOT_SENT else
                   SynthesisAmbiguousFailure if submission is SubmissionEvidence.AMBIGUOUS else SynthesisSubmittedFailure)
        raise failure(SynthesisFailureEvidence(
            submission, tuple(events), tuple(publications), timing_ref, usage, reason, usage_receipt
        )) from None
