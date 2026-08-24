# Narration voice — cost analysis (2026-07-20)

*Budget note for the Hindi diary & lecture-teaching Shorts. Written to be presentable to seniors.*

## Bottom line

Across every option and every series length considered, the narration bill lands between
**$0 and $132 for the whole project** — not per month. The spread between cheapest and most
expensive is roughly **$100 over a year**.

**This decision should not be made on price.** The amounts are too small to matter. It should be
made on two things that do: whether the narrator's voice can disappear mid-series, and which engine
can actually deliver expressive devotional narration.

| | Full project |
|---|---|
| Sarvam API | **$0–24** |
| Self-hosted on RunPod | **$29–73** |
| ElevenLabs subscription | **$44–132** |

## The assumptions — challenge these

Every number below derives from these five inputs. If one is wrong, totals change proportionally.

| Input | Value |
|---|---|
| Length of one Short (narration) | 3 min |
| Hindi characters per Short | 2,250 |
| Re-render factor (retakes, fixes, seed re-rolls) | ×3 |
| Billable characters per finished Short | 6,750 |
| Exchange rate used | ₹85 = $1 |

The **re-render factor** is the one worth scrutinising — narration is rarely right on the first
pass. If production proves cleaner, costs fall; if we tune prosody heavily, they rise. At these
absolute amounts, even a ×10 factor would not change the recommendation.

## Cost by series length

| Option | 25 Shorts | 50 Shorts | 100 Shorts |
|---|---|---|---|
| **Sarvam Bulbul v3** (₹30/10k chars) | $0 | $0 | $12 |
| **Self-hosted on RunPod** (Parler-TTS / VoxCPM2) | $29 | $41 | $73 |
| **ElevenLabs Creator** ($22/mo, 121k credits/mo) | $44 | $66 | $132 |

Sarvam totals are net of the ₹1,000 free credit that ships with every plan, which alone covers
roughly the first 48 Shorts.

## Why self-hosting costs more, despite "free" software

The models are free and open-source. The expense is not the software — a rented GPU bills for
**time**, including time it sits idle.

| RunPod cost component | 25 | 50 | 100 |
|---|---|---|---|
| GPU time generating audio (A40 @ $0.44/hr, ~0.5 hr/Short) | $6 | $11 | $22 |
| Storage, accruing monthly (~100 GB @ $0.07/GB/mo, billed whether used or not) | $14 | $21 | $42 |
| One-time setup and voice testing (~20 hrs) | $9 | $9 | $9 |
| **Total** | **$29** | **$41** | **$73** |

**In every scenario, idle storage costs more than the actual audio generation.**

> ⚠️ **Unverified figure.** The 100 GB storage estimate is assumed, not measured — RunPod's
> volume-listing endpoint currently errors for our account. The real volume may be smaller, which
> would reduce the self-hosting total. Confirm before quoting externally.

## The risk that actually matters

Cost separates these options by ~$100. Voice continuity separates them far more meaningfully,
because this series depends on **one recognisable narrator across every episode**.

| Option | Can the voice disappear? | Rights |
|---|---|---|
| **Indic Parler-TTS** ✅ safest | No. Apache-2.0, self-hosted, frozen permanently. | Commercial use permitted, no attribution. |
| **Sarvam Bulbul v3** | Low. Preset speakers may shift across model versions, but past outputs remain ours. | Outputs explicitly assigned to us. No attribution. |
| **ElevenLabs** ⚠️ continuity risk | **Yes.** Default voices **expire 31 Dec 2026**; library voices may be withdrawn "with or without notice." | Commercial on all paid tiers. Free tier requires "elevenlabs.io" in the video title. |

> ⚠️ **If we choose ElevenLabs, we must archive every generated file.** Audio produced during a paid
> subscription stays usable indefinitely, but the voice itself may become unavailable to generate
> *new* episodes with. For a multi-year series, a narrator changing partway through is a break the
> audience will hear.

> ⚠️ **Licensing trap.** Sarvam's open-weight models on HuggingFace are licensed **non-commercial
> only**. Only their paid API grants commercial rights. We must not self-host those weights.

## Recommendation

1. **Test before committing, at near-zero cost.** Compare all candidate voices on the same Hindi
   passage for roughly **$7** total — Sarvam's free credits, one month of ElevenLabs' $6 entry tier,
   and Parler-TTS run locally. Requires no GPU rental at all.
2. **Do not rent a GPU yet.** At our volume, renting a computer by the hour costs more than paying
   per word. Revisit only if the open models prove clearly better and local testing becomes too slow.
3. **Prefer Sarvam or Parler-TTS for production**, on continuity grounds rather than price.
4. **Budget ask: under $150 for the full project**, whichever option wins. Not a line item worth
   optimising — drive the decision on narration quality and voice permanence.

---
Pricing verified July 2026 from published rate cards for Sarvam AI, ElevenLabs and RunPod. Character
estimates derived from Hindi speech at ~150 words/min. Storage volume size assumed pending confirmation.
