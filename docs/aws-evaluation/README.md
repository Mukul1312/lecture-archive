# AWS Evaluation for the Heritage Audio Project

**Started:** 2026-08-24 · **Status:** in progress — 3 of 12 categories analysed, plus a cross-cutting
provider comparison · **No actions taken; discussion only.**

This folder records a structured evaluation of whether, and where, Amazon Web Services
should be used for this project. It is a *decision record*, not a migration plan. Nothing
in it has been implemented, provisioned, or committed to.

---

## Why this exists

The project has been built across a local Windows machine and four different cloud GPU
providers, accumulating twelve distinct kinds of infrastructure resource without ever
choosing a platform deliberately. This evaluation asks, category by category, what AWS
would actually replace and whether that replacement is an improvement.

The stated driver is **learning AWS for career value** — not cost reduction, not scale
pressure, not a client requirement. That choice shapes every verdict in this folder and is
recorded explicitly in [00-scope-and-method.md](00-scope-and-method.md).

---

## How to read this folder

| Document | What it covers |
|---|---|
| [00-scope-and-method.md](00-scope-and-method.md) | Why this evaluation exists, the driver, the method, ground rules, what is out of scope |
| [01-resource-inventory.md](01-resource-inventory.md) | The twelve resource categories this project actually consumes, with repo evidence |
| [02-category-01-local-cpu-compute.md](02-category-01-local-cpu-compute.md) | Category 1 — local CPU compute → EC2 / Batch / Fargate |
| [03-categories-02-03-gpu-compute.md](03-categories-02-03-gpu-compute.md) | Categories 2 & 3 — ephemeral and batch GPU, including a recorded correction |
| [04-gpu-provider-landscape.md](04-gpu-provider-landscape.md) | The non-AWS options: RunPod tiers, marketplaces, India-based providers |
| [05-odia-gpu-cost-model.md](05-odia-gpu-cost-model.md) | The Odia transcription scenario priced across four providers |
| [07-cloudflare-and-the-provider-matrix.md](07-cloudflare-and-the-provider-matrix.md) | Cloudflare as a third provider; R2 vs S3; the provisional 12-category provider matrix |
| [06-decisions-and-open-questions.md](06-decisions-and-open-questions.md) | What has been decided, what is open, what must be measured |
| [evidence/price-snapshot-2026-08-24.md](evidence/price-snapshot-2026-08-24.md) | Every external number with its source and retrieval date |
| [evidence/api-tier-pricing-2026-08-27.md](evidence/api-tier-pricing-2026-08-27.md) | **The hosted ASR tier, verified.** Corrects doc 05's $3.02/audio-hour to $0.73–$1.03 |

Read 00 and 01 first. Categories 02–05 can be read independently.

---

## Decisions reached so far

| # | Decision | Confidence | Where |
|---|---|---|---|
| D1 | The driver is learning/career, not cost or scale | Stated by user | 00 |
| D2 | Evaluate by resource category, not by workload | Agreed | 00 |
| D3 | Category 1 (CPU compute) is a genuine yes on learning value; compute cost is negligible | High | 02 |
| D4 | Categories 2–3 (GPU) are a no on merit — quota friction and absent hardware tiers, **not** price gouging | High, after correction | 03 |
| D5 | The RunPod Community Cloud baseline is unsound — the tier is in structural wind-down | High | 04 |
| D6 | The strongest non-AWS GPU options are India-based (JarvisLabs, E2E Networks) | Medium-high | 04 |
| D7 | GPU provider choice is economically irrelevant to the Odia bid (spread ≈ $60–120 on a $215k bid) | High | 05 |
| D8 | **Revised.** The case for cloud is storage, governance and delivery — but Cloudflare is stronger for the hot/served layer while AWS holds cold archive and batch-compute learning value | Provisional | 07 |
| D10 | Cloudflare is a storage/delivery/access layer, **not** a compute platform — it complements rather than replaces the GPU decision | High | 07 |
| D11 | Cloudflare Access is the clearest functional fix available for category 9, and is free at this scale | Medium-high | 07 |
| D12 | R2's S3-compatible API means the storage decision need not be a learning sacrifice — the SDK skill transfers | High | 07 |
| D14 | **The API tier costs $0.73–$1.03 per audio-hour, not $3.02** — but compute was already a rounding error, so this changes no decision. The bid's deciding number is **M, human work-hours per audio-hour** (5.5–36) | High | evidence/api-tier-pricing-2026-08-27 |

---

## Still to analyse

Categories 4–12: persistent network storage, object/bulk data, model artifact registry,
code and artifact transfer, static web hosting, access control, state and database,
secrets and identity, caching. Each must now be assessed against **three** providers
(AWS, Cloudflare, and provider-agnostic/local) rather than two. See
[06-decisions-and-open-questions.md](06-decisions-and-open-questions.md) and the provisional
matrix in [07](07-cloudflare-and-the-provider-matrix.md) section 9.

---

## Standing caveats

1. **All AWS prices in this folder are us-east-1, Linux, list.** The user is in India and
   the previous RunPod volume was EU-SE-1. **ap-south-1 (Mumbai) is the likely real region
   and its prices differ.** Every figure must be re-priced once a region is chosen.
2. **Prices retrieved 2026-08-24** and will drift. See the evidence file for sources.
3. **The IndicConformer real-time factor is unmeasured.** All Odia GPU-hour figures are
   bracketed estimates, not measurements. This is flagged wherever it matters.
4. **Cloudflare rates** (R2 $0.015/GB-mo, zero egress; Access free to 50 users) retrieved
   2026-08-24 from Cloudflare's own documentation.
5. Nothing here has been validated by running it.
