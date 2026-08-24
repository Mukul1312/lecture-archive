"""
extract_hindi_v3.py — CLEAN Hindi clip extraction, built on MEASURED ground truth.

Replaces v2's broken Whisper-LID hi-spans (proven garbage: MMS-LID + the ear-check showed no LID can pick
out his Odia-accented Hindi — see docs/hindi-extraction-pipeline-research.md) with:
  BASE  = GGS's diarized speech intervals (content_triage.json `ggs_intervals`) — a SPEAKER decision, reliable
  MINUS = sung kirtana/bhajan (content_triage_music.json `music_segments`, from strip_kirtana / inaSpeech)
  CUT   = Silero-VAD + the FIXED clips_from_speech (no gap-bridging) -> clean 3-15s clips
  TEXT  = 3 ASR drafts/clip (IndicConformer + Vaani + Trelis) for the transcript-review gallery

Odia is ~0 (measured), so no Odia filter. Residual pure-English / a little Bengali-Sanskrit / noise are
dropped by the HUMAN review, not by any LID. Keep accented Hindi + embedded English.

Runs on a pod with: torch, transformers==4.46.3, silero-vad, ffmpeg. Needs HF token (IndicConformer gated).
  python cloud/extract_hindi_v3.py
Output per lecture: clips_hi/*.wav + train_hi_v3.jsonl {audio, lecture, start, end, texts:{model->draft}}
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent.parent
HI = ROOT / "data" / "hi" / "lectures"

MODELS = [                                        # (spec, display label)
    ("indicconformer", "IndicConformer-600M RNNT"),
    ("whisper:ARTPARK-IISc/whisper-large-v3-vaani-hindi@openai/whisper-large-v3", "Vaani-Hindi"),
    ("whisper:Trelis/whisper-hinglish-preview@openai/whisper-large-v3", "Trelis-Hinglish"),
]


def to_wav_16k(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-ac", "1", "-ar", "16000", str(dst)], check=True)
    return dst


def subtract_music(intervals, music, pad=0.3):
    """GGS speech intervals minus (padded) music segments -> clean-speech intervals (kirtana removed)."""
    m = sorted((max(0.0, s - pad), e + pad) for s, e in music)
    out = []
    for (a, b) in intervals:
        segs = [(a, b)]
        for (ms, me) in m:
            nxt = []
            for (s, e) in segs:
                if me <= s or ms >= e:            # no overlap
                    nxt.append((s, e))
                else:                             # cut the music span out
                    if s < ms:
                        nxt.append((s, ms))
                    if me < e:
                        nxt.append((me, e))
            segs = nxt
        out.extend([(s, e) for s, e in segs if e - s > 0.5])
    return out


def clips_from_speech(segs, min_s, max_s, gap_bridge=0.6):
    """FIXED cutter (v2 bug): any pause > gap_bridge ENDS the clip (flush if long enough, else discard) —
    clips never bridge across a removed/silent gap."""
    clips, cur = [], []
    for s, e in segs:
        if cur and (s - cur[-1][1] > gap_bridge):
            if cur[-1][1] - cur[0][0] >= min_s:
                clips.append((cur[0][0], cur[-1][1]))
            cur = []
        cur.append((s, e))
        if cur[-1][1] - cur[0][0] >= max_s:
            clips.append((cur[0][0], cur[-1][1]))
            cur = []
    if cur and (cur[-1][1] - cur[0][0] >= min_s):
        clips.append((cur[0][0], cur[-1][1]))
    return clips


def in_intervals(seg, intervals, pad=0.1):
    s, e = seg
    return any(s >= a - pad and e <= b + pad for a, b in intervals)


def build_whisper(hf_id, base, dev):
    from transformers import (pipeline, WhisperForConditionalGeneration,
                              WhisperProcessor, GenerationConfig)
    model = WhisperForConditionalGeneration.from_pretrained(hf_id)
    model.generation_config = GenerationConfig.from_pretrained(base)   # graft modern gen-config
    proc = WhisperProcessor.from_pretrained(hf_id)
    pipe = pipeline("automatic-speech-recognition", model=model, tokenizer=proc.tokenizer,
                    feature_extractor=proc.feature_extractor, device=(0 if dev == "cuda" else -1), chunk_length_s=30)

    def transcribe(p):
        return pipe(p, generate_kwargs={"language": "hi", "task": "transcribe"})["text"].strip()
    return transcribe, pipe


def build_indicconformer(dev):
    from transformers import AutoModel
    m = AutoModel.from_pretrained("ai4bharat/indic-conformer-600m-multilingual",
                                  trust_remote_code=True).to(dev).eval()

    def transcribe(p):
        w, sr = torchaudio.load(p)
        if w.shape[0] > 1:
            w = w.mean(0, keepdim=True)
        if sr != 16000:
            w = torchaudio.transforms.Resample(sr, 16000)(w)
        with torch.no_grad():
            out = m(w.to(dev), "hi", "rnnt")
        return (out[0] if isinstance(out, (list, tuple)) else out).strip()
    return transcribe, m


def purge(hf_id):
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        base = Path(HF_HUB_CACHE)
    except Exception:
        base = Path.home() / ".cache" / "huggingface" / "hub"
    d = base / ("models--" + hf_id.replace("/", "--"))
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="one lecture (default: all)")
    ap.add_argument("--min-sec", type=float, default=3.0)
    ap.add_argument("--max-sec", type=float, default=15.0)
    ap.add_argument("--base-whisper", default="openai/whisper-large-v3")
    ap.add_argument("--keep-cache", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    from silero_vad import load_silero_vad, get_speech_timestamps, read_audio
    vad = load_silero_vad()

    slugs = [a.slug] if a.slug else [p.name for p in sorted(HI.iterdir()) if p.is_dir()]

    # PASS 1 — cut clips (VAD inside GGS-intervals-minus-kirtana)
    all_clips = {}                                # slug -> [(cs, ce, dst_path)]
    for slug in slugs:
        d = HI / slug
        tj, mj = d / "content_triage.json", d / "content_triage_music.json"
        if not tj.exists():
            print(f"  skip {slug}: no content_triage.json")
            continue
        ggs = [tuple(x) for x in json.loads(tj.read_text(encoding="utf-8")).get("ggs_intervals", [])]
        music = ([tuple(x) for x in json.loads(mj.read_text(encoding="utf-8")).get("music_segments", [])]
                 if mj.exists() else [])
        kept = subtract_music(ggs, music)
        wav16 = to_wav_16k(d / "audio.mp3", ROOT / "_work" / f"hi_{slug}.wav")
        y = read_audio(str(wav16), sampling_rate=16000)
        sp = get_speech_timestamps(y, vad, sampling_rate=16000, return_seconds=True)
        segs = [(s["start"], s["end"]) for s in sp if in_intervals((s["start"], s["end"]), kept)]
        clips = clips_from_speech(segs, a.min_sec, a.max_sec)
        cdir = d / "clips_hi"
        cdir.mkdir(parents=True, exist_ok=True)
        for old in cdir.glob("*.wav"):
            old.unlink()
        lst = []
        for i, (cs, ce) in enumerate(clips, 1):
            dst = cdir / f"{slug}_{i:04d}.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav16),
                            "-ss", str(cs), "-to", str(ce), str(dst)], check=True)
            lst.append((round(cs, 2), round(ce, 2), dst))
        all_clips[slug] = lst
        sec = sum(ce - cs for cs, ce, _ in lst)
        print(f"  {slug}: {len(lst)} clips, {sec/60:.1f}min "
              f"(GGS {sum(e-s for s,e in ggs)/60:.0f}m − kirtana {sum(e-s for s,e in music)/60:.1f}m)")

    tot = sum(len(v) for v in all_clips.values())
    print(f"\ncut {tot} clips; transcribing with {len(MODELS)} models (one at a time) ...", file=sys.stderr)

    # PASS 2 — transcribe every clip with each model
    texts = {slug: {i: {} for i in range(len(lst))} for slug, lst in all_clips.items()}
    for spec, label in MODELS:
        print(f"\n=== {label} ===", file=sys.stderr)
        try:
            if spec.startswith("whisper:"):
                body = spec[len("whisper:"):]
                hf_id, _, base = body.partition("@")
                base = base or a.base_whisper
                cache_id = hf_id
                transcribe, handle = build_whisper(hf_id, base, dev)
            else:
                cache_id = "ai4bharat/indic-conformer-600m-multilingual"
                transcribe, handle = build_indicconformer(dev)
        except Exception as ex:
            print(f"  LOAD FAILED {label}: {ex}", file=sys.stderr)
            for slug, lst in all_clips.items():
                for i in range(len(lst)):
                    texts[slug][i][label] = "[[LOAD FAILED]]"
            continue
        n = 0
        for slug, lst in all_clips.items():
            for i, (cs, ce, dst) in enumerate(lst):
                try:
                    texts[slug][i][label] = transcribe(str(dst))
                except Exception as ex:
                    texts[slug][i][label] = f"[[ERR: {ex}]]"
                n += 1
                if n % 40 == 0:
                    print(f"  {n}/{tot}", file=sys.stderr)
        del handle, transcribe
        if dev == "cuda":
            torch.cuda.empty_cache()
        if not a.keep_cache:
            purge(cache_id)

    for slug, lst in all_clips.items():
        rows = [{"audio": f"clips_hi/{dst.name}", "lecture": slug, "start": cs, "end": ce, "texts": texts[slug][i]}
                for i, (cs, ce, dst) in enumerate(lst)]
        (HI / slug / "train_hi_v3.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    print(f"\n==== CLEAN HINDI v3 ==== {tot} clips across {len(all_clips)} lectures "
          f"(GGS-diarized − kirtana, {len(MODELS)} ASR drafts each)")
    print("NEXT: build the transcript-review gallery on train_hi_v3.jsonl.")


if __name__ == "__main__":
    main()
