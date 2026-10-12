# Does Melbourne's ranking hold on the archive?

**The English ranking replicates. The Sanskrit ranking cannot be tested on this corpus at all.**

Five archive lectures, read by both ElevenLabs and Sarvam with the same fifty keyterms, scored
only inside the spans where the published transcript can be trusted:

| | English | Indic | words graded |
|---|---:|---:|---:|
| **ElevenLabs Scribe v2 + 50 keyterms** | **11.7%** `[7.8, 17.1]` | **15.6%** `[7.7, 23.3]` | 12,642 + 1,047 |
| Sarvam Saaras v4 verbatim + 50 keyterms | 16.8% `[12.9, 21.4]` | 25.1% `[20.1, 29.2]` | 12,642 + 1,047 |

Intervals are 95%, from 1,000 bootstrap resamples of **lectures** — not words, because words
inside one lecture share a speaker, a room, a tape and a transcriber, and resampling them would
report a precision the evidence does not support. The honest n here is 5.

Paired, resampling the same lecture indices for both systems:

| track | gap | 95% interval | verdict |
|---|---:|---:|---|
| English | −5.12 pts | `[−7.80, −3.98]` | **separated — ElevenLabs better** |
| Indic | −9.55 pts | `[−13.30, −5.66]` | **separated — ElevenLabs better** |
| Bengali | +2.06 pts | `[−7.69, +7.09]` | straddles zero, and only 97 words |

## The one that replicates

Melbourne put ElevenLabs + keyterms at **10.5% English**. The archive puts it at **11.7%**, and
Melbourne's figure sits inside the archive's interval. A different decade, a different continent,
a different tape, a reference written by a different hand — and the English number holds. That
is what the hosted run was bought to find out, and it is the number the $760 corpus estimate
rests on.

## The one that does not, and why it is not an improvement

Melbourne put the same system at **53.4% Sanskrit**. The archive says **15.6% Indic**. A
38-point gain between two references is not a model getting better; it is a different task, and
the measurement says exactly how:

| | Melbourne, verified verbatim | Archive, published transcripts |
|---|---:|---:|
| Indic share of all words | 10.1% | 8.3% |
| Indic tokens in runs of 5+ words | **24.6%** | **6.0%** |
| longest run | 10 words | 6 words |
| top 20 Indic tokens as share of the track | — | 42.4% (`krsna` alone 15.8%) |

The *quantity* of Indic words is nearly the same. The *shape* is not. Melbourne's reference
carries connected Sanskrit — verse lines, recited — because a listener sat and wrote down what
was chanted. The archive's published transcripts carry Indic words almost entirely as **names
inside English sentences**: `Kṛṣṇa`, `Rādhārāṇī`, `Mahāprabhu`, `Śrīmad Bhāgavatam`. Not because
an editor marked the verse and we stripped it — the raw files contain almost no bracketed
annotations — but because connected recitation is largely not written down there.

And a name in a sentence is the easiest Indic word a recogniser will ever meet: it is surrounded
by English context, it recurs hundreds of times, and **fifty of them were handed to the
recogniser as keyterms**.

So the consequence is a limit on the corpus, not a result about the models:

> **The archive cannot be used to choose a Sanskrit system.** The place the Indian models win —
> flex `bn mixed` at 38.6% against ElevenLabs' 53.4% on connected verse — is 6% of the archive's
> Indic track. Choosing a verse recogniser needs verified verbatim reference text, which means
> Melbourne, or new listening.

## Reaching the Sanskrit gap without new listening (2026-10-11)

The limit above says a verse recogniser needs verified verbatim text. For verse specifically it
does not, because **a quotation has fixed printed text**: where a run of connected Indic words
can be matched to a printed verse, ground truth is exact and free.

`scripts/verse_runs.py` takes every run of four or more consecutive diacritic-marked words from
the forced alignment, with the stretch of audio it occupies, and matches it against KKSongs
through `verse_match`, whose margin gate refuses rather than guesses.

