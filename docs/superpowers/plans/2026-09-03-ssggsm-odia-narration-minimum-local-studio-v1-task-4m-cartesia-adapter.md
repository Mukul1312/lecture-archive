# SSGGSM Odia Narration Minimum Local Studio v1 — Task 4M Cartesia Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Execution handoff:** This plan was prepared on 2026-09-03 for execution in a
> new Codex chat. Do not implement Task 4M in the chat that created this document.

**Goal:** Add one minimum, sequential Cartesia Odia recipe/compiler and synthesis adapter behind the existing Narrator Voice application ports, retaining exact request/audio/evidence truth and making no live provider call during implementation.

**Architecture:** Keep HTTPX, SSE and safe-XML mechanics in `heritage_archive.platform.cartesia`, which never imports a bounded context. Keep Cartesia-to-Narrator-Voice translation in `contexts.narrator_voice.infrastructure`; it implements application-owned ports and never changes aggregate policy. Reuse the existing generation handler, authorization checks, durable budget ledger, attempt workspaces, immutable artifact store and canonical WAV inspection.

**Tech Stack:** Python 3.11, HTTPX 0.28.1, defusedxml 0.7.1, standard-library `json`, `decimal`, `threading` and `wave`, and `unittest`. Do not use the Cartesia SDK, `httpx-sse`, FFmpeg, a generic provider framework or a live Cartesia test.

**Spec:** [Cartesia Odia narration minimum local-studio design — v4](../specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md)

**Authority:** [ADR-0010](../../decisions/0010-cartesia-prompting-is-validated-rendering-evidence.md) and [ADR-0012](../../decisions/0012-narrator-voice-v1-is-a-minimum-local-studio.md)

**Prerequisite:** [Task 3M](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-3m-durable-filesystem-audio.md) is complete and smoke-verified through checkpoint `6ba05b0`; its deferred hardening gate remains open.

## New-chat start protocol

1. Work in `C:\Users\Mukul\code\personal-projects\voice-cloning\.worktrees\narrator-voice-production-v1` on `feature/narrator-voice-production-v1`. Do not implement on `main`.
2. Read `AGENTS.md`, ADR-0010, ADR-0012, the v4 design, this plan, `application/ports.py`, the `GenerateTakeHandler` in `application/handlers.py`, and the Plan 3M infrastructure adapters before editing.
3. Run `git status --short` and preserve any unrelated change. At handoff, Task 3M's tracked checkpoint is clean; never stage private/local files accidentally.
4. Use a task implementer followed by one focused reviewer. Keep progress visible and use the minimum focused test set for each slice.
5. Do not make a live/paid/private Cartesia request. Documentation access is allowed; provider API access requires a later explicit operator approval after the pre-live hardening gate.

## Global constraints

- Lane B remains the authorized SSGGSM Odia diary voice; Lane C remains the separate Odia introduction voice. One job has one fixed voice and the adapter never accepts an arbitrary voice override.
- `CARTESIA_API_KEY` remains environment-only. Private voice/dictionary identifiers stay in the external production root and never enter Git, sanitized evidence, test fixtures or browser-facing values.
- The dated endpoint/model/API/capability contract is verified against official Cartesia documentation before code is frozen. If the documented Odia route, model or required output capability is no longer supported, stop and ask the operator instead of silently substituting a model or language.
- Canonical passage text is NFC Odia without provider markup. Advanced source is an allowlisted authoring input, not a free-form prompt or policy override.
- Previewed and transmitted transcript UTF-8 bytes must be identical. Decimal strings become JSON numbers only at the provider boundary.
- Output is raw PCM16 little-endian, mono, 44,100 Hz, wrapped once into canonical WAV and then re-inspected by the existing `CanonicalWavInspector`.
- One Cartesia request may be in flight at a time. Bounded retry must never replay an ambiguous request.
- Raw timestamps may be preserved as private, untrusted evidence. Plan 4M does not normalize, display or claim trustworthy word timing.
- No automated test contacts Cartesia or consumes credits. Use sanitized fixtures and HTTPX mock transports only.
- Do not add another aggregate, repository, workflow engine, event store, provider abstraction, background worker, website or generation command to the existing offline CLI.
- Record `implemented`, `smoke-verified` and `hardened` separately. Plan 4M may finish smoke-verified; the named pre-live hardening gate remains required before a real request.

