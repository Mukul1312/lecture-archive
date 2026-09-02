# SSGGSM Odia Narration Production v1 — Task 2: Pure Domain and No-Network Application

**Goal:** Deliver the three aggregate roots, immutable values, ports and fake-adapter
walkthrough without a provider or filesystem dependency.

**Spec:** `docs/superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md`

## Global constraints

- The accepted v3 design and ADR-0006 through ADR-0011 bind whenever this plan is less specific; ADR-0001 and ADR-0005 are accepted.
- Perform this feature work only in the isolated linked worktree created after the documentation baseline commit; do not push, merge, publish or make a live Cartesia request.
- Never track private Odia text, authorization evidence, API keys, provider IDs, generated/reference audio, raw private timing or production stores.
- Existing tracked `data/narration/**` is frozen legacy evidence and is not read by Narrator Voice.
- Never import or extend `heritage_production`. The future non-SSGGSM English/Hindi narration programme remains active and intact; its useful technical knowledge may be reused through characterization only.
- Dependencies point inward: domain uses only stdlib plus kernel; application imports domain/ports; infrastructure implements ports and may reach platform; platform never imports a context; composition root is the sole sink/wiring boundary.
- There are exactly three aggregate roots/repositories: `AuthorizationRecord`, `NarrationJob`, and `DiaryEpisode`.
- The v3 authority model wins: initial active attestation, narrowing and irreversible withdrawal only.
- Use v3 vocabulary: `ReleaseSynthesisContract`, `DeliveryControlDefaults`, `EffectiveTakeSettings`, and `EffectiveSynthesisInput`.
- Persist canonical integers and decimal strings, never JSON floats; browser input is non-authoritative.
- Production audio is dry PCM16 little-endian mono 44.1-kHz WAV with exact PCM assembly and explicit zero-sample gaps only.
- Production gaps have no numeric default; private configuration supplies them and tests use explicit literals.
- No automated test contacts Cartesia or consumes credits.
- Follow RED/GREEN/refactor for production behavior; stage/commit exact paths only and do not push, merge or publish.

## Execution

- [ ] Test then implement immutable narrator IDs and values for NFC Odia text, render recipes, fixed contracts, defaults/effective settings, dictionary/authority snapshots, artifacts/media/sample facts, timing values and digests.
- [ ] Test then implement `AuthorizationRecord`: append-only initial attestation, scope narrowing and irreversible withdrawal by the bound steward ActorId.
- [ ] Test then implement `NarrationJob`: fixed contract, ordered revisioned passages, generation and narration-assembly attempts, immutable takes/masters/snapshots, append-only review/selection/listening decisions, and every `INV-NJ-*` guard.
- [ ] Test then implement `DiaryEpisode`: exact intro/diary snapshots, explicit sample gap, assembly attempts, immutable dry masters, listening, timed-package versions, and every `INV-DE-*` guard.
- [ ] Define only aggregate repositories and application-owned ports for authority status, artifacts, recipe compilation, synthesis, media, timing, budgets, actor, clock and identifiers. The status reader delegates to canonical authorization storage; the budget ledger is not an aggregate.
- [ ] Implement frozen commands/results/dependencies and handlers for v3 authority, narration and episode use cases, timing review and all three reconciliation flows.
- [ ] Use fake recipe compiler/provider/media boundaries. Structured and advanced views must resolve to one recipe and one exact effective input.
- [ ] Enforce exactly: 8,000 text scalars; 16,384 advanced UTF-8 bytes; 64 total controls; 16 breaks of 10 ms–5 s and 20 s total; 16 speed/volume/spell controls; spell spans up to 64 scalars without nesting; emotion request-level only.
- [ ] Execute the complete fake Lane-C, Lane-B and episode walkthrough; run invariant, handler, architecture and active repository suites; then commit the exact checkpoint.

## Handoff to Task 3

- [ ] Freeze schema versions and serialization DTOs before persistence: every attempt
  state (`blocked`, `failed`, `unknown`, `quarantined`, `completed`), media and timing
  facts, preview and `EffectiveSynthesisInput`, provider-event stream, attempt
  workspace, and artifact publication/reference DTOs. Task 3 must persist these
  shapes without redefining their semantics.

## Verification

- Fakes prove no network generation occurs.
- Every protected transition has named invariant coverage and expected-revision refusal.
- The complete two-job plus episode walkthrough yields only dry, fake evidence.
