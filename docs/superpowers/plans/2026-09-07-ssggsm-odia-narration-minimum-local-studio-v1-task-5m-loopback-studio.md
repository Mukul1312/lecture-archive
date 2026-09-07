# SSGGSM Odia Narration Minimum Local Studio v1 — Task 5M Loopback Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:subagent-driven-development` in this session and
> `superpowers:test-driven-development` for each production slice. Keep every test
> fixture-only; no test or verification step may contact Cartesia.

**Goal:** Deliver the minimum single-operator, restart-safe loopback website and
`serve` entry point over the persisted Narrator Voice application workflows.

**Architecture:** Preserve the three aggregate roots and their repositories. Close
the small application seams needed by a driving adapter, keep Starlette/Uvicorn in a
context-neutral platform module, keep Narrator-specific request mapping and HTML in
Narrator Voice infrastructure, and keep construction in `composition_root`. The
browser is a non-authoritative view/cache; every state change is an existing or
narrow new application use case with expected-revision checks.

**Tech stack:** Python 3.11, Starlette 1.6.0, Uvicorn 0.52.4, HTTPX 0.28.1 for ASGI
tests, standard-library HTML/JSON/security helpers, minimal local CSS and vanilla
JavaScript, and `unittest`. Do not add React, Node, Jinja2, `python-multipart`, an
OpenAPI generator, a generic task runner, a database or a provider SDK.

**Spec:** [Cartesia Odia narration minimum local-studio design — v4](../specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md)

**Authority:** [ADR-0012](../../decisions/0012-narrator-voice-v1-is-a-minimum-local-studio.md)

**Prerequisite:** [Task 4M](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-4m-cartesia-adapter.md)
is implemented and smoke-verified through the locally merged `main` checkpoint
`3f6b00b`. Its pre-live hardening gate remains open.

## Registration and execution status (2026-09-07)

This detailed plan is the authoritative Task 5M execution entry point. Execution is
authorized in the same chat that registers it, on
`feature/narrator-voice-production-v1` in the isolated
`.worktrees/narrator-voice-production-v1` worktree. The clean Task 4M baseline passed
the focused 219-test matrix before Task 5M planning. Task 5M is not yet
`implemented`, `smoke-verified` or `hardened`.

Planning and automated implementation remain entirely fixture-only. Do not read a
private production root, read `CARTESIA_API_KEY`, open a provider socket, make a
paid/private request, push, publish, or merge while executing this plan.

## Fixed implementation rulings

1. **One local operator and one episode.** v1 owns one configured Lane-B diary voice,
   one configured Lane-C intro voice and one diary episode. Lane C's configured
   authorization record is immutably episode-bound, so the UI must not promise a
   second episode. If discovery finds more than one episode, readiness fails closed
   with a generic unsupported-state message. Supporting another episode requires an
   explicit configuration and authorization decision outside Task 5M.
2. **Server-rendered shell, small progressive enhancement.** Return semantic HTML
   escaped with the standard library, local static CSS, and one local JavaScript file.
   JavaScript serializes exact JSON mutation bodies, displays responses and reloads
   authoritative server state. It stores no state in `localStorage`, performs no
   optimistic write and never retries a mutation.
3. **Framework confinement.** Only `heritage_archive.platform.web` may import
   Starlette or Uvicorn. Platform web code must not import a bounded context.
   Narrator Voice infrastructure implements a framework-neutral request/response
   application; the composition root is the only wiring sink.
4. **Fixed loopback origin.** Serve exactly one worker on `127.0.0.1:8765`; expose no
   host, port, worker, proxy or CORS switch. Accept exactly `Host:
   127.0.0.1:8765`. Mutations accept exactly `Origin:
   http://127.0.0.1:8765` and same-origin fetch metadata.
5. **Process security.** Generate independent 256-bit process session and CSRF
   tokens. Set a host-only, `HttpOnly`, `SameSite=Strict`, `Path=/` session cookie.
   Compare tokens in constant time. A restart invalidates session, CSRF and pending
   generation confirmation tokens while retaining the stable configured `ActorId`.
6. **Strict input.** Allow only GET/HEAD and POST. Mutation bodies are exact
   `application/json`, at most 262,144 bytes, valid UTF-8, with duplicate and unknown
   fields rejected. IDs, enums, integers and decimal strings are parsed into existing
   nominal domain/application values before handler invocation. Browser-supplied
   actor/principal, authorization record, voice/provider/dictionary identifier,
   artifact location or filesystem path fields are always rejected.
