# ADR-0002 — One shared provenance kernel; separate lifecycle models per flow. Cut over transcription first.

**Date:** 2026-08-29 · **Status:** **Accepted 2026-08-29** · **Governs:** `scripts/ggsm_transcription/`, `scripts/youtube_enhance/`
**Supersedes:** nothing — it **confirms** the context set in §5/§16 of [`2026-08-26-corpus-ledger-domain-design.md`](../superpowers/specs/2026-08-26-corpus-ledger-domain-design.md) · **Superseded by:** —

> **Revision note, 2026-08-29.** Revised twice on the same day. First, an adversarial
> audit refuted the row this record originally called its strongest (`stage`) and
> corrected two of its three tables — the evidence in §3 is what survived, and it is
> **weaker than the first draft claimed**. Nothing was removed quietly; the refuted row
> is recorded in §3.2 as a false positive. Second, §5's structure sketch was superseded
> by [ADR-0005](0005-code-layout-rulebook.md), which ports a layout rulebook from a
> working DDD codebase instead of inventing one. Third, the open question in §6 was
> **resolved against this record's own first draft**: Decision 2 now keeps **one**
> bounded context, not three. The evidence that pointed the other way did not survive
> the audit, and what remained dissolves under a rewrite — see §6.

---

## 1. Context

Two pipelines are live in the tree and each has produced real output:
[`scripts/ggsm_transcription/`](../../scripts/ggsm_transcription/) (2,984 lines) and
[`scripts/youtube_enhance/`](../../scripts/youtube_enhance/) (8,163 lines, of which
[`cli.py`](../../scripts/youtube_enhance/cli.py) is 2,682). Both are being restructured
under [ADR-0004](0004-clean-room-rewrite-with-cutover.md). The steward asked for both,
and how to do both is this record.

The existing design of record answers part of this already. §3.2 of the corpus-ledger
spec applies the governing skill's linguistic criterion — *"Where language changes =
bounded context boundary"* — across the five programmes and concludes:

> Same word. Two incompatible meanings. Same repository. **That is a bounded context
> boundary by the skill's own criterion**, and it is the only one present.

The spec's §5 then names two contexts: **Corpus Ledger** (§5.1) and **Narrator Voice**
(§5.2), and §16 records the count. Corpus Ledger was subsequently **deferred by
AMENDMENT A3** and never built — `ls src/` returns only `heritage_production`.

**That analysis compared programmes at the level of five domain terms.** This record
compares the two packages at the level of the vocabulary actually in the code, which
§3.2 never examined.

## 2. Decision

1. **Model the shared provenance vocabulary once**, as the kernel from
   [ADR-0001](0001-reuse-only-the-shared-kernel.md) plus the aggregates the spec's §16
   already named: `ArchiveItem`, `DerivedArtifact`, `Judgement`.
2. **One bounded context (`archive`), with a separate lifecycle *aggregate* per flow.**
   `TranscriptionJob` and `EnhancementJob` are different aggregates with different
   invariants inside the same context and the same ubiquitous language — not different
   contexts. Narrator Voice remains a second context, materialising when programme 5
   lands. This is the spec's §5/§16 answer, confirmed rather than revised.
3. **Cut over sequentially, transcription first.** Enhancement second, against a model
   already proved once.
4. **`Judgement` is a first-class aggregate from the start**, not a field on a job.

Decision 2 was the open one. It is resolved in §6.

## 3. Evidence

### 3.1 The shared vocabulary is real, and it is infrastructural

These terms mean the same thing in both packages:

| Term | Shared meaning | Evidence |
|---|---|---|
| `job` | `job.json` as the aggregate file, per-job OS lock, Windows reserved-device rejection | `store.py:87–100, 373–378, 412–419` vs `workflow_state.py:219–284` |
| `source` | Immutable input recording, identified by SHA-256 | both |
| `artifact` | Job-relative file recorded with its SHA-256 and byte size, path-validated against traversal/symlink/reparse, re-hashed on read | `store.py:158–174, 455–478` vs `workflow_state.py:443–495` |
| `lock` | OS file lock plus in-process guard, Windows-aware | both, different topology |
| digest case | Lowercase, both | `store.py:88` vs `workflow_state.py:462`, guarded by `tests/youtube_enhance/test_digest_case.py` |

