# ADR-0005 — The code-organisation rulebook, ported from a working DDD codebase rather than invented.

**Date:** 2026-08-29 · **Status:** Accepted 2026-09-02 · **Governs:** the new package's on-disk structure
**Supersedes:** the structure sketch in [ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) §5 · **Superseded by:** [ADR-0008](0008-lane-b-production-boundaries.md) §2.4, only where this record's CLI example could be read as the sole permitted Narrator Voice inbound adapter

---

## 1. Context

[ADR-0004](0004-clean-room-rewrite-with-cutover.md) commits to a clean-room DDD rewrite;
[ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) decides the contexts. Neither says
where files go, what they are called, or when a new folder is allowed to exist. Those
questions get answered a hundred times during a rewrite, and answering them ad hoc is
how a layout becomes inconsistent.

Rather than invent rules, this record **ports them from a working TypeScript DDD
codebase the steward already runs and trusts**: `ticket-to-lord`, branch `main`, studied
2026-08-29. Its rulebook is `docs/ddd/08-hexagonal-layout.md` (811 lines). That project
has two bounded contexts, 6,432 lines of context code (`leaderboard` 4,084 + `quiz-play`
2,348), and a team of five engineers plus a lead.

**It is not copied wholesale.** That codebase is a Cloudflare Workers + Neon Postgres web
service built by a team; this is a local Python CLI maintained by one person. §7 lists
what was deliberately left behind and why.

**Which of its two styles is being ported.** That repository contains two different DDD
styles, and only one is worth taking:

- **`leaderboard/`** — real tactical DDD. A rich aggregate with private state, validating
  value objects, typed errors, returned events. The mature context: 4,084 lines, four
  test files. **This is the model.**
- **`quiz-play/`** — deliberately anemic per its ADR-0017: aggregates are type aliases and
  invariants live in Postgres CTEs. Its `domain/errors.ts` and `domain/events.ts` are
  imported by nothing. **Not ported** — see §7.

## 2. Decision

Adopt the rules in §3–§6 for the new package. They are the default; departing from one
requires a superseding ADR, not a code-review argument.

## 3. The dependency rule

Verbatim from the source rulebook (`08-hexagonal-layout.md:20–22`):

> Dependencies point **inward**, toward the domain. Outer layers know about inner layers;
> inner layers never know about outer layers.

```
infrastructure  ──depends on──▶  application  ──depends on──▶  domain
(adapters, CLI,                  (handlers)                    (aggregates, VOs,
 filesystem, ffmpeg,                                            events, errors,
 ASR, DSP)                                                      ports, services)
```

Per-folder import table, adapted:

| Folder | May import from | Must not import from |
|---|---|---|
| `domain/` | the shared kernel, same-context `domain/` siblings, stdlib | anything else — **no third-party imports at all** |
| `application/` | same-context `domain/`, the shared kernel | `infrastructure/`, other contexts |
| `infrastructure/` | same-context `domain/` and `application/`, `platform/` | other contexts' internals |

**Ports live in `domain/ports.py`, not `application/ports/`.** The governing skill permits
either; the reference codebase puts repository interfaces in `domain/ports/repositories.ts`
in both its contexts, and it reads better — the aggregate and the interface that persists
it sit together.

> **Honest note on the source.** That rulebook's own import table says `application/`
> owns its ports, while its code puts them in `domain/ports/`. The table is stale; §3 of
> the same document shows `application/ports/inbound|outbound/` as *deferred* folders,
> created only "when ports beyond the current `domain/ports/` (repositories) earn distinct
> grouping." Code wins over table. This record follows the code.

## 4. Per-context layout

```
src/<package>/
├── contexts/
│   └── <context>/
│       ├── domain/
│       │   ├── <thing>.py            # aggregate: class, private state, two doors
│       │   ├── value_objects.py
│       │   ├── events.py
│       │   ├── errors.py
│       │   ├── ports.py              # Protocols
│       │   └── services/<rule>.py    # pure functions, no I/O
│       ├── application/
│       │   └── handlers/<verb>_<noun>.py
│       └── infrastructure/
│           ├── persistence/<thing>_repository_<tech>.py
│           └── inbound/cli.py
├── kernel/                            # the 1,044-line lift, ADR-0001
└── platform/                          # cross-cutting primitives; the ONLY place
                                       # third-party SDKs are imported
```

Each `contexts/<name>/` is a mini-hexagon. Nothing outside the composition root imports
from two contexts at once.

**Naming carries the role in the filename, not in folder nesting.** From the reference:
`weekly-cycle.repository.postgres.ts`, `finalize-week.command.handler.ts`,
`get-shortlist.query.handler.ts`. Python equivalents:

| Kind | Pattern |
|---|---|
| Aggregate | `transcription_job.py` (class `TranscriptionJob`) |
| Repository port | a `Protocol` in `domain/ports.py` |
| Repository adapter | `transcription_job_repository_sqlite.py` |
| Command handler | `handlers/finalize_job.py` — one public function |
| Query handler | `handlers/get_job_status.py` |
| Domain service | `domain/services/<rule>.py` — pure functions |

Commands and queries live in one `handlers/` folder, distinguished by verb, not by a
`commands/` vs `queries/` split. The reference collapsed that split deliberately.

## 5. Graduation thresholds — no folder exists before its first occupant

The source rulebook's strongest idea, and the one this repository most needs:

> **Why minimal-by-default:** the canonical aspiration above is the *shape primitives
> migrate into as they earn weight*, not a Day-1 scaffold. **Empty folders rot.**