7. **No secret-bearing output.** Presenters use explicit allowlists. Never serialize
   API keys, opaque provider voice/dictionary references, authorization record IDs,
   absolute paths, artifact locations, raw evidence, provider endpoints or exception
   text. Private narration text is rendered only on its editor page, HTML-escaped,
   with `Cache-Control: no-store` and no request-body logging.
8. **One-shot generation confirmation.** Estimation creates a bounded in-memory token
   bound to the exact job, preview, post-estimate current job revision from
   `GenerationEstimateResult.revision`, preview digest and estimate.
   `GenerationPreview.base_job_revision` remains evidence of the pre-estimate state;
   it is not the generation command's expected revision. The generation POST carries
   only CSRF plus that token. Atomically consume the token before invoking generation;
   lost responses, refreshes and restarts cannot replay it. A nonblocking process
   lock rejects concurrent generation with a stable 409 `generation_busy` response.
9. **No generic background execution.** The accepted generation request runs the
   synchronous handler in one AnyIO worker thread while the HTTP request remains
   open. The existing durable attempt/workspace/status model remains recovery truth.
   Do not add task IDs, queues, workers, schedulers or automatic replay.
10. **Server-owned output locations.** The web adapter derives canonical safe paths
    from server-generated `CommandId` plus the owning job/episode ID:
    `studio/takes/<job>/<command>.wav`,
    `studio/narration-masters/<job>/<command>.wav`, and
    `studio/episode-masters/<episode>/<command>.wav`. The browser never chooses or
    sees a path.
11. **Checked full-file playback.** Audio routes resolve an opaque parent/child ID via
    an application handler, verify immutable bytes and decoded media facts, and return
    `audio/wav`. Range streaming is deferred; Task 5M serves the verified whole file.
12. **Truthful backup status.** Show current `doctor`/storage readiness and the exact
    guidance that backup history is not persisted. Keep `backup`, `verify-backup` and
    `restore` in the existing offline CLI; do not invent a last-backup timestamp or
    add a backup ledger.

## Required routes

The one-page studio may group these operations into sections, but it implements only
this surface:

- `GET /`, `GET /assets/studio.css`, `GET /assets/studio.js`;
- `POST /api/v1/episode`, `POST /api/v1/authority/{lane}`;
- `POST /api/v1/jobs/diary`, `POST /api/v1/jobs/intro`;
- `POST /api/v1/jobs/{job}/order` and
  `POST /api/v1/jobs/{job}/defaults`;
- `POST /api/v1/jobs/{job}/passages/{passage}/text`,
  `POST /api/v1/jobs/{job}/passages/{passage}/recipes/validate`,
  `POST /api/v1/jobs/{job}/passages/{passage}/recipes/require`, and
  `POST /api/v1/jobs/{job}/passages/{passage}/dictionary/require`;
- `POST /api/v1/jobs/{job}/estimate`, `/generate`, and
  `/generation-attempts/{attempt}/reconcile`;
- `POST /api/v1/jobs/{job}/takes/{take}/review` and `/select`;
- `POST /api/v1/jobs/{job}/narration-masters`,
  `/narration-masters/{master}/listen`, and
  `/narration-masters/{master}/attach/{role}`, plus
  `/narration-assembly-attempts/{attempt}/reconcile`;
- `POST /api/v1/episodes/{episode}/gap`, `/speech-masters`,
  `/speech-masters/{master}/listen`, and
  `/assembly-attempts/{attempt}/reconcile`; and
- `GET /audio/jobs/{job}/takes/{take}.wav`,
  `GET /audio/jobs/{job}/masters/{master}.wav`, and
  `GET /audio/episodes/{episode}/masters/{master}.wav`.

There is no general JSON CRUD API, filesystem browser, raw evidence viewer, word
timing UI, web backup/restore action, second episode journey or generic audit page.

## Fixed HTTP contract

