"""
assemble_diary.py — the funnel + stitch for the full-diary v1.

Pull the pod's /workspace/out_diary/ to data/out/lecture1/diary/ first, then this:
  per chunk -> reject gross-length outliers (repeats/glitches) + off-identity takes (ECAPA),
  rank the survivors by graveness (calm), keep the CALMEST clean take, stitch the 23 picks with
  soft silences into full.wav, and build an interactive gallery to hear the whole Short and swap
  any chunk's take by ear.

  .venv/Scripts/python.exe scripts/assemble_diary.py
"""
import json, re, shutil, sys
from collections import defaultdict
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_graveness as bg
import gate_takes as gt

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/lecture1/diary"
SRC_NARR = ROOT / "data/out/lecture1/diary_narr"   # 3rd-person male narrator takes
NARR = {1, 2, 3}                                    # narration chunks (not GGS)
CHUNKS = ROOT / "data/narration/diary_chunks_calm.txt"
OUT = ROOT / "voice_lab" / "diary_full"
AUD = OUT / "audio"
GAP = 0.90                       # seconds of silence between chunks (breath) — slower/prayerful
VER = "v5"                       # label shown in the gallery + note export
sys.stdout.reconfigure(encoding="utf-8")


def vocal_effort(p):
    """Alpha ratio (spectral tilt) = the loudness-INDEPENDENT signature of shouting / pressed voice.
    Per-frame -> 'alpha' (mean effort) AND 'peak' (p90 = the loudest moment). The peak catches a single
    shouted word that the mean hides. Higher = shoutier. numpy only."""
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    rms_all = np.sqrt(np.mean(y ** 2)) + 1e-9
    frame, hop = 1024, 256
    win = np.hanning(frame)
    freqs = np.fft.rfftfreq(frame, 1 / sr)
    lo = (freqs >= 50) & (freqs < 1000)
    hi = (freqs >= 1000) & (freqs < 5000)
    a = []
    for i in range(0, max(0, len(y) - frame), hop):
        seg = y[i:i + frame]
        if np.sqrt(np.mean(seg ** 2)) < 0.35 * rms_all:    # voiced frames only
            continue
        mag = np.abs(np.fft.rfft(seg * win))
        a.append(10.0 * np.log10((mag[hi].sum() + 1e-9) / (mag[lo].sum() + 1e-9)))
    if not a:
        return {"alpha": 0.0, "peak": 0.0}
    a = np.array(a)
    return {"alpha": round(float(a.mean()), 2), "peak": round(float(np.percentile(a, 90)), 2)}


def noise_floor(p):
    """Background-noise bed = 10th-percentile frame level (dBFS): the quietest frames = noise-only.
    Lower = quieter. numpy only (no librosa -> no speechbrain lazy-import conflict in this process)."""
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    frame, hop = 1024, 256
    r = [np.sqrt(np.mean(y[i:i + frame] ** 2)) + 1e-9 for i in range(0, max(0, len(y) - frame), hop)]
    if not r:
        return {"nfloor": -120.0}
    return {"nfloor": round(float(20 * np.log10(np.percentile(r, 10))), 2)}


