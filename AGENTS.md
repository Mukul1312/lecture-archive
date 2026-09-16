# Project Working Rules

## Implementation and verification cadence

- Use risk-based TDD in small, visible vertical slices. Write the minimum failing
  tests that prove the behavior or reproduce the defect, implement the slice,
  and run its focused regression tests before expanding the test matrix.
- This strategy refines how new tests are selected and when suites run; it does
  not replace existing coverage. Preserve every existing test. Do not delete,
  disable, skip or weaken tests to deliver faster.
- Give the strongest test-first treatment to irreversible or expensive behavior:
  Cartesia/provider calls, billing and budgets, concurrency and recovery,
  authorization, aggregate invariants and rehydration, storage and immutable-
  evidence integrity, audio corruption, and timing truthfulness.
- For low-risk UI, presentation, DTO, wiring, projection and mechanical-validation
  changes, add only the smallest coherent regression coverage needed; do not create
  exhaustive new test matrices.
- Do not let analysis or test planning replace implementation. Produce a small
  reviewable code diff early, then harden it iteratively.
- During development, run only the smallest affected test modules after each
  vertical slice. Run broad repository suites only at major integration or release
  checkpoints.
- After each visible workflow change, provide simple manual testing instructions.
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
- Preserve existing integrity and hashing behavior. Exercise current safeguards
  first; do not add speculative hashing, evidence machinery, abstractions or extra
  hardening unless an essential safety check fails or an actual defect is observed.
- The current production requirement is Lane-B diary narration only. Preserve the
  existing Lane-C introduction implementation and every related test as dormant,
  tested capability; do not register, generate, select or assemble introduction
  audio during controlled validation unless the operator explicitly restores that
  requirement.
- Never make a live Cartesia request without explicit operator approval. On
  2026-09-10 the operator authorized bounded, defect-driven validation of at most ten
  live calls, each no longer than one minute. Before each call, retain current
  authorization, configured cost caps, healthy storage, one request at a time, no
  automatic replay, and checked immutable audio. Do not treat this as standing
  authorization beyond that validation.

## Current execution handoff

- Tasks 3M and 4M are complete and smoke-verified, not hardened. Task 4M was
  merged locally into `main` through checkpoint `3f6b00b` without a live request.
- Task 5M is implemented and smoke-verified, not hardened. Its fixture-only
  intro-plus-two-diary journey survives a closed/rebuilt studio, including checked
  audio, selections, masters, listening and process-token invalidation. Read
  `docs/superpowers/plans/2026-09-07-ssggsm-odia-narration-minimum-local-studio-v1-task-5m-loopback-studio.md`
  for evidence. The repaired Windows runner now passes `socket.socketpair()`,
  `asyncio.run()` and the complete 195-test fixture-only Task 5M checkpoint.
  Whole-branch review found one malformed-generation-result boundary gap; local fix
  `0a00936` passed scoped rereview and final fixture checkpoints.
- Automated tests remain fixture-only: do not read a private production root or API
  key, bind a test server socket, or make a live, paid or private Cartesia request
  from a test.
- No additional numbered build task is scheduled after 5M. Remaining work is bounded
  Lane-B diary validation and defect-driven hardening; do not invent Task 6M or
  broaden the local, single-operator, single-episode scope.
