# GGSM Hindi Voice-Clone — Plan & State

Durable plan for extending the finished **English** clone to a **Hindi** clone of Gour Govinda Swami
Mahārāja. Companion to [project-findings.md](../voice-cloning/project-findings.md) (English) and
[identity-verification.md](../voice-cloning/identity-verification.md). Seva; license unconstrained.

Created: 2026-07-01. Research-verified (primary sources cited inline).
**Status (updated 2026-07-02):** **VoxCPM2-Hindi is a GO.** Content pass run (he's ~solo in all 4 lectures;
~109 min confident Hindi); **210 clips extracted** with Whisper-draft transcripts; transcript review IN
PROGRESS; base-model probe ear-confirmed (recognizably him + clean, correct Hindi); reference-selection
scorer built. All data pulled to `data/hi/` locally, pod stopped. **Next:** finish the 210-clip review →
reference selection over the corrected pool → Hindi LoRA.

---

## 0. The one fact that decides everything

**We have ~4 real Hindi lectures of him.** That makes this **same-language cloning** (the regime the
English clone already solved to 0.806 ECAPA) — **not** cross-lingual synthesis. This matters because the
entire research literature warns that *cross-lingual* cloning (making a voice speak a language it never
recorded) degrades badly for Hindi specifically:

- Google zero-shot voice-transfer: from a single **English** reference, **Hindi scored *lowest* of 9
  languages** (~47% same-speaker vs 68–90% for European) — [arXiv 2409.13910](https://arxiv.org/html/2409.13910v1).
- Our own hypothesis *"an English LoRA/reference preserves identity into Hindi"* came back **REFUTED** in
  verification — timbre and accent are entangled, so an English reference leaks an English accent.

Because we have his Hindi audio, **we sidestep all of that**: train the LoRA on his Hindi clips, prompt
with a Hindi reference clip of his own voice. The scary literature does not apply to us.

---

## 1. Source archive — ISKCON Desire Tree (recon 2026-07-01)

Folder: `audio.iskcondesiretree.com/.../His_Holiness_Gour_Govinda_Swami/Hindi_Lectures`

- **4 MP3s, flat, no transcripts.** `GGM_Hindi_Lecture-01…04.mp3`, ~107 MB total.
- Static PHP file-index (Andromeda 1.9.3.6) — plain server-rendered HTML, **stable path-based URLs**, no
  auth, `Accept-Ranges: bytes` (resumable), `robots.txt` empty. **A stdlib HTTP scraper suffices** — no
  firecrawl/headless. → scripts/fetch_idt.py (`scripts/fetch_idt.py`).
- **Measured (fetched 2026-07-01, `fetch_idt.py` → `data/hi/lectures/`):** **4.47 h** — L01 78.8min, L02
  49.5min, L03 71.6min, L04 68.3min; all **56 kbps MP3, ~4 kHz effective bandwidth** (old narrowband masters).
  Closer to the user's "~5 h" than first estimated. Either way it's **enough** — the English clone trained on
  *one* ~30-min lecture (140 clips); four lectures is more.
- **Bonus:** the same parent folder holds his **`Oriya_Lectures`** (subfoldered) + 92 Bhajans. The Oriya
  trove is exactly what the long-term **Odia→Hindi translation** goal needs, and an extra *Indic* reference
  source. One scraper-recursion away.

---

## 2. Model reality — verified

**VoxCPM2 officially supports Hindi** (CONFIRMED): named in the 30-language list on the live
[GitHub README](https://github.com/OpenBMB/VoxCPM) + [HF card](https://huggingface.co/openbmb/VoxCPM2),
accepts **Devanagari directly**, no language tag. So the whole trained-model recipe *can* carry over.

**But Hindi is one of its two weakest languages** (CONFIRMED): the
[tech report](https://arxiv.org/html/2606.06928v1) says *"The main weaknesses appear in Arabic and Hindi …
relatively limited data volume."* Minimax-test Hindi **WER 19.7** vs English ~2.3, and
[issue #288](https://github.com/OpenBMB/VoxCPM/issues/288) reports Hindi cloning misbehaving. So the **base
model gives our LoRA a shakier Hindi foundation than English had** — this is the wildcard, and why we
**probe before investing** (§6, step "base-model probe").

**Fallback if VoxCPM2 Hindi is too weak:** **IndicF5** (AI4Bharat — native Hindi, reference-clip cloning,
MIT tag; fine for non-commercial seva — note its F5-base license lineage is murky for *commercial* use) or
**svara-tts-v1** (Apache-2.0, LoRA-friendly). Switching the base keeps all data-prep / eval / funnel.
`IndicParler-TTS`/`Sarvam` (our old notes) are **not** right — IndicParler can't clone an arbitrary voice
(catalog voices only); Sarvam is closed API-only.

---

## 3. Source analysis — measured (2026-07-01)

Analyzed the raw source *before* any transcription/labor (cheap → expensive; de-risk before build).

**Acoustic triage** (`scripts/analyze_source.py`, local CPU): 4.47 h, no clipping, healthy 70–83% speech.
Effective bandwidth ~**3.9–4.9 kHz** across all four → old narrowband masters, a real timbre ceiling (VoxCPM
super-res can't invent >~5 kHz detail that was never recorded). Per-lecture cleanliness (`spectral_inspect.py`
noise-bed shape on mid-lecture 75 s excerpts):
- **L03 = cleanest** (noise floor −55 dB, SNR ~39) → cut the **reference clip** from here; prioritize in training.
- **L01/L04 noisy but mostly low-freq rumble** (L01 81% <120 Hz; L04 67% .12–.5k) → a **high-pass ~100–120 Hz**
  removes it *without touching his ~130 Hz voice* (identity-safe, unlike broadband denoise which cost −0.04).
- **L02 noise sits in the speech band** (59% mid + 20% hiss) → hardest to clean; handle last.

**Analysis toolkit inventoried** (codebase + ML Journey + field-standard, 3-agent survey): the full menu of
ways to characterize the source (acoustic quality · speaker identity · register/prosody · content/language ·
segmentability). Concepts we lacked as documented pages were written up as **5 new Notion ML Journey pages**
(SNR/neural-MOS/bandwidth · reverb+LUFS · MCD/F0-RMSE · WER/CER+multi-ASR · VAD+language-ID).

**Content pass — built + reviewed, awaiting a pod:** `cloud/content_triage.py` = the **viability gate**. Reuses
`pod_dataprep.py`'s diarization + ECAPA cluster-pick verbatim, adds Whisper language-ID over GGS-only windows →
per-lecture **GGS-min and how many are Hindi = the trainable pool** (`data/hi/content_triage.json` + `.tsv`).
Adversarially reviewed (no blockers; 7 metric/reporting fixes applied). Honest caveat baked in: Whisper has no
Odia label, so "Hindi" may fold in his Odia stretches (Bengali/Nepali mislabels flag it) — a coarse Hindi-share
+ Sanskrit/English router, not a true Hindi-vs-Odia separator.

---

## 4. What transfers / changes / new

| Stage | Hindi status |
|---|---|
| Fetch | 🆕 `fetch_idt.py` — ISKCON DT is a file-index with no transcripts (vs taptajivanam's page-scrape) |
| **Transcribe** | 🆕 **the only genuinely new stage** — Hindi ASR (Whisper-large-v3 / IndicWhisper / IndicConformer) + light human correction. Bounded: ~2–4 h of audio |
| Diarize + ECAPA cluster-pick | ♻️ reuse as-is (language-agnostic — separates by voice) |
| Align → sentence clips (`align_cut`/`propose_segments`) | 🔧 swap `language='en'` for a Hindi aligner (MMS / Whisper-hi / MFA-Hindi) |
| Text norm (`lexicon.py`/`classify_transliterate.py`) | 🔧 rebuild → Devanagari-native + Hindi number/date spell-out (`lexicon_hi.py`) |
| QA round-trip (`qa`/`gate_takes`/`score_funnel`) | 🔧 Hindi ASR + re-calibrated CER/WER thresholds |
| Manifest + LoRA train (`pod_train.sh`, `voxcpm_lora.yaml`) | ♻️ reuse ~verbatim (same VoxCPM2, r=32, bf16 memfix) |
| Reference selection (`find_calm_ref`/`make_ref_candidates`) | ♻️ reuse method (ECAPA-cos-to-centroid); needs a Hindi ref clip |
| Identity eval (`verify_identity`) | ♻️ reuse method; 🔧 re-establish floor/ceiling *numbers* (ECAPA is English/VoxCeleb-trained) |
| Funnel + prosody meters (`assemble_diary`,`build_graveness`,`find_shouty_words`) | ♻️ reuse (find_shouty needs the Hindi aligner) |
| Infra + deploy (RunPod `voxcpm-vol`, galleries, Vercel) | ♻️ reuse as-is |

Two things in our favor, already established: **don't denoise** (training on original noisy clips beat
denoised, −0.04), and his **Odia-accented Hindi is authentic**, not a defect.

---

## 5. Codebase structure — DECIDED: additive (English stays frozen)

The English clone is shipped; `data/out/lecture1/` is hardcoded 126× but almost all in *frozen R&D
scripts*. So **no big-bang restructure.** Additive changes only:

1. **Namespace data by language:** new work under `data/hi/lectures/<slug>/` and `data/hi/out/<slug>/`.
   English data + scripts untouched.
2. **One small per-language config** (`configs/hi.py` / `configs/en.py`, or a `PROJECT` dict): source
   archive, ASR/aligner lang code, lexicon module, data roots, QA thresholds, locked reference clip. This
   is the DRY move that makes the eventual **Odia** layer nearly free.
3. **Parameterize the ~15-file reusable spine** with `--lang`/`--config` (default `en`, so English behavior
   is byte-identical). Leave the flat `scripts/` layout; the frozen `build_*`/`score_*`/`infer_*` R&D pile
   is not touched or ported.

Reusable spine (generalize) vs frozen English R&D (leave): the spine is ~⅓ of the files; the rest is
one-off experiment scaffolding that got English to 0.806 and the diary Short.

---

## 6. Roadmap — status (updated 2026-07-02)

- ✅ **Fetch** — `fetch_idt.py` → 4 mp3s (4.47 h).
- ✅ **Acoustic triage** — L03 cleanest, L01/L04 low-freq rumble, ~4 kHz band (§3).
- ✅ **Content pass** — `content_triage.py` on an A5000 pod: he is ~**solo in all 4** lectures (~100% GGS,
  negligible questioners); ~**109 min confident Hindi** (hi+ur). Whisper (no Odia label) dumps his Odia into
  Bengali/Nepali (~22 min) and hedges ~44 min "uncertain". **Data quantity is not a constraint.** (L04's
  `low_margin` flag was a false alarm — a 0.2-min blip cluster; he's unmistakably the pick.)
- ✅ **Extract Hindi clips** — `extract_hindi.py`: LID-confident (hi+ur) spans → sentence clips + Whisper-draft
  transcripts = **210 clips / ~48 min** (already > the English clone's 140; the cutter drops sub-8s fragments,
  so 48 min is the clean core, not a shortfall).
- 🔶 **Transcript review** — `build_hi_review.py` gallery (play + edit Devanagari + drop + ⭐ref + autosave);
  **IN PROGRESS** — user correcting the 210 Whisper drafts.
- ✅ **Base-model probe = GO** — `probe_hi_refs.py`: 4 user-picked refs × 3 Hindi sentences × 3 seeds on BASE
  VoxCPM2 (no LoRA). **Ear-verdict: recognizably him + clean, correct Hindi** at the floor. ECAPA output
  ~0.69–0.75 to his Hindi centroid (his real clips ~0.87; LoRA will close the gap). → **build on VoxCPM2**;
  IndicF5 fallback unused.
- ⏳ **Reference selection** — `score_probe_refs.py` (ECAPA cos-to-centroid) built + practised on the 4:
  representativeness barely varies over a homogeneous set (0.05 spread) and DIFFERED from output-identity at
  #1 → the robust method is **two-stage: representativeness-shortlist over all 210 → refsweep-confirm by
  output identity** (as English did). Run over the corrected 210 to lock the production reference.
- ⏳ **Hindi LoRA** — reuse `pod_train.sh` + `voxcpm_lora.yaml` on the corrected clips + locked reference; eval + funnel.

**Infra note (2026-07-02):** content-pass ran on a **no-volume community A5000** pod (torch-2.4 whisper/pyannote
system env + a separate torch-2.6 venv for VoxCPM2 via `pod_infer.sh`). Driving the pod: the RunPod MCP does
lifecycle only (no exec) — run pod commands via `ssh root@<ip> -p <port> "cmd"` (the skill's own recommendation).
All data (clips, transcripts, content_triage LID, probe takes) pulled to `data/hi/` locally; pod **stopped**.
New pods were capacity-limited, so tomorrow may need a fresh pod (re-`pod_setup.sh`/`pod_infer.sh` + re-upload `data/hi/`).

---

## 7. Open questions / caveats

- **Devanagari vs romanized** frontend — untested; the probe answers it (finetune-plan.md (`docs/finetune-plan.md`)
  flags the tokenizer as zh+en-centric).
- **Base-model Hindi ceiling** — WER 19.7 + issue #288 mean base artifacts could cap quality even after
  LoRA. Audition (probe) before committing.
- **ECAPA/d-vector recalibration** — encoders are English/VoxCeleb-trained; the identity floor/ceiling
  framing must be re-established on Hindi (method transfers, numbers don't).
- **Transcription QA** — no ground-truth transcripts, so the ASR-round-trip gate compares ASR-to-ASR;
  needs a Hindi ASR good enough that its errors don't mask real ones. Human spot-check the corrected text.

---

## 8. Scripts added this phase

| Script | Purpose |
|---|---|
| scripts/fetch_idt.py (`scripts/fetch_idt.py`) | Stdlib scraper: enumerate the ISKCON DT Hindi folder → download 4 mp3s into `data/hi/lectures/` |
| scripts/analyze_source.py (`scripts/analyze_source.py`) | Acoustic-quality triage (duration/speech%/loudness/clip%/SNR/effective-bandwidth), local CPU |
| cloud/content_triage.py (`cloud/content_triage.py`) | Content pass / viability gate: diarization + ECAPA cluster-pick + Whisper language-ID → GGS-min & Hindi-min (trainable pool) |
| cloud/extract_hindi.py (`cloud/extract_hindi.py`) | Cut confident-Hindi (hi+ur) spans → 210 sentence clips + Whisper-draft transcripts (`clips_hi/` + `train_hi.jsonl`) |
| scripts/build_hi_review.py (`scripts/build_hi_review.py`) | Local transcript-review gallery: play + edit Devanagari + drop + ⭐ref, autosave, download corrected/ref JSONL |
| cloud/probe_hi.py (`cloud/probe_hi.py`) | De-risk probe (single ref): base VoxCPM2 Hindi audition (Devanagari/romanized × hifi/plain × seeds) |
| cloud/probe_hi_refs.py (`cloud/probe_hi_refs.py`) | Multi-ref VoxCPM2 Hindi probe from `probe_refs.jsonl` (refs × sentences × seeds) — the GO/no-go |
| scripts/build_probe_gallery.py (`scripts/build_probe_gallery.py`) | Audition page for the probe takes (real ref vs generated, per reference) |
| cloud/score_probe_refs.py (`cloud/score_probe_refs.py`) | Reference scorer: ECAPA cos-to-centroid representativeness + per-ref output identity |
