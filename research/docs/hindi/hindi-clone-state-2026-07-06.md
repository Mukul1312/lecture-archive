# GGSM Hindi Clone — State & Handoff (2026-07-06)

Resume point after today's session. Companion to [hindi-clone-plan.md](hindi-clone-plan.md),
[project-findings.md](../voice-cloning/project-findings.md), [identity-verification.md](../voice-cloning/identity-verification.md).

## Headline: a working **zero-shot** Hindi clone + first 3-min diary Short. LoRA deferred.

We hit a wall on **LoRA fine-tuning** (NaN), root-caused it, then **pivoted to VoxCPM2 zero-shot
voice cloning** — which works and, at passage length, measures **at/above his real-voice level**.

## What works now (the locked v1 recipe)
- **Base:** VoxCPM2 (`/workspace/VoxCPM2` on the pod), no LoRA. Inference is clean (EN + HI).
- **Mode:** `generate(text, prompt_wav_path=<ref>, prompt_text=<ref transcript>)` — "hifi/Ultimate".
  Plain mode (prompt_wav without prompt_text) is **not supported** by this build (ValueError).
- **Reference clip: `ggm-hindi-lecture-01_0008.wav`** (winner of a 12-candidate ECAPA refsweep;
  output-ECAPA **0.784** vs the old 0074's 0.657 — **+0.13 just from reference choice**).
  Its transcript (prompt_text) is in `data/hi/ref_shortlist.jsonl`.
- **Passages, not short clips:** generate multi-sentence passages (~6–14s each). Longer = more
  confidently him (short 4s clips understate identity). **Drop the lead-in** for passages.
- **Seed funnel:** 4 seeds/passage → gate truncation/loops by duration → keep highest ECAPA.
- **cfg 2.0, inference_timesteps 10.**

## Measured results (local ECAPA, cross-lecture centroid from L2-4; his-own ceiling ~0.767)
- His real reference clip: 0.812
- Short clips (ref 0008): 0.76–0.79
- **v1 combined 16s passage: 0.836**
- **Diary Short (2:46 whole clip): 0.864**  ← above ceiling and above his real ref
- Per-passage diary mean 0.816 (range 0.77–0.85)
- Prosody caveat: crude F0 (numpy autocorr) suggests the clone is a touch **higher-pitched + flatter**
  than his grave real voice (his real spread ~60Hz; clone ~49Hz; ~6/15 passages flagged flat).
  Numbers are directional only (his masters are narrowband ~4kHz vs the 48kHz clone). This prosodic
  gap is the main zero-shot-vs-real difference and is what a **LoRA would close**.

## Deliverable produced
- **`data/hi/diary_entry2.wav`** — 2:46, GGSM's own 1975 diary Entry 2 ("You are the real desire tree")
  in cloned Hindi. Text (15 passages) in `data/hi/diary_passages.json`. Only the `[GGS]` parts; the
  `[NARRATOR]` intro is a separate voice (not done yet).
- Awaiting the **user's ear verdict**: ship zero-shot for diary Shorts, or invest in the LoRA for ~0.87.

## The LoRA situation (deferred, root-caused)
- Training NaN'd from step 0 in the **DiT flow-matching loss** — two causes: (1) padded rows fed to the
  per-row DiT → NaN → poisons masked-loss grads; (2) DiT activation explosion → backward overflow.
- **Fix built:** `scripts/hi/patch_voxcpm_fix.py` (memfix + fp32-diff + padfix row-filter + math-SDPA +
  grad safety-net). It makes training **stable** (no crash) but effective learning was inconclusive in
  short tests; `batch_size 1` made it worse; fp32-master (no memfix) fit 24GB but didn't help.
- **Untried lever if we resume LoRA:** pin **torch 2.5.1** (docs' tested version; we're on 2.6.0 which
  has bf16-SDPA NaN regressions). VoxCPM2 Hindi is a documented weak language (WER 19.7, issue #288),
  so there's a real ceiling; IndicF5 is the plan's fallback.

## Pod (RESUME TOMORROW)
- **Pod `oc3x3gyn7w3xgu`** (RTX 4090, EU-RO-1, $0.69/hr) — **STOPPED** today. Persistent network volume
  `guh6h6cs9a` at `/workspace` keeps: `VoxCPM2` base, `venv_train` (torch 2.6, VoxCPM installed -e +
  patched), whisper-large-v3 cached, `out_diary`/`out_refsweep`/`out_v1`, `ref_shortlist.jsonl`, and all
  gen scripts. **Start the pod, re-fetch the SSH endpoint (IP/port change on restart), /workspace is intact.**
- SSH pattern: `ssh -i ~/.ssh/id_ed25519 -p <port> -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@<ip>`
- Detached jobs: `setsid bash -c '... > log 2>&1' < /dev/null &` (the ssh call will "time out" locally at 2min
  because the child holds the channel — the job keeps running; poll the log).

## Scripts (rescued to `scripts/hi/`)
- Pod (generation): `refsweep_hi.py`, `gen_diary.py`, `combine_v1.py`, `final_v1.py`, `base_infer.py`,
  `clone_test.py`, `improve_clone.py`, `plain_vs_hifi.py`, `asr_check.py`, `patch_voxcpm_fix.py`.
- Local (CPU analysis, uses `.venv/Scripts/python.exe` + speechbrain ECAPA cached in `.venv/spkrec`):
  `score_hi_clones.py`, `ref_shortlist.py`, `refsweep_score.py`, `funnel_diary.py`, `analyze_diary.py`,
  `trim_leadin.py`.

## Immediate next steps (tomorrow)
1. **User's ear verdict** on `data/hi/diary_entry2.wav` → decide zero-shot-ship vs LoRA.
2. **Finish the ASR word-check** (`scripts/hi/asr_check.py`, now decodes audio via soundfile to bypass the
   broken torchcodec) — start pod, re-run, get per-passage CER vs intended Hindi.
3. If zero-shot ships: add the `[NARRATOR]` intro (separate voice) + build the remaining diary entries.
4. If LoRA: apply `patch_voxcpm_fix.py` on a **torch 2.5.1** venv and retest.
