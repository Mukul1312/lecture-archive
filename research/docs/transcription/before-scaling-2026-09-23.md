# What to settle before transcribing at scale

**The pipeline's remaining risks are no longer technical. They are questions of validity.**
Every recogniser has been measured, the selector works, the verse corpus exists and every word
now has a time. What none of that establishes is whether the answers hold for **lecture number
two**, and the archive is 3,766 lectures.

This page exists because the next move is to transcribe more. It is the list of what a mistake
would cost if it is discovered after a thousand lectures rather than before.

## The one that matters most

!!! danger "A second verified lecture"
    **Every number in this project rests on one 66-minute recording.** Melbourne 1990. The
    ranking of nine systems, the 15.1% English figure, the decision to buy ElevenLabs, the
    Sanskrit and Bengali split, the timing agreement — all of it, one lecture.

    This is not a theoretical worry. **The one other corpus ever tried reversed the result:** on
    Prabhupadavani, Whisper won. And **public benchmarks have mispredicted this corpus three
    times out of three** — `large-v3-turbo`, Indic-Transcribe-flex and Deepgram all ranked well
    elsewhere and did badly here.

    A second verified lecture is the only thing that distinguishes "ElevenLabs is better for this
    archive" from "ElevenLabs was better for that afternoon in Melbourne". Everything below is
    cheaper to fix than this is, and none of it protects against being wrong about this.

    **Cost:** the expensive part is human — verifying a transcript cue by cue in the reference
    editor. Choose a lecture that differs on purpose: a different decade, a different venue, more
    Bengali song, a different recording chain.

## Cheap, and removes a caveat from existing work

!!! warning "~100 hand-marked word onsets"
    The forced aligner agrees with three commercial systems more closely than they agree with
    each other. That is **agreement, not accuracy** — nothing measured so far shows it is correct
    to any tolerance, only that it keeps good company.

    Marking about a hundred word onsets by hand settles it permanently, and it is hours of work,
    not days. It would also decide the **word-onset convention**, which is currently unrecorded:
    MMS_FA has no word-separator token, so the silence between two words belongs to neither, and
    whether a highlight begins at the first strongly-scoring frame or reaches back into the
    preceding gap is undecided. Published figures swing several fold on exactly that choice.

!!! warning "The `data/reference/` gitignore question"
    Roughly twenty analysis scripts live under a gitignored directory — `error_text.py`,
    `adjudication.py`, `inspect.py` and, most importantly, **the verifiers that check published
    figures**. If that directory is lost, the numbers in these pages cannot be reproduced.

    Flagged five times across sessions and still undecided. It is a one-line decision and it is
    protecting nothing.

## Needed before the output is a product

!!! danger "The transcript is not yet a document"
    Everything measured so far is **folded tokens** — lower-cased, unpunctuated, no diacritics.
    The deliverable is readable text with capitals, sentence breaks, paragraphs and IAST for the
    Sanskrit. The fused files are measurement artifacts, not drafts.

    **flex emits almost no punctuation at all**, so any word chosen from flex arrives bare — and
    flex is the only system that can do Bengali. Nobody has decided where punctuation and casing
    come from in the final text. This is not a small stage: at scale it is the difference between
    something a devotee reads and something only a corrector can use.

!!! warning "Nothing can say 'unclear'"
    The pipeline cannot decline to answer. For scripture that is the difference between a gap and
    a **fabrication** — a plausible wrong verse presented as what he said. `verse_match.find`
    abstains correctly, but nothing else in the chain does, and the transcript itself has no way
    to mark a passage as unrecovered.

!!! warning "Nobody knows who is speaking"
    Other people talk. Mr Peter and others open 43 of 512 cues in this one lecture, and a
    read-along page presumably needs to show that. Nothing in the pipeline attributes speech, and
    the only thing currently done with a speaker label is to **delete it** so it is not aligned
    as if spoken.

## Ready to run, no decisions needed

!!! success "flex over a full lecture"
    `scripts/flex_timed.py` works end to end and was proved on a five-minute slice: 12 segments,
    470 words, every invariant holding. A whole lecture is roughly **40 minutes of decoding plus
    25 of alignment**, as a background job. This produces the first complete Bengali read-along
    timing the archive has ever had.

## Blocked on a decision, not on work

!!! question "The spend: ~$760 or ~$2,000"
    ElevenLabs alone is $759 across the corpus and gives the fewest corrections — **459 stops
    against Whisper's 627, 27% less labour**. All three systems combined is ~$2,000 and recovers
    the most speech, because mishearing chanted Sanskrit is the largest remaining recoverable
    class and no single system fixes it.

    The timing objection to spending is now gone. What remains is the second lecture, and the
    **corpus's real average length**, which every one of these figures multiplies and which is
    still unverified.

!!! question "Where the GPU benchmark applies"
    The existing GPU costing is for `large-v3-turbo` — **a model that was rejected** — and its
    own benchmark says accuracy was not measured. Any bulk local pass needs re-costing on the
    models actually chosen, and the confidence-gated route needs three of them, so triple the
    hours. Storage may exceed compute: 0.5 TB at $0.07/GB/month is about $38/month.

---

## Suggested order

1. **A second verified lecture.** Everything else is cheaper to redo than this is to discover.
2. **~100 hand-marked onsets** — hours, and it upgrades a claim already made.
3. **Decide the gitignore question** — one line, protects the verifiers.
4. **Run flex over the full lecture** — background job, no decisions.
5. **Decide where punctuation and casing come from**, because the output is not yet a document.
6. Only then the spend, and only then a bulk pass.
