# Hindi ASR model research — picking the transcriber for GGSM's Hindi lectures

**Date:** 2026-07-03 · **Method:** Firecrawl deep-research (4 parallel sourced agents) + primary papers/leaderboards.
**Question:** Which open ASR gives the highest-quality Devanagari transcripts on GGSM's audio —
*spontaneous* Hindi by a **native-Odia speaker** (heavy accent), **~56 kbps**, **noisy** (room + audience),
with **English + Sanskrit code-switch**? These transcripts train a VoxCPM2 LoRA, so text accuracy matters
for text↔audio alignment.

Companion to [noisy-source-dataprep-research.md](noisy-source-dataprep-research.md),
[hindi-clone-plan.md](hindi-clone-plan.md).

---

## TL;DR / decision

1. **Benchmark WER does not answer our question.** Every published number is on *native-Hindi, mostly-read*
   test sets. Our audio (Odia accent + noise + code-switch + spontaneous) is out-of-distribution for **all**
   of them. Both AI4Bharat's own preprint and the vasista22 model card literally say *"run a pilot on your
   own clips."* So the deciding evidence is an **empirical A/B on GGSM's actual clips**, not a table.
2. **Our current model (vasista22) is likely NOT the best fit.** It is trained ~95% on *read* speech and has a
   **documented repetition-loop failure on a spontaneous lecture** — our exact scenario.
3. **Two better-suited Whisper-large-v3 fine-tunes surfaced**, both usable via the same HF pipeline
   (one-flag swap in `extract_hindi_v2.py`):
   - **ARTPARK-IISc/whisper-large-v3-vaani-hindi** — best measured *noisy* Hindi; trained on the **Vaani**
     corpus that deliberately covers **eastern-India accents (near Odisha)** → most relevant to his accent.
   - **Trelis/whisper-hinglish-preview** — purpose-built for **accented code-switched** Hindi (English/Sanskrit
     mixing), with a dedicated `<|mixedcode|>` token.
4. **IndicConformer-600M** is trained on the *right distribution* (spontaneous noisy field audio) and **never
   hallucinates** (CTC/RNNT), but **fails catastrophically on out-of-region accents** in the one relevant study
   and **drops/garbles embedded English**. Best used as a **no-hallucination cross-check**, not the primary.

**Plan:** run all four on the identical VAD-cut clips and pick by *his* voice. Prior expectation after research:
**Vaani-Hindi** is the leading single bet for mostly-Hindi accented/noisy audio; **Trelis** if code-switch is
heavy; **IndicConformer** as the disagreement detector; **vasista22** as the baseline we already have.

---

## The candidates

| Model | Type / params | Loads via | Gated | Best-for | Biggest risk |
|---|---|---|---|---|---|
| **vasista22/whisper-hindi-large-v2** *(current)* | Whisper-large-v2 FT, 1.5B | HF `pipeline` | No (Apache-2.0) | clean read Hindi | **hallucination/repetition on spontaneous+noise**; ~95% read-trained |
| **ai4bharat/indic-conformer-600m-multilingual** | Conformer hybrid CTC+RNNT, 600M | `AutoModel` `trust_remote_code` + onnxruntime pins | Yes (MIT) *(access granted)* | spontaneous noisy field Hindi; never hallucinates | **out-of-region accent collapse (55–65% WER)**; drops English; no punctuation |
| **ARTPARK-IISc/whisper-large-v3-vaani-hindi** | Whisper-large-v3 FT, 1.5B | HF `pipeline` | No | **noisy + accent-diverse Hindi** | weaker code-switch (Devanagari-focused); self-reported numbers |
| **Trelis/whisper-hinglish-preview** | Whisper-large-v3 FT (from Vaani), 1.5B | HF `pipeline` | No (research preview) | **accented Hindi↔English↔Sanskrit code-switch** | preview status; self-reported internal benchmarks |

---

## Benchmark numbers (with the caveat that they're the wrong distribution)

