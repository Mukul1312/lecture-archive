# Cartesia Odia narration production design — v3

**Date:** 2026-09-02

**Status:** **Historical accepted full-scope design.** Superseded for remaining v1
implementation by [ADR-0012](../../decisions/0012-narrator-voice-v1-is-a-minimum-local-studio.md)
and the [v4 minimum local-studio design](2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md).

**Authority:** [ADR-0006](../../decisions/0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md),
[ADR-0007](../../decisions/0007-two-policy-isolated-narration-lanes.md),
[ADR-0008](../../decisions/0008-lane-b-production-boundaries.md),
[ADR-0009](../../decisions/0009-share-narration-mechanics-not-policy.md),
[ADR-0010](../../decisions/0010-cartesia-prompting-is-validated-rendering-evidence.md)
and [ADR-0011](../../decisions/0011-diary-episodes-compose-fixed-voice-narration-masters.md)
govern its retained policy/domain decisions. ADR-0012 governs implementation depth,
verification cadence and deferrals. This document superseded the workflow and
implementation detail in the
[v2 design](2026-09-02-cartesia-odia-narration-production-v2-design.md). The v1 and
v2 documents remain historical design evidence.

Acceptance of this design authorizes documentation and implementation planning only.
It does not itself authorize a Cartesia request, spending credits, generating private
speech, publishing audio or video, or broadening any speaker, text, language or
distribution permission.

> **V1 scope correction (2026-09-03):** This design overestimated the needs of the
> confirmed one-operator local workflow. Do not implement its separate physical
> ledgers, per-aggregate lock hierarchy, exhaustive crash/security matrices, trusted
> word-timing workflow, comprehensive audit console or fixed React/OpenAPI toolchain
> as v1 requirements. The v4 design preserves the accepted voice, aggregate,
> authorization, immutable-audio, review and dry-assembly boundaries while specifying
> the minimum remaining system.

### Pre-implementation legacy-data boundary

Existing tracked `data/narration/**` is frozen legacy evidence. The new Narrator Voice
system must not read it, and this checkpoint does not open, move or delete it. The
no-private-production-data rule applies to all new v1 material; new private text,
authority evidence, bindings, audio, raw timing and production stores remain outside
Git.

## 1. Outcome

Build a private, resumable production system that produces one reviewed Odia diary
episode from two independently governed narration jobs:

1. a short Lane-C Odia intro using one separately fixed Cartesia voice; and
2. the Lane-B Odia diary body using the approved SSGGSM Cartesia Instant Voice Clone.

The two voices never share a job or release contract. The system reviews and masters
each narration independently, then composes their immutable narration masters into
one dry episode speech master and an auditable timed-text package.

The production journey is:

~~~text
create a draft DiaryEpisode identity
  -> record current voice-use authority
  -> prepare one fixed-voice intro job bound to that episode
  -> prepare one fixed-voice SSGGSM diary job
  -> author exact Odia text and validated render recipes
  -> preview exact provider input and estimate cost
  -> generate preserved takes
  -> listen, review and select each passage
  -> assemble and listen to each narration master
  -> issue immutable narration-master snapshots through both job roots
  -> assemble and listen to the dry episode speech master
  -> build a versioned timed narration package
  -> retain reproducible evidence for a future Presentation consumer
~~~

The first inbound adapter is a loopback-only website for one operator. A qualified
Odia reviewer receives a login-based, review-only interface only when publishing
becomes a real stage. Background music, subtitle styling and video rendering are not
part of this implementation.

## 2. Production boundaries

### 2.1 Included

- one narrow Lane-C intro job for an Odia diary episode;
- one Lane-B SSGGSM Odia diary job;
- exact NFC Odia text, stable passage identities and explicit passage order;
- a hybrid structured plus Advanced Cartesia markup editor;
- provider-neutral passage render recipes and immutable effective synthesis inputs;
- local character/credit preflight and explicit generation caps;
- one immutable attempt and take history for every deliberate generation;
- bounded retry, resume and crash reconciliation without overwriting audio;
- passage audition, actor-attributed notes, operational accept/reject and explicit
  working selection;
- current authority checks and immutable authority snapshots;
- deterministic narration-master and dry episode assembly;
- narration-master snapshots issued only by their source job roots;
- final whole-narration and whole-episode listening decisions;
- provider timing capture when supported, validated cue normalization and explicit
  passage/sentence fallback;
- immutable, versioned TimedNarrationPackage values;
- private manifests, append-only history, hashes and decoded media facts;
- a loopback-only sole-operator website; and
- Cartesia, filesystem and media isolation behind ports and adapters.

### 2.2 Excluded

- clone creation, replacement or Professional Voice Clone training;
- Lane A non-SSGGSM English/Hindi production;
- a generic say command, arbitrary voice selection or arbitrary script generation;
- any Lane-C language, content or voice beyond the one fixed Odia episode-intro scope;
- automatic identity, pronunciation, alignment, emotion or release approval;
- public hosting, automatic publishing or an inferred distribution right;
- remote reviewer access before the publishing trigger;
- background selection, licensing, mixing or ducking;
- subtitle styling/rendering and video generation;
- a Presentation aggregate or empty Presentation package scaffold;
- destructive denoising, EQ, normalization, gain or music hidden in a speech master;
- a database, cloud object store, OAuth service, worker queue, event bus, CQRS or event
  sourcing merely in anticipation of scale; and
- promotion of narration masters into a separate aggregate or repository.

## 3. Policy scopes and fixed release contracts

### 3.1 Lane B — SSGGSM Odia diary body

Lane B retains every restriction in ADR-0006 through ADR-0008:

- speaker and voice: the already approved private SSGGSM Cartesia IVC binding;
- content: reviewed Odia diary narration only;
- language: or;
- provider: Cartesia;
- release model snapshot: sonic-3.6-2026-08-27;
- canonical audio: WAV, PCM signed 16-bit little-endian at 44.1 kHz, with the channel
  layout selected and frozen by the implementation plan;
- preferred future-take defaults: speed 0.90, volume 1.00 and emotion calm;
- review authority: qualified/native Odia listening, not an automated identity score;
  and
- authority: the job's immutable binding to the private SSGGSM authorization record.

Speed, volume, emotion and dictionary selection remain deliberate controls rather than
global locks. Calm is a reviewable request hint whose effect in Odia is empirical, not
a guaranteed acoustic property.

### 3.2 Lane C — fixed-voice Odia episode intro

Lane C is narrower than a general intro service:

- content: the reviewed introduction for one Odia diary episode;
- language: or;
- provider: Cartesia;
- speaker/voice: one opaque private intro voice reference fixed in the job contract;
- authority: a separate private authority binding that covers the voice, the intro
  text scope, generation and one intended `DiaryEpisodeId`;
- model/API: one dated route and request-schema snapshot proved to support the fixed
  voice and Odia before the job is created;
- canonical audio: the same complete WAV/PCM/44.1-kHz/channel-layout contract selected
  for Lane B and required by episode assembly; and
- review: exact Odia words, pronunciation, delivery, expected voice and audio quality.

Lane C does not inherit SSGGSM authorization, the SSGGSM voice reference or Lane-B
identity criteria. It also does not inherit Lane-B delivery defaults automatically.
Its speed, volume, emotion and dictionary defaults are explicit contract-adjacent job
inputs chosen before its first cost preflight and recorded for every resulting take.

A different intro voice, language, purpose, provider class or use outside the defined
diary episode starts another policy decision and another fixed-contract job. A dated
model/API change always starts another contract and follows accepted upgrade evidence
rather than mutating an existing job.

### 3.3 One job means one scope and one voice

Both lanes use the same NarrationJob aggregate model and neutral production
mechanics, but they enter through separate lane-policy factories and handlers. One
job declares exactly one lane and one fixed ReleaseSynthesisContract. No UI field,
render recipe, provider option or persistence edit can turn one job into the other.

The intro is never a special passage in the Lane-B job. Sharing Cartesia transport,
artifact storage, media inspection or review-record mechanics does not share voice
authority or release policy.

## 4. Domain model

### 4.1 Context overview

~~~text
Narrator Voice bounded context
|
|-- NarrationJob aggregate: one Lane-C intro
|   |-- fixed ReleaseSynthesisContract
|   |-- DeliveryControlDefaults
|   |-- ordered Passages
|   |   |-- current PassageText revision
|   |   |-- PassageRenderRecipe revisions
|   |   |-- GenerationAttempts and immutable Takes
|   |   |-- append-only ReviewDecisions
|   |   `-- append-only SelectionDecisions
|   |-- immutable NarrationMasters
|   `-- append-only NarrationMasterListeningDecisions
|
|-- NarrationJob aggregate: one Lane-B diary body
|   `-- same production shape, different fixed policy/contract
|
|-- AuthorizationRecord aggregates
|   `-- separate authority identity/history for each applicable voice scope
|
`-- DiaryEpisode aggregate
    |-- one Lane-C intro NarrationMasterSnapshot
    |-- one Lane-B diary NarrationMasterSnapshot
    |-- explicit intro-to-diary gap
    |-- AssemblyAttempts
    |-- immutable EpisodeSpeechMasters
    |-- append-only EpisodeListeningDecisions
    `-- immutable versioned TimedNarrationPackages
~~~

Audio bytes, raw provider responses and large timing artifacts do not live in
aggregate snapshots. Aggregates store immutable artifact references and facts.

### 4.2 NarrationJob vocabulary

| Term | Meaning |
|---|---|
| NarrationJob | One fixed-lane, fixed-speaker, fixed-voice narration production and its complete decision history. |
| ReleaseSynthesisContract | Immutable lane, authority binding, speaker/voice, language, provider, dated model/API and canonical output envelope. |
| DeliveryControlDefaults | Adjustable defaults used only when resolving future takes. |
| Passage | Stable passage identity/order plus revisioned text and render requirements. |
| PassageText | Exact NFC Odia lexical text and punctuation used for listening review and later display. It never contains provider markup. |
| PassageRenderRecipe | The concrete per-passage form of ADR-0010's RenderRecipe: immutable provider-neutral rendering intent bound to one text revision. |
| GenerationAttempt | One reserved/budgeted provider-call attempt, including blocked, failed, unknown, quarantined or completed outcome. |
| EffectiveTakeSettings | Exact resolved speed, volume, emotion and dictionary binding, including inherited/set/omitted provenance. |
| EffectiveSynthesisInput | Complete frozen text, recipe, settings, authority, contract, provider-capability and exact rendered-transcript evidence used for one attempt. |
| Take | Immutable successful production result with one opaque TakeId and one audio ArtifactRef. |
| ReviewDecision | Append-only actor-attributed outcome, authority class and notes against one exact take. |
| SelectionDecision | Append-only working choice of a current, eligible, operationally accepted take. |
| NarrationMaster | Immutable ordered assembly facts and artifact for one job's selected passage takes. |
| NarrationMasterSnapshot | Immutable value issued through a NarrationJob root for safe episode composition. |

TakeId identifies a production event. Audio SHA-256 identifies the resulting bytes.
Two attempts remain two attempts and two takes even if their output bytes match.

### 4.3 NarrationMasterSnapshot

A narration master remains a child/history record owned by its NarrationJob. There is
no MasterRepository and no direct external loading of a child MasterId.

When an application handler proves a source master is current and eligible, it asks
the source job root to issue a NarrationMasterSnapshot value containing:

- issuing NarrationJobId and job revision;
- source MasterId and the passing operational master-listening decision used for issuance;
- lane, release-contract and authority-snapshot identities;
- role eligibility, either intro or diary, plus the intended DiaryEpisodeId for Lane C;
- immutable audio ArtifactRef, SHA-256 and decoded media facts;
- duration and exact decoded sample count;
- ordered source passage IDs, text revisions and canonical text digests;
- selected TakeIds, explicit inter-passage gaps and the sample-accurate passage offset map;
- timing/alignment references;
- issuance time and snapshot digest.

The snapshot is evidence of what the root issued at that revision. It is not current
authority. Attach, episode assembly and delivery handlers still consult the source job
and current authority readers.

### 4.4 DiaryEpisode vocabulary

| Term | Meaning |
|---|---|
| DiaryEpisode | Composition aggregate that begins as a draft and becomes configured only with exactly one intro snapshot followed by exactly one diary snapshot. |
| ComponentRole | The closed first-release values intro and diary. |
| AssemblyAttempt | Recoverable attempt to create a dry EpisodeSpeechMaster from exact snapshots and gap settings. |
| EpisodeSpeechMaster | Immutable dry PCM assembly of the two narration masters and explicit gap only. |
| EpisodeListeningDecision | Append-only actor-attributed whole-episode listening outcome referencing one exact EpisodeSpeechMasterId. |
| TimedNarrationPackage | Immutable versioned text-and-timing handoff tied to one exact EpisodeSpeechMaster. |

DiaryEpisode does not generate TTS, review individual takes, decide source-job
eligibility or update either source job.

## 5. Stable invariant catalogue

