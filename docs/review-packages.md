# Review packages — lecture-archive's side

**What this is.** `lecture-archive`'s own notes on the review packages: how it builds, publishes
and imports them, what it has published, and the choices it is still making. **None of this is
part of the agreement with the review app.** The agreement is
[`contracts/review/`](../contracts/review/README.md), which `review-assistance` copies byte for
byte. This page is not copied, so changing it never makes the two copies differ.

Split out of `contracts/review/README.md` on 31 October 2026 (Mukul): that README had grown to
hold status and builder notes beside the agreement. The notes went stale, and every edit to them
changed a file the app pins.

## Where to check each side's state

Notes drift, and records don't. When this page, a handoff or a memory disagrees with one of
these, the record wins.

| Question | The record |
|---|---|
| Which version of the contract does the app understand? | `../review-assistance/contracts/review.pin.json`: the commit its copy was taken from (`source.commit`) and every file's SHA-256. `git diff <that commit> HEAD -- contracts/review/` shows what the app does not have yet. |
| What has been published? | The bucket, `gs://ssggsm-seva-media/packages/`. A package's SHA-256 is computed from its bytes. The table below is this repository's record of each upload. |
| What have reviewers answered? | The newest export folder in the app's exports bucket. Dev-project exports are trials. |

On 31 October 2026 the app's pin was `d95d285`, and every pinned file matched this repository
except the README.

## Changes that need the app

