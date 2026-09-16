# ADR-0013 — Narrator Voice moves to its own repository; transcription and enhancement stay together here

**Date:** 2026-09-16 · **Status:** **Accepted 2026-09-16** · **Governs:** `src/heritage_archive/`, `tests/heritage_archive/`, and the repository boundary between Narrator Voice and the archive flows
**Supersedes:** AMENDMENT A7 ("Separate repository — not yet") of the [corpus-ledger design](../superpowers/specs/2026-08-26-corpus-ledger-domain-design.md), in full · **Superseded by:** —

---

## 1. Context

On 2026-08-26, A7 rejected a separate repository because it "solves none of the problems
found" — the digest-case split, `heritage_production`'s isolation, and absolute paths in
`job.json` — and set one trigger: **"Revisit when one programme has a running pipeline he
would be willing to hand to someone else."**

**That trigger has not fired.** The steward still maintains this codebase alone and has not
proposed handing any programme over. This record does not claim otherwise. It replaces the
trigger, because the problems that now argue for a split are different from the three A7
examined, and handover was never the only reason a repository boundary can pay for itself.

What changed since A7, all measured on 2026-09-16 at `62ce5a5`:

- **Narrator Voice became working code of known shape** — A7's own precondition for a move
  ("working code of known shape rather than a plan"). `src/heritage_archive/` is 62 tracked
  files and 18,359 Python lines; `tests/heritage_archive/` is 52 files and 16,032 lines.
  Task 5M is implemented and smoke-verified with a 195/195 fixture checkpoint
  ([plan](../superpowers/plans/2026-09-07-ssggsm-odia-narration-minimum-local-studio-v1-task-5m-loopback-studio.md)).
- **The Archive context of [ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) was never
  built in new code.** Transcription and enhancement remain `scripts/ggsm_transcription/`
  (2,984 lines) and `scripts/youtube_enhance/` (8,163 lines), both last changed 2026-08-27.
  `heritage_archive`, named for the whole archive, contains only Narrator Voice and the
  321-line kernel that only Narrator Voice imports.
- **The two contexts already live apart in practice**: separate dependency stacks, separate
  virtual environments, and root-level instructions ([`AGENTS.md`](../../AGENTS.md)) that
  are entirely about Narrator Voice.

**What the DDD sources say, checked 2026-09-16.** They lean towards separation but do not
require it:

- Evans ties a context's boundary to its code: "Explicitly set boundaries in terms of team
  organization, usage within specific parts of the application, and physical manifestations
  such as code bases and database schemas"
  ([*DDD Reference*](https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf), p. 2).
- Vernon goes furthest: "There should also be a separate source code repository for each
  Bounded Context" (*Domain-Driven Design Distilled*, 2016, ch. 2). **Checked only through
  secondary quotations, not the book.**
