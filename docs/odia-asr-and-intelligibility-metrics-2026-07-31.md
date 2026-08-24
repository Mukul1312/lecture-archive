# Deep Research: Odia ASR Models + Measuring Intelligibility Damage Without a Speaker of the Language

**Date:** 2026-07-31
**Trigger:** The evaluator does not speak Odia. He can judge timbre and accent, but cannot tell whether
denoising has eaten words. I proposed ASR round-trip WER to fill that gap and started building it.
**Verdict: that plan was invalid, and the literature says so unambiguously.**

**Related:** [enhance-analysis-methodology-research-2026-07-31.md](enhance-analysis-methodology-research-2026-07-31.md) · [odia-transcription-bid-estimate-2026-07-25.md](odia-transcription-bid-estimate-2026-07-25.md)

---

## Executive Summary

The proposed method — transcribe the original and each enhanced candidate, then treat the divergence
between transcripts as a measure of intelligibility damage — **cannot work**, for a reason that is
independent of which ASR we use. A December 2025 systematic study found speech enhancement degraded ASR
in **40 out of 40 tested configurations**, including a 1.3–3.2% penalty on audio that had *no added
noise at all*. There were **zero** configurations where enhancement helped. The cause is distribution
mismatch against ASR pretraining, not loss of human-audible information. An ASR would therefore report
damage from *every* candidate we test, in proportion to how much we processed — which is exactly the
signal we already have from the d-vector gate, dressed up as an intelligibility measurement.

The second candidate approach — intrusive intelligibility metrics (STOI, ESTOI, SIIB) using the original
as reference — fails for a structural reason. These metrics are defined against a **clean** reference,
and ours is the noisy original. A metric that scores similarity to the noisy signal is **maximised by
doing nothing**. It measures "did you change the waveform," not "can the words still be understood."
Worth noting plainly: our existing d-vector gate has the same degenerate property, and only the natural-
variation anchor keeps it useful — the anchor tells us whether a change is *large*, never whether it is
an *improvement*.

The genuinely available options are narrower than hoped. **IndicConformer does support Odia** (MIT
licence, 22 Indian languages, real `or` support — unlike Whisper, which has no Odia token and scores
125.6% WER on real Odia). It could produce an actual transcript, which is useful for confirming words
are present at all. But it cannot rank our candidates, because the enhancement-degrades-ASR effect
confounds exactly the comparison we would be making. **The only sound way to answer "did denoising eat
words in Odia" is an Odia-speaking listener** — and this project already has a route to one.

---

## Key Findings

