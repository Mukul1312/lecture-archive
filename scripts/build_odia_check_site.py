"""
build_odia_check_site.py — deployable blind listening page for an ODIA-SPEAKING checker.

Why this exists: our evaluator does not speak Odia. He can judge timbre and accent, but not whether
denoising has eaten words. Research (research/docs/odia/odia-asr-and-intelligibility-metrics-2026-07-31.md) closed
off every automated substitute:
  - ASR round-trip WER is invalid — enhancement degrades ASR in 40/40 configurations regardless of
    human intelligibility, including a 1.3-3.2% penalty on audio with no added noise at all.
  - STOI/ESTOI need a CLEAN reference; ours is the noisy original, so they degenerate to
    "doing nothing wins".
So the only sound instrument left is a person who speaks the language. This page is that instrument.

DIFFERENT QUESTION FROM THE LOCAL TEST. The local test rates voice and background.
This page asks the one thing only an Odia speaker can answer: ARE THE WORDS STILL THERE.
Intelligibility is the primary scale; naturalness is secondary.

Design follows the existing devotee-facing pages (site/, site-casting/): aubergine/gold, Georgia,
noindex, self-contained, relative paths, compressed audio, copy-out feedback. Visual continuity
matters — same audience, same project.

Audio is encoded at 192 kbps MP3. The source is band-limited to ~7.7 kHz, so 192k is transparent and
adds no artifacts of its own — important, since the whole test is about detecting subtle damage.

Writes to site-odia-check/ — its own Vercel project, like site-casting/.

RUN:    .venv/Scripts/python.exe scripts/build_odia_check_site.py [seed]
DEPLOY: cd site-odia-check && vercel --prod
"""
import base64
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "data/enhance/poc/v2"
OUT = ROOT / "site-odia-check"
AUD = OUT / "audio"

# ROUND 2 — NARROWED LADDER.
# The first private review ruled out the ladder extremes and located the useful decision range at
# 12-22 dB. This round puts five steps inside that range instead of spending slots on endpoints that
# have already been ruled out.
# The untouched original stays in as the anchor: it is the "before" reference, and if it ever wins
# outright that is still a real result.
LADDER = {
    "original_0dB":  V2 / "00_original.wav",
    "atten12_12dB":  V2 / "11_dfn_atten12.wav",
    "atten15_14dB":  V2 / "11b_dfn_atten15.wav",
    "atten18_17dB":  V2 / "12_dfn_atten18.wav",
    "atten21_20dB":  V2 / "12b_dfn_atten21.wav",
    "atten24_22dB":  V2 / "13_dfn_atten24.wav",
}
# Round 1's passage 1 ENDED MID-WORD (-27.1 dB at the boundary), so every version there sounded
# "cut" — my error, and it likely caused the false "words got cut" report. These two windows were
# chosen by scanning for 25 s spans whose BOTH ends sit in a pause, with >55% speech inside.
EXCERPTS = [(59, 25), (203, 25)]
TARGET_RMS = 0.06
MP3_KBPS = 192

