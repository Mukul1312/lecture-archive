# 01 — Resource Inventory

**Date:** 2026-08-24 · **Status:** confirmed by the user; governs the category analyses.

What follows is what this project *actually consumes*, derived from the repository rather
than from recollection. Every row carries its evidence. This inventory is the agreed spine of
the whole evaluation: the twelve categories below are the units of analysis.

---

## The twelve categories

### 1. Local CPU compute

Windows 11 machine, **no NVIDIA GPU**, running DeepFilterNet3 rendering, all scoring and
metrics, gallery generation, and every non-GPU pipeline stage.

**Measured characteristics:**

- `torch 2.0.1+cpu`, `torch_threads: 6`, `cuda_available: false`
- DeepFilterNet end-to-end real-time factor **0.280761**
- Model-inference-only real-time factor **0.09642**
- Benchmark basis: 57.46 s of audio processed in 16.13 s wall time

**Evidence:** enhancement job manifests (`data/enhance/jobs/*/job.json`, `benchmark` block);
`cloud/LIGHTNING_SETUP.md` states plainly that the laptop has no NVIDIA GPU, so training
(~12–20 GB VRAM) cannot run locally.

**Why it matters:** this is the *active* workload. The current production pipeline is
CPU-bound, not GPU-bound — a fact that inverts the usual assumptions about what cloud
infrastructure this project needs.

---

### 2. Ephemeral cloud GPU (interactive)

**Four separate providers**, each reached for opportunistically:

| Provider | Hardware | Used for |
|---|---|---|
| RunPod | RTX 4090, RTX A5000 | LoRA training, inference sweeps, denoise passes |
| Lightning AI Studio | T4 / L4 (free monthly hours) | Data prep, VSCode-over-SSH development |
| Google Colab | T4 | The verified data-prep notebook |
| Kaggle | T4 | The original zero-shot voice baseline |

**Evidence:** `cloud/RUNPOD_SETUP.md`, `cloud/pod_train.sh`, `cloud/pod_infer.sh`,
`cloud/LIGHTNING_SETUP.md`, `colab/README.md`, `cloud/HANDOFF.md` (which records that the
VoxCPM2 zero-shot clone baseline was run on a Kaggle T4).

**Access pattern:** SSH from desktop VSCode into the pod, with per-pod host and port. The
`.claude/settings.json` permission list still contains hardcoded SSH invocations against
long-expired pod addresses — a fossil record of how ad-hoc this was.

---

### 3. Batch GPU jobs

Distinct from category 2 because the *pattern* differs: long-running, unattended, fan-out
work rather than interactive sessions.

- VoxCPM2 LoRA training runs
- Best-of-N seed sweeps: **24 seeds x 20 chunks** per diary entry
- ASR A/B comparisons across engines
- Denoise passes across cleaning tiers

**A documented parallelism finding:** one generation process left the A5000 at ~46%
utilisation (autoregressive batch-1 inference has idle bubbles). Running **one process per
cleaning tier** filled it to 100% — VRAM ~21/24 GB fits three — but yielded only ~**1.3x**
throughput, because the workload is compute-bound rather than idle-bound. More parallelism
past ~3 processes does not help.

**Evidence:** `research/docs/voice-cloning/project-findings.md` section 10.

---

### 4. Persistent network storage

The RunPod network volume **`voxcpm-vol`**, 40 GB, region EU-SE-1, ~**$2.80/month**, holding
the entire environment: VoxCPM2 (4.7 GB), LoRA checkpoints, the repository, **the virtualenv
itself**, and generated takes.

This existed to solve a specific, painful problem: community and stopped pods repeatedly
could not restart because the host was full, and the RunPod MCP integration could not attach a
network volume to a pod. The workaround was to deploy a fresh pod onto the volume via the web
console each time — instant, because nothing needed re-downloading.

**Evidence:** `research/docs/voice-cloning/project-findings.md` section 6.

**Why it matters:** this is a *stateful environment* pattern, not just a disk. It is the
closest thing the project has to infrastructure-as-a-persistent-thing, and it is the reason
pod churn was survivable.

---

### 5. Object and bulk data

**Corrected figure — the working tree is 53 GB, not the ~7 GB initially assumed.**

| Location | Size | Nature |
|---|---:|---|
| `.worktrees/` | **41 GB** | Enhancement job working sets (see below) |
| `data/` | 8.3 GB | Corpora, outputs, enhancement inputs |
| `.git/` | 2.2 GB | Repository history (media was committed historically) |
| `_work/` | 335 MB | Active transcript reconstruction — **gitignored** |
| Root media | 250 MB | Three source recordings, untracked |