### 5.1 NarrationJob

| ID | Invariant |
|---|---|
| INV-NJ-1 | Passage IDs and explicit order are unique inside one job. |
| INV-NJ-2 | Every take binds exact text revision, job/lane, release contract, effective settings, dictionary, authority snapshot, render recipe, effective synthesis input and artifact reference. |
| INV-NJ-3 | Take metadata and produced bytes are immutable; another render creates another TakeId. |
| INV-NJ-4 | Editing passage text preserves prior takes but makes them text-stale. |
| INV-NJ-5 | Review and selection decisions are append-only; only a take satisfying current review and eligibility policy can be selected. |
| INV-NJ-6 | A narration master uses exactly one selected, current and eligible take per passage in manifest order; this alone does not make it publishable. |
| INV-NJ-7 | Generation, assembly and delivery fail closed unless current authority is readable and covers the operation. |
| INV-NJ-8 | A job cannot change lane, speaker, voice, language or release-contract identity in place. |
| INV-NJ-9 | Human decisions use a server-resolved ActorId, never an actor identifier supplied by the browser. |
| INV-NJ-10 | A job's voice-authority binding is immutable. Withdrawal permanently blocks protected work on that job; later authority creates a new record and job rather than silently rebinding history. |
| INV-NJ-11 | Canonical PassageText contains no provider markup and remains the sole lexical text used for review and display. |
| INV-NJ-12 | Every take binds one exact text revision, one immutable PassageRenderRecipe revision and one immutable EffectiveSynthesisInput with canonical digests. |
| INV-NJ-13 | Advanced markup is accepted only after authoritative server-side structural, allowlist, capability and Unicode-aware lexical-equivalence validation by the provider ACL. |
| INV-NJ-14 | Exact rendered provider transcript bytes, digest, dialect/capability snapshot and billable-character estimate are frozen before provider I/O and cannot be supplied authoritatively by the browser. |
| INV-NJ-15 | A render recipe cannot alter lane, speaker, voice, language, release contract, authority scope or canonical lexical content. |
| INV-NJ-16 | A required-recipe mismatch is recipe-ineligible, never text-stale; another render never rewrites prior evidence. |
| INV-NJ-17 | A job root issues a NarrationMasterSnapshot only for a master with a current passing operational whole-master listening decision; this does not imply publishing approval. |
| INV-NJ-18 | Every NarrationMaster records explicit gaps and a sample-accurate passage offset map, and every issued snapshot carries those exact facts. |

Text-stale is reserved for a passage-text revision mismatch. Recipe, dictionary,
contract or current-authority mismatches are separately inspectable forms of
ineligibility.

### 5.2 AuthorizationRecord

| ID | Invariant |
|---|---|
| INV-AR-1 | Grant identity, evidence digest and prior authority history are immutable. |
| INV-AR-2 | Only the record's bound authorization-steward ActorId may append a scope/status change; no change rewrites historical snapshots. |
| INV-AR-3 | A narrowed or withdrawn grant cannot be widened or reactivated in place; later permission creates another attested record. |

### 5.3 DiaryEpisode

| ID | Invariant |
|---|---|
| INV-DE-1 | A draft episode may contain zero or one component; it becomes configured only with exactly one Lane-C intro snapshot followed by exactly one Lane-B diary snapshot, and only configured episodes may reserve assembly. |
| INV-DE-2 | Every component snapshot is issued by its source NarrationJob root and binds source job/master revisions, contract/lane/episode-role identity, passing operational master listening, audio/text/timing digests, passage offsets and media facts. A Lane-C snapshot's intended DiaryEpisodeId must match the receiving episode. Browser-supplied paths or MasterIds are never authority. |
| INV-DE-3 | Attach, assembly and delivery use application-level current source-job and authority checks; a stored snapshot is never current authority. |
| INV-DE-4 | Both component artifacts satisfy the same canonical PCM sample rate, sample format and channel layout before assembly. |
| INV-DE-5 | EpisodeSpeechMaster is immutable exact component PCM in declared order with only the explicit gap; it never mutates source masters or hides gain, normalization, music or other DSP. |
| INV-DE-6 | Changing a component, role/order, gap or assembly input preserves history and creates a new episode revision and, after assembly, a new EpisodeSpeechMasterId. |
| INV-DE-7 | Assembly and episode-listening decisions are append-only and actor-attributed; each listening decision references one exact episode master. |
| INV-DE-8 | Every TimedNarrationPackage binds one exact episode master, source text revisions/digests, component offsets, cue provenance and validation results; a correction creates another package version. |
| INV-DE-9 | Cues are monotonic and non-overlapping within their declared stream, fall inside referenced durations and preserve role/order. Untrusted or absent word timing is represented honestly and never fabricated. |
| INV-DE-10 | Background audio, subtitle rendering and video artifacts cannot become children of DiaryEpisode in this implementation. |

## 6. Synthesis configuration

### 6.1 ReleaseSynthesisContract

The contract is immutable for one job and contains:

- lane and permitted narration purpose;
- fixed speaker/voice binding and opaque provider voice reference;
- immutable voice-authority binding;
- language;
- provider and dated model snapshot;
- exact API/request-schema version;
- provider-capability snapshot identity;
- canonical audio contract;
- permitted episode role; and
- for Lane C, the one intended DiaryEpisodeId.

Changing any of these values starts another job. Private provider/voice references are
stored outside Git and are represented in ordinary audit views by opaque IDs or
digests. API keys are never manifest data.

### 6.2 DeliveryControlDefaults

Defaults resolve only future takes. Lane B begins with:

~~~yaml
speed: 0.90
volume: 1.00
emotion: calm
pronunciation_dictionary: configured-private-binding
~~~

Lane C records its own explicit defaults and never silently copies this Lane-B
profile. Revising defaults does not reinterpret or invalidate historical takes.

### 6.3 EffectiveTakeSettings

Every attempt freezes exact values and provenance:

~~~text
inherit current default
explicitly set value
explicitly omit
~~~

Explicitly omitted emotion is distinct from inherited calm. Effective means requested
from a generative provider, not guaranteed acoustically.

### 6.4 Pronunciation dictionaries

A dictionary binding contains:

- an opaque private provider reference;
- a canonical content digest and private export;
- a dictionary revision/capability identity; and
- its job default or explicit passage-remap provenance.

Editing provider dictionary content creates another immutable binding. Provider ID
alone is insufficient because provider-side content may change.