The order is part of the agreement: see "Versioning" in the
[contract](../contracts/review/README.md#versioning). In short:

1. Write the change into `contracts/review/` with an example that uses it, and commit.
2. The app re-pins at that commit; its tests fail on the new example until it supports it.
3. The app ships the support.
4. Only then publish packages that use it. First check the app's `review.pin.json` names that
   commit or a later one.

This covers a new format version and also anything new under the same version, such as the first
republished package (v2). Uploading a v2 before the app carries answers over would ask
reviewers the same questions again.

## Published packages

Built from commit `213f1d4` and uploaded on 30 October 2026:

| Published to `gs://ssggsm-seva-media/packages/…/v1.json` | Stops | SHA-256 |
|---|---:|---|
| `bg-3-37-the-duty-of-a-human-being-brisbane` | 640 | `bf4b32675e88bf44dea653b2547ccf35132366307789c32e794eb885b197b321` |
| `cc-adi-lila-7-114-why-lord-buddha-denied-veda-bhubaneswar` | 276 | `57b1d6baac8f9f3bc0993cbc136652518cce6dc44ee3da7b466ade8eb65643e4` |
| `cc-adi-lila-9-46-a-true-attitude-and-the-process-of-chanting-the-holy-name-bhubaneswar` | 726 | `89bf159b7bd112153018a6f5e56efe542dfb65c1f04ae89f8ae42a0efbefaf31` |
| `evening-darshan-about-bhubaneswar-temple-and-preaching-bhubaneswar` | 773 | `92bc9c74bf5cae99174b2f37a5e465301175ae94d0f9bf60f124bb5a39fd6af6` |
| `arrival-address-from-usa-no-question-of-disappointment-and-pessimism-in-mahaprabhu-s-line-bhubaneswar` | 143 | `f0e628204e2f3755ef2921a54d88bca23a9eccbc84b9b3c58c3b416d75bd2bf4` |

On 30 October 2026 every lecture had a listening copy, listed in `manifests/media-v2.json`.

## Building, publishing and importing

```
.venv/Scripts/python.exe -m scripts.review_package <lecture> --media-manifest <local copy of manifests/media-v2.json>
```

This builds one lecture's package from this repository's own tested code: `spoken_words`, the trustworthy spans, the placement check in `compare_hosted`, `read_along`'s word check, `indic_language` and the verse matches. It checks the package against the schema and P1 to P10, refuses to write one that fails, and writes it locally to `data/reference/review/packages/<lecture>/v1.json`. The listening copies come from a copy of the bucket's `manifests/media-v2.json` kept in `data/reference/review/manifests/`. With `--every-agreed-piece` it asks every agreed piece instead of a few random agreement samples (see the builder table below); the report then lists the agreed words left unasked, by reason.

```
.venv/Scripts/python.exe -m scripts.review_republish <lecture>
```

This writes the next version of a published package, `v2.json` beside `v1.json`, adding one agreement stop for every agreed piece (the builder's `--every-agreed-piece` mode). It starts from the published bytes and never builds v1 again: the code has moved on since, and a rebuild could draw different stops under the same ids. So it refuses unless `v1.json` has the SHA-256 recorded in the table above and every input v1 names still has its hash. It finds each v1 word and stop among the words read again from those inputs, by text and times, and runs the comparison again on v1's spans only to find disagreements too long to ask. If that comparison does not draw v1's disagreements exactly, it writes nothing. Spans are read at the aligner's unrounded edges: on the evening darshan a span starts at 1414.378210 s, the package stores 1414.378, and ElevenLabs's "So" at 1414.3780 lies between the two. The result must pass P1 to P11.

```
.venv/Scripts/python.exe -m scripts.review_publish <lecture> [<lecture> ...] [--version 2]
```

This uploads it to `gs://ssggsm-seva-media/packages/<lecture>/v<version>.json` (Mukul's go-ahead, 30 October 2026). A version above 1 is refused until `../review-assistance/contracts/review.pin.json` names a commit holding the republished example: before the app carries answers over, a v2 would ask reviewers v1's questions again. Before sending anything it checks the file again: LF bytes only, the schema and P1 to P10, not a DRAFT, and the original and listening copy it names both in the bucket. A published package is never changed, because answers name it by its bytes. The same bytes again are left alone. Different bytes under the same name are refused, and the upload itself can only create (`--if-generation-match=0`). The object is read back and compared after upload.

```
.venv/Scripts/python.exe -m scripts.review_import gs://<exports bucket>/exports/<folder> --configuration <gcloud configuration>
```

This is `import review answers`. It copies an export folder read-only, checks each pair against its package (the package's bytes, the answers file's hash and record count, A1-A9, C1-C3), applies the app's list as it stands, and writes per-language results in `review-results` 0.1 (R1) to the gitignored `data/reference/review/results/`. Answers from the app's dev project are trials: their results go under `TRIAL-<export>/` and are marked TRIAL, and nothing is applied to a transcript (Mukul, 30 October 2026). The published transcript is deliberately edited for grammar, so a published "error" in these results is a distance from what was said, not a mistake. `scripts.review_findings` sorts every answered disagreement into grammar, disfluency and content for reading. Publishing results back to the app is not built.

A package built from producer code with uncommitted changes says so at the start of `producer.notes` ("DRAFT, not for publishing"), because its `revision` would not contain the code that built it. The upload step refuses such a package.

## How the builder chooses stops

**These choices are `lecture-archive`'s proposals to Mukul, not agreements.** Mukul ruled on 29 October 2026 that they are not to be settled on one lecture: `lecture-archive` decides them once four or five lectures have been reviewed (ADR-0016). The figures in the table are from the first real package, BG 3.37 (Brisbane): 640 stops for a 61-minute lecture.

| Question | What the builder does now | Why |
|---|---|---|
| What counts as a difference | Words are compared after the scorer's own `normalise` and folding, so contractions, numbers written as digits, punctuation and fillers are not stops | A corrector would not stop there, and the scorer does not charge them |
| How stops are grouped | One stop per differing phrase: a run of words that differ together. Phrases less than 1 s apart, in one language, are joined, up to 12 words a side. Larger ones are not asked, and the build lists them | Each stop should stay about ten seconds of work. Brisbane's median stop asks about 0.5 s of audio, mostly one word |
| Clip length | 3 s either side, always inside the recording; 6 context words either side | Enough to hear the word arrive. Median clip 6.8 s, longest 14.4 s, 80 minutes of listening in all |
| Language | A published word the editor wrote with diacritics is Indic. Sanskrit or Bengali comes from `indic_language` over the Indic words within six tokens. An unmarked word between two Indic words of one language belongs to them. A differing passage is split where the language changes. Words only ElevenLabs has are `unknown` | See the evidence below |
| Verse checks | Every match in `verse-runs.json` at its 0.25 gate that lies inside a trustworthy span. The differences inside a verse are not asked separately. Nothing below the gate is shown | A confidently wrong verse attributed to the teacher is worse than an admitted gap |
| Agreement samples | Six identical words. One sample for every 20 disagreements, aiming for at least 3. Out of earshot of every other stop: neither clip plays the other's words. Chosen at random with a seed taken from the lecture id, so a rebuild picks the same ones. On dense lectures there are fewer places than wanted: `arrival-address-from-usa` has none, `arrival-class` 7 of 19 | A small unmarked sample, as the requirements ask. Brisbane's first build put one 0.065 s after the `later`/`latter` stop, so its clip played that disagreement and its context words differed |
| Every agreed piece (`--every-agreed-piece`, an option; random samples stay the default) | Every published word in a trustworthy span that belongs to no other stop and that ElevenLabs wrote exactly alike, punctuation and case included, is asked once. The words are cut into pieces of up to 6 in one language, never across a span edge or another stop's words on either side; the last piece of a run may be shorter. No 3-second rule: a piece's context words stop at the first word of a disagreement or verse check instead, in both versions. A pair heard over 1 s apart is not asked. Agreed words left unasked are reported as unchecked, by reason | Mukul's decision of 31 October 2026 to listen to every agreed piece on seven lectures ([plan](plan-check-every-agreed-piece-2026-10-31.md)). Built that day for the arrival class and Cc. Ādi 4.256: 806 pieces holding 2,540 words (2,536 English, 4 Sanskrit), 27% of them one word. Of 768 agreed words left unasked, 646 match only after folding and 82 are placed over 1 s from where ElevenLabs heard the same word, mostly beside speech the published text leaves out ("Huh?", "Isn't it?") |
| Single-version stops | ElevenLabs's words outside every trustworthy span, broken at pauses over 1 s and at 12 words | A ten-second question |
| Misplaced words | The spans lose every stretch `read_along.word_check` finds misplaced. They also lose every stretch where a disagreement pairs words more than 1 s apart, which is the same fault in places the word check cannot measure. Then the comparison runs again | A stop built on misplaced words plays the wrong audio |
| Recogniser words with no real time | An ElevenLabs word lasting over 5 s is never part of a stop. Brisbane has one: `Kama.`, stretched across 55 s of chanting | It cannot be placed in a clip |
| Stop ids | Serial numbers in timeline order. A later version (`scripts.review_republish`, 31 October 2026) keeps every earlier stop under its id, and new stops take serials after the previous version's highest, in timeline order among themselves. Ids are then no longer in timeline order; the stops array still is (P4) | Ids must never be reused for a different question, and answers carry over by id (rule P11) |

**Evidence on one language per stop.** The proposed rule works, but word-level labels needed two repairs, both found by reading the Brisbane stops:

- **Unmarked Sanskrit words.** `ca`, `ceha`, `iha` and `enam` carry no diacritics. Judged word by word, they are English, and SB 1.2.10 would be cut at `nārtho yaś | ceha | karmabhiḥ`. `verse_runs`'s own bridging rule keeps a single such word with its verse. Runs of two or more unmarked words (`viddhy enam iha vairiṇam`) and unmarked names (`Yudhisthira`) still come out English.
- **English votes.** The scorer's `compare_hosted.language_mask` lets every word in the window vote. English "more" is also the Bengali pronoun *more*, so two of the three words it called Bengali here were Sanskrit (`śreya`, `pūrṇa-vikacita-cetana`). In the package, only Indic words vote, and the one Bengali stop left is Bengali by reading (`'āmāra' bolite āre kichu nāi`). The same defect affects `compare_hosted`'s research figures; that is not changed here.

**Seven lectures, 29 October 2026.** Packages now build for every lecture that has both recognisers' output and passes the placement check: seven, 264 minutes of audio, 3,558 stops (13.5 per minute of tape) and 445 minutes of clips. `19941228-padayatra-arrival` is refused by the placement check, as it should be. What the six others showed, every figure counted from the packages:

- **Bengali labelled Sanskrit.** `indic_language` labels a line by two word lists and calls a tie Sanskrit. On the two Caitanya-caritāmṛta lectures, 8 of the 13 Bengali verse checks are labelled Sanskrit by reading. `uttama hañā āpanāke māne tṛṇādhama` matches neither list. In `jīvera nistāra lāgi' … māyāvādi-bhāṣya śunile haya sarva-nāśa`, *bhāṣya* is counted as a Sanskrit genitive in *-asya*, tying with *haya*. Odia has no list at all: `bhāvaku nikaṭa bhāvaku dura` comes out Sanskrit. This is the scorer's instrument, so its research figures share the fault; it is not changed here.
- **Indic word stops are mostly names.** 317 of the 538 Sanskrit or Bengali word disagreements are capitalised names inside English sentences, and 129 are `Kṛṣṇa` alone. 280 of the 538 (52%) are spelling only by the scorer's rule.
- **Words only ElevenLabs heard are mostly English.** 704 of the 789 `unknown` stops (89%) sit between two English words, and 105 hold `understand`: the lecturer's "Do you understand?", which the transcripts leave out.
- **One verse check is wrong by reading.** On `cc-adi-lila-7-114`, the song fragment `calo aiyo re` (KKSongs, *Calo Aiyo Re Syama Mere Palakana Pe*) is matched at margin 0.333 to the prose `Māyāvādī scholar, Sadānanda Yogīndra,`. It is left in the package, since "not a verse" is an answer the reviewer has, but `verse_truth.json` does not yet hold it.
- **Three builder faults, fixed with a test each:** an agreement sample within earshot of a disagreement (above); a transcript storing ṛ as r plus a combining dot, refused by P9 (`cc-adi-lila-4-256-258`); and the span-manifest guard comparing spans recomputed after `renumber` dropped editorial notes, which refused a current manifest (`cc-adi-lila-9-46`).

## Open questions on building stops

Each has a working default in the builder (above):

- how stops are grouped, and how long a clip and its context are;
- which spelling the checked text keeps after "both are right";
- whether verse suggestions below the gate are left out (they are now) or shown;
- how agreement samples are chosen, and how many (see
  [the plan to ask every agreed piece](plan-check-every-agreed-piece-2026-10-31.md));
- whether spelling-only differences should be stops at all. On Brisbane they are 42 of the 86 Sanskrit stops, and the scorer already forgives them;
- whether words only ElevenLabs has should take the language of the published words around them, rather than `unknown`. There are 188 such stops on Brisbane, 72 of them a single word.

Proposed, not made: **the media manifest records a listening copy's decoded length** only for the three lectures re-checked on 29 October. For the rest, the builder decodes the local copy itself, after checking its hash. Recording `copy_decoded_seconds` for every lecture would let packages be built without the audio on disk.