The process cookie is named `narrator_session`; the mutation header is
`X-Narrator-CSRF`. `GET /` creates/refreshes the process cookie and places the
separate CSRF value in
`<meta name="narrator-csrf" content="…">`. No token appears in a URL, log or
JavaScript bundle. Dynamic JSON success uses
`{"ok":true,"result":{...allowlisted fields...}}`. Errors use only
`{"ok":false,"error":{"code":"<stable_code>","message":"<generic guidance>"}}`;
never include exception text or inputs. Map malformed input to 400, missing session
to 401, hostile origin/CSRF or denied authority to 403, missing owned resource to 404,
stale/already-existing/busy state to 409, oversized bodies to 413, wrong content type
to 415, domain validation to 422 and unexpected faults to a generic 500.

All `expectedRevision` values are positive JSON integers. All IDs are lowercase UUIDv4
text. All operator text is NFC, LF-only UTF-8. Passage text retains the domain's
8,000-scalar bound; advanced recipe source retains the compiler's 16,384-byte bound;
review/listening notes and selection reasons are nonempty and limited by the web
adapter to 2,000 scalars and 8,192 UTF-8 bytes. Job creation accepts 1–128 passage
objects containing only `text`; the server assigns passage IDs and zero-based order.
Recipe validation assigns a new recipe ID at revision 1; the browser may return only
an ID listed by the editor projection when requiring that recipe.

| Mutation | Exact JSON keys |
|---|---|
| create episode | none (`{}`) |
| register configured authority | `evidenceDigest`, `validFrom`, `validUntil` |
| prepare diary job | `passages` |
| prepare intro job | `expectedEpisodeRevision`, `passages` (server derives the sole episode) |
| revise passage text | `expectedRevision`, `text` |
| reorder passages | `expectedRevision`, `orderedPassageIds` |
| revise defaults | `expectedRevision`, `speed`, `volume`, `emotion` |
| validate recipe | `expectedRevision`, `mode`, `structuredControls`, `advancedSource` |
| require recipe | `expectedRevision`, `recipeId` |
| require configured dictionary | `expectedRevision` |
| estimate | `expectedRevision`, `passageId`, `recipeId`, `speedMode`, `speed`, `volumeMode`, `volume`, `emotionMode`, `emotion`, `dictionaryMode` |
| generate | `confirmationToken` |
| reconcile any generation/assembly attempt | `expectedRevision` |
| review take | `expectedRevision`, `outcome`, `notes` |
| select take | `expectedRevision`, `passageId`, `reason` |
| assemble narration | `expectedRevision`, `gapsSamples` |
| listen to narration/episode master | `expectedRevision`, `outcome`, `notes` |
| issue-and-attach narration master | `sourceExpectedRevision`, `episodeId`, `episodeExpectedRevision` |
| set episode gap | `expectedRevision`, `gapSamples` |
| assemble episode | `expectedRevision` |

Nullable fields remain present where listed: `emotion`, the matching value for an
`omit`/`inherit` control mode, and the unused recipe-authoring branch are JSON `null`.
`structuredControls` is an array of the existing allowlisted break/speed/volume/
spelling control shapes; it is empty in advanced mode. `dictionaryMode` is
`inherit`, `set` or `omit`; on `set`, the server injects only the lane's configured
binding. Validity timestamps are explicit RFC 3339 UTC values. Digests are exactly 64
lowercase hexadecimal characters. All arrays contain integers/IDs only as described;
booleans, floats and numeric strings are not accepted in their place.

The one-shot confirmation constants are fixed at a 600-second monotonic TTL and 128
live entries. On capacity, reject a new estimate confirmation with 409
`confirmation_capacity` after the estimate itself has truthfully persisted; never
evict an unexpired confirmation silently. Expired/consumed/wrong-session tokens all
produce the same 409 `confirmation_unavailable` response.

---

### Task 1: Close configured authorization bootstrap

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/application/commands.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/handlers.py`
- Modify: `tests/heritage_archive/narrator_voice/test_application_authority.py`
- Modify: affected authority callers in `tests/heritage_archive/narrator_voice/`

**Interface:**

```python
@dataclass(frozen=True, slots=True)
class RegisterAuthorizationCommand:
    command_id: CommandId
    principal: str
    record_id: AuthorizationRecordId
    scope: AuthorityScope
    evidence_digest: ContentDigest