## Current integration findings

The existing `RecipeCompiler` already owns authoring validation and exact preview compilation. The existing `SynthesisGateway` returns provider events, canonical WAV bytes, raw timing references and usage. `GenerateTakeHandler` already owns authorization rechecks, budget reservation/finalization, attempt state, immutable audio publication, WAV inspection and take completion.

Only these narrow seams must change:

1. The gateway needs the generation attempt ID and complete fixed release contract in addition to `EffectiveSynthesisInput` so it can bind Cartesia `context_id`, model and private voice correctly.
2. Expected gateway failures must carry already-published sanitized evidence, partial PCM/timing references, known usage and submission certainty; current bare exceptions discard those facts.
3. The handler must persist frozen-input and external-work-started workspace evidence before transmission.
4. Provider/timing evidence must retain full `PublishedArtifact` paths in the attempt workspace rather than leave unresolvable `ArtifactRef` values.
5. The private raw-PCM WAV encoder must become one public context infrastructure operation rather than being duplicated.
6. A concrete fixed Lane-B/Lane-C release-policy resolver must bind private configuration to the immutable contract. The present local profile needs stable `voice_binding`, `authorization_record_id` and per-lane initial delivery defaults; it must not duplicate authorization status.

---

### Task 1: Verify and freeze the provider contract and dependency boundary

**Files:**

- Modify: `pyproject.toml`
- Create: `docs/cartesia-odia-tts-contract-snapshot.md`
- Create: `src/heritage_archive/platform/cartesia/__init__.py`
- Create: `src/heritage_archive/platform/cartesia/contract.py`
- Create: `tests/heritage_archive/platform/test_cartesia_contract.py`
- Modify: `tests/heritage_archive/test_architecture.py`

**Interfaces:**

- Produces `CartesiaTransportContract`, a frozen platform value containing only verified provider protocol facts: HTTPS origin, SSE path, API version header/value, authentication header name, timeout values, retry count/backoff, event/audio size limits and allowed redirect/proxy behavior.
- Provider model, language, lane, voice, dictionary and narration defaults remain Narrator Voice policy and do not enter the generic platform contract.

```python
@dataclass(frozen=True, slots=True)
class CartesiaTransportContract:
    origin: str
    sse_path: str
    api_version: str
    authentication_header: str
    connect_timeout_seconds: int
    write_timeout_seconds: int
    read_timeout_seconds: int
    operation_timeout_seconds: int
    maximum_submissions: int
    retry_backoff_seconds: tuple[int, ...]
    maximum_retry_after_seconds: int
    maximum_event_bytes: int
    maximum_response_bytes: int
    maximum_decoded_pcm_bytes: int
```

- [ ] Use official `docs.cartesia.ai` pages only to verify the current SSE endpoint, authentication header, dated API version, Sonic model ID, `language=or`, raw PCM format, sample rate, timestamps, dictionary request field, supported markup and usage/billing semantics. Record direct URLs, access date and the accepted values in `docs/cartesia-odia-tts-contract-snapshot.md`.
- [ ] Retain the existing candidate values only when official documentation confirms them: `/tts/sse`, `Cartesia-Version: 2026-08-14`, `sonic-3.6-2026-08-27`, `language=or`, raw `pcm_s16le` at 44,100 Hz, timestamps enabled, phonemes disabled and normalization disabled. Stop for operator direction if any load-bearing value is unavailable or incompatible.
- [ ] Add a pinned `narrator` optional dependency group containing exactly `httpx==0.28.1` and `defusedxml==0.7.1`; do not add an SDK or a second SSE library.
- [ ] Add focused contract tests for HTTPS-only origin, relative SSE path, positive bounded limits, exactly three or fewer submissions, and redirects/proxy inheritance disabled by construction.
- [ ] Extend the architecture characterization only as needed to prove third-party imports remain in `platform/cartesia` and the platform still cannot import `contexts`.
- [ ] Run `tests.heritage_archive.platform.test_cartesia_contract` and `tests.heritage_archive.test_architecture`, then commit the exact Task 1 files locally.

