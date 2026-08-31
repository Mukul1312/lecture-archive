# ADR-0004 — The DDD restructure is a clean-room rewrite with cutover, not incremental extraction.

**Date:** 2026-08-29 · **Status:** **Accepted 2026-08-29** · **Governs:** the restructure as a whole
**Supersedes:** nothing · **Superseded by:** —

This is the parent decision. [ADR-0001](0001-reuse-only-the-shared-kernel.md),
[ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) and
[ADR-0003](0003-archive-research-scripts.md) all assume it.

---

## 1. Context

The steward judged the codebase no longer maintainable or readable and chose to
restructure it around DDD, in which he has high confidence. Two approaches were put
forward: **incremental extraction** (strangler-fig — pull the domain out of the live
flows one aggregate at a time, both pipelines running throughout) and **clean-room
rewrite** (build the complete domain, ports and adapters in a new package, then migrate
the flows across). **The steward chose clean-room, with the concern below recorded and
in view.**

The maintainability complaint is well-founded and measured:
[`youtube_enhance/cli.py`](../../scripts/youtube_enhance/cli.py) is 2,682 lines of
transaction script over a 38-line anemic
[`models.py`](../../scripts/youtube_enhance/models.py);
[`ggsm_transcription/store.py`](../../scripts/ggsm_transcription/store.py) is 717 lines
in which the `_NEXT_STAGE` state machine — the core business rule — sits at line 42, in
the same module as `os.replace`, `stat`, `tempfile` and `PureWindowsPath`; and 12,656
lines of one-off research scripts sit in the same reading path, 14,400 counting the
eighteen not covered by the bulk move ([ADR-0003](0003-archive-research-scripts.md)).

## 2. Decision

1. **Clean-room rewrite.** Build the new package complete, then cut the flows over.
2. **Layering architecture tests go in first**, before any domain code — the approach
   from [ADR-0001](0001-reuse-only-the-shared-kernel.md) decision 2(a). This is the
   mitigation for §3, and it is not optional. Named-invariant guards (2(b)) arrive with
   their invariants instead.

   *Note the reference codebase does not have layering tests — its rulebook §13 records
   that it dropped the `dependency-rule` test as "low value at single-context scale;
   intra-context dep direction is naturally enforced by import paths." That reasoning is
   TypeScript-specific: its import paths and compiler make violations visible. Python has
   neither, and this repository already owns working AST-walking versions. Keep them.*
3. **Cutover is sequential, not big-bang** — transcription then enhancement, per
   [ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) decision 3. "Clean-room"
   describes how the model is built, not how it lands.
4. **The stopping rule in §5 applies.** It is set: a start gate, a 35-day box, and three
   evidence clauses checked at the end of it.

## 3. The recorded risk

**A domain-first DDD build, stopped one step short of adapters, is what this repository
already did, and it is shelved.** `src/heritage_production/` is 14,634 lines of Python,
with 20,045 lines of tests in `tests/heritage_production/` — **34,679 lines** — with a
stdlib-only domain layer, an architecture firewall, and 656 passing tests, none of which
has ever run against either pipeline. It reached step 4 of the governing skill's
five-step implementation order and stopped before "Add adapters last": Tasks 1–6 of 11
were built, Task 7 onward never was.

The corpus-ledger spec names the cause in §14 — a section the AMENDMENT later marks
wrong, though not on this point:

> This is the discipline whose absence produced 31,641 lines that do not run against
> either working pipeline.

*(31,641 is the 2026-08-26 branch figure for the same body of code; it measures 34,679
today. The gap is growth on the branch before the merge, not a disagreement.)*

Two further data points from the AMENDMENT itself, and what has happened to each since:

- **A1.** When an independent five-dimension analysis was commissioned before building
  — *specifically because the author did not trust his own estimate* — the 2–4 day
  figure came back as **REWRITE, 16–24 working days**, with all five dimensions
  `divergent`. This is the one estimate in this repository that was independently
  checked, and it was wrong by 5–8×. Whether that generalises to a DDD rewrite of two
  pipelines is unknown; A1's subject was the corpus ledger's increment 1.
- **A3.** The design's own falsification test, applied before the expensive work rather
  than after, deferred the ledger — *"costs half a day and saves four weeks."* A6 item 5
  later retired that specific test (*"should not be revived"*); what carries forward is
  the **ordering** principle, not the test.

This is recorded so the decision is legible later as one made **with** this evidence.
It is the steward's call and it is made.

### 3.1 The reference codebase was grown, not clean-roomed

The steward nominated `ticket-to-lord` as the DDD he wants. Studied on 2026-08-29, that
codebase was built the way this record's rejected alternative describes:

- Its **ADR-0016** rejects scaffolding outright — *"Empty folders rot"* — and lists
  folders that deliberately do not exist yet, each with the event that will create it.
  `shared-kernel/` and `composition-root/` are both still absent.
- Its **ADR-0017** describes itself as a *"post-hoc backfill of pattern that emerged
  during Phase 3 pilot refactor"*, and records that the pattern shrank one handler from
  330 to 95 lines. The shape was discovered by building, then written down.

This does not overturn decision 1 — the steward has lived through the grown version's
mess in this repository and may want the clean result precisely because of it. It is
recorded because it is evidence from the steward's own chosen reference, and because it
is what a superseding ADR would cite if §5 fires.

**What it does change now:** "complete" in decision 1 means *every folder has an
occupant*, not every folder that might one day be needed. The graduation thresholds in
[ADR-0005](0005-code-layout-rulebook.md) §5 apply during the clean-room build, not after
it. A clean-room rewrite that scaffolds `platform/`, `composition-root/` and a
speculative `kernel/` before anything imports them is repeating this package's mistake
at a smaller scale.