Two qualifications the first draft got wrong and that matter:

- **The record *shape* differs** even where the concept agrees. Transcription writes a
  `{sha256, byte_size}` dict (`store.py:166`); enhancement writes a frozen
  `ArtifactRecord(relative_path, sha256, size_bytes, file_id, media)`
  (`workflow_state.py:53–59`).
- **Job identity is *not* shared.** Transcription binds the job id to the source hash —
  `store.py:39` requires an 8-hex suffix. Enhancement's `JOB_ID` regex
  (`workflow_state.py:16`) has no hash component, and `workflow_state.py` contains zero
  occurrences of `source_sha256`. This belongs in §3.3 as an asymmetry, and is listed
  there.

This shared set is where the corpus-ledger spec's §4.1 duplicate-store bug lived — the
two stores holding different string identities for the same bytes. **The bug was in the
shared vocabulary, not the divergent vocabulary.** Decision 1 is what fixes it.

### 3.2 Six domain-vocabulary collisions — and one that was a false positive

| Word | In `ggsm_transcription` | In `youtube_enhance` |
|---|---|---|
| **`aggregate`** | The DDD aggregate root. `store.py:20` *"violates the aggregate contract"* | A **numeric roll-up field**. `gates.py:401` `{"aggregate": 0.0, ...}` |
| **`candidate`** | A possible **duplicate match** during dedup. `find_url_candidates`, `find_hash_candidates` (`store.py:531,534`) | A **rival output** awaiting human selection. `_CANDIDATE_IDS = ("original", "adaptive-22", "adaptive-24")` (`gates.py:21`) |
| **`chunk`** | A unit of **human review work** — `review/chunk-001.md` with a `Review-State:` header (`review.py:110–177`). The read-buffer `chunk` at `store.py:74–76` is a generic idiom, not a domain sense | A **DSP block** — DeepFilterNet core/halo/blend samples (`generic_d30.py:280`) |
| **`completion`** | A typed transition operation. `complete_asr()`, `complete_review()` | A **marker file** proving a step finished. `render-completion.json` (`cli.py:1610`) |
| **`identity`** | Record/dedup identity — a repo-wide mutex around an exact binary sameness decision (`store.py:422–425`, sole caller `intake.py:104`) | **Speaker** identity, a float cosine-similarity veto (`gates.py:24`); **blind-code** identity (`candidates.py:355–368`); and **repository** identity, a git-root fingerprint (`workflow_state.py:37–41`) |
| **`transition`** *(weak)* | State-machine movement. `StageTransitionError` (`store.py:27`) | An **audio seam** between processed chunks — `transition_peak_discontinuity` (`gates.py:325`). But `workflow_state.py:70` also declares `InvalidTransition` in the state-machine sense (declared, never raised) |

**`stage` was withdrawn as a false positive.** The first draft called it the strongest
row — a persisted lifecycle state in transcription versus a scratch directory and a
step name in enhancement. It is not: enhancement **also** persists `job["stage"]`,
guards on it (`generic_d30.py:104`, refusing to run unless `full_render_approved`) and
advances it (`generic_d30.py:356`, to `awaiting_final_listening`). Both flows use the
word in the lifecycle sense. It is recorded here rather than deleted because it was
this record's headline and its removal is the single biggest change between drafts.

Two words checked and **cleared**, so not counted above: `window` (every transcription
hit is Windows-the-OS except an English idiom in a docstring at `store.py:235`; no
audio or time-window sense) and `gate` (transcription has zero word-boundary hits — the
matches were substrings of "aggregate").

Softer, real but arguably the same idea at different altitudes: `verify`, `review`,
`state`, `manifest`.

### 3.3 Structural asymmetries

| | `ggsm_transcription` | `youtube_enhance` |
|---|---|---|
| Lifecycle | Explicit **validated** state machine — `_NEXT_STAGE` (`store.py:42`), `stage_history` replayed at `store.py:653` | **Rudimentary.** A persisted `stage` with named states and one enforced precondition (`generic_d30.py:104, 356`), but no ordering dict, no history, remaining phases implicit in six `_verify_*_state` functions and marker files |
| Job identity | Bound to source hash — 8-hex suffix required (`store.py:39`) | No hash component (`workflow_state.py:16`); `source_sha256` appears nowhere in the file |
| Unit of Work | `JobTransaction`, single write path, monotonic `revision` | **None**, and zero occurrences of `revision` anywhere in the package |
| Job state objects | Raw `dict[str, Any]` policed by `_validate_manifest` (`store.py:639–701`) | Also raw `Mapping[str, Any]`, policed by `_require_mapping`/`_exact_mapping` (28 call sites). Typed frozen value objects exist only for audio segmentation (`models.py`, 38 lines) |
| CLI | 256 lines, thin Protocol-driven shell | 2,682 lines, holds orchestration and validation |

