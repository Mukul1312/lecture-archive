# SSGGSM Odia Narration Minimum Local Studio v1 Implementation Plan

> **For agentic workers:** implement one small vertical slice at a time. Report
> `implemented`, `smoke-verified` and `hardened` separately. Do not expand a slice to
> exhaustive hardening without an observed defect or a release checkpoint.

**Goal:** Finish a simple, restart-safe, single-operator local studio for the accepted
Lane-C intro and Lane-B SSGGSM Odia diary workflow.

**Operational scope update (2026-09-11):** the current production requirement is
Lane-B diary narration only. Preserve the completed Lane-C introduction capability
and all of its tests, but leave it dormant during configuration and controlled live
validation. Do not create, authorize, generate, select or assemble an intro job
unless the operator explicitly restores that requirement.

**Architecture:** Preserve the existing three aggregate roots and inward dependency
rule. Add only concrete local filesystem, audio, Cartesia and loopback-web adapters;
do not create generic frameworks or rewrite safe dormant Plan 2 types.

**Tech stack:** Python 3.11, standard-library filesystem/WAV facilities, the minimum
HTTP client/parser needed for Cartesia, and the smallest loopback web frontend chosen
at Task 5.

**Spec:**
`docs/superpowers/specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md`

## Global constraints

- ADR-0012 and the v4 design govern remaining v1 work. ADR-0006 through ADR-0011
  continue to govern the domain/policy decisions they retain.
- Continue on `main`; do not push, merge or publish without separate instruction.
- Never track private text, authorization evidence, provider IDs, keys, generated or
  reference audio, raw private timing or production stores.
- Keep exactly three aggregate roots/repositories. Add no Master repository, budget
  aggregate, CQRS/event-sourcing layer or generic workflow engine.
- Keep dry PCM16 little-endian mono 44.1-kHz WAV, exact PCM assembly and explicit
  sample gaps. Add no hidden DSP, music or resampling.
- Use risk-based verification: preserve every existing test, run the smallest affected
  modules during development, and run broad suites only at major integration or
  release checkpoints.
- Stage exact paths only. Preserve unrelated and interrupted worktree changes.

## Task 2C — close only the persistence-critical Plan 2 findings

**Files:** existing Narrator Voice domain/application modules and their focused tests.

**Detailed executable plan:**
[Task 2C Recovery Closure](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-2c-recovery-closure.md).

The detailed plan records which recovery behavior is already implemented and limits
the remaining work to snapshot/selection authenticity, frozen-plan evidence, an
explicit media-recovery port and evidence-before-CAS ordering. It is the authoritative
execution basis for Task 2C.

- [x] Preserve workspace/artifact/budget evidence when a post-side-effect save
  conflicts; ambiguous provider work must remain recoverable and must not be retried.
- [x] Bind recovered narration and episode masters to the exact frozen source
  takes/snapshots and gaps.
- [x] Reject a narration snapshot not issued by its current source job.
- [x] Reject rehydrated selection made after the take's latest operational rejection.
- [x] Run only the focused affected tests and the Narrator Voice architecture check.
- [x] Record coding and smoke verification separately; make exact local task checkpoints
  only after their focused checks pass.

Word-timing display/review hardening is deferred because v1 does not deliver trusted
word timing. Do not rewrite other safe Plan 2 types merely to reduce line count.

## Task 3M — minimum durable filesystem and audio

**Produces:** concrete implementations of the existing three repository ports,
artifact/workspace storage, media inspection/assembly, budget ledger and operational
commands.

**Detailed executable plan:**
[Task 3M Durable Filesystem and Audio](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-3m-durable-filesystem-audio.md).

- [x] Require explicit external `CARTESIA_NARRATION_ROOT`; implement private config
  and `init` without an `.env` loader. Keep the API key environment-only.
- [x] Implement one application-wide OS writer lock plus expected-revision checks.
- [x] Persist one canonical full snapshot per immutable aggregate revision using
  staged, digest-verified, atomic no-clobber publication. Do not create physical event
  or decision ledgers.
- [x] Publish immutable artifacts with SHA-256, byte length, decoded facts and safe
  relative paths. Preserve/report incomplete staging without automatic repair.
- [x] Inspect canonical non-empty/non-silent WAV and assemble exact narration/episode
  PCM with explicit gaps and component/passage sample offsets.
- [x] Persist append-only reserve/settle/release/hold budget facts in the single
  non-aggregate `operations/budget-ledger.json`, atomically replaced under the
  application-wide lock, with per-take, per-run and billing-cycle caps.
