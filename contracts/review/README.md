# The review format

**Adopted by `lecture-archive` on 29 October 2026 ([ADR-0016](../../docs/decisions/0016-lecture-archive-publishes-the-review-format.md)). The first five packages were published on 30 October 2026, built from commit `213f1d4`, so the format now changes only by the versioning rules below.**

| Published to `gs://ssggsm-seva-media/packages/…/v1.json` | Stops | SHA-256 |
|---|---:|---|
| `bg-3-37-the-duty-of-a-human-being-brisbane` | 640 | `bf4b32675e88bf44dea653b2547ccf35132366307789c32e794eb885b197b321` |
| `cc-adi-lila-7-114-why-lord-buddha-denied-veda-bhubaneswar` | 276 | `57b1d6baac8f9f3bc0993cbc136652518cce6dc44ee3da7b466ade8eb65643e4` |
| `cc-adi-lila-9-46-a-true-attitude-and-the-process-of-chanting-the-holy-name-bhubaneswar` | 726 | `89bf159b7bd112153018a6f5e56efe542dfb65c1f04ae89f8ae42a0efbefaf31` |
| `evening-darshan-about-bhubaneswar-temple-and-preaching-bhubaneswar` | 773 | `92bc9c74bf5cae99174b2f37a5e465301175ae94d0f9bf60f124bb5a39fd6af6` |
| `arrival-address-from-usa-no-question-of-disappointment-and-pessimism-in-mahaprabhu-s-line-bhubaneswar` | 143 | `f0e628204e2f3755ef2921a54d88bca23a9eccbc84b9b3c58c3b416d75bd2bf4` |

Until `review-assistance` takes this folder into its pinned copy, its schema refuses these packages: their `producer.inputs` use the roles `sarvam` and `media-manifest`, which its copy does not have yet.

