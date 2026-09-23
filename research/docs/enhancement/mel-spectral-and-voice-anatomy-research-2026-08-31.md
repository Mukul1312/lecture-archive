# Deep Research: Mel-Spectral Processing and "Perfect Voice Anatomy" as a Route Past the Subtractive Ceiling

**Date:** 2026-08-31
**Question asked:** The pipeline uses DeepFilterNet3 and the claim "DFN3 is the best mechanism for
this type of enhancement" has never been properly tested. What about mel-spectral techniques? And
if we had a *perfect anatomy of the voice*, could mel-spectral processing enhance at peak capacity?
**Answer:** No — but the reason is not the one that seemed obvious, and the research produced one
concrete, code-verified finding that is worth more than the answer.

> **Evidence status:** Treat this as a dated research synthesis. `[CODE]` claims were checked
> against the machine's then-installed `.venv` copy of DeepFilterNet; `[SWEEP]` items remain
> explicitly unverified leads. The linked measurement record amends the causal interpretation and
> also states the remaining reproduction gap.

**Related:** [generative-restoration-research-2026-08-02.md](generative-restoration-research-2026-08-02.md) ·
[enhance-analysis-methodology-research-2026-07-31.md](enhance-analysis-methodology-research-2026-07-31.md) ·
[enhance-pipeline-research-2026-07-31.md](enhance-pipeline-research-2026-07-31.md)

> **Amended 2026-08-31** by
> [dfn3-multiframe-ceiling-measurements-2026-08-31.md](dfn3-multiframe-ceiling-measurements-2026-08-31.md),
> which measured what this document only reasoned about. One nuance to finding 16 — see the note
> there. No literature finding in this document is affected.

---

## How to read this document

This research ran as 8 parallel literature sweeps, 8 primary-source deep reads that checked the
sweeps (producing **135 corrections**), 1 completeness critic, and then 36 adversarial verification
agents applying three hostile lenses to each load-bearing claim: *does the source say this*, *does
it transfer to our conditions*, *is there contrary evidence*.

**Five claims were killed. Two of them had already been stated in conversation as headline
findings.** That failure rate is the single most important calibration fact here: treat any claim
below by its tag, not by how confident the prose sounds.

| Tag | Meaning |
|---|---|
| `[CODE]` | Verified first-party by reading the package installed in `.venv` on this machine |
| `[V3]` | Survived all three adversarial lenses |
| `[V1]` | Survived, but fewer than three lenses completed (session limits) — weaker |
| `[DR]` | Verified by a deep-read agent against the primary source, verbatim |
| `[SWEEP]` | Single-pass literature finding, **not** independently verified — treat as a lead |
| `[KILLED]` | Refuted by two or more lenses. Recorded because knowing what failed is the point |

---

## Executive Summary

The hypothesis maps onto a real, well-developed architecture family: predict a clean mel or SSL
representation from degraded input, then resynthesise a waveform with a neural vocoder. Miipher-2,
Sidon, AnyEnhance, MaskSR, UniPASE and SenSE are all instances. **That family does genuinely beat
the subtractive ceiling on perceptual quality — that half of the hypothesis is correct and
measured.** It beats it by *resynthesising* the voice rather than filtering it.

Three things make that trade unacceptable for this corpus, and one of them is decisive on its own.

**Mel is not a domain choice, it is a resynthesis.** A mel filterbank projects ~1025 linear STFT
bins onto 80–128 channels and discards phase entirely. Getting audio back requires a vocoder, so the
output waveform is generated, not filtered — which exits the multiplicative regime that
[generative-restoration-research](generative-restoration-research-2026-08-02.md) already ruled out
for an unverifiable low-resource-language archive.

**The round trip is not free, and it spends exactly the currency the identity gate measures.** Mel
copy-synthesis — analyse clean speech to mel, invert, *no enhancement at all* — costs 0.03–0.04
speaker similarity and 0.45 UTMOS `[DR]`. The ±0.03 identity tolerance would be spent before a
single dB of noise was removed.

**Phase is the bottleneck, and we already have the true phase.** The Vocos oracle ablation shows a
13.2M-parameter model given ground-truth *phase* beating a 112M-parameter vocoder on periodicity and
V/UV accuracy, while the same model given ground-truth *magnitude* is the worst row in the paper
`[DR]`. The original recording contains the true phase. A mel round trip throws it away and pays a
network to re-invent it. This is the sharpest single argument against the whole approach.

