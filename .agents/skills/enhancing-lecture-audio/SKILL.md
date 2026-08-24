---
name: enhancing-lecture-audio
description: Use when the user explicitly invokes $enhancing-lecture-audio for a long lecture recording that needs conservative denoising, complete-timeline preservation, blind auditioning, resumable processing, and FLAC plus MP3 delivery.
---

# Enhancing Lecture Audio

## Overview

Run the repository's proven Original/D30 workflow. Voice naturalness and word integrity are the veto; stronger noise removal never overrides either one. This skill is explicit-only.

## Start or Resume

Read [references/workflow.md](references/workflow.md) completely before changing a job. From the canonical repository root, discover `data/enhance/jobs/*/job.json` before creating anything. Resume the single source-hash match using its validated artifacts; conversation memory is not authority.

## Non-negotiable Gates

1. Hash and probe the source, check storage and Windows path budget, then benchmark short excerpts.
2. Prepare five blind, downward loudness-matched Original/D30 pairs covering the beginning, middle, ending, noisy speech, pauses, and event material when present.
3. Stop for per-clip choices. Render fully only when the private key maps every choice to D30; discuss mixed or tied results instead of majority voting.
4. Apply one DeepFilterNet3 pass at a 30 dB attenuation limit to the original mid. Restore the untouched side and every decoded frame. Never stack enhancement or cut the timeline.
5. Deliver 48 kHz stereo 24-bit FLAC and 192 kbps MP3, validate them end to end, then stop for final listening approval.
6. Record explicit approval in a hash-bound `listening-approval.json`. Automated QA cannot grant acceptance.

## Keep It Fast

- Estimate runtime from the audition benchmark and report a range before rendering.
- Run focused production checks; run the full engineering suite only when code changes.
- Reuse validated `work/c/<64-character-key>` chunks after interruption.
- Report blockers immediately with preserved work and the exact next action.
- Treat a runner defect as a bounded tested fix, then resume; do not redesign during a production job.

## Quick Reference

| State | Action |
|---|---|
| New source | Hash, probe, preflight, create one job record |
| Audition ready | Give the user the five blind pairs and wait |
| Unanimous D30 | Record the mapped decision and run the generic D30 command |
| Interrupted | Validate artifacts and resume only the missing stage/chunks |
| Delivery ready | Report MP3/FLAC paths and request final listening |
| User says approved | Write the immutable approval receipt and close the job |

## Red Flags and Corrections

- "Start rendering while the user reviews": stop at the audition gate.
- "A majority chose D30": require all five mapped D30 choices.
- "A fresh job is simpler": resume the matching hash-bound job.
- "Retry in any short directory": stay inside the verified job root.
- "Duration gives the ETA": benchmark the actual model and machine.
- "Technical QA means approved": preserve final human listening.
