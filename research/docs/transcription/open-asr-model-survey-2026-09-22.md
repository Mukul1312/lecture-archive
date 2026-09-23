# Beyond Whisper: open ASR models for the SSGGSM corpus (2026-09-22)

Until now only Whisper had been tested on this corpus. This survey looks at the open
models and tools beyond it, for this corpus and this laptop. Every claim here was checked
at its primary source by an adversarial verifier.

Source: workflow run `wf_4e095424-673` (script `.agents/workflows/open-asr-model-survey.js`):
five independent research sweeps and one verifier. Full structured result, with a source
URL for every claim: `data/research/asr-model-survey-2026-09/workflow-result-wf_4e095424-673.json`.
Each sweep's running notes are in the same directory.

**What this survey can and cannot do.** Published benchmarks are clean or modern speech:
phone clips, call-centre dialogue, read speech. None is a 1990 cassette monologue by an
Odia-speaking lecturer who chants Sanskrit. The matrix has already shown how little
leaderboards transfer here: turbo ranks above medium on leaderboards and was far worse
at Sanskrit on our reference. So this survey produces a **shortlist for a bake-off on the
Melbourne reference**. It does not pick a winner.

## The laptop sets the field

AMD Ryzen 5 5625U (6 cores, 12 threads), integrated Vega graphics, **no NVIDIA GPU and so
no CUDA**, 15.3 GB RAM, Windows 11, **44 GB of free disk** (91% full).

