# Handoff: build the read-along page (2026-10-12)

**Read this before writing any code.** Everything needed already exists on disk; the task is
presentation, not new measurement.

## The first five minutes, if you read nothing else

1. **Regenerate the span manifest.** It covers **24 lectures; 56+ are aligned.** Spans are what
   mark where a transcript can be trusted, so building on the stale file silently omits most of
   the corpus. `.venv-indic/Scripts/python.exe -m scripts.scoreable` (§2).
2. **Only 5 alignments are verified. ~50 are not.** The page must say which is which rather than
   imply they are all sound. Verification needs a recogniser's words and only 9 lectures have
   any; 1 of the 6 checked **failed** (§4).
3. **Use `.venv-indic` for alignment, `.venv-api` for hosted recognisers, `.venv` otherwise.**
   The wrong one fails *after* doing the work (§6).
4. **Two background jobs are running** — the aligner and a wisdomlib fetch. Do not start a second
   copy of either, and do not run competing CPU work (§6).
5. **Expect the page to find alignment faults the numbers missed.** That is the point of it, not
   a failure of it (§1).

Everything below is the detail behind those five. **Treat claims in §8 as this session's
findings, not as ground truth** — each is evidenced, but a handoff can launder an inference into
authority, and six inferences in this project have already turned out wrong (§5).

## 1. What to build, and why it is the next thing

A page that plays a lecture's audio and highlights the transcript word by word as the speaker
reaches it. That is the archive's product: it lets a devotee read while listening, and it is the
reason forced alignment was built in the first place.

It is also the only test that catches what tables cannot. An alignment that drifts slowly scores
well and is instantly, obviously wrong when you watch text highlight against audio. **Expect the
page to find alignment faults that every number so far has missed** — that is a success for the
page, not a failure of it.

Secondary purpose, stated by the steward: everything so far has been numbers in a terminal, and
he cannot relate the work to the goal. The page is for him to look at.

## 2. Prerequisite: the span manifest is stale

`data/reference/analysis/scoreable-spans.json` has **24 lectures**. The aligner has since
finished **56** (and is still running; it will reach 78). Spans are what say *where a transcript
can be trusted*, so a read-along over all 56 needs the manifest regenerated first:

```
.venv-indic/Scripts/python.exe -m scripts.scoreable
```

Check what it actually writes before relying on it, and re-read `scripts/scoreable.py` —
`alignment_confidence` in it is **not a quality gate** (see §5).

## 3. Where everything is

All of `data/reference/` and `data/lectures/*/audio.mp3` are **gitignored** (`.gitignore:111`
and `:121`). The data is local only; do not expect it in a fresh clone, and do not try to commit
it.

| what | path | shape |
|---|---|---|
| word timings | `data/reference/analysis/archive-alignment/<slug>.json` | `words: [{word, index, start, end, score}]`, plus `coverage`, `mean_score`, `words_placed`, `transcript_words`, `invariants_violated` |
| trustworthy spans | `data/reference/analysis/scoreable-spans.json` | `detail: [{slug, audio, audio_seconds, spans, spans_detail: [{start, end, score, words}], share_of_audio, alignment_confidence, transcript_records_other_speakers, duplicate_of}]` |
| audio | `data/lectures/<slug>/audio.mp3` | 44.1 kHz MP3, VBR |
| transcript | `data/lectures/<slug>/transcript.txt` | the archive's published prose |
| identified verses | `data/reference/analysis/verse-runs.json` | `matched: [{slug, start, end, text, verse, song, score, margin, printed_words, scoreable, also_at_addresses}]` — `song` is the **address**, e.g. `Cc. Antya 20.22` |
| refusal diagnosis | `data/reference/analysis/refusal-diagnosis.json` | why each unmatched run was refused, with its top candidates |
| hosted transcripts | `data/reference/analysis/hosted/{elevenlabs,sarvam}/<slug>.json` | 6 and 8 lectures; `unit` is `word` or **`segment`** — Sarvam's times are segment-level |

`scripts/forced_align.py` holds `spoken_words()` and `problems()`; use them rather than
re-deriving what counts as speech or what counts as a broken timing.

## 4. Which lectures to show

**Only lectures whose alignment is trustworthy**, and trust is established by the placement
check, not by a confidence score:

> Restricting a grade to the trustworthy spans should only ever *help*, because it removes
> stretches nobody wrote down. A lecture scoring far worse inside its spans than over its whole
> file therefore has **misplaced words**. `scripts/compare_hosted.MISPLACED_RATIO = 1.5`, and it
> is measured: five sound lectures ran 1.00–1.23 while the broken one hit 2.11 and 5.64.

