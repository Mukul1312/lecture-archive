# Odia Design — Measured Findings and Corrections

**Date:** 2026-08-28 (later session) · **Corrects:** [odia-dual-output-system-design-2026-08-28.md](odia-dual-output-system-design-2026-08-28.md)

Two multi-agent research passes (37 agents) plus direct measurement on the actual machine.
**Three claims in the design doc are superseded.** They are marked here, not deleted.

> **Evidence currency:** Machine measurements and provider/source-host observations are dated
> 2026-08-28. Provider capabilities and prices can change; recheck their official sources before
> implementation or spending. The companion design's §7 is the durable source index. Raw retrieved
> pages are retained only in the repository's ignored local research cache.

---

## 1. Infrastructure: laptop, not AWS. Measured, not argued.

| Question | Measured answer |
|---|---|
| Triage speed, streaming from URL | **282–868× realtime** (real 72-min Odia lecture + 3 local files) |
| Triage peak RAM, **streaming** | **42–43 MB, FLAT** at 45.8 / 74.6 / 89.2 min — O(1) in file length |
| Triage peak RAM, **whole-file (librosa)** | **1,418 / 2,194 / 3,016 MB** — O(n). `analyze_source.py` hits ~4.1 GB (loads native 48 kHz *stereo* before downmix) |
| Disk needed | **0 bytes.** ffmpeg reads HTTPS natively; nothing is ever a file |
| Download from source host | **5.64 MB/s median** (13 samples). One connection saturates the origin; 8 connections buy **+8%** |
| CPU under sustained load | 6 workers → package at 94.9% of nominal, ~23% slower than idle. **Flat plateau, no runaway, no damage** |
| Machine | Ryzen 5 5625U 6C/12T, 15.3 GB RAM (**2.27 GB free — Chrome holds 8.65 GB**), 75.5 GB disk free (drifts ~9 GiB/hr) |

**Verdict: use the laptop.** Every constraint is either zero or a ~20-line code fix. AWS is not
rejected on cost (~$0.30 of Spot) but on **coupling**: it reverses the approved local-first
decision (Q2) for a one-shot 3-hour job, and D1 already says the AWS driver is *learning* — a
months-long single-maintainer seva pipeline on someone else's donated server is the wrong vehicle.

**Azure ingestion confirmed**, Microsoft's words: *"When you store source audio files outside of
Azure, the service can access them through a public URI."* The host was probed independently:
plain Apache, single IP, no CDN, no bot protection, anonymous, `206` on Range GETs, 8+ files.

**RAM is an architecture choice, not a hardware limit.** Three streaming workers = 129 MB, which
fits the *currently available* 2.27 GB seventeen times over. Chrome outweighs the whole pipeline
~200×.

### Two real bugs found in this repo

