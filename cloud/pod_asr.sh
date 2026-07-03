#!/usr/bin/env bash
# =====================================================================================
# pod_asr.sh — env for extract_hindi_v2 (AI4Bharat IndicConformer-600M + Silero-VAD).
# Dedicated venv so IndicConformer's deps don't collide with pod_setup (aligner/whisper) or the
# VoxCPM venv. Run on a fresh pod after `git clone` + `python scripts/fetch_idt.py`.
#   bash cloud/pod_asr.sh
#   then:  /workspace/venv_asr/bin/python cloud/extract_hindi_v2.py --langs hi,ur
# =====================================================================================
set -e
cd /workspace

echo "[asr 1/3] venv + torch (cu124) ..."
python3.11 -m venv venv_asr 2>/dev/null || python3 -m venv venv_asr
source venv_asr/bin/activate
pip install -q -U pip
pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cu124

echo "[asr 2/3] transformers + Silero-VAD + IndicConformer runtime deps ..."
pip install -q transformers silero-vad soundfile librosa sentencepiece
# IndicConformer-600M's remote code uses onnxruntime; pin the versions the model card specifies.
pip install -q "onnx==1.20.1" "onnxruntime==1.20.1" "onnxruntime-gpu==1.20.1"

echo "[asr 3/3] smoke test — load IndicConformer + Silero (fails setup, not a paid run) ..."
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available(),
      torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU")
from silero_vad import load_silero_vad
load_silero_vad(); print("silero-vad OK")
from transformers import AutoModel
m = AutoModel.from_pretrained("ai4bharat/indic-conformer-600m-multilingual", trust_remote_code=True)
print("IndicConformer-600M load OK")
PY
echo "[asr] DONE — run: /workspace/venv_asr/bin/python cloud/extract_hindi_v2.py --langs hi,ur"
