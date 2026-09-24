<!--
Produced 2026-09-24 by a 21-agent audit of the repository: eight dimensions
(scripts layout, src+tests, docs, data, git health, tooling, duplication, web
artifacts), each surveyed and then adversarially re-verified against the real
tree, plus three external research tracks and a completeness critic.

Every count and path below was reproduced by a second agent before it was
written down. Nothing here has been applied. This is a proposal, not a record
of work done — it is not an ADR and does not govern anything until acted on.
-->

# Reorganizing `lecture-archive` — the plan

## The verdict

**Ranked by what actually costs you time and correctness today:**

1. **The repo already decided how to organize `scripts/` and never executed it.** `docs/decisions/0003-archive-research-scripts.md` (2026-08-29) is the only one of 14 ADRs still marked `Status: Proposed`. It decides: archive 85 files / 12,819 lines into `scripts/_archive/`, keep 10 live, handle 16 separately, delete nothing. `ls scripts/_archive` → does not exist. Every "which of these 91 files is dead?" question you've paid for since August was answered a month ago on paper.
2. **The repo's own entry points are wrong, and one of them repeats a correctness error AGENTS.md says already inverted a result.** README line 32 says "`docs/` keeps what is project state rather than research"; line 59 says "`docs/`: research, architecture, and operational decisions." Line 58 and `scripts/transcript_accuracy.py:351` both label the Indic track "Sanskrit" — the exact conflation AGENTS.md warns about. README documents 4 of 11 test roots and omits every tool built since September. There is no `docs/README.md`; the only runnable command block in the repo sits at line 1252 of a 110 KB handoff and every command in it reads gitignored `data/reference/`.
3. **`.gitignore` is decorative for the largest part of `data/`.** 528 tracked files match a current ignore rule (495 under `data/out`, 11 under `data/hi`, 2 under `data/lectures`, 17 `.firecrawl/*`, 1 stray `.pyc`) — the rules were written after the commits. `git count-objects -vH` → `size-pack: 2.05 GiB`.
4. **Moving any script is more dangerous than it looks.** 18 files under `scripts/` call `shutil.rmtree`; 16 of them compute the target from a position-dependent `ROOT = Path(__file__).resolve().parent.parent` (or `.parent.parent.parent` in `hi/`). A `git mv` one level deeper retargets a recursive delete. `scripts/hi/build_floor_set.py` uses `parents[2]` and deletes `ROOT/"data/hi/floor_speakers"` — moved one level, `ROOT` becomes `C:/Users/Mukul/code/personal-projects/`.
5. **The published archive figure counts the same recording twice.** I verified this directly: `data/lectures/only-he-can-lead-you/audio.mp3` and `.../only-he-can-lead-you-bhubaneswar/audio.mp3` are the same 24,500,393 bytes under the same `aid=1143`, with identical transcripts, and `MIRROR.json` counts both (2,834 words each). A second pair — `cc-adi-lila-9-49-51-…-chaitanya-…` (aid 863) and `ccadi9-49-51-…-caitanya-…` (aid 1652) — is the same 108,967,377-byte recording carrying **two different transcripts** (29,760 vs 45,901 chars), both counted. So `MIRROR.json`'s `usable: 78` and `total_words: 318571` — the numbers commit `bfd0853` publishes as "78 of 100" — are inflated. Separately there are three disagreeing censuses: 99 lecture directories on disk, 100 `MIRROR.json` entries, 112 `lecture_triage.tsv` rows.

---

## What is already good — do not churn it

- **`research/` is the well-maintained half and should be left alone.** 48 nav entries, 48 files on disk, zero orphans, zero missing targets, and the answer-first `index.md` rule holds in all five topics. It is the model, not the problem.
- **`docs/decisions/` is a working supersession chain.** 14 records, flat, never renumbered, with a README that defends its own conventions. ADR-0014 links into the narration set nine times; ADR-0004 and ADR-0005 carry forward `Superseded by:` links. Do not move or renumber any of it.
- **`scripts/youtube_enhance/` is complete and tested** — 17 modules, 17 test files — and `scripts/youtube_enhance/manifest.py` already implements canonical JSON + sha256 cache keys with a test. The provenance primitive you need repo-wide already exists here.
- **The correctness invariants AGENTS.md names are genuinely covered.** `tests/forced_align/test_invariants.py` imports `problems`; `test_tokenising.py` covers `spoken_words`.
- **`meta.json` is uniform** — all 79 files share one 8-key schema and every `slug` equals its directory name.
- **Secrets are clean.** `.env.local` holds five live API keys and `git log --all -- .env.local` returns **0 commits**; it is ignored at `.gitignore:17`. `.hf_token` likewise, 0 commits. You checked nothing and got lucky, but the state is correct.
- **`.agents/workflows/README.md`** is a real index — 7 scripts, each with what it did, its run id and where output landed. Copy its format for `docs/README.md`.

---

## The plan

Six phases. Phase 0 is reversible and touches no code paths. Nothing later depends on a phase that hasn't run.

---

### Phase 0 — Corrections that cannot break anything
**Goal:** stop the repo from lying to you, in one commit, with no moves.
**Effort:** 2–3 hours.

**0a. `.gitignore` — two lines.**
```gitignore
.ruff_cache/
.hypothesis/
```
Both exist on disk right now (`.ruff_cache` 127 KB, `.hypothesis` 269 KB), both return non-zero from `git check-ignore`, both are zero-tracked — so today `git add -A` commits them.

