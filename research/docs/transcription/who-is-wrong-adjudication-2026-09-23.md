# Are the models wrong, or is our reference? (2026-09-23)

Every accuracy number in this project is measured against one human-made subtitle file for
the Melbourne lecture. [Reading the mistakes](error-text-analysis-2026-09-23.md) raised a
worry it could not settle: at some places the reference looked wrong and the machines looked
right. If that were common, the ruler has nicks in it — and worse, **a corrector following
the reference would be editing correct machine text into errors.**

So every one of the best system's remaining 483 disagreements was judged, one at a time.

## The answer

**The models are genuinely making mistakes — about seven times in ten. But a quarter of what
we have been charging them is not theirs.**

| verdict | sites | share |
|---|---:|---:|
| **the model is wrong** | 349 | **72.3%** |
| the reference is wrong | 72 | 14.9% |
| nobody is wrong | 61 | 12.6% |
| undecidable without audio | 1 | 0.2% |

The model's own errors, by kind:

| | sites |
|---|---:|
| mishearing English | 136 |
| mishearing Sanskrit | 101 |
| writing a word nobody said | 63 |
| other (claims against the reference that did not survive) | 49 |

**Mishearing chanted Sanskrit is the single largest recoverable class.** That is precisely
what the Indian models are better at, and it is the measured case for the combination route
rather than ElevenLabs alone.

## How it was judged

There is no audio available to an automated reader, so the judgement rests on evidence that
survives in text, and it is stronger than it sounds:

- **Independent agreement.** Six systems built by different teams on different data —
  Whisper, Sarvam, Indic-Transcribe-flex, ElevenLabs, Deepgram. They do not converge on the
  same mistake. Several agreeing against the reference is real evidence.
- **Scripture.** The verses are published and fixed, so a quotation can be checked.
- **Sense.** `puport` is not a word; `purport` is, and it is what a Bhāgavatam class says.
- **Grammar.** The speaker says "these is", "he have". A subtitler tidies that; the archive
  wants verbatim.

Twenty agents worked in two passes over ten batches. Every verdict of "the reference is
wrong" was handed to a second reader whose instructions were to **refute** it and to default
to refuted when uncertain. **That pass overturned 50 of 122 claims — 41%.** The 72 that
survived are what this page reports; 31 of them were rated high confidence.

## What is genuinely wrong with the reference

| class | sites | example |
|---|---:|---|
| dropped a word | 33 | `if i give up all sorts ‖ religion` — the reference is missing *of* |
| tidied his English | 21 | `are` → *is*, `these` → *this*; the machines are the verbatim ones |
| typos | 12 | `puport`, `commiting`, `embarassed` |
| editorial text nobody spoke | 6 | `(Laughter)`, `(inaudible reply)`, `(SB 3.25.42)`, `(CB Madhya 23.77)` |

And the class where nobody is at fault — 53 of the 61 — is **spelling and romanisation**:
`oh`/`o`, `saraswati`/`sarasvati`, `acarya`/`acharya`. A corrector does not stop for these.

### The last one was mechanically fixable

The reference writes its editorial notes in round brackets, and the scorer only stripped
square ones. Those are now removed on both sides, like the speaker labels before them. The
reference falls from 6,698 to **6,613 scored words**.

## A claim from the earlier write-up, withdrawn

The previous analysis said **the reference abridges verses**, citing BG 18.66 and SB 12.8.40.
**That was wrong, and the adjudication caught it.** The reference contains both verses in
full and correctly:

```
sarva-dharmān parityajya, mām ekaṁ śaraṇaṁ vraja
ahaṁ tvāṁ sarva-pāpebhyo, mokṣayiṣyāmi mā śucaḥ
yan-māyayāpi vibudhā / muhyanti jñāna-kāśayā
```

The edit sites were *fragments* of long verse quotations, split where the machine garbled the
middle; a ten-word context window showed the fragment and hid the rest. The machines were
mishearing chanted Sanskrit, and the reference was right. No verse abridgement was found
anywhere in the 483.

A second correction, of the method rather than the finding: the first adjudication run was
given **faulty evidence for insertions** — the record's "heard" field swept in the machine's
rendering of the *next* reference word, so every inserted word looked like a duplicate of
what followed. Judges classified 116 sites as alignment artifacts on that basis. With the
evidence corrected, the honest figure is **8**. The whole run was discarded and repeated.

## The corrected table

Three rounds of scorer repair — contractions and speaker labels, then mid-cue labels, then
bracketed editorial text — against the first published figures:

| system | WER | stops |
|---|---|---|
| Whisper medium, skip rule off | 28.8% → **26.6%** | 666 → **627** |
| Deepgram Nova-3 `en-IN` | 35.0% → **32.8%** | 694 → **636** |
| flex `en native` | 26.5% → **24.2%** | 700 → **651** |
| flex `bn mixed` | 28.5% → **26.2%** | 798 → **752** |
| Sarvam Saaras v4 `verbatim` | 23.8% → **21.9%** | 633 → **600** |
| **ElevenLabs Scribe v2** | 22.5% → **20.2%** | 523 → **459** |
| ElevenLabs + 50 keyterms | 22.0% → **19.8%** | 543 → **474** |
| **All three combined** | 20.5% → **18.3%** | 579 → **509** |

**The ranking has not moved once across three rounds of correction.** ElevenLabs now makes
**27% fewer stops than Whisper** (627 → 459), against the 21% first published. Every repair
has enlarged the gap, never reversed it.

## What this does not establish

The reference faults were found by adjudicating **only ElevenLabs' errors**. Where another
system stops and ElevenLabs does not, that place was never examined, so every other system's
discount is a lower bound and any "corrected per-system ranking" would flatter ElevenLabs.
The per-system table in `bakeoff/errors/adjudication.json` carries that caution and should be
read as indicative only.

Settling it would mean adjudicating each system's own errors — worth doing before the
reference is used to judge a second lecture, not before the route decision, which has now
survived three corrections unchanged.

## Reproducing

```
python data/reference/error_text.py dossier elevenlabs-scribe-v2-keyterms50 \
    --against whisper-medium-noskip sarvam-saaras-v4-verbatim flex-bn-mixed \
              deepgram-nova3-en-in flex-en-native --out dossier-full.json
python data/reference/adjudication.py <verdicts-dir>
```

The verdicts, with every reason and refutation, are in
`data/reference/bakeoff/errors/adjudication.json`.
