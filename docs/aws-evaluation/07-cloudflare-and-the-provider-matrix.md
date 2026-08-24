# 07 — Cloudflare, and the Provider Matrix

**Date:** 2026-08-24 · **Status:** provisional; revises decision D8.

---

## 1. Origin and scope of this document

The user raised Cloudflare from **prior experience on other projects**, not from use in this
one. That distinction matters and is recorded because it changes the evaluation in two
opposite directions at once (see section 8).

**Repository check:** a scoped search for `cloudflare`, `r2`, `wrangler`, `workers.dev`,
`pages.dev`, `cf-` and `tunnel` across `docs/`, `cloud/`, `scripts/`, `colab/`, the site
directories and all root config files returned **no Cloudflare usage**. Every apparent hit was
a false positive:

- `r2` / `R2` in `scripts/propose_segments.py` and `scripts/score_calibrate.py` — the
  statistical coefficient of determination.
- `tunnel` in `cloud/asr_ab.py:223` and `scripts/build_probe_gallery.py:7` — **SSH tunnels**
  to a pod's `http.server` on `localhost:8000`, not Cloudflare Tunnel.

There is therefore nothing Cloudflare-shaped in this project to migrate from or to
reconcile. This is a clean evaluation, like the AWS one.

---

## 2. What Cloudflare is, in this project's terms

Cloudflare is **a storage, delivery and access layer — not a compute platform.** It
complements the India-based GPU providers from
[04-gpu-provider-landscape.md](04-gpu-provider-landscape.md) rather than competing with them,
and it competes with AWS only in categories 5, 8, 9 and 12.

That is precisely the set of categories where decision D8 provisionally located "AWS's real
case." Cloudflare's entry therefore challenges D8 directly.

---

## 3. Where Cloudflare fits

| Category | Cloudflare service | AWS equivalent | Assessment |
|---|---|---|---|
| **5 — Object/bulk data** | **R2** — $0.015/GB-mo, **$0 egress**, S3-compatible API | S3 Standard $0.023/GB-mo + $0.09/GB egress | **Cloudflare better** for hot and served data |
| **8 — Static hosting** | **Pages** — no egress charges | S3 + CloudFront, or Amplify | Roughly equal; consolidation is the argument |
| **9 — Access control** | **Access (Zero Trust)** — free to 50 users, email one-time PIN | Cognito + CloudFront signed URLs | **Cloudflare clearly simpler** |
| **12 — Delivery cache** | CDN in front of R2, included | CloudFront, metered | **Cloudflare better** on cost model |

---

## 4. Where Cloudflare cannot help

| Category | Why not |
|---|---|
| **1 — CPU compute** | Workers run JS/WASM under CPU-time limits. DeepFilterNet (Rust core plus PyTorch) will not run there. Containers exist but are not an AWS Batch equivalent. |
| **2/3 — GPU** | No general GPU rental. Workers AI carries no Odia ASR model, and Whisper is useless for Odia regardless (125.6% WER). |
| **4 — Persistent network storage** | No EFS/FSx analogue. |
| **6 — Model artifact registry** | R2 can hold weights, but there are no registry semantics (versioning, lineage, staging). |
| **10 — State** | D1 (managed SQLite) exists and is tempting given the SQLite decision — but the approved DDD design specifies **local-first, deliberately not cloud**. Moving to D1 would contradict it as much as moving to DynamoDB would. See Q2 in [06](06-decisions-and-open-questions.md). |

---

## 5. The storage comparison in detail

| Dimension | Cloudflare R2 | AWS S3 |
|---|---|---|
| Hot storage | **$0.015/GB-month** | $0.023/GB-month (Standard) |
| Infrequent access | $0.01/GB-month + $0.01/GB retrieval | S3 IA / Intelligent-Tiering |
| **Cold archive** | **None — single class only** | **Glacier Deep Archive $0.00099/GB-month** |
| **Egress** | **$0** | **$0.09/GB** after 100 GB/month free |
| Free tier | 10 GB-month | Varies |
| API | **S3-compatible** (`boto3` with `endpoint_url`) | Native |

### The one place AWS clearly wins

**R2 has no archival tier.** S3 Glacier Deep Archive at **$0.00099/GB-month ($1/TB-month)** is
roughly **10–15x cheaper than R2's cheapest option**.

For irreplaceable heritage masters — files that should exist in three places and be touched
once a decade — Deep Archive is the correct product and Cloudflare has no answer. The
trade-off is retrieval: **hours of latency** plus per-GB retrieval cost, which makes it wrong
for anything that might be wanted this week.

### Why R2's zero egress matters *here* specifically

[01-resource-inventory.md](01-resource-inventory.md) established that this project's data has
**~190x amplification** — a 102 MB source becomes a 19 GB working set — and that the working
set is written, read, and pulled back repeatedly. It also serves 205 MB FLAC deliverables to
devotees and named external reviewers.

Both patterns are egress-heavy. On S3 every retrieval meters; on R2 none does.

---

## 6. Scale reality check — the same lesson as GPU

Applying the rates to this project's actual data:

| Data population | Size | R2 Standard | R2 IA | S3 Standard | S3 Deep Archive |
|---|---:|---:|---:|---:|---:|
| Enhancement working sets | 41 GB | $0.62/mo | $0.41/mo | $0.94/mo | — (wrong product) |
| `data/` corpora and outputs | 8.3 GB | $0.12/mo | $0.08/mo | $0.19/mo | — |
| Odia corpus (1,952 h @ 64 kbps) | ~56 GB | $0.84/mo | $0.56/mo | $1.29/mo | **$0.06/mo** |

Annualised, **the total spread across every option is under $15 per year.**