- CUDA-first models (NVIDIA NeMo, and most speech LLMs) run here only through CPU ports:
  ONNX Runtime ([onnx-asr](https://github.com/istupakov/onnx-asr), sherpa-onnx) or GGUF
  ([transcribe.cpp](https://github.com/handy-computer/transcribe.cpp)). NeMo has no native
  Windows support.
- **The integrated GPU is usable through Vulkan, and nothing else.** transcribe.cpp on the
  same class of graphics runs about twice as fast as the CPU. ROCm does not support this
  generation of graphics, OpenVINO lists only Intel CPUs, and CTranslate2 (our current
  runtime) has no AMD GPU support.
- Models of 8B parameters and up (Granite 8B, Voxtral Small 24B) do not fit in 15 GB.

## First: Whisper has a skip rule, and our pipeline leaves it on

The verifier ranked this above every model swap. It is confirmed in the installed code at
`.venv-transcribe/Lib/site-packages/faster_whisper/transcribe.py:1215-1235`. When a 30-second
window's no-speech probability exceeds `no_speech_threshold` (0.6) **and** its average log
probability is below `log_prob_threshold` (−1.0), faster-whisper discards the window's text
and jumps to the next window (`seek += segment_size`). Our matrix used the defaults, so the
rule was active in all six runs.

Accented cassette speech is exactly where both conditions fire together. On the Zurich
lecture, `no_speech_prob > 0.6` held for 61% of segments.

- **The test:** `medium-beam1` with `no_speech_threshold=None`. It needs no install, carries
  no licence question and costs about 35 minutes. It isolates how much of the **41% of
  errors that are dropped words** this rule causes.
- **A second Whisper control:** `BatchedInferencePipeline` never applies this skip. It needs
  VAD or fixed `clip_timestamps`, and it is also the main lever on Whisper's speed.

Every other model should be compared against these controls, not against the old runs.

## The shortlist

Verifier priorities, highest first. Laptop speeds are extrapolated from measurements on
11–35-second clips on a similar AMD laptop (Ryzen 7 4750U). **No sustained hour-long
run has been measured**, so treat them as ±30% at best.

| priority | model | licence | word times | on this laptop | why it is on the list |
|---|---|---|---|---|---|
| **high** | Whisper controls: medium with the skip rule off; batched | MIT / Apache-2.0 | native | already runs, 2x | Isolates the skip rule before changing models |
| **high** | [NVIDIA Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) | CC-BY-4.0 | native (80 ms frames) | ~10–16x on CPU, ~2x that on the integrated GPU: **5–7 min per lecture** | Best published evidence on long, accented English. Call-centre Indian English 9.9 WER against 11.9 for Whisper large-v3. Stable however the audio is cut. Runs 5–8 times faster than medium here |
| **high** | [Qwen3-ASR 1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) (+ Qwen3-ForcedAligner 0.6B) | Apache-2.0 | only via the separate aligner | ~2.3–2.7x on CPU (~30 min per lecture); aligner CPU speed unverified | The most stable model across segmentation methods, and the best 14-accent average. Trained on singing, which might help chant (unmeasured) |
| medium | Parakeet TDT 0.6B v3 | CC-BY-4.0 | native | same as v2 | Costs almost nothing beside v2. But it is weaker on Indian English, and most dropped-speech reports are about v3 |
| medium | [Cohere Transcribe 03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026) | Apache-2.0 (gated) | **none** | ~4x on CPU; at most ~400 s per call | Best leaderboard numbers. But its own card warns it transcribes non-speech sounds and is inconsistent on code-switched audio, which is our case |
| medium | Whisper large-v3 (full, never tested; we only ran turbo) | Apache-2.0 | native | ~1x (an overnight run) | Separates "turbo" from "large". Sanskrit is where turbo failed |
| medium | Sanskrit on verse spans only: [Su-śrotā](https://huggingface.co/prathoshap/sushrota-sanskrit-asr) and [AI4Bharat IndicConformer-sa](https://huggingface.co/OpenVoiceOS/ai4bharat-indicconformer-sa-onnx) | Su-śrotā **unclear**; IndicConformer MIT | via CTC alignment | small, fast ONNX | Su-śrotā is the only open model with published chant numbers (CER ~6% on Bhāgavata recitation, self-reported). Testing is fine; **do not publish its output until the author grants a licence** |
| low | SraVaani-1.0, Indic-Transcribe-core, Parakeet CTC 1.1B, Canary-Qwen 2.5B | various | — | — | Gated, custom code, bespoke licences, or weaker than the models above on our questions |

**Ruled out:** Meta Omnilingual ASR has no Sanskrit, only takes clips under 40 s, and
scores 72–90 WER on Odia. MMS ASR has no Sanskrit and is CC-BY-NC. Sarvam has no
open-weights ASR. 8B+ models don't fit in RAM.

## Things we believed that the evidence does not support

- **"Models that aren't autoregressive won't drop speech."** Not established.
  - Parakeet TDT has its own failure: in long windows its decoder state stops changing
    during blanks, and it silently drops soft speech. One report measured the kept-word
    ratio falling from 0.99 at 69 s to 0.45 at 311 s, on clean speech.
  - In the one published breakdown, pure CTC models deleted words at the same rate as
    Whisper.
  - So the bake-off must count **dropped words** as its headline metric, and Parakeet
    must be fed VAD chunks of 30 s or less.
- **"Whisper is bad at Indian English."** In 2023 (Svarah) it was the best open family by
  far, including for Odia-L1 speakers (6.2 WER against 12.1 for NVIDIA's Conformer). By
  2026 Parakeet, Qwen3-ASR and Phi-4 match or slightly beat Whisper large-v3 on Indian
  English. The gap has closed; it has not reversed.
- **"Clean the audio before recognition."** Enhancement before ASR usually hurts. In one
  study, denoising made every recogniser worse in all 40 configurations tested. **Do not
  feed the enhancement pipeline's output to ASR by default.**
- **"A rented GPU makes the corpus nearly free."** Nearly, but the $3–15 estimates leave
  out uploading ~3,450 hours of mp3, pod setup, scoring and alignment. See the cost section.

## Sanskrit: retrieve the verse, don't recognise it

Nothing open recognises chanted Sanskrit well. The best self-reported chant figure is
Su-śrotā's CER of ~6%, which is still ~46% of words wrong. Its authors draw the useful
lesson: **"for chant practice we know the target text, so the problem is verification,
not recognition."**

That applies here, for two reasons:

- **Each catalogue entry names its verse** (e.g. `19890310 SB4.20.28-29`).
- **Gour Govinda Swami quotes a finite canon:** Gītā, Bhāgavatam, Caitanya-caritāmṛta,
  Brahma-saṁhitā, Gauḍīya songs.

So a verse route could work like this:

1. Detect the chanted span.
2. Get a rough hypothesis (Su-śrotā, IndicConformer-sa, or Whisper with
   `language='sa'` as a zero-cost control).
3. Match it against a bank of verse texts.
4. Publish the **canonical IAST text**.
5. Force-align that text to the audio for word timings.

This fixes verses; it does not fix Sanskrit *names inside English sentences*. Those need
the English model and, at most, the suggestion-only glossary pass from the eight-point
findings (about 2 points).

The supporting pieces exist and are permissive:
[indic_transliteration](https://github.com/indic-transliteration/indic_transliteration_py)
(MIT) converts Devanagari to IAST, and the archive's ṁ convention needs a small post-map.
For finding verse spans, off-the-shelf language ID is weak: VoxLingua107 includes Sanskrit
but warns about accented speech, and it has no Odia. The better approach is a small
classifier trained on the Melbourne reference's own labelled verse spans.

## Timestamps for corrected text (the stage we had not costed)

Corrected text has no word times, so it has to be force-aligned back to the audio **cue by
cue, never the whole hour in one pass**. A whole-hour pass with torchaudio-style Viterbi
needs ~47 GB per hour of audio.

| aligner | licence | notes |
|---|---|---|
| Montreal Forced Aligner 3.x | MIT | Most accurate on English word boundaries (~22 ms on Buckeye); fast on CPU; wants segments under 30 s; warns against noise and singing |
| ctc-forced-aligner + MMS | code BSD-2, **weights CC-BY-NC-4.0** | Many languages, romanised input. Its "star" token can mark untranscribed speech, which could also serve as a **dropped-speech detector** |
| Omnilingual CTC 300M + a Viterbi aligner | Apache-2.0 | The permissive route: its vocabulary includes IAST and Devanagari. torchaudio removed `forced_align` in 2.9, so pin an older torchaudio or use another Viterbi |
| WhisperX align | BSD-2 | Aligns pre-existing segments; its default English model is LibriSpeech-only |

**The NC question is yours to decide.** A free, non-commercial devotional archive may
well fall within CC-BY-NC; the sweeps treated it as disqualifying, and the verifier
disagreed.

All published aligner accuracies are on US English. The **~100 hand-marked word onsets**
recommended by the eight-point findings would let the aligners be compared on this
speaker.

## Dropped words: a second recogniser is the missing detector

The eight-point findings found no signal for dropped words (41% of errors). This survey
suggests two:

- **Two-family disagreement.** Run a cheap second model (Parakeet, at 5–8 times medium's
  speed) beside the main one and flag stretches where one has words and the other
  doesn't. This is the duplicate-tape diff idea from the handoff, done with models
  instead of tapes.
- **Speech coverage.** Speech found by Silero VAD but covered by no transcribed word,
  ranked per 15-second window. Score it against the 34% the gap-length signal achieved.

## Cost: laptop, rented GPU, or free GPU

These are planning estimates for ~3,450 audio hours (the 55-minute average is still a
guess):

| route | model | machine time | money |
|---|---|---|---|
| This laptop, CPU | faster-whisper medium | ~70 days | electricity |
| This laptop, CPU/iGPU | Parakeet TDT v2 | ~9–15 days (extrapolated from short clips) | electricity |
| RunPod community GPU (RTX A5000 $0.16/h, RTX 3090 $0.22/h, prices of 2026-09-13) | Parakeet TDT | ~13 GPU-hours | ~$3–7, **plus** uploading the audio and setup |
| RunPod community GPU | Whisper medium | ~150 GPU-hours | ~$34 |
| Kaggle free GPU (~30 h a week) | Parakeet TDT | ~2–3 weeks of weekly quota | free (estimate) |

The bake-off itself fits comfortably on the laptop.

## One precedent

No published ASR evaluation exists for ISKCON or Vaishnava discourse audio. The closest
analogue is Srila Prabhupada's archive: 2,400+ hours of 1966–77 tapes, transcribed by
humans and proofread by volunteers since 2014, with no ASR. The longest-term lever that
research on archival tapes points to is **fine-tuning on in-domain corrected text**
(−37% WER on 1969–83 dialect tapes). That becomes possible once a few dozen lectures are
corrected.

## Proposed bake-off (for the steward's approval)

Scoring: the existing harness, plus **dropped words and dropped runs of 5 s or more as the
headline metric**, CER on verse spans, and Sanskrit names inside English kept as their own
track. Score the exact runtime that would be deployed, because ports and quantisation have
dropped words that the reference implementations kept.

| stage | runs | install | disk | laptop time |
|---|---|---|---|---|
| A: Whisper controls | medium with `no_speech_threshold=None`; medium batched with fixed 30 s clips; `language='sa'` on the verse spans | none | none | ~1.5 h |
| B: Parakeet | TDT v2 and v3 via onnx-asr with Silero VAD chunks of 30 s or less | `onnx-asr` (pure-Python wheel) | ~1.3 GB int8, ~5 GB fp32 | ~20 min |
| C: Sanskrit verse spans | IndicConformer-sa via onnx-asr; Su-śrotā ONNX | none extra | ~0.3 GB | minutes |
| D: larger models | Qwen3-ASR 1.7B via the transcribe.cpp Windows binary; Whisper large-v3 overnight | transcribe.cpp CLI (20 MB) | ~5 GB | ~30 min + one night |

Models can be deleted after scoring to protect the 44 GB of free disk.