**The catch:** the check needs a recogniser's words, and only 9 lectures have any. So today you
can only verify 5 as sound (1 of 6 paired lectures failed). For the remaining ~50, the
alignment is **unverified**, and the page must say so rather than imply otherwise. Mark it on
the page. Do not quietly present unverified alignments as good.

This is also the open spend decision in §7.

## 5. Rules that will bite you

All of these are in `AGENTS.md`; these are the ones this task touches.

- **A transcript carries writing nobody said.** Speaker labels (`Gour Govinda Swami:`) and
  bracketed editorial text (`[verse]`, `[?]`) are notes to a reader. Use
  `scripts.forced_align.spoken_words`.
- **Timings must be checked, never assumed.** A word placed before its predecessor, or past the
  end of the recording, produces a page that highlights the wrong line and reports nothing.
  `scripts.forced_align.problems` checks these invariants.
- **`alignment_confidence` is not a quality gate.** The Melbourne reference, verified cue by
  cue, scores **0.2134**; the archive's transcripts average **0.3575** and 21 of 23 score above
  it. Any threshold above 0.21 rejects the one alignment known to be right.
- **Mark where the transcript can be trusted, don't classify the audio.** VAD does not separate
  chanting from teaching here. Grey out untrustworthy spans; do not label them "kirtan".
- **Six inferences of mine have failed in this project**, each plausible when made, each a number
  standing in for a property nobody checked. The list is in `AGENTS.md`. The most recent: I read
  a distribution of retrieval margins and concluded the system "cannot tell which verse it is",
  without reading a single refusal — in fact it had the right verse ranked **first** in 10 of 26,
  four at a perfect score, and 12 of the 26 were not verse quotations at all.

## 6. What is running in the background

- **The aligner** — `.venv-indic/Scripts/python.exe -m scripts.align_archive`. 56 of 78 done,
  resumable, writes atomically. Do not start a second copy; do not run competing CPU jobs
  (standing instruction from the steward).
- **Caitanya-bhāgavata Ādi/Madhya fetch** — `python -m scripts.wisdomlib_cb --fetch`, ~505 of
  7,800 pages, spaced 1.5 s, resumable. When it finishes: `--parse --write`, then
  `scripts/caitanya_bhagavata.py` picks the file up automatically.

Interpreters are not interchangeable: `.venv-indic` for alignment and transliteration
(`torchaudio`, `indic_transliteration`), `.venv-api` for hosted recognisers (`sarvamai`,
`requests`), `.venv` for everything else.

## 7. Open decisions that are the steward's, not yours

1. **~$12–28 to run both recognisers over the remaining aligned lectures.** It is the highest-
   leverage spend available: it verifies ~50 unverified alignments with the placement check,
   takes the system comparison from 5 lectures to ~30, takes verse runs from 44 to ~300, and
   takes the reference-error sample from 13,689 words to ~80,000. Do not spend it without asking.
2. **Two known retrieval defects, deliberately left unfixed** (deprioritised as a small slice —
   verse is ~6% of the Indic track, which is ~8% of words): non-verse runs are queried and
   pollute the results, and containment scoring gives short queries spurious perfect scores
   (`kāma eṣa krodha eṣa,` scored 1.000 against an unrelated song while BG 3.37 sat in the
   corpus). Fix these only if asked, or if the page needs them.

## 8. What the measured state is, so nothing gets re-derived

- **English engine decided: ElevenLabs Scribe v2 + 50 keyterms.** 11.7% against the archive's
  transcripts `[7.8, 17.1]`, ~**9.3%** after subtracting the reference's own wrong words; Sarvam
  16.8%. The gap survives bootstrapping over lectures. Melbourne's 10.5% sits inside the
  interval, so the ranking replicated across decade, continent and tape.
- **The yardstick's own error is measured**: the archive's transcripts carry a wrong word 2.39%
  of the time and omit speech 4.99% — a lower bound of 7.38%. Only the 2.39% inflates a
  recogniser's rate (`score()` does not charge insertions).
- **Verse is retrieval, not transcription.** 177,373 windows across KKSongs, GRETIL, Sanskrit
  Wikisource, Vedabase SB/BG/CC and Caitanya-bhāgavata. 18 of 44 runs matched, 16 right by
  reading. Both recognisers are poor on chanted verse (ElevenLabs 55.8%, Sarvam 68.8% over 77
  printed words) — which is why lookup beats transcription there.
- **Sanskrit cannot be chosen from this archive**: only 6.0% of its Indic tokens sit in runs of
  five or more words, against Melbourne's 24.6%. Its Indic words are names inside English
  sentences.
