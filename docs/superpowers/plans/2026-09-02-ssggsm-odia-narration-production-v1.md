# SSGGSM Odia Narration Production v1 Implementation Plan

> **Status (2026-09-03): Historical for remaining work.** Tasks 0 and 1 remain valid
> completed checkpoints and Task 2 remains implementation history. Task 2 closure and
> Tasks 3–5 are replaced by the
> [minimum local-studio plan](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1.md)
> under ADR-0012. Do not resume the full-scope requirements below.

Date: 2026-09-02

Spec: `docs/superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md`

Branch: `feature/narrator-voice-production-v1`

## Goal

Build the accepted local production system for a separately governed Lane-C Odia
intro and Lane-B SSGGSM Odia diary narration. Each fixed-voice job must preserve
exact authoring, generation, review, selection, assembly, listening, authority and
artifact evidence. A `DiaryEpisode` then composes the two immutable dry narration
masters and exports trustworthy sample-based timing for a later Presentation
consumer.

## Global constraints

- The accepted v3 design and ADR-0006 through ADR-0011 are binding when this plan is
  less specific. ADR-0001 and ADR-0005 are accepted in Task 0 before their code rules
  are used.
- Work on the feature only in an isolated linked worktree after the documentation
  baseline commit. Do not push, merge, publish or make a live Cartesia request.
- Never track private Odia text, authorization evidence, API keys, provider voice or
  dictionary IDs, generated/reference audio, raw private timing or production stores.
- Never import or extend `heritage_production`. The future non-SSGGSM English/Hindi
  narration programme remains active and intact; its useful technical knowledge may
  be reused only through characterization, never by importing the shelved package.
- Dependencies point inward. Domain is standard-library plus the accepted kernel;
  application imports domain; infrastructure implements ports; platform is reachable
  only through infrastructure; the composition root is a sink.
- There are exactly three aggregate roots and repositories: `AuthorizationRecord`,
  `NarrationJob`, and `DiaryEpisode`. Passage, take, master, snapshot and timing
  records remain children or immutable values.
- The v3 authority model wins over the roadmap's shorthand status list: registration
  creates an attested active record; the steward may only narrow or irreversibly
  withdraw it. Draft is an editor state, expiry is derived from validity scope, and
  suspension/reactivation are not aggregate transitions.
- Use v3 vocabulary in code: `ReleaseSynthesisContract`,
  `DeliveryControlDefaults`, `EffectiveTakeSettings`, and
  `EffectiveSynthesisInput`.
- Persist canonical integers and decimal strings, never JSON floats. Browser input is
  never authoritative for ActorId, provider transcript, private references or paths.
- Production audio is dry PCM16 little-endian mono 44.1-kHz WAV. Assembly performs
  exact PCM concatenation and explicit zero-sample gaps only; no hidden DSP.
- Production gap values have no built-in numeric default. Private configuration must
  provide them; tests use explicit literals only.
- No automated test contacts Cartesia or consumes credits. The first live call remains
  a later, separately approved gate.
- Follow strict test-first red/green/refactor for production behavior. Documentation,
  generated contracts and dependency lock files are exempt from a contrived RED step.
- Stage and commit exact paths only. Never use `git add -A` in this repository.

## Task 0: Documentation and branch baseline

1. Save this roadmap plus five executable child plans, one for each Task 1-5, under
   `docs/superpowers/plans/`.
2. Change only the status metadata of ADR-0001 and ADR-0005 to
   `Accepted 2026-09-02`; do not alter their decisions.
3. Update the ADR index and dependent documentation that still says ADR-0001 or
   ADR-0005 is proposed/conditional. Preserve the measured lift and its exclusions.
4. Update the root README to name the accepted v3 design and accepted ADR-0009.
5. Ensure `.worktrees/` remains ignored and the SDD scratch workspace self-ignores.
6. Verify links, `git diff --check`, the active 418-test baseline, and the absence of
   private/unrelated files from the exact staged set.
7. Make one local documentation-baseline commit on `main`, without pushing.
8. Create `.worktrees/narrator-voice-production-v1` on
   `feature/narrator-voice-production-v1` and perform all remaining work there.

## Task 1: Package, accepted kernel and architecture guard

