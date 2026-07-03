"""
build_narration_site.py — build the CURATED, devotee-facing narration site (for a private Vercel deploy).
Standalone (no research-lab links, no ECAPA/technical jargon), dignified, with a clear AI-reconstruction
disclosure + noindex. Reads data/narration/diary_display.txt (diacritics) + audio from data/out/narration/.
Output -> site/  (index.html + audio/). Run: .venv/Scripts/python.exe scripts/build_narration_site.py
"""
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/narration"
DISPLAY = ROOT / "data/narration/diary_display.txt"
OUT = ROOT / "site"
AUD = OUT / "audio"

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>The Diary of Śrīla Gour Govinda Swami Mahārāja — 8 May 1975</title>
<style>
 :root{--bg:#100d13;--card:#1c1720;--line:#312836;--ink:#f1ebf4;--mut:#a99fb3;--gold:#c9a24a;--v:#8f7ad6}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 Georgia,'Times New Roman',serif}
 .wrap{max-width:720px;margin:0 auto;padding:40px 20px 90px}
 .top{text-align:center;margin:0 0 26px}
 .om{color:var(--gold);font-size:15px;letter-spacing:.2em;margin:0 0 10px}
 h1{font-size:25px;line-height:1.3;margin:0 0 6px;font-weight:600}
 .date{color:var(--mut);font-size:14px;margin:0}
 .intro{color:#d8c7a0;font-style:italic;font-size:15px;text-align:center;margin:20px auto 26px;max-width:600px}
 .full{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:0 0 26px;text-align:center}
 .full .t{font-size:12px;color:var(--gold);letter-spacing:.14em;text-transform:uppercase;margin:0 0 10px}
 audio{width:100%;height:40px}
 h2{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--mut);margin:26px 0 12px;text-align:center}
 .line{display:flex;gap:14px;align-items:flex-start;margin:0 0 15px}
 .play{flex:0 0 auto;margin-top:2px}
 .play button{cursor:pointer;width:30px;height:30px;border-radius:50%;border:1px solid var(--line);
   background:#241d2b;color:var(--v);font-size:12px;line-height:1}
 .play button.on{background:var(--v);color:#100d13;border-color:var(--v)}
 .tx{flex:1}.a .tx{color:#d8c7a0;font-style:italic}.b .tx{color:var(--ink)}
 .disc{margin:40px 0 0;padding:16px 18px;border:1px solid var(--line);border-radius:12px;background:#17131c;
   color:var(--mut);font-size:13px;line-height:1.65;font-family:system-ui,Segoe UI,Roboto,sans-serif}
 .disc b{color:#c9b8cf}
</style></head><body><div class="wrap">
 <div class="top">
   <div class="om">॥ śrī śrī guru-gaurāṅgau jayataḥ ॥</div>
   <h1>The Diary of Śrīla Gour Govinda Swami Mahārāja</h1>
   <p class="date">8 May 1975 &middot; his vow on giving up night Prasādam</p>
 </div>
 <p class="intro">Listen to Mahārāja's own words of vow, repentance, and prayer — offered at the lotus feet of his beloved Lord Gopāla.</p>
 <div class="full"><div class="t">&#9673;  The complete narration</div><audio controls preload="metadata" id="full"></audio></div>
 <div id="parts"></div>
 <div class="disc">
   <b>A note on this offering.</b> This is a devotional offering — seva. The words are transcribed from Śrīla Gour Govinda Swami Mahārāja's own hand-written diary entry of 8 May 1975. The <b>voice is an AI reconstruction</b> of his voice, created with love and reverence for the pleasure of the devotees — it is <b>not an original recording</b>. Offered humbly at his lotus feet.
 </div>
</div>
<script>
const D=/*__DATA__*/;const $=s=>document.querySelector(s);
if(D.full)$("#full").src=D.full;
let cur=null;
function mk(x){
  const line=document.createElement("div");line.className="line "+x.part.toLowerCase();
  line.innerHTML=`<span class="play">${x.url?'<button aria-label="play">&#9654;</button>':''}</span><div class="tx">${x.text}</div>`;
  if(x.url){const b=line.querySelector("button");const a=new Audio(x.url);
    b.onclick=()=>{if(cur&&cur.a!==a){cur.a.pause();cur.b.classList.remove("on");cur.b.innerHTML="&#9654;";}
      if(a.paused){a.play();b.classList.add("on");b.innerHTML="&#10073;&#10073;";cur={a,b};}else{a.pause();b.classList.remove("on");b.innerHTML="&#9654;";}};
    a.onended=()=>{b.classList.remove("on");b.innerHTML="&#9654;";};}
  return line;
}
const parts=$("#parts");
const A=D.items.filter(x=>x.part==="A"),B=D.items.filter(x=>x.part==="B");
const h1=document.createElement("h2");h1.textContent="The occasion";parts.appendChild(h1);
A.forEach(x=>parts.appendChild(mk(x)));
const h2=document.createElement("h2");h2.textContent="His diary entry";parts.appendChild(h2);
B.forEach(x=>parts.appendChild(mk(x)));
</script></body></html>
"""

AUD.mkdir(parents=True, exist_ok=True)
lines = [l.strip() for l in DISPLAY.read_text(encoding="utf-8").splitlines() if l.strip()]


def put(name):
    s = SRC / name
    if s.exists():
        shutil.copyfile(s, AUD / name)
        return f"audio/{name}"
    return None


full = put("full.wav")
items = [dict(text=t, url=put(f"chunk_{i:02d}.wav"), part="A" if i <= 3 else "B") for i, t in enumerate(lines, 1)]
(OUT / "index.html").write_text(TEMPLATE.replace("/*__DATA__*/", json.dumps(dict(full=full, items=items), ensure_ascii=False)), encoding="utf-8")
print(f"wrote {OUT/'index.html'} | full={bool(full)} | {len(items)} lines | audio -> {AUD}")
