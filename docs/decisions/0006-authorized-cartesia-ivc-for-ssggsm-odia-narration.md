# ADR-0006 — The authorized Cartesia Instant Voice Clone is the current SSGGSM Odia production voice, with configurable delivery controls.

**Date:** 2026-08-31 · **Status:** **Accepted 2026-08-31** · **Governs:** the Narrator Voice context for SSGGSM Odia diary narration
**Supersedes:** the SSGGSM no-clone constraint in [`handoff-voice-pivot-2026-07-10.md`](../handoff-voice-pivot-2026-07-10.md), and only the speaker/language description of programme 5 in [`2026-08-26-corpus-ledger-domain-design.md`](../superpowers/specs/2026-08-26-corpus-ledger-domain-design.md) §2 · **Superseded by:** [ADR-0007](0007-two-policy-isolated-narration-lanes.md) §2.2, for the preceding Programme-5 speaker/language supersession clause only

Related: [ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) anticipated Narrator
Voice as the second bounded context. This record materialises that context; it does not
join it to the archive rewrite or its [ADR-0004](0004-clean-room-rewrite-with-cutover.md)
deadline.

---

## 1. Context

The July 10 handoff recorded an instruction not to clone GGSM and correctly redirected
the work at that time. On 2026-08-31, the steward stated that he had since received
direct permission from SSGGSM and that the resulting Cartesia Instant Voice Clone had
passed his listening review. Older documents call the same speaker “GGSM”; this record
uses the steward's current name, “SSGGSM”.

This repository contains no consent artifact and this record does not independently
authenticate the permission. It records the steward's attestation and the resulting
project decision. Private evidence must not be placed in this public source repository.

The approved use is narrow: SSGGSM's cloned voice speaking reviewed Odia diary
narration. Permission to clone a voice is not, by itself, permission to publish every
source text, lecture or generated release. Hindi, English, other speakers, arbitrary
scripts and distribution rights remain outside this decision.

The clone was created and auditioned in Cartesia's Playground with Sonic 3.6. The
steward preferred `speed=0.90`, `volume=1.00` and `emotion=calm`, but explicitly asked
that these remain adjustable while production quality is still improving. Playground
generation was useful for approval; it does not provide the repeatable manifests,
resume behaviour, cost preflight or take history required for production.

## 2. Decision

1. **Use the already approved Cartesia Instant Voice Clone as the current production
   baseline for SSGGSM Odia diary narration.** “Current baseline” is not a claim that
   the clone is perfect or final. Native Odia listening review remains authoritative.
2. **Move production control into this codebase.** The Playground remains available for
   voice administration, pronunciation-dictionary maintenance and deliberate
   auditions; routine project generation, review state and assembly belong to a
   code-controlled workflow.
3. **Start every project from one named delivery profile:** `speed=0.90`,
   `volume=1.00`, `emotion=calm`. These are defaults, not locks. A project, passage or
   new take may override them deliberately, including omitting `emotion`; the manifest
   must record both the requested override and the effective request settings.
4. **Set `language=or` explicitly and pin a dated Sonic 3.6 snapshot for release
   takes.** The initial release profile uses `sonic-3.6-2026-08-27`. A moving alias may
   be auditioned as a candidate, but it cannot replace the release snapshot silently.
5. **Keep every take and make review state explicit.** A rejected take is evidence, not a
   file to overwrite. The linked proposed design defines approval, selection and final
   listening gates; those workflow details remain subject to steward review before
   implementation.
6. **Treat Cartesia as an outbound provider, not the domain model.** The Narrator Voice
   context owns passages, delivery profiles, takes, review decisions and masters. A
   Cartesia adapter translates those concepts into provider requests; Cartesia SDK and
   request types do not enter domain or application policy.
7. **Keep private and binary material out of Git.** API credentials, voice identifiers,
   reference audio, generated audio, private run manifests and consent evidence stay in
   an authorized external work area. Versioned source may contain schemas, redacted
   examples and non-sensitive text only, under
   [`external-audio-assets.md`](../external-audio-assets.md).

The implementation design is
[`2026-08-31-cartesia-odia-narration-production-design.md`](../superpowers/specs/2026-08-31-cartesia-odia-narration-production-design.md).
It is proposed for review; this ADR does not itself authorize code or provider calls.

## 3. Evidence

