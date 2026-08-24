# 04 — GPU Provider Landscape

**Date:** 2026-08-24 · **Purpose:** answer the question "if not AWS, and if RunPod is
weakening, then what?"

All prices retrieved 2026-08-24; see
[evidence/price-snapshot-2026-08-24.md](evidence/price-snapshot-2026-08-24.md).

---

## 1. The finding that changes the baseline

RunPod's own documentation, last modified **2026-08-18**, states:

> **"Runpod is no longer accepting new hosts for Community Cloud. Existing Community Cloud
> resources remain available."**

Community Cloud is the tier that supplied the **$0.27/h A5000** on which this project's cost
intuitions were built. Existing capacity remains, but it will not be replenished.

**Consequence:** the project's GPU cost baseline is a **depreciating asset**. Any plan that
assumes $0.27/h has a shelf life, and any comparison against that number understates the true
cost of the status quo.

### The tier distinction, from RunPod's documentation

| | Secure Cloud | Community Cloud |
|---|---|---|
| Infrastructure | T3/T4 data centres | Peer-to-peer providers |
| Reliability | High redundancy | **Variable** |
| Best for | Production, sensitive data | Cost-sensitive workloads |
| Pricing | Standard | Competitive |

Third-party reporting puts the cheapest Community tiers at **70–85% uptime**. This is the
proximate explanation for the pod-restart failures recorded in `project-findings.md`
section 6 — the tier was behaving as specified.

---

## 2. The four-tier landscape

| Tier | Providers | Character | Fit for this project |
|---|---|---|---|
| **Marketplace** | Vast.ai, RunPod Community | Cheapest; variable reliability; auction or peer-supplied | **Poor** — a fail-closed production pipeline should not run on 70–85% uptime |
| **Managed GPU cloud** | RunPod Secure, Lambda Labs, Hyperstack, Northflank, Thunder Compute, Paperspace, Modal | Mid price, real SLAs, simple onboarding | **Good** |
| **India-based** | **JarvisLabs**, **E2E Networks**, Neysa, Yotta | INR billing, low latency, data sovereignty | **Best fit** |
| **Hyperscaler** | AWS, GCP, Azure | Most expensive, most integrated, quota-gated | Poor for GPU; strong for storage/governance |

---

## 3. Price comparison at the tier that matters

The prospective Odia workload needs roughly 3–5 GB VRAM, so **L4 (24 GB) is the reference
tier** and T4 (16 GB) is sufficient.

| Provider | L4 On-Demand | Discounted / Spot | Region | Billing |
|---|---|---|---|---|
| **JarvisLabs** | **$0.44** | ~$0.19 (Spot, up to 56% off) | India | **Per-minute** |
| **E2E Networks** | $0.57 | ~$0.17–0.20 (Spot, 65–70% off) | Mumbai / Delhi / Bangalore | Per-minute |
| **RunPod Secure** | L4 in catalogue (`AMPERE_24`) | — | Global | Per-second |
| **AWS `g6.xlarge`** | $0.805 | **$0.791 (1.7% off)** | Quota-gated | Per-second |
| *AWS `g4dn.xlarge` (T4)* | *$0.526* | *$0.356* | *Quota-gated* | Per-second |

### Wider catalogue, for context

| GPU | JarvisLabs | E2E Networks |
|---|---|---|
| L4 24 GB | $0.44 | $0.57 |
| A30 24 GB | $0.41 | $1.35 |
| A100 40 GB | $0.89 | $1.98 |
| A100 80 GB | $1.49 | $2.10 |
| L40S 48 GB | — | $1.20 |
| H100 80 GB | $2.69 | $3.77 |
| H200 141 GB | $3.99 | $4.54 |

JarvisLabs is consistently cheaper than E2E at every comparable tier, and both are well below
AWS.

---

## 4. The two India-based options in detail

### JarvisLabs

- **Per-minute billing** — significant for bursty work such as an engine bake-off, where a
  10% rate difference matters far less than not paying for idle hours.
- **Dedicated datacentre hardware, 99.9% uptime**, no community-cloud gamble.
- Self-serve signup, no quota ticket.
- Spot available at up to 56% off; commitment discounts are modest (1 month 2%, 3 months 3%,
  6 months 5%, 1 year 9%) — which suits an uncommitted project.

**Why it fits:** it targets precisely the failure mode that cost this project time — pods
that will not restart — without paying hyperscaler rates.

### E2E Networks

- **Three Indian regions** (Mumbai, Delhi, Bangalore) with explicit data-sovereignty
  positioning — directly relevant given the rights-holder and steward-approval model in the
  DDD design.
- **Deepest spot discount found: 65–70%**, entry GPUs from around ₹49–50/hour.
- Per-minute billing, INR-denominated.

**Why it fits:** the better choice for sustained, large-volume corpus processing where the
spot discount compounds, and where Indian data residency is an argument to the client.

---

## 5. Storage and egress — an under-weighted RunPod advantage

| | RunPod | AWS |
|---|---|---|
| Network storage | From **$0.05/GB/month** | S3 tiers plus EBS |
| Data transfer out | **No data-transfer fees** reported | **Per-GB egress** |

Against a 41 GB working set that is repeatedly written, read, and pulled back down, the
absence of egress charges is a material and easily overlooked advantage. This should be
carried forward into the category 4 and 5 analyses rather than treated as a GPU footnote.

---

## 6. Serverless GPU — worth a look

For a workload that runs for a couple of hours a month, **scale-to-zero** is a better shape
than a rented instance. **Modal**, **RunPod Serverless** and **fal** all offer per-second GPU
execution with no idle cost.

Modal in particular is career-legible and would satisfy part of the learning driver without
AWS's quota gate. Flagged as an option, not yet analysed.

---

## 7. Conclusions

1. **The RunPod Community baseline is unsound** — the tier is in wind-down. Re-baseline
   before making any cost argument.
2. **RunPod Secure remains viable**, but once paying Secure rates the India-based providers
   become directly competitive on both price and reliability.
3. **JarvisLabs and E2E Networks are the strongest non-AWS options**, beating AWS
   simultaneously on price, latency, billing currency, and data sovereignty.
4. **AWS is not competitive for GPU in this project** and its Spot escape hatch is closed at
   the L4 tier.
5. **Egress-free storage** is a real RunPod advantage that must be carried into the storage
   analysis.
