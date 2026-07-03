"""
ref_ab.py — DECISIVE downstream confirmation of the noise fix. Controlled intervention: generate the
SAME GGS chunks with the SAME seeds under 4 reference conditions, changing ONLY the reference/denoise.
Then (locally) compare OUTPUT noise floor + OUTPUT identity — because clip-level identity != downstream.

Conditions:
  noisy      raw clips/ggs_l1_0001.wav                     (baseline — the current v5 recipe)
  denoised   clips_dn/ggs_l1_0001.wav  (Resemble-Enhance)  (-21.5 dB ref, -0.057 clip identity)
  hpf120     high-pass-120 of the noisy ref                (identity-safe, -5.9 dB ref)
  zipenh     raw ref + generate(denoise=True)              (VoxCPM's built-in ZipEnhancer at inference)

Run on the pod:  /workspace/venv/bin/python /workspace/ref_ab.py
Output -> /workspace/ref_ab/<cond>/{NN}__s{seed}.wav
"""
import gc
import json
import os
import sys

import soundfile as sf
import torch
from voxcpm.core import VoxCPM
from voxcpm.model.voxcpm import LoRAConfig

BASE = "/workspace/VoxCPM2"
LORA = "/workspace/lora_champion"
FINAL = "/workspace/voice-cloning/data/out/lecture1/final"
CHUNKS = "/workspace/diary_chunks_calm.txt"
OUT = "/workspace/ref_ab"

CHUNK_IDS = [10, 15, 20, 21]                       # spread: medium, long, refrain, "well-wishers" line
SEEDS = [42, 123, 7, 2024, 99, 314]                # same seeds across all conditions (controlled)
CONDS = [                                          # (name, reference_wav_path, denoise)
    ("noisy",    f"{FINAL}/clips/ggs_l1_0001.wav",     False),
    ("denoised", f"{FINAL}/clips_dn/ggs_l1_0001.wav",  False),
    ("hpf120",   "/workspace/ref_hpf120.wav",          False),
    ("zipenh",   f"{FINAL}/clips/ggs_l1_0001.wav",     True),
]

lines = [l.strip() for l in open(CHUNKS, encoding="utf-8") if l.strip()]
picks = [(i, lines[i - 1]) for i in CHUNK_IDS]
print(f"=== ref A/B: {len(CONDS)} conds x {len(picks)} chunks x {len(SEEDS)} seeds "
      f"= {len(CONDS)*len(picks)*len(SEEDS)} gens ===", file=sys.stderr)

info = json.load(open(f"{LORA}/lora_config.json"))
cfg = LoRAConfig(**info["lora_config"]) if info.get("lora_config") else None
m = VoxCPM.from_pretrained(hf_model_id=BASE, load_denoiser=True, optimize=False,
                           lora_config=cfg, lora_weights_path=LORA)
sr = m.tts_model.sample_rate

for name, ref, denoise in CONDS:
    if not os.path.exists(ref):
        print(f"SKIP {name}: missing ref {ref}", file=sys.stderr)
        continue
    d = f"{OUT}/{name}"
    os.makedirs(d, exist_ok=True)
    for i, line in picks:
        for s in SEEDS:
            out = f"{d}/{i:02d}__s{s}.wav"
            if os.path.exists(out):
                continue
            wav = m.generate(text=line, reference_wav_path=ref, denoise=denoise,
                             cfg_value=1.6, inference_timesteps=20, seed=s)
            sf.write(out, wav, sr)
        print(f"wrote {name} chunk {i:02d}", file=sys.stderr)

del m
gc.collect()
torch.cuda.empty_cache()
print("REF_AB DONE")
