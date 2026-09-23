# Deep Research: Industry-Standard Methodology for *Analyzing* a Recording Before Enhancing It

**Date:** 2026-07-31
**Scope:** The single 5-min segment `data/enhance/poc/segment_30min_5min_original.wav`
(Jiva Goswami Part-01, 30:00–35:00; 48 kHz mono decoded from 64 kbps MP3)
**Question asked:** *Is "pick DeepFilterNet, run it, listen" the right approach — or should we analyze the
segment through multiple methods first to determine what suits it best?*
**Answer:** Analyze first. Every authority surveyed treats diagnosis as a mandatory, separate phase, and
three of them independently predict the exact failure we already hit.

**Companion doc:** [enhance-pipeline-research-2026-07-31.md](enhance-pipeline-research-2026-07-31.md) — the tool-selection research this one corrects.

---

## Executive Summary

The industry does not choose an enhancement tool and then evaluate it. It **characterizes the degradation
first**, derives the treatment from that characterization, and treats "no processing" as a legitimate
outcome. iZotope's canonical repair workflow opens by telling you to run Waveform Statistics *before
touching anything* ("you should start every audio repair job by popping it open and looking at the
numbers"), and orders all subsequent treatment by *depth of damage*, not audibility. We inverted this: we
selected DeepFilterNet3 from a general benchmark table, ran it, and only measured afterward — with a
metric that turned out to be broken.

The most important finding is that **our failure was predictable and is the single best-documented result
in the speech-enhancement literature**. Hu & Loizou's ITU-T P.835 study (32 listeners, 13 algorithms, 673
citations) concluded that listeners judge overall quality *primarily by distortion imparted to the speech
signal, not by how much background noise was removed*. The P.835 SIG scale that measures this is worded
"5 = VERY NATURAL … 1 = VERY UNNATURAL" — the user's verbatim complaint ("feels not natural") is a SIG
rating, and our aggressive DeepFilterNet setting maximized BAK (noise removal) at SIG's expense. That is
the classic mistake, and 18 years of P.835 literature says it is the mistake that most reliably makes
listeners reject audio.

Second: **no single objective metric can adjudicate this.** NTIA's 2024 study of no-reference tools on
real-world audio found inter-metric correlations as low as 0.50 (Squim MOS vs. NISQA MOS). DNSMOS —
purpose-built to rank noise suppressors — achieves PCC 0.94–0.98 at the *system* level but only
SRCC 0.72 for SIG at the *clip* level, and Microsoft explicitly does not use it to decide DNS Challenge
winners. The Interspeech 2024 "PESQetarian" paper demonstrates Goodhart's Law directly: a model tuned to
PESQ scored 3.82 (nominally state-of-the-art) while scoring "very poorly in a listening experiment." The
consensus prescription is: **multiple complementary metrics, scored over many short windows, ratified by
blind listening.** Our "+134 dB SNR improvement" was a textbook Goodhart failure — the number went up
because DeepFilterNet zeroed 23% of the samples, which is also precisely why it sounded wrong.

---

## Key Findings

1. **Measure before you treat — it's step zero, not step four.** iZotope's repair workflow: "If you don't
   already use Waveform Statistics, you should start every audio repair job by popping it open and looking
   at the numbers." The stated reason is that instruments detect damage "too subtle to be picked up by
   human ears" but which *later stages will amplify*. ([iZotope](https://www.izotope.com/community/blog/order-of-audio-repair-operations))