- [x] Implement evidence-based `reconcile`, plus `doctor`, full locked `backup` and
  `verify-backup`, plus `restore` restricted to an empty destination; rehearse one
  verified restore into an empty temporary root. Put `serve` in Task 5M.
- [x] Smoke-verify save/restart/load, stale revision refusal, no-clobber artifact
  publication, exact PCM/offsets, unknown budget hold and one backup round trip.

Defer exhaustive crash windows, lock/path matrices, cleanup/retention engines,
incremental backup and cloud/database storage.

## Task 4M — minimum Cartesia adapter

**Produces:** one sequential Cartesia synthesis adapter behind the existing
application port, with sanitized evidence and no automated live calls.

**Detailed executable plan:**
[Task 4M Cartesia Adapter](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-4m-cartesia-adapter.md).

Task 4M is implemented and smoke-verified, not hardened. Its fixture-only result was
merged locally into `main` through checkpoint `3f6b00b`; the detailed plan retains
the implementation evidence and unresolved live-operation limitations.

- [x] Confirm the smallest current supported HTTP/parser dependency set immediately
  before implementation; do not add a provider-generic transport framework.
- [x] Support the one fixed Odia synthesis route and only the structured/advanced
  markup controls used by the initial workflow.
- [x] Preserve exact UTF-8 preview-to-transmission bytes, fixed contract fields,
  private dictionary binding, canonical raw PCM wrapping and sanitized evidence.
- [x] Use bounded timeouts and conservative retry classification. Any ambiguous
  post-send/audio outcome becomes `unknown` and is never automatically repeated.
- [x] Preserve raw timestamps if returned, but do not normalize or claim word timing.
- [x] Smoke-verify exact request bytes, one multibyte SSE stream, terminal success,
  terminal failure, truncation and retry ambiguity using sanitized fixtures only.

## Task 5M — minimum loopback studio

**Produces:** one local website and `serve` composition root over the persisted
application handlers.

**Detailed executable plan:**
[Task 5M Loopback Studio](2026-09-07-ssggsm-odia-narration-minimum-local-studio-v1-task-5m-loopback-studio.md).

The detailed plan selects a server-rendered Starlette boundary with minimal local
JavaScript, records the fresh-store authorization/discovery/playback seams, fixes the
single-episode v1 constraint, and is the authoritative Task 5M execution basis.

Task 5M is `implemented` and `smoke-verified`, not `hardened` (2026-09-09).
The fixture journey closes/rebuilds the real local studio and retains three selected
takes, two listened source masters and one listened episode master with exact PCM
ordering/gaps. After the Windows IPv4/asyncio repair, `socket.socketpair()` and
`asyncio.run()` pass and the complete fixture-only Task 5M checkpoint passes 195/195,
including all eleven async tests. Raw ASGI also verified packaged assets and checked
audio without a listening socket. The current Task 4M regression set passed 227. The
detailed plan records the advancing-clock generation defect found and fixed by the
journey. Whole-branch
review found one malformed-generation-result boundary gap; `0a00936` fixed it and
the original reviewer approved the scoped rereview. Final fixture checkpoints and
offline package/import verification passed at that reviewed head.

- [x] Choose the smallest frontend only after Task 3M works. React/OpenAPI generation
  is optional rather than preselected.
- [x] Bind one worker to `127.0.0.1`; resolve ActorId server-side and enforce a process
  session, exact Host/Origin and anti-forgery checks on mutations.
- [x] Never expose credentials, private provider IDs or absolute artifact paths;
  provide opaque checked audio playback routes.
- [x] Implement only readiness/authorization, passage/recipe editing, preview/budget,
  sequential generation/recovery, take review/selection, narration assembly/listening,
  episode assembly/listening and backup status.
- [x] Keep browser state non-authoritative and show stale-revision/unknown outcomes.
- [x] Smoke-verify one complete fake intro-plus-diary workflow and focused mutation
  security checks. Do not build duplicate browser journeys or a comprehensive audit
  explorer.

## Controlled live validation and deferred hardening

On 2026-09-10 the operator authorized at most ten live Cartesia calls, each no longer
than one minute. Begin with one Lane-B diary call; Lane C remains dormant. Before
every call, require healthy `doctor` output, current authorization, deliberately
configured caps, exact preview confirmation, a single request with no automatic
replay, and checked immutable audio. This approval does not extend beyond the
ten-call/one-minute boundary.

Use the real result to drive the next step. Reproduce any observed defect with the
smallest focused test, preserve existing tests and integrity/hashing behavior, and
fix only that defect. Broader storage, recovery, budget, audio and backup regression
work remains a release checkpoint rather than a prerequisite for this bounded live
validation. Contingency is not a scheduled phase; record actual defects and their
impact separately. Do not create Task 6M.
