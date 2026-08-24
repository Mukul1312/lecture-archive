"""
build_enhance_blind.py — BLIND listening test for the enhancement shortlist.

The gate (enhance_gate.py) only decides who gets auditioned. Ears decide the winner — every source
in the research says so, including the DNS Challenge organisers who refuse to let DNSMOS pick their
own winners.

Blind mechanics copied from build_blind_gallery.py, because a labelled gallery primes the verdict:
  - candidates copied to OPAQUE names, so the filename leaks nothing
  - independent shuffle into slots A/B/C/D per excerpt
  - answer key base64-encoded so it can't be read off the page source
  - random unprinted seed: nobody, including me, has seen this arrangement

Two adaptations for THIS decision:

 1. TWO SCALES, rated separately — straight from ITU-T P.835, which exists precisely because
    listeners conflate the two otherwise:
       SIG  the VOICE alone      5 = very natural ... 1 = very unnatural
       BAK  the BACKGROUND alone 5 = not noticeable ... 1 = very intrusive
    Hu & Loizou (32 listeners) found SIG drives overall preference, so they must not be merged.

 2. THE UNTOUCHED ORIGINAL IS ONE OF THE BLIND OPTIONS. If it wins, that IS the result — "no
    algorithm improved quality" is a documented outcome, and we should be able to detect it.

RUN:  .venv/Scripts/python.exe scripts/build_enhance_blind.py [seed]
OPEN: voice_lab/enhance_blind/index.html
"""
import base64
import json
import os
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/enhance/poc/v2"
OUT = ROOT / ("voice_lab/enhance_blind2" if "--ladder" in sys.argv else "voice_lab/enhance_blind")
AUD = OUT / "audio"

# the gate's survivors + the untouched control
CANDIDATES = {
    "original":      SRC / "00_original.wav",
    "dfn_atten06":   SRC / "10_dfn_atten06.wav",
    "dfn_atten12":   SRC / "11_dfn_atten12.wav",
    "nr_gentle":     SRC / "20_nr_gentle.wav",
}
# ROUND 2 (--ladder): a NOISE-REDUCTION LADDER. Round 1 showed every safe option still sounds
# noisy, and that the cut-vs-damage trade-off is near-linear (r=-0.95) with no method beating the
# curve. So the only open question is where the EAR breaks. dfn_full is included deliberately as a
# positive control: it is the setting already rejected, so if it does not score worst, the test
# itself is not discriminating and the results should be thrown away.
LADDER = {
    "original":     SRC / "00_original.wav",
    "atten06_6dB":  SRC / "10_dfn_atten06.wav",
    "atten12_12dB": SRC / "11_dfn_atten12.wav",
    "atten18_17dB": SRC / "12_dfn_atten18.wav",
    "atten24_22dB": SRC / "13_dfn_atten24.wav",
    "full_39dB":    SRC / "14_dfn_full.wav",
}
# excerpts (seconds into the 5-min segment) — different speaking styles, incl. a pause-rich stretch
EXCERPTS = [(35, 25), (140, 25), (245, 25)]
if "--ladder" in sys.argv:
    CANDIDATES = LADDER
    EXCERPTS = [(35, 25), (245, 25)]      # 6 options x 2 excerpts = 12 clips
TARGET_RMS = 0.06
_a = [a for a in sys.argv[1:] if not a.startswith("-")]
SEED = int(_a[0]) if _a else int.from_bytes(os.urandom(4), "big")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def cut_rms_matched(src, start_s, dur_s, dst):
    y, sr = sf.read(str(src), dtype="float32", start=int(start_s * 48000),
                    frames=int(dur_s * 48000))
    if y.ndim > 1:
        y = y.mean(axis=1)
    r = float(np.sqrt(np.mean(y * y))) + 1e-9
    y = y * (TARGET_RMS / r)          # loudness must not bias the judgement
    pk = float(np.max(np.abs(y)))
    if pk > 0.99:
        y = y * (0.99 / pk)
    sf.write(str(dst), y.astype("float32"), sr)


