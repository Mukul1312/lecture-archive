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
- **A transcript carries writing that was never spoken, and it must be removed before the text is
  scored or aligned.** Speaker labels (`Gour Govinda Swami:`) and bracketed editorial text
  (`[verse]`, `[?]`, `[Śrīmad Bhāgavatam 5.5.8]`) are notes to a reader. Scoring charges them to
  the machine as errors it never made; forced alignment cannot decline a word, so it finds them
  anyway in audio belonging to their neighbours, which are then placed wrongly too. Use
  `scripts.forced_align.spoken_words`, which reuses the scorer's rules so both agree on what
  counts as speech.
- **Timings must be checked, never assumed.** A word placed before the word before it, or past the
  end of the recording, produces a read-along page that highlights the wrong line and reports
  nothing. `scripts.forced_align.problems` checks these invariants on the finished result, which
  is where they belong: one-pass, cue-by-cue and segment-by-segment alignment each have their own
  way of going wrong and the same way of looking fine. And agreement with other systems is not
  accuracy — say which one a figure is.
- **Do not infer what audio or data contains from a cheap proxy. Measure it, or say it is
  unknown.** Five inferences of this kind failed here in one week, every one of them plausible
  when made:
    1. "Pure Sanskrit" filtered by **diacritic density** — fed fourteen Bengali songs to a
       Sanskrit-only model and reported a loss that was really a win.
    2. A second `log_softmax` called a **harmless no-op** by reasoning about normalisation
       instead of printing the sum — it was 2.0, not 1.0, and every confidence was halved.
    3. Bengali onset error of 0.32 s — the matcher had paired `ei` with **another occurrence
       twenty-five seconds away**; the real figure was 0.05 s.
    4. An 86% "verified complete" baseline — computed **inside** Melbourne's reference span
       while the thing it controlled was computed over whole files. On the same basis it is 64%.
    5. Melbourne's skipped head "almost certainly **kirtan**", inferred from loudness — it is a
       spoken archival announcement.
  The common shape is a number standing in for a property nobody checked. Before a proxy
  becomes a claim: listen to the audio, print the intermediate value, or check that two figures
  were computed the same way. A surprising result on this corpus is more often a defect in the
  instrument than a discovery about the archive.
- **Voice-activity detection does not separate chanting from teaching here**, so audio-type
  labelling is not currently derivable: 27 s of speech in 90 for kirtan against 24 s for
  teaching, and Whisper reads Sanskrit prayers as Malayalam. Mark **where a transcript can be
  trusted** — one boolean per span, which the aligner already computes — rather than classifying
  what the audio is.
- Detailed research reports live in the MkDocs site at `research/` (`research/docs/<topic>/`),
  each topic opening with an answer-first `index.md`. Add new research there, not to `docs/`,
  and list it in the `nav` in `research/mkdocs.yml`. `docs/` keeps project state: handoffs,
  decision records, the AWS evaluation and implementation plans.
- The narration decision records, designs and plans under `docs/` remain here as
  history. The copies in `narrator-voice` are the maintained ones.
