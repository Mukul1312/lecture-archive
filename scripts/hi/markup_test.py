"""markup_test.py — how much prosody markup does VoxCPM2 honor? (dubbing service, ref 0008 clean identity)
Isolates ONE variable per pair so the effect is unambiguous by ear. Content = the संन्यासी clip."""
import json, os, sys
import numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
refs = {json.loads(l)["audio"]: json.loads(l)
        for l in open("/workspace/ref_shortlist.jsonl", encoding="utf-8") if l.strip()}
ref = refs["wavs/ggm-hindi-lecture-01_0008.wav"]
OUT = "/workspace/out_markup"; os.makedirs(OUT, exist_ok=True)

TESTS = {
    # (A) QUESTION intonation: does '?' make समझे rise?
    "A1_samjhe_period":   "यह देवदासी का प्रसंग समझे।",
    "A2_samjhe_question": "यह देवदासी का प्रसंग समझे?",
    # (B) PAUSES: do …/, land pauses where marked?
    "B1_flow":     "यह देवदासी का प्रसंग जो गीत-गोविंद गा रही थी।",
    "B2_ellipsis": "यह देवदासी… का प्रसंग… जो गीत-गोविंद गा रही थी।",
    "B3_comma":    "यह देवदासी, का प्रसंग, जो गीत-गोविंद गा रही थी।",
    # (C) EMPHASIS via exclamation: does '!' add stress/energy?
    "C1_plain": "तुमने मेरी जान बचाई।",
    "C2_excl":  "तुमने मेरी जान बचाई!",
    # (D) HOLISTIC: the dramatic beat, flat vs fully annotated
    "D1_full_plain": "महाप्रभु उन्मत्त हो गए वे उसकी ओर दौड़े कोई गोपी गा रही है "
                     "गोविंद ने उन्हें रोका देवदासी गा रही है महाप्रभु रुक गए",
    "D2_full_annot": "महाप्रभु उन्मत्त हो गए। वे उसकी ओर दौड़े— “अरे! कोई गोपी गा रही है!” "
                     "गोविंद ने उन्हें रोका— “अरे! देवदासी गा रही है।” महाप्रभु… रुक गए।",
}

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
for name, text in TESTS.items():
    w = np.asarray(m.generate(text=text, prompt_wav_path=f"{BASE}/{ref['audio']}",
                              prompt_text=ref["text"], cfg_value=2.0, inference_timesteps=10,
                              seed=42)).flatten()
    sf.write(f"{OUT}/{name}.wav", w, sr)
    print(f"{name}  {len(w)/sr:.1f}s", file=sys.stderr)
print("DONE")