A new take resolves the current job default or explicit passage override. Changing a
future default does not invalidate prior takes. Declaring a new passage requirement or
remap makes earlier mismatched takes dictionary-ineligible. The program does not guess
which passages are semantically affected by a job-wide dictionary change.

## 7. Hybrid synthesis authoring

### 7.1 Three separate concepts

The hybrid editor never recreates a mutable all-purpose prompt profile:

| Concept | Responsibility |
|---|---|
| PassageText | Approved lexical Odia and punctuation for listening and display. |
| PassageRenderRecipe | Revisioned provider-neutral instructions such as explicit pauses, local delivery variation or spelling intent. |
| EffectiveSynthesisInput | Exact immutable provider request evidence frozen for one generation attempt. |

Request-level speed, volume and emotion remain EffectiveTakeSettings. The recipe may
refer to these controls and add local annotations, but it cannot own or alter the
release contract.

### 7.2 One canonical editor state

The website presents three jointly previewed inputs:

1. request-level delivery settings and a pronunciation-dictionary binding;
2. structured render annotations; and
3. an optional Advanced Cartesia markup view.

Only structured render annotations and Advanced markup are two views of one
server-validated recipe, not two sources of truth. Request settings and dictionary
remain separate `EffectiveTakeSettings` inputs. Structured annotation edits update the
normalized recipe. Advanced input is parsed completely, translated to that same
provider-neutral recipe and returned with all inputs in one canonical preview. The
browser never submits already-rendered provider bytes as authority.

Advanced source is always displayed as escaped text, never inserted as HTML. Browser
feedback is advisory. Save, preflight and generation require server-side parsing.

### 7.3 Validation and initial capability policy

The Cartesia ACL must:

- parse a complete document rather than strip strings or tags;
- reject malformed nesting, unknown tags/attributes, unsafe entities and unsupported
  combinations;
- apply finite configured bounds for source size, nesting, tag count, individual
  breaks and total inserted silence;
- validate tags and ranges against the pinned model, language, API and capability
  snapshot;
- translate accepted input to a provider-neutral PassageRenderRecipe;
- project its lexical content with a versioned Unicode/Odia-aware algorithm;
- prove that projection equals the exact canonical PassageText; and
- return normalized recipe, exact provider transcript, warnings and estimated
  billable character count.

The initial semantic allowlist covers explicit breaks, supported inline speed/volume
variation and explicit spelling intent. Spelling intent must retain a mapping to the
unchanged canonical display span. Inline emotion tags are rejected for language or
until a later pinned capability and reviewed Odia evidence support them. Lane-B's
request-level calm value remains permitted as the already accepted empirical hint.

Ordinary punctuation belongs in PassageText. A requested punctuation, word or order
change creates another text revision instead of being hidden inside markup.

### 7.4 Mandatory frozen preview

Preview is invalidated by a change to:

- PassageText or its revision;
- PassageRenderRecipe;
- effective delivery settings;
- dictionary binding;
- release contract;
- authority snapshot;
- provider dialect/capability snapshot;
- timestamp flags or endpoint; or
- output contract.

Generation accepts a server-created preview token/digest under expected revisions. It
revalidates the referenced revisions and freezes the same exact UTF-8 rendered
transcript bytes before provider I/O. A stale preview is rejected and re-previewed;
the server never silently recompiles different billable input after the operator
confirmed cost.

### 7.5 EffectiveSynthesisInput contents

The frozen value records:

- job, lane, passage and text revision/digest;
- recipe revision, normalized recipe digest and compiler version;
- EffectiveTakeSettings and dictionary binding;
- release contract and authority snapshot;
- provider endpoint, API/request schema and dialect/capability snapshot;
- exact UTF-8 rendered transcript bytes, byte length and SHA-256;
- verified canonical plain-text projection and digest;
- requested timestamp/normalization flags;
- canonical output contract;
- dated billable-character rule and estimate; and
- canonical request digest over all preceding fields.

Raw advanced source, normalized markup and exact provider response metadata are
retained as private audit evidence. Cartesia SDK/request DTO types remain confined to
the adapter.

## 8. Authority and actor ownership

### 8.1 Source and steward

The relevant speaker, authorized representative or valid provider entitlement is the
source of voice-use authority. The software does not grant permission. Initially one
locally configured stable ActorId is both operator and authority steward and records
the attested private status. A future Odia reviewer does not gain authority
administration merely by receiving a login.

Lane B and Lane C use separate authority bindings. The Lane-C binding must cover its
fixed voice, Odia intro text scope, generation and one intended DiaryEpisodeId. It
cannot borrow the SSGGSM record.

Only the record's server-resolved steward actor may record the initial scope or append
narrowing/withdrawal. Private evidence and canonical authority records remain outside
Git. History is append-only.

### 8.2 Historical snapshot versus current truth

Every job, take, narration-master snapshot and protected episode operation records an
immutable authority snapshot: record identity, observed revision/digest, relevant
scope and observation time. A snapshot answers what was observed then. Current truth
comes only from the canonical private status reader.

| Operation | Current-status rule |
|---|---|
| Prepare/preflight | Show status and block provider eligibility if unreadable or out of scope. |
| Generate | Re-read immediately before provider I/O and fail closed. |
| Local review/listen | Retained historical audio may be heard and annotated; that does not restore eligibility. |
| Select/assemble narration | Re-read and fail closed for eligibility-changing work. |
| Issue NarrationMasterSnapshot | Load the root, require passing operational whole-master listening and re-read current status; Lane C also verifies the intended DiaryEpisodeId. |
| Attach/assemble DiaryEpisode | Re-read both source jobs and both applicable current authority statuses. |
| Delivery/publishing preparation | Re-read every source and require the later distribution/publication policy as well. |

Withdrawal observed before the final pre-provider check blocks the call. A local
system cannot recall a request already sent. A response racing a narrowing,
withdrawal or status outage is preserved as quarantined/ineligible evidence.

A later grant never silently rebinds an old job, take, narration master or episode.

## 9. Hexagonal architecture

