# Transcription

**The question.** About 3,766 of Gour Govinda Swami's lectures need transcripts a devotee can
read while listening. The speech is trilingual — English, Bengali and Sanskrit, switching inside
single sentences — and someone has to correct whatever the machine produces. Which system, and
what will the correcting cost?

## The answer, as it stands on 2026-09-23

**Hosted services beat every local model, and there is no single winner.**

| | best system | what it gives |
| --- | --- | --- |
| English (≈88% of the words) | **ElevenLabs Scribe v2** | 11.7% wrong against Whisper's 18.7% |
| Sanskrit and names | **flex `bn mixed`**, then Sarvam | 38.6% and 45.9% against Whisper's 62.1% |
| Fewest words lost | **all three combined** | 476 dropped against Whisper's 829 |
| Fewest corrections | **ElevenLabs alone** | **470 stops against Whisper's 636 — 26% less labour** |

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
3. **Keyterm prompting works only inside the recogniser.** Fifty Sanskrit names cut ElevenLabs'
   Sanskrit errors by 8 points. The same list failed as a Whisper prompt and as a post-correction
   pass.
4. **184 words a lecture are lost by every system** — Bengali songs and chanted verse. They are
   quotations, so the fix is retrieval from print, not a better recogniser.
5. **Never let a language model rewrite a transcript.** It degrades transcripts in every published
   study, and over-correction erases the verbatim speech this archive exists to preserve.
6. **Public benchmarks have mispredicted this corpus three times out of three** — `large-v3-turbo`,
   Indic-Transcribe-flex and Deepgram all ranked well elsewhere and did badly here.

## The pages

**Measured findings** — what was actually run and scored.

- [What the eight purposes measured](melbourne-reference-eight-point-findings-2026-09-22.md) —
  accuracy, model choice, correction workload, the Sanskrit glossary, where the errors are, timing
  for the read-along, the correction workflow, and the regression check.
- [The nine-system bake-off](commercial-bakeoff-results-2026-09-23.md) — nine systems on one
  66-minute cut of the same lecture, one scorer, with costs and practical notes. **The main
  result.**
- [Reading the mistakes, not the rates](error-text-analysis-2026-09-23.md) — printing the errors
  word by word, which found three faults in the scoring itself and moved where the labour is.

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