2. **Listeners weight voice distortion over noise removal.** Hu & Loizou (P.835, 32 listeners):
   "The algorithms that performed the best in terms of yielding low speech distortion were also the
   algorithms yielding the highest overall quality. This suggests that listeners were influenced for the
   most part by the distortion imparted on the speech signal than on the background noise when making
   judgments of overall quality." Confirmed by regression of OVRL on SIG and BAK.
   ([Hu & Loizou 2007](https://pmc.ncbi.nlm.nih.gov/articles/PMC2098693/))

3. **The P.835 SIG scale is literally the user's complaint.** SIG: `5 = VERY NATURAL, NO DEGRADATION` /
   `3 = SOMEWHAT NATURAL, SOMEWHAT DEGRADED` / `1 = VERY UNNATURAL, VERY DEGRADED`. BAK (background
   intrusiveness) is rated separately and *must not be traded against it silently*. ([ITU-T P.835](https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-P.835-200311-I!!PDF-E&type=items))

4. **Sometimes the correct answer is "do nothing."** Hu & Loizou finding (4): "only a subset of the
   algorithms tested provided significant benefit to overall quality and only in a few conditions…
   No algorithm produced significant quality improvement in multi-talker babble." Enhancement is not
   guaranteed to be an improvement, and a diagnosis phase is what tells you which case you're in.

5. **Forensic-grade noise reduction is explicitly not listening-grade.** iZotope on Spectral De-noise:
   "can do as much as 40 dB, but it can have a dire effect on voice quality — for this reason, it's mainly
   used in audio forensics." Their working engineer chose **18 dB** because it "minimized the slightly
   hollow effect on the voice." Our goal (devotional listening) is the opposite pole from forensics.

6. **Mixing untreated original back in is documented professional practice.** iZotope, on techniques
   beyond the basic chain: "mixing back a tiny bit of untreated original audio to add realism." This is
   the direct remedy for the discontinuous-room-tone artifact we measured.

7. **Applying a treatment for a defect that isn't present actively damages the voice.** iZotope ran
   De-hum on material with no hum: "Can you hear the whistling resonance under the voice? The more
   harmonics you add, the worse it gets, until everything sounds like it's being heard through a metal
   tube, due to all that comb filtering." Our §11 pipeline prescribes notch filters at 200/250 Hz; the
   segment has no tonal hum there.

8. **No-reference metrics disagree substantially on real-world audio.** NTIA TM-24-571 measured
   inter-metric correlations across 2,592 real conference-speech excerpts: NISQA MOS ↔ Squim MOS = **0.50**,
   WAWEnets MOS ↔ WAWEnets PESQ = 0.94, most pairs 0.55–0.80. However, "listening to the excerpts in the
   low-quality tail of any metric confirms that all six reliably identify low quality speech" — they agree
   on *bad*, not on fine-grained ranking. ([NTIA TM-24-571](https://its.ntia.gov/publications/download/NTIA%20TM-24-571.pdf))

9. **DNSMOS is built for exactly our bake-off — with a clip-level caveat.** Trained on P.835 human
   ratings; PCC 0.94 (SIG), 0.98 (BAK, OVRL) at model level. But per-clip SRCC is 0.72 / 0.82 / 0.81, and
   the authors note "the prediction of SIG is a much harder task and is less correlated with BAK and
   OVRL" — they trained a *separate model* just for SIG. Implication: **score many short windows and
   average; never rank on one score for a whole segment.** ([Reddy et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.01763))

10. **Even Microsoft won't let DNSMOS decide.** ICASSP 2023 DNS Challenge: "We neither use the dev-test
    set nor DNSMOS P.835 for deciding final winners." Human P.835 testing is the arbiter.
    ([Microsoft Research](https://www.microsoft.com/en-us/research/academic-program/deep-noise-suppression-challenge-icassp-2023/))

11. **Optimizing any single metric is a known failure mode (Goodhart's Law).** The "PESQetarian" achieves
    3.82 PESQ — nominally SOTA on VB-DMD — "while scoring very poorly in a listening experiment."
    Recommendation: "other metrics should be included in the evaluation and the resulting performance
    predictions should be confirmed by listening." ([de Oliveira et al., Interspeech 2024](https://arxiv.org/abs/2406.03460))

12. **NISQA's dimensions diagnose *why* something sounds wrong.** Beyond MOS it predicts **Noisiness,
    Coloration, Discontinuity, Loudness**. `Discontinuity` captures gating/dropouts; `Coloration` captures
    timbre alteration. These are the two axes that describe "the voice character feels not natural,"
    and no SNR-style measure sees either. ([Mittag et al., Interspeech 2021](https://github.com/gabrielmittag/NISQA))

13. **Forensic standards concede that objective metrics can't certify improvement.** SWGDE Best Practices
    §1.3.3, as characterized in the JAES review, acknowledges objective intelligibility and quality metrics
    "are unable to consistently and reliably determine whether FSE has made indistinct audio clearer on
    any given occasion"; §4.4 emphasizes "the crucial role of practitioners *listening* to evaluate whether
    their enhancing has been successful." ([Fraser, Maher et al., JAES 2024](https://www.montana.edu/rmaher/publications/fraser_maher_etal_jaes_1124.pdf))

14. **Blind (non-intrusive) RT60 and DRR estimation from single-channel speech is a solved, benchmarked
    problem.** The ACE Challenge established the task and evaluated dozens of single-channel estimators —
    so "how reverberant is this segment, really?" is measurable rather than guessable, which matters
    because our §3 assumed 2.4 s RT60 without measuring it.
    ([Eaton et al., IEEE TASLP 2016](https://dl.acm.org/doi/pdf/10.1109/TASLP.2016.2577502))

---

## Detailed Analysis

### The standard shape of an analysis phase

Synthesizing iZotope's workflow, SWGDE's forensic examination structure, and the NTIA signal-analysis
battery, the industry-standard diagnosis produces a **defect inventory** before any tool is chosen:

| Stage | What is measured | Why it comes first | Our segment |
|---|---|---|---|
| Integrity | clipped-sample count, DC offset, dropouts | clipping is "deepest"; later stages magnify it | **not yet measured** |
| Level / dynamics | peak, RMS, LUFS, dynamic range, crest factor | sets normalization target; detects prior compression | RMS −19.0 dBFS; p90 −14.4 dB |
| Noise floor | per-frame energy percentiles over time | distinguishes stationary from drifting noise | −41…−44 dB, **stationary (3 dB spread)** |
| Noise *spectrum* | avg spectrum of lowest-energy frames | tells you whether it's hiss, hum, rumble, or codec | broadband, worst margin 60–120 Hz |
| Tonal defects | narrowband peaks above local median in noise-only frames | hum needs notch, not denoise | **none** (peaks are 410–492 Hz voice resonance, +3–5 dB, broad) |
| Reverberation | blind RT60 / DRR (ACE-style) | decides dereverb necessity and ordering | **not yet measured** |
| Bandwidth / codec | speech spectral rolloff; energy above the cutoff | reveals band-limit; guards against denoising empty bands | 7.05 kHz @95%, 7.66 kHz @99% |
| SNR margin | speech percentile − noise percentile, per band | sets realistic expectations | ~18–26 dB across speech band |

Only after this inventory does treatment get selected, and only then in "deepest-first" order:
**clipping → stereo → clicks → hum → broadband noise (steady, then variable)**.

Our segment's inventory says something specific and useful: **stationary, broadband, moderate-SNR,
band-limited, no tonal defects.** Stationary noise is the *easiest* case and the one where gentle
classical methods are competitive — Hu & Loizou's cheapest winners were Wiener-as and multi-band spectral
subtraction. It is emphatically not the case that demands a heavyweight neural model run at maximum
aggression.

### Why "no hum" and "no drift" matter more than they sound

Two stages in our existing §11 pipeline were specified for defects this segment does not have: notch
filters at 200/250 Hz, and adaptive profiling for a "20 dB floor drift." Finding 7 shows this isn't merely
wasted compute — iZotope demonstrates that a de-hum pass with no hum present produces audible comb
filtering ("heard through a metal tube"). A notch at 200/250 Hz sits directly in the region where our own
measurement shows this speaker's strongest energy margin (180–320 Hz: speech 10.7 dB vs. noise −11.2 dB).
Applying it would carve his fundamental region to solve a non-problem.

This is the general argument for a diagnosis phase, stated concretely: **treatment specified from a
generic profile rather than a measured one is not neutral — it does harm.**

### What the evaluation battery should be

The literature converges on a triangulated design rather than a single number:

- **Multiple NR metrics, because they disagree** (NTIA: 0.50–0.94 inter-correlation). Use DNSMOS P.835
  (SIG/BAK/OVRL — the axis of our actual problem) *and* NISQA v2 (Noisiness/Coloration/Discontinuity/
  Loudness — the axis that explains *why*).
- **Windowed scoring, because clip-level prediction is weak** (DNSMOS SIG SRCC 0.72). Score e.g. 5-second
  windows across all 5 minutes and compare distributions, not a single segment-level number.
- **A do-nothing control**, because "no algorithm improved quality" is a real documented outcome.
- **Signal-level artifact probes that metrics don't cover**: exact-zero-sample fraction and noise-floor
  continuity, which is what caught our gating defect (22.77% digital silence in the post-filter version)
  when SNR did not.
- **Blind listening as the decision rule**, because SWGDE, the DNS Challenge, and the PESQetarian paper
  all independently refuse to let instruments make the final call.

Crucially, **SIG must be a veto, not a term in an average.** Finding 2 means an option that improves BAK
while dropping SIG is likely to be rejected by a listener even if a combined score improves.

### Where this leaves the plan

The bake-off proposed earlier survives this research essentially intact, with three corrections:
its metric set widens (add NISQA for Coloration/Discontinuity), its scoring becomes windowed rather than
whole-segment, and it gains the two missing diagnostics (clipping/integrity check, blind RT60) so that the
candidate list is derived from the segment's measured defects rather than a generic profile. The two
candidates aimed at restoring room-tone continuity (dry/wet mix-back, noise-floor reinjection) turn out to
be documented professional practice rather than improvisation.

---

## Contrarian Views and Risks

- **Diagnosis can become procrastination.** SWGDE's full protocol is built for court admissibility, where
  documentation burden is the point. We are producing devotional listening material for one corpus. The
  analysis phase should be one script that runs in minutes, not a program of work. The right depth is
  "enough to eliminate wrong candidates," not "enough to testify."

- **These metrics were trained on English, mostly narrowband telephony/conferencing speech.** Our source
  is Odia lecture speech from a 64 kbps MP3 at 7 kHz. NISQA and DNSMOS may be systematically miscalibrated
  here. Their *relative* ordering across our candidates is more trustworthy than any absolute value, and
  even that is an assumption we should state rather than assume.

- **DNSMOS was trained largely on DNS-Challenge-style suppressors.** It may reward exactly the aggressive
  suppression profile that produced our problem. This is a real risk of the metric agreeing with the tool
  and both being wrong about the listener — which is why NISQA's Discontinuity dimension and the raw
  zero-sample probe are included as independent checks.

- **Goodhart's Law applies to *our* bake-off too.** If we iterate settings against DNSMOS OVRL, we will
  eventually produce our own PESQetarian. Fix the metric set before running, use it to *rank* not to
  *tune*, and let listening decide.

- **Hu & Loizou is 2007 and classical-algorithms-only.** Its algorithm rankings do not transfer to neural
  enhancement. What transfers is the *perceptual* finding (SIG dominates OVRL), which has been reconfirmed
  by every P.835-based DNS Challenge since, and by DNSMOS's own architecture (a dedicated SIG model).

- **The 5-minute segment may not represent the corpus.** It is one excerpt from one of seven parts. Whatever
  wins here should be re-validated on at least one segment from a different part, and on a kirtana passage,
  before committing 12 hours of audio to it.

- **Source-reading limits, stated honestly:** I read the iZotope article, the Fraser/Maher JAES paper, and
  the PESQetarian abstract in full; the NTIA memo's §4 (tool selection, metric reconciliation) and
  references; Hu & Loizou's abstract, P.835 methodology tables, and conclusions. I read only the front
  matter and laboratory sections of SWGDE Best Practices for Forensic Audio v2.5 — **finding 13's SWGDE
  §1.3.3/§4.4 content is quoted via the JAES paper's characterization, not read directly from the separate
  SWGDE "Enhancement of Digital Audio" document.** ITU-T P.835 itself is paywalled; its scale wording is
  taken from Hu & Loizou's reproduction of it. NISQA and ACE Challenge findings come from abstracts and
  repository documentation rather than full papers.

---

## Open Questions

1. **Is there clipping in the segment?** Never measured. It is the "deepest" defect in the standard
   ordering and would change the whole treatment plan. Cheap to check.
2. **What is the actual RT60?** The §3 assumption of 2.4 s drove the "we need DeepFilterNet for joint
   dereverb" conclusion. If blind estimation says ~0.4 s, the dereverb justification for DFN largely
   evaporates and lighter methods become viable.
3. **Do DNSMOS/NISQA behave sanely on Odia at 7 kHz bandwidth?** Testable: score the untouched original and
   check the values are plausible rather than pinned.
4. **Is the noise stationary across the whole 110-minute part**, or only within this 5-minute window? Our
   3 dB stability result is a 5-minute claim being used to justify a corpus-wide method choice.
5. **What does a kirtana passage measure like?** The pipeline treats it differently but it has never been
   characterized.
6. **Is there a perceptible floor below which noise reduction stops mattering** for this material? If the
   original at 28.6 dB SNR is already acceptable to devotional listeners, the correct answer may be
   normalization only — Hu & Loizou finding (4) makes this a live possibility, not a rhetorical one.

---

## Sources

- [iZotope — Order of Operations: Audio Repair](https://www.izotope.com/community/blog/order-of-audio-repair-operations) — canonical deepest-first repair ordering; measure-first instruction; 18 dB vs 40 dB; forensics≠listening; mix-back-original; de-hum-with-no-hum comb filtering. Most directly applicable source found.
- [Hu & Loizou, "Subjective comparison and evaluation of speech enhancement algorithms" (PMC2098693)](https://pmc.ncbi.nlm.nih.gov/articles/PMC2098693/) — ITU-T P.835, 32 listeners, 13 algorithms; SIG dominates OVRL; SIG/BAK scale wording; "do nothing" as a valid outcome.
- [NTIA Technical Memorandum 24-571 (Pieper & Voran, 2024)](https://its.ntia.gov/publications/download/NTIA%20TM-24-571.pdf) — no-reference tools on 2,592 real-world excerpts; inter-metric correlation table; metrics agree on the low-quality tail, not on ranking.
- [Reddy et al., "DNSMOS P.835" (arXiv 2110.01763)](https://ar5iv.labs.arxiv.org/html/2110.01763) — SIG/BAK/OVRL prediction; PCC 0.94/0.98/0.98 system-level vs clip SRCC 0.72/0.82/0.81; separate SIG model.
- [de Oliveira et al., "The PESQetarian: On the Relevance of Goodhart's Law for Speech Enhancement" (arXiv 2406.03460, Interspeech 2024)](https://arxiv.org/abs/2406.03460) — metric overfitting; 3.82 PESQ with poor listening scores; confirm by listening.
- [Fraser, Aubanel, Maher et al., "Forensic Speech Enhancement" (JAES 2024)](https://www.montana.edu/rmaher/publications/fraser_maher_etal_jaes_1124.pdf) — forensic vs general enhancement; relays SWGDE §1.3.3 and §4.4 positions on objective metrics and listening.
- [SWGDE Best Practices for Forensic Audio v2.5 (2022)](https://www.swgde.org/wp-content/uploads/2023/11/2022-06-09-SWGDE-Best-Practices-for-Forensic-Audio_v2.5.pdf) — forensic examination structure; read partially (front matter + laboratory sections).
- [SWGDE Best Practices for the Enhancement of Digital Audio (20-A-001)](https://www.swgde.org/documents/published-complete-listing/20-a-001-swgde-best-practices-for-the-enhancement-of-digital-audio/) — the enhancement-specific companion document; **not read directly** — cited via JAES characterization.
- [NISQA (Mittag et al., Interspeech 2021)](https://github.com/gabrielmittag/NISQA) — multidimensional NR quality: Noisiness, Coloration, Discontinuity, Loudness.
- [ITU-T Recommendation P.835](https://www.itu.int/ITU-T/recommendations/rec.aspx?rec=7041) — separate rating scales for speech signal, background noise, and overall quality (paywalled; scales read via Hu & Loizou).
- [Eaton et al., "Estimation of Room Acoustic Parameters: The ACE Challenge" (IEEE TASLP 2016)](https://dl.acm.org/doi/pdf/10.1109/TASLP.2016.2577502) and [ACE Challenge site](http://www.ee.ic.ac.uk/naylor/ACEweb/) — blind single-channel RT60 and DRR estimation.
- [ICASSP 2023 Deep Noise Suppression Challenge](https://www.microsoft.com/en-us/research/academic-program/deep-noise-suppression-challenge-icassp-2023/) — P.835 framework as arbiter; DNSMOS explicitly not used to decide winners.
- [IASA TC-04, Guidelines on the Production and Preservation of Digital Audio Objects](https://www.iasa-web.org/tc04/audio-preservation) — archival preservation-master vs access-copy distinction (surfaced, not read in depth).

---

## Resolution — what happened when we actually ran this (added 2026-08-02)

The two "open gaps" above were measured. **Both first answers were wrong**, and the way they were wrong
is the most useful thing in this document.

**Clipping — retracted.** The diagnostic reported 226 flat-top runs, longest 15 samples pinned at
exactly −1.0, and I called it source clipping needing a declip stage. It was **our own extraction**.
64 kbps MP3 decodes *above* full scale (peaks of 1.22 in this window, 1.86 elsewhere in the part); the
WAV cut clamped those to ±1.0 and manufactured the flat tops I then "found". Fixed by decoding to float
and scaling to 0.95 peak — see `scripts/enhance_make_candidates.py`. **There is no clipping in the
source.**

**RT60 — withdrawn as unreliable.** Reported as 0.71 s and used to argue the 2.4 s assumption was wrong
and the case for a joint dereverb model collapsed. Testing the estimator against its own parameters:
0.10 s window → 0.45 s; 0.15 s → 0.71 s; 0.25 s → **1.50 s**. A 5× spread driven entirely by an
arbitrary choice. The true value is somewhere in 0.5–1.5 s and the homemade estimator cannot narrow it.
The dereverb argument is **unresolved**, not settled either way.

**What did hold**, verified across five windows spanning the whole 110-minute part: stationary noise
floor (3.8 dB spread), ~7 kHz band-limit (6.91–7.21 kHz), no tonal hum, and — measured on the outputs,
so unaffected by extraction — 22.77% digital-zero samples in the aggressive DeepFilterNet run.

**"SNR" is definition-dependent.** Same audio, four reasonable definitions: 28.6 / 27.3 / 18.9 / 43.1 dB.
Quote the definition or don't quote the number.

### Two methodological lessons, both learned the hard way

1. **A number counts once it survives a *different* method, window, or parameter setting.** Every claim
   that failed was a first measurement I treated as established. Every claim that held had been
   reproduced some other way.
2. **Reuse the layer, not the artifact.** `eval_metrics.mcd` looked like a free upgrade over our own
   MCD — but it is DTW-aligned, because its use case is clone-vs-real with differing timing. Ours is
   sample-aligned, so DTW would have *masked* the distortion we were measuring. Physical features
   (`voice_quality.vq_feats`) transfer freely; comparison procedures transfer only if the comparison
   structure matches; **thresholds almost never transfer** — the `−0.03` ECAPA gate from
   `ecapa_denoise_check.py` is meaningless on d-vector, whose natural spread on this material is ~0.05.

### The outcome

The anchored gate (`scripts/enhance_gate.py`) turned out **too conservative**: it failed settings that
both a timbre listener and an Odia-speaking listener accepted. It detects damage; it cannot detect
improvement, since `cos(original, candidate)` is maximised by doing nothing. It is a safety rail.

Blind ladder testing settled it. **Locked: DeepFilterNet3 `--atten-lim 24`** (~22.4 dB reduction),
chosen by Mukul with the word-cutting trade-off at that level explicitly accepted. Production pipeline:
`scripts/enhance_part.py`. Intelligibility research that ruled out every automated substitute for a
human Odia ear: [odia-asr-and-intelligibility-metrics-2026-07-31.md](../odia/odia-asr-and-intelligibility-metrics-2026-07-31.md).

---

## Rerun Inputs

```
workflow: firecrawl-deep-research
topic: industry-standard methodology for analyzing/diagnosing a single archival speech
       recording before selecting an enhancement method (audio forensics + broadcast
       restoration practice; no-reference quality metrics for method selection)
depth: thorough
output: markdown
```
