# Handoff — SSGGSM corpus transcription, reference build and repository split

**Written:** 2026-09-21, at the end of a long working session (2026-09-16 → 2026-09-21).
**Purpose:** everything a new session needs to continue without the conversation that produced it.
**Read first:** §1 (state right now) and §17 (resume checklist). Everything else is reference.

Conventions: "you" is the steward (Mukul). Times like `11:22` are positions in the Melbourne
mp3 (`90-11-14 SB12.10.2 MEL 90-85.mp3`) unless stated. "Measured" means a number was produced
by a command or a file on disk; "estimate" and "unverified" are labelled as such.

---

## 1. State right now

| Item | State |
|---|---|
| **Melbourne reference sitting** | **DONE (2026-09-21).** All 512 cues checked: 495 words confirmed, **17 corrected**, 0 unsure. Verified reference = `data/reference/MELBOURNE_vs_90-85_aligned-review.json` (6,494 words, span 11:22–1:20:16). The steward switched to the re-timed file with `--carry-over` |
| **First accuracy number** | **Measured (§10.12), Whisper `small`/beam 1: English 24.9% wrong or missing; Sanskrit 67.9% unrecognisable (217 of 676 recognised); WER 34.2% forgiving romanisation, 36.4% strict.** Harness: `scripts/transcript_accuracy.py` |
| **Subtitle timings** | The synced file is wrong mid-lecture (§10.4). **A validated re-timed file now exists:** `data/reference/MELBOURNE_vs_90-85_aligned.srt` (update 2026-09-21, §10.11) |
| **Whisper word-timing run** | **Done:** 5,951 words in 826 s (~5.1× real time). Long-form decoding **silently skipped speech** (e.g. 11:19–11:49); 30 gaps ≥6 s were re-decoded as short windows (`melbourne_gapfill.py`, +283 words) → `melbourne-whisper-small-words-gapfilled.jsonl` |
| **Next action** | Read **`docs/melbourne-reference-eight-point-findings-2026-09-22.md`** and **`docs/open-asr-model-survey-2026-09-22.md`**. The survey's top finding is not a model: faster-whisper discards whole 30 s windows when no_speech_prob > 0.6 and avg_logprob < -1.0, and every run so far left that rule on. Proposed next (awaiting the steward): bake-off stage A (Whisper with the skip rule off; batched), then Parakeet TDT v2 via onnx-asr, Sanskrit verse-span models, Qwen3-ASR; dropped words as the headline metric |
| **lecture-archive git** | Pushed through `162843a`; the steward approved pushing on 2026-09-21 |
| **narrator-voice** | Parked by the steward. Another session is working there (`playground/` is untracked — not ours, do not touch) |
| **rclone** | **Finished** — no rclone process was running on 2026-09-21 at 22:10. The steward freed the machine for 2–3 h of full-capacity work. (Still never invoke rclone on his behalf.) |

---

## 2. Repository topology after this session

### 2.1 The split (ADR-0013, accepted 2026-09-16)

- **`narrator-voice`** — new private repo (`github.com/Mukul1312/narrator-voice`), extracted with
  `git filter-repo` (run through `uv`) from a `git clone --no-local --single-branch` of `voice-cloning@4b2b4ed`.
  162 files, 77 commits kept (96 unrelated commits pruned), pack 743 KB instead of ~2 GB.
  Old→new commit hashes: `docs/voice-cloning-commit-map.txt` in that repo (e.g. `0a00936→a3809bb`, `3f6b00b→800b833`, `4b2b4ed→c8e434d`).
  Cross-repo links in its docs point at `github.com/Mukul1312/voice-cloning/blob/4b2b4ed…/…` (GitHub redirects to `lecture-archive`).
  Its `pyproject.toml` names the distribution `narrator-voice`; the import package stays `heritage_archive`.
- **`lecture-archive`** — this repo, renamed from `voice-cloning` on 2026-09-17 (GitHub rename + local folder + Claude memory folder).
  The old GitHub name redirects; **never create a new repo called `voice-cloning`** (it would break the redirects the permanent links rely on).
  Both repositories are **private** (an earlier claim that `voice-cloning` was public was wrong).

### 2.2 Commits in lecture-archive from this session

| Commit | What |
|---|---|
| `ea21ab2` | ignore local `.env` files |
| `62ce5a5` | narration docs: bounded live validation, Lane-B-only scope |
| `4b2b4ed` | ADR-0013 accepted (the split commit; permanent links pin to it) |
| `84daab3` | remove Narrator Voice (114 files) after its move |
| `f343d5d` | README retitled "Lecture archive" |
| `75fd4da` | `.gitignore` note: repository is private |
| `9ae0d9b` | ADR-0014 accepted |
| `3875ece` | ignore `data/reference/`, `data/catalogue/` |
| `2b85314` | reference editor (local web tool) |
| `fb70698` | editor: visible subtitle shift |
| `76463e4` | `retime` + `--carry-over` |

### 2.3 Environments

