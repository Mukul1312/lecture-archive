"""
asr_ab.py — head-to-head ASR A/B on GGSM's ACTUAL clips (decide by his voice, not benchmark tables).

Transcribes the SAME VAD-cut clips (already produced on the pod by extract_hindi_v2) with several Hindi
ASR models and emits a side-by-side gallery, so we pick the transcriber empirically. Rationale + the model
shortlist: docs/hindi-asr-model-research.md.

--models is comma-separated; each entry is one of:
    whisper:<hf_id>                     Hindi Whisper fine-tune (base gen-config = openai/whisper-large-v2)
    whisper:<hf_id>@<base_whisper>      ... with an explicit base whose generation_config is grafted on
    indicconformer[:rnnt|:ctc]          AI4Bharat IndicConformer-600M (gated; needs HF access + HF_TOKEN)
Default = the 4-way shortlist from the research.

Loads one model at a time (frees GPU between) so 4 large models don't co-reside. Reads existing
data/hi/lectures/<slug>/clips_hi/*.wav; writes voice_lab/asr_ab/index.html (+ audio) and asr_ab.jsonl.

  /workspace/venv_asr/bin/python cloud/asr_ab.py --n 25
  /workspace/venv_asr/bin/python cloud/asr_ab.py --slug ggm-hindi-lecture-01 --n 15
  /workspace/venv_asr/bin/python cloud/asr_ab.py --models "whisper:ARTPARK-IISc/whisper-large-v3-vaani-hindi,indicconformer:rnnt"
"""
import argparse
import html
import json
import shutil
import sys
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent.parent
HI = ROOT / "data" / "hi" / "lectures"
OUT = ROOT / "voice_lab" / "asr_ab"

DEFAULT_MODELS = ",".join([
    "whisper:vasista22/whisper-hindi-large-v2",
    "whisper:ARTPARK-IISc/whisper-large-v3-vaani-hindi@openai/whisper-large-v3",
    "whisper:Trelis/whisper-hinglish-preview@openai/whisper-large-v3",
    "indicconformer:rnnt",
])

# short, human-friendly column labels
LABELS = {
    "whisper:vasista22/whisper-hindi-large-v2": "vasista22-large-v2 (baseline)",
    "whisper:ARTPARK-IISc/whisper-large-v3-vaani-hindi@openai/whisper-large-v3": "Vaani-Hindi (accent+noise)",
    "whisper:Trelis/whisper-hinglish-preview@openai/whisper-large-v3": "Trelis-Hinglish (code-switch)",
    "indicconformer:rnnt": "IndicConformer-600M RNNT",
    "indicconformer:ctc": "IndicConformer-600M CTC",
}


