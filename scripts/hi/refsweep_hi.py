"""refsweep_hi.py — stage 2 reference selection: generate from each shortlisted reference, so we can
score the OUTPUT identity (the plan's refsweep-confirm). hifi mode (only mode available) + 'हे जी।' lead-in
(trimmed/absorbed onset). 12 refs x 2 sentences x 2 seeds. Resumable."""
import json, os, sys
import numpy as np, soundfile as sf
from voxcpm import VoxCPM

BASE = "/workspace/voice-cloning/data/hi/train_final"
OUT = "/workspace/out_refsweep"
os.makedirs(OUT, exist_ok=True)
refs = [json.loads(l) for l in open("/workspace/ref_shortlist.jsonl", encoding="utf-8") if l.strip()]
LEADIN = "हे जी। "
SENTS = [("hk", "हरे कृष्ण। आज हम श्रीमद्भागवत की कथा सुनेंगे।"),
         ("jv", "जीवन का असली उद्देश्य कृष्ण की भक्ति और सेवा करना है।")]
SEEDS = [42, 7]

m = VoxCPM.from_pretrained("/workspace/VoxCPM2", load_denoiser=False)
sr = m.tts_model.sample_rate
jobs = [(r, sid, txt, s) for r in refs for (sid, txt) in SENTS for s in SEEDS]
todo = [j for j in jobs
        if not os.path.exists(f"{OUT}/r{os.path.splitext(os.path.basename(j[0]['audio']))[0]}__{j[1]}__s{j[3]}.wav")]
print(f"{len(todo)}/{len(jobs)} takes to generate", file=sys.stderr)
for r, sid, txt, seed in todo:
    stem = os.path.splitext(os.path.basename(r["audio"]))[0]
    out = f"{OUT}/r{stem}__{sid}__s{seed}.wav"
    try:
        w = np.asarray(m.generate(text=LEADIN + txt, prompt_wav_path=f"{BASE}/{r['audio']}",
                                  prompt_text=r["text"], cfg_value=2.0, inference_timesteps=10,
                                  seed=seed)).flatten()
        sf.write(out, w, sr)
        print(f"wrote {os.path.basename(out)}", file=sys.stderr)
    except Exception as e:
        print(f"FAILED {os.path.basename(out)}: {type(e).__name__}: {e}", file=sys.stderr)
print("DONE")
