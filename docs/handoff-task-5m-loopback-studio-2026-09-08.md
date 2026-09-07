# HANDOFF — Task 5M local narration studio (paused 2026-09-08)

> **Pause instruction:** Mukul asked to stop before Task 7 implementation because
> the weekly usage limit is nearly exhausted. Resume from this checkpoint; do not
> redo completed Tasks 1–6.

## Read this first on resume

The authoritative implementation plan is
[`docs/superpowers/plans/2026-09-07-ssggsm-odia-narration-minimum-local-studio-v1-task-5m-loopback-studio.md`](superpowers/plans/2026-09-07-ssggsm-odia-narration-minimum-local-studio-v1-task-5m-loopback-studio.md).
The active branch is `feature/narrator-voice-production-v1` in the isolated worktree
`.worktrees/narrator-voice-production-v1`. Its Task 5M baseline is `3f6b00b`.

Task 5M is registered and Tasks 1–6 are complete. Task 7 has been pre-audited and its
plan corrected, but **no Task 7 production or test implementation has begun**. Tasks
7–9 remain. Task 5M has not been merged or pushed.

## Completed, reviewed checkpoints

| Task | Outcome | Commit(s) | Review/evidence status |
|---|---|---|---|
| Registration | Registered the full fixture-only loopback-studio plan | `4346ce1` | Initial plan review approved after corrections |
| 1 | Exact configured narration authority ID is supplied by the trusted adapter | `1454ac9` | Approved; one deferred test-clarity Minor |
| 2 | Repository discovery and redacted editor/status projections | `a3184ff` | Approved; two deferred optional regression Minors |
| 3 | Parent-owned, evidence-checked whole-file audio playback handlers | `9efa3be` | Approved; one deferred optional mutation regression |
| 4 | Complete 33-handler live composition plus actor/readiness seams | `deab7ad` | Independent review: no findings |
| 5 | Secured framework-neutral loopback/ASGI boundary and fixed local server | `9886457`, `178b672` | Two Important transport-fallback findings fixed; re-review clean; 69 focused + 9 adjacent fixture tests reported green |
| 6 | Session-gated one-page authoring, configured authority/bootstrap, packaged CSS/JS | `d481145`, `42ab53a` | Leading-LF and NUL textarea fidelity fixed with RED/GREEN; two independent re-reviews clean; original 110 Python + 14 JS/package checks, then 90 fix-focused/adjacent tests reported green |

Task 6 preserves a leading newline in every textarea, rejects incoming U+0000 before
handler dispatch, and fails old persisted U+0000 text closed through the generic
unavailable page. No private text is rendered to a missing or stale session.

Two additional plan-clarification commits precede Task 6: `aa7113f` fixes the exact
job-vs-passage authoring route mapping; `caaff1f` closes the Task 6 web-boundary,
bootstrap, identifier and typed repository-failure gaps.

## Safety record

All work so far is fixture-only.

- No live Cartesia request was made.
- No listener or real loopback socket was started.
- No real credential was read and no production/private narration root was opened.
- Route tests use direct framework-neutral calls, raw ASGI, or HTTPX
  `ASGITransport`; provider behavior is fake or `MockTransport`-backed.
- No paid generation, push, publish, or Task 5M merge occurred.
- Unrelated untracked AWS documents in the main checkout were not touched.

Continue to enforce these rules through Tasks 7–9. A live/paid smoke is outside Task
5M and needs a separate explicit decision after the fixture checkpoint is complete.

## Local environment and evidence

Use the ignored worktree environment:

```powershell
.venv-task5m\Scripts\python.exe
```

It contains the local web test/runtime dependencies used here (Python 3.11.4,
Starlette 1.6.0, Uvicorn 0.52.4 and HTTPX 0.28.1). Task 6's offline package evidence
was built and byte-compared without publishing. Do not delete the ignored SDD folder
or package evidence before final verification.

Detailed briefs, immutable review diffs, reports and the append-only execution ledger
are under:

```text
.superpowers/sdd/2026-09-07-ssggsm-odia-narration-minimum-local-studio-v1-task-5m-loopback-studio/
```

Start with `progress.md`, `task-6-report.md`, `task-7-brief.md`,
`task-7-domain-context.md`, and `task-7-integration-audit.md`.

## Exact Task 7 resume point

The Task 7 plan was amended and independently approved with no Critical or Important
plan findings. Implement only after re-reading the authoritative section and the two
Task 7 audit notes. The important settled boundaries are:

1. Web composition creates one process-lifetime `ProcessGenerationControl` from the
   exact `ProcessSecurity` session token. A restart gets a fresh empty confirmation
   store and gate.
2. Confirmations are private immutable records with 256-bit opaque tokens, 600-second
   monotonic TTL and a 128-live cap. They bind the session, job, preview,
   `GenerationEstimateResult.revision`, preview digest and exact estimate. Capacity
   failure happens after the estimate is durably persisted and never evicts a live
   token.
3. Generation validates the request and derives
   `studio/takes/<job UUID>/<command UUID>.wav`, acquires the nonblocking gate, then
   atomically consumes the token. Busy refusal does not inspect or consume it. A
   consumed stale token is never restored.
