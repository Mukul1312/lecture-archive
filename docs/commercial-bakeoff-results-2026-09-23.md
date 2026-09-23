# The nine-system bake-off on Gurudeva's own lecture (2026-09-23)

Nine transcription systems, three local and three hosted plus three combinations, measured on
the Melbourne reference with one scorer. This is the first work in the project that reduces
the steward's **correction labour** rather than only improving word counts, and it settles
which systems belong in the pipeline.

## How the comparison was made fair

- **One audio file for everyone:** `data/reference/melbourne-cut.wav`, 66.4 minutes. It is the
  reference span (650–4840 s) minus the 3.4 minutes of speech that no subtitle cue covers,
  removed in 11 pieces. Without that cut, a system with no word timestamps would be punished
  for transcribing speech the reference does not contain, while Whisper could have those
  stretches excluded by time. Whisper was **re-run** on this file rather than reusing its
  earlier output.
- **One scorer, text only:** word order, not word times, through
  `scripts/transcript_accuracy.py`. English is scored strictly; Sanskrit and names are scored
  by whether a reader would recognise the word, so *śrī* heard as *shri* is not an error.
- **Three normalisations, applied to every system and to the reference**, because they are
  differences of writing rather than of hearing:
  - apostrophes become spaces (flex writes "he ll", Whisper "he'll");
  - numbers under 1,000 are spelt out (some systems write "3 hours", the reference "three");
  - bracketed annotations are removed (`[singing]`, `[speaking Bangla]`, `[laughs]`).
- **Reference:** 6,799 scored tokens from the steward's verified review, 6,002 English and
  676 Sanskrit or names (counts differ slightly from earlier documents because of the
  normalisations above).

Commands: `data/reference/melbourne_bakeoff.py` (cut, whisper, flex, fuse, score) and
`data/reference/commercial_bakeoff.py` (deepgram, elevenlabs, sarvam).

## Results

"Edit sites" counts the places a human must **stop and type**. It is the measure that tracks
correction time; error words do not, as the eight-point findings established.

| system | WER | English | Sanskrit | dropped | wrong | invented | **edit sites** | speed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Whisper medium, skip rule off | 28.8% | 20.3% | 62.1% | 928 | 736 | 292 | 666 | 2.0x |
| Deepgram Nova-3 `en-IN` | 35.0% | 24.9% | 89.5% | 1,584 | 545 | 254 | 694 | **517x** |
| flex `en native` | 26.5% | 20.6% | 41.9% | 705 | 838 | 255 | 700 | 1.4x |
| flex `bn mixed` | 28.5% | 23.2% | **38.6%** | 749 | 933 | 258 | 798 | 1.8x |
| Sarvam Saaras v4 `verbatim` | 23.8% | 17.4% | 45.9% | 729 | 647 | 245 | 633 | 118x |
| Sarvam `verbatim` + 50 keyterms | 24.1% | 17.6% | 43.5% | 730 | 644 | 267 | 669 | 125x |
| **ElevenLabs Scribe v2** | 22.5% | 13.8% | 61.1% | 922 | 336 | 274 | **523** | 104x |
| ElevenLabs + 50 keyterms | 22.0% | 13.6% | 53.1% | 832 | 358 | 304 | 543 | 114x |
| ElevenLabs + Sarvam | **20.5%** | 12.7% | 43.0% | 606 | 462 | 327 | 567 | — |
| ElevenLabs + flex | 20.7% | 12.9% | 42.9% | 649 | 430 | 329 | 577 | — |
| **All three combined** | **20.5%** | **12.6%** | 41.4% | **572** | 478 | 347 | 579 | — |

### English errors by distance from the nearest Sanskrit word

The steward's code-switching finding, tested across every system:

| system | next to it | 2–3 words | 4–10 words | far away |
|---|---:|---:|---:|---:|
| Deepgram | 62.1% | 36.0% | 23.2% | 18.0% |
| Whisper medium | 51.4% | 26.5% | 19.4% | 14.9% |
| flex `bn mixed` | 48.6% | 31.9% | 21.8% | 18.4% |
| ElevenLabs | 44.5% | 22.1% | 10.7% | 9.1% |
| Sarvam + keyterms | 42.6% | 26.5% | 16.2% | 12.9% |
| ElevenLabs + keyterms | 41.2% | 22.4% | 11.3% | 8.8% |
| All three combined | **36.7%** | 20.8% | 10.6% | **8.3%** |

**No system escapes the effect; better systems suffer less.** Every one of them is three to
five times more likely to err beside a Sanskrit word than away from one.

## What the numbers mean

### 1. The first result measured in the steward's hours

ElevenLabs cuts edit sites from 666 to **523, a 21% reduction**. Every earlier improvement —
a bigger model, the no-speech skip rule, combining two local systems — moved error words while
leaving the number of stops flat. Across ~3,766 lectures, ~690 stops each, roughly 2.6 million
review decisions, a fifth is a very large number of hours.

### 2. Three specialists, not one winner