```

- [ ] Write a failing application test proving registration persists the exact
  configured record ID supplied by the trusted driving adapter and does not request
  an authorization ID from `IdentifierSource`.
- [ ] Add denial/no-clobber cases for unauthorized principal and duplicate
  registration. The configured-ID/scope web-boundary test belongs to Task 6 after the
  trusted route adapter exists.
- [ ] Change `RegisterAuthorizationHandler` to use `command.record_id`; remove only
  its record-ID generator dependency. Retain generated change IDs inside the domain
  aggregate and the existing `save(record, None)` no-clobber boundary.
- [ ] Update every existing caller mechanically; do not change authority lifecycle or
  weaken the current actor-admin check.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_application_authority -v
  ```

- [ ] Commit the exact Task 1 files as `fix: register configured narration authority`.

### Task 2: Add restart discovery and editor projections

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/application/ports.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/commands.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/results.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/status.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/handlers.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_repositories.py`
- Modify: `tests/heritage_archive/narrator_voice/fakes.py`
- Modify: `tests/heritage_archive/narrator_voice/test_filesystem_repositories.py`
- Modify: `tests/heritage_archive/narrator_voice/test_application_status.py`
- Modify: `tests/heritage_archive/test_architecture.py`

**Interfaces:**

```python
class NarrationJobRepository(Protocol):
    def list_ids(self) -> tuple[NarrationJobId, ...]: ...

class DiaryEpisodeRepository(Protocol):
    def list_ids(self) -> tuple[DiaryEpisodeId, ...]: ...

@dataclass(frozen=True, slots=True)
class DiscoverStudioCommand:
    command_id: CommandId

@dataclass(frozen=True, slots=True)
class ShowNarrationEditorCommand:
    command_id: CommandId
    job_id: NarrationJobId
```

- [ ] Write failing repository tests for an empty store, reverse creation with stable
  lexical UUID ordering, reopen/restart discovery, and fail-closed handling of an
  invalid ID directory, non-directory/reparse entry, invalid first revision, revision
  gap and snapshot/directory identity mismatch.
- [ ] Add `list_ids()` only to the job and episode repository ports and their existing
  filesystem/fake adapters. Authorization IDs remain fixed private configuration and
  are never enumerated. Do not add a fourth repository or scan storage in a route.
- [ ] Add frozen discovery result/projection types returning only opaque job and
  episode IDs. Add an editor projection containing current ordered canonical passage
  text, text/recipe revisions, validated recipe metadata, public delivery controls,
  required/not-required flags, and only the restart-visible preview summary needed by
  the form: preview ID/base revision, canonical projection, billable characters,
  estimated usage and issue time. Exclude endpoint, authority snapshot, full effective
  settings, contract internals, authorization record IDs and opaque
  dictionary/provider references. A restarted process requires a fresh estimate and
  confirmation token before generation.
- [ ] Add `DiscoverStudioHandler` and `ShowNarrationEditorHandler`; all data comes
  through repositories and domain accessors. Keep the existing operational status
  projections unchanged for recovery/readiness truth.
- [ ] Extend the architecture characterization for the new explicit use cases while
  continuing to assert exactly three repository ports/roots.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_filesystem_repositories tests.heritage_archive.narrator_voice.test_application_status tests.heritage_archive.test_architecture -v
  ```

- [ ] Commit as `feat: add narrator studio discovery projections`.

### Task 3: Add application-owned verified playback

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/application/ports.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/commands.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/results.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/handlers.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_evidence.py`
- Create: `tests/heritage_archive/narrator_voice/test_application_audio_playback.py`
- Modify: `tests/heritage_archive/narrator_voice/test_filesystem_evidence.py`
- Modify: `tests/heritage_archive/test_architecture.py`

**Interfaces:**

```python
class VerifiedArtifactReader(Protocol):
    def read_verified_bytes(self, publication: PublishedArtifact) -> bytes: ...

@dataclass(frozen=True, slots=True)
class AudioPlaybackResult:
    command_id: CommandId
    content_digest: ContentDigest
    byte_size: int
    media_type: str
    payload: bytes
```

- [ ] Write failing tests for take, narration-master and episode-master audio reads;
  wrong-parent IDs, missing/tampered/reparse files, non-WAV media, digest/length
  mismatch and decoded-media mismatch must fail without returning a path.
- [ ] Add `ReadTakeAudioCommand`, `ReadNarrationMasterAudioCommand` and
  `ReadEpisodeMasterAudioCommand` with only opaque parent/child IDs.
- [ ] Resolve children through `NarrationJob.take`, `NarrationJob.master` and
  `DiaryEpisode.speech_master`; require `audio/wav`; use the application-owned reader
  and `MediaInspector`; require decoded facts equal the aggregate's stored facts.
- [ ] Reuse `FilesystemArtifactEvidenceVerifier.read_verified_bytes` structurally
  behind the new port. Do not expose `PublishedArtifact`, `ArtifactRef`, artifact ID,
  location or root in `AudioPlaybackResult`. Historical/rejected takes remain
  playable to the authenticated local operator and are not re-gated by current
  generation authority.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_application_audio_playback tests.heritage_archive.narrator_voice.test_filesystem_evidence tests.heritage_archive.test_architecture -v
  ```

