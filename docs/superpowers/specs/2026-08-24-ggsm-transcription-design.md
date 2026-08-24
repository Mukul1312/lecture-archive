# GGSM English Lecture Transcription Workflow Design

Date: 2026-08-24
Status: Approved for implementation by the user's explicit implementation request on 2026-08-24

## Context

The repository contains several distinct audio and speech projects. This workflow is
not a continuation of the lecture-audio enhancement pipeline and must not be folded
into it simply because both work with lectures. Its purpose is narrower: when the
user chooses an English SSGGSM archive lecture to hear, create a reliable local
transcription workspace and a OneNote-ready listening draft for that recording.

The result is intentionally not a published transcript, a catalog entry, a OneNote
sync, or a claim of final textual authority. It is a traceable draft that a person can
listen through and improve in OneNote.

## Goals

1. Provide an explicit-only workflow for Codex and Claude:
   `$transcribing-ggsm-lecture <URL>` and `/transcribing-ggsm-lecture <URL>`.
2. Bind every job to the actual downloaded source by SHA-256, rather than URL,
   filename, duration, chat memory, or a previous partial transcript.
3. Run local English ASR with a reproducible, recorded configuration and no required
   network download at execution time.
4. Make inspection and a whole-timeline editorial listening pass mandatory before
   assembly.
5. Preserve the evidence needed to resume safely while keeping OneNote delivery
   clean and human-readable.
6. Keep the new workflow independent from `scripts/youtube_enhance`.

## Non-goals

- No website, public transcript catalog, publishing, or archive-wide scheduler.
- No OneNote API integration, automatic copy, or completion claim about OneNote.
- No RunPod implementation in this first version.
- No non-English transcription or translation. Meaningful non-English speech is
  represented by an exact timestamped omission marker.
- No automatic Taptajivanam scraping. An agent may capture a local reference and
  explicitly register it as secondary evidence.
- No historical-job migration, unrelated enhancement refactor, or storage-health
  work.

## Bounded Context and Architecture

This is a small, local workflow, not a service platform. The **transcription job** is
the aggregate: it owns source identity, stage, registered artifacts, review coverage,
and delivery state. Its immutable value-like facts include source hashes, artifact
digests, time spans, model configuration, and review chunk identifiers.

`scripts/ggsm_transcription` separates pure job-policy code from adapters:

```text
CLI command adapter
        -> job use cases and workflow policy
        -> local job repository / lock / files / source download / ffprobe / ASR
```

The job state and editorial invariants have no dependency on HTTP, FFmpeg, or
`faster-whisper`. Local file, network download, FFprobe, and model loading are outer
adapters. That makes source matching, stages, inspection, review coverage, assembly,
and verification testable with temporary files and fake ASR adapters.

No database, event bus, CQRS split, or generic workflow framework is justified here.

## Job Identity, State, and Storage

Each recording is stored at:

```text
data/transcribe/jobs/<safe-source-slug>-<source-sha256-first8>/
```

`job.json` is the source of truth. Every update is written atomically and guarded by
a per-job OS lock. It records a revision, source URL and resolved URL, source hash,
byte size, duration, stream/codec information, stage history, tool versions, ASR
configuration, and hashes for every registered artifact.

The only forward stages are:

```text
created -> source_ready -> asr_ready -> inspected
        -> reviewed -> draft_ready -> handed_off
```

Each command validates the current stage and all inputs it relies upon. `intake`
first seeks a validated matching source/hash job. It must never silently create a
second job for a source that already has one. An incomplete job is resumable only
after its source artifact and recorded hash still validate.

Job artifacts use these predictable paths:

```text
source/
asr/full.jsonl, metadata.json, reruns/
inspection/report.json, report.md
review/manifest.json, chunk-*.md
reference/taptajivanam.md, provenance.json
delivery/onenote-transcript.md, verification.json, handoff.json
```

Generated job directories and incoming download staging are ignored by Git. Workflow
code, requirements, tests, skills, and documents remain tracked.

## Command Contract

The workflow is exposed only through:

```text
python -m scripts.ggsm_transcription intake --url <https-url>
python -m scripts.ggsm_transcription status --job <job-id>
python -m scripts.ggsm_transcription transcribe --job <job-id>
python -m scripts.ggsm_transcription inspect --job <job-id>
python -m scripts.ggsm_transcription rerun-span --job <job-id> --start <seconds> --end <seconds>
python -m scripts.ggsm_transcription prepare-review --job <job-id>
python -m scripts.ggsm_transcription register-reference --job <job-id> --url <reference-url> --file <markdown>
python -m scripts.ggsm_transcription record-review --job <job-id>
python -m scripts.ggsm_transcription assemble --job <job-id>
python -m scripts.ggsm_transcription verify --job <job-id>
python -m scripts.ggsm_transcription handoff --job <job-id>
```