4. The route invokes the synchronous handler once and directly. The platform already
   places the entire app in an AnyIO worker thread; do not add an executor or bounded-
   context framework import. Preserve only the transport's already accepted bounded
   retry for a proved pre-send failure—there is no web retry or automatic replay.
5. Successful estimate is the sole no-reload mutation. JavaScript must use
   `textContent` and place the token only into an ephemeral sibling generation form;
   no URL, log, bundle, local/session storage or cookie.
6. Generation and explicit generation reconciliation share the same gate. Recovery
   is offered for `unknown` and inactive `reserved`, `input_frozen`,
   `external_work_started`, `artifacts_staged`, and `artifacts_published` attempts.
   Missing owned attempts are 404; present ineligible attempts are 409
   `reconciliation_unavailable`. GET never mutates.
7. Present `completed`, `blocked`, `failed`, `unknown`, and `quarantined` exactly.
   Keep all provider, authority-record, dictionary/voice, workspace, evidence and path
   fields out of responses.
8. Add the shared `FilesystemOperationalFailure` boundary. Repository failures remain
   a compatible subtype. Retype stored-ledger parse/replay/configuration and atomic-
   replacement faults, workspace topology/read/decode/stored-binding/storage faults,
   and artifact-publication faults only after public argument validation. Preserve
   `BudgetDenied`, `WriterLockUnavailable`, and candidate-progression validation.
   Only trusted generate/reconcile handler `ValidationError` that escapes after full
   request conversion maps to generic 500; authoring and estimate validation stays
   422. Never inspect exception text.

The interrupted focused failure-seam audit left one useful implementation warning:
do **not** retype `_validate_workspace_progression(existing, candidate)` as a
filesystem failure. It describes port-caller candidate misuse/conflict. Budget
`_load_document`/`_replay` failures are operational, including a cap failure caused
by replayed stored facts; `BudgetDenied` for the newly requested reservation must
remain the normal budget outcome.

Task 7's focused command remains:

```powershell
.venv-task5m\Scripts\python.exe -m unittest tests.heritage_archive.narrator_voice.test_web_generation tests.heritage_archive.narrator_voice.test_application_generation tests.heritage_archive.narrator_voice.test_application_recovery tests.heritage_archive.narrator_voice.test_cartesia_generation_integration -v
```

Use strict RED/GREEN, a separate implementation commit, an immutable diff package,
and an independent review. If review finds a Critical/Important issue, the same Task
7 implementer should fix it in a separate commit before proceeding.

## Tasks 8 and 9 still remaining

Task 8 adds operational review/select, checked take/master playback, narration and
episode dry mastering/listening, snapshot issue-and-attach, and explicit assembly
reconciliation. Before implementation, reconcile its existing domain audit with the
actual Task 7 code. Important known seams already recorded in
`task-8-domain-context.md` are:

- map stored-media corruption to generic 500 while preserving owned-resource 404;
- expose reconciliation for inactive persisted assembly orphans, not only `unknown`;
- add a narrow projection if exact persisted `gap_samples` must be displayed;
- choose and document an explicit safe per-gap/total allocation cap before accepting
  browser-controlled silence samples—the PCM assembler otherwise allocates without a
  bound;
- retain an issued snapshot and truthful source revision/count when the later episode
  attach CAS fails; never serialize the snapshot to the browser; and
- share a small nonblocking assembly/reconciliation gate so active assembly cannot be
  raced or multiplied.

Task 9 is the representative fixture-only intro-plus-diary journey through the
framework-neutral/ASGI boundary, followed by close/rebuild against the same temporary
root. It also owns the final focused checkpoint, Task 4M regression matrix, offline
package/import/asset checks, `serve --help`, exact diff/secret/private-data/media scan,
README/AGENTS updates and evidence-backed plan checkbox/status changes.

After Task 9 and clean final review, decide whether to merge Task 5M locally. Do not
silently proceed to a live Cartesia request: credentialed smoke, real media judgment,
operational backup/restore rehearsal and production hardening remain separate gates.

## Deferred final-review notes from Tasks 1–3

- Task 1: remove or strengthen the now-vacuous identifier-call assertion in
  `test_application_authority.py` if final review treats it as worth changing.
- Task 2: optional direct regressions for a snapshot whose internal revision differs
  from its filename, and newest-per-passage preview selection with interleaved
  previews.
- Task 3: optional isolated playback regression where only
  `all_digital_silence` differs.

These are non-blocking Minors; do not expand them into unrelated refactors.

## Resume checklist

```powershell
cd C:\Users\Mukul\code\personal-projects\voice-cloning\.worktrees\narrator-voice-production-v1
git status --short --branch
git log --oneline 3f6b00b..HEAD
```

Expected state is a clean `feature/narrator-voice-production-v1` worktree. Then read
`AGENTS.md`, this handoff, the full Task 5M plan, `progress.md`, and all three Task 7
brief/audit files. Confirm there is still no live-request authorization, create a
fresh Task 7 implementer, and resume at the first failing Task 7 test—not at an
earlier task.
