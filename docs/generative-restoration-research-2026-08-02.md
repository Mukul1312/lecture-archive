# Deep Research: Beyond DeepFilterNet — Generative Speech Restoration for the Jiva Seminar

**Date:** 2026-08-02
**Question:** We shipped DeepFilterNet3 `--atten-lim 24` (~21 dB reduction). Noise is still audible, ~0.17%
of the file is effectively digital silence, and the band-limit is untouched. Across everything we tried
the suppression-vs-damage trade-off was near-linear (r = −0.95) and **nothing beat the curve**. Do the
2025–2026 generative methods break it?

**Short answer: yes, they break the curve — and for *this* corpus that is exactly what makes them
dangerous.** The failure mode they introduce is invisible to every instrument we have and to the one
human we have.

**Related:** [enhance-analysis-methodology-research-2026-07-31.md](enhance-analysis-methodology-research-2026-07-31.md) · [odia-asr-and-intelligibility-metrics-2026-07-31.md](odia-asr-and-intelligibility-metrics-2026-07-31.md)

---

## Executive Summary

The curve we hit is real and it is a property of **subtractive** enhancement. Every method we tested —
DeepFilterNet at six attenuation levels, spectral gating, four stacked mild-pass combinations — removes
noise by *taking energy away*, and past a point the only energy left to take is the speaker's own
aperiodic texture. That is precisely what our Praat features measured: CPPS +3.9, HNR +3.0,
Hammarberg +4.2, i.e. a voice made more periodic and duller. Generative restoration escapes this by not
subtracting at all: it *resynthesises* speech conditioned on the degraded input. Google's Miipher-2
reports studio-quality output from noise, reverberation **and codec artifacts** at a real-time factor of
0.0078 — a million hours in three days. Its open reproduction, **Sidon**, is released, runs 500× faster
than real time on one GPU, and reaches comparable quality.

But the Interspeech 2025 URGENT challenge — the largest recent head-to-head, explicitly designed to test
universality and multilinguality — delivers a verdict that lands directly on our situation. **The winner
was purely discriminative.** The purely generative entrant scored **0.47 speaker similarity against 0.76
for the discriminative winner**, and **67.9% character accuracy against 79.8%**. It "occasionally
hallucinated spoken content, particularly under low-SNR conditions." Most damning for us: on Japanese,
*unseen in training*, its outputs "sometimes resembled English or other European languages," and
character accuracy collapsed to **36.8%** versus 68–74% for discriminative systems.

Our source is **Odia**. Sidon's own evaluation **excludes Odia** — the authors could not find a public
ASR supporting it. So Odia sits squarely in the unseen/low-resource regime where generative restoration
fails worst, and it fails by *inventing plausible speech*. Compounding this: the URGENT organisers
report that "non-intrusive metrics yielded high scores even when hallucinations occur" — meaning DNSMOS
and NISQA, the tools we would naturally reach for, **cannot detect the failure**. Neither can our
evaluator, who does not speak Odia. Neither can ASR round-trip, which we already ruled out. A generative
model could substitute fluent-sounding syllables into a spiritual teacher's lecture and **no instrument
or person currently in our loop would notice.**

That is not a reason to never use generative methods here. It is a reason that the gate must come first.

---

## Key Findings

1. **The curve we hit is a property of subtractive methods, not of enhancement in general.** Generative
   models resynthesise rather than attenuate, so they are not bound by "the only energy left to remove is
   his voice." This is the real answer to why nothing we tried beat the trade-off.

