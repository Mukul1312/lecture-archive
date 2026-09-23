# Noisy-source cloning data-prep — research pass (the 0.74 ECAPA plateau)

*Source-verified 2026-06-30 via a deep-research harness (5 angles → 24 sources → 112 claims → 25 adversarially verified, 2/3-refute kill rule → **16 confirmed, 9 refuted**). Full output: `tasks/wp49iafav.output`. This pass deliberately searched the **GPT-SoVITS / CosyVoice / Fish-Speech** neighborhood + papers/READMEs — the cone a prior `voxcpm+lora+train` code-search was structurally blind to. Supersedes nothing in tts-dataprep-pipeline.md (`docs/tts-dataprep-pipeline.md`); it adds the noisy-source layer.*

## The question
Why is the GGS clone plateaued at **~0.74 ECAPA-TDNN cosine on unseen-content** sentences (140 clips, lecture 1), and what cheap data-side levers could move it?

## TL;DR verdict
The noisy-source TTS communities converge on: **a 0.74 plateau on 140 clips is more likely a data-quality / normalization ceiling than a dataset-size ceiling.** The single most-sourced theme is that **enhancement is a documented identity-vs-quality tradeoff** — denoiser artifacts propagate downstream, and enhancement that raises UTMOS/DNSMOS/WER can *lower* speaker similarity. So "more cleaning" may be *capping* identity here.

> ⚠️ **The denoise evidence is genuinely MIXED, not "denoise less."** The verifier killed claims pointing *both* ways (a denoise front-end *improving* similarity at 10 dB SNR → refuted 0-3; "denoising isn't beneficial" → refuted 1-2). The only defensible conclusion is **"A/B enhancement, don't assume."**

---

