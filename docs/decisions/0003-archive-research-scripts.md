# ADR-0003 — Archive the 85 research scripts. Ten are live and one is pinned by a test.

**Date:** 2026-08-29 · **Status:** Proposed · **Governs:** `scripts/` (excluding the two production packages)
**Supersedes:** nothing · **Superseded by:** —

> **Revision note, 2026-08-29.** Revised twice. First, an adversarial audit refuted this
> record's original blocking mechanism: sixteen files were said to be pinned by a test,
> and only one is — §3.2 is rewritten and Decision 3 split accordingly. Second, the two
> files left to the steward's judgement were decided: `hi/build_casting_site.py` is
> **live** (§3.1) and `build_graveness.py` **archives**. The census is now
> 10 live / 16 flagged / 85 archive.

---

## 1. Context

Outside the two production packages, `scripts/` holds **15,745 lines** across 111 files.
`cloud/` holds a further **3,056** across 25 files — counted here for scale only, and
governed by no record yet (§7).

Most of `scripts/` is one-off research: `build_*` gallery builders, `score_*`
evaluators, and all of `scripts/hi/` from the Hindi-clone era that the 2026-07-10 voice
pivot superseded. **DDD offers it nothing** — these are research one-offs, not services.
The rewrite in [ADR-0004](0004-clean-room-rewrite-with-cutover.md) does not touch them,
so without a decision they stay in the reading path indefinitely.