- `.venv` was **rebuilt** on 2026-09-17 as the enhancement environment (`requirements-enhance-windows.txt`, then `resemblyzer==0.1.4 --no-deps`): torch 2.0.1+cpu, numpy 1.26.4, DeepFilterNet, librosa.
  Default suite green in it: `tests/youtube_enhance` 274 run / 0 failures / 5 skipped (symlink privilege), `tests/ggsm_transcription` 132/132, `tests.test_legacy_script_paths` 2/2, `tests/reference_editor` 30/30.
  Versus `requirements.lock.txt`: 36/48 exact; 8 transitive packages one patch/minor newer; `cryptography`, `hypothesis`, `rfc8785`, `sortedcontainers` (shelved-package test deps) not installed. `pip install --no-deps -r requirements.lock.txt` would match the lock exactly — not run (steward's rule: no silent env changes).
- `.venv-transcribe` — faster-whisper 1.2.1, used for all Whisper runs.
- `.env.local` (Cartesia key + voice IDs) was **deleted from lecture-archive** after confirming a byte-identical copy in `narrator-voice/.env.local` (gitignored there).

---

## 3. Decisions of record

- **ADR-0013** — Narrator Voice lives in its own repo; transcription and enhancement stay together here. Repo boundary follows the only bounded-context boundary (the word "identity" means file hash here, vocal resemblance there). Evans' *DDD Reference* ties a context's boundary to "physical manifestations such as code bases"; Vernon (checked only via secondary quotes) recommends a repo per context. Relationship between the two contexts: Evans' *Separate Ways*.
- **ADR-0014** — the clean-room archive rewrite missed ADR-0004's 2026-09-05 start gate (no archive-context commit on any branch) and is **deferred**. New archive code **grows from real demand** in `src/lecture_archive/contexts/archive/` (package name `lecture_archive`, not `heritage_archive`). The first such pipeline is the **SSGGSM corpus pipeline** (§12). Triggers that reopen it: first commit of a new archive pipeline; three behaviour-changing commits to `scripts/youtube_enhance/cli.py` or `scripts/ggsm_transcription/store.py` within 60 days; a second defect from the two flows handling identity/hashing/locking differently. The steward may restart a clean-room rewrite any time with a new start gate.
- The **reference editor** is a helper under `scripts/`, deliberately not the pipeline, so it does not fire ADR-0014 trigger 1.

---

## 4. The SSGGSM corpus project — goals and the steward's decisions

| Topic | Decision / statement (date) |
|---|---|
| Scope | Transcribe the whole SSGGSM English lecture archive, ~5,000 lectures (steward's figure) |
| Audio source | Archive copied to Google Drive with rclone (running). **Drive files are the same files as archive.org `SSGGSM1985`–`SSGGSM1996`** (2026-09-18). The pipeline fetches from each row's archive.org `Download URL`; Drive is the preservation copy |
| Engine | **Local Whisper** — no money for Sarvam or any paid API (2026-09-17) |
| Output | A **website** that plays the audio with its transcript, **replacing OneNote**; transcripts are **drafted and corrected on the website**, with **private and public** modes; publish after hearing and correcting ("follow the flow of draft versions") (2026-09-18). **Open:** is this an existing site or one to build, and what stack? |
| Standard | **Read while listening** — the audio is always present; timing matters most (2026-09-17) |
| Non-English and chanted spans | **Mark them** (timestamped span, no guessed text) in v1 (2026-09-18) |
| Diarization | **Deferred** (2026-09-18); the steward later argued it helps with compilation tapes — the boundary test (§8) showed silence depth solves splitting and diarization would mislead there. Speaker labels in published text remain a possible later feature |
| Listening | The steward listens personally, 2–3 hours per sitting |
| When the machine runs | Decided together each time |
| Rights | Decide together; email the archive uploader (`ssggsm.archives@gmail.com`) later, not now — also ask whether more subtitle files exist |

**Correction workload reality (raised 2026-09-18):** ≥7,378 h of audio; correcting while listening runs ~1–2× audio length, so personal correction of everything at 2 h/day is 10–20 years. The pipeline must therefore make drafts cheap and point the listener at likely errors; publication order and policy are the steward's lever.

---

## 5. Corpus facts (measured)

### 5.1 archive.org audio items

Year items `SSGGSM1985`, `1986`, `1989`–`1996`: **5,936 original MP3s**; **≥7,378 h** among files with a recorded `length` (a lower bound). Per-item audio counts: 1985: 31 · 1986: 110 · 1989: 462 · 1990: 344 · 1991: 678 · 1992: 1,399 · 1993: 893 · 1994: 932 · 1995: 985 · 1996: 102.
Every file's metadata has `size`, `length` (seconds), `md5`, `sha1`. Licences: 1985, 1986, 1990 **CC BY-NC-ND 4.0**; 1989, 1991–1996 **CC BY-NC 4.0**. Filenames encode date, verse, place and tape series, in at least three date conventions (`21.8.85`, `85-08-21`, `85-8-21`).
Full parsed index: `data/research/ssggsm-2026-09/transcript-check/audio-index.json`.

### 5.2 The steward's tracking spreadsheet

Columns (17): `Folder Year | Primary Date | Date Quality | All Dates on Tape | Sessions Detected | Title / Tape Label | Scripture References | Session Type Codes | Location Code | Location Name | Variant / Source Marker | Quality / Consistency Flags | Duplicate Group ID | Tapes in Group | Likely Duplicate Copy | Filename | Download URL`.
A sheet **`Unique Events` lists 3,766 distinct event groups** (from 5,936 tapes, ~1.58 tapes/event).
The steward's methodology notes (condensed): ~50% of tapes are duplicate copies (ORG, MST, CPY, BTM, Rec1/Rec2, Side A/B) grouped heuristically by same dates + references + type + location — only listening can confirm; ~30% of tapes hold several lectures (`All Dates on Tape`, `Sessions Detected`), kept tape-level because boundaries are unknown; dates parsed from DD.MM.YY, YY-MM-DD, YYMMDD, M.YY with US-format swaps flagged and `00` placeholders kept as partial dates; wrong-year filings flagged, files not moved; location codes decoded via a legend (BBSR Bhubaneswar, MYP Mayapur, MAF Maison Alfort, ZUR Zurich, PHL Philadelphia …), 714 unique events (19%) have no location; session-type codes (ED, EP, AA, ACD, SP, HP House Program, GK Guru-katha/Kirtan series …); label defects standardised into flags (defective, incomplete/INCM, DEF, DUC, PQ poor quality, distortion, clipping, date uncertain); nothing content-verified; durations and sizes not included.
**Pending:** CSV exports of the tape sheet and `Unique Events` into `data/catalogue/` (gitignored). Joining archive.org durations then replaces every estimate below with a measured total.

### 5.3 Duplicates, compilations, bandwidth

- "~78% duplicates" in filenames is **clustering, not verified duplication**: only **12 MD5 values across 24 files (0.4%)** are byte-identical. The Melbourne pair `90-85` and `BTM143` is the **same recording, BTM143 transferred 4.9% fast** (5304.22 s vs 5564.27 s), with different MD5s. **MD5 cannot dedupe this corpus**; speed-normalised envelope correlation can (r 0.65–0.94 after slowing BTM143 by 0.9533).
- **Compilation tapes:** 1,954 files (32.9%) hold several lectures joined by "&" — 2,737 h, 157.8 GB, ~2,424 interior boundaries. 45 files sit in the wrong year item.
- **Bandwidth:** one archive.org stream measured ~1.06 MB/s (88.7 MB in 84 s); the Melbourne mp3 came at ~2.3 MB/s (89 MB in 38 s). Remote `ffmpeg -ss` seeks took 20 s to several minutes each. Bandwidth, not CPU, dominates splitting/dedup work unless local copies exist (**open question:** does the steward have local copies besides Drive?).

---

## 6. Existing transcripts — archive.org item `ssggsm-transcripts`

- **833 originals**: 710 `.rtf`, 82 `.doc`, 22 `.docx`, 3 `.pdf`, plus 2 `.srt`, `.xls`, `.mdb`, zips and plumbing. 680 carry a full `YYYYMMDD` prefix; 748 at least a year; `19000000` means unknown date.
- The item's own description: files ending "Final" are finished; **everything else is a draft that "may have many errors"**. Only **16 of 818 documents (2.0%)** are Final.
- **Sample of 8** (under 1% — indicative only): 5 verbatim-style, 3 lightly edited; **8/8 cover only part of their lecture** (tape sides, "cassette ends before class is finished"); **8/8 contain zero um/uh** (a typing convention); 8/8 have gap placeholders or spliced book text; **0/8 usable as a verbatim reference as-is**.
- **Draft vs Final:** only **2** genuine pairs exist (not 4). A Final pass changes ~2.3% of words (median), of which genuine English edits are **0.3–0.6%**; the rest is transliteration, timecode cleanup and verse completion. So drafts are nearly as good as Finals for English words once transliteration is normalised.
- **Pairing by filename fails:** 75/820 unique (≈62 corroborated), 597 ambiguous, 148 unpairable; verse references wrong on both sides sometimes. **Pair by text after ASR** (word overlap, then rare n-gram anchoring for offsets inside compilation tapes).
- **No transcript of the Zurich 1985-08-21 lecture exists; the item contains zero SB canto 6 transcripts.**
- **Two `.srt` files** are the only near-verbatim, timestamped material: `19901114_SB12.10.2_Melbourne_TakeHolyNameBecomeFearless.srt` (used for the reference) and `19920904_Radhastami_GadeiGiri.srt`.
- **Archive catalogue** (`Data base of lectures.xls`, `database for lectures.mdb`) was parsed with stdlib-only readers: a **typists' transcription work tracker** (Access `Table1`, 429 rows, created 2004), not a tape catalogue — no place legend, no tape/duplicate/session data; it does carry `status`, `done by`, `printed` columns. CSVs: `data/research/ssggsm-2026-09/refprep/catalogue/`.
- **Legacy Sanskrit fonts:** 61 of 66 sampled RTFs store diacritics as 8-bit font slots in **two incompatible families**. Family A (53 files) decoded: `0xE4 ā, 0xE9 ī, 0xEB ṇ, 0xF1 ṣ, 0xEF ñ, 0xE0 ṁ, 0xE5 ṛ, 0xE7 ś, 0xF9 ḥ, 0xF6 ṭ, 0xF2 ḍ, 0xFC ū`. Family B (8 files) uses lower slots (`0x80 ā, 0x83 ḥ, …`) and is damaged. Naive decoding corrupts text silently.
- **Tooling:** `antiword` and `pdftotext` exist in `/mingw64/bin`; no RTF library is installed — one validated stripper exists: `data/research/ssggsm-2026-09/refprep/rtf2txt.py` (agreement 0.97–1.00 with earlier extractions, fixes CR/LF-inside-literal splitting).
- **Glossary** (66 RTFs, 512k words): 4,407 candidate terms, 110 curated, variant clusters (Krishna/Krsna ×6, Gauranga/Gouranga …). Measured against the Melbourne reference: curated list covers 25% of Sanskrit word occurrences, full list 61%. Suggested prompt: *"Srila Gour Govinda Swami Maharaja speaks on Srimad-Bhagavatam and Bhagavad-gita: Sri Krishna, Radharani, Gauranga Mahaprabhu, Nityananda, Chaitanya-charitamrita, Srila Prabhupada, Bhaktivinoda Thakura, Gurudeva, guru, sadhu, shastra, bhakti, bhakta, prema, bhava, jiva, tattva, lila, katha, nama, acharya, Vaishnava, Goswami, gopis, Vraja, Vrindavan, Jagannath Puri."* Files: `data/research/ssggsm-2026-09/refprep/glossary/`.

---

## 7. Machine and engine facts

- Laptop: AMD Ryzen 5 5625U, 6 cores / 12 threads, 15.3 GB RAM, integrated AMD graphics only (**no CUDA**), ~40 GB free disk (2026-09-17).
- faster-whisper **1.2.1**: has `BatchedInferencePipeline` (batch default 8), `multilingual` (per-segment language detection), `hallucination_silence_threshold`, `hotwords`, `clip_timestamps`. **Batched mode ignores `hallucination_silence_threshold` and forces `condition_on_previous_text=False`.** `distil-large-v3` is English-only (`multilingual` silently off). Whisper cannot do Odia.
- Published CPU speed (README, i7-12700K, 8 threads): `small` int8 13 min audio in 1m42s (~7.6×), batched 51 s (~15×). No official CPU numbers for turbo/medium.
- **Measured on this laptop** (`small`, int8, beam 1, word timestamps, VAD, 4 threads): 150 s audio in 56 s, 70 s in 23 s, and the full Melbourne span running at ~2.5–2.9× real time. The earlier "30 min for the 89-min Zurich lecture" note is **unverified**; the Zurich job record only bounds it at ≤1.55× audio length.
- **Estimate, not measured:** one copy per unique event ≈ 3,766 × 1.24 h ≈ 4,700 h audio → at ~2.7× on 4 threads ≈ 1,740 CPU-hours (~73 days 24/7). Replace with real numbers after the CSV join and the settings matrix.
- Inspection lesson (Zurich job): `no_speech_prob > 0.6` flagged 481/785 segments (median 0.65) — useless as a flag; the 22 gaps over 10 s held the real problems; median word probability 0.93, 13.2% of words below 0.5.
- Transcript data size: ~635 KB per audio-hour with word timings (145 KB gzipped); ~40 KB/hour as plain text.

---

## 8. Splitting compilation tapes (tested 2026-09-18)

Tape `89-03-27 SB7.7.16 & 89-03-30 CCAdi4.225 BBSR DINA2.mp3` (92.4 min, 2 lectures):
- **Rule: silence depth, not length.** `ffmpeg -i tape.mp3 -af silencedetect=noise=-50dB:d=3 -f null -` returns exactly one interior gap, 2782.8–2790.2 s, confirmed by Whisper probes (lecture 1 cut off mid-topic; lecture 2 opens with verse + translation). Adaptive variant: tape noise floor = 10th percentile of 50 ms frame levels (−47.3 dB here); flag runs ≥2 s below floor −10 dB. At −35 dB, 48 of 49 candidates were noise and the longest silence was a false positive.
- The real gap floors at −66.6 dB — 19 dB below cassette hiss — so it is the fingerprint of a digital join.
- Loudness/spectral step and music heuristics did not help; drop them.
- **Diarization verdict:** would have found nothing (same lecturer both sides) and would likely have flagged a mid-sentence channel change at 73 min.
- Cost ≈ 96 s/tape, mostly download; ~6 core-hours for all 1,954 compilation tapes if local.

---

## 9. Website and hosting facts

- Google Drive cannot feed a synced player: the official embed is an iframe; `<audio src>` from Drive is undocumented and reported to 403 since 2024. Drive stays the preservation copy.
- archive.org already hosts every file publicly and free; the website should stream from the sheet's `Download URL`s (licences are non-commercial).
- If ever needed: Cloudflare R2 (10 GB free, no egress fees, ~$2–4/month for the audio, needs a custom domain), Backblaze B2 (10 GB free, $6.95/TB/month). GitHub Pages is capped at 1 GB.
- Read-along players: Hyperaudio Lite (MIT, v2.6.4 2026-08-04), ReadAlongs Studio-Web (MIT). WebVTT supports word-level timestamp tags ("karaoke-style").

---

## 10. The Melbourne reference (in progress)

### 10.1 Why it exists

The corpus has no verbatim answer key. Verifying the Melbourne subtitles (68.8 min, 6,505 words, 94.5 words/min) creates one, which lets us: measure word error rate (English, Sanskrit/names and coverage reported separately); choose model and settings by numbers; predict the steward's correction workload; test the glossary prompt; calibrate which warning signals point at real errors; check read-along timing; learn what the correction website needs; and keep a permanent regression check. Limits: one lecture, one hall; 6,500 words separates settings a few points apart, not hair-thin ones; CPU runs vary slightly; Sanskrit needs its own track (IAST vs Whisper romanisation). A second step (six 10-minute windows from other years/venues, ~3–4 h listening) may follow once the first numbers are in.

### 10.2 Files in `data/reference/` (gitignored — archive.org content)

| File | What |
|---|---|
| `90-11-14 SB12.10.2 MEL 90-85.mp3` | The audio, downloaded 2026-09-21, 89,028,797 bytes, **MD5 `cea44a7e3349b87789a73228057fb453` verified** against archive.org (`90-85-expected.json`) |
| `MELBOURNE_vs_90-85_synced.srt` | 512 cues, text correct, **timings wrong mid-lecture** (§10.4). Never edit it — the review is bound to its SHA-256 |
| `MELBOURNE_vs_90-85_synced-review.json` (+ `.bak`, `-snapshots/`) | **The steward's work so far** |
| `MELBOURNE-LISTENING-BRIEF.md` | Instructions, coverage, lag profile, how the first offset was built |
| `melbourne_words.py` | The transcription script (download → MD5 → cut 650–4840 s → faster-whisper word timings) |
| `melbourne-whisper-small-words.jsonl` / `.config.json` | Whisper words `{w, s, e, p}` in mp3 seconds, and the exact configuration + wall time (when complete) |

The subtitles are also the first real use of the corpus: the original SRT was timed against another copy (its clock reads 1:01:09 at the verse).

### 10.3 What the audio contains at the start (checked 2026-09-21 by listening and transcription)

0:00–~9:00 prayers and kirtan · 9:03 "12th canto, Chapter 10, Text 2" · **9:09–9:47 the full, slow recitation** (the steward's "one recitation") · 9:48–10:29 chanted again · ~10:26–11:19 word-by-word synonyms · **11:19–11:34 a quick reading of the verse = cue #1** · 11:34 "Translation" · 11:37 translation (cues #4–7) · **11:58–12:38 the translation read a second time — not subtitled** · 12:38 purport begins (cue #8 "Purport / Conditioned souls are attracted").
The steward confirmed by ear: verse read 11:22–11:39 matches cues #1–3; 1:20:04–1:20:15 matches cues #511–512.

### 10.4 Measured misalignment of the synced subtitles (2026-09-21)

| Audio | Subtitles are |
|---|---|
| 11:22 | ~3 s late |
| 12:05 – 16:00 | 32–39 s **early** |
| 22:00 – 34:00 | 23–25 s early |
| 40:00 – 47:00 | 4–12 s early |
| 50:00 – 60:00 | 14–15 s early |
| 78:20 – 1:20:15 | ~1.5 s early |

The first alignment (a workflow agent, reported as "high confidence") only checked the start, the song at ~46 min and the end, so the middle went unseen. A constant or smoothly warped offset cannot follow a file that skipped ~40 s of speech. Hence per-cue re-timing.

### 10.5 Spot-check anchors (Whisper-heard time ~ cue), for validating the re-timed file

`12:40 ~ #8` · `12:45 ~ #10` · `16:00 ~ #32` · `16:30 ~ #37` · `22:07 ~ #83` · `22:27 ~ #86` · `34:09 ~ #173` · `34:15 ~ #174` · `40:29 ~ #214` · `44:27 ~ #242` · `46:00 ~ #256` · `47:01 ~ #265` · `50:06 ~ #293` · `60:08 ~ #363` · `78:27 ~ #498` · `78:39 ~ #499` · `1:20:04 ~ #511` · `1:20:07 ~ #512`. (Matches with ratio ≥0.55 from a 40-s-window scan; the 70:00 window was ambiguous and is excluded.)

### 10.6 If the transcription run was interrupted

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv-transcribe\Scripts\python.exe -u data\reference\melbourne_words.py
```
It skips the download when the MD5 already matches. ~25 min at ~2.7× real time on 4 threads. It deletes its temporary `melbourne-span.wav` at the end (delete it by hand if a run died).

### 10.7 Re-time

```powershell
.\.venv\Scripts\python.exe -m scripts.reference_editor.retime `
    --srt data/reference/MELBOURNE_vs_90-85_synced.srt `
    --words data/reference/melbourne-whisper-small-words.jsonl `
    --out data/reference/MELBOURNE_vs_90-85_aligned.srt
```
It refuses to overwrite `--out`. The printed report gives cues anchored, words matched, unmatched cues, shift statistics and **`spoken_but_not_subtitled`** spans (expect ~11:58–12:38 among them). Keep that list: the accuracy harness must exclude those spans.

### 10.8 Validate before switching

Compare the new cue starts against §10.5 (within ~2 s), confirm cue #1 ≈ 11:19–11:23 and #512 ≈ 1:20:07, and check that `unmatched_cues` is small and mostly chanted/Sanskrit cues. If anything is far off, do not switch — investigate.

### 10.9 Switch the steward to the re-timed file (their work carries over)

1. Ask the steward to **stop the running editor** (Ctrl+C in its terminal) so no edit happens mid-move.
2. Start the editor on the re-timed file, importing the work:
```powershell
.\.venv\Scripts\python.exe -m scripts.reference_editor `
    --srt data/reference/MELBOURNE_vs_90-85_aligned.srt `
    --audio "data/reference/90-11-14 SB12.10.2 MEL 90-85.mp3" `
    --carry-over data/reference/MELBOURNE_vs_90-85_synced-review.json
```
It prints how many cues were carried (checked / corrected / unsure) and any cue it could not carry. It refuses if `MELBOURNE_vs_90-85_aligned-review.json` already exists. The subtitle shift resets to "not shifted" (re-timing replaces it). The local mp3 makes seeking instant.
3. Every later session: the same command **without** `--carry-over`.
4. Update `MELBOURNE-LISTENING-BRIEF.md`: the lag profile becomes obsolete.

### 10.10 After the sitting

1. "Download verified SRT" (or `GET /api/export.srt`) → the verified reference; "Download change log" → the list of corrections.
2. Build the accuracy harness. Rules from the 2026-09-18 synthesis (full text in `data/research/ssggsm-2026-09/workflow-results/reference-and-catalogue-prep.journal.jsonl`, label `synthesize`): the verified Melbourne file is the only primary reference; the two genuine Finals (19890310 SB4.20.28-29 Mayapur, 19890325 SB7.7.12-14 Bhubaneswar) are secondary, English-only, after transliteration normalisation; never use the `19000000 Another class` pair (two different lectures), the `19940215` Vishnupriya pair or the RipenedMango `.rtf/.odt` pair; never gate on similarity to the `_work` 1985 transcripts. Normalise fillers on both sides; exclude gap placeholders, spliced book text, paraphrased questions and `spoken_but_not_subtitled` spans; report English, Sanskrit/names and covered fraction separately.
3. First WER: the words already transcribed by `melbourne_words.py` are a valid first hypothesis (`small`, beam 1). Then the settings matrix (model size, batching, VAD, beam, glossary prompt) when the steward allows CPU time.

### 10.11 Update — re-timing done and validated (2026-09-21, commit `d71039f`)

- First attempt (global word matching) put the translation cues on the **second** reading (it runs into the purport, forming a longer match) and matched no Sanskrit cue. Rewritten: each cue searches recognised words within 120 s of its current time, scores by **letter-level** similarity (Whisper glues compounds), with a 0.002-per-second prior penalty; a dynamic programme picks the best time-ordered set.
- Second problem: the 70-min long-form run **skipped 30 s at 11:19–11:49** (and other gaps). Fixed by re-decoding every gap ≥6 s as a short window (`data/reference/melbourne_gapfill.py`, log in `melbourne-gapfill-log.json`). **Pipeline lesson: long-form Whisper drops whole passages without any error; a gap re-decode stage is required** (the Zurich run lost a Sanskrit verse the same way).
- Result (`retime-report.json`): 433/512 cues anchored on their own words (median letter score 0.864); 79 placed proportionally (mostly chanted verses and short interjections). Cue #1 11:22.4, #4 "Translation" 11:33.8, first translation reading 11:37.9–11:51.7, #8 "Purport" 12:33.9. **Spoken but not subtitled:** 10:55.8–11:21.5 (synonyms), **11:56.3–12:33.9 (the repeated translation)**, 17:42.6–17:53.4, 25:11.8–25:21.3, **46:14.2–46:54.3 (song)**, 47:57.3–48:05.3, 59:10.2–59:29.5, 73:59.4–74:29.2, 75:31.9–75:43.4, 79:23.8–79:37.1 — the accuracy harness must exclude these.
- Spot checks of the largest remaining anchor differences (#32, #173, #174) show the re-timed cue starts sit exactly on their words; the anchors (segment starts) were the imprecise side.
- The lag profile in the listening brief is obsolete once the steward switches.

### 10.12 The sitting is done, and the first measurement (2026-09-21)

**The verified reference** is `data/reference/MELBOURNE_vs_90-85_aligned-review.json`: 512/512 cues checked, 495 `ok`, **17 `fixed`**, 0 unsure, 6,494 words, span 11:22–1:20:16, bound to `MELBOURNE_vs_90-85_aligned.srt`. Export a verified SRT / change log with the editor's buttons or `GET /api/export.srt`, `/api/changes.md`.

**What the 17 corrections were — a systematic editorial habit:** 15 of 17 are `"Do you understand?" → "you understand?"` (he omits "Do"; the subtitle writer tidied it). #121 adds "revered spiritual master"; #38 adds an extra "you understand?". Any transcript from this collection likely carries the same tidy-up, which matters when scoring drafts.

**First accuracy measurement** — script `data/reference/melbourne_wer.py` (reference = verified cues; hypothesis = `melbourne-whisper-small-words-gapfilled.jsonl` restricted to the reference span with `spoken_but_not_subtitled` stretches removed; fillers dropped on both sides; diacritics folded):

| Track | Result |
|---|---|
| English words (6,002) | **24.9% wrong or missing** |
| Sanskrit / names (676, IAST in the reference) | **67.9% unrecognisable** — 68 exact + 149 recognisable romanisations = 217 recognised |
| Overall | **34.2%** forgiving romanisation; **36.4%** strict (977 wrong, 976 missing, 331 invented, 4,576 exact, 149 near; hypothesis 6,033 words) |

The harness is now versioned: `scripts/transcript_accuracy.py` (tests in `tests/transcript_accuracy/`, in the README suite). English is scored strictly (so `soles→souls` is an error); Sanskrit counts as recognised when a reader would recognise it (character similarity, or after removing meaningless romanisation choices such as sh/s, v/b). Its strict total reproduces the earlier hand-rolled 36.4% exactly. **The Sanskrit result is real, not a spelling artefact:** the English `small` model genuinely fails on chanted verses, which supports the policy of marking chanted spans rather than guessing.

**Read it with care.** The Sanskrit track is mostly measuring spelling convention (`sri→shri`, `bhagavad→bhagad`), not recognition — **fix it to score romanisations by closeness before quoting it**. Typical English errors: `soles→souls` (homophone), `bewildered→build here`, `material→metal`. This is a baseline for comparison, not a verdict on Whisper.

**Settings matrix — started 2026-09-21 21:56 (see §10.13 for results as they land).** `data/reference/run_matrix.py` runs six configurations (small beam 1; small beam 1 + glossary prompt; small beam 5; medium; large-v3-turbo; turbo + prompt), each transcribed over the same span, gap re-decoded, and scored with `scripts/transcript_accuracy.py`. It is **resumable** (a configuration whose words file exists is skipped) and uses 10 of 12 threads. Estimated 2.5–3.5 h total, plus model downloads (~1.5 GB each for medium and turbo). Start with:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv-transcribe\Scripts\python.exe -u data/reference/run_matrix.py
```

It prints a summary table (WER, English, Sanskrit, minutes per configuration) and writes `data/reference/matrix-summary.json`.

### 10.13 Settings matrix — FINISHED (2026-09-21 21:56 → 2026-09-22 00:39)

Command (resumable, skips finished configurations):

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv-transcribe\Scripts\python.exe -u data/reference/run_matrix.py
```

Order: small beam 1 → small + glossary prompt → small beam 5 → medium → large-v3-turbo → turbo + prompt. Each: transcribe 650–4840 s, re-decode gaps ≥6 s, score with `scripts/transcript_accuracy.py`.

**Configuration 1 result (small, beam 1, 10 threads, 23 gaps re-decoded, 17.5 min, 4.0× real time):** WER 34.2% (36.4% strict), English **25.3%** wrong or missing, Sanskrit 68.0% unrecognisable.

**Configuration 2 result (small, beam 1, glossary prompt, 28 gaps, 18.5 min, 3.8x real time):** WER 34.5%, English **25.2%**, Sanskrit 68.2%.

**The glossary prompt does not help.** 25.2% against 25.3% English, and 68.2% against 68.0% Sanskrit, are both inside the ~0.4 point run-to-run variation, and it cost 1 minute more. The Sanskrit words it was meant to rescue did not improve. Whether a prompt helps a *larger* model is still open (configuration 6 tests it on turbo), but on `small` it buys nothing.

Two things learned already:
- **Run-to-run variation is ~0.4 points** (25.3% here vs 24.9% for the earlier 4-thread run of the same settings). Treat differences below ~0.5 points as noise.
- **More threads did not help**: 10 threads gave 4.0× real time against 5.1× on 4 threads for the same model. The gap re-decodes (many short windows) are included in this figure and parallelise badly. Worth re-checking on the larger models before choosing thread counts for the corpus run.

#### The full table (all six configurations, same 69.8-minute span, same verified reference)

> **Superseded 2026-09-22:** these figures came from a scorer that dropped the heard words of 16
> cues while still scoring their reference words. Corrected table and the fix:
> `docs/melbourne-reference-eight-point-findings-2026-09-22.md`. The ranking and the choice did not change.

| configuration | English wrong | Sanskrit unrecognisable | WER | wall | speed |
|---|---:|---:|---:|---:|---:|
| `small-beam1` | 25.3% | 68.0% | 34.2% | 17.5 min | 4.00x |
| `small-beam1-prompt` | 25.2% | 68.2% | 34.5% | 18.5 min | 3.77x |
| `small-beam5` | 23.4% | 66.4% | 32.9% | 23.1 min | 3.03x |
| **`medium-beam1`** | **20.1%** | **61.4%** | **28.5%** | **34.2 min** | **2.04x** |
| `turbo-beam1` | 19.6% | 71.0% | 28.9% | 36.6 min | 1.91x |
| `turbo-beam1-prompt` | 20.2% | 69.1% | 29.6% | 32.5 min | 2.15x |

Counts (reference 6,678 words = 6,002 English + 676 Sanskrit):

| configuration | exact | recognisable | wrong | missing | invented |
|---|---:|---:|---:|---:|---:|
| `small-beam1` | 4556 | 146 | 980 | 996 | 310 |
| `small-beam5` | 4680 | 143 | 849 | 1006 | 339 |
| `medium-beam1` | 4889 | 169 | 773 | 847 | 281 |
| `turbo-beam1` | 4899 | 121 | 742 | 916 | 272 |

#### Decision: `medium-beam1`

`turbo-beam1` has the lowest English error (19.6% against 20.1%), but that 0.5 point gap is
exactly the measured run-to-run variation, so it is not a real difference. **Sanskrit
decides: 61.4% unrecognisable for medium against 71.0% for turbo — a 10 point gap, far
outside the noise.** Those are the names and verse terms the archive will be searched by.
Compute is a wash: turbo ran at 1.91x and 2.15x on two runs of the same model, so medium's
2.04x sits inside turbo's own noise, and medium's wall time was in fact shorter (34.2 min
against 36.6 min).

#### What the matrix settled

- **The glossary prompt does nothing.** No effect on small (25.2% vs 25.3%), and on turbo it
  traded English for Sanskrit, both around noise. Do not carry it into the pipeline.
- **`large-v3-turbo` is worse at Sanskrit than `small`** (71.0% against 68.0%), while being
  much better at English. Its aggressive distillation appears to cost exactly the vocabulary
  this corpus needs. A "better" model on paper was the wrong model here.
- **Model size beats beam width.** `small-beam5` costs 1.3x of `small-beam1` and buys 1.9
  points; `medium-beam1` costs 2.0x and buys 5.2 points. Spend compute on the model.
- **`medium-beam5` was not tested** and is the obvious next question: if beam 5 repeats its
  small-model gain on medium, English lands near 18% for about 45 minutes per lecture.
- **Sanskrit is the real problem and the decoder will not fix it.** The best of six
  configurations still fails on 61% of Sanskrit words. Two untried levers, in order of
  expected value: a **post-hoc lexicon correction** built from the 710 RTF transcripts
  (costs no decode time, testable on this reference), and faster-whisper's **`hotwords`**
  parameter, which is a different mechanism from `initial_prompt` and untested.
- **Dropped speech is still 12.7% of the reference** (847 missing words) with medium, after
  the gap re-decode. The gap re-decode stage is necessary but not sufficient.

### 10.14 Timing polish of the 79 guessed cues — tool built and measured

79 of the 512 cues never matched a heard word in the first re-timing, so their times are
interpolated between their neighbours. `data/reference/polish_timings.py` searches for them
again using the steward's **verified** text (not the subtitle text, which held the 17 errors
he fixed) and a matrix transcript. Nothing is re-decoded, so it costs about a minute.

It has two modes, and the difference matters:

- **`--mode bracketed` (default, safe).** The 433 cues that did anchor keep their times
  exactly. Each unmatched cue is searched for only *between its anchored neighbours*, so a
  cue either finds real speech inside that bracket or keeps the guess it already had. By
  construction nothing the steward checked can move. **Measured against the `small`
  transcript: 26 of the 79 rescued, 0 regressions, 9 of them moving 2 s or more.**
- **`--mode global` (second opinion, do not apply blindly).** Re-runs the whole matcher.
  Against the same transcript it rescued only 9 **and lost 6 cues that had previously
  anchored**, and it disagreed with 16 already-anchored cues by 2 s or more — one by 19.8 s
  (cue 358). That list is a useful shortlist to listen to; it is not a set of fixes.

The global result is why bracketed is the default: a better global optimum for the whole
lecture is not the same thing as a better time for each cue, and the steward's checked cues
must not be collateral.

Neither mode writes to the review. `--apply` writes `…-review-polished.json` beside it and
leaves the original untouched.

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe data/reference/polish_timings.py --words data/reference/matrix-<winner>-words.jsonl
```

### 10.15 Overnight watcher (started 2026-09-21 22:41)

The steward went to sleep with the matrix running, so `data/reference/watch_matrix.py` runs
detached and does three things:

1. **Watches the output files, not the process**, so a restarted run still counts as the
   same work.
2. **Restarts the matrix if it dies** — the same resumable command, never a changed setting,
   at most 3 times, each restart written to `data/reference/watcher.log` and marked in
   `matrix-run.log`. (The restart path was tested against a dummy script before being
   trusted: it launches detached and appends its marker.)
3. **Writes `data/reference/MORNING-REPORT.md`** when all six configurations are scored: the
   comparison table, the recommendation (most accurate, then the fastest configuration
   within half a point of it, because half a point is the noise floor), what the winner
   costs per 1,000 hours of audio, the bracketed timing polish against the winning
   transcript, and — honestly — any configuration that produced no result, with the tail of
   the log.

The report builder was dry-run against the two finished configurations before the watcher
was launched, so its output is known to work rather than assumed to.

**The machine will not sleep:** "Sleep after" and "Hibernate after" are both 0 (never) on AC
power. The run only needs the laptop to stay plugged in.

### 10.16 Eight-point measurement workflow (launched 2026-09-22 09:52)

The steward framed the reference sitting as eight purposes. Points 1 (measure accuracy),
4 (test the glossary) and 7 (test the correction workflow) were already answered; point 2
(choose the model by numbers) is answered for model size and the prompt but **not for
batching or silence skipping**; point 8 (regression baseline) has every ingredient but is
not pinned. The four that needed real computation were given to a workflow:

- **correction workload** — edit *sites* rather than error words (adjacent errors are one
  fix), his observed working rate reconstructed from the review snapshot timestamps rather
  than assumed, and what choosing medium over small saves in *his* hours;
- **error-signal calibration** — ground-truth error labels, then nine candidate signals
  scored by precision, recall and **lift**, plus a proper post-mortem of the signal that
  flagged 481 of 785 segments;
- **read-along timing drift** — designed around the circularity trap: the reference's cue
  times came from Whisper, so cross-model disagreement is used as an honest floor instead;
- **Sanskrit lexicon headroom** — the upper bound of a post-hoc glossary pass *and* the
  damage it would do to English words that are currently correct.

A fifth agent then tries to refute all four, recomputing every headline number itself.

**Run `wf_1d5e654d-7eb`.** Script versioned at
`.agents/workflows/melbourne-eight-point-measurements.js` (see that directory's README for
how to resume, and where a run's output lives). Agent outputs go to
`data/reference/analysis/` (gitignored). If the run was interrupted — a usage limit, a
closed session — read `journal.jsonl` in the session's `subagents/workflows/wf_1d5e654d-7eb/`
directory **before** re-running: it records what each agent actually returned, and finished
agents do not need to be paid for twice.

### 10.17 Eight-point measurements — finished and verified (2026-09-22)

The workflow in §10.16 completed after one resume (the first attempt hit a usage limit on
two of its five agents; the three finished ones replayed from cache). The verifier
reproduced most arithmetic, **disputed several conclusions, and found a bug in
`scripts/transcript_accuracy.py`** that biased every earlier accuracy figure. The bug is
fixed with a test, all six configurations are re-scored, and the old scores are kept in
`data/reference/analysis/accuracy-before-scorer-fix/`.

Everything measured, point by point, with the verifier's corrections applied:
**`docs/melbourne-reference-eight-point-findings-2026-09-22.md`.**

### 10.18 Beyond Whisper: open ASR survey (2026-09-22)

The steward pointed out that only Whisper had been considered. A five-sweep survey with a
verifier (run `wf_4e095424-673`, script `.agents/workflows/open-asr-model-survey.js`)
produced **`docs/open-asr-model-survey-2026-09-22.md`**. In short:

- Before any model swap, turn off faster-whisper's verified 30 s skip rule
  (`no_speech_threshold=None`). It was on in all six matrix runs.
- Shortlist: Parakeet TDT 0.6B v2 (CC-BY-4.0, native word times, ~5-7 min per lecture on
  this laptop via onnx-asr or transcribe.cpp), Qwen3-ASR 1.7B, then Parakeet v3, Cohere
  Transcribe, Whisper large-v3 full, and Sanskrit models on verse spans only.
- For verses, retrieve the canonical text rather than recognise it: catalogue entries name
  the verse, and the canon is finite.
- "Non-autoregressive models don't drop speech" is not established. Dropped words must be
  the bake-off's headline metric.
- Don't feed enhanced audio to ASR by default.

---

## 11. Tools built this session (lecture-archive)

`scripts/reference_editor/` — stdlib-only, `127.0.0.1` only.
- `server.py` — static page + JSON API; `Host` check; saves need header `X-Reference-Editor: 1`; strict CSP (`media-src` allows only self and archive.org); atomic save (temp → fsync → `os.replace`), `.bak`, snapshot at most every 10 min; refuses a review from a different subtitle file; local audio with HTTP byte ranges; `--carry-over`.
- `review.py` — SRT parsing (only `b/i/u/font` tags stripped; `<inaudible>` is a word), review state `reference-review/1`, validation (timings and original words immutable; statuses `unchecked | ok | fixed | unsure`, `ok/fixed` derived from whether words changed), `export_srt`, `change_log`, `carry_over`.
- `retime.py` — per-cue re-timing from heard words (§10.7).
- `static/` — the page: player, speed buttons, "◀ 0.5 s earlier / 0.5 s later ▶" shift (moves highlight, printed times and seek target; never saved timings), follow audio, next unchecked cue, session notes, per-cue ✓ Checked / ? Unsure / ↺ Revert / note, Esc play-pause, F2/F4 ±3 s, Ctrl+Enter check-and-next, autosave with visible "Saved hh:mm:ss".
- Tests: `tests/reference_editor/` (30), in the README's default suite.

---

## 12. SSGGSM corpus pipeline — design draft (not yet written as a spec)

**Unit of work:** one job per **unique event** (3,766), not per tape. Pick a copy by `Variant / Source Marker` (prefer ORG/MST over CPY/BTM) and skip label-flagged defects (DEF, INCM, PQ); record the choice. Duplicates are **insurance**: retry with the next tape in the group if the chosen copy is bad; transcribing a second copy and diffing gives a free error locator for flagged events.

**Stages:** ① import the sheet CSV (report rows without audio, audio without rows, multi-part lectures) → ② queue in **SQLite** (stdlib; one writer; resumable) → ③ fetch one file at a time over HTTP from `Download URL` (disk budget: never mirror the corpus) → ④ verify size, duration, SHA-256 (lowercase, INV-DG-1) and archive.org MD5 → ⑤ transcribe (faster-whisper; config chosen by the reference) recording full config and wall time → ⑥ shape words → sentences → paragraphs; mark non-English/chant/unclear spans → ⑦ inspect (drop `no_speech_prob`; use gaps >10 s, repetition loops, words-per-minute outliers, low-probability share, invented text in gaps; calibrate on the reference) → green/amber/red → ⑧ publish versioned JSON (+ WebVTT) → ⑨ status CSV for the sheet. Compilation tapes split by silence depth (§8). Pause/resume and `--until` are requirements.

**Domain (ADR-0002/0005/0014):** bounded context `archive`; one aggregate `TranscriptionJob` (two doors create/rehydrate; transitions return events `RecordingFetched`, `RunCompleted`, `TranscriptHeld`, `TranscriptPublished`; idempotency as return value). Invariants: INV-TJ-1 transcript bound to the SHA-256 of the exact bytes; INV-TJ-2 only inspected, not-held jobs publish; INV-TJ-3 every run records full config, model snapshot, threads and wall time; INV-TJ-4 re-publishing creates a new version. Ports in `domain/ports.py`; adapters `faster_whisper_recognizer.py` (lifting the proven pieces from `scripts/ggsm_transcription/asr.py`: float-subclass fix, 1.0 s word-bound tolerance, gap computation), `job_repository_sqlite.py`, HTTP audio source, CLI. Layering tests first. No folder before its first file.

**Published transcript (draft schema `ssggsm-transcript/1`):** recording (sha256, md5, duration, audio_url), catalogue (id, title, date, place), run (engine, model, config hash, wall time, quality band, flags), paragraphs → sentences → words `[text, start, end, probability]`, spans `{kind, start, end}`, version. Corrections from the website must be stored durably with history — they are the most valuable, least reproducible output.

**The website** (separate repo, per ADR-0013's test — different stack and deployment, sharing only the transcript format): private drafts, correction, public publishing, archive.org audio, word-level read-along. The reference editor is its first working prototype.

---

## 13. Open questions for the steward

1. The correction website: existing (which, what stack) or to build?
2. Local copies of the audio besides Drive? (decides ~41 h+ of downloading)
3. CSV exports of the tape sheet and `Unique Events` → `data/catalogue/`.
4. Publishing details: public machine drafts with a "not yet corrected" badge, or only corrected lectures?
5. Rights for the CC BY-NC-ND years (1985, 1986, 1990) — later, with the uploader; also ask about more `.srt` files.
6. CPU scheduling for the settings matrix and, later, the corpus run.
7. After the first numbers: do the second reference step (six 10-minute windows)?

## 14. Pending work (mine), in order

1. ~~Re-time, validate, switch~~ **done** (§10.11); ~~first WER~~ **done** (§10.12).
2. Fix the Sanskrit track in `melbourne_wer.py` (score romanisations by closeness, e.g. character similarity ≥0.8 counts as heard), then rerun; after that, run the settings matrix when the steward frees the machine and pick a configuration by accuracy against compute.
3. Rank which of the ~800 draft transcripts are complete (last `(inaudible MM.SS)` / `(? MM.SS)` marker vs tape duration) — no audio, no listening.
4. One tested RTF extractor + legacy-font decoding (family B still undecoded).
5. Glossary across all 710 RTFs; final prompt/hotwords.
6. Join archive.org durations with the sheet CSV → measured hours, compute and download totals.
7. Write the pipeline design spec in `docs/superpowers/specs/` (§12), website section left open until question 1 is answered.

## 15. Corrections made during the session (so they are not repeated)

- `voice-cloning` was **private**, not public.
- "About 70 days" compute was based on an unverified note; measured speed is now in §7.
- "78% duplicates" is filename clustering; MD5 cannot dedupe (§5.3).
- "Four draft/Final pairs" — only two exist.
- "Use existing transcripts as a test set / align their text instead of ASR" — weakened: nearly all are partial drafts.
- "SSGGSM and Odia pipelines would share a lot of code" — withdrawn: there is no Sarvam code in the repo; the Odia work (Haladhara Swami) runs by hand.
- "DDD says nothing about repositories" — Evans and Vernon do tie contexts to code bases.
- The subtitle offset was "high confidence" — wrong in the middle (§10.4). The brief's "+0.5 s" direction was also wrong (the start is ~3 s **late**).

## 16. Parked: narrator-voice

- `doctor` from both repos reported `config_missing`, `layout_missing`: the studio root was never initialised — run `init` (with its private config) from `narrator-voice` before any live call.
- `tests/heritage_archive/narrator_voice/test_acceptance_walkthrough.py:111` fails (`SynthesisInvocation` has no `rendered_transcript_bytes`) — pre-existing since `843e7e2` (2026-09-07), outside the 195-test checkpoint.
- A separate session is doing Odia emotional-TTS research there (see that repo's `research/HANDOFF-2026-09-21.md`).

## 17. Resume checklist for a new session

1. Read §1, then check: is `melbourne_words.py` finished? (`melbourne-whisper-small-words.config.json` exists with `words` and `wall_seconds`.) If not, and no process is running it, rerun (§10.6).
2. Run §10.7, validate per §10.8, then do §10.9 **with the steward** (they must stop the editor first).
3. Ask the open questions in §13 that are still unanswered.
4. Research artefacts from 2026-09-17/18 workflows are preserved in `data/research/ssggsm-2026-09/` (indexes, match report, reference-set CSV, catalogue CSVs, glossary, both workflows' full results as `workflow-results/*.journal.jsonl`).
5. Respect: rclone never touched; no silent environment changes; commit locally, push only when the steward says; tests stay fixture-only and never touch private data.
