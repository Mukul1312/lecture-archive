# ADR-0016 — lecture-archive publishes the review format; the review app keeps a pinned copy

**Date:** 2026-10-29 · **Status:** Accepted 2026-10-29 — decision 3 open, §2 · **Governs:** `contracts/review/`, `scripts/review_contract.py`, `scripts/review_package.py`
**Supersedes:** nothing · **Superseded by:** —

---

## 1. Context

`review-assistance`, the TypeScript review app, needs everything a devotee reviewer sees to arrive
precomputed. The app does no language processing (agreed with the steward, 29 October 2026). On
29 October it drafted the shared format from the reviewer's side, in its `contracts-proposal/`:
four JSON Schemas (Draft 2020-12), golden examples with an `index.json` saying what each must do,
and a README with the rules a schema cannot check (P1-P10, A1-A8, C1-C3, R1). The steward ruled
the same day that the producer owns its published format, so the schemas live here. The app then
keeps a pinned copy with a test that fails if it differs.

What this repository knew that the draft could not, found while building the first real package
from BG 3.37 (Brisbane), the lecture the examples were excerpted from:

- **A lecture can pass the placement check and still have misplaced words.** Brisbane passes
  `compare_hosted`'s check at 1.05 (ElevenLabs) and 1.05 (Sarvam), against `MISPLACED_RATIO =
  1.5`. `read_along.word_check` still finds 17 stretches where published words sit more than 1 s
  from where ElevenLabs heard them, one by up to 22 s (2485-2506 s). Three more show up only as
  disagreements pairing words more than 1 s apart, which is where the word check is blind. In all,
  20 stretches and 112 s.
- **`verse-runs.json` was stale.** It was written at 21:18 on 12 October, four minutes before
  commit `9dfd807` restored the 0.25 gate, and it still held the wrong `Pranesvari` attribution at
  margin 0.229. It was regenerated on 29 October with the committed code (`INVENTORY: ... 27
  matched ... at margin 0.25`). The previous file is kept in the session scratchpad.
- **The alignment predates the shared cleanup rule** (commit `ec0ccd7`). Four timed words are now
  editorial notes, `(In sattva-guṇa)` and `(the mic)`. `read_along.renumber` carries the other
  4,946 timings over.
- **The scorer's Sanskrit/Bengali split lets English words vote.** In `compare_hosted.language_mask`,
  English "more" counts as the Bengali pronoun *more*: two of the three words it labelled Bengali on
  Brisbane were Sanskrit.
- **The listening copy's decoded length is not in the media manifest** for Brisbane: it records
  only `length_matches_original: true`. A full decode measures the original and the copy at
  3649.016 s each, which agrees with the aligner's 3649.0.

Every figure above was measured on 29 October 2026 by the code named. None of it is recalled.

## 2. Decision

1. **The format lives in `contracts/review/` and is owned here.** The four schemas and the
   examples were copied byte for byte. `.gitattributes` keeps their line endings LF, because an
   answer record names its package by SHA-256. `review-assistance` replaces its
   `contracts-proposal/` with a pinned copy of this folder.
2. **Both sides check every example.** `scripts/review_contract.py` implements the schema
   validation and every rule. `tests/review_contract/` requires each example to give exactly the
   result `index.json` states: a failing example must break the rule it names and no other. Each
   rule without an invalid example is broken once, in memory. Where the README is silent, the rules
   follow the app's `src/contract/*Rules.ts`, so the two implementations can disagree only when one
   of them is wrong. The examples are the arbiter.
3. **OPEN: how stops are built.** `scripts/review_package.py` builds one lecture's package, refuses
   to write one that fails the schema or any P rule, and writes it locally only. Its defaults are
   working proposals awaiting the steward: grouping, clip length, the language rule, verse gating,
   agreement sampling, and cutting misplaced stretches out of the spans. They are listed in
   `contracts/review/README.md` ("How lecture-archive builds a package"). Uploading a package needs
   the steward's separate go-ahead and is not written.

   **Steward's ruling, 29 October 2026:** the questions are important and are not to be settled
   on one lecture. `lecture-archive` decides four of them (one language per stop, spelling-only
   stops, the `unknown` language, and the working defaults) once four or five lectures have been
   reviewed. Until then the defaults stand as proposals. Packages now build for seven lectures
   (§3).

   **Steward's answers, 30 October 2026:** keep a copy of the media manifest in this repository
   (it is the bucket's `manifests/media-v2.json`, byte for byte, in the gitignored
   `data/reference/review/manifests/`); fix the Sanskrit/Bengali labelling, *and* show each
   stop's language to reviewers so their corrections teach this repository to label better (see
   decision 4); and publish. `scripts/review_publish.py` uploads a package to
   `gs://ssggsm-seva-media/packages/<lecture>/v1.json`, refusing a DRAFT, a package that fails its
   checks, one whose audio is not in the bucket, and any overwrite. Five packages were published
   with it on 30 October 2026, built from commit `213f1d4`; their hashes are listed at the top of
   `contracts/review/README.md`.
4. **The format changed on adoption** where this repository's knowledge required it. The changes
   are listed in `contracts/review/README.md` ("Changes made on adoption"). There are two schema
   changes. `producer.inputs[].role` gains `sarvam` and `media-manifest`. And on 30 October
   2026, before any package was uploaded, an answer gained an optional `spoken_language` with rule
   A9, so a reviewer can correct a stop's language. The draft's examples are unchanged; two new
   ones go with `spoken_language`.
5. **`jsonschema==4.23.0` is installed in `.venv`**, recorded in `requirements-contracts.txt`.
   This is the version the app's side checked the examples with. `.venv` is used because the
   builder also imports `forced_align`, which needs torch.

## 3. Evidence

| Measurement | Value | Where |
|---|---|---|
| Golden examples giving their stated result | 20 of 20 (18 from the draft, 2 added for `spoken_language`) | `tests/review_contract/` |
| Rules broken once each, with no invalid example | 16 (P2 three ways) | `tests/review_contract/` |
| Brisbane package: stops | 640: 452 word disagreements, 158 single-version, 23 agreement samples, 7 verse checks | `data/reference/review/packages/…/v1.json` |
| …by language | 200 English, 93 Sanskrit, 1 Bengali, 346 `unknown` (188 words only ElevenLabs has inside spans, 158 single-version) | the same |
| …spelling-only Sanskrit stops | 42 of 86 | `recognisable()` on every word pair |
| …clips | median 6.8 s, longest 14.4 s, 80 min of listening | the build's report |
| …size | 1.74 MB, 0.16 MB compressed | the same |
| Misplaced stretches cut from the spans | 20, 112 s (17 by the word check) | the same |
| Bengali labels right by reading, scorer's rule / package rule | 1 of 3 / 1 of 1 | stops read on 29 October |
| Packages for seven lectures (all with both recognisers' output that pass the placement check) | 3,558 stops for 264 min of audio; 445 min of clips | `data/reference/review/packages/*/v1.json` |
| …Bengali verse checks labelled Sanskrit, by reading | 8 of 13, on the two Caitanya-caritāmṛta lectures | the same; `contracts/review/README.md` |
| …Indic word disagreements that are names / spelling only | 317 / 280 of 538 | the same |
| …`unknown` stops between two English words | 704 of 789 | the same |
| `indic_language` on text of known language, before / after 30 October | Bengali verse checks 5 / 12 of 12; held-out KKSongs Bengali lines 31.5% / 49.4%; SB called Bengali 0.6% / 0.7% | `tests/transcript_accuracy/test_language.py`; the function's docstring |
| `compare_hosted` after the language fix | Bengali words 171 → 252; English and Sanskrit conclusions unchanged; Bengali still undecided | `python -m scripts.compare_hosted` |

**Against:** the misplaced-stretch rule rests on ElevenLabs being placed better than the aligner.
That holds lecture-wide (median offset 0.02 s over 4,200 checked words), but ElevenLabs stretched
`Kama.` across 55 s of chanting. So a stop never holds a recogniser word lasting over 5 s. Every
figure above is from one lecture.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| Keep the schemas in `review-assistance` | The steward ruled that the producer owns its published format (29 October 2026). |
| One rule implementation shared by both sides | There is no shared runtime: Python here, TypeScript there. The examples, run on both sides, are the cheaper agreement. |
| Generate the schemas from Python types | The app consumes JSON Schema through Ajv; generating them would make this repository's code the format's definition, which the app cannot read. |
| Filter the stale `verse-runs.json` at margin ≥ 0.25 instead of regenerating it | Margins are stored rounded to three places. BG 3.37's match is stored at exactly 0.250, so a filter cannot tell which side of the gate it truly fell. |
| Keep misplaced stretches in the trustworthy spans | Every stop there plays audio that does not hold its words. |
| Label ElevenLabs-only words from the published words around them | It infers what audio contains from its neighbours. AGENTS.md forbids exactly that proxy until it is measured. It is offered to the steward instead. |
| Do nothing until the steward settles every default | The task was to produce a reviewable package early. The defaults are labelled as proposals in the package's README. |

## 5. Consequences

- `review-assistance` must update its copy (two enum values, `spoken_language` with rule A9, and
  text) and replace `contracts-proposal/` with the pinned copy. Until it does, its schema refuses
  the published packages, whose inputs use the new roles. It must also show each stop's language
  and offer the correction. Its `packageRules.ts` does not yet check that an untimed word comes
  from the published source (P2).
- Two implementations of the rules now have to be kept in step. A change to a rule is a change to
  both, plus an example.
- The builder needs `.venv` (torch, jsonschema), ffmpeg on PATH, the local audio and listening
  copy, and a local copy of `manifests/media-v2.json`, kept in `data/reference/review/manifests/`.
  Publishing needs `gcloud`, signed in with write access to the bucket.
- A package built from uncommitted producer code is marked DRAFT in its notes, and
  `scripts/review_publish.py` refuses it.
- Republishing (v2), which must carry stop ids over, is not built. The builder refuses to make one.
- `compare_hosted.language_mask` keeps its English-votes defect. The language lists it votes with
  were improved on 30 October 2026, which moved its Bengali figures (§3); the research page that
  quotes the Melbourne split carries a dated correction.

## 6. Revisit trigger

- **A file accepted by one side's rules and refused by the other's.** Write it down as an example
  before fixing either side. If it happens three times, one implementation should be generated
  from the other.
- **Four or five lectures have been reviewed** (the steward's ruling, §2). `lecture-archive` then
  decides the open stop-building questions in `contracts/review/README.md` from the reviewers'
  answers, and records them in a new ADR that supersedes decision 3 of this one.
- **Reviewers answer "can't tell" or "not the lecturer" on more than a fifth of the word
  disagreements in one lecture's first export.** That would mean misplacement inside the
  trustworthy spans is still reaching stops, and the cutting rule is not enough.

## 7. What this record does not decide

How answers are imported and applied (`import review answers` waits for real exports). How
results are computed. Which spelling the checked text keeps after "both are right". Anything about
the upload step, the bucket, or packages for other lectures, whose ElevenLabs runs are a separate
task.
