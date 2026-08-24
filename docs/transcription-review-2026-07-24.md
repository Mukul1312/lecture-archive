# Hindi Transcription Review — `data/hi/train_final` (2026-07-24)

Audit of the human-reviewed Hindi transcription set produced by
`build_hi_review_v3.py` → review app → `cut_hi_final.py`.

**Scope:** 106 clips / 14.54 min, all from `ggm-hindi-lecture-01`.
**Method:** structural checks (ffprobe durations, cross-file consistency, chars/sec
outliers) + line-by-line reading of all 106 Devanagari transcripts, with each suspected
error cross-checked against the three raw ASR drafts in `train_hi_v3.jsonl`
(IndicConformer-600M RNNT / Vaani-Hindi / Trelis-Hinglish) and, for verse quotations,
against the canonical Sanskrit.

**Verdict:** the mechanical pipeline is clean — no missing files, no manifest drift.
The problems are (a) coverage, (b) one text/audio desync, and (c) ~19 word-level
transcription errors, most of which are cases where the reviewer picked the wrong ASR
draft on a single word and a *different* draft had it right.

---

## 1. Structural integrity — PASS

| check | result |
|---|---|
| `train.jsonl` / `metadata.csv` / `train.voxcpm.jsonl` row counts | 106 / 106 / 106 ✔ |
| text agreement across all three manifests | 0 mismatches ✔ |
| wavs on disk vs manifest | 106 present, 0 missing, 0 orphan ✔ |
| ffprobe duration vs manifest `duration` | 0 deviations > 60 ms ✔ |
| empty / whitespace-broken text | none ✔ |
| leftover `[...]` filler brackets after `clean_text()` | none ✔ |
| total audio | 872.1 s = 14.54 min ✔ |

Duration spread: min 2.24 s, median 7.10 s, max 20.50 s (2 clips < 3 s, 15 clips > 15 s).
Vocabulary: 1961 tokens, 523 types, 279 hapax.

---

## 2. Coverage — only 1 of 4 lectures was harvested

`train_hi_final.jsonl` (the review-app download) contains **106 rows, all
`ggm-hindi-lecture-01`**. The v3 pool that was built and loaded into the review tool was:

| lecture | clips in `clips_hi` | kept |
|---|---|---|
| ggm-hindi-lecture-01 | 319 | 106 |
| ggm-hindi-lecture-02 | 194 | 0 |
| ggm-hindi-lecture-03 | 237 | 0 |
| ggm-hindi-lecture-04 | 195 | 0 |
| **total** | **945** | **106** |

Within lecture-01 the highest kept clip is `0267` of `0319`, so even that lecture was not
reviewed to the end. Roughly **626 clips (66 % of the pool) were never triaged**.

Consequences:
- The training set is **single-recording**: one room, one mic, one session. A LoRA trained
  on it would fit that channel, not just the voice.
- At the observed ~33 % keep rate, finishing lectures 02–04 would plausibly yield
  **~40–45 min** of clean audio instead of 14.5 min.
- The ECAPA "cross-lecture centroid" used for identity scoring draws on L2–L4, but no
  L2–L4 audio is in the training/reference set — so scoring and training sit on
  disjoint recordings. That is fine (arguably good) for scoring, but worth stating
  explicitly rather than leaving implicit.

This may have been a deliberate stop once 14.5 min was reached. Flagging it because
nothing in `docs/` records it as intentional.

---

## 3. Text/audio desync — 1 clip

`ggm-hindi-lecture-01_0234.wav`

- v3 segment: 3337.6–3341.9 s = **4.30 s**; final wav after review trim: **2.24 s**
- text kept in full: `यह कैसे समझेंगे मेरी बात मैं इते कृष्णा की बात बोलूंगा`
- density: **19.6 Devanagari chars/sec** vs a median of **7.9** across the set

The reviewer shaved ~48 % off the audio but did not shorten the transcript, so roughly
half of this line's text has no audio behind it. This is the only such case — the other
19 trimmed clips all land at a plausible speaking rate (the big trims on `0257`, `0236`,
`0096` correctly removed trailing `हरे कृष्ण` chanting / silence *and* the text was
edited to match).

**Recommendation:** drop `0234`, or re-trim it and re-cut the text.

---

## 4. Word-level errors — high confidence

Each row was verified against the three ASR drafts or against the canonical verse.
"Evidence" = why I'm confident, not a guess from context alone.

