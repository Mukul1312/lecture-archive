"""asr_check.py — back-transcribe the 15 chosen diary takes with Hindi Whisper, compare to intended text.
The 'each and every word' check: does the clip actually SAY the intended Hindi? Flags mispronounced/skipped
words. Runs on the pod GPU."""
import json, sys
from math import gcd
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
import torch
from transformers import pipeline

CHOSEN = ["p01__s42", "p02__s7", "p03__s2024", "p04__s7", "p05__s123", "p06__s7", "p07__s7",
          "p08__s42", "p09__s7", "p10__s2024", "p11__s2024", "p12__s42", "p13__s42", "p14__s7", "p15__s42"]
passages = {p["id"]: p["hi"] for p in json.load(open("/workspace/diary_passages.json", encoding="utf-8"))}

def load16k(p):                                   # decode with soundfile -> bypass broken torchcodec
    y, sr = sf.read(p, dtype="float32")
    if y.ndim > 1: y = y.mean(1)
    if sr != 16000:
        g = gcd(sr, 16000); y = resample_poly(y, 16000//g, sr//g).astype("float32")
    return {"array": y, "sampling_rate": 16000}

asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3",
               device=0, dtype=torch.float16)

def lev(a, b):
    m, n = len(a), len(b)
    d = list(range(n + 1))
    for i in range(1, m + 1):
        prev, d[0] = d[0], i
        for j in range(1, n + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j-1] + 1, prev + (a[i-1] != b[j-1]))
            prev = cur
    return d[n]

print("=== ASR back-transcription (Hindi Whisper-large-v3) ===\n")
cers = []
for c in CHOSEN:
    pid = c.split("__")[0]
    ref = passages[pid]
    hyp = asr(load16k(f"/workspace/out_diary/{c}.wav"),
              generate_kwargs={"language": "hi", "task": "transcribe"})["text"].strip()
    rc = ref.replace(" ", ""); hc = hyp.replace(" ", "")
    cer = lev(rc, hc) / max(1, len(rc))
    cers.append(cer)
    print(f"### {pid}  CER {cer:.2f}")
    print(f"  intended: {ref}")
    print(f"  heard:    {hyp}\n")
print(f"=== mean CER {sum(cers)/len(cers):.2f}  (0=perfect; <0.15 good; ASR itself adds some error on Hindi) ===")
print("DONE")