**0b. README — four fixes, one file plus one string.**
- Line 59: replace `` `docs/`: research, architecture, and operational decisions. `` with `` `docs/`: project state — handoffs, decision records, the AWS evaluation, designs and plans. Research lives in `research/`. ``
- Line 58: replace "English and Sanskrit tracks separately" with "English and Indic tracks separately; `scripts.transcript_accuracy.indic_language` splits Indic into Sanskrit and Bengali, which AGENTS.md requires be read apart."
- `scripts/transcript_accuracy.py:351`: change the printed label `Sanskrit/names` → `Indic (Sanskrit+Bengali)`. **Guard:** `grep -rn 'Sanskrit' tests/transcript_accuracy/*.py` hits only docstrings and one assertion *message* (`test_scoring.py:44`) — no test asserts the CLI string. Re-run `.venv\Scripts\python.exe -m unittest discover -s tests/transcript_accuracy -t .` after.
- Lines 44–59: add the components built since September — `scripts/ggsm_transcription/`, `forced_align.py`, `align_lecture.py`, `align_archive.py`, `timing_check.py`, `flex_timed.py`, `transcript_select.py`, `verse_match.py`, `verse_cache.py`, `kksongs_mirror.py`, and `src/heritage_production/` marked SHELVED with a link to its `SHELVED.md`.

Do **not** yet extend the test-root list — that is Phase 2, after you have measured which venv runs which root.

**0c. `src/heritage_production/SHELVED.md` — one false number.** Line 60's "Roughly 55 seconds" is wrong and sends readers hunting in the wrong place. Measured: 16.0s–24.2s for 643 tests. Line 8's "656 tests" is essentially right (655 `def test_` exist); what is false there is "passes" — 16 do not collect because `hypothesis` and `rfc8785` are in none of the five venvs. State both with the command that produced them.

**0d. The one broken markdown link.** `docs/decisions/README.md` → `../odia-dual-output-system-design-2026-08-28.md`. The target now lives at `research/docs/odia/odia-dual-output-system-design-2026-08-28.md`. This is the only broken relative link repo-wide across 135 files.

**0e. Two empty `__init__.py` files.**
```bash
touch scripts/__init__.py scripts/hi/__init__.py && git add scripts/__init__.py scripts/hi/__init__.py
```
Today both import as implicit namespace packages with `__file__ = None`, which means any directory named `scripts` earlier on `sys.path` silently merges in. **Guard:** leave `[tool.setuptools.packages.find] where = ["src"]` exactly as it is. If that is ever changed to `["src", "."]`, `scripts` becomes a top-level distribution package name — a collision hazard in any venv.

**0f. Write down the invocation rule** next to README's test block:
> Everything under `scripts/` is invoked as `python -m scripts.<module>` from the repository root. A bare file path does not work and never has.

Verified both directions: `python scripts/align_archive.py --help` fails **from the repo root** with `ModuleNotFoundError: No module named 'scripts'`; `python -m scripts.align_archive --help` prints the help. The alignment cluster already uses `-m` in `docs/handoff-ssggsm-corpus-pipeline-2026-09-21.md:1253,1256,1397,1398` and two research pages.

**0g. `rm -rf '%localappdata%'`** — it contains exactly one file, `%localappdata%/Netspark/logs/NsGUI.log` (148 KB), from a third-party content filter that expanded an environment variable wrongly. Nothing to do with this project.

**Verify Phase 0:** `git status` shows only the files you edited; `.\.venv\Scripts\python.exe -m unittest discover -s tests/transcript_accuracy -t .` passes; `python -m scripts.align_archive --help` prints help.

---

### Phase 1 — Make the repo findable: two README files
**Goal:** the facts exist; they are unreachable. Put them where you already look.
**Effort:** 3–4 hours. **New tool:** none.

**1a. `docs/README.md`** — modelled on `.agents/workflows/README.md`, ~150 lines, four sections:

1. **Where things are** — one row per top-level directory: what it holds, and whether it is live, shelved or frozen history. Include the honest note that **28 of the 56 markdown files under `docs/` are Narrator Voice history** whose maintained copies live in the `narrator-voice` repo under ADR-0013. *(Use 28, not 27 — the filename grep that yields 27 misses `docs/decisions/0008-lane-b-production-boundaries.md`, which is a narration ADR.)*
2. **How do I…** — the task table, lifted verbatim from the handoff's tool table at lines 1239–1249 and its command block at 1252–1265. **Label every one of those commands `owner-only`**: they all read `data/reference/`, which `git check-ignore -v` reports ignored at `.gitignore:111`. None of them runs on a fresh clone.
3. **Which venv** — the table that exists nowhere today. `.venv-indic` — the environment forced alignment and timing checks need — appears in exactly three markdown files and in neither README nor AGENTS.md. Rows: `.venv` (enhancement, `requirements-enhance-windows.txt`), `.venv-transcribe` (faster-whisper), `.venv-indic` (alignment + timing — torchaudio 2.11), `.venv-api`, `.venv-1`, and `research/.venv` (mkdocs, already documented at README:24–29).
4. **Superseded material still at the repo root** — one line each for `voice-cloning-research.md`, `tts-dataprep-pipeline.md`, `finetune-plan.md`, `spectrogram-triage.md`, `learning-path.md`: June-2026 voice-clone work superseded by the 2026-07-10 pivot, **staying where they are** because seven live prose references point at them by bare filename (`scripts/ecapa_score.py:2`, `scripts/prep_trial.py:32`, `cloud/HANDOFF.md:9,10,41`, `cloud/LIGHTNING_SETUP.md:16,69` — and `:16` is a *runnable git command*). Prepend each the same `!!! danger "History — superseded on 2026-07-10"` banner `research/docs/voice-cloning/index.md` carries.

