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
| **Next action** | **Hand-mark ~100 word onsets** so forced alignment can be stated as accuracy rather than agreement (10.33). Then run `flex_timed.py` over a full lecture, and re-split the earlier verse-retrieval figures by language |
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
> `research/docs/transcription/melbourne-reference-eight-point-findings-2026-09-22.md`. The ranking and the choice did not change.

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
**`research/docs/transcription/melbourne-reference-eight-point-findings-2026-09-22.md`.**

### 10.18 Beyond Whisper: open ASR survey (2026-09-22)

The steward pointed out that only Whisper had been considered. A five-sweep survey with a
verifier (run `wf_4e095424-673`, script `.agents/workflows/open-asr-model-survey.js`)
produced **`research/docs/transcription/open-asr-model-survey-2026-09-22.md`**. In short:

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

### 10.19 Deepgram and other commercial services (2026-09-22)

The steward asked about Deepgram. Survey with a verifier (run `wf_659d3dd8-130`):
**`research/docs/transcription/commercial-asr-survey-2026-09-22.md`**.

- Deepgram: $200 free credit; Nova-3 costs ~$890 for the corpus (~$1,160 with keyterms),
  possibly doubled by stereo billing. It fetches archive.org URLs itself and has useful
  per-word confidence. But it is in the lower half on independent accuracy, and it skips
  non-English speech (verse) by design.
- The best independent evidence is for ElevenLabs Scribe v2 and AssemblyAI, including the
  fewest long runs of dropped words. Speechmatics is the privacy-friendliest free test.
- **Rights: permission received 2026-09-22.** On 2026-09-22 the steward reported: "I've also got permission from right-holders that transcription can be done on models." Recorded as permission to transcribe the lectures with ASR models, local or hosted. It does not clearly extend to a vendor *training* on the recordings, so hosted tests keep training switched off (Deepgram `mip_opt_out=true` on every request; ElevenLabs training disabled in settings; no AssemblyAI free tier, which cannot opt out) unless the rights-holder explicitly allows training too.
- **Rights come first:** the vendors require the uploader to hold the rights, and several
  train on uploads by default. Ask the rights-holder before any commercial test.
- The decision rule is correction labour: a paid service is worth it only if it removes
  enough of the ~690 fixes per lecture on the reference.

### 10.20 Code-switching is where the errors concentrate (measured 2026-09-22)

The steward's hypothesis: the errors come from relying on monolingual models (every run forced
`language="en"`) when the lectures are trilingual — English, Bengali and Sanskrit, with heavy
code-switching. Measured on `stagea-medium-beam1-noskip` with the fixed scorer
(`data/reference/analysis/codeswitch_errors.py`):

| cue type | cues | words | error rate | share of all errors |
|---|---:|---:|---:|---:|
| plain English | 329 | 4,336 | 19.3% | 46.3% |
| English with Sanskrit words | 148 | 1,975 | **36.8%** | **40.0%** |
| verse (>50% Sanskrit) | 35 | 367 | 67.8% | 13.7% |

**English words only**, by distance from the nearest Sanskrit word: **1 word away 49.8%** wrong
or missing; 2-3 words 24.8%; 4-10 words 16.8%; over 10 words 14.7%.

- **Cues containing Sanskrit hold 35% of the words but 54% of the errors.**
- **Code-switching damages the English around it**, not only the Sanskrit. An English word next
  to a Sanskrit word is wrong or missing more than three times as often as one far from any.
  Part of the gradient may come from how alignment assigns words inside a garbled block, so
  treat the size as approximate. The direction is unambiguous.
- **Code-switching explains about half the problem, not all of it.** English far from any
  Sanskrit is still ~15% wrong: accent, cassette audio and dropped words. A multilingual model
  alone will not fix that half.
- **The shortlist's best English models are monolingual.** Parakeet's vocabulary is English-only,
  Deepgram `en` skips other languages, and Qwen3-ASR has no Bengali or Sanskrit. By this
  measurement they risk the same damage at every switch.
- **The reference does not mark Bengali.** Bengali written without diacritics (*jakhona*) counts
  as English. Tagging Bengali spans is needed before trilingual models can be scored fairly.

### 10.21 Bake-off Stage A results (2026-09-22)

`data/reference/run_stage_a.py`. Each configuration changes one thing from `medium-beam1`.

| configuration | English | Sanskrit | WER | dropped words | verse-cue error | time |
|---|---:|---:|---:|---:|---:|---:|
| medium-beam1 (skip rule on) | 19.5% | 58.7% | 27.7% | 768 | 73.3% | 34.2 min |
| **medium, skip rule off** | **19.3%** | **55.8%** | **27.2%** | **706** | **67.8%** | 39.0 min |
| medium, batched | 21.2% | 71.6% | 29.6% | 1,147 | 88.0% | 23.9 min |

- **Skip rule off is the new baseline.** It is a small but real gain, concentrated in verse:
  verse-cue error fell from 73.3% to 67.8%. Only one segment in 957 still meets both skip
  conditions, and it is a verse. The cost is +14% time, from 24 temperature retries.
- **Batched mode is 43% faster but drops 441 more words**, and verse collapses to 88% error.
  Batched decoding relies entirely on Silero VAD segments, with a much tighter default
  segmentation (160 ms minimum silence) than sequential decoding. Chanted verse is what it
  loses most. **This points at VAD as a cause of dropped speech**, including in the
  sequential runs, which also use VAD. It is not yet proven; the test is sequential with VAD
  off, or batched with fixed clip_timestamps and no VAD.
- 60% of real speech segments score no_speech_prob > 0.6, which again shows the signal is
  meaningless on this corpus.

### 10.22 The steward's 34 Indic links (2026-09-22)

Read at source and verified (run `wf_b39c2eed-460`): **`research/docs/transcription/indic-links-survey-2026-09-22.md`**.
For SSGGSM, the find is **Prabhupadavani** (arXiv 2201.11391): 94 h of English devotional
lectures with code-mixed Sanskrit and Bengali, romanised with diacritics and counted per
language. It is a second, independent benchmark for the trilingual code-switching problem
(§10.20), with Bengali already marked. The audio is BBT/Vanipedia's, so it is fine as a
private test set but needs permission before any training. Indic-Transcribe-flex is the one
open recogniser trained on Indian English, Sanskrit and Bengali together. For the Odia seva:
IndicTrans2 (MIT, Odia to English) and Indic-Transcribe-core. Nothing new for narrator-voice.
The language models (Sarvam, Param-1, Qwen3 and its Sanskrit fine-tune) do not help:
deterministic verse retrieval and transliteration beat them.

