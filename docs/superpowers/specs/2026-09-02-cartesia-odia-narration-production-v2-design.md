# Cartesia SSGGSM Odia narration production design — v2

**Date:** 2026-09-02

**Status:** **Superseded for implementation by the
[2026-09-02 v3 design](2026-09-02-cartesia-odia-narration-production-v3-design.md).**

This file is retained as the historical Lane-B-only proposal. ADR-0010 and ADR-0011
add the accepted hybrid Cartesia authoring, narrow Odia-intro, dry episode-composition
and timed-narration boundaries without weakening ADR-0008's fixed-voice job.

**Authority:** [ADR-0006](../../decisions/0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md),
[ADR-0007](../../decisions/0007-two-policy-isolated-narration-lanes.md) and
[ADR-0008](../../decisions/0008-lane-b-production-boundaries.md) govern. This design
supersedes the workflow/model in the
[2026-08-31 v1 design](2026-08-31-cartesia-odia-narration-production-design.md), which
is retained as historical research. It does not authorize implementation, provider
calls or publication.

## 1. Outcome

Build a private, resumable production system that takes a reviewed Odia diary and
produces a reviewable narration with the already approved SSGGSM Cartesia Instant
Voice Clone. The normal journey is:

```text
prepare exact Odia text
  → estimate cost
  → generate preserved takes
  → listen/review each passage
  → select one operationally accepted take per passage
  → assemble without changing speech
  → listen to the whole master
  → retain reproducible evidence
```

The system begins as a localhost website for one operator. When publishing becomes a
real stage, a qualified Odia reviewer receives a login-based, review-only interface
over the same application use cases.

The locked baseline and adjustable delivery defaults are:

```yaml
lane: ssggsm-odia-diary
provider: cartesia
voice: approved-private-ssggsm-ivc-reference
language: or
model_snapshot: sonic-3.6-2026-08-27
canonical_audio: wav-pcm-s16le-44100hz
# channel layout is chosen and frozen by the implementation plan

delivery_defaults:
  speed: 0.90
  volume: 1.00
  emotion: calm
  pronunciation_dictionary: configured-private-binding
```

`speed`, `volume`, `emotion` and dictionary selection remain reviewable controls, not
global locks. The speaker, voice, language, dated model/API contract and canonical
format cannot drift silently within a job.

## 2. Scope

### In the first production version

- exact NFC Odia diary preparation and ordered passage management;
- local character/credit preflight and hard generation caps;
- one new immutable take per explicit provider generation;
- safe retry/resume without overwriting prior audio;
- passage audition, notes, operational accept/reject and explicit working selection;
- authorization recording/status enforcement;
- deterministic assembly and final-master listening;
- private manifests, hashes, media facts and audit history;
- a loopback-only sole-operator web console; and
- provider isolation behind a synthesis port.

### Outside this version

- clone creation, replacement or Professional Voice Clone training;
- Lane A's non-SSGGSM English/Hindi workflow;
- generic `say --voice --text` or arbitrary-script generation;
- automatic identity, pronunciation, emotion or release approval;
- public hosting, automatic publishing or distribution-rights decisions;
- a remote reviewer before the publishing trigger;
- a database, object-store migration, OAuth service, worker queue, event bus, CQRS or
  event sourcing merely in anticipation of scale; and
- denoising, EQ, music or destructive mastering hidden inside the speech master.

## 3. The model in plain language

### 3.1 Why one `NarrationJob`

A diary is produced and assembled as one ordered whole. To answer “may we build the
master?” the software must know, together:

- the current text and order of every passage;
- every generated take and whether it still matches current text/settings/scope;
- every review and which operationally accepted take was selected; and
- whether one eligible selected take exists for every passage.

That consistency boundary is `NarrationJob`. A passage or take is important, but it
does not need independent transactional ownership in the first one-operator system.

