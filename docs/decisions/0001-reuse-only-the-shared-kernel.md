# ADR-0001 — Only the 1,044-line shared kernel comes out of `heritage_production`. The rest stays shelved.

**Date:** 2026-08-29 · **Status:** Accepted 2026-09-02 · **Governs:** `src/heritage_production/`
**Revised:** 2026-08-29 after studying the `ticket-to-lord` reference codebase — see §3 "What the reference changed"
**Revised:** 2026-08-31 after verifying that repository-wide test discovery still collected the shelved suite
**Supersedes:** nothing · **Superseded by:** —

Related: [ADR-0004](0004-clean-room-rewrite-with-cutover.md) is the rewrite this feeds.

---

## 1. Context

A clean-room DDD rewrite is starting ([ADR-0004](0004-clean-room-rewrite-with-cutover.md)).
`src/heritage_production/` holds **14,634 lines** of Python across 59 files, with
**20,045 lines** of tests — **34,679 lines** in total, roughly three times the size of
all live production code. It is shelved: nothing under `scripts/`, `cloud/` or `colab/`
imports it, and its CLI at [`presentation/cli/main.py`](../../src/heritage_production/presentation/cli/main.py)
is 62 lines of subcommands that parse arguments and return 0.

The question this record answers is narrow: **what carries across into the new package,
and what stays where it is.**

Its own disposition document,
[`SHELVED.md`](../../src/heritage_production/SHELVED.md), already answers part of
this and names four unfreeze triggers. That file is cited here in preference to
§12 of the [corpus-ledger spec](../superpowers/specs/2026-08-26-corpus-ledger-domain-design.md)
wherever the two overlap, because it lives in the tree beside the code and declares
its own authority.

## 2. Decision

1. **Lift the shared kernel** — `domain/shared/`, minus `trust.py` and minus the
   credential block at `refs.py:78–125`, with `__init__.py` trimmed to match.
   **1,044 lines across 11 files**, measured by building the tree and importing it.
   **Also drop `AggregateEventRecorder`** (`events.py:61–77`, 17 lines) — superseded by
   the return-the-event pattern in §3. It is used only by shelved aggregates
   (`production/aggregate.py`, `review/findings.py`, `review/rounds.py`,
   `transcription/edition.py`), none of which is lifted. `DomainEvent` stays;
   `SealedAggregateRoot` stays as a marker for the layering tests.
   Arithmetic puts the result near **1,025** — but that figure is *not* build-verified,
   and the 1,076 trap in §3 is exactly what unverified arithmetic here produces.
   **Re-measure by building and importing, before quoting it.**
2. **Carry over the architecture-test approach**, not the tests themselves — in two
   distinct kinds, because the reference codebase shows they are not the same thing:
   - **(a) Layering guards.** The AST-walking checks in
     [`test_architecture.py`](../../tests/heritage_production/test_architecture.py) and
     [`test_domain_import_boundaries.py`](../../tests/heritage_production/test_domain_import_boundaries.py)
     — dependency direction, no third-party imports in domain, no cycles. These go in
     **first, before domain code**, and must exempt the composition root by name
     ([ADR-0005](0005-code-layout-rulebook.md) §5).
   - **(b) Named-invariant guards.** One test per `INV-<ID>`, each guarding a single
     decision that would otherwise silently rot, citing the ADR that mandated it. These
     arrive with the invariant, not up front.
   The first `INV-` guard already exists in this repository and predates the numbering:
   `tests/youtube_enhance/test_digest_case.py`, which fails the build if
   `.hexdigest().upper()` returns.
3. **Read the port shapes as reference; import none of them.**
   [`application/ports/`](../../src/heritage_production/application/ports/) is a
   worked example of one repository port per aggregate root. It is a reading, not a
   dependency.
4. **Everything else stays shelved**, unedited, with its four unfreeze triggers intact.
5. **Stop using repository-wide discovery as the default test command.** The documented
   active suite discovers `tests/ggsm_transcription/`, `tests/heritage_archive/` and
   `tests/youtube_enhance/`, then runs `tests.test_legacy_script_paths`; it does not
   collect `tests/heritage_production/`. The shelved suite remains in place and is run
   only when requested explicitly.

## 3. Evidence

### What the package is made of

| Part | Lines | Unfreeze trigger (verbatim, `SHELVED.md`) | Fired? |
|---|---:|---|:--:|
| `domain/shared/` (trimmed) | **1,044** | — designated the shared kernel | **take** |
| `domain/production/` + `domain/release/` | 5,116 | "A rights-holder or recipient asks for a formal sign-off before delivery" | ❌ |
| `domain/review/` | 3,143 | "The first finding submitted by a human who is not the steward" | ❌ |
| `domain/transcription/` | 1,839 | "The first sealed edition that will receive a second human correction pass" | ❌ |
| `application/` | 2,966 | "Only alongside one of the above. Its `run_operation` idempotency design is superseded by the run-key approach in the 2026-08-26 design" | ❌ |
| `domain/shared/trust.py` | 377 | — excluded from the kernel by §12 Task 2 | ❌ |

