# Heritage Production DDD and Hexagonal Architecture Design

Date: 2026-08-22

Status: Approved by the user. First-slice implementation started on
2026-08-24 on branch `work/heritage-production-first-slice`.

## 1. Executive decision

Build a production-first, local-first Python modular monolith for heritage-audio
work. The first implemented vertical slice is transcript reconstruction for the
August 21 lecture currently represented under
`_work/ssggsm-1985-08-21/`.

The architecture is deliberately:

- one Python application and one local CLI;
- one Heritage Production bounded context;
- four explicit domain modules: Production, Transcription, Review, and Release;
- Clean Architecture dependency direction;
- Hexagonal ports and adapters around SQLite, files, legacy scripts, ASR,
  review packages, and release export, with remote publishing deferred;
- normal state persistence, not event sourcing;
- simple use-case handlers and read services, not CQRS infrastructure;
- in-process domain events, with a same-database local outbox only where an
  after-commit action must survive a crash;
- incrementally introduced around the existing repository, without a
  repository-wide rewrite.

DDD determines the language, invariants, aggregates, and module boundaries.
Hexagonal Architecture keeps tools and storage outside the domain. Clean
Architecture keeps dependencies pointing inward. None of these choices imply
microservices.

## 2. Why a new system is needed

The repository contains useful scripts and valuable artifacts, but its current
operating model is a collection of independent programs and mutable file
conventions rather than one authoritative production system.

The codebase audit established the following:

- Transcript reconstruction is the active workflow. The August 8 and August 21
  listening transcripts are current working artifacts, not approved releases.
- Voice cloning was explicitly superseded by the July 10 pivot. It remains
  historical, directly runnable code, but it is not part of the new production
  domain.
- Review decisions are commonly held in Markdown, TSV, JSON, generated HTML,
  or browser localStorage, with no durable canonical review ledger.
- Several pipelines identify data by filename, numeric suffix, or array index.
  Rebuilding a manifest or clip directory can therefore attach old evidence to
  different bytes.
- Cached results frequently rely on file existence rather than input, model,
  and configuration identity.
- Generated sites have conflicting producers, and the current static
  passcodes, unlisted URLs, `noindex`, and base64-encoded keys are not access
  control.
- Important tool, model, checkpoint, and promotion decisions are not always
  durably connected to their inputs and outputs.
- The active `_work/` transcript material is ignored by Git and therefore
  lacks a versioned application-level history.
- The repository already contains several gigabytes of source and generated
  media. A bulk copy or big-bang migration would be wasteful and risky.

The new system must preserve the useful scripts and artifacts while replacing
path-based authority with explicit identity, immutable history, policy-based
approval, and reproducible release evidence.

## 3. Mission and scope

### 3.1 Mission

Manage one intended heritage-audio deliverable from source intake through
reconstruction, review, evidence, approval, and an immutable release package.

The system is production-first. Legacy voice-cloning work becomes read-only
history. Restoration, narration, narrator selection, and other production
types can be designed later without weakening the transcript workflow.

### 3.2 First vertical slice

The first slice is transcript reconstruction:

1. register a source recording;
2. import ASR or alignment output as a proposal;
3. create an immutable transcript edition;
4. collect review findings against that exact edition;
5. create successor editions with traceable segment lineage;
6. evaluate a versioned release policy;
7. record steward approval of an exact release candidate;
8. export the approved package locally for delivery to an external publisher.

This workflow requires no GPU. Existing ASR output can be imported rather than
recomputed.

### 3.3 Explicit non-goals

The first slice does not:

- revive, train, evaluate, or publish a cloned voice;
- implement restoration, narration, casting, or model-experiment workflows;
- migrate the entire historical corpus;
- rewrite or reorganize every existing script;
- build a collaborative editor or hosted multi-user review service;
- automate public deployment;
- add microservices, a message broker, event sourcing, or full CQRS;
- normalize every historical artifact into canonical state;
- treat current static sites as secure private applications;
- delete, move, or overwrite existing artifacts.

## 4. Approved product decisions

The following decisions are requirements, not implementation suggestions.

### 4.1 Operating model

- A single steward operates the local CLI and owns final approval.
- Selected external reviewers receive versioned review packages.
- A production can require named reviewer, subject-matter, or rights-holder
  sign-offs before the steward is allowed to approve it.
- The system calculates eligibility; it never replaces the steward's explicit
  approval decision.

### 4.2 Production boundary

A `Production` represents one intended deliverable, such as an August 21
listening transcript. It can use multiple sources and create multiple working
editions, but it ends with at most one approved release package.

### 4.3 Transcript history

- Every meaningful committed correction creates a successor edition.
- Editing UI drafts do not create editions until committed.
- Editions are immutable after creation.
- Previous editions remain addressable and traceable.

### 4.4 Segment identity

- Transcript content is divided into timestamped segments.
- Each logical segment has a stable `SegmentId`.
- Each exact text-and-time representation has a `SegmentRevisionId`.
- Unchanged segments retain both identities.
- A text correction retains `SegmentId` and creates a new
  `SegmentRevisionId`.
- A split or merge creates new `SegmentId` values and records parent lineage.
- Array position, timestamp alone, filename, and numeric suffix are never
  identity.

### 4.5 ASR boundary

ASR produces an immutable `ASRProposalSet`. A fully provenanced set records the
source digest, tool, pinned model revision, configuration digest, and raw output
digest. A legacy set preserves missing provenance explicitly and requires a
steward attestation; it never masquerades as fully provenanced evidence. The
steward can use either permitted proposal type to create the first transcript
edition. ASR never writes or edits canonical transcript state directly.

### 4.6 Review

- Reviewers submit immutable findings against an exact edition and segment
  revision.
- Reviewers do not directly edit a transcript edition.
- The finding body remains immutable.
- The steward records one append-only accepted or rejected disposition.
- Accepted findings are inputs to a successor edition; they never mutate the
  reviewed edition.

### 4.7 Structured uncertainty

Uncertainty is domain data attached to an exact span. Initial kinds are:

- `INAUDIBLE`;
- `UNCERTAIN_WORDING`;
- `UNCERTAIN_SPEAKER`;
- `UNCERTAIN_LANGUAGE`.

Each mark records an exact source span, an optional character span within the
segment text, and an optional explanatory note. Release policy determines
which uncertainty is permitted or blocking.

### 4.8 Release

- Each production selects an explicit, immutable release-policy version.
- The policy declares required checks, permitted uncertainty, blocking finding
  categories, coverage requirements, and required sign-offs.
- Eligibility is derived from exact immutable inputs. It is not a manually set
  lifecycle status.
- Approval binds the exact edition, closed review evidence, policy version,
  sign-offs, and artifact manifest.
- The terminal domain fact is `ReleaseCandidateApproved`.
- Publishing is an external adapter and never occurs automatically on
  approval.

### 4.9 Migration

Migration is incremental:

- preserve all current artifacts;
- wrap useful scripts behind anti-corruption adapters;
- import their outputs with validation and provenance;
- replace one workflow at a time;
- cut over one Production ID at a time;
- never reconcile two authorities by filename or latest timestamp.

## 5. Architecture lock

| Concern | Decision |
|---|---|
| Deployment | One local Python process |
| Primary interface | CLI |
| Architecture | Modular monolith |
| Strategic DDD boundary | One Heritage Production bounded context |
| Domain modules | Production, Transcription, Review, Release |
| Persistence | One SQLite database plus content-addressed filesystem objects |
| Messaging | No broker |
| Domain events | In-process |
| Reliable after-commit work | Same-database local outbox processed by this application |
| State model | Current aggregate state plus immutable historical records |
| Event sourcing | Not used |
| CQRS | No full CQRS architecture or separate read store; lightweight command/query separation uses one application and database |
| Legacy integration | Anti-corruption adapters |
| Review delivery | Offline, versioned review packages initially |
| Publishing scope | First slice provides deterministic local export only; remote/public publishing is deferred |

The local outbox does not change the deployment model. It is a SQLite table
processed by the same application. Aggregate state remains the source of
truth and is never reconstructed by replaying events.

## 6. Strategic DDD design

### 6.1 Bounded context

The first slice has one bounded context: `Heritage Production`.

Production, Transcription, Review, and Release are separate domain modules
inside it. They are not four bounded contexts because they currently share:

- one steward and ownership model;
- one production lifecycle;
- one vocabulary;
- one local deployment;
- closely coordinated invariants;
- no independently evolving external consumer contracts.

Splitting them into services or bounded contexts now would add translation,
distributed consistency, and operational work without resolving a real
language or ownership boundary.

The system can split a module into another bounded context later only when its
language, ownership, lifecycle, and rate of change become independently
meaningful. A future Model Operations context is plausible if training,
checkpoint promotion, and experiment comparison become first-class production
work. It is not part of this slice.

### 6.2 Context map

```text
Archive, filesystem, and legacy scripts
                  |
                  | source/proposal anti-corruption adapters
                  v
        +-----------------------------------------------+
        |       Heritage Production bounded context     |
        |                                               |
        | Production -> Transcription -> Review -> Release
        |                    ^             |             |
        |                    +-------------+             |
        |                 accepted findings              |
        +-----------------------------------------------+
                                  |
                                  | approved immutable package
                                  v
                     External publishing adapter
```

The return from Review to Transcription creates a successor edition. It does
not edit the edition that was reviewed.

### 6.3 Module ownership

| Module | Owns | Must not own |
|---|---|---|
| Production | Deliverable intent, source references, steward, selected policy/gate-set references, active candidate binding, external sign-offs, terminal approval | Transcript text, ASR rows, review findings, policy rules |
| Transcription | Proposal sets, immutable editions, segments, revisions, uncertainty, lineage | Reviewer decisions, publication |
| Review | Review rounds, immutable finding bodies, dispositions, evidence digests, sign-offs | Transcript mutation, release-policy evaluation |
| Release | Policy versions, gate definitions, eligibility evaluation, release-package specification | Source acquisition, transcript editing, reviewer-authored content |

Release defines candidate and eligibility concepts. Production owns the
at-most-one final approval invariant and stores the exact approved candidate
snapshot.

### 6.4 Ubiquitous language

| Term | Meaning |
|---|---|
| Production | One intended deliverable with one steward and at most one approved release |
| Source recording | Media used as evidence for the production |
| Source version | Exact immutable source bytes identified by digest |
| Artifact | Immutable bytes stored or referenced by content digest |
| Proposal set | Advisory machine/tool output that can seed an edition |
| Transcript edition | Sealed, immutable transcript snapshot |
| Segment | A logical portion of the transcript that can persist across corrections |
| Segment revision | One exact text, timing, language, speaker, and uncertainty representation |
| Review round | A review scope bound to one exact transcript edition |
| Review finding | A reviewer's immutable observation or correction proposal |
| Finding disposition | The steward's one accepted or rejected decision |
| Sign-off | Evidence that a required actor accepted a named target and policy role |
| Release policy version | Immutable rules used to evaluate a candidate |
| Release content manifest | Sign-off-free immutable set of exact content and evidence proposed for release |
| Eligibility assessment | Deterministic result of applying one policy version to exact evidence |
| Release candidate | Exact edition, review, policy, sign-offs, and artifact manifest proposed for approval |
| Release approval | Immutable steward decision stored on Production |
| Release package | Immutable, hash-addressed deliverable and evidence bundle |