Git history cannot be used to sort them. Commit `88d3470` — *"feat: publish source-only
audio workflows (#1)"*, 2026-08-24 — changed **147 files in one commit**, so "recently
modified" is meaningless here. Only
[`odia_transcript_index.py`](../../scripts/odia_transcript_index.py) (`f8a66b6`,
2026-08-27) has a genuine recent individual commit. **The census below was done by
reading imports and documents, not by date.**

## 2. Decision

1. **Archive 85 files, 12,819 lines** — 81.4% of the 15,745 lines in `scripts/` outside
   the two production packages — into `scripts/_archive/`, preserving structure.
   Nothing deleted.
2. **Keep 10 files, 1,551 lines, in place.** They are live (§3.1).
3. **Handle the remaining 16 separately:**
   - **3a.** `cut_hi_final.py` cannot move until `tests/test_legacy_script_paths.py:41`
     (`from scripts import cut_hi_final`) is fixed **in the same commit**.
   - **3b.** The other fifteen move with the bulk (§3.2 explains why they are not blocked).
4. **Rewrite none of them.** Not one becomes part of the new package.
5. **Relocate the ~11 MB of untracked research dumps at repository root** into
   `docs/aws-evaluation/evidence/`, or `.gitignore` them. Independent and cheap.

## 3. Evidence

### 3.1 The ten that are live — 1,551 lines

Two are **hard module-level dependencies of the production packages** — the only two
`from scripts` imports in either package. Archiving either breaks a running programme:

| Script | Lines | Why it is live |
|---|---:|---|
| [`enhance_diagnose.py`](../../scripts/enhance_diagnose.py) | 377 | `youtube_enhance/diagnostics.py:22` — module-level `from scripts import enhance_diagnose as legacy_diagnostics`; 7 distinct functions across 8 call sites at `:221–257` |
| [`voice_quality.py`](../../scripts/voice_quality.py) | 163 | `youtube_enhance/gates.py:14` — module-level `from scripts.voice_quality import vq_feats`, called at `gates.py:256`. `gates.py` is the fail-closed objective veto |
| [`repo_paths.py`](../../scripts/repo_paths.py) | 17 | Imported by 16 scripts — exactly the sixteen in §3.2 — and by `tests/test_legacy_script_paths.py:30` |
| [`enhance_youtube_lecture.py`](../../scripts/enhance_youtube_lecture.py) | 12 | Subprocess-invoked as a real test at `tests/youtube_enhance/test_cli.py:79` |
| [`odia_transcript_index.py`](../../scripts/odia_transcript_index.py) | 165 | Programme 1 (daily). Named twice in `odia-dual-output-system-design-2026-08-28.md` (`:229`, `:251`) and shipped as AMENDMENT A6 item 5 |
| [`fetch_idt.py`](../../scripts/fetch_idt.py) | 126 | Programme 1. Named as *next action item (3)* in the corrections doc, with a live bug at `:43` — **"It cannot enumerate the Odia corpus as written."** |
| [`analyze_source.py`](../../scripts/analyze_source.py) | 72 | Programmes 1–2. One of three tools named as "doing most of this" for intake stratification |
| [`spectral_inspect.py`](../../scripts/spectral_inspect.py) | 137 | Programme 1, same triage sentence |
| [`build_odia_check_site.py`](../../scripts/build_odia_check_site.py) | 276 | Programme 2's only instrument for its human quality gate. The evaluator does not speak Odia, and `odia-asr-and-intelligibility-metrics-2026-07-31.md` closed off the two substitutes actually proposed — ASR round-trip WER and intrusive metrics (STOI/ESTOI/SIIB) — while leaving SRMR-CI uninvestigated. `site-odia-check/README.md` carries a present-tense instruction to run it |
| [`hi/build_casting_site.py`](../../scripts/hi/build_casting_site.py) | 206 | Programme 5, expected within 1–2 months of 2026-08-26. `site-casting/README.md` carries a present-tense run instruction *word-for-word the same shape* as `site-odia-check/README.md`. Identical evidence to the row above; treating the two differently would be indefensible. Costs are asymmetric — wrongly archiving it costs friction at the moment programme 5 starts, wrongly keeping it costs one file |

**That the two production packages import loose scripts at module level is itself a
finding.** The packages are not cleanly separable from `scripts/` today, which is why
this is done deliberately rather than with a bulk `git mv`.

### 3.2 The sixteen not covered by the bulk move

**Only one is genuinely pinned.** `tests/test_legacy_script_paths.py:41` does
`from scripts import cut_hi_final`, which fails the moment that file moves.

**The `LEGACY_SCRIPTS` tuple does not block anything**, contrary to this record's first
draft. `test_repository_and_data_roots_resolve_from_every_script_location` builds
`script = REPOSITORY_ROOT / relative_path` from a hardcoded **string** and passes it to
`repository_root()`, whose `Path.resolve()` is non-strict and succeeds on paths that do
not exist. The test never touches the filesystem, so it passes unchanged after the move.
The sixteen files it names can move freely — fifteen of them under Decision 3b, and
`cut_hi_final.py` under 3a.

The sixteen: `calibrate_gate.py`, `calibrate_gate2.py`, `predictiveness.py`,
`predictiveness2.py`, `cut_hi_final.py`, and `hi/`'s `analyze_diary.py`,
`expressive_refs.py`, `funnel_diary.py`, `funnel_v3.py`, `reconcat_diary.py`,
`refsweep_score.py`, `ref_shortlist.py`, `score_comb.py`, `score_expr.py`,
`score_hi_clones.py`, `score_v1.py`. §7 of the corpus-ledger spec says "Freeze them" for
the `score_*` / `predictiveness*` / `calibrate_gate*` group, and puts `scripts/hi/` under
the 2026-07-10 pivot as *"superseded … Runnable history"*.

**Both judgement calls are now decided** (2026-08-29):

- [`build_graveness.py`](../../scripts/build_graveness.py) (163) — **archives.** Imported
  by `voice_quality.py:133` but **only inside `_selftest()`**, so the live `vq_feats` path
  does not pull it. Flagged originally because it greps as a transitive dependency.
- [`hi/build_casting_site.py`](../../scripts/hi/build_casting_site.py) (206) — **stays
  live**, promoted to §3.1. See that row for the reasoning.

### 3.3 The remainder — 85 files, 12,819 lines

Gallery builders, scorers, calibration sweeps, and the Hindi-clone lineage. No import
from either production package, and no current programme.

**They are not undocumented.** §7 of the corpus-ledger spec names several by filename —
`fetch_lecture.py`, `triage_lectures.py`, `propose_segments.py`, `recut_segments.py`
("intake and measurement. They feed the ledger"), plus `seed_ablation.py`,
`find_calm_ref.py`, `ref_denoise_ab.py`. That section was written for a ledger
AMENDMENT A3 then deferred, so the roles it assigns are unfilled — but a future reader
should know these were considered, not overlooked.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| **Leave everything as it is** | Keeps 15,745 lines — the largest single readability problem outside the shelved package — in the reading path, and it is the one problem here that costs almost nothing to fix. |
| **Rewrite them into the new package** | Research one-offs, not services. Folding them in imports 12,656 lines of dead vocabulary into a package whose purpose is legibility. |
| **Delete them** | Contradicts the README's retention statement, and the retention principle in §12 of the corpus-ledger spec — *"Cutting working code is a write-off, not a saving"* — stated there for `src/heritage_production` and applied here by analogy. Archiving gets the whole readability gain at zero risk. |
| **Bulk `git mv` everything, fix fallout after** | §3.1 and §3.2. Two are module-level imports of the live enhancement pipeline and one is pinned by a test; a bulk move breaks a running programme and the build in the same commit. |

## 5. Consequences

- **`tests/test_legacy_script_paths.py:41` must change alongside `cut_hi_final.py`.**
  Worth asking whether that test still earns its place: its other test asserts a
  property of hardcoded strings and would pass with every file deleted.
- **The two hard dependencies stay in `scripts/`**, so the new package will eventually
  inherit `enhance_diagnose.py` and `voice_quality.py` as real dependencies of
  enhancement, or absorb them properly. This record notes that; it does not resolve it.
- **`build_odia_check_site.py` stays un-packaged** while serving a running programme.
  Untidy and correct.
- **Nothing is deleted**, so the cost of being wrong about any file is one `git mv` back.

## 6. Revisit trigger

- **Anything promoted back out of `scripts/_archive/`** means the census was wrong.
  Record which file and why, and bring it into the new package properly rather than
  running it from the archive.
- **Programme 5 starting** (spec §2: expected within 1–2 months) may pull more of
  `scripts/hi/` back out. `hi/build_casting_site.py` is already kept live in anticipation;
  if nothing else is wanted with it, that was the right call and no action follows.
- **If `_archive/` is still being edited three months from now**, it is not an archive
  and this record is wrong about what these files are.

## 7. What this record does not decide

Whether `enhance_diagnose.py`'s measured O(n^1.79) bug gets fixed is not decided here;
the `np.percentile(rdb, 60)` call sits inside `blind_rt60`'s `while` loop at **`:206`**.
The draft of `odia-design-measured-corrections-2026-08-28.md` cited
`enhance_diagnose.py:192`, which is a docstring line; that reference was corrected to the
actual percentile call at `:206` before the document was published on 2026-09-01. This
record also does not decide whether `fetch_idt.py`'s regex at `:43` gets fixed. Both are
live defects in live scripts and both are out of scope here.

`cloud/` is counted in §1 for scale only and is governed by no record yet — it is
GPU-host tooling with a different lifecycle and deserves its own assessment.