- [ ] Commit as `feat: add checked narrator audio playback`.

### Task 4: Complete the single-operator composition graph

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/local_operator.py`
- Modify: `src/heritage_archive/composition_root/narrator_voice_live.py`
- Create: `tests/heritage_archive/narrator_voice/test_local_operator.py`
- Create: `tests/heritage_archive/narrator_voice/test_live_studio.py`

**Interface:**

```python
@dataclass(frozen=True, slots=True)
class SingleOperatorActorResolver:
    process_principal: str
    actor_id: ActorId

    def resolve_principal(self, principal: str) -> PrincipalAuthority: ...
```

- [ ] Test exact constant-time principal matching, stable configured actor mapping,
  administration plus operational-review permissions, and redacted denial for an
  unknown/malformed principal. Word-timing review remains unavailable.
- [ ] Expand `LiveNarrationStudio` (or factor one shared studio service graph) to wire
  every Task 5M handler: authority, discovery/editor/status, prepare/edit/recipe,
  estimate/generate/reconcile, review/select, narration assemble/listen/snapshot,
  episode prepare/attach/gap/assemble/listen/reconcile, narration-assembly
  reconciliation and all three playback reads.
- [ ] Reuse one repository instance per aggregate type, one clock/identifier source,
  one artifact store/reader, one workspace store/verifier set, one budget ledger, one
  compiler/gateway and one dry assembler. Routes must receive handlers, never
  repositories or handler internals.
- [ ] Inject one read-only readiness callable wrapping `doctor(root)` into the web
  graph. It returns `DoctorResult` to an explicit presenter allowlist containing only
  `healthy`, `checkedFileCount` and stable issue codes plus the literal guidance
  “backup history is not persisted; use CLI backup and verify-backup”. Routes never
  invoke filesystem helpers or receive the root.
- [ ] Prove construction with a temporary fixture configuration neither reads
  `CARTESIA_API_KEY` nor opens DNS/socket/HTTP. Closing the graph closes the transport
  exactly once.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_local_operator tests.heritage_archive.narrator_voice.test_live_studio -v
  ```

- [ ] Commit as `feat: compose the complete local narration studio`.

### Task 5: Build the secure loopback platform boundary and fixed `serve`

**Files:**

- Modify: `pyproject.toml`
- Create: `src/heritage_archive/platform/web/__init__.py`
- Create: `src/heritage_archive/platform/web/loopback.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/__init__.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/security.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/app.py`
- Create: `src/heritage_archive/composition_root/narrator_voice_web.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/cli.py`
- Modify: `src/heritage_archive/composition_root/narrator_voice_cli.py`
- Create: `tests/heritage_archive/platform/test_loopback_web.py`
- Create: `tests/heritage_archive/narrator_voice/test_web_security.py`
- Modify: `tests/heritage_archive/narrator_voice/test_cli.py`
- Modify: `tests/heritage_archive/test_architecture.py`

- [ ] Pin `starlette==1.6.0` and `uvicorn==0.52.4` in the existing `narrator` optional
  extra. Register `loopback_web/assets/*.css` and `*.js` as package data so an
  installed source/wheel contains the same local assets. Install only that extra into
  the isolated development environment when the failing import test requires it.
- [ ] Define small context-neutral `WebRequest`, `WebResponse` and web-application
  protocol values. Implement the Starlette ASGI translation and
  `serve_loopback(application)` only in `platform/web/loopback.py`; Uvicorn receives
  host `127.0.0.1`, port `8765`, one worker, `proxy_headers=False` and no reload.
