# Melbourne reference: what the eight purposes measured (2026-09-22)

The steward gave the Melbourne reference sitting eight purposes. This records what each
one measured, with every number checked by an independent verifier. Where the verifier
disputed a number or a conclusion, the corrected version is the one given here.

Source: workflow run `wf_1d5e654d-7eb` (script `.agents/workflows/melbourne-eight-point-measurements.js`):
four measuring agents and one adversarial verifier that recomputed every headline number
from the raw files. Full structured result:
`data/reference/analysis/workflow-result-wf_1d5e654d-7eb.json`. Analysis scripts and
intermediate data: `data/reference/analysis/` (gitignored, like the rest of `data/`).

**Read this first:** every finding rests on **one lecture**, one tape, one speaker. It was
chosen because a verbatim transcript existed, not at random. Anything described as a
calibration here is fitted and tested on that same lecture.

## Summary

1. **The accuracy scorer had a bug, now fixed.** It deleted the heard words of 16 cues
   (the Bengali song among them) while still scoring their reference words, so all six
   configurations looked worse than they are. Corrected: medium-beam1 is **19.5% English,
   58.7% Sanskrit, WER 27.7%**. The ranking and the choice of medium are unchanged.
2. **Correcting a Whisper transcript is close to retranscribing it.** medium-beam1 leaves
   about **690 places to stop and fix** in this 69-minute lecture: one every 9.4 words, in
   86% of cues. The reference sitting needed 18.
3. **Nobody can yet say how many hours the corpus would take to correct.** The two inputs
   that set it (seconds per fix, and listening speed while correcting) were not measurable
   from a sitting that verified a nearly clean transcript. One hard floor holds regardless:
   listening to the whole corpus once takes at least as long as the corpus plays, about
   **3,450 hours** if the average lecture is 55 minutes.
4. **One warning signal works for wrong words:** the share of words Whisper is unsure of
   (probability below 0.70) in each 15-second window. Listening to the worst-ranked 20% of
   a lecture finds **38% of the wrongly heard words**. Nothing tested flags **dropped
   words**, which are **41% of all errors** and the largest single error class.
5. **Word timings from different models agree closely**, with no drift over 70 minutes.
   But there is no ground truth yet, so this is agreement, not accuracy.
6. **A glossary pass cannot fix Sanskrit.** The glossary already contains almost every
   Sanskrit word. The problem is choosing the right entry. The robust gain is about 2
   points, and its failure mode is text that looks right and is wrong.
7. **The single most valuable next step is one timed correction sitting on a different
   lecture.** It would measure seconds per fix and listening speed (point 3), test the
   warning signal on a lecture it wasn't fitted to (point 5), try the real correction
   workflow (point 7), and give a second reference (point 8).

## The scorer bug

`scripts/transcript_accuracy.py` leaves out heard words inside stretches that the
re-timing marked as "spoken but never subtitled". Those stretches are heard speech that
no *matched* cue covered. But 16 of the 79 cues the re-timing could not match had their
times interpolated into those same stretches. Their heard words were dropped while their
reference words stayed, so every word in those cues counted as missing.

The fix keeps any heard word that falls inside a cue's own time range
(`load_hypothesis(..., covered=...)`, test
`test_heard_words_inside_a_cue_are_scored_even_within_an_unsubtitled_span`). Two
independent repairs agree: the verifier's own restoration gave 19.53% English, 58.88%
Sanskrit and 27.76% WER for medium-beam1. The fixed scorer gives 19.5%, 58.7% and 27.7%.

| configuration | English | Sanskrit | WER | missing words | wall | speed |
|---|---:|---:|---:|---:|---:|---:|
| `small-beam1` | 24.9% | 67.8% | 34.3% | 942 | 17.5 min | 4.00x |
| `small-beam1-prompt` | 24.8% | 66.9% | 34.4% | 916 | 18.5 min | 3.77x |
| `small-beam5` | 23.1% | 64.9% | 32.4% | 927 | 23.1 min | 3.03x |
| **`medium-beam1`** | **19.5%** | **58.7%** | **27.7%** | **768** | 34.2 min | 2.04x |
| `turbo-beam1` | 19.1% | 70.1% | 28.4% | 846 | 36.6 min | 1.91x |
| `turbo-beam1-prompt` | 19.7% | 67.6% | 29.0% | 835 | 32.5 min | 2.15x |

The earlier scores are kept in `data/reference/analysis/accuracy-before-scorer-fix/`.

## Point by point

### 1. Measure accuracy — done, with the correction above

His speaking rate matches his own estimate: **94.3 words a minute, 5,656 an hour** over
the whole span. That rises to 104.8 while he is actually speaking, since 7.5% of the span
is pauses. The span is 68.9 minutes of cues inside 69.8 minutes of audio.