| Considered approach | Result |
|---|---|
| **A. One `NarrationJob` containing passage/take/review/master state** | **Chosen.** One command can enforce master eligibility without coordinating several repositories. |
| **B. Separate Passage and Take aggregates** | Rejected initially. It adds cross-aggregate transactions and partial-selection states before concurrency demonstrates the need. |
| **C. Job plus an immutable take ledger** | Its **storage seam is adopted**, not its second source of truth. Immutable attempt/artifact entries aid recovery and audit while `NarrationJob` remains the decision-making aggregate. |

### 3.2 What the storage seam means

The job snapshot answers “what is true now?” The append-only ledger and immutable
artifact records answer “what happened and which exact bytes resulted?”

```text
application command
   │
   ├─ loads NarrationJob and checks its expected revision
   ├─ asks the aggregate to validate/change current state
   └─ repository publishes together:
        • the new current snapshot
        • immutable audit/attempt entries
        • references to already validated immutable audio
```

The ledger cannot independently approve/select a take or make a master eligible. It
is not replayed to reconstruct the domain and is not an event bus. Audio bytes remain
outside the snapshot.

### 3.3 Domain vocabulary

| Term | Meaning |
|---|---|
| `NarrationJob` | One Lane-B diary production, its passages, takes, review/selection history and masters. |
| `Passage` | Stable passage ID/order plus a revisioned exact NFC text value. |
| `GenerationAttempt` | One budgeted provider-call attempt, including completed, failed or unknown outcome. |
| `Take` | Immutable production result with its own opaque `TakeId`, exact request evidence and one artifact reference. |
| `ArtifactRef` | Safe relative location plus audio SHA-256, size and decoded media facts. SHA identifies bytes, not the take. |
| `ReviewDecision` | Append-only actor-attributed outcome, authority class and notes against an exact take/text revision. Operational audition is distinct from qualified-Odia publishing approval. |
| `SelectionDecision` | Append-only working choice of a current, eligible, operationally accepted take for a passage. |
| `Master` | Immutable assembly facts/artifact for selected takes and explicit gap settings. Later listening decisions are separate append-only job records referencing `MasterId`. |
| `AuthorizationRecord` | Separate aggregate containing the steward-recorded permission history and current effective scope/status. |
| `AuthorizationSnapshot` | Immutable facts observed from the authorization record and bound to a job/take/operation. |
| `ActorId` | Stable server-resolved identity of the human responsible for a decision. |

## 4. Aggregate boundaries and invariants

```text
Narrator Voice context
├── NarrationJob aggregate
│   ├── passages / attempts / takes
│   ├── reviews / selections
│   └── masters / listening decisions
├── AuthorizationRecord aggregate
└── ports
    ├── job repository + immutable ledger/artifact store
    ├── authorization repository/status reader
    ├── synthesis provider
    ├── media inspector/assembler
    ├── clock/actor resolver
    └── review/status presenters
```

The two aggregates are not updated in one cross-aggregate transaction. An application
handler reads current authorization at each protected boundary, records the observation
and then changes the job. If authorization changes concurrently, the conservative
eligibility and quarantine rules apply; history is never rewritten to pretend the race
did not occur.

The accepted invariant catalogue is ADR-0008 §3 (`INV-NJ-1` through `INV-NJ-9` and
`INV-AR-1` through `INV-AR-2`). This proposal adds two candidates that become
implementation/test obligations only when this design is accepted:

| Proposed ID | Additional invariant |
|---|---|
| `INV-NJ-10` | A job's `AuthorizationRecordId` binding is immutable. Withdrawal permanently blocks that job; a later grant requires a new job rather than silent rebinding. |
| `INV-AR-3` | A narrowed or withdrawn historical grant cannot be widened/reactivated in place; later permission creates a new attested grant/record. |

Tests and enforcement sites cite the final accepted IDs.

Three distinctions are essential:

1. `TakeId` identifies a production event; SHA-256 identifies bytes.
2. **Text-stale** means the passage text revision no longer matches.
3. **Ineligible** means current contract, dictionary or authorization rules do not
   permit selection/assembly even though the historical take remains valid evidence.

## 5. Synthesis configuration

### 5.1 `ReleaseSynthesisContract`

