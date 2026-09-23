# Lecture Archive Research

The measured research behind this archive's transcription, Odia and audio-enhancement work.
Each topic states its answer first, then the evidence. Where a later measurement overturned an
earlier claim, both are kept and the correction is marked — nothing is quietly deleted.

| Topic | Question | Answer | As of |
| --- | --- | --- | --- |
| [Transcription](transcription/index.md) | Which system should transcribe ~3,766 lectures, and what will correcting them cost? | **ElevenLabs Scribe v2** makes 26% fewer corrections than local Whisper. Combining three systems loses the fewest words. The spend decision is open. | 2026-09-23 |
| [Odia](odia/index.md) | Can 1,952 hours of Odia be transcribed *and* translated affordably, and audited without listening to all of it? | Yes — on the laptop, not AWS. Two engines, Azure plus ElevenLabs Scribe. Three claims of the first design were overturned by measurement. | 2026-08-28 |
| [Audio enhancement](enhancement/index.md) | How far can a noisy seminar recording be cleaned without damaging the voice? | Subtractive first; naturalness beats noise removal. DeepFilterNet3's ceiling is now quantified, and the claim that the loss is structurally unavoidable was refuted. | 2026-08-31 |
| [Voice cloning](voice-cloning/index.md) | Can Gour Govinda Swami's English voice be cloned well enough to narrate? | **History.** Superseded on 2026-07-10: narration now uses a different voice. The measurements remain useful. | 2026-07-20 |
| [Hindi clone](hindi/index.md) | Can the English clone be extended to Hindi? | **History.** Same supersession. The extraction and review work stands on its own. | 2026-07-24 |

## How to read these notes

- **The answer comes first.** Every topic index says what was decided and what is still open
  before it says how the work was done.
- **Measurements beat reputation.** Public benchmarks have mispredicted this corpus three times
  out of three. Nothing here is adopted because it ranks well elsewhere.
- **Corrections are kept beside the claim.** Several documents carry a banner pointing at a later
  one that overturns part of them. Read both.
- **Dated filenames are deliberate.** A file named `…-2026-09-23.md` is a record of what was known
  that day, not a living page.

## What is not here

Handoffs, architecture decision records, the AWS evaluation and the implementation plans stay in
the repository's `docs/` folder, because they are project state rather than research. Narration
research lives in the separate `narrator-voice` repository under ADR-0013.

## Viewing this site

```powershell
cd research
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m mkdocs serve
```

Then open <http://127.0.0.1:8000>. Every page also reads fine on its own in VS Code or on GitHub.
