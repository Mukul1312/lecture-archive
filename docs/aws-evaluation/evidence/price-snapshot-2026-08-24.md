# Evidence — Price and Fact Snapshot, 2026-08-24

Every external figure used in this folder, with its source. Retrieved **2026-08-24**.
Prices drift; re-verify before relying on any of this.

**Standing caveat:** all AWS prices are **us-east-1, Linux, list price**. The likely real
region is ap-south-1 (Mumbai), which differs.

---

## 1. AWS EC2 — CPU instances

Source: `instances.vantage.sh` (Vantage EC2 instance comparison).

| Instance | vCPU | RAM | On-Demand | Spot | 1-Yr Reserved | 3-Yr Reserved |
|---|---:|---:|---:|---:|---:|---:|
| `c7g.xlarge` (Graviton) | 4 | 8 GiB | $0.145 | **$0.065** | $0.096 | — |
| `c7i.xlarge` | 4 | 8 GiB | $0.179 | **$0.073** | $0.118 | — |
| `c7g.2xlarge` (Graviton) | 8 | 16 GiB | $0.290 | $0.127 | $0.191 | $0.127 |
| `c7i.2xlarge` | 8 | 16 GiB | $0.357 | $0.168 | $0.236 | $0.157 |
| `c7i.4xlarge` | 16 | 32 GiB | $0.714 | $0.316 | $0.472 | $0.314 |

---

## 2. AWS EC2 — GPU instances

Source: `instances.vantage.sh`.

| Instance | GPU | VRAM | vCPU | On-Demand | Spot | Spot discount |
|---|---|---:|---:|---:|---:|---:|
| `g4dn.xlarge` | T4 | 16 GB | 4 | $0.526 | $0.356 | 32% |
| `g5.xlarge` | A10G | 24 GB | 4 | $1.006 | $0.675 | 33% |
| `g6.xlarge` | L4 | 24 GB | 4 | $0.805 | **$0.791** | **1.7%** |

**Note:** the `g6` Spot discount of 1.7% is anomalous and materially affects the analysis. It
indicates tight L4 capacity. Worth re-checking, and worth checking per-region.

---

## 3. AWS GPU quotas

Source: `docs.aws.amazon.com` — *Amazon EC2 instance type quotas* and *Spot Instance quotas*.

| Quota | Default | Adjustable |
|---|---:|---|
| Running On-Demand G and VT instances | **0** | Yes |
| All G and VT Spot Instance Requests | **0** | Yes |

A new account cannot launch any G-family GPU instance without an approved Service Quotas
increase. Corroborating community reports (AWS re:Post, Stack Overflow, Reddit r/aws) describe
multi-day waits and occasional refusals on accounts without billing history.

---

## 4. RunPod

Source: `docs.runpod.io/pods/choose-a-pod` (last modified **2026-08-18**);
`runpod.io/pricing` (updated 2026-07-27); `docs.runpod.io/references/gpu-types`.

### Tier structure

| | Secure Cloud | Community Cloud |
|---|---|---|
| Infrastructure | T3/T4 data centres | Peer-to-peer providers |
| Reliability | High redundancy | Variable |
| Best for | Production, sensitive data | Cost-sensitive workloads |
| Pricing | Standard | Competitive |

### Key statement, verbatim

> "Runpod is no longer accepting new hosts for Community Cloud. Existing Community Cloud
> resources remain available."

### GPU catalogue (subset)

A30 24 GB, A40 48 GB, L4 24 GB, L40 48 GB, L40S 48 GB, RTX A4000 16 GB, RTX A5000 24 GB.
Grouped as `AMPERE_16` (A4000, A4500, RTX 4000, RTX 2000), `AMPERE_24` (L4, A5000, 3090),
`AMPERE_48` (A6000, A40), `ADA_48_PRO` (L40, L40S, 6000 Ada).

### Storage

- Storage from **$0.05/GB/month** (runpod.io/pricing).
- Network volumes reported at **$0.07/GB/month** under 1 TB with **no data transfer fees**
  (Northflank comparison article — third-party, not RunPod primary).

### Project's own historical figure

RunPod A5000 at **~$0.27/hour** plus **~$2.80/month** for a 40 GB network volume in EU-SE-1
(`docs/project-findings.md` section 6). Almost certainly Community Cloud pricing.

---

## 5. JarvisLabs

Source: `jarvislabs.ai/pricing`; `jarvislabs.ai/compare/runpod`.

| GPU | VRAM | vCPU | On-Demand |
|---|---:|---:|---:|
| L4 | 24 GB | 32 | **$0.44** |
| A30 | 24 GB | 16 | $0.41 |
| A100 40 GB | 40 GB | 16 | $0.89 |
| A100 80 GB | 80 GB | 16 | $1.49 |
| RTX Pro 6000 Blackwell | 96 GB | 28 | $1.89 |
| H100 SXM | 80 GB | 16 | $2.69 |
| H200 SXM | 141 GB | 28 | $3.99 |

