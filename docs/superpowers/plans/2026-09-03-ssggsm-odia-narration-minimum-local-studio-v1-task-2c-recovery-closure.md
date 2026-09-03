# SSGGSM Odia Narration Minimum Local Studio v1 — Task 2C Recovery Closure

> **For agentic workers:** use `superpowers:executing-plans` to execute this plan.
> Work through the tasks in order because they share evidence types and handlers.
> Stop after the Task 2C checkpoint; do not begin Task 3M.

**Goal:** Close only the persistence-critical gaps left in the already implemented
Narrator Voice domain/application baseline, so a generated or assembled audio artifact
cannot be repeated or detached from its exact inputs after an aggregate revision
conflict.

**Architecture:** Keep the existing three aggregate roots and three repositories.
Strengthen the existing attempt-workspace recovery seam, then persist trustworthy
workspace and budget evidence before trying an aggregate compare-and-swap (CAS) after
external work. Explicit reconciliation completes the existing attempt from that
evidence; it never calls the provider or audio assembler again.

**Tech stack:** Python 3.11, frozen dataclasses, standard-library `unittest`, the
existing `heritage_archive.kernel` canonical digest helpers, and the existing
Narrator Voice domain/application modules and fake adapters.

**Parent plan:**
[SSGGSM Odia Narration Minimum Local Studio v1](2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1.md)

**Governing design:**
[Cartesia Odia Narration Minimum Local Studio v4](../specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md)
and [ADR-0012](../../decisions/0012-narrator-voice-v1-is-a-minimum-local-studio.md).

**Implementation status (2026-09-03): Complete and smoke-verified; not hardened.**
Tasks 1–4 were accepted through local commits `29811e6`, `0818050`, `6a51937`,
`e9f5f22`, `449b45a`, and `fd440dc`. The combined affected checkpoint passed 86
recovery/domain/application tests and 26 architecture checks. No network or paid
provider call was made. Durable filesystem implementations remain in Task 3M.

## Scope boundary

This is a small correctness closure, not another architecture phase.

In scope:

- prove that a narration snapshot came from the current source job;
- validate a historical selection against the latest operational review that existed
  when that selection was made;
- bind each recovery workspace to the exact generation, narration-assembly or
  episode-assembly plan;
- make recovery media retrieval an explicit application port;
- write post-side-effect workspace and budget evidence before aggregate CAS;
- complete an evidence-proven attempt from its existing nonterminal aggregate state;
- cover the changed behavior with focused no-network tests.

Out of scope:

- no new aggregate, repository, event store, outbox, unit-of-work framework or
  workflow engine;
- no Plan 3M filesystem repositories, locks, backups, commands or real WAV adapter;
- no Plan 4M Cartesia HTTP/SSE code and no provider call;
- no Plan 5M server or UI;
- no word-timing normalization or review work;
- no broad repository suite and no cosmetic rewrite of safe Plan 2 code.

Execution note (2026-09-03): the operator approved implementing independent Task 3M
filesystem/audio slices before this gate. Consequently, Task 2 must also update the
positional `AttemptWorkspaceEvidence` fixture in
`tests/heritage_archive/narrator_voice/test_filesystem_evidence.py`. This is the
small integration cost anticipated by that acceleration ruling; no Plan 3M
production adapter behavior belongs in this checkpoint.

## Current baseline — preserve it

The implementation baseline already contains the following Plan 2 behavior. Do not
reimplement or replace it:

| Capability | Current state |
| --- | --- |
| Three aggregate roots and repository ports | Implemented |
| Pure recovery reducer and three reconciliation handlers | Implemented |
| Attempt-owned selected take IDs, component snapshot digests and exact sample gaps | Implemented |
| Exact narration/episode master reconstruction during recovery | Implemented |
| Idempotent replay after a completed recovery | Implemented |
| Runtime selection based on the latest operational review | Implemented |
| No-network fake synthesis and audio assembly | Implemented |

The remaining defects are narrower:

