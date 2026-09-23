# The "Sanskrit" column was two languages (2026-09-23)

Every Sanskrit figure in this project has been wrong in the same way, and the error hid a
routing result.

The scorer's Indic track counts **any word the reference wrote with diacritics**. Bengali
transliteration carries just as many as Sanskrit, so `bhuliyā tomāre saṁsāre āsiyā` — a
Bhaktivinoda song — was being scored in a column labelled Sanskrit. Splitting them changes
which system is best, and shows the archive's weakest link was never visible.

## The split

**676 Indic words = 486 Sanskrit + 190 Bengali.** Classifier in
`scripts.transcript_accuracy.indic_language`, checked against thirty cues classified by
reading them: **thirty right, none wrong**.

| system | as reported | **Sanskrit** | **Bengali** |
|---|---:|---:|---:|
| Whisper medium | 67.6% | 61.1% | 84.2% |
| Deepgram Nova-3 | 90.4% | 86.6% | **100.0%** |
| flex `en native` | 48.8% | 46.3% | 55.3% |
| **flex `bn mixed`** | 45.7% | 44.2% | **49.5%** |
| Sarvam Saaras v4 | 51.5% | 46.1% | 65.3% |
| ElevenLabs Scribe v2 | 62.7% | 51.0% | 92.6% |
| ElevenLabs + keyterms | 54.6% | **42.6%** | 85.3% |
| all three fused | 44.7% | **36.8%** | 64.7% |

## What the blended number was hiding

**ElevenLabs was badly misjudged.** Its 54.6% concealed **42.6% on Sanskrit** — second-best of
any single system — and **85.3% on Bengali**. A strength and a collapse averaged into a
mediocrity, and we drew conclusions from the average.

**Deepgram gets every Bengali word wrong.** Not 90% — **100.0%**. Consistent with its
documentation saying English mode will not transcribe other languages, but the blend disguised
how total the failure is.

**flex `bn mixed`'s win was differently shaped than we thought.** It is not primarily a
Sanskrit specialist: it is **the only system under 50% on Bengali**, by six points, and that
is what pulled its blended figure down into apparent Sanskrit leadership. Its actual Sanskrit
number, 44.2%, is beaten by both ElevenLabs configurations.

## The Sanskrit-specific recogniser, measured

A model fine-tuned for chanted Sanskrit — Su-śrotā, IndicConformer-CTC, int8 ONNX, Apache-2.0,
~30× real time on CPU — had never been tried here. On the verse cues, once the two languages
are separated:

| | Sanskrit cues (n=16) | Bengali cues (n=14) |
|---|---:|---:|
| **Su-śrotā** | **35.7% CER** | 61.6% |
| ElevenLabs + keyterms | 37.0% | 82.3% |
| flex `bn mixed` | 37.9% | **45.7%** |
| Sarvam | 38.1% | 69.1% |
| Whisper medium | 57.6% | 65.8% |

**It wins on Sanskrit** and loses on Bengali, exactly as a Sanskrit-only model should.

!!! warning "This result was nearly missed, by the same mistake"
    The first run of this measurement filtered "pure Sanskrit" cues by *diacritic density* and
    so fed **fourteen Bengali songs to a Sanskrit-only model**, scoring its failures against
    it. That produced 47.8% CER and an apparent loss to flex. The model was fine; the method
    was not. The steward was right to disbelieve it.

The margin over the next system is modest — 35.7% against 37.0% — not the 4× the literature
suggests (Whisper 99.0% vs a Sanskrit Conformer's 22.8% on IndicVoices). The gap is the
recording: 1980s cassette of a man chanting mid-lecture to a room, against curated or
phone-recorded corpora. A window sweep confirmed it is not our segmentation — even an oracle
window per cue only reaches 38.1%.

## What follows

The routing is **three-way**, and each language has a different owner:

| | best | note |
|---|---|---|
| **English** | the three local systems, confidence-gated | 15.1% error |
| **Sanskrit** | fused, or ElevenLabs + keyterms; Su-śrotā on verse spans | 36.8–42.6% |
| **Bengali** | **flex `bn mixed`, and nothing else works** | 49.5% |

**Bengali is the weakest link in the whole design, and it has been invisible.** It is 190
words in this lecture, the longest blackouts we measured, has no openly-licensed corpus
anywhere, and exactly one system manages even 50%. Every earlier conclusion that treated
"Sanskrit" as one problem was reasoning about an average of a hard problem and a much harder
one.

## Corrections this forces elsewhere

- The bake-off's Sanskrit column, and every claim of the form "flex is the Sanskrit
  specialist", should be read as **Sanskrit and Bengali combined**.
- "ElevenLabs is poor at Sanskrit" is wrong: it is second-best at Sanskrit and poor at
  Bengali.
- The verse-retrieval work is measured over both languages together and should be re-split.
