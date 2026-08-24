# Heritage Production DDD First-Slice Implementation Plan

Date: 2026-08-24

Spec: `docs/superpowers/specs/2026-08-22-heritage-production-ddd-hexagonal-design.md`

Branch: `work/heritage-production-first-slice`

## Goal

Implement the approved transcript-reconstruction first slice as one local
Python 3.11 modular monolith with Clean Architecture, DDD, and Hexagonal
boundaries. The application must take a Production from exact source intake
through immutable transcript editions, offline review, policy eligibility,
explicit steward approval, deterministic local export, and verified
backup/restore. The August 21 workspace is the pilot, but its real cutover and
approval remain explicit steward gates after the software and rehearsal pass.

## Global constraints

- The design spec is binding when this plan is less specific or appears to
  conflict with it.
- Work only under `src/heritage_production/`, `tests/heritage_production/`,
  Heritage packaging/docs, and `.gitignore` unless the task explicitly says
  otherwise.
- Do not modify, move, delete, or make canonical writers of `_work/`, `site/`,
  `scripts/youtube_enhance`, `voice_lab`, cloning code, or existing media.
- Domain code imports only the Python standard library. Dependencies point
  `presentation -> infrastructure/application -> domain`; infrastructure may
  implement application-owned ports, and presentation never calls a
  repository directly.
- There are exactly six aggregate roots and repository ports: `Production`,
  `ASRProposalSet`, `TranscriptEdition`, `ReviewRound`, `ReviewFinding`, and
  `ReleasePolicyVersion`. Migration authority and operations are
  infrastructure records, not additional aggregates.
- One aggregate root is written per application transaction. Cross-root
  consistency uses exact IDs/digests and events, not multi-root mutation.
- No ORM, Alembic, pytest, Pydantic, Typer, import-linter, broker, full CQRS,
  event sourcing, hosted review, or remote publisher.
- Use `unittest`, stdlib AST architecture checks, real temporary SQLite/CAS
  adapter tests, and Hypothesis only for property/state-machine tests.
- Follow strict TDD for behavior: add one failing test, confirm the expected
  failure, write the minimum production code, confirm green, then refactor.
- Every task ends with focused tests and the complete Heritage suite. Existing
  repository tests must remain unchanged and pass at final verification.
- Normal tests are offline and require no private corpus, network, GPU,
  FFmpeg, ASR, or working DeepFilterNet runtime.

## Locked technical decisions

- Package root: `src/heritage_production/`; test root:
  `tests/heritage_production/`; console script: `heritage-production`.
- Runtime: Python `>=3.11`, setuptools, `cryptography==50.0.0` only.
  Development: `hypothesis==6.165.10`, `rfc8785==0.1.4` as an oracle, and
  `build==1.5.0`. Preserve all legacy requirements and commit a separate exact
  `requirements-heritage.lock.txt`.
- IDs are typed lowercase UUIDv4 strings generated only through `IdGenerator`.
  Times are positive UTC epoch microseconds. Spans are half-open.
- Manifest integers are limited to the I-JSON safe range. Floats, duplicate
  keys, lone surrogates, CR line endings, non-NFC strings, non-string keys, and
  unsupported values are rejected.
- Semantic hashes use lowercase SHA-256 of
  `{\"digest_schema\":...,\"schema_version\":1,\"payload\":...}`. Outer byte
  digests remain separate `ArtifactRef` values.
- SQLite uses foreign keys, WAL, `synchronous=FULL`, and
  `busy_timeout=5000`. Review submit/close serialization uses
  `BEGIN IMMEDIATE`.
- CAS location is `.heritage-production/objects/sha256/ab/<digest>`, with
  same-volume staging, durable flush, no-overwrite promotion, and verification
  before reuse.
- Deterministic archives use `ZIP_STORED`, sorted normalized POSIX names,
  fixed `1980-01-01 00:00:00` timestamps, mode `0o100644`, empty extras and
  comments, and a checksum member written last.
- ActorAuthority verifies externally produced Ed25519 proofs. The application
  never creates or stores private keys.