On the anatomy half: **"perfect voice anatomy" is not representable with current tools, and no
published system uses estimated anatomy as an enhancement prior**, so there is no ceiling to raise
`[SWEEP]`. More fundamentally, a prior gives you the *support* of the distribution, not the
*realization*. The measured damage (CPPS +3.9, HNR +3.0, Hammarberg +4.2) is loss of the
**stochastic component of the glottal source**. A perfect model of the speaker's glottis describes
the distribution of aperiodic energy it emits; it cannot tell you which sample it emitted in a given
20 ms frame. Closing that gap means generating, which means inventing.

**The finding that matters more than the answer:** reading the DeepFilterNet3 source installed on
this machine shows the measured voice damage is produced by the *deep filtering stage*, that
`--atten-lim` cannot reach it, and that the model authors' own high-SNR protection rule is absent
from the code path this pipeline uses. There is a one-flag experiment nobody has run.

---

## Key Findings

### On the mel-spectral hypothesis

1. **Mel copy-synthesis measurably costs speaker similarity, with zero enhancement applied.** `[DR]` `[V1]`
   F5-TTS Tables 1–2 and 5, Vocos 24 kHz: ΔSIM-o **−0.03** on LibriSpeech-PC test-clean and Seed-TTS
   test-en, **−0.04** on test-zh; UTMOS **4.09 → 3.64 (−0.45)** on LibriSpeech-PC. SIM-o is a
   cross-utterance same-speaker cosine, structurally analogous to (but not numerically comparable
   with) the 0.936 d-vector anchor used here.
   *Caveat:* two of three verification lenses were lost to session limits. Single paper, single
   vocoder, single speaker encoder, English/Chinese read speech.

2. **Out-of-distribution vocoding is far worse, and the OOD case is the one that matches this
   corpus.** `[DR]` Communications Medicine 2024, "Only HiFi-GAN" condition — pure mel
   copy-synthesis with a LibriTTS-trained (healthy English) vocoder applied to German pathological
   speech, a double distribution shift structurally identical to English-vocoder-on-Odia.
   Speaker-verification EER rose 4–5×: dysarthria 1.80% → 7.48%; dysglossia 1.78% → 11.39%;
   dysphonia 2.19% → 11.27%; cleft lip/palate 7.01% → 23.45%. Pathology-detection AUROC also
   degraded significantly (CLP 96.44 → 90.50, p=3.1e-56).

3. **Phase, not magnitude, is the bottleneck of time-frequency vocoding.** `[DR]`
   *Revisiting Vocos* (arXiv 2607.24323) oracle ablation: Vocos-Mag (13.2M params, given true phase)
   reaches SCOREQ .073, V/UV F1 .987, periodicity RMSE .0273 — outperforming the 112M BigVGANv2
   (.092 / .967 / .0665). Vocos-Phase (given true magnitude, predicting phase) is the worst row in
   the paper (SCOREQ .495). **A masking method that keeps original phase sits on the good side of
   this ablation; a vocoder sits on the bad side.**

4. **The mel-domain ceiling is lower than the input, not higher.** `[SWEEP]`
   Feeding a vocoder the *ground-truth clean mel* is a hard upper bound on the whole family.
   Mel-McNet (Interspeech 2025) reports "Clean Mel + Vocos" at WB-PESQ **3.63 vs 4.50** for clean
   speech, STOI 97.7% vs 100%. VoiceFixer's "Oracle-Mel" row at 44.1 kHz/128 mel is worse:
   PESQ-wb 2.52 vs 4.64 target, SI-SNR **−17.52 dB**. A multiplicative pipeline's ceiling is the
   input itself.

5. **No mel-domain speech enhancement system operates at 48 kHz.** `[SWEEP]`
   Published mel-domain SE is 16 kHz (CleanMel, Mel-FullSubNet, Mel-McNet, Fast FullSubNet) or
   44.1 kHz (VoiceFixer). Any 48 kHz mel pipeline built here would be unprecedented, not merely
   untested. Recorded as a "could not find", which is itself the finding.

6. **Nobody has measured what a vocoder does to the aperiodic voice-quality features this project
   tracks.** `[SWEEP]` No study reporting CPPS, HNR, H1–H2, jitter or shimmer through a vocoder
   round trip was located. Robust MelGAN states that GAN vocoders do not separate periodic from
   aperiodic components and re-render aperiodic energy as harmonic structure — the same direction as
   the DFN3 damage signature, not a fix for it. The instruments in `vq_feats` may be genuinely novel
   here.

### On the "perfect voice anatomy" hypothesis

