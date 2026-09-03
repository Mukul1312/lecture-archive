# Cartesia Odia narration minimum local-studio design — v4

**Date:** 2026-09-03

**Status:** **Accepted implementation scope.**

**Authority:** [ADR-0012](../../decisions/0012-narrator-voice-v1-is-a-minimum-local-studio.md)
narrows the remaining implementation. ADR-0006 through ADR-0011 continue to govern
voice authorization, lane isolation, aggregate identity, hybrid authoring and dry
episode composition wherever ADR-0012 does not explicitly narrow operational depth.

This document replaces the
[v3 production design](2026-09-02-cartesia-odia-narration-production-v3-design.md) as
the implementation authority for the remainder of v1. V3 remains historical design
evidence and a possible source of later hardening requirements.

## 1. Outcome

Build a small private application that lets one local operator:

1. prepare a separately voiced Odia intro and SSGGSM Odia diary;
2. author exact passages using structured controls or validated Cartesia markup;
3. preview cost and generate one passage at a time;
4. listen to, accept/reject and select immutable takes;
5. assemble and listen to dry narration masters;
6. assemble the intro, explicit gap and diary into one dry episode master; and
7. close and reopen the application without losing state or audio.

The first release does not publish, mix background music, render subtitles/video or
support a remote reviewer.

## 2. Operating assumptions

- One trusted operator.
- One local Windows machine.
- One running writer process and one Cartesia request at a time.
- Loopback-only website; no LAN/public hosting.
- Lane B is the authorized SSGGSM/Odia/diary voice.
- Lane C is one separately authorized Odia intro voice bound to its episode.
- Cartesia credentials and private provider identifiers never reach the browser or Git.

A change to any of these assumptions triggers review before adding machinery.

## 3. Architecture kept

Dependencies remain inward:

~~~text
local website/CLI -> application handlers -> domain
                           |
                           +-> filesystem, audio and Cartesia ports
~~~

The only aggregate roots and repositories are:

- `AuthorizationRecord` — the operator's attested voice-use status and scope;
- `NarrationJob` — one fixed-voice intro or diary job with passages, attempts, takes,
  decisions and narration masters; and
- `DiaryEpisode` — the selected intro master, diary master, explicit gap and dry
  episode master.

Passages, takes, masters, snapshots and timing records are not independent
repositories. Audio bytes remain outside aggregate JSON.

## 4. Minimum durable storage

`CARTESIA_NARRATION_ROOT` is an explicit existing directory outside the repository and
worktrees. There is no implicit default or `.env` loader. `CARTESIA_API_KEY` remains
environment-only.

V1 uses:

- one application-wide OS writer lock;
- expected-revision checks for mutations;
- one complete canonical JSON snapshot for every immutable aggregate revision;
- staged, flushed, digest-checked, no-clobber publication;
- safe relative artifact paths under the configured root; and
- immutable artifacts with SHA-256, byte length and decoded audio facts.

The latest valid contiguous revision is current. Incomplete staging is preserved and
reported. V1 does not implement physical decision ledgers, automatic repair/cleanup,
retention scheduling, a database abstraction or cloud storage.

## 5. Minimum audio and timing

Every take must decode as non-empty, non-silent PCM16 little-endian mono 44.1-kHz WAV.
Narration and episode masters concatenate exact PCM and explicit zero-valued sample
gaps. No denoising, EQ, compression, normalization, gain, resampling or music is
hidden in the canonical master.

Assembly records exact component and passage sample offsets. Word timing is not a v1
delivery requirement. Raw provider timing may be retained privately, but it remains
untrusted and is not normalized or shown as word-synchronous truth.

## 6. Minimum generation safety

The operator confirms an exact frozen preview and budget before generation. The
application reserves budget before the provider call and stores the exact effective
input. It settles known usage, releases definite pre-send failures and holds ambiguous
post-send outcomes as `unknown`.