`lecture-archive` owns this format (agreed 29 October 2026) and publishes it from this folder. It began as `review-assistance`'s draft, written from the reviewer's side; [the changes made on adoption](#changes-made-on-adoption) are listed at the end. `review-assistance` keeps a pinned copy of this folder, with a test that fails if its copy differs.

In this repository the schemas are checked with Python `jsonschema` 4.23.0 and the rules below by [`scripts/review_contract.py`](../../scripts/review_contract.py); [`tests/review_contract/`](../../tests/review_contract/) runs every example. Packages are built by [`scripts/review_package.py`](../../scripts/review_package.py).

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

Every lecture now has a listening copy, listed in `manifests/media-v2.json`. The format still allows for a missing one, for future lectures. Such a package has `"listening_copy": null` and a `listening_copy_missing` reason (`failed-length-check` or `not-made-yet`). [The example](examples/valid/package-arrival-from-bali-no-listening-copy.json) shows `arrival-from-bali-…` as it stood before its copy was uploaded.

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
- **Readers refuse what they don't know** (agreed 29 October 2026). Every object lists all its fields, so a reader refuses a newer minor version, with a clear message, until it is updated. It never silently ignores a field it doesn't understand. In practice: when the format changes, update the app first, then publish the new packages.
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

```
.venv/Scripts/python.exe -m scripts.review_package <lecture> --media-manifest <local copy of manifests/media-v2.json>
```

This builds one lecture's package from this repository's own tested code: `spoken_words`, the trustworthy spans, the placement check in `compare_hosted`, `read_along`'s word check, `indic_language` and the verse matches. It checks the package against the schema and P1 to P10, refuses to write one that fails, and writes it locally to `data/reference/review/packages/<lecture>/v1.json`. The listening copies come from a copy of the bucket's `manifests/media-v2.json` kept in `data/reference/review/manifests/`.

```
.venv/Scripts/python.exe -m scripts.review_publish <lecture> [<lecture> ...]
```

This uploads it to `gs://ssggsm-seva-media/packages/<lecture>/v1.json` (Mukul's go-ahead, 30 October 2026). Before sending anything it checks the file again: LF bytes only, the schema and P1 to P10, not a DRAFT, and the original and listening copy it names both in the bucket. A published package is never changed, because answers name it by its bytes. The same bytes again are left alone. Different bytes under the same name are refused, and the upload itself can only create (`--if-generation-match=0`). The object is read back and compared after upload. `import review answers` waits until the app produces real exports.

A package built from producer code with uncommitted changes says so at the start of `producer.notes` ("DRAFT, not for publishing"), because its `revision` would not contain the code that built it. The upload step refuses such a package.

**These choices are `lecture-archive`'s proposals to Mukul, not agreements.** Mukul ruled on 29 October 2026 that they are not to be settled on one lecture: `lecture-archive` decides them once four or five lectures have been reviewed (ADR-0016). The figures in the table are from the first real package, BG 3.37 (Brisbane): 640 stops for a 61-minute lecture.

| Question | What the builder does now | Why |
|---|---|---|
| What counts as a difference | Words are compared after the scorer's own `normalise` and folding, so contractions, numbers written as digits, punctuation and fillers are not stops | A corrector would not stop there, and the scorer does not charge them |
| How stops are grouped | One stop per differing phrase: a run of words that differ together. Phrases less than 1 s apart, in one language, are joined, up to 12 words a side. Larger ones are not asked, and the build lists them | Each stop should stay about ten seconds of work. Brisbane's median stop asks about 0.5 s of audio, mostly one word |
| Clip length | 3 s either side, always inside the recording; 6 context words either side | Enough to hear the word arrive. Median clip 6.8 s, longest 14.4 s, 80 minutes of listening in all |
| Language | A published word the editor wrote with diacritics is Indic. Sanskrit or Bengali comes from `indic_language` over the Indic words within six tokens. An unmarked word between two Indic words of one language belongs to them. A differing passage is split where the language changes. Words only ElevenLabs has are `unknown` | See the evidence below |
| Verse checks | Every match in `verse-runs.json` at its 0.25 gate that lies inside a trustworthy span. The differences inside a verse are not asked separately. Nothing below the gate is shown | A confidently wrong verse attributed to the teacher is worse than an admitted gap |
| Agreement samples | Six identical words. One sample for every 20 disagreements, aiming for at least 3. Out of earshot of every other stop: neither clip plays the other's words. Chosen at random with a seed taken from the lecture id, so a rebuild picks the same ones. On dense lectures there are fewer places than wanted: `arrival-address-from-usa` has none, `arrival-class` 7 of 19 | A small unmarked sample, as the requirements ask. Brisbane's first build put one 0.065 s after the `later`/`latter` stop, so its clip played that disagreement and its context words differed |
| Single-version stops | ElevenLabs's words outside every trustworthy span, broken at pauses over 1 s and at 12 words | A ten-second question |
| Misplaced words | The spans lose every stretch `read_along.word_check` finds misplaced. They also lose every stretch where a disagreement pairs words more than 1 s apart, which is the same fault in places the word check cannot measure. Then the comparison runs again | A stop built on misplaced words plays the wrong audio |
| Recogniser words with no real time | An ElevenLabs word lasting over 5 s is never part of a stop. Brisbane has one: `Kama.`, stretched across 55 s of chanting | It cannot be placed in a clip |
| Stop ids | Serial numbers in timeline order. Republishing, which must carry ids over, is not built, so the builder will not make a v2 | Ids must never be reused for a different question |

**Evidence on one language per stop.** The proposed rule works, but word-level labels needed two repairs, both found by reading the Brisbane stops:

- **Unmarked Sanskrit words.** `ca`, `ceha`, `iha` and `enam` carry no diacritics. Judged word by word, they are English, and SB 1.2.10 would be cut at `nārtho yaś | ceha | karmabhiḥ`. `verse_runs`'s own bridging rule keeps a single such word with its verse. Runs of two or more unmarked words (`viddhy enam iha vairiṇam`) and unmarked names (`Yudhisthira`) still come out English.
- **English votes.** The scorer's `compare_hosted.language_mask` lets every word in the window vote. English "more" is also the Bengali pronoun *more*, so two of the three words it called Bengali here were Sanskrit (`śreya`, `pūrṇa-vikacita-cetana`). In the package, only Indic words vote, and the one Bengali stop left is Bengali by reading (`'āmāra' bolite āre kichu nāi`). The same defect affects `compare_hosted`'s research figures; that is not changed here.

**Seven lectures, 29 October 2026.** Packages now build for every lecture that has both recognisers' output and passes the placement check: seven, 264 minutes of audio, 3,558 stops (13.5 per minute of tape) and 445 minutes of clips. `19941228-padayatra-arrival` is refused by the placement check, as it should be. What the six others showed, every figure counted from the packages:

- **Bengali labelled Sanskrit.** `indic_language` labels a line by two word lists and calls a tie Sanskrit. On the two Caitanya-caritāmṛta lectures, 8 of the 13 Bengali verse checks are labelled Sanskrit by reading. `uttama hañā āpanāke māne tṛṇādhama` matches neither list. In `jīvera nistāra lāgi' … māyāvādi-bhāṣya śunile haya sarva-nāśa`, *bhāṣya* is counted as a Sanskrit genitive in *-asya*, tying with *haya*. Odia has no list at all: `bhāvaku nikaṭa bhāvaku dura` comes out Sanskrit. This is the scorer's instrument, so its research figures share the fault; it is not changed here.
- **Indic word stops are mostly names.** 317 of the 538 Sanskrit or Bengali word disagreements are capitalised names inside English sentences, and 129 are `Kṛṣṇa` alone. 280 of the 538 (52%) are spelling only by the scorer's rule.
- **Words only ElevenLabs heard are mostly English.** 704 of the 789 `unknown` stops (89%) sit between two English words, and 105 hold `understand`: the lecturer's "Do you understand?", which the transcripts leave out.
- **One verse check is wrong by reading.** On `cc-adi-lila-7-114`, the song fragment `calo aiyo re` (KKSongs, *Calo Aiyo Re Syama Mere Palakana Pe*) is matched at margin 0.333 to the prose `Māyāvādī scholar, Sadānanda Yogīndra,`. It is left in the package, since "not a verse" is an answer the reviewer has, but `verse_truth.json` does not yet hold it.
- **Three builder faults, fixed with a test each:** an agreement sample within earshot of a disagreement (above); a transcript storing ṛ as r plus a combining dot, refused by P9 (`cc-adi-lila-4-256-258`); and the span-manifest guard comparing spans recomputed after `renumber` dropped editorial notes, which refused a current manifest (`cc-adi-lila-9-46`).

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
- **The media manifest records a listening copy's decoded length** only for the three lectures re-checked on 29 October. For the rest, the builder decodes the local copy itself, after checking its hash. Recording `copy_decoded_seconds` for every lecture would let packages be built without the audio on disk.

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

Also open, each now with a working default in the builder ([above](#how-lecture-archive-builds-a-package)):

- how stops are grouped, and how long a clip and its context are;
- which spelling the checked text keeps after "both are right";
- whether verse suggestions below the gate are left out (they are now) or shown;
- how agreement samples are chosen, and how many;
- whether spelling-only differences should be stops at all. On Brisbane they are 42 of the 86 Sanskrit stops, and the scorer already forgives them;
- whether words only ElevenLabs has should take the language of the published words around them, rather than `unknown`. There are 188 such stops on Brisbane, 72 of them a single word.

Still open on the app's side: where a stop goes after "I don't know this language" (`review-assistance` requirements question 3).
