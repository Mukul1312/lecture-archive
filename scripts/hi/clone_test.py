"""clone_test.py — ZERO-SHOT voice clone of GGS using VoxCPM2's built-in cloning (no training).
Feeds one clean reference clip + its transcript, generates NEW Hindi in his voice."""
import json, numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
rows = [json.loads(l) for l in open(f"{BASE}/train.jsonl", encoding="utf-8") if l.strip()]

# reference: a clean 7-10s clip, mostly Hindi (few latin chars), decent length text
def latin_frac(t):
    a = sum(c.isascii() and c.isalpha() for c in t); return a / max(1, len(t))
cands = [r for r in rows if 7 <= r["duration"] <= 10 and latin_frac(r["text"]) < 0.15]
cands.sort(key=lambda r: -len(r["text"]))
ref = cands[0] if cands else rows[0]
ref_wav = f"{BASE}/{ref['audio']}"
ref_text = ref["text"]
print(f"REFERENCE: {ref['audio']}  dur={ref['duration']}s")
print(f"REF TEXT : {ref_text}")

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate

new_texts = [
    "हरे कृष्ण। आज हम श्रीमद्भागवत की कथा सुनेंगे।",
    "जीवन का असली उद्देश्य कृष्ण की भक्ति और सेवा करना है।",
]
for i, t in enumerate(new_texts):
    wav = np.asarray(m.generate(text=t, prompt_wav_path=ref_wav, prompt_text=ref_text,
                                cfg_value=2.0, inference_timesteps=10, seed=42)).flatten()
    print(f"[clone{i}] finite={bool(np.isfinite(wav).all())} dur={len(wav)/sr:.2f}s "
          f"rms={float(np.sqrt(np.mean(wav**2))):.3f}  text={t}")
    sf.write(f"/workspace/clone_hi_{i}.wav", wav, sr)
print(f"sample_rate={sr}")