- CLI success is 0, including `eligible=false`; unexpected internal error is
  1; usage/validation 2; not found 3; stale/idempotency conflict 4;
  provenance/integrity/proof rejection 5; domain/policy refusal 6; and
  dependency/storage/export failure 7.

## Task 1: Foundation, packaging, and architecture firewall

Create the installable package and a thin CLI composition seam without domain
behavior.

- Add `pyproject.toml`, the `src` package skeleton, test packages, and the
  `heritage-production` console entry point.
- Add all approved top-level CLI command groups and `--store`,
  `--operation-id`, and `--json`. `--help` must not initialize a store.
- Add `.heritage-production/` to `.gitignore` and keep existing ignore entries.
- Add architecture tests that walk package imports with `ast`: domain
  standard-library purity; no inward layer importing an outward layer; no
  presentation repository imports; no imports from legacy/enhancement modules.
- Add a repository-interface allowlist test that becomes strict once the ports
  are introduced in Task 6.
- Record the approved design status and retain this plan.

Tests: first prove package/CLI/architecture tests fail against the absent
package, then make them pass. Run `heritage-production --help` through the
module entry point without requiring installation.

## Task 2: Shared domain kernel and canonical identity

Implement immutable shared primitives before any aggregate.

- Typed IDs/refs, `ContentDigest`, `ArtifactRef`, `TranscriptText`,
  `SourceSpan`, uncertainty spans/types, actor/credential refs,
  `PolicyEvaluatorRef`, assurance levels, domain errors, and domain events.
- Use frozen slotted dataclasses. Reconstitution and constructors must not
  silently generate IDs or times.
- Implement strict JSON parsing with duplicate-key detection and a stdlib-only
  canonical encoder with RFC 8785 UTF-16 key ordering for the supported subset.
- Implement semantic digest domain separation and exclusion of self-digest
  fields.
- Convert Decimal seconds with at most six fractional digits exactly to
  microseconds; finer input uses `ROUND_HALF_EVEN` and retains original
  evidence at the adapter boundary.

Tests: hand-derived canonical/digest vectors, RFC-oracle comparison when the
dev dependency is installed, duplicate/floats/surrogates/NFC/LF rejection,
emoji and combining-mark coordinates, span boundaries, safe integers, UUID
validation, and domain-event draining/reconstitution behavior.

## Task 3: Transcription aggregate roots

Implement `ASRProposalSet` and `TranscriptEdition` as provenance-bound sealed
roots.

- `ASRProposalSet.create` requires exact source binding, unique proposal
  identities and spans, raw evidence refs, provenance status, warnings, and
  steward attestation for `LEGACY_ATTESTED`.
- `TranscriptEdition.seal_initial` creates an ordered immutable segment
  revision manifest bound to source and proposal evidence.
- `TranscriptEdition.seal_successor` requires a parent digest and complete
  `EditionChangeManifest`; support unchanged, corrected, split, merge, manual,
  and accepted-finding lineage.
- Reject overlap, out-of-scope spans, undeclared gaps, empty text without a
  full inaudible mark, cyclic/ambiguous lineage, undocumented changes, and
  accepted findings without a revision or explicit `NO_EDITION_CHANGE`.

Tests: pure creation/rejection examples plus Hypothesis lineage/state tests and
a synthetic 2,000-segment seal/reconstitution fixture.

## Task 4: Review aggregate roots

Implement immutable findings and review-round lifecycle.

- `ReviewFinding.submit` binds exact round, edition, segment revision, rubric,
  spans, category/severity, observation, proposed change, actor claim, and
  submission evidence.
- `record_disposition` is append-only and permitted once; rejection requires a
  reason.
- `ReviewRound.open`, finalized complete/partial submissions, review sign-offs,
  and `close` freeze deterministic target/coverage/finding/sign-off evidence.
- A complete zero-finding submission remains explicit evidence. Closure is
  permanent and later finding/submission mutation is rejected.

Tests: target staleness, zero-finding coverage, partial coverage, proof
assurance, deterministic evidence ordering/digest, duplicate disposition, and
closed-round mutation.

## Task 5: Production and release-policy domain

