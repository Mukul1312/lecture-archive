# Workflow scripts

Multi-agent workflow scripts run in this repository, kept here so they survive the
session that ran them. A workflow's script is otherwise written only into the Claude
session directory, which is not backed up and is cleaned up eventually.

| script | what it did | run |
|---|---|---|
| `commercial-asr-free-credit-survey.js` | Deepgram in depth, independent accuracy evidence, and commercial peers with free allowances (AssemblyAI, Speechmatics, ElevenLabs, Soniox, Gladia, Google, Azure, Rev, OpenAI), then a verifier that checks prices, free credits and data terms at source. Notes in `data/research/commercial-asr-2026-09/` | `wf_659d3dd8-130`, 2026-09-22 |
| `indic-links-survey.js` | 34 links the steward found (IndicTrans2, IndicBERT, Sarvam, Param-1, Qwen3 and a Sanskrit fine-tune, Indic Parler-TTS, GitaWhisper and more), read at source by five themed readers and judged against the transcription, Odia seva and narrator-voice projects, then verified. Notes in `data/research/indic-links-2026-09/` | `wf_b39c2eed-460`, 2026-09-22 |
| `melbourne-eight-point-measurements.js` | Four measurements on the verified Melbourne reference — correction workload, error-signal calibration, read-along timing drift, Sanskrit lexicon headroom — then one adversarial verifier that recomputes every headline number | `wf_1d5e654d-7eb`, 2026-09-22 |
| `open-asr-model-survey.js` | Five research sweeps on open ASR models beyond Whisper (English, Indic and Sanskrit, alignment and CPU runtimes, 2026 releases, evidence on archival and accented speech plus rented-GPU cost), then a verifier that checks licence, timestamps, CPU feasibility and accuracy claims at primary sources. Sweeps write as they go to `data/research/asr-model-survey-2026-09/` | `wf_4e095424-673`, 2026-09-22 |
| `ssggsm-reference-and-catalogue-prep.js` | Found the corpus's only verbatim reference, built the RTF glossary, prepared the catalogue | `wf_163b7baa-099`, 2026-09-18 |
| `ssggsm-transcript-corpus-check.js` | Surveyed the ~800 draft transcripts and the duplicate structure of the tape corpus | `wf_b4c3304d-910`, 2026-09-18 |

## Resuming a run

A run can be resumed while its session still exists. Completed agents return their
cached results instantly; only edited or new calls run again:

```
Workflow({scriptPath: ".agents/workflows/<script>.js", resumeFromRunId: "<run id>"})
```

If the session is gone, run the script fresh — it is self-contained. Re-running costs
the full token spend again, so check the outputs it wrote first.

## Where a run's output lives

- **Structured returns:** `journal.jsonl` in the session's
  `subagents/workflows/<run id>/` directory. This records what each agent actually
  returned. Read it before concluding a run produced nothing.
- **Per-agent transcripts:** `agent-<id>.jsonl` beside it.
- **Files the agents wrote:** whatever the script told them to write. The Melbourne run
  wrote to `data/reference/analysis/` (gitignored, like the rest of `data/`).

## House rules these scripts follow

- Agents measure from files already on disk; they never run Whisper, ffmpeg or anything
  CPU-heavy, and never touch the network.
- Agents never modify an existing file, never commit, and write only into a new
  directory of their own.
- `PYTHONIOENCODING=utf-8` before every Python call: Windows cp1252 crashes on the IAST
  text in the reference.
- The verified review (`data/reference/MELBOURNE_vs_90-85_aligned-review.json`) is
  read-only to every agent. It is the steward's own work and cannot be regenerated.
