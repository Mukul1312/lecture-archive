"""
build_hi_review_v3.py — transcript review/builder for the clean v3 clips (3 ASR drafts each).

Two-mode single-page app written to data/hi/review_v3/index.html:
  FLASHCARD — one clip at a time, audio auto-plays; keyboard 1/2/3 pick a draft, E edit, K keep, D drop,
              Space replay, arrows move. Explicit state per clip: KEPT / DROPPED / PENDING.
  LIST      — color-coded grid of all clips (green kept / red dropped / grey pending); click to jump.
Download exports train_hi_final.jsonl = ONLY explicitly-KEPT clips with their corrected text (the training
set). Autosaves to browser localStorage. Reads data/hi/lectures/*/train_hi_v3.jsonl; audio referenced from
the clips already under data/hi/lectures/.
  python scripts/build_hi_review_v3.py
"""
import json
import re
from pathlib import Path

HI = Path("data/hi/lectures")
OUT = Path("data/hi/review_v3")
MODELS = ["IndicConformer-600M RNNT", "Vaani-Hindi", "Trelis-Hinglish"]


def norm(t):
    return re.sub(r"\s+", " ", (t or "").strip())


def consensus(vals):
    for v in vals:
        if v and sum(1 for x in vals if x == v) >= 2:
            return v, True
    for v in vals:
        if v:
            return v, False
    return "", False


