# Odia → Odia + English: System Design and Cost Model

**Date:** 2026-08-28 · **Corpus:** 1,357 files / **1,952 audio-hours** (ffprobe'd, `odia-transcription-bid-estimate-2026-07-25.md`)
**FX:** ₹95.5/USD · **Status:** design proposal. Nothing switched. One lecture has been run end to end, on Sarvam.

> **Evidence currency:** Provider capabilities and prices are snapshots retrieved on the dates in
> §7, not current operational guarantees. Recheck official sources before implementation or spend;
> the later correction document records the measured changes to this proposal.

**Supersedes nothing.** Extends `aws-evaluation/evidence/api-tier-pricing-2026-08-27.md` with the
translation leg, an engine capability comparison that pricing alone missed, and a reference-free
QA design for the "we cannot audit 1,952 hours" problem.

> ⚠️ **THREE CLAIMS BELOW ARE SUPERSEDED — read
> [odia-design-measured-corrections-2026-08-28.md](odia-design-measured-corrections-2026-08-28.md)
> alongside this document.** Same day, later session, after measurement and 37 research agents:
>
> 1. **§4.1 — the second engine is ElevenLabs Scribe v2, not Sarvam.** Sarvam has no word-level
>    timestamps and no per-word confidence, and is upload-only (20 files/job). Scribe is cheaper
>    ($0.22/h), takes public URLs, and returns a required per-word `logprob`.
> 2. **§4.1 — run the second engine on 100%, not the worst 30%.** Selecting "the worst 30%" needs
>    a selector, and the only one available was Azure's own confidence — the single-engine signal
>    this design distrusts.
> 3. **§4 — the 1.59% shared-wrong floor does not transfer.** That is 8 engines on English. Two
>    engines on Odia will be materially worse. Hand-measure it.
>
> Also settled there: infrastructure is **the laptop, not AWS** (triage measured at 42 MB RAM flat
> and zero disk, streaming from URL), and two real bugs were found in `scripts/`.

---

## 0. The one thing that changed

The settled review standard (2026-08-27) was:

> Devotees read the transcript **while listening to the lecture**. The audio is always present,
> so errors self-correct. Timestamp accuracy matters more than word accuracy.

**That standard does not survive the English translation.** An English reader who does not speak
Odia has no audio to correct against. The Odia transcript is a *draft with a crutch*; the English
translation is a *standalone document*. Worse, translation is not error-neutral — an LLM given a
mistranscribed Odia word produces a fluent, confident, wrong English sentence. The error stops
being visible as garbled text and becomes invisible as plausible prose.

So the accuracy bar on the **Odia** leg rises because of the **English** goal, even though nothing
about the Odia deliverable itself changed. Everything below follows from that.

Second consequence: the two outputs need **different** quality gates. Odia can ship at draft
quality with good timestamps. English cannot.

---

## 1. Cost is not the constraint. State it plainly.

Both outputs, whole corpus, at list price:

| Scenario | Corpus total | Per audio-hour | QA signal obtained |
|---|---:|---:|---|
| **A.** Sarvam only + Claude translate *(today's shape)* | **₹74,700** ($782) | ₹38.28 | none — chunk timestamps, no confidence |
| **B.** Azure primary + Claude translate | **₹49,700** ($521) | ₹25.47 | per-word confidence + word timestamps, 100% |
| **C.** Azure + Sarvam everywhere, LLM reconciled | **₹115,500** ($1,210) | ₹59.19 | cross-engine disagreement, 100% |
| **D.** Azure 100% + Sarvam on worst 30% + Claude ✅ | **₹69,700** ($730) | ₹35.71 | confidence everywhere, disagreement where it matters |

The spread between the cheapest and the most expensive *complete* design is **₹65,800 (~$690)** on
volunteer work with no deadline. That is not a number worth optimising for its own sake.

**The right question is not "how do I spend less." It is "what does this money buy me, given that
nobody will ever check most of it?"** Scenario A and Scenario D cost within ₹5,000 of each other.
A buys two text files. D buys two text files *plus a per-file risk score*. That is the whole
argument of this document.

### 1.1 The translation leg, costed

1 audio-hour ≈ 9,000 spoken words ≈ 32,000 Odia characters.

| Route | ₹/audio-hour | Corpus |
|---|---:|---:|
| Claude Haiku 4.5, Batch API | ₹3.6 – 4.1 | ₹7,100 – 8,100 |
| **Claude Sonnet 5, Batch API** ✅ | **₹7.3 – 8.3** | **₹14,200 – 16,200** |
| Claude Opus 5, Batch API | ₹18.1 – 20.7 | ₹35,400 – 40,400 |
| Sarvam `saaras:v3 mode=translate` (2nd STT pass) | ₹30.0 | ₹58,560 |
| Sarvam Translate text API (₹2/1,000 chars) | ₹64.0 | ₹124,900 |

Claude via the **Batch API (50% discount — there is no latency requirement here)** is **4× cheaper
than a second Sarvam pass and 8× cheaper than Sarvam's text Translate API.** The earlier finding —
that Sarvam translation would cost more than Sarvam transcription — holds, and is now quantified
against the alternative rather than just against itself.

> **Unmeasured input:** Odia→Claude tokenisation. The bracket above assumes 1.2–2.0 characters per
> token. **Run `client.messages.count_tokens` on one real Odia transcript before quoting this.**
> It is a two-minute check, and it is the only guessed number in the translation line.

---

## 2. Engine choice: pricing missed the deciding fact

The 2026-08-27 pricing work ranked engines on ₹/hour. Ranking them on **what they return** changes
the answer.

| | Azure `or-IN` S1 Batch | Sarvam `od-IN` saaras:v3/v4 | ElevenLabs Scribe v2 |
|---|---|---|---|
| Price | **$0.18/h (₹17.19)** | ₹30/h ($0.314) | $0.22/h (₹21.01) |
| Odia WER (agri field benchmark) | **35.1%** (best of 10) | 35.8% | not in benchmark |
| **Word-level timestamps** | **✅ `wordLevelTimestampsEnabled`** | ❌ **explicitly unsupported** | ✅ |
| **Per-word confidence** | **✅ every word** | ❌ none | partial |
| Direct speech→English | ❌ | ✅ `mode=translate` | ❌ |
| Custom vocabulary adaptation | ✅ plain-text (unverified for `or-IN`) | ❌ | ❌ |

Sarvam's own API docs, retrieved 2026-08-28:

> `with_timestamps` — *"each entry covers a sentence or phrase, not an individual word."*
> **"Word-level timestamps are not supported."**

**This is the finding.** The settled standard says *timestamp accuracy matters more than word
accuracy* — and the engine currently in use is the one that cannot give word-level timestamps,
while the cheaper engine can. Azure is simultaneously **43% cheaper**, **word-timestamped**,
**confidence-scored**, and **first on the one published Odia benchmark**. Sarvam's one real
advantage — direct Odia-audio→English — covers the leg Claude does 4× cheaper anyway.

### 2.1 Caveats that must travel with those WER numbers

- **The 35.1% / 35.8% figures are from farmers speaking into mobile phones in fields**
  (arXiv 2602.03868v2 — 2,233 Odia recordings, 13.6% high-noise). Haladhara Swami's lectures are a
  single miked speaker in a hall, and this repo's own spectral analysis found them *"better quality
  than feared — median speech energy to ~5.8 kHz, most lectures wideband."* **Real WER on this
  corpus is unmeasured and is probably better than 35% on the clean stratum.** Do not quote 35% as
  if it described these lectures.
- **A 0.7 pp gap between Azure and Sarvam is noise**, not a quality ranking. Choose on capability
  (timestamps, confidence), not on that gap.
- **`AI4Bharat` scores 64.8% WER in that benchmark**, but the paper cites Javed et al. — that is
  IndicWav2Vec, **not** IndicConformer-600M. Self-hosting is neither validated nor refuted by it.
- **Whisper remains disqualified** — 125.6% WER, no `or` token. Unchanged.
- Azure `or-IN` is listed in the speech-to-text locale table with fast-transcription support;
  **confirm batch specifically with one real job** before committing.

### 2.2 The timing argument

**One lecture has been transcribed.** The "switching mid-corpus produces transcripts of two
different characters" risk — correctly raised on 2026-08-27 — costs essentially nothing today, and
rises with every lecture processed. **This is the cheapest moment this decision will ever have.**

---

## 3. Heterogeneity: stratify at intake, never blend

1,952 hours recorded across decades, rooms and microphones is not one dataset. A single blended
pipeline is tuned for audio that mostly does not exist, and a single average WER describes no
actual file.

**Measure every file locally before spending a rupee on it.** Cost: zero API calls, roughly 0.02×
realtime on CPU. The repo already has `spectral_inspect.py`, `analyze_source.py` and
`enhance_diagnose.py` doing most of this for the enhancement programme.

Per file, compute and store: **speech-band SNR estimate · effective bandwidth (−30 dB rolloff) ·
clipping fraction · speech/silence ratio · loudness (LUFS) and crest factor · sample-rate and
bitrate provenance**. Cluster into three tiers:

| Tier | Signature | Route |
|---|---|---|
| **1 — Clean** | wideband, high SNR, no clipping | Azure only. Ship. |
| **2 — Ordinary** | mid SNR, some room tone | Azure + confidence gate; escalate the low-confidence tail |
| **3 — Degraded** | narrowband / clipped / low SNR | Azure + Sarvam both, always reconciled; flag for human read |

Two rules that keep stratification honest:

1. **Report WER and cost per tier, never as one corpus average.** A blended average hides exactly
   the files that need attention.
2. **Do not enhance before ASR.** Settled by `odia-asr-and-intelligibility-metrics-2026-07-31.md`:
   speech enhancement degraded ASR in **40 of 40** tested configurations, including a 1.3–3.2%
   penalty on audio with *no added noise at all*. Enhancement is a separate deliverable
   (programme 2) for human listening. Feed ASR the original.

---

## 4. Reliability without auditing: two reference-free signals

You cannot compute WER without references. You *can* compute where the transcript is likely to be
wrong, and spend scarce volunteer attention there. Two independent signals, neither requiring a
reference:

**Glass-box — per-word confidence.** Azure returns a confidence score on every word. Free, on 100%
of the corpus, no second pass. Known to be imperfectly calibrated and blind to deletions — useful
as a *first* filter, not as a verdict.

**Black-box — cross-engine disagreement.** Align two independent engines' output and treat
divergence as a risk score. The strongest published evidence (Frontiers in AI, 2026-07 — medical
ASR, 8 engines, 76,736 aligned token positions):

- 72.1% of positions showed strong agreement; only 2.5% were high-risk.
- Error rate rose **monotonically** as agreement fell: 0.6% (high agreement) → 17.2% (medium) →
  **56.3%** (low).
- Flagging the ≤6-of-8 band selected **28.6% of tokens** and recovered **93.7% of human-verified
  errors**.
- **Ceiling, stated honestly: 1.59% "shared-wrong"** — errors where every engine agreed and all of
  them were wrong. Agreement is evidence of stability, *not* of correctness.

A production system on TV-platform voice traffic (GEM 2026) uses the same consensus construction
across 5 engines for exactly this reason: ground truth is unobtainable at scale.

### 4.1 The funnel

```
1,952 h
   │
   ├─ [0] Local acoustic triage ..................... ₹0        → tier 1/2/3
   │
   ├─ [1] Azure or-IN batch, 100% ................... ₹33,555   → Odia + word timestamps + confidence
   │        └─ per-word confidence  ──────────────────────────┐
   │                                                          │
   ├─ [2] Sarvam 2nd pass, worst ~30% ............... ₹17,568  │  (tier 3 + low-confidence tail)
   │        └─ token-level disagreement ─────────────────────┤
   │                                                          ▼
   ├─ [3] Claude Sonnet 5, Batch API ................ ₹18,600     reconcile Odia + translate EN
   │        └─ carries risk flags into BOTH outputs
   │
   └─ [4] Human read-through — targeted, not exhaustive
                                                     ─────────
                                          TOTAL      ₹69,700  ($730)
```

### 4.2 The gold set — the only thing that turns proxies into a number

Everything above produces *relative* risk. None of it yields a WER. **One human-corrected set of
5–10 audio-hours, stratified across the three tiers**, converts every proxy into a calibrated
estimate, and is reusable forever. It is the single highest-value use of Odia-reading volunteer
time in the whole programme — far higher than reading transcript #400.

Without it you can say "this file is riskier than that one." With it you can say "tier 1 runs at
X% WER, so tier 1 needs no review at all."

### 4.3 What to write into the tracker

The spreadsheet stays the authority. `odia_transcript_index.py` already computes `audio_sha256`
and `transcript_sha256`. Add columns it can also compute, all mechanical:

`tier` · `mean_word_confidence` · `pct_words_below_conf_threshold` · `cross_engine_cer`
(where a 2nd pass exists) · `flagged_span_count` · `verse_suspect_count` · `unicode_nfc_clean`
· `translation_flag_count`

**Sort by risk, review from the top, stop when the volunteers stop.** That is what makes an
unfinishable review queue produce value at every point along the way, rather than only at the end.

---

## 5. Two problems this design does not solve

**Sanskrit verse quotation.** ASR mangles quoted verses, and an LLM will "correct" a teacher's
deliberate variant into the canonical form — fluent, plausible, doctrinally wrong. **Hard-gate
verse spans out of the LLM reconciliation and translation passes.** Mark them; never auto-fix
them. This is editorial work and it stays open.

**Unicode normalisation.** ~32% of raw Odia "errors" are encoding artifacts (precomposed vs
decomposed vowels, ZWJ/ZWNJ, `wa`/`va`). Two engines will disagree *spuriously* unless both outputs
are NFC-normalised before alignment — this would poison the disagreement signal at its source.
**Normalise before comparing.** `odia_transcript_index.py` already flags invalid UTF-8; this
extends it.

---

## 6. Recommendation

1. **Run the calibration pilot. It costs ₹1,600 (~$17).** 20 audio-hours, stratified across the
   three tiers, through Azure + Sarvam + ElevenLabs, reconciled by Claude. It returns: a real WER
   bracket on *this* audio, per-tier cost, the disagreement/error correlation, whether the second
   engine recovers enough to justify itself, and whether Azure's Odia timestamps are actually good.
   Every number in this document that is currently bracketed becomes measured.

   > This reverses the 2026-08-27 position that a multi-engine bake-off should not be built unless
   > asked for. It has now been asked for — WER against cost is the stated question — and adding
   > the English translation is what made accuracy load-bearing.

2. **Do not switch engines before the pilot answers.** One lecture in, the switching cost is near
   zero; ₹25,000 of savings is not worth a corpus of two characters if the pilot says otherwise.

3. **Translate with Claude via the Batch API, not through Sarvam.** 4–8× cheaper, and it is the
   only route where verse spans can be gated and risk flags carried through into the output.

4. **Build the acoustic triage first**, before any engine decision. It is free, it is local, it
   reuses code already in this repo, and every later decision is made per-tier.

5. **Spend volunteer Odia hours on a 5–10 h gold set before spending them on review.** It is the
   only input that converts this entire mechanism from relative risk into an actual accuracy claim.

---

## 7. Sources

| Claim | Source | Retrieved |
|---|---|---|
| Odia ASR WER: Azure 35.1%, Sarvam 35.8%, Gemini 2.5 Pro 37.8%, AI4Bharat 64.8%, Whisper 125.6% | [arXiv 2602.03868v2](https://arxiv.org/html/2602.03868v2), Table VI | 2026-08-28 |
| Odia diarization gain −0.2% (2.2% multi-speaker) — confirms dropping it | same, Table VII | 2026-08-28 |
| Sarvam: word-level timestamps **not supported**; `saaras:v3/v4`, `mode=translate` | [docs.sarvam.ai](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe.md) | 2026-08-28 |
| Azure `or-IN` supported; `wordLevelTimestampsEnabled`; per-word confidence | [Azure language support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=stt) · [batch-transcription-create](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/batch-transcription-create) | 2026-08-28 |
| Cross-model disagreement as reference-free triage; 28.6% tokens → 93.7% of errors; 1.59% shared-wrong | [Frontiers in AI 2026](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1829902/full) | 2026-08-28 |
| Consensus-based referenceless ASR QA in production | [Evaluating ASR Quality at Scale, GEM 2026](https://aclanthology.org/2026.gem-main.35.pdf) | 2026-08-28 |
| Claude pricing (Sonnet 5 $2/$10, Haiku 4.5 $1/$5, Opus 5 $5/$25 per 1M; Batch −50%) | `claude-api` skill, cached 2026-06-24 | 2026-08-28 |
| Azure $0.18/h batch · ElevenLabs $0.22/h · Sarvam ₹30/h | `aws-evaluation/evidence/api-tier-pricing-2026-08-27.md` | 2026-08-27 |
| Enhancement degrades ASR in 40/40 configurations | `odia-asr-and-intelligibility-metrics-2026-07-31.md` | 2026-07-31 |
| Corpus 1,357 files / 1,952 h; audio better than feared | `odia-transcription-bid-estimate-2026-07-25.md` | 2026-07-25 |