Within `.worktrees/`, the per-job breakdown:

| Job | Working set | Source |
|---|---:|---|
| `rupanuga-prabhu-house-e6a0767a` | **19 GB** | 102 MB MP3 |
| `youtube/QgH4QRSnmKI` (Haladhara) | **12 GB** | 37.8 MB WebM |
| `spad-8dc17107` (Prabhupada Appearance Day) | **8.1 GB** | 110 MB MP3 |

Against those working sets, the actual deliverables are tiny: **205 MB FLAC + 66 MB MP3**.

**The structural fact this reveals:** a 102 MB source generates a ~19 GB working set —
roughly **190x amplification** — and every byte of it is *regenerable*. A huge disposable
intermediate tier sitting next to a small permanent deliverable is precisely the shape that
storage classes, lifecycle policies and interruption-tolerant compute exist to serve. This
drives both category 5 and category 12.

**Prospective:** the Odia corpus is a measured **1,952 audio-hours across 1,357 files** at
64 kbps CBR — see [05-odia-gpu-cost-model.md](05-odia-gpu-cost-model.md).

---

### 6. Model artifact registry

Roughly **twelve model families**, all pulled from HuggingFace at runtime, several
version-pinned, at least one **gated**, one as large as 4.7 GB.

| Purpose | Models |
|---|---|
| ASR | `openai/whisper-large-v2`, `-v3`; faster-whisper / CTranslate2; `ai4bharat/indic-conformer-600m-multilingual` |
| Language ID | `facebook/mms-lid-256` |
| Diarization | `pyannote/speaker-diarization-community-1`, `pyannote/speaker-diarization-3.1` (**gated**) |
| Speaker embedding | `speechbrain/spkrec-ecapa-voxceleb`, Resemblyzer d-vector |
| Forced alignment | `ctc-forced-aligner` (MMS-300m), `stable-ts` |
| Enhancement | `Rikorose/DeepFilterNet3`, `resemble-ai/resemble-enhance`, `iic/speech_zipenhancer_ans_multiloss_16k_base` |
| TTS | `OpenBMB/VoxCPM` / VoxCPM2 (**4.7 GB**) + LoRA adapters (**70 MB each**) |
| Segmentation / VAD | `inaSpeechSegmenter`, silero-vad, webrtcvad |

**Evidence:** scoped grep across `cloud/`, `scripts/`, `colab/`, `docs/`.

**The reproducibility problem this creates:** `cloud/pod_setup.sh` documents a **three-way
version deadlock** — pyannote 3.4 requires `huggingface_hub<1.0`, while the CTC aligner
requires `transformers>=4.48` which requires `hub>=1.0`. The resolution was to pin
`transformers==4.46.3` and `huggingface_hub==0.26.5`, **and patch the aligner's source with
`sed`** to rename a single incompatible kwarg. This works, and it is documented honestly, but
it is precisely the class of fragility that container images exist to eliminate.

---

### 7. Code and artifact transfer

**Git is used as the bulk transfer mechanism.** `cloud/LIGHTNING_SETUP.md` Step 0 instructs
pushing to GitHub first because the Studio clones from GitHub and must therefore be current,
and notes that the lecture audio already in git clones along with it.

**Corrected assessment:** `.git/` is now **2.2 GB**, so bootstrapping a pod pulls 2.2 GB
before a single model is downloaded. This weakens git-as-transfer considerably more than was
first credited.

Additional transfer paths: SSH into pods (key-based, per-pod ports); multi-gigabyte
HuggingFace downloads on every fresh environment; source media fetched from YouTube and
ISKCON Desire Tree.

---

### 8. Static web hosting

Three generated static sites plus a local server:

- `site/`, `site-casting/`, `site-odia-check/` — each an `index.html` plus an `audio/` tree
- `vercel.json` rewrites all paths into `/site/`
- `voice_lab/` galleries served locally via `python -m http.server`

These are **human-in-the-loop review instruments**, not marketing pages: blind A/B
comparisons, keyboard-driven flashcard review apps, WaveSurfer waveform trimmers, seed-swap
galleries.