TEMPLATE = r"""<!doctype html><html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Hindi v3 review</title>
<style>
 :root{--gold:#c9a24a;--line:#332e2a;--keep:#3a7d44;--drop:#a05555}
 *{box-sizing:border-box}
 body{margin:0;background:#12100f;color:#f3eee9;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .app{max-width:900px;margin:0 auto;padding:14px}
 .bar{position:sticky;top:0;z-index:5;background:#0d0b0aee;backdrop-filter:blur(4px);border:1px solid var(--line);
      border-radius:10px;padding:9px 12px;margin:0 0 14px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
 button{background:#2a2521;color:#cfc6bd;border:1px solid var(--line);border-radius:7px;padding:6px 12px;font-weight:600;cursor:pointer;font-size:13px}
 button.on{background:var(--gold);color:#1a1712;border-color:var(--gold)}
 button.keep{background:var(--keep);color:#eafaea;border:0;padding:8px 16px}
 button.drop{background:var(--drop);color:#ffeaea;border:0;padding:8px 16px}
 button.dl{background:var(--gold);color:#1a1712;border:0}
 #prog{font-size:13px;color:#cfc6bd;margin-left:auto}
 #prog b{color:var(--gold)}
 /* flashcard */
 .fc{background:#1d1a18;border:1px solid var(--line);border-radius:14px;padding:16px 18px}
 .fc.kept{border-color:var(--keep);box-shadow:inset 4px 0 0 var(--keep)}
 .fc.dropped{border-color:var(--drop);box-shadow:inset 4px 0 0 var(--drop);opacity:.6}
 .fchdr{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:0 0 10px;font-size:13px;color:#a89f97}
 .cid{font:11px ui-monospace,Menlo,monospace;color:#8f8880}
 .badge{font-size:11px;font-weight:700;letter-spacing:.05em;padding:3px 8px;border-radius:20px;background:#2a2521;color:#cfc6bd}
 .badge.kept{background:var(--keep);color:#eafaea}.badge.dropped{background:var(--drop);color:#ffeaea}
 .badge.agree{background:#243b28;color:#8fd39a}
 audio{width:100%;height:38px;margin:0 0 12px}
 .dr{display:flex;gap:9px;align-items:flex-start;padding:7px 8px;cursor:pointer;border-radius:8px;border:1px solid transparent}
 .dr:hover{background:#241f16}.dr.sel{background:#241f16;border-color:var(--gold)}
 .dr .k{flex:0 0 20px;height:20px;border-radius:5px;background:#332e2a;color:var(--gold);text-align:center;font-weight:700;font-size:12px;line-height:20px}
 .dr .ml{flex:0 0 92px;font-size:11px;color:var(--gold);padding-top:2px}
 .dr .dt{flex:1;font:16px/1.5 'Noto Sans Devanagari',serif;color:#cbbfa8}
 .dr .dt i{color:#7a5555}
 textarea{width:100%;margin:12px 0 0;background:#15120f;color:#f3eee9;border:1px solid var(--gold);border-radius:8px;
          padding:9px 11px;font:17px/1.55 'Noto Sans Devanagari',serif;resize:vertical}
 .btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
 .help{color:#8f8880;font-size:12px;margin:12px 0;text-align:center}
 .help b{color:var(--gold)}
 /* list */
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(38px,1fr));gap:5px}
 .cell{aspect-ratio:1;display:flex;align-items:center;justify-content:center;font-size:11px;border-radius:6px;
       background:#2a2521;color:#8f8880;cursor:pointer;border:1px solid var(--line)}
 .cell.kept{background:var(--keep);color:#eafaea;border-color:var(--keep)}
 .cell.dropped{background:var(--drop);color:#ffeaea;border-color:var(--drop)}
 .cell:hover{outline:2px solid var(--gold)}
 .lgd{font-size:12px;color:#a89f97;margin:0 0 10px}
 .lgd b{padding:2px 7px;border-radius:5px}.lgd .g{background:var(--keep);color:#eafaea}.lgd .r{background:var(--drop);color:#ffeaea}.lgd .n{background:#2a2521}
</style></head><body><div class="app">
<div class="bar">
 <button id="tab-card" class="on" onclick="setView('card')">Flashcard</button>
 <button id="tab-list" onclick="setView('list')">List</button>
 <button class="dl" onclick="dl()">⬇ Download kept</button>
 <span id="prog"></span>
</div>
<div id="card"></div>
<div id="list" style="display:none"></div>
<div class="help" id="help"><b>1/2/3</b> pick draft · <b>E</b> edit · <b>K</b> keep→next · <b>D</b> drop→next · <b>Space</b> replay · <b>←/→</b> move</div>
</div>
<script>
const CLIPS=__DATA__, ML=__ML__, KEY="hi_v3_review2";
CLIPS.forEach((c,i)=>{c.id=c.l+"/"+c.n;c.i=i;});
let S=(()=>{try{return JSON.parse(localStorage.getItem(KEY))||{}}catch(e){return{}}})();
function save(){localStorage.setItem(KEY,JSON.stringify(S))}
let cur=0, view="card";
function st(id){return (S[id]&&S[id].st)||""}
function textOf(c){const r=S[c.id];return (r&&r.text!==undefined)?r.text:c.p;}
function esc(s){return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function bar(){let k=0,d=0;Object.values(S).forEach(r=>{if(r.st==="kept")k++;else if(r.st==="dropped")d++;});
 document.getElementById("prog").innerHTML=`<b>${k}</b> kept · <b>${d}</b> dropped · ${CLIPS.length-k-d} pending / ${CLIPS.length}`;}
function renderCard(){
 const c=CLIPS[cur],s=st(c.id),cur_t=textOf(c);
 const drafts=c.d.map((t,n)=>`<div class="dr${cur_t===t&&t?' sel':''}" onclick="pick(${n})">
   <span class="k">${n+1}</span><span class="ml">${ML[n]}</span><span class="dt">${esc(t)||'<i>(empty)</i>'}</span></div>`).join("");
 const badge=s?`<span class="badge ${s}">${s.toUpperCase()}</span>`:(c.g?'<span class="badge agree">2+ AGREE</span>':'<span class="badge">PENDING</span>');
 document.getElementById("card").innerHTML=`<div class="fc ${s}">
   <div class="fchdr"><span>${c.i+1} / ${CLIPS.length}</span><span class="cid">${esc(c.l)} · ${esc(c.n)}</span>${badge}</div>
   <audio id="au" controls src="${esc(c.a)}"></audio>
   <div class="drafts">${drafts}</div>
   <textarea id="ed" rows="2" oninput="live()">${esc(cur_t)}</textarea>
   <div class="btns"><button class="keep" onclick="keep()">✓ Keep (K)</button><button class="drop" onclick="drop()">✗ Drop (D)</button>
     <button onclick="go(cur-1)">◀ Prev</button><button onclick="go(cur+1)">Next ▶</button></div></div>`;
 const au=document.getElementById("au"); if(au) au.play().catch(()=>{});
 bar();
}
function renderList(){
 document.getElementById("list").innerHTML=
  '<div class="lgd"><b class="g">kept</b> <b class="r">dropped</b> <b class="n">pending</b> — click any to jump</div>'+
  '<div class="grid">'+CLIPS.map(c=>`<div class="cell ${st(c.id)}" title="${esc(c.n)}" onclick="jump(${c.i})">${c.i+1}</div>`).join("")+'</div>';
 bar();
}
function pick(n){const c=CLIPS[cur],ed=document.getElementById("ed");if(ed)ed.value=c.d[n]||"";
 S[c.id]=S[c.id]||{};S[c.id].text=c.d[n]||"";save();document.querySelectorAll(".dr").forEach((e,i)=>e.classList.toggle("sel",i===n&&!!c.d[n]));}
function live(){const c=CLIPS[cur];S[c.id]=S[c.id]||{};S[c.id].text=document.getElementById("ed").value;save();}
function keep(){const c=CLIPS[cur];S[c.id]=S[c.id]||{};if(S[c.id].text===undefined)S[c.id].text=c.p;S[c.id].st="kept";save();nextPending();}
function drop(){const c=CLIPS[cur];S[c.id]=S[c.id]||{};S[c.id].st="dropped";save();nextPending();}
function nextPending(){for(let i=cur+1;i<CLIPS.length;i++){if(!st(CLIPS[i].id)){go(i);return;}}go(Math.min(cur+1,CLIPS.length-1));}
function go(i){cur=Math.max(0,Math.min(i,CLIPS.length-1));if(view!=="card")setView("card");else renderCard();window.scrollTo(0,0);}
function jump(i){cur=Math.max(0,Math.min(i,CLIPS.length-1));setView("card");}
function setView(v){view=v;
 document.getElementById("card").style.display=v==="card"?"":"none";
 document.getElementById("list").style.display=v==="list"?"":"none";
 document.getElementById("help").style.display=v==="card"?"":"none";
 document.getElementById("tab-card").classList.toggle("on",v==="card");
 document.getElementById("tab-list").classList.toggle("on",v==="list");
 if(v==="card")renderCard();else renderList();}
function dl(){const rows=[];CLIPS.forEach(c=>{if(st(c.id)!=="kept")return;const t=textOf(c).trim();if(!t)return;
  rows.push(JSON.stringify({audio:c.audio,lecture:c.l,start:c.s,end:c.e,text:t}));});
 if(!rows.length){alert("No clips marked Keep yet.");return;}
 const b=new Blob([rows.join("\n")],{type:"application/jsonl"});const a=document.createElement("a");
 a.href=URL.createObjectURL(b);a.download="train_hi_final.jsonl";a.click();}
document.addEventListener("keydown",e=>{
 if(view!=="card")return;
 const ed=document.getElementById("ed");
 if(document.activeElement===ed){if(e.key==="Escape"){ed.blur();}return;}
 if(e.key>="1"&&e.key<="3"){pick(+e.key-1);e.preventDefault();}
 else if(e.key==="k"||e.key==="K"){keep();e.preventDefault();}
 else if(e.key==="d"||e.key==="D"){drop();e.preventDefault();}
 else if(e.key==="e"||e.key==="E"){if(ed)ed.focus();e.preventDefault();}
 else if(e.key===" "){const au=document.getElementById("au");if(au){au.currentTime=0;au.play();}e.preventDefault();}
 else if(e.key==="ArrowLeft"){go(cur-1);e.preventDefault();}
 else if(e.key==="ArrowRight"){go(cur+1);e.preventDefault();}
});
setView("card");
</script></body></html>"""


def main():
    clips = []
    for d in sorted(HI.iterdir()):
        jf = d / "train_hi_v3.jsonl"
        if not jf.exists():
            continue
        for line in jf.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            lec, name = r["lecture"], Path(r["audio"]).name
            dr = [norm(r["texts"].get(m, "")) for m in MODELS]
            pf, ag = consensus(dr)
            clips.append({"l": lec, "n": name, "audio": r["audio"],
                          "a": f"../lectures/{lec}/clips_hi/{name}",
                          "s": r["start"], "e": r["end"], "d": dr, "p": pf, "g": ag})
    OUT.mkdir(parents=True, exist_ok=True)
    short = [m.split(" ")[0].split("-")[0] for m in MODELS]
    out = (TEMPLATE.replace("__DATA__", json.dumps(clips, ensure_ascii=False))
                   .replace("__ML__", json.dumps(short, ensure_ascii=False)))
    (OUT / "index.html").write_text(out, encoding="utf-8")
    print(f"wrote {OUT/'index.html'} — {len(clips)} clips, flashcard+list, {sum(c['g'] for c in clips)} agree")


if __name__ == "__main__":
    main()