The first draft claimed these were "opposite modelling styles". They are not — both
model job state as validated dicts. The genuine asymmetries are the **Unit of Work**
(present versus absent, cleanly), **job identity** (hash-bound versus not) and the
**degree** of lifecycle validation.

### 3.4 Why transcription cuts over first

- **2,984 lines against 8,163** — a wrong model is discovered in days, not weeks.
- Its lifecycle is an explicit validated 7-state machine, the most mechanical lift available.
- It already has `Protocol` adapters and a Unit of Work, so the ports are pre-shaped.
- It has a real end-to-end run to regress against — job
  `21-8-85-20sb6-2-36-37-20zurich-6ca3c5b8`, through all seven stages to `handed_off`
  on 2026-08-27.

This reverses an earlier verbal recommendation of enhancement-first. Under incremental
extraction you go where the pain is; under a clean-room cutover the first migration is
a **validation of the model**, so lowest-risk-first wins.

AMENDMENT A5 found *"Enhancement is the more mature store, not the more expendable
one."* A5 was arguing which store to **retire**; this is which flow to **migrate
first**, and maturity argues for going second — there is more to lose.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| **One bounded context, one lifecycle model for both flows** | §3.2 — six domain words carry different meanings across the packages, and §3.3 shows genuinely different lifecycle rigour and no Unit of Work on one side. Forcing one model means one flow acquires a foreign vocabulary. It also fixes nothing the kernel does not already fix: the actual duplicate-store bug was in the *shared* terms. **This is the alternative §6 leaves open**, and the `stage` withdrawal strengthens it. |
| **Model and cut over one flow completely, then start the other** | The second flow arrives as a retrofit onto a kernel shaped by the first flow's accidents. The spec's §4.1 is what that produces organically. |
| **Enhancement first** | §3.4. Three times the size, more to lose, and only a rudimentary state machine to lift — a worse first test of a new model. |
| **Two fully independent contexts with no shared kernel** | Recreates the spec's §4.1 by construction. The shared terms in §3.1 are exactly where the known bug was. |

## 5. Consequences

- **The context set is unchanged.** The spec's §5/§16 name Corpus Ledger and Narrator
  Voice. Corpus Ledger was deferred by AMENDMENT A3 and never built; this record revives
  its aggregates (`ArchiveItem`, `DerivedArtifact`, `Judgement`) inside a context named
  `archive`, and adds the two job aggregates beside them. Two contexts, as designed.
- **One vocabulary must be chosen where the old code had two.** The six collisions in
  §3.2 become naming decisions during the rewrite, not boundaries. `chunk` in particular
  needs two distinct words — the unit of human review work and the DSP block are
  genuinely different things and must not both be called `chunk`.
- **`Judgement` must absorb what is scattered today**: blind audition decisions in
  browser `localStorage` across twelve gallery builders, and listening approvals in
  `job.json`.
- **Enhancement's rudimentary lifecycle becomes an explicit design question** — whether
  to promote it to a validated state machine — rather than something decided by accident.
- **Evidence caveats.** `data/enhance/archive/` is gitignored (`.gitignore:85`) and
  local-only; the archived approvals are real but not in version control and not
  reproducible by a third party. The live roots `data/enhance/jobs/` and
  `data/enhance/youtube/` do not currently exist. Those archived approvals store
  **uppercase** SHA-256, predating the 2026-08-27 case fix — history, not an example of
  current discipline.

## 6. The open question, resolved: one context

Decision 2's first draft made this three contexts. **That is now rejected, on four
grounds, in order of weight:**

1. **The collisions are artifacts of code being thrown away.** Under the clean-room
   rewrite of [ADR-0004](0004-clean-room-rewrite-with-cutover.md), the vocabulary of the
   new code is chosen, not inherited. This record's own first draft conceded the point
   that decides it: *the words diverged without anyone deciding they should.* That
   sentence is decisive precisely because the steward is now the one deciding.