| Gap | Consequence if left open |
| --- | --- |
| `is_snapshot_current` does not check issued-snapshot membership | A structurally valid but never-issued snapshot could be accepted |
| Rehydration accepts any earlier acceptance | An acceptance followed by rejection can incorrectly authorize a later selection |
| Workspace has no frozen assembly-plan digest | Storage cannot independently prove which takes/snapshots and gaps produced an artifact |
| Recovery calls `recover_media` dynamically | The application port contract does not promise the media evidence required for completion |
| Workspace/budget evidence is written after aggregate CAS | One or two CAS conflicts can lose the only safe route to reconciliation |

## Accepted recovery rule

After a chargeable provider call or immutable artifact publication, use this order:

```text
provider result or assembled artifact
              |
              v
save the strongest trustworthy attempt-workspace evidence
              |
              v
settle, release or hold the budget when generation is involved
              |
              v
attempt the aggregate CAS once
              |
              +-- succeeds --> finish the normal aggregate transition
              |
              +-- refuses  --> return UNKNOWN/recovery-required
                                  without a second CAS and without replay
              |
              v
explicit reconcile reads the durable evidence and completes or fails closed
```

“Once” means that each planned aggregate transition is attempted once. A normal
success may still have stage, publication and completion transitions, but a refusal
ends the handler; it never triggers an immediate compensating CAS.

`UNKNOWN` in a handler result means “the aggregate still needs reconciliation.” It
must not rewrite known facts. For example, a successful provider response remains
`SubmissionEvidence.COMPLETED`, its workspace remains
`AttemptState.ARTIFACTS_PUBLISHED`, and its budget remains settled even when the
aggregate CAS is refused.

Workspace persistence precedes budget finalization. If the workspace save itself
fails after the gateway was entered, do not attempt an aggregate completion; place
the reservation on hold with a workspace-persistence-failure reason and return a
recovery-required result. If budget finalization fails after the workspace succeeds,
the workspace still contains enough evidence to prevent an automatic replay; again,
do not attempt aggregate completion.

## Required port semantics

Task 2C fixes the behavior contract; Task 3M will later provide durable filesystem
implementations.

`AttemptWorkspaceStore.save(workspace)` must be treated as follows:

- it either completes or raises; it never silently drops evidence;
- saving exactly the same evidence again is an idempotent no-op;
- a later save for the same attempt may only add verified evidence or advance its
  recovery stage while retaining its identity and frozen bindings;
- it may never change the workspace ID, kind, aggregate ID, attempt ID, reservation
  revision, budget ID, preview digest, effective-input digest or frozen-plan digest;
- conflicting terminal facts are rejected.

`GenerationBudgetLedger` finalization must be treated as follows:

- repeated settlement with the same reservation and actual usage is idempotent;
- repeated release or hold with the same facts is idempotent;
- a settled reservation is never downgraded to a hold or release;
- conflicting usage or terminal dispositions are rejected.

The fake adapters in Task 2C must model these rules sufficiently for the focused
application tests. The full durable implementation remains Task 3M.

## Task 1 — Close snapshot and historical-selection authenticity

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/domain/narration_job.py`
- Test: `tests/heritage_archive/narrator_voice/test_narration_job_mastering.py`

### Behavior to add

1. Extend the snapshot-current test with a valid `NarrationMasterSnapshot` created by
   `NarrationMasterSnapshot.create(...)` from the same current master and evidence,
   but with a different snapshot ID and without issuing it through the job.
2. Assert that the genuine issued snapshot is current and the never-issued equivalent
   snapshot is not.
3. In `NarrationJob.is_snapshot_current`, find the issued member by `snapshot_id` and
   require exact dataclass equality before checking current master/listening/authority
   facts:

   ```python
   issued = next(
       (value for value in self._issued_snapshots if value.snapshot_id == snapshot.snapshot_id),
       None,
   )
   if issued != snapshot:
       return False
   ```

4. Add a rehydration regression containing this decision order for one take:

   ```text
   operational ACCEPTED -> operational REJECTED -> selection
   ```

   Give the invalid selection a decision time at or after the rejection and assert
   that `NarrationJob.from_snapshot(...)` raises `ValidationError`.
5. Replace the current `any(prior acceptance)` rehydration rule with the latest
   eligible operational review rule. Iterate the append-only review tuple in reverse,
   restrict it to the selected take and `review.decided_at <= selection.decided_at`,
   and require that first match to be `ReviewOutcome.ACCEPTED`.

Do not change the already-correct runtime `_latest_operational_review` selection path.

### Focused check

```powershell
.\.venv\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_narration_job_mastering -v
```

## Task 2 — Freeze each recovery plan and make media recovery explicit

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/domain/evidence.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/domain/narration_job.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/domain/diary_episode.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/ports.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/handlers.py`
- Modify: `tests/heritage_archive/narrator_voice/fakes.py`
- Test: `tests/heritage_archive/test_architecture.py`
- Test: `tests/heritage_archive/narrator_voice/test_evidence_schema.py`
- Test: `tests/heritage_archive/narrator_voice/test_narration_job_attempts.py`
- Test: `tests/heritage_archive/narrator_voice/test_narration_job_mastering.py`
- Test: `tests/heritage_archive/narrator_voice/test_diary_episode_assembly.py`
- Test: `tests/heritage_archive/narrator_voice/test_application_recovery.py`
- Test: `tests/heritage_archive/narrator_voice/test_filesystem_evidence.py` (constructor compatibility only)

