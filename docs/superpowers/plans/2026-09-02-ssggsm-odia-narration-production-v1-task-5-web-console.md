# SSGGSM Odia Narration Production v1 — Task 5: Secured API and Workflow Console

> **Status (2026-09-03): Superseded before implementation.** The fixed
> React/TanStack/OpenAPI/three-journey scope is not a v1 requirement. Use Task 5M in
> the
> [minimum local-studio plan](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1.md)
> and choose the smallest loopback frontend after durable storage works.

**Goal:** Deliver the loopback-only Starlette API and React workflow console over the
same persisted application handlers, with security and workflow coverage.

**Spec:** `docs/superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md`

## Global constraints

- Accepted v3 and ADR-0006 through ADR-0011 bind; ADR-0001/0005 are accepted.
- Perform this feature work only in the isolated linked worktree created after the documentation baseline commit; do not push, merge, publish or make a live Cartesia request.
- Never track private text/evidence/keys/provider IDs/audio/raw timing/stores; frozen `data/narration/**` is never read.
- Never import or extend `heritage_production`. The future non-SSGGSM English/Hindi narration programme remains active and intact; its useful technical knowledge may be reused through characterization only.
- Dependencies point inward: domain uses only stdlib plus kernel; application imports domain/ports; infrastructure implements ports and may reach platform; platform never imports a context; composition root is the sole sink/wiring boundary.
- Exactly three aggregate roots/repositories exist; v3 authority transitions and vocabulary are mandatory.
- Persist canonical integers/decimal strings; browser input is never authoritative for ActorId, transcript, private references or paths.
- Audio is dry mono PCM16 little-endian 44.1-kHz WAV with exact PCM assembly and explicit gaps only; gaps have no default.
- No automated Cartesia/credit consumption; use RED/GREEN/refactor, exact staging and local commits only; never push, merge or publish.

## Execution

- [ ] Add optional/runtime pins Starlette 1.6.0 and Uvicorn 0.52.4. Use HTTPX `ASGITransport` or a raw ASGI harness in backend tests, never Starlette `TestClient`.
- [ ] Keep framework-neutral inbound DTO/handler mapping in Narrator Voice infrastructure, generic Starlette mechanics in `platform/web`, sequential runner in `platform/execution`, and all wiring in `composition_root/narrator_console.py`.
- [ ] Track `/api/v1` OpenAPI at `contracts/narrator_console/v1/openapi.json`; reject unknown fields. Existing-root mutations require `expectedRevision`; long commands reserve attempts/budget synchronously, return 202, and poll persisted state.
- [ ] Bind only `127.0.0.1:8765`, one worker, no proxy trust/CORS. Implement random 256-bit process session and separate in-memory CSRF token with constant-time checks, host-only HttpOnly SameSite=Strict cookie, exact Host/Origin, fetch metadata/content type/body limits, CSP/security headers, server ActorId and opaque media routes. Never expose secrets, private IDs or paths.
- [ ] Build `apps/narrator_console` with Node 24.20.0, React/DOM 19.2.8, `react-router` 8.3.1, TanStack Query 5.102.2, Vite 8.2.2 and TypeScript 6.0.2. Commit exact npm locks; use semantic HTML/plain CSS, no remote fonts/framework.
- [ ] Implement screens for readiness/authority, jobs, ordered hybrid Odia editing, validation/budget, generation/reconciliation, take review/selection, narration mastering/listening, episode composition/listening, timing handoff and storage/backup status.
- [ ] Keep browser state non-authoritative: no persisted query cache, optimistic writes, mutation retries or localStorage authority. Show explicit 409 reload/reapply; render advanced markup as inert text.
- [ ] Cover backend security/contracts, frontend accessibility/state and three full fake Playwright workflows. Run Python suites, npm lint/typecheck/test/build, Playwright Chromium, packaging/import and `git diff --check`; commit.

## Verification

- API rejects cross-lane, stale-revision and hostile browser requests without leaking private state.
- Browser workflows mutate only through persisted server commands and visibly handle 409 recovery.
- All Python, npm, Playwright, packaging and diff gates pass using fakes only.