~~~text
loopback operator website -----------+
optional diagnostic CLI -------------+--> application handlers --> domain
future authenticated reviewer UI ----+             |
                                                   +--> outbound ports
                                                        |-- repositories/artifacts
                                                        |-- authority/status reader
                                                        |-- render-recipe compiler
                                                        |-- synthesis provider
                                                        |-- media inspector/assembler
                                                        |-- timing normalizer
                                                        `-- clock/actor resolver
~~~

Driver adapters convert input into application commands and read models. They do not
decide lane, authority, eligibility, approval or assembly policy.

The application layer orchestrates cross-root reads and external work. The domain
owns fixed contracts, job/episode transitions and invariants. Infrastructure
implements filesystem, Cartesia, FFmpeg/media and web concerns.

Cartesia markup syntax, capability discovery, SDK types, endpoint DTOs and response
events live in the Cartesia adapter/anti-corruption layer. Domain policy sees
PassageRenderRecipe, EffectiveSynthesisInput and normalized result facts.

Neutral mechanics remain inside Narrator Voice until promotion thresholds in
ADR-0009 are met. Lane C is a candidate second policy-scope consumer, but a mechanic
graduates only after Lane-C tests and implementation prove identical semantics; until
then it remains first-consumer-local. Even proven Narrator Voice sharing does not make
the mechanic a repository-wide kernel concept. No empty framework or Presentation
context is scaffolded.

## 10. Application use cases

### 10.1 Authority

| Use case | Responsibility |
|---|---|
| register_authorization | Steward-only creation of a private authority record under a declared narrow scope. |
| record_authorization_change | Steward-only append of narrowing or withdrawal under expected revision. |
| show_authorization_status | Redacted current and historical status without exposing evidence or private paths. |

### 10.2 Narration jobs

| Use case | Responsibility |
|---|---|
| prepare_intro_narration | Create one Lane-C job through the Lane-C policy factory, bound to an existing draft DiaryEpisodeId and fixed intro contract. |
| prepare_diary_narration | Create one Lane-B job through the SSGGSM/Odia/diary policy factory. |
| revise_passage_text | Create a new exact NFC text revision and preserve older takes as text-stale evidence. |
| validate_render_recipe | Compile/validate structured or advanced authoring and return an authoritative preview. |
| require_render_recipe | Record which recipe revision is now required for future selection. |
| revise_delivery_defaults | Change only defaults for subsequently resolved takes. |
| estimate_generation | Freeze a revision-bound preview and show exact rendered input, estimate and hard cap without provider I/O. |
| generate_take | Reserve budget, re-check authority, freeze EffectiveSynthesisInput and make one provider attempt. |
| generate_pending_passages | Sequentially generate only explicitly eligible passages within one accepted run cap. |
| record_review_decision | Append outcome, authority class, ActorId and notes for one exact take. |
| select_working_take | Append a choice only for a current, eligible, operationally accepted take. |
| assemble_narration_master | Validate exact selected artifacts and create one immutable dry job master. |
| record_narration_master_listening | Append whole-narration listening outcome against one MasterId. |
| issue_narration_master_snapshot | Ask the root to issue a current eligible immutable snapshot only after passing operational whole-master listening; Lane C also validates its intended DiaryEpisodeId. |
| show_narration_status | Present missing, blocked, stale, recipe/dictionary/authority-ineligible, rejected, accepted, selected and mastered states. |

There is no unscoped generation command. A provider call can begin only from one
prepared job, one current passage revision and one server-frozen preview.

### 10.3 Diary episodes

| Use case | Responsibility |
|---|---|
| prepare_diary_episode | Create the empty draft composition aggregate and stable DiaryEpisodeId under expected revision. |
| attach_intro_master | Load Lane-C root/status, validate its intended DiaryEpisodeId, issue one listened-to intro snapshot and attach it by value. |
| attach_diary_master | Load Lane-B root/status, issue one listened-to diary snapshot and attach it by value. |
| set_intro_diary_gap | Record an explicit sample-based gap and create another episode revision. |
| assemble_episode_speech_master | Re-check both roots/authorities, reserve, validate and assemble exact dry PCM. |
| record_episode_listening | Append actor-attributed whole-episode outcome for one exact episode master. |
| build_timed_narration_package | Normalize exact selected text/timing onto the episode sample timeline with provenance. |
| record_timing_correction | Create a new immutable timing-package version; never edit raw or old timing evidence. |
| show_episode_status | Present component, authority, assembly, listening and timing confidence/status. |
| export_presentation_handoff | Export dry episode audio plus a versioned timed package without rendering presentation media. |

## 11. Local operator website

The local website binds explicitly to loopback and provides:

1. **Dashboard:** Lane-B, Lane-C and episode progress, current authority gates, credit
   warnings and integrity failures.
2. **Authority:** steward-only private status/history administration with evidence
   hidden from ordinary views.
3. **Prepare episode:** create the stable draft DiaryEpisodeId that scopes the intro.
4. **Prepare intro:** exact Odia intro passages, intended episode, Lane-C fixed-contract
   summary and explicit Lane-C delivery defaults.
5. **Prepare diary:** ordered exact Odia diary passages and Lane-B contract/defaults.
6. **Hybrid passage editor:** canonical text, structured controls, escaped Advanced
   Cartesia markup, normalized recipe, exact transmitted transcript preview,
   warnings, capability snapshot and estimated characters.
7. **Generation:** revision-bound cost preview, hard run cap, sequential progress,
   failures, unknown outcomes and resume.
8. **Passage review:** exact canonical Odia text, preserved take players, effective
   settings/recipe/dictionary evidence, operational accept/reject, notes and explicit
   working selection.
9. **Comparison:** optional deliberate blind A/B; permanent evidence remains
   unblinded and identified.
10. **Narration masters:** selected order/gaps, player and final whole-intro or
   whole-diary checklist.
11. **Episode assembly:** issued snapshot identities, fixed intro-then-diary order,
    sample gap, dry player and whole-episode checklist.
12. **Timing:** cue provenance, validation failures, passage/sentence fallback,
    optional reviewed word cues and package-version comparison.
13. **Audit:** revisions, attempts, frozen input digests, artifact hashes, actors,
    integrity and quarantine status with secrets/full paths/full text redacted as
    appropriate.

Every state-changing command carries an expected revision. Stale tabs fail rather
than overwrite work. The server resolves ActorId; the browser cannot assert identity
or authority through request fields, localStorage or display names.

Provider credentials and private voice IDs never enter client-side JavaScript.
Advanced markup is escaped on every display path. Minimum local-web security is:

- explicit 127.0.0.1 and/or ::1 binding with no LAN wildcard;
- a random secret-backed session per launch;
- origin and anti-forgery checks for every state-changing request;
- server-side actor resolution;
- expected-revision rejection;
- output escaping and a restrictive content-security policy; and
- zero authoritative state in localStorage.

Concrete web framework and component choices belong to the implementation plan.

## 12. Generation, retry and recovery

### 12.1 Preview and reservation

1. Load the job/passages under expected revision.
2. Resolve text, recipe, settings, dictionary, contract, capability and timestamp
   request locally.
3. Compile and validate the exact provider transcript without provider generation
   I/O.
4. Create a server preview digest and cost estimate over that exact input.
5. Require explicit operator confirmation of the displayed digest/cap.
6. Reject a stale preview if any bound revision changes.

### 12.2 Provider attempt

1. Under expected job revision, reserve a new GenerationAttemptId and budget. Do not
   call the provider under the job lock.
2. Read current voice-use authority. If unavailable or out of scope, finalize the
   attempt as blocked without provider I/O.
3. Under expected revision, freeze the exact authority snapshot and complete
   EffectiveSynthesisInput from the confirmed preview.
4. Invoke Cartesia outside the lock using only the frozen input.
5. Stage audio and raw timing events, decode/hash/inspect them and preserve exact
   provider outcome/usage facts.
6. Re-read current authority to classify the result.
7. Publish immutable artifacts and finalize the attempt/take under expected revision.
   If current authority became unavailable/out of scope, retain the result
   quarantined and ineligible.

The previewed and transmitted rendered transcript digests must match. A mismatch is an
adapter/integrity failure, not a warning.

### 12.3 Retry classification

- Retry 429, timeout and provider 5xx only with bounded backoff and an explicit
  attempt policy.
- Do not blindly retry validation, lexical-equivalence, authority, credential,
  unsupported-capability or contract failures.
- Record a lost/ambiguous provider response as unknown. Exactly-once provider billing
  cannot be promised.
- Partial, undecodable, wrong-format or all-digital-silence bytes never become an
  eligible take.
- A completed matching take is reused unless the operator explicitly requests and
  budgets another stochastic render.
- Generation is sequential initially; concurrency has not earned its race and billing
  complexity.

### 12.4 Crash reconciliation

Recovery reconciles:

- reserved attempts without provider start;
- in-flight/unknown attempts;
- staged audio/timing artifacts;
- already published no-clobber artifacts awaiting aggregate finalization; and
- ledger/snapshot revisions.

It never overwrites a take or reconstructs policy from filenames. Recovery may mark an
attempt blocked, failed, unknown, quarantined or completed only from recorded evidence.

## 13. Narration-master and episode assembly

### 13.1 Narration master

A narration master requires:

- one selected, operationally accepted, current and eligible take per passage;
- current readable authority covering assembly;
- valid selected hashes and canonical media facts;
- order from the aggregate, not filenames or timestamps;
- exact PCM concatenation with only explicit inter-passage silence;
- immutable master digest, duration/sample count, selected TakeIds and settings;
- every explicit inter-passage gap in integer samples and a sample-accurate passage
  offset map; and
- a later append-only whole-narration listening decision.

A passing operational whole-narration listening decision is required before the job
root may issue a NarrationMasterSnapshot. Qualified-Odia publishing approval remains
a separate later gate.

No normalization, EQ, denoising, gain or music is hidden inside the canonical master.
A perceived-level problem is corrected by deliberate generation/settings or a later
explicit derivative, not silent mastering.

### 13.2 Cross-root episode assembly protocol

1. Load DiaryEpisode under expected revision.
2. Load both NarrationJob roots and current authority statuses.
3. Ask each root to issue a current role-eligible, operationally listened-to
   NarrationMasterSnapshot; verify Lane C is bound to this DiaryEpisodeId.
4. Attach snapshots to a new episode revision or verify the already attached exact
   snapshot digests.
5. Reserve a new AssemblyAttempt under expected episode revision.
6. Outside locks, verify component hashes, decoded formats, duration/sample counts and
   canonical compatibility.
7. Assemble exact intro PCM, the explicit sample gap and exact diary PCM.
8. Carry each snapshot's passage map onto the episode timeline and produce a
   sample-accurate component/passage offset map while assembling.
9. Re-read both source jobs and current authorities.
10. Publish the immutable EpisodeSpeechMaster and base timing facts with no-clobber
    semantics, then finalize the attempt under expected episode revision.

There is no transaction that updates two jobs and an episode together. Source masters
are immutable; snapshots pin exact evidence; application-level rechecks and
conservative quarantine handle races honestly.

If a source becomes ineligible during assembly, preserve the resulting bytes and
attempt facts as quarantined/ineligible evidence. Delivery always rechecks current
source status.

### 13.3 Episode recovery

Episode crash recovery reconciles reserved attempts, staged dry PCM, timing-offset
maps and already-published artifacts. It verifies the exact component snapshot/gap
digest before finalization. It never substitutes the newest job master or recomputes
an episode from filenames.

## 14. Timed narration package

### 14.1 Timing capture

The Cartesia adapter requests provider timing only through a pinned endpoint/capability
that supports it, such as the SSE or WebSocket TTS route. It preserves:

- raw provider timing/event payload as a private immutable artifact;
- exact TakeId and audio/text/rendered-transcript digests;
- endpoint, model, language, API schema and timestamp flags;
- provider time unit and normalization option;
- tokens, starts and ends exactly as returned; and
- provider request/response identity when available.

Provider timing is evidence, not an automatic claim of correct Odia word alignment.
Generation may succeed when timing is absent or invalid; its timing status records the
failure honestly.

### 14.2 Normalized package schema

One TimedNarrationPackage contains:

- schema/package version and package digest;
- DiaryEpisodeId, episode revision and EpisodeSpeechMasterId;
- exact episode audio ArtifactRef, SHA-256, format, duration and sample count;
- intro and diary NarrationMasterSnapshot digests;
- exact gap and component offset map;
- ordered cue records;
- raw/normalized timing-artifact references;
- validation results and human timing-review decisions; and
- observed authority/eligibility snapshots that are explicitly not current truth.

Every cue records:

- CueId, component role and source lane;
- source JobId, MasterId, PassageId and PassageText revision/digest;
- exact NFC display text or an exact mapped text span;
- start/end samples, with derived seconds for consumers;
- timing granularity: component, passage, sentence or word;
- provenance: deterministic assembly offset, provider timestamp, forced alignment or
  manual correction;
- source tool/provider and version/capability where applicable;
- input audio/text digests; and
- validation and human-review status.

### 14.3 Guaranteed and optional timing

The first release guarantees sample-accurate component and passage cues from exact
assembly offsets and the explicit passage maps carried by both narration-master
snapshots.

Sentence cues are exported when either:

- the source passage itself is the reviewed sentence boundary; or
- validated provider/alignment/manual evidence maps that sentence exactly.

Word cues are optional. They are exported as trusted only after monotonicity,
duration, token/text-span and qualified Odia listening/visual checks pass. If provider
word timing for Odia is absent or unreliable, the package falls back explicitly to
sentence or passage cues. It never distributes calculated word highlights as if they
were aligned.

Spelling annotations require explicit canonical-display span mappings. Unmapped
provider spelling tokens cannot become trusted word cues.

### 14.4 Correction

Raw provider timing is immutable. Forced-alignment output is another immutable source
artifact. A human correction creates another TimedNarrationPackage version with actor,
reason, source package digest and corrected cue evidence. Old packages remain
auditable.

Timing-package failure never mutates or invalidates otherwise approved speech audio.
It blocks only a delivery requirement that explicitly demands the unavailable timing
granularity.

## 15. Cost and quality gates

### 15.1 Before generation

- the request belongs unambiguously to Lane B or narrow Lane C;
- current authority covers the fixed voice, Odia text and intended operation;
- voice, language, dated model/API and output contract are complete;
- exact PassageText/order/digests are valid;
- recipe server validation and lexical equivalence pass;
- settings/dictionary/capability/timestamp inputs are fully resolved;
- the exact rendered transcript and billable-character estimate are displayed;
- estimated usage is within an explicit per-run and project cap; and
- private storage and provider credentials are available without printing them.

Provider-reported usage is authoritative. Dated pricing/credit conversion is
configuration/evidence, never a domain constant. Clone creation was a prior action;
hosted TTS remains metered.

### 15.2 After generation

- audio decodes exactly as the canonical WAV/PCM format;
- duration and sample count are non-zero;
- bytes are not all digital silence;
- hash, size, decoded facts, exact frozen request and outcome are recorded;
- raw timing is preserved and independently classified; and
- clipping/silence/signal diagnostics may warn but cannot approve a take.

### 15.3 Passage listening

For both lanes, the reviewer judges:

1. no word omission, substitution, reordering or repetition;
2. Odia pronunciation and devotional names/mantras;
3. cadence, pauses and sentence endings;
4. natural calm delivery appropriate to the passage;
5. no spoken markup or unexpected spelling behavior; and
6. no clicks, glitches or other audio artifacts.

Lane B also judges faithful SSGGSM likeness. Lane C judges the expected fixed intro
voice rather than SSGGSM likeness.

The sole operator may record operational acceptance for working selection and private
masters. This is not automatically qualified/native Odia publishing approval.
Publishing later requires separately attributed qualified-Odia decisions under a
dedicated release policy.

### 15.4 Narration and episode listening

Narration-master listening checks completeness, passage order, joins, pacing and
level continuity inside one voice.

Episode listening checks:

- the exact approved intro and diary are present once;
- intro precedes diary;
- the transition gap is correct;
- there is no truncation, duplication or unexpected silence;
- the two voices are correctly assigned to their roles;
- level/pace remains acceptable without hidden DSP; and
- the episode is complete.

An episode listening decision is append-only and references the exact immutable
EpisodeSpeechMasterId.

### 15.5 Timing review

Automated validation checks structure and bounds only. Human timing review verifies
that displayed Odia changes when the corresponding speech is actually heard. Word
highlighting cannot be approved from token count or monotonic timestamps alone.

## 16. Private persistence and security

The private root logically contains three aggregate repositories and immutable
artifact areas:

~~~text
private narrator root/
|-- authorization/
|   |-- current records
|   `-- append-only authority history
|-- narration-jobs/
|   |-- current job snapshots
|   `-- append-only attempt/review/selection/listening ledgers
|-- diary-episodes/
|   |-- current episode snapshots
|   `-- append-only assembly/listening/timing history
`-- artifacts/
    |-- immutable takes
    |-- immutable narration masters
    |-- immutable episode speech masters
    |-- raw timing/provider evidence
    `-- timed narration packages
