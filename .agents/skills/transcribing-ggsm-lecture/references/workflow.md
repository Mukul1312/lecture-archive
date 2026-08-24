# Local GGSM lecture workflow

## Scope and start

Handle one user-selected **English** SSGGSM archive lecture at a time in this
local-only workflow. Do not extend this workflow to a catalog, publishing, OneNote
sync, bulk scheduling, RunPod, or non-English transcription.

Start with the exact shared runner command:

```text
python -m scripts.ggsm_transcription intake --url <https-url>
```

The downloaded source's SHA-256 is the job identity. It is never the URL, filename,
duration, chat memory, reference text, or a prior partial transcript. `intake` may
resume a matching partial job only after the runner validates its hash-bound source
and evidence. Never manually select a lookalike job, copy artifacts between jobs, or
bypass a hash mismatch.

## Required order

Run and respect each stage in this order:

```text
intake
transcribe
inspect
optional rerun-span
prepare-review
whole-timeline listening/editing
record-review
assemble
verify
handoff
```

This is intake, local full ASR, inspection, optional targeted rerun, review, and
verified local handoff in that order. `transcribe` is the local full-ASR stage and
`inspect` must follow it before review preparation.

Use the corresponding runner commands with `--job <job-id>` after intake. A targeted
`rerun-span --start <seconds> --end <seconds>` is supplemental evidence only; it
never replaces full ASR or the whole-timeline review. Do not invent a skipped stage,
edit raw `asr/full.jsonl`, or treat raw ASR as a Listening draft.

`prepare-review` creates the editable review chunks. Every chunk and the entire
source timeline must be genuinely listened to and edited against source audio before
`record-review`. If that editorial review has not happened, stop there and say that
the next safe action is to complete it; strong ASR, a rerun, or a reference does not
waive it.

## Failure and delivery boundaries

If the runner rejects the job, source, stage, or artifact, stop and report the
specific error plus the next safe command, such as
`python -m scripts.ggsm_transcription status --job <job-id>` or a retry of the failed
valid stage. Never manually mutate manifests, hashes, raw ASR, or
verification evidence to force progress.

If the local faster-whisper environment or cached model snapshot is absent, stop and
report that local ASR must be prepared from the repository's
`requirements-transcribe-windows.txt` and
`requirements-transcribe-windows.lock.txt` before retrying. Do not silently download
a model or substitute RunPod.

Only the runner's verified assembly produces `delivery/onenote-transcript.md`.
`handoff` writes a local receipt; it does not copy anything into OneNote or claim that
it did. Manual OneNote copy/edit remains outside this workflow.