The minimum operator-visible recovery states are `reserved`, `blocked`, `completed`,
`failed` and `unknown`. `Blocked` records a definite refusal before provider work;
internal progress/evidence states already implemented by Plan 2 may remain. Recovery
may internally quarantine invalid or authority-ineligible bytes. It never retries an
ambiguous charged operation automatically and never infers policy from filenames.

The budget ledger remains a small non-aggregate application service. Persist its
append-only reserve, settle, release and hold facts in
`operations/budget-ledger.json`, using atomic file replacement under the same
application-wide writer lock. This one record is the restart-safe authority for
per-take, per-run and billing-cycle caps.

The application supplies the existing generation `CommandId` when reserving
budget. One batch already reuses that command ID for all of its take requests,
while a standalone take has its own command ID, so the ledger can enforce a
durable per-run cap without exposing private project or billing-cycle identifiers
through the application contract. Those identifiers remain local infrastructure
configuration.

## 7. Minimum Cartesia boundary

Cartesia remains behind a Narrator Voice adapter. The adapter must:

- keep Lane-B and Lane-C fixed voice/contracts separate;
- send `language=or` and the dated model/API contract selected by policy;
- preserve Odia UTF-8 text and prove previewed/transmitted transcript equality;
- validate only the markup controls the initial diary workflow uses;
- inject credentials only at transmission;
- request canonical raw PCM and wrap it as canonical WAV;
- run sequentially with bounded timeouts and conservative retries; and
- retain sanitized request/outcome evidence without secrets.

Automated tests use a small representative fixture set and never contact Cartesia.
Additional providers, routes, capability-discovery frameworks, fuzz matrices and
trusted word-timing normalization are deferred.

## 8. Minimum local website

The website exposes only:

1. readiness and basic authorization status;
2. intro/diary job and ordered passage editing;
3. hybrid recipe validation, exact preview and budget confirmation;
4. sequential generation and visible unknown recovery;
5. take playback, accept/reject and selection;
6. narration and episode assembly/listening; and
7. backup status.

It binds to loopback with one worker. The server resolves ActorId and protects secrets,
paths and private identifiers. Browser state is a view/cache, never authority.

React, TanStack Query, generated OpenAPI clients, a generic task runner and a large
audit dashboard are not requirements. The Task 5 design chooses the smallest frontend
after the persisted workflow exists.

## 9. Backup and recovery operations

Provide `init`, `doctor`, `reconcile`, `backup`, `verify-backup` and `restore`. A
backup is a full locked copy to an explicit second destination plus a hash manifest.
Restore accepts only an empty destination and verifies every copied hash; its rehearsal
uses an empty temporary root. `serve` belongs to the website task.

No command silently deletes or repairs evidence. Scheduling, incrementality,
encryption/key management and automated retention are deferred.

## 10. Delivery and verification cadence

Each slice has three independent statuses:

- `implemented` — production code exists;
- `smoke-verified` — the smallest focused contract check passes; and
- `hardened` — broader fault, integration and regression checks pass.

Plans may advance after smoke verification. Before the first real paid/private call,
storage restart/CAS, immutable artifacts, canonical audio, budget unknown handling,
reconciliation and backup/restore must be hardened. A live call additionally requires
separate explicit operator approval.

## 11. Explicit deferrals

- multi-user authentication, reviewer roles, remote access and public hosting;
- word-timing normalization, correction UI and alignment fallback;
- background music, subtitles, images and video;
- multi-process/per-aggregate lock hierarchies;
- separate physical event/decision ledgers, CQRS and event sourcing;
- automatic quarantine cleanup or generalized recovery framework;
- incremental/scheduled/encrypted backup and retention management;
- generic provider, storage, workflow or UI frameworks;
- exhaustive crash, browser and cross-platform test matrices; and
- comprehensive audit/reporting screens.

These are not silently abandoned. ADR-0012 gives measurable triggers for reopening
them.