~~~

There is one repository per aggregate root:

- AuthorizationRecordRepository;
- NarrationJobRepository; and
- DiaryEpisodeRepository.

There is no Passage, Take, Master or NarrationMasterSnapshot repository.

Required persistence properties are:

- OS locking and expected-revision/CAS;
- canonical serialization and monotonic revisions;
- atomic snapshot replacement;
- append-only history;
- no-clobber artifact publication;
- safe relative artifact references;
- containment and reparse-point checks;
- hash and decoded-media verification;
- recoverable staged publication; and
- explicit quarantine status.

Git contains source, schemas, redacted fixtures and non-sensitive policy only. It does
not contain:

- real intro or diary text/manifests;
- API keys or private voice/provider references;
- voice-authority evidence;
- reference or generated audio;
- raw provider timing for private text;
- real takes, masters or episode packages; or
- private reviewer notes.

Normal logs omit secrets, complete private paths, full private text and raw provider
payloads. Audit views reveal exact text/evidence only to the local authorized workflow
and redact it from ordinary diagnostics.

## 17. Future Presentation boundary

Narrator Voice exports only:

- immutable dry EpisodeSpeechMaster;
- versioned TimedNarrationPackage;
- artifact/text/package hashes and schema versions; and
- a current-delivery check result that must not be cached as permanent authority.