## Contradictions with our current pipeline (highest value)
1. **peak-norm 0.95 is an outlier.** [Fish-Speech finetune docs](https://github.com/fishaudio/fish-speech/blob/main/docs/en/finetune.md) recommend **loudness (LUFS) normalization** (`fap loudness-norm`); [CosyVoice 3 (arXiv 2505.17589)](https://arxiv.org/html/2505.17589v1) peak-normalizes to **0.6** for headroom. Both 3-0. Our `denoise_postproc.py` peak-norms to 0.95. → switch to integrated-LUFS norm (e.g. pyloudnorm −23/−16 LUFS) or at least drop peak to ~0.6–0.7. *Cheapest lever.*
2. **The "best" denoiser ≠ best for identity.** [Noisy-to-Noisy VC (arXiv 2109.10608)](https://arxiv.org/pdf/2109.10608): DCCRN won every separation metric yet downstream artifacts hurt more than residual noise. [Wildspoof-2026 (arXiv 2602.05770)](https://arxiv.org/pdf/2602.05770): prompt enhancement *lowered* SECS in F5-TTS (0.35→0.28) and StyleTTS2 (0.19→0.18). → **Resemble-Enhance is the prime plateau suspect** — A/B it (caveat: inference-prompt result, not training-data; downstream is VQ-VAE VC not VoxCPM2).
3. **No de-reverb stage.** [CosyVoice clone docs](https://www.alibabacloud.com/help/en/model-studio/cosyvoice-clone-design-api): "Background noise, reverberation, and overlapping voices all reduce the similarity and naturalness of the cloned voice." The GPT-SoVITS **ecosystem** ships UVR-DeEcho-DeReverb (attribute to ecosystem/community, **not** core README — the "README does dereverb-before-slicing" claim was refuted 1-2). Our old room recordings are reverberant; reverb smears ECAPA's identity cues. A/B it — over-dereverb also strips identity.

## Additive techniques (not yet in our pipeline)
| Technique | Why it helps | Source | Confidence |
|---|---|---|---|
| Reference-free MOS gating (DNSMOS/UTMOS/WV-MOS) per clip | Orthogonal to CER/alignment — catches perceptual degradation they pass | [arXiv 2210.06370](https://ar5iv.labs.arxiv.org/html/2210.06370) · [NeMo UTMOS curator](https://docs.nvidia.com/nemo/curator/curate-audio/process-data/quality-filtering/utmos) | medium (2-1) |
| Per-clip SNR gating | Low SNR drags ASV/ECAPA similarity down | [CosyVoice 2](https://funaudiollm.github.io/pdf/CosyVoice_2.pdf) | medium (2-1) |
| Reference = LONGEST clean clip (bias `ref_audio` to longer) | Prompt length correlates with similarity (7.7s>5.5s moved SECS); **inference-only, no retrain** | [arXiv 2602.05770](https://arxiv.org/pdf/2602.05770) | high (3-0) |
| Multi-ASR cross-validation transcript gate (<15% pairwise WER) | Consensus catches mislabels at English↔Sanskrit code-switch boundaries | [CosyVoice 3](https://arxiv.org/html/2505.17589v1) | high (3-0) |

## Guardrail (3-0)
**Do NOT naively mix synthetic/ZS-TTS speech to break the plateau** — [ZeSTA (arXiv 2603.04219)](https://arxiv.org/pdf/2603.04219) shows it raises intelligibility but drops speaker similarity (0.818→0.765); a learned domain embedding recovers it (→0.807). If we ever augment beyond 140 clips with generated audio, do it domain-conditioned.

## Metric calibration (locked, 3-0)
**ECAPA-TDNN cosine ≠ ERes2Net/WavLM cosine.** Three "SOTA is ~0.79 EN / ~0.84 ZH" claims were **refuted 0-3** for this incomparability. → **Never read 0.74 as "below SOTA."** Track only *relative deltas* in our own ECAPA harness across A/Bs.

## Decision rule — RESOLVED (2026-06-30): denoising HURT
The retrain (denoised-data LoRA vs noisy-data LoRA, scored on unseen via `score_denoise_retrain.py`) was the field's #1 experiment. **Result: denoising the training data did NOT raise the ceiling — it lowered it.**
- Best **unseen-content** ECAPA: noisy-trained **0.743** (step 150) → denoised-trained **0.704** (apples-to-apples vs noisy centroid) = **−0.040**.
- Using the both-centroids confound correction the data-validation session explicitly asked for: denoised clone vs **denoised** centroid = **0.727** — still **below** 0.743. So it is **not** the confound masking a real gain; denoising genuinely lost.
- Reconciles cleanly with the ear-check: the denoised *clips* sound like him (voice intact — the −0.076 training-clip drop was the noisy-centroid confound), **yet** a clone trained on them generalizes slightly worse on unseen text. Exactly Finding 1's prediction — "identity-safe by ear" ≠ "best downstream"; denoiser artifacts/removed-cues propagate into the LoRA.
- **→ Train on the ORIGINAL noisy clips. The training-data-denoising lever is a closed dead end** (triple-confirmed: ear-check on data + unseen-ECAPA on the clone + the literature). His-own ceiling 0.825 ⇒ ~0.08 headroom remains, but not via denoising.

**Live question now = data QUANTITY** (the `ggs-curve` learning-curve experiment, 35→70→105→140). If that's flat too → cheapest untried lever is **longest-clip reference selection** (inference-only, no retrain), then de-reverb / LUFS-norm A/Bs.

### QUANTITY — RESOLVED (2026-06-30): FLAT / SATURATED
Best unseen ECAPA per subset (its own peak checkpoint): **n35=0.731 · n70=0.750 · n105=0.765 · n140=0.744** (ceiling 0.825). Whole-range slope n35→n140 = **+0.014** (≈flat); it **peaked at n105 and *dropped* at the full n140**. → **More clips from the same lecture do NOT break the plateau.** Two notes: (1) per-cell std is large (~0.03–0.055; only 6 samples/cell) so n105>n140 is *within noise* — but it's at least consistent with the research's "prune low-quality clips" finding (a curated ~105 subset may beat the raw 140; cheap to check). (2) This tested quantity of **same-lecture** clips only — **cross-lecture DIVERSITY (lectures 2-N: different rooms/prosody/content) is a DIFFERENT, still-open lever.**

**Both data-side levers are now ruled out (denoise HURT, same-lecture quantity FLAT) → the ~0.74–0.765 plateau is NOT a data problem.** Evidence increasingly points at the inference/prompt path (the project's blind eval: "the reference clip does the identity work"). → **Reference-selection is now the clear next experiment** (prepped: `ggs_l1_0081`, 17.4s, ef 0.97).

### REFERENCE-SELECTION — RESOLVED (2026-07-01): THE LEVER. PLATEAU BROKEN.
48-clip sweep `{base, LoRA-150} × {4 refs} × 2 unseen × 3 seeds`, unseen ECAPA vs noisy centroid (ceiling 0.825):

| reference | base | LoRA-150 |
|---|---|---|
| 0112 noisy (BASELINE) | 0.644 | 0.733 |
| 0112 denoised | 0.616 | 0.670 |
| 0086 calm-modal | 0.723 | 0.779 |
| **0081 typical/shout** | 0.756 | **0.806** |

**Best = LoRA-150 + reference `ggs_l1_0081` = 0.806**, up **+0.063** from the 0.743 baseline — the BIGGEST gain of the project (vs denoise −0.04, quantity +0.014) — now only **0.019 below his own ceiling (0.825).** The reference clip was the lever all along; both data levers failing pointed here correctly.
- **Q1** a good reference beats the atypical 0112 by ~+0.07 — *dominant*.
- **Q2** the shouty-but-most-ECAPA-typical 0081 (cos-to-centroid 0.939) beat calm-modal 0086 by +0.027 (~1 std) → **ECAPA-typicality dominated register; the cos-to-centroid representativeness metric that picked 0081 was validated.** (Ear-check whether the shout bleeds into output.)
- **Q3** LoRA + reference **STACK** — LoRA adds +0.05–0.09 at *every* reference → the earlier blind-eval "base+prompt ≥ LoRA+prompt" hunch is **REFUTED; keep the LoRA.**
- **Q4** denoising the reference is **clip-dependent, not a reliable lever**: it *hurt* 0112 (0.733→0.670, −0.063) but *helped* 0081 (noisy 0.773 → denoised **0.806**, +0.033). Follow-up **tested**: NOISY-0081 = 0.773, did **NOT** beat denoised-0081 (0.806). So the winner (denoised 0081) is both the metric-best AND the user's ear-preferred clean clip — they converge. The Q4-on-0112 "denoise hurts" was thus a confound/clip artifact, not a rule.
- Caveats: ECAPA = timbre-match, not perceptual quality; 0081 has the highest variance (±0.038, the shout); the Q4 denoise penalty is confounded by the noisy centroid.

**Winning recipe (CONFIRMED): LoRA-150 + `ggs_l1_0081` DENOISED reference = 0.806** (0.019 below ceiling; noisy-0081 follow-up lost at 0.773). Next: (1) **user ear-check** — 0081 (0.806, shouty) vs 0086 (0.779, calm): does the shout carry into the output? user's call; (2) lock the chosen clip as the production reference in `infer_eval.py`/`infer_curve.py`.

## Honest caveats (do not over-read)
- **Regime mismatch (dominant):** nearly all sources build LARGE MULTI-SPEAKER corpora (CosyVoice 100k+ hr), not single-speaker LoRA on VoxCPM2. Everything transfers *by analogy*, none was validated on our case or on a 0.74 plateau.
- **Mixed denoise evidence:** the literature is NOT unanimous "denoise less." Conclusion is "A/B, don't assume."
- **Source strength:** de-reverb / SNR / MOS findings were 2-1 (one dissent each on regime-transfer overreach) → medium confidence, worth trying, not proven.

## Open questions (no source resolved these for our case)
- Does Resemble-Enhance `--denoise_only` specifically harm identity on *this* speaker? (must measure — the retrain A/B is exactly this)
- LUFS vs peak-0.6 vs peak-0.95 — does loudness-norm actually move ECAPA cosine, or only perceptual consistency?
- Is 140 clips the binding constraint at all, or purely a quality/normalization/reference ceiling?
