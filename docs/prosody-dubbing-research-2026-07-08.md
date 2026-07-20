# Prosody / emphasis for EN→Hindi dubbing in his voice — research synthesis (2026-07-08)

From 4 firecrawl research agents (prosody-preserving S2ST systems · EN→HI + Indic TTS · cross-lingual prosody
mechanics & limits · DIY pipeline + commercial tools) + the VoxCPM2 markup research. Companion to
[voxcpm2-markup-research-2026-07-08.md](voxcpm2-markup-research-2026-07-08.md),
[lora-finetune-research-2026-07-07.md](lora-finetune-research-2026-07-07.md).

## THE headline finding (reframes the goal)
**"Carry his English emphasis into Hindi" is the wrong target — English and Hindi encode emphasis with
OPPOSITE cues.**
- **English** marks focus by **raising pitch ON the focused word** (a pitch accent).
- **Hindi** marks focus mainly by **post-focal pitch COMPRESSION — lowering the register *after* the focused
  word** — plus **word order** (SOV + free scrambling) and **particles (ही / तो)**. (Patil et al. 2008; Kügler 2020.)

So copying his English pitch-spike onto the "aligned" Hindi word is the **wrong cue in the wrong place** — a
Hindi listener may not even perceive the intended focus. This is a **typological reality, not a tooling gap.**
Hard evidence: even **EN→Spanish** (a *related* pair) scores only **14% F1** on placing emphasis on the correct
word (SeamlessM4T on EmphAssess); EN→Hindi (heavier reordering) is worse, and benchmarks had to *discard*
sentences where the emphasized word didn't align 1:1 — exactly what Hindi reordering destroys.

**Corollary:** his **English performance is a poor template for his Hindi delivery.** The right sources are
(a) his **real Hindi lectures** (his authentic Hindi focus/cadence → LoRA) and (b) the **meaning** (which points
to emphasize, authored the *Hindi* way).

## What transfers EN→HI vs not
| Transferable ✅ | Not transferable ❌ |
|---|---|
| Overall emotion / style (global embeddings) | Frame-level F0-contour copying |
| Duration / pause / rate (isochrony) — most language-agnostic | Word-level pitch-emphasis copying (wrong cue for Hindi) |