7. **The best published *physical* voice anatomy captures roughly half a speaker embedding.** `[SWEEP]`
   Huckvale (2025): 9 interpretable parameters including estimated vocal tract length, glottal noise
   energy, spectral slope, F0 median and IQR, over 9,836 speakers, reconstructs a 256-d speaker
   embedding to a mean cosine distance of **0.354** (~7 principal components, ~50% of variance).
   Half the voice is not in the anatomy — and the embedding it fails to reconstruct is itself only a
   partial description of identity.

8. **Glottal inverse filtering is unreliable in this recording's conditions.** `[SWEEP]`
   Best case (OPENGLOT Repository I: synthetic 8 kHz vowels, noiseless, ground-truth glottal flow
   known, parameters grid-searched per signal against that ground truth) — QCP still has 4.89%
   median RMS waveform error, IAIF 13.45%. Under codec degradation (Narendra et al., Interspeech
   2017, AMR narrowband): NAQ *relative* error 0.812–0.933, H1H2 error ~5.2–5.5 dB.
   **Do not compare these figures directly to the CPPS/HNR/Hammarberg damage signature** — a deep
   read explicitly flagged that as an invalid comparison (different quantities, different
   conditions; AMR is a CELP codec while this source is 64 kbps MP3 transform coding). The
   defensible statement is only that GIF degrades badly under codec, noise and reverberation.

9. **The vocal-tract inverse problem is formally ill-posed.** `[SWEEP]` Sondhi (1979): the transfer
   function of even a lossless tract does not uniquely specify the area function, and the speech
   wave does not uniquely specify the transfer function. Reliable recovery requires an *external*
   driving-point measurement at the lips — impossible on an archival recording.

10. **No published system uses estimated voice anatomy as an enhancement prior.** `[SWEEP]`
    Searched for directly. There is no ceiling to raise because nobody has built the thing.

11. **A prior gives the support, not the realization.** `[SWEEP]` — *conceptual; flagged as
    inference, not published result.* A perfect anatomy model sharpens p(X), reducing epistemic
    uncertainty. What remains when speech and noise energy are comparable in a T-F cell is aleatoric.
    Sampling from that posterior yields a plausible realization, not *the* realization.
    **Note:** a deep read flagged the specific epistemic/aleatoric attribution as "INVENTED MAPPING —
    nowhere in the cited source." The intuition may be right; the citation was not.

### On the already-built version: personalized speech enhancement

12. **Personalized SE gain comes from rejecting another talker and collapses toward zero for
    non-speech noise.** `[SWEEP]`, four independent confirmations: pDeepFilterNet2 ("on the pn
    subset, both models achieve the same PESQ"), Eskimez et al., SEF-PNet (1-speaker+noise: SI-SDR
    14.49 → 14.50), and the cross-attention PSE paper. **This source has no interfering talker at
    all** — the one condition where the method earns its keep is absent.
    *Caveat:* the deep read found several supporting numbers overstated or resting on box plots
    rather than published values. The *direction* held across four sources; individual figures did not.

13. **Mainstream personalized SE is discriminative and mask-based**, so it structurally cannot
    invent a word `[SWEEP]`. If speaker conditioning were ever adopted here, this is the safe family.

### On DeepFilterNet3's actual structure — the code-verified section

14. **DFN3 contains no cross-frequency term anywhere.** `[CODE]` `[contested 1/2; corrected form survives]`
    `.venv/Lib/site-packages/df/multiframe.py:136` —
    `torch.einsum("...tfn,...ntf->...tf", spec, coefs)` contracts over the tap index `n` at fixed
    `t` and `f`; `spec_unfold` unfolds on dim 2 (time). Bins 0–95 get a 5-tap complex filter along
    **time only**; bins 96+ get a real sigmoid ERB gain in (0,1).
    Shipped config (independently read by a verifier from `models/DeepFilterNet3.zip`):
    `sr=48000, fft_size=960` → 50 Hz/bin, `nb_df=96` → **exactly 4800 Hz**, `df_order=5`,
    `df_lookahead=2`, `mask_pf=False`.
    **Consequences:** no energy moves between frequency bins; an exactly-zero bin stays exactly zero
    under any `--atten-lim`; the dead band above 7.0–7.2 kHz can never be filled; any output content
    in a bin derives from that same bin within a 5-tap (±2 frame, ~40 ms tap span, ~60 ms signal
    support) window. **The no-hallucination requirement is provable from the shipped code.**

