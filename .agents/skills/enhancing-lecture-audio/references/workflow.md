# Repository workflow

Use this reference only after the user explicitly invokes `$enhancing-lecture-audio`.

## 1. Locate or create the job

Work from the canonical repository root. Search `data/enhance/jobs/*/job.json`, parse candidates, and compare their recorded source SHA-256 with the supplied file's current SHA-256. Resume one matching job; if more than one valid match exists, show them and ask which to resume.

For a new source, use a short ID such as `<safe-stem>-<first-eight-lowercase-sha256>` and create:

```text
data/enhance/jobs/<job-id>/
  job.json
  model/DeepFilterNet3/config.ini
  model/DeepFilterNet3/checkpoints/model_120.ckpt.best
  audition/
  work/
  delivery/
```

Keep the source at its original path. Record its physical absolute path, SHA-256, byte size, codec/container, duration, sample rate, channels, and bitrate. Never use a protected legacy workspace outside `data/enhance/jobs/` as a new job root.

## 2. Preflight and estimate

Before expensive work:

- resolve FFmpeg, FFprobe, Python, `deepFilter.exe`, and the job-bound model files;
- record tool versions and model hashes;
- enumerate the deepest planned `work/dfn-scratch`, `work/c/<64-key>`, `.d-<32-hex>`, output, sidecar, and atomic `.new` names; require every fully composed path to be shorter than 260 characters;
- require free bytes on the job volume of at least `max(10 GiB, ceil(25 GiB * decoded_frames / 131,864,451))`;
- decode and enhance one short excerpt;
- report the measured inference and end-to-end real-time factors and a duration-scaled ETA range.

Do not promise the historical 45-70 minute target as a constant. The estimate must come from this source, hardware, and model run.

## 3. Build the blind Original/D30 audition

Select five 8-15 second source-coordinate windows. Cover beginning, middle, ending, clean/noisy speech, pause onset or quiet consonants, and crowd/music/chanting when present. Record every start and duration in `job.json` before processing.

For each window:

1. Decode from the original source to 48 kHz float PCM without timeline-changing filters.
2. Form the mid channel; retain the original side if the source is stereo.
3. Produce Original and D30 independently from that same original mid. D30 is one DeepFilterNet3 pass with `--atten-lim 30`.
4. Match active RMS downward: lower the louder candidate, never boost or limit either candidate.
5. Encode both audition files with identical settings.
6. Randomize A/B separately for every clip and save the mapping only in `audition/_private/key.json`.
7. Publish pairs in `audition/fair/clip-01` through `clip-05` plus a short listening guide.

Ask for five choices such as `1B, 2A, 3A, 4B, 5A`. Map them through the private key. Record raw votes, mapped candidates, timestamp, and result in `job.json`.

- All five D30: advance to `full_render_approved`.
- Any Original, tie, or `same`: stop and discuss the affected timestamps. Never convert a mixed result into approval by majority vote.

## 4. Approved job contract

Before the full render, the runner-relevant state must have this shape (retain additional measured fields):

```json
{
  "schema_version": 1,
  "job_id": "lecture-example-1a2b3c4d",
  "stage": "full_render_approved",
  "source": {
    "path": "C:/absolute/path/Lecture Example.mp3",
    "sha256": "UPPERCASE_64_CHARACTER_SHA256"
  },
  "treatment": {
    "mode": "dfn30_parallel",
    "model": "DeepFilterNet3",
    "attenuation_limit_db": 30,
    "preserve_complete_timeline": true
  },
  "audition": {
    "choice": {
      "selected_candidate": "dfn30_parallel",
      "result": "unanimous"
    }
  },
  "delivery": {
    "status": "approved_pending_render",
    "formats": ["flac_24bit", "mp3_192kbps"]
  }
}
```

The source hash must still match, and the model files must exist under the job root.

## 5. Full render

Run:

```powershell
.venv\Scripts\python.exe -m scripts.youtube_enhance.generic_d30 `
  --job "data\enhance\jobs\<job-id>\job.json"
```

The runner decodes to 48 kHz stereo, enhances the original mid once, restores the original side, reuses hash-validated chunks, preserves exact frames, normalizes near -16 LUFS with a -1.5 dBTP ceiling, and writes FLAC, MP3, QA, completion, and checklist artifacts. Delivery filenames are derived safely from the approved source name; do not hardcode another lecture's name.

On failure, preserve `work/c`, provenance sidecars, logs, source, model, audition, and job record. Diagnose the exact failed boundary and retry the same command only after the cause is corrected. The cache validators decide which chunks can be reused.

Never relocate a running job outside canonical `data/enhance/jobs`. If its root itself prevents a valid path budget, stop and propose a shorter job ID. Migration requires explicit user approval, an atomic new job record, byte-for-byte source/model binding, validation of every copied or hard-linked cache object, and retention of the old job as recovery evidence.

## 6. Verify and request listening

Require:

- runner exit code 0;
- job stage and delivery status `awaiting_final_listening`;
- FLAC and MP3 full decode succeeds;
- exact authoritative decoded frame count is preserved;
- both files are 48 kHz stereo;
- FLAC is 24-bit and MP3 is approximately 192 kbps;
- loudness is -16.5 through -15.5 LUFS and true peak is no higher than -1.5 dBTP;
- hashes, cache context, model provenance, boundaries, and artifact paths agree.

Give the MP3 first for convenient listening and the FLAC as the lossless master. Final listening checks naturalness, word integrity, transitions, quiet speech, overlaps, events, beginning, and ending.

## 7. Record final approval

Only after the user explicitly says `approved`, create `delivery/listening-approval.json`. Bind it to the job ID, reviewer, timestamp, current completion hash, QA-report hash, and current FLAC/MP3 hashes. Create it atomically and refuse to overwrite an existing receipt. Do not rewrite the audio or mutate the renderer's immutable `completion.json`. Future sessions treat a valid approval receipt whose hashes still match as the final human gate.

If any bound hash has changed, the receipt is invalid and the job returns to investigation; never regenerate approval silently.