### Task 2: Close the application invocation and evidence seam

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/application/ports.py`
- Create: `src/heritage_archive/contexts/narrator_voice/application/synthesis_failures.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/handlers.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/domain/evidence.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/pcm_audio.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_evidence.py`
- Modify: `tests/heritage_archive/narrator_voice/fakes.py`
- Modify: `tests/heritage_archive/narrator_voice/test_application_generation.py`
- Modify: `tests/heritage_archive/narrator_voice/test_application_recovery.py`
- Modify: `tests/heritage_archive/narrator_voice/test_pcm_audio.py`
- Modify: `tests/heritage_archive/narrator_voice/test_filesystem_evidence.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SynthesisInvocation:
    attempt_id: GenerationAttemptId
    contract: ReleaseSynthesisContract
    effective_input: EffectiveSynthesisInput

@dataclass(frozen=True, slots=True)
class SynthesisFailureEvidence:
    submission: SubmissionEvidence
    events: tuple[ProviderEventEvidence, ...]
    publications: tuple[PublishedArtifact, ...]
    raw_timing_reference: ArtifactRef | None
    usage: NonNegativeDecimal | None
    reason_code: str

@dataclass(frozen=True, slots=True)
class SynthesisResult:
    events: tuple[ProviderEventEvidence, ...]
    canonical_wav_bytes: bytes
    evidence_publications: tuple[PublishedArtifact, ...]
    raw_timing_reference: ArtifactRef | None
    usage: NonNegativeDecimal

class SynthesisGateway(Protocol):
    def synthesize(self, invocation: SynthesisInvocation) -> SynthesisResult: ...
