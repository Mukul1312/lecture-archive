# ADR-0014 — The clean-room archive rewrite missed its start gate and is deferred; archive code grows from real demand instead

**Date:** 2026-09-17 · **Status:** **Accepted 2026-09-17** · **Governs:** `scripts/ggsm_transcription/`, `scripts/youtube_enhance/`, and the future archive-context package
**Supersedes:** [ADR-0004](0004-clean-room-rewrite-with-cutover.md) decisions 1 and 4 and its §5.1 start gate and 35-day box; [ADR-0007](0007-two-policy-isolated-narration-lanes.md) §2 decision 4, only for the package path it names · **Superseded by:** —

---

## 1. Context

[ADR-0004](0004-clean-room-rewrite-with-cutover.md) §5.1 set a start gate: *"The first
commit creating the new package must land by **2026-09-05**. If it has not, the rewrite
is not actually starting and this record is revisited rather than left to drift."*
[ADR-0007](0007-two-policy-isolated-narration-lanes.md) §5 repeats that a missed gate
means ADR-0004 "must be revisited on its own terms". This is that revisit.

**The gate was missed.** On 2026-09-17 there is no archive-context commit on any branch,
under either package name (`git log --all -- src/heritage_archive/contexts/archive
src/lecture_archive tests/heritage_archive/contexts/archive` returns nothing).

**The steward's original call is on record and this record reverses part of it.**
ADR-0004 §4 shows the steward chose clean-room over incremental extraction, overruling
the analysis, "who wants the clean result rather than a sequence of partial states".
ADR-0004 §7 names the choice a superseding record faces: finish on a new time-box, or
return to incremental extraction.

Since then, [ADR-0013](0013-narrator-voice-moves-to-its-own-repository.md) moved Narrator
Voice out of this repository, and its decision 7 assigned this revisit one more job: choose
the archive's import package name, because `heritage_archive` now lives in `narrator-voice`.

**Real demand arrived while this record was being drafted.** On 2026-09-17 the steward
described the next SSGGSM transcription project. These are the steward's statements, not
measurements:

- The SSGGSM lecture archive is being copied to Google Drive with `rclone` (in progress), and
  the tracking spreadsheet's lecture links will point to the Drive copies.
- About **5,000 lectures** will be transcribed by an automated flow: pick up the audio from
  Drive, transcribe it with a **local Whisper model** — there is no budget for a paid API such
  as Sarvam — and publish it to a **website that plays the audio with its transcript**,
  replacing OneNote.
- The standard is **read while listening**: the audio is always present, so timing matters
  most and small word errors are acceptable. There is no per-lecture human listening pass.

## 2. Decision

1. **Withdraw the 2026-09-05 start gate and the 35-day box.** The clean-room rewrite is
   deferred. `scripts/ggsm_transcription/` and `scripts/youtube_enhance/` stay the running
   implementations and receive fixes normally.
2. **When new archive code is written, grow it rather than clean-room it.** Any new archive
   pipeline is built in `src/lecture_archive/contexts/archive/`, taking from the two existing
   flows only what it uses and following [ADR-0005](0005-code-layout-rulebook.md) §5's
   graduation thresholds. This is the incremental extraction ADR-0004 §4 rejected.
   **The first such pipeline is the SSGGSM corpus pipeline** described in §1: Drive → local
   Whisper → published transcript. It is not built by extending `scripts/ggsm_transcription/`.
   It takes from that package the parts a real run proved — the faster-whisper adapter, the
   word-timestamp tolerance and the silence/hallucination inspection — and leaves behind the
   per-lecture human review stages that the read-while-listening standard does not use.
3. **The archive's import package is `lecture_archive`.** ADR-0007 §2 decision 4's
   start-commit paths are restated as `src/lecture_archive/contexts/archive/` and
   `tests/lecture_archive/contexts/archive/`. They matter only if a time-boxed rewrite is
   scheduled again (decision 5).
4. **Unchanged:** [ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) — one `archive`
   context with a lifecycle aggregate per flow, transcription first; ADR-0004 decision 2 —
   layering tests before domain code; ADR-0013 decision 6 — the kernel is copied and pinned
   with shared test vectors, not imported from `narrator-voice`.
5. **The steward can restart a clean-room rewrite at any time** by writing an ADR that
   sets a new start gate. ADR-0004 §5.1's three end-of-box clauses carry over to it
   unchanged: (a) the Zurich lecture re-runs end to end through the new package, (b)
   `store.py` no longer computes a digest, job id or stage transition of its own, (c) the
   old implementation is deleted or reduced to a shim.

## 3. Evidence

All measured on 2026-09-17 in this repository unless stated.

### 3.1 For deferring

| Measurement | Result |
|---|---|
| Commits to either flow since ADR-0004 was accepted (2026-08-29) | **0**. Last changes: `e7f43b2` (transcription) and `a89910d` (enhancement), both 2026-08-27 |
| Real jobs on this machine | **1** transcription job (Zurich, 2026-08-27); **0** live enhancement jobs; **2** archived enhancement jobs (2026-08-23). Runs on other machines or pods are not visible here |
| Both flows' tests, in the rebuilt `.venv` | `tests/ggsm_transcription` 132/132; `tests/youtube_enhance` 274 run, 0 failures, 5 skipped for lack of symlink privilege; `tests.test_legacy_script_paths` 2/2 |
| Where maintainer time went instead | **52** commits to `src/` or `tests/` of Narrator Voice between 2026-08-29 and 2026-09-16 (`narrator-voice` repository) |
| Size of the rewrite | ADR-0004 §5.1's own estimate: ~12–14 working days, doubled to ~25 |
| Reliability of such estimates here | ADR-0004 §3, AMENDMENT A1: the one independently checked estimate was wrong by 5–8× |
| Precedent | `heritage_production` (34,679 lines with tests) is shelved; the corpus ledger was deferred by AMENDMENT A3. Both were built ahead of demand |
| The steward's own reference codebase | ADR-0004 §3.1: `ticket-to-lord` was grown, not clean-roomed — its ADR-0017 is "a post-hoc backfill of pattern that emerged during Phase 3 pilot refactor" |

