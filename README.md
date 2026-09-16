# Lecture archive

This repository contains source code, tests, research notes, and reusable
workflows for lecture transcription, spoken-lecture audio enhancement, and the
earlier voice-cloning experiments. It was named `voice-cloning` until 2026-09-17
([ADR-0013](docs/decisions/0013-narrator-voice-moves-to-its-own-repository.md)).
Older or currently inactive workflows are intentionally retained because they
remain useful technical work.

New work keeps recordings, voice-training datasets, generated review galleries,
model artifacts, and finished audio deliveries outside Git. The existing remote
history predates that policy and already contains some legacy media; this branch
does not add more media or rewrite the published baseline. See
[External audio assets](docs/external-audio-assets.md) for the expected local
paths and publication policy.

## Narration moved to `narrator-voice`

Narrator Voice — the local narration studio for authorized SSGGSM Odia diary narration
and the future non-SSGGSM English/Hindi narration — moved to its own `narrator-voice`
repository on 2026-09-16 under
[ADR-0013](docs/decisions/0013-narrator-voice-moves-to-its-own-repository.md), with its
history. Its code, tests, install and live-validation instructions, and working rules
live there. The narration decision records, designs and plans under `docs/` remain here
unchanged as history; the copies in `narrator-voice` are the maintained ones.

## Main components

- `scripts/hi/` and `cloud/`: Hindi extraction, ASR, evaluation, and training
  workflows.
- `scripts/youtube_enhance/`: resumable, timeline-preserving lecture audio
  enhancement implementation.
- `.agents/skills/enhancing-lecture-audio/`: explicitly invoked operational
  workflow for processing a new lecture.
- `tests/youtube_enhance/`: unit and workflow-safety coverage.
- `docs/`: research, architecture, and operational decisions.

## Lecture-enhancement development

The verified enhancement environment uses Python 3.11. On Windows, create an
isolated environment with that interpreter and use the wheel-based dependency
set:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-enhance-windows.txt
.\.venv\Scripts\python.exe -m pip install resemblyzer==0.1.4 --no-deps
$activeTestRoots = @(
    "tests/ggsm_transcription",
    "tests/youtube_enhance"
)
foreach ($testRoot in $activeTestRoots) {
    & .\.venv\Scripts\python.exe -m unittest discover -s $testRoot -t . -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& .\.venv\Scripts\python.exe -m unittest tests.test_legacy_script_paths -v
```

Resemblyzer's declared `webrtcvad` package has no Windows wheel and otherwise
tries to compile from source. `webrtcvad-wheels` supplies the same `webrtcvad`
import. Because their distribution names differ, `pip check` will still report
the legacy requirement even though the runtime import is available.

On Linux or another platform that can build `webrtcvad`, use the standard
requirements file:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements-enhance.txt
for test_root in tests/ggsm_transcription tests/youtube_enhance; do
    ./.venv/bin/python -m unittest discover -s "$test_root" -t . -v || exit
done
./.venv/bin/python -m unittest tests.test_legacy_script_paths -v
```

FFmpeg is also required for real audio processing.

These commands are the active default suite. They deliberately exclude the shelved
`tests/heritage_production/` suite under
[ADR-0001](docs/decisions/0001-reuse-only-the-shared-kernel.md); repository-wide
`discover -s tests` is therefore not the default command.