### 10.23 Prabhupadavani benchmark and Indic-Transcribe-flex (2026-09-22)

The steward asked to test both Whisper and a code-switching model on Prabhupadavani.
Everything lives in `data/research/prabhupadavani/` (gitignored):

- `fetch_test.py` downloads the TEST split from the dataset's public Google Drive: 1,048
  subtitle lines from 20 clips, one small mp3 per line. Drive rate-limits with HTTP 503,
  so it retries with a long backoff and skips what it already has.
- `score.py` scores any system the same way, reusing `scripts/transcript_accuracy.py`.
  Because the released text does not tag Bengali separately, the two tracks are English and
  **Sanskrit + Bengali** (every word written with diacritics). It strips what nobody speaks:
  speaker labels from the dataset's own list (mid-line as well as at line start), scripture
  citations and editorial notes, but it keeps verse quotations that end in a colon
  ("Me śṛṇu:"), which a pattern-based stripper would have deleted.
  Two fairness normalisations are applied to every system and to the reference: apostrophes
  become spaces (flex writes "he ll", Whisper "he'll") and numbers under 1,000 are spelt out
  (flex writes "3 hours", the reference "three hours").
- `run_whisper.py` uses the Melbourne baseline exactly (medium, skip rule off).
- `run_flex.py` feeds flex the same joined audio through its own chunked helper, then
  converts Devanagari, Bengali and Odia script to IAST (stripping the nukta the
  transliteration library leaves behind).

**Flex measured on this laptop (probe, 61 s of real audio, CPU, 6 threads):**

| run | speed | what it writes |
|---|---|---|
| `lang=en` | 1.45x real time | plain English, no apostrophes; **translates Sanskrit terms**: the reference's *brāhmaṇa* becomes "Brahmin" |
| `lang=bn mode=mixed` | 1.30x | English in Latin, Bengali in Bengali script - the promising one |
| `lang=sa mode=mixed` | 1.31x | mangles plain English into Devanagari ("देर् इस् ए practical story") |
| `lang=hi mode=mixed` | 1.32x | the same problem |

So flex runs locally at about 1.3-1.45x real time (model load 14 s, ~5 GB of RAM in
float32). Only `en` and `bn mode=mixed` are worth scoring. Its card publishes **no English
and no Sanskrit accuracy**, and flex is weaker than its sibling *core* on their own
benchmark (11.3 against 8.7 average), but only flex has the mixed-script mode.

Setup: `.venv-indic` (a separate environment: torch CPU, transformers, sentencepiece,
soundfile, indic_transliteration); model in `data/models/indic-transcribe-flex` (4.89 GB,
the duplicate `nemo/` copy skipped). The model is gated; the steward accepted its licence
and `HF_TOKEN` is in `.env.local` (git-ignored).

### 10.24 What language models can do here (2026-09-22)

The steward pointed out that GPU rental and licences are available, so neither may be used
to dismiss a model. Re-judged on capability: **`research/docs/transcription/llm-roles-for-transcription-2026-09-22.md`**
(run `wf_40a9456e-3c0`). In short:

- **Free-form LLM correction of transcripts is the most replicated failure in the
  literature** (Whisper 3.89 -> 5.84 WER with GPT-3.5 on lecture speech; "all LLMs degrade
  the baseline ASR" in Apple's study; only *fine-tuned* mT5/ByT5 helped a strong Indic
  baseline). The failure mode, over-correction toward written language, is exactly what
  would erase Gurudeva's verbatim English. Our own matrix found the same one stage earlier:
  the glossary prompt made WER worse.
- **Text-only correction has an arithmetic ceiling of 10.6% WER** on the reference, because
  706 of 6,678 words are missing and no text model can hear them.
