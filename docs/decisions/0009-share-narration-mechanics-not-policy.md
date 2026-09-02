# ADR-0009 — Share provider-neutral narration mechanics, never lane policy

**Date:** 2026-09-02 · **Status:** **Accepted 2026-09-02** · **Governs:** technical capability
shared, or considered for sharing, between Narrator Voice policy scopes
**Supersedes:** nothing · **Superseded by:** —

Evidence: [Narrator Voice shared-capability audit](../narrator-voice-shared-capability-audit-2026-09-02.md)

**Pre-acceptance revision:** The same 2026-09-02 acceptance pass generalized this
boundary's wording from Lane A/Lane B to Narrator Voice policy scopes after ADR-0011
introduced narrow Lane C. The sharing and promotion rule itself did not change.

---

## 1. Context

ADR-0007 keeps two narration programmes active:

- Lane A will produce non-SSGGSM English/Hindi narration and must reject SSGGSM
  resemblance; and
- Lane B may faithfully reproduce the authorized SSGGSM Cartesia voice, but only for
  reviewed Odia diary narration.

ADR-0011 adds one narrower Lane-C consumer for a fixed-voice Odia diary-episode intro.
It remains a policy scope inside Narrator Voice, not a new bounded context.

These policy scopes need files, hashes, synthesis attempts, audio inspection,
listening review and assembly. They must not share speaker permission,
language/content scope, identity criteria or release authority. The repository also
contains three very different
sources of apparent reuse: active production packages, loose historical scripts and a
large shelved DDD package. Calling all three “reusable code” would hide materially
different risks.

## 2. Decision

### 2.1 The allowed neutral boundary and its layers

The following capabilities may become provider-neutral Narrator Voice mechanics:

1. canonical serialization, opaque IDs and content digests;
2. safe relative artifact references, hashing and media facts;
3. path-containment/reparse checks, OS locking, expected-revision/CAS and atomic
   publication;
4. narrow provider-neutral retry classification and attempt facts, after Lane B proves
   them;
5. media probing/inspection and ordered assembly primitives, with Lane-B output-WAV
   decode/contract validation implemented as a new requirement;
6. Lane-B-local append-only, actor-attributed review records, eligible for sharing only
   after another real consumer proves identical semantics; and
7. synthesis/media/artifact ports that accept an **already resolved lane request**.

“Neutral” does not mean “put it all in `kernel/`”:

- ADR-0001 independently governs its accepted one-time, trimmed, measured kernel lift;
  its exact source-and-symbol manifest is characterized and remeasured after
  exclusions. After that lift, a **new** symbol enters the repository-wide
  `kernel/` only when it genuinely crosses two bounded contexts, as ADR-0005 requires;
- a port belongs in Narrator Voice `domain/ports.py`; the first synthesis port is
  Lane-B-driven but may serve multiple policy scopes because they are one context;
- filesystem/media implementations belong in context infrastructure; a cross-cutting
  `platform/<primitive>` is created at its first real consumer, while Cartesia SDK
  imports remain platform/infrastructure boundary code under ADR-0005; and
- mechanics shared by Narrator Voice policy scopes but no other bounded context remain neutral
  **inside Narrator Voice**, not in the global kernel.

The neutral boundary is structurally forbidden from containing:

- SSGGSM identity or authorization rules;
- a default language, voice, provider or model;
- resemblance/dissimilarity thresholds;
- permitted-text or distribution policy;
- native-Odia or automated release authority; or
- Cartesia SDK/request types.

Lane A, Lane B and Lane C keep separate domain/application policy modules and separate tests
for scope, speaker identity, languages, provider/voice eligibility and review/release
authority. Sharing a transport interface does not mean sharing a request policy.

### 2.2 Reuse means four different things

| Classification | Rule |
|---|---|
| **Governed direct lift** | The accepted ADR-0001 permits only its exact trimmed source-and-symbol manifest after characterization and post-exclusion remeasurement. Never import the shelved package in place. |
| **Extract after characterization** | Proven active mechanics in `ggsm_transcription/store.py`, `youtube_enhance/workflow_state.py` and related manifest/media code may be moved behind narrow tests. Do not make Narrator Voice depend on another context's job model. |
| **Design precedent only** | Static galleries, review pages and ordered-join scripts may inform interaction and algorithms, but are reimplemented behind durable commands because their paths, browser state and policies are coupled to experiments. |
| **Prohibited from Lane-B policy; Lane-A evidence only where applicable** | Old Hindi dissimilarity/automatic-selection logic, VoxCPM/LoRA workflows and Hindi ASR/transliteration cannot enter Lane-B policy. The dissimilarity material remains Lane-A historical evidence; all files remain preserved. |

