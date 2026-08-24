# 02 — Category 1: Local CPU Compute

**Date:** 2026-08-24 · **Verdict:** qualified yes — strong on learning value, negligible on cost,
weak on necessity.

---

## The workload

DeepFilterNet3 rendering plus all scoring, metrics and gallery generation, currently running
on a 6-thread Windows machine with no GPU.

Measured characteristics, from the project's own job manifests:

| Metric | Value |
|---|---|
| End-to-end real-time factor | **0.280761** |
| Model-inference-only real-time factor | **0.09642** |
| Runtime | `torch 2.0.1+cpu`, 6 threads, `cuda_available: false` |
| Benchmark basis | 57.46 s audio in 16.13 s wall |

The workload has three properties that determine everything below: it is **CPU-bound**, it is
**embarrassingly parallel by chunk**, and it is **already content-addressed and resumable**.

---

## Question 1 — What is the direct AWS equivalent?

Three layers, and the distinction is not cosmetic:

| Layer | Service | Character |
|---|---|---|
| Raw instance | **EC2** (`c7i`, `c7g`) | A rented Linux box. Closest to current practice. |
| Managed batch | **AWS Batch** | A job queue that provisions EC2 or Fargate per job, runs a container, tears it down. |
| Serverless container | **Fargate** | No instance management. Capped at 16 vCPU / 120 GB. No GPU. |

**The idiomatic answer for this workload is AWS Batch on EC2 Spot, with the container image
in ECR and audio in S3.** The renders are queued, independent, restartable jobs — which is
precisely Batch's design centre.

Fargate is the simpler option and would work, but it forfeits Spot pricing for this shape of
job and adds nothing the workload needs.

---

## Question 2 — Better, or just different?

### For a single lecture: just different, and arguably worse

There is a working local machine. The render takes about 30 minutes. Moving it to AWS adds a
container build, an S3 round-trip, IAM roles, and an entirely new failure surface. **Nothing
becomes faster.**

### It becomes genuinely better under three conditions

1. **Fan-out.** Twenty lectures locally is twenty sequential 30-minute renders — about ten
   hours. On Batch it is twenty concurrent jobs, still about thirty minutes. This is the
   single strongest operational argument.
2. **Unattended operation.** The laptop stops being the render farm. For a machine that is
   also the development environment, this is worth more than it sounds.
3. **Reproducibility.** `cloud/pod_setup.sh` resolves a three-way dependency deadlock by
   `sed`-patching a library's source. A pinned container image eliminates that entire class
   of problem permanently.

### The honest qualification

Point 3 is the strongest argument, and **it is a Docker win, not an AWS win.** The same
benefit is available from Docker on any host, including the existing local machine and any
GPU provider. This folder should not bank a containerisation benefit as an AWS benefit.

What AWS adds *beyond* Docker is the managed queue, the Spot market, and the surrounding
IAM/S3/CloudWatch integration.

---

## Question 3 — What does it teach, and what does it cost?

### Cost — computed from measured figures, not estimated

Rupanuga source duration is 6,373.624125 s (1.77 h). At the measured end-to-end RTF of 0.28
that is ~1,784 s of compute, or about **0.5 compute-hours** — which independently matches the
job manifest's own recorded delivery estimate of 1,200–1,800 s.

| Instance | vCPU | Spot rate | Cost per 1h46m lecture |
|---|---|---|---|
| `c7g.xlarge` (Graviton) | 4 | $0.065/h | **~$0.05** |
| `c7i.xlarge` | 4 | $0.073/h | **~$0.05** |
| `c7g.2xlarge` | 8 | $0.127/h | **~$0.06** |
| `c7i.2xlarge` | 8 | $0.168/h | **~$0.08** |
| `c7i.2xlarge` On-Demand | 8 | $0.357/h | ~$0.18 |

**Enhancement compute costs under ten cents per lecture.** Extended to the full 1,952-hour
Odia corpus at the same RTF — about 547 compute-hours — the total is **$69 on `c7g.2xlarge`
Spot, or $92 on `c7i.2xlarge` Spot.**

Cost is not a constraint anywhere in this category. It should not be used as an argument in
either direction.

### A note on instance sizing

An earlier draft of this analysis anchored on 8-vCPU instances. That was over-specced: the
local workload uses 6 threads, and 4-vCPU instances are the correct starting point.

Note also that **$/vCPU-hour is nearly flat across sizes** ($0.016/vCPU-h for both
`c7g.xlarge` and `c7g.2xlarge` on Spot). For an embarrassingly parallel workload, instance
size therefore selects **wall-clock time, not total cost**. The meaningful lever is not size
but **architecture**: Graviton at $0.065 versus Intel at $0.073 on the 4-vCPU tier, widening
to $0.127 versus $0.168 at 8 vCPU — roughly a 24% saving.

### Two caveats that must not be lost

1. **Graviton is unverified for DeepFilterNet.** DFN has a Rust core plus PyTorch; ARM64
   builds exist for both, but DFN3 has **not** been confirmed working on `c7g` in this
   project. The 24% saving must not be budgeted until tested.
2. **The real cost is not compute, it is the 19 GB working set.** Compute is $0.08 per
   lecture; storing and moving the intermediate cache is not. This is where category 1
   collides with categories 5 and 12, and it is the genuinely difficult design question —
   ephemeral instance storage is cheap but forfeits resumability across Spot interruption,
   while durable storage preserves resumability and costs real money.

### Teaching value — the highest in the project

ECR, Batch job queues and compute environments, Spot interruption handling, S3 I/O patterns,
IAM task roles, CloudWatch Logs.

Given the stated learning driver, **this is the highest-value single unit in the entire
evaluation.** It is the canonical "containerised batch workload on AWS" pattern, it is
directly interview-legible, and it costs almost nothing to run while learning it.

---

## Verdict

| Dimension | Assessment |
|---|---|
| Necessity | Low — the local machine works |
| Cost | Negligible (under $0.10/lecture; ~$70–92 for the whole Odia corpus) |
| Operational gain | Real but conditional on fan-out and unattended running |
| Teaching value | **Highest in the project** |
| Honest caveat | The biggest single win (reproducibility) is Docker's, not AWS's |

**Recommendation:** proceed here first if any AWS work is undertaken. It is cheap, safe,
genuinely useful at fan-out, and teaches the most transferable pattern available in this
codebase.
