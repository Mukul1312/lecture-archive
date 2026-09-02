# ADR-0011 — Diary episodes compose fixed-voice narration masters without becoming a mixed-voice job

**Date:** 2026-09-02 · **Status:** **Accepted 2026-09-02** · **Governs:**
the narrow Lane-C Odia diary-episode intro and episode-composition boundary in Narrator
Voice
**Supersedes:** only ADR-0007 §2 decision 1's two-lane closure and its
“Anything else” row, solely to admit the Lane C defined here · **Superseded by:** —

Related: [ADR-0006](0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md)
keeps the approved SSGGSM clone scope narrow;
[ADR-0007](0007-two-policy-isolated-narration-lanes.md) isolates narration policy;
and [ADR-0008](0008-lane-b-production-boundaries.md) fixes the Lane-B production
aggregate and its release-contract invariants. The complete accepted workflow is in
the [v3 production design](../superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md).

---

## 1. Context

The production workflow now needs a short spoken intro before an Odia diary narration.
The intro is to use one existing Cartesia voice that is distinct from the authorized
SSGGSM voice used by Lane B. A common provider does not make the speakers, voice-use
authority, release contract, or review policy interchangeable.

Lane B deliberately fixes a job to its authorized SSGGSM voice, Odia language and
dated release contract. In particular, ADR-0008 `INV-NJ-8` forbids changing a job's
lane, speaker, voice, language or release-contract identity in place. Adding an intro
as a different-voice passage to the diary `NarrationJob` would therefore make the
aggregate contradict its own evidence and blur the authorization boundary.

ADR-0007 originally allowed Lane A and Lane B only, with all other work blocked
pending a decision. That conservatism is still correct for arbitrary narration. It is
too broad, however, for the now-defined, reviewed Odia diary-episode intro. The new
scope must be an exception with an equally explicit contract, not a generic Cartesia
TTS capability.

An episode also needs a durable way to order the independently produced intro and
diary masters, preserve dry assembled speech, and later carry timing data useful for
text display. Background audio, subtitles and video have different assets, rights,
rendering and review concerns. Bringing them into the narration production model now
would weaken the reproducible speech boundary before there is a presentation workflow
to prove the correct model.

## 2. Decision

1. **Add Lane C — reviewed Odia diary-episode intros — and no broader scope.** Lane C
   may generate a reviewed intro solely for an Odia diary episode, using one separately
   fixed Cartesia voice and an authority binding that covers that voice, the intro text
   scope, generation and one intended `DiaryEpisodeId`. It is not Lane B, does not inherit
   SSGGSM clone authorization, and is not an arbitrary-script or generic
   `say --voice --text` service. A different Lane-C voice, language, text scope,
   provider class, or use beyond a diary episode requires another decision and a new
   fixed contract. A dated model/API change always creates another contract and must
   follow accepted upgrade evidence; it never mutates the existing job.

2. **Keep narration jobs single-voice and fixed-contract.** A Lane-C intro and its
   Lane-B diary narration are separate `NarrationJob` aggregate roots. Each owns its
   own ordered passages, takes, review/selection history, authorization snapshot and
   immutable narration master under its own fixed release contract. A Lane-C contract
   binds the one approved intro voice, its authority reference and its one intended
   `DiaryEpisodeId`; a Lane-B contract
   retains the SSGGSM voice binding required by ADR-0006 through ADR-0008. Neither job
   can substitute, borrow, or change the other's voice in place. `INV-NJ-8` remains
   fully in force.