**Cloudflare check (added 2026-08-24):** the user has prior Cloudflare experience, but from
*other projects*. A scoped search of this repository for `cloudflare`, `r2`, `wrangler`,
`workers.dev`, `pages.dev` and `tunnel` found **no Cloudflare usage here**. All apparent hits
were false positives — the statistical coefficient `R2` in `propose_segments.py` and
`score_calibrate.py`, and **SSH** tunnels in `cloud/asr_ab.py:223` and
`scripts/build_probe_gallery.py:7`. Vercel is the only hosting provider this project has
actually used. Cloudflare is nonetheless a serious candidate going forward — see
[07-cloudflare-and-the-provider-matrix.md](07-cloudflare-and-the-provider-matrix.md).

---

### 9. Access control

Currently: **static passcodes, unlisted URLs, `noindex`, and base64-encoded keys.**

The project's own architecture audit states these are not access control. That assessment is
adopted here rather than re-litigated.

**Evidence:** `docs/superpowers/specs/2026-08-22-heritage-production-ddd-hexagonal-design.md` section 2.

This matters more than it might elsewhere: the material is sacred, the DDD design
contemplates rights-holder sign-off, and review packages go to named external reviewers.

---

### 10. State and database

**There is no database.** State lives in:

- JSON / JSONL / TSV files
- `manifest.json` per enhancement run, `job.json` per job
- **Browser `localStorage`** for review decisions in the generated galleries
- Markdown documents

SQLite is *planned* in the approved DDD design but not implemented. The same design notes
that review decisions currently have no durable canonical review ledger, and that several
pipelines identify data by filename, numeric suffix, or array index — so rebuilding a clip
directory can silently attach old evidence to different bytes.

---

### 11. Secrets and identity

`.hf_token` (gitignored), an SSH keypair, manual acceptance of gated HuggingFace repos, a
Vercel project link, Notion credentials via MCP. All manual, all local, no rotation, no
central store.

Worth noting: `.gitignore` carries an explicit warning that secrets must never be committed
because the repository is public, so the constraint is already understood and handled by
exclusion.

---

### 12. Caching

A genuine content-addressed cache, and a well-built one. Chunk cache keys are bound to source
PCM, original mid channel, attenuation limit, model file hashes, tool versions, and chunk
policy — so an interrupted render resumes rather than restarting, and a changed input cannot
silently reuse stale output.

**Evidence:** `scripts/youtube_enhance/generic_d30.py` and
`docs/superpowers/plans/2026-08-23-rupanuga-generic-d30-delivery.md`.

**Important nuance:** this rigour exists only in the *new* `youtube_enhance` package. The
legacy scripts largely cache on file existence, which the architecture audit flags as
unsound.

---

## Absent entirely

Recording the gaps is as informative as recording the inventory:

- **No CI/CD.** No automated build, test, or deploy anywhere.
- **No observability.** Logs are files (`train.log`, `setup.log`), read by `tail` over SSH.
- **No job queue.** Orchestration is bash scripts and manual sequencing.
- **No container registry.** No Docker in the workflow at all.
- **No infrastructure-as-code.**
- **No backup or disaster recovery** for irreplaceable source material.

---

## Two structural findings

### Finding 1 — This is provider fragmentation, not a compute shortage

Four GPU providers, each with separate auth, bootstrap, and storage. The binding problem is
not insufficient compute but **environment reproducibility**: the `sed`-patched dependency
deadlock in `pod_setup.sh` is the clearest symptom.

The honest reading is that this is a **Docker problem before it is an AWS problem**.
Containerisation fixes it on any host. AWS offers a good home for containers (ECR plus
Batch), but the fix does not require AWS, and this folder should not claim otherwise.

### Finding 2 — This project is an unusually good AWS learning vehicle

Given the stated learning driver, the breadth of the inventory is itself an argument. The
twelve categories map onto S3 and its storage classes, EC2 and Spot, Batch, ECR, EFS, IAM,
Secrets Manager, CloudFront with signed URLs, Cognito, DynamoDB or RDS, Step Functions,
CloudWatch, and Glacier.

Most side projects touch three or four AWS services. This one legitimately touches a dozen,
with real data, real constraints, and a real deliverable. As a portfolio artefact that is
substantially more compelling than a CRUD application.

---

## A note on live state

The `.worktrees/` figures above were measured on 2026-08-24 while the user was actively
working in that worktree in a parallel session. During the analysis, the Rupanuga job's
`job.json`, `audition/`, `delivery/` and `model/` directories were removed, leaving only the
19 GB `work/` cache. The storage totals should therefore be treated as a **snapshot of an
actively changing tree**, and re-measured before any sizing decision is finalised.
