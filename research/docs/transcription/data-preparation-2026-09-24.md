# Preparing found audio to measure recognisers on

**The archive's lectures were never made to be a test set.** The transcripts are published prose
— no timings, no diarisation, edited for reading, some omitting questioner turns, six stopping
before the recording does. Everything between "78 downloaded lectures" and "a number you can
make a decision on" is data preparation, and most of it was invisible until it was looked for.

This page records what was measured, what published practice says, and — the larger part — what
published practice says that is **wrong for this archive**.

## The finding that matters most

**A known-correct alignment scores *worse* than the suspect ones.**

| | mean alignment confidence |
|---|---:|
| Melbourne, verified cue by cue against the audio | **0.2134** |
| the archive, 23 published transcripts | **0.3575** |

**21 of 23 archive lectures score above the one alignment we know is right.** Any quality gate
set anywhere above 0.21 would reject the verified reference and keep the doubtful ones.

So `alignment_confidence`, added to the manifest because it was a signal being thrown away, is
**not a quality threshold and must not be used as one.** It measures how cleanly the audio
matched the letters it was told to find — which varies with the recording, the speaker's pace and
the amount of Sanskrit, not with whether the transcript is any good.

This is the concrete form of a general trap: *a number that ranks things is not thereby a number
that grades them.* It needed a calibration point — a correct alignment — and nobody had asked
what one scores.

## What was measured

### Audio: all 78, not a guess

| | |
|---|---|
| format | 44.1 kHz LAME3.100 VBR, 100–177 kbps |
| channels | **75 stereo, 3 mono** |
| loudness | −27.1 to −17.1 dB RMS, median −23.4 |
| clipping | **none** — peak −1.30 dB, flat factor 0.000000 |
| encoder delay | 1105 samples, declared identically in every file and honoured by both decoders |

⚠️ `scripts/analyze_source.py` does **not** measure this archive. It globs `data/hi/lectures/` —
the Hindi clone corpus — and its "56 kbps MP3" docstring describes those files. Any claim about
archive audio quality sourced from it is about a different corpus.

### The stereo downmix is not free

Every stage currently does a blind `.mean(axis=1)`. Measured across the stereo files:

- inter-channel correlation runs **0.37 to 1.00**
- **31 of 75 lose more than 3 dB of the 2–5 kHz band** to the sum; 5 lose more than 8 dB
- 23 have an inter-channel lag of ≥5 samples; three have **negative** correlation

2–5 kHz is the consonant band. One lecture is literally the same signal twice, where the downmix
costs nothing; another has genuinely different channels, where it costs real information.

### Loudness changes recognition, and only for some models

One clip, four loudnesses, same 89 reference words:

| condition | words heard | English error |
|---|---:|---:|
| −10 dB | 91 | 45.6% |
| as published | 72 | 32.2% |
| +10 dB | 93 | **8.9%** |
| `loudnorm` | 27 | 72.2% |

**This is not a settled result and must not be quoted as one.** 89 words, one clip, one lecture.
Two known faults sit in it: the `loudnorm` row is roughly **9 dB of attenuation in dynamic mode**,
not the clean 3 dB it was labelled; and the "+10 dB clips" premise was false, because the masters
are not near clipping at all.

What it does establish is that **loudness is not a no-op**, which was the question. And the
sharper form of it: **MMS_FA is gain-invariant and faster-whisper is not.** Audio preparation
therefore has to be *versioned as part of the comparison definition*, or "which recogniser is
best" partly measures "which recogniser liked the preparation we happened to apply".

### Decoders agree, with three exceptions

Durations match to the millisecond between libsndfile and ffmpeg across every file checked, and
ffmpeg input-seek and output-seek are sample-identical on these VBR MP3s. Encoder-delay offsets
and seek inaccuracy are **not** live defects here.

The exception is real though: the aligner reads through libsndfile, the recognisers through
ffmpeg/PyAV, and `align_archive.read_audio` **silently switches to ffmpeg for damaged files**.
Three of 78 lectures disagree about the time origin, and span-restricted scoring grades by word
midpoint — so where the clocks differ, the scorer compares the right words against the wrong
audio.

## What published practice recommends, and whether it fits

### Worth taking