def main():
    missing = [k for k, v in CANDIDATES.items() if not v.exists()]
    if missing:
        sys.exit(f"missing candidates: {missing}")
    AUD.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    names = list(CANDIDATES)
    tests, key = [], {}
    counter = 0
    for ei, (start, dur) in enumerate(EXCERPTS):
        slots = names[:]
        rng.shuffle(slots)                       # independent shuffle per excerpt
        entries = []
        for si, ident in enumerate(slots):
            counter += 1
            opaque = f"x{counter:03d}.wav"       # filename leaks nothing
            cut_rms_matched(CANDIDATES[ident], start, dur, AUD / opaque)
            slot = "ABCDEFGH"[si]
            entries.append({"slot": slot, "file": f"audio/{opaque}"})
            key[f"{ei}{slot}"] = ident
        tests.append({"idx": ei, "label": f"Excerpt {ei+1} — {start//60}:{start%60:02d}",
                      "entries": entries})

    answer = base64.b64encode(json.dumps(key).encode()).decode()
    html = (TEMPLATE.replace("__TESTS__", json.dumps(tests)).replace("__KEY__", answer)
            .replace("__LS__", "ladder-v1" if "--ladder" in sys.argv else "v1"))
    (OUT / "index.html").write_text(html, encoding="utf-8")

    print(f"built {OUT/'index.html'}")
    print(f"  {len(EXCERPTS)} excerpts x {len(names)} candidates = {counter} clips, RMS-matched")
    print(f"  seed {SEED} (not needed to reveal — the key is embedded)")
    print("  the untouched original is one of the blind options")


TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blind enhancement test</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#f6f7f9;color:#1a1a1a;line-height:1.6;padding:24px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:26px;margin-bottom:6px}
.sub{color:#666;font-size:14px;margin-bottom:20px}
.note{background:#fff8e1;border-left:4px solid #ffc107;padding:14px 16px;border-radius:6px;margin-bottom:22px;font-size:14px}
.test{background:#fff;border-radius:10px;padding:20px;margin-bottom:22px;box-shadow:0 2px 10px rgba(0,0,0,.07)}
.test h2{font-size:17px;margin-bottom:14px}
.slot{border:1px solid #e3e5e8;border-radius:8px;padding:14px;margin-bottom:12px}
.slot.done{border-color:#8bc48b;background:#f6fbf6}
.slotname{font-weight:700;font-size:15px;margin-bottom:8px}
audio{width:100%;margin-bottom:10px}
.scales{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:700px){.scales{grid-template-columns:1fr}}
.scale label{display:block;font-size:12px;font-weight:600;color:#444;margin-bottom:5px}
.opts{display:flex;gap:5px;flex-wrap:wrap}
.opts button{flex:1;min-width:34px;padding:7px 4px;border:1px solid #ccd;background:#fff;border-radius:5px;cursor:pointer;font-size:13px}
.opts button:hover{background:#eef}
.opts button.sel{background:#2d6cdf;color:#fff;border-color:#2d6cdf}
.hint{font-size:11px;color:#888;margin-top:4px}
textarea{width:100%;margin-top:10px;padding:8px;border:1px solid #ddd;border-radius:5px;font-family:inherit;font-size:13px;resize:vertical}
.bar{position:sticky;bottom:0;background:#fff;border-top:1px solid #e0e0e0;padding:14px;display:flex;gap:12px;align-items:center;margin-top:20px;border-radius:8px}
.bar button{padding:10px 18px;border:0;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600}
#reveal{background:#2d6cdf;color:#fff}#export{background:#eee}
#prog{font-size:13px;color:#666;margin-right:auto}
table{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}
th,td{padding:9px;text-align:left;border-bottom:1px solid #eee}
th{background:#f6f7f9}
.res{background:#fff;border-radius:10px;padding:20px;margin-top:20px;box-shadow:0 2px 10px rgba(0,0,0,.07);display:none}
</style></head><body><div class="wrap">
<h1>Blind enhancement test</h1>
<div class="sub">Jiva Goswami seminar, Part 01 — which processing preserves his voice?</div>
<div class="note"><b>You are rating two separate things.</b> Please judge them independently — that
separation is the entire point of the ITU-T P.835 method.<br><br>
<b>VOICE</b> — ignore the background completely. Does <i>he</i> sound natural, or processed/hollow/dull?<br>
<b>BACKGROUND</b> — ignore the voice completely. How intrusive is the hiss and room noise?<br><br>
One of the options in every excerpt is the <b>untouched original</b>. All clips are loudness-matched,
and the labels are hidden until you press Reveal. Headphones recommended.</div>
<div id="tests"></div>
<div class="bar"><span id="prog"></span>
<button id="export">Export JSON</button><button id="reveal">Reveal &amp; score</button></div>
<div class="res" id="res"></div></div>
<script>
const TESTS=__TESTS__, KEY=JSON.parse(atob("__KEY__")), LS="enhance-blind-__LS__";
let S=JSON.parse(localStorage.getItem(LS)||"{}");
const save=()=>localStorage.setItem(LS,JSON.stringify(S));
const SIG=["1 very unnatural","2 fairly unnatural","3 somewhat natural","4 fairly natural","5 very natural"];
const BAK=["1 very intrusive","2 fairly conspicuous","3 noticeable","4 somewhat noticeable","5 not noticeable"];
function draw(){
  const root=document.getElementById("tests"); root.innerHTML="";
  TESTS.forEach(t=>{
    const d=document.createElement("div"); d.className="test";
    d.innerHTML=`<h2>${t.label}</h2>`;
    t.entries.forEach(e=>{
      const id=`${t.idx}${e.slot}`, st=S[id]||{};
      const box=document.createElement("div");
      box.className="slot"+((st.sig&&st.bak)?" done":"");
      box.innerHTML=`<div class="slotname">Option ${e.slot}</div>
        <audio controls preload="none" src="${e.file}"></audio>
        <div class="scales">
          <div class="scale"><label>VOICE (ignore background)</label>
            <div class="opts" data-k="sig" data-id="${id}">${SIG.map((l,i)=>
              `<button data-v="${i+1}" class="${st.sig==i+1?'sel':''}" title="${l}">${i+1}</button>`).join("")}</div>
            <div class="hint">1 very unnatural &rarr; 5 very natural</div></div>
          <div class="scale"><label>BACKGROUND (ignore voice)</label>
            <div class="opts" data-k="bak" data-id="${id}">${BAK.map((l,i)=>
              `<button data-v="${i+1}" class="${st.bak==i+1?'sel':''}" title="${l}">${i+1}</button>`).join("")}</div>
            <div class="hint">1 very intrusive &rarr; 5 not noticeable</div></div>
        </div>
        <textarea rows="2" placeholder="notes (optional)" data-note="${id}">${st.note||""}</textarea>`;
      d.appendChild(box);
    });
    root.appendChild(d);
  });
  root.querySelectorAll(".opts button").forEach(b=>b.onclick=()=>{
    const p=b.parentElement, id=p.dataset.id, k=p.dataset.k;
    S[id]=S[id]||{}; S[id][k]=+b.dataset.v; save(); draw();
  });
  root.querySelectorAll("textarea").forEach(t=>t.onchange=()=>{
    const id=t.dataset.note; S[id]=S[id]||{}; S[id].note=t.value; save();
  });
  const tot=TESTS.length*TESTS[0].entries.length;
  const done=Object.values(S).filter(v=>v.sig&&v.bak).length;
  document.getElementById("prog").textContent=`${done}/${tot} rated`;
}
document.getElementById("reveal").onclick=()=>{
  const agg={};
  Object.entries(S).forEach(([id,v])=>{
    const who=KEY[id]; if(!who||!v.sig||!v.bak)return;
    agg[who]=agg[who]||{sig:[],bak:[]}; agg[who].sig.push(v.sig); agg[who].bak.push(v.bak);
  });
  const m=a=>a.length?(a.reduce((x,y)=>x+y,0)/a.length):NaN;
  const rows=Object.entries(agg).map(([k,v])=>({k,sig:m(v.sig),bak:m(v.bak),n:v.sig.length}))
    .sort((a,b)=>b.sig-a.sig);
  document.getElementById("res").style.display="block";
  document.getElementById("res").innerHTML=`<h2>Results — ranked by VOICE (SIG)</h2>
   <table><tr><th>Candidate</th><th>VOICE</th><th>BACKGROUND</th><th>n</th></tr>
   ${rows.map(r=>`<tr><td>${r.k}${r.k==="original"?" <i>(untouched)</i>":""}</td>
   <td><b>${r.sig.toFixed(2)}</b></td><td>${r.bak.toFixed(2)}</td><td>${r.n}</td></tr>`).join("")}</table>
   <p style="margin-top:12px;font-size:13px;color:#666">P.835 finding (Hu &amp; Loizou, 32 listeners):
   overall preference tracks VOICE far more than BACKGROUND. If the untouched original tops the VOICE
   column, that is a real result — not every recording benefits from processing.</p>`;
  document.getElementById("res").scrollIntoView({behavior:"smooth"});
};
document.getElementById("export").onclick=()=>{
  const out=Object.entries(S).map(([id,v])=>({id,candidate:KEY[id],...v}));
  const b=new Blob([JSON.stringify(out,null,2)],{type:"application/json"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(b);
  a.download="enhance-blind-results.json"; a.click();
};
draw();
</script></body></html>"""


if __name__ == "__main__":
    main()
