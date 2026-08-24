# Persistent Lecture Audio Enhancement Skill Design

Date: 2026-08-22
Status: Approved by the user on 2026-08-22

## Context

The repository now contains a tested lecture-audio enhancement pipeline and one
completed full-length D30 review delivery. Producing that delivery exposed a second
problem: the operating procedure and job progress lived partly in chat context. A new
session could not safely tell which source, model, cache, artifacts, approvals, and
recovery decisions were authoritative without reconstructing hours of history.

The project needs a durable, explicitly invoked workflow for two upcoming audio jobs
and later lecture recordings. It must survive a new session or context compaction,
resume completed work safely, preserve human decisions, and avoid turning routine
production runs into open-ended engineering sessions.

## Goals

1. Add an explicit project-local skill named `$enhancing-lecture-audio`.
2. Make a fresh agent able to start or resume a job using repository state rather
   than chat history.
3. Generalize the existing source-specific D30 runner for arbitrary lecture filenames,
   hashes, and durations while reusing the tested DSP, cache, render, loudness, and QA
   components.
4. Use per-audio blind auditions before every full render.
5. Preserve the complete decoded timeline and prioritize voice naturalness and word
   integrity over maximum noise removal.
6. Keep a similar 45-60 minute lecture to approximately 45-70 minutes of machine time,
   excluding human listening and source-download time.
7. Fail early, preserve valid work, and record an exact next action whenever a job
   cannot continue.

## Non-goals

- No video processing or delivery.
- No voice cloning, speech replacement, generative reconstruction, transcript, or
  content editing.
- No automatic source choice between technically different source files.
- No automatic candidate selection or final human acceptance.
- No parallel full rendering of the two upcoming jobs.
- No automatic cache deletion.
- No general-purpose media-management platform or workflow-engine rewrite.
- No migration or modification of completed legacy lectures or their artifacts.
- No new download subsystem. The skill may invoke the existing `yt-dlp` installation
  during intake when the user supplies a URL.

## Chosen approach

Use a project-local skill, a deterministic repository runner, and one persistent state
record per audio job:

```text
$enhancing-lecture-audio
        -> find or create job.json
        -> validate recorded state and artifacts
        -> resume the first incomplete stage
        -> stop only at a human gate or a recorded blocker
```

An instructions-only skill would leave mechanical execution too dependent on agent
interpretation. A full orchestration-platform rewrite would add unnecessary scope. The
chosen middle approach keeps judgment in the skill and enforces mechanical invariants
in tested Python code.

## Repository structure

```text
.agents/skills/enhancing-lecture-audio/
  SKILL.md
  agents/openai.yaml
  references/workflow.md
  references/job-state.md

scripts/youtube_enhance/
  workflow.py

tests/youtube_enhance/
  test_workflow.py

data/enhance/jobs/<job-id>/
  job.json
  source/
  analysis/
  auditions/
  cache/
  work/
  delivery/
```

`SKILL.md` will remain concise and route to the two references only when executing the
workflow or interpreting state. `agents/openai.yaml` will set
`allow_implicit_invocation: false`, so ordinary audio requests do not activate the
skill. Activation requires the exact `$enhancing-lecture-audio` invocation token; a
plain audio-enhancement request must not activate it. Validation will parse
`agents/openai.yaml`, assert the policy is false, and forward-test both an ordinary
audio request and an explicit invocation with fresh agents.

Production jobs use the canonical primary checkout, never the current feature-worktree
root. The runner derives that checkout from the absolute Git common directory: its
parent must contain the real `.git` directory and the installed project skill. It then
uses exactly `<canonical-root>/data/enhance/jobs`. If canonical-root discovery is
ambiguous or the stored repository identity does not match, the runner stops before
reading or writing a job. Job paths are stored relative to this root whenever they are
inside it; external source paths are stored as normalized physical absolute paths.
Generated audio and cache files remain ignored, while state and evidence records remain
locally durable across sessions.

## Responsibilities

### Skill

The skill will:

- discover active jobs and summarize their verified status;
- ask for a job ID only when more than one active job is eligible;
- invoke the deterministic runner for the appropriate stage;
- stop at the source, audition, and final-listening human gates;
- never infer approval from chat history;
- report the current stage, progress, elapsed time, artifacts, blocker, and exact next
  action;