### 3.2 Against deferring

| Observation | Weight |
|---|---|
| **The maintainability complaint is unchanged.** `scripts/youtube_enhance/cli.py` is still 2,682 lines of transaction script; `scripts/ggsm_transcription/store.py` is still 717 lines mixing the state machine with file I/O. | Real, and this record does not fix it. It is paid only when someone changes those files, and §3.1 shows nobody has since 2026-08-27. The second trigger in §6 fires if that changes. |
| **It reverses the steward's explicit choice.** | The deciding reason for clean-room was preference for a clean result over partial states, not a measurement. Decision 5 keeps that option open without a deadline that has already been missed once. |
| **Deferral can drift into never.** | ADR-0004 §5.1 exists to stop exactly that. §6 replaces the date with triggers someone else can check. If none fires, the flows keep working and the deferral cost nothing. |

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| **Restart clean-room with a new start gate** (e.g. first commit by 2026-10-01, 35-day box) | Honours the steward's original choice, but commits ~25 working days — on an estimate this repository has missed by 5–8× before — to two flows with no pending change and green tests, while the same single maintainer carries narration validation. Kept available as decision 5. |
| **Leave ADR-0004 unchanged and let the gate lapse** | Forbidden by ADR-0004 §5.1 itself: "revisited rather than left to drift". |
| **Scheduled incremental extraction with its own time-box** | Still spends dedicated weeks with no demand pulling the design, which is how the corpus ledger and `heritage_production` got built ahead of use. Decision 2 extracts only when real work needs it. |
| **Abandon the archive domain model** | Nothing shows ADR-0002's model is wrong; it has simply not been needed yet. Decision 4 keeps it. |
| **Build the SSGGSM corpus pipeline by extending `scripts/ggsm_transcription/`** | That package is the code ADR-0004 §1 criticised — `store.py` mixes the state machine with file I/O — and its stages are built around a per-lecture human listening gate the new standard drops. Extending it grows the structure this record defers fixing. |
| **Build the SSGGSM corpus pipeline in its own repository** | It uses the same engine, speaker and proven fixes as `scripts/ggsm_transcription/`, so the [ADR-0013](0013-narrator-voice-moves-to-its-own-repository.md) test for a split — no shared code — fails. The website that will display the transcripts is a different case: different language, toolchain and deployment, sharing only the transcript format. This record does not decide where the website lives. |
| **Keep `heritage_archive` as the archive package name** | ADR-0013 decision 7: that name now belongs to `narrator-voice`, and two installed packages with one import name overwrite each other. |

## 5. Consequences

- **ADR-0004 gets a `Superseded by:` line** for decisions 1 and 4 and §5.1 when this record
  is accepted. Its decisions 2 and 3 stand.
- **ADR-0007 §2 decision 4 is superseded only for its path**; its rule that narration work
  neither starts nor extends the archive clock is moot, because there is no clock.
- **ADR-0013 decision 7's open choice is closed**: the archive package is `lecture_archive`.
- **`cli.py` and `store.py` stay as they are** until a trigger fires or the steward
  schedules a rewrite. That is the cost of this decision, stated in §3.2.
- **The SSGGSM corpus pipeline carries the structural work.** Its first slice creates
  `src/lecture_archive/`, the layering tests (ADR-0004 decision 2) and, only if it needs
  canonical identities, the copied kernel with shared test vectors (ADR-0013 decision 6).
  Size its first slice accordingly.
- **It is a long-running batch job, so pause and resume are requirements, not extras.** How
  fast local ASR runs is **not measured**. The job store records no ASR run time; the Zurich
  job's stage history only bounds it: `source_ready` to `asr_ready` took 2 h 18 min for
  89.2 minutes of audio (faster-whisper `small`, int8, CPU), a span that also includes setting
  the prompt by hand. Session notes from that day say about 30 minutes, which the record can
  neither confirm nor refute. The corpus's total audio length is not measured either. The
  first slice should measure both before any completion date is stated.
- **Trigger 1 in §6 fires on the pipeline's first code commit**, and that commit must land in
  `src/lecture_archive/contexts/archive/`.

## 6. Revisit trigger

Any one of these reopens the question. Write an ADR that chooses between extracting the
affected flow into `lecture_archive` now and scheduling a time-boxed rewrite under
decision 5.

1. **New pipeline:** the first commit that adds code for an archive pipeline not already
   under `scripts/`. Decision 2 applies from that commit; check that it did.
2. **Maintenance pressure:** three commits that change the behaviour of
   `scripts/youtube_enhance/cli.py` or `scripts/ggsm_transcription/store.py` within any
   60-day window. Formatting-only and comment-only commits do not count.
3. **Duplicated-mechanics defect:** a second defect whose root cause is the two flows
   implementing job identity, artifact hashing or locking differently. The first was the
   digest-case split fixed in `a89910d`.

## 7. What this record does not decide

It does not decide the SSGGSM corpus pipeline's design — its stages, transcript format,
handling of non-English and chanted spans, diarization, resume behaviour or spreadsheet
updates — which belong to its own design document; where the transcript website lives; the
Odia transcript and translation pipeline's design, engine or whether it will be built in
this repository; the research-script archive
([ADR-0003](0003-archive-research-scripts.md)); anything in `narrator-voice`; or the
persistence technology. It does not require extracting code during an urgent fix.
