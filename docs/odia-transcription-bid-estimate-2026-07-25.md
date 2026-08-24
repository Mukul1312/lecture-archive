# Odia Lecture Transcription — Cost Estimate & Bid Strategy

**Client project:** transcribe the Odia lecture archive of **Haladhara Swami** (~1,700 lectures).
**Prepared:** 2026-07-25 · FX 1 USD = 96.72 INR · figures exclusive of GST.
**Status:** pre-bid. Not yet signed — the client wants a cost estimate first.

> **One-line recommendation.** Do **not** quote a fixed price on audio nobody has transcribed yet.
> Bid a **~$42k / 14-week paid pilot** (≈$28k credited back to production), which *measures* the one
> number that drives 40–70% of the cost. Offer **Tier 1 (machine archive) at ~$215k** as the only thing
> safe to sign fixed-price today. Offer Tiers 2–3 as formulas with a written numeric renegotiation collar.

---

## 1. What is actually being bid — the corpus, measured

The client said "1700 lectures, 1–2.5 hr each." That count is roughly right, but "1–2.5 hr" and the
implied hour-count are the single biggest cost lever, so I **measured the archive** rather than trusting
the estimate. Haladhara Swami's lectures are public on ISKCON Desire Tree (`audio.iskcondesiretree.com`),
the same host the prior Hindi/GGSM project used. Full enumeration + `ffprobe`:

| Branch | Files | Audio-hours | Mean/lecture | Basis |
|---|---:|---:|---:|---|
| **Oriya_Lectures** | **1,357** | **1,952** | 86 min | exact (64 kbps CBR, 27/27 sampled confirm) |
| Hindi_Lectures | 242 | ~377 | 94 min | exact (64 kbps CBR) |
| English_Lectures | 260 | ~327 | 75 min | approx (mixed bitrate) |
| Bahasa_Translation | 78 | ~136 | 105 min | approx |
| Bhajans (sung — exclude) | 80 | ~35 | 26 min | approx |
| **Total archive** | **2,020** | **~2,831** | | |

**"1700 lectures" is almost certainly Oriya + Hindi (1,599 files, ~2,330 h)** — the closest match. Odia
alone is 1,357 files / **1,952 audio-hours**.

**This overturns the workflow's planning midpoint.** The cost research below priced everything at a
*guessed* 2,975 hours. The measured Oriya corpus is **1,952 h — the workflow's "low" scenario, not its
middle.** Every headline number here has been re-based onto the measured hours. (Note: this also corrects
an earlier proxy I gave you — I'd used GGSM's shorter lectures and wrongly implied the client *over*stated
duration. Haladhara Swami's lectures are ~2× longer; the client's per-lecture estimate was accurate.)

**Audio quality — measured, and better than feared.** Spectral analysis of a stratified sample shows
median speech energy to ~5.8 kHz (−30 dB), most lectures wideband, only a small minority genuinely
narrowband. This is **not** telephone-band cassette. It de-risks the biggest WER driver and makes
published Odia benchmarks more transferable than a 4 kHz master would. *(A 320-file census refining the
exact degraded-file share is running; this section updates when it lands.)*

---

## 2. Why this is expensive, and where the money goes

Compute is a rounding error. **GPU + API + LLM for the entire 1,952-hour corpus is ~$6k — about 1% of
the bid.** The cost is almost entirely **human hours**, and a large fixed block of **building an Odia
transcription capability that does not currently exist**.

The dominant driver is **M = human work-hours per audio-hour** to bring machine output to publishable
quality. Nobody has ever measured it for Odia audio of this kind. The credible published range is **5.5
to 36 — a 6.5× spread.** Three independent cost models guessed 5.5 / 7.0 / 11.5; three independent
red-team reviews all judged those too low and converged on **11–15**. This estimate adopts **11.5** and
flags it as the number the pilot must measure.

Two structural facts to say out loud to the client:

- **The fixed engineering + management block (~$169k) is larger than the entire human transcription bill
  for a 25%-verified subset.** A solo vendor building a first-of-kind Odia pipeline carries unusually
  heavy fixed cost. It only amortises well above ~1,700 verified hours — an argument *for* including the
  whole corpus, not a curated slice.
