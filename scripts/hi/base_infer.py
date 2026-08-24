"""base_infer.py — sanity-check that BASE VoxCPM2 (no LoRA) generates clean audio in this env.
If finite + non-silent -> model/env OK, the NaN is purely a training-loss issue.
If nan / silence -> the base model or env is broken (bad download / torch 2.6), which is the real root."""
import numpy as np, soundfile as sf, sys
from voxcpm import VoxCPM

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
tests = [
    ("en", "This is a test of the base model, one two three."),
    ("hi", "भगवान की कथा सुनो, यह बहुत सुंदर है।"),
]
for name, text in tests:
    try:
        wav = m.generate(text=text, cfg_value=2.0, inference_timesteps=10, seed=42)
        wav = np.asarray(wav).flatten()
        finite = bool(np.isfinite(wav).all())
        rms = float(np.sqrt(np.mean(wav**2))) if len(wav) else 0.0
        peak = float(np.max(np.abs(wav))) if len(wav) else 0.0
        print(f"[{name}] finite={finite} samples={len(wav)} dur={len(wav)/sr:.2f}s "
              f"rms={rms:.4f} peak={peak:.3f}")
        sf.write(f"/workspace/base_{name}.wav", wav, sr)
    except Exception as e:
        print(f"[{name}] FAILED: {type(e).__name__}: {e}")
print(f"sample_rate={sr}")
