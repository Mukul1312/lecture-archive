# Corpus Ledger — domain design for the five archive programmes

Date: 2026-08-26

Status: Proposed. Supersedes the *build order* of
`plans/2026-08-24-heritage-production-first-slice.md` (Tasks 7–11) and narrows
the scope of `specs/2026-08-22-heritage-production-ddd-hexagonal-design.md`.
It does **not** supersede that design's domain modelling, which remains correct
for the subdomain it describes.

---

## 1. Why this document exists

The 2026-08-22 design modelled one bounded context — Heritage Production — for
one deliverable: the August 21 SSGGSM transcript. Six of its eleven tasks were
implemented between 2026-08-24 and 2026-08-26.

Between those two dates the actual programme became clear, and it is five
concurrent services rather than one deliverable. This document re-does the
*strategic* design against that wider reality, keeps what survives, and states
plainly what does not.

It also records a second finding: the pace problem in Tasks 1–6 was not caused
by DDD or by TDD. It was caused by verification disciplines added on top of
both, which the governing skill does not mandate. That is corrected here.

---

## 2. The five programmes

All five are ongoing services, not projects with completion dates. They are of
**equal priority**. Where cadence differs, that is a fact about demand, not a
ranking.

| # | Programme | Recipient | Cadence as of 2026-08-26 |
|---|---|---|---|
| 1 | ~1,800 h Odia lectures → Odia transcript **and** English translation | HH Haladhara Swami | **Daily.** Sarvam currently used as a second option |
| 2 | Enhance all Odia lecture audio for listenability | HH Haladhara Swami | On demand, deferrable. Requests are sometimes postponed. An emergency flow exists |
| 3 | All SSGGSM lectures → English transcript | — | **Daily.** A flow exists |
| 4 | Enhance all SSGGSM lecture audio | — | Not yet requested. Expected |
| 5 | Voice clone of a devotee other than SSGGSM, for EN/HI narration | — | Expected within 1–2 months |

Two of the five are daily production **today**. One has a soft deadline of
1–2 months. Two are latent. Nothing here is speculative.

### 2.1 Why the model must not encode that table

The cadence column changes month to month. A model shaped around it would be
refitted every time demand shifts, and each refitting is a migration of
accumulated evidence. The design below deliberately treats all five
symmetrically; **only the build order is sequential, and only because work
happens in some order.**

---

## 3. Strategic analysis: why five programmes are not five domains

### 3.1 The test the governing skill actually prescribes

`.agents/skills/clean-ddd-hexagonal/references/DDD-STRATEGIC.md`:

- line 53 — *"Find boundaries — Where language changes = bounded context boundary"*
- line 116 — *"Polysemy (same word, different meanings) across departments is
  natural, not a problem. On what drives context boundaries: 'Usually the
  dominant one is human culture, since models act as Ubiquitous Language, you
  need a different model when the language changes.'"* — Martin Fowler

The criterion is **linguistic**, not organisational. "Is this a separate
programme?" is not the question. "Does the language change?" is.

### 3.2 Applying it

| Term | 1 Odia txt | 2 Odia enh | 3 GGSM txt | 4 GGSM enh | 5 Narration |
|---|---|---|---|---|---|
| lecture | same | same | same | same | same |
| source recording | same | same | same | same | same |
| derived from | same | same | same | same | same |
| judgement, verdict | same | same | same | same | same |
| **identity** | hash | hash | hash | hash | **vocal resemblance** |

The language is identical across four programmes. It changes in exactly one
place, and the repository already contains the collision:

- `scripts/youtube_enhance/gates.py` — `identity_verdict(natural_anchor_mean,
  candidate_mean) -> bool` means *measured vocal resemblance*.
- `scripts/ggsm_transcription/store.py` — `.identity.lock` means *hash-bound
  job identity*.

Same word. Two incompatible meanings. Same repository. **That is a bounded
context boundary by the skill's own criterion**, and it is the only one
present.

### 3.3 In DDD vocabulary

The five programmes are **subdomains**, not bounded contexts. The skill treats
these as different concepts (DDD-STRATEGIC § Subdomains, line 190).

- **Core subdomain** — archive provenance: which bytes came from which bytes,
  produced by what, and what a human said about them.
- **Supporting subdomains** — transcription, translation, enhancement,
  narration.

Subdomains describe what the work *is*. Bounded contexts describe where a model
stays coherent. Several subdomains legitimately share one context when they
share a language, and here four of five do.

### 3.4 The decisive practical argument