1. Characterize the ADR-0001 audited source behavior before extraction. Narrator Voice
   v1 then performs a further consumer-driven trim: lift only the generic symbols with
   accepted v3 consumers—`ActorId`, `ArtifactId`, `ContentDigest`, `ArtifactRef`,
   `TranscriptText`, `ValidationError`, and canonical text/JSON/digest helpers—into
   `src/heritage_archive/kernel/`. Do not retain archive-specific identities, events,
   source/time/ref types, `trust.py`, the `refs.py:78-125` credential block,
   `AggregateEventRecorder`, or archive-specific dependencies. The 1,044-line
   measurement predates recorder removal and is source evidence, not a destination
   claim.
2. Record the exact retained source/symbol manifest and post-trim source count, import
   every retained module/export and retain behavior tests for
   canonical text/JSON, strict parsing, digests, generic artifacts, transcript text,
   ActorId and ArtifactId.
3. Create only the package units with real consumers under
   `contexts/narrator_voice/{domain,application,infrastructure}`,
   `platform/{audio,cartesia,execution,storage,web}`, and `composition_root`.
4. Keep narrator-specific identities, `SafeRelativeArtifactPath` and
   `CanonicalAudioFacts` inside Narrator Voice.
5. Make the existing architecture guard non-vacuous and add concrete tests for
   forbidden outward imports, context isolation, platform isolation, kernel purity,
   composition-root sink behavior and cycles.
6. Run focused RED/GREEN tests, all active suites, package build/import checks and
   `git diff --check`; commit the checkpoint.

## Task 2: Pure domain and no-network application

1. Implement immutable narrator IDs and values for exact NFC Odia text, render
   recipes, fixed release contracts, defaults/effective settings, dictionary and
   authority snapshots, artifacts/media/sample facts, timing values and digests.
2. Implement `AuthorizationRecord` with append-only initial attestation, scope
   narrowing and irreversible withdrawal under the bound steward ActorId.
3. Implement `NarrationJob` with fixed contract, ordered revisioned passages,
   generation and narration-assembly attempts, immutable takes/masters/snapshots,
   append-only review/selection/listening decisions and every `INV-NJ-*` guard.
4. Implement `DiaryEpisode` with exact intro/diary snapshots, explicit sample gap,
   assembly attempts, immutable dry masters, listening, timed package versions and
   every `INV-DE-*` guard.
5. Define only aggregate repositories plus application-owned ports for authority
   status, artifacts, recipe compilation, synthesis, media, timing, budgets, actor,
   clock and identifiers. The status reader delegates to the same canonical
   authorization storage; the budget ledger is not another aggregate.
6. Implement frozen command/result/dependency structures and handlers for every v3
   authority, narration and episode use case, plus timing review and all three
   reconciliation flows.
7. Use a fake recipe compiler/provider/media boundary for the no-network slice.
   Structured and advanced views resolve to one recipe and exact effective input.
8. Enforce: 8,000 text scalars; 16,384 advanced UTF-8 bytes; 64 total controls;
   16 breaks of 10 ms-5 s and 20 s total; 16 speed, volume and spell controls; spell
   spans of at most 64 scalars with no nesting. Emotion remains request-level.
9. Execute the complete fake Lane-C + Lane-B + episode walkthrough and commit only
   after invariant, handler, architecture and active repository suites pass.

## Task 3: Durable storage, recovery, canonical audio and operations

1. Require explicit external `CARTESIA_NARRATION_ROOT`; add no default and no `.env`
   loader. `init` writes private JSON configuration with stable ActorId, labels,
   opaque private bindings, attestations, required gap values and mandatory per-take,
   per-run, project and billing-cycle caps. `CARTESIA_API_KEY` remains environment-only.
2. Implement exactly three filesystem repositories using immutable revision bundles:
   fully flushed and digest-verified `staging/<uuid>` bundles atomically become
   no-clobber zero-padded `revisions/<n>` directories. Current state is the highest
   contiguous valid revision; there is no mutable HEAD.
3. Use OS-backed locks, expected-revision CAS, strict safe relative paths, containment
   and reparse-point checks. Preserve/report incomplete staging and quarantine; never
   silently delete it.
4. Implement immutable artifact publication, SHA-256 and decoded media facts. Inspect
   canonical WAV, reject zero/all-digital-silence/wrong-format audio, and assemble
   exact PCM with deterministic half-up millisecond-to-sample conversion.
5. Guarantee component/passage sample offsets. Preserve raw word timing as untrusted
   until bounds, monotonicity, text mapping and human review pass; never fabricate.
6. Implement an atomically locked generation budget ledger with reserve/settle/
   release/hold-for-reconciliation semantics across jobs.
7. Add `init`, `doctor`, `backup`, `verify-backup`, `restore`, `reconcile`, and `serve`
   commands. Backup uses a second explicit destination and hash manifest; restore only
   targets an empty root. Nothing is automatically deleted.
