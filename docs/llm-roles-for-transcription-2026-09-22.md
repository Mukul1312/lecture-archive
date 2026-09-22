# What language models can and cannot do for this archive (2026-09-22)

The steward asked for the language models to be judged properly, noting that he can rent
GPUs and obtain licences, so neither size nor licence is a reason to exclude anything. This
records what the evidence says about **capability**, and what would have to be measured.

Source: workflow run `wf_40a9456e-3c0` (script `.agents/workflows/llm-roles-evidence.js`),
three research sweeps and an adversarial verifier that corrected several of their claims.
Full result with sources: `data/research/llm-roles-2026-09/workflow-result-wf_40a9456e-3c0.json`.

## The short answer

1. **Never let a model rewrite a transcript freely.** This is the most replicated result in
   the literature, and every measurement points the same way.
2. **A model that only reads text cannot recover our biggest error class.** 706 of 6,678
   reference words are missing from the best transcript, so text-only correction cannot get
   below **10.6% WER** on this lecture. That is arithmetic, not opinion.
3. **What changes that ceiling is a second, different recogniser** — which is exactly the
   Indic-Transcribe-flex test already under way — plus, on the paid side, an Indic
   recogniser that accepts **keyterm biasing at the recognition stage**.
4. **Where a model is genuinely safe is where it cannot invent words:** choosing between two
   recognisers' words, labelling each word's language, and restoring punctuation with a
   token classifier.
5. **The binding constraint is not money or GPUs. It is the steward's attention:** about 690
   edit sites per lecture across 3,766 lectures is roughly 2.6 million review decisions.

## 1. Free-form correction makes transcripts worse

| study | base recogniser | result |
|---|---|---|
| Cambridge (Ma et al.) | Whisper small.en on TED lectures, 3.89 WER | GPT-3.5 zero-shot **5.84**; GPT-4 **4.60** — every variant worse |
| Apple (Gu et al.) | 2.2 / 5.3 WER | Mistral-7B **32.0 / 37.0**; Llama-3.1-70B **8.8 / 13.0**; "all LLMs degrade the baseline" |
| Ablation, DeepSeek-V2 | Mandarin, 5.06 CER | a simple prompt took it to **53.10**, insertions 0.12 → 38.76 |
| EACL 2026, Hindi | a good IndicConformer baseline | in-context correction degraded it **at every shot count**; only *fine-tuned* mT5/ByT5 helped |

The named failure mode matters to us more than the numbers. Researchers call it
**over-correction**: the model "steers the sentence more towards written language, instead
of a verbatim transcript", removing repeated words and shortening sentences. Gurudeva's
English — his repetitions, his sentence shapes — is exactly what a fluency-seeking corrector
would smooth away. An archive exists to preserve what he said.

**Our own matrix already found the same thing one stage earlier:** putting a Sanskrit
glossary in Whisper's prompt made things *worse* (WER 34.29% → 34.44% on small, 28.42% →
29.04% on turbo). And the post-recognition glossary pass produced confident wrong words
(*baba* → *bhava*).

Two qualifications, in fairness:

- **Gains do appear when the starting transcript is bad.** With Whisper-tiny at 8.13 WER,
  filtered correction reached 5.65; with Whisper-large-v3 at 2.78 it got *worse*. Our 27.2%
  is "weak" by those standards, so headroom may exist — but those gains came from ordinary
  English substitutions, not from 55.8% unrecognisable Sanskrit.
- **One constrained design did beat a Whisper baseline:** forcing the model to pick the
  *closest* of the recogniser's own alternatives. That turns a writer into a chooser, and it
  should be the default wrapper on any model we try.

## 2. The ceiling, and where our missing words actually are

Measured today on the current best transcript (medium, skip rule off):

| where the missing words are | words | missing | rate | share of all missing |
|---|---:|---:|---:|---:|
| plain English cues | 4,336 | 333 | 7.7% | 50% |
| English with Sanskrit words | 1,975 | 264 | 13.4% | 40% |
| verse (mostly Sanskrit or Bengali) | 367 | 65 | 17.7% | 10% |

And **92% of the missing words are not in the stretches the subtitles never covered** — the
model simply did not write them. The worst individual cues are Bengali songs and Sanskrit
verses (*bārdhakye ekhona, bhakativinoda*; *ahny āpṛtārta-karaṇā*).

So two things are true at once. **Dropping is about twice as likely in code-switched and
verse passages**, which supports the steward's hypothesis and points at a multilingual
recogniser. But **half the dropped words are still in plain English**, which no Indic model
will fix.

## 3. Where a language model is actually safe

Ordered by how little damage it can do:

| job | why it is safe | the honest baseline it must beat |
|---|---|---|
| **Choosing between two recognisers' words** | the model may only output an index into existing words; it cannot invent | plain ROVER voting, which is free, deterministic and sometimes wins |
| **Labelling each word's language** (English / Sanskrit / Bengali) | token classification cannot change the text | "any word with diacritics is not English", plus the glossary |
| **Restoring punctuation** with a token classifier such as AI4Bharat's Cadence | structurally cannot add, drop or alter a word | no punctuation at all |
| **Odia → English translation** | a separate text, not an edit to the archive | IndicTrans2 |
| **Identifying which verse was chanted** | the output is a *catalogue reference*, verified by aligning the canonical text | fuzzy search over a verse index |

