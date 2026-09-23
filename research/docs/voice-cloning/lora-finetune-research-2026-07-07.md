# LoRA fine-tuning research — fastbook + modern PEFT, mapped to VoxCPM2 Hindi (2026-07-07)

Deep-research report (adversarially verified: 111 claims extracted → 25 verified → 19 confirmed, **6 killed**).
Primary sources: fastbook ch.5/ch.10; VoxCPM2 finetune docs; a June-2026 VoxCPM2-LoRA paper (arXiv 2606.26618,
Khmer/Korean — same architecture); LoRA-LR-sensitivity (arXiv 2405.09673); Stable-TTS; HF PEFT docs.

## The two honest headlines
1. **The NaN is fixable and our approach was right.** The step-0 NaN can't come from the LoRA (zero-init B =
   no-op at step 0), so it's the base flow-matching DiT forward/loss on padded rows / bf16 overflow. The
   source-grounded fix = **mask padded rows before the DiT loss + grad-clip 1.0 + ~200-step warmup + keep the
   flow-matching head (and audio VAE) in fp32 + LR 1e-4 (drop to 5e-5 if it still NaNs).** A published VoxCPM2
   LoRA recipe trains without divergence at: AdamW wd 0.01, peak 1e-4, 200-step warmup→cosine, **effective batch
   16 (micro 4 × accum 4)**, grad-clip 1.0, bf16. This corroborates our padfix + grad-clip + fp32-diff patches —
   we were missing proper 200-step warmup and the micro-4×accum-4 batch.
2. **Capturing his prosody with a LoRA on 14.5 min is NOT guaranteed — and the evidence leans against it.** The
   encouraging "VoxCPM2 LoRA captured prosody (MOS 3.76→4.36)" claim **was refuted in verification**. Stable-TTS
   deliberately refuses to learn target prosody from few samples (it's unstable). LoRA is a strong regularizer
   ("learns less"). **The highest-leverage prosody move is collecting MORE of his lecturing speech** (your
   lectures 2–4 review) — not hyperparameter tuning.

## Findings (confidence in brackets)
1. **LR [high]:** Start **1e-4** (VoxCPM2 LoRA default; 1e-5 is for full-FT). Warmup ~200 steps → cosine. LoRA is
   *extraordinarily* LR-sensitive (no alt LR reached 90% of best in LLM study) → sweep, pick the **highest stable**
   LR. fastbook `lr_find`: min-loss-LR ÷ 10, or last clearly-decreasing point. NaN → drop to 5e-5.
2. **Freeze/place [high]:** Backbone frozen (LoRA); zero-init B, **alpha = 2r**, adapters on Q/K/V/O attention of
   BOTH the LM and DiT; FFN + audio-VAE frozen. Targeting all attention modules matters more than rank. Modern
   analog of progressive-unfreezing = *staging* which adapters activate (DiT first, then LM) — analogy, not proven.
3. **NaN / stability [high]:** (see headline 1). fp32-on-the-sensitive-head is reasonable but only partially
   source-proven (the paper's fp32 module is the frozen VAE, not the DiT loss); the robust levers are
   **padded-row masking + grad-clip + warmup + lower LR**. Turn on `torch.autograd` anomaly detection to localize.
4. **Overfitting [high]:** **1–3 epochs** is enough for single-speaker; more "often hurts." wd 0.01,
   `training_cfg_rate=0.1` (never 0 — it's the CFG dropout for the DiT). **Pick rank by LISTENING, not val loss**
   (study: val loss best at r128 but MOS peaked at r64; even r8 recovered most gains). Don't mid-1cycle
   early-stop; retrain to the best epoch count. Try **rank 8/16/32**.
5. **Data [medium]:** Timbre transfers from little audio (our ECAPA 0.86); **prosody is the hard, unstable part on
   tiny sets.** Stable-TTS sources prosody from the *prior*, not few target samples. → collect/label MORE of his
   speech is the highest-leverage prosody lever.
6. **Metrics [high]:** **Do NOT trust F0-RMSE** (≈zero correlation with human MOS, can flip sign). Judge prosody by
   **listening tests**; ECAPA for timbre; F0 only as a rough secondary. (Validates the "your ear is the judge" stance.)

## Prioritized checklist
**Fix the NaN (in order):** (1) mask/remove padded rows before the DiT loss; (2) grad-clip 1.0; (3) 200-step
warmup → cosine, peak 1e-4; (4) DiT loss + audio-VAE in fp32; (5) confirm zero-init B; (6) if still NaN → LR 5e-5.
**Then capture prosody / avoid overfit:** (7) AdamW, wd 0.01, `training_cfg_rate 0.1`, effective batch 16
(micro 4 × accum 4); (8) 1–3 epochs, retrain-to-best (no mid-cycle early-stop); (9) LR sweep (pick highest stable)
+ **rank sweep judged by ear** (8/16/32); (10) **collect more of his speech** — the real prosody lever.

## Killed / do-NOT-adopt (adversarial verification)
- ✗ "LoRA captured prosody (3.76→4.36)" — **refuted**; no positive proof for our data regime.
- ✗ Discriminative LR "low-LM / high-DiT with 2.6^4 ratio" — use ONE swept LR.
- ✗ "LoRA improves monotonically with LR up to divergence."
- ✗ "Train the DiT fully fp32 with no clipping / no mixed precision."
- ✗ "Raise rank to 32/64 + enable_dit is *the* lever for prosody/style."
- ✗ "Naive few-sample fine-tune inevitably produces noisy/artifacted output" (0-3).

## Caveats
Nearly all VoxCPM2-specific evidence is ONE paper (different language, larger data, not single-speaker Hindi
prosody) — starting points, not guarantees. The fp32-head→NaN mapping is partial. Prosody capture is **unproven +
likely data-limited**. fastbook predates LoRA (conceptual analogies). LR-sensitivity/module findings are from LLM
benchmarks extrapolated to TTS. rsLoRA at r32 makes updates ~5.6× *larger* (not a NaN remedy).