| clip | in the file | should be | evidence |
|---|---|---|---|
| 0004 | कीतन | **कीर्तन** | Vaani + Trelis drafts both say कीर्तन; the file itself uses कीर्तन in 0265/0267 |
| 0073 | भगवान के **भोजन** करते हैं | **भजन** | Vaani draft says भजन; "eats God" vs "worships God", 24/7 sādhu context |
| 0257 | नाम **भोजन** करेंगे | नाम **भजन** | Vaani + Trelis say भजन; 0258/0264/0267 all use नाम भजन |
| 0073 | चिंताई | **चिंतन** | garbled in all drafts (चिंताई/सिंचाई); चिंतन is the only real word here |
| 0030 | **घूरते** हैं **घूरना** | **घूमते** हैं **घूमना** | Vaani draft says घूमते; context is revolving in the birth–death cycle, not staring |
| 0030 | आयोमान | **आवागमन** | drafts आयोमान/आयामन; आवागमन = transmigration, fits "जन्म मृत्यु चक्र" exactly |
| 0031 | सावरजोनी ×2 | **स्थावर योनि** | drafts सावरजोनी/साबर जोनी; the listed items are पहाड़/पर्वत/वृक्ष/पेड़ — the immobile species |
| 0049 | ... भीष्म **बड़ी बयासकी वयम** | **बलि वैयासकि वयम्** | SB 6.3.20: `...प्रह्लादो जनको भीष्मो बलिर्वैयासकिर्वयम्` |
| 0049 | कपील | **कपिल** | file uses कपिल correctly in 0051/0052 |
| 0053 | सनक **सनंतन सनान्दन** सनत्कुमार | सनक **सनन्दन सनातन** सनत्कुमार | the four Kumāras: Sanaka, Sanandana, Sanātana, Sanatkumāra |
| 0056 | **उभ्रांत** सत्य | **अभ्रांत** सत्य | he is glossing English "Truth"; abhrānta = unerring. उभ्रांत is not a word |
| 0027 | माया **बुद्ध** जीव ×2 | माया **बद्ध** जीव | Vaani draft says मायाबद्ध; baddha-jīva = conditioned soul. बुद्ध = Buddha |
| 0027 | माया के **कब्ज** में | **कब्ज़े** में | कब्ज = constipation; कब्ज़ा = grip/possession |
| 0132 | **शुक्र** के जन्म | **सूकर** के जन्म | drafts सुगर/सुगार; paired with कुत्ते (dog) — it's the pig |
| 0229 | **सुकर** कुत्ता सुकर की तरह | **सूकर** | same word as 0132, and spelled a third way there |
| 0173 | एक सौ **वर्षा** | एक सौ **वर्ष** | IndicConformer says वर्ष; वर्षा = rain |
| 0146 | **भागव** धर्म | **भागवत** धर्म | the file uses भागवत धर्म correctly 8 s later in 0149 |
| 0064 | और **महारा** साधु महाजन | **हमारा** (or **महाजन**) | महारा is not a word; 2/3 drafts read महाजन there |
| 0122 | कृष्णा **saction** नहीं करेंगे | **sanction** | plain typo — 0126 spells it correctly |

Note the pattern: in 0004, 0073, 0257, 0030 and 0027 **one of the three ASR drafts had
the correct word and the review picked a different draft**. A "prefer the draft that
produces a real word" pass over the existing review data would recover most of these
without re-listening.

---

## 5. Needs an ear-check — meaning may be wrong

I could not resolve these from the drafts; they need someone to listen.

| clip | in the file | suspected | why it matters |
|---|---|---|---|
| 0198 | आँ कोई वैज्ञानिक लोग बताया है | likely a dropped **नहीं** | as written it says scientists *did* explain how to cleanse the heart; 0199 argues the opposite. A missing नहीं inverts the teaching |
| 0003 | जो प्रदान किए है कुछ भगवान की कथा | IndicConformer: **सुयोग प्रदान किए हैं तो** | current text is not grammatical; "granted the opportunity" is coherent, and he uses सुयोग again in 0092 |
| 0092 | जन्म में आपको **सुजुग** मिला है | **एक जन्म में ... सुयोग** | all drafts start with एक/ये (dropped); सुजुग/सुजुक is the Odia-inflected सुयोग |
| 0234 | मैं **इते** कृष्णा की बात | Trelis: **मैं तो** | (also the desync clip above) |
| 0150 | ये आत्मा **क्या** ही धर्म है | **का** ही धर्म है | 12.6 chars/s, the 2nd-fastest line in the set |
| 0043 | तो हम दुख दूर हुए | **हमारा दुख दूर होगा** | tense/agreement broken as written |
| 0112 | और **कोई कई** नेता लोग | **कोई कोई** | drafts split कई/कहीं/कोई |
| 0240 | **ओह** एक साधु वहां आए | **वो** | |
| 0006 | इस युग से युग में | IndicConformer: **इस युग से इस युग में** | |
| 0191 | bodily **conscious** of life | **bodily concept of life** | Prabhupāda's stock phrase; IndicConformer heard "constitution" |