Not one trigger has fired. `production` + `release` alone is 35% of the source, and it
models rights-holder sign-off, Ed25519 approval, eligibility assessment and external
gate sets for a delivery process that has never been requested.

### The kernel lift was verified, not estimated

The trimmed tree was **built in a scratch directory and imported** before this record
was written. Package import succeeds, all 10 remaining submodules import, all 59
`__all__` names resolve, and a functional smoke test passes
(`canonical_json({'b':1,'a':[2,3]})` → `b'{"a":[2,3],"b":1}'`).

Three things that inspection alone would have got wrong:

- **`__init__.py` must also be trimmed, 152 → 120 lines.** It re-exports four
  credential names and imports `trust` at lines 63–75. Deleting `trust.py` and cutting
  the `refs.py` block while leaving `__init__.py` alone produces a **1,076-line tree
  that raises `ImportError: cannot import name 'ActorCredentialRef'`.** That 1,076 is
  the number naive arithmetic gives (1,503 − 377 − 50); it describes a tree that does
  not import.
- **"the credential half of `refs.py`" is loose language.** Measured, the credential
  block is `refs.py:78–125` — 48 lines, 40 of them
  non-blank, 50 with the separators that go with them: **18% of the file, not 50%.** The other fourteen ref types are credential-free, `ActorRef` included.
  Repeating "half" would overstate the removal by ~86 lines.
- **The dependency direction is favourable.** `trust.py:11` imports *from* `refs.py`;
  `refs.py` contains no occurrence of the string `trust`. No module under
  `domain/shared/` other than `__init__.py` touches either.

Trimmed kernel, file by file: `refs` 222, `canonical` 158, `ids` 147, `__init__` 120,
`sources` 109, `events` 77, `time` 75, `digests` 53, `transcript` 33, `errors` 25,
`text` 25.

### Why this code is worth keeping at all

