# Where the verses come from (2026-09-23)

Retrieval needs a corpus. This is where it can be obtained, under what licence, and what has
to be repaired before it is usable.

Four research agents using Exa and Firecrawl, each followed by an adversarial reader holding
licence claims to the strictest standard. **11 of 52 source claims were rejected — every one
on licensing rather than coverage.** One rejection ran in the archive's favour.

## The short version

| | status |
|---|---|
| **Sanskrit verse** | **Solved.** GRETIL, explicitly licensed, complete Bhāgavatam |
| **Bengali padāvalī** | **KKSongs**, mirrored, with a permission request — lyrics only, never the purports |
| **Caitanya-caritāmṛta** | **SOLVED 2026-10-12** — BBT permission held; 11,357 verses from `vaniwiki/prabhupada-books`, verse text only |
| **An LLM's role** | May **label**, **choose**, and **search**. Must never **produce** |

---

## Sanskrit: use GRETIL's TEI layer

`sa_bhAgavatapurANa.xml` — **14,067 verse IDs across all twelve skandhas**, and every one of
the five Bhāgavatam citations in our own reference lecture is present at its exact address:
SB 11.2.37, 3.9.10, 3.25.42, 2.1.3, 6.17.28. Plus `sa_bhagavadgItA-comm.xml`, 622 verses.

The licence is printed in each file's own TEI header — **CC BY-NC-SA 4.0**. That is bare
ancient verse text, not anybody's translation or purport.

!!! success "A rejection in our favour"
    The researcher marked GRETIL "unclear" because the HuggingFace mirror's card defers
    ("inherits the license terms from the original GRETIL corpus"). The challenger went to
    GRETIL itself and found **every TEI file carries an explicit licence in its
    `publicationStmt`**. GRETIL does not defer. The source is cleaner than first reported.

### Three repairs before indexing

1. **Deduplicate the long-metre verses.** **584 of 844** starred Bhāgavatam verses repeat
   their first half-verse in the XML — verified on BhP 1.1.2, 1.1.3 and all of BhP 3.9, which
   contains **SB 3.9.10, one of our own citations**. The rule: within a verse, drop any pāda
   group identical to the one before it. Write the regression test on SB 3.9.10 specifically.
2. **Source Bhagavad-gītā chapter 18 separately.** The cleanly-licensed file covers chapters
   1–17. GRETIL's complete 700-verse Gītā is the BORI critical edition, outside the CC layer,
   whose upstream says *"Please do not provide copies of the text to others."*
3. **Check Sanskrit Wikisource** — about an hour's work, never done. If complete and
   CC BY-SA 4.0, it is a better licence and solves chapter 18 at once.

### Two licence consequences to decide deliberately

**NonCommercial is a non-issue** — the lectures are already CC BY-NC-ND, so the corpus is no
more restrictive than what the archive holds. **ShareAlike is the one that bites**: any verse
index derived from GRETIL and then published must itself carry CC BY-NC-SA 4.0. If the index
should be freely reusable by others, a CC BY base is needed.

### What was excluded, and why

- **Bhaktivedanta Book Trust / vedabase** — in copyright. Not usable. **⚠ SUPERSEDED
  2026-10-12: the steward states that full permission from BBT is held.** This is now the
  source of Caitanya-caritāmṛta, via the structured `vaniwiki/prabhupada-books` corpus
  (`scripts/bbt_verses.py`), **verse text only and never the purports**, by the same rule the
  KKSongs mirror follows. The exclusion above stood until then, and it was right to: no
  freely-licensed machine-readable Caitanya-caritāmṛta exists, which was verified on 2026-10-11
  against Exa, Sanskrit Wikisource and Bengali Wikisource rather than assumed.
- **Gaudiya Grantha Mandira** — the only tradition-specific repository, but **no licence
  statement at all**, and its own page says the Bhāgavatam was typed from BBT Folio.
