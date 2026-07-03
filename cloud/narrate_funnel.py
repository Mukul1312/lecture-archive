"""
narrate_funnel.py — generate the diary takes: a MALE 3rd-person narrator (base model, no LoRA) for the
framing lines, and GGS's cloned voice (LoRA + calm reference) for his own first-person prayer.

  Pass 1 (BASE, no LoRA): narration chunks -> a distinct calm male narrator (Voice Design + reference-lock)
  Pass 2 (LoRA):          GGS chunks -> Controllable cloning + calm ref ggs_l1_0001, 24 seeds

N seeds/chunk so the local funnel (scripts/assemble_diary.py) keeps the calmest/softest take.
Run on the voxcpm-vol pod:  /workspace/venv/bin/python /workspace/narrate_funnel.py
Output -> /workspace/out_narr/{NN}__s{seed}.wav (narration) + /workspace/out_diary/{NN}__s{seed}.wav (GGS)
"""
import gc, json, os, sys
import torch
import soundfile as sf
from voxcpm.core import VoxCPM
from voxcpm.model.voxcpm import LoRAConfig

BASE = "/workspace/VoxCPM2"
LORA = "/workspace/lora_champion"
CLIPS = "/workspace/voice-cloning/data/out/lecture1/final/clips"
REF_CALM = f"{CLIPS}/ggs_l1_0001.wav"                 # GGS calmest strong-identity clip
CHUNKS = "/workspace/diary_chunks_calm.txt"
OUT = "/workspace/out_diary"                          # GGS first-person
OUT_NARR = "/workspace/out_narr"                      # male 3rd-person narrator
NARR = {1, 2, 3}                                       # third-person framing lines
NARR_DESC = "(A calm, warm, mature male narrator, gentle, measured, reverent, soft low voice)"
NARR_SEEDS = [42, 123, 7, 2024, 99, 314]
SEEDS = [42, 123, 7, 2024, 99, 314, 777, 2025,        # first 8 already on the volume (skip-if-exists)
         1, 11, 21, 55, 88, 111, 222, 333,            # + 16 new -> 24 total = bigger pool for the funnel
         444, 555, 666, 888, 999, 1234, 1976, 8848]

os.makedirs(OUT, exist_ok=True); os.makedirs(OUT_NARR, exist_ok=True)
lines = [l.strip() for l in open(CHUNKS, encoding="utf-8") if l.strip()]
narr_lines = [(i, l) for i, l in enumerate(lines, 1) if i in NARR]
ggs_lines = [(i, l) for i, l in enumerate(lines, 1) if i not in NARR]
print(f"=== narration {sorted(NARR)} (male base) + {len(ggs_lines)} GGS chunks x {len(SEEDS)} seeds ===",
      file=sys.stderr)

# ---- PASS 1: male narrator, BASE model (NO LoRA -> a voice distinct from GGS) ----
mb = VoxCPM.from_pretrained(hf_model_id=BASE, load_denoiser=True, optimize=False)
sr = mb.tts_model.sample_rate
narr_ref = "/workspace/narr_ref.wav"
if not os.path.exists(narr_ref):                     # design the narrator once, then reference-lock it
    sf.write(narr_ref, mb.generate(text=NARR_DESC + lines[0], cfg_value=2.0, inference_timesteps=15, seed=42), sr)
    print("wrote narr_ref", file=sys.stderr)
for i, line in narr_lines:
    for s in NARR_SEEDS:
        out = f"{OUT_NARR}/{i:02d}__s{s}.wav"
        if os.path.exists(out):
            continue
        wav = mb.generate(text=line, reference_wav_path=narr_ref, cfg_value=1.8, inference_timesteps=18, seed=s)
        sf.write(out, wav, sr); print(f"wrote narr {i:02d}__s{s}", file=sys.stderr)
del mb; gc.collect(); torch.cuda.empty_cache()

# ---- PASS 2: GGS first-person, LoRA + calm reference ----
info = json.load(open(f"{LORA}/lora_config.json"))
cfg = LoRAConfig(**info["lora_config"]) if info.get("lora_config") else None
m = VoxCPM.from_pretrained(hf_model_id=BASE, load_denoiser=True, optimize=False,
                           lora_config=cfg, lora_weights_path=LORA)
for i, line in ggs_lines:
    for s in SEEDS:
        out = f"{OUT}/{i:02d}__s{s}.wav"
        if os.path.exists(out):
            continue
        wav = m.generate(text=line, reference_wav_path=REF_CALM, cfg_value=1.6, inference_timesteps=20, seed=s)
        sf.write(out, wav, sr); print(f"wrote {i:02d}__s{s}", file=sys.stderr)
del m; gc.collect(); torch.cuda.empty_cache()
print("ALL DONE")