def purge_hf_cache(hf_id):
    """Delete a model's HF hub cache dir to free disk between A/B models (4 large models won't co-fit)."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        base = Path(HF_HUB_CACHE)
    except Exception:
        base = Path.home() / ".cache" / "huggingface" / "hub"
    d = base / ("models--" + hf_id.replace("/", "--"))
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return "removed"
    return "not-found"


def build_whisper(hf_id, base, dev):
    from transformers import (pipeline, WhisperForConditionalGeneration,
                              WhisperProcessor, GenerationConfig)
    model = WhisperForConditionalGeneration.from_pretrained(hf_id)
    # Many Hindi fine-tunes ship an outdated generation_config (no language map, empty suppress_tokens);
    # graft a modern base config so generate(language=...) works. See docs/hindi-asr-model-research.md.
    model.generation_config = GenerationConfig.from_pretrained(base)
    proc = WhisperProcessor.from_pretrained(hf_id)
    pipe = pipeline("automatic-speech-recognition", model=model, tokenizer=proc.tokenizer,
                    feature_extractor=proc.feature_extractor,
                    device=(0 if dev == "cuda" else -1), chunk_length_s=30)

    def transcribe(wav_path):
        return pipe(wav_path, generate_kwargs={"language": "hi", "task": "transcribe"})["text"].strip()

    return transcribe, pipe


def build_indicconformer(decoder, dev):
    from transformers import AutoModel
    model = AutoModel.from_pretrained("ai4bharat/indic-conformer-600m-multilingual",
                                      trust_remote_code=True).to(dev).eval()

    def transcribe(wav_path):
        w, sr = torchaudio.load(wav_path)
        if w.shape[0] > 1:
            w = w.mean(0, keepdim=True)
        if sr != 16000:
            w = torchaudio.transforms.Resample(sr, 16000)(w)
        with torch.no_grad():
            out = model(w.to(dev), "hi", decoder)
        return (out[0] if isinstance(out, (list, tuple)) else out).strip()

    return transcribe, model


def sample_clips(slug, n):
    """Evenly sample n clips across lectures (deterministic) for a representative spread."""
    if slug:
        clips = sorted((HI / slug / "clips_hi").glob("*.wav"))
    else:
        clips = sorted(HI.glob("*/clips_hi/*.wav"))
    if n and len(clips) > n:
        step = len(clips) / n
        clips = [clips[int(i * step)] for i in range(n)]
    return clips


HEAD = """<!doctype html><html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Hindi ASR A/B — GGSM clips</title>
<style>
 body{{margin:0;background:#12100f;color:#f3eee9;font:15px/1.55 system-ui,Segoe UI,Roboto,sans-serif}}
 .wrap{{max-width:1000px;margin:0 auto;padding:20px}}
 h1{{font-size:20px;color:#c9a24a;margin:0 0 4px}} .note{{color:#a89f97;font-size:13px;margin:0 0 18px}}
 .clip{{background:#1d1a18;border:1px solid #332e2a;border-radius:12px;padding:12px 14px;margin:0 0 16px}}
 .cid{{font:12px ui-monospace,Menlo,monospace;color:#8f8880;margin:0 0 8px}}
 audio{{width:100%;height:36px;margin:0 0 10px}}
 table{{width:100%;border-collapse:collapse}}
 td{{vertical-align:top;padding:7px 8px;border-top:1px solid #2a2521}}
 td.m{{width:210px;color:#c9a24a;font-size:12px;font-weight:600}}
 td.t{{font:16px/1.5 'Noto Sans Devanagari',serif;color:#e9dcc4}}
 .empty{{color:#7a5555;font-style:italic}}
</style></head><body><div class="wrap">
<h1>Hindi ASR A/B — GGSM's actual clips</h1>
<p class="note">Same clip, every model. Judge: fewest hallucinations/loops, English &amp; Sanskrit rendered right,
fewest Devanagari matra errors, his devotional vocabulary correct. Big disagreements between a Whisper model and
IndicConformer = that clip needs human review. {n} clips × {m} models.</p>
"""
FOOT = "</div></body></html>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="one lecture (default: all)")
    ap.add_argument("--n", type=int, default=25, help="clips to sample")
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--keep-cache", action="store_true",
                    help="don't delete each model's HF cache after use (needs disk for all models at once)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {dev}", file=sys.stderr)
    clips = sample_clips(a.slug, a.n)
    if not clips:
        sys.exit("no clips found — run extract_hindi_v2 first")
    specs = [s.strip() for s in a.models.split(",") if s.strip()]
    print(f"{len(clips)} clips × {len(specs)} models", file=sys.stderr)

    results = {c: {} for c in clips}  # clip -> {spec: text}
    for spec in specs:
        print(f"\n=== loading {spec} ===", file=sys.stderr)
        cache_id = None
        try:
            if spec.startswith("whisper:"):
                body = spec[len("whisper:"):]
                hf_id, _, base = body.partition("@")
                base = base or "openai/whisper-large-v2"
                cache_id = hf_id
                transcribe, handle = build_whisper(hf_id, base, dev)
            elif spec.startswith("indicconformer"):
                cache_id = "ai4bharat/indic-conformer-600m-multilingual"
                dec = spec.split(":", 1)[1] if ":" in spec else "rnnt"
                transcribe, handle = build_indicconformer(dec, dev)
            else:
                print(f"  ?? unknown model spec, skipping: {spec}", file=sys.stderr)
                continue
        except Exception as e:
            print(f"  !! load failed for {spec}: {e}", file=sys.stderr)
            for c in clips:
                results[c][spec] = f"[[LOAD FAILED: {e}]]"
            if cache_id and not a.keep_cache:
                purge_hf_cache(cache_id)  # drop any partial download so the next model has room
            continue
        for i, c in enumerate(clips, 1):
            try:
                results[c][spec] = transcribe(str(c))
            except Exception as e:
                results[c][spec] = f"[[ERROR: {e}]]"
            if i % 5 == 0:
                print(f"  {i}/{len(clips)}", file=sys.stderr)
        del handle, transcribe
        if dev == "cuda":
            torch.cuda.empty_cache()
        if cache_id and not a.keep_cache:
            print(f"  purged {cache_id} cache: {purge_hf_cache(cache_id)}", file=sys.stderr)

    # write JSONL + gallery
    OUT.mkdir(parents=True, exist_ok=True)
    aud = OUT / "audio"
    aud.mkdir(exist_ok=True)
    for old in aud.glob("*.wav"):
        old.unlink()

    rows_jsonl = []
    body = [HEAD.format(n=len(clips), m=len(specs))]
    for c in clips:
        cid = f"{c.parent.parent.name}/{c.name}"
        dst = aud / c.name
        shutil.copy(c, dst)
        body.append(f'<div class="clip"><div class="cid">{html.escape(cid)}</div>')
        body.append(f'<audio controls preload="none" src="audio/{c.name}"></audio><table>')
        for spec in specs:
            txt = results[c].get(spec, "")
            label = LABELS.get(spec, spec)
            cell = html.escape(txt) if txt else '<span class="empty">(empty)</span>'
            body.append(f'<tr><td class="m">{html.escape(label)}</td><td class="t">{cell}</td></tr>')
        body.append('</table></div>')
        rows_jsonl.append({"clip": cid, "texts": {LABELS.get(s, s): results[c].get(s, "") for s in specs}})
    body.append(FOOT)
    (OUT / "index.html").write_text("\n".join(body), encoding="utf-8")
    (OUT / "asr_ab.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows_jsonl), encoding="utf-8")
    print(f"\nwrote {OUT/'index.html'} and asr_ab.jsonl  ({len(clips)} clips × {len(specs)} models)")
    print("NEXT: serve voice_lab/asr_ab over the tunnel and eyeball; pick the winner, run it on all clips.")


if __name__ == "__main__":
    main()
