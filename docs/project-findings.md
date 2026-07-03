# GGSM Voice-Clone — Project Findings & State

Durable record of what we've learned and built. **Goal:** clone Gour Govinda Swami's English voice
(VoxCPM2 LoRA) and produce a **calm diary Short** — GGSM alone at night writing to Gopāla, *not*
class-tone. Seva; license unconstrained.

Last updated: 2026-07-01. Detailed sub-docs linked inline.

---

## 0. Where we are (the map)
```
IDENTITY  (sounds like him)      ✅ provisionally locked  — 93–94% by two encoders
CONTROL   (register/emotion)     ✅ largely solved by CURATION (calm diary is presentable to devotees)
    ├─ register/calm  → calm reference + softened text + best-of-N funnel; residual word-spikes remain
    ├─ pronunciation  → per-word respelling in the text (Gopaal, ...) — deterministic
    └─ hallucination  → funnel gates (ASR/identity/duration) — handled
NOISE     (background bed)       🔬 LOCATED + measured — the reference clip's room tone, transferred and
                                    AMPLIFIED (+19 dB) by conditioning; cleaning trades noise↔identity
                                    → devotee-choice cleaning tiers (§9). Recipe pending their ear.
DIARY     (the deliverable)      🔶 a 5-ENTRY SERIES (§10) — v5 (8th-May) at 24-seed + male narrator;
                                    4 new entries prepped (lexicon + spoken dates); cleaning tier TBD
```
We crossed from an **identity** problem (solved) to a **control** problem (largely solved via curation),
to **production** (assembling the actual Short). The remaining edge is the last bit of residual
"shouting," which is a **data-layer ceiling** (below).

---

## 1. The levers — ranked by evidence
1. **Reference clip is THE dominant lever.** Swapping the prompt clip moved output ECAPA 0.733 →
   **0.806** (`ggs_l1_0081`), the biggest single gain of the project, no retraining. Reference identity
   drives output identity; LoRA + reference **stack** — use both.
2. **VoxCPM2 has a "Controllable Cloning" style dial — and we were bypassing it.** Passing `prompt_text`
   puts it in **Ultimate cloning** mode where a `(calm, hushed…)` style hint is *ignored*. Using
   `reference_wav_path` + the hint + **no** `prompt_text` = **Controllable** mode, where the style
   applies while keeping timbre. *(2B checkpoint only — ours is 2B.)* In practice the *instruction was
   flaky and hurt identity*; the **calm reference + softened text carry the calm** more reliably. See the
   ML-Journey "Controlling register in a voice clone" page.
3. **The reference sets the register.** `ggs_l1_0112` (old ref) is a LOUD lecture clip (186 Hz, 66.8 dB)
   → class-tone. `ggs_l1_0001` (140 Hz, 47.9 dB, identity 0.83) is his calmest strong-identity clip → the
   diary reference. A/B confirmed: calm ref = **measurably calmer prosody at ~zero identity cost**.
4. **Text valence.** Softening `!` → `…` (weight, not volume) + breath pauses makes the delivery
   prayerful — a real, free lever. His diary is already a prayer, so the words carry the intimacy.
5. **Data quantity from the *same* lecture is SATURATED** (n35→n140 flat); **denoising HURT** identity
   (−0.04); **diversity from new lectures** is the untested data lever. Keep new lectures clean.

---

## 2. Identity — solved, robustly?
**Provisionally yes.** ECAPA-TDNN + Resemblyzer d-vector (independent encoders) both place the clone at
**93–94%** of chance→ceiling, no overfitting, within his own clip-to-clip variation. Caveats (shared
English prior, chance floor, single-lecture centroid, no human ABX) in
**[identity-verification.md](identity-verification.md)**.

---

