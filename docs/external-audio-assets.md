# External audio assets

New publication commits contain source code and reproducible workflow
definitions, not recordings or generated media. Voice recordings may carry
consent, copyright, privacy, and storage obligations that source code does not.

The `origin/main` baseline predates this rule and already contains legacy media.
This publication branch adds no new media and does not rewrite that existing
remote history. Removing already-published objects would require a separate,
explicit history-migration project.

The following paths are therefore local or externally managed:

- `data/hi/train_final/`: Hindi training manifests and WAV recordings.
- `data/enhance/`: lecture inputs, diagnostic clips, model work directories,
  blind auditions, QA exports, and final delivery archives.
- `site-casting/audio/` and `site-odia-check/audio/`: private listening-review
  assets used by the static site templates.
- Cartesia narration job roots (`CARTESIA_NARRATION_ROOT`): private voice identifiers,
  detailed/private authorization attestation records and evidence, run manifests,
  generated takes, reviews and masters.
- `.tmp-*`, `voice_lab/`, and deployment metadata: reproducible local output.

Several retained scripts and templates refer to these paths intentionally.
Supply authorized assets locally before running those workflows. Generated
files must not be force-added to Git; use an approved private artifact store or
a release attachment only after checking consent and distribution rights.

The source-only publication branch does not delete local assets. They remain in
the private working copy or its local preservation archive and can be supplied
to the retained code when needed.
