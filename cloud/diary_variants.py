"""
diary_variants.py — generate the full diary's GGS chunks under each cleaning TIER, so devotees can
choose their operating point on the noise<->identity frontier. Only HIS lines differ; the narrator
(base model) is reused unchanged, and every tier uses the same chunks + same seeds + same funnel.

Tiers (reference-conditioning, matching the measured ref A/B):
  hpf    high-pass-120 reference  (identity-safe, ~-6 dB)
  zipenh raw ref + denoise=True   (ZipEnhancer at inference, cleaner, small id cost)
  redn   Resemble-Enhance ref     (clips_dn, cleanest, clearest id cost)
(noisy tier = the existing v5 out_diary; not regenerated.)

Run on the pod:  /workspace/venv/bin/python /workspace/diary_variants.py
Output -> /workspace/diary_var/<tier>/{NN}__s{seed}.wav   (GGS chunks 4..23 only)
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
OUT = "/workspace/diary_var"
NARR = {1, 2, 3}                                    # narrator lines — reused, NOT regenerated here
SEEDS = [42, 123, 7, 2024, 99, 314, 777, 2025, 1, 11, 21, 55,   # 24 seeds/chunk (max-quality A/B);
         88, 111, 222, 333, 444, 555, 666, 888, 999, 1234, 1976, 8848]   # skip-if-exists reuses first 12
TIERS = [                                           # (name, reference_wav_path, denoise)
    ("hpf",    "/workspace/ref_hpf120.wav",           False),
    ("zipenh", f"{FINAL}/clips/ggs_l1_0001.wav",      True),
    ("redn",   f"{FINAL}/clips_dn/ggs_l1_0001.wav",   False),
]

if len(sys.argv) > 1:                               # optional tier filter -> run one tier per process
    want = set(sys.argv[1:])
    TIERS = [t for t in TIERS if t[0] in want]
    print(f"=== tier filter: {[t[0] for t in TIERS]} ===", file=sys.stderr)

lines = [l.strip() for l in open(CHUNKS, encoding="utf-8") if l.strip()]
ggs = [(i, l) for i, l in enumerate(lines, 1) if i not in NARR]
print(f"=== diary variants: {len(TIERS)} tiers x {len(ggs)} GGS chunks x {len(SEEDS)} seeds "
      f"= {len(TIERS)*len(ggs)*len(SEEDS)} gens ===", file=sys.stderr)

info = json.load(open(f"{LORA}/lora_config.json"))
cfg = LoRAConfig(**info["lora_config"]) if info.get("lora_config") else None
m = VoxCPM.from_pretrained(hf_model_id=BASE, load_denoiser=True, optimize=False,
                           lora_config=cfg, lora_weights_path=LORA)
sr = m.tts_model.sample_rate

for name, ref, denoise in TIERS:
    if not os.path.exists(ref):
        print(f"SKIP {name}: missing ref {ref}", file=sys.stderr)
        continue
    d = f"{OUT}/{name}"
    os.makedirs(d, exist_ok=True)
    for i, line in ggs:
        for s in SEEDS:
            out = f"{d}/{i:02d}__s{s}.wav"
            if os.path.exists(out):
                continue
            wav = m.generate(text=line, reference_wav_path=ref, denoise=denoise,
                             cfg_value=1.6, inference_timesteps=20, seed=s)
            sf.write(out, wav, sr)
        print(f"wrote {name} {i:02d}", file=sys.stderr)

del m
gc.collect()
torch.cuda.empty_cache()
print("VARIANTS DONE")