Words such as `latest`, `current file`, `clip 17`, and `the final
version` are not sufficiently precise in domain commands. Commands use exact
IDs and digests.

## 7. Clean Architecture and package structure

The Python package uses a layer-first structure with domain modules inside
each inner layer:

```text
src/heritage_production/
  domain/
    shared/
    production/
    transcription/
    review/
    release/
  application/
    production/
    transcription/
    review/
    release/
    workflows/
    ports/
  infrastructure/
    persistence/sqlite/
    artifacts/
    legacy/
    asr/
    review_packages/
    release_exports/
    events/
  presentation/
    cli/
  bootstrap.py
```

Dependency direction is:

```text
presentation  ----> application ----> domain
infrastructure ---> application ----> domain
```

Rules:

1. Domain imports only Python standard-library facilities and other approved
   domain types.
2. Domain never imports SQLite, filesystem paths, JSONL/TSV parsers,
   subprocess, HTTP, ASR, web, or deployment packages.
3. Application owns use cases, transaction boundaries, actor context, and
   outbound ports.
4. Infrastructure implements repositories, object storage, tool adapters,
   import/export formats, and event delivery.
5. Presentation translates CLI arguments and result codes into application
   commands and queries.
6. CLI handlers never call repositories directly.
7. Cross-module domain references use immutable public IDs or reference
   values, not another module's persistence objects.
8. The composition root in `bootstrap.py` is the only place that selects
   concrete adapters.

## 8. Tactical domain model

An aggregate is the unit whose invariants are protected by one transaction.
The design uses small mutable roots and sealed immutable roots rather than one
large Production object containing every edition, segment, finding, and
policy.

### 8.1 Shared identities and reference values

All IDs are opaque, application-generated identifiers. They are never derived
from filenames, timestamps, titles, row numbers, or database sequence
positions.

Core identity types are:

- `ProductionId`;
- `SourceRecordingId`;
- `SourceVersionId`;
- `ProposalSetId`;
- `ProposalItemId`;
- `TranscriptEditionId`;
- `SegmentId`;
- `SegmentRevisionId`;
- `ReviewRoundId`;
- `ReviewPackageId`;
- `ReviewSubmissionId`;
- `ReviewFindingId`;
- `RubricId`;
- `ReleasePolicyVersionId`;
- `ExternalGateSetId`;
- `ReleaseContentManifestId`;
- `ReleaseCandidateId`;
- `EligibilityAssessmentId`;
- `ArtifactId`;
- `BackupId`;
- `MigrationDecisionId`;
- `ActorId`;
- `OperationId`;
- `DomainEventId`.

Important immutable value objects are:

- `ContentDigest`: algorithm plus lowercase hexadecimal digest; SHA-256 is
  the initial algorithm;
- `ArtifactRef`: artifact ID, content digest, size, and media type;
- `SourceRecordingRef`: logical source-recording ID and descriptive source
  metadata;
- `SourceVersionRef`: source-version ID, logical source-recording ID, exact
  artifact digest, duration, and time base;
- `SourceSpan`: exact `SourceVersionRef` plus half-open integer microsecond
  interval `[start_us, end_us)`;
- `TranscriptScope`: required source intervals and explicit excluded-gap
  declarations;
- `RubricRef`: rubric ID, schema version, content digest, and optional
  content-addressed artifact reference;
- `ActorCredentialRef`: actor ID, verification method, pinned credential
  fingerprint, and public verification-key `ArtifactRef` when cryptographic;
- `PolicyEvaluatorRef`: evaluator name, semantic version, supported policy
  schema, and implementation build digest;
- `TranscriptText`: UTF-8 text normalized to Unicode NFC and LF line
  endings;
- `EditionRef`: edition ID plus content digest;
- `SegmentRevisionRef`: segment ID, revision ID, and revision digest;
- `ReviewEvidenceRef`: review-round ID plus frozen evidence digest;
- `ReviewTargetManifestRef`: review-round ID, target-manifest semantic digest,
  and outer manifest `ArtifactRef`;
- `ReviewPackageRef`: package ID, semantic content digest, and outer
  `ArtifactRef`;
- `PolicyRef`: policy-version ID plus policy digest;
- `ExternalGateSetRef`: Production-owned immutable gate-set ID plus digest;
- `ArtifactManifestRef`: manifest artifact ID plus digest;
- `ReleaseContentManifestRef`: manifest ID, semantic digest, and wrapper
  `ArtifactRef`;
- `ReleaseCandidateRef`: candidate ID plus semantic digest;
- `ActorRef`: stable actor ID and display label;
- `SignOff`: actor credential, required role, typed target reference, decision
  time, and verifiable proof;
- `EligibilityAssessment`: policy reference, exact evidence references,
  gate results, and deterministic assessment digest;
- `ReleaseApproval`: approved candidate snapshot, steward, time, and
  approval evidence digest.

`ClientSubmissionNonce` and `ClientFindingNonce` are validated, package-local
opaque tokens generated by the offline client. They are not domain IDs. On
first import the application assigns canonical `ReviewSubmissionId` and
`ReviewFindingId` values and persists an immutable nonce-to-ID map; an
idempotent reimport must resolve to that same map.

Canonical manifests use RFC 8785 JSON Canonicalization Scheme encoded as
UTF-8, with stricter domain constraints: duplicate object keys, floating-point
numbers, lone Unicode surrogates, and non-NFC strings are rejected; timestamps
and durations are integers; line endings inside strings are LF; and arrays are
ordered only where this document defines order. A digest is calculated from
canonical bytes, never from an in-memory object's incidental representation.
Golden canonicalization vectors are shared by every adapter.

Source intervals are half-open, so adjacent spans may satisfy
`left.end_us == right.start_us` without overlapping. Decimal legacy seconds
with at most six fractional digits convert exactly to microseconds. A finer or
rational time-base value is rounded to the nearest microsecond using decimal
`ROUND_HALF_EVEN`; the original token/time base and conversion are retained as
import evidence, and any collapsed or newly overlapping span is rejected.
Character spans are half-open Unicode scalar-value indexes into the NFC
`TranscriptText`, not UTF-8 byte or UTF-16 code-unit offsets.

### 8.2 Canonical digest contract

Every semantic digest uses the following preimage:

```json
{
  "digest_schema": "<domain-separation-label>",
  "schema_version": 1,
  "payload": {}
}
```

The envelope is serialized as canonical JSON and hashed with SHA-256.
`digest_schema` prevents the same JSON payload from being confused across
artifact types.

Universal rules:

1. The digest field itself is never part of its own preimage.
2. Archive/ZIP bytes have an outer `ArtifactRef` digest separate from an
   inner semantic digest.
3. Filesystem paths, database row positions, container metadata, and display
   labels are excluded.
4. Stable domain IDs are included when identity is semantically meaningful;
   database-generated surrogate row IDs are excluded.
5. Creation/export timestamps are excluded from content identity unless the
   table below explicitly includes a decision time.
6. Sets are sorted lexicographically by their stable identity or digest.
   Transcript segment arrays remain in explicit edition ordinal order.
7. An implementation must reject a supplied digest that does not recompute
   from the documented preimage.

| Digest | Domain-separation label | Included payload | Explicit exclusions |
|---|---|---|---|
| Artifact | Raw bytes; no JSON envelope | Raw bytes hashed directly with SHA-256 | Artifact ID, path, timestamps |
| Proposal set | `heritage-proposal-set-v1` | SourceVersionRef, provenance status/attestation, tool/model/config evidence, raw-package digest, ordered proposal items | ProposalSetId, import time, observed absolute paths, digest field |
| Transcript edition | `heritage-transcript-edition-v1` | Production ID, SourceVersionRefs, TranscriptScope, parent edition digest, ordered segment revisions, sealed edition-change manifest | EditionId, creation time, digest field |
| Review target | `heritage-review-target-v1` | Round ID, Production ID, edition digest, RubricRef, ordered target revision and derived-audio references | Reviewer assignment, package/export time, renderer path, digest field |
| Review package content | `heritage-review-package-v1` | ReviewTargetManifestRef, assigned ActorCredentialRef/role, ordered embedded member paths/digests | Package ID, export time, ZIP metadata/digest, digest field |
| Finding payload | `heritage-review-finding-payload-v1` | ClientFindingNonce, exact target IDs/digests, spans, category, severity, observation, proposed change, author ActorId | Canonical FindingId, submission ID/digest, import/export time, raw-package digest, digest field |
| Review submission | `heritage-review-submission-v1` | ClientSubmissionNonce, optional predecessor semantic digest, review-package semantic digest, assigned ActorId, complete/partial declaration, ordered target outcomes, ordered finding-payload digests | Canonical SubmissionId, ZIP metadata/digest, localStorage state, display label, import/export time, digest field |
| Finding disposition | `heritage-finding-disposition-v1` | Finding ID and payload digest, decision, rationale, steward ActorId, decision time | Database row ID, digest field |
| Sign-off | `heritage-signoff-v1` | ActorCredentialRef, policy role, typed target ID/digest, decision, signer time, proof algorithm/key fingerprint | Import time, display label, digest field |
| Review evidence | `heritage-review-evidence-v1` | Target digest, ordered finalized submission digests, finding-payload/disposition digests, coverage, review sign-offs | Close time, digest field |
| Release policy | `heritage-release-policy-v1` | Complete normalized rule set and policy-author ActorId | PolicyVersionId, creation time, digest field |
| Production gate set | `heritage-production-gates-v1` | Production ID and sorted named actor/role/credential/minimum-assurance/typed-target requirements | GateSetId, selection time, digest field |
| Release-content manifest | `heritage-release-content-v1` | Production ID, edition/review/policy and ExternalGateSet refs, ordered release member IDs/digests, provenance/integrity inputs | Sign-offs, candidate/approval IDs, assembly time, checksum/digest fields |
| Candidate snapshot | `heritage-release-candidate-v1` | Production ID, ReleaseContentManifestRef, ordered external sign-off digests | CandidateId, assembly time, digest field |
| Eligibility | `heritage-eligibility-v1` | Candidate-input digest, PolicyEvaluatorRef, and ordered gate results | Assessment ID/time, digest field |
| Approval evidence | `heritage-release-approval-v1` | Candidate digest, eligibility digest, steward ActorId, explicit decision time | Operation ID, digest field |
| Backup manifest | `heritage-backup-manifest-v1` | Database digest, schema version, sorted object digests, parent backup ID/digest | Backup-manifest digest field and output path |
| Release checksum manifest | `heritage-release-members-v1` | Sorted release-package member paths, media types, sizes, and digests | Checksum-manifest member itself, ZIP metadata, outer archive digest |
| Migration authority | `heritage-migration-authority-v1` | Production ID, predecessor decision ID/digest, from/to authority, exact cutover evidence, canonical-write watermark, actor/reason/decision time | Database row ID, filesystem route, digest field |

