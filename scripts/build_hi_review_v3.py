"""
build_hi_review_v3.py — transcript review/builder for the clean v3 clips (3 ASR drafts each).

Reads data/hi/lectures/*/train_hi_v3.jsonl and writes data/hi/review_v3/index.html: per clip you play the
audio, see the 3 model drafts (click one to load it as the base), edit the FINAL Hindi transcript, or DROP
the clip (residual kirtana / pure-English / noise / non-Hindi). Where 2+ models agree the text is pre-filled
and the card is flagged green (skim it). Autosaves to the browser; "Download" exports train_hi_final.jsonl
(kept clips + corrected text) — the actual training set.

Runs locally (stdlib). Audio is referenced relative to the clips already pulled under data/hi/lectures/.
  python scripts/build_hi_review_v3.py
"""
import html
import json
import re
from pathlib import Path

HI = Path("data/hi/lectures")
OUT = Path("data/hi/review_v3")
MODELS = ["IndicConformer-600M RNNT", "Vaani-Hindi", "Trelis-Hinglish"]


def norm(t):
    return re.sub(r"\s+", " ", (t or "").strip())


def consensus(texts):
    """(prefill, agree): if 2+ drafts match (normalized) -> that text + agree=True; else first non-empty."""
    vals = [norm(texts.get(m, "")) for m in MODELS]
    for v in vals:
        if v and sum(1 for x in vals if x == v) >= 2:
            return v, True
    for v in vals:
        if v:
            return v, False
    return "", False


HEAD = """<!doctype html><html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Hindi v3 — transcript review</title>
<style>
 :root{--gold:#c9a24a;--line:#332e2a}
 body{margin:0;background:#12100f;color:#f3eee9;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .w{max-width:940px;margin:0 auto;padding:14px}
 h1{font-size:19px;color:var(--gold);margin:0 0 4px}.note{color:#a89f97;font-size:13px;margin:0 0 8px}
 .bar{position:sticky;top:0;z-index:5;background:#0d0b0aee;backdrop-filter:blur(4px);border:1px solid var(--line);
      border-radius:10px;padding:9px 12px;margin:0 0 14px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
 button{background:var(--gold);color:#1a1712;border:0;border-radius:7px;padding:6px 11px;font-weight:600;cursor:pointer}
 button.ghost{background:#2a2521;color:#cfc6bd}
 .bar span{font-size:13px;color:#cfc6bd}
 .clip{background:#1d1a18;border:1px solid var(--line);border-radius:11px;padding:10px 12px;margin:0 0 12px}
 .clip.agree{border-left:3px solid #3a7d44}
 .clip.dropped{opacity:.45;border-left:3px solid #7a4a4a}
 .clip.done{border-left:3px solid var(--gold)}
 .top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:0 0 6px}
 .cid{font:11px ui-monospace,Menlo,monospace;color:#8f8880}
 .drop{font-size:12px;color:#c98f8f;cursor:pointer;user-select:none;display:flex;gap:5px;align-items:center}
 audio{width:100%;height:34px;margin:0 0 8px}
 .draft{display:flex;gap:8px;align-items:flex-start;padding:4px 0;cursor:pointer;border-radius:6px}
 .draft:hover{background:#241f16}
 .dl{flex:0 0 96px;font-size:11px;color:var(--gold);padding-top:3px}
 .dt{flex:1;font:15px/1.45 'Noto Sans Devanagari',serif;color:#cbbfa8}
 .dt.empty{color:#7a5555;font-style:italic}
 textarea{width:100%;box-sizing:border-box;margin-top:8px;background:#15120f;color:#f3eee9;border:1px solid var(--gold);
          border-radius:7px;padding:7px 9px;font:16px/1.5 'Noto Sans Devanagari',serif;resize:vertical}
 .lechdr{font-size:14px;color:var(--gold);margin:18px 0 6px;border-top:1px solid var(--line);padding-top:12px}
</style></head><body><div class="w">
<h1>Hindi v3 — build the clean training transcripts</h1>
<p class="note">Per clip: play it, click whichever draft is closest (loads into the box), fix the box, or hit
<b>drop</b> (kirtana / pure-English / noise / not-Hindi). Green stripe = 2+ models agreed (pre-filled, just skim).
Keep his accent + embedded English; only drop clearly non-Hindi/unusable. Autosaves here.</p>
<div class="bar">
 <button onclick="dl()">⬇ Download training set</button>
 <button class="ghost" onclick="flt('all')">All</button>
 <button class="ghost" onclick="flt('todo')">Unreviewed</button>
 <button class="ghost" onclick="flt('kept')">Kept</button>
 <button class="ghost" onclick="flt('drop')">Dropped</button>
 <span id="prog"></span>
</div>
"""
FOOT = """<script>
const KEY="hi_v3_review";
function load(){try{return JSON.parse(localStorage.getItem(KEY))||{}}catch(e){return{}}}
let S=load();
function save(){localStorage.setItem(KEY,JSON.stringify(S))}
function rec(id){return S[id]||(S[id]={})}
function render(){
  document.querySelectorAll('.clip').forEach(c=>{
    const id=c.dataset.clip,r=S[id]||{};
    const ta=c.querySelector('textarea');
    if(ta && document.activeElement!==ta) ta.value=(r.text!==undefined?r.text:c.dataset.prefill);
    c.classList.toggle('dropped',!!r.drop);
    c.classList.toggle('done',!r.drop&&(r.reviewed||r.text!==undefined));
    const d=c.querySelector('.drop input'); if(d) d.checked=!!r.drop;
  });
  bar();
}
function bar(){
  const clips=document.querySelectorAll('.clip').length;
  let kept=0,drop=0;
  Object.values(S).forEach(r=>{ if(r.drop)drop++; else if(r.reviewed||r.text!==undefined)kept++; });
  document.getElementById('prog').innerHTML=`<b>${kept}</b> kept · <b>${drop}</b> dropped · ${clips-kept-drop} left of ${clips}`;
}
document.addEventListener('click',e=>{
  const d=e.target.closest('.draft');
  if(d){const c=d.closest('.clip'),id=c.dataset.clip;rec(id).text=d.dataset.t;rec(id).reviewed=true;rec(id).drop=false;save();render();
        const ta=c.querySelector('textarea');ta.value=d.dataset.t;return;}
  const dr=e.target.closest('.drop');
  if(dr){const c=dr.closest('.clip'),id=c.dataset.clip;rec(id).drop=!rec(id).drop;save();render();}
});
document.addEventListener('input',e=>{
  if(e.target.tagName==='TEXTAREA'){const c=e.target.closest('.clip'),id=c.dataset.clip;
    rec(id).text=e.target.value;rec(id).reviewed=true;save();bar();}
});
function flt(m){document.querySelectorAll('.clip').forEach(c=>{
  const r=S[c.dataset.clip]||{},done=r.reviewed||r.text!==undefined;
  let show=true;
  if(m==='todo')show=!r.drop&&!done; else if(m==='kept')show=!r.drop&&done; else if(m==='drop')show=!!r.drop;
  c.style.display=show?'':'none';});}
function dl(){
  const rows=[];
  document.querySelectorAll('.clip').forEach(c=>{
    const id=c.dataset.clip,r=S[id]||{};
    if(r.drop) return;
    const t=(r.text!==undefined?r.text:c.dataset.prefill).trim();
    if(!t) return;
    rows.push(JSON.stringify({audio:c.dataset.audio,lecture:c.dataset.lec,
      start:parseFloat(c.dataset.start),end:parseFloat(c.dataset.end),text:t}));
  });
  const b=new Blob([rows.join("\\n")],{type:'application/jsonl'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='train_hi_final.jsonl';a.click();
}
render();
</script></div></body></html>"""


