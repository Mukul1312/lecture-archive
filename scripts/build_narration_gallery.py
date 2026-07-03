"""
build_narration_gallery.py — a listening page for the diary narration in GGS's voice.
Full track at top + per-chunk players with text, split PART A (framing) / PART B (his diary entry),
so any single line can be re-rolled if a take is off. Output -> voice_lab/narration/ (servable).
Run: .venv/Scripts/python.exe scripts/build_narration_gallery.py
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
CHUNKS_TXT = ROOT / "data/narration/diary_chunks.txt"
OUT = ROOT / "voice_lab/narration"
AUD = OUT / "audio"

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Diary narration - GGS voice</title>
<style>
 :root{--bg:#0f0d12;--card:#1b1720;--line:#2e2733;--ink:#efe9f2;--mut:#a99fb3;--a:#c9a24a;--b:#8f7ad6}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 Georgia,serif}
 .wrap{max-width:760px;margin:0 auto;padding:26px 18px 90px}
 h1{font-size:22px;margin:0 0 2px;font-weight:600}.date{color:var(--mut);font-size:13px;margin:0 0 18px}
 .full{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 16px;margin:0 0 20px}
 .full .t{font-size:13px;color:var(--a);letter-spacing:.04em;text-transform:uppercase;margin:0 0 8px}
 audio{width:100%;height:38px}
 h2{font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--mut);margin:22px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
 .line{display:flex;gap:12px;margin:0 0 14px}
 .n{flex:0 0 26px;text-align:right;color:var(--mut);font-size:12px;font-family:ui-monospace,monospace;padding-top:3px}
 .body{flex:1}.tx{margin:0 0 5px}.a .tx{color:#d8c7a0}.b .tx{color:var(--ink)}
 audio.mini{height:32px}
</style></head><body><div class="wrap">
 <h1>The Diary of Gour Govinda Swami Mahārāja</h1>
 <p class="date">8 May 1975 &mdash; the vow on giving up night Prasādam &middot; spoken in his cloned voice</p>
 <div class="full"><div class="t">&#9673; The complete narration</div><audio controls preload="metadata" id="full"></audio></div>
 <div id="parts"></div>
</div>
<script>
const D=/*__DATA__*/;const $=s=>document.querySelector(s);
if(D.full)$("#full").src=D.full;
const A=D.items.filter(x=>x.part==="A"),B=D.items.filter(x=>x.part==="B");
const sec=(title,arr,cls)=>`<h2>${title}</h2>`+arr.map(x=>`<div class="line ${cls}"><div class="n">${x.n}</div><div class="body"><div class="tx">${x.text}</div>${x.url?`<audio class="mini" controls preload="none" src="${x.url}"></audio>`:""}</div></div>`).join("");
$("#parts").innerHTML=sec("Part A &mdash; narration / framing",A,"a")+sec("Part B &mdash; his diary entry (first person)",B,"b");
</script></body></html>
"""

AUD.mkdir(parents=True, exist_ok=True)
lines = [l.strip() for l in CHUNKS_TXT.read_text(encoding="utf-8").splitlines() if l.strip()]


def put(name):
    s = SRC / name
    if s.exists():
        shutil.copyfile(s, AUD / name)
        return f"audio/{name}"
    return None


full = put("full.wav")
items = []
for i, txt in enumerate(lines, 1):
    items.append(dict(n=i, text=txt, url=put(f"chunk_{i:02d}.wav"), part="A" if i <= 3 else "B"))

(OUT / "index.html").write_text(TEMPLATE.replace("/*__DATA__*/", json.dumps(dict(full=full, items=items), ensure_ascii=False)), encoding="utf-8")
print(f"wrote {OUT / 'index.html'} | full={bool(full)} | {len(items)} chunks")
