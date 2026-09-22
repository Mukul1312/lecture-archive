# Deepgram and other commercial speech-to-text services (2026-09-22)

Companion to `docs/open-asr-model-survey-2026-09-22.md`. The steward asked about Deepgram.
It is a paid API, so the questions are what its free credit covers, what its terms say,
and how it compares with the commercial services that also offer free allowances.

Source: workflow run `wf_659d3dd8-130` (script `.agents/workflows/commercial-asr-free-credit-survey.js`):
three research sweeps and a verifier. The verifier re-read prices, free credits and
terms on the vendors' own pages on 2026-09-22. Full result with sources:
`data/research/commercial-asr-2026-09/workflow-result-wf_659d3dd8-130.json`.
Prices and terms change; re-check before signing up.

## The short answer

- **Deepgram is worth one free test, but it is not the strongest commercial option.** Its
  real strengths are speed, fetching audio straight from archive.org, and useful per-word
  confidence. Every independent accuracy study puts it in the lower half.
- **The commercial services with the best independent evidence are ElevenLabs Scribe v2
  and AssemblyAI**, with Speechmatics as the most privacy-friendly free test. Their evidence
  on *long recordings* is the most relevant: in one test they never dropped more than 9
  words in a row, while local models, Parakeet and Qwen3-ASR included, dropped runs of
  21–136.
- **No commercial or open service has been independently tested on long Indian-accented
  lectures, cassette audio or Sanskrit.** Only our reference can answer that, and every
  service below can be tested on it within its free allowance.
- **Before uploading any lecture to any vendor, the rights question has to be settled.**
  See the section on it below.

## Deepgram, verified

