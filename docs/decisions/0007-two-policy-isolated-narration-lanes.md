# ADR-0007 — Narrator Voice has two policy-isolated lanes; authorized SSGGSM Odia does not replace non-SSGGSM EN/HI narration

**Date:** 2026-09-02 · **Status:** **Accepted 2026-09-02** · **Governs:** Narrator Voice policy scopes and the archive-rewrite clock trigger
**Supersedes:** only (a) ADR-0006's literal claim to supersede Programme 5's speaker/language description, (b) the SSGGSM `must-not-resemble` rule in the corpus-ledger design for the authorized SSGGSM/Odia/diary lane, and (c) ADR-0004 §5.1's phrase “first commit creating the new package,” as defined in decision 4 · **Superseded by:** —

---

## 1. Context

The 2026-08-26 programme table defined Programme 5 as a voice other than SSGGSM
for English/Hindi narration. Its Narrator model consequently put SSGGSM in a
`must-not-resemble` set and required a dissimilarity gate before publication. The
2026-07-10 handoff records the same historical constraint for Hindi diary narration
and English-to-Hindi dubbing.

ADR-0006 later accepted a different, deliberately narrow use: the approved Cartesia
Instant Voice Clone of SSGGSM speaking reviewed Odia diary narration. Its header said
that it superseded the speaker/language description of Programme 5. The steward has
now clarified that the non-SSGGSM English/Hindi programme remains active future work.
ADR-0006 therefore added a lane; it did not replace the older one.

The two lanes use opposite identity policies for the same named person. The technical
workflow can share code, but an unscoped rule such as “must not resemble SSGGSM” or
“SSGGSM clone allowed” would be wrong in one of the two lanes.

There was a second ambiguity. ADR-0006 says Narrator Voice does not consume the
archive rewrite's 35-day clock, while ADR-0004 started that clock with the first commit
creating the new package. Both contexts may eventually live below the same package, so
the original wording could let narrator-only work start a transcription-cutover clock.

## 2. Decision

1. Narrator Voice has two policy-isolated lanes:

| Lane | Identity policy | Permitted scope | Release authority |
|---|---|---|---|
| **A — future non-SSGGSM EN/HI narration** | SSGGSM must not be the output voice. The historical `must-not-resemble` policy remains. The alternate narrator, clone versus synthetic/preset voice, provider and final production gate remain to be selected. | English/Hindi narration only, subject to a later lane-specific production decision. | The historical donor-similarity plus SSGGSM-dissimilarity rule remains the baseline, not an implemented or newly approved release workflow. |
| **B — authorized SSGGSM Odia diary narration** | The already approved SSGGSM Cartesia IVC is allowed only under its attested scope. SSGGSM is not in a `must-not-resemble` set in this lane. The target is the closest faithful SSGGSM likeness the approved system can produce; no mathematical “100%” claim is made. | Reviewed Odia diary narration with `language=or`; no Hindi, English, other speaker, arbitrary script or distribution authority follows. | Qualified/native Odia listening approval is authoritative. Automated identity and speech metrics may inform review but cannot approve a release. |
| **Anything else** | No policy is implied. | Block pending a new decision and any required authorization. | None. |

2. ADR-0006 remains accepted for Lane B, but its literal claim to supersede Programme
   5's speaker/language description is superseded. It establishes the additional Lane
   B and does not alter or retire Lane A. The old corpus-ledger SSGGSM-dissimilarity
   rule remains applicable to Lane A and is inapplicable to Lane B.

3. Technical capability may be shared; policy may not leak. Shared, provider-neutral
   capability may include immutable artifact handling, content digests, locking and
   atomic replacement, media inspection, ordered assembly, review recording and a TTS
   transport port. It receives an already resolved lane-specific request. Shared code
   must not decide speaker authorization, permitted language/content, resemblance or
   dissimilarity criteria, or release eligibility. Cartesia request and SDK types stay
   outside the domain and application policy.

4. Narrator-only work does not start, consume or extend ADR-0004's archive-rewrite
   clock. For ADR-0004 §5.1, the objectively checkable start commit is the earliest
   commit whose tree contains both:

   - a production `.py` module other than `__init__.py` below
     `src/heritage_archive/contexts/archive/`; and
   - a test below `tests/heritage_archive/contexts/archive/` which imports or exercises
     that archive-context code and is collected without skipping.

   Documentation, package markers, architecture guards, shared code without an
   archive-context production module, and code used solely by either Narrator Voice
   lane do not start it. The trigger can be checked from a commit tree and that
   commit's test result without interpreting intent. ADR-0004's existing 2026-09-05
   start gate, 35-day duration and three end-of-box evidence clauses are otherwise
   unchanged; narration work neither satisfies nor postpones them.