**44 runs across the five admissible lectures. 5 matched, 4 of them length-comparable and so
scoreable.** Scored against printed text neither recogniser has seen:

| | error over 24 printed verse words |
|---|---:|
| ElevenLabs Scribe v2 + keyterms | **29.2%** |
| Sarvam Saaras v4 + keyterms | 45.8% |

**Twenty-four words is far too few to carry a claim.** It is reported because the method is now
proven end to end - exact ground truth, no listening, no money - and because the direction
agrees with the span comparison.

### What the unmatched runs say, and they say it clearly

Reading all 39: roughly **26 are genuine quotations** and 13 are names, term lists or the
mahamantra. And the quotations are overwhelmingly **Caitanya-caritamrta and Bhagavatam**, which
a song book cannot hold:

```
 8w  "Yahan krsna tahan nai mayar adhikara" (Caitanya-caritamrta)
 9w  jivasya tattva-jijnasa nartho yas ceha karmabhih, labho jiveta yavata    (SB 1.2.10)
 5w  mahajano yena gatah sa pantha                                           (x3)
 5w  grha ksetra suta apta vittaih
 5w  gharma-vrsti sahe, anera karaye raksana                                 (CC Antya 20.22)
 4w  tri-tapas: adhyatmika, adhidaivika, adhibhautika.         <- a term list, not a verse
```

So the prize for fetching GRETIL - 14,067 Bhagavatam verses, explicitly licensed, researched and
never downloaded - is most of 26 runs in five lectures, which scales with the corpus. That is the
next concrete step for the Sanskrit question, and it costs a download rather than a listening
campaign.

### The canon fetched, and retrieval working (2026-10-11)

GRETIL downloaded and parsed: **14,293 addressed verses** - 13,594 Bhagavatam, 622 Gita. Both
files state **CC BY-NC-SA 4.0** in their own TEI header, verified here rather than taken on
trust. ShareAlike binds only a *published* index, and `data/reference/` is not in git.

| | matched | correct, by reading | scoreable | printed verse words |
|---|---:|---:|---:|---:|
| KKSongs only | 5 | 4 | 4 | 24 |
| **+ GRETIL** | **9** | **9** | **6** | **36** |

| | error over 36 printed verse words |
|---|---:|
| ElevenLabs Scribe v2 + keyterms | **44.4%** |
| Sarvam Saaras v4 + keyterms | 61.1% |

Six scripture addresses are now identified exactly: **SB 5.5.8**, **SB 1.2.10** (four times) and
**SB 3.2.23**. Before GRETIL, not one scripture citation could be resolved.

**44.4% against the 15.6% those systems score on the archive's Indic track is the composition
argument confirmed from the other side.** Connected recited verse is roughly three times harder
than names in English sentences - so the archive's Indic figure was never measuring the thing
the Indian models were winning at.

**The documented repair is real.** 842 starred long-metre Bhagavatam verses repeat their first
half-verse in the XML: BhP 1.1.2, 1.1.3 and **BhP 3.9.10**, a Melbourne citation, each print
their first half twice. A pada group identical to the one *before* it is dropped - compared only
against the previous group, so a poem that legitimately repeats a refrain is untouched - and the
regression test is written on SB 3.9.10 by name. The Gita file stops at **chapter 17**, so
BG 18.66, the archive's most-cited Gita verse, is absent; a test asserts that absence rather than
letting it surprise someone later.

### The last two gaps, closed and quantified (2026-10-11)

**BG chapter 18 is solved.** GRETIL's cleanly-licensed Gita stops at 17, so BG 18.66 - the
archive's most-cited Gita verse - was absent. Sanskrit Wikisource has all eighteen chapters at
**CC BY-SA 4.0**, read from the wiki's own `siteinfo`, and every page is stored with its
revision id because "the verse at this address" is only reproducible if the revision is
recorded. 700 verses, canonical counts in every chapter but 13 (34 against 35).