### 2.3 Do not extract speculatively

ADR-0001's accepted measured lift is independently governed and is not re-decided
here. For symbols added after that lift, ADR-0005's graduation rule applies: a symbol
enters the global shared kernel only when it has two real **bounded-context** consumers.
Lane A, Lane B and Lane C are policy
scopes of one Narrator Voice context, not separate contexts. A narrow mechanic starts
inside its first real consumer. When another Narrator Voice policy scope proves the
same semantics, it may graduate to a neutral Narrator Voice module. Only if another
bounded context also needs it may it graduate to `kernel/`.
Extract the smallest proven primitive; do not copy it and do not move a whole aggregate.

This decision therefore approves a **boundary and promotion rule**, not a Day-1 folder
full of abstractions.

## 3. Evidence

| Capability | Repository evidence | Classification |
|---|---|---|
| Canonical JSON, digests and opaque IDs | `src/heritage_production/domain/shared/canonical.py`, `digests.py`, `ids.py`; ADR-0001 records the exact manifest, exclusions and post-exclusion remeasurement requirement. | Governed direct lift. |
| Safe artifacts, locks, monotonic revisions and atomic replacement | `scripts/ggsm_transcription/store.py`; `scripts/youtube_enhance/workflow_state.py` and `manifest.py`. | Extractable mechanics after characterization. Expected-revision/CAS remains a new Lane-B requirement. |
| Typed workflow/review evidence | `scripts/ggsm_transcription/review.py`; `scripts/youtube_enhance/manifest.py`. | Reuse narrow patterns/helpers, not either job aggregate. |
| Media probing/inspection and ordered concatenation | `scripts/ggsm_transcription/intake.py`; `scripts/youtube_enhance/gates.py`; `scripts/hi/reconcat_diary.py`. | Extract characterized inspection/assembly pieces only; order comes from the approved manifest. Output-WAV decode/format-contract validation is new Lane-B work. |
| Master/passage playback, alternatives and notes | `scripts/build_narration_gallery.py`, `scripts/build_odia_check_site.py` and other galleries. | Design precedent only; browser state is not authority. |
| Blind A/B | `scripts/build_odia_check_site.py`. | Optional technique for deliberate comparisons, never normal state identity. |
| Signal diagnostics | `scripts/voice_quality.py`; `scripts/youtube_enhance/gates.py`. | Advisory neutral capability; not a Lane-B approval gate. |
| Cost, retry and resume rules | The accepted narration production design. | Start within the producing scope. Only low-level retry classification/attempt facts are candidates after a second matching consumer; budget, authorization, identity and eligibility remain policy. |

The full audit records exact locations, defects and policy hazards rather than
repeating them all here.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| Copy the Hindi pipeline and invert the resemblance threshold | Language, provider, reference-audio and automatic release assumptions remain wrong even after one threshold is reversed. |
| Import `heritage_production` as a framework | It is explicitly shelved, its application/review model has known defects and its tests do not prove a running narration flow. |
| Put every neutral-looking helper in a shared package now | Lane A is not implemented. Premature abstractions would encode Lane-B assumptions before a second consumer tests the boundary. |
| Share one generic `allow_clone`/`language` policy object | A switch does not express Lane A and Lane B's opposite identity rules or the scopes' different authorization/release authorities safely. |
| Share nothing | It would duplicate solved hashing, safe-storage and media mechanics and invite inconsistent artifact identity. |

## 5. Consequences

- The narration implementation plan must label each reused element as a direct lift,
  extraction or precedent; “reuse the old workflow” is not an acceptable task.
- Architecture tests can forbid provider imports and lane-policy symbols in neutral
  modules.
- Some useful mechanics remain policy-scope-local initially. That is deliberate evidence
  gathering, not a rejection of reuse.
- ADR-0001 remains independently accepted; this ADR cannot widen or unfreeze anything
  beyond its exact kernel manifest.
- Historical scripts stay runnable evidence under their existing retention decisions;
  this decision neither deletes nor modernizes them.

## 6. Revisit trigger

Revisit if:

- a second real consumer needs materially different semantics from a neutral
  primitive;
- three lane-policy exceptions appear in shared code;
- direct extraction would require importing another context's aggregate or manifest;
- ADR-0001 is superseded or found infeasible, requiring a clean replacement for canonical IDs/digests; or
- two Narrator Voice policy scopes develop different ubiquitous language and ownership sufficient to
  become separate bounded contexts.

## 7. What this record does not decide

It does not select Lane A's provider/narrator, authorize any lane, choose package
names, approve a specific extraction patch, or start implementation.
Acceptance records the steward's choice of this codebase-wide boundary; it does not
authorize a provider call, a particular extraction patch or any lane's release.