### 2.1 Add domain-separated plan digests

Add these pure helpers to `domain/evidence.py`:

```python
def narration_assembly_plan_digest(
    selected_take_ids: tuple[TakeId, ...],
    gaps_samples: tuple[int, ...],
) -> ContentDigest:
    return semantic_digest(
        "narrator_voice.narration_assembly_plan.v1",
        {
            "selected_take_ids": [str(value.value) for value in selected_take_ids],
            "gaps_samples": list(gaps_samples),
        },
    )


def episode_assembly_plan_digest(
    component_snapshot_digests: tuple[ContentDigest, ...],
    gap_samples: int,
) -> ContentDigest:
    return semantic_digest(
        "narrator_voice.episode_assembly_plan.v1",
        {
            "component_snapshot_digests": [value.hex_digest for value in component_snapshot_digests],
            "gap_samples": gap_samples,
        },
    )
```

Validate the nominal tuple member types, exact component count, and nonnegative
integer gaps before hashing. Use integers and strings only; never put a binary float
in a canonical digest payload.

### 2.2 Extend `AttemptWorkspaceEvidence`

Add:

```python
frozen_plan_digest: ContentDigest | None
```

between `effective_input_digest` and `submission`.

Enforce:

- generation: `frozen_plan_digest == effective_input_digest`; both may be `None` only
  before the effective input is frozen;
- narration and episode assembly: `frozen_plan_digest` is required;
- `matches_completion_binding(...)` receives the expected frozen-plan digest and
  compares it exactly.

Populate the field in the three handler constructors:

- `_workspace`: use `effective_input.request_digest` when an effective input exists;
- `_narration_assembly_workspace`: derive it from the attempt’s ordered
  `selected_take_ids` and `gaps_samples`;
- `_episode_assembly_workspace`: derive it from the attempt’s ordered
  `component_snapshot_digests` and `gap_samples`.

Because Task 3 persistence does not exist yet, this is an intentional in-place update
to the pre-persistence schema-v1 handoff. The generic codec needs no special-case
branch; its strict field-set behavior and round-trip tests must cover the new field.

### 2.3 Give the verifier an expected digest

Change the workspace verifier port to:

```python
class AttemptWorkspaceVerifier(Protocol):
    def verify(
        self,
        workspace: AttemptWorkspaceEvidence | None,
        target: RecoveryTarget,
        attempt_state: AttemptState,
        reservation_revision: int,
        expected_frozen_plan_digest: ContentDigest | None,
    ) -> VerifiedWorkspaceRecoveryFacts: ...
```

Pass the expected digest through `_trusted_recovery_facts` and
`_verified_completion_workspace`. Each reconciliation handler derives it from the
loaded aggregate attempt, never from a browser command:

- generation: the frozen effective input request digest, or `None` when not frozen;
- narration assembly: `narration_assembly_plan_digest(...)`;
- episode assembly: `episode_assembly_plan_digest(...)`.

