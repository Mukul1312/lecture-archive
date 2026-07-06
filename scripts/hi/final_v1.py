"""final_v1.py — v1 zero-shot clone with the sweep-WINNING reference (clip 0008, out-ECAPA 0.784).
hifi mode + 'हे जी।' lead-in (trimmed locally after). 4 devotional sentences."""
import json, os, sys
import numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
OUT = "/workspace/out_v1"; os.makedirs(OUT, exist_ok=True)
refs = {json.loads(l)["audio"]: json.loads(l)
        for l in open("/workspace/ref_shortlist.jsonl", encoding="utf-8") if l.strip()}
ref = refs["wavs/ggm-hindi-lecture-01_0008.wav"]
print(f"reference: {ref['audio']}  text: {ref['text'][:50]}", file=sys.stderr)
LEADIN = "हे जी। "
SENTS = [
    ("hk", "हरे कृष्ण। आज हम श्रीमद्भागवत की कथा सुनेंगे।"),
    ("jv", "जीवन का असली उद्देश्य कृष्ण की भक्ति और सेवा करना है।"),
    ("katha", "भगवान की कथा सुनना ही हमारे जीवन का परम लाभ है।"),
    ("nam", "हरि नाम का जप करो, यही कलियुग का धर्म है।"),
]
m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
for sid, txt in SENTS:
    w = np.asarray(m.generate(text=LEADIN + txt, prompt_wav_path=f"{BASE}/{ref['audio']}",
                              prompt_text=ref["text"], cfg_value=2.0, inference_timesteps=10,
                              seed=42)).flatten()
    sf.write(f"{OUT}/v1_{sid}.wav", w, sr)
    print(f"wrote v1_{sid}.wav  dur={len(w)/sr:.2f}s", file=sys.stderr)
print("DONE")
