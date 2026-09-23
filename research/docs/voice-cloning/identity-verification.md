# GGSM Voice-Clone — Identity Verification & Robustness

**Question:** Have we *actually* solved the identity problem (does the clone sound like Gour Govinda
Swami), and is that conclusion **robust** — not an artifact of one metric?

**Status (2026-07-01):** *Strongly supported, with real caveats.* Two independent encoders + a
no-overfitting check + a "within-his-own-variation" argument all point to yes — but the test has
known limitations (below) that keep it from being an airtight proof. **Not yet fully airtight.**

---

## 1. What "identity" means here, and how we measure it
A voice has two layers (see the emotion doc): **identity** (timbre, pitch-home, accent — fixed by
the clone) and **performance/register** (prosody — re-rolled per seed). This document is about
**identity only**. Register/emotion (the "class-tone vs calm" problem) is a *separate* axis and is
tracked elsewhere.

**Metric:** cosine similarity of a **speaker embedding** (clone clip vs a centroid of his real clips).
Higher = more him-typical. The scale needs two anchors:
- **Floor** = what a non-him voice scores (here: architecture chance level — see caveat C2).
- **Ceiling** = what *his own* held-out real clips score vs a centroid of *other* real clips — "a
  clone cannot beat this; it's his own clip-to-clip variation."

---

## 2. The robustness design
A single metric (ECAPA) declaring "near ceiling" is not proof. So we score with **two encoders of
different architecture and lineage**, each in its own process (they conflict in one):

| Encoder | Family | Independence |
|---|---|---|
| **ECAPA-TDNN** (`speechbrain/spkrec-ecapa-voxceleb`) | attention + channel aggregation | primary |
| **d-vector GE2E** (Resemblyzer) | LSTM d-vector | different architecture & codebase |

Clone = **champion checkpoint c150**, on **UNSEEN** sentences (overfitting-clean) and the seen one
(overfitting-confounded, for contrast). Script: `scripts/verify_identity.py`.

---

## 3. Results (2026-07-01, local clone, reference `ggs_l1_0112`)

```
encoder          floor    clone UNSEEN    clone seen     his CEILING
ECAPA-TDNN       0.006    0.743±0.031    0.702±0.032    0.802±0.082
d-vector GE2E   -0.001    0.865±0.016    0.866±0.015    0.922±0.019

clone vs his own ceiling (UNSEEN):
  ECAPA     0.743 vs 0.802   gap +0.059   93% of the (chance→ceiling) span
  d-vector  0.865 vs 0.922   gap +0.057   94% of the span
  → two independent encoders AGREE (93% vs 94%).
```

**Absolute cosines differ across encoders (0.74 vs 0.87) — expected** (different embedding spaces).
What matters is the *relative position*, which agrees.

### What this establishes
1. **Not a single-metric artifact** — two unrelated models place the clone at the same relative spot.
2. **No overfitting** — clone scores the *same or higher* on unseen vs seen text on both encoders
   (ECAPA 0.743 unseen > 0.702 seen). A memorized clone shows the opposite.
3. **Within his own variation** — the ECAPA ceiling is 0.802 **±0.082**; his real clips span ~0.72–0.88.
   The clone (0.743, tight ±0.031) sits inside that band and is *more consistent than he is*.
4. **Best reference nearly closes the gap** — a pod run hit **ECAPA 0.806** with reference
   `ggs_l1_0081` (at his ceiling). Most of the residual was a *reference-choice* artifact, not a wall.
   *(Caveat: those clips were on a since-terminated pod; the 0.806 is trusted from the run log, not
   re-verified locally.)*

---

## 4. Limitations — why this is NOT yet a perfect proof
Ranked by how much each threatens the conclusion.

- **C1 — Shared domain prior (high).** Both encoders are **VoxCeleb / English-celebrity** trained.
  Neither has seen Indian-accented, Bengali-inflected devotional speech. They are independent in
  *architecture* but share a *domain*; a systematic bias against his voice type would fool both.
- **C2 — Chance floor, not a real-speaker floor (high).** The floor is random vectors (≈0). A real
  different speaker (esp. another Indian male) would score ~0.3–0.5. So "93% of the span" is
  **optimistic**; against a realistic floor the band is narrower and the percentage lower. The raw
  gap (+0.057) and the "within-his-variation" argument are the more honest framings.
- **C3 — Single-lecture circularity (high).** Centroid *and* ceiling are both lecture-1 clips, and
  the clone was trained on lecture 1 (and prompted with a lecture-1 reference). We proved "matches
  lecture-1 GGSM," not "matches GGSM across days/recordings." Cross-lecture identity is untested.
- **C4 — Small n / noisy ceiling (medium).** 10–20 clips; ECAPA ceiling ±0.082 is fuzzy.
  Leave-one-out CV over all 140 would firm it up.
- **C5 — 16 kHz only (medium).** Both encoders run at 16k; the clone's 48 kHz super-res detail (which
  the ear hears) is never scored.
- **C6 — No controlled human ABX (medium).** The final judge of "is it him" is a devotee's ear under
  blind conditions. We only have an informal earlier "recognizably him." Metrics can agree yet both
  drift from perception.
- **C7 — Cosine-to-centroid, not EER (low).** A verification-EER protocol (him-vs-imposters) is more
  standard than distance-to-average.

---

## 5. What a fully-rigorous test would add
- **Real different-speaker floor** — ideally same demographic (Indian male). Cheapest high-impact fix.
- **Cross-lecture centroid** — score the clone against a centroid built from a *different* lecture
  (depends on the lecture-selection / data work in flight). Kills the circularity (C3).
- **Leave-one-out CV over all 140** for a tighter ceiling (C4).
- **A third check from a different domain** — a speaker model trained on diverse/Indian speech, or a
  perceptual measure.
- **Blind human ABX with devotees** on the best (`0081`) clips — the orthogonal ground truth (C6).

---

## 6. Current verdict
Identity is **very likely solved** — the convergent evidence is real and points one way:
two architectures agree, no overfitting, the clone sits inside his own clip-to-clip spread, and the
best reference reaches his ceiling. But the claim is **well-supported, not airtight**: it rests on
same-domain English metrics, a chance floor, and a single lecture. Treat identity as **provisionally
locked**, with the real-speaker floor + cross-lecture centroid + human ABX as the seals that would
make it final.

---

## 7. Reproduce
```
.venv/Scripts/python.exe scripts/verify_identity.py --enc ecapa
.venv/Scripts/python.exe scripts/verify_identity.py --enc dvector
.venv/Scripts/python.exe scripts/verify_identity.py --enc report
```
Deps added this session: `resemblyzer` + `webrtcvad-wheels` (the d-vector encoder). ECAPA cached in
`.venv/spkrec`. Raw per-encoder results: `data/out/lecture1/idcheck_{ecapa,dvector}.json`.