3. **Introduce `DiaryEpisode` as the composition aggregate, not as a multi-voice
   narration job.** It owns an ordered list of immutable `NarrationMasterSnapshot`
   values, each issued by a source `NarrationJob` root; the role for each snapshot
   (`intro` or `diary`); explicit order; and an explicit inter-role gap. A snapshot is
   a value object containing, at minimum, the issuing JobId and MasterId, source
   contract/lane/episode-role identity, master artifact digest and media facts, source
   text/segment identity, inter-passage gaps and sample-accurate passage offsets needed
   for timing, its passing operational whole-master listening decision, and its
   issuance revision/time. It is evidence of what
   the job root issued, not a mutable reference to a file supplied by the browser.

   A new episode begins in `draft` and may temporarily contain neither or only one
   component while the operator attaches them. It becomes `configured` only with
   exactly one Lane-C `intro` followed by one Lane-B `diary`; only a configured episode
   may reserve assembly. No repeated intro, mixed language, additional speaker or
   arbitrary segment role is implied. Creating, replacing or reordering a role creates
   a new episode revision while retaining historical snapshots and episode masters.

4. **Application handlers orchestrate cross-root checks.** At attach and assembly
   time, an application use case loads the relevant narration jobs, checks their
   current contract/review/authorization eligibility, requires a passing operational
   whole-master listening decision, asks their roots to issue the
   immutable snapshots, and then loads and changes `DiaryEpisode` under its expected
   revision. Lane-C snapshot issuance and attachment also require the contract's
   intended `DiaryEpisodeId` to equal the receiving episode. `DiaryEpisode` does not
   decide source-job eligibility and does not update
   a narration job. Before an episode master is assembled or delivered, handlers
   re-check each source job's current eligibility and current authorization; a later
   withdrawal or scope failure blocks protected work without rewriting history.

   There is no `Master` repository, no cross-aggregate master promotion and no second
   source of truth. Narration masters remain children/history of their issuing job
   roots. `DiaryEpisodeRepository` persists episode state only; job repositories
   remain the only repositories that load/save narration jobs.

5. **The episode produces a dry `EpisodeSpeechMaster`.** It is an immutable assembly
   of the exact selected canonical speech PCM from the accepted snapshots, in explicit
   role/order with only the recorded gap. It records its artifact digest, duration,
   component snapshot identities and gap settings, and it never mutates either source
   narration master. `DiaryEpisode` also owns append-only, actor-attributed
   episode-listening decisions against the exact `EpisodeSpeechMaster`.

6. **`DiaryEpisode` owns versioned `TimedNarrationPackage` values as narration
   metadata, not video output.** A package ties exact source text and episode offsets
   to the `EpisodeSpeechMaster` and records segment/sentence cues plus any word cues.
   Each cue records timing provenance: its source type (provider timing, alignment,
   manual correction, or derived offset), source/tool and version where applicable,
   input artifact/text digests, and validation outcome. Packages are immutable and
   versioned; corrections create a new package rather than editing old timing evidence.

   Validation must prove that cues are monotonic and non-overlapping within their
   stream, lie within the referenced component/episode duration, reference exact NFC
   source text, and preserve the declared role/order. If word timing is unavailable,
   fails validation, or is not trustworthy, the package falls back explicitly to
   validated sentence or passage-level cues. It must never invent word-synchronous
   highlighting from unverified timing. Word-level timing is not required to create or
   listen to an `EpisodeSpeechMaster`.

7. **Background/music, subtitle rendering and video remain a future Presentation
   context.** That future context may consume immutable `EpisodeSpeechMaster` and
   `TimedNarrationPackage` artifacts to create separately identified derived audio or
   video outputs. It will decide asset licensing, mixing/ducking, subtitle styling and
   rendering, visual review and release requirements when there is a real presentation
   use case. No presentation aggregate, renderer, media-mixing pipeline, subtitle
   service, or code scaffold is introduced by this decision.

## 3. Evidence

