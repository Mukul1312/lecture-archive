# SSGGSM Odia Narration Minimum Local Studio v1 — Task 3M Durable Filesystem and Audio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status (2026-09-03): Complete and smoke-verified; not hardened.** The deferred
> hardening gate below remains mandatory before the first paid/private Cartesia call.

**Goal:** Make the existing Narrator Voice domain/application durable on one private Windows machine, with exact WAV handling, restart-safe budget/recovery evidence, and minimum local maintenance commands.

**Architecture:** Concrete adapters implement the existing Narrator Voice application ports. Small context-neutral filesystem primitives live in `heritage_archive.platform.storage`; Narrator-specific paths, schemas and recovery meanings stay in `contexts.narrator_voice.infrastructure`; the composition root alone wires them. Exactly three aggregate repositories remain, and audio bytes remain immutable files outside aggregate snapshots.

**Tech Stack:** Python 3.11 standard library (`pathlib`, `hashlib`, `json`, `os`, `shutil`, `wave`, `msvcrt` on Windows), the existing canonical schema-v1 codec, and `unittest`. No database, web framework, provider SDK, FFmpeg or live network access.

**Spec:** [Cartesia Odia narration minimum local-studio design — v4](../specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md)

**Authority:** [ADR-0012](../../decisions/0012-narrator-voice-v1-is-a-minimum-local-studio.md)

**Prerequisite closure:** [Task 2C Recovery Closure](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-2c-recovery-closure.md)

## Global Constraints

- Work only in `feature/narrator-voice-production-v1`; never push or make a paid/private Cartesia call.
- `CARTESIA_NARRATION_ROOT` must name an explicit existing directory outside the repository and all worktrees. There is no default and no `.env` loader.
- `CARTESIA_API_KEY`, private voice/dictionary identifiers, authorization evidence paths and absolute artifact paths never enter tracked files or browser-facing results.
- Keep exactly three aggregate roots/repositories: `AuthorizationRecord`, `NarrationJob`, and `DiaryEpisode`.
- Use one application-wide writer lock. Do not create per-aggregate or per-attempt lock hierarchies.
- Every persisted aggregate revision is a complete canonical schema-v1 snapshot. Publish it through unique staging, flush, verify bytes/digest, and rename without overwriting.
- Current state is the highest valid contiguous revision beginning at revision 1. Preserve and report gaps, invalid revisions and incomplete staging; never repair or delete them automatically.
- Audio is non-empty, non-silent PCM16 little-endian, mono, 44,100-Hz WAV. Assembly concatenates exact PCM frames and explicit zero-valued sample gaps only.
- Persist budget reserve/settle/release/hold facts in `operations/budget-ledger.json`; never automatically retry or release ambiguous charged work.
- Task 3M does not include Cartesia HTTP/SSE, `serve`, a website, word-timing normalization, DSP, music, publishing, multi-user support, CQRS/event sourcing, generic storage frameworks or exhaustive hardening.
- Track each slice separately as `implemented`, `smoke-verified`, and `hardened`. Only focused smoke checks are required to advance; all deferred hardening must pass before the first real paid/private generation.
- Preserve unrelated dirty-worktree changes. Stage exact Task 3M paths only.

## File Map

Create or modify only these planned areas:

```text
src/heritage_archive/
  platform/
    __init__.py
    storage/
      __init__.py
      local_files.py
  contexts/narrator_voice/infrastructure/
    __init__.py
    local_root.py
    filesystem_repositories.py
    filesystem_evidence.py
    pcm_audio.py
    budget_ledger.py
    operations.py
    cli.py
  composition_root/
    __init__.py
    narrator_voice_cli.py

tests/heritage_archive/
  platform/test_local_files.py
  narrator_voice/
    test_local_root.py
    test_filesystem_repositories.py
    test_filesystem_evidence.py
    test_pcm_audio.py
    test_budget_ledger.py
    test_durable_recovery.py
    test_operations.py
    test_cli.py
```