Then one line in README: `New here? Start at [docs/README.md](docs/README.md).`

**1b. `data/README.md`** — a row per subdirectory with a **tracked-or-ignored** column, which is the single most useful fact about that tree. Verified tracked counts: `diary` 1, `enhance` 1, `hi` 11, `lectures` 229, `narration` 12, `out` 519, `transcribe` 0 (untracked and *not* ignored); `models`, `reference`, `research` all ignored. Plus the lecture-directory contract (`audio.mp3` + `meta.json` + `transcript.txt`), what `MIRROR.json` indexes, and what `lecture_triage.tsv`'s 13 columns mean.

**Guard:** verify the lecture contract against at least five directories *including one of the ~59 currently untracked ones*, not from `docs/superpowers/specs/2026-08-26-corpus-ledger-domain-design.md` — which is today the only markdown that mentions `data/lectures` at all, and is the design for a package `SHELVED.md` declares dead.

**Flag, do not fix:** `data/research/` is gitignored, holds 21 untracked research notes across 6 topics, and four maintained research pages cite into it — e.g. `research/docs/transcription/commercial-asr-survey-2026-09-22.md:10` cites `data/research/commercial-asr-2026-09/workflow-result-wf_659d3dd8-130.json`, and all 7 entries in `.agents/workflows/README.md` route output there. Two of the six topics have no `research/` page at all. Say so in `data/README.md`; do not change `.gitignore`.

**Verify:** open `docs/README.md` and run three commands from it end to end.

---

### Phase 2 — One test command, honest environments
**Goal:** `python -m pytest` runs the active suite; every environment is reproducible.
**Effort:** 2–3 hours. **New tool:** pytest (runner only — no test file is rewritten).

**Order inside this phase matters. Freeze first.**

**2a. Freeze `.venv-indic` before anything installs into anything.**
```powershell
.\.venv-indic\Scripts\python.exe -m pip freeze > requirements-align.txt
```
Confirm it pins `torchaudio` at 2.11.0. `torchaudio.functional.forced_align` does not exist in the 2.0.2 that `requirements.lock.txt:66` pins — verified: `.venv` has 2.0.2+cpu (`hasattr` → False), `.venv-indic` has 2.11.0+cpu (True). `tests/forced_align` is 17 errors in `.venv` and 63/63 green in `.venv-indic`, and no requirements file describes `.venv-indic`. Put a header comment in the file: *Windows-only, single-machine record of what works — not a portable contract.*

**Do not** bump `torchaudio` in `requirements.lock.txt`. The enhancement stack in `.venv` is pinned against 2.0.2 and `tests/youtube_enhance` (274 tests) runs there.

