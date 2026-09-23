# Does Whisper support Sanskrit? (2026-09-23)

Two questions: which checkpoint "Whisper medium" actually means, and whether the widely
repeated claim that `large-v3-turbo` "natively supports Sanskrit" is true.

Three research agents, each followed by an adversarial reader. **7 of 46 claims were
rejected** — a much higher survival rate than usual, because these are facts in source code
and paper tables rather than extrapolations from benchmarks.

## The short answers

**"Whisper medium" is `openai/whisper-medium`**: 769M parameters, 24 encoder and 24 decoder
layers, width 1024, multilingual — not `medium.en`. `Systran/faster-whisper-medium` is a
straight CTranslate2 format conversion of that exact checkpoint. Moving to faster-whisper
changed the runtime and the quantisation, not the model.

**"large-v3-turbo natively supports Sanskrit" is false as it is usually meant** — and the
evidence is unusually clean.

## Sanskrit is a label, not a language

`"sa": "sanskrit"` sits at line 96 of `whisper/tokenizer.py`, one of 100 entries. Every
multilingual checkpoint shares that tokenizer, so `--language sa` is accepted by `medium`
just as it is by turbo. **Nothing about turbo added Sanskrit.** The token has been there
since 2022.

What is behind the token:

| | hours in Whisper's training data |
|---|---:|
| Sanskrit — speech recognition | **0** |
| Sanskrit — X→English translation | 195 |
| Bengali — speech recognition | **1.3** |
| Hindi — speech recognition | 12 |

The Whisper paper's Figure 11 has two panels, "Multilingual Speech Recognition (117,113
hours)" and "Translation (125,739 hours)". **Sanskrit appears only in the translation panel.**
The word "Sanskrit" occurs exactly once in the entire 28-page paper, and zero times in
Appendix D's performance tables.

So the only thing Whisper was ever taught about Sanskrit audio was **to render it as
English**. That is a language token with nothing behind it.

The consequence, measured by others: off-the-shelf Whisper scores **99.0% WER on Sanskrit** in
IndicVoices, against **22.8%** for a 130M Conformer actually trained on Sanskrit.

## Why turbo was worse than medium here, specifically

We measured turbo at 70.1% Sanskrit error against medium's 58.7% on our own reference. The
mechanism is in OpenAI's own release note. Turbo is not a distillation — it is large-v3 with
the decoder pruned from 32 layers to 4, then:

> "fine-tuned for two more epochs over the same amount of multilingual transcription data used
> for training large-v3, **i.e. excluding translation data**."

Two extra epochs on a corpus containing zero Sanskrit, having discarded the only corpus
Sanskrit ever appeared in, on a quarter-depth decoder. Turbo being worse at Sanskrit is what
that recipe predicts.

And the published evidence could never have shown it. OpenAI's turbo-vs-large-v3 comparison
covers, in their words, only "the subset of languages in the Common Voice 15 and FLEURS
datasets where **large-v3 scored a 20% error rate or lower**." Every language large-v3 was
already bad at was filtered out. OpenAI names just two degraded languages — **Thai and
Cantonese** — and the baseline for that claim is large-v2, not large-v3.

Sanskrit is excluded twice over: it is in neither FLEURS (102 languages, none of them
Sanskrit) nor Common Voice (absent at 93, 114 and 286 locales). **Our own measurement on the
Melbourne reference is, as far as the agents could find, more Sanskrit evidence than OpenAI
has ever published.**

## Chanted verse is a second problem on top

This is the sharpest finding, and it is the one that matters for this archive.

Models **already fine-tuned on Sanskrit prose** score **99–110% WER on Sanskrit chant**
(Vedavani; IndicWhisper is worst at 109.80). Over 100% means more errors than there are words.
The flagship Sanskrit corpus says why it cannot help: *"we confine our corpora to those
written only in prose (Gadya)."*

The general mechanism is well documented — the same text and same recogniser goes from **88.5%
word accuracy on speech to 12.1% on sung delivery**, because vowels stretch to fill the
metrical unit and pauses land anywhere, including inside words.

It is a domain gap rather than an impossibility: the same models drop to ~21% WER once
fine-tuned on chanted data. But all annotated Sanskrit speech in existence is roughly 400–600
hours, and almost all of it is prose.

## Retrieval is the established answer, and the numbers are not close

Three independent demonstrations that treating a known verse as **retrieval rather than
recognition** works:

| | result |
|---|---|
| Quranic verse finder | **100% verse retrieval at 2.5% false positives**, fuzzy-matching a 10.1%-WER transcript against the verse corpus |
| Gregorian chant pipeline | **24.1% CER → 3.8%**, purely by matching garbled output against a chant database |
| Open-source Quran verse ID | 85% sequence accuracy, 115 MB, 0.33 s — ASR used only for candidate retrieval, never for the final decision |

The Quranic authors explicitly propose transferring the method "to narrow ASR domains like
poetry and singing". This is the archive's case exactly.

!!! warning "A negative result that bears on the three-model idea"
    The Quran verse-ID project ran the experiment closest to our consensus plan, and it failed:
    adding an architecturally different second model **"does not recover any of the 8 samples"**
    the first failed on — *"the 'complementary errors' hypothesis didn't hold."*

    Our own measurement agrees in shape: selection across three systems reaches a **67% ceiling
    on Sanskrit** and no further. Consensus is sound for the **English spine**, where we measured
    98.4% precision. On Sanskrit and Bengali it will average confident nonsense, because the
    models share an encoder lineage and the same zero hours of relevant data.

## Two practical carry-overs

- **Report CER, not WER, for Sanskrit.** Sandhi fuses words, so "half of WER is spacing" —
  standard WER punishes boundary choices that are not errors. Our scorer's closeness rule
  already softens this, but the metric should change.
- **Build in abstention.** Say "unclear" rather than emit a plausible wrong verse. For a
  scripture archive that is the difference between a gap and a fabrication.

## What is not known

**No published work exists on recognising Sanskrit quotation code-switched inside English
speech** — which is this archive's actual task. That is an absence of literature, not evidence
either way.

## What follows

1. **Stay on `medium`, not turbo**, for the local English spine. Our measurement and the
   training-data figures agree, and now we know why.
2. **Do not expect any Whisper checkpoint to read Sanskrit.** Zero hours means zero.
3. **Build the verse index.** It is the established technique, the reported gains dwarf
   anything recognition achieves here, and it is the only approach that improves with the
   archive's own corpus of known quotations rather than with GPU spend.
4. **If a recogniser is wanted for the Sanskrit**, it must come from a different family —
   IndicConformer's Sanskrit checkpoint or IndicWhisper — not a third Whisper.
