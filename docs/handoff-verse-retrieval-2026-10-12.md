# Handoff: verse retrieval and the printed canon (2026-10-12)

Nine scripts now take part in turning a garbled recitation into a printed verse with an address.
This maps them, says what is measured and what is merely believed, and lists the traps that have
already cost time.

## The first five minutes

1. **The question this subsystem answers.** Machines cannot transcribe chanted Sanskrit — 99–110%
   WER in the literature, and 42–64% here. But the teacher quotes a **fixed canon**, so the task
   is *retrieval*, not transcription: identify the verse once, and its printed text is exact for
   all 3,766 lectures.
2. **`verse_runs.py` is the entry point.** `python -m scripts.verse_runs`. It takes ~4–5 minutes
   to build the 192,911-window index, so **`verse-runs.json` holds the PREVIOUS run until it
   finishes** (see §6).
3. **Measure changes against `tests/fixtures/verse_truth.json`.** Do not argue about scoring.
   Every claim here settled by argument has been wrong at least once.
4. **The margin gate is 0.25 and was reverted to it deliberately** — lowering it to 0.15 admitted
   a wrong attribution. Read §5 before touching it.
5. **A confidently wrong verse attributed to this teacher is worse than an admitted gap.** That is
   the standing standard and it has decided every trade in this subsystem.

## 1. What each script does

| script | role |
|---|---|
| `verse_match.py` | the matcher: `skeleton()`, trigram profiles, containment similarity, `VerseIndex.rank/find`. **Pre-existing and validated; I have not changed it.** |
| `verse_runs.py` | the pipeline: pulls Indic runs from the alignment, builds the combined index, identifies, scores systems against printed text, writes the worklist |
| `gretil_verses.py` | GRETIL TEI → 14,293 verses (Bhāgavatam + Gītā 1–17), CC BY-NC-SA |
| `wikisource_gita.py` | Sanskrit Wikisource → 700 Gītā verses incl. **ch. 18**, Devanagari→IAST, CC BY-SA |
| `bbt_verses.py` | Vedabase corpus → 20,270 verses (CC 11,357 · SB 8,260 · BG 653), verse text only |
| `caitanya_bhagavata.py` | CB → 11,124 verses; merges the Antya full text with the wisdomlib khaṇḍas |
| `wisdomlib_cb.py` | fetches CB Ādi + Madhya one page at a time, politely and resumably |
| `verse_cache.py` | verses resolved by search, remembered with provenance; feeds the index automatically |
| `make_verse_truth.py` | regenerates the ground-truth fixture from the live run output |

## 2. The corpus: 192,911 windows

| source | windows | verses | licence |
|---|---:|---:|---|
| KKSongs | 53,214 | 1,175 songs | mirrored; **lyrics only, never purports** |
| GRETIL | 43,858 | 14,293 | CC BY-NC-SA 4.0, in each TEI header |
| Sanskrit Wikisource | 2,051 | 700 | CC BY-SA 4.0, from the wiki's `siteinfo` |
| Vedabase SB/BG/CC | 68,378 | 20,270 | **BBT permission held by the steward, stated 2026-10-12** |
| Caitanya-bhāgavata | 25,410 | 11,124 | same edition wisdomlib serves |

Scope is **KKSongs, SB, BG, CC, CB** — set by the steward. Prabhupāda's other books sit in the
cloned corpus (`bbt_verses.BOOKS`) and are left out deliberately, a line away if scope widens.
He also quotes other Gauḍīya ācārya works — **Prema-vivarta of Jagadānanda Paṇḍita** (Bengali,
not Odia) — less often; out of scope for now by instruction.

**Outstanding: 28 CB verses behind a Cloudflare challenge.** See §6.

## 3. What is measured

- **18 → 31 matched** of 55 runs across 7 lectures, at margin 0.25.
- **ElevenLabs 42.1% vs Sarvam 63.9%** over 183 printed verse words. Both poor on chanted verse,
  which is the point: lookup beats transcription there.
- **Run purity** (commit `9ff1028`): runs 44→33, matched 17→17, unmatched 27→16, match rate
  39%→52%. Eleven phantom runs removed, no real match lost.
- **Precision by reading**: of 20 matches read at an earlier state, 18 were right.

## 4. What is believed but not established

- The fixture covers **31 runs from 5 lectures**; the pipeline now produces **55 across 7**. So
  24 runs are unjudged and every match-count comparison across those sets is confounded.
  **Judging them is the highest-value next step.**
- All figures rest on 5–7 lectures of ~2,000 hours.
- `āmi bāndhi āchi hṛdaya` → Cc. Madhya 25.127 is **uncertain and is being scored**.
- The mahāmantra is cited to a song title. Text right, citation absurd, not scored.

## 5. The scoring, and four of my explanations that were wrong

