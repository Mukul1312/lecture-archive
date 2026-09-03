# ADR-0012 — Narrator Voice v1 is a minimum single-operator local studio, not a general production platform

**Date:** 2026-09-03 · **Status:** **Accepted 2026-09-03** · **Governs:**
remaining Narrator Voice v1 implementation, verification and rollout
**Supersedes:** only ADR-0008 §2.1's requirement for a separate physical
snapshot-plus-ledger persistence seam; its aggregate boundary and all other decisions
remain accepted · **Superseded by:** —

Related: [ADR-0006](0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md)
fixes the authorized SSGGSM/Odia scope;
[ADR-0010](0010-cartesia-prompting-is-validated-rendering-evidence.md) keeps hybrid
authoring safe; and
[ADR-0011](0011-diary-episodes-compose-fixed-voice-narration-masters.md) separates the
intro and diary jobs. The minimum implementation profile is in the
[v4 design](../superpowers/specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md).

---

## 1. Context

The v3 production design was intentionally conservative. It combined per-aggregate
locking, separate persistence ledgers, extensive crash/fault matrices, rich timing
review, comprehensive audit screens and a large React/API contract surface. That is
a defensible design for a multi-user or regulated production platform, but it is
larger than the actual first operating model.

The first operator has now confirmed the real v1 boundary:

- one trusted operator on one local Windows machine;
- one running application process and one provider request at a time;
- one Lane-C Odia intro voice and one authorized Lane-B SSGGSM Odia diary voice;
- a later Odia reviewer only when publishing becomes real; and
- no background music, subtitle rendering, video or public distribution in v1.

The first two implementation tasks have already established useful DDD boundaries.
Deleting those types merely to make the source tree look smaller would create more
work without simplifying the operator's workflow. The correction must therefore
reduce new operational machinery and exposed workflow, not start another rewrite.

## 2. Decision

### 2.1 Keep the accepted domain boundary

Retain exactly three aggregate roots and repositories: `AuthorizationRecord`,
`NarrationJob` and `DiaryEpisode`. Retain fixed Lane-B/Lane-C contracts, exact Odia
text and effective settings, immutable takes/audio, append-only human decisions,
current authorization checks, explicit selection, dry assembly and source-job-issued
episode snapshots.

Existing richer Plan 2 values may remain dormant when they are safe. Do not spend a
v1 tranche removing them, create another aggregate, add CQRS/event sourcing, or build
a generic workflow engine.

### 2.2 Make persistence deliberately small

Use one application-wide OS lock because v1 permits only one running writer. Keep
expected-revision checks inside the application. Each of the three repositories
writes one complete canonical JSON aggregate snapshot per immutable revision using a
staged atomic no-clobber publication. The snapshot already contains historical
attempts and decisions; there is no separate physical event or decision ledger.

Keep immutable SHA-256-addressed audio/evidence artifacts and safe relative
references. Preserve and report incomplete staging, but do not add automatic cleanup,
retention, repair, database abstraction or cloud-storage alternatives.

### 2.3 Keep only recovery needed for paid local work

The minimum operator-visible recovery vocabulary is `reserved`, `blocked`,
`completed`, `failed` and `unknown`. `Blocked` means that provider work definitely
did not begin, for example because budget, authority or a pre-send check refused it.
Existing internal progress and evidence states such as input frozen, work started or
quarantined may remain without becoming extra operator workflows.
An ambiguous post-send Cartesia operation is `unknown` and is never repeated
automatically.

Persist per-take, per-run and billing-cycle caps. Reserve before sending, settle known
usage, release definite pre-send failures and hold unknown attempts. The budget ledger
is an application service, not a fourth aggregate. Its one canonical local record is
`operations/budget-ledger.json`: append-only facts stored by atomic file replacement
under the same application-wide writer lock.

### 2.4 Build the minimum local studio

The local website needs only readiness/authorization, passage authoring and preview,
generation status, take review/selection, narration assembly/listening, episode
assembly/listening and backup status. It stays loopback-only, resolves the operator
server-side and never exposes keys, private voice IDs or absolute paths.

