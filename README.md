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

## Current SSGGSM Odia narration

The approved production baseline is an authorized Cartesia Sonic 3.6 Instant Voice
Clone for SSGGSM Odia diary narration. The accepted scope and configurable
`speed=0.90`, `volume=1.00`, `emotion=calm` defaults are recorded in
[ADR-0006](docs/decisions/0006-authorized-cartesia-ivc-for-ssggsm-odia-narration.md).
[ADR-0007](docs/decisions/0007-two-policy-isolated-narration-lanes.md) records that
this Odia lane does not replace the active future non-SSGGSM English/Hindi narration
programme and prevents their opposite identity policies from leaking across lanes.
[ADR-0008](docs/decisions/0008-lane-b-production-boundaries.md) records the accepted
one-job aggregate, split settings, separate authorization lifecycle, localhost
sole-operator UI and publishing-stage reviewer boundary. The accepted authoritative
domain background remains in the historical
[Cartesia Odia narration v3 design](docs/superpowers/specs/2026-09-02-cartesia-odia-narration-production-v3-design.md).
[ADR-0012](docs/decisions/0012-narrator-voice-v1-is-a-minimum-local-studio.md)
records that the original operational plan was overbuilt for one local operator. The
[v4 minimum local-studio design](docs/superpowers/specs/2026-09-03-cartesia-odia-narration-minimum-local-studio-v4-design.md)
and [minimum implementation plan](docs/superpowers/plans/2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1.md)
govern remaining v1 work.
The next implementation entry point is the
[Task 4M Cartesia adapter plan](docs/superpowers/plans/2026-09-03-ssggsm-odia-narration-minimum-local-studio-v1-task-4m-cartesia-adapter.md),
which is explicitly prepared for a fresh Codex chat.
The [codebase-wide capability audit](docs/narrator-voice-shared-capability-audit-2026-09-02.md)
supports accepted [ADR-0009](docs/decisions/0009-share-narration-mechanics-not-policy.md),
which permits provider-neutral narration mechanics while keeping lane policy isolated.
No production implementation or private audio is added by those documents.

### Offline Narrator Voice operations

Install the repository into its virtual environment once before using the local
operations command from a fresh checkout:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m heritage_archive.composition_root.narrator_voice_cli --help
```

Set `CARTESIA_NARRATION_ROOT` to an existing private directory outside this
repository before running commands that use the live studio. Initialization also
requires an explicit private configuration file; inspect `init --help` for its
arguments. These offline commands do not contact Cartesia or read
`CARTESIA_API_KEY`.

## Main components

- `scripts/hi/` and `cloud/`: Hindi extraction, ASR, evaluation, and training
  workflows.
- `src/heritage_archive/contexts/narrator_voice/`: the authorized Odia narration
  domain, application workflows, and local durable adapters.
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
    "tests/heritage_archive",
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
for test_root in tests/ggsm_transcription tests/heritage_archive tests/youtube_enhance; do
    ./.venv/bin/python -m unittest discover -s "$test_root" -t . -v || exit
done
./.venv/bin/python -m unittest tests.test_legacy_script_paths -v
```

FFmpeg is also required for real audio processing.

These commands are the active default suite. They deliberately exclude the shelved
`tests/heritage_production/` suite under
[ADR-0001](docs/decisions/0001-reuse-only-the-shared-kernel.md); repository-wide
`discover -s tests` is therefore not the default command.