15. **The magnitude bound is FALSE.** `[CODE]` A tempting claim — `|Y(t,f)| ≤ √2·Σ|X(t−i+l,f)|` —
    does not hold. `DfDecoder.forward` returns `self.df_out(c) + c0`; only the first term is
    tanh-bounded, while `c0 = self.df_convp(c0)` is a `Conv2dNormAct` whose default
    `activation_layer` is `ReLU`, unbounded above. **The support guarantee survives; the magnitude
    guarantee does not.** Recorded because this was nearly reported as a headline finding.

16. **The measured damage is produced by the deep-filtering stage, and no attenuation knob reaches
    it.** `[CODE]` `[V1]`
    `.venv/Lib/site-packages/df/deepfilternet3.py:442-443`:
    ```python
    spec_e = self.df_op(spec.clone(), df_coefs)
    spec_e[..., self.nb_df :, :] = spec_m[..., self.nb_df :, :]
    ```
    Below 4.8 kHz the output is **the deep filter applied to the noisy spectrum**; the ERB mask only
    overwrites bins ≥ 96. CPPS, HNR and the Hammarberg index are all computed below 5 kHz.
    Therefore CPPS +3.9 / HNR +3.0 / Hammarberg +4.2 is attributable to the DF stage alone.
    The DFN3 paper states the second stage exists *"to enhance the periodic components of speech"* —
    the damage signature is that stage working exactly as designed.

    > **Amendment 2026-08-31.** The code facts above stand — the DF operator does produce the entire
    > output below 4.8 kHz, and no ERB knob reaches it. But the implication that the deep filter's
    > *separation mechanism* is what damages the voice is **not supported by measurement**. An oracle
    > multi-frame Wiener sweep puts the DF stage's contribution over a plain pointwise mask at only
    > **+0.27 dB** of a +2.87 dB total, and it treats periodic and aperiodic content similarly
    > (+0.38 vs +0.24 dB). The damage is a **sorting** effect happening upstream of the filtering,
    > not a filtering artefact. See
    > [dfn3-multiframe-ceiling-measurements-2026-08-31.md](dfn3-multiframe-ceiling-measurements-2026-08-31.md).

17. **`--atten-lim` is an output-level convex blend, not a mask floor.** `[CODE]`
    `.venv/Lib/site-packages/df/enhance.py:237-238`:
    `if atten_lim_db is not None and abs(atten_lim_db) > 0: lim = 10 ** (-abs(atten_lim_db) / 20)`.
    At D30 that is `lim = 0.0316`. It scales the finished result toward dry; it does not change what
    the DF stage did to the texture. Separately, `Mask.forward(spec, mask, atten_lim=None)` accepts a
    mask-level clamp — but **nothing in the package ever passes it**. That path is dead code.

18. **The authors' high-SNR protection rule is absent from the code path this pipeline uses.** `[CODE]`
    The DFN3 paper documents: predict local SNR ξ ∈ [−15, 35] dB per frame, and at
    **ξ > 20 dB "Disable DF decoder. Only low noise condition, enhancing the periodicity is not
    necessary."** That rule lives in the Rust runtime (`libDF/src/tract.rs`). `DfNet.forward` in
    `df/deepfilternet3.py` contains **no such gate** — its only `lsnr` branch is
    `if self.lsnr_droput:` thresholding at `lsnr.squeeze() > -10.0`, and `LSNR_DROPOUT` defaults to
    `False`. `df/enhance.py` calls the model directly and never gates.
    **This pipeline runs the Python path:** `.venv/Scripts/deepFilter.exe` is a Python console-script
    wrapper containing `from df.enhance import run`.

19. **`run_df=False` is supported and is a one-flag experiment.** `[CODE]`
    `deepfilternet3.py:382-384` logs `"Running without DF stage"`; line 446 sets `spec_e = spec_m`,
    i.e. the pure ERB mask everywhere — strictly attenuating, phase-preserving, per-bin gain in
    (0,1). **This is the stage that structurally cannot produce the measured damage signature.**

### On the field's own record

