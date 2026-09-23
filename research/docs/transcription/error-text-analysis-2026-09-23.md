# Reading the mistakes, not the rates (2026-09-23)

!!! warning "Partly superseded the same day"
    Every remaining disagreement was then adjudicated one at a time — see
    [Are the models wrong, or our reference?](who-is-wrong-adjudication-2026-09-23.md).
    Two things here did not survive it:

    - **The claim that the reference abridges verses is withdrawn.** The reference quotes
      BG 18.66 and SB 12.8.40 in full and correctly. The edit sites were fragments of long
      verse quotations, and the context window hid the rest. The machines were mishearing
      chanted Sanskrit.
    - **The numbers below are superseded.** Two further reference faults were found and
      repaired (speaker labels appearing mid-cue, and bracketed editorial text), so the
      reference is now 6,613 words and ElevenLabs makes 459 stops against Whisper's 627.

    Everything else stands, and the ranking has not moved.

The nine-system bake-off said *how much* each system gets wrong. It could not say *what*,
and so it could not say whether a given mistake is fixable by routing to another system, by
a glossary, by a regular expression — or not at all. This is what the errors actually say
when you print them.

The first thing they said was that the measurement was blaming the recognisers for three
things they had not done. Those are now fixed, every system has been re-scored, and **the
ranking did not change**. The second thing they said is where the remaining correction
labour really lives, which is not where the earlier documents implied.

Tool: `data/reference/error_text.py` (`sites`, `patterns`, `compare`, `passages`).
Reports: `data/reference/bakeoff/errors/`.

---

## 1. Three ways the measurement was unfair, now repaired

Each was found by reading the repeated confusions, each is mechanical, and each is now
applied identically to the reference and to every transcript — which is what makes it a
normalisation rather than a thumb on the scale.

| what was counted as an error | why it is not one | fix |
|---|---|---|
| **Speaker labels.** "Mr Peter:" and "Gour Govinda Swami:" open 41 cues. Nobody says them aloud, so every system "dropped" them — 40 stops on ElevenLabs. | A note about who is speaking is not speech. | `strip_speaker_label`, removing 101 reference words |
| **Contractions.** The reference writes "he is"; ElevenLabs writes "he's". The old rule split apostrophes, making "he s", so `is → s` was counted 10 times, `will → ll` 8 times. | A corrector does not stop at "he's" for "he is". | `expand_contractions`, both sides |
| **Split clitics.** `flex-en-native` writes no apostrophes at all: "isn t", "don t", "he ll". | One regular expression repairs it; it is a formatting defect, not a word misheard. | `join_orphan_clitics`, both sides |

The contraction fix cuts both ways, and that is the test of its honesty: it *helped* the
systems that write apostrophes properly (ElevenLabs, Sarvam, flex-bn) and briefly made
`flex-en-native` look worse, because the old rule had been giving it a free pass on about
74 places where it genuinely emits broken text. The clitic-joining rule then gave that back,
on the principle that any real pipeline would run that regular expression.

### The corrected table

Fused rows are built on `elevenlabs-scribe-v2-keyterms50` as the base.

| system | WER | English | Sanskrit | dropped | **stops** |
|---|---|---|---|---|---|
| Whisper medium, skip rule off | 28.8% → **27.5%** | 20.3% → **18.7%** | 62.1% | 928 → 829 | 666 → **636** |
| Deepgram Nova-3 `en-IN` | 35.0% → **33.4%** | 24.9% → **22.9%** | 89.5% | 1,584 → 1,488 | 694 → **643** |
| flex `en native` | 26.5% → **25.1%** | 20.6% → **18.9%** | 41.9% | 705 → 609 | 700 → **664** |
| flex `bn mixed` | 28.5% → **27.0%** | 23.2% → **21.4%** | **38.6%** | 749 → 651 | 798 → **765** |
| Sarvam Saaras v4 `verbatim` | 23.8% → **22.7%** | 17.4% → **15.9%** | 45.9% | 729 → 637 | 633 → **609** |
| Sarvam `verbatim` + keyterms | 24.1% → **23.0%** | 17.6% → **16.2%** | 43.5% | 730 → 636 | 669 → **644** |
| **ElevenLabs Scribe v2** | 22.5% → **21.1%** | 13.8% → **11.9%** | 61.1% | 922 → 827 | 523 → **470** |
| ElevenLabs + 50 keyterms | 22.0% → **20.5%** | 13.6% → **11.7%** | 53.1% | 832 → 738 | 543 → **487** |
| ElevenLabs + Sarvam | 20.5% → **19.1%** | 12.7% → **10.8%** | 43.3% | 606 → 510 | 567 → **513** |
| ElevenLabs + flex | 20.7% → **19.2%** | 12.9% → **11.0%** | 42.9% | 649 → 555 | 577 → **520** |
| **All three combined** | 20.5% → **19.1%** | 12.6% → **10.7%** | 41.7% | 572 → **476** | 579 → **523** |

