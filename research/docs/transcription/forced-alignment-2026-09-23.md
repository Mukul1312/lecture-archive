# Giving every word a time

**Read-along playback needs to know when each word was said, and the recogniser the archive
depends on for Bengali does not say.** `flex` returns 6,175 words in one string with no timing
anywhere. Sarvam is the same: 263 rows, every timestamp null, each "word" a whole utterance. Two
of the nine systems cannot drive a read-along page at all.

Forced alignment answers the question they leave open. The transcript is treated as known and
only the timing is searched for, which is a far easier problem than recognition — and the reason
it works here is that **the model never has to be right about what was said.** That is what
makes it usable on 1980s cassette audio that defeats recognition, and on Sanskrit that Whisper
has zero hours of training data for.

## The result

Measured across all 512 verified cues, 6,365 words, in 34 minutes on CPU:

| | words | median error | within 0.1s | within 0.5s |
|---|---:|---:|---:|---:|
| **English** vs ElevenLabs | 4,985 | **0.03s** | 86% | 89% |
| **English** vs Whisper | 4,649 | 0.07s | 62% | 87% |
| **English** vs Deepgram | 4,341 | 0.08s | 62% | 89% |
| **Sanskrit** vs ElevenLabs | 77 | **0.02s** | 90% | 91% |
| **Sanskrit** vs Whisper | 40 | 0.06s | 68% | 88% |
| **Bengali** vs ElevenLabs | 10 | 0.05s | 70% | 70% |

**These are agreement figures, not accuracy.** There are no hand-marked onsets for this lecture,
so nothing here establishes that the aligner is correct to any tolerance. What it can establish
is bounded, and the control is what makes it readable:

| the control — no aligner involved | words | median | within 0.1s |
|---|---:|---:|---:|
| Whisper vs Deepgram | 4,576 | 0.06s | 69% |
| Whisper vs ElevenLabs | 4,973 | 0.06s | 72% |
| Deepgram vs ElevenLabs | 4,739 | 0.06s | 74% |

Three independent commercial systems agree with each other to a median 0.06s. **The aligner sits
inside that spread**, and against ElevenLabs it is closer than the systems manage with one
another. A forced aligner that agreed with none of them would be very unlikely to be right; one
that agrees with all three is very unlikely to be badly wrong.

The honest next step is unchanged: **~100 hand-marked word onsets**, after which this becomes a
statement about accuracy rather than about company.

## Why MMS_FA

torchaudio's `MMS_FA` — wav2vec2 fine-tuned across 1,100+ languages onto **one romanised
alphabet of 29 symbols**. That alphabet is the whole reason it suits this archive: the reference
is already romanised IAST, so English, Sanskrit and Bengali go through a single model, and there
is no per-language aligner to hunt for languages that have none.

It is also the whole difficulty. Twenty-nine symbols, against a transcript carrying diacritics,
hyphens, digits and avagrahas. **Nothing fails loudly when that mapping is wrong** — a dropped
symbol just slides every later word, and the page highlights the wrong one for the rest of the
lecture.

⚠️ **Licence: CC-BY-NC 4.0 — non-commercial.** This is the model's weights, a separate question
from the text corpora. Fine for a devotional archive; a constraint if that ever changes.

## Four traps, all silent

**`-` is the blank symbol.** In MMS_FA's table `-` is index 0, which is CTC's blank. A hyphen in
`aṅghri-mūlaṁ` mapped naively becomes a target that the algorithm forbids. Hyphens are deleted
by joining, so the word stays one highlight unit.

**The apostrophe is two different things.** Inside a word it is a contraction the model expects
to see. At an edge it is an avagraha marking an elided vowel (`prapanno 'smy`) or a possessive —
written, not spoken — and aligning it spends audio belonging to the neighbouring letter. Kept
internally, stripped at edges. Curly and straight fold together first: this reference uses U+2019
for all four avagrahas and U+0027 for all 122 contractions, but that is its habit, not a rule.

**Not everything written was spoken.** Forced alignment cannot decline a word, so anything left
in the text is found anyway — in audio belonging to its neighbours, which are then placed wrongly
too. 43 of 512 cues open with a speaker label (`Gour Govinda Swami:`); with it left in, cue 41's
mean confidence was 0.017. Melbourne has no bracketed editorial inserts, but **the next lecture
in the queue has 28 of them carrying 60 phantom words** — `[verse]`, `[?]`, `[Śrīmad Bhāgavatam
5.5.8]`, and bracketed words an editor supplied to finish a sentence.

