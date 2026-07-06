"""improve_clone.py — fix the zero-shot ONSET garble. Same reference (0074, sounds like him),
sweep 3 fixes x 2 problem sentences. Loads model once."""
import json, numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
rows = [json.loads(l) for l in open(f"{BASE}/train.jsonl", encoding="utf-8") if l.strip()]
ref = [r for r in rows if r["audio"] == "wavs/ggm-hindi-lecture-01_0074.wav"][0]
ref_wav, ref_text = f"{BASE}/{ref['audio']}", ref["text"]

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate

def gen(text, seed=42, ts=30, cfg=2.0, norm=True):
    return np.asarray(m.generate(text=text, prompt_wav_path=ref_wav, prompt_text=ref_text,
                                 cfg_value=cfg, inference_timesteps=ts, normalize=norm,
                                 seed=seed)).flatten()

sents = {
    "harekrishna": "हरे कृष्ण। आज हम श्रीमद्भागवत की कथा सुनेंगे।",
    "jeevan": "जीवन का असली उद्देश्य कृष्ण की भक्ति और सेवा करना है।",
}
for key, s in sents.items():
    variants = {
        "A_norm30":  gen(s, ts=30, norm=True),                 # more refinement + text norm
        "B_leadin":  gen("जी हाँ। " + s, ts=30, norm=True),    # filler absorbs onset garble
        "C_cfg15":   gen(s, ts=30, cfg=1.5, norm=True),        # lower guidance
    }
    for vname, wav in variants.items():
        sf.write(f"/workspace/imp_{key}_{vname}.wav", wav, sr)
        print(f"{key}/{vname}: finite={bool(np.isfinite(wav).all())} dur={len(wav)/sr:.2f}s "
              f"rms={float(np.sqrt(np.mean(wav**2))):.3f}")
print(f"sample_rate={sr}")