The application port signatures remain unchanged except for the approved Task 2C additions and Task 7's minimal `GenerationBudgetLedger.reserve(..., run_id: CommandId)` addition. The existing command ID is the generation-run identity: a batch already passes one command ID to every take, while a standalone take has its own command ID. Private project and billing-cycle identifiers remain infrastructure configuration. `application/schema_v1.py` remains the canonical aggregate codec.

---

## Slice 3A — Local root, one lock and three repositories

### Task 1: Explicit local root and generic file publication primitives

**Files:**

- Create: `src/heritage_archive/platform/__init__.py`
- Create: `src/heritage_archive/platform/storage/__init__.py`
- Create: `src/heritage_archive/platform/storage/local_files.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/__init__.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/local_root.py`
- Create: `tests/heritage_archive/platform/__init__.py`
- Create: `tests/heritage_archive/platform/test_local_files.py`
- Create: `tests/heritage_archive/narrator_voice/test_local_root.py`
- Modify: `tests/heritage_archive/test_architecture.py`

**Interfaces:**

- Produces `SingleWriterFileLock(lock_path: Path)` as a context manager that locks one byte and raises `WriterLockUnavailable` rather than waiting indefinitely.
- Produces `PublishedFile(sha256_hex: str, byte_length: int)`.
- Produces `publish_bytes_no_clobber(staging_directory: Path, destination: Path, payload: bytes) -> PublishedFile`.
- Produces `replace_bytes_atomically(staging_directory: Path, destination: Path, payload: bytes) -> PublishedFile` only for explicitly mutable operational files such as the budget ledger.
- Produces `LocalNarrationRoot.open(path: str | Path, forbidden_roots: tuple[Path, ...]) -> LocalNarrationRoot` and `initialize_layout()`.

- [x] **Step 1: Write focused root and file primitive tests**

  Assert that missing/relative/root-inside-repository paths are rejected, an external temporary root is accepted, a second non-blocking writer lock is refused, no-clobber publication preserves the first destination, and a successfully published file exactly matches the supplied SHA-256 and byte count.

- [x] **Step 2: Run the tests and observe the missing-module failure**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.heritage_archive.platform.test_local_files tests.heritage_archive.narrator_voice.test_local_root -v
  ```

  Expected: import failure because the platform storage and Narrator Voice infrastructure modules do not exist.

- [x] **Step 3: Implement only the tested primitives**

  `publish_bytes_no_clobber` must create a UUID-named staging file with mode `xb`, write bytes, flush and `os.fsync`, reread and hash it, reject any mismatch, then move it to a destination that must not already exist. With the one writer lock held, an existence check plus Windows no-overwrite rename is the publication boundary. Preserve the staging file whenever publication cannot be proven.

  `LocalNarrationRoot` must expose only safe child directories (`aggregates`, `staging`, `artifacts`, `attempts`, `operations`) and `.writer.lock`. It must reject filesystem roots, repository/worktree descendants, missing directories, non-directories and reparse points. It must not inspect or load an API key.

- [x] **Step 4: Run the focused tests and architecture guard**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.heritage_archive.platform.test_local_files tests.heritage_archive.narrator_voice.test_local_root tests.heritage_archive.test_architecture -v
  ```

  Expected: PASS. Architecture assertions prove platform never imports a bounded context and domain/application remain filesystem-free.

