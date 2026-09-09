# Project Working Rules

## Implementation and verification cadence

- Use risk-based TDD in small, visible vertical slices. Write the minimum failing
  tests that prove the behavior or reproduce the defect, implement the slice,
  and run its focused regression tests before expanding the test matrix.
- Give the strongest test-first treatment to irreversible or expensive behavior:
  provider calls, billing and budgets, concurrency and recovery, authorization,
  aggregate invariants and rehydration, immutable evidence, audio integrity, and
  timing truthfulness.
- For low-risk wiring, DTOs, projections, and mechanical validation, cover a
  coherent slice instead of creating an exhaustive test case for every field or
  implementation detail upfront.
- Do not let analysis or test planning replace implementation. Produce a small
  reviewable code diff early, then harden it iteratively.
- Run focused tests after each vertical slice. Run broader repository suites at
  meaningful tranche or plan checkpoints, rather than after every micro-edit.
- Report design work, code written, tests passing, and committed checkpoints as
  separate kinds of progress. Never describe analysis alone as implemented work.

## Narrator Voice v1 scope

- Build the minimum single-operator local narration studio described by ADR-0012.
  Do not turn v1 into a general production, workflow, storage, audit or publishing
  platform.
- Preserve the accepted three aggregate roots, voice/lane isolation, exact take
  evidence, immutable audio, human selection, budget protection and dry assembly.
  Simplicity means fewer adapters and exposed workflows, not weaker truth for paid
  operations.
- Prefer one concrete local implementation over generic frameworks. Do not add CQRS,
  event sourcing, extra aggregates/repositories, multi-provider abstractions,
  multi-user infrastructure or speculative Presentation code.
- Treat the former v3 design and task plans as historical full-scope evidence. ADR-0012,
  the v4 minimum design and its replacement plan govern remaining v1 work.
- Track every slice separately as `implemented`, `smoke-verified` and `hardened`.
  Moving to the next plan requires smoke verification, not exhaustive hardening.
- The deferred hardening gate for storage, recovery, budgets, audio and backup must
  pass before the first real paid/private Cartesia generation. Contingency is recorded
  only when an actual defect occurs.

## Current execution handoff

- Tasks 3M and 4M are complete and smoke-verified, not hardened. Task 4M was
  merged locally into `main` through checkpoint `3f6b00b` without a live request.
- Task 5M is implemented and smoke-verified, not hardened. Its fixture-only
  intro-plus-two-diary journey survives a closed/rebuilt studio, including checked
  audio, selections, masters, listening and process-token invalidation. Read
  `docs/superpowers/plans/2026-09-07-ssggsm-odia-narration-minimum-local-studio-v1-task-5m-loopback-studio.md`
  for evidence and the Windows async-runner limitation. Whole-branch review found
  one malformed-generation-result boundary gap; local fix `0a00936` passed scoped
  rereview and final fixture checkpoints on `feature/narrator-voice-production-v1`.
- Task 5M tests remain fixture-only. Do not read a private production root or API
  key, bind a test server socket, or make a live, paid or private Cartesia request.
- The pre-live storage/budget/recovery/audio/backup and provider-usage gates remain
  open. Task 5M completion does not itself authorize a production call.
- No additional numbered build task is scheduled after 5M. Remaining work is the
  pre-live gate and separately approved controlled production validation; do not
  invent Task 6M or broaden the single-operator/single-episode scope.