Outside its own package, the domain layer imports **nine module roots and nothing
else**: `__future__`, `dataclasses`, `decimal`, `enum`, `hashlib`, `json`, `re`,
`typing`, `unicodedata`. Internal `heritage_production.domain.*` imports are permitted
by name in the firewall's own predicate.
Zero third-party imports, enforced over the real tree by
`test_domain_uses_only_standard_library_imports`
([`test_architecture.py:145`](../../tests/heritage_production/test_architecture.py#L145))
against `sys.stdlib_module_names`. (Line 133 is that rule's own predicate test, which
never opens a source file.) RFC 8785 canonicalization is hand-implemented in
[`canonical.py`](../../src/heritage_production/domain/shared/canonical.py); `rfc8785`
appears only in tests, as an independent oracle.

Identity is also the thing the two live flows have actually disagreed about — §4.1 of
the corpus-ledger spec records the two stores holding different string identities for
the same bytes. That was fixed in `a89910d`, and both now produce what this kernel
produces. Rewriting it means rewriting the one solved problem in the area.

### Corrections this record makes to existing documents

- **§12.1 of the corpus-ledger spec says "roughly 1,500 move into the ledger as the
  shared kernel."** That is the untrimmed `domain/shared` figure and contradicts §12
  Task 2's own "minus `trust.py` and the credential half of `refs.py`" in the same
  table. The measured figure is **1,044**. This ADR supersedes the 1,500.
- **§12 Task 1 reads "Its packaging and architecture-test approach is the template for
  `corpus_ledger`."** `src/corpus_ledger/` was never created — `ls src/` returns only
  `heritage_production` — because the ledger was deferred by AMENDMENT A3. Decision 2
  above redirects that template to the new package.
- **`SHELVED.md` says "656 tests"; the source contains 655 `def test_`.** Both are
  right and this is not a defect. `unittest` collects 656; the extra is
  `ProductionApprovalStateMachine.TestCase.runTest`, synthesised by Hypothesis from
  [`test_production_properties.py:79`](../../tests/heritage_production/test_production_properties.py#L79).
- **`SHELVED.md`'s "roughly 55 seconds" is mis-scoped.** It covers the entire `tests/`
  tree, not this package's own suite, and Hypothesis settings make it machine- and
  seed-sensitive. On 2026-08-31, the exact measured repository-wide command,
  `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`, ran 799 tests in
  858.415 seconds and ended with 13 import errors because the shelved application modules
  are absent. That measurement is why Decision 5 names the active roots instead of
  advertising repository-wide discovery.

### What the reference changed

A working TypeScript DDD codebase (`ticket-to-lord`, studied 2026-08-29) uses a pattern
that is strictly better than what this package does, and it costs the kernel 17 lines:

**Transitions return their events; they never accumulate them.** Its aggregate does
`finalize(shortlist) -> {finalized, shortlistGenerated}` — the handler receives the
events as the return value and dispatches after commit. This package instead has
`AggregateEventRecorder` with `_pending_events` and `pull_events()`, drained by
`_publish()` in every handler. Under the reference's shape, forgetting to drain is a
**type error**; under this one it is a silent dropped event, and correctness depends on
every handler remembering to call `_publish`.

Returning the event is also easier to test: the reference's aggregate tests assert on
the returned object with no event-collector spy and no fakes at all.

That is why decision 1 drops the recorder rather than lifting it.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| **Mine it broadly** — also take `edition.py`'s segment lineage, the review model, and the ports as the new backbone | Three reasons, in order of weight. (a) The bulk models demand that does not exist: 5,116 lines of release governance with no rights-holder. (b) `domain/review/` carries a live modelling defect — `findings.py:27` imports `rounds` at module level while `rounds.py` defers four imports of `findings` into function bodies (`:103`, `:157`, `:706`, `:1583`) to dodge the cycle, and `finalize_submission` at `rounds.py:1575` takes `tuple[object, ...]` of whole `ReviewFinding` roots, passing aggregates by object reference with the type erased to hide it. Importing that means inheriting a wrong aggregate boundary and fixing it under its own constraints. (c) `SHELVED.md` states in writing that deferring lineage is free: "Digest-scoped anchors are a strict *subset* of this, so adding lineage later invalidates nothing recorded in the meantime." |
| **Start completely clean** | The kernel is stdlib-only, property-tested, verified to lift, and is the one component both live flows already agree with after `a89910d`. Rewriting it is rewriting a solved problem, worse. The architecture-test approach is also the single mechanism that would stop this rewrite becoming the next shelved package. |
| **Delete the 34,679 lines** | Contradicts the retention principle in §12 of the corpus-ledger spec — *"Nothing is deleted. Everything either moves, is shelved with a **named unfreeze trigger**, or is shelved indefinitely"* — and one trigger is foreseeable: the 2026-08-28 Odia translation scope change makes a second correction pass on a sealed edition plausible within months. Decision 5 removes the recurring cost without removing the option. |
| **Leave it entirely alone, take nothing** | Leaves the new package to re-derive canonical identity, and leaves the rewrite with no architecture firewall — the exact absence this package's own history indicts. |

## 5. Consequences

- **Six of the 655 test methods have the removed code as their whole subject**: `AssuranceTests`
  ([`test_shared_refs.py:73`](../../tests/heritage_production/test_shared_refs.py#L73), 3)
  and `SharedTrustVocabularyTests`
  ([`test_review_trust.py:45`](../../tests/heritage_production/test_review_trust.py#L45), 3).
  `test_review_trust.py` already wraps part of its shared import in `try/except
  ImportError`, so it half-anticipates this split. A further 67 methods across 13 files
  reference the removed symbols incidentally; all sit in production, release and review
  tests this record leaves shelved, so none of them blocks the lift.
- **The review aggregate boundary must be drawn from scratch**, when review is
  eventually needed. This is a gain, not a cost — but it is work that mining would
  have appeared to avoid.
- **The documented default suite changes.** `README.md` names each active discovery
  root and no longer advertises `discover -s tests`. A raw repository-wide discovery
  still means "run everything", including the intentionally shelved suite, and is not
  the supported default.
- **Two published documents now disagree with this one** (§12.1's 1,500, §12 Task 1's
  `corpus_ledger`). §3 above records the corrections; the spec is not edited, per this
  repository's supersession practice.

## 6. Revisit trigger

Per part. The second and third are externally checkable; the first needs a modelling
judgement and is stated as such:

- **Decisions 1–3** — revisit if the new package needs a concept the kernel cannot
  express and that the shelved code already models correctly. Name the concept and the
  shelved file in the superseding ADR.
- **Decision 4** — the four `SHELVED.md` triggers stand unchanged and are the trigger.
  When one fires, a new ADR supersedes this record *for that part only*. Fix the four
  known defects in `SHELVED.md` before unfreezing, not after; the first is CRITICAL.
- **Decision 5** — if the shelved suite becomes part of an active default or CI run,
  record which unfreeze trigger fired and supersede this part rather than widening the
  default silently.

## 7. What this record does not decide

It does not decide the shape of the new domain model, the bounded-context split, or
which flow is restructured first — that is [ADR-0002](0002-one-kernel-two-lifecycle-contexts.md).
It does not authorise deleting anything. It does not fix the four known defects in
`SHELVED.md`, all four of which remain open and all four of which sit in code this
record leaves shelved.