_a = [a for a in sys.argv[1:] if not a.startswith("-")]
SEED = int(_a[0]) if _a else int.from_bytes(os.urandom(4), "big")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def cut_to_mp3(src, start_s, dur_s, dst):
    """RMS-match (so loudness cannot bias the verdict), then encode transparently."""
    y, sr = sf.read(str(src), dtype="float32", start=int(start_s * 48000),
                    frames=int(dur_s * 48000))
    if y.ndim > 1:
        y = y.mean(axis=1)
    y = y * (TARGET_RMS / (float(np.sqrt(np.mean(y * y))) + 1e-9))
    pk = float(np.max(np.abs(y)))
    if pk > 0.99:
        y = y * (0.99 / pk)
    tmp = dst.with_suffix(".tmp.wav")
    sf.write(str(tmp), y.astype("float32"), sr)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                    "-b:a", f"{MP3_KBPS}k", str(dst)], check=True)
    tmp.unlink()


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found — needed to compress audio for the web")
    missing = [k for k, v in LADDER.items() if not v.exists()]
    if missing:
        sys.exit(f"missing candidates: {missing}")

    if AUD.exists():
        shutil.rmtree(AUD)
    AUD.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    names = list(LADDER)
    tests, key = [], {}
    n = 0
    for ei, (start, dur) in enumerate(EXCERPTS):
        slots = names[:]
        rng.shuffle(slots)
        entries = []
        for si, ident in enumerate(slots):
            n += 1
            opaque = f"c{n:03d}.mp3"          # leaks nothing
            cut_to_mp3(LADDER[ident], start, dur, AUD / opaque)
            slot = "ABCDEF"[si]
            entries.append({"slot": slot, "file": f"audio/{opaque}"})
            key[f"{ei}{slot}"] = ident
        tests.append({"idx": ei, "label": f"Passage {ei + 1}", "entries": entries})

    html = (PAGE.replace("__TESTS__", json.dumps(tests))
                .replace("__KEY__", base64.b64encode(json.dumps(key).encode()).decode()))
    (OUT / "index.html").write_text(html, encoding="utf-8")
    if not (OUT / ".gitignore").exists():
        (OUT / ".gitignore").write_text(".vercel\n", encoding="utf-8")

    mb = sum(f.stat().st_size for f in AUD.glob("*.mp3")) / 1e6
    print(f"built {OUT/'index.html'}")
    print(f"  {len(EXCERPTS)} passages x {len(names)} versions = {n} clips, {mb:.1f} MB total")
    print(f"  seed {SEED} — blind; answer key embedded, revealed only by the Reveal button")
    print(f"\ndeploy:  cd site-odia-check && vercel --prod")


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Listening check — Odia</title><style>
:root{--bg:#100d13;--card:#1c1720;--line:#312836;--ink:#f1ebf4;--mut:#a99fb3;--gold:#c9a24a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 Georgia,'Times New Roman',serif}
.wrap{max-width:760px;margin:0 auto;padding:38px 20px 90px}
.top{text-align:center;margin:0 0 20px}
.om{color:var(--gold);font-size:15px;letter-spacing:.2em;margin:0 0 10px}
h1{font-size:25px;line-height:1.3;margin:0 0 6px;font-weight:600}
.sub{color:var(--mut);font-size:14px;margin:0}
.ask{background:#17131c;border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:22px 0;
  font-size:15px;font-family:system-ui,Segoe UI,Roboto,sans-serif}
.ask b{color:var(--gold)}
.ask ol{margin:10px 0 0;padding-left:20px}.ask li{margin:0 0 7px}
h2{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--mut);margin:34px 0 12px;
  font-family:system-ui}
.rec{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:0 0 14px}
.rec.on{border-color:var(--gold)}
.rec .t{font-size:13px;color:var(--gold);letter-spacing:.14em;text-transform:uppercase;margin:0 0 10px;
  font-family:system-ui}