- **`scripts/enhance_diagnose.py:206`** — `np.percentile(rdb, 60)` sits *inside* `blind_rt60`'s
  while loop → O(n^1.79), 176 s/lecture, **~105 h corpus-wide**. Hoisting it out measured
  **17.3× faster with byte-identical output**. (Triage doesn't need RT60 — skip the script.)
- **`scripts/fetch_idt.py:43`** — `MP3_HREF` expects `href="..."` (quoted). This branch serves
  **unquoted** hrefs nested two levels deeper. **It cannot enumerate the Odia corpus as written.**

### Crawl traps, verified against the live site

1. Each file row emits **three** hrefs. One is a player link `index.php?q=m&m=...` returning a
   **196-byte M3U playlist**, not audio — exactly the "invokes interactive scripts" case Azure
   rejects. It is **one third of all mp3 hrefs.** Take only the quoted `href="/....mp3"`.
2. **Do not re-encode hrefs.** The site already percent-encodes; `%20` → `%2520` → 404.
3. Live crawl found **1,362** files across 123 folders vs the bid doc's **1,357** — reconcile.
4. Corpus is nested by series (`Bhagavad_Gita/Chapter-01`, `Srimad_Bhagavatam`, `Seminars`, …) —
   **natural strata**. Sampled files are dated 2021, so this is not an old cassette archive.
5. **Use 1–2 connections.** Parallelism buys ~28 minutes across the whole corpus against a single
   unfronted, donation-funded Apache box. `fetch_idt.py` already says *"be a good guest."*

---

## 2. SUPERSEDED — the second engine is **ElevenLabs Scribe v2**, not Sarvam

Supersedes the design doc's §4.1 funnel and the Scenario D row.

| Engine | Odia | $/audio-hr | URL ingest | Word timestamps | Per-word confidence | Independence from Azure |
|---|---|---:|---|---|---|---|
| **ElevenLabs Scribe v2** ✅ | `ori` | **0.22** | ✅ `source_url` | ✅ | ✅ **`logprob`, required field** | **HIGH** (inferred seq2seq) |
| Azure MAI-Transcribe-1.5 | `or` | 0.36 | ✅ `audioUrl` | ✅ | ❌ phrase-level | MED-HIGH (preview, sync-only) |
| Sarvam saaras v3/v4 | `od-IN` | 0.314 | ❌ **upload-only** | ❌ **chunk only** | ❌ | MED-HIGH (moot) |
| Azure Fast Transcription | `or-IN` | 0.36 | ✅ | ✅ | ❌ | **NONE — same models. Disqualified** |

**Sarvam is demoted on granularity, not quality.** It is the best-measured Odia engine here
(14.0 OIWER on Voice of India, beating IndicConformer's 14.4 — and that benchmark seeded its Odia
references with IndicConformer output, a handicap that makes 14.0 *more* credible). But chunk-level
flags cannot localise. At per-token disagreement *d* and *w* tokens per chunk, the flagged fraction
is `1 − (1−d)^w`:

| | Token-level | Chunk-level (w=10) |
|---|---:|---:|
| d = 0.05 | 5% | **40%** |
| d = 0.10 | 10% | **65%** |

A chunk flag also cannot say *which* word is suspect, so the reviewer re-listens to a whole segment
instead of glancing at a phrase. **That is a 2–6× multiplier on volunteer attention** — the only
genuinely scarce resource in this project.

Switching also **removes code**: one POST with `source_url` replaces `initiate → upload-files →
start → status → download-files` across ~21 jobs (Sarvam caps at **20 files/job, 2 h/file**).

**Keep Sarvam provisionally for `mode="translate"` only** — a third independent opinion on
*meaning*, diffed against Claude's translation-from-transcript. 20 h = ₹600. Not a production path.

**No Odia at all — stop considering:** every Whisper variant (no `or` token, unfixable), Deepgram,
AssemblyAI, Speechmatics, Rev, IBM Watson, Gladia. GPT-4o Transcribe emits Odia at 42–72% WER.

**Open gap: AWS Transcribe was never profiled** — it scored **17.9 on VoI Odia, better than
Scribe's 20.7.** Worth 20 minutes of doc-reading before the pilot locks.

---

## 3. SUPERSEDED — run the second engine on 100%, not the worst 30%

The flaw in the original funnel: **the worst 30% has to be selected by something**, and the only
selector available was Azure's own per-word confidence — a single-engine signal the design
explicitly distrusts. It used the untrusted thing to decide where to apply the trusted thing.

Scribe is cheap enough to remove the choice: **₹41,011 for all 1,952 h vs ₹12,304 for 30%** —
₹21 per extra audio-hour of real two-engine coverage. No other candidate is arguable at full scale
(Sarvam ₹58,560, MAI ₹67,110).

| Design | ASR | + Claude translate | Total |
|---|---:|---:|---:|
| Azure + Scribe worst 30% | ₹45,859 | ₹16,000 | **₹61,859** |
| Azure + Scribe **100%** | ₹74,566 | ₹16,000 | **₹90,566 (~$950)** |

Decide after the pilot measures the actual disagreement rate.

---

## 4. SUPERSEDED — the 1.59% shared-wrong floor was over-optimistic

The design doc's *"Ceiling, stated honestly: 1.59%"* does not transfer. That figure is **8 engines
on English** medical ASR, where training data is abundant. With **2 engines on Odia** — whose
entire public supervised corpus is a few overlapping datasets (IndicVoices, Shrutilipi, Kathbath,
Vaani, FLEURS, Common Voice) — expect **materially worse**. The 93.7%-recall-at-28.6%-review figure
inherits the same caveat. **Both must be hand-measured on this audio.**

**New rule — glossary asymmetry.** Feed Sanskrit/Gaudiya-Vaishnava keyterms to **exactly one
engine, never both.** Giving both the same glossary correlates their errors on precisely the
vocabulary the archive most depends on, raising the shared-wrong floor where it hurts most.
(Convenient: phrase lists work on Azure *Fast* but "aren't available with batch transcription".)

---

## 5. The two cheap tests that gate everything — run these FIRST, alone

1. **Can ElevenLabs' fetcher read `audio.iskcondesiretree.com`?** One file, **~$0.32**. The host
   returns `Vary: User-Agent`, and archive hosts routinely block datacenter ranges. This single
   unknown decides whether zero-laptop-bytes survives.
   *Verified contingency:* Google Storage Transfer Service was empirically tested against this host
   (`206`, `Accept-Ranges: bytes`, agentless transfers free) — mirror to GCS, serve public URLs.
2. **Does Azure's `words[]` carry `confidence` for `or-IN`?** The docs show confidence only at the
   nBest level, and half the design assumes per-word. Also unsettled: **`or-IN` in *batch* mode
   specifically** — the locale table ticks it under *fast transcription*. One job settles both.

**The pilot's real deliverable is a normalization harness.** Azure emits lexical/ITN/maskedITN/
display forms; Scribe keeps English words in **Latin script** where Azure may transliterate.
Diffing raw output produces a false-disagreement rate that makes every downstream number wrong.
Also set `tag_audio_events: false` — it defaults **true**, and `(laughter)` tokens are pure
false disagreement.

**What the pilot must not conclude:** that any published WER predicts this corpus. Every available
Odia number comes from telephonic conversation, degraded mobile field recordings, or read
Wikipedia — none is 86-minute single-speaker 64 kbps lecture monologue dense with Sanskrit. The
pilot's job is to produce two measured numbers — ***d*** (disagreement rate) and the
**shared-wrong floor** — and those two decide 30% vs 100% coverage.

---

## 6. Where this leaves the plan

Nothing has been built. Nothing has been switched. One lecture remains the only thing transcribed,
so switching cost is still near zero.

**Next action, in order:** (1) the two gate tests above, ~$1 total; (2) AWS Transcribe doc-read;
(3) fix the `fetch_idt.py` regex and build a preflighted URL manifest into SQLite; (4) streaming
triage overnight at 3 workers, BelowNormal, on AC; (5) the ₹1,433 pilot.

## 7. Evidence trail

- Provider, benchmark and pricing sources are indexed in
  [the companion design's §7](odia-dual-output-system-design-2026-08-28.md#7-sources).
- Infrastructure figures and crawl behavior are local observations from 2026-08-28, not portable
  performance guarantees.
- The 61 raw provider/API captures from that session are local research cache, not project source;
  they are intentionally excluded from Git because some pages contain expiring signed asset URLs
  or public browser-client keys.