One immutable contract is created with the job and contains:

- Lane-B identity and authorized speaker/voice binding;
- `language=or`;
- provider and dated model snapshot;
- exact API/request-schema version once the implementation adapter is selected; and
- canonical WAV/PCM output contract, including a channel layout selected during the
  implementation plan.

The manifest stores private opaque provider/voice references or digests, never the
secret API key. Changing speaker, voice, language, model/API snapshot or canonical
format requires a new release contract and therefore a new job, not a casual
per-passage override.

### 5.2 `DeliveryControlDefaults`

Defaults resolve settings for **future** takes:

- speed `0.90`;
- volume `1.00`;
- emotion `calm`; and
- a default immutable pronunciation-dictionary binding.

They may change as production listening improves. A change affects only subsequently
resolved take requests and never reinterprets or invalidates old evidence by itself.

### 5.3 `EffectiveTakeSettings`

Every attempt freezes the exact resolved provider request before calling Cartesia. For
each controllable field it records both the value and provenance:

```text
inherit default  |  explicitly set value  |  explicitly omit
```

Explicit omission matters for `emotion`: omitted is different from inheriting `calm`.
The take also binds the exact dictionary binding and request digest. “Effective” means
the values actually requested, not a claim that a generative model achieved an exact
acoustic speed, volume or emotion.

### 5.4 Pronunciation dictionary

A dictionary binding contains an opaque private provider reference and a canonical
content digest/export. Provider ID alone is insufficient evidence because provider
content could change.

- Editing content creates a new binding; it never mutates the old one.
- A new take resolves either the current job default or an explicit passage override.
- Changing the job default affects subsequent takes only.
- An explicit passage requirement/remap makes earlier takes dictionary-ineligible for
  that new requirement.
- The program does not infer which passages contain a semantically affected word.

This keeps a pronunciation correction local when the operator explicitly maps it
locally, while remaining honest about a job-wide default change.

## 6. Authorization and actor ownership

### 6.1 Who assigns status

Permission originates with SSGGSM or an authorized representative. The software does
not invent or approve it. Initially one locally configured stable `ActorId` is bound as
the sole authorization steward/operator and records the attested status in the private
system. Later reviewers do not gain authorization-management power merely by receiving
accounts.

`AuthorizationRecord` owns immutable grant/evidence identity, granted scope, the bound
authorization-steward actor, an append-only change history and a monotonic revision.
Only that server-resolved actor may record an initial active grant, narrowing or
withdrawal. A narrowed/withdrawn grant is never widened or reactivated in place; a
later permission is a new attested grant. A narration job binds one record ID
immutably; withdrawal blocks that job, and later permission starts a new job rather
than silently rebinding historical takes. Exact serialization and evidence-retention
rules are deferred to the implementation plan.

### 6.2 Historical snapshot versus current truth

A job/take keeps an immutable snapshot so an audit can answer what was observed at the
time. Current permission is answered only by `AuthorizationStatusReader`, backed by
the canonical private record.

| Operation | Current-status rule |
|---|---|
| Prepare/generation preflight | Show status; no provider call if unavailable or out of scope. |
| Generate | Re-read and fail closed immediately before the provider boundary. |
| Review/listen | Historical retained audio may be heard and notes may be added. This does not make it eligible or release-approved. |
| Working select/assemble | Re-read; unavailable, narrowed or withdrawn scope blocks eligibility-changing work. |
| Delivery/publishing preparation | Re-read and require separate content/distribution authority when that policy is later defined. |

### 6.3 Withdrawal race

The local system can guarantee that a withdrawal observed before its final pre-call
check blocks a new provider call. It cannot recall a request already transmitted to
Cartesia. If a status change races an in-flight request, preserve the response and its
facts as quarantined/ineligible evidence, then require current valid authorization
before any later use. The proposed call-order protocol is in §11; the implementation
plan must prove its crash/race behaviour rather than promise instantaneous revocation.

## 7. Hexagonal architecture