20. **Noise suppression improves BAK and does not improve SIG.** `[V3]`
    ICASSP 2023 Speech Signal Improvement Challenge announcement, verbatim:
    > "For example, in the ICASSP 2022 Deep Noise Suppression challenge, the improvement in the
    > background (BAK) and overall (OVRL) quality is impressive, but the improvement in the speech
    > signal (SIG) is statistically zero."

    Braun & Gamper (arXiv 2111.11606), CRUSE with L²⁰_SD loss: **ΔSIG −0.17, ΔBAK +1.98, ΔOVL +0.85**.

    **Four corrections the verifiers forced:**
    (a) the correct challenge paper is **arXiv 2303.06566** (Cutler et al., Speech Signal
    Improvement), *not* arXiv 2303.11510 (which is the ICASSP 2023 DNS challenge and contains
    neither phrase);
    (b) the peer-reviewed paper uses the softer "not statistically significant";
    (c) **this is a property of noise-suppression objectives, not a law** — the same SSI challenge
    reports "The top entries improved SIG by DMOS > 0.6, unlike previous DNS challenges" — but those
    gains came from *generative resynthesis*, which is excluded here. For a discriminative denoiser
    like DFN3 the flat-or-negative SIG expectation applies directly;
    (d) the CRUSE deltas are 16 kHz on DNS3 and are quoted by Braun & Gamper from their reference
    [24], not measured in that paper. **Do not carry −0.17/+1.98 across as an expected trade** — at
    an 18–26 dB margin the achievable BAK gain is a fraction of that while the SIG risk is
    undiminished, so the trade here is *worse* than in the literature, not equivalent.

21. **IASA-TC 03 v4 governs what may be shipped.** `[V3]`
    > "Above all, subjective alterations or 'improvements', such as de-noising … must be avoided.
    > Subjective alterations effectively rewrite the historical document according to the
    > perspective of the operator undertaking the change."

    And: unintended artefacts (noise, distortion, drop-outs) "are also part of it". TC-03 permits
    subjective modification **only of access copies, never the archival master**, and only with full
    documentation of every parameter.
    **Implication:** retaining the unprocessed 48 kHz decode is correct and is the preservation
    master. The FLAC currently described as an "archival master" is an **access copy** and should be
    labelled as such.

---

## What was killed, and why

This section is as valuable as the findings. Each of these was stated confidently before verification.

### KILLED — "At an 18–26 dB margin the oracle mask is a near no-op, so there is no headroom"

The argument was: the ideal ratio mask gain at 20 dB SNR is 0.995 (−0.043 dB), therefore the optimal
amount of processing inside the speech is near zero, therefore any audible processing is already
*past* the oracle and no better prior can help.

**Refuted 3/3.** The arithmetic is correct — verified numerically against Wang, Narayanan & Wang
(2014) Eq. (3) with β=0.5. The *substitution* is a category error. The paper defines `SNR(t,f)` as
**the local SNR within a single T-F unit**; this project's 18–26 dB is a **global broadband
margin**. Kjems et al. (JASA 126(3):1415–1426, 2009 — same senior author) established that the ideal
mask depends only on `RC = LC − mixture SNR`, so **raising global SNR rigidly translates the local
SNR distribution rather than compressing it**. Measured spread for speech-shaped noise is roughly
43 dB (RC = +12.7 dB at 1.5% ones, −30.3 dB at 80% ones). Plenty of T-F cells still sit at low local
SNR at a 20 dB global margin, and the mask is genuinely doing work there.

A second break: above the 7.0–7.2 kHz codec cutoff, speech energy is ~zero while noise is not, so
local SNR there is strongly negative and the oracle IRM approaches 0 — *maximal* attenuation, the
exact opposite of "do nearly nothing".

**Lesson: never substitute a global margin into a per-bin formula.** This error recurs; guard against it.

### KILLED — "No published evaluation of a modern enhancer exists at 18–26 dB input SNR"

**Refuted 3/3, and by its own citation.** The Interspeech 2020 DNS Challenge paper states synthetic
test clips were mixed at "SNR levels … sampled from a uniform distribution between 0 dB and 25 dB"
(training 0–40 dB). A uniform 0–25 dB draw puts ~28% of clips at ≥18 dB. Zhang, Shen & Williamson
(ICASSP 2019) built a dataset specifically because "only a narrow range of SNRs are used" and
published a per-SNR PESQ table **with a dedicated 20 dB column**. The VoiceBank-DEMAND half was
correct (test SNRs 17.5/12.5/7.5/2.5 dB) but proves less than claimed — 17.5 dB is 0.5 dB below this
project's band, not "far below".

Additional strike: DeepFilterNet is trained on the full multilingual DNS4 set, which mixes up to
25 dB, and the architecture carries an explicit named branch for ξ > 20 dB. The field is not blind
to this regime.

### KILLED — "Personalization helps only small models and hurts large ones"

