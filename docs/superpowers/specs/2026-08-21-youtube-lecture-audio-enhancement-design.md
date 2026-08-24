# YouTube Lecture Audio Enhancement Design

Date: 2026-08-21
Status: Approved by the user on 2026-08-21

## Context

This work enhances one new lecture and is independent of previously completed lecture
work. Existing outputs and their work directories must remain untouched.

The original validation job used a verified 48 kHz stereo Opus lecture source. Its
title, URL, source hash, decoded sample count, and alternate-source measurements are
job records and are intentionally kept outside this publication. For every new job,
the manifest must record those values and use the exact FFmpeg-decoded PCM frame count
as the authoritative timeline rather than multiplying a container display duration.

## Goals

1. Improve spoken-word clarity and reduce distracting noise while preserving the
   speaker's natural voice and every word.
2. Retain the complete source timeline. No introductions, pauses, chanting, music,
   applause, audience sound, or speech may be removed.
3. Treat the main lecture conservatively and preserve non-speech or uncertain content
   with minimal processing.
4. Produce a lossless archival master and a convenient listening copy.
5. Make every processing decision reproducible and reversible.

## Non-goals

- No video download, editing, remuxing, or delivery.
- No voice cloning, speech replacement, generative restoration, or synthetic content.
- No transcript, subtitles, chapters, or content editing.
- No changes to prior lecture outputs or their accepted settings.
- No maximization of denoising metrics at the expense of naturalness.

## Approved requirements

- Voice naturalness and word integrity are hard vetoes. Residual room tone is better
  than damaged speech.
- The full timeline and decoded sample count must be preserved after model-latency
  compensation.
- Main speech may use conservative DeepFilterNet3 attenuation limits of 22 dB or
  24 dB, selected by blind listening on this source.
- Chanting, music, applause, audience sections, overlaps, and uncertain regions use
  the original signal or only a separately approved mild treatment.
- Every candidate is rendered in parallel from the same original PCM. An enhanced
  output must never be fed through DeepFilterNet again.
- Segment and chunk transitions use duration-preserving fades on the original sample
  timeline.
- Final integrated loudness target is -16 LUFS, with a tolerance of +/-0.5 LU.
- Final true peak must not exceed -1.5 dBTP.
- Deliverables are 48 kHz, 24-bit stereo FLAC and 48 kHz, 192 kbps stereo MP3.

## Design summary

The workflow is an adaptive, voice-first pipeline:

```text
immutable WebM
  -> float PCM decode with recorded headroom gain
  -> diagnostics and segment map
  -> matched candidate renders (original / adaptive-22 / adaptive-24)
  -> objective vetoes and blind listening approval
  -> duration-preserving full render
  -> two-pass EBU R128 normalization
  -> FLAC + MP3 exports
  -> full technical and listening QA
```

This design reuses the repository's proven diagnostic, DeepFilterNet, identity-gate,
and loudness concepts. It requires a new isolated orchestration path because the
existing full-part scripts collapse audio to mono, use source-specific 16-bit/128 kbps
exports, and shorten the timeline when overlapping chunk joins.

## Workspace isolation and artifacts

All new generated artifacts belong under:

```text
data/enhance/youtube/<video-id>/
  manifest.json
  analysis/
  candidates/
  work/
  final/
    <run-id>/
```

The implementation must add a targeted ignore rule for generated audio and work files
in this directory while retaining small manifests and reports when useful. The source
The source media remains immutable at its current location. The manifest records
its path, hash, metadata, tool versions, settings, candidate choice, and output hashes.

Each approved full render receives an immutable run ID derived from its settings and
creation time. Cached artifacts are reusable only when their cache key matches the
source SHA-256, tool/model versions, and all processing parameters. A mismatch creates
a new version; it never silently reuses stale output.

## Components and data flow

### 1. Source validation and lossless working decode

Before processing, verify the source hash and probe the selected audio stream. Decode
stereo Opus once to 48 kHz float PCM without integer clamping. Measure the full decoded
peak. If its absolute peak exceeds 0.95, apply one global headroom gain so the peak is
0.95 and record the exact gain in the manifest. Do not clip samples at +/-1.0.

Represent stereo as mid/side for processing:

```text
mid  = (left + right) / 2
side = (left - right) / 2
```

DeepFilterNet processes the mid channel. The original side channel is retained by
default so that music, chanting, applause, and room ambience are not collapsed to
mono. A side-attenuation experiment is allowed only as a separately named candidate
when diagnostics show that the side channel is dominated by uncorrelated noise; it is
never enabled implicitly.

### 2. Diagnostic pass

Run source-specific diagnostics before selecting filters. At minimum, report:

- decoded and true peak, flat-top runs, DC offset, and digital dropouts;
- integrated loudness, loudness range, crest factor, and level drift;
- global and per-block noise-floor distributions;
- broadband and per-band speech-to-noise margins;
- tonal peaks such as hum and harmonics;
- reverberation estimates across multiple windows;
- usable bandwidth and codec roll-off;
- left/right correlation and side-to-mid energy;
- candidate locations for clean speech, noisy speech, pauses, and non-speech content.

The diagnostic pass may recommend no declicking, notch filtering, or dereverberation.
Those are valid outcomes. A corrective stage is added only when the defect is measured
and a matched candidate demonstrates audible benefit without voice damage.

### 3. Segment map

Create a sample-aligned JSON segment map with these labels:

- `main_speech`
- `mixed_or_audience_speech`
- `chanting_or_music`
- `applause_or_crowd`
- `guarded_pause`
- `uncertain`

Energy/VAD and spectral features may propose regions, but labels that change processing
strength must be reviewable. `uncertain` always uses the untouched original mid/side
signal; it is never enhanced automatically. No label may change source duration or move
a boundary off the original sample timeline.