## 3. The diary production pipeline (what actually works)
```
TEXT     data/narration/diary_chunks_calm.txt  — softened (! → …), Gopaal respelled, his words intact
  ↓  split by role:
NARRATION (lines 1–3, 3rd-person)      GGS PRAYER (lines 4–23, 1st-person)
  base VoxCPM2, NO LoRA                  LoRA + calm ref ggs_l1_0001 (Controllable)
  → male narrator voice                  cfg 1.6, slow timesteps, 24 seeds/chunk
  (Voice Design + reference-lock)              ↓
       ↓                                 FUNNEL (scripts/assemble_diary.py):
       └──────────────┬───────────────→  gate: duration-outlier + (GGS chunks) ECAPA identity
                      ↓                   rank: graveness (↓pitch ↓range ↓rate) + VOCAL EFFORT
              STITCH with 0.9s pauses          (alpha ratio) + PEAK effort  → pick softest clean take
                      ↓
              full.wav  +  interactive swap gallery (voice_lab/diary_full/)
```
- **Pipeline scripts:** `cloud/narrate_funnel.py` (pod, two-pass generation) + `scripts/assemble_diary.py`
  (local funnel + stitch + gallery). Scoring is **cached** so pacing/weight tweaks re-stitch instantly.
- **The male-narrator split** is the fix for register *and* correctness: the 3rd-person framing (incl.
  the "lotus feet" line) is spoken by a base-model male narrator; GGSM's clone only speaks his own words.

---

## 4. Detecting "shouting" systematically (the key DSP insight)
Shouting is **not loudness** (we normalize that) — it's **vocal effort / pressed phonation**, whose
loudness-independent signature is **spectral tilt = the alpha ratio** (energy in 1–5 kHz vs 50–1000 Hz).
Higher = shoutier. The graveness meter (pitch/range/loud/rate) was *blind* to it, which is why "calmest"
picks still shouted. Added to the funnel (`vocal_effort()` in `assemble_diary.py`):
- **mean alpha** — overall effort; **peak alpha (p90)** — the loudest *moment* (a single shouted word
  hides in the mean). Both penalized in the pick.
- **Word-level** (`find_shouty_words.py`): force-align + per-word alpha names the shouty words (caveat:
  sibilants s/sh inflate it; compare the *same* word across seeds for a clean read).
- **The ceiling:** the funnel only picks the softest of N seeds; the lecture-trained clone has a
  **softness floor**, so residual word-spikes persist until (a) more seeds surface softer takes, or
  (b) the data-layer fix (calm training audio / voice conversion). More seeds = the current lever.

---

## 5. Tools built (scripts)
| Script | Purpose |
|---|---|
| `cloud/narrate_funnel.py` | Pod generator: base-model male narrator (1–3) + LoRA GGSM 24-seed (4–23) |
| `scripts/assemble_diary.py` | Funnel (gate + graveness + vocal-effort + peak) → stitch full.wav + swap gallery |
| `scripts/find_shouty_words.py` | Word-level vocal-effort — names the shouty words |
| `scripts/find_calm_ref.py` | Ranks his 140 clips by calmness (identity-guarded) → `ggs_l1_0001` |
| `scripts/gate_takes.py` | Take funnel: ASR hallucination + ECAPA identity + register rank |
| `scripts/build_graveness.py` | Register/calmness meter (↓pitch ↓range ↓loud ↓rate) |
| `scripts/verify_identity.py` | Two-encoder (ECAPA + d-vector) identity robustness check |
| `scripts/triage_lectures.py` | Scores all 112 taptajivanam lectures (English%/solo/transcript) |
| `scripts/propose_segments.py` | Pause-VAD segmenter (+auto-text +keep/cut); replaces the `.?!` cutter |
| `scripts/spectral_inspect.py` | Mel-spectrograms + noise-floor + band-shape — makes the noise VISIBLE, localizes its source |
| `scripts/ref_denoise_ab.py` | Reference noisy-vs-denoised A/B: noise floor + **dual-centroid** (confound-free) identity |
| `scripts/make_ref_candidates.py` | Builds gentle high-pass reference candidates (identity-safe clean) |
| `cloud/ref_ab.py` + `scripts/score_ref_ab.py` | Downstream CAUSAL ref A/B: same seeds × 4 refs → output noise + **two-encoder** identity |
| `scripts/assemble_variants.py` | 4 cleaning-tier full Shorts + combined **devotee A/B gallery** (population-labeled) |
| `scripts/seed_ablation.py` | Best-of-N seed curve (6/12/18/24) — what more seeds actually buy |
| `scripts/lexicon.py` | Maintained pronunciation dict + `spoken_date`/`spoken_range` (digits → spoken) |
| `scripts/prep_entries.py` | `data/diary/entries.md` → narration-ready chunks (lexicon + dates + role-split + soften) |