| Observation | Status | Consequence |
|---|---|---|
| ADR-0006 authorizes one approved SSGGSM clone only for reviewed Odia diary narration, and keeps the provider outside the domain model. | Accepted scope and boundary. | A different Cartesia voice needs its own authority/contract even when the adapter is shared. |
| ADR-0007 makes Lane B an authorized SSGGSM/Odia/diary lane and blocks anything outside its listed lanes. | Accepted policy; its closure is too narrow for the explicitly defined intro only. | Supersede only that closure to admit Lane C; preserve Lane A/B isolation and all other blocked work. |
| ADR-0008 gives Lane B one `NarrationJob` and makes lane, speaker, voice, language and release-contract identity immutable in place (`INV-NJ-8`). | Accepted aggregate invariant. | The intro cannot be another passage/take in the Lane-B job; composition must reference two roots. |
| The historical v2 design introduced masters as immutable selected speech and says music/EQ/denoising create separately identified derived artifacts. | Proposed detail consistent with ADR-0008's immutable-artifact seam and accepted here for episode composition. | Keep the episode master dry and defer presentation work. |
| No accepted workflow currently supplies verified word timings for Cartesia audio. | Known absence, not a provider guarantee. | Require provenance and validation, with sentence/passage fallback rather than fabricated word-level synchronization. |
| Cross-root source validation introduces more application orchestration and possible authorization races. | Cost of the chosen boundary. | Re-check protected operations conservatively; do not hide the work by promoting masters into another repository. |

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| Put the different-voice intro in the Lane-B `NarrationJob`. | It violates the fixed SSGGSM voice/release contract and `INV-NJ-8`, and would misrepresent the authority that covers the result. |
| Treat every Cartesia voice as implicitly allowed in Lane B. | Cartesia is a transport provider, not a speaker-authority model; this would turn a narrow authorization into generic TTS. |
| Create a multi-voice super-job containing intro, diary, music and video. | It combines independently authorized production lifecycles with presentation concerns and creates a premature god aggregate. |
| Create a repository for masters and promote source-job masters into it. | It creates a second source of truth and cross-aggregate lifecycle that the source job already owns. |
| Generate video/subtitles/background audio in this slice. | Their licensing, timing, rendering and review rules are not yet decided; the dry speech and timing handoff is sufficient now. |
| Omit word-timing provenance and display calculated words as if they were aligned. | A visible word-by-word presentation would claim synchronization the system cannot audit or validate. |

## 5. Consequences

- Lane C adds a small, separately testable policy module and fixed-contract job flow;
  it does not change Lane B's authorization or its existing SSGGSM invariants.
- Episode assembly is a cross-root application workflow. It needs expected-revision,
  source-snapshot issuance, authorization/eligibility re-checks and recovery tests;
  it must not use a cross-aggregate transaction as a shortcut.
- The `DiaryEpisode` aggregate gains only the decisions it must make consistently:
  allowed source roles, snapshot order, gap, episode-master facts, timing-package
  versions and listening evidence. It does not become a narration provider or a
  release-authority service.
- A presentation implementation later receives reliable dry audio and explicit timing
  confidence/provenance, but still must design background rights, audiovisual output
  and publishing authority independently.
- Existing provider-neutral artifact/media primitives may be reused only under
  ADR-0009's accepted extraction rule. This decision does not accept speculative
  shared code or authorize Cartesia calls by itself.

## 6. Revisit trigger

Write a superseding ADR if any of the following is observed:

- an episode needs more than the fixed `intro` then `diary` role/order or needs a
  second Lane-C voice;
- a source narration job legitimately needs to change speaker, voice, language or
  contract in place;
- three justified presentation-specific exceptions are required in `DiaryEpisode`;
- source-job authorization/review checks cannot be made reliable with the recorded
  snapshot and expected-revision protocol; or
- a real presentation workflow establishes stable requirements for background audio,
  subtitles, video rendering or word-level timing that cannot be represented as a
  separately derived consumer of the episode artifacts.

## 7. What this record does not decide

It does not identify the Lane-C Cartesia voice, provide its private authority evidence,
write the intro text, set a concrete model/API snapshot or cost cap, replace or widen
SSGGSM authorization, or authorize another speaker/language/content scope. It does
not change Lane A, ADR-0006's SSGGSM scope, or ADR-0008's Lane-B aggregate and
invariants. It does not decide presentation licensing, background selection/mixing,
subtitle design, video rendering, public hosting, publishing authority, disclosure
wording, reviewer identity/count, a database/schema, or any implementation package
layout. It creates no code, provider call, presentation scaffold or publication.