`status` is read-only. All other commands fail rather than guess when an identifier,
path, stage, or source binding is invalid.

## ASR Policy

The first adapter is local `faster-whisper==1.2.1`, in a dedicated ignored
`.venv-transcribe`. It is imported lazily so ordinary unit tests need neither the
dependency nor a model. The default is the locally cached `small` snapshot, with:

```text
device=cpu
compute_type=int8
language=en
beam_size=5
word_timestamps=true
vad_filter=false
condition_on_previous_text=false
```

The selected local snapshot path/commit, actual configuration, library version,
FFmpeg/FFprobe version, and source hash are recorded with the job. The runner never
silently downloads a model. Targeted `rerun-span` output is supplemental evidence;
it never rewrites `asr/full.jsonl`.

## Inspection and Editorial Review

Inspection identifies confidence outliers, repeated segments, suspicious decoder
patterns, and intervals not covered by ASR segments. An ASR gap is always described
as **ASR-uncovered**, never assumed to be silence.

`prepare-review` splits the entire source timeline into approximately 30-minute
chunks on ASR boundaries and creates one editable Markdown review file per chunk.
Coverage begins at zero and ends at the measured source duration, including all ASR
gaps. `record-review` accepts review only when every ordered chunk exists and is
marked reviewed. A targeted rerun may help an editor, but it does not waive listening
to the rest of the timeline.

Editorial authority is ordered as follows:

1. the source audio;
2. a careful listener's correction supported by that audio;
3. raw ASR and span reruns as drafts;
4. an optionally registered Taptajivanam reference as secondary evidence only.

A reference may suggest a place to re-listen, but it can never replace an
audio-unverified gap, overwrite raw ASR evidence, or introduce an unverified line.

## Delivery Contract

Assembly creates `delivery/onenote-transcript.md` in Unicode NFC. Its header states
`Status: Listening draft`, identifies the source URL, title, and duration in
human-readable form, and makes clear that manual OneNote copy/editing remains outside
the runner. It contains natural paragraphs and conservative speaker labels only where
the audio supports them. A timestamp appears at paragraph/speaker transitions often
enough that no content-bearing stretch exceeds five minutes without one.

The editor must use exact timestamped markers when needed:

```text
[Non-English interpretation omitted, 00:18:05-00:19:34]
[Recording silence, 00:46:18-00:48:10]
[Indistinct English speech, 00:31:09-00:31:14]
```

These markers are not interchangeable: only an audible silence may be called
`Recording silence`; missing ASR coverage alone must remain ASR-uncovered in
inspection/review material. Hashes, diagnostic scores, and internal provenance stay
in evidence files, not in the delivery Markdown.

`verify` checks the source and delivery hashes, review order/coverage, NFC, required
Listening-draft label, source/delivery integrity, and deterministic assembly. Only a
successful verification advances to `draft_ready`. `handoff` writes a local receipt
and advances to `handed_off`; it never claims the draft was copied to OneNote.

## Skill and Claude Bridge

The canonical project skill lives in
`.agents/skills/transcribing-ggsm-lecture/`. Its entrypoint is concise and
explicit-only; its detailed workflow and editorial rules are in `references/`.
`agents/openai.yaml` sets `allow_implicit_invocation: false`.

The Claude bridge at `.claude/skills/transcribing-ggsm-lecture/SKILL.md` is a small
tracked instruction that points to the canonical skill and shared runner. There is no
symlink and no duplicated workflow. `.gitignore` continues to ignore local Claude
skill caches while unignoring only this bridge hierarchy.

## Verification Strategy

Tests use the repository's `unittest` style and temporary job roots. They cover job
IDs, safe job-relative paths, exact source/hash matching, locks, atomic manifests,
artifact rejection, stage transitions, ASR configuration through a fake model,
ASR-uncovered inspection gaps, chunk coverage/order, review refusal, NFC/deterministic
assembly, and changed-source/changed-delivery verification failure. No automated test
downloads audio or loads a real Whisper model.

The skill is checked with its validator and by a bridge-contract test. Independent
fresh-context pressure scenarios must show that the skill keeps audio authoritative,
does not use a reference to fill an ASR gap, resumes a partial matching job by hash,
does not include non-English interpretation, and refuses a request to skip the full
review or hand off raw ASR as a Listening draft.

## Design Review

- No placeholders, TODOs, or deferred decisions are needed for the first local adapter.
- The source hash, whole-timeline review, audio authority, and Listening-draft status
  are consistent in the job model, workflow, and delivery contract.
- The only future extension deliberately left open is a new ASR adapter such as
  RunPod; it must honor the same aggregate state and evidence contract.
- The user's implementation request follows the design discussion and approved plan,
  and is the documented user-review gate before code execution.