Wrapper manifests store the semantic digest calculated from the digest-free
payload. The final wrapper or archive is then stored normally and receives its
own raw-byte artifact digest. A reference named `*Ref` always names both the
stable identity and semantic or byte digest; an ID alone never satisfies an
integrity check.

### 8.3 Aggregate roots

| Aggregate root | Mutability | Primary invariants |
|---|---|---|
| `Production` | Mutable until approval | One intended deliverable, explicit sources and candidate, at most one approval |
| `ASRProposalSet` | Sealed at creation | One exact source version and explicit complete or legacy-attested provenance |
| `TranscriptEdition` | Sealed at creation | Ordered valid segments, deterministic digest, explicit parent and provenance |
| `ReviewRound` | Open then permanently closed | One exact target edition, fixed rubric/target manifest, frozen evidence digest |
| `ReviewFinding` | Immutable body, one appended disposition | Exact target, no editing, at most one steward decision |
| `ReleasePolicyVersion` | Sealed at creation | Complete, versioned, deterministic gate configuration |

There is one repository per aggregate root. There is no repository for a
segment, segment revision, proposal row, sign-off, eligibility result,
release approval, or gate result.

### 8.4 Production

`Production` owns:

- its identity;
- the intended deliverable description;
- the steward;
- immutable source-version references;
- the selected immutable `PolicyRef`;
- append-only immutable external-gate requirement sets and the active
  `ExternalGateSetRef`;
- the currently selected candidate-edition reference;
- append-only external sign-offs against exact release-content manifests;
- append-only immutable release-candidate snapshots and the active candidate
  reference;
- the final immutable release approval.

It does not contain transcript text, proposal rows, review findings, or
release-policy rules.

Invariants:

1. A production must have a non-empty intended deliverable description.
2. Every attached source includes exact artifact and content digests.
3. Selecting another candidate edition is forbidden after approval.
4. Selecting another edition, policy, or gate set clears the active candidate
   reference. Review and release-content applicability are derived from exact
   edition, policy, and gate-set identity; historical reviews, manifests,
   sign-offs, and candidate snapshots are not changed.
5. An external sign-off is append-only, is accepted only from the credential
   pinned by the corresponding gate declaration, and targets an exact sealed
   release-content manifest or other policy-authorized typed artifact.
6. A release candidate must reference a release-content manifest for the
   production's exact selected edition, policy, and gate set. Each required
   sign-off targets that manifest unless its gate explicitly requires a
   narrower typed artifact that is itself named in the manifest.
7. Superseded candidate snapshots remain immutable and addressable.
8. Approval requires a matching eligible assessment and authorized steward.
9. A production can contain at most one `ReleaseApproval`.
10. Approval is terminal for this first slice.

Changing the selected policy before approval is allowed but auditable. It does
not mutate the old policy or existing review evidence; all subsequent content,
sign-offs, candidate assembly, and eligibility must bind the new `PolicyRef`.
Changing external gates likewise appends and selects a new immutable gate set;
it never edits an earlier declaration or makes sign-offs for old content
applicable to the new set. Production-specific gates can strengthen but never
relax the selected release policy.

Production has no manually editable lifecycle-status enum. A read model derives
the display phase, in precedence order, from immutable facts:

1. `APPROVED` when the terminal approval exists;
2. `CANDIDATE_ASSEMBLED` when an active candidate matches the selected edition,
   policy, and gate set;
3. `CONTENT_SEALED` when a matching edition/policy/gate-set release-content
   manifest exists;
4. `REVIEWED` when a closed ReviewRound matches the selected edition;
5. `IN_REVIEW` when an open ReviewRound matches it;
6. `TRANSCRIPT_SELECTED` when an edition is selected;
7. `SOURCED` when at least one source is attached;
8. `DRAFT` otherwise.

These labels are presentation projections, not command guards or eligibility
states. Each command enforces its own exact-reference invariants, and
eligibility remains a separate deterministic assessment.

Release-candidate snapshots are immutable child records owned by Production,
stored append-only in their own table for efficient history. They are not an
independent aggregate and have no repository.

### 8.5 ASRProposalSet

`ASRProposalSet` is an immutable import of advisory machine or alignment
output. It owns:

- exact `SourceVersionRef`;
- package digest and schema version;
- importing adapter and adapter version;
- tool identity;
- model name and observed or verified model revision;
- configuration digest;
- provenance status;
- optional steward legacy-provenance attestation;
- creation/import time;
- raw-payload artifact reference;
- ordered proposal-item records.

Each proposal item has its own proposal identity, source span, proposed text,
language, optional speaker hypothesis, confidence evidence, and raw-row
locator. Confidence is evidence, not truth.

Invariants:

1. Every item references the proposal set's exact source version.
2. Source spans are non-negative, have start before end, and lie within the
   source duration.
3. Proposal IDs are unique within the set.
4. Tool/model/config fields are either verified or explicitly recorded as
   unknown; absence is never silently treated as complete provenance.
5. `COMPLETE` status requires verified tool, model revision, and
   configuration identity.
6. `LEGACY_ATTESTED` status requires raw metadata, exact source binding,
   explicit missing-field warnings, and an immutable steward attestation.
7. Index-only or filename-only identity cannot satisfy import validation.
8. A sealed set cannot be edited or marked as canonical transcript content.

Using a proposal to create an edition is recorded in the edition's
provenance. The proposal set itself does not need a mutable accepted status.

### 8.6 TranscriptEdition

`TranscriptEdition` is one immutable transcript snapshot. It owns:

- edition identity and digest;
- production and source-version references;
- immutable transcript scope and coverage declaration;
- optional parent-edition reference;
- ordered segment-revision manifest;
- edition-level provenance;
- creation actor and time;
- a sealed edition-change manifest mapping proposal/manual/finding inputs to
  the resulting revisions.

The edition root stores its metadata and manifest digest. Its repository can
persist the ordered segment-revision records separately for efficient access,
but those records remain immutable content owned through the edition model.
Queries do not need to load the entire aggregate merely to display one
segment.

Edition invariants:

1. An edition contains at least one segment.
2. Every segment revision references an attached production source.
3. Every segment has a unique, contiguous edition ordinal that defines
   transcript order.
4. Source spans on the same source version must not overlap in the first
   transcript slice.
5. Required source intervals are either represented by segments or by
   explicit gap declarations with a reason.
6. Every revision has non-empty transcript text or an explicit inaudible
   uncertainty covering its source span.
7. Every uncertainty mark lies within its segment's source and text bounds.
8. Segment and revision IDs are unique within the edition.
9. Parent edition and provenance references are exact IDs plus digests.
10. Every new or changed revision is justified by an accepted finding or an
    explicit steward-authored manual-change entry.
11. Every accepted finding is mapped to the resulting revision references or
    to an explicit no-edition-change reason.
12. The edition digest covers scope, the complete ordered manifest, and the
    sealed edition-change manifest.
13. A sealed edition has no update or delete operation.

Segment lineage rules:

- Unchanged: reuse `SegmentId` and `SegmentRevisionId`.
- Text, timing, speaker, language, or uncertainty correction: reuse
  `SegmentId`, create a new `SegmentRevisionId`, and reference the previous
  revision.
- Split: create two or more new `SegmentId` values, each with
  `SPLIT_FROM` pointing to the exact parent `EditionRef` and
  `SegmentRevisionRef`.
- Merge: create one new `SegmentId` with `MERGED_FROM` pointing to every
  exact parent `EditionRef` and `SegmentRevisionRef`.
- The lineage graph is acyclic. Parent references always point to an earlier
  edition.

An accepted finding never alters an edition. A successor edition copies
unchanged revision references and introduces only the new revisions recorded
in its `EditionChangeManifest`. The manifest maps each accepted finding and
disposition digest to applied revision references or a justified
`NO_EDITION_CHANGE` outcome, and maps every manual revision to its actor and
reason. This prevents both accepted findings and manual edits from disappearing
silently.

### 8.7 ReviewRound

`ReviewRound` owns:

- its identity;
- exact production and target-edition references;
- a sealed `ReviewTargetManifestRef` with durable ordered membership;
- an exact `RubricRef` and review-package schema version;
- requested reviewer credentials and required sign-off roles;
- open/closed state;
- finalized immutable review-submission summaries;
- closure time and actor;
- frozen evidence digest;
- explicit coverage summary.

The round does not embed every finding. Independent `ReviewFinding`
aggregates reference it, avoiding a large mutable root when a transcript has
hundreds of segments. It does own the small set of finalized
`ReviewSubmission` summaries, normally one per assigned reviewer. A summary
records the submission semantic digest, raw result `ArtifactRef`, verified or
attested reviewer identity, complete/partial declaration, reviewed/unreviewed
targets, and finding-payload references. This preserves a clean review that
produced zero findings.

Rules:

1. Findings can be submitted only while the round is open.
2. Every submitted finding must target a revision in the round's frozen target
   manifest artifact/membership rows.
3. A finalized submission can be attached only while the round is open and
   only after all of its finding imports completed.
4. Every submitted finding must receive a steward disposition before closing.
5. No incomplete review-import operation can exist when the round closes.
6. Closing calculates a deterministic digest over sorted submission, finding,
   disposition, coverage, and sign-off evidence.
7. Closing is permanent.
8. Closure means the evidence set is frozen; it does not by itself mean the
   candidate passed release policy.
9. Partial reviewer coverage is recorded explicitly. Release policy decides
   whether it blocks eligibility.

### 8.8 ReviewFinding

A `ReviewFinding` body contains:

- finding identity;
- review-round ID;
- review-submission ID;
- exact edition ID and digest;
- exact segment and segment-revision ID and digest;
- optional character and source subspans;
- category and severity;
- reviewer's observation;
- optional proposed text, boundary, speaker, language, or uncertainty change;
- reviewer identity;
- exported `FindingPayloadDigest`;
- reserved canonical review-submission ID and semantic submission digest.

The body is immutable. Its `FindingPayloadDigest` is calculated without any
submission wrapper or raw-package digest. The raw result `ArtifactRef` is
owned by the submission/import record, not duplicated inside each finding.

The aggregate permits exactly one append-only `FindingDisposition` child
value:

- `ACCEPTED`, with an optional steward note; or
- `REJECTED`, with a required reason.

The disposition records steward identity, decision time, and its own semantic
digest. It cannot edit, replace, or erase the reviewer's content.

### 8.9 Reviewer identity and sign-off trust

An offline result package's display name or `ActorId` is only a claim. It does
not become authenticated merely because it matches the assignment. The first
slice supports two explicit assurance levels:

- `VERIFIED_SIGNATURE`: the result or sign-off is signed by the private key
  corresponding to the `ActorCredentialRef` pinned in the Production gate or
  ReviewRound assignment. The initial verification scheme is Ed25519 behind
  an `ActorAuthority` port.
- `STEWARD_ATTESTED`: the steward explicitly binds an unsigned identity claim
  to an ActorId and records the reason and time. This permits the content to be
  reviewed as a finding, but it cannot satisfy a gate whose policy requires a
  verified external signature.

Every gate declares its minimum assurance. Rights-holder gates require
`VERIFIED_SIGNATURE` by default. A signature covers the semantic payload
digest together with actor ID, role, typed target ID/digest, operation kind,
and schema version. This prevents a signed response for one round, production,
role, or manifest from being replayed as another.

A review sign-off targets the immutable review-target digest. An external
release sign-off targets the sign-off-free `ReleaseContentManifest` digest (or
a narrower typed source-artifact target explicitly allowed by policy). Neither
sign-off targets a digest that already contains itself. Verification records
the algorithm, credential fingerprint, proof bytes or `ArtifactRef`, and
verification result as immutable evidence.

### 8.10 ReleasePolicyVersion and eligibility

`ReleasePolicyVersion` is immutable and contains:

- policy identity, semantic label, schema version, and digest;
- required integrity checks;
- allowed uncertainty kinds and limits;
- blocking finding categories and severities;
- required review coverage;
- required reviewer and rights-holder sign-off roles;
- required artifact types;
- rules for unresolved findings;
- the policy author and creation time.

A stateless `ReleaseEligibilityEvaluator` is selected by exact
`PolicyEvaluatorRef` and reads:

- the exact production candidate;
- the selected edition and digest;
- the edition's transcript-scope and gap-coverage assessment;
- a closed review round and evidence digest for that same edition;
- the selected policy version and digest;
- the active Production `ExternalGateSetRef`, which may only strengthen the
  policy;
- the sealed release-content manifest and digest;
- exact external sign-offs satisfying the gate set's typed-target rules;
- integrity-check results.

It returns an immutable `EligibilityAssessment`, stored as a content-addressed
assessment artifact plus query metadata rather than as an aggregate.
Eligibility is never stored as a manually editable Production status.
Approval re-evaluates or verifies the exact assessment inputs immediately
before mutating Production.

The final `ReleaseApproval` stored by Production records:

- release-candidate ID and digest;
- edition ID and digest;
- review-round ID and evidence digest;
- policy-version ID and digest;
- Production external-gate-set ID and digest;
- policy-evaluator name, semantic version, and build digest;
- release-content-manifest ID and digest;
- complete gate results or their canonical digest;
- eligibility-assessment artifact ID and semantic digest;
- all accepted sign-offs;
- steward identity;
- approval time;
- approval operation ID.

Approval emits `ReleaseCandidateApproved`.

## 9. Application layer and end-to-end flow

Application handlers coordinate aggregates and ports. They do not contain
domain rules that belong in aggregates or value objects.

### 9.1 Commands

| Command/use case | Reads | Writes | Result |
|---|---|---|---|
| `CreateProduction` | Deliverable intent and steward actor context | New Production | Production ID |
| `AttachSourceRecording` | Production, artifact metadata | Production | Exact source reference |
| `ImportProposalPackage` | Source reference, raw package | New ASRProposalSet | Proposal-set reference |
| `CreateInitialTranscriptEdition` | Production, proposal set | New TranscriptEdition | Sealed edition reference |
| `SelectCandidateEdition` | Production, edition reference | Production | Candidate binding |
| `CreateReleasePolicyVersion` | Normalized policy definition, author | New ReleasePolicyVersion | PolicyRef |
| `SelectReleasePolicyVersion` | Production, exact PolicyRef | Production | Selected policy binding |
| `ConfigureExternalGates` | Production, selected policy, named actor/role/credential requirements | Production | New active ExternalGateSetRef |
| `RegisterRubric` | Rubric bytes and schema | Artifact/operation records only | RubricRef |
| `RegisterActorCredential` | Actor, algorithm, public verification key | Artifact/operation records only | ActorCredentialRef |
| `OpenReviewRound` workflow | Production, edition, PolicyRef, ExternalGateSetRef, RubricRef, reviewer credentials, artifact inputs | Prepared target artifacts plus new ReviewRound | Round and target references |
| `ExportReviewPackage` | Open review round, sealed target manifest, artifact queries | Export artifact only | Review-package reference |
| `ImportReviewSubmission` workflow | Review round, result package | Durable import-operation progress | Import summary |
| `SubmitReviewFinding` | Open round and one validated finding payload | New ReviewFinding | Finding reference |
| `FinalizeReviewSubmission` | Open round, completed import operation, finding references | ReviewRound | Immutable submission summary |
| `DecideReviewFinding` | One finding, steward actor | ReviewFinding | Final disposition |
| `RecordReviewSignOff` | Open round, assigned credential, target digest, proof | ReviewRound | Immutable verified/attested sign-off |
| `CloseReviewRound` | Round and write-side finding/submission evidence snapshot | ReviewRound | Frozen evidence reference |
| `CreateSuccessorTranscriptEdition` | Base edition, closed round, accepted findings, change manifest | New TranscriptEdition | Successor reference |
| `AssembleReleaseContent` | Production, edition, review, policy, gate set, rendered artifacts | Artifact/operation records only | Sealed sign-off-free manifest |
| `RecordExternalSignOff` | Production gate, release-content target, actor credential, proof | Production | Immutable external sign-off |
| `AssembleReleaseCandidate` | Production, release-content manifest, exact sign-offs | Production | Candidate snapshot |
| `EvaluateReleaseEligibility` | Exact candidate inputs | Assessment artifact/metadata only | Eligibility assessment |
| `ApproveReleaseCandidate` | Production and exact immutable evidence | Production plus domain event | Release approval |
| `ExportApprovedRelease` | Approved Production and artifacts | Export artifact only | Release-package location/digest |
| `RecordProductionAuthorityCutover` | Exact migration/candidate/restore evidence | Append-only infrastructure authority record | Decision ID/digest |
| `SupersedePreWriteCutover` | Latest cutover and zero canonical-write markers | Append-only infrastructure authority record | Superseding decision |

`RegisterRubric`, `RegisterActorCredential`, `ExportReviewPackage`,
`EvaluateReleaseEligibility`, and read-only status operations do not mutate
domain aggregates. Registration/export operations can create content-addressed
artifacts and operation records through infrastructure ports.

The two authority operations are migration-administration use cases, not
domain aggregate commands and not additional aggregate roots. Their exact
append-only protocol is defined in Section 17.2.

`OpenReviewRound` is an application workflow with one aggregate transaction.
It allocates the round ID, renders and verifies any target audio into managed
storage, seals the reviewer-independent target-manifest artifact and ordered
membership, and only then creates the ReviewRound referencing that exact
manifest. A failure before the root transaction can leave only reportable
unreferenced artifacts; it cannot create a half-open round.

`ImportReviewSubmission` is an application workflow, not one domain
transaction. It validates and stores the raw package, then invokes one
idempotent `SubmitReviewFinding` command per finding. After every finding is
present, `FinalizeReviewSubmission` appends one immutable summary to
`ReviewRound`. A package with zero findings still creates a finalized
submission and coverage record.

### 9.2 Required sequence

1. Create Production and attach exact source versions.
2. Import a legacy or new ASR package through an anti-corruption adapter.
3. The steward creates and seals the first transcript edition.
4. Select that exact edition as the production candidate.
5. Create or select the exact release-policy version and immutable external
   gate set for this Production; an explicit empty set is valid.
6. Open a review round against the candidate's ID/digest and a prepared,
   sealed target manifest.
7. Export a versioned review package.
8. Import and finalize reviewer submissions, record steward dispositions and
   sign-offs, and close the round.
9. If any accepted correction changes the transcript, create a successor
   edition and select it as the new candidate.
10. Every successor edition receives a new review round. Prior review remains
   historical evidence but cannot authorize the successor.
11. Render and seal the sign-off-free release-content manifest from the exact
    edition, closed review, policy, Production gate set, and release artifacts.
12. Collect every required external sign-off against that exact manifest.
13. Assemble a release candidate from the manifest and sign-off evidence.
14. Evaluate eligibility.
15. The steward explicitly approves the exact eligible candidate.
16. Export only that approved package. Remote publication is a future adapter
    outside this slice.

### 9.3 Transaction rule

One domain transaction changes one aggregate root. Immutable inputs from
other aggregates are read by exact ID and digest. An application workflow can
run multiple such transactions, but it cannot disguise them as one atomic
cross-aggregate write.

Multi-step workflows are explicit application sequences rather than
distributed transactions. A successfully created immutable edition remains a
valid historical object even if selecting it as the Production candidate
fails; the selection command can be retried safely.

Mutable roots use optimistic versions. Approval never retries blindly after a
version conflict. It reloads and re-evaluates all candidate evidence.

Finding submission and review closure use SQLite `BEGIN IMMEDIATE`
transactions. `SubmitReviewFinding` checks that the target round is still
open before inserting one new finding. `CloseReviewRound` acquires the same
write lock, verifies the round version, rejects incomplete import operations,
loads the write-side evidence set, computes its canonical digest, and closes
only ReviewRound. SQLite serializes a concurrent submission before or after
closure; one admitted after the frozen snapshot is impossible.

### 9.4 Idempotency

Every command has an `OperationId`. Every content-producing operation also
defines a versioned, digest-free command-input manifest with a distinct
`heritage-command-<command-name>-v1` domain label. Its semantic idempotency key
is the digest of every domain-semantic input, not a convenient subset. At
minimum:

- proposal import includes the complete `SourceVersionRef`, raw-package
  `ArtifactRef`, adapter identity/version, provenance status and attestation,
  and all tool/model/config evidence;
- initial or successor edition creation includes Production ID, complete
  SourceVersionRefs, parent `EditionRef` when present, TranscriptScope, ordered
  revision manifest, and complete edition-change manifest;
- review opening includes Production/Edition refs, RubricRef, reviewer
  credential assignments, ordered target membership/derivations, and renderer
  version/config;
- review export includes the `ReviewTargetManifestRef`, reviewer assignment,
  ordered embedded members, and exporter version;
- review import includes ReviewRound/ReviewPackage refs and semantic submission
  digest; the raw package digest remains separately auditable;
- release-content assembly includes Production/Edition/Review/Policy refs,
  every derivation, and ordered release-member digests;
- external sign-off includes the complete semantic sign-off payload;
- release-candidate assembly includes ReleaseContentManifestRef and every
  ordered sign-off digest;
- eligibility and approval include candidate digest, PolicyEvaluatorRef,
  eligibility-assessment digest where applicable, and steward ActorId.

Repeating an identical completed operation returns the original result.
Repeating an operation ID with different inputs is rejected.

### 9.5 Read services

Read services can join and denormalize SQLite tables without loading aggregates.
Initial read models are:

