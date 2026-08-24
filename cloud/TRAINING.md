# GGS voice clone — VoxCPM2 LoRA training runbook

Everything is prepped. This turns your 140 hand-reviewed clips into a fine-tuned model you can hear.
All numbers are from VoxCPM's own fine-tuning guide (cited in [docs/clip-segmentation-policy.md](../docs/clip-segmentation-policy.md)).

## What's ready
- **Dataset:** `data/out/lecture1/final/clips/` (140 wavs, 16k mono, ~25 min) + `final/train.jsonl` (clean text).
- **Manifest:** `final/train.voxcpm.jsonl` — VoxCPM2 format, 46/140 with `ref_audio` (33%), `/workspace` paths.
- **Config:** `cloud/voxcpm_lora.yaml` — LoRA `r=32`, lr 1e-4, save every 50 steps, max 500.
- **Setup:** `cloud/pod_train.sh` — makes a torch-2.5 venv, installs VoxCPM, downloads the base model, trains.

## Step 1 — transfer the private dataset outside Git
Do not add the recordings or manifests under `data/out/` to this repository.
They may contain identifiable voice data and consent-restricted text. Upload the
dataset through an approved private artifact store or directly to a persistent
RunPod volume, then restore it at:

```
/workspace/voice-cloning/data/out/lecture1/final/
```

Only the source code and configuration belong in Git. See
[`docs/external-audio-assets.md`](../docs/external-audio-assets.md) for the
repository-wide media policy.

## Step 2 — start a pod + clone
- RunPod → **RTX 4090 (24 GB)**, a CUDA-12.4 PyTorch image (the same family as dataprep). SSH on.
- `cd /workspace && git clone https://github.com/Mukul1312/voice-cloning.git` (or `git -C voice-cloning pull`).

## Step 3 — run setup + training
```
bash /workspace/voice-cloning/cloud/pod_train.sh
```
This installs a **separate torch-2.5 venv** (training needs ≥2.5; dataprep used 2.4), pulls VoxCPM, downloads `openbmb/VoxCPM2`, and starts training. First run downloads the base model (several GB).
- If the model download **403s** → it's gated: `export HF_TOKEN=hf_xxx` first.
- If you hit **OOM** → edit `cloud/voxcpm_lora.yaml`, set `max_batch_tokens: 4096`, re-run.
- If VoxCPM's repo script path differs from `scripts/train_voxcpm_finetune.py` → tell me the actual path; the docs reference that name.

## Step 4 — monitor
```
tensorboard --logdir /workspace/logs/lora    # (forward the port, or just watch the console loss)
```
- `loss/diff` should **steadily fall, then flatten**. `loss/stop` should stabilize low.
- **Overfit alarm:** if generated audio starts ignoring the text (same output regardless of input) → overfit; use an earlier checkpoint. Small datasets overfit *fast* — the sweet spot may be a **few hundred steps**, not 500.

## Step 5 — hear the clone (the payoff)
Checkpoints land in `/workspace/ckpt/lora/step_0000NNN/`. Evaluate a few (e.g. 150, 250, 350) by inference — the LoRA bakes his voice into the weights, so plain `--text` already speaks in his voice:
```
python /workspace/VoxCPM/scripts/test_voxcpm_lora_infer.py \
    --lora_ckpt /workspace/ckpt/lora/step_0000250 \
    --text "Real intelligence is to give up this illusion and inquire about Krishna." \
    --output /workspace/sample_250.wav
```
Listen to `sample_250.wav` across checkpoints; **pick the one that sounds most like him AND reads the text correctly.** (Validation loss ≠ perceptual quality — judge by ear.)

Optional stronger conditioning — clone from a reference clip (Python API):
```python
from voxcpm import VoxCPM
m = VoxCPM.from_pretrained("openbmb/VoxCPM2", lora_weights_path="/workspace/ckpt/lora/latest")
wav = m.generate(text="Your new English sentence in his voice.")
```
**Inference reference clip** (a clean English one, if you want prompt-based cloning):
`data/out/lecture1/final/clips/ggs_l1_0112.wav` — *"Namabhasa means offences are not completely gone. If offences will completely go, then pure name will rise..."*

## If it's undertrained / not similar enough
- Bump LoRA rank: `r: 48` (or 64) and `alpha` to match, re-run.
- Or add ~15–20 clips from a 2nd lecture (you have the whole pipeline now) and retrain.

## Expected outcome
A first, recognizable GGS English clone — the end-to-end validation of everything you built. Then we iterate on quality.