2. **The two structural survivors dissolve under a rewrite.** §3.3's Unit-of-Work gap and
   job-identity divergence are *maturity* differences, not language differences —
   enhancement has no Unit of Work because nobody wrote one, not because its domain
   forbids one. Both flows get one in the new package. After the audit removed `stage`
   and corrected the "opposite modelling styles" claim, these two were the whole case
   for a split, and neither survives contact with new code.

3. **The spec's own linguistic analysis, done at the domain level, found one boundary and
   it is not this one.** §3.2 of the corpus-ledger spec compared *lecture, source
   recording, derived-from, judgement, identity* and found language change in exactly one
   place: hash versus vocal resemblance. That is archive-provenance versus narrator-voice.
   The six collisions in §3.2 above were found at the implementation-noun level, which is
   the level a rewrite renames.

4. **[ADR-0005](0005-code-layout-rulebook.md)'s philosophy applies to boundaries, not just
   folders.** "Empty folders rot" generalises: a bounded context is the largest structure
   that can be created prematurely, and three of them means three sets of ports, three
   composition roots and three architecture-test suites for one maintainer.

`Judgement` with a competence field already unifies the two kinds of human decision —
editorial correction in transcription, perceptual choice in enhancement. That design is
in the spec's §5 and it is good.

**What replaces the split:** two aggregates in one context. `TranscriptionJob` has a
validated seven-state machine; `EnhancementJob` has its own states and its own invariants.
Different aggregates, different invariants, one ubiquitous language, one set of ports.

## 7. Revisit trigger

**The split trigger, stated so someone else could check it:** if, while writing the new
code, one word is needed for two different things and neither meaning can be renamed
without losing precision, that is the bounded-context boundary. Split then — on evidence
from the new code, not from the code being replaced. Record which word, and both meanings.

- **If the shared vocabulary in §3.1 shrinks below those five terms during the rewrite**,
  the context is not holding together and the split should be reconsidered before
  enhancement starts.
- **Programme 5 landing** materialises Narrator Voice as the second context, per the
  spec's §5.2. That is expected, not a trigger to revisit this.

## 8. Shape of the model, ported from the reference

[ADR-0005](0005-code-layout-rulebook.md) governs where code lives. Three shape decisions
belong here because they are about the model, not the layout, and all three come from the
`leaderboard` context of the `ticket-to-lord` reference:

1. **Aggregates have two doors.** A creation classmethod that validates, and a
   `rehydrate` classmethod that deliberately does *not* — it reconstructs whatever state
   persistence holds. This kills the standard bug where creation-time validation blocks
   loading a legacy row. Keep the reference's comment saying the bypass is intentional.

2. **Transitions return events.** `complete(...) -> TranscriptCompleted` rather than
   recording into a pending list. See [ADR-0001](0001-reuse-only-the-shared-kernel.md) §3.

3. **Handlers are free functions `(deps, input) -> result`**, where `deps` is a plain
   frozen struct of ports plus optional overridables (`now`, config) defaulted on the
   first lines of the body. No handler classes, no DI container, no command bus.

**Idempotency is a return value, not machinery.** The reference expresses it as a
discriminated union on a `status` field — `'finalized' | 'already_finalized'`,
`'refreshed' | 'skipped'` — decided by re-reading persisted aggregate state at the top of
the handler. Re-running finished work is a normal return, not an exception and not a
dedup table. In Python: a frozen-dataclass union matched with `match`.

This replaces `heritage_production`'s `run_operation` idempotency registry outright, which
[§12 Task 6 of the corpus-ledger spec](../superpowers/specs/2026-08-26-corpus-ledger-domain-design.md)
had already marked superseded. The state-machine short-circuit needs no operation table,
no input digest, and no replay verification — the aggregate's own state is the record of
what has happened.

## 9. What this record does not decide

Whether enhancement should acquire a validated state machine; where `Judgement` rows are
stored; the persistence technology; and the time-box for the cutover, which belongs to
[ADR-0004](0004-clean-room-rewrite-with-cutover.md). File layout and naming belong to
[ADR-0005](0005-code-layout-rulebook.md).