- refuse scope expansion or workflow-code modification during a production run.

### Runner

The runner will expose stable `init`, `status`, `preflight`, `audition`, `select`,
`render`, `qa`, `accept`, and `cleanup` commands. It will reuse the existing `source`,
`dfn`, `render`,
`loudness`, `qa`, and manifest/hash utilities instead of duplicating DSP logic.

Mechanical requirements belong in the runner: schema validation, atomic state writes,
hash verification, path safety, storage checks, state transitions, cache validation,
sample counts, output formats, and transactional publication.

## Persistent job contract

`job.json` is the sole resume authority. It records at least:

- schema version, job ID, creation/update timestamps, canonical repository identity,
  canonical root, and stable workspace-relative path;
- every source candidate's path, SHA-256, decoded program hash, codec/container,
  channels, sample rate, decoded frame count, and comparison evidence; URL sources also
  record the original URL, extractor ID, selected native format ID, yt-dlp version and
  arguments, download timestamp, and downloaded-file hash;
- the selected source and any explicit human source decision;
- absolute tool paths plus FFmpeg, FFprobe, DeepFilterNet, Python, NumPy, SoundFile,
  model-config, and checkpoint versions or hashes;
- audition window coordinates, private candidate identities, blind public labels,
  candidate artifact hashes, and gate results;
- the explicit human-selected blind candidate and the evidence hashes it approved;
- chunk, halo, blend, attenuation, model, and cache-key policy;
- per-stage status, timestamps, elapsed time, progress counters, run token, heartbeat,
  and last successful checkpoint;
- output paths, hashes, decoded metadata, loudness, true peak, integrity, and boundary
  measurements;
- technical-QA status and human-listening status as separate fields;
- the last error and an exact next action when blocked or interrupted.

State updates use atomic replacement. Each mutating command holds a non-blocking,
OS-enforced exclusive lock on the job lock file for its complete lifetime and records a
UUID run token plus heartbeat for observability. A second session that cannot acquire
the lock refuses to run. If a new session can acquire it, no previous runner still
holds the lock; it may then mark a stale `running` record `interrupted` after validating
the recorded artifacts. Safety never depends on PID identity or heartbeat age alone.

Completed artifacts are trusted only after their
current paths, hashes, metadata, and binding inputs validate. A fresh session does not
trust a `completed` label by itself.

## State machine and human gates

```text
created
  -> source-ready
  -> preflight-passed
  -> audition-ready
  -> selection-recorded
  -> rendered
  -> technical-qa-passed
  -> human-accepted
```

Every stage may also be `blocked` or `interrupted`. A fresh invocation converts an
abandoned `running` stage to `interrupted` only after validating the process is no
longer active. It then revalidates existing artifacts and resumes from the first
incomplete operation.

The workflow has two mandatory human gates and one conditional human gate:

1. **Source choice (conditional):** required whenever multiple sources have different
   decoded program hashes. A single source records `selection_kind: automatic_single`.
   Multiple sources may bypass the human gate only when their decoded program hashes
   are identical; the runner then chooses deterministically by uppercase source SHA-256
   and normalized path order and records `selection_kind: automatic_pcm_equivalent`.
   Both automatic cases advance to `source-ready` with comparison evidence and are not
   represented as human approval. Quality measurements may recommend a differing
   source, but only the user may select it.
2. **Blind audition:** always required before a full render. The decision is bound to
   the exact audition artifacts and blind map.
3. **Final listening:** always required before acceptance. Technical QA cannot certify
   voice naturalness or word integrity.

No command may silently advance through an applicable human gate. Acceptance requires
the two mandatory approvals and the conditional source approval only when that gate was
opened.

## Processing stages

### Intake and comparison

Accept one or more local files. When given a URL, acquire the native audio stream
without transcoding and preserve download metadata. Hash, probe, and fully decode each
source. Compare program content, decoded duration, channels, bitrate/codec, usable
bandwidth, clipping, dropouts, and noise evidence. With multiple differing decoded
program hashes, persist the comparison and recommendation and stop for human selection;
there is no quality-score threshold that can silently bypass this gate.