```

- Produces `SynthesisPreSendFailure`, `SynthesisAmbiguousFailure` and `SynthesisSubmittedFailure`, each carrying one immutable `SynthesisFailureEvidence` while retaining the existing application meanings: definitely not sent, ambiguous after possible send, and definitive submitted failure.
- Produces `encode_canonical_pcm16_wav(raw_pcm: bytes, audio: CanonicalAudioFacts) -> bytes` in `pcm_audio.py`.

- [ ] Add focused tests proving an invocation binds the attempt, complete release contract and effective input; contract digest mismatch is rejected before the gateway is called.
- [ ] Add focused tests proving success and all three expected failure categories retain contiguous provider events, immutable evidence publications, one combined raw-timing reference when present, known usage and sanitized reason codes.
- [ ] Require every `ProviderEventEvidence` raw/PCM/timing reference to resolve to exactly one returned immutable evidence publication with the same artifact identity, digest, byte length and media type.
- [ ] Change `GenerateTakeHandler` to save an `INPUT_FROZEN` workspace after freezing the aggregate input, then an `EXTERNAL_WORK_STARTED` workspace immediately before calling the gateway. Keep `submission=NOT_STARTED` at this pre-call durability boundary; a crash after this boundary is conservatively reconciled, never treated as proof that nothing was sent.
- [ ] Update and test `_workspace_evidence_stage()` so this pre-call workspace is derived as `EXTERNAL_WORK_STARTED` from its explicit workspace state even while `submission=NOT_STARTED`; do not let recovery misreport it as merely `INPUT_FROZEN`.
- [ ] Pass `SynthesisInvocation(attempt_id, job.contract, effective_input)` to the gateway. Catch evidence-bearing failures, persist their publications/events before budget finalization, and preserve legacy empty-evidence behavior only for existing test doubles.
- [ ] Make budget disposition explicit and test it at this boundary: a definitely-not-sent failure releases the reservation; an ambiguous or unexpected post-boundary failure holds it and leaves the attempt unknown; a definitive submitted failure with authoritative usage settles the reservation and fails the attempt; and a definitive submitted failure without authoritative usage holds the reservation while recording the failed attempt for reconciliation.
- [ ] Add a final defensive catch for an unexpected exception escaping after the external-work boundary: persist an `UNKNOWN` workspace with a sanitized internal reason code, hold budget and never expose exception text as provider evidence.
- [ ] Permit a generation workspace to contain provider evidence publications plus exactly one selected canonical audio publication. Update completion binding to require that the canonical audio publication occurs exactly once rather than requiring it to be the workspace's only publication.
- [ ] Update `FilesystemArtifactEvidenceVerifier.verify()` and `recover_media()` for that multi-publication model. Recovery must resolve the requested canonical audio publication by exact identity, require it exactly once, verify all workspace publications and their staging bindings, and reject zero/multiple matching audio publications; it must not require `published_artifacts == (audio_artifact,)`.
- [ ] Make the existing PCM encoder public and prove it writes the exact canonical RIFF/WAVE header and unmodified even-length PCM payload. Do not move HTTPX or Cartesia DTOs into this module.
- [ ] Run the affected generation/recovery/audio tests and architecture guard, then commit the exact Task 2 files locally.

### Task 3: Implement the safe hybrid recipe compiler

**Files:**

- Create: `src/heritage_archive/platform/cartesia/markup.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/cartesia_recipe.py`
- Create: `tests/heritage_archive/platform/test_cartesia_markup.py`
- Create: `tests/heritage_archive/narrator_voice/test_cartesia_recipe.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ParsedMarkupAnnotation:
    kind: str
    start_scalar: int
    end_scalar: int
    value: str

@dataclass(frozen=True, slots=True)
class MarkupTagCapability:
    tag: str
    attributes: tuple[str, ...]
    may_contain_text: bool
    may_contain_children: bool

@dataclass(frozen=True, slots=True)
class CartesiaMarkupCapability:
    identity: str
    tags: tuple[MarkupTagCapability, ...]

@dataclass(frozen=True, slots=True)
class ParsedMarkupFragment:
    canonical_projection: str
    annotations: tuple[ParsedMarkupAnnotation, ...]

def parse_safe_markup_fragment(
    source: str,
    capability: CartesiaMarkupCapability,
) -> ParsedMarkupFragment: ...

class CartesiaRecipeCompiler(RecipeCompiler):
    def compile_recipe(self, request: RecipeAuthoringRequest) -> RecipeAuthoringResult: ...
    def compile(self, request: RecipeCompileRequest) -> PreviewCompilerResult: ...