- Billing: **per-minute**.
- Spot: **up to 56% off**.
- Commitment discounts: 1 month 2%, 3 months 3%, 6 months 5%, 1 year 9%.
- Positioning: dedicated datacentre hardware, **99.9% uptime**, no community cloud.

---

## 6. E2E Networks

Source: `e2enetworks.com/pricing` and E2E cloud-terms pages.

| GPU | VRAM | vCPU | RAM | Hourly On-Demand |
|---|---:|---:|---:|---:|
| L4 | 24 GB | 25 | 110 GB | **$0.57** |
| L40S | 48 GB | 60 | 220 GB | $1.20 |
| A30 | 24 GB | 16 | 90 GB | $1.35 |
| A40 | 48 GB | 16 | 100 GB | $1.44 |
| RTX PRO 6000 | 96 GB | 32 | 170 GB | $1.90 |
| A100 40 GB | 40 GB | 16 | 115 GB | $1.98 |
| A100 80 GB | 80 GB | 16 | 115 GB | $2.10 |
| H100 | 80 GB | 26 | 250 GB | $3.77 |
| H200 | 141 GB | 30 | 375 GB | $4.54 |
| B200 | 192 GB | 32 | 400 GB | $6.99 |

- Regions: **Mumbai, Delhi, Bangalore**.
- Entry GPUs from **Rs 49-50/hour**; L4 quoted at Rs 50-70/hour on cloud-terms pages.
- **Spot instances at 65-70% discount.**
- Billing: per-minute, INR-denominated.

---

## 6b. Cloudflare

Sources: `developers.cloudflare.com/r2/pricing/`; `cloudflare.com/products/r2/`;
`cloudflare.com/plans/zero-trust-services/`; `developers.cloudflare.com/workers/platform/pricing/`.

### R2 object storage

| Item | Standard | Infrequent Access |
|---|---:|---:|
| Storage | **$0.015 / GB-month** | $0.010 / GB-month |
| Data retrieval (processing) | None | $0.010 / GB |
| **Egress to internet** | **$0** | **$0** |
| Free tier | 10 GB-month | — |
| Class B operations (GET, SELECT) | $0.00036 / 1,000 | — |

- **Single storage class family — there is no archival/cold tier equivalent to Glacier.**
- **S3-compatible API**: `boto3` with `endpoint_url = https://{account-id}.r2.cloudflarestorage.com`.

### Access / Zero Trust

- **Free plan up to 50 users.**
- Supports **email one-time PIN (OTP)** — no Google/Microsoft SSO integration required.
- Sits in front of an existing origin; no application code changes needed.

### Pages / Workers

- Pages: static hosting, **no egress charges**.
- Workers: JS/WASM at the edge, CPU-time limited. Containers exist but are not an AWS Batch
  equivalent. **No general GPU rental; Workers AI carries no Odia ASR model.**

---

## 6c. AWS S3 storage classes (for comparison)

Source: `aws.amazon.com/s3/storage-classes/glacier/` and cross-checked pricing analyses.

| Class | Storage | Notes |
|---|---:|---|
| S3 Standard | $0.023 / GB-month | Hot |
| **S3 Glacier Deep Archive** | **$0.00099 / GB-month** ($1 / TB-month) | Lowest cost in the cloud; **retrieval latency in hours**, per-GB retrieval cost |
| Egress to internet | **$0.09 / GB** after 100 GB/month free | The decisive difference vs R2 |

**Deep Archive is roughly 10-15x cheaper than R2's cheapest option** and has no Cloudflare
equivalent. Conversely R2 is ~35% cheaper than S3 Standard on hot storage and charges nothing
for egress.

---

## 7. GPU hardware specifications

| | RTX A5000 | A10G | A10 | L4 | T4 |
|---|---|---|---|---|---|
| Architecture | Ampere GA102 | Ampere | Ampere | Ada | Turing |
| VRAM | 24 GB GDDR6 | 24 GB GDDR6 | 24 GB GDDR6 | 24 GB | 16 GB |
| Memory bandwidth | **768 GB/s** | 600 GB/s | 600 GB/s | — | — |
| Released | 2021 | Q2 2021 | Q2 2021 | — | — |

Sources: TechPowerUp GPU database (A5000: GA102, 628 mm2 die, 28.3 bn transistors);
GetDeploying (A10G vs A5000 bandwidth); GPUPerHour (768 vs 600 GB/s); Baseten (A10 and A10G
"similar in GPU memory and bandwidth, mostly interchangeable").

Cross-cloud market rates (Shadeform): **A5000 from $0.44/h; A10 from $1.29/h.**

---

## 8. Project's own measured figures

Source: this repository. These are measurements, not estimates.

