# Hindi clone

!!! danger "History — superseded on 2026-07-10"
    This extended the English clone to Hindi. It was withdrawn by the same instruction that ended
    the [voice-cloning](../voice-cloning/index.md) work: narration uses a different voice, not
    Gour Govinda Swami's. The extraction, transcription-review and reference-selection work is
    kept because it stands on its own and would be needed again by any Hindi speech work here.

## What reached a result

- **VoxCPM2-Hindi was judged a go**: the base-model probe was ear-confirmed as recognisably him,
  speaking clean and correct Hindi.
- **About 109 minutes of confident Hindi** was found across four lectures where he speaks
  essentially alone, and **210 clips** were extracted with Whisper-draft transcripts.
- **The drafts needed review, and the review mattered.** The transcription review page is the
  record of how far the draft transcripts could be trusted — the same question the current
  [transcription](../transcription/index.md) work asks at much larger scale.
- The final v1 state was a zero-shot clone using reference clip 0008 through an ECAPA funnel,
  reaching 0.864 on the diary Short.

## The pages

- [Plan and state](hindi-clone-plan.md) — the durable plan, research-verified with primary sources
  cited inline.
- [State handoff, 2026-07-06](hindi-clone-state-2026-07-06.md)
- [Picking the Hindi transcriber](hindi-asr-model-research.md) — the Hindi ASR model comparison.
- [Clean-Hindi extraction pipeline](hindi-extraction-pipeline-research.md) — finding the stretches
  where he speaks Hindi alone and cleanly.
- [Reviewing the Hindi transcripts](transcription-review-2026-07-24.md) — `data/hi/train_final`.
