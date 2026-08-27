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

## 4. Sarvam's 2.5x contradiction — **SETTLED by invoice, 2026-08-27**

Three Sarvam pages disagreed:

| Source | Rate | Per hour |
|---|---|---:|
| `docs.sarvam.ai/api/getting-started/pricing` — developer pricing table | ₹30/hour | **₹30** |
| `sarvam.ai/apis/speech-to-text/odia` — product page, "Base plan" | ₹1.25/minute | **₹75** |
| `sarvam.ai/speech-to-text` — product page | ₹1.5/minute | **₹90** |

This was recorded as the one material uncertainty here, needing an email to Sarvam. **No
email was needed.** The steward had already run a real lecture through the console, and the
dashboard billed it:

> **₹38 for 51.4 minutes** of Saaras v3 Odia speech-to-text.

₹38 ÷ 0.857 h = **₹44.36/hour**. Checked forward: 3,084 s ÷ 3600 × ₹45 = **₹38.55**. At
₹30/hour the same audio would have cost ₹25.70; at ₹75/hour, ₹64.

So the billed rate is **₹45/hour — the diarization tier** — and the transcript confirms it,
carrying `Speaker 1` / `Speaker 2` labels throughout. **The developer table is correct; the
per-minute product-page figures are not what gets billed.**

**Rates as they appear on the steward's own dashboard**, which is the authority here:

| Service | Rate |
|---|---|
| Speech to text — real-time / streaming / batch | **₹30/hour** |
| Speech to text with diarization — batch | **₹45/hour** |
| Translate & transliterate | ₹2.00 / 1,000 characters |
| Sarvam 105B | ₹29.28 / ₹10.98 / ₹73.20 per 1M tokens |

Two corrections this forces. **The dashboard carries no "Speech to Text & Translate" line
at all** — that product appears only in the API docs, so the earlier claim that translation
comes bundled free could not be exercised from this account. And **translating the corpus
through Sarvam would cost more than transcribing it**: at ₹2 per 1,000 characters and
roughly 32,000 Odia characters per audio-hour, 1,952 hours is about ₹125,000 against
₹58,560 for the transcription. The steward translates with Claude instead, at no marginal
cost.

**A paid invoice beats a vendor's website.** The lesson outlasts the number: one lecture
actually run settled in minutes what three contradictory pages could not, and the research
that produced those three pages was mine.

**Diarization is being dropped** (2026-08-27). The speaker labels split a single lecturer's
speech more often than they identify a second voice. That takes the corpus from ₹87,840 to
**₹58,560 (~$613)** and yields cleaner text.

---

## 5. Against the bid

| | Per audio-hour | x 1,952 hours |
|---|---:|---:|
| Doc 05 §6, derived by subtraction from the bid's ~$6,000 compute line | $3.02 | **$5,900** |
| **Verified from list prices** | **$0.73 – $1.03** | **$1,430 – $2,010** |
| Sarvam at the ₹75 product-page rate instead | $1.18 | $2,300 |
| Sarvam alone, no diarization — **the actual plan** | **$0.31** | **$613** |

**The compute line was overstated by roughly $4,000 — but it never mattered.** See the scope
correction below: there is no contract, so no figure here decides anything.

### 5a. What actually constrains programme 1

Not money. **1,357 Oriya lectures at one per day is 3.7 years**, and Sarvam could process all
1,952 hours this month for ₹58,560. The corpus finishes when volunteers finish reading it, or
it finishes immediately if nobody has to.

The steward settled the standard on 2026-08-27: **devotees will read the transcript while
listening to the lecture.** That is decisive, because the reader always has the audio —
they hear the right word and see a wrong one, and carry on. Two consequences:

- **Timestamp accuracy matters more than word accuracy.** Following along breaks if timing
  drifts; it survives a mistranscribed word.
- **Audio-verified review is the wrong bar.** That is the standard for the GGSM Listening
  draft, which stands alone as a text. Here a light Odia read-through — catching nonsense,
  not checking against audio — is the matched level of effort, and the steward's senior
  reads Odia.

> **Scope correction, twice revised.** This verification was undertaken believing $3.02 sat
> in a submitted bid. Reading `docs/odia-transcription-bid-estimate-2026-07-25.md` showed it
> was **pre-bid** — *"Not yet signed"* — and that its section 2 already called compute *"a
> rounding error … about 1% of the bid"*. The steward then corrected the premise entirely:
>
> > **There is no client and no money.** Programme 1 is volunteer seva. The transcripts are
> > handed to a senior devotee; the "bid document" was a basic costing exercise, and the
> > people who will review the output are volunteers who are not paid.
>
> So the tier pricing ($215k / $510k / $940k), the renegotiation collar, the WER acceptance
> annex and the walk-away rights all describe machinery for a contract that does not exist.
> **M — human work-hours per audio-hour — stops being a cost driver and becomes a schedule
> input**, and the steward has said the schedule may stretch.
>
> What survives the correction: the measured corpus (1,952 h, ffprobe'd), the engine finding
> that Whisper cannot transcribe Odia at all while IndicConformer and Sarvam can, and the
> Unicode normalisation warning — which is now the live risk rather than a contract clause.
>
> **The real figure is ₹58,560 (~$613) for all 1,952 hours** at ₹30/hour without diarization.
> Small enough that it should shape no decision at all. The only real constraint is how much
> volunteer attention the output has to pass through — see section 5a.

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