- [ ] Test exact Host/Origin, one process cookie, distinct CSRF token, constant-time
  checks, same-origin fetch metadata, allowed methods, exact JSON content type,
  duplicate/unknown JSON fields, invalid UTF-8, 262,144-byte cap, duplicate incoming
  Host/Origin/content-type/CSRF headers and generic error bodies. Enforce the body cap
  while consuming ASGI chunks rather than buffering an unbounded request first. Use
  `httpx.AsyncClient` plus `ASGITransport` or a raw ASGI harness—never Starlette
  `TestClient` and never a listening socket.
- [ ] Apply on every dynamic response: `Cache-Control: no-store` and exact CSP
  `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self';
  media-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none';
  frame-ancestors 'none'; object-src 'none'`, plus
  `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, COOP/CORP and restrictive
  `Permissions-Policy`. Fixed-name static assets use `Cache-Control: no-cache` plus a
  content-derived strong ETag so upgrades revalidate; they have no remote dependency.
- [ ] Add `serve` to the existing CLI with no host/port/worker flags. Import web code
  lazily only for `serve`; `init`, `doctor`, reconciliation and backup commands remain
  offline and retain their existing JSON output contract. `--help` must not construct
  the live graph or read the key.
- [ ] Extend the architecture guard to confine `starlette`/`uvicorn` imports to
  `platform/web`, preserve platform-to-context prohibition and reject a new
  `presentation` layer outside the enforced context layering.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.platform.test_loopback_web tests.heritage_archive.narrator_voice.test_web_security tests.heritage_archive.narrator_voice.test_cli tests.heritage_archive.test_architecture -v
  ```

- [ ] Commit as `feat: add secured narrator loopback server`.

### Task 6: Render truthful readiness, authorization and authoring

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/app.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/security.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/presenters.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/routes.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/assets/studio.css`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/assets/studio.js`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_repositories.py`
- Modify: `src/heritage_archive/composition_root/narrator_voice_live.py`
- Modify: `src/heritage_archive/composition_root/narrator_voice_web.py`
- Create: `tests/heritage_archive/narrator_voice/test_web_authoring.py`
- Modify: `tests/heritage_archive/narrator_voice/test_web_security.py`
- Modify: `tests/heritage_archive/narrator_voice/test_live_studio.py`
- Modify: `tests/heritage_archive/narrator_voice/test_filesystem_repositories.py`

- [ ] Start with failing route/presenter tests for empty/fresh/restarted stores, HTML
  escaping, NFC Odia round-trip, explicit output allowlists, one-episode enforcement,
  configured authority registration, rejection of any browser-supplied configured
  ID/scope/private field, redacted readiness/backup guidance and stale revision
  response.
- [ ] Render one semantic page with readiness/storage guidance, redacted Lane-B/C
  authority status, the single episode, discovered jobs, ordered passages, canonical
  text, delivery defaults and recipe-required state. Do not render hidden private
  values in HTML, comments, data attributes or JavaScript.
- [ ] Keep a first request with no/currently invalid process cookie nonprivate: issue
  the cookie and CSRF meta in a bootstrap shell, then let the local script reload the
  same URL. Render private editor text only when that second `GET /` carries the
  current session; do not add another page or authentication flow.
- [ ] Implement episode creation first; bind Lane-C authorization to that episode.
  The authority route obtains the lane only from its allowlisted path segment; its
  JSON body accepts only evidence SHA-256 and explicit UTC validity bounds. Server
  code derives the record ID, identity, purpose, language, episode and complete
  operation set from the configured lane policy.
- [ ] Implement diary/intro job preparation and text/order/default/structured-or-
  advanced-recipe/require-recipe/require-configured-dictionary mutations. Every
  existing-root mutation requires `expectedRevision`; stale conflicts return 409
  `stale_revision` and JavaScript asks the operator to reload/reapply without retry.
- [ ] Keep advanced source inert text and rely on the existing recipe compiler
  allowlist/16,384-byte bound. Do not render it through `innerHTML`.
- [ ] Inject one identifier source into both the complete live graph and the route
  adapter. Introduce a compatible typed filesystem-repository failure distinction so
  storage/rehydration/publication faults map to generic 500 while valid authoring
  `ValidationError` remains 422; never classify by exception text.
- [ ] Verify the installed-package resource API and an offline-built wheel/sdist both
  contain the two real local assets. Do not download build dependencies or publish.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_web_authoring tests.heritage_archive.narrator_voice.test_application_source_workflow tests.heritage_archive.narrator_voice.test_application_narration_preview -v
  ```

- [ ] Commit as `feat: expose local narration authoring`.