- **Digital Corpus of Sanskrit** — better licence (CC BY 4.0) but only 119 of ~335 Bhāgavatam
  chapters, **missing canto 6 entirely**, including SB 6.17.28, one of ours.
- **sacred-texts.com** forbids bulk fetching.

One provenance question is open: GRETIL's `sourceDesc/bibl` is empty, so it does not say which
edition its Bhāgavatam came from. One email to `gretil@sub.uni-goettingen.de` settles it, and
the archive's posture is that it does not ship what it cannot account for.

---

## Bengali: there is no corpus, and that has to be said plainly

**No bulk-downloadable, openly-licensed, machine-readable corpus of Gaudiya padāvalī exists
anywhere.** Nothing in this space resembles GRETIL. No dataset on HuggingFace or Kaggle — the
one relevant corpus withholds its text files for copyright reasons. No API. Every candidate is
a website to crawl.

The best available is **KKSongs.org**: 1,437 song pages, **707 tagged Bengali**, romanised IAST
throughout, Bengali Unicode for about a third. It **states no licence whatsoever**.

The bulk alternative fails on measured evidence: in one 24.5k-character sample of archive.org
Bengali OCR, the poet signature চণ্ডীদাস appears in **twelve different spellings, only 19.5%
correct**, and cleaner prints are two-column-merged so verse segmentation breaks. Usable as a
search aid, never as reference text.

!!! warning "If KKSongs is used"
    Mirror by walking the 26 A–Z index pages — the advertised `sitemap.xml` is a 191-byte stub.
    Take **only** the romanised lyrics, the Bengali-script pages where they exist, and the
    header metadata. **Never follow the `/authors/purports/` links** — that is BBT and
    Prabhupāda material and is the one thing that would make the result unshippable.
    Send a permission request in parallel.

A lead worth checking: the challenger found the `gaudiyakirtan` repository's licence was
misquoted **in the dangerous direction** — the live README reads *"Songbook content —
CC-BY…"*, so it may be usable after all. That is an hour's work and it is the most promising
thread for Bengali.

---

## The matcher we built was measured, and one thing in it is backwards

An agent ran `scripts/verse_match.py` at scale. **The abstention rule is sound** — precision
held at 100% in every cell tested, at every corpus size and garbling level. Keep the shape:
skeleton → score → margin → abstain.

!!! danger "`skeleton()` folds the wrong way"
    It currently collapses `sh→s`, `bh→b`, `v→b`, `aa→a` and then de-duplicates runs — which
    throws away **precisely the information that separates 20,000 verses**. The published
    approach does the inverse: represent each word by its **two most infrequent letters**, and
    reach Talmud-scale coverage "essentially the same as slow exhaustive methods" in 11
    seconds. Select rare letters; do not fold toward common ones.

!!! warning "A sobering number for scale"
    The closest real analogue — Sikh Kirtan captioning against **141,264 canonical scripture
    lines** at 52–69% WER — reports **Recall@1 of only 21.5–31.9%**.

    Our 61% was against 59 verses that were all present in the lecture. Expect it to fall a
    long way against a real corpus. The 100% precision is the part that should survive, because
    it comes from the margin rule rather than from corpus size.

---

## The LLM question, answered

The steward identifies verses by hand with Google and Gemini and asked whether that belongs in
the pipeline. The evidence is one-sided.

**Never let it produce the verse or the citation:**

| | exact reproduction |
|---|---:|
| unassisted models quoting scripture, English (33,000 observations) | **32.6%** |
| the same, non-English | **7.3%** |
| general models quoting Qur'anic verses exactly | 4.77–6.86% |

The best published system for *repairing* a misquoted verse beat doing nothing by **0.66
points**.

**But two jobs are well-evidenced, and one of them fills a gap we already had:**

- **Span detection** — "a quotation starts here and ends here". Best-evidenced LLM task in the
  literature: **90.06% macro-F1 against a 36.17% baseline**. The output is character offsets,
  not text, so it **cannot corrupt a transcript by construction**. This is exactly the
  segmentation problem the matcher has — at inference time nobody knows where a verse begins.
