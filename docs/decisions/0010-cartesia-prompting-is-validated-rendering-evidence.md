# ADR-0010 — Cartesia prompting is validated rendering evidence, not free-form narration policy

**Date:** 2026-09-02 · **Status:** **Accepted 2026-09-02** · **Governs:** Narrator Voice synthesis authoring and Cartesia request compilation
**Supersedes:** nothing · **Superseded by:** —

Related: [ADR-0006](0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md)
selects the Lane-B Cartesia voice and delivery baseline;
[ADR-0007](0007-two-policy-isolated-narration-lanes.md) owns lane policy; and
[ADR-0008](0008-lane-b-production-boundaries.md) owns the fixed release contract,
delivery defaults, immutable take evidence and aggregate invariants. This record adds
an authoring and provider-compilation boundary without weakening any of them.
[ADR-0011](0011-diary-episodes-compose-fixed-voice-narration-masters.md) separately
defines the narrow Odia intro, episode and timed-narration boundary.

---

## 1. Context

Cartesia calls guidance for transcript authoring, punctuation, supported SSML-like
tags and request-scoped generation controls “prompting.” Its documented TTS request
does not provide a general hidden instruction field. Treating “custom prompting” as
an unrestricted string in `NarrationJob` would therefore be both inaccurate and
unsafe: provider syntax would leak into the domain, the exact text intended for Odia
review could become ambiguous, and an advanced field could bypass the job's fixed
speaker, voice, language, content or authorization policy.

The operator nevertheless needs both convenient ordinary controls and precise
provider-supported authoring. Structured controls alone cannot express every useful
pause or spelling instruction. Raw markup alone is error-prone and makes it difficult
to prove which lexical content was approved, displayed and sent to synthesis.

ADR-0008 already separates the immutable `ReleaseSynthesisContract`, mutable defaults
for future takes and exact per-take settings. Prompt authoring must complement that
split rather than recreate the former all-purpose profile. It must also preserve
ADR-0008's distinction between **text-stale** and other forms of ineligibility.

## 2. Decision

### 2.1 Separate approved text, render intent and transmitted input

Use three distinct concepts:

| Concept | Meaning | Ownership and change rule |
|---|---|---|
| Canonical passage text | The exact NFC Odia text and punctuation approved for narration and later display, identified by its existing passage text revision and digest. | Domain-owned. Editing lexical content or punctuation creates a new text revision and makes older takes text-stale under ADR-0008. Provider tags never become part of this value. |
| `RenderRecipe` | Immutable, provider-neutral render intent for one passage text revision: structured delivery annotations such as explicit pauses or spelling intent, plus references to the independently resolved delivery controls and dictionary binding. It has its own opaque revision identity and canonical digest. | Domain/application-owned. It contains no Cartesia tags, SDK types, voice override, language override or arbitrary instruction string. Editing it creates a new recipe revision. |
| `EffectiveSynthesisInput` | The complete immutable input frozen immediately before one generation attempt: passage text revision/digest, recipe revision/digest, effective take settings, dictionary binding, release contract, authorization snapshot, provider markup dialect/capability snapshot, and the exact rendered transcript bytes sent to the provider with their digest and billable-character estimate. | Bound to the attempt and resulting take. It is evidence of what was requested, not a claim that the model achieved an exact acoustic result. |

The existing `EffectiveTakeSettings` remains the exact resolved settings record from
ADR-0008. `EffectiveSynthesisInput` contains or references it; it does not replace the
three-way configuration split.

### 2.2 Accept a hybrid editor

The local operator website provides:

1. ordinary structured controls for speed, volume, emotion, pronunciation-dictionary
   binding and supported render annotations; and
2. an optional **Advanced Cartesia markup** editor for deliberate provider-specific
   authoring.

The advanced editor is not a generic prompt box. The browser may provide immediate
ergonomic feedback, but only server-side validation is authoritative. Before a recipe
can be saved or a provider request can be frozen, the Cartesia anti-corruption layer
must:

- parse the complete input rather than filter it with string replacement;
- allow only tags, attributes, value ranges and nesting supported by the pinned
  model/language/API capability snapshot;
- reject unknown tags, malformed nesting, entity or escaping tricks and unsupported
  combinations;
