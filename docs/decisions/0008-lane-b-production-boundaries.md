# ADR-0008 — Lane-B production keeps one narration job while separating authorization, artifacts, settings, and user entry points

**Date:** 2026-09-02 · **Status:** **Accepted 2026-09-02** · **Governs:** the
authorized SSGGSM/Odia/diary lane (ADR-0007 Lane B)
**Supersedes:** only (a) ADR-0006 §§2.3–2.4's single-profile configuration
shape, while retaining its accepted defaults and pinned-model rule; (b) ADR-0006
§7's statement that UI work is undecided; (c) ADR-0007 §3's `NarrationTake`
identity conflict row and closing aggregate/persistence-open statement, plus §7's
Lane-B aggregate-model non-decision; and (d) ADR-0005's CLI-only inbound-adapter
example for this context · **Superseded by:** —

Related: [ADR-0006](0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md)
selects the voice and delivery baseline; [ADR-0007](0007-two-policy-isolated-narration-lanes.md)
isolates Lane B from the future non-SSGGSM English/Hindi lane. The complete
workflow is in the
[Lane-B production design](../superpowers/specs/2026-09-02-cartesia-odia-narration-production-v2-design.md).

---

## 1. Context

The approved Instant Voice Clone is moving from Playground auditioning into a
repeatable production workflow. That workflow must preserve every generated take,
support native-Odia listening review, resume safely, assemble only selected takes,
and prove which text, voice, authorization and settings produced an artifact.

Several design questions were deliberately left open by ADR-0006 and ADR-0007. The
steward has now chosen:

- one `NarrationJob` aggregate, with the immutable-ledger/storage seam from the
  alternative take-ledger approach;
- separate fixed release constraints, adjustable delivery defaults and exact
  per-take settings;
- a separately managed authorization lifecycle rather than a mutable Boolean in
  every job;
- a private localhost website for the initial sole operator; and
- a login-based Odia-reviewer interface only when the workflow reaches publishing.

The initial operator and authorization steward are the same person. That does not
make identity or authorization implicit: evidence recorded now must still be
understandable when another reviewer joins later.

## 2. Decision

### 2.1 One production aggregate, not one object for every noun

Lane B has one production aggregate root: `NarrationJob`.

```text
NarrationJob
├── ReleaseSynthesisContract
├── ordered Passages
│   ├── current text revision
│   ├── GenerationAttempts
│   ├── immutable Takes
│   ├── append-only ReviewDecisions
│   └── append-only SelectionDecisions
├── immutable Masters
└── append-only MasterListeningDecisions referencing MasterId
```

The aggregate owns the rules that must be true together: passage order, current text,
take eligibility, review history, selected takes and master eligibility. `Passage`,
`Take`, review and master records are not separate aggregates in the first production
version. This avoids cross-aggregate coordination merely to decide whether one diary
can be assembled.

Audio bytes do not live inside the aggregate snapshot. A take refers to an immutable
artifact record containing a safe relative location, SHA-256, byte size and decoded
media facts. `TakeId` identifies the production attempt and its history; the audio
SHA-256 identifies the resulting bytes. Two attempts remain two takes even if their
bytes happen to match.

The repository persists the current job snapshot together with append-only ledger
entries and immutable artifact records. This is a **storage and audit seam**, not a
second narration aggregate and not event sourcing. Domain commands still load and
save a `NarrationJob`; the ledger makes completed attempts and decisions recoverable
and allows audit storage to evolve without changing the aggregate boundary.

### 2.2 Split synthesis configuration by responsibility

The former all-purpose “profile” becomes three concepts:

| Concept | Meaning | Change rule |
|---|---|---|
| `ReleaseSynthesisContract` | The fixed Lane-B release envelope: authorized speaker/voice binding, `language=or`, dated model/API snapshot and canonical output format. | The contract is immutable for one job; changing it starts a new job. |
| `DeliveryControlDefaults` | Operator defaults for request-scoped delivery controls: initially `speed=0.90`, `volume=1.00` and `emotion=calm`. | May be revised; only future takes resolve against the new defaults. |
| `EffectiveTakeSettings` | The exact fully resolved request used for one take, including its dictionary binding and whether each overrideable value was inherited, explicitly set or explicitly omitted. | Immutable once generation starts. |

ADR-0006's preferred values and dated-model pin remain accepted. This decision changes
their shape, not their values. A default is never re-applied retrospectively to an
existing take.

A passage text change retains its historical takes but makes those takes
**text-stale** for that passage. Dictionary-default/remap eligibility is specified in
the proposed v2 design rather than fixed as an additional accepted lifecycle rule here.