| | |
|---|---|
| Free credit | **$200**, one-off. The pricing page says "No minimums. No expiration. No credit card required." The ToS promotion clause says payment information is required unless stated otherwise, so confirm at sign-up. |
| Price (pre-recorded Nova-3) | $0.0043/min = **$0.258/h**. Keyterms add $0.0013/min, for **$0.336/h**. Billed per second. |
| Whole corpus (~3,450 h) | **~$890**, or **~$1,160 with keyterms**. The $200 covers ~775 h (22%), or ~595 h with keyterms. |
| Stereo billing | **Risk.** The FAQ says a 10-minute stereo file is billed as 20 minutes. Archive.org mp3s are stereo, so costs could double. Downmixing to mono locally avoids it, but gives up the URL fetch. Test one file and read the billed duration. |
| Our reference | ~$0.30–0.40 per run; ~$0.80 if stereo is billed twice. |
| Word timestamps and confidence | Yes, on every word. An independent study (Kuhn et al., 2025) found Deepgram's confidence among the most useful for flagging errors (AUC 0.86). No confidence score can flag a *dropped* word. |
| Audio from a URL | Yes. It fetches archive.org files itself, with up to 50 concurrent requests. |
| Languages | Per the [models page](https://developers.deepgram.com/docs/models-languages-overview), read 2026-09-22: Nova-3 English includes `en-IN`. Every model defaults to `en`, so `en-IN` must be requested explicitly. Nova-3 also covers Bengali, Hindi, Assamese, Gujarati, Kannada, Marathi, Nepali, Punjabi, Tamil, Telugu and Urdu. **No Odia, no Sanskrit.** With `language=en`, "speech in other, non-specified languages will not be transcribed": **chanted verse will be skipped by design.** The code-switching mode (`multi`) covers English, Hindi and eight European languages, not Bengali or Sanskrit. A long-shot diagnostic: verse spans alone with `language=hi` or `mr` (Devanagari-script languages), transliterated to IAST. Flux is for live voice agents and does not handle pre-recorded audio. The page's "47.4% lower batch WER than competitors" is a vendor claim that the independent leaderboard below does not support. |
| Keyterm prompting | Up to 100 terms and 500 tokens; "focus on the most important 20–50". A comma-separated list "silently boosts nothing". A semi-independent study found it raises accuracy on rare names for every system, but overall WER changes little, and long lists cause false insertions. It is a different mechanism from Whisper's prompt, which did nothing for us, so it is worth one A/B test. |
| Independent accuracy | Artificial Analysis: Nova-3 **5.2%**, behind ElevenLabs Scribe v2 (2.2), Microsoft MAI-Transcribe-2 (2.0), AssemblyAI (3.1), Speechmatics Enhanced (4.0) and even hosted Whisper large-v3 (4.1). Older academic studies, including one on university lectures, put it in the lower half. Its genuine lead is speed: 583x real time, the fastest of 61 models. |

**Deepgram's data terms:**

- **Training is on by default.** Unless `mip_opt_out=true` is sent **on every single
  request**, Deepgram gets an "irrevocable, perpetual" licence to train on the audio and
  the transcript. An account-wide opt-out requires contacting Deepgram.
- **The transcripts are yours:** "We do not claim ownership of Your Content." No clause
  restricts publishing them.
- The ToS forbids using the service or its output "for competitive purposes, including
  model training, benchmarking and other competitive analysis". Two consequences:
  - **Never fine-tune an open model on Deepgram transcripts.**
  - **Keep any Deepgram-vs-others scores internal.** Evaluating it to choose a service for
    your own archive is not obviously a competitive purpose, but publishing comparisons
    would be riskier.

  This is a reading of the terms, not legal advice.

## The peers

Verified on 2026-09-22. "Corpus" means ~3,450 hours at list price.

| service | free allowance | price/h | corpus | independent accuracy | data terms | priority |
|---|---|---|---|---|---|---|
| **ElevenLabs Scribe v2** | 4.5 h **every month**; free users may use it for non-commercial purposes only | $0.22 (+$0.05 keyterms) | ~$760 | **Best evidence:** AA 2.2%; longest dropped run 9 words on podcasts (a commercial blog); best code-switching; Bengali 10.0, Hindi 7.7, Odia 20.7 | Trains on content by default (opt-out not re-verified); you keep all rights in the output | **high** |
| **Speechmatics** (Melia 1 / Standard / Enhanced) | **$100, no card** | $0.129 / $0.24 / $0.40 | ~$445 / $830 / $1,380 | Enhanced AA 4.0%; strong on older university-lecture tests; no Indian-English evidence | FAQ: batch data auto-deleted after 7 days, "never used to improve our models". The ToS grants it a licence to use transcripts for ML, which conflicts | **high** |
| **Deepgram Nova-3** | $200 | $0.258 (+keyterms $0.336) | ~$890–1,160 (x2 if stereo is billed twice) | AA 5.2%; lower half in academic studies | Trains unless `mip_opt_out=true` on every request | **high** (for speed, URL fetch and confidence) |
| AssemblyAI Universal-3.5 Pro | $50, no card, no expiry | $0.21 | ~$725 | AA 3.1%; longest dropped run 9 words | **Free users cannot opt out of training.** ToS bans benchmarking, uploading material you lack rights to, and presenting output as human-generated | medium, blocked by terms |
| Microsoft MAI-Transcribe-2 (Azure) | **card required**; one free account per customer | $0.10 promo until 2026-12-31 | ~$345 | AA 2.0% (best measured) | Not re-verified | medium (preview; no per-word confidence) |
| Gladia Solaria-1 | €50 | $0.61 | ~$2,100 | No published Sanskrit accuracy | Free accounts keep all data for a year; training opt-out only on paid plans | low-medium: **the only service listing Sanskrit** |
| Deepgram Nova-3 multilingual | same $200 | $0.312 | ~$1,080 | — | as Deepgram | medium: one diagnostic run on verse |
| Rev.ai Reverb, Groq Whisper, Soniox, Google Chirp 3 | various | — | — | Weaker, Whisper again, no free credit, or no timestamps | — | low / exclude |

A free *monthly* tier is not a corpus route. At 4.5 hours a month, ElevenLabs would take
over 60 years. The free allowances are for **testing on our reference**, which each covers
many times over.

**Not examined:** the Google Gemini API free tier. An independent study of long, noisy
Indian-English recordings found Gemini 2.5 Pro best of all systems tested (14.15 WER,
against 46.8 for Whisper large-v3). It gives no word timestamps, but forced alignment
could supply them. Its free-tier data use is unverified.

## The rights question, which comes before any test

Hosting on archive.org is not a licence to hand the recordings to a company. Most vendors
make the customer **warrant that they hold the rights** to what they upload. AssemblyAI
explicitly forbids uploading, for testing, material "not independently created by the
Customer" without "all necessary rights and licenses". Several vendors also **train on
uploaded audio by default**: Deepgram unless opted out per request, AssemblyAI's free tier
always, Gladia's free tier with a year of retention, and ElevenLabs.

For Gurudeva's lectures that is a decision for the rights-holder, not for us. It joins the
open question already in the handoff about the ND-licensed years. **Asking the
rights-holder's permission is the first step before any commercial test.** The local
bake-off has no such issue.

## Correction labour, not money, should decide

The eight-point findings showed that correction labour dominates. medium leaves about 690
fixes per lecture, and just listening to the corpus once takes ~3,450 hours of the
steward's time. Against that, $350–1,200 for commercial transcription of the whole corpus
is small **if it removes a large share of the fixes**. If it doesn't, the local route
(Parakeet at ~9–15 laptop-days, or ~$3–7 of rented GPU) wins.

Only our reference can say which applies. The decision rule:

> Count the fixes per lecture for each candidate on the reference. A commercial service
> earns its price only if it removes enough fixes to buy back meaningfully more of the
> steward's hours than the local models do. Dropped words and Sanskrit are scored as
> their own tracks, not folded into one WER.

## Proposed commercial tests (after the rights question is settled)

All within free allowances, on the 69.8-minute reference, scored exactly like the local
models:

1. **Deepgram Nova-3**, `language=en-IN` and `en`, with `mip_opt_out=true`. Run with and
   without ~30 keyterms (Sanskrit names from the glossary). Check the billed duration for
   stereo on this first file.
2. **ElevenLabs Scribe v2**, after switching training off in its settings.
3. **Speechmatics Enhanced** (no card; batch data is not used for training).
4. Optionally, **Deepgram multilingual** on the verse spans only, to see whether verse is
   transcribed or skipped.