Reference: 6,799 → **6,698** scored words. Sanskrit rates are unchanged, as expected — none
of the three fixes touches a Sanskrit word.

**Every system improved and not one changed rank.** The decision in front of the archive is
the same decision. What changed is the size of the prize: ElevenLabs now makes **26% fewer
stops than Whisper** (636 → 470), not 21%.

---

## 2. Where the correction labour actually is

### It is a thousand small corrections, not a few catastrophes

| | Whisper | ElevenLabs + keyterms | all three |
|---|---:|---:|---:|
| stops that are **one word for one word** | 304 (48%) | **266 (55%)** | 282 (54%) |
| stops spanning 6+ words | 89 (13%) | 58 (11%) | 46 (8%) |

More than half of every remaining stop is a single word swapped for a single word. This is
the shape of the work: not rescuing lost paragraphs, but fixing `at` → `of`, `these` →
`this`, `them` → `thee`, one at a time, 487 times a lecture.

### It is mostly in plain English, not in the Sanskrit

Stops, and stops per 100 reference words of that kind:

| | plain English cues | cues mixing Sanskrit | verse or chant |
|---|---|---|---|
| reference words | 4,346 (65%) | 1,949 (29%) | 403 (6%) |
| Whisper | 399 — 9.2/100w | 188 — 9.6/100w | 49 — **12.2/100w** |
| ElevenLabs + keyterms | 279 — **6.4/100w** | 161 — 8.3/100w | 47 — **11.7/100w** |
| Sarvam verbatim | 374 — 8.6/100w | 185 — 9.5/100w | 50 — **12.4/100w** |

Verse is the densest trouble — about twice the stop rate of plain English — but it is only
6% of the words, so it is under 10% of the stops. **Roughly three-fifths of the labour is
plain English with no Sanskrit anywhere near it.** This is consistent with the earlier
finding that half the errors are plain English, and it is the unglamorous fact the
code-switching story tends to hide.

### What nobody delivers: the songs

Ten stretches of eight or more consecutive words are failed by all four systems — **184
words, 2.7% of the lecture**. They are almost entirely Bengali songs and chanted Sanskrit.
The longest is 41 words of Bhaktivinoda Ṭhākura's *Bhuliyā tomāre saṁsāre āsiyā*, where all
four systems write some version of "do you understand" and nothing else:

```
said:  ...here i will sing one song bhuliya tomare samsare asiya peye nana vidha
       byatha tomara carane asiyachi ami bolibo duhkehera katha...
whisper-medium-noskip        you understand
elevenlabs-scribe-v2-keyter  yeah do you understand
sarvam-saaras-v4-verbatim    do you understand
flex-bn-mixed                yes do you understand
```

**This matters for completeness, not for labour.** A 41-word blackout is *one* stop, so
these ten stretches account for only 7 or 8 stops out of ~500. Fixing them would barely move
the correction time. But they are 184 words of the lecture that currently do not exist in
any transcript, and they are among the most devotionally significant passages in it.

They are also **quotations**. They exist in print. This is the measured case for the verse
and song index: the fix is retrieval, not a better recogniser, and no amount of ASR spending
will produce it.

### 9.8% of the lecture defeats everything

Across Whisper, ElevenLabs, Sarvam and flex: 656 of 6,698 words (9.8%) are failed by all
four. At least one system is right on 90.2%. That gap is the ceiling on what any routing or
fusion strategy can reach, and the three-way fusion currently captures part of it.

Errors that are one system's own, and so recoverable by combining:

| system | words wrong | wrong where no other system is |
|---|---:|---:|
| flex `bn mixed` | 1,629 | **390** |
| Whisper medium | 1,615 | 256 |
| Sarvam verbatim | 1,348 | 108 |
| ElevenLabs + keyterms | 1,186 | **109** |