2. **URGENT 2025: the winner was purely discriminative** — a sub-band RNN, ~102M parameters. "Most other
   competitive ones are hybrid methods." Discriminative models led on intrusive metrics (PESQ, ESTOI);
   generative led on subjective MOS. ([arXiv 2505.23212](https://arxiv.org/html/2505.23212v2))

3. **Generative cost, quantified on the same benchmark:**

   | System | Character accuracy | Speaker similarity |
   |---|---|---|
   | T1 (discriminative) | **79.80%** | **0.76** |
   | T2–T5 (hybrid) | 76–78% | 0.74 |
   | T13 (purely generative) | **67.87%** | **0.47** |

   Generative roughly **halved speaker similarity** — the exact axis our evaluator vetoed on.

4. **Hallucination is documented, not hypothetical.** T13 "occasionally hallucinated spoken content,
   particularly under low-SNR conditions."

5. **The failure is language-dependent and worst on unseen languages.** On Japanese (unseen), T13's
   outputs "sometimes resembled English or other European languages that dominated the training data,"
   and character accuracy fell to **36.8%** vs 68–74% for discriminative models. The organisers state
   plainly that "purely generative SE models can exhibit language dependency."

6. **Our quality metrics would not catch it.** URGENT organisers: "non-intrusive metrics yielded high
   scores even when hallucinations occur," and they call for "a new subjective listening protocol, which
   takes into account spoken content and/or speaker consistency." DNSMOS and NISQA are exactly the
   non-intrusive metrics in question.

7. **Miipher-2 (Google) is the quality ceiling — and unavailable.** Frozen 2B-parameter USM encoder +
   20M adapters + WaveFit vocoder; fixes noise, reverberation and codec artifacts; RTF 0.0078. Speaker
   similarity 0.744 (English), 0.569–0.738 on unseen languages. **"The code and checkpoints will not be
   released due to potential misuse risks."** ([arXiv 2505.04457](https://arxiv.org/html/2505.04457v1))

8. **Sidon is the open reproduction and is genuinely usable** — restoration "comparable to Miipher,"
   100+ languages, **500× faster than real time on a single GPU**, code and model released
   (`hf.co/spaces/Wataru/SidonSamples`). TTS trained on Sidon-cleaned data scored MOS 4.248 vs 3.254 on
   the original noisy data. ([arXiv 2509.17052](https://arxiv.org/html/2509.17052v2))

9. **Sidon explicitly excludes Odia.** It evaluates on FLEURS-R subsets only, having "could not find any
   publicly available ASR models supporting" `or_in`. **Odia performance is entirely unvalidated** — and
   this is the same wall we hit in the intelligibility research.

10. **AnyEnhance is the most identity-preserving generative option found.** Masked generative model with
    two mechanisms aimed at our exact problem: **prompt-guidance** (feed 3 s of the target speaker's
    audio to steer timbre) and a **self-critic** head. Speaker similarity **0.955**, rising to **0.963
    with prompt** — far above URGENT's generative entrant. Open source
    ([GitHub](https://github.com/viewfinder-annn/anyenhance-v1-ccf-aatc)), 363.5M params, RTF 0.254, and
    it does super-resolution from 2–8 kHz input to 44.1 kHz. ([arXiv 2501.15417](https://arxiv.org/html/2501.15417v3))
    **But** its evaluation is English and Mandarin only; no low-resource language results, and
    hallucination is not discussed.

11. **Apollo targets our exact codec problem but is music-only.** Trained on MP3 at 24/32/48/**64**/96/128
    kbps — our source is 64 kbps. Tiny (16.5M params), fast (53 ms per second of audio on GPU), open
    source. But evaluated solely on MUSDB18-HQ/MoisesDB; "applicability to speech remains undocumented."
    ([arXiv 2409.08514](https://arxiv.org/html/2409.08514v1))

12. **The field is moving to flow matching and few-step diffusion**, which mainly buys *speed* rather
    than fixing the identity problem: DriftSE, FlowSE, FLowHigh, Stream FM, Real-time Flow, SAGA-SR.
    A 2026 survey frames diffusion as "state-of-the-art across a wide range of audio generation and
    restoration tasks." ([survey arXiv 2605.16681](https://arxiv.org/html/2605.16681v1))

---

## Detailed Analysis

### Why generative breaks the curve

Subtractive enhancement estimates a mask and multiplies. At high attenuation the mask necessarily
suppresses low-energy, noise-like components — which in speech are breath, fricative turbulence, and
glottal aperiodicity. Those are not noise; they are what makes a voice sound like a person. Our Praat
measurements caught this directly (CPPS and HNR *rising* = the residual became too periodic).

A generative model conditioned on degraded input predicts clean speech tokens or a clean waveform. It can
output a breathy, textured voice in a quiet room because it *generates* the texture rather than trying to
keep it while removing everything around it. That is a genuinely different operating point, not a better
setting on the same dial.

The cost is that what it generates is a *plausible* reconstruction, not necessarily *the* reconstruction.

### Why our corpus is the worst case for that cost

Three properties stack badly:

| Property | Consequence |
|---|---|
| **Odia, low-resource** | The regime where URGENT measured 36.8% character accuracy and cross-language leakage |
| **Evaluator doesn't speak Odia** | Word substitution is undetectable by our human |
| **No working Odia ASR** | Already established; round-trip WER independently invalid |
| **Devotional content** | A substituted word in a spiritual teacher's discourse is a different class of error from a substituted word in a podcast |

Add the URGENT finding that non-intrusive metrics score hallucinated audio *highly*, and the situation is
that we would have no detector at all. The one instrument that *would* fire is our own anchored d-vector
gate — a 0.47-style identity drop would be unmissable against our 0.937 anchor. That is worth stating as
a positive: **the gate we built for the DeepFilterNet work is the right screen for this risk too.**

### What is actually worth trying, in order

1. **AnyEnhance with prompt-guidance.** It is the only option found that *explicitly conditions on the
   target speaker*, and its 0.955–0.963 speaker similarity is in a different class from URGENT's 0.47.
   Open, 363M params, runs faster than real time. The prompt would be a clean 3-second excerpt of the
   Swami's own voice — which we have in abundance.
2. **Sidon**, as the Miipher-class baseline. Open, fast, multilingual — with the explicit caveat that
   Odia is unvalidated and must be treated as an experiment, not a pipeline.
3. **Apollo** for codec artifacts only. Cheapest to try (16.5M params), targets 64 kbps MP3 precisely,
   but is music-trained and speech-unvalidated. Low cost, unknown payoff.
4. **Bandwidth extension: hold.** Our earlier research already flagged that the 6.8–7 kHz limit "may
   actually be fine for listening" and that fake harmonics sound "digital and detached." Nothing found
   here changes that, and it adds a second generative risk on top of the first.

### What this does *not* justify

Replacing the shipped DeepFilterNet pipeline. It is measured, it is bounded, it cannot invent words, and
the setting was chosen by two humans. Generative restoration is an experiment to run **beside** it on the
5-minute segment, gated by the same anchored test and an Odia ear, not a swap.

---

## Contrarian Views and Risks

- **URGENT's generative entrant may not represent the best available.** T13 is one system; AnyEnhance's
  reported 0.955 SIM suggests prompt-conditioned models behave far better on identity. Judging all
  generative methods by T13 would be unfair. The *language-dependency* finding is the durable one, and it
  is an argument about training-data coverage that applies to any model — including AnyEnhance, whose
  evaluation contains no low-resource language at all.

- **Speaker similarity numbers are not comparable across papers.** URGENT's 0.76/0.47, Miipher-2's 0.744,
  AnyEnhance's 0.955 use different encoders (CAM++, WavLM, unspecified) and different test sets. Only
  within-paper comparisons are meaningful. Our own 0.937 anchor is on yet another encoder and is **not**
  comparable to any of them — it is only comparable to our own measurements. This is the same
  "thresholds don't transfer" lesson from the earlier reuse analysis.

- **"Studio quality" is a TTS-corpus goal, not a devotional-listening goal.** Miipher and Sidon exist to
  clean training data for speech synthesis, where the target is a neutral studio sound. For an archival
  lecture the room *is* part of the record. A model optimised to erase it may be solving a different
  problem from ours.

- **Authenticity.** Subtractive enhancement removes what was added by the recording chain; generative
  restoration produces audio the microphone never captured. For a religious teacher's recorded discourse
  that is arguably a change in the nature of the artefact, not just its quality. This is a judgement call
  for the project, not a technical finding — but it should be a conscious one, and it argues for keeping
  the FLAC of the subtractive version as the archival master regardless of what else we do.

- **Reading limits, stated honestly.** I gathered sources via Firecrawl search and read the primary
  papers (Miipher-2, URGENT 2025, Sidon, AnyEnhance, Apollo) through targeted page-level extraction
  rather than reading each paper end to end myself. The specific figures quoted (0.47/0.76 SpkSim,
  36.8% CAcc, 0.955 SIM, RTF values) come from that extraction and I have **not** independently verified
  them against the PDFs. Treat them as well-sourced but single-pass. Licences for AnyEnhance and Apollo
  are not stated in their papers and need checking in the repos before any use. I did not investigate
  dereverberation-specific 2025–2026 methods in depth — the RT60 question remains open from the earlier
  research and nothing here resolves it.

---

## Open Questions

1. **Does AnyEnhance's prompt-guidance actually hold identity on Odia?** Its 0.963 is English/Mandarin.
   Testable directly on our 5-minute segment with our existing gate.
2. **Does any of these preserve the aperiodic texture our Praat features track?** No paper reports CPPS,
   HNR or spectral tilt. Our `vq_feats` pipeline can measure it — this may be a genuinely novel check.
3. **Would generative restoration substitute words in Odia specifically?** The Japanese result says it
   can happen; only an Odia listener can tell us whether it does here.
4. **Is Apollo useful on speech at 64 kbps?** Undocumented, cheap to find out.
5. **Does the room tone matter to the listeners?** If devotees value the sense of presence, "studio
   quality" may be the wrong target entirely — and that reframes the whole project.

---

## Sources

- [Interspeech 2025 URGENT Speech Enhancement Challenge (arXiv 2505.23212)](https://arxiv.org/html/2505.23212v2) — discriminative winner; generative SpkSim 0.47 vs 0.76, CAcc 67.9% vs 79.8%; hallucination; 36.8% CAcc on unseen Japanese; non-intrusive metrics miss hallucination. **The decisive source.**
- [URGENT challenge site](https://urgent-challenge.github.io/urgent2025/) — challenge design: 7 distortion types, multilingual, explicitly probing generative language dependency.
- [Miipher-2 (arXiv 2505.04457)](https://arxiv.org/html/2505.04457v1) — 2B USM + 20M adapters + WaveFit; RTF 0.0078; SpkSim 0.744 EN / 0.569–0.738 unseen; **checkpoints not released**.
- [Sidon (arXiv 2509.17052)](https://arxiv.org/html/2509.17052v2) — open Miipher-class restoration, 100+ languages, 500× real time, code released; **Odia explicitly excluded from evaluation**.
- [AnyEnhance (arXiv 2501.15417)](https://arxiv.org/html/2501.15417v3) — prompt-guidance + self-critic; SIM 0.955/0.963; 363.5M params; RTF 0.254; super-resolution 2–8 kHz → 44.1 kHz; English/Mandarin evaluation only.
- [Apollo (arXiv 2409.08514)](https://arxiv.org/html/2409.08514v1) — MP3 codec restoration trained at 24–128 kbps incl. 64; 16.5M params; music-only evaluation.
- [Survey of Audio Super-Resolution and Restoration (arXiv 2605.16681)](https://arxiv.org/html/2605.16681v1) — flow-matching/diffusion landscape: FLowHigh, GSFM, SAGA-SR, Stream FM, Real-time Flow.
- [Rethinking Flow and Diffusion Bridge Models for SE (arXiv 2602.18355)](https://arxiv.org/html/2602.18355v1) and [DriftSE (arXiv 2604.24199)](https://arxiv.org/html/2604.24199v2) — current generative SE direction.
- [SenSE: Semantic-Aware High-Fidelity Universal SE (arXiv 2509.24708)](https://arxiv.org/html/2509.24708v1) — semantic conditioning as a hallucination guard (not read in depth).
- [Analyzing and Improving Speaker Similarity Assessment (arXiv 2507.02176)](https://arxiv.org/html/2507.02176v1) — ASV embeddings neglect dynamic identity; proposes U3D rhythm metric. Relevant caveat on our own d-vector gate.
- [FlowSE (arXiv 2505.19476)](https://arxiv.org/html/2505.19476v1) — flow-matching SE reporting WeSpeaker cosine similarity for identity preservation.
- [USEMamba / Universal SE with Regression and Generative (Interspeech 2025)](https://www.isca-archive.org/interspeech_2025/chao25b_interspeech.pdf) — hybrid: generative variant "able to mitigate such artifacts by inferring the missing content".

## Rerun Inputs

```
workflow: firecrawl-deep-research
topic: generative/restorative speech enhancement beyond DeepFilterNet3 for archival low-bitrate
       Odia spiritual lectures; whether generative methods break the suppression-vs-identity
       trade-off, and their hallucination/identity risks on low-resource languages
depth: exhaustive
output: markdown
```