**Refuted 3/3.** The Sivaraman & Kim quote is verbatim genuine ("10.28 vs. 11.23") but is scoped to
**one method (plain PseudoSE) in the zero-shot context**. Three paragraphs later, same figure, same
largest model: CM personalization 11.06 and PseudoSE+DP 10.91 against the 11.23 generalist —
effectively parity — and in the few-shot context personalized large models *beat* the generalist
(11.37 vs 11.08). Stripping the possessive "PseudoSE's" promoted a finding about one pretext task
into a claim about personalization in general.

**Corrected position:** personalization is not harmful. It is simply not aimed at this problem,
because there is no interfering talker (see finding 12).

### KILLED — "The pitch-scaled harmonic filter is the missing instrument"

**Refuted 2/3 on misquoted numbers.** Jackson & Shadle (IEEE TSAP 9(7):713–726, 2001) is a real,
correctly-attributed paper and the mechanism description is verbatim accurate. But the claimed
"+5 dB HNR for the aperiodic component" is wrong: the paper reports ξv = 5 dB for the *periodic*
part and **ξu = 15 dB for the aperiodic part**, and the aperiodic figure is an SER improvement that
**scales with the noise level** rather than a fixed gain. It is also **signal-adaptive, not linear** —
window length is re-optimised per frame by a pitch tracker, and pitch-tracker robustness is named as
a main limitation. Only the amplitude-based output pair partitions the input additively.

**Worth keeping on the list anyway**, for two reasons the verifiers explicitly conceded: the paper's
experiments ran at **48 kHz natively**, and PSHF has **no training set**, so the usual "16 kHz
English" and "Odia is out of distribution" objections both fail to apply. Re-evaluate on correct
numbers.

### KILLED — "Denoising speech while passing non-speech through bit-identical steps the noise floor"

**Refuted 3/3 on two independent grounds.** First, the cited remedy (Shin et al., Interspeech 2006,
residual noise shaping) contains **zero** occurrences of segment boundary, discontinuity, passthrough
or gating — its method applies a per-bin gain to every frame uniformly and has no passthrough branch,
so structurally it cannot address a join artifact. Second, **the pipeline already crossfades**:
`scripts/youtube_enhance/cli.py:107` sets `segment_fade_samples: 5760` = **120 ms** raised-cosine,
applied by `build_speech_mask` in `scripts/youtube_enhance/segments.py`.

Whether 120 ms is *enough* for a large noise-floor step at D30 remains an open, checkable question —
but the artifact was asserted without evidence and the citation did not support it.

---

## Contested claims

| Claim | Status | What survives |
|---|---|---|
| RemixIT-style adaptation buys BAK and pays in SIG (UDASE CHiME-5: unprocessed SIG-MOS 3.48 → RemixIT 3.26; BAK 2.92 → 3.64) | 1/3 refuted | Direction plausible; the real-recording numbers are the relevant ones. The simulated LibriCHiME-5 SI-SDR gains are a different measurement at 6.6 dB input SNR |
| WPE dereverberation needs no RT60 | 1/3 refuted | It needs no *RIR* and is blind — but NTT's own guidance sets prediction filter length **from** the reverberation time via `L ~ (M−1)/(P−1)`, which **degenerates at P=1** (single channel). An unresolved 0.5–1.5 s RT60 blocks correct configuration rather than being irrelevant to it. Also **not linear** — it is an iterative signal-adaptive estimator; the safety property is narrower: each output bin is the observation minus a linear combination of *that same signal's own delayed past frames*, so no external content can enter |
| DFN3 has no cross-frequency term | 1/2 refuted | Corrected form survives essentially as stated (finding 14). Independently confirmed against the shipped `config.ini` |

---

## The actionable finding

Findings 16–19 combine into something concrete and cheap.

**The damage is in the DF stage. `--atten-lim` cannot reach it. The authors wrote a protection rule
for high-SNR material. This pipeline runs the code path that omits it.**

Three steps, in order, none requiring a new model:

**1. Measure the local-SNR distribution.** `DfNet.forward` already **returns `lsnr`** as its third
output. Run one lecture, histogram the per-frame estimate, and see what fraction sits above the
20 dB threshold the authors wrote `run_df` protection for. This is free — the model computes it
regardless — and it is the missing evidence.

> **Do not skip to the conclusion here.** The ξ in the paper's rule is *local* per-frame SNR, not the
> global 18–26 dB margin. Claiming "the gate would fire everywhere on our material" would repeat
> exactly the category error that killed the IRM argument above. Measure it.

