# 05 — Odia Transcription: GPU Cost Model

**Date:** 2026-08-24 · **Headline:** GPU provider choice is **economically irrelevant** to this
bid. The spread between cheapest and most expensive provider is roughly **$60–120 on a $215k
engagement** — under 0.1%.

Source for all corpus and bid figures:
`docs/odia-transcription-bid-estimate-2026-07-25.md`.

---

## 1. The workload

| Parameter | Value | Basis |
|---|---|---|
| Corpus | **1,357 files / 1,952 audio-hours** | Full enumeration plus `ffprobe`; 27/27 sampled confirm 64 kbps CBR |
| Mean lecture | 86 minutes | Measured |
| Full archive (all languages) | 2,020 files / ~2,831 h | Measured |
| Bid tiers | Tier 1 $215k · Tier 2 $510k · Tier 3 $940k | Bid document |
| **Compute line (GPU + API + LLM)** | **~$6k, about 1% of the bid** | Bid document |

---

## 2. What actually runs on a GPU — three constraints that reshape the question

These come from the bid document's sourced fact base and materially change the hardware
requirement:

1. **Whisper cannot transcribe Odia at all.** `or` / `ory` are absent from the tokenizer's
   language set; measured **125.6% WER** on real Odia. The GPU model is therefore *not*
   Whisper.
2. **MMS-1B-all is CC-BY-NC — commercially unusable** for a paid engagement.
3. **The only self-hosted engine is `ai4bharat/indic-conformer-600m-multilingual`** (best open
   Odia ASR: 20.6% WER / 12.1% OIWER on clean benchmark). Azure `or-IN` (35.1% on degraded
   field audio), Sarvam `od-IN` (35.8%) and ElevenLabs Scribe `ori` are **paid APIs**, not GPU
   workloads.

**Consequence for sizing:** a 600M-parameter Conformer needs roughly **3–5 GB VRAM**. The
24 GB cards this project has historically used are badly over-specced. T4 (16 GB) or L4
(24 GB) is the correct tier — and the binding constraint is throughput, not memory.

---

## 3. The unmeasured number, stated honestly