### 2.3 Authorization has its own lifecycle and owner

`AuthorizationRecord` is a small, separate aggregate within the Narrator Voice
context. It exists because a grant can be recorded, narrowed or withdrawn independently
of any one diary job and the local UI will manage that history.

- SSGGSM is the source of the permission recorded for the present scope.
- The steward records the attested grant and later status changes; initially one
  locally configured stable `ActorId` is bound as the authorization steward.
- The software does not grant permission. It reads the recorded status and enforces it.
- The canonical authorization record and private evidence stay outside Git.
- Status and scope changes append history; they never rewrite an earlier grant,
  snapshot, take or review.

Only the bound authorization steward may append the initial status/scope and later
reported changes. This is enforced by the application/domain boundary, not merely
hidden in an administration screen. The exact transition vocabulary and reauthorization
semantics remain part of the proposed v2 implementation design.

Every job and take stores an immutable `AuthorizationSnapshot`: the record identity,
observed revision/digest, relevant scope and observation time. The stored snapshot is
not treated as current truth. Before generation, assembly and delivery, application
handlers consult an `AuthorizationStatusReader`. Unavailable, withdrawn or
out-of-scope status fails closed for those operations. Historical audio remains
auditable and may be listened to locally; it does not silently regain release
eligibility.

The exact private schema, evidence-retention policy and provider-call race protocol
remain implementation-design choices. Whatever protocol is chosen must not claim that
a local withdrawal can recall a request already transmitted to a provider; a returned
artifact in that race is preserved as evidence and treated as ineligible pending a
valid decision.

### 2.4 Local operator UI now; authenticated reviewer later

The first inbound adapter is a private web console bound only to the local machine. It
supports the sole operator's complete workflow:

1. dashboard and job preparation;
2. cost preflight and take generation;
3. passage listening, operational review and explicit working selection;
4. draft/master assembly and final listening;
5. authorization-status administration; and
6. audit and integrity status.

The browser calls application use cases; it never edits `job.json`, authorization
records or ledger files directly. Browser `localStorage`, display names and request
payloads are not authority. The server resolves the configured stable `ActorId` and
records it on decisions. Provider credentials remain outside the UI. The linked v2
proposal supplies the concrete browser-origin/session safety requirements.

The initial operator may audition, compare, record operational decisions and build a
working master. The system does not infer from sole operation that this actor is a
qualified/native Odia release reviewer. ADR-0007's qualified-Odia release gate must be
satisfied by an explicitly attributed reviewer decision before publishing.

The first slice does not require a public URL, user database, cloud object store,
OAuth provider, worker queue or general web dashboard. Concrete web technologies are
an implementation-plan choice. A small CLI may remain as a secondary operational or
diagnostic adapter over the same use cases; neither adapter owns domain rules.

When the workflow reaches publishing, an authenticated qualified-Odia reviewer may
log in through a second adapter. Its accepted scope is listening, review decisions and
notes—not authorization administration or general TTS generation. Exact selection,
sign-off and release-role permissions, including the number of required qualified
reviews, are decided at that publishing trigger. Account-to-`ActorId` resolution and
remote storage/security are added then without changing existing domain commands or
historical actor identities.

This future portal does not itself authorize publication, distribution, a particular
reviewer, or synthetic-voice disclosure wording.

### 2.5 Lane isolation remains non-negotiable

One job declares exactly one ADR-0007 lane. Lane-B configuration cannot turn the
approved SSGGSM voice into an English/Hindi or arbitrary-text service. Lane A keeps
its opposite identity policy and remains future work.

The detailed classification of reusable mechanics is recorded in the
[shared-capability audit](../narrator-voice-shared-capability-audit-2026-09-02.md).
[ADR-0009](0009-share-narration-mechanics-not-policy.md) proposes the extraction rule;
it is not made accepted merely by this Lane-B decision.

## 3. Aggregate invariants

The implementation must assign these stable identifiers before tests are written:

| ID | Invariant |
|---|---|
| `INV-NJ-1` | Passage IDs and explicit order are unique inside one job. |
| `INV-NJ-2` | Every take binds the exact text revision, job/lane, release contract, effective settings, dictionary binding, authorization snapshot and artifact reference used. |
| `INV-NJ-3` | Take metadata and produced bytes are immutable; another render creates another `TakeId`. |
| `INV-NJ-4` | Editing passage text preserves prior takes but makes them text-stale. |
| `INV-NJ-5` | Review and selection decisions are append-only; only a take satisfying the current review/eligibility policy can be selected. |
| `INV-NJ-6` | A master uses exactly one selected, current and eligible take per passage, in manifest order; this does not by itself make the master publishable. |
| `INV-NJ-7` | Generation, assembly and delivery fail closed unless current authorization is readable and covers the operation. |
| `INV-NJ-8` | A job cannot change lane, speaker, voice, language or release contract identity in place. |
| `INV-NJ-9` | A recorded human decision is attributed to the server-resolved `ActorId`, never an actor supplied by the browser. |
| `INV-AR-1` | Grant identity/evidence digest and prior authorization history are immutable. |
| `INV-AR-2` | Only the record's bound authorization-steward actor may append a scope/status change; the change cannot rewrite historical snapshots. |

