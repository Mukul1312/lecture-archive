# SSGGSM Odia Narration Production v1 — Task 4: Cartesia Anti-Corruption Layer

**Goal:** Implement the frozen Cartesia request/SSE boundary and exhaustive fake-fixture
contract tests without a live request.

**Spec:** `docs/superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md`

## Global constraints

- Accepted v3 and ADR-0006 through ADR-0011 bind; ADR-0001/0005 are accepted.
- Perform this feature work only in the isolated linked worktree created after the documentation baseline commit; do not push, merge, publish or make a live Cartesia request.
- Never track private text/evidence/keys/provider IDs/audio/raw timing/stores; frozen `data/narration/**` is never read.
- Never import or extend `heritage_production`. The future non-SSGGSM English/Hindi narration programme remains active and intact; its useful technical knowledge may be reused through characterization only.
- Dependencies point inward: domain uses only stdlib plus kernel; application imports domain/ports; infrastructure implements ports and may reach platform; platform never imports a context; composition root is the sole sink/wiring boundary.
- Exactly three aggregate roots/repositories exist; v3 authority transitions and vocabulary are mandatory.
- Persist canonical integers/decimal strings; browser values are non-authoritative.
- Audio is dry mono PCM16 little-endian 44.1-kHz WAV with exact PCM assembly and explicit gaps only; gaps have no production default.
- Automated tests make no Cartesia call and spend no credits. Use RED/GREEN/refactor, exact staging and local commits only.

## Execution

- [ ] Add narrator-only pins through an optional extra and `requirements-narrator.lock.txt`: HTTPX 0.28.1 and defusedxml 0.7.1. Do not use the Cartesia SDK or `httpx-sse`.
- [ ] Parse advanced markup with defusedxml inside the ACL. Reject declarations, DTD/entities, unknown tags/attributes, invalid nesting, unsupported capabilities and lexical projections not exactly equal to NFC `PassageText`.
- [ ] Implement a strict incremental UTF-8 SSE parser over HTTPX against the fixed HTTPS Cartesia origin, with `trust_env=False`, redirects disabled and bounded streams. Freeze `/tts/sse`: `Cartesia-Version: 2026-08-14`, `sonic-3.6-2026-08-27`, `language: or`, no locale, normalization off, raw `pcm_s16le` 44100, timestamps on, phonemes off, normalized timestamps off.
- [ ] Serialize Odia without ASCII escaping; convert decimal strings to JSON numbers only at the boundary; prove previewed transcript bytes equal transmitted bytes; freeze and send those exact request bytes with HTTPX `content=`. Inject the API key only at transmission, store sanitized request/response evidence, and wrap PCM as canonical WAV.
- [ ] Run one request at a time with connect/write 10 s, read-idle 30 s, total 180 s; at most three submissions with 1 s/3 s backoff and `Retry-After` capped at 30 s. Retry only definite pre-send connection failures, 429, 5xx and pre-audio SSE errors. Post-send/audio ambiguity is unknown and never retried automatically.
- [ ] Test normal/multibyte/split SSE, timestamps, errors, truncation, retries, ambiguity, exact bytes, dictionary evidence and WAV wrapping using sanitized fixtures only; run all gates and commit.

## Verification

- Request bytes, preview evidence and frozen headers/body match exactly.
- Malformed markup/SSE never becomes synthesis input.
- Retry tests distinguish safe retries from unknown outcomes; no test calls the provider.