8. Add crash/fault-injection, Windows lock, path, backup/restore, byte-exact audio and
   restart tests; run all gates and commit.

## Task 4: Cartesia anti-corruption layer

1. Add exact narrator dependencies through a dedicated optional extra and
   `requirements-narrator.lock.txt`: HTTPX 0.28.1 and defusedxml 0.7.1. Do not use the
   Cartesia SDK or `httpx-sse`.
2. Parse advanced markup with defusedxml inside the Cartesia ACL. Reject declarations,
   DTD/entities, unknown tags/attributes, invalid nesting, unsupported capabilities
   and any lexical projection not exactly equal to NFC `PassageText`.
3. Implement a strict incremental UTF-8 SSE parser over HTTPX and the frozen request:
   `/tts/sse`, `Cartesia-Version: 2026-08-14`, model
   `sonic-3.6-2026-08-27`, `language: or`, no `locale`, `normalization: off`, raw
   `pcm_s16le` at 44100, timestamps on, phonemes off and normalized timestamps off.
4. Serialize Odia without ASCII escaping, map decimal strings to JSON numbers only at
   the boundary, and prove previewed transcript bytes equal transmitted bytes. Store
   sanitized exact request/response evidence and wrap PCM in canonical WAV.
5. Run one request at a time. Use connect/write 10 s, read-idle 30 s and total 180 s.
   Allow at most three submissions with 1 s/3 s backoff and Retry-After capped at
   30 s. Retry only definite pre-send connection failures, 429, 5xx and pre-audio SSE
   errors. Ambiguous post-send/audio failures become unknown and never auto-retry.
6. Test normal/multibyte/split SSE, timestamps, errors, truncation, retries,
   ambiguity, exact bytes, dictionary evidence and audio wrapping using sanitized
   fixtures only. Run all gates and commit.

## Task 5: Secured Starlette API and React workflow console

1. Add optional/runtime pins Starlette 1.6.0 and Uvicorn 0.52.4. Use HTTPX
   `ASGITransport` or a raw ASGI harness for backend tests, not Starlette TestClient.
2. Keep framework-neutral inbound DTO/handler mapping in Narrator Voice
   infrastructure; generic Starlette mechanics in `platform/web`; a sequential task
   runner in `platform/execution`; and all wiring in
   `composition_root/narrator_console.py`.
3. Track `/api/v1` OpenAPI under `contracts/narrator_console/v1/openapi.json`; reject
   unknown fields. Existing-root mutations require `expectedRevision`. Long commands
   reserve attempts/budget synchronously, return 202 and poll persisted state.
4. Bind exactly `127.0.0.1:8765`, one worker, no proxy trust or CORS. Implement a
   random 256-bit per-process session and separate in-memory CSRF token with
   constant-time checks, host-only HttpOnly SameSite=Strict cookie, exact Host/Origin,
   fetch metadata/content type/body limits, CSP/security headers, server ActorId and
   opaque media routes. Never expose secrets, private IDs or paths.
5. Build `apps/narrator_console` with Node 24.20.0, React/DOM 19.2.8,
   `react-router` 8.3.1, TanStack Query 5.102.2, Vite 8.2.2 and TypeScript 6.0.2.
   Commit exact npm locks; use semantic HTML/plain CSS, no remote fonts/framework.
6. Implement workflow-first screens for readiness/authority, jobs, ordered hybrid
   Odia editing, validation/budget, generation/reconciliation, take review/selection,
   narration mastering/listening, episode composition/listening, timing handoff and
   storage/backup status.
7. Keep browser state non-authoritative: no persisted query cache, optimistic writes,
   mutation retries or localStorage authority. Show explicit 409 reload/reapply flow;
   render advanced markup as inert text.
8. Cover backend security/contracts, frontend accessibility/state, and three complete
   fake Playwright workflows. Run Python suites, npm lint/typecheck/test/build,
   Playwright Chromium, packaging/import and `git diff --check`; commit.

## Final verification and rollout boundary

- Re-run all active Python suites and the characterized storage/media set, package
  build/import checks, every frontend gate, secret/private-file scan and a complete
  requirements checklist.
- Obtain an independent whole-branch review and fix Critical/Important findings.
- Do not merge or push automatically. Present the tested feature branch for the
  operator's integration choice.
- After integration, private provisioning, `doctor` and verified backup are required.
  Stop for explicit approval before the first chargeable SSGGSM and intro smoke calls.