- **The marginal cost of a verified audio-hour is ~$100 of labour; the fixed cost of being *able* to
  produce any verified Odia hour is $130k–$200k** — recruiting, screening, training and QA-ing a bench
  that the market does not supply. (AI4Bharat's flagship Bhashini programme has transcribed **75 hours of
  Odia total**. GoTranscript *sells* Odia at a 2× premium but doesn't even recruit for it.)

---

## 3. The three tiers — re-based on the measured 1,952 Oriya hours

| | **Tier 1 — Machine Archive** | **Tier 2 — Machine + Verified Subset** *(recommended)* | **Tier 3 — Full Human-Verified** |
|---|---|---|---|
| **Coverage** | All 1,357 lectures, no per-lecture human pass | All machine-processed + 25% of duration (~488 h) fully human-verified | All 1,357 fully human-verified |
| **Deliverable** | Multi-engine Odia-script transcript (IndicConformer + Azure `or-IN` + Sarvam, LLM-reconciled), timestamps, confidence + "Sanskrit-verse suspected" flags, chant spans tagged & untranscribed, full-text search index | Tier 1 + verbatim punctuated transcript on the subset, code-switch tags, Sanskrit verse cited to source, 2 human passes + Sanskrit-literate proof, published inter-annotator agreement | Tier 2 spec applied to the whole corpus + verse concordance + term authority file |
| **Accuracy** | **Not warranted as text** (expect 25–45% WER). Warranted on *findability*: keyword/entity recall + chant/verse boundary recall | ≤10% normalised WER on the subset; Tier-1 level on the rest | ≤8% normalised WER corpus-wide |
| **Total (measured 1,952 h)** | **~$215k** / ₹2.08 cr | **~$510k** / ₹4.93 cr | **~$940k** / ₹9.1 cr |
| **Per audio-hour** | **~$110** / ₹10,600 | **~$260** / ₹25,100 | **~$481** / ₹46,500 |
| **Timeline** | 11–14 mo | 18–24 mo | 28–36 mo |
| **Peak headcount** | ~2 FTE | ~13 | ~24 (**not realistically recruitable in Odia — subcontract**) |

*If scope is Oriya + Hindi (2,330 h): Tier 1 ~$217k, Tier 2 ~$530k, Tier 3 ~$1.04M. Hindi should be a
separate line item — Hindi ASR is far more accurate than Odia and needs much less correction.*

**Tier 2 dialable formula:** `~$215k (machine, all lectures) + ~$195k (workforce standing cost) + $200 ×
verified-audio-hours`. Client picks the verified fraction; 25% is the default.

> **Confidence note.** Tier 1 is robust — it's machine + fixed cost with minimal human labour. Tier 2/3
> totals rest on the **unmeasured** M = 11.5. If the pilot measures M at 15, Tier 2 rises ~$80k; at the
> Bambara-analogue tail (30+), the post-edit model breaks entirely. This is exactly why the pilot exists.

---

## 4. The pilot — buy the missing measurement before quoting

**~$42,000, 14 weeks, two gates. ~$28k of it (engineering + tooling) is reusable in production, so offer
it credited back — net cost of the option ≈ $14k.**

- **Gate 0a (3 wk, ~$13k):** full archive inventory + `ffprobe` histogram; 100-file condition audit
  (SNR, bandwidth, chant %, verse %, multi-speaker %); **multi-engine ASR bake-off on 20 real audio-hours**
  (IndicConformer, Sarvam `od-IN`, Azure `or-IN`, ElevenLabs Scribe `ori`) incl. cross-engine error
  correlation; enhancement A/B. Withdrawal right for either party.
- **Gate 0b (11 wk, ~$29k):** finish Odia pipeline + Odia-script review tool with **per-clip timed logging**;
  orthography/style annex + glossary; recruit & train 4 pilot transcribers; 10-hour three-way adjudicated
  gold set; deliver 20 lectures (~35 h) at full Tier-2 spec; re-baseline the production tariff.

**What the pilot returns:** measured **M** (effort ratio), **WER per condition tier**, **chant %**, **true
corpus hours**, **verse density**, **keyword-recall** (the real Tier-1 acceptance metric), and whether
buying a 2nd/3rd ASR draft actually recovers errors.

**The renegotiation collar — put these exact numbers in the contract:**

| Measured M (effort ratio) | Consequence |
|---|---|
| ≤ 8 | tariff rebases **down** (client benefit) |
| 8 – 13 | **tariff stands** — this is the collar |
| 13 – 18 | rebases **up**; either party may terminate within 15 business days |
| > 18 | Tiers 2–3 auto-withdrawn, only Tier 1 remains (vendor walk-away right) |

Secondary trigger on WER: stands 20–45%; above 45% the post-edit framing is dead and labour re-prices at
from-scratch rates. Tertiary: chant fraction, corpus duration, and "masters not digital" each re-open the
relevant scope line.

---

## 5. What the vendor must NOT agree to (top items)

1. **A fixed price on unheard audio.** Fixed-price the *pilot only*; price production off measured M in writing.
2. **A collar with no numbers.** Use the exact bands above, including the walk-away above M = 18.
3. **A billing denominator of "transcribed" or "non-chant" duration.** Bill on **source duration as delivered**; chant is out of scope *and* out of the WER denominator, but must stay *in* the billing denominator or a 20% chant fraction silently deletes revenue.
4. **A single blended rate across audio-condition tiers.** Stratify at intake; price each tier; rebase if the mix moves >10 pts from pilot.
5. **WER acceptance without a signed Odia normalisation annex.** ~32% of raw Odia "errors" are Unicode/encoding scoring artifacts (precomposed vs decomposed vowels, ZWJ/ZWNJ, `wa/va`). Without the annex, both sides compute different numbers from identical files. **If the client refuses the annex, withdraw — don't discount.**
6. **Tier 1 accepted against WER.** Tier 1 sells findability; insist on **keyword/entity recall + MRR** on a client-agreed query set. (Proper nouns like "Jagannath" and verse citations fail far above the corpus-average WER — exactly what a researcher searches for.)
7. **Any Sanskrit verse citation deliverable before a Sanskrit-literate Odia editor is contracted.** That's scholarship, not transcription, and the hardest hire. Also **hard-gate verse spans out of the LLM correction pass** — an LLM will "fix" a teacher's deliberate variant into the canonical form: fluent, plausible, doctrinally wrong.
8. **Unlimited revisions** (cap 2 on verified / 1 on machine, deemed-acceptance clock), **English translation as an "option"** (it's a 3–8× second contract), **liability beyond fees for the affected batch**, **USD fixed price over 2–3 years with no FX mechanism** (quote INR or a ±3% collar), and **volunteer labour on the critical path** (a comparable devotee project delivered ~18% of plan).

---

## 6. What I still need from the client (blocking)

1. **Are the masters already digital?** Written confirmation + 5 `ffprobe`-verified sample files. If they're
   cassette, add **$60k–$149k and 12–18 months** for digitisation (serial, can't be parallelised). *The
   public files are usable digital MP3 — but confirm whether the client wants those or has originals.*
2. **Exact scope:** Oriya only (1,357 / 1,952 h) or Oriya + Hindi (1,599 / 2,330 h)? Hindi priced separately.
3. **Deliverable & accuracy standard:** searchable draft, verbatim-verified, or subtitled? (5–10× cost spread.)
4. **Output language:** Odia-script transcript, or translation to English? (Different job — translation is a second contract.)
5. **Sanskrit orthography:** Odia script / Devanagari / IAST? Locks the transcriber skill profile and rate.
6. **Chant/kirtan in scope?** If yes, separately scoped & priced with its own acceptance criteria.
7. **Paying entity Indian or foreign?** (GST/TDS vs export-zero-rated.) **Rights holder?** (chain-of-rights warranty.) **Deadline?** (>Tier-1 schedules are recruiting-bound, not money-bound.) **Would they accept a subcontracted Odisha BPO for the human layer?** — possibly the single biggest cost/risk lever.

---

## 7. Key sourced facts (safe to cite)

| Fact | Value | Source |
|---|---|---|
| Whisper cannot transcribe Odia | `or`/`ory` absent from language set; 125.6% WER on real Odia | openai/whisper tokenizer.py · arXiv 2602.03868 |
| Best open Odia ASR (clean benchmark) | IndicConformer **20.6% WER / 12.1% OIWER** | arXiv 2603.00941 |
| Best on *degraded field* Odia | Azure 35.1%, Sarvam 35.8% (Whisper 125.6%) | arXiv 2602.03868 |
| MMS-1B-all licence | **CC-BY-NC — commercially unusable** | huggingface.co/facebook/mms-1b-all |
| ASR post-editing crossover | **~30% WER** — above it, correcting is slower than typing fresh | Gaur et al., W4A 2016 |
| Vendor effort ratios | 5–6+ poor audio; **8–12 non-professionals** | Ditto, GMR transcription |
| Closest methodological analogue (Bambara, low-resource oral) | **30 work-h/audio-h lab, 36 field** | arXiv 2510.12781 |
| Indian agency Odia list price | **₹95/audio-min ≈ $59/audio-hour** | IndiaMART (Parikh Info Solutions) |
| Odia scarcity premium | **$2.13 vs $1.02 /audio-min** (same vendor) | GoTranscript |
| Whisper non-speech hallucination | 40% of clips hallucinate; music explicitly excluded from best-case studies | arXiv 2501.11378 |

*Full 126-claim fact base, 3 cost models, and 3 red-team reviews retained in the workflow output
(`scratchpad/factbase.md`, `models.json`, `redteam.json`).*

---

### Bottom line

The corpus is **measured (1,952 Oriya h / 2,330 with Hindi)**, the audio is **better quality than feared**,
and the compute is **trivial**. The whole risk lives in one unmeasured number — the human effort ratio —
whose honest range spans 6.5×. **Sell the client a pilot that measures it. Sign nothing fixed-price on the
full corpus until you have.**