Egress tells the same story at this scale: a full 41 GB re-download costs **$3.69** on S3 once
past the 100 GB monthly free allowance, and **$0** on R2. Serving one lecture's 271 MB
deliverable pair to fifty devotees is ~13.5 GB — **$1.22** versus **$0**.

**Conclusion, identical in shape to [05](05-odia-gpu-cost-model.md): storage cost cannot decide
this.** What should decide it are the operational properties:

1. **Zero egress removes an entire category of anxiety.** Serving sacred audio to devotees
   without watching a meter has value beyond the dollars.
2. **Deep Archive retrieval latency is hours.** Correct for masters; wrong for working data.
3. **Access solves a problem that is currently unsolved.** See below.

---

## 7. The genuinely strong argument: category 9

This is the single clearest functional win available anywhere in this evaluation, for either
provider.

The approved DDD design requires that "selected external reviewers receive versioned review
packages," and that a production can require named reviewer, subject-matter, or rights-holder
sign-offs. The current implementation is static passcodes, unlisted URLs, `noindex` and
base64-encoded keys — which the same document states are **not access control**.

**Cloudflare Access (Zero Trust) is free for up to 50 users and supports email one-time PIN**,
requiring no SSO integration. It places an identity gate in front of an existing static site
**with no change to the gallery code** — `build_*_gallery.py` and the generated HTML stay
exactly as they are.

The AWS equivalent is CloudFront signed URLs plus Cognito user pools: more services, more
plumbing, more code, and a genuine learning curve. For an outcome the project needs and does
not currently have, Cloudflare's version is materially simpler and costs nothing at this scale.

---

## 8. The learning driver — and why prior experience cuts both ways

The stated driver is **learning AWS for career value** ([00 §2](00-scope-and-method.md)). The
user's Cloudflare experience comes from **other projects**, which produces a genuine tension:

| Factor | Effect |
|---|---|
| Prior Cloudflare experience | **Lowers adoption friction** — known console, possibly an existing account and zone |
| Prior Cloudflare experience | **Lowers learning value** — using it here does not advance the career goal |
| Cloudflare technically better for 5/8/9/12 | Pulls toward Cloudflare |
| AWS is the stated learning target | Pulls toward AWS |

This is exactly the "tuition, not architecture" situation the ground rules anticipated. It
should be resolved deliberately rather than by drift.

### The synthesis that mostly dissolves the tension

**R2 is S3-API compatible.** It is `boto3` with a different `endpoint_url`:

```python
s3 = boto3.resource('s3',
    endpoint_url='https://{account-id}.r2.cloudflarestorage.com',
    aws_access_key_id=..., aws_secret_access_key=...)
```

So the S3 **SDK, bucket semantics, presigned URLs, multipart upload, and lifecycle thinking**
can all be learned while pointing at R2. **The skill transfers; only the endpoint changes**,
and switching later is a configuration edit rather than a rewrite.

This does not cover Cloudflare Access or Glacier Deep Archive, which are genuinely
platform-specific. But it removes the largest part of the conflict, and it means the storage
decision does not have to be a learning sacrifice.

### Where the learning value genuinely is

Given prior Cloudflare familiarity, the AWS services that would actually teach something new
are **ECR, Batch, Spot interruption handling, IAM roles and CloudWatch** — that is,
[category 1](02-category-01-local-cpu-compute.md), which was already the highest-value unit in
the evaluation, and which Cloudflare cannot serve at all.

**The two conclusions are compatible rather than competing.**

---

## 9. Provisional provider matrix

Across all twelve categories. Provisional — categories 4 through 12 have not yet been analysed
in full.

| # | Category | Provisional home | Confidence |
|---|---|---|---|
| 1 | Local CPU compute | Local, or **AWS Batch on CPU Spot** (learning) | Medium-high |
| 2 | Ephemeral GPU | **JarvisLabs / E2E Networks** | Medium-high |
| 3 | Batch GPU | **JarvisLabs / E2E Networks** | Medium-high |
| 4 | Persistent network storage | Unanalysed | — |
| 5 | Object/bulk data — hot | **Cloudflare R2** | Medium |
| 5b | Object/bulk data — cold masters | **AWS S3 Glacier Deep Archive** | Medium |
| 6 | Model artifact registry | Unanalysed (likely ECR) | — |
| 7 | Code/artifact transfer | Containers — provider-agnostic | Medium |
| 8 | Static hosting | **Cloudflare Pages** (or keep Vercel) | Low-medium |
| 9 | Access control | **Cloudflare Access** | Medium-high |
| 10 | State/database | **Local-first SQLite** — per approved DDD design | High (unless Q2 reopens) |
| 11 | Secrets/identity | Unanalysed | — |
| 12 | Caching/delivery | **Cloudflare CDN + R2** | Medium |

---

## 10. Revised decision D8

> **D8 (original):** AWS's real case in this project is storage, governance and delivery — not
> compute.
>
> **D8 (revised):** The case for *cloud* is storage, governance and delivery. But the provider
> splits: **Cloudflare is stronger for the hot and served layer (R2, Access, Pages, CDN),
> while AWS holds the cold-archive tier (Glacier Deep Archive) and the batch-compute learning
> value (ECR, Batch, Spot).** GPU belongs with India-based providers. State stays local.

The likely outcome of this evaluation is therefore **a deliberate three-way hybrid**, not a
migration to any single platform.

---

## 11. Open questions added

- **Q9.** Is there an existing Cloudflare account or zone from the earlier projects? An
  existing zone makes Access and Pages nearly free to adopt.
- **Q10.** Should the cold-archive tier be adopted at all right now, given the total corpus is
  ~56 GB and the annual saving over R2 is under $10? The argument for Deep Archive here is
  **durability discipline**, not cost.
- **Q11.** Does R2's lack of an archival class matter in five years, when the corpus may be
  several hundred gigabytes rather than tens?