For verse identification the research missed something our own data shows: **we need two
indexes, not one.** Gurudeva chants Sanskrit verses *and* sings Bengali padāvalī
(Bhaktivinoda Ṭhākura, Narottama dāsa). A Sanskrit corpus like GRETIL does not contain the
Bengali songs — and Bengali songs are exactly the cues where the most words go missing.

## 4. The models, by capability

Verdicts from the verifier. Size and licence are excluded from the reasoning, as the steward
asked. Every score below is a multiple-choice test where **25% is guessing**.

| model | verdict | why |
|---|---|---|
| **A second recogniser** (Indic-Transcribe-flex; Sarvam Saaras v4 with keyterms) | **measure first, ahead of every language model** | Only this changes the 10.6% ceiling. Whisper's own alternatives are unusually low-diversity, so a *different* architecture is worth more than more Whisper guesses |
| **Plain ROVER** over two recognisers | **the mandatory baseline** | Free, deterministic, cannot hallucinate; it beat every local 4–9B model in one practitioner test |
| **Fine-tuned ByT5 / mT5 corrector** | worth building, later | The *only* systems that improved a strong Indic baseline. Needs training pairs — which the Prabhupadavani run now under way produces |
| **Sarvam-105B** | worth measuring, hosted | No independent evaluation at all; a gap to close cheaply on its free credit |
| **MITRA-QWEN 9B** | worth one verse-identification test | The only open model demonstrably trained on Sanskrit in IAST, though its Sanskrit token count is not published |
| **DeepSeek-V3.2** | worth measuring as the open ceiling | Best open Sanskrit on the independent record (51.3) |
| **Llama-4-Scout, Llama-3.3-70B** | constrained arms only | Best open Sanskrit under 400B (44.0), but two benchmarks disagree about it |
| **Gemma-3-27B / Gemma-4-31B** | worth measuring for translation | The base that Indic translation teams actually fine-tune |
| **Qwen3-32B** | the open-weight control | Good Sanskrit for its size (39.2), but the Hindi study found it degrades a good baseline |
| **Frontier hosted models** | worth measuring as the ceiling — **after a contamination check** | The only positive evidence on our problem shape: GPT-5.1 restored 38.2% of deleted words at 83.3% precision, from *five* hypotheses |
| **Sarvam-30B** | control only | Its one independent number is unsound (72% of its Sanskrit answers were cut off mid-thought) |
| **Param-1-7B** | not worth measuring | A 4,096-token context cannot hold a chunk plus two hypotheses plus a glossary. That is a capability limit, not a licence one |
| **Sarvam-1, Param-1-2.9B, Paramanu, dhee-qwen3-sanskrit** | not worth measuring | Base models with no instruction following; English-and-Hindi only; or, for the Sanskrit fine-tune, a configuration byte-identical to Qwen3-1.7B with no added Sanskrit vocabulary and no published evaluation |
| **Encoders** (IndicBERT-v3, MuRIL, XLMIndic) | worth measuring for word-labelling only | XLMIndic is trained on romanised text closest to IAST, but has no English at all, so it can only separate Sanskrit from Bengali inside spans already known to be non-English |

## 5. Guardrails for any trial

- **Constrain the output.** Either an index into existing words, or an explicit edit list.
  Run the free-form version **once**, to measure the damage.
- **A do-nothing control.** Feed 100 already-correct sentences and count spurious edits.
  Target under 1%.
- **Measure verbatim fidelity**, not only error rate. Edits to already-correct sentences are
  a first-class metric.
- **Check for contamination before trusting any hosted model:** if the Melbourne subtitles
  are published online, that arm measures memorisation, not recognition.
- **Never publish a confidently wrong verse.** For verse identification, the model must be
  allowed to answer "unknown", and every proposal must be verified by aligning the canonical
  text to the audio.

## 6. Corrections to the research itself

The verifier found errors in the sweeps, recorded here so they are not repeated:

- **Qwen3.5 does not publish a language list, and no official source names Sanskrit.** Two
  sweeps built recommendations on a table that does not exist.
- **Gemma-3-27B is not Apache-2.0** (it uses the Gemma licence); Gemma-4-31B is.
- **Qwen3-32B's Odia score is 28.9, not 40.7** (that belongs to Llama-3.3-70B), so
  Sarvam-30B's 31.7 actually beats it on Odia.
- **The best-controlled low-resource study degraded one sentence in five (19.3%)**, not one
  in eight as reported.
- **"Sanskrit pretraining" for MITRA-QWEN** is a combined Tibetan, Sanskrit, Pali and
  Chinese corpus; no Sanskrit-only figure is published.

## 7. What was missed, and matters

- **Sarvam's Saaras v4 accepts up to 50 keyterms at recognition time**, with a code-mix mode
  that keeps a term in Latin script. That is glossary biasing *inside the recogniser*, which
  is where the literature says it belongs, and it is the paid-side counterpart to the flex
  test.
- **Sarvam's API also hosts Gemma-4-31B and DeepSeek V4 Flash**, so several "rent a GPU"
  arms have a hosted route costing rupees per lecture, inside the free credit.
- **The Odia seva starts from audio, not text.** Every comparison here judges translation of
  written Odia, while the recogniser that produces that Odia has not been chosen.
- **Nobody priced the human side.** ~2.6 million review decisions is the real constraint, and
  the precision threshold an automatic pass must meet should be derived from it, not picked
  by feel.