1. **Enhancement degrades ASR essentially universally.** "When De-noising Hurts" (Dec 2025) tested
   MetricGAN+ against Whisper Large-v3, Parakeet, Gemini Flash 2.0 and Parrotlet-a across 10 noise
   conditions: *"Original noisy audio achieves lower semWER than enhanced audio in all 40 tested
   configurations, with degradations ranging from 1.1% to 46.6% absolute semWER increase."* Mean
   ΔsemWER +7.83%. **Zero** configurations improved.
   ([arXiv 2512.17562](https://arxiv.org/html/2512.17562v1))

2. **The penalty exists even with no noise present.** Same study: *"even in original conditions,
   denoising introduces measurable performance penalties across all models (1.32% to 3.19%),
   suggesting that the denoising process itself introduces artifacts or information loss."* This is
   the decisive fact for us — it means an ASR would penalise our candidates *for being processed*,
   with no way to separate that from genuine intelligibility damage.

3. **Perceptual improvement and ASR accuracy actively diverge.** "When Denoising Hinders" found
   SAM-Audio *"substantially improves signal-level quality, as reflected by higher PSNR and better
   perceptual clarity for human listeners"* while *"frequently leading to higher WER and CER"* —
   and the degradation was **worse for larger Whisper models**. Attributed to *"a systematic shift in
   the input distribution."* ([arXiv 2603.04710](https://arxiv.org/html/2603.04710v1))

4. **The mechanism is artifacts, not information loss.** Iwamoto et al. decomposed enhancement error
   via orthogonal projection and *"experimentally identify the artifact component as the main cause of
   performance degradation."* Also: *"Most single-channel SE approaches tend to only slightly improve
   or even degrade ASR performance."* Single-channel is our case.
   ([Interspeech 2022](https://www.isca-archive.org/interspeech_2022/iwamoto22_interspeech.pdf))

5. **Microsoft Research states the trade-off directly:** *"the introduced speech distortion and
   artifacts greatly harm speech quality and intelligibility, and often significantly degrade automatic
   speech recognition rates."* Their table shows ΔSIG −0.7 against ΔBAK +1.98 — the same SIG/BAK
   trade-off our own gate measured. ([Braun & Gamper, ICASSP 2022](https://www.microsoft.com/en-us/research/wp-content/uploads/2022/07/0000996.pdf))

6. **STOI and ESTOI are intrusive and assume a CLEAN reference.** *"The STOI-measure is intrusive,
   i.e., a function of the clean and degraded speech signals."* Introduced specifically *"for the
   evaluation of noisy speech and time-frequency weighted (enhanced) noisy speech"* — i.e. the
   reference is the clean source, and the noisy/enhanced signal is what gets scored.
   ([torchmetrics](https://lightning.ai/docs/torchmetrics/stable//audio/short_time_objective_intelligibility.html) · [MathWorks](https://www.mathworks.com/help/audio/ug/measure-speech-intelligibility-and-perceived-audio-quality-with-stoi-and-visqol.html))

7. **Noisy references provably distort intrusive metrics.** A derivation of SI-SDR under noisy
   references shows *"noise limits the achievable SI-SDR, or leads to undesired noise in the separated
   outputs"* — the same structural problem applies to any reference-based measure fed a noisy
   reference. ([arXiv 2508.14623](https://arxiv.org/html/2508.14623v2))

8. **But reference-based metrics ARE robust to language mismatch** — the one property that would have
   helped us. An evaluation on Spanish speech attributes this to *"the former's access to clean
   reference signals, which makes reference-based OIMs more robust to training–test acoustic
   mismatches, such as language mismatch."* The robustness comes *from* the clean reference we don't
   have. ([arXiv 2607.10619](https://arxiv.org/html/2607.10619v1))

9. **IndicConformer genuinely supports Odia, MIT-licensed.** `ai4bharat/indic-conformer-600m-multilingual`
   — 600M params, hybrid CTC+RNNT, 22 languages with Odia (`or`) explicitly listed, 76,847 downloads
   last month, 7 quantised variants. A **monolingual Odia checkpoint** is also directly downloadable
   outside HuggingFace's gating: `indicconformer_stt_or_hybrid_rnnt_large.nemo`.
   ([HF model card](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual) · [GitHub](https://github.com/AI4Bharat/IndicConformerASR))

10. **Whisper remains disqualified for Odia** — confirming our own prior finding rather than
    superseding it: no `or`/`ory` token, 125.6% WER on real Odia, and hallucination on ~40% of
    non-speech clips. Our Notion note put it plainly: *"Whisper's language-ID lied to us, because
    Whisper has no Odia label at all."* (prior research: `odia-transcription-bid-estimate-2026-07-25.md`)

---

## Detailed Analysis

### Why the round-trip idea is structurally broken, not just noisy

The plan assumed: `ASR(original)` vs `ASR(enhanced)` diverge ⟹ enhancement damaged intelligibility. That
inference requires the ASR to be sensitive to human-relevant degradation and *insensitive* to
human-irrelevant change. Findings 1–4 show the opposite holds: the ASR is strongly sensitive to
processing artifacts that listeners may not even notice, because those artifacts move the signal off the
distribution it was trained on.

Concretely, we would expect the transcript divergence to rank our candidates in almost exactly the order
`dfn_full > atten24 > atten18 > atten12 > atten06`, since that is the order of how heavily processed
they are. We would then have "confirmed" that heavier processing damages intelligibility — but the
result would be inseparable from the artifact-sensitivity effect, and would have added no information
beyond what the d-vector cosine already told us.

For Odia this is compounded, not caused, by weak language support. Even with a *perfect* Odia ASR the
confound remains.

### Why intrusive metrics degenerate here

STOI, ESTOI and SIIB compare a degraded signal against clean ground truth. We have no clean ground
truth — the 64 kbps MP3 with a −43 dB noise floor *is* our best signal. Scoring `STOI(original,
candidate)` asks "how similar is the candidate to the noisy original," which is maximised at
**do nothing**. Every dB of noise removed lowers the score. It is an anti-enhancement metric.

This is worth turning on our own work: **the d-vector gate has the same shape.** `cos(original,
candidate)` is also maximised by doing nothing. The natural-variation anchor (0.937) rescues it only
partially — it lets us say "this change is bigger than the recording's own variation," which is a
meaningful *damage* threshold. It never tells us a candidate is *better*. Our gate is a safety rail,
not a quality metric, and should be described that way.

### What IndicConformer can and cannot do for us

**Can:** produce a real Odia transcript of the original, so we can confirm the segment contains coherent
lecture speech (and give an Odia reader something checkable). Useful groundwork for the transcription
bid regardless.

**Cannot:** rank enhancement candidates. Finding 2 means it will penalise all of them for being
processed.

**Practical friction, unverified:** the model needs `transformers` (not installed here) and recent
`torchaudio`, while our venv is pinned to torch 2.0.1 / torchaudio 2.0.2 for DeepFilterNet. This likely
needs a separate environment. The HF repo is also gated behind a contact-information agreement, though
the `.nemo` monolingual Odia checkpoint appears to be a direct download.

### The option that actually answers the question

An Odia-speaking listener rating a handful of 25-second excerpts. Two or three minutes of someone's
time settles what no metric available to us can. **This project already has the route:** the Odia
transcription bid involves sourcing Odia transcribers for ~1,952 audio-hours. One of those people
listening to six clips is a rounding error against that effort, and it would also serve as a free
pilot signal for the bid.

---

## Contrarian Views and Risks

- **The "denoising hurts ASR" studies used different denoisers than ours.** MetricGAN+ and SAM-Audio,
  not DeepFilterNet at low attenuation. The authors explicitly caveat: *"this does not imply that speech
  enhancement is inherently detrimental to ASR."* Our gentlest settings (6 dB attenuation) might sit
  below the artifact threshold. This weakens the finding for `atten06` specifically — but not enough to
  rescue the method, because we cannot calibrate where that threshold sits without the ground truth we
  lack.

- **The medical-ASR study is domain-specific.** Medical English consultations, not Odia lectures. The
  authors flag generalisation to other domains and languages as unverified. However finding 3 (SAM-Audio)
  and finding 4 (Iwamoto) reproduce the effect in different domains, so the direction is well supported
  even if the magnitude is not transferable.

- **I have not verified IndicConformer's Odia accuracy on our audio.** The 20.6% WER figure comes from
  our own earlier research citing arXiv 2603.00941, on a *clean* benchmark. Our source is 64 kbps MP3
  with reverb. The same prior research measured 35.1% (Azure) / 35.8% (Sarvam) on *degraded field* Odia,
  which is the more relevant regime and suggests real-world Odia WER near 35%, not 20%.

- **A ~35% WER transcript is above the post-editing crossover** (~30% WER, per Gaur et al., recorded in
  our bid estimate) — the point where correcting is slower than transcribing fresh. So an IndicConformer
  transcript may not even be a useful aid to a human Odia checker.

- **Reading limits, stated honestly:** I read the "When De-noising Hurts" HTML in full including all
  results tables, the "When Denoising Hinders" abstract and results discussion, the Iwamoto abstract,
  the Braun & Gamper abstract and results table, and the IndicConformer model card in full. STOI's
  clean-reference requirement is taken from documentation (torchmetrics, MathWorks) rather than Taal
  et al.'s original 2010 paper. I did **not** access arXiv 2602.03868 or 2603.00941 directly — those
  WER figures are carried from our earlier bid research, not re-verified here. SIIB, HASPI, NCM and
  CSII were not investigated individually; they share STOI's intrusive clean-reference structure, so
  finding 6 is expected to apply, but I did not confirm this per-metric.

---

## Open Questions

1. **Is there an artifact threshold below which enhancement stops hurting ASR?** If yes, and `atten06`
   sits below it, a round-trip check might be salvageable as a coarse pass/fail. Testable only with
   ground-truth text.
2. **Does IndicConformer run in a separate venv without disturbing the DeepFilterNet pinning?** Untested.
3. **What is IndicConformer's actual Odia WER on 64 kbps reverberant lecture audio?** The clean-benchmark
   20.6% is almost certainly optimistic for our material.
4. **Would a non-intrusive metric help instead?** SRMR-CI reportedly matches STOI's performance without
   needing a reference. Not investigated; worth a look precisely because it sidesteps the whole
   noisy-reference problem.
5. **Is word-level damage even a live risk at the settings we are considering?** Our shortlist cuts only
   6–12 dB. The catastrophic ASR failures in the literature came from aggressive enhancement. The risk
   may be concentrated entirely in candidates we have already rejected on other grounds.

---

## Sources

- [When De-noising Hurts: A Systematic Study of Speech Enhancement Effects on Modern Medical ASR Systems (arXiv 2512.17562, Dec 2025)](https://arxiv.org/html/2512.17562v1) — 40/40 configurations degraded; 1.32–3.19% penalty even on clean audio. The decisive source.
- [When Denoising Hinders: Revisiting Zero-Shot ASR with SAM-Audio and Whisper (arXiv 2603.04710)](https://arxiv.org/html/2603.04710v1) — perceptual gain with WER loss; distribution mismatch.
- [Iwamoto et al., How Bad Are Artifacts? Analyzing the Impact of Speech Enhancement Errors on ASR (Interspeech 2022)](https://www.isca-archive.org/interspeech_2022/iwamoto22_interspeech.pdf) — artifacts, not noise, drive the degradation; single-channel SE rarely helps.
- [Braun & Gamper, Effect of Noise Suppression Losses on Speech Distortion and ASR Performance (Microsoft Research, ICASSP 2022)](https://www.microsoft.com/en-us/research/wp-content/uploads/2022/07/0000996.pdf) — distortion harms intelligibility and ASR; ΔSIG/ΔBAK trade-off.
- [torchmetrics STOI documentation](https://lightning.ai/docs/torchmetrics/stable//audio/short_time_objective_intelligibility.html) — STOI is intrusive, clean+degraded.
- [MathWorks — Measuring Speech Intelligibility with STOI and ViSQOL](https://www.mathworks.com/help/audio/ug/measure-speech-intelligibility-and-perceived-audio-quality-with-stoi-and-visqol.html) — both metrics intrusive; clean signal is the reference.
- [A Study of the Scale Invariant Signal to Distortion Ratio with Noisy References (arXiv 2508.14623)](https://arxiv.org/html/2508.14623v2) — noisy references bound and distort reference-based measures.
- [An Objective Intelligibility Metric Evaluation on Spanish Speech (arXiv 2607.10619)](https://arxiv.org/html/2607.10619v1) — reference-based OIMs are robust to language mismatch *because of* clean-reference access.
- [ai4bharat/indic-conformer-600m-multilingual (HuggingFace)](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual) — MIT, 22 languages incl. Odia, CTC+RNNT, gated by contact agreement.
- [AI4Bharat/IndicConformerASR (GitHub)](https://github.com/AI4Bharat/IndicConformerASR) — direct `.nemo` download for the monolingual Odia model.
- [AI4Bharat ASR overview](https://ai4bharat.iitm.ac.in/areas/asr/) — IndicWav2Vec / IndicWhisper / IndicConformer lineage; Vistaar benchmark.
- [Objective Quality and Intelligibility Prediction for Users of Assistive Listening Devices (PMC4452133)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4452133/) — SRMR-CI matches STOI without needing a reference.
- Prior in-repo research (not re-verified here): `docs/odia-transcription-bid-estimate-2026-07-25.md` — Whisper 125.6% WER on Odia; IndicConformer 20.6% clean; Azure 35.1% / Sarvam 35.8% degraded; ~30% post-editing crossover.

## Rerun Inputs

```
workflow: firecrawl-deep-research
topic: Odia ASR models for degraded field audio; validity of ASR round-trip WER and intrusive
       intelligibility metrics (STOI/ESTOI/SIIB) for measuring enhancement damage when no clean
       reference and no speaker of the language are available
depth: thorough
output: markdown
```