### Vistaar leaderboard — the only apples-to-apples Hindi table (same test sets)
Source: [AI4Bharat/vistaar README](https://github.com/AI4Bharat/vistaar), paper [arXiv 2305.15386](https://arxiv.org/abs/2305.15386).
Hindi WER %, lower better. "IndicWhisper" = Whisper-medium Hindi FT (vasista22's sibling lineage); "Nvidia-large" =
NVIDIA `stt_hi_conformer_ctc_large` (a *read-trained* Conformer, **not** the 600M IndicConformer).

| Hindi test set | Character | IndicWhisper (seq2seq) | Nvidia-large (Conformer-CTC) | IndicWav2Vec (CTC) |
|---|---|---|---|---|
| Kathbath | read, clean | **10.3** | 12.7 | 12.2 |
| Kathbath-Hard | read + noise | **12.0** | 14.2 | 16.2 |
| FLEURS | read | **11.4** | 15.7 | 18.3 |
| CommonVoice | read | **15.0** | 21.2 | 20.2 |
| IndicTTS | studio read | **7.6** | 12.2 | 15.0 |
| MUCS | storybook read | 12.0 | **11.8** | 22.9 |
| **Gramvaani** | **spontaneous, telephone, dialectal** | **26.8** | 42.6 | 42.1 |
| **Average** | | **13.6** | 18.6 | 21.0 |

**Reading:** Whisper-Hindi beats the Conformers on 6/7 sets and **wins hugest on the one noisy/spontaneous set
(Gramvaani 26.8 vs ~42)** — the closest proxy to our audio. BUT the Conformer here is the old read-trained NVIDIA
one, **not** IndicConformer-600M (which is IndicVoices-trained and would close some of that gap). No table pits
vasista22 vs indic-conformer-600m directly — a genuine gap only our A/B can fill.

### Per-model self-reported / other
- **vasista22-large-v2:** FLEURS **6.80**, CommonVoice-11 **10.98** (self-reported; FLEURS was in training → optimistic).
  No noisy/spontaneous numbers published. [card](https://huggingface.co/vasista22/whisper-hindi-large-v2)
- **IndicConformer-600M:** Voice-of-India (real telephonic noisy) Hindi **OIWER 8.2** — best *open-source*, "Tier I"
  (vs Sarvam 5.0, Gemini-3-Pro 6.0). Vaani-Bench **13.2**. IndicVoices **15.0** (that number is the 130M predecessor).
  *OIWER is a lenient metric; strict WER on our audio will be higher.* [arXiv 2604.19151](https://arxiv.org/html/2604.19151v2), [card](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual)
- **Whisper-Vaani-Hindi:** **Gramvaani 25.11**, Kathbath-Noisy **11.80**, FLEURS 11.20, CommonVoice 13.84, RESPIN 7.36
  (self-reported). Best *noisy* Hindi of the open models surveyed. [card](https://huggingface.co/ARTPARK-IISc/whisper-large-v3-vaani-hindi)
- **Trelis-Hinglish:** hiacc-adult (accented code-switch) **12.73**, hiacc-child 10.69, CoSHE-500 (conversational CS)
  13.67, FLEURS 12.57, CommonVoice 12.86 (self-reported preview). Only open model benchmarked on *accented CS*. [card](https://huggingface.co/Trelis/whisper-hinglish-preview)

---

## The two decisive risks for OUR audio

### Risk A — Whisper hallucination on noise/silence (seq2seq)
- Large-scale study (AGH Kraków, ICASSP 2025, 301k non-speech files): base Whisper large-v3 **hallucinated 40.3%**
  of the time on non-speech; **9.1% were repetition loops**; worst at short (1s: 52%) and long (30s: 62%) gaps.
  [arXiv 2501.11378](https://arxiv.org/html/2501.11378v1). "Careless Whisper" (FAccT 2024): hallucinations
  concentrate on **longer pauses**. [ACM](https://dl.acm.org/doi/fullHtml/10.1145/3630106.3658996)
- **Directly on our model:** vasista22 discussion #8 — a user's **30-sec spontaneous physics lecture** produced a
  loop: *"बता बता बता … interference interference ये देख interference …"*.
  [#8](https://huggingface.co/vasista22/whisper-hindi-large-v2/discussions/8)
- **Why our pipeline already mitigates most of this:** we transcribe **per VAD-cut clip** (8–18 s, speech-gated),
  each an independent `pipe()` call. That removes the two biggest triggers — decoding over silence, and
  cross-segment `condition_on_previous_text` loop propagation. The #8 failure was a raw 30-s chunk, *not* a
  VAD-gated clip. Still worth adding `no_speech`/logprob thresholds as belt-and-suspenders.

### Risk B — Conformer accent collapse + English drop (CTC/RNNT)
- Voice-of-India preprint: Tier-I models incl. **IndicConformer "fail catastrophically for out-of-region migrants
  (Chhattisgarhi speakers in Tamil Nadu → 55–65% WER)."** GGSM is a **native Odia** speaker doing Hindi = exactly
  this out-of-distribution accent. [arXiv 2604.19151](https://arxiv.org/html/2604.19151v2)
- Conformer is **Devanagari-only** → embedded English ("consciousness", proper nouns) gets **transliterated or
  dropped**; **no punctuation/casing**. Upside: it **never hallucinates** — it fails by *deleting* words (silent
  gaps you can see), which is a *safer* failure mode than Whisper's confident fiction. Sanskrit (Devanagari) is the
  one place it could be competitive.

---

## Code-switch (English + Sanskrit)
- Base multilingual Whisper knows English/Latin natively → best raw code-switch capability, but weak Hindi acoustics.
- A **Hindi-only fine-tune** (vasista22, Vaani-Hindi) forces Hindi decoding; English *sometimes* survives in Latin,
  *sometimes* transliterates/drops — **inconsistent** (vasista22 #3/#8). Fine-tuning on Hindi likely *narrows* base
  Whisper's code-switch ability (inferred, not measured).
- **Trelis-Hinglish** explicitly adds a `<|mixedcode|>` token for Devanagari+Latin mixing → the only open model
  *designed* for this. Best bet if his English/Sanskrit mixing is frequent.
- Oracle Interspeech-2025 code-mix study: even base large-v2 "excels on mono-lingual but struggles with code-mixed,
  often **deleting** at the switch point." [ISCA](https://www.isca-archive.org/interspeech_2025/biswas25_interspeech.pdf)

---

## Also-rans (why they're out)
- **Base Whisper large-v3 / turbo** — poor raw Hindi (FLEURS ~27) + high hallucination; use a *fine-tune* of it.
- **AI4Bharat IndicWav2Vec / NVIDIA read-Conformers** — collapse on noise (Gramvaani ~42); Devanagari-only.
- **NVIDIA Canary-1b-v2 / Parakeet-v3** — **no Hindi** (Granary = 25 European langs). Indic Parakeet = NGC-gated.
- **Sarvam Saaras/Saarika** — strongest marketed (noise+accent+code-mix) but **paid, closed API** → disqualified
  (non-commercial seva, open-only).
- **Meta MMS / SeamlessM4T** — general multilingual, lose to Indic-specific FTs; normalizer distorts Indic WER.

---

## Recommendation → empirical A/B on his clips
Because no benchmark covers Odia-accented spontaneous code-switched Hindi, **transcribe the identical VAD-cut clips
with 4 models and diff**:

| # | Model | Flag | Hypothesis |
|---|---|---|---|
| 1 | vasista22-large-v2 | `--whisper-model vasista22/whisper-hindi-large-v2` | baseline (already have) |
| 2 | Whisper-Vaani-Hindi | `--whisper-model ARTPARK-IISc/whisper-large-v3-vaani-hindi` | **best accent+noise fit** |
| 3 | Trelis-Hinglish | `--whisper-model Trelis/whisper-hinglish-preview` | **best code-switch** |
| 4 | IndicConformer-600M RNNT | `--asr indicconformer` | no-hallucination cross-check / disagreement flag |

Decide by: (a) fewest hallucinations/loops, (b) English/Sanskrit rendered right, (c) fewest Devanagari matra errors,
(d) his devotional vocabulary correct. Where Whisper-model and IndicConformer **disagree sharply**, that clip needs
human review (Whisper's fabrications and Conformer's deletions both show up as large divergences).

**Decode hardening for the Whisper models** (all seq2seq): `condition_on_previous_text=False` (structural — we're
already per-clip), plus `no_speech_threshold`/`logprob_threshold`/`compression_ratio_threshold` to suppress
loops, and a small hallucination blocklist ("thank you", "amara.org", etc.).

---

## Sources (primary first)
- Vistaar leaderboard + paper: https://github.com/AI4Bharat/vistaar · https://arxiv.org/abs/2305.15386
- IndicVoices (IndicConformer training data): https://arxiv.org/abs/2403.01926
- Voice-of-India (IndicConformer real-world + accent collapse): https://arxiv.org/html/2604.19151v2
- Whisper hallucination (AGH ICASSP-2025): https://arxiv.org/html/2501.11378v1 · Careless Whisper (FAccT-2024): https://dl.acm.org/doi/fullHtml/10.1145/3630106.3658996
- Code-mix Whisper (Interspeech-2025): https://www.isca-archive.org/interspeech_2025/biswas25_interspeech.pdf
- Model cards: vasista22 https://huggingface.co/vasista22/whisper-hindi-large-v2 · IndicConformer https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual · Vaani-Hindi https://huggingface.co/ARTPARK-IISc/whisper-large-v3-vaani-hindi · Trelis-Hinglish https://huggingface.co/Trelis/whisper-hinglish-preview
- vasista22 failure/config threads: #8 loop https://huggingface.co/vasista22/whisper-hindi-large-v2/discussions/8 · #7 matras https://huggingface.co/vasista22/whisper-hindi-large-v2/discussions/7 · generation_config https://huggingface.co/vasista22/whisper-hindi-large-v2/raw/main/generation_config.json

### Rerun inputs
workflow: firecrawl-deep-research · depth: thorough (4 parallel agents, ~25 sources) · output: markdown