Implement `ReleasePolicyVersion`, pure eligibility evaluation, and the
`Production` root.

- Seal normalized policy rules: required checks, permitted uncertainty,
  blocking finding types, required review/rights-holder gates, and exact
  evaluator ref.
- Evaluate immutable inputs without mutation and return every gate result.
- Production behavior covers creation, source attachment, selected
  edition/policy/gate set, external sign-offs, candidate snapshots, and one
  terminal approval.
- Changing a selection makes existing candidates inapplicable without
  rewriting history. Candidate/approval must bind the exact release-content,
  policy, gates, evidence, assessment, and package digests.
- Approval emits `ReleaseCandidateApproved`; reconstitution emits nothing.

Tests: gate thresholds, empty and configured gate sets, uncertainty blockers,
verified versus attested proofs, stale candidates, superseded snapshots,
single approval, and approval reachability state tests.

## Task 6: Application ports, commands, and first vertical workflow

Define application-owned ports and implement source/proposal/edition commands
against fakes before real adapters.

- Six repositories, `UnitOfWork`, `ArtifactStore`, metadata/derivation
  verifier, `OperationRecorder`, outbox, clock, IDs, actor authority, legacy
  translator, review/release renderer/parser/exporter, process runner, backup,
  integrity, authority, and read-service ports.
- Define every command named in design section 9.2 as immutable DTOs with
  OperationId, actor context, exact refs, and expected version where needed.
- Operation records hash a digest-free `heritage-command-<name>-v1` input
  manifest. Identical replay returns the original result; changed input under
  the same OperationId is a conflict.
- Implement `CreateProduction`, `AttachSourceRecording`,
  `ImportProposalPackage`, `CreateInitialTranscriptEdition`, selection,
  policy/gate/rubric/credential registration, and successor-edition handlers.
- Artifact promotion/validation precedes the one-root transaction; failed
  validation or optimistic conflict commits no aggregate change.

Tests: fakes verify one-root writes, no writes after rejection, operation
replay/conflict, source/proposal exact binding, and an August-21-shaped
sanitized fixture through selected edition.

## Task 7: SQLite, CAS, operations, and transactional outbox

Implement real local storage adapters and contracts.

- Four immutable checked migrations: infrastructure/Production,
  Transcription, Review, and Release. Historical checksum changes fail closed.
- Manual SQLite mappers and repositories for exactly the six roots;
  optimistic versions on mutable roots and update/delete triggers on sealed
  data.
- `SQLiteUnitOfWork` owns one connection and transaction. Aggregate state,
  operation result, canonical write marker when required, and emitted outbox
  events commit atomically.
- Implement streamed CAS ingest/open/verify with staging and orphan reporting.
  Reject traversal, links/reparse points, cross-volume staging, and corrupt
  existing objects.
- Implement outbox delivery status/attempts and unique per-handler delivery
  markers. Effects and marker commit in one immediate transaction.

Tests: all six repository contracts, migration replay/tampering, optimistic
conflict, sealed mutation triggers, CAS reuse/corruption/crash windows,
aggregate-plus-outbox atomicity, failed delivery, and idempotent replay.

## Task 8: Offline review workflow and deterministic packages

Implement review use cases and file adapters.

- `OpenReviewRound` verifies all target/derived artifacts before creating the
  round; never persist a half-open round.
- Render deterministic versioned review ZIPs containing `manifest.json`,
  `review-data.json`, local `index.html`, digest-named assets, and checksum
  evidence. Validate all archive names before reading or writing.
- Browser state is a draft only. Import validates the exported wrapper,
  package semantic digest, target identities, coverage, nonces, actor proof,
  and finding payload digests.
- Resume through durable import batches and nonce-to-canonical-ID mappings;
  submit each finding idempotently, then finalize under `BEGIN IMMEDIATE`.
- Implement finding disposition, review sign-off, closure, read views, and the
  full corresponding CLI commands.

Tests: byte-identical rebuild, traversal/case-collision/tamper, spoofed proof,
nonce replay/fork, complete zero-finding and partial submissions,
close-versus-submit concurrency, crash/resume, and successor review.

## Task 9: Release, signature verification, approval, and export

