# Clip segmentation policy — GGS voice clone (VoxCPM2 LoRA)

*Source-verified 2026-06-15 via two independent research passes that converged: a 102-agent web-search harness (adversarially verified — 15 claims confirmed, 10 killed) + a Firecrawl full-content scrape of primary docs. Plus a direct analysis of GGS's own transcript.*

## TL;DR
**A clip = one pause-bounded prosodic phrase, cut in real silence, ~5–15s, text matched exactly to the audio.**
Follow the **audio's pauses**, not the transcript's `.?!`.

---

## 1. Duration (high confidence)
- **Target average ~5–10s; working range ~3–15s; soft ceiling ~20s.** Floor: avoid <3s, never <1s (unstable).
- VoxCPM docs state **3–30s** is the "practical sweet spot" (<1s unstable; very long clips filtered by `max_batch_tokens`). The ~30s upper figure is the *doc's* range; the broader, verified evidence says **autoregressive TTS degrades past ~20s** (alignment failures, skips/repeats, OOM), so treat **~20s as the real ceiling**. (The "VoxCPM tolerates ~35s" claim was *refuted* 0–3.)
- Cross-field convergence: LJSpeech 1–10s (mean 6.6s); FireRedTTS 2–20s; Tortoise 5–20s (27s cap); Azure Custom Voice ≤15s; Orpheus "best 5–15s". Ideal **average** ~5–10s (confirmed 3–0).
- **Keep a natural mix of short + long** clips (Gaussian-ish). Only-short hurts long-text inference; only-long harms alignment (confirmed 3–0). Don't force uniform length.

## 2. Boundary unit (high confidence) — the key decision
- **Cut at a real PAUSE (silence), at a natural prosodic boundary. No mid-word cuts; merge tiny fragments.** (confirmed)
- **Sentence-level is the standard for *read* speech** (LJSpeech/LibriTTS), where the reader pauses at printed periods so sentences == pauses.
- **GGS is a spontaneous speaker, so `.?!` ≠ pauses.** Direct transcript evidence (this lecture, 3,440 words):
  - 282 terminal marks vs **185 real major pauses** → a period every ~12 words, a real pause every ~19 words.
  - **26% of "sentences" are ≤4 words, 41% ≤6 words** — phrase-ends ("You see.", "This griha is mine."), not sentence-ends.
  - ⇒ The transcriptor's punctuation is orthographic, not acoustic. **Do not use `.?!` to place boundaries.**
- For spontaneous speech the unit is the **inter-pausal prosodic phrase**. Sub-sentence *breath-group fragmentation that ignores pauses* is not better (the "IPU beats sentence" superiority claim was refuted 0–3) — but **pause-bounded segmentation is correct and is what we use.**
- **Multi-sentence "idea-level" clips (20–40s) are discouraged** (exceed the AR ceiling).
- **The transcript supplies the WORDS for a span; the audio supplies the BOUNDARIES.**

## 3. Mid-sentence / mixed-idea cuts
- Avoid. Cut in silence at a real pause; never split mid-word; don't let a clip's audio run into the next phrase. (A clip whose text doesn't match its audio is the #1 poison — see the boundary-offset findings.)

## 4. Silence edges (high confidence, primary)
- **Trim leading/trailing silence to <0.5s** — long trailing silence is the **#1 cause** of VoxCPM "won't-stop-generating" after fine-tuning (primary, 3–0).
- Clean onsets/offsets; no clipped boundary words.

## 5. Clip count / LoRA rank
- ~**150 clips is fine** — above the 5–50 single-speaker minimum, in the 50–500 "domain/style" tier → use **higher LoRA rank (r=32–64)** at train time.

## 6. Code-switching (English + sprinkled Sanskrit/Bengali)
- No source addresses it directly (low confidence). General rules apply: keep his English-with-sprinkled-terms (his real voice), drop continuous verse/Bengali/second-voice spans, cut in silence.

---

## Operative policy for the re-segmenter
1. **Boundaries = audio pauses** (waveform silence), cut at the *strongest* pause in each ~5–15s window.
2. **Transcript = words only** (correct each clip's text to match the audio; ignore `.?!` as cut points).
3. Target avg ~8–10s; ≤~20s ceiling; merge sub-3s fragments; keep a length mix.
4. Trim silence <0.5s; no mid-word cuts.

## Sources
voxcpm.readthedocs.io/en/latest/finetuning/{finetune,faq}.html (primary) · github.com/OpenBMB/VoxCPM/issues/271 (maintainer) · keithito.com/LJ-Speech-Dataset · docs.coqui.ai XTTS + "What makes a good TTS dataset" wiki · arXiv 2409.11915 (IPU), 2509.17988, 2106.06309 (HUI), 2305.07243 (Tortoise), 2409.03283 (FireRedTTS) · learn.microsoft.com Azure Custom Voice.