- Fowler's [BoundedContext](https://martinfowler.com/bliki/BoundedContext.html) is silent on
  repositories and allows several contexts within a single application. Microsoft Learn treats
  repository layout as a separate trade-off: "Teams widely use both approaches in production"
  ([CI/CD for microservices](https://learn.microsoft.com/en-us/azure/architecture/microservices/ci-cd)).

So the sources support the boundary; the decision to make it a repository still rests on the
measured costs in §3.

**The relationship between the two contexts is Separate Ways.** Nothing flows between them
today, which is Evans' pattern: "If two sets of functionality have no significant
relationship, they can be completely cut loose from each other. Integration is always
expensive, and sometimes the benefit is small" (*DDD Reference*, p. 37; *Domain-Driven
Design*, ch. 14). If Lane A later narrates archive translations, the relationship becomes
Customer–Supplier over a file format, which works across repositories.

## 2. Decision

1. **Two repositories, not more.** Move Narrator Voice — all of `src/heritage_archive/` and
   `tests/heritage_archive/` — into a new repository named `narrator-voice`. Transcription,
   enhancement, the shelved `heritage_production`, the Hindi clone work and the research
   scripts stay in `voice-cloning`. Transcription and enhancement are not separated from each
   other, and Lane A does not get its own repository.
2. **Code moves; documents are copied.** Copy the 34 `docs/` files reachable by relative
   links from `AGENTS.md` and the narration records (§3.3), plus `docs/decisions/README.md`
   and `TEMPLATE.md`. Delete no document from this repository. In the new repository, the
   25 link targets that stay here — 24 code paths and `src/heritage_production/SHELVED.md` —
   become permanent links to this repository at the commit the split starts from.
   `AGENTS.md` moves; this repository gets a new, archive-scoped one.
3. **Keep Narrator Voice's history; never rewrite this repository's.** Extract with
   `git filter-repo` on a new clone made with `git clone --no-local`, keeping only the paths
   in decision 2 via `--paths-from-file`. Never use `--force`. The tool runs through the
   already-installed `uv`, which its `INSTALL.md` documents, and is added to no project venv;
   running it still needs the steward's approval at that step. If declined, the fallback is
   one import commit that names the source commit. This repository keeps its full history
   either way.
4. **Verify the new repository before removing anything here.** From a new venv with
   `pip install -e ".[narrator]"`, the new repository must pass the Task 5M focused checkpoint
   (195 tests, including `tests.heritage_archive.test_architecture`), `serve --help` and
   `doctor --help`. Only then does decision 5 run.
5. **Remove moved code from this repository in one ordinary commit on a branch** — no history
   rewrite. That commit removes `src/heritage_archive/` and `tests/heritage_archive/`, removes
   the `narrator` extra and its package-data entry from `pyproject.toml`, drops
   `tests/heritage_archive` from the README's default suite, and replaces the README's
   narration sections with a pointer to the new repository.
6. **The kernel moves with its only consumer.** Nothing is published as a shared package. When
   the Archive rewrite ([ADR-0004](0004-clean-room-rewrite-with-cutover.md)) needs canonical
   JSON, digests or opaque IDs, it copies them and both repositories pin the copies with the
   same test vectors: the same bytes give the same lowercase digest string, and the same value
   gives the same canonical JSON bytes.
7. **The import package keeps its name; the archive will not reuse it.** Narrator Voice's
   import package stays `heritage_archive` through the split — renaming it touches 84 source
   and test files. When ADR-0004 is revisited, the archive rewrite chooses a different import
   package name, and that record restates the start-commit path in ADR-0007 §2.4, which today
   names `src/heritage_archive/contexts/archive/`. ADR numbers 0001–0013 keep their meaning in
   both repositories; from 0014 each repository numbers its own records, and a citation across
   repositories names the repository (`narrator-voice ADR-0014`).
8. **The new `pyproject.toml` declares only what Narrator Voice uses**: distribution name
   `narrator-voice`, the `narrator` extra, no `dev` extra, and no base `cryptography` dependency
   (§3.4). The old distribution name `heritage-archive` stays with this repository; its only
   check is the shelved `tests/heritage_production/test_packaging_and_cli.py:53`.
9. **Nothing leaves this machine without separate approval.** Creating a private GitHub
   repository, pushing either repository, and removing the
   `.worktrees/narrator-voice-production-v1` worktree are each approved separately.
10. **Rename `voice-cloning` to `lecture-archive`.** After decision 5 the repository contains
    no voice cloning, so its name misleads. `lecture-archive` names what remains — lecture
    transcription and audio enhancement — and, unlike `heritage-archive`, cannot be mistaken for
    the home of the `heritage_archive` package that now lives in `narrator-voice`. `ggsm-archive`
    was rejected because the Haladhara Swami Odia work lives here too. How to rename:
    - **Rename only after decision 5 lands**, so the name describes what remains.
    - **Rename the GitHub repository and the local folder in the same session.** GitHub
      redirects web traffic and `git clone`, `git fetch` and `git push` from the old name,
      except project site URLs, and warns that creating a new repository under the old name
      breaks those redirects
      ([GitHub Docs](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)).
      Never reuse `voice-cloning` for another repository; the permanent links of decision 2
      depend on the redirect.
    - **The local folder rename is the costly half**, because the absolute path is stored in:
      the `.venv` editable install
      (`.venv/Lib/site-packages/__editable__.heritage_archive-0.0.0.pth`); both sides of the
      worktree link (`.worktrees/narrator-voice-production-v1/.git` and
      `.git/worktrees/narrator-voice-production-v1/gitdir`); Claude Code's project memory
      folder, which is keyed by path; and 2 of the 3 local `job.json` files — both archived
      enhancement jobs under `data/enhance/archive/`. The Zurich transcription job that
      ADR-0004 §5.1 clause (a) regresses against contains no absolute path.
    - **Do the folder rename together with rebuilding the enhancement environment** (§5), so
      the virtual environments are recreated once, not twice.
    - The rename, like decision 9's actions, needs separate approval.

## 3. Evidence

### 3.1 For the split

| Measurement | Result | How measured |
|---|---|---|
| Python imports between Narrator Voice and the rest of the repository, either direction, source and tests | **0** | `grep` for `heritage_archive` / `heritage_production` imports under `scripts/`, `cloud/`, `colab/` and archive tests; for `scripts.` and `data/` under `src/heritage_archive/` and `tests/heritage_archive/` |
| Commits since 2026-07-18 touching more than one code area | **1 of 134** — `88d3470`, the 2026-08-24 publication commit (#1) that added 147 files at once, not a change spanning areas | `git log --name-only`, paths classified per area |
| Files renamed into Narrator Voice or narration-doc paths from elsewhere, all branches | **0**, so a path filter keeps complete history | `git log --all -M --diff-filter=R` |
| Commits touching Narrator Voice code or the 27 narration seed documents | **66**, 2026-08-30 (`af9196c`) to 2026-09-09 (`0a00936`) | `git log -- <paths>` |
| Dependency stacks | Narrator Voice: `httpx`, `defusedxml`, `starlette`, `uvicorn`. Enhancement: `torch==2.0.1`, `DeepFilterNet==0.5.6`, `librosa`, `numpy==1.26.4`. Transcription: `faster-whisper` | `pyproject.toml`, `requirements-enhance-windows.txt`, `requirements-transcribe-windows.txt` |
| Declared dependency conflict inside one project file | `pyproject.toml:24` pins `build==1.5.0` in the `dev` extra; `requirements-enhance-windows.txt:5–6` says not to install it beside DeepFilterNet ("DeepFilterNet 0.5.6 requires packaging<24.0") | direct reading |
| Root agent instructions | All three `AGENTS.md` sections (lines 3, 27, 58) are Narrator Voice rules, loaded by every agent session on transcription or enhancement | `grep -n "^## " AGENTS.md` |
| Kernel consumers | `src/heritage_archive/kernel/` (321 lines) is imported only by Narrator Voice, its composition root and its tests | `grep -r "heritage_archive.kernel"` |

### 3.2 Against the split, or weaker than it looks

| Observation | Weight |
|---|---|
| **A7's handover trigger has not fired.** | This record replaces a stated trigger rather than meeting it. That is a real cost to the discipline in [`README.md`](README.md): a trigger should not be swapped because a new argument appeared. §6 gives the replacement a falsifiable test so the swap can itself be judged wrong. |
| **History weight is a minor factor.** The pack is 2.05 GiB, 1,554 MB of it blob content under `data/`. | Narrator Voice runs on one local Windows machine and is rarely cloned. Pods clone the *archive* side, which keeps the heavy history. The saving is real but small. |
| **The strongest alternative keeps one repository**: per-directory instruction files, one venv per flow, per-flow `pyproject` extras. | It addresses the instruction bleed and the dependency collision. It does not give each product its own root `README`, `pyproject.toml`, branch and worktree list, or Claude Code project memory, and with zero shared changes (§3.1) the single repository buys nothing in return. Rejected in §4, narrowly. |
| **One maintainer keeps two of everything**: `README`, `AGENTS.md`, venv set, memory folder. | Ongoing cost is low while changes never span both (§3.1); §6 turns that into the trigger. |
| **Cross-repository links**: 25 link targets. | One-time rewrite to permanent links (decision 2). |

### 3.3 Document link closure

Starting from 27 seed documents — `AGENTS.md`, ADR-0006 to ADR-0012, the 2026-08-31 and
2026-09 narration specs, the 2026-09 narration plans, both `narrator-voice-*` audits, the
Cartesia contract snapshot and the Task 5M handoff — following relative Markdown links
reaches **36 documents**. The nine pulled in are ADR-0001 to ADR-0005,
`docs/external-audio-assets.md`, `docs/handoff-voice-pivot-2026-07-10.md`, the corpus-ledger
design and `src/heritage_production/SHELVED.md`. Excluding `AGENTS.md` (moved) and
`SHELVED.md` (linked, not copied) leaves the **34 `docs/` files** of decision 2. Those
documents also link **24 code paths** outside Narrator Voice: 16 under `scripts/` (two of
them the `ggsm_transcription` and `youtube_enhance` folders), 3 under
`src/heritage_production/` and 5 under `tests/heritage_production/`.

### 3.4 Unused dependencies in the shared `pyproject.toml`

`cryptography==50.0.0` is the only base dependency. Nothing under `src/` or `tests/` imports
it; its only occurrences are two assertions in the shelved
`tests/heritage_production/test_packaging_and_cli.py` (lines 55, 74) that check the declared
list itself. It arrived with `6af4bf1` ("Add Heritage Production foundation"). Narrator Voice
tests use neither `hypothesis` nor `rfc8785`, the `dev` extra's other members. This
repository's `pyproject.toml` keeps both unchanged so the shelved test is not disturbed.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| **Keep one repository (A7 stands)** | The collisions in §3.1 are already being worked around by hand — a root `AGENTS.md` scoped to one programme, a `pyproject.toml` whose `dev` extra must not be installed in the enhancement venv, and a README default suite whose enhancement tests no current venv can import (§5). |
| **One repository, made tidier** — nested instruction files, one venv per flow | The strongest option (§3.2). It fixes instruction bleed and dependency collision, but leaves one root `README`, one `pyproject.toml` declaring both worlds, one branch list, and one Claude Code memory folder mixing all programmes. With no change ever spanning both, keeping them together has no offsetting benefit. |
| **One repository per programme** (transcription, enhancement, narration, …) | Contradicts [ADR-0002](0002-one-kernel-two-lifecycle-contexts.md) §6: transcription and enhancement are one context with two aggregates. The only test covering both flows, `tests/youtube_enhance/test_digest_case.py`, guards the digest-case fix from `a89910d`; separate repositories would lose it. |
| **Separate repository for Lane A** | [ADR-0009](0009-share-narration-mechanics-not-policy.md) §2.3: lanes are policy scopes of one context. Lane A is not built. |
| **Publish the kernel as a versioned package now** | It has one consumer. [ADR-0005](0005-code-layout-rulebook.md) §5: a kernel symbol graduates only when it crosses two contexts. Evans also warns that a shared kernel is "a very intimate interdependency" that needs "a continuous integration process that will keep the kernel model tight" (*DDD Reference*); across two repositories with no CI, the shared test vectors of decision 6 are the lightweight substitute. |
| **Move the documents instead of copying them** | Documents that stay here link to narration documents — the ADR index alone links the v4 design and its plan — and the narration documents link back to ADR-0001 to ADR-0005 and the corpus-ledger design (§3.3). Moving either side breaks links in the other. |
| **Rewrite this repository's history to drop the media** | Every commit hash cited in its ADRs, plans and `AGENTS.md` would stop resolving, and the published `origin/main` would need a force-push. |
| **Import without history** | Kept as the fallback in decision 3, not rejected: it avoids a new tool, but loses `git log` and `git blame` on 34,391 lines in the repository where they are maintained. |

## 5. Consequences

- **A7 is superseded in full.** The corpus-ledger design is not edited, per this repository's
  supersession practice.
- **Every change to Narrator Voice happens in the new repository** once decision 5 lands. The
  `feature/narrator-voice-production-v1` branch and its worktree here become obsolete.
- **Commit hashes in the new repository differ from those cited in its copied documents**
  (`0a00936`, `3f6b00b`, …). `git filter-repo` rewrites hashes only in commit messages, never
  in file contents, and leaves a message hash unchanged when it names a commit that was pruned,
  meaning one that touched no kept path. Citations in documents therefore keep the old hashes,
  which stay resolvable in this repository; `.git/filter-repo/commit-map` in the new repository
  translates old to new for every commit that survived.
- **The new repository starts with no remote.** `git filter-repo` removes `origin` after
  rewriting, so the extracted history cannot be pushed back into `voice-cloning` by accident.
  A new private remote is added only under decision 9.
- **The new repository contains only commits that touched kept paths.** `git filter-repo`
  prunes commits that become empty. No file was ever renamed into a kept path (§3.1), so no
  history before a rename is lost.
- **Permanent links need the split commit on `origin`.** Until this repository is pushed
  (decision 9), the 25 rewritten links do not resolve on GitHub.
- **ADR-0009's "extract after characterization" crosses repositories.** Extraction from
  `scripts/ggsm_transcription/` or `scripts/youtube_enhance/` into Narrator Voice is by copy,
  never by import.
- **`heritage_archive` ends up naming the narration package, not the archive.** ADR-0007 §2.4
  defines the archive rewrite's start commit by a path under
  `src/heritage_archive/contexts/archive/`. If the rewrite restarted there, both repositories
  would ship an import package called `heritage_archive`: the two would overwrite each other in
  any shared environment, and the name would mislead in both. Decision 7 moves that choice to
  the ADR-0004 revisit. **That revisit is already due, independent of this record:** ADR-0004's
  2026-09-05 start gate has passed with no archive-context commit on any branch
  (`git log --all -- src/heritage_archive/contexts/archive`), and ADR-0007 §5 says a missed
  gate means ADR-0004 "must be revisited on its own terms".
- **Claude Code project memory is stored per folder.** The new repository starts with none;
  the notes that concern Narrator Voice are copied by hand, and this repository's index stops
  carrying narration state.
- **This repository's README default suite shrinks** to `tests/ggsm_transcription`,
  `tests/youtube_enhance` and `tests.test_legacy_script_paths`.
- **Not caused by this decision, found while measuring it:** no virtual environment in this
  checkout can import the enhancement flow. In `.venv`, both `scripts.youtube_enhance.cli`
  and `tests.youtube_enhance.test_digest_case` fail with
  `ModuleNotFoundError: No module named 'numpy'`; `.venv-1` has no `numpy` either. The README
  still directs the enhancement tests to `.venv`. It needs its own fix and is not part of
  this split.

## 6. Revisit trigger

- **The split was wrong** if, within the first 90 days after decision 5 lands, **three
  separate changes each need commits in both repositories to keep either one working**.
  Record each change and both commits. At the third, write an ADR that either merges the
  repositories or names the shared thing that should have been extracted.
- **A further split of this repository** uses ADR-0002 §7's trigger unchanged: one word needed
  for two different things in new archive code, neither renameable without losing precision.
- **A7's handover condition** — the steward proposes handing a programme to someone else — no
  longer triggers a repository split by itself; it triggers a review of access and ownership
  for that programme's repository.

## 7. What this record does not decide

It does not change any Narrator Voice domain, policy or authorization decision (ADR-0006 to
ADR-0012), authorize a live Cartesia call, start or consume ADR-0004's archive-rewrite clock,
rename the `heritage_archive` package, choose the archive rewrite's package name (decision 7),
purge media from this
repository's history, fix the enhancement environment, or approve creating a GitHub
repository, pushing, or deleting the worktree.