**2. Render `run_df=False` as a third candidate.** Pure ERB mask: strictly attenuating,
phase-preserving, per-bin gain in (0,1), no cross-frequency term, no periodicity enhancement. It is
architecturally incapable of producing the CPPS/HNR signature. Compare against D24 and D30.

**3. Actually run the gate on it.** `score_candidate_windows` in `scripts/youtube_enhance/gates.py`
computes `cpps_delta`, `hnr_delta`, `hammarberg_delta`, `spectral_tilt_delta`,
`parallel_mfcc_distance` and `pumping_index_delta` — every instrument needed to settle this.
**The D30 delivery path currently skips it entirely** (`scripts/youtube_enhance/local_d30.py` passes
`candidate_window_scores=[]`), and `_CANDIDATE_IDS` is still hardcoded to
`("original", "adaptive-22", "adaptive-24")`, so the shipping setting has never been scored on the
SIG axis.

**Judge on SIG-axis instruments, not noise-floor drop.** Finding 20 is the reason.

---

## Contrarian views and risks

- **Eight lanes all returned "no", which is itself suspicious.** The angles were framed by someone
  who already had a view. The deep reads and verifiers pushed back hard (135 corrections, 5 kills),
  which is partial protection, but the *framing* of the question was never adversarially tested. A
  genuinely independent pass might ask "under what conditions would mel-domain processing be right?"
  rather than "is it right here?"

- **The verification was only run on 12 claims.** The `[SWEEP]` findings — most of the anatomy
  section — carry the *unverified* single-pass error rate, which the deep reads suggest is high. Do
  not build on a `[SWEEP]` tag without checking it first.

- **Two verification lenses were lost to session limits** on `mel-roundtrip-identity-cost` and one on
  `dfn3-damage-in-df-stage`. Their `SURVIVES` status is weaker than the tag suggests. The DFN3 one is
  independently backed by first-party code reading; the mel one is not.

- **"DFN3 is best" is still not established, and this research did not test it.** It tested one
  *alternative family*. The matched-suppression comparison — fix noise-floor drop, compare damage
  across DFN3, Wiener-as, and multi-band spectral subtraction — remains the experiment that would
  actually settle the original claim, and it remains unrun. See
  [enhance-analysis-methodology-research-2026-07-31.md](enhance-analysis-methodology-research-2026-07-31.md)
  for why the classical family was represented only by its weakest member (`noisereduce` spectral
  gating) in the original bake-off.

- **The archival-ethics finding may be the most consequential and got the least attention.** If
  IASA-TC 03 is taken seriously, the question shifts from "how much enhancement" to "what is the
  access copy allowed to be, and is the preservation master properly documented". That is a policy
  decision, not a technical one.

- **84 hours of one speaker is a measurement asset, not a modelling asset.** The critic's assessment,
  and the personalization literature supports it. What it unambiguously buys: a noise PSD estimated
  from thousands of genuine pause frames rather than a running minimum-statistics tracker; a
  speaker-specific long-term average spectrum; and a held-out set large enough to make a paired
  listening test statistically meaningful. No published work fine-tunes DeepFilterNet on a single
  speaker — a genuine "could not find".

---

## Open questions

1. **What is the actual per-frame `lsnr` distribution on this material?** Free to measure, and it
   determines whether finding 18 is decisive or merely interesting.
2. **Does `run_df=False` reduce noise usefully at all?** The ERB stage alone may be too weak to be
   worth shipping. Unknown until rendered.
3. **Is 120 ms enough crossfade for the noise-floor step at D30?** The step size is measurable; the
   audibility is a listening question.
4. **Does the matched-suppression comparison change the DFN3 verdict?** Still the unrun experiment.
5. **What do the `vq_feats` measures do through a vocoder round trip?** Nobody has published this.
   Running it would be a genuinely novel contribution, and the harness already exists.
6. **Should the shipped FLAC be relabelled an access copy?** Policy question raised by finding 21.
7. **Was the 22/24 → 30 escalation ever justified by evidence?** Predates this research and remains
   unresolved; the design doc specifies 22 or 24 and `cli.py:598` hard-refuses anything else.

---

## Sources

**Verified against primary sources during this research:**