```

- [ ] Use `defusedxml` by wrapping the advanced fragment in one internal root. Reject XML declarations, DTDs, entities, comments, processing instructions, unknown tags/attributes, unsupported nesting and invalid numeric values before creating a domain recipe.
- [ ] Implement only the verified provider syntax corresponding to the existing domain controls: `BreakControl`, `SpeedControl`, `VolumeControl` and `SpellingControl`. Emotion remains request-level for the initial Odia workflow; reject inline emotion markup.
- [ ] Enforce the existing limits: 16,384 advanced-source UTF-8 bytes, 64 controls total, 16 per family, 16 breaks of 10–5,000 ms with at most 20,000 ms total, and spelling spans of at most 64 Unicode scalar values without nested spelling.
- [ ] Build a Unicode-scalar projection from parsed text nodes and require exact equality with `PassageText.value`, including punctuation and normalization. A lexical change must fail validation and be made as a passage text revision instead.
- [ ] Compile structured controls and equivalent advanced source into the same sorted `PassageRenderRecipe`. Render deterministic provider markup from canonical text plus that recipe; the same input and capability snapshot must produce identical UTF-8 bytes and digest.
- [ ] Reject crossing or overlapping inline spans across control families in v1 (breaks may occur only at unambiguous scalar boundaries). The domain can represent richer overlap, but the Cartesia compiler must not invent XML nesting or split controls unless the verified capability snapshot defines one deterministic equivalent.
- [ ] Keep whole-request speed, volume, emotion and dictionary out of inline markup. Return them only through the frozen request configuration represented by `EffectiveTakeSettings` and `ReleaseSynthesisContract`.
- [ ] Compute billable characters and estimated usage using the dated billing rule recorded by Task 1. Return the exact rendered transcript, canonical projection, endpoint, timestamp/normalization flags, compiler/capability identity and warnings through the existing preview result.
- [ ] Smoke-test one plain Odia passage, one structured recipe, one equivalent advanced recipe, one lexical substitution rejection, one entity/DTD rejection, and deterministic exact UTF-8 output. Do not add a broad fuzz matrix.
- [ ] Run the two Task 3 modules plus narration preview/recipe tests and architecture guard, then commit the exact Task 3 files locally.

### Task 4: Implement bounded HTTPX SSE transport

**Files:**

- Create: `src/heritage_archive/platform/cartesia/sse.py`
- Create: `src/heritage_archive/platform/cartesia/transport.py`
- Create: `tests/heritage_archive/platform/test_cartesia_sse.py`
- Create: `tests/heritage_archive/platform/test_cartesia_transport.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SseFrame:
    event: str | None
    data: bytes

class TransportSubmissionCertainty(str, Enum):
    DEFINITELY_NOT_SENT = "definitely_not_sent"
    SENT = "sent"
    AMBIGUOUS = "ambiguous"

@dataclass(frozen=True, slots=True)
class CartesiaTransportOutcome:
    frames: tuple[SseFrame, ...]
    http_status: int | None
    submission: TransportSubmissionCertainty
    stream_complete: bool
    reason_code: str | None
    retry_after_seconds: int | None

class CartesiaCredentialSupplier(Protocol):
    def read_for_transmission(self) -> str: ...

class CartesiaSseTransport:
    def stream(
        self,
        *,
        request_body: bytes,
        credentials: CartesiaCredentialSupplier,
    ) -> CartesiaTransportOutcome: ...
```

- [ ] Implement incremental SSE framing over byte chunks: support LF and CRLF, blank-line dispatch, multiple `data:` lines and comment lines. Decode each completed frame as strict UTF-8 so an Odia/multibyte code point split across HTTP chunks remains valid.
- [ ] Reject invalid UTF-8, malformed fields, an unterminated final frame, events over 1 MiB and a total HTTP/SSE response beyond the verified bounded response limit. Preserve exact sanitized frame bytes for the context adapter; never retain the credential header. The JSON-agnostic transport does not attempt to count decoded audio bytes.
- [ ] Construct one `httpx.Client` with `trust_env=False`, redirects disabled and the Task 1 timeout contract. Use the verified fixed HTTPS origin/path and ask the credential supplier for the environment API key immediately before each authorized transmission; neither the transport nor gateway retains it after the request.
- [ ] Serialize no JSON in the transport. It accepts already-frozen request bytes and returns provider frames; it does not know Odia passages, lanes, jobs, voices, recipes or aggregates.
- [ ] Return an evidence-bearing `CartesiaTransportOutcome` for every expected HTTP/stream result, including failure: preserve all completed sanitized frames, HTTP status, submission certainty, completion state, bounded `Retry-After` and a stable reason code. This gives the gateway enough evidence to classify partial streams and budget disposition without parsing exception text. Unexpected programming exceptions may still escape for the handler's defensive unknown path.
- [ ] Serialize all calls through one process-local lock. A second caller waits; it does not create a second provider request.
- [ ] Default to one submission. Permit up to three submissions with 1-second then 3-second backoff only for a connection failure proven to occur before any request bytes were sent. Retry HTTP 429 or HTTP 5xx only if Task 1 records an authoritative Cartesia guarantee that the request was not processed, or a documented idempotency mechanism that prevents duplicate synthesis and charging; otherwise classify it as sent/ambiguous and do not replay. Honor `Retry-After` only on a safely retryable outcome and cap it at 30 seconds. Never retry provider SSE errors, write/read timeouts, truncated responses, partial audio or any other ambiguous send.
- [ ] Use HTTPX mock transport fixtures to prove normal split/multibyte SSE, definitely-pre-send retry then success, conservative 429/5xx classification under the verified contract, redirect rejection, timeout classification, truncation, partial-frame retention and absence of credentials from returned/debug evidence.
- [ ] Run the two Task 4 test modules and architecture guard, then commit the exact Task 4 files locally.

### Task 5: Implement the Narrator Voice gateway, fixed policies and evidence bundle

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/cartesia_gateway.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/cartesia_policy.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/operations.py`
- Create: `src/heritage_archive/composition_root/narrator_voice_live.py`
- Create: `tests/heritage_archive/narrator_voice/test_cartesia_gateway.py`
- Create: `tests/heritage_archive/narrator_voice/test_cartesia_policy.py`
- Modify: `tests/heritage_archive/narrator_voice/test_operations.py`
- Create: `tests/heritage_archive/narrator_voice/test_cartesia_generation_integration.py`