- **Missing words, located today** (answering the verifier's own gap): only 8% lie in the
  never-subtitled stretches; **92% are inside cues, i.e. the model did not write them**.
  Rate by cue type: plain English 7.7%, English-with-Sanskrit 13.4%, verse 17.7%. So
  dropping is twice as likely in code-switched passages (the steward's hypothesis again),
  but **half of all dropped words are still in plain English**.
- **Safe jobs for a model are the ones where it cannot invent words:** choosing between two
  recognisers (baseline: plain ROVER, free and deterministic), labelling each word's
  language, restoring punctuation with a token classifier, translating Odia.
- **Verse identification needs TWO indexes**: Sanskrit verses and Bengali padavali. The
  Bengali songs are where the most words go missing, and a Sanskrit corpus does not contain
  them.
- **Missed by the sweeps, worth following up:** Sarvam Saaras v4 accepts up to 50 keyterms
  *at recognition time* with a code-mix mode - glossary biasing where the literature says it
  belongs; Sarvam's API also hosts Gemma-4-31B and DeepSeek V4 Flash inside its free credit.
- **The binding constraint is human attention** (~690 edit sites x 3,766 lectures is roughly
  2.6M review decisions), which nobody has priced.

Order of work this implies: the second recogniser first (already running), then ROVER as the
baseline any model must beat, then constrained-edit model arms with a do-nothing control.

### 10.25 State at the end of 2026-09-22, and how to resume

**Running unattended tonight.** `data/research/prabhupadavani/run_tonight.py`, started 23:32,
detached (it survives this session ending). It waits for the Whisper run already in progress,
then runs the two flex configurations, scores all three and writes
`data/research/prabhupadavani/MORNING-REPORT-prabhupadavani.md`.

| stage | command (from the repo root) | output | expected |
|---|---|---|---|
| 1 | `.venv-transcribe\Scripts\python.exe -u data/research/prabhupadavani/run_whisper.py` | `whisper-medium-noskip/<folder>.jsonl` | ~48 min, ~2.1x real time |
| 2 | `.venv-indic\Scripts\python.exe -u data/research/prabhupadavani/run_flex.py --lang en --mode native` | `flex-en-native/<folder>.txt` | ~80 min, ~1.4x |
| 3 | `.venv-indic\Scripts\python.exe -u data/research/prabhupadavani/run_flex.py --lang bn --mode mixed` | `flex-bn-mixed/<folder>.txt` | ~80 min, ~1.3x |
| score | `python data/research/prabhupadavani/score.py data/research/prabhupadavani/<stage> --label <stage>` | `accuracy-<stage>.json` | seconds |

Every stage writes one file per clip folder and skips finished ones, so an interruption costs
only the folder in progress. Logs: `tonight.log` (the runner), `<stage>.log`, `whisper.log`.

**Power.** The steward was about to leave the laptop on battery at 45%. Tonight needs about
3.5 hours of continuous CPU, which the battery would not survive, and Windows throttles the
processor on battery. He plugged it back in. Sleep and hibernate are both set to never on
mains.

#### Environments and paths

| what | where |
|---|---|
| Whisper (faster-whisper 1.2.1) | `.venv-transcribe` |
| Scoring, editor, tests | `.venv` |
| Indic-Transcribe-flex (torch CPU, transformers, indic_transliteration) | `.venv-indic` |
| flex weights, 4.89 GB, gated model accepted by the steward | `data/models/indic-transcribe-flex` |
| Hugging Face token (read) | `.env.local`, git-ignored. Never print it |
| Melbourne reference and all Whisper runs | `data/reference/` |
| Prabhupadavani benchmark | `data/research/prabhupadavani/` |
| Research results from the four workflow runs | `data/research/*/workflow-result-*.json` |

#### What 2026-09-22 established

Each has its own write-up; this is the map:

1. **The scorer had a bug** that made every published figure too pessimistic; fixed with a
   test. Corrected baseline for medium: English 19.5%, Sanskrit 58.7%, WER 27.7% (§10.17,
   `research/docs/transcription/melbourne-reference-eight-point-findings-2026-09-22.md`).
2. **Whisper's no-speech skip rule** discards whole 30 s windows and was on in every earlier
   run. Turning it off is the new baseline: **English 19.3%, Sanskrit 55.8%, 706 dropped
   words** (§10.21). Batched decoding is 43% faster but loses the chanted verse (§10.21).
3. **Code-switching concentrates the errors** (§10.20): cues containing Sanskrit are 35% of
   the words and 54% of the errors; an English word next to a Sanskrit word is wrong 49.8% of
   the time against 14.7% far from any. Half the remaining errors are in plain English, so a
   multilingual model can fix about half the problem.
4. **The missing words are located** (§10.24): 92% sit inside cues, not in never-subtitled
   stretches; the rate is 7.7% plain English, 13.4% mixed, 17.7% verse. The worst individual
   cues are Bengali songs and Sanskrit verses.
5. **Open ASR survey** (`research/docs/transcription/open-asr-model-survey-2026-09-22.md`): Parakeet TDT and
   Qwen3-ASR shortlisted, but both are monolingual, which finding 3 makes a liability here.
6. **Commercial survey** (`research/docs/transcription/commercial-asr-survey-2026-09-22.md`): Deepgram supports
   Bengali and Indian English separately but cannot switch between them in one request, so it
   is a router target, not a code-switching model. ElevenLabs Scribe v2 and Speechmatics have
   better independent evidence. Rights permission received 2026-09-22; vendor training stays
   off.
7. **The steward's 34 Indic links** (`research/docs/transcription/indic-links-survey-2026-09-22.md`): the find is
   Prabhupadavani; IndicTrans2 and Indic-Transcribe-core for the Odia seva; nothing new for
   narrator-voice.
8. **Language models** (`research/docs/transcription/llm-roles-for-transcription-2026-09-22.md`): never let one
   rewrite a transcript; text-only correction has a 10.6% WER floor here; the safe jobs are
   choosing between two recognisers (baseline: plain ROVER), word-language tagging,
   punctuation by token classification, and Odia translation.

#### Decisions waiting for the steward

- Whether to test **Sarvam Saaras v4 keyterms** (biasing at the recognition stage, free
  credit) and the three commercial recognisers on the Melbourne reference.
- Whether to run **Parakeet TDT** locally (Stage B: one pip install, ~1.3 GB).
- Whether to spend one **timed correction sitting** on a different lecture, which is still the
  single most valuable measurement outstanding (it fixes the corpus-hours estimate, tests the
  error signal out of sample, and yields a second reference).
- Whether to mark ~100 word onsets by ear (~20 minutes) to turn the read-along timing bounds
  into measured accuracy.

#### Gotchas worth remembering

- `PYTHONIOENCODING=utf-8` before every Python call, or Windows cp1252 crashes on IAST text.
- Google Drive rate-limits with HTTP 503; `fetch_test.py` now backs off and retries. One clip
  line (`0580_clip36`) never returned audio and is excluded from both sides of the scoring.
- flex `lang=sa` and `lang=hi` mangle plain English into Devanagari; only `en` and
  `bn mode=mixed` are worth scoring.
- The transliteration library leaves Bengali's nukta behind; `run_flex.py` strips it.

### 10.26 Prabhupadavani results, and the Melbourne bake-off (2026-09-23)

The overnight runner finished all three stages by 02:12 with no intervention.
Report: `data/research/prabhupadavani/MORNING-REPORT-prabhupadavani.md`.

| system | WER | English | Sanskrit+Bengali | dropped | wrong | invented | speed |
|---|---:|---:|---:|---:|---:|---:|---:|
| **whisper-medium-noskip** | **17.2%** | **13.5%** | **27.6%** | 835 | 941 | 315 | 2.30x |
| flex-en-native | 18.6% | 13.8% | 33.1% | **608** | 1,256 | 395 | 1.97x |
| flex-bn-mixed | 20.5% | 15.9% | 35.0% | 711 | 1,402 | 374 | 1.94x |

**Whisper won overall, including on Sanskrit and Bengali** — the opposite of what flex's
design promised. But **flex dropped 27% fewer words** (608 against 835): it hears more and
writes it wrong, where Whisper stays silent. Dropped words are the error class no text-level
fix can repair, so flex looks like a complement rather than a replacement, which is the case
for combining two recognisers (plain ROVER first, per §10.24).

**The code-switching gradient barely appears on this corpus.** English wrong next to a
Sanskrit word against far from one: Whisper 17.2% vs 14.4%, flex-en 24.3% vs 13.2%. On
Melbourne the same measurement is 49.8% vs 14.7%. Three candidate explanations, untested:
cleaner audio; a different speaker; and — the actionable one — **Prabhupadavani audio is
pre-cut at subtitle boundaries**, so a model never has to recover mid-phrase. If that is the
cause, cutting Gurudeva's audio at phrase boundaries before decoding should reduce the damage
at switch points.

**So flex had not been tested where the problem lives.** Started 2026-09-23 09:42:
`data/reference/run_melbourne_bakeoff.py` (stages in `melbourne_bakeoff.py`), writing
`data/reference/MELBOURNE-BAKEOFF-REPORT.md`. To keep it fair to a system with no word
timestamps, all three decode the same **cut** audio: the reference span minus the 3.4 minutes
of never-subtitled speech (66.4 minutes in 11 pieces, `melbourne-cut.wav`), and scoring is
text-only for everyone with the same apostrophe and number normalisations. Whisper is re-run
on that audio rather than reusing its earlier timestamped output. About two hours.

### 10.27 The nine-system bake-off (2026-09-23) — the hosted services win

Full write-up, with method, costs and practical notes:
**`research/docs/transcription/commercial-bakeoff-results-2026-09-23.md`**. All nine decoded the same 66.4-minute cut
audio and were scored by one text-only scorer with three shared normalisations (apostrophes,
numbers, bracketed annotations). Clients: `data/reference/melbourne_bakeoff.py` (local + fuse
+ score) and `data/reference/commercial_bakeoff.py` (`.venv-api`; Deepgram and ElevenLabs over
REST because the ElevenLabs SDK cannot install on Windows, Sarvam through its SDK for the
batch flow).

| system | WER | English | Sanskrit | dropped | edit sites | speed |
|---|---:|---:|---:|---:|---:|---:|
| Whisper medium, skip rule off | 28.8% | 20.3% | 62.1% | 928 | 666 | 2.0x |
| Deepgram Nova-3 en-IN | 35.0% | 24.9% | 89.5% | 1,584 | 694 | 517x |
| flex en native | 26.5% | 20.6% | 41.9% | 705 | 700 | 1.4x |
| flex bn mixed | 28.5% | 23.2% | **38.6%** | 749 | 798 | 1.8x |
| Sarvam Saaras v4 verbatim | 23.8% | 17.4% | 45.9% | 729 | 633 | 118x |
| Sarvam verbatim + keyterms | 24.1% | 17.6% | 43.5% | 730 | 669 | 125x |
| **ElevenLabs Scribe v2** | 22.5% | 13.8% | 61.1% | 922 | **523** | 104x |
| ElevenLabs + 50 keyterms | 22.0% | 13.6% | 53.1% | 832 | 543 | 114x |
| ElevenLabs + Sarvam | **20.5%** | 12.7% | 43.0% | 606 | 567 | — |
| ElevenLabs + flex | 20.7% | 12.9% | 42.9% | 649 | 577 | — |
| **All three combined** | **20.5%** | **12.6%** | 41.4% | **572** | 579 | — |

- **The first result measured in the steward's hours: ElevenLabs cuts edit sites 21%**
  (666 -> 523). Model size, the skip rule and local fusion all moved words while stops stayed
  flat.
- **Three specialists, not one winner.** English: ElevenLabs (13.6%). Sanskrit: the Indian
  models, flex 38.6% and Sarvam 43.5% against Whisper's 62.1%. Fewest dropped words: Sarvam
  and flex. The steward's trilingual hypothesis in its strongest form.
- **Combining buys completeness at about ten stops each**: dropped words 922 -> 572 and
  Sanskrit 61.1% -> 41.4% across the chain, and even the three-way stays 13% below Whisper on
  stops. The method is deterministic (keep the base, insert the other only where the base
  wrote nothing), so it cannot hallucinate.
- **Keyterms work, but only inside the recogniser**: 50 names cut ElevenLabs' Sanskrit 8
  points. The same list failed as a Whisper prompt (WER worse) and as post-correction (~2
  points, confident wrong words).
- **Deepgram is out** (89.5% Sanskrit unrecognisable, 1,584 dropped) though it is 517x real
  time and has the best-evidenced per-word confidence - possibly useful as an error signal
  rather than a transcriber.
- **Public benchmarks have mispredicted this corpus three times out of three** (turbo, flex,
  Deepgram). Nothing may be adopted on reputation.
- **Code-switching persists everywhere**: English next to Sanskrit is wrong 36.7% of the time
  even in the best combination, against 8.3% far from any.
- **Cost if adopted**: ElevenLabs ~$760 (+20% with keyterms), Sarvam ~$1,180, both ~$2,000,
  all three ~$2,000 plus 9-15 laptop-days for flex. Spent producing the table: 2.2 h of
  ElevenLabs' free month, Rs 66 of Sarvam's Rs 100, $0.29 of Deepgram's $200.
- **Still unmeasured**: a second reference for these systems, word-timestamp accuracy for the
  read-along, whether flex's Sanskrit strength generalises, and the corpus average length.

### 10.28 Reading the mistakes: the scoring was unfair, the ranking was right (2026-09-23)

Full write-up: **`research/docs/transcription/error-text-analysis-2026-09-23.md`**. Tool:
`data/reference/error_text.py` (`sites`, `patterns`, `compare`, `passages`); reports in
`data/reference/bakeoff/errors/`. The stop count now lives in
`scripts/transcript_accuracy.edit_sites`, pinned by tests; before it was changed it
reproduced every published figure exactly, which is what licensed changing it.

**Three scoring faults, found by printing the errors, all now fixed on both sides:**
unspoken speaker labels ("Mr Peter:" opens 41 cues), contractions ("he is" vs "he's"), and
clitics a recogniser split off ("isn t" - `flex en native` writes no apostrophes at all).
Everything re-scored. **The ranking did not change; every figure improved.**

| system | WER | English | dropped | stops |
|---|---:|---:|---:|---:|
| Whisper medium, skip rule off | 27.5% | 18.7% | 829 | 636 |
| flex bn mixed | 27.0% | 21.4% | 651 | 765 |
| Sarvam Saaras v4 verbatim | 22.7% | 15.9% | 637 | 609 |
| **ElevenLabs Scribe v2** | 21.1% | 11.9% | 827 | **470** |
| ElevenLabs + 50 keyterms | 20.5% | 11.7% | 738 | 487 |
| **All three combined** | **19.1%** | **10.7%** | **476** | 523 |

Reference 6,799 -> 6,698 words. **ElevenLabs now makes 26% fewer stops than Whisper**, not
21%. `research/docs/transcription/commercial-bakeoff-results-2026-09-23.md` has been corrected throughout.

**Where the labour actually is, now that it can be read:**

- **55% of remaining stops are one word for one word.** Not lost paragraphs - `at` -> `of`,
  `these` -> `this`, `them` -> `thee`, 487 times a lecture.
- **Three-fifths of the labour is plain English with no Sanskrit near it** (279 of 487 stops,
  6.4 per 100 words). Verse is the densest at 11.7 per 100 words but is only 6% of the words.
  The Sanskrit is where the rate is worst; the English is where the hours are.
- **Ten stretches, 184 words (2.7% of the lecture), are lost by EVERY system** - Bengali songs
  and chanted verse, the longest 41 words of Bhaktivinoda Thakura. But a 41-word blackout is
  ONE stop, so this is only ~7 stops: **a completeness problem, not a labour problem**. They
  are quotations, so the fix is retrieval from print, not a better recogniser. This is the
  measured case for the verse and padavali indexes.
- **9.8% of words defeat all four systems**; at least one is right on 90.2%. flex contributes
  390 errors no other system makes (most idiosyncratic); ElevenLabs 109 (least).
- **The reference is not clean either.** 42 of ElevenLabs' 487 stops are words a reader would
  still recognise: reference typos (`puport`, `commiting`, `deficity` x3), the subtitler
  tidying Gurudeva's Indian English (`are` -> is, `these` -> this - the machines are the
  verbatim ones), and romanisations of names the reference wrote without diacritics. At **34
  places all three independent systems wrote the same word and the reference disagrees**.
  Not repaired - it needs judgement - but it means every system is somewhat better than even
  the corrected table shows.
- **Keyterms destroy the language markers.** Plain ElevenLabs writes `[singing]` x15 and
  `[speaking Bangla]` x12; with keyterms both vanish into a generic `[foreign language]` x43.
  Take the markers from a plain pass.

**Next mechanical fix:** let the closeness rule apply to any word in the archive's glossary,
not only to words the reference happened to write with diacritics (~2% off every system).

### 10.29 Are the models wrong, or is our reference? (2026-09-23)

Full write-up: **`research/docs/transcription/who-is-wrong-adjudication-2026-09-23.md`**.
Tools: `data/reference/error_text.py dossier` and `data/reference/adjudication.py`; verdicts
in `data/reference/bakeoff/errors/adjudication.json`.

All 483 of the best system's remaining disagreements were judged one at a time - from
independent agreement between six systems, from published scripture, and from sense. Every
verdict of "the reference is wrong" went to a second reader told to REFUTE it and to default
to refuted. **That pass overturned 50 of 122 claims (41%).**

| verdict | sites | share |
|---|---:|---:|
| **the model is wrong** | 349 | **72.3%** |
| the reference is wrong | 72 | 14.9% |
| nobody is wrong (spelling, romanisation) | 61 | 12.6% |

**The models ARE mostly making real mistakes.** Their own errors: mishearing English 136,
**mishearing Sanskrit 101**, writing a word nobody said 63. The Sanskrit class is the largest
recoverable one, which is the measured case for the combination over ElevenLabs alone.

**What is genuinely wrong with the reference:** dropped words 33 (`all sorts || religion`
missing "of"), tidied grammar 21 (the machines are the verbatim ones), typos 12 (`puport`,
`commiting`, `embarassed`), editorial text nobody spoke 6 (`(Laughter)`, `(inaudible reply)`,
`(SB 3.25.42)`).

**Two more scorer repairs, both found by the adjudication:**
1. `strip_speaker_label` removed only a LEADING label; 6 cues carry a second label mid-cue
   (16 words). Now every line-initial label is removed.
2. The reference writes editorial notes in ROUND brackets and the scorer stripped only square
   ones. Now both. Reference 6,698 -> **6,613 words**.

| system | WER first -> now | stops first -> now |
|---|---|---|
| Whisper medium, skip rule off | 28.8% -> **26.6%** | 666 -> **627** |
| Sarvam Saaras v4 verbatim | 23.8% -> **21.9%** | 633 -> **600** |
| **ElevenLabs Scribe v2** | 22.5% -> **20.2%** | 523 -> **459** |
| ElevenLabs + keyterms | 22.0% -> **19.8%** | 543 -> **474** |
| **All three combined** | 20.5% -> **18.3%** | 579 -> **509** |

**The ranking has not moved across three rounds of correction.** ElevenLabs now makes **27%
fewer stops than Whisper**, against the 21% first published. Every repair enlarged the gap.

**TWO CLAIMS OF MINE WITHDRAWN, both caught by the adjudication:**
- **The reference does NOT abridge verses.** It quotes BG 18.66 and SB 12.8.40 in full and
  correctly; the edit sites were fragments of long quotations and the context window hid the
  rest. The machines were mishearing chanted Sanskrit.
- **The first adjudication run was fed faulty evidence** for insertions (the record's "heard"
  field swept in the machine's rendering of the NEXT reference word, so every insertion looked
  like a duplicate). Judges called 116 sites alignment artifacts on that basis; the honest
  figure is 8. The run was discarded and repeated. A "mechanical confirmation" I ran used the
  same broken field and confirmed nothing.

**Known limit:** reference faults were found by adjudicating only ElevenLabs' sites, so other
systems' discounts are lower bounds and the per-system table flatters ElevenLabs. Settle it
before using this reference to judge a second lecture, not before the route decision.

### 10.30 The unexploited lever: pick the best system PER WORD (2026-09-23)

**Start a new session here.** The steward, reading the data himself in the inspector, said
there are "many possibilities to make a transcription 100%" and that the previous sessions
were looping on measurement rather than pursuing them. He is right, and here is the number
that makes the point:

| | words | share |
|---|---:|---:|
| best single system right (ElevenLabs + keyterms) | 5,628 | **85.1%** |
| **at least one of eight systems right** | 6,155 | **93.1%** |
| no system right | 458 | 6.9% |

**Eight points of headroom sit between the best single system and a per-word choice**, and
the deterministic fusion built so far captures only part of it, because it only fills gaps
where the base system wrote nothing. It never *replaces* a word the base got wrong.

How many systems are right at each word:

| systems right | words |
|---|---:|
| 8 of 8 | 4,020 |
| 5-7 of 8 | 1,270 |
| 2-4 of 8 | 713 |
| **only 1 of 8** | **152** |
| none | 458 |

The 4,020 unanimous words need no work. The middle band is where majority voting would pay.
**The 152 words only one system gets are the hard problem**: any voting scheme loses them, so
they need a selector that can back a lone dissenter - per-word confidence, or a language
model choosing between candidates (a job the LLM research already sanctioned, unlike
rewriting). Deepgram is the only system with well-evidenced per-word confidence and is 517x
real time, which is a role for it even though it is the worst transcriber here.

The 458 nobody gets are the Bengali songs and chanted verse: **quotations, so the answer is
retrieval from print, not recognition.** Together, per-word selection plus verse retrieval is
the only credible route to the steward's "100%".

**Tools for this are in place** (all under the gitignored `data/reference/`, see the warning
below): `error_text.py csv` writes the whole lecture as spreadsheets with timestamps, and
`inspect.py` serves `inspect.html`, a local page where clicking any row seeks the recording
to that moment. Five views: word-by-word grid, one system's mistakes, all systems compared,
what was lost, and who was judged wrong.

**A bug fixed on the way, which had been inflating things:** `error_flags` charged an
insertion to the reference word that followed it, so "sri" showed as wrong in 9 of 9 systems
when all nine wrote "sri". Insertions are still stops, counted by `edit_sites`; they are just
not any particular reference word's failure. Corrected figures: words no system gets right
6.9% (was 7.6%), words every system gets right 60.8% (was 59%). **The "9.8% of words defeat
all four systems" figure in 10.29 is inflated for the same reason and should be recomputed.**
Edit-site counts and WER are unaffected - they come from `edit_sites` and `score`, which were
always right.

**WARNING - none of this tooling is versioned.** `error_text.py`, `adjudication.py`,
`inspect.py`, `inspect.html` and every CSV live under `data/reference/`, which `.gitignore`
excludes wholesale for a licensing reason that applies to the archive.org audio and
subtitles, not to our own code. Twenty-plus scripts are affected, including the verifiers
that check published figures. The steward has been asked twice and has not yet decided; ask
once and act on the answer.

### 10.31 The pipeline, built and measured (2026-09-23)

**Read `research/docs/transcription/methodology-2026-09-23.md` first** - the five stages and
the honest list of what is missing. Everything below is code in `scripts/` (VERSIONED, unlike
the analysis tools under the gitignored `data/reference/`), with tests.

| what | where | tests |
|---|---|---|
| per-word selection between recognisers | `scripts/transcript_select.py` | 19 |
| verse retrieval from a garbled hypothesis | `scripts/verse_match.py` | 11 |
| the cache that becomes the corpus | `scripts/verse_cache.py` | 13 |
| the KKSongs song mirror | `scripts/kksongs_mirror.py` | 10 |

#### Stage 2, the English spine: confidence beat voting

**Plain ROVER voting LOST.** Against its own pivot it fixed 33 words and broke 75, net -42.
By setting: plain English net ZERO, mixed Sanskrit -30, verse -12. **A correction to 10.30:**
the 92.4% figure is a ceiling requiring an ORACLE that knows which system is right. Voting
has no such signal, so it captures none of the headroom; counting "two of three are right" as
recoverable was misleading, because those are mostly words the pivot already had.

**Confidence is the missing signal, and Whisper already emits it.** Its per-word probability
sat unused in the decode output. Checked before building on it: lowest-confidence quarter
**49.6% correct**, highest quarter **98.5%**. Using it to overrule the best single local
system (`overrule_where_confident`, threshold 0.50):

| | WER | English | Sanskrit |
|---|---:|---:|---:|
| **confidence-gated** | **23.7%** | **15.1%** | 48.4% |
| flex-en-native alone | 24.2% | 17.8% | 41.9% |
| gap-filling fusion | 24.7% | 17.1% | 41.9% |

Best local English measured, by two points. Threshold swept with the lecture split in half;
the gain holds on the unseen half (77.6% -> 78.7%) but smaller than on the fitted half.

**Deepgram is OUT as the second confidence source** - it would cost **$904** across the corpus
against **$759** for ElevenLabs as an outright better transcriber, and a confidence signal
runs on every lecture forever. The local replacements: **flex decodes through HuggingFace
`generate()`, so `output_scores=True` yields per-token log-probabilities** for a small wrapper
change and nothing per lecture (NOT YET BUILT - this is the next slice); and the forced
aligner needed anyway for timestamps scores every word uniformly.

#### Stage 3, the quotations: retrieval works, and refuses

`verse_match.py` matches a garbled hypothesis against printed verses on a phonetic skeleton.
Measured against the 59 verse lines of the verified reference, three local recognisers:

| min_margin | attempted | wrong | precision | recall |
|---:|---:|---:|---:|---:|
| 0.05 | 45 | 7 | 84% | 64% |
| 0.15 | 36 | 1 | 97% | 59% |
| **0.25 (default)** | 34 | **0** | **100%** | **58%** |

**Dropping vowels from the skeleton is what made never-wrong affordable** - before it, 100%
precision cost all but 47% recall. Measured: after folding, "a" alone was 27% of all
characters and "i" another 14%, two letters carrying 41% of the signal while discriminating
nothing. Consonants-only raised the mean margin 0.245 -> 0.286. Rare-letter signatures won
recall by 3 points but are not separable from noise at 59 verses.

**The default is the never-wrong end**, because a verse of scripture wrongly attributed to him
is not worth three extra verses recovered.

#### The corpus: search builds it, the cache IS it

The steward's insight, and it reframed the design: **an LLM that SEARCHES is not an LLM that
PRODUCES**, and search reaches what no download can - Caitanya-caritamrta and
Caitanya-bhagavata have no machine-readable text anywhere. The cost objection that killed
Deepgram does not apply because this is not per-lecture: 59 verse occurrences but 53 distinct
in one lecture, yet he teaches a fixed canon across 3,766 lectures, so **each distinct verse
is resolved once ever** and the marginal cost falls to zero.

**Sources are a RECORD, not a gate.** The steward has the licences and asked not to gate on
them. What is still enforced is that **a verse with no source URL is refused** - that guard is
about fabrication, not rights: models reproduce scripture exactly 32.6% of the time in English
and 7.3% in other languages.

**Measured with the real Exa key: search bridges MILD garbling and fails HEAVY.**
`bhayam dvitiya vinivesatah syat` -> found at rank 1. `upaja prapanna asmiyangri malam ti` ->
missed, returned three different "prapanna" texts. `ahani aprutartakarona nisini soyana` ->
missed badly, returned Sinhala pop music. So search is a fallback that works about half the
time, and downloadable text (GRETIL, wisdomlib) is worth more than it first appeared.

#### KKSongs mirror

`kksongs_mirror.py index|fetch|corpus`. **1,437 song addresses collected**; the fetch was
running when this was written (~40 min at 0.35 s/page, resumable, `data/reference/kksongs/`).
Plain HTTP - the pages are static Word-export HTML, so no scraping service and no credits.
Only the LYRICS section is taken; `/authors/purports/` is refused outright as BBT material.

Two parsing traps the tests exist to hold: the pages wrap long lines with **real newlines
inside the text**, so line structure lives in the tags (getting it backwards halved every
lyric line); and diacritics arrive as **combining** marks via numeric entities, so the parser
composes to NFC.

#### What to do next, in order

1. **Finish the KKSongs fetch**, run `corpus`, and **re-measure retrieval against thousands of
   lines rather than 59**. That is the number that says whether this design survives. Expect
   recall to fall - the Sikh Kirtan analogue reports Recall@1 of 21.5-31.9% against 141k lines
   - and precision to hold, since it comes from the margin rule.
2. **Extract flex's token scores** (`output_scores=True`), so two of three local systems carry
   confidence rather than one.
3. **Pull wisdomlib's Caitanya-bhagavata** (complete, four scripts) and GRETIL's Bhagavatam
   (14,067 verses, CC BY-NC-SA, but 584 of 844 long-metre verses duplicate a half-verse -
   regression-test the dedup on SB 3.9.10, which is one of our own citations).
4. **Forced alignment** - still the structural gap. flex emits NO timestamps, so a transcript
   assembled across three systems has timing for a minority of its words, and read-along
   alignment IS the product.
5. **A second verified lecture.** Everything still rests on one.

### 10.32 The "Sanskrit" column was two languages (2026-09-23)

**Write-up: `research/docs/transcription/sanskrit-and-bengali-2026-09-23.md`.** This corrects
claims in 10.27-10.31 and in the bake-off page, which now carries a banner.

The scorer's Indic track counts **any word the reference wrote with diacritics**, and Bengali
transliteration carries as many as Sanskrit. So every "Sanskrit" figure in this project has
been **Sanskrit AND Bengali**. Classifier now in `scripts.transcript_accuracy.indic_language`,
checked against thirty cues read by hand: **thirty right, none wrong**.

**676 Indic words = 486 Sanskrit + 190 Bengali.**

| system | as reported | Sanskrit | Bengali |
|---|---:|---:|---:|
| Whisper medium | 67.6% | 61.1% | 84.2% |
| Deepgram | 90.4% | 86.6% | **100.0%** |
| flex `bn mixed` | 45.7% | 44.2% | **49.5%** |
| Sarvam | 51.5% | 46.1% | 65.3% |
| ElevenLabs + keyterms | 54.6% | **42.6%** | 85.3% |
| all three fused | 44.7% | **36.8%** | 64.7% |

**Three corrections.** ElevenLabs is **second-best at Sanskrit**, not poor - its blend hid
42.6% Sanskrit against 85.3% Bengali. Deepgram gets **100.0%** of Bengali wrong, not 90%. And
flex `bn mixed`'s apparent Sanskrit lead is really that it is **the only system under 50% on
Bengali**, which dragged its blend down.

**Bengali is the weakest link and was invisible**: 190 words, the longest blackouts, one
system that manages 50%, and no licensed corpus but KKSongs.

#### A Sanskrit-specific recogniser, tested

`data/models/sushrota-onnx/` - Su-srota, IndicConformer-CTC fine-tuned for **chanted** Sanskrit,
int8 ONNX, Apache-2.0, ~30x real time on CPU, runs in `.venv-indic` (onnxruntime already there).
On verse cues, languages separated:

| | Sanskrit (n=16) | Bengali (n=14) |
|---|---:|---:|
| **Su-srota** | **35.7% CER** | 61.6% |
| ElevenLabs + keyterms | 37.0% | 82.3% |
| flex `bn mixed` | 37.9% | **45.7%** |
| Whisper medium | 57.6% | 65.8% |

**It wins on Sanskrit.** The margin is modest, not the 4x the literature suggests; a window
sweep showed that is the cassette audio, not our segmentation (even an oracle window per cue
only reaches 38.1%).

**WARNING - this was nearly missed by the same error.** My first run filtered "pure Sanskrit"
by diacritic density, fed **fourteen Bengali songs to a Sanskrit-only model**, and reported
47.8% CER and a loss. The steward disbelieved it and was right.

#### KKSongs corpus complete, and retrieval at real scale

**1,437 of 1,437 songs mirrored -> 25,687 distinct lyric lines** in
`data/reference/kksongs/`. Rerun with `kksongs_mirror.py index|fetch|corpus`.

Retrieval measured against it, and **the first two answers were both wrong because of my own
indexing**:

| index | coverage of the reference's Bengali |
|---|---:|
| 25,687 single lines | 27% |
| 84,075 windows of 1-3 lines | 13% |
| **windows + passage-identity margin + length check** | **67%** |

**The bug:** the margin compared the winner against the literal second-ranked item, which with
overlapping windows is **the same passage at a different length** - both score 1.000 by
containment, so the margin read 0.000 and abstention refused everything. The ranking was
always perfect; the confidence measure was not.

**The fix, not yet in `verse_match.py`** (it lives in a scratch script -
`scratchpad/retrieval_at_scale.py`): compute the margin against the best candidate from a
**different song**, and require a candidate to be at least 55% the query's length, because
containment lets a 3-word window trivially score 1.0 against a 10-word query.

Remaining misses are honest: Caitanya-caritamrta lines are correctly absent from a songbook,
and one is split across a line boundary the windows did not span.

**Stop citing the Sikh Kirtan Recall@1 figure.** It was a placeholder analogue while we had no
real number - live tracking with no abstention, not comparable. We now have our own: 67% on
84,075 windows. The caution that remains is **sample size** - 15 Bengali cues from one lecture.

#### Next

1. **Move the margin fix into `verse_match.py`** with passage identity as a first-class
   concept and tests that hold it. It is the highest-value pending change.
2. Re-split the earlier verse-retrieval measurements by language.
3. Route by language: English -> local trio confidence-gated; Sanskrit -> fused or
   ElevenLabs+keyterms, Su-srota on verse spans; **Bengali -> flex `bn mixed`, nothing else**.

### 10.33 Every word now has a time (2026-09-23)

**Write-up: `research/docs/transcription/forced-alignment-2026-09-23.md`.**

Read-along playback is the product and it needs a time per word. **Two of the nine systems
emit none at all**: flex returns 6,175 words in one string, and Sarvam returns 263 rows with
every timestamp null and each "word" a whole utterance. Forced alignment supplies what they do
not - the transcript is treated as known and only the timing is searched for, so the model never
has to be right about what was said. That is why it works on cassette audio and on Sanskrit.

**All 512 verified cues aligned: 6,365 words, 34 minutes on CPU, no failures.**
Output `data/reference/analysis/word-timings-mmsfa.json`. Model is torchaudio's MMS_FA,
wav2vec2 over 1,100+ languages sharing one 29-symbol romanised alphabet - which is why one model
serves English, Sanskrit and Bengali. **Licence CC-BY-NC 4.0** (the weights, not the corpora).

| median onset difference | English | Sanskrit | Bengali |
|---|---:|---:|---:|
| vs ElevenLabs | **0.03s** (n=4,985) | **0.02s** (n=77) | 0.05s (n=10) |
| vs Whisper | 0.07s | 0.06s | 0.70s (n=5) |
| vs Deepgram | 0.08s | 0.09s (n=6) | - |
| **the control: those three against EACH OTHER** | **0.06s** | | |

**The control is the point.** Three commercial systems agree with one another to a median 0.06s.
The aligner sits inside that spread and beats it against ElevenLabs. **These are agreement
figures, not accuracy** - the ~100 hand-marked onsets remain the honest next step, and nothing
here establishes correctness to a tolerance.

#### Four silent traps, all now handled

1. **`-` is CTC's blank.** A hyphen in `angghri-mulam` mapped naively is a forbidden target.
2. **The apostrophe is two things.** Kept inside a word (contraction), stripped at an edge
   (avagraha, possessive - written, not spoken).
3. **Not everything written was spoken.** 43 of 512 cues open with a speaker label; with it left
   in, cue 41 scored 0.017. Melbourne has no bracketed inserts but **the next lecture has 28,
   carrying 60 phantom words**. Forced alignment cannot decline a word.
4. **`get_model()` output is ALREADY log-probabilities** - log-softmaxed over 28 symbols with the
   star appended at probability 1, so `exp()` sums to **2, not 1**. Applying log_softmax again
   subtracts log 2 uniformly: **timings untouched, every confidence halved.** Found by a research
   sweep that read the installed library instead of the docs.

#### The measurement was wrong first, in the familiar way

Bengali first read 0.32s against ElevenLabs and 3.47s against Whisper. Both artifacts: `ei` and
`nama` are two letters and recur through a song, so the sequence matcher paired ours with an
occurrence **25 seconds away**. The aligner had placed them inside their own cues, correctly.
Requiring a pair to fall in the same cue took Bengali to **0.05s**; English barely moved, which
is how one tells the filter removes mistakes and not inconvenient data.

**Known limit:** the disagreement tail sits at cue edges - 20% of edge words over 1s out, falling
monotonically to 6% four or more words inside. The aligner cannot place a word outside its window.

#### flex's timestamps are discarded, not missing

`transcribe_long` cuts audio at pauses into <=30s pieces, decodes each, then ends with
`" ".join(out)` - knowing which piece produced which words and dropping it. `scripts/flex_timed.py`
keeps it, reusing flex's own `split_on_silence` and decode so the text matches what was scored.
A 30-second piece with known words aligns in under a second and **no chunk boundary is guessed** -
which matters because one-pass alignment of the whole blob needs a ~12 GB backtrack matrix and
raises `bad allocation`.

**Trial run (5 minutes): 12 segments, 470 words timed**, decode 280s + align 111s, every invariant
holding. A full lecture is ~40 min decode + ~25 min align. `problems()` now checks those
invariants on every run of both pipelines, on the finished result rather than inside any one
path - a word placed before its predecessor or past the end of the recording is a page that
highlights the wrong line and reports nothing.

#### Still open

1. **~100 hand-marked onsets**, turning agreement into accuracy.
2. **A star token cannot be expressed** - `romanise('*')` returns nothing by design. The cue-less
   path needs it against a recogniser's omissions.
3. **Word-onset convention unrecorded** - MMS_FA has no word-separator token, so the silence
   between words belongs to neither. Published figures swing several fold on this choice.
4. **Alignment confidence is not transcription confidence.** Where flex misheard, the span will
   look monotonic and well-scored while pointing at the wrong audio.

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
