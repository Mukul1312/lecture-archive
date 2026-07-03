"""
infer_diary_ab.py — Does a CALM reference + VoxCPM2 "Controllable Cloning" give a calm diary read?

The finding: our infer_pretest uses ULTIMATE cloning (prompt_wav_path + prompt_text) — VoxCPM2's style
instruction is INERT in that mode. CONTROLLABLE cloning (reference_wav_path + a parenthetical style hint,
NO prompt_text) keeps the timbre AND applies the style. VoxCPM2 (2B) supports it; our base is 2B. This
A/B/C run isolates the two new levers on the same diary lines:

  A  current best      Ultimate cloning, max-identity ref ggs_l1_0081 + its transcript, no style control
  B  calm reference    Controllable cloning, calm ref ggs_l1_0001, NO instruction   (does calm ref alone help?)
  C  full P1 fix       Controllable cloning, calm ref ggs_l1_0001 + "(calm ...)" style instruction

A->B isolates the calm reference; B->C isolates the style instruction. Score locally with
scripts/score_diary_ab.py (identity ECAPA + graveness), goal: B/C calmer than A while ECAPA >= ~0.74.

Run on the pod (champion LoRA at /workspace/lora_champion). Output -> /workspace/out_diary_ab/
  {arm}__{label}__s{seed}.wav   (~$0.10, 3 arms x 5 lines x 5 seeds = 75 clips)
"""
import gc, json, os, sys
import torch
import soundfile as sf
from voxcpm.core import VoxCPM
from voxcpm.model.voxcpm import LoRAConfig

BASE = "/workspace/VoxCPM2"
LORA = "/workspace/lora_champion"
CLIPS = "/workspace/voice-cloning/data/out/lecture1/final/clips"
OUT = "/workspace/out_diary_ab"

REF_MAXID = f"{CLIPS}/ggs_l1_0081.wav"      # max-identity (0.939 to centroid) — the current best
REF_MAXID_TEXT = ('thats the process - and an intelligent disciple like Arjuna says, "No Guru Maharaja '
                  'whatever you say Ill do. I have no other thought." This is the proper use of independence,')
REF_CALM = f"{CLIPS}/ggs_l1_0001.wav"       # calmest strong-identity clip (47.9 dB, 140 Hz, identity 0.83)
STYLE = "(calm, hushed, intimate, slow, prayerful, soft low voice)"

# diary-representative lines (prayer / confession / vow — the actual register we want)
LINES = {
    "gopala":   "Oh my Lord, Gopala! Please shower Your mercy.",
    "prayer":   "Oh Lord, please excuse this servant, as You know he has many faults.",
    "prasadam": "He will not accept any Prasadam at night.",
    "vow":      "This servant took a vow not to eat anything at night except a little maha water with Tulasi.",
    "gauranga": "May this servant achieve success in the service of Sri Sri Guru and Gauranga. Hare Krishna.",
}
SEEDS = [42, 123, 7, 2024, 99]
os.makedirs(OUT, exist_ok=True)

info = json.load(open(f"{LORA}/lora_config.json"))
cfg = LoRAConfig(**info["lora_config"]) if info.get("lora_config") else None
print("=== loading champion checkpoint (VoxCPM2 2B + LoRA) ===", file=sys.stderr)
m = VoxCPM.from_pretrained(hf_model_id=BASE, load_denoiser=True, optimize=False,
                           lora_config=cfg, lora_weights_path=LORA)
sr = m.tts_model.sample_rate


def gen(arm, label, seed, **kw):
    out = f"{OUT}/{arm}__{label}__s{seed}.wav"
    if os.path.exists(out):
        return
    wav = m.generate(seed=seed, **kw)
    sf.write(out, wav, sr)
    print(f"wrote {arm}__{label}__s{seed}", file=sys.stderr)


for label, line in LINES.items():
    for s in SEEDS:
        # A — current best: Ultimate cloning, max-identity reference, no style control
        gen("A", label, s, text=line, prompt_wav_path=REF_MAXID, prompt_text=REF_MAXID_TEXT, denoise=True)
        # B — calm reference alone: Controllable cloning, no instruction
        gen("B", label, s, text=line, reference_wav_path=REF_CALM, cfg_value=1.6, inference_timesteps=20)
        # C — full P1 fix: Controllable cloning + calm style instruction
        gen("C", label, s, text=f"{STYLE}{line}", reference_wav_path=REF_CALM, cfg_value=1.6, inference_timesteps=20)

del m; gc.collect(); torch.cuda.empty_cache()
print("ALL DONE")
