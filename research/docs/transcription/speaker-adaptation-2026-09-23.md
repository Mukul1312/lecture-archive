# Should we fine-tune a model on his voice? (2026-09-23)

The corpus is 3,766 lectures by **one speaker**, which is the textbook case for speaker
adaptation. The obvious objection is that there is exactly **one verified transcript** to
train on. This page settles both questions: whether the data problem is real, and whether
fine-tuning is the right thing to do even if it were solved.

Method: five research agents on separate dimensions, each followed by an adversarial reader
told to find claims that would not survive contact with this archive. **They rejected 40 of
79 claims.** Only what survived is reported here. The measurements on our own corpus were
made directly and are marked as ours.

## The answer

**Not yet, and not the way the question is usually asked.** Three measured failure modes make
fine-tuning actively dangerous for *this* archive, and one unrelated finding is worth more
than fine-tuning would be.

---

## 1. The data problem is smaller than it looks — measured here

If all three local systems write the same thing at a word, that consensus is **correct 98.4%
of the time** (99.2% across all nine). That is not a guess; it is measured against the
verified reference.

| | |
|---|---:|
| words where Whisper, flex en-native and flex bn-mixed agree | 4,492 (67.9%) |
| of those, consensus is correct | **98.4%** |
| unbroken stretches of 10+ agreed words, from one lecture | 161 |
| audio that yields | 27 minutes (41%) |
| **scaled across 3,766 lectures** | **~1,400 hours** |

The literature says this filtering is exactly what makes pseudo-labelling work: Distil-Whisper
measured **13.4% WER on unfiltered pseudo-labels against 11.4% filtered**, discarding 45.4% of
its data at a 10% threshold. Our consensus rule is that filter, and it is already built.

### But consensus captures the wrong half — also measured here

| | in the lecture | captured as training data |
|---|---:|---:|
| plain English | 4,317 | **52.7%** |
| mixed Sanskrit | 1,884 | 31.7% |
| verse or chant | 412 | **1.7%** |
| Sanskrit words | 676 | **5.0%** |

Agreement is highest exactly where the models are already right. Training on it would improve
the easy majority, leave the hard minority untouched, and report a corpus-average win. Verse
would be almost entirely absent.

---

## 2. Three failure modes that matter more than accuracy

These are the surviving claims, and each is measured in a published source.

!!! danger "Full fine-tuning destroys the languages you are not tuning on"
    Fine-tuning Whisper for code-switching took **Korean from 15.96% to 436% WER**,
    LibriSpeech English from 2.90% to 13.15%, and Aishell Chinese from 9.38% to 15.82% —
    while **LoRA and prompt tuning left all three at baseline**.

    For an archive whose speaker quotes Sanskrit and Bengali inside English sentences, this is
    disqualifying. A model that has lost its Sanskrit does not emit a gap; it emits confident
    English words. That converts a visible defect into an invisible fabrication. **Hard rule:
    LoRA or prompt tuning only, never full fine-tuning, and a held-out non-English probe in
    every evaluation.**

!!! danger "LoRA hallucinates text into silence"
    Described by the challenger as the most archive-relevant finding of the whole set:
    LoRA-induced hallucination is **memorisation-based — the decoder emits high-frequency
    training phrases during silence.** These are 1980s cassette recordings full of pauses,
    tape hiss and room tone. The failure mode lands precisely on our material.

!!! danger "Fine-tuning on short clips destroys long-form alignment"
    Training on sentence-level clips produced the **highest short-clip BLEU of any
    configuration (77.38) together with SubER above 51 on long-form audio.** The model looks
    better on your test set and worse on the actual 90-minute lecture.

    The archive's deliverable is read-while-listening. **Alignment is the product.** A
    WER-only evaluation cannot see this failure at all.

And a fourth, structural: **Whisper is non-verbatim by design** — it omits disfluencies,
fillers, stutters and false starts. CrisperWhisper needed a ~10,000-hour tokenizer
readaptation stage before verbatim output was even learnable. Fine-tuning toward any smoothed
target makes WER fall while faithfulness falls with it. In this corpus repetition is content.

---

## 3. What this does to the cheaper alternatives

Two findings explain results we already had and could not account for.

**Why the Whisper glossary prompt made things worse.** Prompt-style biasing buys rare-word
accuracy and pays for it on ordinary words: rare-word error 23.7% → 18.0%, but **ordinary-word
error rose 9.1% → 11.6%, a 27% relative degradation** — worst next to switch points, which is
where our errors concentrate. Our measured result (WER got worse with a glossary prompt) is
the expected result.

**Why ElevenLabs' keyterms behaved differently.** faster-whisper's `hotwords` is **not**
decoder-level biasing — it is text pasted into the previous-text prompt slot on every
30-second window, capped at half the window. The method that does work is a trie inside beam
search (test-clean 2.81 → 2.31 WER, biased words 9.86 → 5.66, ordinary words untouched at
1.94 → 1.90) — **but no implementation has been released.**

**n-gram shallow fusion is high variance**: on Spanish it moved one test set +25% and another
−63%, depending on config. Not a safe default.

---

## 4. The finding worth more than fine-tuning

Independent of adaptation entirely:

> **The whole 4,708-hour archive can be transcribed on a rented GPU for $25–90, in about five
> hours of wall-clock.**

Verified against provider benchmarks (large-v3-turbo int8: RTX A5000 at 38× real time and
$0.0071 per audio-hour; L40S at 58×). The current plan is ~70 days of laptop time. And a
fine-tuned or base model **runs afterwards exactly where the current one runs** — CTranslate2
converts fine-tuned checkpoints, so adoption implies no ongoing GPU spend.

Cost is not the constraint anywhere in this problem. The real cost of the labelled-data route
is **human**: a comparable study needed ten native speakers over 25 working days. Producing
ten verbatim-verified hours here is 60–100 volunteer hours.

---

## What to do

1. **Rent a GPU for a bulk pass now.** $25–90 and five hours against 70 laptop-days. This is
   independent of every other decision on this page.
2. **Do not fine-tune yet.** Hallucination into silence, segmentation collapse and
   non-verbatim drift each attack something this archive cannot trade away, and the pseudo-
   labels we can generate cover the audio the models already handle.
3. **If adaptation is attempted later:** LoRA only; train on stitched long-form audio, never
   short clips; keep Sanskrit and Bengali audio in the mix; hold out a non-English probe; and
   measure segmentation (SubER) alongside WER, because WER will not show the failure that
   matters.
4. **Build the verse index and glossary first.** They fix the 1.7% consensus cannot reach, and
   no amount of adaptation will.

## What is still unknown

There is **no published measurement of fine-tuning gain for a single speaker whose baseline is
already in the 10–20% WER band.** Every single-speaker result found starts from a baseline
above 100% — dysarthric speech, low-resource languages. The direction is confident; the
magnitude is not. Anyone who tells you what this would buy on Gurudeva's audio is guessing.