Decode the selected source once with the version-bound FFmpeg command to 48 kHz stereo
float PCM, with no asynchronous resampling, silence insertion, or duration trimming.
For non-48-kHz sources this deterministic decode includes the required resampling. The
resulting working PCM's observed frame count—not container duration multiplied by
48,000—is the authoritative timeline for processing and lossless delivery. Record the
original stream time base, original rate, decoder command, resampling decision, and
working frame count.

### Preflight

Before large writes:

- bind physical absolute FFmpeg, FFprobe, DeepFilterNet, and model paths;
- verify tool versions and model config/checkpoint hashes;
- use the short stable production workspace;
- reject reparse-dependent paths and probe the deepest future temporary/cache path;
- require free space of at least
  `max(10 GiB, ceil(25 GiB * working_frames / 131,864,451))`, calculated on the
  physical volume that will hold the job; this scales the measured conservative
  requirement from the completed 45:47 lecture;
- run a short decode and model smoke test;
- persist `preflight.json` and stop without rendering on failure.

### Blind auditions

Automatically select three to five representative excerpts spanning clean and noisy
speech, quiet consonants, a pause onset, event/crowd/music material, and beginning,
middle, and ending coverage. Selection is deterministic for the same source PCM,
diagnostic-version fingerprint, and configuration: record every scored window, feature
values, chosen source coordinates, coverage role, and selection-rule version. Record a
coverage role as unavailable when the source contains no qualifying material rather
than relabeling another excerpt.

Render loudness-matched, blind Original, D24, and D30 candidates independently from the
same original PCM. D24 and D30 mean one DeepFilterNet3 pass over the original mid
channel with `--atten-lim 24` or `--atten-lim 30`, respectively, using the job-bound
model config/checkpoint; both restore the untouched original side. Never feed enhanced
output into another enhancement pass. Automated integrity and identity/timbre checks
may reject a candidate but never choose the winner.

### Full render and delivery

Apply the approved setting once to the original mid channel, restore the untouched
side, and preserve exact source coordinates. Use contextual chunks, same-timeline
blending, latency compensation, content-addressed caches, and validated resumption.
Normalize the completed stereo master to -16 LUFS with a +/-0.5 LU tolerance and a
true-peak ceiling of -1.5 dBTP. Publish a 48 kHz 24-bit stereo FLAC and 48 kHz 192 kbps
stereo MP3 from the same corrected master. MP3 encoding uses libmp3lame constant
192 kbps (`-b:a 192k`, with no VBR quality option), and its effective stream bitrate
must be within 3 kbps of 192 kbps.

### Technical and listening QA

Technical QA decodes both deliverables end to end and verifies exact timeline, rate,
channels, FLAC bit depth, MP3 bitrate, loudness, true peak, non-finite samples,
dropouts longer than 50 ms, clipping/pinned/flat-top regressions, every chunk boundary,
hashes, and provenance. It transactionally publishes `qa-report.json`,
`completion.json`, and `listening-checklist.md`.

The current tested `qa.validate_delivery` contract supplies the measurable thresholds:
source/adaptive/master/FLAC frame counts are identical; decoded MP3 may contain only
0-1,152 verified encoder-delay/padding frames beyond the authoritative program and may
never be shorter; both outputs are 48 kHz stereo; loudness is -16.5 through -15.5 LUFS;
true peak is at most -1.5 dBTP; non-finite count is zero; a new exact-zero run is at
most 2,400 frames; flat-top, pinned, per-block flat-top, and boundary-flat-top counts do
not exceed the original reference; and a measured boundary fails when its absolute
jump exceeds 0.05 while also exceeding the local median by more than 20 dB. Persist the
QA contract version and repository commit with every report.

The final checklist covers all audition anchors, quiet consonants, low-energy words,
overlaps, transitions, crowd/music/chanting, beginning, ending, naturalness, and word
integrity. Only explicit human approval changes the job to `human-accepted`.

## Time and progress contract

For a 45-60 minute lecture on the current Windows machine with DeepFilterNet 0.5.6,
the bound local DeepFilterNet3 model, FFmpeg 8.1.1 full build, and no reusable chunks,
excluding download and human listening, target:

- intake and preflight: 3-8 minutes;
- audition generation: 5-15 minutes;
- full render, normalization, export, and QA: 35-50 minutes;
- total machine time: approximately 45-70 minutes.

