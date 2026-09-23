# The method, and what is still missing (2026-09-23)

Everything measured this session, assembled into one pipeline — and an honest list of what
has not been built, not been measured, or not been thought about. The second list is longer
than it looks, and two items on it are structural rather than incremental.

## The method

Five stages. Each line is measured on the Melbourne reference unless marked otherwise.

| # | stage | what it does | evidence |
|---|---|---|---|
| 1 | **Bulk decode** | three local models over the whole corpus on a rented GPU | ~$33, ~5 days on one GPU — *figure not yet benchmarked for these models* |
| 2 | **English spine** | keep the best system, overrule it where another is confident | English error **17.8% → 15.1%**, the best local result measured |
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

    What the next attempt needs is not better voting but **a confidence signal**, to separate
    "two systems agree and are right" from "two agree and are wrong".

!!! success "1b. Confidence works — English 17.8% → 15.1%"
    Whisper emits a per-word probability that was sitting unused in the decode output. Checked
    against the verified reference before building anything on it:

    | Whisper confidence | words | correct |
    |---|---:|---:|
    | lowest quarter | 1,558 | **49.6%** |
    | 0.80–0.90 | 541 | 94.1% |
    | highest quarter | 1,558 | **98.5%** |

    Using it to overrule the best single local system where the challenger is confident
    (`overrule_where_confident`, threshold 0.50):

    | | WER | English | Sanskrit |
    |---|---:|---:|---:|
    | **confidence-gated** | **23.7%** | **15.1%** | 48.4% |
    | flex en-native alone | 24.2% | 17.8% | 41.9% |
    | gap-filling fusion | 24.7% | 17.1% | 41.9% |

    Best local English measured, by two points. The threshold was swept with the lecture split
    in half and the gain holds on the unseen half (77.6% → 78.7% word accuracy), though smaller
    than on the fitted half — which is what one lecture can honestly support. Sanskrit gets
    worse, because Whisper is confident *and* wrong there; that is the half retrieval owns.

!!! failure "1c. Deepgram cannot be the second confidence source"
    It has the best-evidenced per-word confidence and runs at 517× real time, so it looked like
    the obvious addition. The economics kill it: a confidence source must run on **every**
    lecture, forever.

    | | across the SSGGSM corpus |
    |---|---:|
    | Deepgram as a *confidence* source | **$904** |
    | ElevenLabs as a *transcriber* | $759 |

    Paying more for a signal about words than for better words is incoherent — and it would
    turn a local pipeline into a permanent vendor dependency, shipping 3,450 hours to a service
    that trains on submitted audio unless opted out on every request. The one-lecture bake-off
    hid this, because $0.29 for 66 minutes looks free.

    **The local sources instead:** Whisper's `p` (working now); **flex's own token scores** —
    it decodes through HuggingFace `generate()`, so `output_scores=True` yields per-token
    log-probabilities for a small wrapper change and no per-lecture cost; and the **forced
    aligner**, which now exists and whose per-word acoustic score covers every word uniformly —
    including words from a system with no native confidence of its own. That score is real but
    unproven as a *correctness* signal: it says how cleanly the audio matched the letters it was
    told to find, not whether those were the right letters.

!!! success "2. The timings exist now — built, measured, and honest about what it proves"
    **This was the largest structural gap and it is closed.** Full write-up:
    [Giving every word a time](forced-alignment-2026-09-23.md).

    It was worse than the page originally said. flex emits no timestamps, and **neither does
    Sarvam** — 263 rows, every time null, each "word" a whole utterance. Two of the nine systems
    could not drive a read-along page, not one.

    `scripts/forced_align.py` takes the known text and the audio and finds the one path through
    the frames that spells it. All 512 verified cues, **6,365 words, 34 minutes on CPU, no
    failures**. Against the systems that do emit times, median onset difference:

    | | English | Sanskrit | Bengali |
    |---|---:|---:|---:|
    | vs ElevenLabs | **0.03s** | **0.02s** | 0.05s |
    | vs Whisper | 0.07s | 0.06s | 0.70s |
    | **the control: those systems vs EACH OTHER** | **0.06s** | | |

    **The control is what makes the number readable.** Three commercial systems agree with one
    another to 0.06s; the aligner sits inside that spread and beats it against ElevenLabs.

    It also survives the long-input problem, by not having one. **flex's timings are discarded,
    not missing** — `transcribe_long` cuts at pauses into ≤30s pieces, decodes each, then
    `" ".join(out)` throws the boundaries away. Keeping them turns a one-pass alignment needing
    a ~12 GB backtrack matrix into per-piece alignments where **no chunk boundary is ever
    guessed**. Proved on a five-minute slice: 470 words, every invariant holding.

    **What is still open, and it is the original point.** These are *agreement* figures, not
    accuracy — nothing here shows the aligner is correct to a tolerance, only that it keeps
    company with three independent systems. **The ~100 hand-marked onsets still settle it**, and
    remain the honest next step. Two further limits: the disagreement tail sits at cue edges
    (20% of edge words over 1s out, against 6% deep inside a cue), and **alignment confidence is
    not transcription confidence** — where a recogniser misheard, the span will look perfectly
    monotonic and well-scored while pointing at the wrong audio.

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

1. **Extract flex's token scores** (`output_scores=True` through its HuggingFace `generate()`
   call), so two of the three local systems carry confidence rather than one. Whisper's is
   already working and bought two points of English.
2. **Decide where the verse corpus comes from.** Nothing in stage 3 can start until it exists.
3. **Hand-mark ~100 word onsets.** The forced-alignment stage is built and measured; what it
   has is agreement with other systems, not accuracy. This is the one measurement that turns it
   into a guarantee — and it is cheap.
4. **Verify a second lecture.** Everything rests on one, and the one check we have disagreed.
5. **Decide the gitignore question**, so the tools survive.

Only then does spending on a bulk GPU pass make sense — and it should be benchmarked on the
models actually chosen.