“Stale” is reserved for a text-revision mismatch. A take barred by authorization,
contract or dictionary eligibility is “ineligible”; this keeps the reason inspectable.

## 4. Evidence from the repository

| Observation | Consequence |
|---|---|
| `scripts/ggsm_transcription/store.py` demonstrates OS locking, monotonic revision, safe paths and atomic manifest replacement. | Treat these as implementation precedent to characterize with tests; expected-revision/CAS is a new Lane-B requirement, not an already proven extraction. |
| Existing narration/odia galleries demonstrate useful audio-player, compare, notes and whole-master review interactions. | Reuse their interaction ideas only. Their browser-local state and historical voice policies are not production state. |
| `scripts/hi/reconcat_diary.py` demonstrates ordered boundary trimming and fixed-gap concatenation but also performs model/data work at import time. | Extract and test narrow media mechanics; do not import the historical script as a production adapter. |
| The shelved `heritage_production` model separates opaque IDs from byte digests. | The distinction is correct evidence, but ADR-0001 still governs whether its trimmed kernel is lifted. Do not import the shelved application/review model. |
| There is no current web framework or database dependency. | A framework, database and deployment topology are implementation choices, not facts to smuggle into this ADR. |

## 5. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| Separate `Passage`, `Take`, `Review` and `Master` aggregates immediately | The first workflow is one operator producing one ordered diary. Assembly and selection would need cross-aggregate consistency without demonstrated concurrency or scale. |
| One `NarrationJob` including mutable authorization status | Authorization changes independently, can cover several jobs and has a different owner/source. Copying `active: true` into a job would become stale authority. |
| A separate immutable take aggregate/ledger as the source of truth | It improves audit storage but makes ordinary job decisions coordinate two models. The chosen seam retains its storage benefit without introducing another production aggregate. |
| One mutable synthesis profile | It cannot distinguish a release-breaking speaker/model change from an ordinary speed override and cannot reproduce the exact request used for an old take. |
| Continue with static HTML and `localStorage` exports | Cache clearing loses decisions, client values can be edited, actor identity is absent and state is not transactionally bound to exact audio/text. |
| Build authentication and the reviewer portal now | The sole-operator production stage does not yet have a second user. It would add account, role, deployment and storage decisions before their publishing trigger. |
| Give the future reviewer general generation or authorization administration | Listening review and stewardship are different authorities. Exact publishing sign-off/selection permissions remain a publishing-stage decision. |

## 6. Consequences

- The model remains small enough for one local operator, while its evidence is already
  actor-attributed for a later reviewer.
- Authorization and job updates are separate transactions. Application handlers must
  re-check current status at protected boundaries and define crash/race recovery
  honestly rather than pretending there is one global transaction.
- Real manifests, audio, authorization evidence, voice/provider identifiers and diary
  text remain private external data. Git contains code, schemas, redacted fixtures and
  policy documentation only.
- Takes are never overwritten. Defaults can evolve without rewriting history.
- The local website is an adapter over the hexagon. It does not move business rules,
  secrets or authoritative state into JavaScript.
- No production implementation, Cartesia call, publication or wider authorization is
  approved merely by accepting this architecture record.

## 7. Revisit trigger

Write a superseding ADR if any of these occurs:

- independent workers or concurrent reviewers make one `NarrationJob` a measured
  contention/transaction boundary;
- authorization becomes an organization-wide rights service with its own team or
  bounded language;
- a remote reviewer is required before the publishing stage;
- the reviewer needs generation, selection or release authority;
- a job legitimately needs to mix lanes, speakers, languages or release contracts; or
- three justified exceptions are needed to either the aggregate or UI boundary.

## 8. What this record does not decide

It does not select a Python web framework, database, remote host, identity provider,
concrete actor identifier, authorization transition/rebinding semantics, artifact
layout, backup/retention policy, exact
passage boundaries, mastering targets, reviewer identity, reviewer count, publication
authority or disclosure wording. It does not authorize a PVC, replace the approved
IVC, change Lane A, call Cartesia, or begin implementation.