It is Devanagari, so it is transliterated to IAST by table - a reversible re-encoding, not the
forbidden act of *producing* scripture - and then checked against GRETIL on the 621 addresses
both editions carry:

| | of 621 |
|---|---:|
| letter-identical | 520 (83.7%) |
| GRETIL's verse wholly inside Wikisource's | **565 (91.0%)** |
| neither contains the other | 39 (6.3%) |

The extra text Wikisource carries is exactly `arjuna uvaca`, `sri-bhagavan uvaca`, `sanjaya
uvaca` and the chapter-head `om sriparamatmane namah`. So the transliteration is sound, and
chapter 18 is usable. The five test lectures quote no BG 18, so the match count is unchanged;
the capability is proved instead by a test that corrupts BG 18.66 **as read from the file** and
checks the index returns BG 18.66.

**Caitanya-caritamrta has no freely-licensed machine-readable text, now verified rather than
inherited.** Three independent checks: Exa returns only editions whose own pages name the
Bhaktivedanta Vedabase as their source (anantasatsang.org states it outright), Sanskrit
Wikisource does not carry it, and Bengali Wikisource - already an approved CC BY-SA source in
`verse_cache.SOURCES` - returns **zero hits**. The project's research had excluded BBT as in
copyright, so bulk ingest is not available and the **verse-by-verse route is the only one
open**. That decision belongs to the steward, so the plumbing is finished and left waiting:
resolved verses in the cache join the retrieval index automatically, with provenance attached.

And the remaining runs are now a **worklist of distinct quotations** rather than occurrences,
which is where the economics show. 35 unmatched runs across five lectures are **34 distinct
quotations**, each to be resolved once and then known for all 3,766 lectures. (Strict skeleton
grouping only collapses identical skeletons, so 34 slightly overstates it - `recall` is fuzzy,
so a near-duplicate of a resolved verse hits the cache at lookup and never needs resolving.)

### The canon completed, under BBT permission (2026-10-12)

The steward states that full permission from BBT is held, which settles the one gap that could
not be closed by licensing. **11,357 Caitanya-caritamrta verses** from the structured
`vaniwiki/prabhupada-books` corpus - an independent audit of the same corpus counts 11,359
entries, so it is the same text. **Verse text only, never the purports**, by the same rule the
KKSongs mirror follows, enforced by a test over the whole corpus rather than a fixture.

The retrieval corpus is now **134,354 windows**: 53,214 KKSongs, 43,858 GRETIL, 2,051 Sanskrit
Wikisource, **35,231 Caitanya-caritamrta**.

| | matched | correct by reading | scoreable | verse words |
|---|---:|---:|---:|---:|
| KKSongs only | 5 | 4 | 4 | 24 |
| + GRETIL | 9 | 9 | 6 | 36 |
| **+ Wikisource + Caitanya-caritamrta** | **20** | **18** | **15** | **90** |

| | error over 90 printed verse words |
|---|---:|
| ElevenLabs Scribe v2 + keyterms | **51.1%** |
| Sarvam Saaras v4 + keyterms | 68.9% |

Addresses now identified exactly include **SB 5.5.8**, **SB 1.2.10**, **SB 3.2.23**,
**BG 3.37**, **Cc. Madhya 17.186**, **Cc. Antya 20.22**, **20.24**, **20.26**, **Cc. Adi 17.29**
and **17.33**.

Two of the twenty are worth stating rather than burying. `ami bandhi achi hrdaya` ->
Cc. Madhya 25.127 is **uncertain** - plausible as a loose quotation, but containment scoring is
generous with a four-word query - and it **is** scored, contributing 6 of the 90 words. And the
mahamantra is cited to a KKSongs entry titled "Derdime Deva Eyler": the text is right, the
citation is absurd, and it is not scored.