### Task 2: Immutable canonical aggregate revision repositories

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_repositories.py`
- Create: `tests/heritage_archive/narrator_voice/test_filesystem_repositories.py`

**Interfaces:**

- Produces `FilesystemAuthorizationRecordRepository` implementing `AuthorizationRecordRepository`.
- Produces `FilesystemNarrationJobRepository` implementing `NarrationJobRepository`.
- Produces `FilesystemDiaryEpisodeRepository` implementing `DiaryEpisodeRepository`.
- All three use one private `_FilesystemSnapshotRepository` helper and the same `SingleWriterFileLock` path.

**Required layout:**

```text
aggregates/<aggregate-kind>/<aggregate-id>/revisions/<20-digit-revision>.json
staging/<unique-publication-name>.json
```

- [x] **Step 1: Write repository contract tests using real aggregates**

  For each root, save revision 1 with `expected_revision=None`, construct a fresh repository instance, load and compare `to_snapshot()`, mutate through a real domain method, save with the prior revision, and reload. Assert that a stale expected revision returns `False`, creates no file and leaves current state unchanged.

  Add one corruption/gap test: revision 1 valid, revision 2 missing or invalid, revision 3 present. Loading must return revision 1 rather than the highest numeric filename. Loading an absent ID returns `None`.

- [x] **Step 2: Run and observe the missing repository adapters**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_filesystem_repositories -v
  ```

  Expected: import failure for `filesystem_repositories`.

- [x] **Step 3: Implement the three thin adapters**

  Under the shared lock, `save` must compute current contiguous state, compare it with `expected_revision`, encode `root.to_snapshot()` using `encode_schema_v1`, and publish the exact bytes without overwrite. It returns `False` only for ordinary create/update CAS refusal. Invalid canonical data, an occupied target revision or storage corruption raises `ValidationError` and is never silently replaced.

  `load` decodes with the exact snapshot type and reconstructs through `Root.from_snapshot(...)`; it never returns a cached mutable instance. Do not add a generic repository port, mutable `HEAD`, event ledger or separate child repository.

- [x] **Step 4: Run focused repository and architecture tests**

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_filesystem_repositories tests.heritage_archive.test_architecture -v
  ```

  Expected: PASS.

- [x] **Step 5: Record the 3A checkpoint**

  Run `git diff --check`, inspect only Task 3M paths, and record status as `implemented` and `smoke-verified`. Do not claim `hardened` and do not run the full repository suite.

---

## Slice 3B — Immutable artifacts and exact PCM audio

### Task 3: Immutable artifact store and evidence verification

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_evidence.py`
- Create: `tests/heritage_archive/narrator_voice/test_filesystem_evidence.py`

**Interfaces:**

- Produces `FilesystemArtifactStore.publish(...) -> PublishedArtifact`.
- Produces `FilesystemArtifactEvidenceVerifier.verify(...) -> VerifiedArtifactRecoveryFacts`.
- After Task 2C, implements `recover_media(workspace, artifact) -> DecodedMediaFacts` through the injected `MediaInspector`.

- [x] Write failing tests for exact publish, idempotent same-byte observation, conflicting no-clobber publication, traversal/reparse rejection, hash/length verification and tampered-byte refusal.
- [x] Run `test_filesystem_evidence` and observe failure for the absent adapter.
- [x] Implement content verification without adding an artifact repository. Persist bytes at the requested `SafeRelativeArtifactPath`; the returned evidence binds SHA-256, byte length, media type, safe path and publication time.
- [x] Run `test_filesystem_evidence` and the architecture guard; record `implemented` and `smoke-verified` only.

### Task 4: Canonical WAV inspector and dry assembler

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_evidence.py`
- Modify: `tests/heritage_archive/narrator_voice/test_filesystem_evidence.py`
- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/pcm_audio.py`
- Create: `tests/heritage_archive/narrator_voice/test_pcm_audio.py`

**Interfaces:**

- Produces `CanonicalWavInspector.inspect_canonical_wav(payload: bytes) -> DecodedMediaFacts`.
- Produces `ExactPcmAssembler.assemble_narration(...) -> DryAssemblyResult`.
- Produces `ExactPcmAssembler.assemble_episode(...) -> DryAssemblyResult`.
- Adds an infrastructure-only `FilesystemArtifactEvidenceVerifier.read_verified_bytes(...) -> bytes` seam so audio assembly reuses the artifact path, reparse, digest and length checks. This does not change an application port.