Every structural decision gets a number attached, so "should I add a layer" is a lookup
rather than a debate. Ported, with the reference's numbers adjusted for one maintainer:

| Structure | Create it when |
|---|---|
| `domain/<aggregate>/` sub-folders | ~5+ aggregates in that context (reference: same) |
| `handlers/<use-case>/` sub-folders | ~20+ handlers in that context (reference: same) |
| `composition-root/` | 3+ repositories exist, **or** inline wiring exceeds ~50 lines, **or** cross-context wiring lands (reference: same, plus a team-size clause that does not apply) |
| `kernel/` gains a symbol | The day that symbol genuinely crosses two contexts — not before |
| `platform/<primitive>/` | First real consumer of that primitive |
| `infrastructure/outbound/` | First outbound adapter that is not persistence |

Until `composition-root/` graduates, **wiring is inline at the inbound adapter** — the CLI
command constructs the repositories it needs and passes them to one handler. The reference
does exactly this and records why: *"A separate `composition-root/build-graph.ts` would add
ceremony for less than a screen of code."*

**The composition root is the one named exemption to the dependency rule** — it may import
across contexts. Three properties make that safe, quoted from the source:

1. It is the **main partition**: where the application is *constructed*, distinct from
   where it *runs*. The dependency rule governs running code.
2. **Nothing depends on it.** "It's a sink, not a source … pollution flows in, nothing
   flows out."
3. **Construction is not orchestration.** "If an `if` over a domain value appears, it's
   misplaced."

Architecture tests must exempt it explicitly — a named carve-out, not a loophole.

## 6. Invariant identifiers

Every enforced invariant gets a stable id — `INV-<AGGREGATE>-<n>` — defined once, then
cited by that id in the code comment at the enforcement site, in the test name, and in any
ADR that touches it. In the reference, `INV-WC-1` (shortlist immutability) and `INV-WC-2`
(compute outside transaction) thread through the aggregate's header comment, two
architecture tests, three ADRs, and `CLAUDE.md`.

This repository has ADRs but no invariant ids. It has real invariants to name — the
lowercase-digest rule already guarded by `tests/youtube_enhance/test_digest_case.py` is
`INV-DG-1` waiting for a number.

The aggregate header comment is worth copying too. The reference's `WeeklyCycle` opens
with a state diagram, then an "Aggregate defenses (non-negotiable)" block naming, per
transition, **which check is the primary defence and which is defence-in-depth**. That
distinction is the discipline; the `if` statement is not.

## 7. What was deliberately not ported

| Left behind | Why |
|---|---|
| **The anemic-aggregate pattern** (their ADR-0017) | Forced by Neon's HTTP transport being single-statement, with no `db.transaction()`. This repository has no such constraint, and `ggsm_transcription` already has a working Unit of Work — `JobTransaction`, single write path, monotonic `revision`. Copying it would buy the anemia without the SQL atomicity that paid for it. |
| **The Open Questions apparatus** | 80+ OQs across 13 category files with owners and decide-by dates. That is five engineers coordinating. |
| **Bounded-context canvases, context maps, OHS published ports** | Nine canvases and a relationship catalogue for two Python contexts maintained by one person. |
| **Transactional outbox, in-process dispatcher, reconciler, scoped audit log** | Cross-context async delivery this repository does not do. |
| **Branded ID types** | A TypeScript trick for nominal typing on strings. Python's `NewType` is weaker and `frozen=True` dataclasses are stronger — the kernel's `_OpaqueId` hierarchy ([ADR-0001](0001-reuse-only-the-shared-kernel.md)) already solves this better, with runtime validation TypeScript cannot do. |
| **Source-text-regex architecture tests** | Their `__arch__/` tests are `readFileSync` + regex. This repository's existing AST-walking tests in `tests/heritage_production/test_architecture.py` are strictly better and are already written. |
| **Their `testing/` directory** | k6 load scripts and a 9.5 MB CSV fixture. Not unit tests, and not relevant here. |

## 8. Consequences

- **[ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) §5's structure sketch is
  superseded** by §4 above — chiefly the move of ports from `application/` to `domain/`.
- **The graduation thresholds constrain the clean-room build.** "Complete" in
  [ADR-0004](0004-clean-room-rewrite-with-cutover.md) means every folder has an occupant,
  not every folder that might one day be needed. `kernel/`, `platform/` and
  `composition-root/` do not get scaffolded ahead of their first user.
- **Invariant ids must be assigned before the tests that cite them**, so `INV-` numbering
  is a step in the model, not a retrofit.
- **A rule not in this record is not a rule.** If the reference does something this record
  did not port, it was left out on purpose.

## 9. Revisit trigger

- **If a rule here is broken three times for good reasons**, the rule is wrong — supersede
  it rather than accumulating exceptions.
- **If a graduation threshold is hit and the structure is not created**, the threshold was
  set too low; record the real number.
- **If the shared kernel grows past the 1,044 lines ADR-0001 lifts**, check each new symbol
  against the "crosses two contexts" test in §5. The reference holds its shared kernel to
  *three files* and has an architecture test asserting exactly that.

## 10. What this record does not decide

The domain model's content, the context split ([ADR-0002](0002-one-kernel-two-lifecycle-contexts.md)),
what is reused ([ADR-0001](0001-reuse-only-the-shared-kernel.md)), or the persistence
technology. It governs where code lives and what it is called — nothing about what it does.
