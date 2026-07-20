# HANDOFF — voice pivot: no longer cloning GGSM (2026-07-10)

**Read this first in the new chat.** It supersedes the "clone GGSM's voice" goal that drove all prior work.

## The new constraint
Mukul received an instruction to **use a voice OTHER than GGSM's**. His voice must **not** be cloned or
reproduced in output. His lectures remain the **source** (content/teachings to translate and re-narrate) — only
the **output narration voice** changes.

## The two workstreams
1. **Diary Shorts** — one Short per 1975 diary entry (text in `data/diary/entries.md`; Hindi passages in
   `data/hi/diary_passages.json`). Previously narrated with his clone → now needs a different voice.
2. **Lecture-teaching Shorts (dubbing)** — take his ENGLISH lecture clips → translate to Hindi → re-narrate with
   **meaningful emphasis** (stressing the points that matter), in a non-GGSM voice.

Both need: a Hindi (and probably English) TTS voice with a **devotional-narration register** and good
**expressiveness/control**.

## ⭐ The key unlock (this pivot HELPS the hardest problem)
Our biggest unsolved problem was **expressiveness** — the clone was flat, and no open Hindi TTS offered per-word
emphasis control. **Several strong models were disqualified ONLY because they cannot clone an arbitrary speaker.
That constraint is now gone**, which reopens them:

| Model | Hindi | Prosody control | Was blocked by | Now |
|---|---|---|---|---|
| **Indic Parler-TTS** (AI4Bharat) | ✅ 21 langs | ✅ **natural-language description** control (expressivity monotone→expressive, pitch, pace) | "can't clone GGSM" | ✅ **TOP CANDIDATE** — 69 preset voices, Apache-2.0 |
| **Sarvam Bulbul v3** | ✅ best commercial Hindi | auto LLM-inferred prosody; preset speakers | cloning gated | ✅ viable (API, paid) |
| **VoxCPM2** (our stack) | ✅ ok | punctuation→pauses; Voice-Design tag works in `reference_wav_path` mode | — | ✅ usable with a **non-GGSM** reference/voice |
| **ElevenLabs** library voices | ✅ | good | — | ✅ viable (paid) |

**Indic Parler-TTS is the headline:** description-based control ("expressive, slow, grave voice") is exactly the
steering lever we lacked with the clone. Its only disqualifier was cloning — which we no longer need.

## What CARRIES OVER (all still valid)
- **All prosody research** — `prosody-dubbing-research-2026-07-08.md` (incl. deep-research addendum),
  `voxcpm2-markup-research-2026-07-08.md`, `lora-finetune-research-2026-07-07.md`.
- **The concepts:** explicit vs implicit prosody control · the **text-centric bottleneck** (plain text loses
  delivery; it must be added back) · **cross-lingual emphasis mismatch** (EN raises pitch ON the word; Hindi
  compresses AFTER + word order + ही/तो) · **placement vs contour** (get *where* to emphasize from the source/LLM;
  realize it the *Hindi* way).
- **The experiment method** — pre-registered predictions + gallery-based by-ear judging. Reuse it.
- **The authored Hindi script** (देवदासी prasang) — voice-independent, ready to re-render on any engine.
- **Pipeline scripts** — `scripts/hi/*.py` (generation, funnel, ASR check, scoring), `data/hi/narration_gallery.html`
  (evaluation gallery; serve with `python -m http.server 8747 -d data/hi`).
- **Translation/authoring work** — diary passages, fix passages.

## What is now OBSOLETE
- Cloning his voice (zero-shot with **ref 0008**, expressive-reference search, `ref_shortlist.jsonl`,
  `expressive_refs.jsonl`).
- **LoRA on his voice** (was the planned fix for his cadence) — dropped entirely.
- **ECAPA similarity to HIS centroid** as the quality metric. (ECAPA may be repurposed to check *consistency* of
  whichever new voice we choose.)
- The 106-clip Hindi training set as *voice* training data (`data/hi/train_final`) — his audio is still useful as
  **source content**, not as a voice reference.

## Findings from the last experiment (still inform voice selection)
From `narration-expressiveness-experiment-2026-07-09.md` (judged 2026-07-10):
- Authored `…` **pauses land** ✅ and **`समझे?` renders as a question** ✅ in Hindi on VoxCPM2.
- **Word-level emphasis does NOT render** ❌ (repetition stayed flat) — no emphasis knob.
- Output was **understood but flat** — the gap was **pitch swing** + **pause length/drama** (he wanted long holds
  like *"अरेeee……"*), **NOT** comprehension.
- ⇒ **Whatever voice/engine we pick, judge it on: pitch swing, dramatic pause length, and controllable emphasis.**
  This is exactly where Indic Parler-TTS's description control should be tested first.

## Current state / assets
- **Repo branch:** `hindi-clone` (consider a new branch for this direction). Nothing pushed to `main`.
- **Pod `84nwihsu7dp6ol`: STOPPED** (data preserved). Network volume `guh6h6cs9a` → `/workspace` holds:
  `VoxCPM/` (code @ `07c937b`), `VoxCPM2/` (model), `venv_train/` (py3.11, torch on slow volume — **imports hang**),
  `venv_local/` (py3.12, **fast**, system torch 2.8 + editable voxcpm `07c937b` — **use this one**),
  `gen_narration.py`, `out_narration/`.
- **Gotchas that cost hours — don't repeat:**
  - `venv_train`'s torch is on the network volume and **hangs on import**; use `/root/venv_local/bin/python`.
  - Never put `pkill -f <script>.py` in an SSH command — the SSH shell's own cmdline matches it and **kills the
    session** (`exit 255`). Launch detached with `setsid`.
  - RunPod MCP: its v2 base host `v2-rest.runpod.io` **doesn't exist**; fixed via
    `RUNPOD_REST_V2_API_URL=https://rest.runpod.io/v1` in `~/.claude.json`. **Reads work; write actions**
    (stop/start) need a direct curl to `POST https://rest.runpod.io/v1/pods/{id}/stop`.
- **Local audio:** `data/hi/out_narration/` (14 takes, matched-version render).

## Recommended first steps in the new chat
1. **Decide the voice/register** for each workstream (they may differ: diary = intimate/narrative; teachings =
   authoritative/devotional). Constraint: must not be GGSM.
2. **Bake-off on the same authored Hindi passage** across: **Indic Parler-TTS** (with varied description prompts),
   **Sarvam Bulbul v3**, **VoxCPM2 + a non-GGSM reference/Voice-Design**, and optionally **ElevenLabs**. Judge by
   ear on **swing / pause drama / emphasis control** using the existing gallery pattern.
3. **Confirm licensing/permission** for whichever voice is chosen (preset voices have usage terms; a real person's
   voice needs consent).
4. Then rebuild the Shorts pipeline on the winner.

## Open questions for Mukul
- Any constraint on *which* voice (male/female, age, a specific approved narrator, or a synthetic/preset voice)?
- Should the diary and the teachings use the **same** voice or different ones?
- Is his voice barred from output **entirely**, or may original audio still be used unmodified (e.g. real clips)?
- Does the instruction affect the **English** clone work too, or Hindi only?