**The model's output is already normalised.** `get_model()` log-softmaxes over the 28 real
symbols and appends the star at probability 1, so `exp()` sums to **exactly 2, not 1**. It looks
like an unnormalised score and invites a `log_softmax` that must not be applied. Applying it
subtracts log 2 from every symbol at every frame — a uniform offset, so **every timestamp is
untouched and every confidence score is halved.** English read 0.19 where it should read 0.38. A
timing bug announces itself by sliding the highlight; this one merely made the aligner look less
certain than it was.

## What the measurement itself got wrong first

The first Bengali figure was a median error of 0.32s against ElevenLabs, and 3.47s against
Whisper. Both were artifacts.

`ei` and `nāma` are two letters long and recur throughout a Bengali song, so the sequence matcher
paired our word with an occurrence **twenty-five seconds away** and reported a twenty-five second
error. The aligner had placed those words inside their own cues, correctly. Requiring a matched
pair to fall within the same cue before counting it — a claim about identity, not about agreement
— took Bengali against ElevenLabs from 0.32s to **0.05s**. English barely moved, which is how one
can tell the filter removes mistakes rather than inconvenient data.

Whisper's Bengali figure stays poor at 0.70s over 5 words, and that is expected rather than
alarming: Whisper gets 84% of the Bengali wrong, so its timestamps there belong to words it
misheard.

## The known limitation

The disagreement tail sits at cue edges, cleanly and monotonically:

| distance from the nearer cue edge | words | over 1s out |
|---|---:|---:|
| 0 words (the edge word itself) | 792 | **20%** |
| 1 word | 792 | 15% |
| 2 words | 768 | 12% |
| 3 words | 733 | 8% |
| 4 or more | 2,117 | **6%** |

The aligner cannot place a word outside the window it was given, and a caption boundary is where
an editor decided one line should yield to the next — not where a word begins. Padding of 0.5s
helps; it does not remove the effect.

## The cue-less path, and why flex is not the hard case

Aligning a 6,175-word blob against seventy minutes in one pass does not fit: the Viterbi
backtrack matrix is frames × letters, about **12 GB** at flex's measured density of 7.25
romanised characters per second. Torch raises `bad allocation` and stops.

It does not have to. **flex's timestamps are not missing — they are discarded.**
`transcribe_long` cuts audio at pauses into pieces of at most thirty seconds, decodes each one
separately, and ends with `" ".join(out)` — knowing exactly which piece produced which words and
throwing it away. `scripts/flex_timed.py` keeps it, reusing flex's own `split_on_silence` and
decode so the text is the text the bake-off scored rather than a near-miss.

That turns the hard problem into an easy one. A ≤30-second piece whose words are already known
aligns in under a second, and **no chunk boundary is ever guessed.**

**Measured on a five-minute slice:** 12 segments, **470 words timed**, decode 280s and alignment
111s. Every invariant holds — no word starts before the one before it, none ends before it
starts, none falls outside the audio, and the segments tile contiguously (0–25.1, 25.1–49.7,
49.7–74.8…). Mean confidence 0.479, with the chanted verse scoring highest (`prapanna` 0.96).
A full lecture is roughly 40 minutes of decoding plus 25 of alignment.

Those invariants are now checked on every run by `problems()`, on the finished result rather than
inside any one path: one pass, cue by cue, and segment-by-segment-with-offsets each have their
own way of going wrong and the same way of looking fine.

## What is built

| | |
|---|---|
| `scripts/forced_align.py` | text → CTC targets, span recovery, seconds, chunk planning, long-audio scoring |
| `scripts/align_lecture.py` | times a verified cue transcript end to end |
| `scripts/timing_check.py` | agreement against the timestamped systems, with the control |
| `scripts/flex_timed.py` | flex decoded with its segment boundaries kept, then aligned |

57 tests, none needing the 1.2 GB model.

## Still open

1. **~100 hand-marked word onsets**, so this becomes accuracy rather than agreement.
2. **A star token cannot currently be expressed** — `romanise('*')` returns nothing by design.
   The cue-less path needs it as the defence against a recogniser's omissions.
3. **Word-onset convention is unrecorded.** MMS_FA has no word-separator token, so the silence
   between words belongs to neither. Whether the highlight begins at the first strongly-scoring
   frame or reaches back into the preceding gap is undecided, and published figures swing several
   fold on exactly this choice.
4. **flex's transcript is ASR output, not a verified reference.** Where flex misheard a word,
   forced alignment will confidently place that wrong word on real audio, and the span will look
   perfectly monotonic and well-scored. Alignment confidence is not transcription confidence.
