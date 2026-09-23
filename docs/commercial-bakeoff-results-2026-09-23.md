# The hosted services, measured on Gurudeva's own lecture (2026-09-23)

Three hosted services were tested on the Melbourne reference, on the same audio and with the
same scorer as every local model. This is the first intervention in the whole project that
reduces the steward's **correction labour**, rather than only improving word counts.

Audio: `melbourne-cut.wav`, 66.4 minutes, the reference span minus the 3.4 minutes of speech
no cue covers, so a system without word timestamps is not penalised for speech the reference
does not contain. Scoring is text-only for every system, with three fairness normalisations
applied to all of them and to the reference: apostrophes, small numbers, and bracketed
annotations such as `[singing]`.

## Results

| system | WER | English | Sanskrit | dropped words | **edit sites** | English next to Sanskrit |
|---|---:|---:|---:|---:|---:|---:|
| Whisper medium, skip rule off (local) | 28.8% | 20.3% | 62.1% | 928 | 666 | 51.4% |
| Deepgram Nova-3 `en-IN` | 35.0% | 24.9% | 89.5% | 1,584 | 694 | 62.1% |
| **ElevenLabs Scribe v2** | 22.5% | 13.8% | 61.1% | 922 | **523** | 44.5% |
| ElevenLabs + 50 keyterms | 22.0% | 13.6% | 53.1% | 832 | 543 | 41.2% |
| Sarvam Saaras v4 `verbatim` | 23.8% | 17.4% | 45.9% | 729 | 633 | 44.1% |
| Sarvam `verbatim` + 50 keyterms | 24.1% | 17.6% | **43.5%** | 730 | 669 | 42.6% |
| **ElevenLabs + Sarvam combined** | **20.5%** | **12.7%** | 43.0% | **606** | 567 | **37.1%** |

"Edit sites" counts the places a human must stop and type, not the words that are wrong; it is
the measure that tracks correction time (§10.24, `docs/melbourne-reference-eight-point-findings-2026-09-22.md`).

## What this changes

1. **ElevenLabs cuts the stops by 21%** (666 → 523). Every earlier change — a bigger model,
   the skip rule, combining two local recognisers — moved error *words* while leaving the
   number of stops almost untouched. This one moves the thing that costs the steward time.
2. **English errors fall by a third** (20.3% → 13.6% with keyterms). English is about 90% of
   the words and most of the labour.
3. **Sarvam is the Sanskrit specialist**: 43.5% unrecognisable against Whisper's 62.1%, and
   the fewest dropped words of any single system (729 against 928).
4. **Combining the two is the best transcript** (WER 20.5%, 606 dropped words) but costs 567
   stops against ElevenLabs' 523. So the choice is not automatic: the combination is more
   complete, ElevenLabs alone is less work.
5. **Keyterm prompting finally works.** Feeding 50 Sanskrit names *into the recogniser* cut
   ElevenLabs' Sanskrit errors by 8 points (61.1% → 53.1%). The same glossary failed twice
   before: as a Whisper prompt (WER got worse) and as post-correction (~2 points, with
   confident wrong words). The mechanism matters, not the word list.
6. **Deepgram is out.** Its documentation warned that in English mode "speech in other,
   non-specified languages will not be transcribed", and the measurement agrees: 89.5% of
   Sanskrit unrecognisable, 1,584 words dropped. It is 250x faster than everything else and
   cost 29 cents, but it is the wrong tool for a trilingual archive.

## The leaderboard trap, for the third time

Deepgram ranks near the top of public benchmarks and beats Whisper on several. On a 1990
cassette of an Odia speaker chanting Sanskrit it is clearly worse. The same has now happened
with `large-v3-turbo` (better English, far worse Sanskrit) and Indic-Transcribe-flex (built
for code-switching, lost to Whisper on both corpora). **Public benchmarks have now mispredicted
this corpus three times out of three.**

## Code-switching, again

The gradient the steward identified survives every system, but the better systems flatten it:
English words next to a Sanskrit word are wrong 51.4% of the time with Whisper, 44.5% with
ElevenLabs, and 37.1% with the combination, against 8–18% far from any Sanskrit. No system
escapes it; better systems suffer less.

## Cost, if this became the pipeline

| route | price | corpus (~3,450 h, unverified average) |
|---|---|---|
| ElevenLabs Scribe v2 | $0.22/h | **~$760** |
| ElevenLabs + keyterms | +20% | ~$910 |
| Sarvam Saaras v4 | ₹30/h (~$0.34) | ~$1,180 |
| Both, for the combination | — | ~$2,000 |
| Whisper on this laptop | free | ~70 days of running |

Against that, the labour: ~690 stops per lecture across 3,766 lectures is roughly 2.6 million
review decisions. **A 21% cut in stops is worth far more than $760.**

## What was used, and what it cost today

- ElevenLabs: two runs, 2.2 h of the 4.5 h free monthly allowance.
- Sarvam: two runs, ₹66 of the ₹100 signup credit.
- Deepgram: one run, $0.29 of the $200 credit. Billing confirmed mono, so the stereo
  double-charge risk did not apply.

## Practical notes for whoever builds this

- ElevenLabs wants `keyterms` as **repeated form fields**; a JSON string is rejected with
  "Some keyword contains invalid characters".
- Leave ElevenLabs' `no_verbatim` off, and prefer Sarvam's `verbatim` mode: this archive wants
  what he actually said, including repetitions.
- ElevenLabs **marks non-English spans** in the transcript (`[speaking Bangla]` 12 times,
  `[singing]` 15, `[foreign language]` 9). That is a free language detector for the verse and
  song routing, and worth keeping rather than discarding.
- ElevenLabs writes Sanskrit **in IAST with diacritics**, which is the archive's own
  convention. No other system does.
- Deepgram trains on submitted audio unless `mip_opt_out=true` is sent on every request. The
  client always sends it. ElevenLabs' Zero Retention Mode is enterprise-only and Sarvam
  publishes no retention page; the steward accepted that before anything was sent, since the
  lectures are already public.