def main():
    if not SRC.exists() or not list(SRC.glob("*.wav")):
        sys.exit(f"no clips in {SRC} — pull the pod's /workspace/out_diary/ there first")
    texts = [l.strip() for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()]
    pat = re.compile(r"(?P<ch>\d+)__s(?P<seed>\d+)\.wav")
    cache_p = SRC / "_assemble_cache.json"
    if cache_p.exists():                                       # ECAPA+prosody cached -> pacing tweaks are instant
        C = json.loads(cache_p.read_text(encoding="utf-8")); rows, ceil = C["rows"], C["ceil"]
        print(f"[cache] {len(rows)} takes (delete {cache_p.name} to recompute)")
    else:
        print("[ecapa] centroid ...")
        embed, ref, ceil, cos = gt.ecapa_centroid()
        rows = []
        for src, want_narr in ((SRC_NARR, True), (SRC, False)):   # 1-3 from narrator dir, rest from GGS dir
            for p in sorted(src.glob("*.wav")):
                m = pat.match(p.name)
                if not m:
                    continue
                ch = int(m["ch"])
                if (ch in NARR) != want_narr:
                    continue
                rows.append(dict(ch=ch, seed=int(m["seed"]), wav=p.name, dir=str(src), narr=(ch in NARR),
                                 ecapa=round(cos(embed(p), ref), 3), **bg.feats(p), **vocal_effort(p)))
        cache_p.write_text(json.dumps({"ceil": ceil, "rows": rows}), encoding="utf-8")
    print(f"[load] {len(rows)} takes across {len({r['ch'] for r in rows})} chunks · ceiling {ceil:.3f}")

    ev = np.array([r["ecapa"] for r in rows if not r.get("narr")])   # identity floor from GGS takes only
    id_thr = max(0.55, float(ev.mean() - 1.4 * ev.std()))

    # per chunk: gate (dur-outlier + identity), then rank survivors by graveness (calmest)
    picks, chunks = {}, defaultdict(list)
    for r in rows:
        chunks[r["ch"]].append(r)
    for ch, takes in chunks.items():
        med = float(np.median([t["dur"] for t in takes]))
        clean = [t for t in takes if 0.6 * med <= t["dur"] <= 1.35 * med
                 and (t.get("narr") or t["ecapa"] >= id_thr)]   # narration skips GGS-identity gate
        pool = clean or takes                                  # fallback: never leave a gap
        # z-score gain-independent calmness within the chunk, pick calmest
        for k in ("f0", "spread", "rate", "alpha", "peak"):
            v = np.array([t[k] for t in pool], float); mu, sd = v.mean(), (v.std() or 1.0)
            for t in pool:
                t[f"z_{k}"] = (t[k] - mu) / sd
        for t in pool:   # softest EVERYWHERE: low pitch+range, slow, low mean effort, and low PEAK effort
            t["calm"] = -(t["z_f0"] + t["z_spread"] + 2.0 * t["z_rate"]
                          + 2.0 * t["z_alpha"] + 2.5 * t["z_peak"]) / 9.5
        picks[ch] = max(pool, key=lambda t: t["calm"])

    # stitch the picks in chunk order with soft silences
    order = sorted(picks)
    sr0 = sf.info(str(Path(picks[order[0]]["dir"]) / picks[order[0]]["wav"])).samplerate
    sil = np.zeros(int(GAP * sr0), dtype="float32")
    segs = []
    for ch in order:
        y, sr = sf.read(str(Path(picks[ch]["dir"]) / picks[ch]["wav"]), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        if sr != sr0:
            g = gcd(sr, sr0); y = resample_poly(y, sr0 // g, sr // g).astype("float32")
        segs.append(y); segs.append(sil)
    full = np.concatenate(segs[:-1])
    OUT.mkdir(parents=True, exist_ok=True); AUD.mkdir(exist_ok=True)
    sf.write(str(OUT / "full.wav"), full, sr0)
    dur_min = len(full) / sr0 / 60

    # copy takes for the gallery (picked + up to 4 alts per chunk)
    gal = []
    for ch in order:
        takes = sorted(chunks[ch], key=lambda t: -t["calm"] if "calm" in t else 0)
        keep = [picks[ch]] + [t for t in takes if t is not picks[ch]][:4]
        for t in keep:
            shutil.copyfile(Path(t["dir"]) / t["wav"], AUD / t["wav"])
        gal.append(dict(ch=ch, text=texts[ch - 1] if ch - 1 < len(texts) else "",
                        picked=picks[ch]["wav"],
                        takes=[dict(wav=f"audio/{t['wav']}", seed=t["seed"], grave=round(t.get("calm", 0), 2),
                                    ecapa=t["ecapa"], loud=round(t["loud"], 1),
                                    picked=(t is picks[ch])) for t in keep]))
    (OUT / "index.html").write_text(TEMPLATE.replace("/*__DATA__*/", json.dumps(
        dict(dur=round(dur_min, 2), n=len(order), groups=gal), ensure_ascii=False)
        ).replace("__VER__", VER), encoding="utf-8")

    kept = sum(1 for ch in order if picks[ch].get("narr") or picks[ch]["ecapa"] >= id_thr)
    print(f"\n[stitch] full.wav = {dur_min:.2f} min ({len(order)} chunks) -> {OUT/'full.wav'}")
    print(f"[funnel] {kept}/{len(order)} chunks' calmest pick also passed identity (>= {id_thr:.2f})")
    print(f"[gallery] {OUT/'index.html'} — hear the whole Short + swap any chunk by ear")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Diary — full Short __VER__</title>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--acc:#7cff9c;--pick:#5cc8ff;--note:#ffd479}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:760px;margin:0 auto;padding:22px 18px 120px}h1{font-size:21px;margin:0 0 4px}
 .full{background:#141b16;border:1px solid var(--acc);border-radius:12px;padding:14px 16px;margin:0 0 18px}
 .full audio{width:100%;height:42px;margin-top:8px}.sub{color:var(--mut);font-size:13px}
 .item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
 .txt{font-size:14.5px;margin:0 0 8px;color:#fff}.n{color:var(--mut);font-size:12px}
 .take{display:flex;align-items:center;gap:10px;margin:5px 0;padding:4px 6px;border-radius:8px;cursor:pointer;border:1px solid transparent}
 .take:hover{background:#11161d}.take.chosen{border-color:var(--pick);background:rgba(92,200,255,.08)}
 .take .s{width:120px;font-size:12px;color:var(--mut)}.take .s b{color:var(--pick)}
 audio{flex:1;height:30px} .m{font-size:11px;color:var(--mut);width:120px;text-align:right}
 label.nl{display:block;font-size:11px;color:var(--mut);margin:9px 0 3px}
 .note{width:100%;min-height:38px;background:#0f141b;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:7px 9px;font:13px/1.5 system-ui;resize:vertical}
 .note:focus{border-color:var(--note);outline:none}.note::placeholder{color:#5b6472}.note.noted{border-color:var(--note)}
 .ovl{background:#1b1810;border-color:#3a3320}
 .bar{position:fixed;left:0;right:0;bottom:0;background:#11141b;border-top:1px solid var(--line);padding:11px 16px;display:flex;gap:12px;justify-content:center;align-items:center}
 .bar button{cursor:pointer;border:1px solid var(--acc);background:var(--acc);color:#0f1115;border-radius:8px;padding:9px 16px;font:inherit;font-weight:800}
 #out{display:none;width:100%;max-width:760px;height:130px;margin:8px auto 0;background:#11141b;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px;font:12.5px ui-monospace,monospace}
</style></head><body><div class="wrap">
<h1>🌙 The diary — full Short (__VER__)</h1>
<div class="full"><b>Listen to the whole thing first ↓</b> <span class="sub">(__N__ chunks · __DUR__ min · calmest clean take auto-picked per chunk)</span>
<audio controls preload="none" src="full.wav"></audio></div>
<div class="item ovl"><label class="nl">📝 Overall notes on __VER__ (auto-saved in this browser)</label>
<textarea class="note ovl" data-ch="_overall" placeholder="general impressions — pacing, background noise, narrator fit, anything…"></textarea></div>
<p class="sub">Per chunk: the ⭐ auto-pick is the calmest clean take. Click a better take to mark a swap, and jot a 📝 note on anything you hear. Then <b>Copy notes + swaps</b> and paste it back to me.</p>
<div id="list"></div></div>
<div class="bar"><span id="cnt" class="sub"></span><button id="copy">Copy notes + swaps</button></div>
<textarea id="out" readonly></textarea>
<script>
const D=/*__DATA__*/; const LS="diary_full_swaps", LN="diary_full_notes";
let sw=JSON.parse(localStorage.getItem(LS)||"{}"), nt=JSON.parse(localStorage.getItem(LN)||"{}");
document.getElementById("list").innerHTML=D.groups.map(g=>`<div class="item"><div class="txt">${g.ch}. "${g.text}"</div>
 ${g.takes.map(t=>`<div class="take" data-ch="${g.ch}" data-wav="${t.wav.split('/').pop()}"><span class="s">${t.picked?'<b>⭐ pick</b> · ':''}seed ${t.seed}</span>
   <audio controls preload="none" src="${t.wav}"></audio><span class="m">grave ${t.grave} · id ${t.ecapa}</span></div>`).join("")}
 <label class="nl">📝 note on chunk ${g.ch}</label><textarea class="note" data-ch="${g.ch}" placeholder="e.g. still shouts on 'well-wishers' · pacing fast · noise/hiss here · seed 7 calmer…"></textarea>
 </div>`).join("");
function paint(){document.querySelectorAll(".take").forEach(el=>{const ch=el.dataset.ch,w=el.dataset.wav;
  const chosen = sw[ch]? sw[ch]===w : el.querySelector(".s b");
  el.classList.toggle("chosen", !!chosen);});
  const ns=Object.keys(sw).length, nn=Object.keys(nt).length;
  document.getElementById("cnt").textContent=`${nn||"no"} note${nn===1?"":"s"} · ${ns||"no"} swap${ns===1?"":"s"}`;}
document.querySelectorAll(".take").forEach(el=>el.onclick=e=>{if(e.target.tagName==="AUDIO")return;
  const ch=el.dataset.ch,w=el.dataset.wav; if(sw[ch]===w){delete sw[ch];}else{sw[ch]=w;}
  localStorage.setItem(LS,JSON.stringify(sw)); paint();});
document.querySelectorAll(".note").forEach(el=>{const k=el.dataset.ch; if(nt[k])el.value=nt[k]; el.classList.toggle("noted",!!nt[k]);
  el.oninput=()=>{const v=el.value.trim(); if(v)nt[k]=v; else delete nt[k];
    localStorage.setItem(LN,JSON.stringify(nt)); el.classList.toggle("noted",!!v); paint();};});
document.getElementById("copy").onclick=()=>{const o=document.getElementById("out");o.style.display="block";
  let s="Diary __VER__ — inspection\n\n== NOTES ==\n";
  if(nt._overall)s+=`[overall] ${nt._overall}\n`;
  const ck=Object.keys(nt).filter(k=>k!=="_overall").sort((a,b)=>a-b);
  ck.forEach(k=>s+=`[chunk ${k}] ${nt[k]}\n`); if(!nt._overall&&!ck.length)s+="(none)\n";
  s+="\n== SWAPS ==\n"; const sk=Object.keys(sw).sort((a,b)=>a-b);
  s+= sk.length? sk.map(c=>`chunk ${c} -> ${sw[c]}`).join("\n") : "(no swaps — auto-picks stand)";
  o.value=s;o.select();document.execCommand("copy");document.getElementById("copy").textContent="✓ copied";};
paint();
</script></body></html>
"""

if __name__ == "__main__":
    main()