These are operational targets, not acceptance gates; runtime scales with duration,
source complexity, and hardware. Record a warning when elapsed machine time exceeds
1.5 times the duration-scaled upper target. Each stage records elapsed time and
progress. A stage with no measurable child-process activity, CPU work, heartbeat,
cache publication, or artifact growth for 10 minutes stops and records a blocker rather
than continuing silently. Status updates distinguish active compute from human waiting.

The two upcoming jobs run sequentially. Normal production runs execute per-job
preflight and QA, not the entire engineering test suite. The full suite runs only when
workflow code changes.

## Failure and recovery rules

- Never overwrite a source, approved audition, accepted delivery, or previous run.
- Never change the selected source, model, attenuation, or tool provenance during a
  retry.
- Preserve validated completed chunks and reconstruct disposable compositor files on
  retry.
- Stage delivery and evidence privately and publish complete sets transactionally.
- Detect partial publication and recover or roll it back without a bespoke script.
- Record failures with stage, command, timestamp, validated artifacts, and exact next
  action.
- Do not redesign, refactor, install alternative processing systems, or expand scope
  inside a routine production run. A code defect blocks the job and becomes a separate
  approved development task.
- Cleanup is a separate action available only after human acceptance. `cleanup` first
  runs as a write-nothing dry run that lists exact validated transient paths, sizes, and
  the current job-state hash. Deletion requires a second command with a confirmation
  token bound to that listing and state hash while holding the exclusive job lock. It
  may remove only those listed transients; it keeps the source, FLAC, MP3, reports,
  decisions, and provenance.

## Testing strategy

### Runner TDD

Write failing tests before implementation for:

- arbitrary filenames, hashes, durations, and exact decoded frame counts;
- legal and illegal state transitions;
- atomic state updates and interrupted-session recovery;
- stale source, cache, tool, and model rejection;
- differing-source comparison, deterministic PCM-equivalent selection, and every
  applicable human gate;
- disk-space, reparse, and Windows path-length preflight;
- canonical-primary-root discovery and rejection of feature-worktree job roots;
- exclusive-lock contention, stale `running` recovery, and concurrent-session refusal;
- cache reuse without stacked enhancement;
- deterministic 48 kHz resampling and authoritative working-frame semantics;
- exact timeline, side restoration, formats, loudness, peak, and QA publication;
- partial-publication recovery and authorized cleanup boundaries.

Run a small end-to-end synthetic stereo fixture through the state machine with an
injected deterministic identity enhancer. Existing DSP unit tests remain the authority
for DeepFilterNet, chunk rendering, loudness, and QA internals.

### Skill TDD

Before writing the skill, run fresh-agent baseline scenarios without it and record the
observed failures. Scenarios include an interrupted job after context loss, pressure to
skip a human gate, and a stale cache/tool mismatch. Then write the minimum skill that
corrects those failures, rerun the scenarios with the skill loaded, and close any
observed loopholes. Validate the final skill structure and explicit-only invocation
metadata with the skill validator. A separate activation scenario must show that a
plain audio-enhancement request does not load the installed skill, while the exact
`$enhancing-lecture-audio` token does.

## Deliverables and acceptance

Implementation is complete when:

- `$enhancing-lecture-audio` is discoverable only through explicit invocation in this
  repository;
- a fresh session can initialize, inspect, and resume a job using only repository state;
- a forced interruption resumes without repeating validated completed chunks;
- both mandatory human gates and every opened conditional source gate are enforced and
  hash-bound;
- a synthetic end-to-end job produces the required delivery/evidence set;
- focused and full enhancement tests pass;
- independent fresh-agent tests demonstrate correct behavior with the skill loaded;
- the runner rejects protected legacy workspaces outside the canonical jobs root and
  cannot address their cache or delivery paths;
- before and after implementation/tests, locally recorded hashes for any protected
  legacy source, manifest, delivery, and QA artifacts remain unchanged;
- a before/after path-size-mtime inventory of the protected legacy cache tree shows no
  additions, removals, or writes.

After this specification is approved, the next step is a detailed implementation plan.
No production skill or runner code is authorized by specification approval alone.
