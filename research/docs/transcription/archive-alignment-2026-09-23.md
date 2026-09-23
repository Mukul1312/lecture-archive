# The whole archive, timed

**Everything this project had measured came from one lecture.** The official archive at
taptajivanam.com carries **112 lectures, 100 of them with both audio and a published
transcript** — 413,812 words. This is the run that puts the pipeline against all of it.

It is a harder test than Melbourne, and deliberately so. The Melbourne reference arrived already
cut into cues a human had timed, so every alignment was handed a few seconds of audio and the
words belonging to them. **These transcripts are paragraphs.** No timings, no diarisation, and —
because they are edited for publication — questioner turns largely left out, so the recording
contains speech the text never mentions.

## What works

The first lecture through the pipeline:

| | |
|---|---:|
| words placed | **718 of 728 (99%)** |
| mean acoustic score | 0.525 |
| invariants violated | **none** |
| span | 0.2 – 493.6 s of 493.6 s |
| speed | **1.56× real time** on CPU |

It opens on `"I thank you, one and all, for your…"` at 0.2 s and closes on `"Jaya Srila Gurudeva
ki jaya!"` at 493.5 s. The transcript's own rate — **88 words per minute** — matches the 91
measured on the one other lecture we have, which is the first evidence that these published
transcripts are not heavily abridged.

## How, given there is nothing to start from

Two walls stand in front of simply aligning a lecture. The Viterbi backtrack matrix is frames ×
letters, which for 47 minutes wants about **6 GB**; and cutting the audio into pieces means
deciding which words belong to which piece, which is the very thing being computed.

The way through is to **walk forward and let the text run out on purpose**:

1. Take a window of audio (7 minutes).
2. Offer it **fewer words than could possibly fit** — a floor of 55 words per minute, well under
   the 88–91 actually measured.
3. Close the word list with a **star**, the wildcard that matches anything.
4. The words land where they were said; the star absorbs whatever audio is left over.
5. **The last word placed becomes the start of the next window.**

Nothing is ever guessed. Each step is anchored by the step before it, so a step that goes wrong
shows up as a collapsed score rather than as silent drift. The cost is that the tail of each
window gets scored twice — about 1.6× overhead — which is the price of never having to guess a
boundary.

The encoder is chunked separately, because wav2vec2's attention is quadratic in frames and a
seven-minute window is 21,000 of them: an attention matrix of roughly 1.8 GB per head. I wrote
`emissions_long` for exactly that and then forgot to use it; the first run was slower and
hungrier than it needed to be.

## The star, and what it is actually for

I expected the star to stop words being dragged across untranscribed audio. Testing it showed
that was the wrong reason: **CTC's blank already absorbs a gap**, and the neighbouring words were
not being stretched.

Its real worth on this corpus is that **blank swallows a gap in a way indistinguishable from
success, and a star leaves a mark**. The step records show 147 seconds absorbed in the first
window alone — that is audio the published transcript does not account for, and now it is a
number rather than a silence.

That also makes the star the measuring instrument for this corpus's central problem. Where a
question from the floor was never transcribed, the alignment does not quietly misplace the
surrounding words and call it done; it reports how much audio had no text.

## What this corpus can and cannot settle

**It can** break the one-lecture dependency for anything that does not need verbatim text:
forced-alignment quality, speaking rate, how much of a lecture a published transcript actually
covers, and where the archive's Bengali and Sanskrit passages fall.

**It cannot** be used to quote a word error rate without qualification. The transcripts omit
questioner turns, so a recogniser will be charged for words it heard correctly. `colab/README.md`
records this. **43 of the 100 lectures record no other speaker at all** — those are the fair ones
to measure recognition against, and even then the text is edited rather than verbatim. Melbourne's
carefully *verified* subtitle file was still at fault in 14.9% of disagreements; a published
transcript will be worse.

## Two traps in the fetching, both real

**The site runs two page templates.** The older marks the lecture body `dir="ltr"` and justified;
the newer drops the `dir`. `fetch_lecture.extract_transcript` knows only the older one, and using
it alone silently loses about a third of the corpus — the kind of shortfall that looks like the
site's fault rather than ours.

**The MP3 filenames contain spaces**, because a person typed them:
`19920630_AA_BBSR_Arrival from USA_No Question of Disappointment….mp3`. urllib refuses such a
path outright, and the refusal is an `InvalidURL` — neither a `URLError` nor an `OSError`, so it
escapes the obvious `except` clause and takes the whole batch with it.

**Six lectures serve audio by JavaScript injection** and have no static `<source>` tag. They need
a headless fetch and are not in this run.

## Running it

```bash
# mirror the archive (resumable; pages come from the triage cache, audio is spaced)
python scripts/taptajivanam_mirror.py plan
python scripts/taptajivanam_mirror.py fetch

# place every fetched transcript against its audio (resumable)
.venv-indic/Scripts/python.exe -m scripts.align_archive

# what has been aligned so far
.venv-indic/Scripts/python.exe -m scripts.align_archive --report
```

At 1.56× real time, the full 78 hours is roughly **50 hours of CPU**, so this is a job that runs
across nights rather than within one. Every lecture is written as it finishes and already-aligned
lectures are skipped, so it can be stopped and resumed freely.
