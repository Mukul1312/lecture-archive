# This package is SHELVED — it is not part of any running flow

**Read this before changing, extending, or planning around anything here.**

Last active 2026-08-26 at commit `35f9c44`. Nothing in this package is
imported by `scripts/`, `cloud/`, or `colab/`. Its CLI
(`presentation/cli/main.py`) is 62 lines of unimplemented subcommands that
return 0. The test suite passes — 656 tests — but it verifies only itself.

**Authority:** `docs/superpowers/specs/2026-08-26-corpus-ledger-domain-design.md`,
section 12 and the AMENDMENT at the end. That document supersedes the build
order in `docs/superpowers/plans/2026-08-24-heritage-production-first-slice.md`.

## Why it is shelved rather than deleted

The domain modelling is correct and was expensive to get right. Cutting working
code is a write-off, not a saving. Two parts in particular are worth keeping:

- **`domain/shared/`** — canonical identity, digests, RFC 8785 canonical JSON.
  Designated as the shared kernel if a corpus ledger is ever built. Best
  specified code in the repository.
- **`domain/transcription/edition.py`** — segment lineage: `CORRECTED_FROM`
  with exactly one parent, `SPLIT_FROM` with one, `MERGED_FROM` with at least
  two. Genuinely hard and genuinely correct. Digest-scoped anchors are a strict
  *subset* of this, so adding lineage later invalidates nothing recorded in the
  meantime.

## Unfreeze triggers — do not resurrect without one

| Part | Unfreeze when |
|---|---|
| `domain/transcription/` (Task 3) | The first sealed edition that will receive a second human correction pass |
| `domain/review/` (Task 4) | The first finding submitted by a human who is not the steward |
| `domain/production/`, `domain/release/` (Task 5) | A rights-holder or recipient asks for a formal sign-off before delivery |
| `application/` (Task 6) | Only alongside one of the above. Its `run_operation` idempotency design is superseded by the run-key approach in the 2026-08-26 design |

## Known defects, deliberately unfixed

Found by independent review of Task 6 on 2026-08-26 and left in place because
this code is shelved. **Fix them before unfreezing, not after.**

1. **CRITICAL** — no handler ties a `TranscriptEdition`'s `source_versions` to
   the Production's attached sources. `create_initial_transcript_edition` loads
   the Production and discards the result; `_resolve_proposal_sets` only checks
   the edition's *own* declared list. A sealed, undeletable edition can be
   created on a source the Production never attached, then selected as the
   candidate under a selection naming a different source. Design 8.6 invariant
   2 is unenforced.
2. `AttachSourceRecording` never consults the artifact store — it trusts a
   declared digest rather than hashing the bytes. Design 10.4 requires the
   source to be hashed before it is bound.
3. `CreateSuccessorTranscriptEdition` never reads a closed review round, though
   design 9.1 lists one in its read set. There is no round repository injected.
4. `SubmitReviewFinding.payload` is typed `object` and cannot be digested; the
   reachability guard in `test_application_idempotency.py` does not see fields
   declared directly on a command, only on nested dataclasses.

## Two things it costs you today

- Roughly 55 seconds on a full `unittest discover -s tests -t .` run. Kept
  deliberately: silent rot is what makes unfreezing expensive.
- The `dev` extra in `pyproject.toml` (`hypothesis`, `rfc8785`) exists only for
  these tests.

## Running its tests

```
PYTHONPATH=src python -m unittest discover -s tests/heritage_production -t .
```

The `-t .` matters: without it, `tests/heritage_production` shadows
`src/heritage_production`.