Update `FakeAttemptWorkspaceVerifier` so `frozen_plan_matches` is true only when the
workspace field equals the supplied expected digest. Add a separate optional
`force_frozen_plan_match` override for reducer-focused negative tests; ordinary
application tests must compare the real digests.

Also pass the same computed digest into each aggregate recovery method’s
`matches_completion_binding(...)` call. This gives two layers of defense: the
application verifier decides whether durable storage proves the plan, and the
aggregate independently binds the recovered object to its attempt.

### 2.4 Make media recovery part of the port

Extend `ArtifactEvidenceVerifier` explicitly:

```python
class ArtifactEvidenceVerifier(Protocol):
    def verify(
        self,
        workspace: AttemptWorkspaceEvidence | None,
    ) -> VerifiedArtifactRecoveryFacts: ...

    def recover_media(
        self,
        workspace: AttemptWorkspaceEvidence,
        artifact: PublishedArtifact,
    ) -> DecodedMediaFacts: ...
```

Replace the `getattr(..., "recover_media", None)` branch in
`_verified_workspace_artifact_and_media` with the typed port call. Implement the
method in `FakeArtifactEvidenceVerifier`; it must reject an artifact that is not the
workspace’s exact published artifact and return configured non-silent decoded facts.
The test-only `RecoveryArtifactEvidence` subclass may configure the media but must no
longer invent the method outside the port contract.

Extend the architecture test to assert that the port declares `recover_media` and
the recovery handler no longer dynamically probes for that method.

### Focused checks

```powershell
.\.venv\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_evidence_schema tests.heritage_archive.narrator_voice.test_narration_job_attempts tests.heritage_archive.narrator_voice.test_narration_job_mastering tests.heritage_archive.narrator_voice.test_diary_episode_assembly tests.heritage_archive.narrator_voice.test_application_recovery -v
```

