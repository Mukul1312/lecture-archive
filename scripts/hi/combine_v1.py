"""combine_v1.py — v1 as ONE flowing passage (winning ref 0008). Generate the 4 sentences as a single
text (natural rhythm, one onset). Both with lead-in and without, to compare onset behavior at passage length."""
import json, os, sys
import numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
OUT = "/workspace/out_v1"; os.makedirs(OUT, exist_ok=True)
refs = {json.loads(l)["audio"]: json.loads(l)
        for l in open("/workspace/ref_shortlist.jsonl", encoding="utf-8") if l.strip()}
ref = refs["wavs/ggm-hindi-lecture-01_0008.wav"]
PASSAGE = ("हरे कृष्ण। आज हम श्रीमद्भागवत की कथा सुनेंगे। "
           "जीवन का असली उद्देश्य कृष्ण की भक्ति और सेवा करना है। "
           "भगवान की कथा सुनना ही हमारे जीवन का परम लाभ है। "
           "हरि नाम का जप करो, यही कलियुग का धर्म है।")
m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
for tag, text in [("combined_leadin", "हे जी। " + PASSAGE), ("combined_plain", PASSAGE)]:
    w = np.asarray(m.generate(text=text, prompt_wav_path=f"{BASE}/{ref['audio']}", prompt_text=ref["text"],
                              cfg_value=2.0, inference_timesteps=10, seed=42)).flatten()
    sf.write(f"{OUT}/v1_{tag}.wav", w, sr)
    print(f"wrote v1_{tag}.wav dur={len(w)/sr:.2f}s", file=sys.stderr)
print("DONE")
