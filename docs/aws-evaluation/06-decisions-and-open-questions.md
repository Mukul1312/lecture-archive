# 06 — Decisions, Open Questions, and What Comes Next

**Date:** 2026-08-24 · **Status:** 3 of 12 categories analysed, plus the cross-cutting provider
comparison in [07](07-cloudflare-and-the-provider-matrix.md).

---

## 1. Decisions reached

| # | Decision | Basis | Confidence |
|---|---|---|---|
| D1 | The driver is **learning AWS / career**, not cost, scale, durability, or client requirement | Stated by the user | Settled |
| D2 | Evaluate by **resource category**, not by workload | User rejected the workload framing; inventory framing adopted | Settled |
| D3 | **Category 1 (CPU compute) is a yes** on learning value; compute cost is negligible (<$0.10/lecture) | Computed from measured RTF 0.28 | High |
| D4 | **Categories 2–3 (GPU) are a no** — quota friction and absent hardware tiers, not price gouging | AWS quota docs; hardware specs; corrected after challenge | High |
| D5 | The **RunPod Community Cloud baseline is unsound** — tier in structural wind-down | RunPod docs, modified 2026-08-18 | High |
| D6 | The strongest non-AWS GPU options are **India-based** (JarvisLabs, E2E Networks) | Live pricing; region and billing fit | Medium-high |
| D7 | **GPU provider choice is economically irrelevant** to the Odia bid (~0.05% of contract value) | Cost model in doc 05 | High |
| D8 | **Revised in [07](07-cloudflare-and-the-provider-matrix.md).** The case for cloud is storage, governance and delivery — but **Cloudflare** is stronger for the hot/served layer (R2, Access, Pages, CDN) while **AWS** holds cold archive (Glacier Deep Archive) and batch-compute learning value | Emergent across 02–07 | Provisional |
| D9 | The biggest single win in category 1 (reproducibility) is **Docker's, not AWS's** | `pod_setup.sh` analysis | High |
| D10 | Cloudflare is a **storage/delivery/access layer, not a compute platform** — it complements the GPU decision rather than competing with it | Workers CPU limits; no GPU rental | High |
| D11 | **Cloudflare Access** is the clearest functional fix for category 9 and is free at this scale (50 users, email OTP, no gallery code changes) | Cloudflare Zero Trust plans | Medium-high |
| D12 | **R2's S3-compatible API** means the storage choice is not a learning sacrifice — the boto3/S3 skill transfers, only `endpoint_url` changes | Cloudflare R2 docs | High |
| D13 | Storage cost, like GPU cost, **cannot decide this** — the total annual spread across all options is under $15 at current data volumes | Doc 07 §6 | High |
| D14 | **The API tier is $0.73–$1.03 per audio-hour, not $3.02** — doc 05's derived figure is 3–4x high, so the corpus prices at $1,430–$2,010 rather than $5,900. Structurally this *strengthens* D7. **But it changes no decision:** the bid estimate already called compute “a rounding error … about 1% of the bid”, and this moves it to ~0.3%. The deciding number is **M, human work-hours per audio-hour** (range 5.5–36, adopted at 11.5), which the estimate flags as “the number the pilot must measure” | [evidence/api-tier-pricing-2026-08-27.md](evidence/api-tier-pricing-2026-08-27.md), verified against list prices | High |

---

## 2. Open questions — blocking

These must be answered before the remaining categories can be analysed properly.

### Q1. Which region?

All prices in this folder are **us-east-1**. The user is in India; the previous RunPod volume
was EU-SE-1. **ap-south-1 (Mumbai) is the likely real region** and differs on price, and
possibly on instance-type availability.

**Blocks:** every cost figure in this folder.

### Q2. Does the local-first state decision stand?

`docs/superpowers/specs/2026-08-22-heritage-production-ddd-hexagonal-design.md` approves a
**local-first modular monolith with SQLite, deliberately not cloud**. Category 10 cannot be
analysed without knowing whether that decision is open for reconsideration or fixed.

**Recommendation:** treat it as fixed unless consciously reversed. Drifting past an approved
architectural decision is exactly the failure mode the DDD work was undertaken to prevent.

### Q3. Is the Odia bid live? — **Answered 2026-08-27: there is no bid.**

First answer: the estimate exists but is pre-bid, *"Not yet signed"*. The steward then
corrected the premise outright — **programme 1 is volunteer seva.** No client, no money, no
transaction. Transcripts are handed to a senior devotee; reviewers are unpaid volunteers.
The estimate was, in his words, *"a basic document"*.

**This does not reopen categories 2–3.** The work runs today on Sarvam, a hosted API, not on
GPU anyone rents — so there is still no GPU workload, which strengthens D4 rather than
challenging it. It also removes any commercial reason to optimise anything in this folder.

### Q12. What is M, human work-hours per audio-hour? — **downgraded 2026-08-27**

Briefly recorded here as the question that mattered, on the reasoning that one point of M
outweighed every infrastructure question in this folder against a $215k contract.

**With no contract, M stops being a cost driver and becomes a schedule input.** Volunteers
are unpaid, so a higher M costs time rather than money, and the steward has said the
schedule may stretch. Measuring it is no longer worth a pilot.

