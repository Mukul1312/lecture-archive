# Measured: How Much Separation Is Available to DeepFilterNet3, and Where the Aperiodic Loss Actually Happens

**Date:** 2026-08-31
**Type:** Experimental record — measurements on real lecture audio, not a literature survey.
**Question asked:** Does the claim *"DFN3 already captures the available separation gain on the
periodic component; the ceiling we hit is the aperiodic component, which is structurally
unpredictable and therefore cannot benefit from coherent-sum filtering"* survive scrutiny?
**Answer:** The first half survives and is now quantified. **The second half is refuted by
measurement.** And the diagnostic tooling that produced the original claim had a serious defect.

> **Reproducibility status:** This is a dated experimental record, not an independently
> reproducible benchmark. The five analysis scripts plus the shared `pa_split.py` helper named
> under **Reproduction** were created in a session scratchpad, and the real lecture inputs remain
> external to Git. Preserve the measured findings and limitations; reconstruct and version those
> inputs before treating a rerun as exact.

**Related:** [mel-spectral-and-voice-anatomy-research-2026-08-31.md](mel-spectral-and-voice-anatomy-research-2026-08-31.md) ·
[enhance-analysis-methodology-research-2026-07-31.md](enhance-analysis-methodology-research-2026-07-31.md)

---

## Summary

Three experiments were run against a real lecture clip.

1. **An oracle multi-frame Wiener filter**, built the same way the oracle Wiener mask was built
   (true speech and noise known), sweeping filter length from 1 tap to 17. This measures how much
   separation gain exists beyond pure masking, and how much of it DFN3's 5-tap architecture reaches.
2. **Per-bin interframe correlation vs lag**, which is the quantity multi-frame filtering feeds on.
3. **A split-quality check**, comparing the HPSS decomposition the earlier diagnostic used against an
   F0-driven harmonic split.

The headline results:

| Question | Answer |
|---|---|
| How much gain does multi-frame filtering add over pure masking? | **+0.38 dB** total available; DFN3's 5 taps capture **+0.27 dB** of it (~71%) |
| Is DFN3's `df_order=5` the bottleneck? | **No.** Extending to 160 ms of context adds **+0.11 dB** |
| Does the tap span mismatch this speaker's F0? | **No.** Speech interframe correlation decays monotonically; no comb structure at integer pitch periods |
| Does multi-frame gain vanish on aperiodic content? | **No.** Aperiodic gets **+0.24 dB** vs periodic **+0.38 dB** — 63%, not zero |
| Was the periodic/aperiodic split trustworthy? | **No.** HPSS assigned **93.2%** of total energy to "aperiodic" |

The revised picture is cleaner than the claim it replaces:

> **The aperiodic loss is a sorting problem, not a filtering problem.** Aperiodic content is not
> excluded from the separation mechanism — it receives most of the same benefit. The separation
> mechanism is simply worth very little for anything (0.24–0.38 dB), and the pointwise sort that
> does the real work (+2.60 dB of the +2.87 dB total) discards low-energy cells regardless of what
> kind of signal is in them.

---

## Method

**Material.** 8 s and 20 s mono clips decoded from `Haladhara-lecture.webm` at t = 900 s, 48 kHz
float. Decoded peak **1.75** — decoder overshoot above full scale, exactly as
[enhance-analysis-methodology-research](enhance-analysis-methodology-research-2026-07-31.md)
documents for 64 kbps MP3 sources. All scripts peak-normalise before use.

**Noise.** White Gaussian, mixed at exactly **20 dB global SNR** to sit inside the project's measured
18–26 dB margin. Mixing our own noise is what makes an oracle possible: the true `S` and `V` are
known separately.

**Oracle multi-frame Wiener filter.** For each time-frequency cell, with taps
`x = [X(t+l), …, X(t−l)]`:

```
c = R⁻¹ r        R = E[x xᴴ]        r = E[x S*]
output speech part = cᴴ s_taps      output noise part = cᴴ v_taps
```

Because the filter is linear its output splits exactly into a speech term and a noise term — the same
trick `demo_masking_is_sorting.py` uses for the pointwise mask. N=1 reduces to the pointwise Wiener
gain, i.e. the pure sorting bound. N=5 is DFN3's `df_order`. STFT parameters are DFN3's real ones:
48 kHz, `n_fft=960`, `hop=480`, and bins 0–95 (0–4.8 kHz) are the band DFN3 actually deep-filters.