5. Existing English/Hindi scripts are evidence and potential sources of small
   technical patterns, not a base to copy wholesale. The classified reuse decision is
   recorded in
   [the legacy narration reuse audit](../narrator-voice-legacy-reuse-audit-2026-09-02.md).

## 3. Conflict register and evidence

| Prior text | Conflict | Resolution in this record |
|---|---|---|
| Corpus-ledger design §2 calls Programme 5 non-SSGGSM EN/HI narration. | ADR-0006's header literally said it superseded that description. | That clause is superseded: Lane A remains active future work and Lane B is additional and narrower. |
| Corpus-ledger design §5.2 and §13 Increment 3 seed SSGGSM into `must-not-resemble`. | That rule would reject the authorized Lane-B voice by design. | Keep it for Lane A; explicitly disapply it to Lane B. |
| Corpus-ledger design §5.2 makes the produced-audio SHA-256 the `NarrationTake` identity. | The proposed Lane-B design distinguishes a production attempt/take from the bytes it produced. | Scope the old identity model to Lane A. Decide Lane B's aggregate and `TakeId` separately; this ADR does not pre-approve either shape. |
| July handoff says GGSM must not be reproduced. | Read without its later banner, it contradicts Lane B. | It remains historical authority for Lane A; ADR-0006/0007 are the narrow Lane-B exception. |
| ADR-0006 excludes Hindi/English from its authorization. | This might be misread as cancelling all Hindi/English narration. | It excludes them only from Lane B; it does not cancel Lane A. |
| ADR-0004 starts a 35-day clock with the first new-package commit. | Narrator-only code in the same package could start an archive cutover clock. | Only executable archive-context transcription-cutover implementation starts it. |
| Historical scripts contain both resemblance and dissimilarity automation. | Reusing a script by location could import the wrong identity policy. | Reuse only audited technical capability behind lane-specific policy. |

These are the documentation and legacy-policy conflicts found by the 2026-09-02
review. The aggregate boundary, persistence shape and implementation plan remain open;
they are not hidden conflicts resolved by this ADR.

## 4. Alternatives rejected

| Alternative | Why it lost |
|---|---|
| Treat ADR-0006 as retirement of non-SSGGSM EN/HI narration. | It contradicts the steward's confirmed continuing programme and erases useful prior work. |
| Put both lanes behind a generic `allow_clone` flag. | A Boolean cannot safely express speaker, language, content, authorization and release authority together. |
| Put each lane in a different bounded context immediately. | Both use the Narrator Voice language and can share provider-neutral production capability. Policy isolation is sufficient until the model's language actually diverges. |
| Copy the old Hindi workflow and reverse its similarity threshold for Odia. | It carries VoxCPM, transliteration, hard-coded paths and automatic identity decisions that do not match the approved Cartesia/native-Odia-review workflow. |
| Let Narrator Voice start ADR-0004's clock. | It evaluates narration work against unrelated archive transcription-cutover evidence. |
| Edit the older decisions as if they had always said this. | It would erase why each earlier decision was reasonable and violate the repository's ADR supersession discipline. |

## 5. Consequences

- Lane A remains active future work, but this record does not select its narrator,
  provider or implementation.
- Lane B retains every ADR-0006 restriction, including its exclusion of Hindi/English
  use and broader publication authority.
- A production request must declare one lane; one narration job cannot mix lanes.
- Tests must prove that Lane A cannot use the authorized SSGGSM IVC and that Lane B
  cannot be broadened to EN/HI or arbitrary text by a configuration override.
- Useful review UI and assembly/DSP patterns may be extracted from older scripts, but
  the old automatic resemblance/dissimilarity verdicts cannot cross the boundary.
- If the archive rewrite misses ADR-0004's unchanged 2026-09-05 start gate, ADR-0004
  must be revisited on its own terms. Narration work is neither compliance nor an
  extension.

## 6. Revisit trigger

Write a superseding ADR if any of the following occurs:

- a requested narration job cannot be assigned unambiguously to one lane;
- authorization is granted for SSGGSM output outside reviewed Odia diary narration;
- Lane A selects its narrator/provider and a concrete release gate;
- the two lanes develop different ubiquitous language or ownership, rather than only
  different policy values;
- a legitimate job needs to mix lanes; or
- shared capability requires three lane-policy exceptions, showing the boundary is
  wrong rather than the cases exceptional.

## 7. What this record does not decide

It does not authorize implementation or provider calls, choose the aggregate model,
approve a Cartesia Professional Voice Clone, choose an alternate narrator/provider for
Lane A, authorize Hindi/English output using the SSGGSM clone, settle publication or
disclosure wording, or create a third bounded context. It does not change ADR-0006's
accepted Odia baseline or ADR-0004's archive evidence and duration.