### The corpus scope completed - and more corpus made retrieval slightly worse

The steward set the scope: **KKSongs, SB, BG, CC, CB**. All five are now in, at **177,373
windows**:

| source | windows | verses |
|---|---:|---:|
| KKSongs | 53,214 | 1,175 songs |
| GRETIL (SB, BG 1-17) | 43,858 | 14,293 |
| Sanskrit Wikisource (BG 1-18) | 2,051 | 700 |
| Vedabase SB/BG/CC | 68,378 | 20,270 |
| Caitanya-bhagavata Antya | 9,872 | 3,352 |

Caitanya-bhagavata's Antya-khanda came off the Internet Archive as one file rather than 3,352
page requests. **Adi and Madhya could not**: their archive.org scans are failed OCR - one item's
language was auto-detected as Armenian at "confidence 1.0", its text numeric noise - and the one
complete PDF answers 403 to everything. Those 7,800 verses are being fetched from wisdomlib a
page at a time, spaced, resumable, raw pages kept so a parser change costs no refetching.

| | matched of 44 runs | correct by reading | scoreable | verse words |
|---|---:|---:|---:|---:|
| KKSongs only | 5 | 4 | 4 | 24 |
| + GRETIL | 9 | 9 | 6 | 36 |
| + Wikisource + CC | 20 | 18 | 15 | 90 |
| **+ SB/BG/CB (full scope)** | **18** | **16** | **14** | **77** |

| | error over 77 printed verse words |
|---|---:|
| ElevenLabs Scribe v2 + keyterms | **55.8%** |
| Sarvam Saaras v4 + keyterms | 68.8% |

**Adding corpus cost two matches, and that is worth understanding rather than hiding.** A bigger
haystack holds more near-rivals, and the margin gate - which defends against citing the wrong
verse of scripture - refuses more as a result. `grha ksetra suta apta vittaih` went from matched
at margin 0.317 to **refused at 0.167** purely because the enlarged corpus introduced a
competitor. Nothing regressed in the instrument; the question simply got harder.

It also bought real improvements that the match count hides. BBT's segmentation supplies
**right-sized** windows where GRETIL's did not: `kam va dayalum saranam` now scores against the
5-word `kam va dayalum saranam vrajema` instead of being identified and then refused against a
10-word window, and `labho jiveta yavata` found a 3-word pada of its own.

And the refusals are not the gate being timid: of 26 unmatched runs, **only one** sits in the
near-miss band 0.20-0.25; the other 25 are well below it. So the limit is discrimination, not
threshold - which says the next gain for retrieval is longer runs or surrounding context, **not
more text**.

### The margin gate broke, and the way it broke is the finding

**Caitanya-caritamrta quotes the same verse verbatim at more than one address.** `radhayah
pranaya-mahima kidrsam` scores 1.000 at both Cc. Adi 1.6 and Cc. Adi 4.230 with identical text,
so a margin defended against "a different passage" is 0.000 and a correct identification is
refused. The rival is not a rival; it is the same verse under another number.

The first fix was wrong, and the data said so: skeleton **equality** does not group a *shorter
window of the same verse*, whose skeleton necessarily differs, so it went on cancelling the
margin. The relation is **containment**.

**The margin itself was not relaxed.** `Yahan krsna tahan nai` (0.033) and `bhartsana-tadane
kake kichu na` (0.111) stay refused, because their rivals are genuinely different verses, and a
test pins that.

Two reporting faults travelled with it: accepted matches printed `margin 0.0`, because the
display showed `verse_match`'s own margin rather than the one acceptance used - an output
contradicting itself - and BG 3.37 was cited to the KKSongs song that quotes it. Among
candidates that tie, the scripture is now cited rather than the song.

### Two defects the cross-check found, both mine

