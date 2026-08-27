# Evidence — Hosted ASR API Tier Pricing, 2026-08-27

Verification of the one figure [05](../05-odia-gpu-cost-model.md) flagged as unverified: the
**$3.02 per audio-hour** attributed to Azure `or-IN` + Sarvam `od-IN` + ElevenLabs Scribe +
LLM reconciliation, which doc 05 §6 identifies as **~98% of compute spend** and doc 05 §9
records as *"derived from it by subtraction and should be verified directly against Azure,
Sarvam and ElevenLabs list pricing before use in a quote."*

Retrieved **2026-08-27**. **USD/INR = 95.5** (Wise / investing.com, 2026-08-27).

**Result: the figure is overstated by roughly 3–4x.** The list-price total is
**$0.73–$1.03 per audio-hour**, not $3.02.

---

## 1. The three engines

| Engine | Service | List rate | USD/audio-hr | Confidence |
|---|---|---|---:|---|
| **Sarvam** | Speech to Text **+ Translate** | ₹30/hour | **$0.314** | High — see §4 |
| **Azure** | `S1 Speech to Text Batch` | $0.18/hour | **$0.180** | **Authoritative** |
| **ElevenLabs** | Scribe v2 (batch API) | $0.22/hour | **$0.220** | High |
| | **Three engines, same audio** | | **$0.714** | |

Plus LLM reconciliation, §3: **$0.02–$0.32**. **Total $0.73–$1.03 per audio-hour.**

---

## 2. Azure — from the retail prices API, not the pricing page

Azure's public pricing page renders its numbers client-side after a region/currency
selection, so it scrapes as `$-` placeholders. Two independent fetch attempts returned
nothing usable. **Microsoft publishes the same data as an unauthenticated REST API**, which
is authoritative and needs no scraper:

```
https://prices.azure.com/api/retail/prices?currencyCode=USD
  &$filter=armRegionName eq 'centralindia' and productName eq 'Azure Speech'
```

Service `Foundry Tools`, product `Azure Speech`. Non-commitment speech-to-text meters:

| Meter | Central India | East US |
|---|---:|---:|
| **`S1 Speech to Text Batch`** | **$0.18/hr** | **$0.18/hr** |
| `S1 Custom Speech to Text Batch` | $0.225/hr | $0.225/hr |
| `Fast Transcription Speech To Text` | $0.36/hr | $0.36/hr |
| `Custom - Fast Transcription Speech To Text` | $0.45/hr | $0.45/hr |
| `S1 Speech to Text Enhanced Feature Audio` | $0.30/hr | $0.30/hr |

**Batch is the correct meter** for a 1,952-hour archive corpus; latency is irrelevant, so
Fast Transcription's 2x premium buys nothing here.

**Two corrections this API forced, both worth recording:**

1. Microsoft's own pricing-update blog announces Standard Batch at **$0.36/hr**, down from
   $1.00. That blog is **stale** — the meter now bills $0.18. Secondary sources, including
   Microsoft's own, were wrong about Microsoft's current prices.
2. $0.36 nonetheless appears in today's table as **Fast Transcription**, a different
   product. Reading the blog figure as the batch rate would have doubled this line by
   coincidence rather than by error.

**Region is not a variable for this line.** Central India and East US are identical across
every speech meter. This partly closes **Q1** in [06](../06-decisions-and-open-questions.md):
whatever the region decision costs elsewhere, it is free here.

**Do not buy a commitment tier.** `Commitment Tier Speech to Text Azure 2K Unit` is
$1,600/month for 2,000 hours — **$0.80/hour, over four times the pay-as-you-go batch rate.**
The commitment tiers price real-time, not batch.

---

## 3. LLM reconciliation

One audio-hour of lecture speech is roughly 9,000 words. Three ASR drafts in, one
reconciled transcript out, is approximately **40,000 input and 13,000 output tokens**.

| Model | Input | Output | Per audio-hour |
|---|---|---|---:|
| Sarvam 105B | ₹29.28/1M | ₹73.2/1M | ₹2.12 = **$0.02** |
| Frontier-class (~$3/$15 per 1M) | $3/1M | $15/1M | **$0.32** |

Either way this is a **minor line**, not the bulk of the $3.02. Doc 05 grouped it with the
ASR engines, which is reasonable, but it cannot account for the gap.

---

## 4. Sarvam contradicts itself by 2.5x — the one open uncertainty

| Source | Rate | Per hour |
|---|---|---:|
| `docs.sarvam.ai/api/getting-started/pricing` — developer pricing table | ₹30/hour | **₹30** |
| `sarvam.ai/apis/speech-to-text/odia` — product page, "Base plan" | ₹1.25/minute | **₹75** |
| `sarvam.ai/speech-to-text` — product page | ₹1.5/minute | **₹90** |

**₹30/hour is used here**, on the grounds that the developer pricing table is what governs
API billing and the product pages are marketing surfaces. **This is a judgement, not a
verified fact, and it is the only material uncertainty left in this document.** One email to
Sarvam settles it.