- **Choosing among candidates the retriever already supplied**, provided the decision is
  recorded as a candidate ID and never as text (89.82% against a 70.00% baseline).

!!! warning "Do not port the Arabic numbers across"
    Those figures are on clean Arabic. The Sanskrit analogue tops out around **72 F1**, and
    GPT-4o reaches only **45.58**. Pilot span detection on our own reference lecture and
    measure it there.

---

---

## The resolution: search builds the corpus, it does not run per lecture

The steward's objection to the above is correct and changes the design. **An LLM that
*searches* is not an LLM that *produces*** — it returns a located quotation with a source,
which is a different act from recalling one from weights. And it reaches what no download
can: **Caitanya-caritāmṛta and Caitanya-bhāgavata have no machine-readable text anywhere**, so
no amount of GRETIL work covers them.

The cost objection that killed Deepgram-as-confidence does not apply here, and the reason is
worth stating precisely. Measured on our reference: 59 verse occurrences, **53 distinct** — so
caching within a lecture saves almost nothing. But that is the wrong unit. He teaches from a
fixed canon across 3,766 lectures, quoting the same verses over and over. **Keyed by
skeleton, each distinct verse is looked up once, ever.** The cache fills quickly, and the
marginal cost per lecture falls towards zero.

So search is not an alternative to building a corpus. **It is how the corpus gets built** for
the texts that cannot be downloaded — incrementally, driven by what he actually quotes rather
than by indexing 14,067 verses he may never cite.

### The shape that keeps the archive's posture intact

1. **Local index first**, from GRETIL, for Bhāgavatam and Gītā. Free, deterministic, auditable,
   and it will answer most lookups.
2. **Search only on a miss**, for Caitanya-caritāmṛta, Caitanya-bhāgavata and anything else the
   index lacks.
3. **Every result must arrive with a source URL**, and the URL is checked against an allowlist.
   This is the one guard that matters: without it a search may return **vedabase**, and BBT
   text would enter the corpus silently — undoing the entire licence analysis above.
4. **Cache by skeleton, permanently.** A verse resolved once is never looked up again, and the
   cache becomes the archive's own corpus, with provenance attached to every entry.
5. **Never accept text without a source.** A result the model produced rather than found is
   refused, which is the same rule as the matcher's abstention.

---

## Songs: KKSongs, decided

The steward's decision is to rely on KKSongs.org, which is reasonable — it is the only clean
machine-readable Bengali source that exists, and the alternative measured 19.5% correct.

One distinction to hold onto while mirroring it, because it is the difference between usable
and unshippable:

| | |
|---|---|
| **the songs themselves** | Bhaktivinoda Ṭhākura died in 1914 — the compositions are long out of copyright |
| **KKSongs' transliteration and arrangement** | their work; no licence stated, hence the permission request |
| **`/authors/purports/`** | **BBT and Prabhupāda material — not KKSongs' to give.** Never follow these links |

Take the romanised lyrics, the Bengali-script pages where they exist, and the header metadata.
Nothing else.

## What to do next

1. **Fetch GRETIL, deduplicate, index.** Sanskrit is unblocked today. Regression-test the
   deduplication on SB 3.9.10.
2. **Rewrite `skeleton()` to select rare letters** rather than fold toward common ones, and
   re-measure retrieval at realistic corpus size.
3. **Mirror KKSongs** — lyrics, Bengali-script pages and header metadata only, never the
   purports — and send the permission note in parallel.
4. **Build the search-and-cache layer** for Caitanya-caritāmṛta, Caitanya-bhāgavata and
   anything else the index misses: source URL required, allowlist enforced, cached by skeleton
   so each verse is resolved once ever.
5. **Check Sanskrit Wikisource** (better licence, solves Gītā 18) and the `gaudiyakirtan`
   repository. An hour each.
6. **Pilot LLM span detection** on the reference lecture — and only as offsets.