- translate accepted markup into the provider-neutral `RenderRecipe`;
- prove lexical equivalence with the canonical passage text: no word may be added,
  removed, reordered or substituted through markup; and
- return a preview containing the canonical text intended to be heard/displayed, the
  normalized recipe, the exact provider transcript to be transmitted, warnings and
  the estimated billable character count.

Lexical equivalence uses a versioned, Unicode-aware comparison that preserves Odia
lexical units. A requested lexical or punctuation change is made through a new passage
text revision, never hidden inside the advanced editor. A spelling annotation may
change how existing text is pronounced, but it cannot replace the approved display
text.

Preview is mandatory after any change to text, recipe, effective settings,
dictionary, release contract or provider capability snapshot. Generation uses only a
server-frozen preview result; it never trusts rendered bytes returned by the browser.

### 2.3 Compile through the Cartesia adapter/ACL

Cartesia markup parsing, capability discovery, tag rendering and request DTOs remain
inside the Cartesia adapter/anti-corruption layer. Domain and lane-policy modules know
only `RenderRecipe` and immutable synthesis evidence. The adapter may retain the raw
advanced-editor source and exact rendered provider transcript as private audit
evidence, but provider syntax does not become domain policy or shared neutral code.

For ordinary whole-request speed, volume and emotion, the compiler uses Cartesia's
documented request-level generation configuration. Fine-grained annotations use only
the allowlisted inline features supported by the pinned route. Provider documentation
or runtime acceptance does not turn an unsupported Odia emotion instruction into a
release guarantee; human Odia listening remains authoritative.

The exact UTF-8 provider transcript bytes are frozen before the provider call. Their
SHA-256, byte length, provider-billable character estimate, markup dialect/capability
snapshot and canonical request digest are recorded. Cost preflight is calculated from
that exact rendered transcript under a dated provider billing rule, because Cartesia
documents that supported tags count as characters. Provider-reported usage remains
authoritative after generation. The application core binds these bytes as opaque
evidence; only the Cartesia adapter interprets their provider-specific syntax.

### 2.4 Recipe changes create new production evidence

Changing a recipe never mutates, relabels or overwrites an existing take. Generating
with the changed recipe creates a new `GenerationAttemptId` and, if successful, a new
`TakeId` with a newly frozen `EffectiveSynthesisInput`.

Historical takes remain auditable. When a passage declares a newer recipe revision as
required for selection, takes bound to an older recipe become
**recipe-ineligible**. They are not text-stale if their passage text revision still
matches. Changing a default recipe for future takes does not retrospectively make old
takes ineligible unless the operator explicitly records the new passage requirement.

No render recipe can change a job's lane, speaker, voice, language,
`ReleaseSynthesisContract`, authorization binding, permitted content or release gate.

## 3. Invariants

| ID | Invariant |
|---|---|
| `INV-NJ-11` | Canonical passage text contains no provider markup and remains the sole lexical text used for review and display. |
| `INV-NJ-12` | Every take binds one exact passage text revision, one immutable `RenderRecipe` revision and one immutable `EffectiveSynthesisInput`; their canonical digests are part of the request evidence. |
| `INV-NJ-13` | Advanced markup is accepted only after server-side allowlist, structural, capability and lexical-equivalence validation by the provider ACL. |
| `INV-NJ-14` | The exact rendered provider transcript bytes, digest, dialect/capability snapshot and billable-character estimate are frozen before provider I/O and cannot be supplied authoritatively by the browser. |
| `INV-NJ-15` | A recipe revision cannot alter lane, speaker, voice, language, release contract, authorization scope or canonical lexical content. |
| `INV-NJ-16` | A required-recipe mismatch is recipe-ineligible, never text-stale; another render creates another attempt/take and never rewrites prior evidence. |

These extend ADR-0008's invariant catalogue. ADR-0008's existing IDs and meanings are
unchanged.

## 4. Evidence