**There is no measured real-time factor for IndicConformer on this audio.** Producing one is
explicitly part of Gate 0a of the proposed pilot ("multi-engine ASR bake-off on 20 real
audio-hours").

Rather than guess a single figure, the model below is **bracketed** across a plausible range.
Conformer-class models commonly exceed 20x realtime on modern inference GPUs with batching,
but 64 kbps mono field audio with chunking overhead argues for caution. The 10x row is
deliberately pessimistic.

| Throughput | GPU-hours for 1,952 h |
|---|---:|
| 50x realtime (optimistic) | 39 |
| 20x realtime (central) | 98 |
| 10x realtime (pessimistic) | 195 |

---

## 4. The cost model

One full IndicConformer pass over the entire 1,952-hour corpus:

| Provider / rate | 39 GPU-h | 98 GPU-h | 195 GPU-h |
|---|---:|---:|---:|
| **E2E Networks spot** (~$0.18/h) | **$7** | **$18** | **$35** |
| **JarvisLabs spot** (~$0.19/h) | $7 | $19 | $37 |
| AWS `g4dn.xlarge` spot ($0.356/h) | $14 | $35 | $69 |
| **JarvisLabs on-demand** ($0.44/h) | $17 | $43 | $86 |
| **E2E on-demand** ($0.57/h) | $22 | $56 | $111 |
| AWS `g5.xlarge` spot ($0.675/h) | $26 | $66 | $132 |
| **AWS `g6.xlarge`** ($0.791–0.805/h) | $31 | $77 | **$154** |

**The entire GPU bill for a full corpus pass is between $7 and $154.**

Allowing three passes — the bake-off, a production run, and one reprocessing cycle — plus
generous padding, the realistic total is **$50–$500**.

---

## 5. Why this means the analysis does not matter

At the central 98 GPU-hour estimate, the spread from cheapest (E2E spot, $18) to most
expensive (AWS `g6`, $77) is **$59**. At the pessimistic 195-hour estimate it is **$119**.

Against a Tier 1 bid of $215,000, that spread is **0.03–0.06% of contract value.**

The bid document already concluded that "compute is a rounding error." This model refines
that: **GPU is a rounding error inside the rounding error.** Provider selection here cannot
move the commercial outcome and should not consume analytical effort.

---

## 6. Where the compute money actually is

> **Corrected 2026-08-27.** The $3.02 figure below was verified against list prices and is
> **overstated by roughly 3–4x**. The measured total is **$0.73–$1.03 per audio-hour**
> ($1,430–$2,010 for the corpus), against $3.02 ($5,900) here. Azure batch is $0.18/hr, not
> the $0.36 its own blog still advertises; Sarvam bundles Odia→English translation free at
> ₹30/hr; ElevenLabs Scribe v2 batch is $0.22/hr. Since $3.02 was obtained by subtracting the
> GPU estimate from the bid document's ~$6,000 compute line, **the discrepancy is most likely
> in that $6,000 figure**, which remains unrebuilt. Full working, sources and sensitivity:
> [evidence/api-tier-pricing-2026-08-27.md](evidence/api-tier-pricing-2026-08-27.md).
>
> **The original reasoning is left intact below.** Its structural conclusion — that the API
> tier dominates compute and GPU choice does not — is *strengthened*, not weakened: at
> $0.73–$1.03 per audio-hour the API tier is still ~93–95% of a corrected compute line, and
> GPU is still a rounding error.

If GPU is on the order of $100 and the total compute line is ~$6,000, then approximately
**$5,900 — about $3.02 per audio-hour — is Azure `or-IN` + Sarvam `od-IN` + ElevenLabs Scribe
+ LLM reconciliation.**

That is roughly **98% of compute spend, and none of it is a GPU-provider decision.**

**Implication:** if a compute cost lever is wanted on this bid, it is (a) API tier
negotiation and (b) whether the second and third ASR drafts actually recover enough errors to
justify their cost — a question the pilot is already designed to answer ("whether buying a
2nd/3rd ASR draft actually recovers errors"). Not hardware.

---

## 7. A hypothesis worth measuring: skip GPU entirely

If GPU cost is this trivial, the interesting question inverts: **is a GPU needed at all?**

A 600M Conformer on `c7g.xlarge` Spot at $0.065/h, if it achieves even 1–2x realtime, implies
976–1,952 CPU-hours and a total of **$63–$127** — competitive with GPU, while:

- sidestepping the AWS GPU quota gate entirely;
- avoiding contention for scarce L4 capacity;
- parallelising trivially across cheap, interruption-tolerant Spot instances;
- using the same CPU-batch infrastructure as the enhancement workload (category 1).

**This is a hypothesis with an unmeasured real-time factor, not a recommendation.** CPU
inference for a Conformer may well fall below 1x realtime, which would break the arithmetic.
But it is cheap to test alongside the Gate 0a engine bake-off, and if it holds it materially
simplifies the infrastructure.

---

## 8. Recommendations

1. **Do not optimise GPU spend.** At $7–$154 for the whole corpus, choose on operational fit
   and move on.
2. **If GPU is used, prefer JarvisLabs or E2E Networks** — India-based, roughly half AWS,
   per-minute billing, no quota gate, data sovereignty.
3. **Measure the IndicConformer real-time factor in Gate 0a**, on both GPU and CPU. It is the
   only number here that is guessed rather than known.
4. **Redirect cost analysis to the API tier**, which is ~98% of compute spend.
5. **Do not let GPU provider choice gate the bid.** It cannot move the outcome.

---

## 9. Caveats

- The RTF bracket is an estimate. Everything downstream of it inherits that uncertainty.
- Prices are 2026-08-24 snapshots; AWS figures are us-east-1 and ap-south-1 will differ.
- The $6k compute figure comes from the bid document and has not been independently rebuilt
  here; the $3.02/audio-hour API figure is derived from it by subtraction and should be
  verified directly against Azure, Sarvam and ElevenLabs list pricing before use in a quote.
  **Done 2026-08-27** — see [evidence/api-tier-pricing-2026-08-27.md](evidence/api-tier-pricing-2026-08-27.md).
  The API tier prices at **$0.73–$1.03/audio-hour**, so the $3.02 is 3–4x high and the
  ~$6,000 bid line is now the figure that needs rebuilding.
- This model covers **transcription inference only**. Enhancement of the same corpus is
  costed separately in [02](02-category-01-local-cpu-compute.md) at roughly $69–92.
