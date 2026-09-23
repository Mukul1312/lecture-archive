# Odia

**The question.** 1,357 Odia lectures, **1,952 audio-hours**, need transcripts — and since
2026-08-28, English translations too. This is volunteer seva, so cost matters absolutely. Nobody
can listen to 1,952 hours to check the result, so the design has to audit itself.

## The answer, as it stands on 2026-08-28

- **The laptop, not AWS.** Triage runs at **282–868× real time** streaming straight from a URL,
  at a flat **42–43 MB** of memory regardless of file length, and needs **zero bytes** of disk —
  ffmpeg reads HTTPS natively. The whole-file approach it replaced used 1.4–3.0 GB.
- **Two engines, not one.** Azure for the first pass, **ElevenLabs Scribe v2** for the second.
- **Run the second engine on everything**, not on a selected worst slice — selecting the worst
  slice needs a confidence signal, and the only one available was the first engine's own.
- **Adding English translation breaks the read-while-listening standard**, which was the whole
  point of the original transcripts. That trade-off is the design's central tension.

## Read these two together

The design document was written first; a later session the same day measured its assumptions and
**overturned three of its claims**. Both are kept:

- [Odia → Odia + English: system design and cost model](odia-dual-output-system-design-2026-08-28.md)
  — the proposal, the engine comparison and the reference-free QA design.
- [Measured findings and corrections](odia-design-measured-corrections-2026-08-28.md) — what
  measurement and 37 research agents changed. **Read alongside, not instead.**

Superseded: Sarvam as the second engine (no word-level timestamps, no per-word confidence,
upload-only, 20 files a job), and selecting only the worst 30% for a second pass.

## The pages

- [Odia ASR models and measuring intelligibility damage](odia-asr-and-intelligibility-metrics-2026-07-31.md)
  — which models exist, and how to tell when cleaning has hurt the words.
- [Odia → Odia + English: system design and cost model](odia-dual-output-system-design-2026-08-28.md)
- [Measured findings and corrections](odia-design-measured-corrections-2026-08-28.md)
- [Cost estimate and bid strategy](odia-transcription-bid-estimate-2026-07-25.md) — where the
  1,952-hour figure comes from (ffprobe'd, not estimated).

!!! note "Standing constraint"
    This work is **volunteer seva, not paid**. Every provider price in these pages is a dated
    snapshot, not an operational guarantee — recheck the official source before spending.