audio{width:100%;height:40px;margin:0 0 12px}
.lbl{font-size:12px;color:var(--mut);font-family:system-ui;margin:0 0 6px;letter-spacing:.04em}
.lbl b{color:#d8c7a0}
.opts{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
.opt{cursor:pointer;border:1px solid var(--line);background:#221b29;color:var(--ink);border-radius:30px;
  padding:8px 15px;font:13.5px system-ui}
.opt.on{border-color:var(--gold);background:rgba(201,162,74,.16);color:#fff;font-weight:700}
.note{width:100%;min-height:46px;background:#0f0c13;border:1px solid var(--line);color:var(--ink);
  border-radius:10px;padding:9px 11px;font:14px system-ui;resize:vertical}
.bar{position:sticky;bottom:0;background:#141019;border-top:1px solid var(--line);padding:14px;
  display:flex;gap:10px;align-items:center;margin-top:26px;border-radius:12px;
  font-family:system-ui;flex-wrap:wrap}
.bar button{cursor:pointer;border-radius:10px;padding:11px 18px;font:14px/1 system-ui;font-weight:700;
  border:1px solid var(--gold)}
.cp{background:var(--gold);color:#100d13}.rv{background:transparent;color:var(--gold)}
#prog{color:var(--mut);font-size:13px;margin-right:auto}
.res{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-top:20px;
  display:none;font-family:system-ui;font-size:14px}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{padding:8px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.1em}
.disc{margin:34px 0 0;padding:16px 18px;border:1px solid var(--line);border-radius:12px;background:#17131c;
  color:var(--mut);font-size:13px;line-height:1.65;font-family:system-ui}
</style></head><body><div class="wrap">
<div class="top"><div class="om">॥ ॐ ॥</div>
<h1>Listening check</h1>
<div class="sub">Private Odia lecture review</div></div>

<div class="ask">
We are cleaning background noise from these recordings. Cleaning can accidentally
<b>damage or remove words</b> — and we cannot hear that ourselves, because we do not speak Odia.
<ol>
<li>Each passage below has the <b>same audio in 6 different versions</b>, in random order.</li>
<li>For each one, the important question is: <b>can you understand every word?</b>
Listen for words that sound cut, muffled, robotic, or missing.</li>
<li>Please also say whether <b>his voice still sounds natural</b> — like him, in a quiet room.</li>
<li>If something specific sounds wrong, please write it in the notes
(for example: <i>"at 0:12 one word is unclear"</i>).</li>
</ol>
Headphones are best. The versions are unlabelled on purpose.
<br><br><b>Important:</b> when you finish, please press the <b>Copy my answers</b> button at the
bottom and send that text. It records exactly which version you meant — writing the letters by
hand is easy to mix up between passages.
</div>

<div id="tests"></div>

<div class="bar"><span id="prog"></span>
<button class="rv" id="reveal">Reveal</button>
<button class="cp" id="copy">Copy my answers</button></div>
<div class="res" id="res"></div>

<div class="disc"><p>This review page is intended only for authorized participants and is not
indexed by search engines. Thank you for your help.</p></div>
</div>
<script>
const TESTS=__TESTS__, KEY=JSON.parse(atob("__KEY__")), LS="odia-check-v1";
let S=JSON.parse(localStorage.getItem(LS)||"{}");
const save=()=>localStorage.setItem(LS,JSON.stringify(S));
const WORDS=["1 — many words unclear","2 — some words unclear","3 — mostly clear",
             "4 — clear, one or two doubtful","5 — every word clear"];
const NAT=["1 — very unnatural","2 — unnatural","3 — acceptable","4 — natural","5 — completely natural"];
function draw(){
  const root=document.getElementById("tests"); root.innerHTML="";
  TESTS.forEach(t=>{
    const h=document.createElement("h2"); h.textContent=t.label; root.appendChild(h);
    t.entries.forEach(e=>{
      const id=`${t.idx}${e.slot}`, st=S[id]||{};
      const d=document.createElement("div");
      d.className="rec"+((st.words&&st.nat)?" on":"");
      d.innerHTML=`<div class="t">Version ${e.slot}</div>
        <audio controls preload="none" src="${e.file}"></audio>
        <div class="lbl"><b>Can you understand every word?</b></div>
        <div class="opts" data-k="words" data-id="${id}">${WORDS.map((l,i)=>
          `<button class="opt ${st.words==i+1?'on':''}" data-v="${i+1}">${l}</button>`).join("")}</div>
        <div class="lbl"><b>Does his voice sound natural?</b></div>
        <div class="opts" data-k="nat" data-id="${id}">${NAT.map((l,i)=>
          `<button class="opt ${st.nat==i+1?'on':''}" data-v="${i+1}">${l}</button>`).join("")}</div>
        <textarea class="note" placeholder="Notes — anything that sounded wrong (optional)"
          data-note="${id}">${st.note||""}</textarea>`;
      root.appendChild(d);
    });
  });
  root.querySelectorAll(".opts button").forEach(b=>b.onclick=()=>{
    const p=b.parentElement; S[p.dataset.id]=S[p.dataset.id]||{};
    S[p.dataset.id][p.dataset.k]=+b.dataset.v; save(); draw();
  });
  root.querySelectorAll("textarea").forEach(t=>t.onchange=()=>{
    S[t.dataset.note]=S[t.dataset.note]||{}; S[t.dataset.note].note=t.value; save();
  });
  const tot=TESTS.length*TESTS[0].entries.length;
  document.getElementById("prog").textContent=
    Object.values(S).filter(v=>v.words&&v.nat).length+" / "+tot+" answered";
}
document.getElementById("copy").onclick=()=>{
  let out="Odia listening check — results\n\n";
  TESTS.forEach(t=>t.entries.forEach(e=>{
    const id=`${t.idx}${e.slot}`, v=S[id]||{};
    out+=`${t.label} / Version ${e.slot} [${KEY[id]}]  words=${v.words||"-"}  natural=${v.nat||"-"}`
       +(v.note?`  note: ${v.note}`:"")+"\n";
  }));
  navigator.clipboard.writeText(out).then(()=>alert("Copied — please paste and send it back."),
    ()=>{const w=window.open("");w.document.write("<pre>"+out.replace(/</g,"&lt;")+"</pre>");});
};
document.getElementById("reveal").onclick=()=>{
  const agg={};
  Object.entries(S).forEach(([id,v])=>{const k=KEY[id]; if(!k||!v.words||!v.nat)return;
    agg[k]=agg[k]||{w:[],n:[]}; agg[k].w.push(v.words); agg[k].n.push(v.nat);});
  const m=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:NaN;
  const rows=Object.entries(agg).map(([k,v])=>({k,w:m(v.w),n:m(v.n)})).sort((a,b)=>b.w-a.w);
  const r=document.getElementById("res"); r.style.display="block";
  r.innerHTML="<b>Results — ranked by words understood</b><table><tr><th>Version</th>"
    +"<th>Words</th><th>Natural</th></tr>"+rows.map(x=>
    `<tr><td>${x.k}</td><td>${x.w.toFixed(2)}</td><td>${x.n.toFixed(2)}</td></tr>`).join("")+"</table>";
};
draw();
</script></body></html>"""


if __name__ == "__main__":
    main()