**Islands of confidence** (LibriSpeech). A reference word is trustworthy only inside an exact
match with an independent hypothesis, and segment boundaries are allowed only at silences inside
such an island. This is the direct upgrade to scoreable spans: our break rule is *acoustic*
(>10 s silence), the island rule is *textual*, and a span whose first and last words are
corroborated by a second source is trustworthy at its edges in a way a silence gap never
establishes.

**Boundary agreement** (LIUM TED, SPGISpeech 2.0). Keep a segment only if an independent source
agrees on its first and last N words. SPGISpeech requires five under two different aligners. This
attacks a failure we actually hit: the loudness experiment took "the first 1.9% of a span's
words" and got 71 instead of the right 89, and a boundary-corroboration rule would have refused
the clip rather than scored it.

**A duration floor.** `min_words_per_span: 5` has no duration bound — it would admit a 2-second
span. MLS guarantees 10–20 s segments, and the manifest already carries the times needed.

**Lightly supervised alignment** (Kaldi, TED-LIUM 3, GigaSpeech). Decode with a text-biased LM
and edit-align the result, rather than forcing text onto audio. TED-LIUM 3 raised coverage from
58.9% to 83.0% of audio this way. The Kaldi machinery is wrong here (GMM/HMM, lexicon and G2P for
three languages, on Windows) but the transferable half is cheap: Smith-Waterman one hypothesis
we are *not* grading against the published transcript, and keep the per-word edit labels as a
text-side trust signal. Forced alignment can absorb disagreement but cannot report it.

### Wrong for this archive

!!! danger "Accept/reject thresholds that delete material"
    VoxPopuli drops CER>20%, MLS WER>40%, People's Speech CER>50%, YODAS CTC<2.0. Two problems,
    both fatal here. All of them filter **training** data with the same model family they then
    train — circular, and for a *benchmark* the gatekeeper must be a system you are not grading.
    And discarding audio from a devotional archive of a departed teacher is a loss, not a tidy-up.

!!! danger "Denoising before recognition"
    The likeliest mistake to actually get made, because `scripts/youtube_enhance/` already has a
    working DeepFilterNet stage. It optimises what a **devotee** hears. This pipeline optimises
    what a **recogniser** hears, and the literature is clear that enhancement can hurt ASR.

!!! danger "Whisper's `BasicTextNormalizer` on the Indic track"
    It replaces Mark-class characters with spaces. `has_diacritics()` is what decides **which
    track a word is scored on**, so this would not merely inflate a number — it would silently
    move words between languages.

Also rejected, with reasons: **declipping** (nothing is clipped), **SCTK/MAPSSWE** (wants sclite
on Windows to make a claim the paired bootstrap already makes), **e-WER** (needs decoder
internals ElevenLabs and Sarvam do not expose; its 16.9% RMSE is wider than the entire spread
between best and worst), **indic-nlp-library** (there is no Devanagari or Bengali script in these
references to normalise), **SN-WER** (its own scope section excludes romanised-reference cases),
**inaSpeechSegmenter** (a European broadcast model, for a question already abandoned on
evidence), and **bootstrapping an in-domain acoustic model** (a model fine-tuned on this speaker
stops being an independent judge).

## What was built from it

**Confidence intervals, by resampling lectures.** `combine()` was building per-span totals and
discarding what was needed to say how sure any of it is. Resampling is over **lectures, not
words** — words in one lecture share a speaker, a room, a tape and a transcriber, so treating
81,630 of them as independent reports an interval far tighter than the evidence supports. The
honest n is **23 lectures**. Comparisons are paired, and two systems are called separated only
when the whole interval sits on one side of zero.

This will probably make at least one published ordering indefensible. That is the point.

## Still open

1. **Re-run the loudness experiment relabelled**, as a per-file linear gain rather than
   `loudnorm`'s dynamic processing.
2. **Record channel facts per lecture** and decide whether picking a channel beats downmixing.
3. **One decoder on both sides**, or a recorded offset where they differ.
4. **Measure the reference's own error rate** — ~100 spans transcribed verbatim by a devotee.
   Zero CPU, and it puts a floor under every figure this project reports, which are all currently
   *(system error + reference error)* with no way to separate them.
5. **A duration floor on spans**, and **boundary corroboration** from a second source.