| Observation | Status | Consequence |
|---|---|---|
| The steward attested direct authorization on 2026-08-31 | Steward assertion; not independently verified here | Proceed only within the narrow scope above; retain private evidence outside Git |
| The steward approved the Instant Voice Clone after Playground listening | Human acceptance evidence | IVC is the production baseline; do not restart provider/model selection without a trigger |
| `0.90 / 1.00 / calm` was preferred | Human listening evidence | Use it as the default profile, while retaining recorded overrides |
| [Sonic 3.6](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest) lists Odia (`or`) and Instant Voice Cloning support, and publishes the immutable `sonic-3.6-2026-08-27` snapshot | Provider documentation checked 2026-08-31 | The chosen model/language combination is supported and can be pinned |
| Cartesia says speed and volume are request-scoped guidance, not strict transforms; its [emotion documentation](https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion) labels emotion beta and says emotion tags are supported only for English | Provider limitation | `calm` in Odia is an empirical preference, not a guaranteed capability; every changed passage still needs listening review |
| Cartesia's [Instant Voice Clone guide](https://docs.cartesia.ai/build-with-cartesia/capability-guides/clone-voices) recommends target-language, clean, tightly trimmed speech and says Sonic 3.6 can use up to 60 seconds | Provider guidance plus completed clone | Preserve the approved clone; do not repeatedly rebuild it from arbitrary lecture excerpts |
| On 2026-08-31, [pricing](https://www.cartesia.ai/pricing) lists Pro at $5/month with Instant Voice Cloning and about 133 Sonic 3.6 minutes, and Startup at $49/month with Professional Voice Cloning | Time-sensitive provider pricing | Hosted generation remains metered after clone creation; capture cost assumptions by date rather than treating them as architecture |

The evidence against overconfidence is material: Cartesia does not guarantee that an
emotion hint will control Odia, a dated snapshot controls model drift but does not make
generative output byte-identical, and the approval so far is the steward's listening
judgement rather than a native-speaker panel or a formal identity score.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| **Keep producing in the Playground** | It hides effective per-take history, makes resumption manual, and makes ordered review/assembly and cost preflight difficult. It remains useful for administration and auditioning. |
| **Create a Cartesia Professional Voice Clone now** | The approved IVC already clears the current gate. PVC needs at least 30 minutes of suitable audio and a Startup plan, and it learns pacing/loudness from the dataset rather than honoring request-time speed/volume controls. PVC remains a separate evidence-led upgrade, not a prerequisite. |
| **Switch to an open-source model now** | It reopens model selection after the hosted IVC has been approved and adds GPU, deployment and Odia-validation work before any production diary is delivered. Provider isolation keeps this option available later. |
| **Lock `0.90 / 1.00 / calm` globally** | The steward explicitly kept them adjustable, and Cartesia treats the values as guidance whose effect can vary by text. |
| **Continue obeying the July no-clone constraint** | That constraint was valid under the instruction then recorded. The steward's later direct-authorization attestation and clone approval supersede it for this specific scope. |

## 5. Consequences

- Clone creation is not ownership of a local TTS model. Future speech is still generated
  by Cartesia and consumes the account's subscription/credits; already exported audio
  remains a separate artifact.
- Reproducibility now requires metadata: approved text digest, language, voice reference,
  model snapshot, API version, pronunciation-dictionary identity and content digest,
  effective controls, take identity, provider request identity when available, and audio
  digest.
- The provider boundary creates some implementation work, but prevents Cartesia request
  shapes from defining the domain and leaves an open-source or future PVC adapter possible.
- Per-passage overrides improve quality but create variants. Immutable take IDs and an
  explicitly recorded selection are therefore required; filenames alone are not state.
  Whether selection requires a formal approval gate remains part of the proposed design.
- `calm` remains a reviewable hint. A successful prior take does not prove that it will
  improve every Odia passage.
- Authorization scope and content/distribution rights remain separate checks. If the
  authorization changes, future generation and unpublished release work stop while the
  steward resolves the new scope.
- The Narrator Voice production track is independent of ADR-0004's archive rewrite. It
  does not consume or extend that rewrite's 35-day box.

## 6. Revisit trigger

Write a superseding ADR if any one of these occurs:

- the steward reports that authorization was withdrawn or narrowed;
- Cartesia removes Odia/IVC support from the pinned production route, or the pinned route
  cannot be used for the approved voice;
- a passage still cannot receive native-Odia approval after pronunciation/text correction
  and three preserved takes under deliberately chosen profiles;
- a Cartesia PVC or open-source candidate wins a recorded blind listening comparison on
  identity, Odia pronunciation and devotional delivery, and its operating cost is accepted;
- provider pricing or availability exceeds the project budget recorded in the production
  manifest.

## 7. What this record does not decide

It does not decide PVC training data, purchase of the Startup plan, an open-source model,
exact passage boundaries, inter-passage silence, UI work, automated publication,
synthetic-voice disclosure wording, or commercial distribution. It does not authorize
other speakers, arbitrary scripts, Hindi/English output, public sharing of the cloned
voice, or upload of the lecture corpus. It does not change ADR-0001, ADR-0003, ADR-0004
or ADR-0005, and it does not revive the shelved VoxCPM/LoRA pipeline.