The frontend framework, generated OpenAPI client, generalized background runner and
comprehensive audit explorer are not architectural requirements. Task 5 must select
the smallest implementation that serves the workflow. Multi-user login, reviewer
roles and remote access wait for the publishing decision.

### 2.5 Keep trustworthy base timing; defer word timing

Exact component and passage sample offsets remain part of canonical assembly. Raw
provider timing may be retained as private evidence. Word-level normalization,
qualified review, correction UI, alignment fallback and word-synchronous delivery are
deferred. The system must omit unsupported timing rather than invent it.

### 2.6 Separate implementation, smoke verification and hardening

Track work as `implemented`, `smoke-verified` and `hardened`.

- A slice may advance after the smallest focused check proves its contract.
- Broad suites, exhaustive fault permutations and independent review run at meaningful
  checkpoints, not after every edit.
- Storage, budget, recovery, audio integrity and backup must be hardened before the
  first real paid/private generation, even if Plans 4 and 5 begin earlier with fakes.
- Contingency is not scheduled work; record it only when an actual defect occurs.

No automated test may contact Cartesia or consume credits. A live call still requires
separate explicit operator approval.

## 3. Evidence

| Observation | Consequence |
|---|---|
| The confirmed initial workflow has one local operator and no simultaneous reviewer. | A single process-wide writer lock is sufficient for v1. |
| The Narrator Voice package already has domain/application behavior and ports but no production infrastructure adapters. | Simplify the adapters still to be built rather than rewrite the completed boundary. |
| The v3 Task 3 requires separate ledgers, nested locks, exhaustive recovery and timing work. | Its operational profile is historical, not the remaining v1 implementation authority. |
| Cartesia calls spend credits and may have ambiguous post-send outcomes. | Minimal durable reservation, evidence and `unknown` handling remain necessary. |
| Generated takes and human review decisions are expensive to reproduce. | Immutable artifacts, restart-safe state and a verified full backup remain in v1. |

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| Continue the complete v3 platform plan now | It optimizes for concurrency, audit and timing consumers that do not exist and delays the usable studio. |
| Replace the DDD model with one script and mutable folders | It would discard already-built rules and make paid attempts, review choices and exact episode assembly difficult to recover safely. |
| Rewrite Plan 2 to delete every dormant type | Source-code reduction would cost more than it saves and risks reopening settled voice, authorization and episode rules. |
| Skip all verification until the end | A persistence or audio defect would contaminate every later layer and make failures harder to locate. |

## 5. Consequences

- V1 remains a production tool, but only for one local operator and the two accepted
  fixed-voice Odia roles.
- The code keeps clean inward dependencies and explicit provider/storage ports without
  building generic frameworks.
- Some implemented Plan 2 types will not appear in the first UI. Dormant does not mean
  authoritative or required for v1 completion.
- Cold full backups require the application writer to be stopped or exclusively
  locked. Incremental and online backups are future work.
- Moving quickly transfers some broad verification to a named pre-live hardening gate;
  it does not waive that gate for paid/private production.
- The v3 design and its original task plans remain historical evidence, but the linked
  v4 design and replacement plan govern remaining work.

## 6. Revisit trigger

Write a superseding ADR when any of these is observed:

- a second operator or reviewer must write concurrently;
- the application must run more than one worker/process or on more than one machine;
- three real recovery incidents cannot be resolved from the minimum evidence;
- a Presentation consumer requires reviewed sentence/word timing;
- scheduled, incremental, encrypted or remote backup becomes an operating requirement;
  or
- a publishing workflow establishes concrete identity, role and release-signoff rules.

## 7. What this record does not decide

It does not widen either voice authorization, change language/model contracts,
authorize a live request or publication, select the eventual frontend framework, or
add Presentation concerns. It does not weaken exact preview-to-request binding,
immutable audio, current authorization checks, human listening, budget holds for
unknown work, or the no-private-data-in-Git rule.