`skeleton()` folds aspirates and sibilants, maps `e→i`/`o→u`, **deletes every vowel**, collapses
repeats — ~15 symbols, so only **3,375 possible trigrams** against 192,911 windows.
`_similarity = shared / min(|a|,|b|)` is **one-sided containment**: a short query asks only "is
all of me somewhere in you". Consequence: **22 of 33 runs score exactly 1.000.** The score has
near-binary resolution and the margin is a difference of two saturated numbers. The vowel
deletion was calibrated on **59 verses**.

Refuted by measurement, each cheap to test and damaging to ship:

1. *Bound candidate length.* Correct matches have candidates **longer** relative to the query —
   median ratio 1.89 vs refusals' 1.01, one correct at 5.00.
2. *idf weighting.* Only **5 of 2,544 trigrams appear in one window**; nothing is rare. Measured
   worse (13 vs 14 correct).
3. *Minimum query length.* Floors 8–9 do nothing; 10–12 lose correct matches.
4. *"The system cannot tell which verse it is."* It can — the right text ranked **first** in 10 of
   26 refusals, four at a perfect 1.000.

**What is true instead:** the gate was already strictly safe — `WRONG=0` and `LEAKED=0` at every
setting tested. Its 9 refusals were conservatism working.

**0.15 was adopted and reverted.** The sweep said it was the lowest margin with no wrong answer;
reading the four newly-admitted matches found one wrong (`'āmāra' bolite āre kichu nāi` → the
song `Pranesvari…`, matched line `yogāibo lalitāra kāche`). ⚠ **The harness was blind to it**
because that run is `unresolved` and unresolved runs were excluded from the tally — so an address
assigned to an unresolved run must be counted as a flagged event. No threshold separates the
cases anyway: the correct `Cc. Ādi 4.63` and the wrong `Pranesvari` both sit at margin **0.229**.
The **firm** leak boundary is **0.08**.

**The structural ceiling:** at margin 0.000 correct and wrong are perfectly mixed —
`pratiṣthāśā āsi'` correct at 1.000/0.000, `Rāma Hare Rāma` wrong at 1.000/0.000. Two verified
identifications are unreachable at any safe setting. Recovering them needs a signal this scoring
has not got — the surrounding English, or which scripture the lecture is already on. **Not a
threshold.**

## 6. Traps that have already cost time

- **The stale-file trap.** `verse_runs` takes minutes; `verse-runs.json` holds the previous run
  meanwhile. I reported "AT MARGIN 0.15 — matched 17" from the stale 0.25 file. **Check the log's
  `INVENTORY` line, which prints the margin used.**
- **Mixed Unicode normalisation.** `pratiṣthāśā` precomposed and decomposed print identically and
  compare unequal. `skeleton()` is immune (NFKD first); anything comparing text is not. The
  fixture stores verbatim text **and** an NFC `key`.
- **Cloudflare, not truncation.** 28 wisdomlib pages came back ~22 KB with the correct `<title>`
  and no verse; `curl` returns the same bytes. The tail is `/cdn-cgi/challenge-platform/…`. The
  danger was **saving** them — once on disk, resume never asks again and the hole is permanent.
  `looks_complete()` refuses to write them.
- **Commentary inside verses.** GRETIL's Gītā is a commentary; Śaṅkara's prose sits in bare `<l>`
  elements before the `<lg>`, so accumulating across the boundary made BG 3.17 read
  `evaṃ sthite kim evaṃ pravartitaṃ caktraṃ…`.
- **Address spellings are not cosmetic.** Vedabase writes `Bg. 18.66`, GRETIL `BG 18.66`;
  `SCRIPTURAL` picks scripture over a song by prefix, so `Bg.` lost that preference until
  canonicalised.
- **Length may only break ties, never overrule similarity.** Choosing the printed form by length
  alone re-pointed three correct song matches at unrelated lines of the right song, because for
  KKSongs a "passage" is a whole song.
- **A margin measures crowding, not confusion.** Six inferences of this shape have failed here;
  the list is in `AGENTS.md`.

## 7. What I would do next, in order

1. **Judge the 24 unjudged runs** and regenerate the fixture. Everything else is confounded
   without it. `python scripts/make_verse_truth.py` then read what it marks `unjudged`.
2. **Retry the 28 Cloudflace-blocked CB verses** — `python -m scripts.wisdomlib_cb --fetch`, later
   and slower. The challenge is per-client and temporary.
3. **Cross-check against the steward's CB PDF** (`~/Downloads/Caitanya Bhagavata(Vrindavana Dasa
   Thakur).pdf`, 4,689 pages, real text layer, legacy Balaram font encoding). It has no addresses
   — no outline, and its khaṇḍa/chapter strings are commentary cross-references — so it is a
   **second witness**, not a source. Validate the font remap against the Antya text we already
   hold in clean IAST.
4. **Only then** consider the scoring. The honest next idea is *context*: which scripture the
   lecture is already discussing, which would break the margin-0.000 ties that no threshold can.
