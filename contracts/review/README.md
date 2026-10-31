# The review format

**Adopted by `lecture-archive` on 29 October 2026 ([ADR-0016](../../docs/decisions/0016-lecture-archive-publishes-the-review-format.md)). Packages have been published since 30 October 2026, so the format changes only by the versioning rules below.**

**This folder holds only the agreement between `lecture-archive` and `review-assistance`.** `lecture-archive`'s own notes are kept outside it, in [`docs/review-packages.md`](../../docs/review-packages.md): how it builds, publishes and imports packages, which packages it has published and their hashes, and its open questions on building stops (Mukul, 31 October 2026). So a change to those notes never makes the app's copy differ.

`lecture-archive` owns this format (agreed 29 October 2026) and publishes it from this folder. It began as `review-assistance`'s draft, written from the reviewer's side; [the changes made on adoption](#changes-made-on-adoption) are listed at the end. `review-assistance` keeps a pinned copy of this folder, with a test that fails if its copy differs. Its `contracts/review.pin.json` names the commit the copy was taken from and every file's SHA-256. That file is the record of which version of this folder the app understands; no note is, this README included.

In this repository the schemas are checked with Python `jsonschema` 4.23.0 and the rules below by [`scripts/review_contract.py`](../../scripts/review_contract.py); [`tests/review_contract/`](../../tests/review_contract/) runs every example.

## What is here

| File | What it is |
|---|---|
| [`lecture-review-package.schema.json`](lecture-review-package.schema.json) | What `lecture-archive` publishes for one lecture: everything a reviewer sees |
| [`review-answers.schema.json`](review-answers.schema.json) | One answer record. The app exports these, one per line. |
| [`accepted-answers.schema.json`](accepted-answers.schema.json) | The app's list, sent with each export, of the answer that counts for each stop |
| [`review-results.schema.json`](review-results.schema.json) | A sketch: the per-language results `lecture-archive` publishes back |
| [`examples/`](examples/) | Golden examples. [`examples/index.json`](examples/index.json) says what each one must do. |

A *schema* is a machine-checkable description of a file: which fields it must have and which values they may take. Both projects check every file against the same schema: Python with `jsonschema`, TypeScript with Ajv. The schemas use JSON Schema 2020-12.

## How the files move

1. `lecture-archive` builds a package for a lecture and publishes it to private cloud storage.
2. The app shows the package's stops to a signed-in reviewer. Each answer becomes a record in the app's own database. The app exports to `exports/` in pairs. One file holds every record for the lecture so far, as JSON Lines (a text file with one record per line). The other is the app's list of which answer counts for each stop.
3. `lecture-archive` checks both files and applies the answers the list names. It builds the checked text, measures each language, and publishes a results file. The app displays it.

**The app does no language processing.** Everything it shows comes precomputed in the package: which words differ, each word's language, and where a verse was matched. A typed fix is stored exactly as typed, after Unicode NFC normalisation and nothing else. (NFC is the standard way of storing accented letters, so that "ā" is always the same bytes.)

## The lecture review package

The package holds, in order:

- **Lecture:** its id (the slug), the title as reviewers see it, and its length in seconds. The length is the decoded length, which agrees with the aligner. It is never the MP3 header's figure, which is wrong for some originals.
- **Audio:** the original recording's SHA-256 fingerprint and object name, `audio/<sha256>.mp3`. Then the listening copy: its object name, `listen/<original-sha256>-cbr128.mp3`, its own hash and its length. If there is no listening copy, this is `null` with a reason. Object names are inside the private bucket `gs://ssggsm-seva-media`. They are never web addresses, and the app streams audio only to signed-in reviewers.
- **Package and producer:** the package id (`<lecture>/v<version>`), the version number and the publishing time. Also the producer's Git commit, and every input file with its hash, so each stop can be traced back to its data.
- **Alignment check:** `passed`, `failed` or `not-checked`. This records whether the word timings passed `lecture-archive`'s placement check over the whole lecture. An alignment score is not a check. For anything other than `passed`, the app tells reviewers "word timings not yet checked". **Passing does not mean every word is in place.** BG 3.37 (Brisbane) passes at 1.05 against a limit of 1.5, and still has 20 stretches (112 s) where published words sit more than a second from where ElevenLabs heard them, one by 22 s. `lecture-archive` takes those stretches out of the trustworthy spans before building any stop, and `detail` says how much was taken out.
- **Trustworthy spans:** where the published transcript can be trusted, words and timings both. Word comparisons happen only inside these. A lecture's time therefore falls into three kinds: trustworthy spans; untranscribed stretches; and stretches where the published transcript has words but they cannot be trusted there. The third kind is not marked on screen. Only ElevenLabs's words are shown there, and its stops are single-version.
- **Untranscribed stretches:** audio the published transcript has no words for. The app marks them and never labels them, not as kirtan or as anything else.
- **Transcript**, for "listen through" mode: every word, with its start, end, language and source, and the stop it falls in, if any. Inside trustworthy spans these are the published words; elsewhere they are ElevenLabs words. Speaker labels and bracketed notes are already removed. The real Brisbane package's 5,953 words come to 1.74 MB as written (one field per line), or 0.16 MB compressed.
- **Stops**, in timeline order.

Each stop has:

- a stable **id**, `<lecture>#<serial>`. The serial is not the stop's position, and reviewers never see it; they see "Stop 41 of 312".
- a **kind** and one **language**. English, Sanskrit, Bengali and Odia are always separate. `unknown` means nothing measured the language: every word only ElevenLabs has is `unknown`, because its plain spellings carry none of the editor's diacritics to read a language from. Results report `unknown` as a language of its own and never fold it into another.
- **start** and **end**, and a **context**: the clip, a few seconds either side and always inside the recording;
- its **versions**, one per source. Each version has a few words before, the words in question with their timings, a few words after, and the positions of the words that differ, for highlighting.
- for verse checks, a **verse**: the suggested reference (such as `SB 1.2.10`), the printed text, the printed words, and `lecture-archive`'s suggestion of which printed words were actually recited.

### Kinds of stop

| Kind | The reviewer sees | Answers |
|---|---|---|
| `word-disagreement` | Two versions as A and B, in random order, with the differing words highlighted | A or B (`chose-version`), both are right (`both-right`), typed fix, can't tell, not the lecturer, I don't know this language |
| `single-version` | One text: only ElevenLabs has words here | Correct as heard (`confirmed`), typed fix, can't tell, not the lecturer, I don't know this language |
| `agreement-sample` | One text, shown exactly like a single-version stop | The same as a single-version stop |
| `verse-check` | The words heard, and the suggested printed verse with its reference | This is the verse, ticking the printed words actually recited (`verse-confirmed`); a different verse; not a verse; can't tell; not the lecturer; I don't know this language |

Four choices to note:

- **Reviewers see each stop's language and can correct it** (Mukul, 30 October 2026). The label is `lecture-archive`'s guess, and the guess is measurably imperfect: before 30 October it called 7 of 12 Bengali verse checks Sanskrit, and it has no Odia at all. Reviewers and the producer are a feedback loop, so on any stop a reviewer may say which language was actually spoken (`spoken_language`). It never repeats the stop's own label (A9). It sits beside the answer and does not replace it. "I don't know this language" with `spoken_language: odia` is a useful answer: the reviewer recognised Odia but cannot check it. `lecture-archive` collects the corrections as a test set for its language rule, the way `verse_truth.json` is the test set for verse matching. One answer never relabels a stop.

- **Spelling-only differences get "both are right"** (agreed 29 October 2026). The two versions may differ only in spelling, such as Kṛṣṇa and Krishna, or Śrīla and Srila. The app cannot tell which differences are spelling only, because it does no language processing, so the answer is offered on every word disagreement and the reviewer judges. `lecture-archive` decides which spelling goes into the checked text. Neither version counts as wrong for that stop.
- **Agreement samples show one text.** The requirements say they appear like any other stop. Showing two identical versions as A and B would give them away, so the app shows them like a single-version stop. That is why there is a `confirmed` answer beside `chose-version`.
- **A verse is never pasted in whole.** The package carries only the printed portion the match covers. Only the words a reviewer confirms as recited count as spoken text. Reviewers start with no words ticked (agreed 29 October 2026). The package keeps `lecture-archive`'s suggestion of which words were recited, but the app neither shows it nor pre-ticks it.

### Keeping the order blind

- The package labels every version with its source. The app never shows that label. It shuffles A and B, and records the order it showed (`shown_order`), so `lecture-archive` can check that the blind order worked.
- The supervisor's settling and spot-check screens are blind in the same way (agreed 29 October 2026), so `shown_order` is recorded on every record.
- In "listen through" mode the transcript would give the answer away, because inside trustworthy spans it is the published text. So each transcript word names its stop, and the app hides a stop's words until that stop is answered.
- A known limit: single-version stops lie outside trustworthy spans, mostly in untranscribed stretches, which are marked on screen. Agreement samples lie inside trustworthy spans. A reviewer who watches the marking could tell the two apart.
- Another: agreement samples need both versions to be exactly the same text, punctuation included, because the app shows them as one. The published text writes Indic words in IAST and ElevenLabs does not, so in practice every agreement sample is English: all 23 in the Brisbane package are. For Indic words, agreement is the spelling-only word disagreements, which reviewers see anyway (42 of Brisbane's 86 Sanskrit stops).
- Another known limit: spelling style can give the source away. The published text uses IAST (Kṛṣṇa, Śrīla), while ElevenLabs writes plain spellings (Krishna, Srila), so on such stops a reviewer can guess which version is published.

### When there is no listening copy

The format allows a package whose lecture has no listening copy yet. Such a package has `"listening_copy": null` and a `listening_copy_missing` reason (`failed-length-check` or `not-made-yet`). [The example](examples/valid/package-arrival-from-bali-no-listening-copy.json) shows `arrival-from-bali-…` as it stood before its copy was uploaded.

**Agreed (29 October 2026):** the app accepts such a package but does not offer the lecture to reviewers until a listening copy exists. Browsers start clips seconds off when seeking in the original variable-bitrate MP3s.

## The answers file

- **One record per line, never changed.** The app writes records and never edits or deletes one.
- **Each export is complete.** It holds every record for the lecture so far, so an export and its list stand on their own.
- **Each record stands on its own.** It repeats the lecture, the stop, the package's id, version and SHA-256, the original audio's hash, and the stop's interval. It stays meaningful even if the package is lost.
- **Who:** `by` holds a stable id and a role: `reviewer`, `supervisor` or `owner` (Mukul). The Google account behind the id stays in the app's own database; exports never carry an email (agreed 29 October 2026).
- **Effort:** `active_seconds` is the time actually spent on the stop. The optional `clip_played_seconds` shows when a clip was never played; a larger number does not prove anyone listened.
- **Changing an answer:** the new record names the one it replaces in `supersedes`. The old record is kept. Only the same person can replace their own answer.
- **Flagging:** a reviewer can add `flag` to ask the supervisor to look at a stop.
- **The supervisor's records:**
    - `adjudication` settles a stop. `reviews` names the record being settled, and `answer` holds the final answer. The answer may be `escalated`, which passes the stop to Mukul. Mukul settles it with an adjudication whose role is `owner`.
    - `spot-check` checks a randomly chosen answer. `reviews` names that answer. The outcome is `agree`, or `corrected` with the right answer. These outcomes are the only measure of reviewers' accuracy, because no stop is reviewed twice.

### Which answer counts

One answer per stop is accepted. **Only the app decides which** (agreed 29 October 2026). It sends its decision with each export as a list (see the next section). `lecture-archive` applies the list and never works it out again. So the rule lives in one program, in the context that owns adjudication, and changing it later (for example, to add a second reviewer) touches only the app.

The app's rule: superseded records are ignored. Then:

1. If Mukul has settled the stop, his newest record counts.
2. Otherwise, the supervisor's newest adjudication counts. If it is `escalated`, the stop waits for Mukul.
3. Otherwise, if the supervisor spot-checked the reviewer's current answer: with `corrected`, the supervisor's answer counts; with `agree`, the reviewer's answer counts and is marked as checked.
4. Otherwise, the reviewer's newest answer counts. The exceptions are "can't tell", "I don't know this language" and any flagged answer: those send the stop to the supervisor.

A "can't tell" that counts settles the stop with no text. Only `chose-version`, `both-right`, `confirmed`, `typed-fix`, `not-lecturer` and `verse-confirmed` give `lecture-archive` something to apply. `verse-different` and `not-a-verse` close the verse check, and `lecture-archive` may ask again in a later package.

The steps give the stop states in `review-assistance`'s system design, section 7. Steps 1 and 2 give `settled`, step 3 gives `checked`, and step 4 gives `answered`. A stop waiting for the supervisor or for Mukul is `needs-decision`, and a stop with no answer yet is `open`.

### The answers that count

With each answers export, the app writes `exports/<date>/<lecture>.accepted.json`. It names the package, and the answers file it goes with, by hash and record count. Then it lists every stop in the package, in order, each with:

- its **state**: `open`, `answered`, `checked`, `needs-decision` or `settled`;
- the **record** that counts, or null while the stop is open or needs a decision.

`lecture-archive` reads the named record's own answer to see what to apply. See [the example](examples/valid/accepted-bg-3-37-brisbane.json): stop #0176 is flagged, so it is `needs-decision` and names no record.

## The results file (sketch)

The results file lists the package and the export it read (the answers file and the app's list), with their hashes. `applied` names the records `lecture-archive` applied, so the app can compare them with its own list and show the supervisor any mismatch. For each language separately, it gives:

- the stops applied;
- the words checked, and the share of the lecture's words that are now checked;
- for each source, the errors and the accuracy (null while there are too few checked words to say);
- the agreement-sample results, kept separate.

`lecture-archive` decides how these numbers are computed. The app only shows them in plain words, such as "English: 96 in 100 checked words right; 12% of the lecture checked".

## Rules the schema cannot check

JSON Schema checks each field by itself. It cannot compare one field with another, so these rules must be checked in code on both sides. A file that breaks one is refused. Each rule has a stable id, which the invalid examples refer to.

**Package**

| Rule | What it requires |
|---|---|
| P1 | Every time is between 0 and `lecture.duration_seconds`. |
| P2 | Stops, clips, spans and stretches run forwards (start before end). A word's start is not after its end. A word's start and end are either both times or both null; null is allowed only for a published word the alignment could not place: the version's or the transcript word's source must be `published`. |
| P3 | A stop's clip covers the stop: `context.start` ≤ `start` and `end` ≤ `context.end`. |
| P4 | Stops are in timeline order (by start, then end). Trustworthy spans are in order and do not overlap; neither do untranscribed stretches, and no untranscribed stretch overlaps a trustworthy span. Timed transcript words are in time order. |
| P5 | `package.id` is `<lecture.id>/v<version>`. Every stop id starts with `<lecture.id>#`, and no two are the same. Every stop a transcript word names exists. |
| P6 | The original's object name contains its hash. The listening copy's name contains the original's hash. The copy's length is within 0.05 s of the original's. |
| P7 | At most one version per source. Every `differs` position lies within that version's words. An agreement sample's versions have the same words; a word disagreement's do not. |
| P8 | Every `recited` position lies within `printed_words`. |
| P9 | All text is in Unicode NFC. |
| P10 | Every timed word in a version lies inside the stop's clip. |

**Answers** (checked against the package they name)

| Rule | What it requires |
|---|---|
| A1 | The record matches its package: the package's id, version and SHA-256, the lecture, an existing stop, the original audio's hash, and the stop's exact interval. |
| A2 | The answer fits the stop. Kinds are as in the table above, and `escalated` is for supervisors only. `chosen_source` and `shown_order` name only the stop's own sources, and an answer to a word disagreement was given after seeing every version. `recited` positions lie within the verse's printed words. |
| A3 | `supersedes` names an earlier record by the same person, for the same stop and of the same type. No record is superseded twice. |
| A4 | `reviews` names an earlier record for the same stop. A spot check reviews an answer. An adjudication reviews an answer, or an escalation. |
| A5 | No one changes an answer after it has been settled or spot-checked. The app enforces this by locking the stop. |
| A6 | No two records share an id. Each export repeats every record so far, so the same id always holds the same, unchanged record. |
| A7 | Typed text, notes and typed references are in Unicode NFC. |
| A8 | No record is earlier than its package's publishing time. |
| A9 | `spoken_language`, when given, is not the stop's own language: it is a correction. |

**Answers that count** (checked against the package and the answers file)

| Rule | What it requires |
|---|---|
| C1 | The list names the same lecture and package as the package file, and the answers file's SHA-256 and record count. |
| C2 | Every stop in the package appears exactly once, in the package's order, and no other stop appears. |
| C3 | Every record it names is in the answers file, answers that stop, and has not been replaced by a later record. A carried-over record may come from an earlier version of this lecture's package. |

`lecture-archive` checks that the list is complete and consistent. Whether the app chose the right record is for the app's own tests.

**Results**

| Rule | What it requires |
|---|---|
| R1 | `applied` lists exactly the records the app's list names whose answer gives text or a marking. The package, answers and list hashes match. |

Every rule is checked against the examples, but only P1, P4, A1, A3, C2 and C3 have their own invalid example so far. `tests/review_contract/` breaks each of the others once, in memory, on a copy of the valid example.

## Versioning

- **Every file names its format and version,** for example `"schema": "lecture-review-package/1.0"`.
- **A minor version (1.0 to 1.1) only adds:** a new optional field, or a new allowed value. Every 1.0 file is still a valid 1.1 file, so nothing published before needs to change.
- **A new major version (1.x to 2.0) is needed for anything that breaks.** That means removing or renaming a field, making an optional field required, narrowing the allowed values, or changing what a field means or its units. A new major gets a new schema file. Files already published keep their version and stay readable with the old schema.
- **Readers refuse what they don't know** (agreed 29 October 2026). Every object lists all its fields, so a reader refuses a newer minor version, with a clear message, until it is updated. It never silently ignores a field it doesn't understand.
- **A change the app must newly support goes in this order** (Mukul, 31 October 2026). This covers a new version of the format. It also covers anything new under the same version that the app has not handled before, such as the first republished package.
    1. `lecture-archive` writes the change into this folder, adds an example to `examples/` that uses it, and commits.
    2. `review-assistance` re-pins this folder at that commit. Its tests run every example, so they fail on the new one until the app supports it.
    3. `review-assistance` ships the support.
    4. Only then does `lecture-archive` publish packages that use it. Before it does, it reads the app's `contracts/review.pin.json` to confirm the pin is at that commit or a later one.

  The example is the handoff between the two sides.
- **Ids stay stable.** Lecture, stop, record and reviewer ids, and value words such as `published`, `sanskrit` or `chose-version`, never change meaning and are never reused. A stop keeps its id across package versions while it asks the same question, and small timing shifts keep the id. If what it asks changes (its kind, language, versions' words or verse), it gets a new id and the old one is retired.
- **Answers carry over** (agreed 29 October 2026). When a republished package keeps a stop's id, the stop's earlier records still apply and the reviewer is not asked again. Stops new in that version start open. Stops it drops are retired, and their records stay in the history. No example covers a republished package yet.
- **Answers are never rewritten.** After a major change, `lecture-archive` translates old answers when it imports them. The stored records stay as they were written.
- **Until the first package was uploaded,** the format was edited in place and stayed at 1.0 (0.1 for the results sketch), because no published file could depend on it. That ended on 30 October 2026. Every change now follows the rules above. Major version 0 means the results shape may still change.

## The examples

[`examples/index.json`](examples/index.json) lists every example and what it must do: be valid, fail the schema, or fail a named rule. Both sides' tests can run through the same list.

- **Real excerpts,** copied read-only from `lecture-archive` on 29 October 2026, for BG 3.37 (Brisbane): word text and timings from the alignment and ElevenLabs files, the trustworthy spans, the SB 1.2.10 verse match, the original audio hash, the listening copy's hash (from `manifests/media-v2.json`), and the input hashes.
- **Illustrative, not computed by `lecture-archive`:** which stretches form stops, the stop ids, every language label, the `differs` positions, the verse's word split and recited suggestion, the untranscribed stretches, the listening copy's length, the Git commits, every time of publishing or answering, every answer, and every number in the results. Words outside stops are marked `unknown` rather than guessed. `producer.notes` in the packages and the results, and `index.json`, say what is illustrative.
- The answers example holds the example package's real SHA-256. `.gitattributes` keeps these files' line endings fixed, so the hash survives a Windows checkout.

Adoption did not change the examples: their bytes, and so their hashes, are the draft's. Both sides run every example: `lecture-archive` in `tests/review_contract/`, with Python `jsonschema` 4.23.0 and `scripts/review_contract.py`; the review app in `src/contract/conformance.test.ts`, with Ajv 8.20.0 and its TypeScript rule checks.

## How lecture-archive builds a package

Not part of this agreement. Since 31 October 2026 it is in `lecture-archive`'s
[`docs/review-packages.md`](../../docs/review-packages.md), which the app does not copy. That page
also holds what has been published, with hashes, the builder's working defaults and the evidence
behind them.

## Changes made on adoption

For `review-assistance` to take into its pinned copy:

1. **`lecture-review-package.schema.json`: `producer.inputs[].role` gains `sarvam` and `media-manifest`.** The placement check reads Sarvam's output as well as ElevenLabs's, and the listening copy comes from `manifests/media-v2.json`. Both are inputs, so both must be traceable by hash. The change only adds values, so every existing example still validates.
2. **All four schemas:** the descriptions now say the format is published by `lecture-archive` and point at this README. Text only; no constraint changed.
3. **P2, untimed words:** the README already said that only a published word may be untimed. This repository checks it by the version's or the word's source. The app's `packageRules.ts` does not check the source yet.
4. **Alignment check and spans:** "passed" is the lecture-level check, not a promise about every word. Trustworthy spans already exclude misplaced stretches, which gives a third kind of time (see the package section).
5. **Language `unknown`:** what it means, why every ElevenLabs-only word carries it, and that results keep it separate.
6. **Agreement samples:** in practice they are English only, and why.
7. **Size:** the real package's size replaces the estimate.
8. **Versioning:** "until the first package is uploaded" replaces "while this is a draft", since no published file depends on the format until then.

9. **`review-answers.schema.json`: an optional `spoken_language` and rule A9** (30 October 2026, before any package was uploaded, so still 1.0). The app shows each stop's language and lets the reviewer correct it; see "Four choices to note". Two examples go with it: `valid/answer-language-corrected.json` and `invalid/answer-language-same-as-stop.json`.

The examples from the draft are unchanged, byte for byte. The two above are new.

**Proposed, not made, because they need Mukul or the app:**

- **An explicit field for misplaced stretches.** Today they are implied: neither a span nor untranscribed. With a field, "listen through" could say "timings doubtful here" instead of quietly showing ElevenLabs's words.
- **`verse.reference` can be a song title.** A KKSongs match cites the song (`Pranesvari Ei Bara Karuna Koro More`), not an address. The schema's examples show only addresses. Nothing breaks, but the app should not assume the shape.

## Open questions for Mukul

1. ~~**A lecture with no listening copy.**~~ Settled 29 October: hold it back until a copy exists.
2. ~~**Who is named in exports.**~~ Settled 29 October: a stable app id such as `reviewer-01`. The Google account is kept only in the app's database.
3. ~~**Verse checks: pre-tick the suggested words?**~~ Settled 29 October: start with none ticked.
4. ~~**Who decides which answer counts.**~~ Settled 29 October: the app decides, and sends the list with each export (option B).
5. ~~**Spelling-only differences.**~~ Settled 29 October: reviewers get a "both are right" answer. Still open: which spelling the checked text keeps, which is part of requirements question 4.
6. **One language per stop:** `lecture-archive` splits a passage where the language changes, so each answer counts toward one language. Built that way, with the two repairs described above. Agreed?
7. ~~**Strict versions.**~~ Settled 29 October: the app refuses a package with a newer minor version until it is updated.
8. ~~**Republished packages.**~~ Settled 29 October: answers carry over when a stop keeps its id.
9. ~~**The supervisor's screens.**~~ Settled 29 October: they hide which version is the published one too.

The open questions on how stops are built are `lecture-archive`'s own, each with a working default in its builder; they are in [`docs/review-packages.md`](../../docs/review-packages.md).

Still open on the app's side: where a stop goes after "I don't know this language" (`review-assistance` requirements question 3).