1. **My GRETIL parser was putting commentary inside verses.** `BG 3.17` came back as
   `evam sthite kim evam pravartitam caktram...` and `BG 11.1` as a colophon. The Gita file is a
   commentary, and Sankara's prose sits in **bare `<l>` elements of its own**, immediately
   before the `<lg>` holding the verse it discusses - so accumulating across that boundary
   attached the commentary to the next real address. Pending lines are now discarded when
   another element intervenes, which leaves the Bhagavatam's runs of bare `<l>` untouched
   because those are separated by whitespace alone. Letter agreement went 81.2% to 87.0%.
2. **My first cross-check measured the wrong thing** - 12.3% token agreement, which read as a
   broken transliteration and was nothing of the kind. The two editions segment sandhi by
   different conventions: `anantavijayam` against `ananta-vijayam`, `sahadevasca` against
   `sahadevas ca`. Identical sounds, different typography. Comparing letter sequences with
   spaces and hyphens removed - which is what `skeleton` does, and for the same reason - gave
   the figures above.

### Three more defects, same method: read the output

1. **Whole verses could identify a quotation but not score it.** A GRETIL verse runs 12-20 words
   while the archive quotes 4-13 - a teacher cites a half-verse and talks on. Each verse now
   offers its padas as well as itself, all under its own address so the margin is still taken
   over a *different* passage.
2. **Choosing the printed form by length alone was wrong, and it re-pointed three correct song
   matches at unrelated lines of the right song.** For KKSongs a passage is a whole song, not
   one verse. Candidates are now restricted to forms that account for the run as well as the
   winner does, and length only breaks ties among equals. This one was caught only because the
   output was read again after a change that looked like a pure improvement.
3. **1,962 KKSongs lines carry a combining mark with no base letter** - the letter is gone. The
   worst collapse to near-nonsense that matches almost anything, and once a length-comparable
   form of one existed it began contributing to the verse score. Dropped, with the 4,646 U+FFFD
   lines. The 5,482 whose acute sits *on* an `m` are kept, because `fold` and `skeleton` strip
   combining marks before anything is compared, so they change no number.

### What this settles about the Sanskrit question

Retrieval is the right frame. He teaches from a fixed canon, so each distinct verse is identified
**once, ever**, and its printed text is then exact for all 3,766 lectures - no listening, no
per-lecture cost. Nine identifications from five lectures at 100% precision on this read is a
working method, not a finished corpus; the next gains are **Caitanya-caritamrta**, which has no
machine-readable text and is resolved verse-by-verse through `scripts/verse_cache.py`, and
**BG chapter 18**.

### Three defects found by reading the output rather than trusting it

1. **One unmarked word was cutting verses in half.** SB 1.2.10 is `jivasya tattva-jijnasa nartho
   yas ceha karmabhih`, and `ceha` has no diacritics, so it split into two fragments. Bridging a
   single-word gap took the inventory from 39 runs to 92 at a floor of three. The gap is bounded
   in **time** as well, at 1.5 s: a one-word gap can be a six-second silence, and a test caught
   it joining two recitations nine seconds apart.
2. **A matched window can be longer than what was recited.** `aham bija-pradah pita` correctly
   matched `tasam brahma mahad yonir aham bija-pradah pita` - BG 14.4 - but only three of those
   seven words occupy the run's audio, so scoring both systems on all seven charged them four
   words nobody said there. Matches outside a 0.7-1.4 length band are now reported and not
   scored.
3. **The KKSongs mirror has an undocumented encoding defect.** Found by reading a match whose
   printed side came back as mojibake. 4,646 lines carry U+FFFD where a letter was lost
   (`jnana` stored as `j<FFFD>ana`); these cannot be ground truth and, being wreckage, match
   almost anything, so they are dropped and a damaged line now *breaks* the run of lines rather
   than being skipped over. A further 5,482 lines carry a combining acute where the anusvara
   belongs - cosmetic here, since `fold` and `skeleton` strip combining marks before anything is
   compared, and left unrepaired rather than guessed at. **The mirror should be re-fetched with
   the encoding fixed.**