- production summary and lifecycle;
- source and artifact provenance;
- transcript edition timeline;
- segment comparison and lineage;
- review progress, coverage, findings, and dispositions;
- release-policy explanation;
- eligibility report;
- approval and release-export history;
- integrity and recovery report.

This is lightweight command/query separation, not a full CQRS architecture:
reads and writes use the same application, data model, and database. The
separation prevents query-specific joins from polluting aggregate
repositories.

### 9.6 Domain events

Initial internal domain facts include:

- `ProductionCreated`;
- `CandidateEditionSelected`;
- `TranscriptEditionCreated`;
- `ReviewRoundOpened`;
- `ReviewFindingSubmitted`;
- `ReviewFindingDispositionRecorded`;
- `ReviewSubmissionFinalized`;
- `ReviewSignOffRecorded`;
- `ReviewRoundClosed`;
- `ReleaseContentAssembled`;
- `ExternalSignOffRecorded`;
- `ReleaseCandidateAssembled`;
- `ReleaseCandidateApproved`.

Domain events are immutable and named in past tense. They are dispatched
inside the same application. Events required for a recoverable after-commit
projection are inserted into the local outbox in the aggregate transaction.
No network broker is involved.

`ReleaseCandidateApproved` is always written to the local outbox so the
release-ready projection remains recoverable. Events with no required
after-commit effect can be dispatched synchronously without an outbox row.

The outbox provides at-least-once delivery. A handler records
`DomainEventId` in the same transaction as its effect, making duplicate
delivery safe. The application does not use domain events to reconstruct
aggregate state.

## 10. Hexagonal ports and adapters

### 10.1 Driver side

The first driver adapter is the local CLI. It translates arguments and files
into application commands and queries, supplies actor context, and maps typed
failures to concise messages and stable exit categories.

The review-result importer is also a driver adapter: an external review
package drives `ImportReviewSubmission`. It cannot call repositories or
construct domain objects without the application use case.

A future authenticated web interface can implement the same driver ports. It
is outside the first slice.

### 10.2 Driven ports

Application/domain-owned outbound ports include:

- `ProductionRepository`;
- `ASRProposalSetRepository`;
- `TranscriptEditionRepository`;
- `ReviewRoundRepository`;
- `ReviewFindingRepository`;
- `ReleasePolicyVersionRepository`;
- `UnitOfWork`;
- `ArtifactStore`;
- `ArtifactMetadataReader`;
- `LegacyProposalTranslator`;
- `ReviewPackageRenderer`;
- `ReviewSubmissionParser`;
- `ReleasePackageRenderer`;
- `ApprovedReleaseExporter`;
- `ActorAuthority`;
- `ArtifactDerivationVerifier`;
- `ProcessRunner`;
- `Clock`;
- `IdGenerator`;
- `OperationRecorder`;
- `DomainEventOutbox`.

Ports use domain/application language. They do not expose SQL, filesystem
paths, subprocess exceptions, HTTP response objects, JSONL rows, or Vercel
concepts.

### 10.3 Initial adapters

| Adapter | Responsibility |
|---|---|
| SQLite repositories | Persist and reconstitute aggregate roots |
| SQLite unit of work | Transactions, optimistic versions, outbox atomicity |
| Local artifact store | Stage, hash, validate, store, and stream immutable bytes |
| Legacy ASR importer | Translate existing JSONL/metadata into proposal language |
| Legacy evidence importer | Preserve noncanonical Markdown, TSV, JSON, and browser exports |
| Subprocess runner | Invoke allowlisted media/ASR tools safely and capture provenance |
| Offline review renderer | Produce self-contained, versioned review packages |
| Review-result parser | Validate and translate review exports |
| Release renderer | Build immutable release packages from approved inputs |
| Filesystem release exporter | Copy an approved package to an explicit local destination |
| Actor-authority adapter | Verify pinned reviewer/signatory credentials and signatures |
| Derivation verifier | Validate derived-artifact inputs, spans, tool/config, and output digest |

`ReleasePublisher` is intentionally not a first-slice port. A future remote
publishing design can add it without changing the domain approval model, but
only after provider-specific authentication, idempotency, and rollback rules
are approved.

### 10.4 Anti-corruption rules for legacy scripts

Existing scripts remain outside the application core. An adapter:

1. receives an application-owned request;
2. resolves exact input artifacts;
3. creates an isolated attempt directory;
4. invokes the legacy program or translates its existing output;
5. validates output;
6. records raw input/output artifacts and provenance;
7. translates only valid results into domain/application values.

Legacy schema fields not understood by the domain remain raw evidence. The
adapter does not add guessed semantics.

Specifically:

- An import declares one explicit import root. A relative JSONL `audio` path
  is normalized beneath that root, is rejected if it escapes the root, and is
  hashed before it can be bound to a `SourceVersionRef`.
- An absolute legacy path is never dereferenced as authority. It is retained
  verbatim only as a non-authoritative observed locator. The import proceeds
  only when the operator supplies an independently selected source whose
  bytes are hashed and explicitly bound; otherwise it is quarantined.
- The pilot's `asr-full.metadata.json` contains absolute audio/model-cache
  locators. The adapter preserves that raw file, binds `source.mp3` supplied
  by the operator, records locator mismatch/missing-field warnings, and marks
  the proposal `LEGACY_ATTESTED`. It does not infer a pinned model revision
  from the observed model name `small`.
- A numeric clip index is accepted only when corroborated by a source
  manifest, exact audio digest, and source span.
- Missing objects, duplicate IDs, path traversal, and ambiguous basename
  matches are rejected.
- Existing review exports without round, edition, target-manifest, and
  revision digests are preserved as unlinked evidence, not canonical
  findings.
- Existing generated HTML is a rendering artifact, never a database.

### 10.5 Safe subprocess execution

Subprocess adapters:

- use an allowlisted executable and argument array, never a shell-built
  command;
- set an explicit working directory and timeout;
- preflight required disk space and dependencies;
- capture executable, model, and dependency versions;
- capture stdout, stderr, exit status, start time, and end time;
- redact secrets from diagnostics;
- write only into an attempt-specific staging directory;
- validate output existence, nonzero size, media properties, and digest;
- promote no partial output after failure.

Remote model code is disabled by default. A model requiring remote code must
use a reviewed and pinned revision under an explicit adapter allowlist.

## 11. Persistence and artifact storage

### 11.1 Project-store layout

The default local store is:

```text
.heritage-production/
  metadata.sqlite
  objects/
    sha256/
      ab/
        <full-lowercase-digest>
  staging/
    <operation-id>/
  exports/
    review/
    release/
  backups/
```

The location is configurable through the CLI, but domain objects never contain
the store root or derived object paths.

The repository-local `.heritage-production/` directory must be added to
`.gitignore` before the first write. It contains operational state and possibly
sensitive media; Git is neither its backup nor its authority. Deliberate
portable release artifacts are copied out through `ExportApprovedRelease`.

### 11.2 Authority

SQLite is authoritative for domain metadata, identities, relationships,
operation state, and audit facts. The object store is authoritative for
immutable bytes. SQLite stores artifact ID, digest, size, media type, and
provenance; it does not store large media BLOBs.

An object path is derived from its digest. A legacy path is recorded only as
an observed locator in an import record. It is never canonical identity.

### 11.3 Logical schema ownership

The first schema contains logically module-owned tables:

- infrastructure: `schema_migrations`, `operations`, `artifact_blobs`,
  `artifact_derivations`, `import_batches`, `domain_events`, and
  `outbox`, plus append-only `migration_authority_records` and
  `canonical_write_markers` used only during cutover;
- Production: `productions`, `source_recordings`, `source_versions`,
  `production_sources`, `production_candidate_editions`,
  `production_gate_sets`, `production_gate_requirements`,
  `production_external_signoffs`, `production_release_candidates`, and
  `production_release_approvals`;
- Transcription: `asr_proposal_sets`, `asr_proposal_items`,
  `transcript_editions`, `segment_revisions`, and
  `edition_segment_memberships`;
- Review: `review_rounds`, `review_target_manifests`,
  `review_target_memberships`, `review_findings`,
  `review_finding_dispositions`, `review_packages`,
  `review_submission_imports`, `review_import_nonce_maps`, `review_submissions`,
  `review_submission_targets`, and `review_signoffs`;
- Release: `release_policy_versions`, `release_gate_definitions`,
  `release_content_manifests`, `eligibility_assessments`, and
  `release_packages`.

One physical database does not grant modules permission to update one
another's tables. Domain/application modules use repositories, public use
cases, or read services.

Mutable aggregate rows contain an optimistic `version`. SQLite foreign keys
are enabled. SQLite connections use WAL mode, a bounded busy timeout, and
`synchronous=FULL`.

### 11.4 Atomic artifact import

Artifact ingestion follows this order:

1. create an exclusive, no-follow file in an operation-specific directory
   under same-volume `staging/`; reject symlinks/reparse points and a staging
   root on another filesystem;
2. calculate SHA-256 while writing;
3. verify size and media constraints, durably flush the file using the
   platform facility, and close it;
4. when the digest destination is absent, atomically rename without overwrite
   and durably flush the parent directory where supported; when it already
   exists, rehash and size-check the existing object before discarding the
   staged duplicate; never replace an existing digest path;
5. begin a SQLite write transaction;
6. insert or reuse artifact metadata;
7. write the aggregate/import references and operation result;
8. commit.

A crash before the database commit can leave an unreferenced object, which is
safe and reportable. The ordering prevents a committed database reference to
a missing object.

Concurrent imports of identical bytes converge on one object. Different bytes
with the same legacy filename remain distinct.

### 11.5 Derived-artifact provenance

Every derived artifact, including a review audio excerpt, records an immutable
`ArtifactDerivation` containing:

- output `ArtifactRef`;
- ordered input `ArtifactRef` values;
- exact `SourceSpan` and any padding or channel-selection rule;
- renderer/executable identity and pinned version;
- normalized configuration and its digest;
- operation/attempt identity and diagnostics artifact references.

A target never binds an excerpt by output hash alone. The derivation must also
match its source version and span. Before a derived artifact enters a sealed
review or release manifest, `ArtifactDerivationVerifier` validates that record
and, where the adapter promises deterministic rendering, reproduces the output
digest. A hash-valid excerpt from the wrong span is therefore rejected.

### 11.6 Sealing and immutability

Edition, proposal, review-target/package, policy, release-content, candidate,
and release manifests are sealed by writing their membership rows and
canonical manifest digest in one transaction.

Sealed domain records have no repository update/delete API. Database
constraints and integration tests reinforce this rule. A correction creates
a successor object.

### 11.7 Incremental legacy storage

The system does not copy the repository's full media corpus. During the
August 21 migration:

- selected canonical inputs are hashed and copied into managed storage;
- unrelated artifacts remain in their existing locations;
- observed legacy paths and raw package bytes are retained as import evidence;
- an external artifact cannot be used in an approved package until its digest
  is revalidated and it is promoted into managed storage;