## Task 3 — Persist generation evidence before post-provider CAS

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/domain/narration_job.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/handlers.py`
- Modify: `tests/heritage_archive/narrator_voice/fakes.py`
- Test: `tests/heritage_archive/narrator_voice/test_application_generation.py`
- Test: `tests/heritage_archive/narrator_voice/test_application_recovery.py`

### 3.1 Make the fake side-effect stores safely repeatable

Update `FakeWorkspaceStore` and `FakeBudgetLedger` to enforce the port semantics in
this plan. Keep their call/action recording, add explicit one-shot save/finalization
failure injection, make an exact repeated finalization a no-op, and raise
`ValidationError` for a conflicting rewrite or for downgrading a settled budget to
hold/release.

### 3.2 Reorder every post-gateway path

In `GenerateTakeHandler`, preserve the existing reservation-before-provider rule.
After the gateway is entered, use this exact table:

| Observed outcome | Durable workspace written before aggregate CAS | Budget action before aggregate CAS | Intended aggregate result |
| --- | --- | --- | --- |
| `DefinitePreSendFailure` | `BLOCKED` + `DEFINITELY_NOT_SENT` + reason | release | `BLOCKED` |
| `AmbiguousExternalFailure` | `UNKNOWN` + `AMBIGUOUS` + reason | hold | `UNKNOWN` |
| `ExternalWorkFailed` without trusted usage | `FAILED` + `STARTED` + reason | hold | `FAILED` |
| Returned but structurally invalid result | `FAILED` + `COMPLETED` + independently valid sealed events when available + reason; never fabricate or retain malformed events | settle actual usage | `FAILED` |
| Valid non-silent published WAV | `ARTIFACTS_PUBLISHED` + `COMPLETED` + exact input/events/artifact | settle actual usage | stage, publish, then complete or quarantine |

For artifact-bearing success, save the `ARTIFACTS_PUBLISHED` workspace immediately
after immutable artifact publication, then settle usage, then begin the aggregate
stage/publish/complete CAS sequence. The workspace does not need a later
`COMPLETED` rewrite: aggregate completion is authoritative, while the workspace’s job
is to prove the already-published artifact and frozen input.

For authority loss after publication, retain the already-settled budget and complete
the aggregate as `QUARANTINED`; never rewrite provider submission to ambiguous.

### 3.3 Remove the second-CAS recovery write

Replace `_record_post_external_cas_unknown` with a result-only helper and use it for
every aggregate refusal after the gateway has been entered. It may reload the
aggregate to report its actual persisted revision, but it must not:

- call `finalize_generation_outcome`;
- save the aggregate a second time;
- downgrade the settled budget to hold;
- overwrite the known workspace with `UNKNOWN`/`AMBIGUOUS`.

Return `GenerationRunResult(state=AttemptState.UNKNOWN, take_id=None, ...)` to signal
that explicit reconciliation is required. Report the already-durable budget
disposition (`settled`, `released` or `held`) accurately.

This result rule applies to pre-send, ambiguous, definite-failure, invalid-result,
artifact-stage, publication, quarantine and final-completion CAS refusals. The
workspace records what is known; the result records that aggregate finalization is
not yet confirmed.

If the first critical workspace save fails after the provider was entered, catch that
failure, hold the reservation with an exact persistence-failure reason, make no
aggregate CAS and return recovery-required. If workspace persistence succeeds but
settlement fails, make no aggregate CAS; preserve the workspace and return
recovery-required. Explicit reconciliation may hold or quarantine conservatively,
but neither path may invoke the provider again.

### 3.4 Permit direct evidence-proven completion

`NarrationJob.recover_generation_completion` currently assumes that the failed
handler managed to store aggregate state `UNKNOWN`. Permit exact verified completion
instead when the **aggregate attempt** is in:

- `EXTERNAL_WORK_STARTED`;
- `ARTIFACTS_STAGED`;
- `ARTIFACTS_PUBLISHED`;
- `UNKNOWN`;
- or an exact idempotent replay from `COMPLETED`.

Continue rejecting `RESERVED`, `INPUT_FROZEN`, and every conservative terminal state.
The durable workspace remains `ARTIFACTS_PUBLISHED`; do not require it to imitate the
aggregate’s intermediate state. Do not loosen any artifact, media, effective-input,
authorization or budget proof.

### 3.5 Focused regressions

Update the existing post-provider CAS test to assert:

```text
result             = UNKNOWN / reconciliation required
persisted attempt  = last aggregate state accepted before the conflict
workspace          = ARTIFACTS_PUBLISHED + COMPLETED submission
budget             = SETTLED
provider calls     = 1
artifact publishes = 1
```

Add these cases:

1. Reject the first post-artifact aggregate save and the immediately following save.
   The generation handler must consume only the first refusal because it performs no
   second CAS. The first explicit reconciliation must raise `RevisionConflict` when
   its save consumes the second refusal. Supply two recovery IDs because that failed
   reconciliation’s generated ID was never persisted. A fresh-load second
   reconciliation then completes exactly once without another provider call or
   artifact publication.
2. Reject the final normal completion CAS. One explicit reconciliation completes the
   attempt exactly once from the already-published workspace.
3. Reject the aggregate save after an invalid returned provider result. Assert that
   workspace evidence and the settled budget exist before the refusal and that no
   provider retry occurs. A conservative unresolved result is acceptable when no
   valid artifact exists; Task 2C must preserve evidence, not manufacture audio.
4. Fail the first post-provider workspace save. Assert no aggregate completion CAS,
   a held reservation, an `UNKNOWN` result and no provider replay.
5. Let workspace persistence succeed but fail budget settlement. Assert no aggregate
   completion CAS, preserved `ARTIFACTS_PUBLISHED` evidence, and conservative
   reconciliation without provider replay.

### Focused check

```powershell
.\.venv\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_application_generation tests.heritage_archive.narrator_voice.test_application_recovery -v
```

## Task 4 — Apply the same ordering to narration and episode assembly

**Files:**

- Modify: `src/heritage_archive/contexts/narrator_voice/domain/narration_job.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/domain/diary_episode.py`
- Modify: `src/heritage_archive/contexts/narrator_voice/application/handlers.py`
- Test: `tests/heritage_archive/narrator_voice/test_application_recovery.py`
- Test: `tests/heritage_archive/narrator_voice/test_application_episode.py`

### Behavior to implement

1. In `AssembleNarrationMasterHandler`, after the assembler returns and the immutable
   artifact is published, save an `ARTIFACTS_PUBLISHED` narration workspace containing
   the exact frozen-plan digest and artifact before any stage/publish/complete CAS.
2. In `AssembleEpisodeSpeechMasterHandler`, do the same with the exact two component
   snapshot digests and intro-to-diary gap digest.
3. Replace both `_record_post_artifact_cas_unknown` helpers with result-only helpers.
   They may reload current persisted revision; they perform no follow-up aggregate
   save and no second assembly or artifact publication.
4. Permit `recover_narration_assembly_completion` and
   `recover_episode_assembly_completion` to complete directly from
   aggregate-attempt state `EXTERNAL_WORK_STARTED`, `ARTIFACTS_STAGED`,
   `ARTIFACTS_PUBLISHED` or `UNKNOWN`, while retaining exact completed replay. The
   workspace itself remains `ARTIFACTS_PUBLISHED`. Continue rejecting earlier and
   terminal aggregate states.
5. Preserve the current source-authority check. If authority is no longer eligible,
   reconciliation quarantines the existing artifact; it never assembles again.

### Focused regressions

Cover one early post-artifact CAS refusal for narration and one for episode. For each,
assert:

- one assembler call;
- one artifact publication for that attempted master;
- an `ARTIFACTS_PUBLISHED` workspace with the expected frozen-plan digest;
- an `UNKNOWN` handler result without an immediate second aggregate CAS;
- explicit reconciliation completes once when sources remain eligible;
- replaying reconciliation is idempotent and does not call the assembler or artifact
  store.

Also fail the first critical workspace save for each assembly kind. Assert that the
handler performs no aggregate completion CAS and returns recovery-required; missing
durable proof must fail closed during reconciliation and must never cause another
assembly automatically.

Add one tampered-plan case per assembly kind. Changing selected-take order/gaps or
component snapshot digest/gap must make `frozen_plan_matches` false and prevent
completion.

### Focused check

```powershell
.\.venv\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_application_recovery tests.heritage_archive.narrator_voice.test_application_episode -v
```

## Task 5 — Focused checkpoint only

Do not run the 1,168+ repository suite here. Run one combined affected check so the
checkpoint has evidence without repeating every test after every edit:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_evidence_schema tests.heritage_archive.narrator_voice.test_narration_job_attempts tests.heritage_archive.narrator_voice.test_narration_job_mastering tests.heritage_archive.narrator_voice.test_diary_episode_assembly tests.heritage_archive.narrator_voice.test_application_generation tests.heritage_archive.narrator_voice.test_application_episode tests.heritage_archive.narrator_voice.test_application_recovery tests.heritage_archive.narrator_voice.test_acceptance_walkthrough -v
.\.venv\Scripts\python.exe -m unittest tests.heritage_archive.test_architecture -v
git diff --check
git status --short
```