### Task 7: Add exact estimate, one-shot generation and recovery

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/generation.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/routes.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/presenters.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/assets/studio.js`
- Create: `tests/heritage_archive/narrator_voice/test_web_generation.py`

- [ ] Write failing tests proving the displayed canonical projection, billable
  characters and estimate come from `GenerationEstimateResult`; sensitive preview
  fields remain absent.
- [ ] Implement a bounded one-shot confirmation store with cryptographically random
  tokens, monotonic expiry, maximum entries, atomic consume and exact
  job/preview/post-estimate-current-revision/digest/estimate binding. Fix the TTL at
  600 seconds and live-entry cap at 128. Test generation immediately after estimate,
  staleness after an intervening job mutation, wrong session/job, tampering, expiry,
  capacity, double submit and restart invalidation.
- [ ] Derive a fresh command ID and safe take location server-side, acquire the
  nonblocking generation lock, atomically consume the token, and run exactly one
  `GenerateTakeHandler` call in a worker thread with `finally`-based lock release.
  Concurrent calls return 409 `generation_busy` without consuming their token; no
  branch automatically retries a failed, unknown or lost-response generation.
- [ ] Present completed/failed/blocked/unknown results explicitly. Expose the existing
  evidence-driven reconciliation handler for unknown attempts with current
  `expectedRevision`. After a process restart, also offer reconciliation for any
  persisted nonterminal orphan (`reserved`, `input_frozen`,
  `external_work_started`, `artifacts_staged`, or `artifacts_published`); do not turn
  refresh into reconciliation and never auto-replay.
- [ ] Use a fake gateway and credential/socket guards for every route test. Cover
  success, definitive failure, ambiguous unknown, stale revision, busy gate and
  double-submit.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_web_generation tests.heritage_archive.narrator_voice.test_application_generation tests.heritage_archive.narrator_voice.test_application_recovery tests.heritage_archive.narrator_voice.test_cartesia_generation_integration -v
  ```

- [ ] Commit as `feat: add confirmed sequential web generation`.

### Task 8: Add review, checked playback and dry mastering

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/routes.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/presenters.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/loopback_web/assets/studio.js`
- Create: `tests/heritage_archive/narrator_voice/test_web_media.py`
- Create: `tests/heritage_archive/narrator_voice/test_web_mastering.py`

- [ ] Test all three opaque audio routes for correct `audio/wav` bytes and explicit
  length/digest metadata, HEAD behavior, wrong-parent/cross-owner IDs, missing/tampered
  media, traversal-shaped IDs and absence of path/private metadata. Serve only a fully
  verified file; do not add ranges or partial unverified content.
- [ ] Add operational accept/reject and explicit take selection using the process
  principal and expected revision. Notes/reasons are bounded plain text. No qualified
  reviewer or publishing role is invented.
- [ ] Add narration assembly with explicit nonnegative sample gaps, playback,
  pass/fail listening and source snapshot issuance. Derive master output paths
  server-side and show unknown assembly reconciliation without automatic repair.
- [ ] Add atomic UI choreography for attach—not a new domain transaction: issue the
  selected current narration-master snapshot through its handler, then pass that
  returned application value to the existing intro/diary attach handler. Require both
  source-job and episode expected revisions and truthfully retain an issued snapshot
  if the later episode CAS conflicts.
- [ ] Add explicit intro/diary gap samples, episode dry assembly, playback, pass/fail
  listening and unknown assembly reconciliation. Keep timed-package/presentation
  export and raw word timing outside the website.
- [ ] Run:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_web_media tests.heritage_archive.narrator_voice.test_web_mastering tests.heritage_archive.narrator_voice.test_application_episode tests.heritage_archive.narrator_voice.test_diary_episode_assembly -v
  ```

- [ ] Commit as `feat: complete local narration review and mastering`.

### Task 9: Prove one fixture-only intro-plus-diary restart journey

**Files:**

