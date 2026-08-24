"""gen_diary.py — generate each diary passage x N seeds with ref 0008 (plain flowing, hifi prompt_text).
Reads /workspace/diary_passages.json = [{id, hi}]. Resumable."""
import json, os, sys
import numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
OUT = "/workspace/out_diary"; os.makedirs(OUT, exist_ok=True)
refs = {json.loads(l)["audio"]: json.loads(l)
        for l in open("/workspace/ref_shortlist.jsonl", encoding="utf-8") if l.strip()}
ref = refs["wavs/ggm-hindi-lecture-01_0008.wav"]
passages = json.load(open("/workspace/diary_passages.json", encoding="utf-8"))
SEEDS = [42, 7, 123, 2024]

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
jobs = [(p, s) for p in passages for s in SEEDS]
todo = [j for j in jobs if not os.path.exists(f"{OUT}/{j[0]['id']}__s{j[1]}.wav")]
print(f"{len(todo)}/{len(jobs)} takes ({len(passages)} passages x {len(SEEDS)} seeds)", file=sys.stderr)
for p, seed in todo:
    try:
        w = np.asarray(m.generate(text=p["hi"], prompt_wav_path=f"{BASE}/{ref['audio']}",
                                  prompt_text=ref["text"], cfg_value=2.0, inference_timesteps=10,
                                  seed=seed)).flatten()
        sf.write(f"{OUT}/{p['id']}__s{seed}.wav", w, sr)
        print(f"wrote {p['id']}__s{seed} dur={len(w)/sr:.1f}s", file=sys.stderr)
    except Exception as e:
        print(f"FAIL {p['id']}__s{seed}: {type(e).__name__}: {e}", file=sys.stderr)
print("DONE")