---

## 6. Orthographic inconsistency — same word, two spellings

Matters for TTS: the model learns grapheme→phoneme from these strings, so two spellings
of one word teach two pronunciations.

| word | forms present |
|---|---|
| कृष्ण | कृष्ण ×38, **कृष्णा ×5** (0034, 0122, 0234, 0254 ×2) — कृष्णा is the feminine/Draupadī form |
| कीर्तन | कीर्तन ×3, कीतन ×1 |
| भजन | भजन ×5, भोजन ×2 (both wrong — §4) |
| विपद | विपद ×3, **बीपद ×2** (0060) |
| सूकर | सुकर ×2, शुक्र ×1 (both wrong — §4) |
| दुख | दुख ×11, दुःख ×1 (0114) |
| भगवद्गीता | भगवद गीता / भगवदगीता / भगवगीता — **three forms in three occurrences** (0033, 0039, 0096) |
| श्रीमद्भागवत | श्रीमद् भागवत (0044) / श्रीमद भागवत (0182) |
| सम्पत्ति | सम्पत्ति ×2, संपत्ति ×1 (both in 0101) |
| filler "haan" | हाँ ×13, हां ×2 |
| filler "aan" | आँ ×10, आ ×4 |
| जन्म | जन्म ×16, जन्मा ×1 (0030) |
| प्रह्लाद | प्रहलाद ×5 — internally consistent but non-standard; प्रह्लाद is the correct conjunct |

---

## 7. No punctuation anywhere

105 of 106 lines contain **zero** punctuation (the single exception is one comma in 0034).
There are no sentence boundaries, no commas at clause breaks, no `।`.

This is worth connecting to the prosody finding already recorded in
`hindi-clone-state-2026-07-06.md` — the clone measures "a touch higher-pitched and
flatter" than his real voice, with ~6/15 passages flagged flat. Unpunctuated
`prompt_text` gives the model no phrase-boundary signal to imitate, and unpunctuated
training text gives it none to learn. This is cheap to fix relative to a LoRA and is a
plausible (untested) contributor to the flatness.

---

## 8. Production impact — what is actually live today

`ref_shortlist.jsonl` supplies `prompt_text` to the live zero-shot path
(`gen_diary.py`, `final_v1.py`, `combine_v1.py`, `refsweep_hi.py`, `markup_test.py`,
`gen_fixes_expr.py`). Four of its 12 entries carry errors from §4:

- `0004` — कीतन
- `0053` — सनंतन सनान्दन
- `0146` — भागव धर्म
- `0191` — bodily conscious of life

**The current winning reference `0008` is clean.** All three ASR drafts read पघारते and
the reviewer correctly corrected it to **पधारते**; the English `spiritual sky` /
`spiritual kingdom` is right. So `data/hi/diary_entry2.wav` and the measured
0.836 / 0.864 ECAPA numbers are **not** affected by any error in this report.

---

## Recommended actions, in order

1. **Drop or re-cut `0234`** — the only text/audio desync (§3).
2. **Apply the 19 §4 fixes** to `train.jsonl`, `metadata.csv`, `train.voxcpm.jsonl` and
   `ref_shortlist.jsonl` together (they must stay in sync — they agree today).
3. **Ear-check the 10 §5 lines**, `0198` first — it is the one where the meaning inverts.
4. **Normalise spelling** (§6) with a small mapping table applied at manifest-build time,
   so it survives a re-cut instead of being hand-patched.
5. **Decide on coverage** (§2): if a LoRA is ever revisited, finishing lectures 02–04
   is the single highest-leverage data step available (14.5 min → ~40 min, and 4
   recording sessions instead of 1).
6. **Consider adding punctuation** (§7) — cheapest lever on the documented prosody gap.