- unresolvable index-only evidence is quarantined rather than guessed.

Every import produces a content-addressed mapping report from legacy locator
and raw-row locator to new artifact IDs, domain IDs, warnings, and quarantine
reasons.

### 11.8 Backup and restore

A consistent backup uses SQLite's backup API or `VACUUM INTO`; copying
`metadata.sqlite` while WAL is active is not a supported backup.

The adapter first creates the SQLite snapshot and then opens that snapshot
read-only. It derives the complete referenced-object set from the snapshot,
never from the concurrently changing live database, copies exactly that set,
and rehashes every copied object before sealing the backup manifest. A live
import committed after snapshot creation belongs to a later backup and cannot
silently alter this one's membership.

Each backup contains:

- a consistent SQLite snapshot;
- schema version;
- database digest;
- a complete list of referenced object digests;
- parent backup ID for incremental backups;
- a digest-free canonical backup-manifest payload and its separately stored
  semantic digest.

A full portable backup contains the snapshot plus every referenced object. An
incremental backup contains the snapshot plus objects absent from the parent
manifest. Verification walks the complete parent ID/digest chain to a full
backup and fails if any parent manifest or required object is missing or has a
different digest.

Restore always targets an empty store and must pass:

- SQLite integrity check;
- foreign-key check;
- hash verification for every referenced object;
- recomputation of sealed edition, review, policy, candidate, and release
  manifest digests;
- verification of migration-authority predecessor chains and canonical-write
  marker bindings;
- availability of the exact PolicyEvaluatorRef required by any retained
  approval.

No restored store becomes authoritative until all checks pass.

## 12. Review-package protocol

### 12.1 Package purpose

A review package is a versioned, portable projection of one open review round
and one exact sealed transcript edition. It lets an external reviewer work
without direct access to the production database.

The package is not canonical review state. Only a validated import through the
application creates findings.

### 12.2 Package contents

The initial package is a ZIP archive containing:

```text
manifest.json
index.html
review-data.json
assets/
  <content-digest>.<extension>
```

`manifest.json` is a wrapper with two parts. Its `semantic_payload` contains:

- review-target manifest ID and semantic digest;
- review-round ID and Production ID;
- edition ID and digest;
- exact `RubricRef`;
- assigned reviewer `ActorCredentialRef` and requested role;
- the ordered target list;
- ordered embedded member paths, media types, sizes, and digests.

The wrapper also contains package schema version, package ID, exporter name and
version, creation time, the semantic payload, and
`review_package_content_digest`. The digest is computed only from the
`heritage-review-package-v1` envelope around `semantic_payload`; it excludes
the digest field itself, package ID, creation time, and ZIP/container metadata.
The review-target digest is independently recomputed from the
reviewer-independent `heritage-review-target-v1` payload. Thus two reviewers
can receive differently assigned packages while still reviewing the same
frozen target.

Each review target contains:

- an opaque package-local target ID;
- segment ID;
- segment-revision ID and digest;
- exact source span;
- transcript text;
- structured uncertainty;
- content-addressed audio excerpt and `ArtifactDerivation` references when
  included;
- allowed finding categories for the rubric.

The final ZIP is stored as an `ArtifactRef` with a separate outer raw-byte
digest. That outer digest is not embedded inside itself and is not the semantic
package digest. Importers verify the inner semantic digest, every declared
member digest, every derived-artifact binding, and the outer raw artifact.

### 12.3 Reviewer draft and export

The offline HTML can save an unfinished draft in browser localStorage. Its key
includes the package ID and review-package semantic digest. LocalStorage is
disposable convenience state and never evidence.

The reviewer must explicitly export a result wrapper. Its digest-free
`semantic_payload` contains:

- package-local `ClientSubmissionNonce` and result schema version;
- source review-package ID and semantic digest;
- round ID, Production ID, edition ID/digest, and review-target digest;
- assigned reviewer ActorId and role;
- complete/partial declaration;
- one ordered outcome for every reviewed target and an explicit ordered list
  of unreviewed targets;
- zero or more finding payloads, each with a package-local
  `ClientFindingNonce`, exact target IDs/revision digests, and a recomputed
  `FindingPayloadDigest`.

Each target outcome is `NO_ISSUE` or references one or more client finding
nonces; multiple distinct findings against one target are allowed. The result
wrapper adds the source review-package outer `ArtifactRef`, the author-supplied
export time, identity claim, signature/proof when available,
`submission_content_digest`, and container metadata. The semantic
digest is computed only from the `heritage-review-submission-v1` envelope
around `semantic_payload`; it excludes its own field, proof bytes, export time,
and ZIP/container metadata. A signature covers that semantic digest plus the
actor, role, target context, operation kind, and schema version described in
Section 8.9. The raw result container receives a separate outer
`ArtifactRef` after export.

A partial submission explicitly lists reviewed and unreviewed targets.
Absence never means accepted, rejected, keep, cut, or no issue.

### 12.4 Import

Import first stores the raw result package as an immutable artifact and then
validates:

- supported schema;
- exact review package, round, edition, and target-manifest references;
- exact target set and revision digests;
- assigned reviewer identity, role, credential/proof or explicit steward
  attestation, and policy-required assurance;
- unique client submission/finding nonces, exactly one outcome per declared
  target, and no duplicate canonical finding fingerprint; multiple findings
  per target remain valid;
- valid spans and categories;
- declared complete/partial status;
- every finding-payload digest, inner review-package/submission semantic
  digest, declared member digest, and outer raw-package digest;
- duplicate or conflicting prior submission policy.

The importer reserves a canonical application-generated submission ID in the
durable import operation. For each finding it assigns a canonical ID and
stores the immutable `(ReviewPackageId, client nonce) -> canonical ID` entry
in the same transaction that creates that finding. It then translates the
package into individual idempotent
`SubmitReviewFinding` operations. Each finding stores its client nonce,
exported payload digest, and semantic submission reference, never the outer
container digest. A canonical duplicate-finding fingerprint is the digest of
actor, exact target, normalized spans, category, severity, observation, and
proposed change, excluding both client and canonical IDs.

A durable import operation and finalized `ReviewSubmission` store the raw
result `ArtifactRef` and record which findings were created. A crash resumes
at the next unimported finding; it does not recreate prior findings or declare
the submission complete prematurely. The final submission row, target
outcomes, completed nonce-map digest, and round-open check are committed in the
same `BEGIN IMMEDIATE` transaction that mutates `ReviewRound`; all per-item
nonce mappings must already exist and match.

The first finalized submission for a review package is the head of its
assignment chain. A later correction must be exported from a newly issued
package for the same open round and name the predecessor semantic digest. It
does not erase the predecessor or any finding; it supersedes only that
assignment's coverage/outcome declaration. All findings across the chain
remain evidence and require disposition. Identical semantic reimports return
the original IDs; the same client nonce with different content, a forked
predecessor, or a second unlinked submission for one package is rejected.

Stale, ambiguous, or malformed exports are quarantined with a structured
report. They are never merged into a newer edition.

### 12.5 Privacy boundary

The first review adapter is offline. It makes no claim that an HTML passcode,
unlisted URL, `noindex`, base64 encoding, or client-side JavaScript protects
private content.

A hosted review adapter is deferred. Before it can be introduced, it must
provide server-side authentication and authorization, short-lived media
access, server-held blind mappings where applicable, audit logging, and a
separate approved security design.

## 13. Release content, candidate, approval, and export

### 13.1 Sign-off-free content and candidate assembly

Assembly is deliberately two-stage so a sign-off never hashes itself.

First, `AssembleReleaseContent` renders and seals a sign-off-free
`ReleaseContentManifest`. For the transcript slice its allowlisted member set
contains:

- canonical transcript JSON;
- human-readable transcript Markdown;
- edition, change, and segment-lineage manifests;
- structured uncertainty and transcript-scope/gap reports;
- provenance, source-reference, and artifact-derivation reports;
- closed-review evidence summary;
- release-policy version, Production external-gate set, and gate-input report;
- the path, media type, size, and digest of every release-content member.

The release-content manifest excludes sign-offs, candidate identity,
eligibility, approval, and its own digest. Source audio is excluded by default;
it is included only when the selected policy explicitly requires it and the
Production records the necessary rights authorization. The manifest receives
the deterministic `heritage-release-content-v1` digest defined in Section 8.2
and an outer `ArtifactRef` for its wrapper bytes.

Second, required external actors sign that exact semantic digest. Only then
does `AssembleReleaseCandidate` append an immutable Production-owned candidate
snapshot containing the `ReleaseContentManifestRef` and the ordered sign-off
evidence digests. The candidate's `heritage-release-candidate-v1` digest is
therefore nonrecursive. Reassembly with different content or sign-offs creates
a new append-only candidate; it never overwrites the earlier snapshot.

### 13.2 Approval

`ApproveReleaseCandidate`:

1. loads the Production using its expected optimistic version;
2. loads the exact immutable candidate, release-content, and sign-off inputs;
3. recomputes or verifies every digest;
4. loads the exact compatible `PolicyEvaluatorRef` and evaluates the exact
   policy version;
5. verifies steward authority and external sign-offs;
6. calls Production approval behavior;
7. stores Production and `ReleaseCandidateApproved` atomically.

Evaluator versions used by retained assessments/approvals remain available for
verification. If the exact compatible evaluator cannot be loaded, approval
and verification fail closed rather than interpreting an old policy with new
code.

The event payload contains IDs and digests, not large transcript or evidence
documents.

### 13.3 Release-package projection

After approval, an idempotent renderer creates a package containing the exact
release-content members plus:

- `candidate.json` and external sign-off evidence;
- the eligibility-assessment artifact;
- `approval.json`;
- the `ReleaseCandidateApproved` event identity;
- package schema version;
- a final checksum manifest.

The checksum manifest lists every other member in normalized lexicographic path
order and excludes itself. Its semantic digest uses
`heritage-release-members-v1`. The archive is deterministic: UTF-8 names use
`/`, entries are sorted, timestamps and permissions use fixed documented
values, comments and platform-specific extra fields are absent, and the
compression method/level and renderer version are pinned. The checksum
manifest's wrapper and final archive each receive their own outer artifact
digest; neither outer digest is embedded inside its own bytes.

Adding approval evidence does not alter the release-content set that external
actors signed. The archive records the approved candidate digest and its
release-content-manifest digest. Rebuilding from identical immutable inputs
must reproduce byte-identical archive bytes; a golden rebuild test enforces
this rule.

### 13.4 First-slice export and future publishing

The first slice implements only `ExportApprovedRelease`. It verifies the
stored archive against its approval and checksum manifest, then copies those
exact bytes to an explicit local destination. It never rerenders content. The
operation record stores destination, attempt ID, archive digest, time, and
result. A failed copy leaves the approved archive and approval unchanged; a
retry uses the same digest.

Remote publishing is not a first-slice command or port. A future explicit
publisher adapter must:

- accept only a package whose approval references its candidate manifest;
- verify every object digest before sending;
- publish only the allowlisted package contents;
- record provider, destination, attempt ID, package digest, time, and result;
- use the package digest as its idempotency identity where the provider
  permits;
- never rebuild content during publication.

A future publishing failure would not revoke or alter approval. After terminal
approval, a content change is unsupported for that Production in the first
slice; it requires a new Production or a separately approved revocation and
re-release design. Remote/Vercel publication remains outside first-slice
completion.

## 14. Failure handling and recovery

### 14.1 Governing rule

The system fails closed. Missing provenance, uncertain identity, incomplete
output, broken integrity, or failed policy evidence cannot silently become
canonical or release-eligible.

### 14.2 Typed failure envelope

Every failed operation records:

- operation ID and attempt ID;
- category and stable machine-readable code;
- aggregate and artifact references involved;
- retryable or non-retryable classification;
- safe, redacted diagnostic;
- recovery instruction;
- tool/adapter version when relevant;
- start and failure times.

Initial categories are:

- domain validation;
- provenance/import;
- stale reference or concurrency;
- dependency/environment;
- transient filesystem/tool failure;
- subprocess/tool failure;
- persistence;
- integrity;
- review import;
- policy/security;
- release export.

Remote-publication categories are added only with the future publisher
adapter.

### 14.3 Boundary behavior

| Failure | Required behavior |
|---|---|
| Domain invariant violation | Return a precise rejection and commit nothing |
| Candidate is ineligible | Return the complete gate result; treat it as a valid business outcome |
| Unknown or ambiguous legacy identity | Preserve raw input in quarantine; create no canonical object |
| Invalid, spoofed, or replayed reviewer/signatory proof | Reject it as gate evidence; preserve raw bytes and a redacted verification report |
| Stale edition/review/policy reference | Abort and report expected and current IDs/digests |
| Tool nonzero exit, timeout, or invalid output | Record failed attempt; promote no partial artifacts |
| CAS write succeeds but DB commit fails | Leave a reportable orphan object; never a dangling DB reference |
| Existing CAS object fails digest/size verification | Quarantine the path, fail closed, and never reuse or overwrite it automatically |
| Missing or corrupted referenced object | Block review, candidate assembly, approval, and export |
| Outbox handler repeatedly fails | Keep a visible failed-delivery record with explicit replay command |
| Release export fails | Keep approval and stored package unchanged; record failed attempt |
| Backup fails verification | Do not label or use it as restorable |

Warnings are structured evidence. No warning can silently downgrade a failure
into a pass.

### 14.4 Recovery commands

- `retry`: repeat a transient attempt with identical immutable inputs;
- `resume`: continue a multi-item idempotent import or projection;
- `rebuild`: create a new attempt while preserving the failed one;
- `verify`: recompute database, object, and sealed-manifest integrity;
- `quarantine show`: inspect rejected legacy evidence;
- `outbox replay`: retry a named failed event;
- `backup create` and `backup verify`;
- `restore verify`: validate a restored empty-target store.

No recovery command silently overwrites an immutable object or changes a
failed result to accepted.

### 14.5 Integrity maintenance

The integrity read service reports:

- foreign-key violations;
- referenced objects that are missing;
- object size or digest mismatch;
- unreferenced objects;
- broken edition membership or manifest digest;
- review evidence-digest mismatch;
- policy, candidate, approval, or release-manifest mismatch;
- incomplete imports and exports;
- failed or stuck outbox items.

Garbage collection is not part of the first slice. A future collection command
can remove only objects that are unreferenced, older than a configured
retention period, and absent from every retained backup manifest.

## 15. Security, privacy, and policy safeguards

### 15.1 Secrets

Secrets come from environment injection, operating-system credential storage,
or a provider secret manager. They never appear in:

- source control;
- plaintext token files such as `.hf_token`;
- command arguments;
- artifact manifests;
- generated HTML;
- captured logs.

Reviewer/signatory private keys are never copied into the project store or a
review package. Only public verification keys or fingerprints are pinned in
gate and assignment evidence.

Diagnostics redact known secret values before persistence. A suspected leak is
non-retryable and requires revocation or rotation.

### 15.2 Files and paths

Import adapters reject:

- path traversal;
- device paths;
- unsupported links;
- paths outside their explicitly supplied import root;
- absolute legacy/remote/pod locators offered as canonical input identity;
- filenames used as a substitute for a digest.

Artifact reads use digest-derived paths constructed by the local store
adapter. Domain values never carry arbitrary filesystem destinations.

### 15.3 Retired voice-cloning boundary

The new CLI exposes no voice-cloning training, checkpoint, inference, or
publishing command. Legacy cloning scripts and artifacts remain untouched
outside the new domain.

The first transcript release policy rejects candidate artifacts whose
derivation identifies a retired voice-cloning or synthetic-voice pipeline.
Introducing synthetic narration later requires a separately approved domain
design and policy.

### 15.4 Static and hosted content

Static review and release files are not private merely because they are
unlisted, marked `noindex`, base64 encoded, or protected by client-side
JavaScript.

The first slice exports offline review packages and local release directories.
It does not deploy sensitive material. A future remote publisher must perform
provider-specific access-control preflight and post-deployment verification.

## 16. Verification strategy

### 16.1 Test pyramid

The suite contains:

1. many pure domain tests;
2. focused application tests using fake ports;
3. real SQLite and filesystem adapter contract tests;
4. architecture dependency tests;
5. a small number of end-to-end workflows.

The normal suite is offline and requires no GPU, ASR model, network, or
private corpus.

### 16.2 Domain tests

Domain tests use no mocks and cover:

- every Production approval precondition;
- at-most-one approval and terminal behavior;
- source-span and text-span validation;
- half-open adjacency, fractional legacy-time conversion, emoji, and combining
  mark character-coordinate behavior;
- edition immutability;
- corrected, unchanged, split, and merged segment identity;
- acyclic lineage;
- uncertainty kinds and exact containment;
- transcript-scope completeness, explicit gaps, and rejection of omitted
  required audio;
- edition-change-manifest completeness for accepted findings and manual edits;
- review target matching;
- exact RubricRef binding;
- immutable finding body and one disposition;
- permanent review closure and deterministic evidence digest;
- exact policy-version evaluation;
- exact PolicyEvaluatorRef pinning and regression compatibility across an
  evaluator upgrade;
- blocker, coverage, uncertainty, actor-assurance, and sign-off gates;
- sign-off-free release-content and nonrecursive candidate digests;
- deterministic eligibility;
- exact candidate/approval binding and superseded-candidate retention.

Property and state-machine tests generate:

- arbitrary Production command sequences, proving approval is unreachable
  without exact eligible evidence;
- candidate changes during review, proving an edition-A review cannot approve
  edition B;
- correction/split/merge sequences, proving lineage uniqueness and acyclicity;
- findings in arbitrary insertion order, proving canonical evidence digest
  stability;
- policy values around thresholds, proving deterministic boundary behavior.

Rejected operations must leave the aggregate unchanged.

### 16.3 Application tests

Use-case tests provide fake repositories, unit of work, clock, ID generator,
actor context, artifact store, and outbox. They prove:

- commands load exact immutable references;
- each domain transaction changes one aggregate;
- validation and concurrency failures write nothing;
- proposal import cannot select or edit an edition;
- review-package imports resume without duplicate findings;
- a complete clean review with zero findings persists its submission and
  coverage evidence;
- finding payload, submission, sign-off, candidate, approval, and wrapper
  digests reject a supplied self-digest mismatch;
- unsigned identity claims cannot satisfy a verified external gate;
- a sign-off for another round, role, Production, or release-content digest is
  rejected as replayed or out of scope;
- selecting a successor makes prior review inapplicable without mutating
  historical records;
- candidate reassembly preserves every superseded snapshot;
- approval mutates only Production and records the exact event;
- duplicate event delivery has one logical effect;
- release export cannot run without approval.

### 16.4 Adapter contract and integration tests

All repository implementations share aggregate-specific contracts. The
SQLite implementation is tested using a real temporary database and temporary
object store.

Critical cases include:

- persistence/reconstitution with exact digest preservation;
- optimistic-lock conflicts;
- aggregate plus outbox atomicity;
- sealed-record update/delete rejection;
- same bytes imported twice;
- different bytes with the same basename;
- concurrent imports of the same bytes;
- a pre-existing corrupt object at the expected CAS path;
- rejected symlink/reparse destinations and cross-volume staging;
- crashes/power loss after staging write, durable flush, object rename, parent
  sync, and before DB commit;
- semantic digest recomputation with all self/wrapper fields excluded;
- canonical-JSON golden vectors, including duplicate-key, float, non-NFC, and
  lone-surrogate rejection;
- review-submission inner/outer digest recomputation and tamper rejection;
- missing and corrupted objects;
- review close racing with finding submission or disposition;
- hash-valid but wrong-span derived audio excerpt rejection;
- byte-identical deterministic release-archive golden rebuild;
- backup and restore into an empty store, including complete incremental
  parent-manifest-chain verification;
- a concurrent import/backup race proving membership is derived only from the
  copied SQLite snapshot;
- restored operation with `_work/` unavailable and an assertion that no
  canonical reference or non-raw metadata depends on its absolute path;
- outbox retry after handler failure.

Legacy adapter fixtures contain only two to five sanitized rows representing
the repository's real JSONL, TSV, resegmentation, and browser-export shapes.
Private audio and the multi-gigabyte corpus are not copied into tests.

Negative import fixtures cover:

- index-only joins;
- basename collision across lecture roots;
- pilot-style absolute pod/model-cache locators without an independent source
  binding;
- path traversal;
- missing objects;
- malformed JSONL/TSV;
- duplicate proposal IDs;
- invalid or overlapping source spans;
- missing model/config identity incorrectly claimed as `COMPLETE`;
- stale review package digest;
- wrong reviewer or round;
- duplicate target decision;
- silent partial review;
- mixed original/denoised reference identity.

### 16.5 Architecture tests

Python import-boundary tests enforce:

- Domain cannot import Application, Infrastructure, Presentation, SQLite,
  filesystem, subprocess, HTTP, or legacy modules.
- Application cannot import concrete Infrastructure or Presentation adapters.
- Presentation calls application use cases, never repositories.
- Infrastructure implements inward-owned ports.
- Modules cannot update another module's persistence implementation.
- Repositories exist only for the six approved aggregate roots.
- Event handlers and side effects live outside aggregates.
- Domain code is free of import cycles.

### 16.6 End-to-end tests

Four end-to-end scenarios are required:

1. Source and proposal import, first edition, clean review, candidate assembly,
   approval, and release export.
2. Finding acceptance, successor edition, mandatory new review, and approval,
   while all earlier history remains intact.
3. Blocking uncertainty, unresolved finding, or missing sign-off prevents
   approval; corrected evidence later succeeds.
4. Crash/retry around import and outbox processing creates no duplicate
   canonical state or release-projection/export effect.