## The tooling landscape (and the gap)
| Model | Hindi | Emphasis control | Clone arbitrary voice | License |
|---|---|---|---|---|
| **CosyVoice2** | ❌ (ZH/EN/JA/KO) | ✅ `<strong>word</strong>` + instructions | ✅ | open |
| **VoxCPM2** (ours) | ✅ (weak, #288) | ⚠️ punctuation → pauses only | ✅ | Apache-2.0 |
| **IndicF5** (AI4Bharat) | ✅ native, near-human | ⚠️ reference-prosody only | ✅ | **MIT** |
| **Indic Parler-TTS** | ✅ | ✅ NL description (global, not per-word) | ❌ (preset voices) | Apache-2.0 |
| **Sarvam Bulbul v3** | ✅ best commercial | auto (LLM-inferred) | ✅ (enterprise-gated) | closed API |
**The gap:** *no open Hindi TTS has CosyVoice2-grade per-word emphasis markup.* CosyVoice2 has the knob but no
Hindi; VoxCPM2/IndicF5 have Hindi but no tag.

## No turnkey EN→HI + his-voice + his-emphasis system exists
SeamlessExpressive / Hibiki / UniSS (the expressive+clone systems) **do not support Hindi.** SeamlessM4T v2
covers Hindi but preserves neither voice nor emphasis. StressTransfer (the one emphasis-preserving S2ST) is
EN→Chinese only. **The blueprint everyone converges on:** LLM translation that emits emphasis tags → duration
control → a controllable cloning-TTS (StressTransfer/TransVIP pattern) — but it needs a controllable *Hindi*
cloning-TTS, which doesn't exist open.

## Recommended plan (feasibility-ranked)

**A. Benchmark now (cheap, high-info) — ElevenLabs Dubbing v2.** Run 1–2 of his English clips through it →
hear the commercial ceiling for EN→Hindi dubbing *in his cloned voice with delivery preserved* (~$11–22/mo,
non-commercial-OK). It's the fastest way to know if "just use ElevenLabs" is viable, and it's an **oracle** for
where emphasis naturally lands in Hindi. Caveats: it clones from the *English* clip (accent-leak risk), coarse
control, replaces our stack, and may itself hit the EN→HI emphasis problem — which is *why* we test one clip.

**B. Build the correct DIY path on our stack (most control, most linguistically sound).** Re-frame the service:
translate the **meaning + which points to emphasize** → an **LLM authors the Hindi with Hindi-native focus**
(particles ही/तो, word order, expressive structure, punctuation) → render in our Hindi clone. This realizes
emphasis the *correct Hindi way* instead of copying English pitch. Optional emphasis-detection from his English
clip (WhisperX + parselmouth) only as a *hint* to the LLM about which ideas he stressed — not as a pitch source.

**C. His authentic Hindi delivery → LoRA on his HINDI lectures.** This is the only route to *his* Hindi
cadence/focus (learned from how HE speaks Hindi, not translated from English). The lecture 2–4 review feeds it.
Combine with B's authored emphasis + the clone's timbre.

**D. (Optional) Probe IndicF5** (MIT, native-Hindi, near-human) as a possibly-better Hindi base than VoxCPM2's
weak Hindi — same reference-clone paradigm, likely cleaner Hindi.

**De-prioritize:** naive English→Hindi prosody/emphasis *transfer* (linguistically wrong); CosyVoice2 (no Hindi).

## Bottom line
The service isn't "replay his English performance in Hindi" — it's **"say the same meaning, with the right
points emphasized, in his Hindi voice and his Hindi delivery."** That's: authored Hindi-native emphasis (LLM) +
his voice (clone) + his Hindi style (LoRA on his Hindi lectures). Benchmark the commercial ceiling with one
ElevenLabs clip to calibrate expectations.

---

## ADDENDUM — /deep-research workflow (wlnd1n6dk, 101 agents, 25 claims adversarially verified 3-0, 0 refuted)

The second research stream (all-primary sources: HF cards + ACL/Interspeech/NeurIPS/ICASSP papers) **agrees on
the blueprint but ranks the models differently.** Reconciled below.

### The one genuine tension: CosyVoice2
- deep-research ranks **CosyVoice2 fine-tuned on Hindi as its #1 try** — because it is the **only** open system
  that unites zero-shot arbitrary-speaker cloning **with a real per-word emphasis knob**: inline
  `<strong>word</strong>` (CosyVoice2 paper arXiv 2412.10117, trained on 1500h instructed data) + NL instruction
  control (emotion/speed/volume via `<|endofprompt|>`).
- **StressTransfer (arXiv 2510.13194, Oct 2025)** is the exact-shape precedent: an LLM emits target-language text
  with Markdown `**word**` emphasis → converted to CosyVoice2 `<strong>` → emphasis **preserved across
  translation** (demonstrated EN→**Chinese**, off-the-shelf, no FT).
- **My honest calibration (why I still don't rank it #1):** CosyVoice2 has **zero Hindi** in training (9 langs;
  CosyVoice3 Dec-2025 adds none). Teaching a model a **new language + script** from 15–60 min is **not** a
  speaker-LoRA — it's out-of-distribution language acquisition; phonetics/pronunciation will likely be the
  failure point. The workflow itself flags this as its **"UNVERIFIED KEYSTONE"**: neither post-FT Hindi quality
  nor `<strong>`-tag survival is demonstrated — *"validate with a small pilot before committing."* So CosyVoice2
  is a **pilot candidate, not a commitment.**

### The reconciliation that matters (English source: contour ✗, placement ✓)
Finding 9 (arXiv 2207.01718): deciding **WHERE** meaningful (contrastive-focus) emphasis goes **cannot be
inferred from text alone** — a fine-tuned BERT scored only **0.07–0.24 recall** on contrastive focus. So:
- ❌ **English pitch CONTOUR** → don't transfer (wrong cue for Hindi — the headline finding above).
- ✅ **English emphasis PLACEMENT** (which idea/word he stressed) → **DO extract** from the source lecture (his
  stress is audible there) and feed it to the LLM as a **hint**, since Hindi text alone can't predict it.
- The LLM then realizes that placement the **Hindi-native way** (particles ही/तो, word order), and a
  controllable TTS renders it. → *This unifies both streams: source audio for **where**, Hindi linguistics for **how**.*
- Building block: **`emphases`** — MIT, pip-installable module for automatic word-level prominence estimation
  from audio (arXiv 2310.08464) → extract his English emphasis map.

### Data-efficiency finding for the eventual LoRA (Finding 10, arXiv 2603.10904)
**MIXED multi-speaker FT beats pure single-speaker FT** — 11–22% of per-speaker data reaches within 7–9%
speaker-similarity; **pure FT on small homogeneous data can DEGRADE quality.** → When we LoRA his voice, train
it **alongside other Hindi speakers**, not on his ~15 min alone. (Caveat: this is measured for *timbre*;
learning his *prosodic delivery* from limited data is still unquantified.)

### Updated model table (merges both streams)
| Model | Hindi | Per-word emphasis knob | Clone arbitrary voice | License | Verdict |
|---|---|---|---|---|---|
| **CosyVoice2** | ❌ (must FT — risky) | ✅ `<strong>` (real) | ✅ | open (terms unverified) | pilot candidate |
| **IndicF5** | ✅ native, near-human | ❌ (ref-prosody only) | ✅ | (terms unverified) | best native-Hindi base |
| **Higgs Audio v3** (NEW) | likely (102 langs) | ✅ inline prosody/pauses | ✅ | **research-only** (ok for seva) | **worth a probe — possible both-in-one** |
| **Fish Audio S2 Pro** (NEW) | ⚠️ unconfirmed (80+) | ✅ inline `[excited]`… | ✅ | paid commercial | probe only if Hindi confirmed |
| **VoxCPM2** (ours) | ✅ (weak) | ❌ (pauses only) | ✅ | Apache-2.0 | works today, baseline |
| **Indic Parler-TTS** | ✅ | ⚠️ global NL desc, not per-word | ❌ (69 preset voices) | Apache-2.0 | disqualified (no clone) |
| **Sarvam Bulbul v3** | ✅ best commercial | auto-inferred, no user control; **no SSML** | ✅ (enterprise-gated) | closed API, paid | disqualified (gated + no control) |
| **ControlSpeech** (ACL'25) | ❌ (EN only) | ⚠️ global style, not per-word | ✅ | open | design pattern only |

### Custom "word-level control layer" research path (option 3, highest effort/ceiling)
Proven mechanisms if we ever build our own emphasis knob: **WeSCon** (NeurIPS'25, word-level emotion+rate on a
**CosyVoice2 backbone**, data-light self-training) · **EME-TTS** (Interspeech'25, variance-injection with a
`strength` param) · **Apple latent-scaling** (arXiv 2110.03012) · **quantized prominence** (Stephenson,
arXiv 2207.01718). All English/general — would need Hindi adaptation.

### Net recommendation (reconciled) — pilot-first funnel
Both streams end on *"pilot before committing."* The blueprint is settled; only **which TTS renders it** is open.
So: **one sentence we KNOW how he'd emphasize → render across candidates → judge by ear (identity + does the
emphasis land in the right Hindi place):**
1. **ElevenLabs Dubbing v2** — commercial ceiling / oracle (~$11).
2. **Higgs Audio v3** — the NEW hope: might already have Hindi **and** inline emphasis in one open model.
3. **IndicF5** — best native-Hindi base (emphasis via authored text + emphatic ref).
4. **VoxCPM2 (ours)** — today's baseline.
- Defer CosyVoice2-Hindi-FT and any LoRA until the pilot shows which base is worth the investment; when we do
  LoRA, use **mixed-corpus** (Finding 10).

### Two user-supplied sources (2026-07-09) — what they add
**Fast-VGAN** (Abrassart/Obin/Roebel, IRCAM, Interspeech 2025 — arXiv 2507.04817). A lightweight (3.2M-param)
GAN **voice-conversion** model with **explicit, continuous curve-based prosody control** (supply F0 contour +
phoneme durations + intensity directly; also "dynamic prosody transfer" = copy F0/duration curves off an
expressive reference). It sits at the far *explicit* end of our taxonomy. **Not usable for us as-is:** English
only, **any-to-many (needs the speaker in training) — not zero-shot arbitrary cloning**, and **no word-level
emphasis tags** (curves only). **The useful takeaway is a CAUTION:** they *hypothesized* that manipulating
prosody would strengthen identity but found the opposite — *"When both ambitus and dilation are applied
simultaneously, we observe a drop in both naturalness and similarity,"* and extreme prosodic edits degrade
quality (MOS peaks at neutral). → Independent, *quality-side* confirmation of our instinct: **forcing prosody/
pitch manipulation costs identity + naturalness** — don't over-push it (complements the cross-lingual
*wrong-cue* argument with a *quality* argument).