def main():
    rows = []
    for d in sorted(HI.iterdir()):
        jf = d / "train_hi_v3.jsonl"
        if not jf.exists():
            continue
        for line in jf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))

    OUT.mkdir(parents=True, exist_ok=True)
    body = [HEAD]
    cur_lec = None
    for r in rows:
        lec = r["lecture"]
        if lec != cur_lec:
            body.append(f'<div class="lechdr">{html.escape(lec)}</div>')
            cur_lec = lec
        name = Path(r["audio"]).name
        cid = f"{lec}/{name}"
        audio_rel = f"../lectures/{lec}/clips_hi/{name}"
        prefill, agree = consensus(r["texts"])
        drafts = ""
        for m in MODELS:
            t = norm(r["texts"].get(m, ""))
            cell = html.escape(t) if t else "(empty)"
            cls = "dt" if t else "dt empty"
            drafts += (f'<div class="draft" data-t="{html.escape(t, quote=True)}">'
                       f'<div class="dl">{html.escape(m.split("-")[0].split(" ")[0])}</div>'
                       f'<div class="{cls}">{cell}</div></div>')
        body.append(
            f'<div class="clip{" agree" if agree else ""}" data-clip="{html.escape(cid, quote=True)}" '
            f'data-audio="{html.escape(r["audio"], quote=True)}" data-lec="{html.escape(lec, quote=True)}" '
            f'data-start="{r["start"]}" data-end="{r["end"]}" data-prefill="{html.escape(prefill, quote=True)}">'
            f'<div class="top"><span class="cid">{html.escape(name)}</span>'
            f'<label class="drop"><input type="checkbox"> drop</label></div>'
            f'<audio controls preload="none" src="{html.escape(audio_rel)}"></audio>'
            f'{drafts}'
            f'<textarea rows="2"></textarea></div>')
    body.append(FOOT)
    (OUT / "index.html").write_text("\n".join(body), encoding="utf-8")
    print(f"wrote {OUT/'index.html'} — {len(rows)} clips (3 drafts each)")


if __name__ == "__main__":
    main()