| Figure | Value | Location |
|---|---|---|
| DFN end-to-end real-time factor | **0.280761** | `data/enhance/jobs/*/job.json`, `benchmark` |
| DFN model-inference real-time factor | **0.09642** | same |
| Runtime | `torch 2.0.1+cpu`, 6 threads, no CUDA | same |
| Benchmark basis | 57.46 s audio in 16.132543 s wall | same |
| Rupanuga source duration | 6,373.624125 s | `job.json`, `source` |
| Estimated full render | 900-1,200 s (chunked); 1,200-1,800 s (delivery) | `job.json` |
| Working tree total | **53 GB** | `du -sh` |
| `.worktrees/` | 41 GB | `du -sh` |
| Per-job working sets | Rupanuga 19 GB, Haladhara 12 GB, SPAD 8.1 GB | `du -sh` |
| Deliverable sizes | FLAC 204,757,230 B; MP3 65,992,365 B | `ls -la` |
| RunPod baseline | $0.27/h A5000 + $2.80/mo 40 GB (EU-SE-1) | `docs/project-findings.md` s6 |

---

## 9. Odia bid figures

Source: `docs/odia-transcription-bid-estimate-2026-07-25.md` (FX 1 USD = 96.72 INR).

| Figure | Value |
|---|---|
| Oriya corpus | 1,357 files / **1,952 audio-hours** / 86 min mean / 64 kbps CBR |
| Full archive | 2,020 files / ~2,831 hours |
| **Compute line (GPU + API + LLM)** | **~$6k — about 1% of the bid** |
| Tier 1 / 2 / 3 | $215k / $510k / $940k |
| Effort ratio M adopted | 11.5 (credible range 5.5-36) |
| Whisper on Odia | `or`/`ory` absent from tokenizer; **125.6% WER** |
| IndicConformer (clean benchmark) | **20.6% WER / 12.1% OIWER** |
| Azure `or-IN` / Sarvam `od-IN` (degraded field audio) | 35.1% / 35.8% WER |
| MMS-1B-all licence | **CC-BY-NC — commercially unusable** |

---

## 10. Figures derived in this folder

Arithmetic, not measurement. Shown so it can be checked.

| Derived figure | Calculation | Result |
|---|---|---|
| DFN compute per Rupanuga lecture | 6,373.6 s x 0.28 | ~1,784 s = 0.5 h |
| Cost per lecture, `c7i.2xlarge` Spot | 0.5 h x $0.168 | **$0.08** |
| Cost per lecture, `c7g.2xlarge` Spot | 0.5 h x $0.127 | **$0.06** |
| Enhancement of full Odia corpus | 1,952 h x 0.28 = 547 h | **$69-92** on CPU Spot |
| ASR GPU-hours at 50x / 20x / 10x realtime | 1,952 / N | 39 / 98 / 195 |
| GPU cost spread at 98 GPU-h | $77.20 - $17.57 | **$59.63** |
| GPU cost spread at 195 GPU-h | $154.40 - $35.14 | **$119.26** |
| Spread as share of Tier 1 bid | $119 / $215,000 | **0.055%** |
| Implied API + LLM spend | ($6,000 - ~$100) / 1,952 h | **~$3.02 / audio-hour** |
| CPU-only ASR hypothesis at 1-2x realtime | 976-1,952 h x $0.065 | **$63-127** |
| 41 GB working set on R2 Standard | 41 x $0.015 | **$0.62 / month** |
| 41 GB working set on S3 Standard | 41 x $0.023 | **$0.94 / month** |
| Odia corpus size at 64 kbps | 1,952 h x 3600 s x 8,000 B/s | **~56 GB** |
| 56 GB on R2 Standard / R2 IA | 56 x $0.015 / x $0.010 | $0.84 / $0.56 per month |
| 56 GB on S3 Glacier Deep Archive | 56 x $0.00099 | **$0.06 / month** |
| Full 41 GB re-download, S3 (past free tier) | 41 x $0.09 | **$3.69** vs **$0** on R2 |
| One lecture (271 MB) to 50 devotees | 13.5 GB x $0.09 | **$1.22** vs **$0** on R2 |
| Total annual spread, all storage options | — | **under $15/year** |

---

## 11. Known weaknesses in this evidence base

1. **IndicConformer RTF is unmeasured.** Every Odia GPU-hour figure inherits this.
2. **AWS prices are us-east-1 only.** ap-south-1 unpriced.
3. **The $6k compute figure is inherited**, not independently rebuilt. The $3.02/audio-hour
   API figure is derived from it by subtraction and should be verified against Azure, Sarvam
   and ElevenLabs list pricing directly.
4. **Some provider figures are third-party**, not primary — notably RunPod's $0.07/GB
   network-volume rate and the "70-85% Community uptime" claim.
5. **Graviton compatibility with DeepFilterNet is untested.**
6. **Storage measurements were taken from a live, changing worktree** during a parallel
   working session.
7. **Cloudflare figures are from Cloudflare's own documentation** and have not been validated
   by running an account. Free-tier boundaries (notably the Access 50-user limit) should be
   re-checked before relying on them.
8. **The ~56 GB Odia corpus size is derived** from bitrate x duration, not measured on disk.