```text
localhost operator UI ─┐
optional CLI ──────────┼─> application handlers ─> domain aggregates/value objects
future reviewer UI ────┘             │
                                     └─> outbound ports
                                          ├─ private filesystem repositories
                                          ├─ Cartesia adapter
                                          ├─ FFmpeg/media adapter
                                          └─ actor/auth status adapters
```

The UI is a driver adapter. It may format commands and read models; it does not decide
authorization, eligibility, approval or master rules. Cartesia SDK types are confined
to the outbound provider/platform adapter. Domain code has no web, filesystem, FFmpeg
or Cartesia imports.

ADR-0005's dependency rule and minimal-folder thresholds still apply. ADR-0009 remains
proposed for cross-lane extraction; until it is accepted and a second consumer exists,
Lane-B-local neutral mechanics are preferable to a speculative shared framework.

## 8. Application use cases

| Use case | Responsibility |
|---|---|
| `register_authorization` / `record_authorization_change` | Steward-only append to the private authorization history. |
| `prepare_narration` | Validate exact NFC text, assign order/revisions and create a job under one contract. |
| `estimate_generation` | Resolve settings/dictionaries, show passages and local cost estimate without provider I/O. |
| `generate_take` | Check budget/authorization, freeze request evidence and create one new immutable attempt/take. |
| `generate_pending_passages` | Sequentially generate only eligible passages needing a take, within an explicit cap. |
| `record_review_decision` | Append actor-attributed outcome, authority class and notes for an exact take. |
| `select_working_take` | Append a working selection only when the take is operationally accepted, current and eligible. |
| `assemble_master` | Re-check authorization/invariants and join exact selected audio in manifest order. |
| `record_master_listening` | Append final whole-diary listening outcome and notes. |
| `show_narration_status` | Present missing/stale/ineligible/rejected/working-accepted/selected and publishing-review status without secrets. |

There is no unscoped generation command. A provider call starts only from a prepared
Lane-B job and exact recorded text.

## 9. Local operator website

The initial website binds to loopback only and exposes these screens:

1. **Dashboard:** job progress, current authorization gate and integrity warnings.
2. **Prepare diary:** ordered exact Odia passages and contract/default summary.
3. **Generation:** cost preflight, hard cap, sequential progress, errors and resume.
4. **Passage review:** exact text, preserved players, exact settings/dictionary evidence,
   operational accept/reject, notes and explicit working selection. This never implies
   qualified-Odia publishing approval merely from the local actor.
5. **Comparison:** optional blind A/B for a deliberate take/profile question; permanent
   records remain unblinded.
6. **Master:** selected order, gap settings, player and final-listening checklist.
7. **Authorization:** steward-only record/status history without exposing private
   evidence in ordinary views.
8. **Audit:** revisions, attempt outcomes, hashes and integrity status with secrets and
   full private paths redacted.

All commands carry an expected revision so stale tabs cannot overwrite newer work.
The server resolves the configured actor identity; the browser cannot submit an actor
identifier as proof.
No manifest, review decision or authorization state is authoritative in `localStorage`.
Provider credentials and private voice IDs never enter client-side JavaScript.

Framework selection belongs in the implementation plan. Minimum acceptance is an
explicit `127.0.0.1`/`::1` bind with no LAN wildcard, a random per-launch secret-backed
session, origin/anti-forgery validation for every state-changing request, server-side
actor resolution, stale-revision rejection and zero browser-state authority.

## 10. Publishing-stage reviewer

The remote/authenticated adapter is deferred until there is a real qualified Odia
reviewer and publishing workflow. At that trigger:

- login resolves an existing/new stable `ActorId` server-side;
- reviewer scope begins with listening, qualified review decisions and notes; it never
  includes authorization administration or general TTS generation;
- exact selection/sign-off/release permissions and the number of required qualified
  reviews are decided at the publishing trigger;
- private audio delivery, account recovery/revocation, central persistence and audit
  are designed before any public/LAN exposure; and
- historical local actor records remain unchanged.

This stage does not automatically authorize publication or decide how many approvals
a release requires.

