# Voice cloning and lecture audio tooling

This repository contains source code, tests, research notes, and reusable
workflows for voice-cloning experiments and spoken-lecture audio enhancement.
Older or currently inactive workflows are intentionally retained because they
remain useful technical work.

New work keeps recordings, voice-training datasets, generated review galleries,
model artifacts, and finished audio deliveries outside Git. The existing remote
history predates that policy and already contains some legacy media; this branch
does not add more media or rewrite the published baseline. See
[External audio assets](docs/external-audio-assets.md) for the expected local
paths and publication policy.

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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
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
./.venv/bin/python -m unittest discover -s tests -v
```

FFmpeg is also required for real audio processing.
