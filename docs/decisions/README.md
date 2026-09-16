# Architecture decision records

One decision per file. A record is never edited to change its decision — a later ADR
supersedes it, and the older file gets a `Superseded by:` line pointing forward.

**This is a new discipline for this repository, not an existing one.** Today's practice
is in-place revision: the AMENDMENT was appended to
[`2026-08-26-corpus-ledger-domain-design.md`](../superpowers/specs/2026-08-26-corpus-ledger-domain-design.md)
and the superseded-claims banner was inserted at the top of
[`odia-dual-output-system-design-2026-08-28.md`](../odia-dual-output-system-design-2026-08-28.md)
— both are the original file being edited. Those documents are the model for the
*tone* of a supersession here (surgical, itemised, nothing deleted quietly), not for
its mechanism.

**Naming:** `NNNN-slug.md`, four digits from `0001`, never reused, never renumbered.
Cite in prose as `ADR-0004` — distinct from the `D7`-style rows local to
[`docs/aws-evaluation/`](../aws-evaluation/). The date lives in the header, not the
filename: the first four records share a date, so a date suffix would carry no
information across them.

**Why `docs/decisions/` and not `docs/adr/`:** this repository does not abbreviate in
paths (`aws-evaluation`, `superpowers/specs`, `heritage_production`, `youtube_enhance`),
and it already reached for this word on its own in
[`06-decisions-and-open-questions.md`](../aws-evaluation/06-decisions-and-open-questions.md).
Not under `docs/superpowers/` because an ADR must be able to supersede a spec in that
tree, which is awkward from inside it, and because records should stay findable by
someone who never runs that workflow.

## Index

| # | Decision | Status | Governs |
|---|---|---|---|
| [0001](0001-reuse-only-the-shared-kernel.md) | ADR-0001 audits the source kernel; Narrator Voice v1 lifts only its further consumer-driven generic symbol trim | Accepted 2026-09-02 | `src/heritage_production/` |
| [0002](0002-one-kernel-two-lifecycle-contexts.md) | One `archive` context with a lifecycle aggregate per flow; transcription cut over first | Accepted 2026-08-29 | `scripts/ggsm_transcription/`, `scripts/youtube_enhance/` |
| [0003](0003-archive-research-scripts.md) | Archive 85 research scripts; ten are live, one is test-pinned | Proposed | `scripts/` (excluding the two production packages) |
| [0004](0004-clean-room-rewrite-with-cutover.md) | Clean-room rewrite then cutover, not incremental extraction | Accepted 2026-08-29 | the restructure as a whole |
| [0005](0005-code-layout-rulebook.md) | Layout, naming and graduation thresholds, ported from a working DDD codebase | Accepted 2026-09-02 | the new package's on-disk structure |
| [0006](0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md) | The authorized Cartesia IVC is the current SSGGSM Odia production voice, with configurable delivery controls | Accepted 2026-08-31 | Narrator Voice for SSGGSM Odia diary narration |
| [0007](0007-two-policy-isolated-narration-lanes.md) | Narrator Voice has two policy-isolated lanes; authorized SSGGSM Odia does not replace non-SSGGSM EN/HI narration | Accepted 2026-09-02 | Narrator Voice policy scopes and the archive-clock start trigger |
| [0008](0008-lane-b-production-boundaries.md) | Lane-B production keeps one narration job while separating authorization, artifacts, settings and user entry points | Accepted 2026-09-02 | SSGGSM/Odia/diary production architecture |
| [0009](0009-share-narration-mechanics-not-policy.md) | Share provider-neutral narration mechanics, never lane policy | Accepted 2026-09-02 | Technical capability shared or considered for sharing between narration policy scopes |
| [0010](0010-cartesia-prompting-is-validated-rendering-evidence.md) | Cartesia prompting is validated rendering evidence, not free-form narration policy | Accepted 2026-09-02 | Hybrid synthesis authoring and Cartesia request compilation |
| [0011](0011-diary-episodes-compose-fixed-voice-narration-masters.md) | Diary episodes compose fixed-voice narration masters without becoming a mixed-voice job | Accepted 2026-09-02 | Narrow Odia intro scope, dry episode assembly and timed narration handoff |
| [0012](0012-narrator-voice-v1-is-a-minimum-local-studio.md) | Narrator Voice v1 is a minimum single-operator local studio, not a general production platform | Accepted 2026-09-03 | Remaining Narrator Voice v1 implementation, verification and rollout |
| [0013](0013-narrator-voice-moves-to-its-own-repository.md) | Narrator Voice moves to its own repository; transcription and enhancement stay together here | Accepted 2026-09-16 | `src/heritage_archive/`, `tests/heritage_archive/` and the repository boundary |