- [ICASSP 2023 Signal Processing Grand Challenges](https://2023.ieeeicassp.org/signal-processing-grand-challenges/) — the "SIG is statistically zero" statement, verbatim.
- [Cutler et al., ICASSP 2023 Speech Signal Improvement Challenge (arXiv 2303.06566)](https://arxiv.org/abs/2303.06566) — the peer-reviewed version; **use this, not 2303.11510**.
- [Braun & Gamper, "Effect of noise suppression losses on speech distortion and ASR performance" (arXiv 2111.11606)](https://arxiv.org/pdf/2111.11606) — CRUSE ΔSIG −0.17 / ΔBAK +1.98 / ΔOVL +0.85.
- [F5-TTS (arXiv 2410.06885)](https://ar5iv.labs.arxiv.org/html/2410.06885) — Tables 1, 2, 5: mel copy-synthesis SIM-o and UTMOS cost.
- [Speaker anonymization for pathological speech, Communications Medicine 2024, Table 2](https://www.nature.com/articles/s43856-024-00609-5/tables/2) — the "Only HiFi-GAN" out-of-distribution copy-synthesis result.
- [Revisiting Vocos (arXiv 2607.24323)](https://arxiv.org/html/2607.24323) — the oracle magnitude/phase ablation.
- [Wang, Narayanan & Wang, "On Training Targets for Supervised Speech Separation" (PMC4293540)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4293540/) — IRM definition; **the SNR is per-T-F-unit**.
- Kjems et al., JASA 126(3):1415–1426, 2009 — local SNR distribution shape invariance; ~43 dB spread.
- [Reddy et al., Interspeech 2020 DNS Challenge (arXiv 2005.13981)](https://arxiv.org/abs/2005.13981) — test clips uniform 0–25 dB SNR.
- Zhang, Shen & Williamson, ICASSP 2019 — per-SNR PESQ with a dedicated 20 dB column.
- [Sivaraman & Kim, IEEE JSTSP 16(6):1342–1356, 2022](https://minjekim.com/wp-content/uploads/jstsp2022_asivara.pdf) — personalization vs model capacity; read past the quoted sentence.
- [Jackson & Shadle, IEEE TSAP 9(7):713–726, 2001](https://personalpages.surrey.ac.uk/p.jackson/pub/t-sap01/JacksonShadle_T-SAP01_preprint.pdf) — PSHF; ξv = 5 dB, **ξu = 15 dB**.
- [Shin et al., Interspeech 2006, "Speech Enhancement based on Residual Noise Shaping"](https://www.isca-archive.org/interspeech_2006/shin06_interspeech.pdf) — real paper, but says nothing about segment boundaries.
- [IASA-TC 03 v4 §8](https://iasa-web.org/tc03/8-unmodified-transfer-new-target-format) — preservation master vs access copy.
- [DeepFilterNet3 (arXiv 2305.08227)](https://arxiv.org/abs/2305.08227) and [multiframe deep filtering (arXiv 2110.05588)](https://arxiv.org/abs/2110.05588) — architecture; the ξ > 20 dB rule.
- [DeepFilterNet source](https://github.com/Rikorose/DeepFilterNet) — and the copy installed at `.venv/Lib/site-packages/df/`, which is what every `[CODE]` claim here was read from.

**Single-pass, unverified (`[SWEEP]` — treat as leads):** Huckvale (2025) interpretable voice
parameters; OPENGLOT / QCP / IAIF glottal inverse filtering figures; Narendra et al. Interspeech 2017
codec degradation; Sondhi (1979); Mel-McNet and CleanMel; VoiceFixer Oracle-Mel; Miipher-2; Sidon;
AnyEnhance; UniPASE; StuPASE; SenSE; URGENT 2025 and 2026; pDeepFilterNet2; SEF-PNet;
VoiceFilter-Lite; Carbonneau et al. SSW 2025; RemixIT / UDASE CHiME-5.

---

## Rerun Inputs

```
tool: Workflow (Claude Code), two runs

run 1: 8 parallel research angles -> 8 primary-source deep reads -> completeness critic
       17 agents, 3.69M tokens, 627 tool calls, ~32 min
       angles: mel-domain SE; vocoder fidelity ceiling; voice anatomy / source-filter /
               glottal inverse filtering; speaker representations; personalized SE;
               hallucination-safe speaker-conditioned masking; theoretical limits;
               2025-2026 SOTA judged on identity preservation
       output: 135 corrections raised by the deep reads against the sweeps

run 2: 12 load-bearing claims x 3 adversarial lenses (source / transfer / contrary evidence)
       36 agents, 2.88M tokens, 579 tool calls, ~15 min, 5 agents lost to session limits
       result: 4 SURVIVES, 3 CONTESTED, 5 KILLED

search: Exa MCP (semantic, arXiv) + firecrawl CLI + WebFetch
code:   first-party reads of .venv/Lib/site-packages/df/ on this machine
```
