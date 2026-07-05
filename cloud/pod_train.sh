#!/usr/bin/env bash
# =====================================================================================
# pod_train.sh — VoxCPM2 LoRA training env + run, on a RunPod RTX 4090 (24GB, CUDA 12.4 host).
#
# Training needs torch >=2.5 (the dataprep env was torch 2.4) -> we make a SEPARATE venv.
# torch 2.5 cu124 wheels run on a 12.4 host driver. Verify VoxCPM's repo script paths on first
# run; if the repo layout differs from the docs, adjust step 6.
#   bash cloud/pod_train.sh
# =====================================================================================
set -e
cd /workspace
CONFIG="${1:-/workspace/voice-cloning/cloud/voxcpm_lora.yaml}"   # pass voxcpm_lora_dn.yaml for the denoised retrain

echo "=== 1) fresh training venv (torch 2.5+, separate from dataprep) ==="
python3.11 -m venv venv_train 2>/dev/null || python3 -m venv venv_train
source venv_train/bin/activate
pip install -q -U pip

echo "=== 2) torch 2.5 (cu124 — runs on the 12.4 host driver) ==="
pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cu124

echo "=== 3) VoxCPM + training deps ==="
[ -d VoxCPM ] || git clone https://github.com/OpenBMB/VoxCPM.git
pip install -q -e VoxCPM || pip install -q -r VoxCPM/requirements.txt
pip install -q tensorboardX argbind transformers librosa safetensors "huggingface_hub[cli]"

# memfix: VoxCPM2.from_local() casts the 2B base to bf16 ONLY in inference mode; in training
# mode it stays fp32 and OOMs a 24GB GPU (autocast keeps both fp32 master + bf16 copies).
# Inject a bf16 cast of the FROZEN base weights (keep trainable LoRA + audio_vae in fp32).
python - <<'PYFIX'
p = "VoxCPM/scripts/train_voxcpm_finetune.py"
s = open(p).read()
anchor = "    tokenizer = base_model.text_tokenizer\n"
if "[memfix]" in s:
    print("memfix: already patched")
else:
    assert anchor in s, "memfix anchor not found — VoxCPM trainer layout changed"
    inject = anchor + (
        "    import torch as _t\n"
        "    _nb = 0\n"
        "    for _n, _p in base_model.named_parameters():\n"
        "        if _p.requires_grad or (\"audio_vae\" in _n):\n"
        "            continue\n"
        "        _p.data = _p.data.to(_t.bfloat16); _nb += 1\n"
        "    print(f\"[memfix] cast {_nb} frozen base tensors to bf16\", file=sys.stderr)\n"
    )
    open(p, "w").write(s.replace(anchor, inject, 1))
    print("memfix: patched")
PYFIX

echo "=== 4) base model openbmb/VoxCPM2 (~several GB; set HF_TOKEN if it 403s) ==="
# huggingface-cli is fully deprecated in huggingface-hub >=1.x — use `hf download`.
hf download openbmb/VoxCPM2 --local-dir /workspace/VoxCPM2

echo "=== 5) sanity: torch CUDA + data present ==="
CONFIG="$CONFIG" python - <<'PY'
import os, re, torch
print("torch", torch.__version__, "| cuda", torch.cuda.is_available(),
      "|", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")
cfg = os.environ["CONFIG"]                       # count the manifest THIS config trains on
m = re.search(r'^\s*train_manifest:\s*(\S+)', open(cfg).read(), re.M)
mf = m.group(1) if m else None
n = sum(1 for _ in open(mf)) if mf else -1
print("config:", cfg, "| manifest:", mf, "| train samples:", n)
PY

echo "=== 6) train (LoRA r=32; checkpoints -> /workspace/ckpt/lora every 50 steps) ==="
mkdir -p /workspace/ckpt/lora /workspace/logs/lora
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True   # reduce fragmentation on the 24GB 4090
python VoxCPM/scripts/train_voxcpm_finetune.py \
    --config_path "$CONFIG"

echo "=== done. evaluate checkpoints with cloud/TRAINING.md step 5 ==="
