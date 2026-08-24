---
name: transcribing-ggsm-lecture
description: Use when preparing a local Listening draft for a user-selected English SSGGSM archive lecture.
---

# Transcribing a GGSM Lecture

Use this skill only through the explicit invocation
`$transcribing-ggsm-lecture <URL>`. It has only explicit invocation; do not select or
run it implicitly for general transcription, enhancement, catalog, publishing, or
non-English work.

This skill prepares evidence and a local **Listening draft**, never a published or
OneNote-synced transcript. Start with the shared runner:

```text
python -m scripts.ggsm_transcription intake --url <https-url>
```

Before executing, read [the workflow](references/workflow.md) and
[editorial rules](references/editorial-rules.md). Follow their stage order and stop
with the stated safe next action when source identity, job state, artifacts, or the
local ASR environment cannot be validated.

The canonical skill is the authority for this workflow. The Claude bridge is only a
pointer to these instructions and the same runner.
