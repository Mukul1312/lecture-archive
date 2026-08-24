# 00 — Scope, Driver, and Method

**Date:** 2026-08-24 · **Status:** settled; governs the rest of the folder.

---

## 1. Why this evaluation exists

This project has never chosen an infrastructure platform. It accreted one.

Work has been done on a local Windows machine and across **four separate cloud GPU
providers** — RunPod, Lightning AI, Google Colab, and Kaggle — each reached for when a
particular task needed a GPU, each with its own authentication, environment bootstrap, and
storage model. Alongside that sit a Vercel static-hosting footprint, a HuggingFace model
dependency, GitHub used as a bulk transfer mechanism, and a filesystem used as a database.

None of this was a mistake at the time; each choice was locally reasonable. But the result
is twelve distinct categories of infrastructure resource, no single platform, and no
deliberate decision behind any of it.

The question this folder answers is narrow and specific: **for each category, what would
AWS replace, and would that replacement actually be better?**

---

## 2. The driver — and why it changes every verdict

The user was asked directly what motivates looking at AWS, from four options: scale for the
Odia bid, durability of the heritage archive, learning AWS for career value, or escaping
cost/operational pain with RunPod.

**The answer was: learning AWS / career.**

This is load-bearing and must not be quietly forgotten later. It means:

- **Cheapest is not the goal.** A more expensive option that teaches a transferable,
  interview-legible skill can be the right answer.
- **Idiomatic beats clever.** The standard AWS way of doing something is worth more than a
  minimal-cost hack, because the standard way is what transfers to a job.
- **Breadth has value.** Touching twelve services shallowly may be worth more than
  optimising one deeply.
- **But tuition must be named as tuition.** Where AWS is genuinely worse on the merits, this
  folder says so plainly and lets the user pay the learning premium knowingly, rather than
  dressing a weak technical case in false justification.

That last point is the discipline that keeps this document honest.

### What was explicitly *not* the driver

Recording these matters, because each would have produced a different evaluation:

- **Not cost.** No budget pressure was cited.
- **Not scale.** The Odia bid is prospective, not signed.
- **Not durability alone.** Though the archive is irreplaceable, that was not the stated motive.
- **Not a client requirement.** No third party is demanding AWS.

---

## 3. Method — the twelve categories

An early proposal to organise the discussion by *workload* (enhancement, transcription,
cloning, archive, delivery) was **rejected by the user**, on the grounds that this one
project already does many things and the resource types come first.

That was the right call. The workload framing would have forced premature prioritisation and
obscured the fact that several resource types are shared across all workloads. The inventory
framing surfaces the true footprint.

The agreed method is therefore: **enumerate the resource types the project actually
consumes, then evaluate each against AWS in turn.**

The twelve categories are established in [01-resource-inventory.md](01-resource-inventory.md).

## 4. The three questions

For each category, the same three questions are asked, in this order:

1. **What is the direct AWS equivalent?**
   Name the service or services, and distinguish between layers where the distinction
   matters (e.g. EC2 vs Batch vs Fargate are three different answers to "compute").

2. **Is that equivalent actually better here, or just different?**
   This is the question that gives the document its value. Several categories are a lateral
   move dressed as an upgrade. Where that is true, it is stated as "just different" — and
   where AWS is genuinely *worse*, that is stated too.

3. **What does it teach, and what does it cost?**
   Teaching value is a first-class criterion given the driver. Cost is computed from the
   project's own measured figures wherever they exist, rather than estimated.

---

## 5. Ground rules

These were established during the discussion and are binding on the rest of the folder.

### 5.1 Source-verified over remembered

External facts — prices, quotas, service limits, hardware specifications — are retrieved
from live sources and cited, not quoted from memory. Where a number is recalled rather than
retrieved, it is labelled as such. All retrieved values are collected with their sources in
[evidence/price-snapshot-2026-08-24.md](evidence/price-snapshot-2026-08-24.md).

### 5.2 Project measurements beat estimates

This repository contains unusually good instrumentation: recorded real-time factors,
benchmark blocks in job manifests, a measured corpus inventory. Where such a number exists,
the cost model uses arithmetic on it rather than an industry estimate. Where no measurement
exists, the gap is stated explicitly and the figure is bracketed rather than guessed.

### 5.3 Corrections are recorded, not silently patched

Where an earlier claim in the discussion was wrong or poorly framed, the correction is
written into the relevant document alongside what prompted it. The GPU analysis in
[03](03-categories-02-03-gpu-compute.md) contains one such record. The purpose is to make the
reasoning auditable, not to keep a tidy narrative.

### 5.4 The approved architecture is not overridden casually

The repository already contains an approved design decision — a local-first modular monolith
with SQLite, in
`docs/superpowers/specs/2026-08-22-heritage-production-ddd-hexagonal-design.md`. Moving state
to AWS would contradict it. This folder treats that as a decision requiring a conscious
reversal, not something to drift past.

---

## 6. Scope boundaries

**In scope:** all twelve resource categories; AWS service mapping; honest comparison against
current and alternative providers; cost arithmetic; teaching value; operational risk.

**Out of scope for now:**

- Implementation, provisioning, IaC, or any account action.
- Migration sequencing (deferred until the category analysis is complete).
- The heritage-production DDD implementation, which proceeds independently.
- Any change to the active `feature/youtube-lecture-enhancement` work, which the user is
  progressing in parallel.

---

## 7. A finding that frames everything: this is greenfield

A scoped search across the project's own code and documentation for `AWS`, `Amazon`, `S3`,
`EC2`, `SageMaker`, `Bedrock`, `Glacier` and `CloudFront` returned **no genuine hits**. The
only two matches were the ordinary English word "transcribe" in the Hindi pipeline
documentation, not Amazon Transcribe.

There are therefore no prior AWS experiments, no orphaned resources, no half-made decisions,
and no legacy to reconcile. Whatever is decided here is decided from a clean position — which
is a significantly more comfortable place to design from than the usual partial migration.
