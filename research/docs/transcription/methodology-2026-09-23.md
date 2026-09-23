# The method, and what is still missing (2026-09-23)

Everything measured this session, assembled into one pipeline — and an honest list of what
has not been built, not been measured, or not been thought about. The second list is longer
than it looks, and two items on it are structural rather than incremental.

## The method

Five stages. Each line is measured on the Melbourne reference unless marked otherwise.

| # | stage | what it does | evidence |
|---|---|---|---|
| 1 | **Bulk decode** | three local models over the whole corpus on a rented GPU | ~$33, ~5 days on one GPU — *figure not yet benchmarked for these models* |
| 2 | **English spine** | choose the best of three per word | majority vote settles **86.1%** of plain English; ceiling **92.4%** |
| 3 | **Sanskrit & Bengali** | retrieve the printed verse; substitute from a glossary | 54% of Sanskrit is quotation, 46% lone terms; recognition ceiling is only 67% |
| 4 | **Timing** | force-align the finished text to the audio | **not designed yet — see below** |
| 5 | **Correction** | a person fixes what is left, measured in stops | ~474 stops a lecture today |

### Why each stage is shaped that way

**Three local models, not the paid services.** Their per-word ceiling on plain English (92.4%)
essentially matches the best paid single system, at no cost and with nothing leaving the
laptop. ElevenLabs is better as a single system, but the archive is not limited to a single
system.

**Selection, not gap-filling.** The current fusion only inserts where the base is silent and
never overrules a wrong word. That is the whole distance between 82.9% delivered and 92.4%
available.

**Retrieval for the quotations, never recognition.** Whisper has **zero hours** of Sanskrit
transcription training data; Bengali has 1.3. Chanted verse defeats even Sanskrit-trained
models at 99–110% WER. Meanwhile a Quranic verse finder reaches 100% retrieval from a
10.1%-WER transcript, and Gregorian chant goes 24.1% → 3.8% CER by matching against a
database. The quotations have fixed printed text; matching beats hearing.

**No fine-tuning, for now.** Full fine-tuning destroys the other languages in the same audio
(Korean 15.96% → 436% WER). LoRA hallucinates memorised phrases into silence, and these are
cassettes full of pauses. Training on short clips wrecks long-form alignment, which is the
product.

---

## What is missing

### Structural — the plan does not work without these

!!! danger "1. The selector does not exist"
    Every number in stage 2 is a *ceiling*, computed by asking an oracle. Nobody has written
    the thing that actually chooses. This is the largest measured win available — roughly nine
    points of English — and it is entirely unbuilt.

    It has three tiers, and only the first is easy: **709 words** are settled by a plain
    majority; **561 words** are got by exactly one system, where a majority vote picks *wrong*
    and something cleverer is needed; **813 words** no system has.

!!! danger "2. The finished transcript has no timings"
    **flex produces plain text with no timestamps at all.** Only Whisper emits word times. So a
    transcript assembled by choosing across three systems has no timing for most of its words —
    and the deliverable is read-while-listening.

    The fix is a **forced-alignment stage** that takes the final text and the audio and produces
    word onsets. It is standard, and it is not in the plan. It also has to survive 60–90 minute
    inputs and code-switched text.

    Worse, **absolute timing accuracy has never been measured for anything.** We know only that
    Whisper's word times agree across models and do not drift — agreement is not correctness.
    There is still no hand-marked ground truth; roughly 100 marked word onsets would settle it.

!!! danger "3. There is no verse corpus to retrieve from"
    Stage 3 assumes a database of Sanskrit verses **and Bengali padāvalī**. It does not exist
    in this repository, and no source has been chosen. Retrieval cannot be built before the
    corpus is. Bengali is the harder half — the songs are the longest blackouts we measured,
    and the printed sources are scattered.

### The output is not yet a document

Everything measured is **folded tokens**: lower-cased, no punctuation, no diacritics. The
product is readable text with capitals, sentence breaks, paragraphing and IAST for Sanskrit.

- The fused files are measurement artifacts, not drafts.
- **flex emits almost no punctuation at all**, so any word chosen from flex arrives bare.
- Nobody has decided where punctuation and casing come from in the final text.

### Validity — how much one lecture can carry

- **Every number rests on one 66-minute reference.** The one other corpus tried,
  Prabhupadavani, behaved differently — Whisper won there.
- **The reference itself has faults**, and they were adjudicated only at ElevenLabs' errors,
  so every other system's discount is a lower bound.
- **The corpus average length is still unverified**, and every cost figure multiplies it.

### Quality and safety

- **No abstention.** The research is explicit: say "unclear" rather than emit a plausible wrong
  verse. For scripture that is the difference between a gap and a fabrication. Nothing in the
  pipeline can currently decline to answer.
- **No confidence signal**, which is what the 561 hard words need. Deepgram has the
  best-evidenced per-word confidence and is 517× real time — rejected as a transcriber, it may
  still earn a place as an error detector.
- **Sanskrit should be scored by CER, not WER**, because sandhi fuses words and "half of WER is
  spacing". Recommended, not implemented.

### Not yet considered at all

- **Speaker separation.** Other people speak — Mr Peter and others open 41 cues in this one
  lecture. A read-along presumably needs to know who is talking. Nothing in the pipeline
  attributes speech.
- **What a corrector actually uses.** The workflow is measured in "stops", but no correction
  interface exists for the corpus, and the one timed correction test sits on a different
  lecture.

### Operational

- **The GPU figure is for a model we rejected** (`large-v3-turbo` int8). The consensus approach
  needs three models, so triple the GPU-hours, and the benchmark explicitly says accuracy was
  not measured.
- **Storage may exceed compute** — 0.5 TB at $0.07/GB/month is ~$38/month.
- **The tooling is unversioned.** `error_text.py`, `adjudication.py`, `inspect.py` and the rest
  live under a gitignored `data/reference/`. Twenty-plus scripts, including the verifiers that
  check published figures.

---

## What to do next, in order

1. **Build the selector.** Biggest measured win, needs no new data, no GPU, no money. Start
   with the plain majority (settles 709 words) and measure; then attack the 561.
2. **Decide where the verse corpus comes from.** Nothing in stage 3 can start until it exists.
3. **Design the forced-alignment stage**, and hand-mark ~100 word onsets so timing can finally
   be measured rather than assumed.
4. **Verify a second lecture.** Everything rests on one, and the one check we have disagreed.
5. **Decide the gitignore question**, so the tools survive.

Only then does spending on a bulk GPU pass make sense — and it should be benchmarked on the
models actually chosen.