**2b. Adopt pytest as a runner.** Add `requirements-dev.txt` with one line (`pytest==9.1.1`, or whatever `pip install pytest` resolves to on the day) and **one** block to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = [".", "src"]
testpaths = ["tests"]
addopts = "-ra --ignore=tests/heritage_production"
```

Measured against the real tree with pytest 9.1.1:
- `pytest --ignore=tests/heritage_production tests` → **615 tests collected** — exactly the active count.
- `pytest tests/heritage_production` → **639 collected, 4 errors** — an explicit path still runs the shelved suite, so `--ignore` in `addopts` does not block deliberate invocation. That is ADR-0001 decision 5 expressed as a fact the tool reads.
- Whole tree → 1,254 collected, no import shadowing, despite `test_cli.py` existing twice — because every `tests/<root>/` has `__init__.py` today. **That is the load-bearing dependency: do not remove any of them.**

`testpaths = ["tests"]` (not an enumerated list of 11 roots) is the point — a new `tests/<root>/` is picked up automatically. An enumerated list is the same hand-maintained thing that drifted to 4 of 11 in README. `testpaths` is also load-bearing for a second reason: `scripts/hi/clone_test.py` and `scripts/hi/markup_test.py` match pytest's default `*_test.py` glob, contain zero `def test_`, and call `VoxCPM.from_pretrained(...)` at module level — a bare `pytest` at the root without `testpaths` would try to import them.

`-ra` earns its place: there are 19 `skipTest`/`skipUnless` sites across the active suite (symlink/junction privilege, gitignored local reference files) and today a run prints OK with no sign which silently skipped.

**2c. Update the three drifted places in the same commit.** README has **two** command blocks (lines 88–99, a PowerShell `$testRoots` array, and lines 113–116, a bash loop) plus prose at 121–124. `src/heritage_production/SHELVED.md:66-72` needs the pytest form added (keep the unittest form — it stays valid). `docs/decisions/0001-…:62-67` states a third, stale version of the active suite naming `tests/heritage_archive/`, which no longer exists — an ADR is a dated record, so add a dated amendment line, don't rewrite it.

**2d. Revive the 16 dead shelved tests** with the route already declared in `pyproject.toml`: `pip install -e .[dev]` (that extra already pins `hypothesis==6.165.10` and `rfc8785==0.1.4`, and `SHELVED.md:62` names it as its reason for existing). **Tell me which venv before you run it** — it also drags in `cryptography==50.0.0`, which is absent from `.venv`, `.venv-indic` and `.venv-transcribe`.

**2e. Close the one real coverage gap.** `scripts/align_archive.py` is tied for most-changed script of the fortnight (6 commits), produces the figures the last three commits publish, and no test imports it. It **imports cleanly under the plain `.venv`** (torch is present; `torchaudio.functional.forced_align` is only reached at call time), so these tests need no new environment. Add `tests/align_archive/__init__.py` and `test_accounting.py` covering the three pure functions — `audio_accounted_for` (:225), `stops_early` (:244), `report` (:260) — with hand-built word-span lists: full coverage, a transcript ending at 60%, empty, a single word, spans that violate ordering. **Every expected value must be computable by hand from the inputs, stated in a comment** — never asserted against a previous run's output, which AGENTS.md rules out as agreement-not-accuracy. Leave `align_prose` (:59) to a second slice; it needs a tensor fixture.

**Verify:** `python -m pytest` → 615+ passing; `python -m pytest tests/heritage_production` → 639+.

**Optional, owner decision:** `scripts/ggsm_transcription/store.py:557 _assert_safe_directory` walks every lexical ancestor up to `C:\` on every call — 50,329 calls and 2,279,730 `nt.stat` calls in `test_asr_inspection` alone, and the same pattern (87,300 calls, 3,908,798 stats) in `test_review_delivery`. Bounding the walk at `self.data_root` was measured on the real suite via monkeypatch: **294.4s → 123.3s, 132/132 green**. That is 2.4× and ~2 minutes — *not* the "well under a minute" an earlier survey claimed. It narrows a reparse-point security boundary and ADR-0014 §6 trigger 2 counts behaviour-changing commits to `store.py`, so this is a decision, not a refactor. See Open Questions.

---

### Phase 3 — Make git and the corpus census tell the truth
**Goal:** the index matches the ignore rules; the published archive number is correct.
**Effort:** 2 hours + 2–3 hours.

**3a. Untrack the 528.** First, check citations — `git grep -ln 'data/out/lecture1' -- '*.md'` returns exactly three files: `cloud/TRAINING.md` (3 hits), `research/docs/hindi/hindi-clone-plan.md`, `research/docs/voice-cloning/identity-verification.md`. Update those three to say the artifacts are local-only, then:

```bash
git ls-files | git check-ignore --no-index --stdin > /c/Users/Mukul/AppData/Local/Temp/claude/.../tracked-ignored.txt
# review it: 495 data/out, 11 data/hi, 2 data/lectures, 17 .firecrawl/*, 1 scripts/__pycache__/*.pyc
git rm --cached --pathspec-from-file=<that file>
```
`--cached` removes them from the index and **leaves every byte on disk**. One reviewable commit. This removes ~356 MB from every future clone's working tree and makes `git status` mean something.

Note: `git check-ignore` *without* `--no-index` reports 0, which is why this is easy to miss.

**This does not shrink `.git`.** The 2.05 GiB pack is those blobs in history, and removing them is a `git filter-repo` force-push that invalidates every existing clone. See Open Questions — do not do it as part of this phase.

**3b. Resolve the duplicate recordings.** I verified both pairs directly:

| pair | audio | aid | transcript |
|---|---|---|---|
| `only-he-can-lead-you` / `only-he-can-lead-you-bhubaneswar` | identical, 24,500,393 B | **both 1143** | identical, 16,733 chars |
| `cc-adi-lila-9-49-51-…-chaitanya-…` / `ccadi9-49-51-…-caitanya-…` | identical, 108,967,377 B | 863 / **1652** | **29,760 vs 45,901 chars** |

133.5 MB duplicated. `MIRROR.json` counts both members of both pairs (`usable: 78`, `total_words: 318571`). The first pair is an unambiguous delete-one. The second is a source-side question — two published transcripts for one recording — so **diff them, keep one as canonical, and record the other** in `data/lectures/DUPLICATES.tsv` (`canonical_slug, duplicate_slug, aid, audio_sha256, reason`). Then recompute `usable` and `total_words`. AGENTS.md's rule that a figure must say what it is applies directly: "78 of 100" is at most 77 and probably 76 distinct recordings.

**3c. Reconcile the three censuses in the same commit.** 99 lecture directories on disk, 100 `MIRROR.json` entries (99 unique slugs, 97 unique aids — `aid` 1143, 1144, 1137 each appear twice and slug `the-glories-of-sri-gadadhar-pandit` twice), 112 rows in `lecture_triage.tsv`. Pick one as the register of record — `MIRROR.json` is the obvious candidate — and say in `data/README.md` what the other two are and why they differ. Otherwise a deletion in 3b leaves you with a fourth disagreeing number.

**3d. One small guard, no new dependency.** `scripts/fetch_lecture.py:98` writes a 3-key `meta.json`; `scripts/taptajivanam_mirror.py:161` writes the 8-key one. All 79 currently agree by luck. Make `fetch_lecture.py` call the same writer, and add `tests/lecture_meta/test_contract.py` with three assertions: every `meta.json` has the 8 keys; `meta['slug'] == dirname`; no two directories share an `audio.mp3` sha256. That third assertion is the one that would have caught 3b before it entered the corpus. This is AGENTS.md's "smallest coherent regression coverage… for mechanical validation" — not an exhaustive matrix, and no pydantic needed (see Tools).

**Verify:** `git ls-files | git check-ignore --no-index --stdin | wc -l` → 0. `python -m pytest tests/lecture_meta` → green.

---

### Phase 4 — Execute ADR-0003 (the big one)
**Goal:** 85 files leave the reading path without a single silent breakage.
**Effort:** 1–2 days. **This phase starts with a decision, not a command.**

**4a. Put ADR-0003 in front of yourself and Accept, amend, or Reject it.** It is the only unaccepted ADR of 14, it is cross-referenced by ADR-0004 (×3), ADR-0006:139, ADR-0014:153 and `docs/decisions/README.md:35`, and its census was built by reading imports and documents — explicitly refusing git dates, because commit `88d3470` changed 147 files at once. If you reject it, say so in the record and the rest of this phase is dropped. **Nothing below runs until this is decided.**

**4b. Before any `git mv`, run the four gates. In this order.**

**Gate 1 — the recursive-delete gate (this is the one nobody had).**
```bash
git grep -ln 'shutil.rmtree' -- scripts/
```
→ 18 files. 16 of them open with a position-dependent `ROOT`. **No file containing `rmtree` moves unless its `ROOT` line is rewritten in the same commit** to `repository_root(__file__)` (`scripts/repo_paths.py` already provides it, and `tests/test_legacy_script_paths.py` already asserts it resolves correctly from both depths). Three of these do not write into `data/` or `voice_lab/` at all:

```
scripts/build_narration_site.py:20      OUT = ROOT / "site"
scripts/build_odia_check_site.py:43     OUT = ROOT / "site-odia-check"   (rmtree at :101)
scripts/hi/build_casting_site.py:25     OUT = ROOT / "site-casting"      (rmtree at :168)
```
All three target live deploy directories. `scripts/hi/build_floor_set.py` is the worst case: `parents[2]` plus `rmtree(ROOT/"data/hi/floor_speakers")` — one level deeper and `ROOT` escapes the repo entirely.

**Gate 2 — the file-path import gate.** Five modules load siblings by path, which defeats every grep-based census:
```
build_blind_clone_ab.py:43   build_clone_compare.py:34   build_pretest_gallery.py:28
eval_metrics.py:46           score_funnel.py:60
```
all of the form `spec_from_file_location(..., ROOT / "scripts" / "<x>.py")`. This is why `eval_metrics.py` *looks* orphaned and is not. Rewrite these before the move, not after.

**Gate 3 — the live-import gate (ADR-0003 §3.1 already names it).** `scripts/youtube_enhance/diagnostics.py:22` does `from scripts import enhance_diagnose as legacy_diagnostics` and `scripts/youtube_enhance/gates.py:14` does `from scripts.voice_quality import vq_feats` — and `gates.py` is the fail-closed enhancement veto. `voice_quality.py:133` in turn does `from build_graveness import feats`. The production package depends on the flat tree, not the other way round. §3-3a separately requires `tests/test_legacy_script_paths.py:41` (`from scripts import cut_hi_final`) to change in the same commit as `cut_hi_final.py`.

**Gate 4 — the prose-reference gate.** For each file being moved, run
```bash
git grep -n '<basename>' -- '*.md' '*.py' '*.js' '*.json' ':!data/english_words.txt'
```
A markdown link checker is not enough: the dominant reference form in this repo is a **bare filename in prose or in a comment**, at roughly 7-to-1 over real links. Known hits you will find: relative markdown links to `build_graveness.py` and `spectral_inspect.py` **inside ADR-0003 itself**, named references in `docs/superpowers/specs/2026-08-26-…`, `research/docs/voice-cloning/project-findings.md`, `research/docs/hindi/hindi-clone-plan.md`, `docs/aws-evaluation/01-resource-inventory.md:188`, and `.agents/workflows/melbourne-eight-point-measurements.js` — which pins `scripts/transcript_accuracy.py` at lines 21, 71, 151 **and `scripts/reference_editor/retime.py` at line 121**. Any `reference_editor` restructuring updates that JS file too.

**4c. Then move,** in small commits (§3.1's 10 live files stay, §3.2's 16 handled per the record), into `scripts/_archive/` — ADR-0003's own name, not a new one. Add `scripts/_archive/README.md` naming the era (voice-clone and narration work through 2026-07-03), the 2026-07-10 pivot and ADR-0013 as the reason, and stating plainly that these write into gitignored `voice_lab/` or RunPod `/workspace/` paths and are kept as history, not as runnable tools.

**Verify:** `python -m pytest` before and after → same count, same result. Plus `python -m unittest tests.test_legacy_script_paths -v` explicitly. ADR-0003's own falsification test applies: *"anything promoted back out of `scripts/_archive/` means the census was wrong."*

---

### Phase 5 — ruff, F rules only, report first
**Goal:** a linter that starts green and finds real defects, without a five-figure cosmetic diff.
**Effort:** 2 hours. **Runs after Phase 4, never before.**

Linting 85 files that are about to leave the reading path is the standard way a lint adoption dies on day one.

```toml
[tool.ruff]
line-length = 110
target-version = "py311"
exclude = [
    ".venv", ".venv-1", ".venv-api", ".venv-indic", ".venv-transcribe",
    "research/.venv", "site", "site-casting", "site-odia-check",
    "_work", ".worktrees", "colab", "fastbook",
    "src/heritage_production", "scripts/_archive",
]