## 11. Generation, retry and recovery

The canonical request digest covers exact NFC text bytes, job/lane, release contract,
effective take settings, dictionary binding, authorization snapshot and output
contract.

1. Resolve text/settings and estimate cost without provider I/O.
2. Under expected job revision, reserve only a new `GenerationAttemptId` and budget;
   do not freeze the canonical request digest yet.
3. Read current authorization. If unavailable/out of scope, finalize the reserved
   attempt as blocked without a provider call.
4. Under expected job revision, freeze that exact `AuthorizationSnapshot`, the complete
   request and its canonical digest into the reserved attempt.
5. Invoke the provider outside the job lock using only the frozen request.
6. Stage/decode/hash the response, then re-read authorization to classify the result.
7. Publish immutable audio and finalize the attempt/take under expected revision. If
   authorization is unavailable/changed out of scope, preserve it quarantined and
   ineligible. Selection, assembly and later publishing re-check current status again.

- A completed matching take is reused unless the operator explicitly asks to spend on
  another stochastic render.
- Retry `429`, timeout and provider `5xx` only with bounded backoff; validation,
  authorization and credential failures do not receive blind retry.
- A lost/ambiguous provider response is recorded `unknown`. Exactly-once provider
  billing cannot be promised after the response is lost.
- Partial or undecodable bytes never become a take.
- Crash recovery reconciles reserved attempts and already published immutable
  artifacts; it never overwrites any take.
- Generation is sequential initially. Concurrency has no demonstrated benefit for one
  operator and complicates billing/race recovery.

## 12. Cost, quality and mastering gates

### Before generation

- current authorization covers SSGGSM/Odia/diary generation;
- voice, `language=or`, pinned snapshot/API and output contract are complete;
- text/order/digests and dictionary bindings are valid;
- estimated usage is within an explicit per-run/project cap; and
- the private root and credential are available without being printed.

Provider-reported usage is authoritative; Unicode character count is an estimate.
Plan pricing and credit conversions are dated configuration/evidence, never domain
constants. Clone creation was a one-time action; hosted TTS remains metered.

### After generation

- the WAV decodes as the canonical format, has non-zero duration and is not all digital
  silence;
- hash, size, media facts, exact request and outcome are recorded; and
- clipping/silence/signal measures may warn but cannot approve a take.

### Passage review

The operator/reviewer sees the exact Odia text and judges:

1. SSGGSM voice likeness;
2. no word omission, substitution or repetition;
3. Odia pronunciation and devotional names/mantras;
4. cadence, pauses and sentence endings;
5. calm natural devotional delivery without forced theatrical sadness; and
6. clicks, glitches or other audio artifacts.

The local sole operator may record operational acceptance for working selection and a
working master. That is not automatically qualified/native Odia publishing approval.
Before publishing, a separately attributed qualified/native Odia decision must satisfy
ADR-0007's release gate. The publishing-stage plan will define reviewer assignment and
the required approval count. Another render, text correction or dictionary remap
remains an explicit preserved action.

### Master

- exactly one selected operationally accepted/current/eligible take exists per passage;
- selected hashes and formats validate;
- order comes from the job, not filenames or timestamps;
- assembly concatenates exact PCM with only explicit inter-passage silence;
- master hash, duration, take list and settings are recorded; and
- final whole-diary listening checks joins, pace, level and completeness. The listening
  decision is an append-only record referencing the immutable `MasterId`.

Normalization, EQ, denoising or music creates a separately identified derived artifact
with separate settings/review; it never mutates the speech master invisibly.

## 13. Private persistence and security boundary

The exact directory/schema is deferred, but the private root logically contains two
repositories and an artifact area:

```text
private narration root
├── authorization records + append-only history
├── narration jobs + append-only job/attempt/review/listening history
└── immutable takes and masters
```

Required properties are OS locking, expected revision, canonical serialization,
atomic snapshot replacement, append-only history, no-clobber artifact publication,
safe relative references, containment/reparse checks and hash verification.