- [x] Write literal-fixture tests for valid PCM16 mono 44.1-kHz WAV, wrong rate/channels/width/compression, empty PCM and all-zero PCM.
- [x] Write exact assembly tests proving output frames equal `source + zero_samples + source`, and passage/component offsets equal hand-calculated integer samples.
- [x] Run `test_pcm_audio` and observe missing implementation failure.
- [x] Implement with stdlib `wave` and `io.BytesIO`. Reject unsupported facts; never resample, convert, normalize or use floating-point sample calculations.
- [x] Run `test_pcm_audio`, `test_diary_episode_assembly`, and the architecture guard. Record the 3B checkpoint without broad hardening.

---

## Task 2C gate — Recovery contracts before persistent recovery

### Task 5: Complete and smoke-verify Task 2C

**Files:** Follow the separate [Task 2C plan](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-2c-recovery-closure.md) exactly.

- [x] Add `AttemptWorkspaceEvidence.frozen_plan_digest` and digest-bound verification.
- [x] Add the expected frozen-plan digest to `AttemptWorkspaceVerifier.verify`.
- [x] Add typed `ArtifactEvidenceVerifier.recover_media`.
- [x] Persist strongest workspace and budget facts before the one post-side-effect aggregate CAS.
- [x] Smoke-run only Task 2C’s focused checks.

Task 3A and the independent portion of 3B may be completed before this gate. Task 3C must not begin until the gate passes, because otherwise its on-disk schema would immediately require rework.

---

## Slice 3C — Durable workspaces, budget and targeted reconciliation

### Task 6: Attempt workspaces and trusted recovery verifiers

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/infrastructure/filesystem_evidence.py`
- Create: `tests/heritage_archive/narrator_voice/test_durable_recovery.py`

**Interfaces:**

- Produces `FilesystemAttemptWorkspaceStore` implementing `AttemptWorkspaceStore`.
- Produces `FilesystemAttemptWorkspaceVerifier`, `FilesystemProviderEventVerifier`, and the completed `FilesystemArtifactEvidenceVerifier`.

- [x] Write failing tests for exact repeated-save idempotence, conflicting immutable bindings, permitted evidence-stage advancement, frozen-plan mismatch and restart-time verification.
- [x] Implement one canonical workspace file per attempt through staged atomic replacement under the application lock. Identity, aggregate, attempt kind, reservation revision and frozen plan never change; only stronger evidence progression is accepted.
- [x] Connect one explicit recovery target to the existing reconciliation handler and prove it completes without another provider, assembler or artifact publication.
- [x] Run only `test_durable_recovery` plus existing focused recovery tests.

### Task 7: Restart-safe budget ledger

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/budget_ledger.py`
- Create: `tests/heritage_archive/narrator_voice/test_budget_ledger.py`

**Interfaces:**

- Produces one `FilesystemGenerationBudgetLedger` implementing both `GenerationBudgetLedger` and `BudgetReservationStatusReader`.
- Uses exactly `operations/budget-ledger.json` as its authority.

- [x] Write failing tests for per-take, per-run and billing-cycle denial; reserve-before-settle; exact-repeat idempotence; conflicting usage refusal; no downgrade from settled; ambiguous hold; and restart reads.
- [x] Add the generation `CommandId` to `GenerationBudgetLedger.reserve` and pass `GenerateTakeCommand.command_id`; do not add project, billing-cycle or provider configuration to the application contract.
- [x] Implement canonical append-only facts and derive current reservation/cap state by replay. Replace the complete ledger atomically under the same writer lock; never use a second lock or fourth aggregate.
- [x] Run `test_budget_ledger` and the generation/recovery focused tests. Record 3C as `implemented` and `smoke-verified`, not hardened.

---

## Slice 3D — Minimum operations and local entry point