The English track is not purely English. `has_diacritics()` leaves Sanskrit and Bengali
written without diacritics in the English count (*hare* 17 times, *vraja*, *jakhona*,
*baba*). So the English error rate partly measures non-English words. By how much has not
been measured.

### 2. Choose the model by numbers — done for size and prompt; batching and silence skipping untested

`medium-beam1` stands. It ties turbo on English (19.5% against 19.1%, inside the ~0.4-point
run-to-run noise) and beats it clearly on Sanskrit (58.7% against 70.1%).

Two things the verifier raised:

- **Counted by fixes rather than words, turbo looks better** (646 fixes against 688), but
  that difference is not settled. The 95% interval for medium minus turbo is -2 to +87
  fixes on this lecture. turbo is also slower. Neither model can be called cheaper to
  correct on one lecture.
- **Run times come from single runs.** The six configurations ran one after another in
  one process, never at the same time. One small overlap is known: a one-minute
  timing-polish job and a report dry run ran during `small-beam1-prompt`.

**Still untested:** batching (the main lever on machine time), silence skipping off, and
`medium-beam5`. Silence skipping was on for all six runs, and **dropped words are the
largest error class (768 of ~1,850 with medium)**, so turning it off is the most
promising run left.

### 3. Predict the correction workload — the job is measured; the hours are not

A fix is counted at every point where someone has to stop and type. Adjacent wrong words
make one fix, not several. For medium-beam1:

- **About 690 fixes in this lecture, roughly 600 per hour of audio**: one every 9.4 words,
  touching about 425 of 496 scorable cues (424 or 425, depending on
  which cue a pure insertion is assigned to). Only 71 cues are word-perfect.
- **Half the fixes are one word** (329 of 688). The median is 2 words. The 14 largest
  (over 10 words each) hold 16% of the retyping.
- **Few fixes are purely Sanskrit** (30 of 688). But verse cues hold 17% of the words to
  retype.
- **Choosing medium over small removes about 6% of fixes** (732 to 688), even though it
  removes 18% of wrong *words*. Medium mostly makes existing errors smaller instead of
  removing them.
- **Against the sitting he did:** 688 fixes against the 18 in his verified sitting (38x),
  or 425 cues needing work against 17 (25x). An earlier figure of "40.5x" divided fixes by
  cues and was wrong.

**What cannot be said yet: the corpus total.** An earlier projection of 10,800–21,300 hours
is a grid of assumptions, not a range around a measured value. Seconds per fix was
unmeasurable from his sitting (6 ± 29 seconds on 17 fixes). His listening speed came from
*verifying* a transcript with 3.3% of cues wrong, not from correcting one with 86% wrong.
He sometimes covered audio at real time or faster, which correcting 690 errors will not
allow.

Two numbers do hold:

- **Listening to the whole corpus once takes at least as long as the corpus plays: about
  3,450 hours at an assumed 55-minute average.** That is before a single fix. At 2 hours
  a day it is about 4.7 years of listening alone. A policy of correcting every lecture
  before publishing it has to be judged against that floor.
- **The average lecture length is still a guess.** Measuring real durations from archive.org
  would replace the 55 minutes.

### 4. Test the Sanskrit glossary — answered: the prompt does nothing, and a correction pass barely helps

- **The glossary prompt** had no effect on `small` and traded English for Sanskrit on
  turbo. Both changes were within noise.
- **The "25–61% coverage" claim** was not two definitions mixed together. It is one
  definition applied to two lists: 110 curated terms, and all 5,421 candidates. The 61% is
  inflated by English rows (e.g. *nasty* counting as *nāsty*) and by counting a compound as
  covered when any one part is listed.
- **Coverage is not the problem.** The by-name list has an acceptable spelling for 97.5% of
  Sanskrit occurrences. The problem is picking the right one. Whisper's garbles usually
  land on a different valid word (*suta*, *indra*, *lobha*), so the best glossary match is
  the right word in at most 13 of 70 cases.
- **A post-hoc glossary pass is not worth building as an automatic fix.** The only setting
  that held up on all six transcripts improves medium from 61.4% to 59.0% (measured before
  the scorer fix). Its failure mode is text that looks right but is wrong: *baba* became
  *bhava* 6 times, and *Mārkaṇḍeya* became *makhan deya*. At most it could offer
  suggestions on low-confidence words (below 0.5), never silent rewrites.
- **The glossary itself needs cleaning.** Its Sanskrit rows contain English words mangled
  by legacy fonts (*yyou*, *tthe*, *iit*, *aall*). Unguarded, they would rewrite "you" 260
  times.