- Create: `tests/heritage_archive/narrator_voice/test_web_workflow.py`
- Modify: `tests/heritage_archive/narrator_voice/workflow.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: this plan and the minimum master plan after evidence exists

- [ ] Drive the framework-neutral/ASGI boundary through: fresh readiness → episode →
  configured Lane-B/Lane-C authority → diary and intro jobs → passage edit/order →
  structured and advanced recipe validation → exact estimate → one-shot fake
  generation → playback → accept/select → narration assembly/listening/snapshot →
  attach intro/diary → explicit episode gap → episode assembly/playback/listening.
- [ ] Close and rebuild the application against the same temporary external root;
  rediscover the episode/jobs and prove current revisions, selections, masters,
  listening decisions and verified audio remain available. Assert no credential read,
  DNS/socket, HTTP transport or real Cartesia call throughout.
- [ ] Keep the journey representative: one intro passage and the minimum diary
  passages needed to prove ordering/gaps. Do not add duplicate browser journeys,
  Playwright, a browser farm or an exhaustive hostile-input matrix.
- [ ] Run the Task 5M focused checkpoint:

  ```powershell
  python -m unittest tests.heritage_archive.narrator_voice.test_application_authority tests.heritage_archive.narrator_voice.test_application_status tests.heritage_archive.narrator_voice.test_application_audio_playback tests.heritage_archive.narrator_voice.test_filesystem_repositories tests.heritage_archive.narrator_voice.test_filesystem_evidence tests.heritage_archive.narrator_voice.test_local_operator tests.heritage_archive.narrator_voice.test_live_studio tests.heritage_archive.platform.test_loopback_web tests.heritage_archive.narrator_voice.test_web_security tests.heritage_archive.narrator_voice.test_web_authoring tests.heritage_archive.narrator_voice.test_web_generation tests.heritage_archive.narrator_voice.test_web_media tests.heritage_archive.narrator_voice.test_web_mastering tests.heritage_archive.narrator_voice.test_web_workflow tests.heritage_archive.narrator_voice.test_cli tests.heritage_archive.test_architecture -v
  ```

- [ ] Run the existing Task 4M fixture regression matrix, source-package/import
  smoke, `serve --help`, asset GETs through `ASGITransport`, `git diff --check`, and an
  exact staged-file secret/private-data/media scan. Do not bind a real socket during
  automated verification.
- [ ] Update README with the fixed local serve command and the explicit pre-live
  warning. Record Task 5M as `implemented` and `smoke-verified`, not `hardened`, only
  after the evidence exists.
- [ ] Request a whole-branch code review, apply only verified findings, rerun the
  smallest affected tests plus the checkpoint, and commit the exact final Task 5M
  files. Do not push, merge, publish or make a live request.

## Focused completion criteria

Task 5M is smoke-complete only when:

- a fresh configured store can create its exact Lane-B authority, prepare the single
  episode, create the episode-bound Lane-C authority, and prepare both jobs;
- the loopback process binds only `127.0.0.1:8765` with one worker and rejects hostile
  Host/Origin/session/CSRF/input without leaking private facts;
- restart discovery uses the existing repositories and returns deterministic opaque
  IDs without adding another aggregate or repository;
- browser input cannot choose an ActorId/principal, configured authorization/provider
  identity, dictionary binding, artifact location or filesystem path;
- one estimate authorizes at most one sequential fixture generation, and unknown or
  lost-response outcomes are never automatically repeated;
- all take/master playback is parent-bound, digest/length/media verified and pathless;
- the fixture journey reaches accepted intro and diary masters plus a listened episode
  master, then survives reconstruction from the same temporary root;
- backup status is truthful guidance over current health, while destructive/offline
  backup operations remain outside the website; and
- focused tests and packaging/import checks pass without credentials, network,
  provider credits, private data or generated media entering Git.

## Deferred pre-live hardening and post-5M boundary

Task 5M does not authorize a live request. Before the first paid/private generation,
the master plan's pre-live gate must still revalidate the Cartesia contract, exercise
representative restart/fault windows around send/evidence/finalization, verify
storage/budget/recovery/audio/backup integrity against the private operational setup,
set explicit caps, and obtain separate operator approval for one tightly capped
passage. In particular, real successful SSE completion still has no authoritative
usage source: without one, the current adapter holds the reservation and cannot
complete a take. That must be resolved or explicitly accepted at the pre-live gate,
not hidden by the website.

After that gate, the minimum v1 implementation plan has no additional numbered build
task. What remains is controlled production validation and operations—not Task 6M:
one approved capped live smoke, human listening/selection, a verified backup, and any
defect-driven hardening actually revealed. Multi-user access, LAN/public hosting,
additional episodes/voices/providers, publishing UI, trusted word timing, web backup,
generic background work and broader browser matrices remain explicitly deferred.