**The same physical lecture flows through several programmes.** An SSGGSM
lecture is enhanced (#4) *and* transcribed (#3). An Odia lecture is enhanced
(#2), transcribed and translated (#1).

If each programme were its own bounded context, "lecture" would be modelled
once per context, with anti-corruption layers between them — and each context
would own its own notion of identity.

**That experiment has already been run in this repository, and it failed.**
See §4.1. The duplicate-store bug *is* what "one domain per programme" looks
like when it arises organically. Formalising it would entrench the defect.

---

## 4. Verified evidence

Everything in this section was verified directly against the repository on
2026-08-26. Nothing here is inferred.

### 4.1 The two content stores cannot recognise each other

| File | Line(s) | Behaviour |
|---|---|---|
| `scripts/ggsm_transcription/store.py` | 88 | `digest = source_sha256.lower()` |
| `scripts/youtube_enhance/workflow_state.py` | 211, 230, 281, 427 | `.hexdigest().upper()` |

The transcription store lowercases digests; the enhancement store uppercases
them. For the same lecture, the same bytes, the two stores hold **different
string identities and cannot cross-reference at all.**

This is precisely the failure the 2026-08-22 design § 2 was written to prevent
— *"pipelines identify data by filename, numeric suffix, or array index …
rebuilding a manifest or clip directory can therefore attach old evidence to
different bytes"* — reproduced one level up, at the identity string itself.

### 4.2 The DDD work and the transcription pipeline have never coexisted

| Package | on `main` | on `work/heritage-production-first-slice` |
|---|---|---|
| `scripts/ggsm_transcription` | ✅ | ❌ |
| `scripts/youtube_enhance` | ✅ | ✅ |
| `src/heritage_production` | ❌ | ✅ |

`heritage_production` cannot import, and cannot be imported by, the
transcription pipeline as things stand. Any plan that puts a canonical store
inside that package, on that branch, produces a canonical store with no users.

`src/heritage_production/presentation/cli/main.py` is **62 lines**: eighteen
subcommand groups, every one unimplemented, `main()` returning 0.

Measured on the branch: `domain/` is 11,602 lines and
`tests/heritage_production/` is 20,039 lines. None of it currently runs against
either working pipeline.

### 4.3 The cache discipline is on the wrong code

| Code | Rents GPUs? | How it decides to skip work |
|---|---|---|
| `scripts/youtube_enhance/dfn.py` | No — CPU subprocess | `cache_key(...)`, `sha256_file(artifact)`, re-hashes the artifact before accepting a hit, `REQUIRED_RENDER_VERSION_KEYS` covering deepfilternet, model, python, numpy, soundfile, ffmpeg |
| `cloud/asr_ab.py`, `cloud/content_triage.py`, `cloud/denoise_postproc.py` | **Yes** | `if d.exists()`, `if work.exists() and work.stat().st_mtime < mp3.stat().st_mtime` |

The rigorous content-addressed cache guards work that is free. The code that
rents GPUs decides by file existence and modification time.

### 4.4 Model choice for Odia is consequential, not a preference

`docs/odia-transcription-bid-estimate-2026-07-25.md` line 161, on *degraded
field* Odia:

| System | WER |
|---|---|
| Azure | 35.1% |
| Sarvam | 35.8% |
| **Whisper** | **125.6%** |

Whisper is not merely worse on degraded Odia; it is unusable. Which model
produced a given Odia transcript is therefore a first-order fact about that
transcript, and it is currently recorded nowhere.

`cloud/pod_asr.sh` pins `onnxruntime==1.20.1` but loads
`ai4bharat/indic-conformer-600m-multilingual` with **no revision**. The
environment is pinned harder than the model.

### 4.5 Compute is not the dominant cost

- `docs/odia-transcription-bid-estimate-2026-07-25.md` line 49 — *"Compute is a
  rounding error. GPU + API + LLM for the entire 1,952-hour corpus is ~$6k —
  about 1% of [the bid]."*
- `docs/narration-cost-analysis-2026-07-20.md` line 11 — *"This decision should
  not be made on price. The amounts are too small to matter."*

**One asymmetry must be stated, because it is easy to misread the above.**
The ~1% figure concerns the *paid* Odia work. Programmes 2–5 carry no revenue;
for those, compute is 100% of the cost and comes from the steward's own
pocket. The ledger's value proposition is therefore not *"it makes the paid
work affordable"* — it is *"it stops the four acts of seva being paid for
twice."*

### 4.6 Scale of the existing code

| Location | Files | Lines |
|---|---|---|
| `scripts/` | 135 | 26,585 |
| `cloud/` | 25 | 3,056 |
| `colab/` | 1 | 986 |

`data/lecture_triage.tsv` holds 113 rows, keyed by an `aid` column.

---

## 5. The domain map

Two bounded contexts.

### 5.1 Context A — Corpus Ledger

**Purpose.** Hold the one fact no individual script can: for every item in the
archive, which output bytes came from which input bytes, produced by exactly
what tool, model and configuration, and what a human said about them.

It computes nothing. It transcribes nothing. It enhances nothing. Every
existing script keeps doing its job and gains exactly two obligations: **ask
before computing, register after.**

#### Aggregate 1 — `ArchiveItem`

Identity **is** the sha256 of the original source bytes.

Invariants:

1. Titles, URLs, `aid` row numbers, filenames and array positions are
   **labels**, never identity. Relabelling must never re-point evidence.
2. The authoritative duration is the **decoder-reported PCM frame count** at a
   stated sample rate. The container's reported duration is a *claim*; a
   divergence is recorded as a durable fact and never silently reconciled.
   (An archived Prabhupada `job.json` already shows reported 2755.063 s against
   decoded 2749.632 s with a malformed terminal packet. This is live, not
   hypothetical, and it is the same class of defect as the timeline-shortening
   chunk-join bug in the old `enhance_part.py`.)
3. At most one artifact per **deliverable kind** — native transcript, English
   translation, enhanced master, narration — may be *delivered* at a time.
   Replacing one records the supersession.
4. Never deleted. Superseded.

#### Aggregate 2 — `DerivedArtifact`

Identity **is** the sha256 of the produced bytes.

Invariants:

1. Every artifact carries exactly one **run key** — the canonical hash of
   (sorted input digests, tool id, **pinned model revision**, config digest,
   environment-lock digest).
2. Registering *different bytes* under an existing run key raises a
   nondeterminism error. Never an overwrite; never "take the newer file". This
   is the rule that makes `has` safe to trust.
3. An artifact whose declared input digests are not already in the ledger
   cannot be registered. No orphan outputs.
4. Terminal state is exactly one of `SUCCEEDED` (with an output digest),
   `FAILED` (with a reason), `ABANDONED`. **`SUCCEEDED` requires the output
   digest to exist**, so a half-written file is structurally incapable of being
   recorded as a result.
5. Two lease columns — `claimed_by`, `lease_expires_at`. Lease expiry, worker
   loss or spot preemption returns the unit to `UNCLAIMED` — never to `FAILED`,
   never to `SUCCEEDED`. This earns a rule not because it saves money but
   because a preempted, half-written output recorded as complete is then
   reviewed as complete.
6. **Compute evidence** — `wall_seconds`, `gpu_seconds`, device class, input
   audio seconds — is required, or explicitly `cost-unknown`. Never silently
   zero, because a zero understates a sweep.

#### Aggregate 3 — `Judgement`

Append-only.

Invariants:

1. A judgement names the **exact artifact digest** it was made against, and the
   **exact anchor** — byte, character or time span — within it.
2. Immutable. A change of mind is a new judgement that supersedes.
3. **Staleness is computed on read, never stored.** A judgement is stale when
   the digest it judged is no longer the delivered digest for that item and
   kind. There is no settable status field, so a derived answer cannot drift
   and no discipline is required from the steward to keep it true.
4. A judgement survives deletion of the artifact it judged. Knowing that a
   human once vetoed bytes you no longer hold is itself the finding.
5. It carries `competences_held` for the judge, and the competence the question
   required. The steward cannot judge Odia intelligibility; an Odia approval
   signed by him is a materially different claim from one signed by an Odia
   listener, and nothing anywhere records that difference today.
6. **Triage is a judgement kind**, with verdict ∈ {`LEAVE_UNTOUCHED`, `TREAT`,
   `DIGITISE_FIRST`, `OUT_OF_SCOPE`}, citing the diagnostics artifact digest
   that measured it. One scheduling rule follows: **no enhancement run may be
   registered against an item without a current `TREAT` verdict.**
   `run_diagnostics` in `youtube_enhance/diagnostics.py` is pure CPU — cheap
   measurement placed in front of expensive processing.

#### Read models — not aggregates

`has`, `plan`, `coverage`, `spend`.

- `measured_rtf` over a recipe's `SUCCEEDED` runs is **always reported with its
  sample size**, and below three completed runs it returns the literal word
  `unmeasured` and refuses to emit a number. A confident wrong estimate is
  worse than none when about to rent a pod.
  (`docs/narration-cost-analysis-2026-07-20.md` carries an *"Unverified figure
  — assumed, not measured"* warning on the line item that dominates its own
  total. This invariant is the antidote.)
- `coverage` is **derived from judgement rows** — judged seconds over total
  decoded seconds, broken out by competence. No sampling plan, no pre-declared
  strata, no ceremony before listening. Derive, do not declare.

#### `ModelCard` — a data row, not an aggregate, not a policy engine

Three fields with teeth, enforced as preflight assertions at recipe
construction:

1. **Pinned repo + revision.** A floating tag or `latest` is not an identity.
2. **Licence recorded explicitly**, never inferred from silence.
3. **Declared language set taken from the model's own tokenizer or label set**,
   never from a README. Whisper has no `or` token — a checkable fact, not an
   opinion, and the cheapest available guard against fluent, confident garbage
   in a language the steward cannot read. See § 4.4.

Explicitly **not** a policy-version aggregate with an authorization engine. A
schedule-time gate standing between the steward and twenty minutes of
experimental audio is a rule that will be routed around, and a rule routed
around is worse than no rule.

### 5.2 Context B — Narrator Voice

Serves programme 5. It is a genuine second context by § 3.2's evidence, not a
taxonomy preference.

#### `Narrator`

Identity is an opaque id, never a name. Holds a **permission scope** — which
donor recordings, for what output, until when — and a **must-not-resemble set**
which contains SSGGSM by standing instruction from the 2026-07-10 pivot.
Revoking a scope blocks future publishable takes and never deletes past
evidence.

#### `NarrationTake`

Identity is the sha256 of the produced audio, so **the same bytes are one
object in both contexts**. Binds script-text digest, narrator, reference-audio
digest, model revision, seed.

Publishable only when **both** gates were measured **on the exact bytes being
published**: similarity-to-donor at or above floor, **and** dissimilarity from
every must-not-resemble voice at or above floor. A missing, skipped or
unmeasured gate is a failure, never a pass.

**Why it earns its own context.** A rights or resemblance failure is
unrecoverable after publication, where an accuracy failure is re-issuable. And
it converts a standing instruction the steward must otherwise remember across
months into an invariant that fails closed when he forgets. Roughly 150 lines
and a second table.

---

## 6. The shared kernel

Five value types, ~150–200 lines:

1. **`ContentDigest`** — sha256, **lowercase** hex. Pick one case and enforce
   it. (See § 4.1 for what happens otherwise.)
2. **`ArtifactRef`** — digest + byte size + media type.
3. **`RunKey`** — the one canonical-JSON hash.
4. **`Actor` + `Competence`.**
5. A UTC timestamp type.

`src/heritage_production/domain/shared/digests.py` and `ids.py` already contain
most of this and can be kept nearly as-is.

**Why it must be shared and not duplicated.** A `NarrationTake` exists
simultaneously as a `DerivedArtifact` — its script text, reference audio, model
revision and seed must be auditable like any other derivation. If the two
contexts computed digests differently they could disagree about whether they
are discussing the same bytes, which is the precise failure the ledger exists
to prevent, reintroduced at the only seam that exists.

`Competence` belongs in the kernel rather than in one context, because **both
contexts must be able to refuse work.**

### 6.1 Canonical-JSON implementations currently in the repository

Four, at least:

| Location | Function |
|---|---|
| `scripts/youtube_enhance/manifest.py` | `canonical_json`, `cache_key(stage, inputs, params, versions)` — the right primitive |
| `src/heritage_production/domain/shared/canonical.py` | independent RFC 8785 implementation, 158 lines |
| `scripts/ggsm_transcription/review.py` | `_json_text` |
| `scripts/youtube_enhance/gates.py` | `canonical_evidence_hash` |

The ledger must **reduce** this number, not add a fifth. See § 11.

### 6.2 Explicitly not in the kernel

`src/heritage_production/domain/shared/trust.py` (377 lines) —
`ActorCredentialRef`, `AssuranceLevel`, `CredentialVerificationMethod`,
`RoleCode`, `GateCode`, `SignOffTargetKind`, `ManifestMemberRole`.

A credential-assurance ladder is not needed until there is a second actor whose
credential must be pinned. Retained on its branch; see § 10.

---

## 7. What stays as scripts, and is never modelled

A domain model cannot make a DeepFilterNet invocation more correct. The
following keep every line, and gain at most two call sites each — `ledger has`
before, `ledger register-derived` after.

- **`scripts/youtube_enhance/{dfn,local_d30,generic_d30,render,loudness,
  diagnostics,candidates,segments,source,process}.py`** — working, measured
  DSP.
- **`scripts/youtube_enhance/gates.py`, `qa.py`** — objective vetoes over
  sample arrays, already fail-closed and already correct. Their *verdicts*
  become `Judgement`s; their *computation* stays exactly where it is.
- **`scripts/ggsm_transcription/asr.py`, `cli.py`, `intake.py`, `review.py`** —
  model loading, chunking, decoding, rerun handling, review chunking. Tool
  invocation behind an adapter boundary.
- **All `scripts/build_*_gallery.py`, `build_*_compare.py`,
  `build_*_review*.py` presenters** — keep every line of the HTML and the
  blind-panel keyboard UI, which is good. Exactly one thing changes: the
  destination of the JSON their existing "Download review" button already
  produces, from browser `localStorage` to `ledger judge`. No UI rewrite, no
  server.
- **`cloud/` and `colab/`** — `pod_setup.sh`, `pod_asr.sh`, `pod_train.sh`,
  `pod_infer.sh`, `orchestrate.sh`, `pod_dataprep.py`. GPU class,
  spot-vs-on-demand, region, image, batch size, checkpoint cadence and volume
  layout live here **and only here**. These are the levers that actually
  control the compute bill; they must stay cheap to change, which means they
  must never become domain concepts.
- **`voice_lab/` and the one-off research scripts** — `score_*.py`,
  `seed_ablation.py`, `predictiveness*.py`, `calibrate_gate*.py`,
  `probe_hi*.py`, `find_calm_ref.py`, `ref_denoise_ab.py`, `ecapa_*.py`. They
  produced their findings, which are written up in `docs/*.md`. Freeze them.
  Importing them would give old evidence a false present tense.
- **`scripts/hi/`, `cut_hi_final.py`, `build_clone_*.py`,
  `build_blind_clone_ab.py`** — superseded by the 2026-07-10 pivot. Runnable
  history. Do not migrate, do not model, do not test.
- **`fetch_idt.py`, `fetch_lecture.py`, `triage_lectures.py`,
  `analyze_source.py`, `spectral_inspect.py`, `propose_segments.py`,
  `recut_segments.py`** — intake and measurement. They feed the ledger;
  wrapping them adds a layer and removes nothing.

### 7.1 The one subtraction

`scripts/ggsm_transcription/store.py` and
`scripts/youtube_enhance/workflow_state.py` **do not both stay.** They are two
implementations of the same content-addressed store, and § 4.1 is the cost of
having both. One becomes the ledger; the other is retired.

This is the only part of this design whose first increment makes the repository
**smaller**.

---

## 8. Cost, model choice, and infrastructure

### 8.1 Cost is infrastructure — recorded as data, never as a rule

Defended on the repository's own measured numbers, not on principle. See
§ 4.5.

A budget aggregate, or a run that refuses to start because a ceiling was
reached, is an obstacle to a steward with a credit card, not a safeguard. There
is no cost invariant anyone wants enforced, and overspending produces a bill —
**and a bill is not a wrong answer.**

**What actually costs money is repetition, and repetition is a correctness
problem wearing a budget costume.** You re-run 1,800 hours because you cannot
prove a result is current. The run key fixes that, and the ledger must carry it
anyway for attribution reasons. Cost-effectiveness therefore falls out of the
one context already admitted, at zero additional modelling.

> You do not need a cost model. You need a cache key that is honest.

The single highest-value wiring is therefore **`ledger has` as one guard line
in the batch loops of `cloud/pod_asr.sh` and `cloud/orchestrate.sh`** — where
the GPU money is spent, and where the gate is currently `if path.exists()`
(§ 4.3).

### 8.2 Model choice is domain-adjacent

Three data fields and three preflight assertions (§ 5.1, `ModelCard`). Not a
context, not a policy version, not an authorization engine. § 4.4 is why the
fields matter and § 4.4's last paragraph is the first thing they will catch.

### 8.3 Infrastructure is `cloud/`, and stays there

The single exception is the lease and preemption rule (§ 5.1, `DerivedArtifact`
invariant 5), which is domain because a half-written preempted output recorded
as complete is a correctness failure and not a billing one.

---

## 9. Team size, and why the governing skill's exemption does not apply

`.agents/skills/clean-ddd-hexagonal/SKILL.md` line 14–22 gives six criteria.
Against this system:

| Criterion | Verdict |
|---|---|
| Complex business domain with many rules | ✅ use |
| Long-lived system (years of maintenance) | ✅ use |
| Multiple entry points (API, CLI, events) | ✅ use |
| Need to swap infrastructure | ✅ use |
| High test coverage required | ✅ use |
| Team of 5+ developers | ❌ *"Skip when: solo developer or small team (1-2)"* |

**Five of six say use it.** The sixth is set aside deliberately, and for a
reason rather than by preference.

The row assumes a *human* developer who holds the model in their head between
sessions. That assumption does not hold for agent-assisted development, and it
**inverts**:

The classic reasons DDD needs a team are shared ubiquitous language reducing
human miscommunication, structure aiding onboarding, and bounded contexts
permitting parallel work. When an AI agent performs the implementation, **every
session begins with zero continuity.** The agent is a new developer each time.

What keeps such a developer correct is not understanding — it is that
invariants are explicit, aggregates enforce their own rules, and tests fail
loudly. A solo steward working with agents therefore needs explicit structure
**more** than a five-person team does, because the team at least has continuity
of understanding.

This is not a theoretical claim. Tasks 1–6 were implemented across several
sessions and at least one context compaction; correctness survived that
specifically because the invariants were in the code rather than in anyone's
memory.

**Consequence for this design.** Arguments of the form *"one person does not
need X"* are withdrawn wherever they appear in prior analysis. Arguments from
observable fact — *"no second reviewer exists yet"*, *"nothing is being
formally released yet"* — stand, and are recorded as triggers in § 12 rather
than as permanent exclusions.

---

## 10. Verification discipline

### 10.1 What the governing skill mandates

`references/TESTING.md` prescribes a standard testing pyramid and six
principles: test behaviour not implementation; domain tests need no mocks; mock
at port boundaries; integration tests use real infrastructure; fast unit tests
and slower integration; test business rules in the domain.

It does **not** mention mutation testing, adversarial independent review, or
per-guard mutation harnesses.

### 10.2 What was actually done in Tasks 1–6

| Practice | Mandated? | Approximate share of elapsed time |
|---|---|---|
| DDD — aggregates, value objects, ports, layers | ✅ | ~40% |
| TDD and the testing pyramid | ✅ | included above |
| Mutation testing, nine harnesses, ~180 mutants | ❌ added | ~25% |
| Two adversarial independent reviews | ❌ added | the remainder |

**DDD was not the cause of the pace problem.** The skill set as the standard
prescribes very nearly what Tasks 2–5 built. What it does not prescribe is the
verification layered on top and then treated as non-negotiable.

### 10.3 The rule going forward

Normal TDD at the skill's standard. Mutation testing is retained **only** where
a wrong answer would be both silent and irreversible — signature verification
and approval, if and when built.

**One finding is worth preserving**, because it explains why review is kept and
mutation testing is not. The second independent review found a CRITICAL that
nine mutation harnesses and 656 tests had all missed: no handler tied a
transcript edition's source versions to the Production's attached sources.
Mutation testing can only exercise guards that **exist**. It cannot find a
check that was never written. Review can.

**Therefore: keep review at genuine gates. Drop routine mutation testing.**

---

## 11. Placement decision

The ledger lands as **`src/corpus_ledger/` on `main`**, importing only the
shared kernel.

The alternative considered was building it inside `src/heritage_production/`
so that the existing installable package becomes the thing that runs. That was
rejected: `heritage_production` lives only on
`work/heritage-production-first-slice` (§ 4.2), so landing the ledger there
would either produce a canonical store with no users, or require merging
31,641 lines of currently-shelved domain and test code into `main` in order to
ship ~900 lines that are wanted.

`src/corpus_ledger/` on `main` keeps shelved work genuinely shelved, and puts
the ledger where both working pipelines can import it on day one.

---

## 12. Disposition of `src/heritage_production`

Nothing is deleted. Everything either moves, is shelved with a **named
unfreeze trigger**, or is shelved indefinitely. Cutting working code is a
write-off, not a saving.

| Task | Verdict | Trigger to revisit |
|---|---|---|
| **1 — Foundation, packaging, architecture firewall** | **Keep.** Its packaging and architecture-test approach is the template for `corpus_ledger` | — |
| **2 — Shared domain kernel, canonical identity** | **Keep — this *is* the shared kernel** (§ 6), minus `trust.py` and the credential half of `refs.py`. Best-specified code in the repository | — |
| **3 — Transcription aggregate roots** (`edition.py` 1,367 + `proposal.py` 411) | **Shelve, unwired. Do not delete.** The `SegmentId`/`SegmentRevisionId` lineage — `CORRECTED_FROM` with exactly one parent, `SPLIT_FROM` with one, `MERGED_FROM` with at least two — is correct and genuinely hard. Digest-scoped anchors are a strict *subset* of segment lineage, so adding lineage later invalidates nothing already recorded | The first sealed Odia edition that will receive a second human correction pass |
| **4 — Review aggregate roots** | **Shelve** | The first finding submitted by a human who is not the steward |
| **5 — Production and release-policy domain** | **Shelve** | A rights-holder or recipient asks for a formal sign-off before delivery |
| **6 — Application ports, commands, first vertical workflow** | **Keep the port shapes as a reference.** `corpus_ledger` implements only the two ports it needs — artifact store, clock. The `run_operation` idempotency design is superseded by the run key, which achieves re-runnability without an operation registry | — |
| **7 — SQLite, CAS, operations, outbox** | **Partially do, as the ledger.** *Take:* checked SQLite migrations; streamed CAS ingest with staging and orphan reporting; traversal, reparse-point and cross-volume rejection (**this Windows correctness is already proven in `workflow_state.py` and `store.py` — move it, do not rewrite it**); atomic writes. *Drop:* the transactional outbox (it delivers events to handlers that do not exist); the operation registry and idempotency table (the run key already makes every command re-runnable); optimistic version columns on six roots; four per-module migrations for a three-table schema | — |
| **8 — Offline review workflow, deterministic ZIPs** | **Drop for now.** Replaced by `ledger judge` plus an importer for the JSON the existing Download-review button already emits | A second reviewer |
| **9 — Release, Ed25519, approval, export** | **Drop for now.** When a deliverable actually ships, a deterministic export archive is a script | A formal release to an external publisher |
| **10 — Integrity, backup/restore, authority routing** | **Take one piece now:** `ledger verify` — re-hash CAS objects, report mismatches. Backup is `sqlite3.Connection.backup()` plus copying the CAS directory. *Drop:* `MigrationAuthorityRecord`, shadow routing, canonical-write markers, cutover supersession — they model a migration between two systems, and there is one | Corpus large enough that restore rehearsal matters |
| **11 — E2E hardening, release rehearsal** | **Drop as a task.** Its one useful residue is the 2,000-segment scale fixture; keep it in tests | Follows 8 and 9 |

### 12.1 What survives in numbers

Of the 11,602 domain lines measured on the branch: roughly 1,500 move into the
ledger as the shared kernel, roughly 1,800 are shelved with near-term triggers,
and the remainder is shelved indefinitely.

---

## 13. Build order

Three increments. Each must leave something **runnable** and useful to more
than one programme.

### Increment 1 — the ledger. 2–4 days.

`register-item`, `register-derived`, `has`, with the run key **including a
pinned model revision** so that Sarvam-versus-IndicConformer is recorded from
day one (§ 4.4).

Most of this is a **lift-and-merge**, not new code: `manifest.py`'s
`canonical_json` and `cache_key`; `store.py`'s hashing, `msvcrt`/`fcntl`
locking, atomic revisioned writes and staging-directory install;
`workflow_state.py`'s path safety and `ArtifactRecord`. Perhaps 300–400
genuinely new lines, after which **one of the two duplicate stores is retired
rather than maintained** (§ 7.1).

Wire `register-derived` into **both** daily flows — transcription and
enhancement — in this same increment. `enhancing-lecture-audio` already resumes
on source hash, so it is the easier of the two; it is already thinking in the
right terms.

Wire `ledger has` as a single guard line into `cloud/pod_asr.sh` and
`cloud/orchestrate.sh` (§ 8.1).

Then register the real corpus: the 113 rows of `data/lecture_triage.tsv`, the
archived enhance jobs under `data/enhance/archive/`, `_work/ssggsm-1985-08-08`
and `-08-21`, and the Odia files as `fetch_idt.py` pulls them.

*Runnable on day one, serving programmes 1–4:* what exists by digest, which
files are the same bytes under different names, and which already have a
`SUCCEEDED` run for a recipe. Nothing in ~30,000 lines can answer any of those
today. No GPU, no migration, not one line of DSP touched.

### Increment 2 — `judge`, `coverage`, `plan`. 1–2 days.

`ledger judge --artifact <digest> --anchor <span> --verdict … --competence …`
ingests the JSON the gallery builders already export. Twelve-plus builders
currently persist verdicts to browser `localStorage`, keyed by a string,
unbound to bytes, and lost on a cache clear — **the most expensive input in the
entire portfolio stored in the least durable place in the system.**

`ledger coverage` then prints the honest sentence:

> 40 of 1,357 files, 2.1 h of 1,952 h judged; judge = steward; competences held
> {timbre, English intelligibility}; **not competent for Odia intelligibility**;
> 3 defects found; 1 word-integrity veto.

`ledger plan <recipe> --over <selection>` prints:

> 1,102 of your 1,357 files still need this recipe; at a measured 0.52 RTF
> (n=7) that is about 21 GPU-hours; 255 are already done and will be skipped.

— or the word `unmeasured` when fewer than three runs exist (§ 5.1).

*Serves 2 and 4 through the blind enhancement panels, and 1 and 3 through ASR
A/B review, in the same week.*

### Increment 3 — the Narrator Voice context. 2–3 days.

Brought forward from its original position because programme 5 is the only item
with a stated date (1–2 months), and because publishing a narration before the
resemblance gates exist is the one irreversible failure in the portfolio.

`Narrator`, `NarrationTake`, the must-not-resemble set seeded with SSGGSM, and
both gates measured on the exact bytes being published.

### Deferred

Spot-preemption leases and the triage gate. Both were sized for a bulk batch
programme; current cadence is daily and incremental (§ 2). They return when
bulk enhancement of programmes 2 or 4 actually begins, at which point the
triage gate is the largest avoidable GPU line in the portfolio.

### Then stop and measure

**If fewer than about fifty items are ever registered, per-job JSON plus `find`
was already enough and the ledger was waste.** That test is falsifiable and
should be applied honestly.

---

## 14. The stopping rule

This design's strongest objection is against itself.

It claims to be a *merge* rather than a fourth implementation of content
identity (§ 6.1). That claim is true **only if** increment 1 actually deletes
one of the existing stores and actually lands where both pipelines can import
it.

If either half slips — the merge lands but the deletion does not, or it lands
somewhere `ggsm_transcription` cannot see — the result is four identity schemes
and one with no users, **which is strictly worse than doing nothing.** And the
two pipelines with real audio moving through them are precisely the ones most
likely to be left alone.

The mitigation is not a plan. It is a stopping rule, stated in advance:

> **If, at the end of increment 1, `workflow_state.py`'s store is still alive
> and `ledger has` is not being called from `cloud/pod_asr.sh`, abandon the
> ledger and keep the two working islands.**
>
> No second attempt. No "we will wire it next sprint."

This is the discipline whose absence produced 31,641 lines that do not run
against either working pipeline.

---

## 15. Known limitations

### 15.1 Coverage is honest about quantity and silent about bias

`coverage` (§ 5.1) is derived from judgement rows. It answers *how much was
judged*; it cannot answer *whether what was judged was representative*. A
steward who listens to the easy files gets a number that is true and
misleading.

The sampling plan was deliberately deferred rather than built. The trigger is
nameable and the graft is cheap — `ledger sample` is roughly 40 lines over the
same table and invalidates nothing already recorded. But it is a bet, not a
proof, and it should be revisited the first time a WER figure is quoted to
anyone outside this repository.

### 15.2 Conditions under which a different design is better

- **The Odia work becomes contractual**, requiring published inter-annotator
  agreement and WER normalisation. Then a `Transcription Quality` context earns
  itself — *reference transcript, error rate, annotator, agreement* is
  vocabulary that enhancement does not share — and Tasks 4, 5, 8 and 9 stop
  being over-built. The correct response is to **unshelve**, which is why § 12
  shelves rather than deletes.
- **The real bottleneck turns out to be finishing one deliverable** rather than
  governing a corpus — fewer than ~50 items ever registered. Then even this
  design is over-built, and the honest answer is: move `cache_key` into
  `cloud/`, replace `localStorage` with a JSON file, and stop.
- **The next quarter becomes mostly enhancement** rather than daily
  transcription. Then the triage gate outranks the ledger, because
  `LEAVE_UNTOUCHED` as a first-class terminal outcome recovers most of the
  enhancement compute budget on its own, and it needs only diagnostics plus one
  table.

---

## 16. Decision log

| Decision | Basis |
|---|---|
| Five programmes are subdomains, not bounded contexts | The skill's linguistic criterion (§ 3.1) applied in § 3.2; the duplicate-store bug as empirical proof (§ 4.1) |
| Two bounded contexts, split on the `identity` polysemy | `gates.py::identity_verdict` vs `store.py`'s `.identity.lock` |
| `ArchiveItem`, `DerivedArtifact`, `Judgement` as separate aggregates | The skill's aggregate decision tree: no cross-aggregate transaction is required; an item owning 1,800 h of artifacts is the God Aggregate anti-pattern |
| Cost is infrastructure, not domain | Measured figures in § 4.5; repetition is a correctness problem, addressed by the run key |
| Model choice is three fields, not a policy engine | § 4.4; and a schedule-time gate would be routed around |
| Team-size exemption set aside | § 9 — the criterion assumes continuity of understanding that agent-assisted work does not have |
| Routine mutation testing dropped; review retained | § 10.3 — mutation testing cannot find a check that was never written; the second review found exactly such a defect |
| `src/corpus_ledger/` on `main`, not inside `heritage_production` | § 4.2 and § 11 |
| Nothing deleted; everything shelved with triggers | § 12 — cutting working code is a write-off, not a saving |
| Narrator context brought forward to increment 3 | Programme 5 has the only stated date, and its failure mode is the only irreversible one |

---

# AMENDMENT — 2026-08-26, later the same day

Sections 7.1, 13 and 14 above are **wrong** and are superseded by this
amendment. Sections 1–6, 8–12, 15 and 16 stand unchanged.

The error was found by commissioning an independent five-dimension analysis of
the two stores before starting to build, specifically because the author did
not trust his own estimate. Every claim below was then verified directly.

## A1. The increment-1 estimate was wrong by 5–8×

Stated in §13: *"a lift-and-merge of about 300–400 genuinely new lines, 2–4
days."*

Independent verdict: **REWRITE, 16–24 working days.** All five dimensions —
identity, lifecycle, concurrency, atomicity, path safety — returned
`divergent`. The 2–4 day figure correctly sizes extraction of a shared
substrate (~420 liftable lines), but increment 1 as scoped is that substrate
*plus* a three-table ledger, run key, leases, CAS, CLI, two flow wirings and a
corpus registration — of which roughly 75% has no prior art anywhere in the
repository.

## A2. The premise was false — neither store is what §7.1 assumed

**`scripts/ggsm_transcription/store.py` has never run.**

- Every commit touching the package is dated 2026-08-24 or 2026-08-25 — it is
  one day older than the design proposing to replace it.
- Zero job directories exist; `data/transcribe/` does not exist.
- `faster-whisper` is installed in neither venv, against a hard pin of `1.2.1`
  in `asr.py`.
- The two real transcripts in `_work/` were produced by hand in early August,
  before the package existed.

**And it would reject the work actually done.**
`_work/ssggsm-1985-08-21/asr-full.metadata.json` records an `initial_prompt`
(a Sanskrit prompt with diacritics). `DEFAULT_ASR_CONFIGURATION` has no
`initial_prompt` key, and `_matches_fixed_json_value` requires exact set
equality for dicts. `_validate_fixed_configuration` would raise on the very
recipe that produced both real transcripts.

**`scripts/youtube_enhance/workflow_state.py` is mostly dead.** Most of its
exports have no production caller; `cli.py` (2,683 lines) owns the real
enhancement lifecycle and imports almost nothing from it.

So §7.1's *"one becomes the ledger; the other is retired"* is false in both
directions. Retiring `workflow_state.py` is dead-code deletion wearing a
consolidation costume. Retiring `store.py` means rewriting `asr.py` (1,031
lines) and `review.py` (707 lines).

## A3. The design's own falsification test, applied now, says do not build it

§13 ends: *"If fewer than about fifty items are ever registered, per-job JSON
plus `find` was already enough and the ledger was waste."*

Counted honestly on 2026-08-26: **one** local lecture in `data/lectures/`,
**two** archived enhance sources, **two** `_work` transcripts — about **five
items**. Both stores hold zero rows. The 112 rows of `data/lecture_triage.tsv`
have no sha256, size or digest column, and the audio is ~1.7 GB away.

§13 placed that test *after* the expensive part. Running it *first* costs half
a day and saves four weeks. **The ledger is deferred.**

## A4. §14's stopping rule is defective — do not adopt it

It fails three independent ways, any one fatal:

1. **It is a conjunction**, so it is passed by deleting dead code — an
   afternoon that buys nothing.
2. **Its second clause cannot be satisfied honestly.** `cloud/pod_asr.sh` is 34
   lines of venv setup and a model-load smoke test; **it never opens a
   lecture.** The only way to make `ledger has` appear there is a dead line.
   The rule would be satisfied by theatre.
3. **It measures the wrong store.** Passing it leaves `store.py`'s scheme,
   `cli.py`'s manifest, `generic_d30.py`'s `job.json` and the new ledger —
   four identity schemes, verbatim the outcome §14 itself calls "strictly worse
   than doing nothing."

If a ledger is ever built, the tripwire is instead: (a) `store.py` no longer
computes a digest, job id or lock of its own; (b) `ledger has` gates a unit of
work that costs GPU minutes **and a run log shows it skipped one**; (c) ≥50
items registered from bytes on disk; (d) a hard time-box — not done at day 10,
stop.

## A5. §7.1's retirement order is overturned

§7.1 and the surrounding discussion proposed retiring `workflow_state.py`
first, on the grounds that enhancement is on-demand while transcription runs
daily. **Both premises are false.** Transcription has never run (A2).
Enhancement is the flow that has actually shipped — two archived jobs and a
human listening approval dated 2026-08-23, with `approval_record_sha256`
binding that judgement to bytes.

Enhancement is the more mature store, not the more expendable one.

## A6. What replaces §13

> **Status 2026-08-27:** items 1, 2 and 3 are done — merge `1996607`, and the
> digest normalisation described below. Items 4 and 5 remain.

**1. Merge `work/heritage-production-first-slice` into `main`.** ✅ *Done —
`1996607`.* The file sets
are disjoint — `main` added only `ggsm_transcription`, the branch only
`heritage_production`, and `youtube_enhance` is byte-identical on both. The
only overlapping file is `.gitignore`, which must resolve toward `main`
(the branch predates `ggsm_transcription` and would delete its ignores),
plus the branch's one new line `.heritage-production/`. `pyproject.toml`
arrives from the branch naming the whole repository `heritage-production`;
rename it, since heritage is the shelved part.

**2. Add `src/heritage_production/SHELVED.md`** ✅ *Done — `1996607`.* Pointing at §12 and its
unfreeze triggers. In the tree, not only in `docs/` — a future session finding
35,000 lines of dense DDD code will otherwise assume it is live.

**3. Normalise all digests to lowercase.** ✅ *Done 2026-08-27.* Nine sites: `dfn.py:252`,
`legacy_guard.py:119`, `qa.py:350`, `qa.py:371`, `source.py:34`,
`workflow_state.py:211,230,281,427`. Lowercase is already what
`manifest.py::cache_key` and all three fingerprints produce, and what
`store.py` requires. Under a day. **Zero live jobs exist, so nothing needs
re-valuing — that window closes the moment either flow produces output.**

Known costs, all acceptable:
`tests/youtube_enhance/test_workflow_state.py:338` inverts (that is the point);
the DFN chunk cache invalidates (recomputable CPU work); the two archived
approvals become non-recomputable, which they already are since their
`source.path` values no longer resolve.

*What the change actually touched, which was wider than the nine producer
sites: the nine producers, plus every validator that required uppercase
(`workflow_state._SHA256`, `legacy_guard.hash_external_artifacts`, two `qa.py`
alphabet checks, and seven `[0-9A-F]{64}` patterns in `cli.py`), plus
`local_d30.py`'s two authoritative constants. `cli._canonical_sha` lost its
`lowercase` parameter — with one canonical form there is nothing to choose —
and the `.casefold()` comparison at `cli.py:1219`, which existed only to bridge
the two cases, became exact. Digests arriving from outside (`--expected-sha256`,
a pre-fix `job.json`) are normalised with `.lower()` on the way in, matching
`store.make_job_id`. `tests/youtube_enhance/test_digest_case.py` now fails the
build if `.hexdigest().upper()` or `[0-9A-F]` reappears in the package, and
asserts both stores hash the same bytes to the same identity.*

*One documentation line is knowingly left stale:
`docs/superpowers/specs/2026-08-22-persistent-lecture-audio-enhancement-skill-design.md`
line 194 says the source tie-break sorts "by uppercase source SHA-256". Hex
sorts identically in either case, so the ordering is unchanged and only the word
is wrong; it is an approved design document and was not edited.*

**4. Make the SSGGSM flow actually run.** Install the pinned `faster-whisper`,
and reconcile `DEFAULT_ASR_CONFIGURATION` with the `initial_prompt` the real
transcripts used. Wanted daily; currently cannot complete. Worth more than any
architecture work.

**5. Consider the smallest possible Odia record.** Programme 1 runs via Sarvam
outside this repository, so it has no provenance here at all — the largest gap
in the portfolio. Perhaps 120 lines: source digest, model, date, output digest.
No run key, no lifecycle, no lock layer. If it reaches fifty rows, the case for
three tables is made *from data* rather than asserted.

## A7. Separate repository — not yet

Considered and rejected for now. It solves none of the problems found: the
digest split is fixable in place; `heritage_production`'s isolation is a
*branch* split, not a repository split; the absolute paths in `job.json` travel
with the code. Mukul maintains this codebase alone and will not hand it over
(confirmed 2026-08-26).

**Revisit when one programme has a running pipeline he would be willing to hand
to someone else.** At that point the move carries working code of known shape
rather than a plan.
