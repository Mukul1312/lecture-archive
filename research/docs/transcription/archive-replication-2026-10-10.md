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
