# 03 — Categories 2 & 3: Ephemeral and Batch GPU Compute

**Date:** 2026-08-24 · **Verdict:** no on merit — but for different reasons than first stated.
**Contains a recorded correction.**

These two categories are analysed together because they are inseparable in practice: the same
hardware, quota, and provider decisions govern both interactive pod work and unattended batch
sweeps.

---

## Question 1 — What is the direct AWS equivalent?

| Current use | AWS equivalent |
|---|---|
| RunPod A5000 / 4090 interactive pod | **EC2 G5 / G6** (A10G / L4) |
| LoRA training run | **SageMaker Training Jobs** — closest analogue to `pod_train.sh` |
| 24-seed x 20-chunk sweep | **AWS Batch array jobs** on a GPU compute environment |
| Anything larger | P4 / P5 (A100 / H100) — far beyond this project's needs |

An important structural fact: **AWS sells no A5000 and no RTX 4090.** No consumer or
prosumer cards exist in its catalogue at all. There is therefore no like-for-like mapping;
G5 (A10G) and G6 (L4) are the nearest available equivalents, not exact ones.

---

## Question 2 — Better, or just different?

**Worse.** On two counts, both of which survived scrutiny.

### 2.1 The quota gate

From AWS's own documentation:

| Quota | Default | Adjustable |
|---|---|---|
| Running On-Demand G and VT instances | **0** | Yes |
| All G and VT Spot Instance Requests | **0** | Yes |

**A new AWS account cannot launch a single GPU instance.** A Service Quotas request must be
filed and approved — commonly days, and sometimes refused outright on a young account with no
billing history.

This must be weighed against the workflow the project actually uses: deploy a fresh pod onto
the `voxcpm-vol` network volume from the RunPod web console, and it is *instant* — no
download, no re-upload, no ticket. `docs/project-findings.md` section 6 records how much pod
friction already cost this project; AWS does not remove that friction, it substitutes a
slower and more bureaucratic version of it.

### 2.2 Price at the tier actually needed — including a Spot surprise

| Tier | Card | Instance | On-Demand | Spot | Spot discount |
|---|---|---|---|---|---|
| Over-specced | A10G 24 GB | `g5.xlarge` | $1.006 | $0.675 | 33% |
| **Right tier** | **L4 24 GB** | `g6.xlarge` | $0.805 | **$0.791** | **1.7%** |
| Also sufficient | T4 16 GB | `g4dn.xlarge` | $0.526 | $0.356 | 32% |

**The `g6` Spot discount is 1.7%.** L4 capacity on AWS is tight enough that Spot pricing is
effectively meaningless at exactly the tier this project would want — while CPU Spot on the
same account runs 55–59% below On-Demand.

This materially undercuts the usual defence that "AWS Spot makes it competitive." For L4, it
does not.

### 2.3 What AWS does do better

Managed batch GPU. The documented "one process per cleaning tier" trick and the 24-seed
sweeps are textbook **Batch array jobs** — a real capability RunPod does not offer natively.
This is a genuine, if narrow, advantage.

---

## Recorded correction

This section documents an error in the original analysis and what changed after
investigation. It is retained deliberately; the reasoning is more useful than a clean
narrative.

### What was originally claimed

That AWS GPU is "3.7x RunPod" based on `g5.xlarge` at $1.006/h against a RunPod A5000 at
$0.27/h, and that AWS was therefore poor value.

### The challenge

The user pushed back on two grounds: that a direct A5000-versus-4090-versus-AWS comparison
would not be sound, and that if AWS charges that much it is presumably providing something
better — and asked for this to be checked against live sources rather than asserted.

### What the research found

**On the silicon, the challenge does not hold — and the error favoured AWS.**

| | RTX A5000 (RunPod) | A10G (AWS g5) |
|---|---|---|
| Architecture | Ampere GA102 | Ampere |
| VRAM | 24 GB | 24 GB |
| Memory bandwidth | **768 GB/s** | 600 GB/s |

Same generation, same VRAM, and the A5000 carries **~28% more memory bandwidth** — the
binding constraint for inference. Cross-cloud data shows A5000 from $0.44/h against A10 from
$1.29/h. AWS is not charging a premium for superior hardware; if anything the original
comparison **flattered AWS**.

**On the capacity class, the challenge holds squarely.** From RunPod's own documentation:

| | Secure Cloud | Community Cloud |
|---|---|---|
| Infrastructure | T3/T4 data centres | **Peer-to-peer providers** |
| Reliability | High redundancy | **Variable** |
| Best for | Production, sensitive data | Cost-sensitive workloads |

The $0.27/h A5000 was almost certainly **Community Cloud** — peer-provided hardware, with
third-party reporting putting the cheapest tiers at **70–85% uptime**. Comparing that to
AWS's SLA-backed datacentre capacity is genuinely apples-to-oranges. It also reframes the
pod-restart pain in `project-findings.md` section 6: that was not bad luck, it was the tier
behaving as designed.

**On framing, the challenge holds completely.** Comparing on dollars-per-GPU-hour was the
wrong axis. AWS is not a GPU vendor being undercut on price; it is a platform whose GPU line
is incidental. The premium buys VPC, IAM, KMS, CloudTrail audit trails, S3 durability,
compliance attestations, and data-residency guarantees — none of which attach to the GPU.

### The corrected position

- AWS GPU remains a **no**, but because of **quota friction and the absence of the relevant
  hardware tier**, not because AWS overcharges for equivalent silicon.
- The comparison baseline was **unsound in AWS's favour on hardware** and **unsound against
  AWS on capacity class**. Both errors are now recorded.
- The right question is not "is the GPU worth 3x" but **"do I need the platform?"** —
  evaluated separately from compute, which relocates AWS's real case to storage, governance
  and delivery.

---

## Question 3 — What does it teach, and what does it cost?

### A prior question: is GPU still needed at all?

This deserves stating plainly, because it is easy to carry forward an assumption that no
longer holds.

- The **active** workload — DeepFilterNet enhancement — is CPU-bound and runs on six local
  threads.
- The workload that required a 4090 — VoxCPM2 LoRA voice cloning — was **superseded by the
  2026-07-10 voice pivot** (`docs/handoff-voice-pivot-2026-07-10.md`).
- The remaining GPU need is therefore **historical** plus **prospective** (Odia ASR), not
  current.

Any GPU decision taken today is a bet on the Odia bid being signed, not a response to
present demand.

### Sizing — the second correction

The original analysis anchored on 24 GB cards because that is what the *voice cloning* work
used. The prospective Odia workload is different: `ai4bharat/indic-conformer-600m-multilingual`
is a 600M-parameter Conformer needing roughly **3–5 GB VRAM**.

Anchoring on `g5.xlarge` was therefore a **~2.8x over-spec** on the Spot price. The correct
AWS tiers are `g4dn.xlarge` (T4) or `g6.xlarge` (L4). Full arithmetic is in
[05-odia-gpu-cost-model.md](05-odia-gpu-cost-model.md).

### Cost

At the corrected tier, and against the alternatives in
[04-gpu-provider-landscape.md](04-gpu-provider-landscape.md), AWS is roughly **1.5–2x** the
India-based options rather than the 3.7x originally stated — and its Spot escape hatch is
closed at the L4 tier.

### Teaching value

Genuine and non-trivial: **SageMaker** in particular is highly interview-legible, and GPU
Spot with checkpoint-and-resume is a real engineering skill. Batch array jobs transfer
directly.

The counterweight is that the same learning is available on the CPU side (category 1) at a
fraction of the cost, with no quota gate, and on a workload that is actually live.

---

## Verdict

| Dimension | Assessment |
|---|---|
| Necessity | **Currently none** — the live workload is CPU-bound; GPU need is prospective only |
| Price vs alternatives | 1.5–2x India-based providers at the correct tier |
| Spot relief | **Effectively unavailable at L4** (1.7% discount) |
| Access | **Blocked by default** — zero quota, multi-day approval |
| Teaching value | Real (SageMaker, array jobs) but duplicated more cheaply in category 1 |

**Recommendation:** do not move GPU work to AWS. If the SageMaker experience is wanted for
career reasons, take it as a deliberate, time-boxed learning exercise on a small workload —
and call it tuition, not architecture, per the ground rule in
[00-scope-and-method.md](00-scope-and-method.md) section 2.

**Corollary:** whatever is chosen, do not benchmark against $0.27/h. That figure comes from a
capacity tier in structural decline — see [04](04-gpu-provider-landscape.md).
