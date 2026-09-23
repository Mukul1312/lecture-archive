# Deep Research: ML concepts behind the GGS VoxCPM2 voice clone

## Executive Summary

This report synthesizes citation-backed claims supporting a learning journal that documents LoRA fine-tuning of VoxCPM2 (a tokenizer-free, diffusion-autoregressive TTS model) to clone a person's English voice on a 24 GB RTX 4090. Six themes emerge, each grounded in primary or clearly-marked secondary sources.

First, **mixed precision is an op-level runtime behavior, not a model conversion**: PyTorch's `torch.amp` casts individual ops to a lower-precision dtype during the forward pass while instructing users *not* to call `.half()`/`.bfloat16()` on the model, which keeps stored parameters in their default dtype ([PyTorch docs](https://docs.pytorch.org/docs/stable/amp.html)). The classic mixed-precision recipe additionally keeps an fp32 master copy of weights ([PyTorch Training Performance Guide](https://residentmario.github.io/pytorch-training-performance-guide/mixed-precision.html); primary origin: arXiv:1710.03740).

Second, the **fp32-vs-bf16 memory trap** is arithmetic: 4 bytes/param (fp32) vs 2 bytes/param (bf16/fp16) ([Transformers Arithmetic](https://medium.com/@kailaspsudheer/the-transformers-arithmetic-527111099527)). Crucially, OOM happens even when weights fit, because training memory = weights + gradients + optimizer states + activations, and Adam optimizer states alone cost ~12 bytes/param ([Lyceum](https://lyceum.technology/magazine/gpu-memory-requirements-transformer/)). The journal's project survives in 24 GB precisely because **LoRA** confines gradients/optimizer states to small adapters while the frozen base dominates VRAM ([QLoRA, arXiv:2305.14314](https://arxiv.org/abs/2305.14314); [APXML](https://apxml.com/courses/lora-peft-efficient-llm-training/chapter-5-peft-optimization-deployment/peft-infrastructure-requirements)). PEFT's convention is to keep adapters in fp32 for AMP stability ([PEFT issue #2421](https://github.com/huggingface/peft/issues/2421)).

Third, **MOS is a flawed but dominant TTS metric**: a 1–5 Likert rating rooted in ITU recommendations, in practice relative rather than absolute, with poor sensitivity/reliability as systems approach human quality ([Le Maguer et al. 2024](https://www.sciencedirect.com/science/article/abs/pii/S0885230823000967); [TTSDS, arXiv:2407.12707](https://arxiv.org/html/2407.12707v3)).

Fourth, **stochastic decoding** explains seed-driven variation: diffusion/flow-matching TTS generates from a Gaussian-noise prior along a probabilistic density path, so a single sample is one draw from a distribution ([Bridge-TTS, arXiv:2312.03491](https://arxiv.org/html/2312.03491v1); [CosyVoice 2, arXiv:2412.10117](https://arxiv.org/html/2412.10117v3)).

Fifth, **voice acoustics** decompose via the source-filter model: pitch/F0 lives in the source (larynx), while timbre, vowel identity, and accent are encoded in vocal-tract resonances (formants F1/F2/F3) in the spectral envelope ([Edinburgh Speech Processing Module 4](https://speech.zone/wp-content/uploads/2021/10/Speech-Processing_-The-Source-Filter-Model-1.pdf)).

Sixth, **LoRA-baked vs prompt-based cloning** are distinct paths: zero-shot cloning derives timbre, accent, and prosody from the reference at inference (and copies its noise), whereas LoRA few-shot adaptation bakes the voice into adapter weights ([Voice Cloning Survey, arXiv:2505.00579](https://arxiv.org/html/2505.00579v1); [VoxCPM model card](https://huggingface.co/openbmb/VoxCPM-0.5B)).

A central caveat threads through the report: many memory figures and the "16 bytes/param" rule describe *full* fine-tuning and are upper bounds, not the LoRA footprint the project actually incurs.

## Key Findings

1. Under `torch.amp` autocast, ops run in an op-specific dtype chosen at runtime; users should *not* cast the model or inputs, and the model/optimizer are created in default (fp32) precision with only the forward pass wrapped — implying stored parameters remain in their default dtype ([Automatic Mixed Precision package — torch.amp](https://docs.pytorch.org/docs/stable/amp.html)).

2. Autocast wraps only the forward pass (including loss); it is exited before `backward()`, and backward ops reuse the dtype autocast chose for the corresponding forward ops ([torch.amp](https://docs.pytorch.org/docs/stable/amp.html)).

3. The classic mixed-precision recipe keeps an **fp32 master copy** of weights: updates computed on the fp16 copy are applied to the fp32 master, making the update safer (origin: arXiv:1710.03740) ([Mixed Precision — PyTorch Training Performance Guide](https://residentmario.github.io/pytorch-training-performance-guide/mixed-precision.html)).

4. Bytes per parameter: fp32 = 4, fp16/bf16 = 2, int8 = 1; weight memory = params × bytes/param ([Estimate runtime and memory required for LLM Training](https://medium.com/@kailaspsudheer/the-transformers-arithmetic-527111099527)). Derived for this project: a 2B model = ~8 GB (fp32) vs ~4 GB (bf16) for weights alone.

5. Training memory = model states (weights + gradients + optimizer states) + activations; total can far exceed weights (a 7B model's 14 GB of fp16 weights can balloon past 80 GB in full training) ([GPU Memory Requirements for Transformer Models](https://lyceum.technology/magazine/gpu-memory-requirements-transformer/)).

6. With Adam/AdamW in mixed precision, optimizer states cost **12 bytes/param** (fp32 master 4 + momentum 4 + variance 4); combined with 2 B weights + 2 B gradients this gives **~16 bytes/param before activations** ([Lyceum](https://lyceum.technology/magazine/gpu-memory-requirements-transformer/)).

7. Activations scale with batch size × sequence length × hidden dim (quadratic in sequence length via attention), so they — unlike weights/gradients/optimizer states — grow with batch, and can dwarf the weights ([Lyceum](https://lyceum.technology/magazine/gpu-memory-requirements-transformer/)).

8. Full fine-tuning rule of thumb: ~16 GB/1B params in half precision vs ~2 GB/1B for inference; LoRA is much lower because only adapters get optimizer/gradient memory ([How much VRAM do I need for LLM model fine-tuning?](https://modal.com/blog/how-much-vram-need-fine-tuning)).

9. LoRA freezes the full base model and trains only small adapters; gradients pass through frozen weights to update adapters, so optimizer/gradient memory is allocated only for adapters ([QLoRA: Efficient Finetuning of Quantized LLMs](https://arxiv.org/abs/2305.14314)).

10. Concretely, for a 7B LLaMA LoRA run, adapters take only ~26 MB while LoRA input gradients are ~567 MB and the 4-bit base is ~5,048 MB — most memory is base weights + activation gradients, not adapter optimizer state ([QLoRA PDF](https://arxiv.org/pdf/2305.14314)).

11. PEFT keeps LoRA adapters in **fp32 by default** even atop a bf16/4-bit base, because low-precision adapter weights are prone to training instability under AMP (disable via `autocast_adapter_dtype=False`) ([Adapters saved in float16 are loaded in float32 · Issue #2421](https://github.com/huggingface/peft/issues/2421)).

12. MOS (Absolute Category Rating) is a 1–5 Likert listening test rooted in ITU P.800; ~two-thirds of recent speech-synthesis submissions rely on ACR/MOS ([The limits of the Mean Opinion Score for speech synthesis evaluation](https://www.sciencedirect.com/science/article/abs/pii/S0885230823000967)).

13. Despite being "absolute," MOS is in practice a **relative** score sensitive to the other systems and to the presence/absence of anchors; the authors conclude overall-quality MOS has reached a "cul-de-sac" ([Le Maguer et al. 2024](https://www.sciencedirect.com/science/article/abs/pii/S0885230823000967)).

14. MOS becomes less useful as real and synthetic speech converge, cannot be compared across studies/time, and human ratings drift over time ([TTSDS — Text-to-Speech Distribution Score](https://arxiv.org/html/2407.12707v3)).

15. Diffusion TTS runs a forward process that turns data into Gaussian noise and a reverse process that **generates samples starting from noise** — the mechanistic root of stochastic output ([Schrödinger Bridges Beat Diffusion Models on TTS](https://arxiv.org/html/2312.03491v1)).

16. LM-based TTS generates varied, prosody-consistent speech **via autoregressive sampling**; the flow-matching decoder conditions on an intermediate state on a probabilistic density path ([CosyVoice 2](https://arxiv.org/html/2412.10117v3)).

17. Deterministic regression TTS (e.g., Tacotron 2) favors mean predictions and yields over-smoothed, **low-diversity** output; diffusion is introduced to model the full distribution ([SemaVoice](https://arxiv.org/html/2605.16964v1)).

18. Formants are spectral-envelope peaks corresponding to vocal-tract resonances; F1 correlates with vowel height, F2 with backness, F3 the highest of the key three ([Edinburgh Source-Filter Model PDF](https://speech.zone/wp-content/uploads/2021/10/Speech-Processing_-The-Source-Filter-Model-1.pdf); [Vaia](https://www.vaia.com/en-us/explanations/english/phonetics/source-filter-theory/)).

19. Source and filter are (idealized as) independent: changing F0 changes pitch while harmonics shift but formants stay — vowel identity rides on the spectral envelope, pitch on the source ([Source-filter model — speech.zone](https://speech.zone/courses/speech-processing/module-4-the-source-filter-model/videos-3/source-filter-model/)).

20. Formant frequencies differ systematically across accents for the same vowels (per Ferragne & Pellegrino 2010), so accent is partly encoded in F1/F2 ([Edinburgh Source-Filter Model PDF](https://speech.zone/wp-content/uploads/2021/10/Speech-Processing_-The-Source-Filter-Model-1.pdf)).

21. Zero-shot cloning does **not** fine-tune the model — a speaker encoder/prompt supplies voice characteristics at inference — whereas few-shot speaker adaptation fine-tunes on a small target-speaker set ([Voice Cloning: Comprehensive Survey](https://arxiv.org/html/2505.00579v1)).

22. In zero-shot cloning, timbre, prosody, emotion, style, and accent are derived directly from the reference, and **background noise/silence in the prompt substantially degrades** the clone ([Step-Audio-EditX Technical Report](https://arxiv.org/html/2511.03601v1)).

23. VoxCPM is a tokenizer-free, end-to-end diffusion-autoregressive TTS that clones from a short reference (capturing timbre, accent, rhythm, pacing) — and will replicate the prompt's background ambiance unless prompt enhancement (ZipEnhancer denoiser) is enabled ([openbmb/VoxCPM-0.5B](https://huggingface.co/openbmb/VoxCPM-0.5B)).

24. The official VoxCPM2 repo provides LoRA fine-tuning tooling (`lora_ft_webui.py`), confirming LoRA-baked cloning is a supported path alongside prompt-based zero-shot cloning ([OpenBMB/VoxCPM GitHub](https://github.com/OpenBMB/VoxCPM)).

## Detailed Analysis

### Mixed-precision memory

The most-cited misconception this theme corrects is that mixed precision converts the model to fp16. The PyTorch docs show the opposite: the model and optimizer are created in default precision, only the forward pass is wrapped in `torch.autocast`, and users are explicitly told *not* to call `.half()` or `.bfloat16()` on the model or inputs ([torch.amp](https://docs.pytorch.org/docs/stable/amp.html)). Autocast instead casts each op at runtime — `torch.mm` runs in fp16 and produces fp16 output even from fp32 inputs — matching ops that are fast in low precision (linear layers, convolutions) against ops that need fp32's dynamic range (reductions). No provided source states verbatim "parameters stay in stored dtype," but the docs' guidance (don't cast the model; create in default precision; op-level casting in the forward pass) implies it strongly; the journal should phrase it as an inference rather than a quote.

Underneath autocast sits the classic three-part recipe from the 2018 ICLR "Mixed Precision Training" paper (arXiv:1710.03740), summarized by secondary guides: an **fp32 master copy** of weights, selective fp16/fp32 op assignment, and loss scaling ([PyTorch Training Performance Guide](https://residentmario.github.io/pytorch-training-performance-guide/mixed-precision.html); [TDS archive](https://medium.com/data-science/the-mystery-behind-the-pytorch-automatic-mixed-precision-library-d9386e4b787e)). The master copy is *why* AMP does not simply halve all memory: an fp32 weight shadow persists. Note one gap — the user's specific question about autocast caching lower-precision weight copies during the forward pass (`cache_enabled`) is **not** supported by the scraped sources, which were truncated before that subsection; it should not be cited from these files.

### LoRA / optimizer memory

The fp32-vs-bf16 "memory trap" follows directly from byte-per-parameter constants: fp32 = 4 B, fp16/bf16 = 2 B, int8 = 1 B ([Transformers Arithmetic](https://medium.com/@kailaspsudheer/the-transformers-arithmetic-527111099527)). For the journal's ~2B model, weights alone are ~8 GB in fp32 vs ~4 GB in bf16 (derived, not directly quoted). But weights are only one of four terms. Training memory = weights + gradients (same dtype as weights, 2–4 B/param) + optimizer states + activations ([Lyceum](https://lyceum.technology/magazine/gpu-memory-requirements-transformer/)). For AdamW in mixed precision, optimizer states are ~12 B/param: fp32 master weights (4) + first moment (4) + second moment (4). Summed, full fine-tuning costs ~16 B/param before activations — consistent with Modal's "16 GB/1B" full-FT rule of thumb ([Modal](https://modal.com/blog/how-much-vram-need-fine-tuning)).

There is a benign bookkeeping discrepancy worth flagging: Lyceum/Modal fold the fp32 master copy into the 12 B optimizer total, while the Transformers-Arithmetic post counts 12 B as gradient-copy + momentum + variance and treats the master separately. Both agree the AdamW optimizer-state total is 12 B/param (fp32), reducible to ~6 B/param with 8-bit Adam ([APXML](https://apxml.com/courses/lora-peft-efficient-llm-training/chapter-5-peft-optimization-deployment/peft-infrastructure-requirements)). The journal should pick one decomposition and state it explicitly.

Critically, **activations** are the only per-batch term — they scale with batch size × sequence length × hidden dim — which is why OOM occurs even when weights fit, and why activation/gradient checkpointing (recompute activations in the backward pass for ~33% more compute) is a standard escape hatch ([Lyceum](https://lyceum.technology/magazine/gpu-memory-requirements-transformer/)).

LoRA is the lever that makes this fit in 24 GB. Because LoRA freezes the full base and trains only adapters, gradients merely pass *through* the frozen weights to update adapters, so gradient and optimizer memory are allocated only for the small adapter set ([QLoRA, arXiv:2305.14314](https://arxiv.org/abs/2305.14314); [APXML](https://apxml.com/courses/lora-peft-efficient-llm-training/chapter-5-peft-optimization-deployment/peft-infrastructure-requirements)). The QLoRA paper's 7B breakdown makes the proportions vivid: adapters ~26 MB, LoRA input gradients ~567 MB, 4-bit base ~5,048 MB — so even aggressively shrinking adapters yields only minor savings; the dominant terms are base weights and activation gradients ([QLoRA PDF](https://arxiv.org/pdf/2305.14314)). QLoRA's headline (65B from >780 GB to <48 GB) is an aggregate combining 4-bit quantization *and* the LoRA freeze, not an isolated optimizer-state measurement.

Finally, a PEFT-specific dtype detail relevant to debugging NaNs: PEFT loads LoRA adapters in **fp32 by default** even when the base is bf16/fp16 or 4-bit quantized, because low-precision adapters are prone to instability under AMP; the base linear layers stay in low precision (e.g., uint8) while `lora_A`/`lora_B` resolve to fp32 ([PEFT issue #2421](https://github.com/huggingface/peft/issues/2421)). A forum report of bf16 LoRA producing `nan` grad_norm and `inf`/`0.0` loss corroborates the motivation, though it is tertiary and hardware/config-specific ([HF Forums](https://discuss.huggingface.co/t/bf16-training-instability-with-llama-3-1-8b-lora-dora-peft/170326)).

### TTS evaluation & MOS

MOS (the output of an Absolute Category Rating test) is a 1–5 Likert rating with roots in ITU P.800 (general) and the TTS-specific ITU-T P.85, which itself builds on P.800 ([Le Maguer et al.](https://www.sciencedirect.com/science/article/abs/pii/S0885230823000967); [Viswanathan & Viswanathan](https://www.sciencedirect.com/science/article/abs/pii/S0885230803000676)). It dominates — ~two-thirds of recent submissions use ACR/MOS — largely because it is easy and scalable. But the literature is sharply critical: MOS suffers Likert compression, is *relative* despite its "absolute" framing (sensitive to which systems and anchors are present), and its significance is hard to estimate given listener/utterance bias. Some researchers argue the paradigm is fundamentally flawed and should be discarded; the Le Maguer paper itself concludes overall-quality MOS is a "cul-de-sac." TTSDS adds that MOS saturates as synthetic and real speech converge, cannot be compared across studies/time, and that human ratings themselves drift ([TTSDS](https://arxiv.org/html/2407.12707v3)).

Alternatives appear throughout: DMOS (ACR with hidden reference, ITU P.910), MUSHRA, Best-Worst Scaling, A/B preference tests with Elo, and SMOS for speaker similarity ([Le Maguer et al.](https://www.sciencedirect.com/science/article/abs/pii/S0885230823000967); [Voice Reconstruction framework](https://arxiv.org/html/2606.21343v1)). Automatic neural predictors (UTMOS) act as proxies, but their accuracy is inconsistent: VoiceMOS-2022 reported system-level SRCC >0.9, whereas TTSDS reports 0.05–0.85 across cross-era systems — not a contradiction, but different datasets and conditions. For the journal's single-speaker clone, the practical takeaway is that MOS-style absolute scores are weak signals, especially for near-human output, and similarity (SMOS) plus comparative tests are more defensible. Note: no source here defines CMOS or ABX by name.

### Stochastic decoding & seed variance

VoxCPM's diffusion-autoregressive design is inherently stochastic at the sampling step. Diffusion models run a forward process that maps data to Gaussian noise and a reverse process that **generates samples from that noise prior** ([Bridge-TTS](https://arxiv.org/html/2312.03491v1)). Bridge-TTS's own contribution — replacing the "noisy Gaussian prior" with a "clean and deterministic one" — confirms by contrast that conventional diffusion TTS starts from random noise, and that the model family admits both stochastic and deterministic samplers. Flow-matching decoders (CosyVoice 2, Voicebox, Matcha-TTS) follow a probabilistic density path via ODE sampling; the randomness enters through the initial noise draw even when the solver is deterministic ([CosyVoice 2](https://arxiv.org/html/2412.10117v3); [WavTTS](https://arxiv.org/html/2606.03455v1)). The flip side — diversity as a feature — is documented by the contrast between deterministic regression TTS (over-smoothed, low-diversity) and sampling-based generative TTS (high diversity, nuanced prosody) ([SemaVoice](https://arxiv.org/html/2605.16964v1); [CosyVoice 2](https://arxiv.org/html/2412.10117v3)).

Two honest gaps: none of these sources use the word "seed" or state that "a single sample is not a reliable measure of model quality." Both are reasonable inferences from the documented noise-based sampling mechanism, but they are not verbatim-supported; the citations back only the upstream premise (stochastic generation from a noise prior / probabilistic path), not the seed conclusion itself.

### Voice acoustics — timbre / cadence / accent

The source-filter model cleanly separates the two halves of a voice. The **source** is vocal-fold vibration (voiced) or turbulent airflow (unvoiced); its repetition rate is the fundamental frequency F0, the acoustic correlate of perceived pitch (with the missing-fundamental caveat that the brain reconstructs F0 from harmonics) ([Edinburgh PDF](https://speech.zone/wp-content/uploads/2021/10/Speech-Processing_-The-Source-Filter-Model-1.pdf)). The **filter** is the vocal tract; its resonances are formants — peaks in the spectral envelope — which determine vowel identity. F1 tracks vowel height (mouth openness), F2 tracks backness (constriction front/back), F3 rounds out the three most important formants visible up to ~3000 Hz ([UMN Listen Lab](https://www.youtube.com/watch?v=wUE6Q8l17qI); [Vaia](https://www.vaia.com/en-us/explanations/english/phonetics/source-filter-theory/)).

The independence of source and filter — change F0 and harmonics shift while formants (and thus the vowel) stay fixed — is demonstrated by synthesis on the Edinburgh course ([speech.zone video](https://speech.zone/courses/speech-processing/module-4-the-source-filter-model/videos-3/source-filter-model/)), though the slides flag it as a "simplification of reality" with real biomechanical interactions. This maps directly onto the journal's vocabulary: **pitch/cadence** are source properties (F0, phonation type — modal/breathy/creaky); **timbre** is tied to formant/resonance structure, made vivid by helium speech, where resonances shift up and timbre changes without a pitch change. Because resonances scale with vocal-tract length and shape, different speakers produce different formants for the same vowel — the (indirect) basis for speaker timbre. **Accent** is encoded partly in F1/F2: formant frequencies differ systematically across accents for the same vowels (Ferragne & Pellegrino 2010). A clone that reproduces timbre, accent, and cadence is therefore reproducing both the source excitation and the filter's formant structure. Caveat: all sources here are secondary (Edinburgh teaching materials) or tertiary (UMN video, Vaia); the underlying primary references (Johnson 2012; Ferragne & Pellegrino 2010) were not directly scraped.

### Zero-shot vs fine-tuned cloning

The literature draws a clean line. **Zero-shot cloning** does not fine-tune the model: a speaker encoder or audio prompt supplies voice characteristics at inference, deriving timbre, prosody, emotion, style, and accent directly from the reference ([Voice Cloning Survey](https://arxiv.org/html/2505.00579v1); [Step-Audio-EditX](https://arxiv.org/html/2511.03601v1); [MM-Sonate](https://arxiv.org/html/2601.01568v1)). The hazard is that *everything* in the prompt is copied — including background noise and silence, which substantially degrade the clone; one common paradigm reproduces all speaker features but leaves them "deeply entangled and uncontrollable." This motivates reference denoising. **Few-shot speaker adaptation** (the journal's LoRA path) instead fine-tunes on a small target-speaker set, baking the voice into weights at the cost of extra training compute, with quality degrading as adaptation data shrinks ([Scientific Reports](https://www.nature.com/articles/s41598-025-90507-0)).

For VoxCPM specifically, the model card confirms it is tokenizer-free and end-to-end diffusion-autoregressive, clones from a short reference (capturing timbre, accent, rhythm, pacing), and will replicate the prompt's background ambiance unless "Prompt Speech Enhancement" is enabled. That enhancement is an **external, optional** denoiser — ZipEnhancer (`iic/speech_zipenhancer_ans_multiloss_16k_base` from ModelScope), exposed via `denoise=True` / `--denoise` / `--no-denoiser` — not a baked-in weight ([VoxCPM-0.5B card](https://huggingface.co/openbmb/VoxCPM-0.5B)). Crucially, the official VoxCPM2 GitHub repo ships LoRA fine-tuning tooling (`lora_ft_webui.py`, "fine-tuning support" commits), confirming the LoRA-baked path the journal pursues exists alongside prompt-based cloning ([OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM)). A parameter-count caveat: the documented card describes VoxCPM-0.5B (MiniCPM-4 base), while the journal targets a ~2B VoxCPM2; the 0.5B figures (and RTF 0.17 on RTX 4090) document the predecessor checkpoint, not necessarily VoxCPM2.

## Contrarian Views And Risks

- **MOS may be worth keeping for some uses.** Viswanathan & Viswanathan cite evidence that MOS tests are "reliable" for TTS, even as the weight of newer evidence (Le Maguer 2024; TTSDS; the voice-reconstruction framework) argues MOS is unreliable, insensitive, and saturating for near-human systems. The journal should not present MOS as uniformly discredited, but note the trend.
- **Automatic MOS predictors give conflicting reliability stories.** VoiceMOS-2022 system-level SRCC >0.9 vs TTSDS's 0.05–0.85 are both true under different conditions; do not generalize either number.
- **The "16 bytes/param" / "16 GB per 1B" figures are full-FT upper bounds, not the LoRA footprint.** Presenting them as the project's actual VRAM cost would be misleading; under LoRA, optimizer/gradient memory collapses to the adapter scale, and base weights + activations dominate.
- **Source-filter independence is an idealization.** The Edinburgh slides explicitly label pitch/vowel independence a "simplification of reality" with biomechanical interactions; treat pitch (source) and timbre (filter) separability as a model, not a law.
- **Seed-variance and single-sample-unreliability are inferences, not citations.** No provided source uses "seed" or states a single sample is unreliable for evaluation. Cite the sources only for the upstream stochastic-sampling mechanism.
- **VoxCPM source-quality and version risk.** Capability claims come from a project-authored, marketing-toned model card for the 0.5B predecessor; the ~2B VoxCPM2 architecture/param count is not directly evidenced (README truncated). RTF figures differ (0.17 vs 0.15) across mirrors.
- **Future-dated preprints.** Several arXiv IDs (2511.x, 2601.x, 2605.x, 2606.x) carry 2025–2026 timestamps; treat as recent/preprint-stage primary sources whose claims align with established literature but whose dates are uncertain.

## Open Questions

1. Does PyTorch autocast cache lower-precision weight copies during the forward pass (`cache_enabled`)? The behavior is real but the scraped docs were truncated before that subsection — fetch the "Autocast caching" section of the torch.amp page to cite precisely.
2. What is the *isolated* optimizer-state memory saving from the LoRA freeze (separate from quantization)? No provided source gives a pure before/after; QLoRA's >780→<48 GB bundles both.
3. What is VoxCPM2's actual parameter count and architecture (vs the documented 0.5B card)? The repo README was truncated.
4. How much does VoxCPM output actually vary seed-to-seed in practice, and how many samples are needed for a stable similarity judgment? Not addressed by the stochastic-sampling sources.
5. What is the recommended/minimum reference duration for VoxCPM cloning? Only a secondary "~10 second" illustrative figure exists; no primary spec.
6. For the journal's single-speaker clone, which comparative protocol (SMOS, BWS, MUSHRA, A/B-Elo) gives the most reliable signal at near-human quality?

## Sources

### Primary
- [Automatic Mixed Precision package — torch.amp (PyTorch docs)](https://docs.pytorch.org/docs/stable/amp.html) — op-level runtime casting; do not cast the model; autocast wraps only the forward pass.
- [QLoRA: Efficient Finetuning of Quantized LLMs (arXiv:2305.14314)](https://arxiv.org/abs/2305.14314) — LoRA freezes base, trains adapters; precision split (4-bit base / 16-bit adapters / 32-bit optimizer state).
- [QLoRA PDF (arXiv:2305.14314)](https://arxiv.org/pdf/2305.14314) — concrete 7B breakdown: 26 MB adapters, 567 MB LoRA gradients, 5,048 MB 4-bit base; >780→<48 GB.
- [Adapters saved in float16 are loaded in float32 · Issue #2421 (huggingface/peft)](https://github.com/huggingface/peft/issues/2421) — PEFT keeps adapters fp32 by default for AMP stability; base stays low-precision.
- [The limits of the Mean Opinion Score for speech synthesis evaluation (Le Maguer et al., 2024)](https://www.sciencedirect.com/science/article/abs/pii/S0885230823000967) — ACR/MOS definition, dominance, relativity, "cul-de-sac" critique.
- [Measuring speech quality for TTS: modified MOS scale (Viswanathan & Viswanathan, 2005)](https://www.sciencedirect.com/science/article/abs/pii/S0885230803000676) — ITU-T P.85 TTS MOS, built on P.800.
- [TTSDS — Text-to-Speech Distribution Score (arXiv:2407.12707v3)](https://arxiv.org/html/2407.12707v3) — MOS saturation, non-comparability, inconsistent auto-MOS prediction.
- [An Evaluation Framework for TTS Voice Reconstruction (arXiv:2606.21343v1)](https://arxiv.org/html/2606.21343v1) — MOS limitations; SMOS; BWS/MUSHRA; UTMOS.
- [Schrödinger Bridges Beat Diffusion Models on TTS (arXiv:2312.03491v1)](https://arxiv.org/html/2312.03491v1) — diffusion generates from a Gaussian-noise prior; stochastic vs deterministic samplers.
- [CosyVoice 2 (arXiv:2412.10117v3)](https://arxiv.org/html/2412.10117v3) — autoregressive sampling produces varied speech; flow-matching probabilistic density path.
- [SemaVoice (arXiv:2605.16964v1)](https://arxiv.org/html/2605.16964v1) — regression TTS = over-smoothed/low-diversity; diffusion models the distribution.
- [WavTTS (arXiv:2606.03455v1)](https://arxiv.org/html/2606.03455v1) — flow matching, ODE sampling, noise scheduling.
- [Voice Cloning: Comprehensive Survey (arXiv:2505.00579v1)](https://arxiv.org/html/2505.00579v1) — zero-shot (no fine-tune) vs few-shot speaker adaptation.
- [Step-Audio-EditX Technical Report (arXiv:2511.03601v1)](https://arxiv.org/html/2511.03601v1) — prompt noise/silence degrades zero-shot cloning; denoising/silence-trimming.
- [MM-Sonate (arXiv:2601.01568v1)](https://arxiv.org/html/2601.01568v1) — zero-shot timbre injection; entangled/uncontrollable prompt features.
- [High fidelity zero-shot speaker adaptation with denoising diffusion GAN (Scientific Reports)](https://www.nature.com/articles/s41598-025-90507-0) — zero-shot vs fine-tuning trade-offs.
- [openbmb/VoxCPM-0.5B (Hugging Face)](https://huggingface.co/openbmb/VoxCPM-0.5B) — tokenizer-free diffusion-AR; cloning captures accent/rhythm/pacing; external ZipEnhancer denoiser; RTF 0.17 on RTX 4090.
- [OpenBMB/VoxCPM (GitHub)](https://github.com/OpenBMB/VoxCPM) — VoxCPM2; LoRA fine-tuning tooling (`lora_ft_webui.py`).
- [Speech Processing: The Source-Filter Model PDF (Edinburgh, Module 4)](https://speech.zone/wp-content/uploads/2021/10/Speech-Processing_-The-Source-Filter-Model-1.pdf) — formants, F0/pitch, timbre/helium, accent (F1/F2). *Secondary (authoritative teaching material).*
- [Source-filter model — speech.zone video (Edinburgh, Module 4)](https://speech.zone/courses/speech-processing/module-4-the-source-filter-model/videos-3/source-filter-model/) — source/filter independence demonstration. *Secondary.*

### Secondary
- [Mixed Precision — PyTorch Training Performance Guide](https://residentmario.github.io/pytorch-training-performance-guide/mixed-precision.html) — fp32 master-copy recipe (origin arXiv:1710.03740).
- [The Mystery Behind PyTorch AMP (TDS Archive)](https://medium.com/data-science/the-mystery-behind-the-pytorch-automatic-mixed-precision-library-d9386e4b787e) — summarizes the 2018 mixed-precision paper.
- [Estimate runtime and memory for LLM Training (Medium)](https://medium.com/@kailaspsudheer/the-transformers-arithmetic-527111099527) — bytes-per-param constants; gradients in weight dtype.
- [GPU Memory Requirements for Transformer Models (Lyceum)](https://lyceum.technology/magazine/gpu-memory-requirements-transformer/) — four-term memory decomposition; Adam 12 B/param; ~16 B/param; activation checkpointing.
- [How much VRAM do I need for LLM fine-tuning? (Modal)](https://modal.com/blog/how-much-vram-need-fine-tuning) — ~16 GB/1B full-FT rule of thumb; LoRA much lower.
- [Infrastructure Requirements for PEFT Training (APXML)](https://apxml.com/courses/lora-peft-efficient-llm-training/chapter-5-peft-optimization-deployment/peft-infrastructure-requirements) — AdamW = 2× params (fp32) optimizer state; 8-bit/paged optimizers; LoRA cuts optimizer/gradient memory.
- [Speech Acoustics 4 — Source-filter model (UMN Listen Lab, YouTube)](https://www.youtube.com/watch?v=wUE6Q8l17qI) — formant = vocal-tract resonance; tongue→formants→vowel. *Tertiary (auto-transcribed).*
- [Source Filter Theory (Vaia)](https://www.vaia.com/en-us/explanations/english/phonetics/source-filter-theory/) — F1=height, F2=backness, F3 highest. *Tertiary, snippet only.*
- [VoxCPM (GitCode mirror)](https://gitcode.com/OpenBMB/VoxCPM) — RTF 0.15; tokenizer-free diffusion-AR. *Secondary mirror, translated.*
- [VoxCPM: Tokenizer-Free TTS and Voice Cloning (Medium)](https://medium.com/data-science-in-your-pocket/voxcpm-tokenizer-free-tts-and-voice-cloning-ai-af2acdd4f25f) — ~10s reference example; continuous-space modeling. *Secondary.*
- [Bf16 Training Instability with Llama-3.1-8B + LoRA/DoRA (HF Forums)](https://discuss.huggingface.co/t/bf16-training-instability-with-llama-3-1-8b-lora-dora-peft/170326) — anecdotal NaN/inf under bf16 adapters. *Tertiary.*

## Rerun Inputs

- **Workflow:** firecrawl-deep-research
- **Depth:** thorough
- **Topic:** ML concepts behind LoRA fine-tuning VoxCPM2 for English voice cloning on a 24 GB RTX 4090 — mixed-precision memory, LoRA/optimizer memory, TTS/MOS evaluation, stochastic decoding & seed variance, voice acoustics (timbre/cadence/accent), zero-shot vs fine-tuned cloning.
- **Source preferences:** Prefer primary (PyTorch/HF docs, arXiv, peer-reviewed); mark blogs secondary, forums tertiary. Flag inferences vs direct quotes; flag full-FT vs LoRA scope.
- **Known gaps to close on rerun:** autocast weight-caching (`cache_enabled`) subsection of torch.amp docs; isolated LoRA optimizer-state saving; VoxCPM2 (not 0.5B) param count/architecture; explicit seed-variance and single-sample-reliability sources; primary phonetics references (Johnson 2012; Ferragne & Pellegrino 2010); ITU-T P.800/P.85/P.910 primary texts.