Git contains source, schemas, redacted fixtures and non-sensitive policy only. It does
not contain real diary text, manifests, API keys, voice/provider IDs, authorization
evidence, reference audio, generated takes or masters. Normal logs omit secrets, full
private paths and full diary text.

## 14. Test strategy

Implementation starts test-first only after this document is reviewed.

1. **Domain:** every `INV-NJ-*`/`INV-AR-*`, setting resolution including explicit
   omission, text-stale versus ineligible, dictionary remaps and master eligibility.
2. **Application with fakes:** dry-run has no provider I/O; budget refusal; current
   authorization/outage/narrowing/withdrawal and steward-only transitions; retry
   classification; unknown outcomes; review/selection/resumption and quarantine races.
3. **Repositories/artifacts:** snapshot-plus-ledger publication, locks/revisions,
   no-clobber bytes, crash boundaries, malicious/reparse paths and hash verification.
4. **Media:** synthetic-WAV decode, silence/clipping warnings, deterministic ordered
   assembly and exact-byte preservation.
5. **Local web:** loopback-only/no-LAN binding, random launch session,
   origin/anti-forgery enforcement, stable server actor attribution,
   expected-revision rejection, escaping and zero browser-state authority.
6. **Provider contract:** exact mapping of `language=or`, voice, dated model, controls,
   dictionary and WAV format; SDK types stay outside domain/application.
7. **Architecture:** ADR-0005 inward dependencies, no cross-context internals and no
   Cartesia imports outside the provider/platform adapter.
8. **Live smoke:** opt-in, non-private voice/text and strict cap only. CI never calls
   the SSGGSM voice or spends production credits.
9. **Human acceptance:** private Odia review of real takes/master; never committed and
   never replaced by an automated score.

## 15. Production rollout after approval

1. Accept or revise this proposed implementation design and decide proposed ADR-0009
   separately.
2. Write a task-level implementation plan on an isolated branch/worktree.
3. Build the domain/settings/authorization model and fakes using TDD.
4. Demonstrate a complete no-network job through application handlers.
5. Add private filesystem/artifact and media adapters.
6. Add the loopback operator UI against the same handlers.
7. Add the isolated Cartesia adapter and one short, capped private smoke generation.
8. Exercise reject/regenerate/approve/select/resume with one passage.
9. Generate and review the diary, then assemble/listen to the master.
10. Design the authenticated reviewer stage only when the publishing trigger exists.

## 16. Explicitly deferred decisions

- Python web framework, session implementation and UI component approach;
- canonical filesystem/schema, authorization serialization, backup and retention;
- final acceptance, timeout values and crash-recovery details for §11's proposed
  authorization/provider-call protocol;
- first real job ID, passage boundaries, inter-passage silence and mastering target;
- project/monthly credit caps and external artifact root;
- concrete local `ActorId`, reviewer identity, identity provider, reviewer count,
  selection/sign-off permissions and publication approval rule;
- public distribution authority and synthetic-voice disclosure wording;
- PVC/open-source replacement evidence; and
- Lane A's narrator, provider, language-specific processing and release workflow.

None of these deferred choices broadens Lane B.

## 17. Provider evidence retained from v1

The provider-specific findings below were checked on 2026-08-31 and remain dated
evidence, not permanent domain facts:

- [Sonic 3.6 model, Odia support and dated snapshots](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest)
- [Instant Voice Clone guidance](https://docs.cartesia.ai/build-with-cartesia/capability-guides/clone-voices)
- [Volume, speed and emotion controls](https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion)
- [Custom pronunciations](https://docs.cartesia.ai/build-with-cartesia/capability-guides/custom-pronunciations)
- [TTS endpoint comparison](https://docs.cartesia.ai/use-the-api/compare-tts-endpoints)
- [TTS bytes API](https://docs.cartesia.ai/api-reference/tts/bytes)
- [Professional Voice Clone guidance](https://docs.cartesia.ai/build-with-cartesia/capability-guides/clone-voices-pro)
- [Pricing](https://www.cartesia.ai/pricing)