**Interfaces:**

```python
class CartesiaSynthesisGateway(SynthesisGateway):
    def synthesize(self, invocation: SynthesisInvocation) -> SynthesisResult: ...

class ConfiguredNarrationReleasePolicyResolver(NarrationReleasePolicyResolver):
    def resolve_lane_b_diary(self) -> ReleasePolicyResolution: ...
    def resolve_lane_c_intro(self, intended_episode_id: DiaryEpisodeId) -> ReleasePolicyResolution: ...
```

- [ ] Extend private `LocalStudioVoiceProfile` schema with stable `voice_binding`, typed `authorization_record_id`, and explicit initial speed, volume and optional emotion. Preserve separate `opaque_provider_voice_reference` and dictionary binding. Do not store authorization status/evidence or the API key in this configuration.
- [ ] Before changing the private configuration schema, run the report-only `doctor` against `CARTESIA_NARRATION_ROOT` when that variable is configured. If no production configuration exists, write the new strict schema directly and update focused fixtures. If an older real configuration exists, stop and request approval for an explicit migration; never silently reinterpret it.
- [ ] Configure Lane B with the accepted editable starting defaults `speed=0.90`, `volume=1.00`, `emotion=calm`. Require Lane C defaults explicitly from private initialization rather than assuming they match Lane B.
- [ ] Implement fixed release-policy resolution from the verified public Cartesia contract plus private lane configuration. Lane B must reject an episode binding; Lane C must bind exactly the intended episode. Neither resolver may query or copy mutable authorization status.
- [ ] Validate every invocation before I/O: the complete contract digest equals `effective_input.contract_digest`; lane, provider, language, model, API/capability snapshot, canonical audio and voice match the fixed release contract; the frozen `EffectiveTakeSettings` dictionary binding/digest matches the configured lane policy; and `rendered_transcript.encode("utf-8")` matches its frozen byte length and digest.
- [ ] Build one deterministic UTF-8 JSON body with `ensure_ascii=False` and compact separators. Convert validated decimal strings to JSON numbers only here. Use `attempt_id.value` as `context_id`; obtain the voice reference from the invocation's fixed contract and the dictionary reference from its frozen effective settings after the lane-policy validation above.
- [ ] Hash the complete sanitized request body and headers after removing the credential and replacing private provider identifiers with their immutable bindings/digests. Publish one sanitized provider-evidence bundle at an attempt-addressed safe path through `FilesystemArtifactStore`.
- [ ] Parse the fixture SSE vocabulary into contiguous `ProviderEventEvidence`. Normalize every completed stream to exactly one final `ProviderEventKind.TERMINAL` event; an SSE error event is evidence but never the final domain event by itself.
- [ ] Decode and concatenate audio chunks without transformation while enforcing the contract's decoded-PCM byte limit, preserve partial PCM as evidence on ambiguous failure, and call `encode_canonical_pcm16_wav` exactly once only for terminal success. Combine all raw timestamp frames into one private JSON evidence artifact and expose one reference; do not normalize them.
- [ ] Return actual provider usage when present. Map every HTTP, timeout, parse, encoding, storage and provider terminal outcome into success or one of the three evidence-bearing failure types. No unclassified provider exception may escape the adapter.
- [ ] Add a separate live construction function for Task 5M that wires an environment-backed `CartesiaCredentialSupplier` and the existing durable adapters. The supplier reads `CARTESIA_API_KEY` only at the moment of an authorized transmission; construction must not read, retain or validate the secret. Do not modify `narrator_voice_cli.py` or add a generation CLI command.
- [ ] Run gateway, policy, operations and generation-integration fixture tests plus affected application/recovery and architecture checks. The integration test must execute preview → reserve → fake SSE gateway → canonical WAV inspection → immutable publication → completed take without network.
- [ ] Commit the exact Task 5 files locally after one focused review.

