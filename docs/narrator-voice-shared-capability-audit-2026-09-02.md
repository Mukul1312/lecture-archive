# Narrator Voice shared-capability audit — 2026-09-02

**Status:** Recorded evidence for [ADR-0008](decisions/0008-lane-b-production-boundaries.md)
and proposed [ADR-0009](decisions/0009-share-narration-mechanics-not-policy.md)

**Question:** What can the authorized SSGGSM/Odia production workflow safely reuse
from this whole repository, and what must remain lane-specific or historical?

## 1. Classification rule

“Useful” is not the same as “safe to import.” This audit uses four classifications:

| Classification | Meaning |
|---|---|
| **Conditional direct lift** | Cohesive, provider/policy-neutral code can move as code, but only after its governing ADR and verification conditions are satisfied. |
| **Extract after characterization** | A proven mechanic exists inside an active workflow; first pin its behaviour with tests, then move only the neutral part. |
| **Design precedent only** | The interaction or algorithm is useful, but the current implementation carries hard-coded paths, browser-only state, import-time work or historical policy. Reimplement it behind new ports/use cases. |
| **Do not reuse for Lane B** | Its purpose conflicts with authorized faithful SSGGSM/Odia production or it belongs to an unrelated model/language workflow. Preserve it as history; dissimilarity material remains Lane-A evidence. |

The distinction also prevents two common mistakes: treating 656 tests for a shelved
model as evidence of a live integration, and treating a polished static review page
as a durable review system.

## 2. Capability inventory

| Capability | Concrete evidence | Classification and safe use |
|---|---|---|
| Canonical serialization, content digests and opaque IDs | `src/heritage_production/domain/shared/canonical.py`, `digests.py`, `ids.py`; ADR-0001 §§2–3. | **Conditional direct lift.** Lift only the trimmed, import-verified kernel if ADR-0001 is accepted. Preserve its exclusions (`trust.py`, the credential block in `refs.py`, `AggregateEventRecorder`). Never import the shelved package in place. |
| Immutable artifact identity and safe relative paths | `scripts/ggsm_transcription/store.py:70–77, 413–439, 455–476, 596–616`; `scripts/ggsm_transcription/review.py:53–70`; `scripts/youtube_enhance/manifest.py:87–156`. | **Extract after characterization.** Share hashes, artifact facts and containment checks; lane policy supplies eligibility. |
| OS locks, monotonic revision and atomic manifest replacement | `scripts/ggsm_transcription/store.py:103–173`; `scripts/youtube_enhance/workflow_state.py`. | **Extract after characterization.** These are observed implementation precedents to pin with tests. Expected-revision/CAS is a new Lane-B requirement, not proven by these files. Do not couple a narration repository to either existing job aggregate. |
| Typed workflow and review evidence | `scripts/ggsm_transcription/review.py:110–186, 287–419, 499–615`; `scripts/youtube_enhance/manifest.py:75–102`. | **Pattern plus narrow helpers.** Lane B draws its own aggregate; do not reuse either state machine wholesale. |
| Media probing/inspection and signal diagnostics | `scripts/ggsm_transcription/intake.py:49–70`; `scripts/youtube_enhance/gates.py:253–325`. | **Extract after characterization.** Put characterized inspection behind a provider-neutral media port; warnings never approve Odia speech. Full output-WAV decode/format-contract validation is new Lane-B work, not existing extraction evidence. |
| Ordered trim/concatenate | `scripts/hi/reconcat_diary.py:23–37, 55–64`. | **Design precedent first.** Extract only tested boundary-trim/join mechanics. Manifest order is authoritative, never timestamp, filename or similarity rank. |
| Master-first and passage/take audition | `scripts/build_narration_gallery.py`; `scripts/assemble_diary.py`; the prior [legacy audit](narrator-voice-legacy-reuse-audit-2026-09-02.md). | **Design precedent only.** Keep the user journey; drive it with server-side use cases and durable actor-attributed decisions. |
| Native-Odia listening questions | `scripts/build_odia_check_site.py:188–212, 231–266`. | **Design precedent only.** Adapt exact-text, pronunciation and naturalness questions; qualified/native Odia judgement remains authoritative. |
| Blind A/B mechanics | `scripts/build_odia_check_site.py:119–123, 188–212`. | **Optional design technique.** Use for deliberate take/profile comparisons. Bind the opaque mapping to evidence; operational manifests remain unblinded. |
| Player, keyboard, notes and export interactions | `scripts/hi/build_casting_site.py`, `scripts/build_qa_gallery.py`, `scripts/assemble_diary.py`. | **Design precedent only.** Reimplement against durable commands. Do not carry casting assertions, metric defaults or `localStorage` as truth. |
| Generic signal diagnostics | `scripts/voice_quality.py:33–130`; `scripts/youtube_enhance/gates.py:253–325`. | **Potential neutral advisory capability.** Never make it an automatic Lane-B pronunciation, identity or release gate. |
| TTS transport abstraction | ADR-0006 §2.6; ADR-0007 §2.3. | **Share a port shape, not provider DTOs.** It receives a validated/resolved lane request. Cartesia SDK types remain in Lane-B infrastructure; Lane A chooses its provider later. |
| Cost preflight, retries, idempotency and resumption | The Lane-B v1/v2 production designs. | **Planned Lane-B-local behaviour.** A second consumer may justify sharing low-level retry classification/attempt facts; budget, authorization, identity and eligibility remain lane-owned. |

