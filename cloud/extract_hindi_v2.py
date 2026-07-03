"""
extract_hindi_v2.py — HINDI data-prep v2: clean cuts (VAD) + a Hindi-specialized ASR.

v1 (extract_hindi.py) used Whisper-large-v3 and cut at Whisper's own segment boundaries -> on his
noisy, 56 kbps, Odia-accented Hindi BOTH the text and the clip boundaries came out bad. v2 fixes both:
  BOUNDARIES: Silero-VAD (noise-robust) finds real acoustic pauses inside the confident-Hindi spans
              (from content_triage.json), and clips are cut at those pauses -> structurally never mid-word.
  TEXT:       AI4Bharat IndicConformer-600M (RNNT), trained on IndicVoices (real accented + noisy Indian
              field audio) -> far better Hindi than large-v3. Clips are pre-cut, so no timestamps needed.

Output per lecture: data/hi/lectures/<slug>/clips_hi/*.wav + train_hi.jsonl {audio,text,lecture,start,end}.
`text` is still a DRAFT (correct in the gallery) but should need only light edits now.

Runs on a pod with: transformers, torchaudio, onnxruntime-gpu==1.20.1, onnx==1.20.1, silero-vad.
Reuses pod_dataprep.to_wav_16k + cut. Reads the (already-committed) content_triage.json LID spans.
  python cloud/extract_hindi_v2.py --langs hi,ur
  python cloud/extract_hindi_v2.py --slug ggm-hindi-lecture-03
"""
import argparse
import json
import sys
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cloud"))
import pod_dataprep as pdp                        # to_wav_16k, cut

HI = ROOT / "data" / "hi" / "lectures"


def merge_spans(wins, langs, min_prob, gap=1.0):
    keep = sorted((w["start"], w["end"]) for w in wins if w["lang"] in langs and w["prob"] >= min_prob)
    out = []
    for s, e in keep:
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def clips_from_speech(segs, min_s, max_s, gap_bridge=0.6):
    """segs: [(start,end)] VAD speech (within a span) -> clips ~min..max sec, flushed at a real pause
    (a gap > gap_bridge once the clip is long enough, or hard max). Boundaries sit at speech edges,
    i.e. next to silence -> clean cuts, never mid-word."""
    clips, cur = [], []
    for s, e in segs:
        if cur and (s - cur[-1][1] > gap_bridge) and (cur[-1][1] - cur[0][0] >= min_s):
            clips.append((cur[0][0], cur[-1][1]))
            cur = []
        cur.append((s, e))
        if cur[-1][1] - cur[0][0] >= max_s:
            clips.append((cur[0][0], cur[-1][1]))
            cur = []
    if cur and (cur[-1][1] - cur[0][0] >= min_s):
        clips.append((cur[0][0], cur[-1][1]))
    return clips


def in_spans(seg, spans, pad=0.1):
    s, e = seg
    return any(s >= a - pad and e <= b + pad for a, b in spans)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="one lecture (default: all)")
    ap.add_argument("--langs", default="hi,ur", help="LID labels kept as Hindi (Hindustani = hi+ur)")
    ap.add_argument("--min-prob", type=float, default=0.5)
    ap.add_argument("--min-sec", type=float, default=8.0)
    ap.add_argument("--max-sec", type=float, default=18.0)
    ap.add_argument("--decoder", default="rnnt", choices=["rnnt", "ctc"], help="IndicConformer decoder")
    ap.add_argument("--asr", default="indicwhisper", choices=["indicwhisper", "indicconformer"],
                    help="indicwhisper = ungated Whisper-Hindi drop-in (default); indicconformer = gated "
                         "AI4Bharat (needs HF access granted)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {dev}", file=sys.stderr)

    from silero_vad import load_silero_vad, get_speech_timestamps, read_audio
    vad = load_silero_vad()
    if a.asr == "indicconformer":
        from transformers import AutoModel
        print("loading IndicConformer-600M (RNNT) ...", file=sys.stderr)
        model = AutoModel.from_pretrained("ai4bharat/indic-conformer-600m-multilingual",
                                          trust_remote_code=True).to(dev).eval()

        def transcribe(wav_path):
            w, sr = torchaudio.load(wav_path)
            if w.shape[0] > 1:
                w = w.mean(0, keepdim=True)
            if sr != 16000:
                w = torchaudio.transforms.Resample(sr, 16000)(w)
            with torch.no_grad():
                out = model(w.to(dev), "hi", a.decoder)
            return out[0] if isinstance(out, (list, tuple)) else out
    else:
        from transformers import pipeline
        print("loading IndicWhisper (parthiv11/indic_whisper_nodcil) ...", file=sys.stderr)
        pipe = pipeline("automatic-speech-recognition", model="parthiv11/indic_whisper_nodcil",
                        device=(0 if dev == "cuda" else -1), chunk_length_s=30)
        pipe.model.config.forced_decoder_ids = pipe.tokenizer.get_decoder_prompt_ids(
            language="hi", task="transcribe")

        def transcribe(wav_path):
            return pipe(wav_path)["text"]

    langs = set(a.langs.split(","))
    slugs = [a.slug] if a.slug else [p.name for p in sorted(HI.iterdir()) if p.is_dir()]
    tot_clips, tot_sec = 0, 0.0
    for slug in slugs:
        d = HI / slug
        tj = d / "content_triage.json"
        if not tj.exists():
            print(f"  skip {slug}: no content_triage.json")
            continue
        spans = merge_spans(json.loads(tj.read_text(encoding="utf-8")).get("lid_windows", []), langs, a.min_prob)
        if not spans:
            print(f"  {slug}: no confident-Hindi spans")
            continue
        wav16 = pdp.to_wav_16k(d / "audio.mp3", ROOT / "_work" / f"hi_{slug}.wav")
        y = read_audio(str(wav16), sampling_rate=16000)
        sp = get_speech_timestamps(y, vad, sampling_rate=16000, return_seconds=True)
        segs = [(s["start"], s["end"]) for s in sp if in_spans((s["start"], s["end"]), spans)]
        clips = clips_from_speech(segs, a.min_sec, a.max_sec)

        cdir = d / "clips_hi"
        cdir.mkdir(parents=True, exist_ok=True)
        for old in cdir.glob("*.wav"):
            old.unlink()
        rows = []
        for i, (cs, ce) in enumerate(clips, 1):
            dst = cdir / f"{slug}_{i:04d}.wav"
            pdp.cut(wav16, cs, ce, dst)
            text = str(transcribe(str(dst))).strip()
            rows.append({"audio": f"clips_hi/{dst.name}", "text": text,
                         "lecture": slug, "start": round(cs, 2), "end": round(ce, 2)})
        (d / "train_hi.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                                          encoding="utf-8")
        sec = sum(r["end"] - r["start"] for r in rows)
        tot_clips += len(rows)
        tot_sec += sec
        print(f"  {slug}: {len(rows)} clips, {sec/60:.1f}min from {len(spans)} spans / {len(segs)} vad segs")

    print(f"\n==== HINDI CLIP SET v2 ==== {tot_clips} clips, {tot_sec/60:.0f}min "
          f"(Silero-VAD cuts + {a.asr})")
    print("NEXT: rebuild the review gallery; drafts should need only light edits now.")


if __name__ == "__main__":
    main()
