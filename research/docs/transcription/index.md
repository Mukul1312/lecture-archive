# Transcription

**The question.** About 3,766 of Gour Govinda Swami's lectures need transcripts a devotee can
read while listening. The speech is trilingual — English, Bengali and Sanskrit, switching inside
single sentences — and someone has to correct whatever the machine produces. Which system, and
what will the correcting cost?

## The answer, as it stands on 2026-09-23

**Hosted services beat every local model, and there is no single winner.**

| | best system | what it gives |
| --- | --- | --- |
| English (≈88% of the words) | **ElevenLabs Scribe v2** | 10.5% wrong against Whisper's 17.6% |
| Sanskrit and names | **flex `bn mixed`**, then Sarvam | 38.6% and 45.9% against Whisper's 62.1% |
| Fewest words lost | **all three combined** | 405 dropped against Whisper's 746 |
| Fewest corrections | **ElevenLabs alone** | **459 stops against Whisper's 627 — 27% less labour** |

The measure that matters is **edit sites**: the number of places a corrector must stop and type.
Every earlier improvement — a bigger model, turning off Whisper's no-speech skip rule, fusing two
local systems — moved *words* while leaving *stops* flat. ElevenLabs is the first change that
reduces the work itself.

**Still open:** whether to spend ~$760 on ElevenLabs alone, or ~$2,000 for the three-way
combination that recovers the most speech. Before any spend: verify the word timestamps the
read-along needs, test the chosen route on a second lecture, and measure the corpus's real
average length, which every cost figure multiplies.

## What the work established

1. **Code-switching concentrates the errors.** An English word next to a Sanskrit word is wrong
   three to five times more often than one far from any — in *every* system tested. But half of
   all errors are still plain English, so a multilingual model fixes at most half the problem.
2. **More than half the remaining labour is single-word fixes in plain English**, not lost
   paragraphs and not Sanskrit. The Sanskrit is where the error *rate* is worst; the English is
   where the *hours* are.
3. **About 72% of the remaining errors are genuinely the model's.** Of the rest, 15% are the
   reference's own fault and 13% are nobody's — spelling and romanisation variants a corrector
   would never stop for. Mishearing chanted Sanskrit is the largest recoverable class, which is
   the measured case for combining systems rather than buying ElevenLabs alone.
4. **Keyterm prompting works only inside the recogniser.** Fifty Sanskrit names cut ElevenLabs'
   Sanskrit errors by 8 points. The same list failed as a Whisper prompt and as a post-correction
   pass.
5. **184 words a lecture are lost by every system** — Bengali songs and chanted verse. They are
   quotations, so the fix is retrieval from print, not a better recogniser.
6. **Never let a language model rewrite a transcript.** It degrades transcripts in every published
   study, and over-correction erases the verbatim speech this archive exists to preserve.
7. **Public benchmarks have mispredicted this corpus three times out of three** — `large-v3-turbo`,
   Indic-Transcribe-flex and Deepgram all ranked well elsewhere and did badly here.

## The pages

**The method** — everything assembled, and what is still missing.

- [The method, and what is still missing](methodology-2026-09-23.md) — the five-stage pipeline,
  what each stage is measured to buy, and the three structural gaps that would stop it working.

- [Where the verses come from](verse-corpus-sourcing-2026-09-23.md) — GRETIL is the answer for
  Sanskrit and there is no answer for Bengali; plus what an LLM may and may not do here.

**Measured findings** — what was actually run and scored.

- [What the eight purposes measured](melbourne-reference-eight-point-findings-2026-09-22.md) —
  accuracy, model choice, correction workload, the Sanskrit glossary, where the errors are, timing
  for the read-along, the correction workflow, and the regression check.
- [The nine-system bake-off](commercial-bakeoff-results-2026-09-23.md) — nine systems on one
  66-minute cut of the same lecture, one scorer, with costs and practical notes. **The main
  result.**
- [Reading the mistakes, not the rates](error-text-analysis-2026-09-23.md) — printing the errors
  word by word, which found three faults in the scoring itself and moved where the labour is.
- [Does Whisper support Sanskrit?](whisper-sanskrit-2026-09-23.md) — **zero hours** of Sanskrit
  transcription data; `sa` is a token, not a capability. Why turbo was worse, and why verse
  retrieval is the established answer.
- [Should we fine-tune on his voice?](speaker-adaptation-2026-09-23.md) — speaker adaptation,
  its three failure modes for a verbatim archive, and the one finding worth more than it.
- [Are the models wrong, or our reference?](who-is-wrong-adjudication-2026-09-23.md) — all 483
  remaining disagreements judged one at a time, with every claim against the reference put to
  a sceptic. **72% are genuinely the model's mistake.**

**Surveys** — what exists, before anything was run.

- [Beyond Whisper: open ASR models](open-asr-model-survey-2026-09-22.md)
- [Commercial speech-to-text services](commercial-asr-survey-2026-09-22.md)
- [The steward's Indic links, read and judged](indic-links-survey-2026-09-22.md)
- [What language models can and cannot do](llm-roles-for-transcription-2026-09-22.md)

**Ground truth** — what can be trusted as a reference.

- [The 1985 transcripts are not reproducible](ggsm-transcript-reproducibility-2026-08-27.md) —
  and never were, so nothing may be gated on matching them.

## Reading order

New to this topic: start with the [bake-off](commercial-bakeoff-results-2026-09-23.md) for the
decision, then [reading the mistakes](error-text-analysis-2026-09-23.md) for what the numbers
mean. The [eight purposes](melbourne-reference-eight-point-findings-2026-09-22.md) explains why
these particular things were measured.
