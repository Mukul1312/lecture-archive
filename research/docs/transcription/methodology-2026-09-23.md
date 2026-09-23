# The method, and what is still missing (2026-09-23)

Everything measured this session, assembled into one pipeline — and an honest list of what
has not been built, not been measured, or not been thought about. The second list is longer
than it looks, and two items on it are structural rather than incremental.

## The method

Five stages. Each line is measured on the Melbourne reference unless marked otherwise.

| # | stage | what it does | evidence |
|---|---|---|---|
| 1 | **Bulk decode** | three local models over the whole corpus on a rented GPU | ~$33, ~5 days on one GPU — *figure not yet benchmarked for these models* |
| 2 | **English spine** | choose the best of three per word | oracle ceiling **92.4%** on plain English — but **plain voting reaches none of it**, see below |
| 3 | **Sanskrit & Bengali** | retrieve the printed verse; substitute from a glossary | 54% of Sanskrit is quotation, 46% lone terms; recognition ceiling is only 67% |
| 4 | **Timing** | force-align the finished text to the audio | **not designed yet — see below** |
| 5 | **Correction** | a person fixes what is left, measured in stops | ~474 stops a lecture today |

### Why each stage is shaped that way

**Three local models, not the paid services.** Their per-word ceiling on plain English (92.4%)
essentially matches the best paid single system, at no cost and with nothing leaving the
laptop. ElevenLabs is better as a single system, but the archive is not limited to a single
system.

**Selection, not gap-filling** — in principle. The gap-filling fusion only inserts where the
base is silent and never overrules a wrong word, which is why it delivers 82.9% against a
92.4% ceiling. But the voting selector built to close that gap **made things worse**, and the
reason is instructive: see the first gap below.

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

!!! danger "1. The selector was built, and plain voting does not work"
    `scripts/transcript_select.py` implements ROVER: align every transcript onto the first,
    then vote in each slot. 13 tests. Measured on the Melbourne reference against its own
    pivot (flex en-native):

    | | |
    |---|---:|
    | words the pivot got wrong that voting **fixed** | 33 |
    | words the pivot got right that voting **broke** | 75 |
    | **net** | **−42** |

    And where:

    | setting | fixed | broke | net |
    |---|---:|---:|---:|
    | plain English | 20 | 20 | **±0** |
    | mixed Sanskrit | 11 | 41 | **−30** |
    | verse or chant | 2 | 14 | **−12** |

    **Voting is a wash on plain English and actively harmful wherever Sanskrit appears** —
    precisely what the verse-retrieval research predicted when it reported that a second
    architecture "does not recover any" of the failures.

    **A correction to what this page said earlier.** The 92.4% figure is a ceiling that requires
    an *oracle* — something that knows which system is right. Plain voting has no such signal,
    so it captures none of the headroom. Counting "two of three are right" as recoverable was
    misleading: those are mostly words the pivot already had.

    What the next attempt needs is not better voting but **a confidence signal**. Whisper emits
    a per-word probability and we already store it; flex emits none. Deepgram has the
    best-evidenced per-word confidence at 517× real time — rejected as a transcriber, it may
    earn its place here. Until some signal can separate "two systems agree and are right" from
    "two systems agree and are wrong", selection is not the lever it looked like.

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

1. **Find a confidence signal.** The selector is built, and plain voting is measured to lose 42
   words. Without something that separates "two systems agree and are right" from "two agree
   and are wrong", no amount of vote-tuning helps. Whisper's per-word probability is already on
   disk and has never been used; Deepgram sells the best-evidenced one at 517× real time.
2. **Decide where the verse corpus comes from.** Nothing in stage 3 can start until it exists.
3. **Design the forced-alignment stage**, and hand-mark ~100 word onsets so timing can finally
   be measured rather than assumed.
4. **Verify a second lecture.** Everything rests on one, and the one check we have disagreed.
5. **Decide the gitignore question**, so the tools survive.

Only then does spending on a bulk GPU pass make sense — and it should be benchmarked on the
models actually chosen.