**What genuinely differs this time:**

| `heritage_production` | This rewrite |
|---|---|
| Built steps 1–4 of the skill's order, stopped before adapters | Cutover of a live flow is the definition of done (§5) |
| Ports validated only by fakes written the next day | Two pipelines with real audio are the acceptance test |
| No stopping rule; the one later proposed was found defective (A4) | A stopping rule is a precondition, §5 |
| Modelled six aggregate roots ahead of demand | ADR-0001 leaves 33,635 of 34,679 lines shelved — 13,064 of them behind `SHELVED.md`'s four named triggers, none fired |

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| **Incremental extraction (strangler-fig)** | Recommended by the analysis and **overruled by the steward**, who wants the clean result rather than a sequence of partial states. Recorded because it is what a future ADR would most likely return to if §5 fires. **New evidence, 2026-08-29 — see §3.1:** the reference codebase the steward nominated as the target was itself grown, not clean-roomed. |
| **Rewrite in place, flow by flow, taking each offline** | Takes the SSGGSM transcription programme's only automated flow offline for the duration — the spec's §2 records the programme as daily, though the package itself has one recorded run (A2, A5). No better than clean-room on model quality. |
| **Do nothing** | The measured problem in §1 is real, and two of its three parts are concentrated in files the rewrite directly addresses. |

## 5. The stopping rule

AMENDMENT A4 is the worked example of how this goes wrong. The stopping rule originally
proposed for the ledger failed review three independent ways, **any one fatal**: it was
**a conjunction**, so it could be passed by deleting dead code; **its second clause
could not be satisfied honestly**, because the script it named never opens a lecture, so
the only way to satisfy it was a dead line — *"The rule would be satisfied by theatre"*;
and it **measured the wrong store**.

The replacement form A4 proposes is the model to follow — evidence, not activity:

> (a) `store.py` no longer computes a digest, job id or lock of its own; (b) `ledger
> has` gates a unit of work that costs GPU minutes **and a run log shows it skipped
> one**; (c) ≥50 items registered from bytes on disk; (d) a hard time-box — not done at
> day 10, stop.

### 5.1 The rule, set 2026-08-29

**Neither pure time nor pure evidence.** A hard date cannot tell you whether progress was
real; an evidence rule with no date never forces the evaluation to happen — which is how
the previous attempt reached 34,679 unused lines. The form that survives A4's own critique
is **evidence checked at a hard date**.

> **Start gate.** The first commit creating the new package must land by **2026-09-05**.
> If it has not, the rewrite is not actually starting and this record is revisited rather
> than left to drift.
>
> **D = 35 calendar days after that first commit.** (Steward's availability: full-time;
> the naive build estimate is ~12–14 working days, doubled for the A1 lesson gives ~25.)
>
> **At D, check all three. If any fails, stop.**
>
> **(a)** The Zurich lecture `21-8-85-20sb6-2-36-37-20zurich-6ca3c5b8` re-runs end to end
> through the new package — all seven stages, `source_ready` to `handed_off`.
> **(b)** `scripts/ggsm_transcription/store.py` no longer computes a digest, job id or
> stage transition of its own.
> **(c)** The old implementation is deleted or reduced to a shim.

Both dates are checkable from `git log` by someone who did not write the code, which is
the property A4 demands.

**Why clause (c) is not optional.** A4's central finding was that the ledger's rule could
pass while leaving the old store alive: *"the merge lands but the deletion does not … four
identity schemes, strictly worse than doing nothing."* Without (c), (a) and (b) can both
hold while two implementations of the same flow sit side by side.

**Why all three must hold, when A4 condemned conjunctions.** A4's rule was a conjunction of
things that would *pass* it — easy to satisfy. This is a conjunction of things required to
*continue*; failing any one stops the work. The logic is inverted, and so is the incentive.

**If the rule fires**, this ADR is superseded per §7 — not extended in place, and not
quietly re-dated.

## 6. Consequences

- **Nothing runs on the new code until the first cutover.** That is the defining
  property of clean-room and the source of the risk in §3.
- **The live flows keep receiving fixes during the build**, so divergence between old
  and new grows with elapsed time — a direct argument for a tight time-box in §5.
- **`data/` state must survive the cutover.** The Zurich transcription job and the
  archived enhancement approvals are real evidence bound to real bytes; a cutover that
  cannot read them is not a cutover.
- **The 2026-08-27 non-reproducibility limitation carries over unchanged**:
  CTranslate2's int8 CPU inference under faster-whisper is non-deterministic over long
  audio, so a transcript digest seals one run rather than being a recomputable
  checksum. The new package must not assume otherwise.

## 7. Revisit trigger

**When the stopping rule in §5 fires, this ADR is superseded — not extended.** The
superseding record should state what was learned and choose between finishing the
cutover on a new time-box and reverting to incremental extraction against whatever the
rewrite has produced.

Also revisit if the transcription cutover produces the checkable language collision in
[ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) §7 or forces the model beyond its
accepted `archive` context plus the expected Narrator Voice context — scope growth is
the mechanism by which the previous attempt became unlandable.

## 8. What this record does not decide

The domain model's shape, the context split, the cutover order (all
[ADR-0002](0002-one-kernel-two-lifecycle-contexts.md)), what is reused
([ADR-0001](0001-reuse-only-the-shared-kernel.md)), or the research scripts
([ADR-0003](0003-archive-research-scripts.md)). It sets the start gate and 35-day
stopping rule in §5; it does not decide the successor plan or time-box after that rule
fires.
