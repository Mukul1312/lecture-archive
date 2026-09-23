# VoxCPM2 markup / prosody-control — research (2026-07-08)

Adversarially-verified deep-research (17 primary sources: readthedocs, GitHub, HF, PyPI). For the **dubbing
service** (his English clips → Hindi in his voice, matching HIS phrasing). Companion to
[lora-finetune-research-2026-07-07.md](lora-finetune-research-2026-07-07.md).

## Bottom line
**VoxCPM2 has NO markup for emphasis/stress/intonation** — no SSML, no break/pause tokens, no phoneme input,
no stress marks, no temperature. You cannot write "emphasize this word." Delivery is steered only two ways:
**punctuation (pauses)** and a **global Voice-Design style tag** — and even those are documented on
Chinese/English only, **never confirmed for Hindi.**

## What you CAN author
| Lever | Effect | Notes |
|---|---|---|
| **Punctuation → pauses** | `. ?` = clearer sentence-final pause · `,` = shorter pause · `…` = hesitation/trailing | Pause **length NOT controllable** → for a stronger pause, **split into shorter sentences** |
| **Voice Design tag** | `(slow, grave, questioning voice)` at the **start** of the text → steers age/gender/pitch/pace/emotion/texture | Written in **English/Chinese** (Hindi tag unknown). **IGNORED in Hi-Fi cloning mode** (see below) |
| **cfg_value** (1.0–3.0) | higher = stricter adherence to conditioning | slider actually 1–50 |
| **inference_timesteps** (4–30) | more = better detail, slower | default 10 |
| **normalize** = False | keep **OFF** when hand-authoring (else it rewrites numbers/symbols) | ON only for raw digits/dates |

## What you CANNOT author
- ✗ **Word emphasis / stress** — no mechanism at all. Emphasis only emerges from the model's auto-inference from content.
- ✗ **Question rise** — `?` is documented only as a **pause**, NOT a guaranteed rising intonation (exactly the "समझे?" effect we want → unverified).
- ✗ **Pause length** — not controllable (split sentences instead).
- ✗ **SSML / break tokens / phoneme / stress marks / temperature** — none exist. (GitHub feature-requests #276 "pause control" + #297 "speech-rate control" confirm they're wanted but absent.)

## The mode tradeoff (important)
- **Hi-Fi cloning** = `prompt_wav_path` + `prompt_text` → best timbre/identity, **but Voice-Design tags are IGNORED.** (This is the mode we've used.)
- **Controllable cloning** = `reference_wav_path` + `(style tag)` → the tag works (style/pace/emotion), **timbre may be less locked.**
- So: to steer global tone (grave/slow), switch to `reference_wav_path` mode and accept a possible identity cost — **test the tradeoff.**

## The Hindi asterisk (critical)
**Nothing above is confirmed for Hindi.** All confirmed behavior is Chinese/English. VoxCPM is trained primarily
on CN/EN and warns other languages may be unpredictable (relevant to issue #288). The danda `।`, em-dash `—`,
and line breaks are simply **undocumented** (em-dash *reportedly* nudges pauses — untested). **We must verify all
of it empirically on his cloned Hindi voice.**

## What this means for the dubbing service
- ✅ **His deliberate PAUSES / chunking** ("यह देवदासी… का प्रसंग…") **are authorable** — via `…`, `,`, and sentence-splitting. This is a real lever.
- ⚠️ **His EMPHASIS and question-RISE are NOT authorable via markup.** They must come from: (a) **content-driven text** (dramatic dialogue/exclamations read expressively on their own), (b) the **Voice-Design global tone** (mode tradeoff), or (c) a **LoRA** that learns his patterns.
- So authored-markup gets us **phrasing/pauses**, not fine emphasis. The exact "where he stresses" is a LoRA / content-driven job, not a markup job.

## Empirical test to run (when pod is up) — `scripts/hi/markup_test.py` (expand)
1. Does `?` **rise** in Hindi or only pause? (`समझे।` vs `समझे?`)
2. Do `…` / `,` / `।` / `—` create pauses **where placed**? (danda + em-dash are the open questions)
3. Does `!` add any stress/energy?
4. **Voice Design test:** `reference_wav_path` + `(slow, grave, questioning voice)` vs Hi-Fi mode — does the tag help, and what's the identity cost?
5. Keep `normalize=False` throughout.

## Sources
readthedocs api.html / usage_guide.html / cookbook.html / voxcpm2.html · GitHub OpenBMB/VoxCPM (core.py, app.py) +
issues #276/#288/#297 · HF openbmb/VoxCPM2 · PyPI voxcpm. (Hindi-specific claims landed UNVERIFIED due to verifier errors.)
