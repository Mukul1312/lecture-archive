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

## Repository scope

- Narrator Voice moved to the separate `narrator-voice` repository on 2026-09-16
  under ADR-0013. Its v1 scope, live Cartesia authorization and execution handoff
  rules live in that repository's `AGENTS.md`. Do not add narration code here.
- This repository holds lecture transcription (`scripts/ggsm_transcription/`),
  lecture audio enhancement (`scripts/youtube_enhance/`), the shelved
  `heritage_production` package, the Hindi clone work and the research scripts.
- **Sanskrit and Bengali are different languages and must be measured apart.** The scorer's
  Indic track counts any diacritic-marked word, and Bengali transliteration carries as many as
  Sanskrit, so a combined figure hides which system is best. Use
  `scripts.transcript_accuracy.indic_language`. Getting this wrong once produced a completely
  inverted result.
- Detailed research reports live in the MkDocs site at `research/` (`research/docs/<topic>/`),
  each topic opening with an answer-first `index.md`. Add new research there, not to `docs/`,
  and list it in the `nav` in `research/mkdocs.yml`. `docs/` keeps project state: handoffs,
  decision records, the AWS evaluation and implementation plans.
- The narration decision records, designs and plans under `docs/` remain here as
  history. The copies in `narrator-voice` are the maintained ones.