### Task 6: Plan 4M smoke checkpoint and new-session handoff

**Files:**

- Modify: this plan's checkboxes/status only after evidence exists
- Modify: `README.md` only if the optional dependency or operator setup command changed

- [ ] Run the new platform Cartesia contract/markup/SSE/transport modules, Cartesia recipe/gateway/policy/integration modules, affected narration preview/generation/recovery tests, Plan 3 durable evidence/audio tests and architecture guard once.
- [ ] Run the package build/import check using the narrator optional dependencies and exercise only `--help`/construction with a fake key and mock transport. Do not contact the provider endpoint.
- [ ] Run `git diff --check` and inspect the exact staged paths for API keys, private voice/dictionary IDs, authorization evidence, private Odia text, raw provider data and audio.
- [ ] Record Task 4M as `implemented` and `smoke-verified`, not `hardened`. Preserve the deferred pre-live gate: restart windows around send/evidence/finalization, retry fault injection, provider contract revalidation and one explicitly approved capped live passage.
- [ ] Make one local Task 4M checkpoint commit and do not push, merge, publish or perform a live request.

## Focused completion criteria

Task 4M is smoke-complete when:

- structured and allowlisted advanced recipes compile to deterministic, lexically identical Odia provider transcript bytes;
- a frozen invocation binds attempt ID, complete fixed lane contract and exact synthesis input;
- the HTTP/SSE mechanics remain context-neutral and all Cartesia mapping remains outside domain/application;
- Lane B and Lane C cannot exchange voices, authorization bindings, defaults or episode scope;
- a normal fixture stream produces one canonical WAV that the existing inspector accepts and the existing handler stores as an immutable take;
- all expected and unexpected post-boundary failures persist the strongest available sanitized evidence and become blocked, failed or unknown without unsafe replay;
- one request-at-a-time and bounded retry rules are enforced;
- raw timestamps remain private untrusted evidence rather than published timing truth;
- focused tests and architecture checks pass without network or credits; and
- no credentials, private IDs, private text, raw evidence or generated audio are tracked.

## Deferred pre-live hardening

Before the first real Cartesia request, revalidate the official contract, exercise representative crashes before/after send and evidence publication, verify retry/`Retry-After` behavior under faults, rerun Plan 3 storage/budget/recovery/audio/backup gates, inspect the private configuration, set explicit caps, and obtain the operator's separate approval for one tightly capped passage. This deferred work is a release gate, not part of the Plan 4M smoke checkpoint.