**Reading order** for someone new: 0004 (why a rewrite at all) → 0002 (what the model is)
→ 0005 (where code goes) → 0001 (what is reused) → 0003 (the script cleanup, independent
of the rest).

For narration, read 0007 first: it separates the active future non-SSGGSM EN/HI
programme from the authorized SSGGSM/Odia/diary production lane. Read 0006 for the
authorized SSGGSM voice/baseline, then 0008 for the Lane-B production boundary. Read
0009 before extracting code across policy scopes, 0010 for the hybrid Cartesia
authoring boundary and 0011 for the narrow Odia-intro/episode-composition extension.
Read 0012 last: it preserves those policy/domain boundaries while replacing the
overbuilt remaining implementation profile. The
[v4 minimum local-studio design](../superpowers/specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md)
and its [replacement plan](../superpowers/plans/2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1.md)
are the authority for remaining v1 work. The v3 production design remains historical
full-scope evidence.

**Narrator Voice implementation note:** ADR-0005's inbound-adapter extension includes
non-Python `apps/` and `contracts/` when their first real console/contract consumer
lands. This does not pre-create a platform layer: every `platform/<primitive>/` folder
still graduates only with its first real consumer.

**ADR-0001 implementation clarification:** acceptance authorizes the audited source,
not a wholesale export surface. Narrator Voice v1 characterizes source behavior first,
then records its exact generic retained source/symbol manifest and post-trim count;
archive-specific identities, events, refs, sources and policy remain shelved.
Narrator-only work is independent of the archive-rewrite sequence and does not start
or consume 0004's clock; 0007 §2.4 gives the exact archive-context trigger.

Records 0002 and 0003 were materially revised on 2026-08-29 after an adversarial audit
refuted specific claims in each; 0001, 0002 and 0004 were revised again the same day
after studying the `ticket-to-lord` TypeScript reference codebase; and 0002, 0003 and
0004 were revised a third time when the four open questions were resolved. Each carries
a revision note saying what changed.

**Open ADR questions from 2026-08-29: none.** All four decisions that were left to the
steward that day are settled — one bounded context (0002 §6), the stopping rule and its
date (0004 §5), and the disposition of `hi/build_casting_site.py` (0003 §3.1). The linked
production design separately lists implementation choices for review.

## Status values

| Value | Meaning |
|---|---|
| `Proposed` | Written and evidenced; the steward has not accepted it |
| `Proposed — open question, §N` | As above, and one numbered decision is explicitly unresolved |
| `Accepted <date>` | The steward chose this |
| `Accepted <date> — decision N open, §M` | Chosen, but one part is deliberately incomplete |
| `Superseded by ADR-NNNN` | A later record replaced it; the file stays, unedited except for this line |
| `Deferred on <trigger>` | Not decided; a named, falsifiable observation would reopen it |

## Writing a new one

Copy [`TEMPLATE.md`](TEMPLATE.md). The two sections that matter most, and that this
repository has learned the hard way to insist on:

- **Rejected alternatives**, each with the reason it lost. A decision with no recorded
  alternatives cannot be revisited, only re-argued.
- **A revisit trigger** that is falsifiable and stated in advance. AMENDMENT A4 of the
  corpus-ledger spec is the worked example of one that failed review, three independent
  ways: it was a conjunction passable by deleting dead code, its second clause could
  only be satisfied by theatre, and it measured the wrong store. Read it before writing
  one.

**Check the numbers before publishing.** Every quantitative claim in the first four
records was verified against the code, and that pass found a false commit hash, a
kernel line count describing a tree that does not import, a collision that was a false
positive, and a blocking mechanism that did not exist. None of those would have been
caught by re-reading the draft.