A future Presentation context may consume these artifacts to create:

- background-mixed audio;
- subtitle files and styled text;
- word/sentence highlighting;
- images, motion and visual backgrounds; and
- rendered delivery video.

That future context owns background-asset rights, mix/ducking recipes, subtitle
layout, video timeline/rendering, audiovisual review and release artifacts. It cannot
mutate or replace the approved dry speech master. Every presentation result is a
separately identified derivative linked to exact input digests.

No Presentation directory, aggregate, renderer, mixer or subtitle service is created
until a concrete presentation design is approved.

## 18. Test strategy

Implementation begins test-first after a task-level plan.

### 18.1 Domain

- every INV-NJ-*, INV-AR-* and INV-DE-* invariant;
- exhaustive Lane-B/Lane-C fixed-contract isolation;
- text-stale versus recipe/dictionary/authority-ineligible semantics;
- recipe revision and required-recipe transitions;
- setting inheritance, explicit values and explicit omission;
- review/selection/narration-master eligibility;
- snapshot issuance only through eligible source roots after passing operational
  whole-master listening, with Lane-C episode binding;
- narration-master gap and passage-offset preservation;
- exact episode roles/order/gap and immutable episode masters; and
- immutable timing-package correction/version rules.

### 18.2 Application with fakes

- dry-run/preview performs no provider generation I/O;
- stale preview and expected-revision refusal;
- budget refusal and sequential cap;
- current authority outage/narrowing/withdrawal for both lanes;
- steward-only transitions and immutable rebinding rules;
- provider-call withdrawal race and quarantine;
- retry classification, unknown outcomes and recovery;
- take review/selection/resume;
- two-root snapshot issuance without cross-aggregate transactions;
- episode attach/assembly/delivery rechecks; and
- timing absence/invalidity fallback without corrupting audio state.