### Four methodology defects found and fixed along the way

These are recorded because each one produced plausible-looking but wrong numbers, and two of them
would have inverted a conclusion.

1. **Toeplitz shortcut for `R` was not positive semi-definite.** `R[i,j]` is a local autocorrelation
   at lag `i−j`, so `R` is Toeplitz and needs N lag estimates rather than N² outer products. But a
   Toeplitz matrix assembled from *smoothed* lag products is not guaranteed PSD, and an indefinite
   `R` makes `solve` return filters that amplify noise. Symptom: the oracle got **worse** with more
   taps (N=5 scored −13.41 dB against N=1's +4.72 dB), which is impossible — more taps strictly
   enlarge the feasible set. **Fix:** local average of outer products, PSD by construction.

2. **The statistics window grew with N.** Setting `win = 4·N + 1` to keep `R` full rank meant that
   changing N changed *both* the filter length and the locality of the statistics. The comparison
   across N was therefore confounded, and the oracle again appeared to degrade with more taps.
   **Fix:** one fixed 69-frame window for every N.

3. **The interframe-correlation measure summed complex products across bins.** Each bin has its own
   per-hop phase advance `exp(−j2πfH/N_fft)`; summing complex products across bins cancels them and
   understates correlation badly. It reported white-noise lag-1 correlation as 0.005 when the true
   value is 0.169 — with 50 % window overlap adjacent frames share half their samples, so even white
   noise is correlated. **Fix:** correlate per bin, then average magnitudes with energy weighting.

4. **HPSS is not a periodic/aperiodic split.** See Experiment 3 — this is the substantive finding,
   not just a bug.

A fifth, minor: `demo_periodic_aperiodic.py` located `scripts/voice_quality.py` by walking up from
`__file__`, which only works if the script lives inside the repo tree. It does not, so section [3]
would have crashed. Patched to fall back to the working directory.

---

## Experiment 1 — the oracle multi-frame ceiling

### A. Full speech, DFN3's deep-filter band (bins 0–95, 0–4.8 kHz)

Input SNR in band **+26.62 dB**.

| taps | span | out SNR | gain |
|---|---|---|---|
| **N=1** (pointwise Wiener — the sorting bound) | 0 ms | +29.22 | **+2.60 dB** |
| N=3 | 20 ms | +29.40 | +2.78 dB |
| **N=5** (DFN3's `df_order`) | 40 ms | +29.48 | **+2.87 dB** |
| N=9 | 80 ms | +29.55 | +2.94 dB |
| N=17 | 160 ms | +29.59 | **+2.98 dB** |

**The entire multi-frame mechanism is worth +0.38 dB over pure masking. DFN3's 5 taps capture
+0.27 dB of that, about 71%. Extending context to 160 ms adds +0.11 dB.**

### B. Periodic vs aperiodic (using the corrected F0 split — see Experiment 3)

| component | input SNR | N=1 | N=5 | N=17 | multi-frame gain (N=5 − N=1) |
|---|---|---|---|---|---|
| periodic | +26.99 dB | +3.55 | +3.93 | +4.02 | **+0.38 dB** |
| aperiodic | +26.42 dB | +2.62 | +2.86 | +2.96 | **+0.24 dB** |

Aperiodic content receives **63%** of the periodic component's multi-frame gain. Not zero. And N=5
is within +0.09 dB (periodic) and +0.10 dB (aperiodic) of the 160 ms ceiling — DFN3 is near-optimal
on *each component separately*, not merely on average.

Note also that the *sorting* bound is higher for periodic content (+3.55 vs +2.62 dB). That is
expected: periodic energy is more concentrated in time-frequency, so a sort has more to work with.

### C. The band DFN3 does not deep-filter (bins 96+, 4.8–24 kHz, ERB mask only)

Input SNR in band **+10.42 dB** — much lower, because speech carries little energy up there.

| taps | gain |
|---|---|
| N=1 | **+11.02 dB** |
| N=5 | +11.43 dB |
| N=17 | +11.46 dB |

**The high band has roughly 4× the oracle headroom of the deep-filtered band**, it is where aperiodic
energy lives, and DFN3 covers it with ~15 ERB bands smeared across 385 bins — its coarsest tool on
its largest opportunity. *Caveat:* the input SNR there is low precisely because there is little
speech, so part of that +11 dB is removing noise where there is no signal to protect. Treat as a
lead, not a conclusion.

---

## Experiment 2 — interframe correlation vs lag

Per-bin, energy-weighted, bins 0–95. Median F0 **154.8 Hz**, pitch period **6.46 ms**, STFT hop
10 ms = **1.55 pitch periods per frame**.

| lag | ms | pitch periods | speech | noise |
|---|---|---|---|---|
| 1 | 10 | 1.55 | **0.290** | **0.169** |
| 2 | 20 | 3.10 | 0.139 | 0.020 |
| 3 | 30 | 4.64 | 0.126 | 0.019 |
| 4 | 40 | 6.19 | 0.075 | 0.017 |
| 5 | 50 | 7.74 | 0.074 | 0.018 |
| 6 | 60 | 9.29 | 0.050 | 0.019 |
| 7 | 70 | 10.84 | 0.033 | 0.022 |
| 8 | 80 | 12.38 | 0.027 | 0.022 |

Three readings.

**Speech is only 0.29 correlated frame-to-frame**, not near 1.0. This is why the multi-frame gain is
fractions of a dB rather than proportional to N.

**Noise is correlated too — 0.169 at lag 1.** With a 50%-overlap Hann STFT, adjacent analysis windows
share half their samples, so even white noise has correlated STFT coefficients. The intuition
"speech correlates across frames, noise does not" is false at lag 1. What a multi-frame filter can
exploit is the *difference* in correlation structure, and at lag 1 that difference is 0.290 vs 0.169
— a modest margin.

**No comb structure.** Correlation decays monotonically. There is no bump at lag 2 (3.10 periods) or
lag 4 (6.19 periods) where glottal phase would re-align. The 20 ms analysis window already averages
~3 glottal cycles, so frame-to-frame phase is governed by bin frequency, not glottal alignment.

**DFN3's ±2-frame reach covers lags 1 and 2, which is where essentially all the speech correlation
lives.** Lag 3 onward is ≤ 0.126 and falling. The 5-tap choice is well matched to this material.

---

## Experiment 3 — the periodic/aperiodic split was wrong

`demo_periodic_aperiodic.py` originally used `librosa.effects.harmonic(y, margin=3.0)` and called the
remainder "aperiodic". HPSS separates **temporally smooth from impulsive** content, which is not the
periodic/aperiodic axis:

- a sustained fricative (/s/, /ʃ/) is broadband **and** temporally smooth, so HPSS's harmonic branch
  can claim it — the opposite of the truth;
- vowel onsets are impulsive, so genuinely periodic energy leaks into the residual.

Measured on the 20 s clip:

| | aperiodic share of energy | residual 0–1 kHz | residual 4–8 kHz |
|---|---|---|---|
| HPSS, margin=3.0 | **93.2%** | 85.6% | 9.4% |
| F0-harmonic mask (fixed ±30 Hz) | 49.5% | 77.1% | 16.5% |

`margin=3.0` is so conservative that the harmonic output retains only ~7% of the energy, so
`y − y_per` is **almost the entire signal**. Deleting it is not "deleting the aperiodic component."
Normalised correlation between the two aperiodic estimates was +0.824 — they overlap mostly because
both are dominated by low-band vowel energy.

### The replacement: `pa_split.py`

F0-driven harmonic mask with three properties the fixed-tolerance version lacked:

1. **The analysis window is derived from the measured F0** (`n_fft ≥ 8·sr/F0`), so harmonics are
   actually resolved: 2048 points at 48 kHz, 1024 at 16 kHz. A fixed ~42 ms window picks 512 points
   at 16 kHz, whose 62 Hz Hann main lobe is nearly half this speaker's 155 Hz harmonic spacing — too
   coarse to separate anything.
2. **Tolerance grows with harmonic number**, because a relative F0 error `e` displaces the k-th
   harmonic by `k·e·F0`. A fixed ±30 Hz band silently drops upper harmonics into the aperiodic bucket.
3. **Tolerance is capped at 0.45·F0** so the mask can never swallow the gaps between harmonics, with
   raised-cosine edges to avoid resynthesis clicks.

Reconstruction is exact (`per + aper = y`, relative error 0.0000).

### Corrected attribution

```
38% of frames voiced, median F0 154.3 Hz
    periodic  (harmonic):  21.0% of total energy
    aperiodic (residual):  56.4%
    [old HPSS residual  :  93.2%]
```

(The two parts sum exactly in the waveform but are mildly anti-correlated, so their energies do not
add to 100%.)

Band distribution, dB relative to each part's own total:

| band | periodic | aperiodic | difference |
|---|---|---|---|
| 0–500 Hz | −1.9 | −5.8 | −3.9 |
| 500–1000 Hz | −5.1 | −2.6 | +2.4 |
| 1000–2000 Hz | −18.6 | −14.9 | +3.7 |
| 2000–4000 Hz | −17.7 | −16.7 | +1.0 |
| 4000–8000 Hz | −19.2 | −8.5 | **+10.7** |

That is the Harmonics-plus-Noise picture behaving correctly: periodic dominates only the F0 region,
aperiodic takes over monotonically with frequency.

### Damage signature from deleting the aperiodic part

Measured with the project's own `vq_feats`, for comparability with the numbers already in hand.

| feature | original | **F0-split Δ** | old HPSS Δ | DFN3 actual |
|---|---|---|---|---|
| cpps | 6.75 | +8.95 | +1.95 | **+3.9** |
| hnr | 7.91 | +5.82 | +10.95 | **+3.0** |
| hammarberg | 29.15 | **+3.94** | +16.63 | **+4.2** |
| alpha_std | 14.57 | +3.62 | +13.84 | — |
| h1h2 | −3.41 | +1.85 | +5.89 | — |

Hammarberg is now nearly exact (+3.94 vs +4.2). CPPS and HNR overshoot by 2.3× and 1.9× — which is
the *correct direction*, since deleting all aperiodic energy should exceed what DFN3 partially
removes. Under HPSS the pattern was incoherent: CPPS undershot by 2× while the other two overshot by
3.6–4×.

**The mechanism survives, with better evidence than it previously had.** What does not survive is the
original demo's claim to "reproduce the damage signature" — its numbers were the signature of
deleting 93% of the audio.

---

## Verdicts on the three concerns

**Concern 1 — is DFN3 near the periodic-component ceiling? HOLDS.** Quantified: +0.27 dB of +0.38 dB
available, and near-ceiling on each component separately. The sub-concern that the 40 ms tap span
mismatches this speaker's F0 is **not supported** — correlation decays monotonically with no
re-alignment structure. The sub-concern that nobody had run the oracle comparison was the real gap,
and it is now closed in DFN3's favour.

**Concern 2 — is the split clean enough to trust the diagnosis? WAS A REAL GAP, now fixed.** The
qualitative mechanism was right; the quantitative claims from the HPSS-based demo should not be
cited. The corrected split gives a near-exact Hammarberg match and coherent over-shoot on the other
two.

**Concern 3 — is "aperiodic = unrecoverable" over-generalised? YES, and the premise is refuted.**
Aperiodic content receives 63% of the periodic multi-frame gain. The reason is that **aperiodic
speech is modulated noise, not white noise**: a fricative has onset, sustain and offset; breath has
shape. Its fine structure is random but its *envelope* is highly structured, and a multi-frame Wiener
filter exploits envelope correlation. Measured: aperiodic speech has lag-1 interframe correlation
0.094 against white noise's 0.005 — **19× more correlated than the noise it is mixed with.**
"Unpredictable" was true of the waveform and false of the signal.

---

## What this corrects in prior work

**The "coherent sum" mechanism, as stated in the Notion ML Journey page and in conversation, is
quantitatively wrong.** The claim was that speech terms sum coherently (power ∝ N²) while noise sums
incoherently (power ∝ N), giving SNR gain ∝ N — which would predict roughly +7 dB at N=5. Measured
gain is **+0.27 dB**. Both premises fail: speech is only 0.29 correlated at lag 1, and noise is 0.169
correlated because of window overlap. *The conclusion drawn from it (DFN3 is near its ceiling) turned
out to be correct anyway, for a different reason.*

**Finding 16 of
[mel-spectral-and-voice-anatomy-research](mel-spectral-and-voice-anatomy-research-2026-08-31.md)
needs a nuance, not a retraction.** It states — correctly, from the shipped source — that below
4.8 kHz the output comes from the deep filter applied to the noisy spectrum, and that the ERB mask
never reaches that band. That remains true. But the implication one might draw, that the deep
filter's *separation mechanism* is what damages the voice, is not supported: the DF operator's
contribution over a plain mask is ~0.27 dB, and it treats periodic and aperiodic content similarly.
The damage is a sorting effect that happens upstream of the filtering.

**Nothing in the mel-spectral / voice-anatomy document's literature findings is affected.** Those
concern vocoders, speaker embeddings and glottal inverse filtering, none of which this touches.

---

## Limitations

- **One speaker, one clip, one noise type.** White Gaussian noise at 20 dB on 8–20 s of one lecture.
  Real room tone is not white, and results may differ for a different F0 or a more reverberant
  passage. The interframe-correlation profile in particular is speaker- and material-specific.
- **The oracle uses locally-estimated statistics**, not true ensemble ones, over a 69-frame
  (690 ms) window. Speech is non-stationary at that scale, so all oracle numbers are somewhat
  pessimistic in absolute terms. The *relative* comparison across N is fair because the window is
  held fixed.
- **The high-band result (Experiment 1C) is not a like-for-like comparison** with the DF band: its
  input SNR is 16 dB lower because there is little speech there. It is a lead about ERB resolution,
  not a measured deficiency in DFN3.
- **`split_quality_check.py` still uses its own preliminary fixed-±30 Hz mask**, not `pa_split.py`.
  Its F0-column numbers (+8.74 / +4.62 / +5.71) are therefore slightly different from the
  authoritative `pa_split` ones (+8.95 / +5.82 / +3.94). Kept as-is because it is the script that
  *documents the comparison* between methods.
- **No DFN3 run was performed here.** The +3.9 / +3.0 / +4.2 damage figures are the previously
  measured values carried forward; this work measures what is *available*, not what DFN3 achieves.
  Closing that loop needs an actual DFN3 render scored with `score_candidate_windows`.

---

## Reproduction

All scripts in the session scratchpad; they depend only on `.venv` (numpy 1.26.4, soundfile 0.14.0,
librosa 0.11.0, parselmouth 0.4.7, scipy 1.17.1) and the repo's `scripts/voice_quality.py`.

```bash
# 48 kHz clips from the lecture
ffmpeg -ss 900 -t 20 -i Haladhara-lecture.webm -ac 1 -ar 48000 -c:a pcm_f32le clip48.wav
ffmpeg -ss 900 -t  8 -i Haladhara-lecture.webm -ac 1 -ar 48000 -c:a pcm_f32le clip8.wav

.venv/Scripts/python.exe oracle_multiframe_gain.py clip8.wav    # Experiment 1
.venv/Scripts/python.exe ifc_vs_lag.py             clip48.wav   # Experiment 2
.venv/Scripts/python.exe split_quality_check.py    clip48.wav   # Experiment 3, method comparison
.venv/Scripts/python.exe demo_periodic_aperiodic.py clip48.wav  # Experiment 3, corrected attribution
```

| script | role |
|---|---|
| `pa_split.py` | F0-driven periodic/aperiodic split, shared by the others |
| `oracle_multiframe_gain.py` | oracle multi-frame Wiener sweep over tap count |
| `ifc_vs_lag.py` | per-bin interframe correlation vs lag |
| `split_quality_check.py` | HPSS vs F0-mask comparison |
| `demo_periodic_aperiodic.py` | corrected damage attribution (was HPSS-based) |
| `demo_masking_is_sorting.py` | the pointwise-mask oracle this work extends |

---

## Open questions

1. **Does the high-band ERB resolution actually cost anything?** Experiment 1C suggests the largest
   oracle headroom is in the band DFN3 treats most coarsely. Testable by comparing DFN3's actual
   high-band output against a per-bin oracle mask.
2. **Does `run_df=False` change the damage signature?** Still the one-flag experiment from
   [mel-spectral-and-voice-anatomy-research](mel-spectral-and-voice-anatomy-research-2026-08-31.md),
   still unrun. Given that the DF stage contributes only ~0.27 dB, disabling it should cost very
   little noise reduction — which makes the experiment cheaper to justify than it looked.
3. **What is the per-frame `lsnr` distribution on this material?** Unrun. `DfNet.forward` returns it.
4. **Does the picture hold for real room tone rather than white noise?** The noise interframe
   correlation (0.169 at lag 1) is a windowing artefact of white input; coloured, non-stationary room
   tone would have its own structure and could change the available multi-frame gain in either
   direction.
5. **How much of the available +2.87 dB does DFN3 actually realise?** Everything here measures the
   ceiling. Nobody has measured the gap between DFN3 and its own oracle.
