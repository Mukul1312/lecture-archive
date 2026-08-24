# Deep Research: clean-Hindi extraction pipeline for GGSM's lectures

**Date:** 2026-07-03 · **Method:** firecrawl deep-research, 4 parallel sourced agents (accent-robust LID · singing/kirtana detection · code-switch & TTS-data · TTS-data pipelines/contrarian).
**Question:** how to extract CLEAN accented-Hindi speech (for VoxCPM2 voice-clone training) from GGSM's noisy religious lectures — where he's a native-Odia speaker lecturing *in Hindi* (heavy Odia accent), heavily code-switched with English, and Bengali/Odia appears **only in sung kirtana/bhajan** (spoken Odia is rare).

Companion to [hindi-asr-model-research.md](hindi-asr-model-research.md), [noisy-source-dataprep-research.md](noisy-source-dataprep-research.md), [hindi-clone-plan.md](hindi-clone-plan.md).

---

## Executive summary

All four angles converge on one conclusion: **do NOT try to build a precise Hindi-vs-Odia language classifier.** Two independent reasons:
1. **It's unreliable on his voice.** MMS-LID's 97% is clean *read* speech; on accented conversational Hindi, spoken-LID drops to the **~50–70%** regime, and accented speech "degrades LID dramatically." A hard LID would wrongly reject his accented Hindi.
2. **It's unnecessary.** The user's domain knowledge (confirmed as the sensible reading): spoken Odia is *rare* — the real non-Hindi contaminants are **(a) sung kirtana and (b) pure-English stretches**, not Odia monologue.

So the right strategy is the one the user intuited, and it matches the canonical open TTS-data pipelines (Emilia-Pipe, AI4Bharat IndicVoices-R): **strip the sung kirtana with a language-agnostic music/singing detector, keep everything else as candidate Hindi (recall-biased), and let the human transcript-review pass remove the rare Odia/pure-English leftovers.** ~85–150 min is 2–3× the practical fine-tune floor — enough; cleanliness matters more than quantity.

---

## Key findings (sourced)