What replaced it is a standard, not a number: devotees will read the transcript **while
listening to the lecture**, so a light Odia read-through is the matched level of review and
audio-verified checking is over-engineering. See section 5a of
[evidence/api-tier-pricing-2026-08-27.md](evidence/api-tier-pricing-2026-08-27.md).

---

## 3. Open questions — non-blocking

- **Q4.** Does DeepFilterNet3 run correctly on ARM64 (Graviton `c7g`)? Worth ~24% on CPU
  compute. Untested.
- **Q5.** What is the IndicConformer real-time factor, on GPU and on CPU? The only guessed
  number in the cost model. Belongs in Gate 0a.
- **Q6.** Is the 19 GB per-job working set worth persisting at all, or should it be treated as
  fully disposable? This is the central design tension between resumability and storage cost,
  and it drives categories 5 and 12.
- **Q7. Answered 2026-08-27.** Azure `S1 Speech to Text Batch` $0.18/hr, Sarvam STT+Translate
  ₹30/hr ($0.31), ElevenLabs Scribe v2 batch $0.22/hr — **$0.73–$1.03 per audio-hour with LLM
  reconciliation**, against the $3.02 doc 05 derived. See
  [evidence/api-tier-pricing-2026-08-27.md](evidence/api-tier-pricing-2026-08-27.md).
  **Both replacement questions are now closed.** (a) Sarvam's 2.5x contradiction was settled
  **by invoice** on 2026-08-27 rather than by email: a real lecture billed ₹38 for 51.4
  minutes, which is ₹44.36/hour — the ₹45 diarization tier. The developer pricing table is
  correct and the per-minute product-page figures are not what gets billed. Diarization is
  being dropped, putting the corpus at **₹58,560 (~$613)**. (b) Rebuilding the ~$6,000
  compute line is moot: there is no client. See Q3.
- **Q8.** Does serverless GPU (Modal, RunPod Serverless, fal) fit the bursty sweep pattern
  better than a rented instance? Flagged, not analysed.
- **Q9.** Is there an existing Cloudflare account or DNS zone from the earlier projects? An
  existing zone makes Access and Pages nearly free to adopt.
- **Q10.** Should a cold-archive tier be adopted now, given the corpus is ~56 GB and the annual
  saving over R2 is under $10? The argument for Glacier Deep Archive here is **durability
  discipline**, not cost.
- **Q11.** Does R2's lack of an archival class matter in five years, if the corpus grows from
  tens to hundreds of gigabytes?

---

## 4. Remaining categories

Each must now be assessed against **three** options — AWS, Cloudflare, and
provider-agnostic/local — rather than two.

| # | Category | AWS mapping | Cloudflare option | Difficulty |
|---|---|---|---|---|
| 4 | Persistent network storage | EFS, FSx, EBS | **None** | Moderate — interacts with Q6 |
| 5 | Object and bulk data | S3, storage classes, Glacier, lifecycle | **R2** (hot); no archive tier | **High value** — the 190x amplification problem |
| 6 | Model artifact registry | ECR, S3, SageMaker Model Registry | R2 (storage only, no registry semantics) | Moderate |
| 7 | Code and artifact transfer | ECR, S3, CodeArtifact | — | Low — largely solved by containers |
| 8 | Static web hosting | S3 + CloudFront, Amplify | **Pages** | Low — likely "just different" vs Vercel |
| 9 | Access control | CloudFront signed URLs, Cognito, IAM | **Access (Zero Trust)** — free to 50 users | **High value** — clearest functional upgrade |
| 10 | State and database | DynamoDB, RDS, Aurora — **or deliberately not** | D1 — **also contradicts the DDD design** | **Contentious** — see Q2 |
| 11 | Secrets and identity | Secrets Manager, Parameter Store, IAM | Workers Secrets (only if compute moves) | Low — clean 1:1 swap |
| 12 | Caching | S3 + lifecycle, ElastiCache, EFS | **CDN + R2** | Moderate — interacts with Spot interruption |

**Suggested order:** 5 and 9 first — they carry the highest value and the clearest arguments.
Then 4 and 12 together, since all three storage-shaped categories interact. Then 6, 7, 11 as a
fast block. Then 8. Then 10 last, once Q2 is settled.

---

## 5. Provisional shape of the answer

Stated as a hypothesis to be tested by the remaining analysis, **not** as a conclusion:

> **Cloudflare for the hot, served and access-controlled layer (R2, Access, Pages, CDN).
> AWS for cold archive and for the batch-compute learning value (ECR, Batch, Spot).
> India-based providers for GPU. Local-first for state and approval. Containers everywhere,
> because that benefit is portable.**

If the remaining nine categories support this, the outcome is a **deliberate hybrid** rather
than a migration — which would also be the more interesting portfolio story, since choosing
*not* to move something and being able to say why is a stronger signal than moving everything.

---

## 6. What this folder is not

- Not a migration plan. No sequencing, no IaC, no account setup.
- Not a commitment. Nothing has been provisioned or spent.
- Not a substitute for measurement. Q4 and Q5 in particular need experiments, not more
  research.