### Task 8: Init, doctor, backup, verification and restore

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/operations.py`
- Create: `tests/heritage_archive/narrator_voice/test_operations.py`

**Interfaces:**

- Produces `initialize_local_studio`, `doctor`, `backup`, `verify_backup`, and `restore` functions returning frozen redacted result objects.
- Produces strict private `load_local_studio_initialization(path)` and `load_local_studio_configuration(root)` seams so the later composition root never duplicates the private configuration schema.

- [x] Write failing tests proving init creates the private layout/config without an API key; doctor reports but does not mutate invalid/staging evidence; backup copies a locked complete root and writes SHA-256/size manifest; verification catches tampering; restore refuses non-empty destinations and verifies the restored copy.
- [x] Implement a full-copy backup only. No incrementality, schedules, encryption, retention or cleanup.
- [x] Run `test_operations` and one backup/restore temporary-root round trip.

### Task 9: Explicit reconcile command and composition root

**Files:**

- Create: `src/heritage_archive/contexts/narrator_voice/infrastructure/cli.py`
- Create: `src/heritage_archive/composition_root/__init__.py`
- Create: `src/heritage_archive/composition_root/narrator_voice_cli.py`
- Create: `tests/heritage_archive/narrator_voice/test_cli.py`
- Modify: `pyproject.toml` only if an installed `heritage-narrator` entry point is chosen.

- [x] Write failing command tests for `init`, `doctor`, explicit-attempt `reconcile`, `backup`, `verify-backup`, and `restore`; assert redacted output and non-zero status for invalid arguments/state.
- [x] Wire the three repositories and concrete adapters in the composition root. The CLI parses inputs and calls operations/application handlers; it never embeds domain decisions.
- [x] Run the CLI tests and architecture guard. Do not implement `serve`.

Use `python -m heritage_archive.composition_root.narrator_voice_cli` for v1 and leave `pyproject.toml` entry points unchanged. The live root comes only from `CARTESIA_NARRATION_ROOT`; `init` accepts one external private `--config-file`, while backup verification accepts an explicit source. Do not add a `--root` fallback, interactive secret prompts or `.env` loading.

From a fresh checkout, first install the package into the selected virtual environment with `python -m pip install --no-deps -e .`; then invoke the module command above. A source-only test may set `PYTHONPATH` explicitly, but production instructions must not imply that an uninstalled `src/` layout is automatically importable.

### Task 10: Task 3M smoke checkpoint

- [x] Run the focused Task 3M modules, affected recovery/application tests, and architecture guard once.
- [x] Run `git diff --check` and inspect the staged path list for secrets, provider identifiers, audio and unrelated changes.
- [x] Exercise a temporary-root restart/load, stale CAS, immutable artifact, exact WAV/offset, held-budget recovery and backup/restore smoke path.
- [x] Record the deferred hardening list: process-crash edges, expanded Windows/reparse/path matrix, storage corruption matrix, budget concurrency, audio malformed-container matrix and backup fault injection.
- [x] Make one local Task 3M checkpoint commit only after smoke verification; do not push.

## Completion Criteria

Task 3M is complete when:

- all three aggregates survive process restart through immutable canonical revisions;
- stale expected revisions cannot overwrite current state;
- all storage mutation shares one application lock;
- immutable artifacts and recovery workspaces bind exact hashes, lengths, paths and frozen plans;
- canonical WAV inspection and assembly preserve exact samples and offsets;
- the budget ledger survives restart and conservatively holds ambiguous work;
- explicit reconciliation never replays external work;
- backup verification detects tampering and restore accepts only an empty root;
- focused smoke tests and architecture checks pass; and
- no Cartesia transport, website, secrets or generated private audio entered the change.

## Deferred Hardening Gate

Before the first real paid/private Cartesia call, return to Task 3M and harden restart/CAS, artifact integrity, canonical audio, budget unknown handling, reconciliation and backup/restore. This is a release gate, not a reason to delay Plan 4M and Plan 5M implementation after smoke verification.
