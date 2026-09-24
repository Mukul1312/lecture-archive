# The whole archive, timed

**Everything this project had measured came from one lecture.** The official archive at
taptajivanam.com carries **112 lectures, 100 of them with both audio and a published
transcript** — 413,812 words. **78 of them could be fetched whole**, carrying 318,571 words, and
this is the run that puts the pipeline against those.

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
ki jaya!"` at 493.5 s.

The second lecture through was four times longer and did better still: **2,333 of 2,337 words
placed — 100%** — 24 minutes of audio in 12.7, at 1.9× real time.

Their speaking rates, **88 and 91 words per minute**, agree with each other and with the one
other lecture in the repository. That is the first evidence that these published transcripts are
not heavily abridged: a transcript missing large stretches would imply a rate far below what the
recording can support.

## The result that matters, and the metric that hid it

**22 lectures aligned overnight — 18.5 hours, 86,004 transcript words, 95.3% placed, zero broken
invariants, at 2.44× real time.**

That 95% is the wrong headline, and it took a control to see why.

**Coverage asks how much of the TRANSCRIPT could be placed.** A transcript that omits half its
lecture still scores 99%, because the half it kept was placed perfectly. The question that
decides whether these transcripts can serve as references is the other one: **how much of the
AUDIO does the text account for?**

Measuring silent stretches over two seconds gives a median of **82%** — which reads alarmingly
until you run the same measure on the Melbourne reference, a caption transcript verified cue by
cue:

| | audio accounted for |
|---|---:|
| Melbourne, **verified complete** | **86%** |
| the archive, median of 22 | 82% |
| the archive, worst | **44%** |

A complete transcript scores 86%, not 100%, because roughly a seventh of any lecture is genuine
pause. So the typical archive transcript is **four points short of verified** — much better than
the raw number suggests — and the story is entirely in the tail.

**Seven of 22 are missing much of their lecture**, and every one of them reads 96–100% on
coverage:

| accounted for | coverage | wpm | lecture |
|---:|---:|---:|---|
| **44%** | 99% | 40 | cc-adi-lila 4.256-258 |
| 59% | 99% | 41 | cc-adi 13.2-6 |
| 64% | 100% | 42 | Padayatra arrival, Sankirtan is Life |
| 66% | 99% | 64 | cc-adi-lila 9.46 |
| 67% | 96% | 65 | cc-adi-lila 8.59-62 |
| 68% | 99% | 54 | cc-adi-lila 9.49-51 |
| 75% | 99% | 82 | Arrival from Bali |

The first of those has words for **44% of a 47-minute recording** — 27 minutes with no text at
all — while reporting 99% coverage. **Words per minute is the tell**: 40 wpm against a measured
83 median means the transcript cannot be describing all the speech.

This is what the corpus needed most: **the aligner triages its own references.** Before any of
these can be used to measure recognition, the incomplete ones have to be found, and now they are
found automatically rather than assumed absent.

### Two things about that tail

**The scripture classes are worse**: `cc-`/`sb-`/`bg-` titles account for a median 79% of their
audio against 87% for darshans and arrivals. The effect is real and the cause is not established.

The obvious explanation — untranscribed Sanskrit recitation — **is not supported by the test I
ran**: transcripts in the more diacritic-dense half account for 83% against 81% for the less
dense, essentially no difference and in the wrong direction. That test cannot settle it either
way, though, and for a reason worth recording: **verse omitted from a transcript leaves no
diacritics to count.** Deciding this needs recognition run over the silent stretches, not a
property of the text that is missing.

**Missing questioner turns are a smaller effect than expected**: transcripts recording no other
speaker account for a median 99.4% of their own words placed, against 96.5% for those that do —
three points, not the dominant factor.

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

**Twenty-one lectures serve audio by JavaScript injection** and have no static `<source>` tag.
Their transcripts came down fine; the audio needs a headless fetch (firecrawl would do it) and
they are not in this run.

**One lecture is published damaged.** A broken MPEG frame partway through, and a fresh download
returns byte-identical — so the damage is in the file on the server, not the transfer.
libsndfile refuses it outright; ffmpeg skips the bad frame and recovers **60.8 of its 61
minutes**, which for a lecture recording is the right trade. The fallback only runs after
soundfile has already failed.

**So the run covers 78 of the 100**, carrying 318,571 transcript words.

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
