# SSGGSM Odia Narration Minimum Local Studio v1 Implementation Plan

> **For agentic workers:** implement one small vertical slice at a time. Report
> `implemented`, `smoke-verified` and `hardened` separately. Do not expand a slice to
> exhaustive hardening unless its named pre-live gate has arrived.

**Goal:** Finish a simple, restart-safe, single-operator local studio for the accepted
Lane-C intro and Lane-B SSGGSM Odia diary workflow.

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
- Work only in `feature/narrator-voice-production-v1`; do not push, merge, publish or
  make a live Cartesia request.
- Never track private text, authorization evidence, provider IDs, keys, generated or
  reference audio, raw private timing or production stores.
- Keep exactly three aggregate roots/repositories. Add no Master repository, budget
  aggregate, CQRS/event-sourcing layer or generic workflow engine.
- Keep dry PCM16 little-endian mono 44.1-kHz WAV, exact PCM assembly and explicit
  sample gaps. Add no hidden DSP, music or resampling.
- Use risk-based verification: minimal focused checks now, named hardening before the
  first real paid/private call, and broad suites only at meaningful checkpoints.
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

- [ ] Confirm the smallest current supported HTTP/parser dependency set immediately
  before implementation; do not add a provider-generic transport framework.
- [ ] Support the one fixed Odia synthesis route and only the structured/advanced
  markup controls used by the initial workflow.
- [ ] Preserve exact UTF-8 preview-to-transmission bytes, fixed contract fields,
  private dictionary binding, canonical raw PCM wrapping and sanitized evidence.
- [ ] Use bounded timeouts and conservative retry classification. Any ambiguous
  post-send/audio outcome becomes `unknown` and is never automatically repeated.
- [ ] Preserve raw timestamps if returned, but do not normalize or claim word timing.
- [ ] Smoke-verify exact request bytes, one multibyte SSE stream, terminal success,
  terminal failure, truncation and retry ambiguity using sanitized fixtures only.

## Task 5M — minimum loopback studio

**Produces:** one local website and `serve` composition root over the persisted
application handlers.

- [ ] Choose the smallest frontend only after Task 3M works. React/OpenAPI generation
  is optional rather than preselected.
- [ ] Bind one worker to `127.0.0.1`; resolve ActorId server-side and enforce a process
  session, exact Host/Origin and anti-forgery checks on mutations.
- [ ] Never expose credentials, private provider IDs or absolute artifact paths;
  provide opaque checked audio playback routes.
- [ ] Implement only readiness/authorization, passage/recipe editing, preview/budget,
  sequential generation/recovery, take review/selection, narration assembly/listening,
  episode assembly/listening and backup status.
- [ ] Keep browser state non-authoritative and show stale-revision/unknown outcomes.
- [ ] Smoke-verify one complete fake intro-plus-diary workflow and focused mutation
  security checks. Do not build duplicate browser journeys or a comprehensive audit
  explorer.

## Pre-live hardening gate

This gate may run after Tasks 4M/5M, but it must pass before the first real paid or
private generation:

- [ ] Exercise representative restart boundaries around provider send, artifact
  publication and aggregate finalization.
- [ ] Verify stale revisions, immutable artifacts, exact WAV/PCM and unknown budget
  holds using the durable adapters.
- [ ] Create, verify and restore one complete backup into an empty temporary root.
- [ ] Run the focused Narrator Voice suite, architecture checks, package/import checks,
  one active repository regression checkpoint and `git diff --check`.
- [ ] Scan the exact staged set for private IDs, keys, text and audio.
- [ ] Stop and request explicit operator approval before any chargeable Cartesia call.

Contingency is not a scheduled phase. If an actual defect appears, record the defect,
its impact and the additional time separately.
