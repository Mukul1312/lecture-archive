# Editorial rules for the Listening draft

## Evidence authority

Use evidence in this order:

1. Source audio.
2. A careful listener correction supported by that audio.
3. Raw ASR and targeted reruns as drafts.
4. An optionally registered Taptajivanam/reference file as secondary evidence.

Reference material must be locally captured and explicitly registered with
`register-reference`; the runner does not scrape it. It can suggest a place to
re-listen, but cannot fill an ASR gap, overwrite audio-supported text, or add an
unverified line. An ASR gap is always **ASR-uncovered**, not presumed silence.

## Whole-timeline review

Listen to and edit the whole timeline, including every review chunk and every
ASR-uncovered interval. Do this even when the ASR sounds strong, a targeted rerun
helps, or a reference appears to agree. Do not mark a chunk reviewed unless its
content has been checked against source audio.

## English and uncertainty markers

This is English-only. Do not translate, transcribe, or interpret meaningful
non-English speech. Use these exact, time-bounded markers where they apply:

```text
[Non-English interpretation omitted, HH:MM:SS-HH:MM:SS]
[Recording silence, HH:MM:SS-HH:MM:SS]
[Indistinct English speech, HH:MM:SS-HH:MM:SS]
```

`Recording silence` requires an audible silence confirmed in the review; missing ASR
coverage alone is not evidence of silence. Do not substitute the markers for one
another or remove their timestamps.

## Delivery language

The assembled document must remain `Status: Listening draft`, with conservative
speaker labels and natural timestamps only where source audio supports them. No
content-bearing stretch may go more than five minutes without a timestamp. Keep
hashes and diagnostics in evidence files rather than the delivery document. It is not
publication or final textual authority. Manual OneNote copy/edit is outside the
runner, and a handoff receipt must never claim that manual OneNote work happened.
