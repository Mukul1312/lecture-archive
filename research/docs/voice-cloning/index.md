# Voice cloning

!!! danger "History — superseded on 2026-07-10"
    The goal here was to clone **Gour Govinda Swami's own English voice** with VoxCPM2 and a LoRA
    adapter, to narrate a calm diary Short. On 2026-07-10 that goal was withdrawn: narration is to
    use a **different voice**, not his. Nothing below is deleted, because the measurements — on
    speaker similarity, identity verification and what actually damages a clone — remain useful
    and were expensive to obtain. Nothing below is current authority for cloning anyone's voice.

    Narration work now lives in the separate `narrator-voice` repository under ADR-0013.

## What this work established

- **Identity is measurable, and the measurement has to be adversarial.** A clone that sounds right
  to its maker is not evidence; the verification pages describe what passes and what does not.
- **A dissimilarity gate is worth more than a similarity score.** The useful question is not "how
  close is it?" but "is it close enough to be mistaken for him?", which is a threshold with
  consequences.
- **Noisy sources plateau.** The data-preparation work hit an ECAPA plateau around 0.74 that more
  cleaning did not move — the limit was the source material, not the pipeline.
- **Expressiveness was pre-registered and then tested**, rather than judged after the fact.

## The pages

**Understanding the method**

- [The ML concepts behind the clone](ggs-clone-concepts-research.md) — the longest piece here, and
  the one to read first if the vocabulary is unfamiliar.
- [LoRA fine-tuning research](lora-finetune-research-2026-07-07.md) — fastbook and modern PEFT,
  mapped onto VoxCPM2.
- [VoxCPM2 markup and prosody control](voxcpm2-markup-research-2026-07-08.md)
- [Prosody and emphasis for English → Hindi dubbing](prosody-dubbing-research-2026-07-08.md)

**Measurements and state**

- [Project findings and state](project-findings.md) — the durable record of what was built.
- [Identity verification and robustness](identity-verification.md)
- [The voice dissimilarity gate](voice-dissimilarity-gate-2026-07-20.md) — the first measurement.
- [The expressiveness experiment](narration-expressiveness-experiment-2026-07-09.md) — with
  predictions registered before the results.
- [Narration cost analysis](narration-cost-analysis-2026-07-20.md)

See also the [Hindi clone](../hindi/index.md), which extended this work and was superseded on the
same date.