## 3. Policy that cannot be shared

| Concern | Lane A — future non-SSGGSM EN/HI | Lane B — authorized SSGGSM Odia diary |
|---|---|---|
| Output identity | Must not be SSGGSM; historical dissimilarity baseline remains. | Faithful use of the approved SSGGSM IVC is allowed within its attested scope. |
| Language/content | English/Hindi; concrete narrator/provider and release flow remain future decisions. | Reviewed Odia diary only with `language=or`; not arbitrary text or EN/HI. |
| Authorization | No authority is inherited from Lane B. | Current recorded authorization, exact voice and content scope are required at protected operations. |
| Release authority | Historical donor-similarity plus SSGGSM-dissimilarity baseline, not yet a new approved workflow. | Qualified/native Odia human listening; metrics are advisory only. |
| Provider/model | Undecided. | ADR-0006's approved Cartesia IVC and dated Sonic 3.6 release baseline. |
| Publication/distribution | Undecided. | Not granted by clone authorization or by the production workflow. |

A neutral module therefore receives a lane-resolved request. It must not decide any
cell in this table.

## 4. Code that must not become Lane-B production policy

| Area | Reason |
|---|---|
| `scripts/hi/voice_gate.py`, `scripts/hi/vd_analyze.py`, `docs/voice-dissimilarity-gate-2026-07-20.md` | They intentionally enforce the opposite SSGGSM identity goal. They remain Lane-A evidence. |
| Casting assertions in `scripts/hi/build_casting_site.py` and `build_casting_gallery.py` | They state that the historical voice will not be used and claim non-resemblance. Only interaction ideas are reusable. |
| `scripts/gate_takes.py`, `scripts/hi/funnel_diary.py`, automatic selection in `scripts/assemble_diary.py` | Metrics automatically reject/select takes, conflicting with Lane-B human Odia authority. |
| `scripts/hi/asr_check.py` | Hindi Whisper/CER, fixed paths and back-transcription assumptions do not establish Odia correctness. |
| `scripts/prep_narration.py` | English/IAST preparation and lossy ASCII transliteration for VoxCPM conflict with exact NFC Odia input. |
| `scripts/hi/analyze_diary.py`, `expressive_refs.py`, `score_hi_clones.py` | Their references, thresholds and baselines belong to Hindi-era experiments. |
| `cloud/narrate.py`, `narrate_funnel.py`, `diary_variants.py` and related VoxCPM/LoRA scripts | Different provider/model/reference-transfer architecture; ADR-0006 does not revive it. `cloud/` is also outside ADR-0003's script governance. |
| Publication text in `scripts/build_narration_site.py` | Historical disclosure wording does not supply current publication authority or policy. |

## 5. Refactor and defect warnings

1. `scripts/hi/reconcat_diary.py` and `scripts/hi/funnel_diary.py` initialize
   SpeechBrain and perform data-dependent work at import time. They are not safe
   library modules.
2. `cloud/narrate_funnel.py` has no `main()` guard, performs filesystem/model work at
   import time and imports the locally excluded VoxCPM stack.
3. Loose narration/cloud scripts hard-code worktree or `/workspace` paths, model
   assets, references, thresholds and filenames. A useful algorithm does not make the
   containing script a reusable adapter.
4. `heritage_production` is shelved and is not imported by active flows. Its CLI parses
   commands and returns success without running a production workflow.
5. Do not unfreeze its application/review/release layers. `SHELVED.md` records four
   defects, including the unattached-source `TranscriptEdition` problem; ADR-0001 also
   records the review import-cycle/erased aggregate-boundary defect.
6. The supported test commands deliberately exclude `tests/heritage_production/`.
   Its test volume proves the historical model was exercised, not that it is an active
   Narrator Voice platform.

## 6. Result

The codebase contains strong low-level mechanics and strong review-interaction ideas,
but no existing production workflow should be copied wholesale. The safe direction is:

```text
Lane A policy ─┐
               ├─> already-resolved request ─> neutral mechanics/ports
Lane B policy ─┘
```

For the Lane-B first slice, reuse by **measured extraction**, not by dependency on
historical scripts. Keep a mechanic Lane-B-local until another lane earns a neutral
Narrator Voice helper. ADR-0001 independently governs its conditional one-time trimmed
kernel lift; only a second bounded context can earn later additions to `kernel/` under
ADR-0005. This preserves useful work without allowing identity, language, authorization
or release policy to leak between opposite lanes.