### A. Language-ID on his accented Hindi is the wrong hammer
1. **MMS-LID `mms-lid-256` = 97.4% on FLEURS — but that's clean READ speech**; no confusion matrix, no accented eval. On close Indo-Aryan out-of-domain, spoken-LID accuracy is **~47–72%** (Central IA is hardest; Hindi↔Urdu the top confuser). [MMS paper arXiv:2305.13516](https://ar5iv.labs.arxiv.org/abs/2305.13516) · [Indic-LID study arXiv:2606.09317](https://arxiv.org/html/2606.09317v1)
2. **Odia is *Eastern* Indo-Aryan — better-separated** than the Central cluster; no study reports Hindi↔Odia confusion. The risk is purely the *accent* axis, and "accented speech degrades LID dramatically." [arXiv:2203.16972](https://arxiv.org/abs/2203.16972)
3. **If speech-level Hindi/Odia is ever needed, the accent-robust way is NOT a dedicated LID:** either (a) **ASR force-decode** — decode a segment as Hindi vs Odia with a bilingual ASR (IndicConformer does both) and compare confidence — **35–63% fewer errors on accented speech**; or (b) a **tiny 2-class head trained on *his own* labeled clips** (frozen MMS/Vaani-FastConformer embedding + margin loss + calibrated, asymmetric threshold). [arXiv:2203.16972](https://arxiv.org/abs/2203.16972) · [arXiv:2606.09317](https://arxiv.org/html/2606.09317v1)

### B. Kirtana → cut it with music/singing detection (language-agnostic)
4. **inaSpeechSegmenter is the primary cutter** — CNN speech/music/noise segmenter; its docs state **"singing voice is tagged as music."** So sung kirtana is dropped as *music* regardless of language. One pass over a full lecture, timestamped output. Won MIREX-2018 speech detection; ranked #1 vs 6 VAD systems (Pyannote/Silero/SpeechBrain/rVAD/LIUM). [GitHub](https://github.com/ina-foss/inaSpeechSegmenter) · [LREC-COLING 2024](https://aclanthology.org/2024.lrec-main.785/)
5. **AudioSet taggers (PANNs CNN14 / YAMNet) as cross-check** — AudioSet has explicit `Chant`, `Mantra`, `Choir`, `Singing` classes; `Chant` is *defined* as "rhythmic speaking/singing on one or two reciting tones" (child: `Mantra`) — a textbook description of kirtana. Frame-level scores confirm/relocate music↔speech transitions. [PANNs](https://github.com/qiuqiangkong/panns_inference) · [AudioSet ontology](https://github.com/audioset/ontology)
6. **Honest limit:** *group* kirtana (choir + harmonium + mridanga + clapping) is the easy case; *solo* mantra recitation sits acoustically near speech — "SAD systems often misclassify singing as speech." No off-the-shelf "kirtan detector" exists and no accuracy is published on noisy Indian devotional audio → **calibrate on a 10–20 min hand-labeled slice of his own recordings.** [SVD survey PMC8775013](https://pmc.ncbi.nlm.nih.gov/articles/PMC8775013/)
7. **pyannote has no music class** (would keep singing as speech); **Silero-VAD** fires on singing too — use Silero only to *tighten* kept-speech edges (30 ms resolution), not to cut kirtana. [pyannote card](https://huggingface.co/pyannote/segmentation-3.0) · [silero-vad](https://github.com/snakers4/silero-vad)

### C. Code-switch & data volume
8. **Keep Hindi-matrix clips with *embedded* English; drop long *pure*-English stretches.** Code-switched clips *help* the clone say his real embedded-English terms naturally and don't threaten speaker identity (timbre is language-agnostic). The only risk is *proportion* — if English dominates, Hindi prosody is under-taught. [Thomas et al. Interspeech 2018](https://www.isca-archive.org/interspeech_2018/thomas18_interspeech.html) · [voice-cloning survey arXiv:2505.00579](https://arxiv.org/html/2505.00579v1)
9. **~85–150 min is enough** — 2–3× the XTTS fine-tune floor (min 3 min, 5+ recommended). The binding constraint is **cleanliness, not quantity**: LoRA single-speaker fine-tuning "faithfully encodes both desirable and undesirable aspects" — clean refs gained +0.42 DNSMOS, low-quality refs *degraded* −0.27 to −0.41 MOS even as loss fell. So **clean/enhance first.** [LoRA-TTS arXiv:2603.10904](https://arxiv.org/html/2603.10904v1) · [XTTS thesis](https://campus-fryslan.studenttheses.ub.rug.nl/708/1/MAs5965055QYZhu.pdf)
10. **De-facto clip spec:** 3–15 s, one speaker per clip, audibly clean (DNSMOS ≳ 3.0), language-consistent. [Emilia](https://arxiv.org/html/2407.05361v1) · [LJSpeech](https://keithito.com/LJ-Speech-Dataset) · [Rasa](https://huggingface.co/datasets/ai4bharat/Rasa)

### D. Pipeline template & the contrarian core
11. **Canonical order (Emilia-Pipe):** standardize → source-separate (UVR/HTDemucs) → diarize (pyannote-3.1) → VAD (Silero) → ASR → filter. Filtering uses the ASR's **own language posterior** as a *soft* whitelist (confidence ≥ 0.80), not a separate LID. Kept ~29% of raw. [Emilia arXiv:2407.05361](https://arxiv.org/html/2407.05361v3)
12. **AI4Bharat IndicVoices-R** (includes Odia) restores ASR-grade field audio to TTS-grade with **demix (HTDemucs) → dereverb (VoiceFixer) → enhance (DeepFilterNet3) → filter**; English-trained enhancers generalize to Indian languages. But its pitch/rate filters would cut impassioned devotional delivery — **loosen them.** [arXiv:2409.05356](https://arxiv.org/html/2409.05356v2)
13. **Don't hard-filter on ASR language-confidence** — code-switched Hindi scores *low* on a Hindi ASR, so that would drop the exact clips we want. And **don't gate on pitch/speed** — that cuts his expressive delivery (the identity we're cloning). [Hinglish corpus arXiv:1810.00662](https://ar5iv.labs.arxiv.org/html/1810.00662) · [naturalness-vs-style arXiv:2606.31729](https://arxiv.org/html/2606.31729v1)

---

## Recommended pipeline (ordered)

1. **Standardize** — mono 16 kHz (+ a 32 kHz copy for PANNs); loudness-normalize.
2. **GGS-only** — reuse the existing pyannote-3.1 + ECAPA diarization (removes audience/questioner). *(Already have GGS intervals from the triage.)*
3. **Strip kirtana** — **inaSpeechSegmenter** (drop `music`/`noise`, keep `speech`), cross-checked with **PANNs/YAMNet** `Chant`/`Mantra`/`Choir`/`Singing` scores over the kept regions. Language-agnostic → removes the sung Bengali/Odia without any Hindi/Odia LID.
4. **VAD cut (fixed cutter)** — Silero-VAD → clean 3–15 s clips at real pauses (the `clips_from_speech` bug is fixed: no gap-bridging across the removed regions).
5. **Transcribe** with the A/B winners — **IndicConformer + Vaani + Trelis** (3 drafts/clip); keep ASR internals (`avg_logprob`, `no_speech_prob`, `compression_ratio`).
6. **Recall-biased soft filter** — drop only clear failures (repetition via `compression_ratio` > ~2.4, empties, phone-duration outliers). **Keep** accented Hindi + embedded English. *Flag* (don't drop) low-confidence for review.
7. **Human transcript-review** (the ⭐/✓/edit builder) — the FINAL language + quality gate: reviewer drops the rare Odia / pure-English / kirtana-leftover / noisy clips and fixes transcripts. This is where "we don't need precise LID" pays off.
8. **(Optional, A/B) gentle enhancement** — DeepFilterNet3, but test raw-vs-enhanced clone (enhancement can smear accent formants; LoRA copies noise, so a *light* denoise may still help).

## Validation plan
- **Empirically test "Odia is rare":** run **MMS-LID-256** (it *can* label `ory`) over GGS's speech → measure the actual `ory` %. Confirms/refutes the whole premise before we commit.
- **Hand-label a ~50–100 clip dev set** of his own audio (accented-Hindi / code-switched / pure-English / Odia / kirtana / noise). Measure: kirtana-detection precision/recall, and **recall on code-switched accented Hindi** (must stay high — the key failure mode).
- **Retention sanity:** compare kept minutes vs the old 488/173 min; *listen* to what's dropped — if impassioned passages are being cut, loosen.
- **Downstream A/B:** clone on the filtered set; score **ECAPA speaker-similarity** to a held-out reference + accent-fidelity listening.

## Contrarian views & risks
- **Solo mantra ≈ speech** → the singing detector's main error; the PANNs cross-check + manual calibration exist to manage it.
- **Over-filtering kills style** — MOS gates and pitch/rate filters penalize expressive devotional delivery; keep gates loose.
- **No published accuracy** for any of these tools on ~56 kbps noisy Indian devotional audio → every number is an analogue; **validate on his own labeled slice**.
- **Enhancement can strip his Odia accent** (the thing we're preserving) → apply gently, A/B it.

## Open questions
- Exact `ory` % in his speech (resolved by the MMS empirical check above).
- Whether inaSpeech alone suffices for kirtana or the PANNs cross-check is needed (resolved by the calibration slice).
- Raw vs enhanced for the clone (resolved by the downstream A/B).

## Sources
Primary (high-confidence): Emilia-Pipe [2407.05361](https://arxiv.org/html/2407.05361v3) · IndicVoices-R [2409.05356](https://arxiv.org/html/2409.05356v2) · MMS [2305.13516](https://ar5iv.labs.arxiv.org/abs/2305.13516) · Indic-LID [2606.09317](https://arxiv.org/html/2606.09317v1) · accented-LID [2203.16972](https://arxiv.org/abs/2203.16972) · inaSpeechSegmenter [GitHub](https://github.com/ina-foss/inaSpeechSegmenter) + [LREC 2024](https://aclanthology.org/2024.lrec-main.785/) · PANNs [GitHub](https://github.com/qiuqiangkong/panns_inference) · AudioSet ontology [GitHub](https://github.com/audioset/ontology) · SVD survey [PMC8775013](https://pmc.ncbi.nlm.nih.gov/articles/PMC8775013/) · Thomas Interspeech-2018 [ISCA](https://www.isca-archive.org/interspeech_2018/thomas18_interspeech.html) · LoRA-TTS [2603.10904](https://arxiv.org/html/2603.10904v1) · Hinglish corpus [1810.00662](https://ar5iv.labs.arxiv.org/html/1810.00662).
Recent preprints (directional): naturalness-vs-style [2606.31729](https://arxiv.org/html/2606.31729v1) · ASR/CER filtering [2606.28728](https://arxiv.org/html/2606.28728v1).

### Rerun inputs
workflow: firecrawl-deep-research · depth: exhaustive (4 parallel agents, ~40 sources) · output: markdown