Deps added: `resemblyzer`, `webrtcvad-wheels`, `silero-vad`, `parselmouth` (F0/effort).

---

## 6. Infrastructure — the `voxcpm-vol` pattern (avoids the pod pain)
Community/stopped pods repeatedly **can't restart** (host full), and the RunPod MCP **can't attach a
network volume** to a pod. Solution: a **network volume `voxcpm-vol`** (EU-SE-1) holding the *entire*
environment — VoxCPM2 (4.7 GB) + LoRA + repo + **the venv** + generated takes. Every run: **deploy a
fresh pod on `voxcpm-vol` via the web console** (MCP can't), and it's **instant** — no download, no
LoRA re-upload. Drive it over SSH; leave it running while iterating (stop only when done). Cost: A5000
~$0.27/hr + ~$2.80/mo for the 40 GB volume.

---

## 7. Diary Short — status (v1 → v5)
- **v1** (calm ref + softened text + funnel): *presentable to devotees; shouting much reduced but present.*
- **v2/v3** (longer pauses 0.9s + slower/softer picks): calmer pacing; near the softness floor.
- **v4** (mean+peak vocal-effort penalty): marginal — the floor.
- **v5** (in progress): **3rd-person male narrator** for framing + **24-seed** GGSM pool for the prayer.

**Open next steps:** confirm v5 by ear → pronunciation pass on any remaining terms → optional music bed
for the devotee showing. If residual shouting still bothers below the floor: the data-layer fix
(collect calm audio of him, or voice conversion of a calm human read → his timbre).

---

## 8. Honest posture
Every claim is measured; caveats sit next to claims. The clone **is him** (identity), the calm register
is **achieved by curation** (not a dial), the residual shout is a **data-layer ceiling** we can name and
measure. Where a measurement first *disagreed* with a prior result (the noise labels, below) we chased the
artifact and fixed it rather than shipping it. For a **subjective, sacred** deliverable we make the
trade-off measurable and then **let the devotees choose** — we don't impose our ear.

---

## 9. Noise — located, measured, and handed to the devotees (2026-07-01)
The user's ear caught a faint background bed in v5. Made **visible + measurable** with
`scripts/spectral_inspect.py` (mel-spectrogram + noise-floor = p10 frame level + band-shape). **Localized**
and **confirmed three independent ways**:
1. **Spectral shape (correlational).** The GGS take's noise is ~99% below 500 Hz and matches the calm
   reference `ggs_l1_0001`'s room-tone shape; the **base-model narrator (no reference) is 50 dB cleaner**
   → the noise rides the LoRA+**reference** path, not the model's floor.
2. **Reference A/B + dual-centroid** (`scripts/ref_denoise_ab.py`). Denoising the reference drops its
   floor **−21.5 dB**, but a **confound-free** check (score vs a *denoised* centroid, mirroring
   `score_denoise_retrain.py`) shows a **real −0.057** identity move survives — the aggressive
   Resemble-Enhance denoiser shaves speaker cues too. A gentle high-pass is identity-safe but only ~−6 dB.
3. **Downstream CAUSAL A/B** (`cloud/ref_ab.py` + `scripts/score_ref_ab.py`) — same seeds, 4 references,
   only the reference changes. Output noise floor / ECAPA / d-vector: **noisy −52 dBFS / 0.805 / 0.913**;
   **hpf −58 / 0.793 / 0.902** (id-safe); **zipenh −64 / 0.781 / 0.882**; **RE −66 / 0.768 / 0.864**.
   **Both encoders AGREE** the aggressive cleans cost identity. So the survey's "denoise hurts identity"
   lesson **extends to the output/reference side too**.

**Decision:** don't impose a recipe on his sacred voice — produce the full diary in **4 cleaning tiers**
(untouched / high-pass / ZipEnhancer / RE) and let **devotees pick**. `scripts/assemble_variants.py` builds
the 4 full Shorts + a combined A/B gallery (`voice_lab/diary_variants/`), each tier labeled by its
**population-mean** noise+identity (all takes — the honest number). Whatever the devotees choose **locks
the recipe for all 5 entries**. hpf barely cleans (~−2 dB population) — the real fork is **untouched vs
ZipEnhancer** (~−13 dB, small measured identity cost).

**Two gotchas, recorded so we don't repeat them:**
- **Label tiers by POPULATION, not funnel-picks.** The first gallery mislabeled hpf as *noisier* — an
  artifact of averaging over the 20 funnel-*picked* takes (tiny, high-variance) plus a noise-gate that
  cherry-picked p10 **silence-frame** outliers. Population means are monotonic and match the causal A/B.
- **The funnel noise-floor gate was tried, then REMOVED.** Within a tier the bed is ~uniform (set by the
  reference), so a per-take noise term adds no signal and risks picking silence-glitch takes. **Noise
  belongs at the reference (tier), not the take-ranker.** The funnel ranks by graveness + vocal-effort only.

## 10. The diary is a 5-entry SERIES — prep pipeline + best-of-N seeds
The deliverable grew from one Short to a **series**: the 8th-May "night prasadam" entry (v5) **plus 4 new
entries** in `data/diary/entries.md` (Apr 13–27 sannyāsa dīkṣā, May 4 "desire tree", Jun 1 "machine in Your
hands", Jul 8–9 Puri). Each entry = **one full audio**; entries 2–3 open with a 3rd-person **narrator**
(base-model male voice), all carry his 1st-person prayer + the shared Gopāla refrain.

**Deterministic prep (not hit-and-trial):**
- `scripts/lexicon.py` — a *maintained* pronunciation dict: `normalize()` (Gopāla→Gopaal, Kṛṣṇa→Krishna, …
  + typographic-punctuation→ASCII + residual-diacritic strip → 7-bit clean, so any leftover non-ASCII is a
  true unmapped-term alarm) and `spoken_date()`/`spoken_range()` (the clone reads digit dates badly →
  `15-04-75` → "April fifteenth, nineteen seventy five").
- `scripts/prep_entries.py` — parses `entries.md` → role-splits NARR/GGS → substitutes inline dates →
  applies the ear-approved **prayerful softening** (`!`→`…`, lowercasing plain openers but **preserving
  reverential caps** You/Your/Lord, and *joining* short interjections: "Oh Lord… this servant…") → chunks
  under the ~20 s ceiling → writes per-entry `.tsv` (generation) + `.display.md` (transcript) + a
  `_review.md` **lexicon + spoken-date CHECK**. Output in `data/narration/entries/`.
  *Caveat: ~20 new diary terms (Vrindavan Dhaam, deeksha, tridanda, Ishopanishad, Ghanashyama, shravan,
  Ratha Yatra…) are best-guess spellings, NOT yet ear-tested — refine as takes are heard.*

**Best-of-N seeds (the funnel is best-of-N).** `scripts/seed_ablation.py` measured N = 6/12/18/24 on the
noisy tier: **24 seeds → a softer, less-shouty pick** (peak vocal-effort −0.99 → −1.27, ~10/20 lines get a
better take) but **diminishing returns** (6→12 is the big jump, 12→24 a polish — the √(ln N) shape of the
expected-max order statistic). **Noise and identity are TIER-level, seed-independent.** Practice: run the
A/B tiers at a fair **12 seeds**; regenerate only the **chosen** recipe at **24** for max quality. Concept +
citations (WebGPT, Tortoise CLVP, Beirami KL bound, order statistics) → Notion "Best-of-N sampling" page.

**Infra note — parallel generation.** One process leaves the A5000 at ~46% util (autoregressive batch=1
has idle bubbles); running **one process per tier** fills it to 100% (VRAM ~21/24 fits 3), but only
~**1.3×** throughput — it's compute-bound, not idle-bound, so more parallelism won't help past ~3.