Then inspect and stage only the Task 2C source/tests plus this plan and its parent-plan
link. Do not stage private data, audio, secrets or unrelated interrupted work.

```powershell
git diff --cached --name-only
git diff --cached --check
git commit -m "fix: close narrator recovery gaps"
```

This is a local checkpoint only. Do not push, merge or make a live Cartesia request.

## Completion criteria

Task 2C is complete only when all of these are true:

- a never-issued but structurally valid narration snapshot is not current;
- rehydration rejects a selection made after the take’s latest operational rejection;
- every workspace carries and verifies the exact frozen generation/assembly digest;
- decoded recovery media comes through the explicit application port;
- known provider success never becomes ambiguous merely because aggregate CAS fails;
- a settled charge is never downgraded to a hold by the CAS-conflict path;
- two consecutive CAS refusals cannot erase recovery evidence;
- generation, narration assembly and episode assembly each reconcile without replaying
  provider/assembler/artifact work;
- focused tests and the architecture check pass;
- no Plan 3M, Plan 4M or Plan 5M work entered the checkpoint.

## Handoff to Task 3M

Task 3M will implement these already-defined port semantics on the filesystem. It
must not reinterpret Task 2C’s evidence ordering or introduce another aggregate. Its
first persistence tests should reuse the Task 2C failure scenarios against the real
workspace store, budget ledger and aggregate repositories.