Precision, by reading all five matches: **four right, one wrong** - the wrong one being a
wholly-mojibake corpus line, caught by the length gate before it could score. The floor of four
words is itself measured: at a floor of three, five of thirteen matches were wrong and **every
one of them was a three-word run**, with `Babu eka paisa` matching `tumhare darasa ke bhuke
pyase` three separate times.

One change that was indicated by the data and **did not work**: runs reach thirteen words while a
KKSongs line is four to six, so three-line windows were indexed. The corpus grew from 40,463
windows to 58,845 and recovered nothing.

## Two instruments that had to be fixed first

Neither number above was reachable until two measurement defects were found, and both reported
themselves as clean results.

**The Indic track was empty.** `span_score.score_span` decided which reference words were Indic
by walking the written words and zipping the marks against the folded tokens, falling back to
"all English" if the two counts disagreed. `fold` splits on punctuation, so `Vedānta-sūtras,`
becomes two tokens — the counts disagree on *every* real span. One 3,735-word span holding 214
diacritic words reported **0 Indic words**, and the fallback left no trace.
`transcript_accuracy.folded_with_marks` now folds each word and carries its mark to every token
it produces, which is what `load_reference` always did; the token sequence is identical, and the
counts cannot disagree.

**One lecture scored 91% for both systems.** Two independent recognisers failing identically
indicts the instrument, not the recognisers. The same reference text scored against the *whole*
transcript gives 16.1% — so the words are in the wrong places, and the spans were built from
those places. No constant time offset repairs it, so it is not the known decoder clock
disagreement; the alignment is internally scrambled.

That yields an alignment gate that `alignment_confidence` could never be, because it needs no
known-good case: **restricting a grade to trustworthy spans should only ever help**, so a lecture
that scores far worse inside its spans than over its whole file has misplaced words.

| | span error | whole-file error | ratio |
|---|---:|---:|---:|
| five sound lectures, both systems | — | — | **1.00 – 1.23** |
| `19941228-padayatra-arrival-bbsr`, Sarvam | 92.9% | 44.1% | **2.11** |
| `19941228-padayatra-arrival-bbsr`, ElevenLabs | 90.9% | 16.1% | **5.64** |

Nothing sits between 1.23 and 2.11, so the gate is set at 1.5 and that lecture is excluded by
name in the output rather than quietly dropped. One straw in the wind: it scores
`alignment_confidence` 0.1978, below Melbourne's verified 0.2134 — n=1, and not yet a rule.

## What these numbers are not

They are **agreement with the archive's published transcripts inside trustworthy spans**, which
is *system error plus reference error* with no way yet to separate the two. The transcripts are
faithful but they tidy. Every figure here ranks systems against each other on identical
material; none is a word error rate against what was actually said. The reference's own error
rate remains unmeasured and is the next thing worth measuring, because it costs no compute.

Two further caveats stated in the output of every run:

- **Sarvam reports segments, not words** (10–60 s). Its words are placed by spreading each
  segment evenly across its own duration, and the number of words that fell inside a segment
  crossing a span edge is printed per lecture — 21 to 209 on the admissible lectures.
- **The Sanskrit/Bengali split is provisional.** `indic_language` returns `sanskrit` whenever
  neither orthography is evident, which is right for a verse and wrong for a Bengali song built
  of words its pattern does not list: `pache`, `kangal`, `babu` and `paisa` all land in the
  Sanskrit bucket. With 97 Bengali words the split cannot carry a claim. The combined Indic
  figure is the sound one.

## Reproducing it

```
.venv-api/Scripts/python.exe -m scripts.hosted_run plan          # sends nothing
python -m scripts.compare_hosted
python -m unittest discover -s tests/compare_hosted -t .
```

Written to `data/reference/analysis/hosted-comparison.json`.