### 18.3 Render compiler and provider contract

- parser allowlist, malformed nesting, entities, escaping and configured limits;
- Unicode/Odia lexical equivalence, including combining marks and punctuation;
- structured/advanced round-trip to one normalized recipe;
- spelling-to-display-span mapping;
- stale capability/compiler snapshots;
- exact preview/transmitted-byte digest equality;
- exact mapping of language or, voice, dated model, controls, dictionary, timestamps
  and WAV output;
- raw timing preservation and normalized response facts; and
- zero Cartesia SDK/request imports in domain/application modules.

### 18.4 Repositories and artifacts

- snapshot-plus-ledger atomic publication;
- locks, CAS and stale revisions;
- no-clobber bytes and duplicate-digest/different-take behavior;
- crash boundaries and reconciliation;
- malicious relative, absolute and reparse paths;
- hash/media/timing integrity; and
- proof that no Master repository exists.

### 18.5 Media and timing

- synthetic canonical-WAV decode and wrong-format refusal;
- silence/clipping warnings;
- deterministic job and episode assembly;
- exact PCM preservation and explicit sample gaps;
- exact sample-count component/passage offsets;
- monotonic/bounded cue validation;
- text-span and digest mismatches;
- trusted/untrusted word timing and passage/sentence fallback; and
- immutable correction versions.

### 18.6 Local web

- loopback-only/no-LAN binding;
- random launch session and origin/anti-forgery enforcement;
- server-resolved actor attribution;
- expected-revision and stale-preview rejection;
- raw-markup/text escaping and content-security policy;
- no private voice IDs or credentials in client JavaScript;
- no browser-state authority; and
- Lane B, Lane C and episode commands cannot be confused by crafted requests.

### 18.7 Architecture

- ADR-0005 inward dependency rule;
- lane-policy modules remain separate;
- Cartesia/FFmpeg/web/filesystem imports remain in adapters/platform code;
- no cross-context internal imports;
- no speculative Presentation scaffold; and
- neutral-mechanic promotion obeys ADR-0009.

### 18.8 Live and human evidence

Automated CI uses fakes and may run an opt-in, strict-cap smoke only with
non-sensitive voice/text. CI never uses the SSGGSM voice, Lane-C private voice or real
diary text.

A separately authorized, steward-run capped private smoke is required before
production to verify both fixed voices, Odia route behavior, exact request mapping and
timestamp availability. That run is not authorized merely by this design.

Real take, narration-master, episode and timing acceptance is private human Odia
review. It is never committed and never replaced by an automated score.

## 19. Production rollout

1. Review this accepted design and write a task-level implementation plan on an
   isolated branch/worktree.
2. Assign enforcement sites for every invariant and define the first private schema,
   backup/retention policy, caps and concrete adapter versions.
3. Build AuthorizationRecord, NarrationJob, PassageRenderRecipe and DiaryEpisode
   domain behavior with tests.
4. Demonstrate two complete no-network fixed-voice jobs plus one dry episode using
   in-memory adapters.
5. Add private filesystem repositories, immutable artifacts and crash reconciliation.
6. Add deterministic narration/episode media assembly and sample-accurate base timing.
7. Add the Cartesia render compiler/ACL and contract tests without making a live call.
8. Add the loopback operator website against the same application handlers.
9. Add the isolated Cartesia synthesis/timestamp adapter and verify exact
   preview-to-request evidence with fakes.
10. Obtain separate explicit approval for one short capped private smoke, then verify
    each fixed voice and Odia/timestamp behavior.
11. Exercise reject, regenerate, recipe correction, select, resume, narration-master,
    snapshot, episode and timing-fallback flows with short private material.
12. Generate and review the real intro and diary only within their current authority
    and explicit budget caps.
13. Assemble/listen to the dry episode and export its timed package.
14. Design authenticated publishing review only when the real Odia reviewer and
    publication policy are ready.
15. Design Presentation separately before adding background, subtitles or video.

## 20. Explicitly deferred decisions

The implementation plan, not ad hoc code, must select:

- Python web framework, session implementation and UI component approach;
- canonical on-disk schema, backup, retention and disaster recovery;
- canonical channel layout shared by both narration contracts;
- concrete first Lane-C private voice/authority references and its delivery defaults;
- Lane-C dated model/API snapshot after capability validation;
- initial parser library and finite markup safety limits;
- first real job/episode IDs, passage boundaries and explicit silence values;
- per-run, project and monthly credit caps;
- exact retry/backoff/timeout values;
- external private artifact root;
- concrete local ActorId;
- reviewer identity, identity provider, reviewer count and publishing sign-off rule;
- public distribution authority and synthetic-voice disclosure wording;
- word-alignment fallback tool if provider timing is inadequate;
- Presentation asset/licensing, mix, subtitle and video-render design;
- PVC/open-source replacement evidence; and
- Lane A narrator/provider and release workflow.

Each item has a named decision point and none may broaden Lane B or Lane C silently.
Implementation may proceed without a Presentation design because the accepted output
boundary is the dry episode master and timed package.

## 21. Dated provider evidence

These provider findings are dated implementation evidence, not permanent domain
facts:

- [Sonic 3.6 model, Odia support and dated snapshots](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest)
- [Instant Voice Clone guidance](https://docs.cartesia.ai/build-with-cartesia/capability-guides/clone-voices)
- [Prompting tips](https://docs.cartesia.ai/build-with-cartesia/capability-guides/prompting-tips)
- [Supported SSML-like tags](https://docs.cartesia.ai/build-with-cartesia/capability-guides/ssml-tags)
- [Volume, speed and emotion controls](https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion)
- [Custom pronunciations](https://docs.cartesia.ai/build-with-cartesia/capability-guides/custom-pronunciations)
- [TTS endpoint comparison](https://docs.cartesia.ai/use-the-api/compare-tts-endpoints)
- [TTS bytes API](https://docs.cartesia.ai/api-reference/tts/bytes)
- [TTS WebSocket API and timestamps](https://docs.cartesia.ai/api-reference/tts/websocket)
- [Professional Voice Clone guidance](https://docs.cartesia.ai/build-with-cartesia/capability-guides/clone-voices-pro)
- [Cartesia pricing](https://www.cartesia.ai/pricing)

Provider documentation does not guarantee that a beta control or word timestamp is
accurate for Odia. Pinned capabilities, exact request evidence and private human
review remain mandatory.