[tool.ruff.lint]
select = ["F"]
```

`F` only — not `["E","F","I"]`. `F821` (undefined name) and `F811` (redefinition) are real-defect rules. `I` (import sorting) would actively fight the deliberate `sys.path.insert` / `# noqa: E402` ordering in 37 files, and `E` on 30,472 lines of one-person research code is churn.

**First command is report-only, and the output comes to you before anything changes:**
```powershell
ruff check . --statistics
```

**Never run `--fix` across this tree.** `F401` unused-import removal is unsafe here: the five `spec_from_file_location` loads and at least one documented import-order dependency (`scripts/enhance_voice_impact.py:42` comments that librosa submodules must resolve before torch-based encoders) are invisible to a linter, and 82 of 91 flat scripts have no test that would catch a bad removal. Apply fixes by hand, one file at a time, re-running the suite after.

**Do not enable the formatter in the same change.** See Tools.

**Note:** `.ruff_cache/` already exists because a survey ran `uvx ruff` during this investigation. Phase 0a ignores it.

---

## Target layout (after the plan)

```
lecture-archive/
├─ README.md                      # fixed: docs/≠research, Indic not Sanskrit, all current tools,
│                                 #   the `-m scripts.<module>` rule, one pytest command
├─ AGENTS.md                      # unchanged
├─ pyproject.toml                 # + [tool.pytest.ini_options]  + [tool.ruff]
│                                 #   packages.find stays where=["src"] — deliberately
├─ requirements-align.txt         # NEW — frozen .venv-indic (torchaudio 2.11). The gap that
│                                 #   made tests/forced_align unreproducible.
├─ requirements-dev.txt           # NEW — pytest pin
├─ .gitignore                     # + .ruff_cache/  .hypothesis/
│
├─ docs/                          # project state. SHAPE UNCHANGED — on purpose.
│  ├─ README.md                   # NEW — the map: where things are / how do I / which venv /
│  │                              #   what's superseded. Modelled on .agents/workflows/README.md
│  ├─ decisions/                  # 14 ADRs, flat, never renumbered, chain intact.
│  │                              #   0003 now Accepted (or Rejected) — no longer the open one
│  ├─ superpowers/{plans,specs}/  # NOT renamed — 34 files reference this path, one is a test
│  ├─ aws-evaluation/  handoff-*.md  triage/
│
├─ research/                      # the MkDocs site — the good half. Untouched.
│  ├─ mkdocs.yml                  # + strict: true (free — nav is already clean, 48/48)
│  └─ docs/<topic>/index.md       # answer-first, 0 orphans
│
├─ scripts/
│  ├─ __init__.py   hi/__init__.py        # NEW — 2 empty files, ends the namespace-package drift
│  ├─ repo_paths.py                       # the resolver the archived files now use
│  ├─ forced_align.py  align_lecture.py  align_archive.py  timing_check.py  flex_timed.py
│  ├─ transcript_accuracy.py  transcript_select.py  verse_match.py  verse_cache.py
│  ├─ taptajivanam_mirror.py  kksongs_mirror.py  fetch_lecture.py
│  ├─ voice_quality.py  enhance_diagnose.py        # ADR-0003 §3.1 — imported by youtube_enhance
│  ├─ ggsm_transcription/  youtube_enhance/  reference_editor/  hi/
│  └─ _archive/                            # NEW — ADR-0003's 85 files, ROOT lines rewritten,
│     └─ README.md                         #   spec_from_file_location loads fixed
│
├─ src/heritage_production/                # SHELVED, untouched; SHELVED.md numbers corrected
├─ tests/                                  # every test preserved. 615 active + 655 shelved.
│  ├─ align_archive/                       # NEW — the published-figure functions
│  ├─ lecture_meta/                        # NEW — 8-key schema, slug==dirname, no dup audio hash
│  └─ heritage_production/                 # excluded by default, still runs on an explicit path
│
├─ data/
│  ├─ README.md                            # NEW — per-dir: what it is, tracked or ignored
│  ├─ DUPLICATES.tsv                       # NEW — the resolved duplicate recordings
│  ├─ lectures/                            # audio.mp3 + transcript.txt + meta.json, deduplicated
│  ├─ out/                                 # 495 files git rm --cached; bytes still on disk
│  └─ reference/ research/ models/         # ignored, local-only — now documented as such
│
├─ cloud/  colab/  .agents/                # unchanged (but cloud/TRAINING.md:37,49 name two
│                                          #   scripts that do not exist — fix in Phase 1)
└─ fastbook/                               # owner decision — see Open Questions
```