A scale fixture with at least 2,000 synthetic segments verifies that read
views, finding submission, closure, and release evaluation do not depend on
loading all findings into one mutable aggregate.

Optional smoke tests can exercise installed FFmpeg or ASR adapters separately.
They are not part of the deterministic default suite.

## 17. Incremental migration and cutover

### 17.1 Pilot production

The pilot is the August 21 transcript workspace:

`_work/ssggsm-1985-08-21/`.

Its initial classification is:

| Legacy material | Migration treatment |
|---|---|
| `source.mp3` | Operator selects it explicitly; hash, validate, promote, and bind it as the exact SourceVersionRef |
| `asr-full.jsonl` and metadata | Preserve raw bytes and absolute observed locators; import only as `LEGACY_ATTESTED` with the explicit source binding, missing pinned-model/config warnings, and steward attestation |
| `onenote-transcript.md` | Preserve as a legacy draft; convert to a sealed edition only through explicit structured mapping and steward confirmation |
| `review-01.md`, `review-02.md`, `review-03.md` | Preserve as historical/unlinked evidence; do not infer canonical findings |
| raw text and reference files | Preserve as supporting evidence |
| workspace helper scripts | Keep in place; invoke or translate only through named legacy adapters |
| generated browser state | Preserve raw export when available; reject as canonical review without exact target identity |

No existing file is moved, rewritten, or deleted.

### 17.2 Authority-record protocol

Authority routing is enforced by a content-addressed, append-only
infrastructure migration record, not by a seventh domain aggregate. Each
`MigrationAuthorityRecord` contains:

- MigrationDecisionId and schema version;
- Production ID;
- predecessor decision ID and semantic digest, or `null` for the first record;
- explicit `from_authority` and `to_authority` values;
- exact source, edition, review, PolicyRef, release-content, candidate,
  eligibility, and restore-report references required by the transition;
- the canonical-write watermark observed when deciding;
- steward ActorId, reason, and decision time;
- `heritage-migration-authority-v1` semantic digest.

Its canonical wrapper is stored as an `ArtifactRef`, and the database row
stores both semantic and outer byte digests.

The CLI route for a Production is determined only from the latest valid record
in its unbroken predecessor-digest chain. Before cutover, writes to the new
store require explicit shadow mode. After cutover, every canonical domain
transaction atomically appends a `canonical_write_marker` containing the
authority-record digest, OperationId, affected aggregate ID/version, and write
sequence. The first such marker makes automatic routing back to legacy
illegal.

`RecordProductionAuthorityCutover` expects the current authority record/digest
and inserts the next record transactionally. `SupersedePreWriteCutover` is
allowed only when the latest record is the cutover and no later canonical
write marker exists. These records are audit/operational facts; they do not
participate in heritage-domain eligibility or event sourcing.

### 17.3 Migration phases

#### Phase 1: Foundation

- Establish package boundaries and architecture tests.
- Implement identity/value primitives.
- Implement SQLite unit of work, aggregate repositories, operation records,
  object storage, and integrity verification.
- Implement the CLI composition root.

Legacy remains the operational authority.

#### Phase 2: Shadow import

- Create one Production for the August 21 deliverable.
- Import and fingerprint the selected source and proposal evidence.
- Produce import mapping and quarantine reports.
- Create a first sealed edition under explicit steward confirmation.
- Compare deterministic read/export views with the legacy listening draft.

The new store is shadow state and does not yet replace the old workflow.

#### Phase 3: Validated review in shadow

- Create and select the explicit pilot policy version and Production-specific
  external gate set.
- Select the exact candidate edition.
- Open and export a versioned review round.
- Perform or collect review using the new package.
- Import validated canonical-form findings and record dispositions while the
  store remains provisional shadow state.
- Create and review a successor edition when corrections are accepted.

Existing Markdown reviews remain evidence only. Legacy remains operationally
authoritative throughout Phases 3 and 4; records in the new store are in
canonical form but provisional until the authority cutover.

#### Phase 4: Release rehearsal

- Assemble the exact sign-off-free release-content manifest, collect required
  sign-offs, and assemble the candidate.
- Exercise eligible and ineligible cases.
- Verify eligibility for the real pilot without approving it.
- Copy the store to an isolated rehearsal store while retaining every immutable
  Production/edition/review/content ID and digest. Mark the environment itself
  `NON_AUTHORITATIVE_REHEARSAL`, exercise approval only in that copy, and keep
  its deterministic package confined to the rehearsal output.
- Restore another copy into an empty location, make `_work/` unavailable, and
  verify all manifests plus release rendering from managed objects alone.

No approval is recorded on the real pilot Production and no public deployment
occurs during rehearsal.

#### Phase 5: Narrow cutover

First revalidate that the source/legacy fingerprints have not changed, the
real candidate remains eligible, and the independent restore check passed.
Then record one immutable steward cutover decision containing:

- Production ID;
- source-version IDs and digests;
- selected edition ID and digest;
- closed review-round ID and evidence digest;
- policy-version ID and digest;
- unapproved release-candidate, release-content-manifest, and
  eligibility-assessment digests;
- verified backup/restore report digest;
- cutover actor and time.

After that decision:

- the new application is the only canonical writer for that Production ID;
- legacy files are treated as historical observations, although the new
  application cannot technically make external paths immutable;
- old scripts can contribute only through adapters and new imports;
- there is no dual-write synchronization;
- no other production is implicitly migrated.

The stored authority-record digest becomes the routing prerequisite for every
following command. The steward then runs `ApproveReleaseCandidate` on the real
Production, processes the recoverable release projection, and runs
`ExportApprovedRelease`. Finally, create a post-approval backup, restore it into
another empty store with `_work/` unavailable, and verify export of the exact
approved package. A failure between cutover and approval is resumed in the new
application; it is not resolved by writing the legacy workflow.

If legacy material changes during shadowing, import it as new evidence or a
new edition and repeat the affected review. Never resolve authority by latest
filesystem timestamp.

### 17.4 Rollback

Before the cutover decision, rollback simply routes operations back to the
legacy workflow; the shadow store and immutable evidence are retained. After
cutover but before any subsequent canonical domain write, the steward may
record an explicit superseding migration decision and restore the prior route.

After the first post-cutover canonical write, rollback never makes legacy state
authoritative automatically. Recovery restores or repairs a verified new
store and resumes the command there. Returning authority to a legacy or third
system would require a separate approved supersession design, an exact export,
and an immutable authority-transfer record; the first slice does not provide
that command.

If an observed legacy path changes at any stage, its new bytes require a new
import batch and identity. A filesystem timestamp never updates existing
canonical evidence.

An already approved release remains an immutable historical decision. The
first slice does not model revocation; a need to revoke an approved release
requires a separate domain design.

### 17.5 Shared-site protection

The migration never writes to the repository's shared `site/` directory.
Review and release projections use digest-specific directories under
`.heritage-production/exports/`. This prevents the existing conflicting
site builders from overwriting one another.

## 18. Definition of done

The first slice is complete only when all of the following are true.

### 18.1 Functional completion

The steward can use only the new CLI to:

- create and inspect the pilot Production;
- register and verify its source;
- import the ASR proposal package;
- create and compare immutable editions;
- export and import a versioned review;
- accept/reject findings;
- create a successor edition with correct lineage;
- close a review;
- inspect release-policy eligibility;
- assemble and approve a release candidate;
- export the approved release package;
- inspect the complete provenance and decision history.

### 18.2 Integrity completion

- Every canonical artifact is content-addressed.
- Every sealed manifest recomputes to its recorded digest.
- No review targets a stale or ambiguous segment revision.
- The approved package exactly matches its approval.
- Repeating any completed import or content-producing command is idempotent.
- Backup and restore verification succeeds.
- The copied restored store can export the approved transcript without the
  original legacy paths.

### 18.3 Quality completion

- Domain, application, adapter-contract, architecture, and end-to-end tests
  pass.
- Fault-injection tests prove atomic storage and retry behavior.
- The integrity report contains no unresolved blocking issue.
- The pilot's release policy reports eligible before approval.
- The final approval was an explicit steward command.

### 18.4 Migration completion

- The new application has not written any byte in the pre-recorded legacy
  migration evidence set; separately observed external changes are reported as
  new evidence rather than attributed to the application.
- The authority decision for the pilot Production is explicit,
  content-addressed, and enforced by routing and canonical-write markers.
- The shared `site/` output has not been touched.
- Other production workflows remain outside the new authority boundary.

## 19. Risks and mitigations

| Risk | Mitigation |
|---|---|
| DDD becomes excessive for a solo tool | One process, one database, one bounded context, six roots, no broker/full CQRS/event sourcing |
| Production becomes a god aggregate | Store only lifecycle, exact references, small append-only sign-off/candidate records, and approval on Production |
| Large transcripts or review sets cause locking | Sealed edition manifests, independent ReviewFinding roots, read models, optimistic versions |
| Legacy evidence is attached to wrong media | Require source, artifact, edition, and revision digests; quarantine ambiguous imports |
| Browser review state becomes authoritative | Require explicit package export and validated application import |
| Candidate changes after review | Exact edition binding and mandatory new review for every successor |
| Policy changes during approval | Bind an immutable policy-version ID and digest |
| Crash loses an important event | Aggregate and local outbox row commit together; handlers are idempotent |
| Disk use grows during migration | Import one production, deduplicate by digest, preflight space, use incremental backup |
| SQLite writer contention | Single-steward workflow, short transactions, optimistic versions, WAL, busy timeout |
| Sensitive media is exposed by a static site | Offline review first; no hosted privacy claim; authenticated hosted design required later |
| Legacy subprocess mutates shared directories | Isolated staging and allowlisted adapters; validate before promotion |
| Scope expands into cloning/restoration/narration | Explicit non-goals and separate future design gates |

## 20. Future extension rules

The architecture is intentionally extensible without prebuilding future
features.

- Restoration and narration start as separately designed modules only after
  their production language, artifacts, review gates, and release policies are
  approved.
- A module becomes another bounded context only when language, ownership, or
  lifecycle divergence justifies translation and eventual consistency.
- A hosted review service requires an authentication/privacy design before an
  adapter is added.
- A remote publisher requires provider-specific access, idempotency,
  verification, and rollback design.
- A message broker is introduced only if another process genuinely consumes
  durable events.
- CQRS is introduced only inside a context whose measured read/write needs
  diverge materially.
- Event sourcing is not a planned evolution path. Immutable editions,
  findings, policies, approvals, operation records, and domain-event audit
  already provide the required traceability.
- Release revocation, post-approval correction, and multiple releases from one
  intended deliverable require explicit new domain decisions rather than
  weakening the at-most-one terminal approval invariant.

## 21. Implementation boundary

This document approves architecture and behavior, not implementation.

Implementation begins only after the user reviews this written specification.
The next artifact will be a separate, test-driven implementation plan that
names exact files, migrations, commands, tests, checkpoints, and incremental
commits.
