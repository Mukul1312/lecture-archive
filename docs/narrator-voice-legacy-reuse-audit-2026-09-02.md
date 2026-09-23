# Narrator Voice legacy-script reuse audit — 2026-09-02

**Status:** Recorded input to ADR-0007, the
[codebase-wide shared-capability audit](narrator-voice-shared-capability-audit-2026-09-02.md)
and the accepted [Lane-B boundary decision](decisions/0008-lane-b-production-boundaries.md)

**Question:** Which existing English/Hindi-era narration capabilities can safely help
the authorized SSGGSM/Odia/diary lane without importing the old voice policy?

## Decision rule

The repository contains useful production ideas, but most loose narration scripts are
research one-offs with hard-coded paths, models and policies. Reuse a demonstrated
technical capability only after extracting it behind the new lane-specific application
policy. Do not treat a script's existence, filename or former “live” status as release
authority.

## Reuse in the new workflow

| Existing capability | Evidence | Safe reuse |
|---|---|---|
| Native-language listening | `scripts/build_odia_check_site.py` asks an Odia listener to judge intelligibility and naturalness. | Make exact-text, pronunciation and naturalness review by a qualified Odia listener the release authority. Adapt the questions to generated narration. |
| Master-first and passage-level audition | `scripts/build_narration_gallery.py` and `scripts/assemble_diary.py` present a whole track plus individual chunks/takes and notes. | Preserve this reviewer journey: listen to the master, inspect a passage, compare preserved alternatives, record a decision and comment. Build a new adapter rather than using their old state model. |
| Careful ordered joining | `scripts/hi/reconcat_diary.py` trims only boundary silence and inserts a fixed gap. | Extract separately tested trim/normalise/assemble operations. Order comes from the manifest, not timestamps or similarity scores. |
| Blind A/B mechanics | `scripts/build_odia_check_site.py` uses opaque randomized slots and retains an answer key. | Use only for deliberate comparisons of two takes/profiles. Durable take IDs and review evidence remain unblinded in the manifest. |
| Audio diagnostics | `scripts/voice_quality.py` calculates generic signal features and documents limitations. | Show advisory diagnostics if useful; never promote them to an automatic Odia release gate. |
| Review-page interaction | `scripts/hi/build_casting_site.py`, `scripts/build_qa_gallery.py` and `scripts/assemble_diary.py` contain player, keyboard, notes and export patterns. | Reimplement/refactor the interaction against the new review commands and durable manifest. Do not reuse their casting claims, metric defaults or browser-local state as domain truth. |

## Do not reuse as Odia production policy

| Legacy area | Why it must not cross into Lane B |
|---|---|
| `scripts/hi/voice_gate.py`, `scripts/hi/vd_analyze.py`, `research/docs/voice-cloning/voice-dissimilarity-gate-2026-07-20.md` | They intentionally enforce the old opposite goal: output must be dissimilar from SSGGSM. That remains relevant to Lane A only. |
| `scripts/hi/build_casting_site.py`, `scripts/hi/build_casting_gallery.py` casting assertions | They state that the historical voice will not be used and candidates were screened for dissimilarity. UI ideas are reusable; those assertions and verdicts are not. |
| `scripts/gate_takes.py`, `scripts/assemble_diary.py` automatic identity/calmness selection | They let metrics reject or select speech. ADR-0006 makes qualified Odia listening authoritative for Lane B. |
| `scripts/hi/asr_check.py` | It runs Hindi Whisper/CER against Hindi passages and fixed paths. It is not an Odia correctness gate. |
| `scripts/hi/analyze_diary.py`, `scripts/hi/expressive_refs.py`, `scripts/hi/score_hi_clones.py` | Their baselines, reference selection and thresholds are Hindi/historical-speaker experiments, not the approved Cartesia workflow. |
| `scripts/prep_narration.py` | It contains English diary preparation and lossy IAST-to-ASCII transliteration for a VoxCPM chunk limit, not NFC Odia input. |
| `cloud/narrate.py`, `cloud/narrate_funnel.py`, `scripts/hi/clone_test.py` and related VoxCPM/LoRA scripts | They generate with a different model, reference-transfer design and historic policy. ADR-0006 expressly does not revive the shelved VoxCPM/LoRA pipeline. |
| `scripts/build_narration_site.py` publication text | Its historical “AI reconstruction” wording and release page do not supply the publication/disclosure authorization that ADR-0006 leaves undecided. |

## Required seam before reuse

The first Odia implementation should expose provider-neutral ports for synthesis,
artifact storage, media inspection/assembly and review presentation. Lane-specific
application policy supplies the authorization binding, speaker, language, permitted
text scope and release rules before any adapter is called.

This keeps the valuable old ideas—human listening, compare-and-comment review,
immutable alternatives and careful assembly—while preventing four kinds of leakage:

1. non-SSGGSM dissimilarity policy;
2. Hindi/English text and ASR assumptions;
3. VoxCPM/LoRA provider and reference-audio assumptions; and
4. metric-driven release decisions.

The audit does not authorize deletion or rewriting of historical code. The `scripts/`
entries remain evidence and runnable research history under ADR-0003. That ADR
explicitly excludes `cloud/`; the two audited `cloud/` narrators remain ungoverned
historical evidence and are not authorized for either new production lane.

Legacy player, keyboard and compare patterns may inform the localhost operator UI.
They do not supply its persistence or identity model: every durable command is handled
server-side with a stable `ActorId`. The publishing-stage reviewer portal is a separate
authenticated adapter and must not inherit browser `localStorage` as authority.