Sensitivity: at ₹75/hour the three-engine total becomes **$1.18/audio-hour** and the corpus
**$2,300** — still under half of doc 05's figure. **The conclusion survives either reading.**

**Sarvam bundles translation at no extra charge.** "Speech to Text" and "Speech to Text +
Translate" are both ₹30/hour; only diarization moves the price (₹45). The Odia → English
requirement is therefore free on this engine. Doc 05 does not appear to account for this.

---

## 5. Against the bid

| | Per audio-hour | x 1,952 hours |
|---|---:|---:|
| Doc 05 §6, derived by subtraction from the bid's ~$6,000 compute line | $3.02 | **$5,900** |
| **Verified from list prices** | **$0.73 – $1.03** | **$1,430 – $2,010** |
| Sarvam at the ₹75 product-page rate instead | $1.18 | $2,300 |
| Sarvam alone, if the pilot retires drafts 2 and 3 | $0.31 | **$613** |

**The compute line is overstated by roughly $4,000.**

> **Scope correction, added after reading the bid document.** This verification
> was undertaken on the belief that $3.02 sat in a submitted bid. It does not.
> `docs/odia-transcription-bid-estimate-2026-07-25.md` is **pre-bid** -- *"Not yet
> signed -- the client wants a cost estimate first"* -- and its section 2 already
> states *"Compute is a rounding error. GPU + API + LLM for the entire 1,952-hour
> corpus is ~$6k -- about 1% of the bid."* Correcting $5,900 to ~$1,800 moves
> compute from 1% of the bid to about 0.3%. **It confirms a claim the estimate
> already made, and changes no decision.**
>
> The number that decides this contract is **M, human work-hours per audio-hour**:
> credible range **5.5 to 36**, driving 40-70% of cost, adopted at 11.5 and flagged
> by the estimate itself as *"the number the pilot must measure."* Against a $215k
> Tier 1, moving M by one point outweighs every API question in this document
> combined. The Sarvam ambiguity in section 4 is worth about $920, or 0.4%.
>
> The pricing below stands and is correct. It is simply worth much less than the
> effort implied, and this note exists so nobody repeats the mistake of optimising
> the rounding error.

**The error is in the bid's favour** — margin is better than modelled, not worse. But an
inflated cost line can lose a bid on price, so it is worth correcting in either direction.

Because the $3.02 was obtained by subtracting a ~$100 GPU estimate from the bid document's
~$6,000 compute line, **the discrepancy is most likely in that $6,000 figure**, not in doc
05's arithmetic. Either the bid's compute line was estimated generously, or it covers items
beyond these APIs — retries, re-runs, enhancement, storage, egress. Doc 05 §9 already warns
that the $6k "has not been independently rebuilt here." **Rebuilding it is the natural next
step, and this document does not attempt it.**

---

## 6. Taxes and exclusions

- **Sarvam prices are in INR and almost certainly exclude 18% GST**: ₹30 → ₹35.40, or
  **$0.371/audio-hour**. Three-engine total with GST: **$0.771**.
- **ElevenLabs states "prices exclude taxes"** on its API pricing page.
- Azure retail prices exclude tax; Indian billing adds GST.
- All three vendors advertise volume or enterprise discounts. **None are modelled here** —
  every figure is undiscounted list, so the real cost is a ceiling, not an estimate.

---

## 7. What this document does not establish

- **Whether Odia is billed at standard rates.** No per-language meter appears in Azure's
  table and neither Sarvam nor ElevenLabs advertises a language premium, but this was not
  confirmed with any vendor.
- **Whether all three engines are needed.** That is the pilot's question — doc 05 §6 already
  frames it as "whether buying a 2nd/3rd ASR draft actually recovers errors." If the answer
  is no, the corpus cost falls to **$613**.
- **Accuracy.** This is a pricing document. The WER figures in doc 05 §3 are untouched, and
  a cheaper engine that transcribes Odia worse is not cheaper.
- **The bid's ~$6,000 compute line**, which remains unrebuilt.

---

## 8. Sources

| Figure | Source | Retrieved |
|---|---|---|
| Azure speech meters, all regions | `prices.azure.com/api/retail/prices` (unauthenticated REST API) | 2026-08-27 |
| Sarvam ₹30/hr STT and STT+Translate | `docs.sarvam.ai/api/getting-started/pricing` | 2026-08-27 |
| Sarvam ₹1.25/min product-page rate | `sarvam.ai/apis/speech-to-text/odia` | 2026-08-27 |
| Sarvam 105B token rates | `docs.sarvam.ai/api/getting-started/pricing` | 2026-08-27 |
| ElevenLabs Scribe v2 $0.22/hr batch, $0.39 realtime | `elevenlabs.io/pricing/api` | 2026-08-27 |
| USD/INR 95.5 | wise.com, investing.com | 2026-08-27 |
| Azure blog claiming $0.36 batch (**superseded**) | `techcommunity.microsoft.com` | 2026-08-27 |
