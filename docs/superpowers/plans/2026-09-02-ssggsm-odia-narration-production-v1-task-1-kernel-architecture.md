# SSGGSM Odia Narration Production v1 — Task 1: Package, Kernel and Architecture

**Goal:** Establish the importable Narrator Voice package, lift only the accepted safe
kernel manifest, and enforce the inward architecture before production behavior.

**Spec:** `docs/superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md`

## Global constraints

- The accepted v3 design and ADR-0006 through ADR-0011 bind whenever this plan is less specific; ADR-0001 and ADR-0005 are accepted.
- Perform this feature work only in the isolated linked worktree created after the documentation baseline commit; do not push, merge, publish or make a live Cartesia request.
- Never track private Odia text, authorization evidence, API keys, provider IDs, generated/reference audio, raw private timing or production stores.
- Existing tracked `data/narration/**` is frozen legacy evidence and is not read by Narrator Voice.
- Never import or extend `heritage_production`. The future non-SSGGSM English/Hindi narration programme remains active and intact; its useful technical knowledge may be reused through characterization only.
- Dependencies point inward: domain uses only stdlib plus kernel; application imports domain/ports; infrastructure implements ports and may reach platform; platform never imports a context; composition root is the sole sink/wiring boundary.
- There are exactly three aggregate roots/repositories: `AuthorizationRecord`, `NarrationJob`, and `DiaryEpisode`; all other records are children or immutable values.
- The v3 authority model wins: initial active attestation, narrowing and irreversible withdrawal only; draft is editor state, expiry is derived, and suspension/reactivation are not transitions.
- Use `ReleaseSynthesisContract`, `DeliveryControlDefaults`, `EffectiveTakeSettings`, and `EffectiveSynthesisInput` vocabulary.
- Persist canonical integers and decimal strings, never JSON floats; browser input is never authoritative for ActorId, provider transcript, private references or paths.
- Production audio is dry PCM16 little-endian mono 44.1-kHz WAV; assembly is exact PCM concatenation with explicit zero-sample gaps and no hidden DSP.
- Production gap values have no numeric default; private configuration supplies them and tests use explicit literals.
- No automated test contacts Cartesia or consumes credits; the first live call requires a separate approval.
- Follow RED/GREEN/refactor for production behavior. Documentation, generated contracts and dependency locks are exempt from a contrived RED step.
- Stage and commit exact paths only; never use `git add -A`, push, merge or publish.

## Accepted kernel manifest

The historical 1,044-line count is a pre-`AggregateEventRecorder` source measurement,
not a destination target. Characterize the audited sources first, then lift only this
consumer-driven v1 manifest and remeasure it after the trim:

- `canonical.py`: `JsonValue`, `canonical_json`, `parse_strict_json`, and `semantic_digest`.
- `digests.py`: `ArtifactRef` and `ContentDigest`.
- `errors.py`: `ValidationError`.
- `ids.py`: `ActorId` and `ArtifactId`.
- `text.py`: `require_canonical_text`.
- `transcript.py`: `TranscriptText`.
- A trimmed `__init__.py` may re-export only those symbols.

Do not lift `events.py` (`DomainEvent`, `SealedAggregateRoot`, or
`AggregateEventRecorder`), `time.py`, `sources.py`, `refs.py`, `trust.py`, credential
types, or any backup/production/review/release/source identity. Narrator-specific
events and identities belong in the Narrator Voice context. `ArtifactRef` from
`digests.py` is retained exactly as the generic artifact value.

## Execution

- [ ] Create focused characterization tests for canonical JSON/strict parsing/digests,
  generic artifacts, transcript text, `ActorId`, and `ArtifactId`; run them against the
  source behavior before moving code.
- [ ] Add `src/heritage_archive/kernel/` with only the manifest modules and trimmed
  export surface. Re-measure the resulting source after the consumer trim, record the
  exact retained source/symbol manifest and actual count in checkpoint evidence, and
  do not substitute arithmetic for imports.
- [ ] Import every retained module and public export in a dedicated test. Assert that
  excluded symbols and `heritage_production` imports are absent.
- [ ] Create only consumed package units under `contexts/narrator_voice/{domain,application,infrastructure}`, `platform/{audio,cartesia,execution,storage,web}`, and `composition_root`; do not create empty folders.
- [ ] Keep Narrator Voice identities, `SafeRelativeArtifactPath`, and `CanonicalAudioFacts` in Narrator Voice rather than the kernel.
- [ ] Make architecture guards non-vacuous: prohibited outward imports, context isolation, platform isolation, kernel stdlib purity, composition-root sink behavior, and cycles all have concrete failing cases.
- [ ] Run focused RED/GREEN tests, all active suites, package build/import checks, and `git diff --check`.
- [ ] Commit the checkpoint using an exact path allowlist.

## Verification

- The measured post-exclusion source count is reported as evidence, never promised as 1,044.
- Every retained module/export imports, and no test imports the shelved package.
- Architecture tests demonstrate each required failure mode and all active suites pass.