ElevenLabs is both the most accurate and the least idiosyncratic. flex is the opposite: it
contributes the most unique errors, which is why adding it to the fusion buys so little
(513 → 523 stops for 66 fewer dropped words).

---

## 3. The reference is not clean either

After the three fixes, **42 of ElevenLabs' 487 stops are places where the word it wrote
would still be recognised by a reader.** Reading them, they fall into three kinds:

- **Reference typos.** `puport` → *purport*, `commiting` → *committing*, `embarassed` →
  *embarrassed*, `rememberance` → *remembrance*, `deficity` → *deficit* (three times). The
  machine is right and is charged for it.
- **The subtitler tidied his English.** Gurudeva speaks Indian English; the reference
  normalises it. `are` → *is* (6×), `these` → *this* (3×), `have` → *has*, `libraries` →
  *library*. **The machines are transcribing what he actually said** — which is precisely
  what this archive wants, and the reference is the edited version.
- **Romanisation of names written without diacritics.** `bhaktivinode thakur` →
  *bhaktivinoda thakura* (4×), `saraswati` → *sarasvati*, `acarya` → *acharya*, `mahamantra`
  → *maha mantra*. The scorer forgives close romanisations only for words the reference
  wrote in IAST; names written plainly fall through to strict English scoring.

A sharper check: at **34 places, Whisper, ElevenLabs and Sarvam independently wrote the same
word and the reference disagrees with all three.** Three systems built by different teams on
different data do not converge on the same mistake; the reference is the likelier suspect.

None of this is repaired, because none of it is mechanical — it needs a person's judgement.
It is reported so the numbers are read correctly: **the true accuracy of every system is
somewhat better than even the corrected table shows**, by roughly 5–8% of the stop count.

The last of the three *is* mechanically improvable, and is the clearest next fix: let the
closeness rule apply to any word in the archive's glossary, not only to words the reference
happened to write with diacritics.

---

## 4. Keyterms cost the language markers

An unnoticed trade-off. Plain ElevenLabs Scribe v2 marks non-English spans specifically:

| | `[singing]` | `[speaking Bangla]` | generic `[foreign language]` |
|---|---:|---:|---:|
| ElevenLabs Scribe v2 | **15** | **12** | 19 |
| + 50 keyterms | 0 | 0 | 43 |

With keyterms the specific labels vanish and become generic. Since those markers are the
free detector for exactly the passages nobody transcribes — the songs in §2 — this is a real
cost of the keyterm list, not a cosmetic one. If the routing plan depends on knowing *which*
language, the archive may want both runs, or the markers taken from a plain pass.

---

## 5. What follows

1. **The route decision is unchanged** and now rests on cleaner numbers. ElevenLabs alone:
   470 stops. All three: 523 stops but 476 dropped words against 738.
2. **Verse and song retrieval is now measured, not assumed**: 184 words per lecture that no
   recogniser will ever deliver, recoverable only from printed sources. It buys completeness,
   not time, and should be judged that way.
3. **Extend the closeness rule to the glossary**, so plainly-spelt names stop being scored as
   strict English. Expected effect: another ~2% off every system's stop count.
4. **Do not spend money on Sanskrit accuracy first.** Three-fifths of the labour is plain
   English. The Sanskrit is where the *rate* is worst; the English is where the *hours* are.
5. **Take the language markers from a plain ElevenLabs pass**, not the keyterm pass.
6. Still unmeasured, as before: a second reference lecture, word-timestamp accuracy for the
   read-along, and the corpus's real average length.

---

## Reproducing this

```
python data/reference/melbourne_bakeoff.py score <system>
python data/reference/error_text.py patterns elevenlabs-scribe-v2-keyterms50
python data/reference/error_text.py sites elevenlabs-scribe-v2-keyterms50 --kind wrong
python data/reference/error_text.py compare whisper-medium-noskip elevenlabs-scribe-v2-keyterms50 \
    sarvam-saaras-v4-verbatim flex-bn-mixed
python data/reference/error_text.py passages
```

The stop count is defined once, in `scripts/transcript_accuracy.edit_sites`, and pinned by
`tests/transcript_accuracy/test_error_sites.py`; the three fairness rules are pinned by
`tests/transcript_accuracy/test_fairness.py`. Before the fixes, that definition reproduced
every published figure exactly (666, 523, 543, 633, 579 stops and all their wrong/dropped/
invented columns), which is what licensed changing it.
