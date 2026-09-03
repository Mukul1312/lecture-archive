# SSGGSM Odia Narration Production v1 — Task 3: Durable Storage, Audio and Operations

> **Status (2026-09-03): Superseded before implementation.** This plan is the
> historical hardened profile and must not be executed for v1. Use the executable
> [Task 3M durable filesystem and audio plan](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-3m-durable-filesystem-audio.md).

**Goal:** Add private durable repositories, canonical audio/artifact handling, recovery
and operator commands without changing the domain boundaries.

**Spec:** `docs/superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md`

## Global constraints

- Accepted v3 and ADR-0006 through ADR-0011 bind; ADR-0001/0005 are accepted.
- Perform this feature work only in the isolated linked worktree created after the documentation baseline commit; do not push, merge, publish or make a live Cartesia request.
- Never track private text/evidence/keys/provider IDs/audio/raw timing/stores; frozen `data/narration/**` is never read.
- Never import or extend `heritage_production`. The future non-SSGGSM English/Hindi narration programme remains active and intact; its useful technical knowledge may be reused through characterization only.
- Dependencies point inward: domain uses only stdlib plus kernel; application imports domain/ports; infrastructure implements ports and may reach platform; platform never imports a context; composition root is the sole sink/wiring boundary.
- Exactly three aggregate roots/repositories exist: `AuthorizationRecord`, `NarrationJob`, `DiaryEpisode`.
- v3 authority transitions, v3 vocabulary, canonical integers/decimal strings and non-authoritative browser input are mandatory.
- Audio is dry mono PCM16 little-endian 44.1-kHz WAV, assembled as exact PCM plus explicit zero gaps only.
- Production gaps have no default; tests use explicit literals. No automated Cartesia/credit use is allowed.
- Use RED/GREEN/refactor, exact staging and local commits only; never push, merge or publish.

## Execution

- [ ] Require an existing, explicit, non-reparse `CARTESIA_NARRATION_ROOT` outside the repository and all worktrees; add neither default nor `.env` loader. `init` writes private configuration with stable ActorId, labels, opaque bindings, attestations, gaps and mandatory per-take/per-run/project/billing-cycle caps; `CARTESIA_API_KEY` remains environment-only.
- [ ] Implement exactly three filesystem repositories with flushed/digest-verified `staging/<uuid>` revision bundles atomically becoming no-clobber `revisions/<n>` directories. Current state is highest contiguous valid revision; no mutable HEAD.
- [ ] Add OS locks, expected-revision CAS, safe relative paths, containment/reparse checks, and preserved/reported incomplete staging/quarantine; never silently delete. Fix lock order as generation mutex then job lock, never reverse.
- [ ] Publish immutable artifacts with SHA-256 and decoded media facts. Inspect canonical WAV and reject zero/all-digital-silence/wrong-format output. Assemble exact PCM with deterministic half-up millisecond-to-sample conversion.
- [ ] Guarantee component/passage sample offsets. Preserve raw word timing as untrusted until bounded, monotonic, text-mapped human review passes; never fabricate timing.
- [ ] Add an atomically locked budget ledger with reserve/settle/release/hold-for-reconciliation semantics across jobs. Reserved and unknown attempts conservatively consume caps until reconciliation.
- [ ] Implement `init`, `doctor`, `backup`, `verify-backup`, `restore`, `reconcile`, and `serve`; backup needs a second explicit destination and hash manifest, restore targets only an empty root, and no command deletes automatically.
- [ ] Add crash/fault-injection, Windows lock, path, backup/restore, byte-exact audio and restart tests; run all gates and commit.

## Verification

- Private roots and backups are explicit and outside Git.
- Restart/crash tests retain or quarantine evidence without deletion.
- Audio and offsets are byte/sample exact, and all operational commands are tested without Cartesia.
