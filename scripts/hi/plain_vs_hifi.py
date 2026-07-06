"""plain_vs_hifi.py — test the issue-#288 onset fix: HIFI (prompt_text on) vs PLAIN (prompt_text off).
Same reference (0074), same 2 defect sentences, seed 42. If plain fixes the garbled onset -> we switch mode."""
import json, numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
rows = [json.loads(l) for l in open(f"{BASE}/train.jsonl", encoding="utf-8") if l.strip()]
ref = [r for r in rows if r["audio"] == "wavs/ggm-hindi-lecture-01_0074.wav"][0]
ref_wav, ref_text = f"{BASE}/{ref['audio']}", ref["text"]

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
sents = {
    "harekrishna": "हरे कृष्ण। आज हम श्रीमद्भागवत की कथा सुनेंगे।",
    "jeevan": "जीवन का असली उद्देश्य कृष्ण की भक्ति और सेवा करना है।",
}
for key, s in sents.items():
    # HIFI: with prompt_text (the mode that garbled the onset)
    wh = np.asarray(m.generate(text=s, prompt_wav_path=ref_wav, prompt_text=ref_text,
                               cfg_value=2.0, inference_timesteps=10, seed=42)).flatten()
    sf.write(f"/workspace/mode_{key}_hifi.wav", wh, sr)
    # PLAIN: NO prompt_text (issue-#288 fix candidate)
    try:
        wp = np.asarray(m.generate(text=s, prompt_wav_path=ref_wav,
                                   cfg_value=2.0, inference_timesteps=10, seed=42)).flatten()
        sf.write(f"/workspace/mode_{key}_plain.wav", wp, sr)
        pd = f"{len(wp)/sr:.2f}s"
    except Exception as e:
        pd = f"FAILED: {type(e).__name__}: {e}"
    print(f"{key}: hifi={len(wh)/sr:.2f}s | plain={pd}")
print("DONE")