---

## Tools introduced

| Tool | Replaces | Why worth it | Cost |
|---|---|---|---|
| **pytest** (runner only, pinned) | README's PowerShell `$testRoots` array + bash loop, both drifted to 4 of 11 roots | One command. `testpaths=["tests"]` picks up new suites automatically instead of needing a config edit — the exact drift that caused the problem. Collects all 83 `unittest.TestCase` files unchanged. Retires the `-t .` shadowing footgun `SHELVED.md` warns about. Shaped like `npm test`. | One dev dependency in one venv. `-ra` will surface ~19 skips that currently print as silent green — that is the point, but it will look worse before it looks better. |
| **ruff** (`select=["F"]`, report mode) | nothing — there is no linter today | `F821`/`F811` are real defects across 647 never-checked imports. Single pinned binary, one config block, Windows wheels. The closest thing to the eslint step you already know. | Must be scoped (`exclude` five venvs + three `site*` dirs) or it reports tens of thousands of irrelevant hits. Must never be run with `--fix` here. |
| **`.gitignore` + `git rm --cached`** | the 528 tracked-but-ignored files | One command, fully reversible, bytes stay on disk. The stated intent and the index finally agree. | None. Does not shrink `.git`. |

### Considered and rejected

| Tool | Why not |
|---|---|
| **uv** (package manager) | The four profiles are genuinely un-co-resolvable — `.venv` has torch 2.0.1/numpy 1.26.4 with DeepFilterNet pinning `packaging<24`; `.venv-indic` has torch 2.14/numpy 2.4.6. uv resolves everything into **one** `uv.lock` and one `.venv`; `tool.uv.conflicts` gives forked *resolutions*, not multiple live environments, so switching profiles re-installs multi-GB torch. `UV_PROJECT_ENVIRONMENT` is explicitly a user setting, declined as a project setting ([uv#12587](https://github.com/astral-sh/uv/issues/12587)). A uv *workspace* makes it worse — members share one venv. The honest shape would be four sibling projects, which is a restructure of environments that already work. Also: an open Windows meta-issue on AV/EDR interference ([uv#20792](https://github.com/astral-sh/uv/issues/20792)) with Defender named. Revisit only if you rebuild an environment from scratch. |
| **`ruff format`** | Formatter is stable (since v0.3.0, 2024-02-29) and safe — but the ">99.9% identical" figure applies to *already-Black-formatted* code. Nothing here is. Expect a diff across ~300 files with zero defects in it, which buries the `F` findings. Revisit after Phase 4, as its own commit, with `.git-blame-ignore-revs`. |
| **Typer / Click** | Only 29 of 91 flat scripts use argparse; 47 have **no CLI at all**, so the work there would be *designing* arguments that don't exist. And `align_archive.py:177`, `transcript_accuracy.py:317`, `taptajivanam_mirror.py:178`, `kksongs_mirror.py:191` already define `main()`; `reference_editor` and `ggsm_transcription` already ship `__main__.py`. `-m` already works and is already documented. Adding console_scripts would add a *second* invocation style, not replace one. |
| **mypy / pyright / ty** | `ty` is `0.0.x` with no stable API and is stricter-by-default than either alternative — a wall of diagnostics on a largely unannotated repo. More importantly, the failure modes AGENTS.md names — Sanskrit vs Bengali measured apart, editorial text stripped before scoring, timings checked not assumed — are **value** errors no type checker catches. If you ever want one, scope it to `transcript_accuracy` and `forced_align`, in the editor only, and use basedpyright. |
| **pydantic for `meta.json`** | Genuinely tempting — it's zod-shaped and you'd find it natural. But all 79 files already share one schema, there is exactly one bad writer (`fetch_lecture.py:98`), and the fix is to make it call the good writer. A 3-assertion stdlib test does the same job with no runtime dependency added to a `pyproject` whose only dep is `cryptography`. Upgrade to pydantic later if you want the model to also be the documentation — the decision is reversible either way. |
| **DVC / git-lfs / LakeFS / Oxen** | DVC's default cache type on Windows is `copy` (no reflinks), so 4 GB becomes 8 GB, and it adds a second state system to keep in sync. git-LFS makes the 2.1 GB *permanent* — deleting LFS objects needs a history rewrite **plus** a GitHub Support ticket. LakeFS and Oxen need a server. And none of them address the actual cause: the bloat is self-inflicted generated audio, which a `.gitignore` fixes. DrivenData (cookiecutter-data-science) recommend exactly the rclone-plus-manifest approach over all of these. |
| **Prefect / Snakemake / Hamilton** | Prefect requires the API server ("orchestration fundamentally relies on state preservation"). Snakemake is the best fit on features — and is a Linux tool whose own docs send Windows users to WSL. Hamilton would mean rewriting 153 scripts as pure typed functions. |
| **just / make / poethepoet** | `make` doesn't exist on Windows. `just` needs two mandatory `set windows-shell` lines and pwsh 7 as a hard prerequisite. `poethepoet` is the best of the three — but its main draw here (per-task venv selection) comes from its **uv** executor, and we rejected uv. Without uv it doesn't solve the which-venv problem, and the `docs/README.md` venv table does. Revisit if the command count grows past ~10. |
| **A second MkDocs site for `docs/`, or `mkdocs-monorepo-plugin` to merge them** | The real argument for merging is one search index, and it is a fair argument. Against: `docs/` is read one document at a time (ADRs by number, dated handoffs), not as a body of cross-referenced argument; and a merged nav is a second thing to maintain. `docs/README.md` plus `strict: true` on the existing site costs nothing and covers it. Revisit if you ever find yourself grepping `docs/` for something you knew you'd written. |
| **pre-commit** | A hook on a machine with five venvs and no single canonical interpreter is a daily obstacle for a solo developer with no CI. |

---

## What I would NOT do

- **Move `scripts/` under `src/`.** `scripts/repo_paths.py:9-13` locates the repo by walking parents for a directory literally named `scripts` and raises `ValueError` otherwise; `tests/test_legacy_script_paths.py:8-24` pins 16 `scripts/…` paths. The move costs a helper rewrite plus a tracked-test rewrite — which AGENTS.md constrains — and buys nothing two `__init__.py` files don't.
- **Rename `docs/superpowers/` to `docs/designs` + `docs/plans`.** `git grep -ln superpowers` → 34 files, including `tests/heritage_production/test_packaging_and_cli.py:51`, `pyproject.toml:7`, `SHELVED.md:10,12` and two maintained research pages. And `docs/decisions/README.md` cites `superpowers/specs` as an example of the naming rule being **followed** ("this repository does not abbreviate in paths"). It's a label change for a solo reader at the cost of touching a test and the research site.
- **Move the narration ADRs (0006–0013) into `docs/narration-history/`.** ADR-0014 links into that set nine times; ADR-0004:4 and ADR-0005:4 carry `Superseded by:` links into it; `docs/decisions/README.md`'s index and reading-order paragraph point at all of them. That's 25+ relative links through a live supersession chain, rewritten so half of a fourteen-record numbered log lives in a sibling directory — to get a labelling benefit that one paragraph in `docs/README.md` delivers for free.
- **Move the five root `.md` files into `research/`.** Seven live prose references point at them by bare filename, one of which (`cloud/LIGHTNING_SETUP.md:16`) is a runnable `git add` command. A markdown link checker sees none of them. Prepend the supersession banner in place instead.
- **Rename `data/` to `raw/interim/processed`.** Pure churn. cookiecutter-data-science's own opinions page says the folder names matter less than the flow; a per-directory README and a written immutability rule get you the whole benefit.
- **Extract a shared HTML page shell for the 25 gallery builders.** 5,739 lines producing pages with four different `h1` spellings — but they are one-off research galleries with no users beyond you, and under ADR-0003 most of them archive anyway. AGENTS.md's own rule about low-risk presentation work argues against it.
- **Memoise `job_root()`'s data_root/jobs_root checks** (the second half of the `store.py` speedup). It converts a repeated reparse-point check into a start-up-only one — a TOCTOU regression dressed as an optimisation — and the bounded walk alone delivers the entire measured 2.4×.
- **Open an ADR to record that you decided against Typer, or against a second docs site.** `docs/decisions/README.md` restricts numbering to records that govern code. A sentence in `docs/README.md` carries the same information.

---

## Open questions for the owner

1. **Accept, amend or reject ADR-0003?** Nothing in Phase 4 starts until this is decided, and it is a governance call, not a cleanup. The alternative it explicitly rejected — "bulk `git mv` everything, fix fallout after" — is what every ad-hoc cleanup would do.

2. **Rewrite git history to reclaim the 2.05 GiB?** `git filter-repo --path data/out --invert-paths` (or `--strip-blobs-bigger-than 10M`) is **irreversible**: it rewrites every commit SHA and needs `push --force --mirror`; every other clone must be re-cloned, not pulled, including any cloud session. GitHub's stated limits: repos "ideally less than 1 GB, less than 5 GB strongly recommended", 10 GB on-disk `.git` recommended max, 2 GB push limit. **2.05 GiB is over "ideal" and under everything enforced** — so this is deliberate, not urgent. Phase 3a gets the working-tree benefit with zero irreversibility; do this only if you decide separately that you want it.

3. **Rotate the five API keys in `.env.local`?** They were never committed — I verified `git log --all -- .env.local` → 0 commits, and `.gitignore:17` covers them. But four of the five (`SARVAM_API_KEY`, `ELEVENLABS_API_KEY`, `DEEPGRAM_API_KEY`, `EXA_API_KEY`) are billable third-party credentials in a tree that seven agent workflows and a shared scratchpad read. Also worth knowing: `.hf_token` is **0 bytes**, so anything reading it gets an empty string — `HF_TOKEN` lives only in `.env.local`.

4. **Which of the two `merciful-glances` transcripts is canonical?** Same 108,967,377-byte recording, `aid` 863 with 29,760 chars vs `aid` 1652 with 45,901 chars. This is a source-side judgement I should not make for you. It changes the published archive figure.

5. **`fastbook/` — keep, annotate, or untrack?** 4 tracked files, 224 KB, verbatim fast.ai book text (the `/home/jhoward/.fastai/...` paths in the output cells are Jeremy Howard's machine), committed with no README, no source URL and no license note. fastbook is CC BY-NC-ND. It is the one third-party redistribution in the tree and no document mentions it.

6. **Bound the `store.py` ancestor walk?** Measured 294.4s → 123.3s with 132/132 green. It narrows a reparse-point security boundary from "every lexical ancestor up to `C:\`" to "`data_root` and below" — a deliberate trust decision that assumes the path to `data_root` is trusted — and ADR-0014 §6 trigger 2 counts behaviour-changing commits to `store.py`. If yes, write the two boundary tests first: a junction inside the job root is still rejected; a junction above `data_root` is explicitly out of scope.

7. **Which venv gets pytest, ruff and the `[dev]` extra?** `pip install -e .[dev]` also pulls `cryptography==50.0.0`, absent from `.venv`, `.venv-indic` and `.venv-transcribe`. Your standing rule is never to change environments silently, so name the venv before Phase 2 runs.

8. **The 6.7 GB of local-only evidence — record it or accept the loss?** `git clean -xdf` today destroys `voice_lab/` (1.1 GB, 1,765 files), `_work/` (335 MB), `data/reference/` (296 MB, 293 files), `data/research/` (153 MB, 1,603 files including 21 research notes across 6 topics) and `data/models/` (4.8 GB). All correctly ignored; none recorded anywhere; four published research pages and all seven agent workflows cite into it. The cheap middle path is a `CHECKSUMS.tsv` (`path, sha256, bytes, fetched_from, fetched_on`) covering only the ~15 paths that research pages actually cite, plus committing the ~10 small analysis `.py` files under `data/reference/analysis/` that produced published accuracy numbers. That makes a figure's input *identifiable* without redistributing archive.org material. The full 6.7 GB is a different, bigger question.

---

**Two smaller things found along the way, not worth a phase:** `cloud/TRAINING.md:37` and `:49` name `scripts/train_voxcpm_finetune.py` and `scripts/test_voxcpm_lora_infer.py`, neither of which exists. And `.agents/workflows/ssggsm-reference-and-catalogue-prep.js:10-12` and `ssggsm-transcript-corpus-check.js:12` hardcode a **session-scoped** Claude scratchpad UUID under `AppData/Local/Temp`; they run today and will stop the moment that temp tree is cleaned, with no error pointing at the cause.