**Shukla, "The Persistent Challenge of Prosody Modeling…"** (Medium, Aug 2025 — a survey). Cleanest framing of
*why plain-text TTS can't recover his delivery*: the **text-centric bottleneck** — an ASR→LLM→TTS pipeline (or
just feeding plain Hindi text to a TTS) routes speech through text, and *"the complete paralinguistic
information from the input speech is lost."* His delivery was never *in* the Hindi text → this is exactly our
problem, named. Two **new word-level control mechanisms** to add to our toolbox (alongside CosyVoice2
`<strong>`, WeSCon, EME-TTS, Apple latent-scaling):
- **PROSODYLM** — explicit **per-word prosody tokens** (F0/duration/energy as 5-dim vectors per word).
- **DrawSpeech** — **"prosody sketches"**: graphical *per-word* pitch/energy specification ("precise,
  fine-grained, word-level control"); also **ProsodyFlow** (conditional flow-matching) and the SpeechLM
  direction (encode waveform→speech tokens to skip the text bottleneck).
It also names **our exact blocker as a field-wide open problem:** *"data scarcity for aligned speech input and
output in source and target languages with matching speakers impedes speech-to-speech translation"* — i.e. why
no turnkey EN→HI-same-speaker-expressive system exists. **No Hindi-specific content.**

**Net effect on the plan:** unchanged direction, two reinforcements — (a) *don't over-force prosody* (Fast-VGAN
quality caution), (b) the **text-centric bottleneck** is the crisp "why" behind everything (delivery must be
*added back* via markup/LoRA/source-emphasis, because plain text can't carry it). PROSODYLM/DrawSpeech join the
"custom word-level control layer" research path (option 3), still highest-effort and English-first.