- **English: ElevenLabs** (13.6% with keyterms, against Whisper's 20.3%). English is ~88% of
  the words and most of the labour.
- **Sanskrit: the Indian models.** flex `bn mixed` reaches **38.6%** and Sarvam 43.5%, against
  Whisper's 62.1% and Deepgram's 89.5%.
- **Fewest dropped words: Sarvam and flex** (729 and 705, against Whisper's 928).

The best English system is Western; the two best Sanskrit systems are Indian-built. That is
the steward's trilingual hypothesis in its strongest form: **no single system is good at both,
and this corpus needs both.**

### 3. Combining systems buys completeness, and costs a little labour

Each system added recovers more lost speech and costs about ten more stops:

| combination | dropped words | Sanskrit | edit sites |
|---|---:|---:|---:|
| ElevenLabs alone | 922 | 61.1% | 523 |
| + keyterms | 832 | 53.1% | 543 |
| + Sarvam | 606 | 43.0% | 567 |
| + flex as well | **572** | **41.4%** | 579 |

Even the three-way combination still makes **13% fewer stops than Whisper alone**. The method
is deterministic: keep the base system's words, and insert the other system's words only where
the base wrote nothing. It cannot hallucinate, and it is the baseline the research said any
language model must beat before it earns a place.

### 4. Keyterm prompting finally works — inside the recogniser

Fifty Sanskrit names from the archive's own glossary cut ElevenLabs' Sanskrit errors by
**8 points** (61.1% → 53.1%) and improved everything else slightly. The same word list had
failed twice before:

- as a Whisper `initial_prompt`: WER got **worse** (34.29% → 34.44% on small, 28.42% → 29.04%
  on turbo);
- as a post-recognition glossary pass: ~2 points, with confident wrong words (*baba* → *bhava*).

**The mechanism mattered, not the word list.** On Sarvam the gain was smaller (45.9% → 43.5%)
and its WER rose slightly, so keyterms are not free everywhere.

### 5. Deepgram is out

Its own documentation says that in English mode "speech in other, non-specified languages will
not be transcribed", and it does not support Sanskrit at all. The measurement agrees: **89.5%
of Sanskrit unrecognisable and 1,584 words dropped**, the worst of any system. It is
extraordinary at speed — 517x real time, the whole lecture in 7.7 seconds for 29 cents — and
its per-word confidence is the best-evidenced error signal available. If it has a role here it
is as a fast confidence estimator, not as the transcriber.

### 6. Public benchmarks have now mispredicted this corpus three times out of three

- `large-v3-turbo` ranks above `medium` publicly; it was far worse at Sanskrit here.
- Indic-Transcribe-flex is built for code-switching; it lost to Whisper on both corpora
  overall, while quietly being the best at Sanskrit on this one.
- Deepgram ranks mid-table on clean speech and beats Whisper on several public sets; it is the
  worst system here.

**Nothing may be adopted on reputation. Measure it on the reference.**

## Cost, if this became the pipeline

Per 3,450 audio hours, on the unverified 55-minute average:

| route | price per hour | corpus | edit sites per lecture |
|---|---|---|---:|
| Whisper on this laptop | free (~70 days of running) | — | 666 |
| **ElevenLabs Scribe v2** | $0.22 | **~$760** | 523 |
| ElevenLabs + keyterms | $0.27 | ~$910 | 543 |
| Sarvam Saaras v4 | ₹30 (~$0.34) | ~$1,180 | 669 |
| ElevenLabs + Sarvam, both | — | ~$2,000 | 567 |
| All three (flex runs locally) | — | ~$2,000 + ~9–15 laptop-days | 579 |

Against roughly 2.6 million review decisions, a fifth fewer stops is worth far more than $760.

**Spent to produce this table:** 2.2 hours of ElevenLabs' 4.5-hour free month, ₹66 of Sarvam's
₹100 signup credit, and $0.29 of Deepgram's $200. The local runs cost about 2.5 hours of
laptop time.

## Practical notes for whoever builds this

- **ElevenLabs wants `keyterms` as repeated form fields.** A JSON string is rejected with
  "Some keyword contains invalid characters".
- **Leave ElevenLabs' `no_verbatim` off**, and prefer Sarvam's `verbatim` mode. This archive
  wants what he actually said, including repetitions.
- **ElevenLabs writes Sanskrit in IAST with diacritics** — the archive's own convention. No
  other system does.
- **ElevenLabs marks non-English spans**: `[speaking Bangla]` 12 times, `[singing]` 15,
  `[foreign language]` 9. That is a free detector for the verse and song routing, and worth
  keeping rather than discarding.
- **Deepgram trains on submitted audio unless `mip_opt_out=true` is sent on every request.**
  The client always sends it. ElevenLabs' Zero Retention Mode is enterprise-only and Sarvam
  publishes no retention page; the steward accepted both before anything was sent, since the
  lectures are already public on archive.org.
- **Sarvam's direct endpoint stops at 30 seconds**; a 66-minute file needs the batch job flow
  through their SDK. ElevenLabs accepts a 5 GB upload directly.
- **The ElevenLabs Python SDK cannot install on Windows** (a file path exceeds the limit, and
  fixing it means a registry change), so both it and Deepgram are called over REST.
- Neither ElevenLabs nor Sarvam publishes **word timestamps in a form we have verified** for
  the read-along page; ElevenLabs does return word-level times, which still need checking
  against the audio before the highlighting can trust them.

## What is still unmeasured

- **A second reference.** Everything here rests on one lecture, as before. Prabhupadavani was
  added as a second corpus and behaved differently (Whisper won there), which is itself the
  warning.
- **Word-timestamp accuracy** for the hosted systems.
- **Whether flex's Sanskrit strength holds on other lectures**, or is particular to this
  recording's chanting.
- **The corpus average length**, which every cost figure multiplies.