| Observation | Consequence |
|---|---|
| Cartesia's [prompting tips](https://docs.cartesia.ai/build-with-cartesia/capability-guides/prompting-tips) describe transcript wording, sentence structure, punctuation and supported tags as the means of directing speech. | Model authoring as exact text plus validated render intent, not an invented free-form instruction field. |
| Cartesia's [SSML-tag guide](https://docs.cartesia.ai/build-with-cartesia/capability-guides/ssml-tags) documents inline speed, volume, emotion, break and spelling tags, labels several controls beta and says tags count as characters. | Pin an allowlist/capability snapshot, preview exact markup, preserve the rendered request and estimate cost from it. Do not freeze today's tag list into the domain. |
| Cartesia's [volume, speed and emotion guide](https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion) recommends request-level generation configuration for ordinary speed/volume control and inline tags for variation within a generation; it also describes controls as guidance rather than strict transforms. | Keep structured request controls distinct from fine-grained render annotations and retain listening review as the quality authority. |
| Cartesia's [TTS endpoint comparison](https://docs.cartesia.ai/use-the-api/compare-tts-endpoints) and API references expose provider request/response capabilities that can change by endpoint, model and language. | Version the provider compilation capability and keep it in an adapter/ACL rather than leaking endpoint DTOs into the domain. |
| ADR-0008 already requires exact text revision, effective settings, dictionary binding, authorization snapshot and artifact reference on every take. | Add recipe and exact-render evidence to the same immutable production event rather than introduce a mutable “prompt” field. |

## 5. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| Store one unrestricted `custom_prompt: string` on the job or take. | Cartesia's TTS interface does not define a general hidden instruction contract, and an arbitrary string could change content or policy without typed validation. |
| Put raw Cartesia markup directly into canonical Odia passage text. | It would corrupt the review/display source, confuse text-stale semantics and couple the domain to one provider's syntax. |
| Offer structured controls only. | It prevents deliberate fine-grained pauses and spelling guidance already supported by the provider and needed for production correction. |
| Trust browser-side validation and preview. | Browser input is not authority under ADR-0008; it is editable, bypassable and cannot bind the exact server-transmitted bytes. |
| Allow arbitrary markup but record only its SHA-256. | A digest proves identity, not safety, lexical equivalence, cost or what the operator was shown before spending credits. |
| Treat every recipe/default change as a text edit. | It would falsely mark lexically identical takes text-stale and erase the useful distinction between source correction and delivery correction. |
| Put Cartesia tags or request DTOs in a shared narration module. | It violates ADR-0006/0009's provider boundary and makes future providers conform to Cartesia syntax rather than the application's render intent. |

## 6. Consequences

- The operator gains precise provider-supported control without gaining an unscoped
  arbitrary-text or policy override.
- The system must implement a real server-side parser/compiler, Unicode-aware lexical
  equivalence, deterministic preview and private retention of exact request evidence.
- Cost preflight becomes more accurate but remains an estimate until Cartesia reports
  usage.
- A provider capability or dialect update can invalidate a preview and require
  recompilation or a new take; it cannot reinterpret an old request silently.
- Review screens must show canonical Odia text separately from normalized recipe and
  exact provider transcript evidence.
- Recipe experimentation produces additional immutable takes and therefore consumes
  credits and storage deliberately.
- The provider-neutral recipe may later support another synthesis adapter, but only
  proven shared semantics may graduate under ADR-0009; raw Cartesia markup never does.
- Acceptance of this record authorizes the architecture and hybrid-editor design. It
  does not itself issue a provider call, approve generated audio or broaden any
  speaker/content authorization.

## 7. Revisit trigger

Write a superseding ADR if any of the following occurs:

- Cartesia introduces a documented semantic instruction/prompt field whose content
  cannot be represented safely as canonical text plus `RenderRecipe`;
- a second production provider cannot express three required accepted recipes without
  provider-specific exceptions in the neutral recipe;
- lexical equivalence rejects three legitimate Odia authoring cases that cannot be
  represented as an explicit text revision plus a supported annotation;
- provider rendering ceases to be deterministic from the frozen input/dialect
  snapshot, preventing the exact transmitted bytes from being established before I/O;
  or
- a measured review workflow requires recipe approval to have an independent owner or
  lifecycle from its passage/job, justifying a separate aggregate rather than a value
  revision.

## 8. What this record does not decide

It does not authorize a new voice, speaker, language, narration lane, arbitrary text,
intro voice or publication; select the exact first-release tag allowlist; guarantee
emotion support for Odia; approve a generated take automatically; choose the web
framework or markup-parser library; define word-timestamp or subtitle policy; or place
background music or video rendering inside Narrator Voice. Those remain governed by
their lane, provider evidence and later production/presentation decisions.
