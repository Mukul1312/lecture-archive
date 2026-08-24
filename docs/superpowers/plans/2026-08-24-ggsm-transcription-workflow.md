# GGSM English Lecture Transcription Workflow Implementation Plan

## Global Constraints

- The design at `docs/superpowers/specs/2026-08-24-ggsm-transcription-design.md`
  is the binding authority.
- Create an independent `scripts/ggsm_transcription` package. Do not refactor,
  migrate, import, or alter `scripts/youtube_enhance` for similarity alone.
- Apply test-driven development: each production behavior starts with a focused
  failing `unittest`, followed by minimal implementation and a passing test run.
- Use only local processing. Never add a hidden RunPod fallback or non-English
  transcription feature.
- Make all job mutations atomic and locked. No command may silently relax a stage,
  artifact, source hash, review, or delivery invariant.
- Keep generated jobs and `.venv-transcribe` ignored. Track source code, skills,
  tests, requirements, documentation, and the Claude bridge.
- Commit each independently reviewed implementation group.

## Task 1: Document the approved contract and establish the package boundary

Create the approved design specification and this implementation plan. Add the empty
independent package/test namespaces and update `.gitignore` so future job artifacts
are ignored without ignoring the tracked Claude bridge. Add the direct pinned runtime
requirements file, but do not make normal unit tests import `faster-whisper`.

Review points:

- The scope says Listening draft, not publication or OneNote synchronization.
- The ignore rules permit only the intended `.claude/skills/transcribing-ggsm-lecture/SKILL.md` bridge to be tracked.
- No existing enhancement workflow files are changed.

## Task 2: Implement the hash-bound job aggregate and local source intake

Write tests first for safe job IDs/relative paths, stage transitions, atomic JSON
updates, exclusive locks, registered artifact hashing, source hash validation, and
resuming an existing matching job. Implement the job repository/value objects and the
source/download/ffprobe adapters required by `intake` and `status`.

The runner must create the specified job layout, record requested/resolved URLs,
SHA-256, byte size, duration, codec, and tool versions. It must reject unsafe paths,
invalid artifacts, duplicate/mismatched resume candidates, and URLs outside HTTP(S).

## Task 3: Implement local ASR, reruns, and inspection

Write fake-adapter tests for the exact ASR configuration and metadata. Implement lazy
local snapshot resolution, no-download behavior, full JSONL output, supplemental
span reruns, and inspection reports. The inspection test suite must prove that a gap
is represented as an ASR-uncovered interval and never labeled as silence.

Only `small`, CPU `int8`, English, beam size 5, word timestamps, VAD off, and
`condition_on_previous_text=False` are the default full-run settings. Record actual
model snapshot/configuration and tool versions in the job.

## Task 4: Implement whole-timeline review, reference registration, and delivery

Write tests first for ~30-minute ASR-boundary chunking, full timeline coverage,
ordered review records, refusal of unreviewed/missing/out-of-order chunks, Unicode
NFC, deterministic assembly, and verification failures after source/delivery edits.

Implement review manifest/chunks, optional local reference capture provenance,
record-review, assembly, verification, and handoff. Preserve audio-over-reference
authority and English-only omission rules. Verify final Markdown contains Listening
draft status, readable source information, timestamps at least every five minutes,
and only the exact uncertainty/silence/omission marker forms.

## Task 5: Expose and test the complete CLI contract

Write command-level tests for the specified eleven commands and the legal stage
transitions between them. Add `python -m scripts.ggsm_transcription` entrypoint and
clear failures/next-action output. Use fakes and temporary directories; do not
download a recording or execute a real model in automated tests.

Run focused and full repository unit tests. Create the dedicated `.venv-transcribe`,
install the pinned package only if necessary for a smoke import, and generate the
corresponding lock file from that environment. Preserve normal test independence from
the ASR virtual environment.

## Task 6: Create and validate the canonical cross-agent skill

Before writing the skill, use fresh baseline scenarios for (1) a partial matching job,
(2) a reference conflicting with an ASR gap, and (3) a request for raw ASR with the
whole review skipped. Create the canonical explicit-only Codex skill with detailed
workflow/editorial references and a minimal non-symlink Claude bridge.

Validate the skill structure with the supplied validator and execute fresh-context
post-skill scenarios in both Codex and Claude conventions. Acceptance requires
hash-bound resumption, audio authority, full review, English-only handling, exact
uncertainty markers, and Listening-draft labeling.

## Task 7: Final integration verification and independent review

Run the full suite, skill validator, bridge contract test, CLI help smoke test, and a
synthetic complete job through handoff with fake source/ASR adapters. Independently
review the branch against the design and this plan. Fix verified findings, re-run the
affected tests and final suite, then report the evidence and any explicit rulings.