- **The Sanskrit score is too lenient.** 39 of the 169 words credited as recognisable
  romanisations are actually a different word (*aham* heard as *artham*). Under a
  same-word rule medium's Sanskrit baseline was 67.2%, not 61.4% (before the fix).
- **Some Sanskrit is never heard at all.** The lexicon agent put this at 24.4%, but that
  figure was inflated by the scorer bug. The verifier puts it at 9–17%. No text pass can
  recover it. Only decoding can, which is another reason to test silence skipping off.

### 5. Point the steward to the right places — one signal works, and only for half the errors

- **What works:** cut each lecture into 15-second windows and rank them by the share of
  words with probability below 0.70. The worst 20% of windows (about 13 minutes of a
  69-minute lecture) contain **38% of the wrongly heard words** instead of 20%. That is
  81% of what a perfect oracle could do. Mean word probability works equally well; they
  are the same signal.
- **Rank within each lecture; don't ship a fixed threshold.** The cut-offs measured here
  are this lecture's own quantiles.
- **The existing `no_speech_prob > 0.6` flag** in `scripts/ggsm_transcription/asr.py` flags
  61% of segments. A flag on most of a lecture cannot direct anyone's attention. That is
  why it marked 481 of 785 segments.
- **Dropped words have no working detector.** They make up 41% of all errors, and word
  probability cannot see a word that was never written down. The signals agent called gap
  length "worse than random", but it had scored gap length only against wrongly heard
  words, which a silent gap cannot contain. Scored against dropped words, the longest gap
  in a window finds 34% of them in the worst 20% of windows. The honest verdict: **gap
  signals are unproven, not disproven.**
- **Even a perfect signal has a low ceiling.** Errors are spread through this lecture
  rather than clustered, so even an oracle puts only 46% of them in the worst 20%. Guided
  listening concentrates effort; it does not let him skip most of a lecture.
- **Not measured:** whether he actually corrects faster when pointed at flagged windows.

### 6. Check read-along timing — models agree; accuracy is still unmeasured

- **Medium and turbo agree** on 93% of shared words to within one word position. The
  median difference is 0.16 s against a median word length of 0.36 s.
- **No drift.** The disagreement is flat across all seven 10-minute blocks (0.14–0.16 s),
  so long lectures don't need splitting for timing reasons.
- **Medium runs about 0.15 s later** than both small and turbo. That is a constant, so it
  can be subtracted, but nobody yet knows which side is right.
- **Words recovered by the gap re-decode have sound timing but doubtful text:** only 42%
  are confirmed by another model, against 80% for the rest.
- **What is missing, according to the verifier:**
  - There are no ground-truth word starts at all. Marking ~100 true word onsets by ear
    (about 20 minutes) would turn every bound into a measured error.
  - The website will play the mp3 in a browser, and browser seek offsets on VBR mp3 files
    were never checked. They could exceed 0.15 s.
  - Corrected text has no timestamps. About 690 fixes and ~770 missing words get no word
    times from Whisper, so the pipeline needs **forced alignment of the corrected text
    back to the audio**. That stage was never costed.
- **For the website:** end each highlight at the next word's start, never at the word's own
  end. 150 words have zero length, and 19 run past 2 seconds.

### 7. Test the correction workflow — the verification workflow is tested; correction is not

The sitting verified a transcript in which 96.7% of cues were already right. Correcting a Whisper
transcript means about 40 times more fixes. What the sitting did establish (per-cue
re-timing, printed times that follow the shift control, carry-over between subtitle
versions) is recorded in the handoff §10. The correction workflow itself has not been
tried.

### 8. A permanent check against regressions — ingredients ready, and the bug shows why pinning matters

The reference, the audio fixity record (`data/reference/90-85-expected.json`: MD5 and
duration) and the scorer with its 10 tests all exist. What's missing is a command that
re-scores this lecture and fails if accuracy drops. The scorer bug is the argument for
it: it went unnoticed across six configurations and two sessions.

## What would settle the rest

| next step | cost | settles |
|---|---|---|
| **One timed correction sitting** on a *different* lecture, correcting medium-beam1 output | one sitting of the steward's time | seconds per fix and correction listening speed (3), the signal on a new lecture (5), the real correction workflow (7), a second reference (8) |
| Mark ~100 true word onsets on this lecture | ~20 minutes of listening | timing accuracy instead of agreement (6) |
| medium with silence skipping off; medium batched; medium beam 5 | ~35 min of machine time each | dropped words (the largest error class), machine time, the last accuracy gap (2) |
| Measure real lecture durations from archive.org | cheap, no CPU | replaces the 55-minute guess in every corpus figure |
| Pin the regression check | short | protects everything above (8) |
