# Voice dissimilarity gate — first measurement (2026-07-20)

> **Scope clarification (2026-09-02):** This is historical gate evidence for the
> active future **non-SSGGSM EN/HI narration lane**. It must not approve, reject or
> select takes in the authorized SSGGSM/Odia/diary lane, whose goal is faithful
> SSGGSM likeness and whose release authority is qualified Odia listening review.
> See [ADR-0007](decisions/0007-two-policy-isolated-narration-lanes.md).

**Why this exists.** The pivot (`handoff-voice-pivot-2026-07-10.md`) bars GGSM's voice from output.
Mukul's constraint: a synthetic base voice we generate is usable, *but we must check it doesn't sound
like him*. That check can't be a threshold we invent — this doc measures it.

**The sign flip.** `verify_identity.py` asked "is the clone close enough to him?" (maximize cosine).
This asks the opposite: a candidate narration voice must sit **far below** his ceiling on **two
independent encoders**. Same machinery, opposite goal. The metric declared obsolete by the pivot
becomes the safety gate. Script: `scripts/hi/voice_gate.py`.

## The tension to keep in view
Mukul's brief — **male, mature, sweet, prayerful** — is the closest possible demographic *and*
register match to GGSM. Speaker-similarity and "fits the brief" load onto the same axis, so any
voice that satisfies the brief will trend *toward* him by construction. The gate is therefore not a
formality; it is the thing that decides which good-sounding voices are actually usable.

## Design (and what it fixes)
- **Centroid** = his real Hindi clips, lectures **01+02** (77 clips, 4–12 s).
- **Ceiling** = his clips from lectures **03+04** (48 clips) vs that centroid — *him on a different
  day/recording*. Different lectures for centroid vs ceiling **kills caveat C3** (single-lecture
  circularity) from `identity-verification.md`, which the original ceiling never did.
- **Hindi**, not the English lecture-1 centroid in `ecapa_score.py` — candidates get scored in the
  language they'll be judged in, avoiding cross-language embedding drift.
- Two encoders, separate processes (they conflict in one): ECAPA-TDNN and d-vector GE2E.

## Results

```
encoder          chance floor    HIS ceiling (cross-lecture)
ECAPA-TDNN              0.007                0.694 ± 0.111
d-vector GE2E          -0.003                0.811 ± 0.038

candidate                  ECAPA    d-vector    worst margin below ceiling
VoxCPM2 base (en)          0.065       0.528              +0.284
VoxCPM2 base (hi)          0.102       0.551              +0.261
```

Note the honest cross-lecture ECAPA ceiling is **0.694**, well below the **0.802** reported in
`identity-verification.md` — that older number was inflated by same-lecture circularity. Expected,
and it is the number to use going forward.

## Verdict: base voice provisionally clears — but the two encoders differ in *degree*

- **ECAPA: emphatic pass.** base_hi at **0.102** against a 0.694 ceiling, sitting essentially on the
  chance floor (0.007) — ~15% of the floor→ceiling span. Reads as a stranger.
- **d-vector: directionally agrees, but far less emphatic.** 0.551 against a 0.811 ceiling is
  **~68% of the span**. In isolation that is uncomfortably close.

**Do not average these into a pass.** The divergence is most likely d-vector's known upward
compression — GE2E d-vectors return high cosine for almost any same-gender speech — but "most
likely" is not measured. This is **caveat C2 biting exactly where it matters**: with only a *chance*
floor, we cannot tell whether 0.551 means "different person" or "somewhat similar," because we have
never established what a genuinely different Indian male speaker scores on this encoder.

**Status: provisionally clear, not certified.** ECAPA's result is strong enough to keep the base
voice as a live candidate. It is not strong enough to close the question.

## Secondary caveat
Both base samples are short — **2.7 s (en) and 3.4 s (hi)**. Speaker embeddings get noisy under
~5 s. Re-score once we have ≥10 s of the chosen voice.

## What would certify it
1. **Real-speaker floor (blocking).** Score several known non-GGSM Indian male devotional speakers
   against his centroid. This converts both encoders from "relative evidence" to a calibrated
   decision band, and is the single highest-value missing measurement. Local `kirtana_samples/` is
   *not* a safe source — it is music and may contain him.
2. **Longer candidate samples** (≥10 s) to de-noise the embeddings.
3. **Blind human check** — caveat C6. Metrics can agree and still drift from perception; the final
   question ("would a devotee hear him?") is perceptual and no cosine settles it.

## Reproduce
```
.venv/Scripts/python.exe scripts/hi/voice_gate.py --enc ecapa
.venv/Scripts/python.exe scripts/hi/voice_gate.py --enc dvector
.venv/Scripts/python.exe scripts/hi/voice_gate.py --enc report
# add bake-off candidates:
.venv/Scripts/python.exe scripts/hi/voice_gate.py --enc ecapa --cand "parler A=data/hi/bakeoff/a.wav"
```
Raw: `data/hi/voice_gate/gate_{ecapa,dvector}.json`.