### 4. Candidate construction

The diagnostic report chooses several representative, non-overlapping windows that
collectively include:

- relatively clean main speech;
- the noisiest main speech;
- low-energy speech and consonant detail;
- at least one guarded pause;
- chanting/music or applause/audience material when present;
- material near the beginning, middle, and end of the lecture.

For each window, generate matched, loudness-balanced files with blind names:

1. untouched original;
2. adaptive speech render with DeepFilterNet attenuation limited to 22 dB;
3. adaptive speech render with attenuation limited to 24 dB.

Non-speech masks use the original mid/side signal in both adaptive candidates. A strong
pause render may be included only inside confirmed guarded pauses, with at least 250 ms
of protection around detected activity and a smooth, duration-preserving fade of at
least 120 ms.

### 5. Candidate gates and approval

Automated metrics shortlist candidates; they do not select the winner. Evaluate:

- same-window speaker-embedding cosine against the untouched signal, calibrated by
  natural variation between untouched speech windows;
- noise-floor reduction and the amount and duration of new exact-zero runs;
- parallel spectral/timbre distance;
- changes in CPPS, HNR, and spectral tilt;
- clipping, peak, loudness, and exact sample alignment;
- transition discontinuities and pumping around masks.

A candidate is rejected when its mean identity score falls more than 0.03 below the
untouched natural-variation anchor, when it introduces a new exact-zero run longer than
50 ms outside an original dropout, or when listening reveals word damage, metallic
speech, pumping, musical noise, dulled consonants, or unnatural silence.

The user listens blind to the surviving candidates. The approved 22 dB or 24 dB speech
setting and any approved pause behavior are recorded in the manifest before a full
render begins.

### 6. Duration-preserving full render

Render the approved speech setting from the original mid channel in memory-safe chunks.
Chunks have contextual halos, but their core sample ranges partition the source exactly.
After each model call:

1. compensate any model latency;
2. verify the expected sample count;
3. crop contextual halos;
4. place the core back on its original sample coordinates.

Adjacent cores blend through same-timeline weights whose sum is one. Unlike the existing
overlap-and-concatenate stitch, this does not remove overlap samples and therefore cannot
shorten the lecture. If a model allocation fails, bisect that core near a quiet point,
retain halos, and retry. Already validated cores remain cached.

Create a full-length processing mask from the reviewed segment map. Reconstruct stereo
from the selected mid signal and original side signal:

```text
left_out  = selected_mid + original_side
right_out = selected_mid - original_side
```

The mask blends between original and processed mid on the same sample indices. The full
render must contain exactly the same number of decoded samples as the working source.

### 7. Loudness normalization and export

Apply two-pass EBU R128 normalization only after the complete adaptive render. Target
-16 LUFS integrated, -1.5 dBTP, and preserve natural lecture dynamics. Use measured
first-pass values in the second pass and force the output sample rate back to 48 kHz.
If dynamic loudness mode audibly pumps, use the closest linear result that respects the
true-peak ceiling rather than adding broadband compression.

Export:

- `final/<run-id>/lecture-enhanced.flac`: 48 kHz, 24-bit PCM, stereo;
- `final/<run-id>/lecture-enhanced.mp3`: 48 kHz, 192 kbps, stereo.

The FLAC is the archival master. The MP3 is derived only from the final normalized
master. If decoded MP3 true peak exceeds -1.5 dBTP, lower the master gain minimally and
regenerate both deliverables so they remain a matched pair.

## Failure handling

- Never overwrite the WebM source, approved candidates, or previous final versions.
- Stop on source-hash mismatch, decode error, missing model/tool, invalid segment map,
  channel/sample-rate mismatch, cache-key mismatch, or failed output decode.
- A model failure may trigger quiet-boundary bisection, but never a silent change to a
  different enhancement model or strength.
- A segment that fails an artifact gate falls back visibly to the milder approved render
  or the original. Record the timestamp and reason in the report.
- Any sample-count mismatch is fatal until model latency or chunk placement is corrected.
- Preserve work files so interrupted full renders resume rather than restart.

## Verification and acceptance

### Technical checks

- Input SHA-256 matches the recorded source hash.
- All intermediate stage assertions pass for 48 kHz, stereo reconstruction, and sample
  alignment.
- The adaptive render and decoded FLAC contain exactly 131,864,451 samples per channel
  (2747.1760625 seconds); the MP3 preserves the same program subject only to verified
  encoder delay/padding and container metadata rounding.
- FLAC and MP3 decode from beginning to end with no errors.
- Integrated loudness is -16 LUFS +/-0.5 LU.
- Decoded true peak of each deliverable is at or below -1.5 dBTP.
- No clipping, non-finite samples, unexpected digital dropouts, or boundary impulses.
- Output hashes, tool versions, settings, and the approved candidate are in the report.

### Listening checks

- Compare original and enhanced audio at matched loudness.
- Re-audition every candidate window in the full render.
- Audition every processing-class transition and each chunk boundary.
- Spot-check quiet consonants, low-energy words, overlaps, music/chanting, applause,
  audience speech, and the beginning and end of the file.
- Naturalness and word integrity override every objective score.

## Implementation boundary

Implementation should create an isolated adaptive orchestrator and focused tests rather
than mutate the behavior or outputs of the previous lecture jobs. Existing scripts may
provide tested helper logic, but the new path must correct these source-specific limits:

- mono-only decoding and rendering;
- hard-coded source and candidate locations;
- overlap stitching that shortens the timeline;
- fixed 16-bit FLAC and 128 kbps mono MP3 exports;
- silence-only blending without reviewed content labels.

The implementation plan will define exact file changes, tests, commands, and checkpoints
after this specification is reviewed and approved.
