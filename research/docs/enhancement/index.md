# Audio enhancement

**The question.** HH Haladhara Swami's seven-part Jiva Goswami seminar — about twelve hours — is
noisy. How far can it be cleaned so it is pleasant for devotional listening, without damaging the
voice itself?

## The answer

- **Subtractive enhancement first.** Generative restoration is reserved for bandwidth extension,
  where it adds detail the recording never had rather than inventing speech.
- **Naturalness beats noise removal.** A cleaner file that sounds processed is a worse file. The
  signal-quality judgement is a **veto**, not one score among several — a candidate that damages
  the voice is rejected however much noise it removed.
- **The DeepFilterNet3 ceiling is now quantified**, and the comfortable explanation for it was
  wrong.

!!! warning "A claim that did not survive measurement"
    The received view was: *DFN3 already captures the available separation gain on the periodic
    component; the ceiling is the aperiodic component, which is structurally unpredictable and so
    cannot benefit from coherent-sum filtering.*

    **The first half survives and is now quantified. The second half is refuted by measurement** —
    and the diagnostic tooling that produced the original claim had a serious defect. See
    [How much separation DFN3 has available](dfn3-multiframe-ceiling-measurements-2026-08-31.md).

## The pages

**Method and tools**

- [Enhancement pipeline research](enhance-pipeline-research-2026-07-31.md) — the tool comparison
  and the pipeline chosen for the seminar.
- [How to analyse a recording](enhance-analysis-methodology-research-2026-07-31.md) — the
  industry-standard methodology for diagnosing what is wrong before trying to fix it.
- [Beyond DeepFilterNet: generative speech restoration](generative-restoration-research-2026-08-02.md)
  — what the generative models can and cannot be trusted with.

**Measurements**

- [How much separation DFN3 has available](dfn3-multiframe-ceiling-measurements-2026-08-31.md) —
  an experimental record on real lecture audio, including the refutation above.
- [Mel-spectral processing and voice anatomy](mel-spectral-and-voice-anatomy-research-2026-08-31.md)
  — what the representations actually encode, and what "perfect voice anatomy" would mean.

**Preparation**

- [Noisy-source data preparation](noisy-source-dataprep-research.md) — the research pass behind
  the 0.74 ECAPA plateau.
- [Clip segmentation policy](clip-segmentation-policy.md) — how audio is cut, and why.

!!! note "Reproducibility"
    The DFN3 measurements are a **dated experimental record, not a reproducible benchmark**: the
    analysis scripts were written in a session scratchpad and the lecture inputs live outside git.
    The findings and their limitations stand; the tooling would need rebuilding to re-run them.
