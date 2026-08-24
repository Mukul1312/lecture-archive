"""gen_fixes_expr.py — one pod job, two tracks.
A) fix the flagged diary passages (ref 0008, 6 seeds each) -> /workspace/out_fixes/
B) expressive-reference sweep: 5 animated refs x 2 sentences x 2 seeds -> /workspace/out_expr/
Resumable."""
import json, os, sys
import numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
refs = {json.loads(l)["audio"]: json.loads(l)
        for l in open("/workspace/ref_shortlist.jsonl", encoding="utf-8") if l.strip()}
ref8 = refs["wavs/ggm-hindi-lecture-01_0008.wav"]
fixes = json.load(open("/workspace/fix_passages.json", encoding="utf-8"))
expr = [json.loads(l) for l in open("/workspace/expressive_refs.jsonl", encoding="utf-8") if l.strip()]

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
def gen(text, ref, seed):
    return np.asarray(m.generate(text=text, prompt_wav_path=f"{BASE}/{ref['audio']}",
                                 prompt_text=ref["text"], cfg_value=2.0, inference_timesteps=10,
                                 seed=seed)).flatten()

# ---- Track A: regenerate flagged passages (kalpataru fix + onset), 6 seeds ----
os.makedirs("/workspace/out_fixes", exist_ok=True)
for p in fixes:
    for s in [42, 7, 123, 2024, 99, 314]:
        out = f"/workspace/out_fixes/{p['id']}__s{s}.wav"
        if os.path.exists(out): continue
        try:
            sf.write(out, gen(p["hi"], ref8, s), sr); print(f"A {p['id']} s{s}", file=sys.stderr)
        except Exception as e:
            print(f"A FAIL {p['id']} s{s}: {e}", file=sys.stderr)

# ---- Track B: expressive-reference sweep ----
os.makedirs("/workspace/out_expr", exist_ok=True)
SENTS = [("hk", "हरे कृष्ण। आज हम श्रीमद्भागवत की कथा सुनेंगे।"),
         ("jv", "जीवन का असली उद्देश्य कृष्ण की भक्ति और सेवा करना है।")]
for r in expr:
    stem = os.path.splitext(os.path.basename(r["audio"]))[0]
    for sid, txt in SENTS:
        for s in [42, 7]:
            out = f"/workspace/out_expr/r{stem}__{sid}__s{s}.wav"
            if os.path.exists(out): continue
            try:
                sf.write(out, gen(txt, r, s), sr); print(f"B {stem} {sid} s{s}", file=sys.stderr)
            except Exception as e:
                print(f"B FAIL {stem} {sid} s{s}: {e}", file=sys.stderr)
print("DONE")
