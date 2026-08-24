"""Build a local Odia word-loss audit from find_dfn_word_risks.py output."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parent.parent
SR = 48_000


def read_clip(path: Path, center_s: float, duration_s: float) -> np.ndarray:
    info = sf.info(str(path))
    sr = info.samplerate
    start = max(0, round((center_s - duration_s / 2) * sr))
    frames = round(duration_s * sr)
    audio, _ = sf.read(str(path), start=start, frames=frames, dtype="float32")
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    if len(audio) < frames:
        audio = np.pad(audio, (0, frames - len(audio)))
    return audio


def level_match(audio: np.ndarray, target_rms: float = 0.055) -> np.ndarray:
    rms = float(np.sqrt(np.mean(audio * audio)) + 1e-12)
    output = audio * (target_rms / rms)
    peak = float(np.max(np.abs(output)))
    if peak > 0.98:
        output *= 0.98 / peak
    # Short fades prevent the review clip itself from creating a false "cut".
    n = min(round(0.08 * SR), len(output) // 2)
    ramp = np.linspace(0, 1, n, dtype=np.float32)
    output[:n] *= ramp
    output[-n:] *= ramp[::-1]
    return output.astype("float32")


def encode(audio: np.ndarray, destination: Path) -> None:
    temporary = destination.with_suffix(".tmp.wav")
    sf.write(str(temporary), audio, SR, subtype="PCM_16")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(temporary),
        "-b:a", "128k", str(destination),
    ], check=True)
    temporary.unlink()


def select_events(events: list[dict], acoustic_count: int, separation_s: float) -> list[dict]:
    joins = [dict(e) for e in events if e["kind"].startswith("mandatory-")]
    risks = sorted(
        (dict(e) for e in events if e["kind"] == "acoustic-risk"),
        key=lambda e: e["risk_score"], reverse=True,
    )
    selected = joins[:]
    acoustic_selected = 0
    for event in risks:
        # Avoid presenting the same phrase twice. Join checks already cover any
        # acoustic candidate falling in their context window.
        if any(abs(event["original_time_s"] - old["original_time_s"]) < separation_s
               for old in selected):
            continue
        selected.append(event)
        acoustic_selected += 1
        if acoustic_selected >= acoustic_count:
            break
    return sorted(selected, key=lambda e: e["original_time_s"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path,
                        default=ROOT / "data/enhance/out/part-01/word-risk-audit.json")
    parser.add_argument("--original", type=Path,
                        default=ROOT / "data/enhance/out/part-01/_work/00_raw.wav")
    parser.add_argument("--enhanced", type=Path,
                        default=ROOT / "data/enhance/out/part-01/part-01-enhanced.mp3")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data/enhance/out/part-01/word-risk-review")
    parser.add_argument("--acoustic-count", type=int, default=50)
    parser.add_argument("--clip-seconds", type=float, default=14.0)
    parser.add_argument("--separation-seconds", type=float, default=7.0)
    args = parser.parse_args()

    payload = json.loads(args.audit.read_text(encoding="utf-8"))
    selected = select_events(payload["events"], args.acoustic_count, args.separation_seconds)
    audio_dir = args.output / "audio"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)
    audio_dir.mkdir(parents=True)

    rows = []
    for index, event in enumerate(selected, 1):
        original = level_match(read_clip(args.original, event["original_time_s"], args.clip_seconds))
        enhanced = level_match(read_clip(args.enhanced, event["enhanced_time_s"], args.clip_seconds))
        original_name = f"r{index:03d}_original.mp3"
        enhanced_name = f"r{index:03d}_enhanced.mp3"
        encode(original, audio_dir / original_name)
        encode(enhanced, audio_dir / enhanced_name)
        rows.append({
            "id": index,
            "kind": event["kind"],
            "original_time_s": round(event["original_time_s"], 3),
            "enhanced_time_s": round(event["enhanced_time_s"], 3),
            "risk_score": event.get("risk_score"),
            "original": f"audio/{original_name}",
            "enhanced": f"audio/{enhanced_name}",
        })
        print(f"{index:03d}/{len(selected):03d} {event['kind']} "
              f"at {event['original_time_s']/60:.2f} min")

    (args.output / "manifest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (args.output / "index.html").write_text(
        PAGE.replace("__ROWS__", json.dumps(rows)), encoding="utf-8"
    )
    print(f"wrote {args.output / 'index.html'} ({len(rows)} comparisons)")


PAGE = r'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DFN24 word-loss audit</title><style>
body{max-width:900px;margin:30px auto;padding:0 18px;background:#111;color:#eee;font:15px system-ui}
h1{font-size:24px}.intro{line-height:1.55;color:#ccc}.card{padding:18px;margin:16px 0;background:#1b1b1b;border:1px solid #333;border-radius:12px}
.meta{color:#aaa;margin-bottom:10px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}.pair div{min-width:0}audio{width:100%}
button{padding:8px 12px;margin:9px 6px 0 0;background:#292929;color:#eee;border:1px solid #555;border-radius:8px;cursor:pointer}
button.on{border-color:#e4b64b;background:#493a17}textarea{width:100%;min-height:45px;margin-top:10px;background:#111;color:#eee;border:1px solid #444}
@media(max-width:650px){.pair{grid-template-columns:1fr}}</style></head><body>
<h1>DFN24 word-loss audit</h1><div class="intro"><p>Compare the same passage before and after enhancement. Judge only the middle of each 14-second clip; the faded beginning and ending are artificial review boundaries.</p>
<p>Select <b>Enhanced loses a word/syllable</b> only when something understandable in Original becomes missing, clipped, or unintelligible in Enhanced. Noise or timbre differences alone do not count.</p></div>
<div id="cards"></div><button id="copy">Copy decisions</button><script>
const rows=__ROWS__, key='dfn-word-risk-v1';let state=JSON.parse(localStorage.getItem(key)||'{}');
function draw(){let root=document.getElementById('cards');root.innerHTML='';rows.forEach(r=>{let s=state[r.id]||{};let d=document.createElement('div');d.className='card';d.innerHTML=`<div class="meta">Check ${r.id} · ${r.kind} · source ${(r.original_time_s/60).toFixed(2)} min</div><div class="pair"><div><b>Original</b><audio controls preload="none" src="${r.original}"></audio></div><div><b>DFN24 enhanced</b><audio controls preload="none" src="${r.enhanced}"></audio></div></div><div>${[['same','All words preserved'],['loss','Enhanced loses a word/syllable'],['unsure','Unsure — needs another listener']].map(x=>`<button data-id="${r.id}" data-v="${x[0]}" class="${s.verdict==x[0]?'on':''}">${x[1]}</button>`).join('')}</div><textarea data-note="${r.id}" placeholder="Which word/time sounds damaged?">${s.note||''}</textarea>`;root.appendChild(d)});
document.querySelectorAll('button[data-v]').forEach(b=>b.onclick=()=>{state[b.dataset.id]=state[b.dataset.id]||{};state[b.dataset.id].verdict=b.dataset.v;localStorage.setItem(key,JSON.stringify(state));draw()});
document.querySelectorAll('textarea').forEach(t=>t.onchange=()=>{state[t.dataset.note]=state[t.dataset.note]||{};state[t.dataset.note].note=t.value;localStorage.setItem(key,JSON.stringify(state))})}draw();
document.getElementById('copy').onclick=()=>{let out=rows.map(r=>{let s=state[r.id]||{};return `check=${r.id} source_s=${r.original_time_s} verdict=${s.verdict||'-'} note=${s.note||''}`}).join('\n');navigator.clipboard.writeText(out).then(()=>alert('Copied'))};
</script></body></html>'''


if __name__ == "__main__":
    main()
