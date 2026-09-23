# The nine-system bake-off on Gurudeva's own lecture (2026-09-23)

> **Corrected the same day.** Reading the errors word by word
> (`docs/error-text-analysis-2026-09-23.md`) found that the scoring was charging the
> recognisers for three things they had not done: unspoken speaker labels, contractions
> ("he's" for "he is") and split clitics ("isn t"). All three are now normalised on both
> sides, every system has been re-scored, and **the ranking did not change** - but every
> figure below improved. The tables here are the corrected ones. Anything quoting 666 or
> 523 stops, or a 21% reduction, predates the fix.

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
  - contractions are written out in full on both sides ("he's" and "he is" become the same
    two words), and a clitic a recogniser split off is rejoined (`flex en native` writes
    "isn t", "he ll");
  - speaker labels are removed from the reference ("Mr Peter:" opens 41 cues and nobody
    says it aloud);
  - numbers under 1,000 are spelt out (some systems write "3 hours", the reference "three");
  - bracketed annotations are removed (`[singing]`, `[speaking Bangla]`, `[laughs]`).
- **Reference:** 6,698 scored tokens from the steward's verified review, 6,022 English and
  676 Sanskrit or names (counts differ slightly from earlier documents because of the
  normalisations above).

Commands: `data/reference/melbourne_bakeoff.py` (cut, whisper, flex, fuse, score) and
`data/reference/commercial_bakeoff.py` (deepgram, elevenlabs, sarvam).

## Results

"Edit sites" counts the places a human must **stop and type**. It is the measure that tracks
correction time; error words do not, as the eight-point findings established.

| system | WER | English | Sanskrit | dropped | wrong | invented | **edit sites** | speed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Whisper medium, skip rule off | 27.5% | 18.7% | 62.1% | 829 | 716 | 294 | 636 | 2.0x |
| Deepgram Nova-3 `en-IN` | 33.4% | 22.9% | 89.5% | 1,488 | 493 | 259 | 643 | **517x** |
| flex `en native` | 25.1% | 18.9% | 41.9% | 609 | 812 | 260 | 664 | 1.4x |
| flex `bn mixed` | 27.0% | 21.4% | **38.6%** | 651 | 899 | 261 | 765 | 1.8x |
| Sarvam Saaras v4 `verbatim` | 22.7% | 15.9% | 45.9% | 637 | 632 | 254 | 609 | 118x |
| Sarvam `verbatim` + 50 keyterms | 23.0% | 16.2% | 43.5% | 636 | 631 | 274 | 644 | 125x |
| **ElevenLabs Scribe v2** | 21.1% | 11.9% | 61.1% | 827 | 303 | 280 | **470** | 104x |
| ElevenLabs + 50 keyterms | 20.5% | 11.7% | 53.1% | 738 | 325 | 311 | 487 | 114x |
| ElevenLabs + Sarvam | **19.1%** | 10.8% | 43.3% | 510 | 434 | 332 | 513 | - |
| ElevenLabs + flex | **19.2%** | 11.0% | 42.9% | 555 | 396 | 336 | 520 | - |
| **All three combined** | **19.1%** | **10.7%** | 41.7% | **476** | 449 | 351 | 523 | - |

### English errors by distance from the nearest Sanskrit word

The steward's code-switching finding, tested across every system:

| system | next to it | 2–3 words | 4–10 words | far away |
|---|---:|---:|---:|---:|
| Deepgram | 62.1% | 34.7% | 21.4% | 15.2% |
| Whisper medium | 51.4% | 26.1% | 18.1% | 12.5% |
| flex `bn mixed` | 48.6% | 31.1% | 20.3% | 15.9% |
| ElevenLabs | 44.3% | 21.1% | 8.7% | 6.6% |
| Sarvam + keyterms | 42.6% | 25.8% | 14.9% | 10.8% |
| ElevenLabs + keyterms | 41.0% | 21.4% | 9.3% | 6.4% |
| All three combined | **35.7%** | 20.0% | 8.8% | **5.9%** |

**No system escapes the effect; better systems suffer less.** Every one of them is three to
five times more likely to err beside a Sanskrit word than away from one.

## What the numbers mean

### 1. The first result measured in the steward's hours

ElevenLabs cuts edit sites from 636 to **470, a 26% reduction**. Every earlier improvement —
a bigger model, the no-speech skip rule, combining two local systems — moved error words while
leaving the number of stops flat. Across ~3,766 lectures, ~690 stops each, roughly 2.6 million
review decisions, a quarter is a very large number of hours.

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
| ElevenLabs alone | 827 | 61.1% | 470 |
| + keyterms | 738 | 53.1% | 487 |
| + Sarvam | 510 | 43.3% | 513 |
| + flex as well | **476** | **41.7%** | 523 |

Even the three-way combination still makes **18% fewer stops than Whisper alone**. The method
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
| Whisper on this laptop | free (~70 days of running) | — | 636 |
| **ElevenLabs Scribe v2** | $0.22 | **~$760** | 470 |
| ElevenLabs + keyterms | $0.27 | ~$910 | 487 |
| Sarvam Saaras v4 | ₹30 (~$0.34) | ~$1,180 | 644 |
| ElevenLabs + Sarvam, both | — | ~$2,000 | 513 |
| All three (flex runs locally) | — | ~$2,000 + ~9–15 laptop-days | 523 |

Against roughly 2.6 million review decisions, a quarter fewer stops is worth far more than $760.

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
- **ElevenLabs marks non-English spans — but only without keyterms.** A plain pass writes
  `[speaking Bangla]` 12 times and `[singing]` 15; with the keyterm list those become a
  generic `[foreign language]` 43 times and the specific labels disappear entirely. Since
  those markers are the free detector for exactly the passages nobody transcribes, take them
  from a plain pass.
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

## Where the remaining mistakes are

Printed and classified in **`docs/error-text-analysis-2026-09-23.md`**: more than half of
every remaining stop is one word swapped for one word; three-fifths of the labour is plain
English with no Sanskrit near it; ten stretches totalling 184 words (Bengali songs and
chanted verse) are lost by every system and are recoverable only by retrieval from print;
and about 42 of ElevenLabs' 487 stops are places where the reference, not the machine, is
the likelier suspect.

## What is still unmeasured

- **A second reference.** Everything here rests on one lecture, as before. Prabhupadavani was
  added as a second corpus and behaved differently (Whisper won there), which is itself the
  warning.
- **Word-timestamp accuracy** for the hosted systems.
- **Whether flex's Sanskrit strength holds on other lectures**, or is particular to this
  recording's chanting.
- **The corpus average length**, which every cost figure multiplies.