Implement the release path without remote publishing.

- Infrastructure Ed25519 verifier consumes a canonical
  `heritage-signature-v1` message binding semantic digest, actor, role, typed
  target ID/digest, operation kind, and schema version. Store public evidence
  only.
- Assemble sign-off-free release content; record compatible external
  sign-offs; assemble candidate; evaluate using the pinned evaluator; and
  require a separate approval command that reloads every exact input.
- Approval writes only Production and its `ReleaseCandidateApproved` outbox
  row in one transaction.
- The idempotent projection creates/stores the deterministic release archive.
  Local export verifies and copies those exact bytes and never rerenders.
- Source audio is excluded unless an explicit policy and rights decision
  includes it. No publishing port or command is added.

Tests: official Ed25519 vectors and replay-context mismatch, invalid gates and
proofs, incompatible evaluator, eligible=false success, blocked approval,
approval/outbox crash, deterministic projection, export retry, and exact
approved-byte digest.

## Task 10: Integrity, backup/restore, recovery, and authority routing

Implement operational safety and expose it through the thin CLI.

- Integrity checks foreign keys, CAS membership/hash/size, sealed semantic
  digests, lineage, review evidence, policy/candidate/approval/package links,
  incomplete operations, and failed outbox items.
- Backup uses `sqlite3.Connection.backup()`; membership comes only from the
  closed snapshot. Seal a full manifest. Incrementals contain a complete DB
  snapshot and objects missing from the verified parent chain.
- Restore only into an empty staging target and promote after full integrity,
  migration, evaluator, backup-chain, authority-chain, and object checks.
- Add retry/resume/rebuild/verify/quarantine/outbox replay/backup/restore CLI
  behavior without overwriting immutable evidence.
- Implement append-only `MigrationAuthorityRecord`, explicit shadow routing,
  unbroken predecessor-digest validation, atomic canonical-write markers, one
  Production cutover, and pre-first-write cutover supersession only.
- Add provenance, history, edition comparison, coverage, eligibility, and
  approval/export read views.

Tests: full/incremental chains, corruption/missing parent, snapshot under live
WAL writes, nonempty restore rejection, restore with `_work/` unavailable,
authority-chain tamper, shadow requirement, first-marker rollback boundary,
and CLI exit/error envelopes.

## Task 11: End-to-end hardening and release rehearsal readiness

Complete cross-cutting verification and documentation without performing the
real pilot cutover.

- Add four offline end-to-end scenarios: clean review to export; accepted
  finding to successor/new review/export; blockers then correction; and
  crash/retry import plus outbox with no duplicates.
- Exercise the 2,000-segment fixture through persistence/package rendering and
  record a reasonable single-steward performance budget without making timing
  assertions flaky.
- Add explicit fault injection at every named CAS/DB/import/outbox/backup/export
  boundary and deterministic archive golden rebuilds.
- Build wheel/sdist, install the wheel in a clean Python 3.11 environment, and
  run CLI help plus a synthetic full rehearsal/backup/restore/export.
- Update operator documentation with command sequence, stable exits, store
  layout, recovery procedures, pilot inputs, and the five mandatory steward
  gates.
- Confirm no tracked or untracked mutation under `_work/` or `site/`, and no
  changes to legacy/enhancement code.

Final commands include:

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s tests/heritage_production -t . -v
python -m build
heritage-production --help
```

The task ends with the software ready for Gate 1 shadow import. Real source
binding, edition confirmation, reviewer/gate configuration, cutover, and real
approval are not inferred or automated.

## Pilot gates after implementation

1. Shadow-import the August 21 evidence and pause for exact source/edition
   confirmation.
2. Require steward-supplied immutable policy, gates, rubric, credentials, and
   reviewer assignment before canonical review.
3. Approve only in an isolated `NON_AUTHORITATIVE_REHEARSAL` clone and verify
   an empty-target restore with `_work/` unavailable.
4. Present complete eligibility/restore evidence and require explicit steward
   authorization before the one-Production authority cutover.
5. Require another explicit steward command for real approval, then export,
   post-approval backup, empty-target restore, and exact-byte re-export.
