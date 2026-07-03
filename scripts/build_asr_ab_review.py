"""
build_asr_ab_review.py — turn an asr_ab A/B dump into an INTERACTIVE review gallery.

Reads <dir>/asr_ab.jsonl (from cloud/asr_ab.py) and rewrites <dir>/index.html as a review tool:
per clip you play the audio, ⭐-pick the best model, ✓-tick any acceptable ones, and add a note.
Everything autosaves to browser localStorage (survives reloads) and a "Download review" button
exports asr_ab_review.json so the pick tally + notes come back as structured data.

Runs locally (stdlib only); reuses the already-pulled <dir>/audio/*.wav.
  python scripts/build_asr_ab_review.py voice_lab/asr_ab
"""
import html
import json
import sys
from pathlib import Path

HEAD = """<!doctype html><html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hindi ASR A/B — review</title>
<style>
 :root{--gold:#c9a24a;--bg:#12100f;--card:#1d1a18;--line:#332e2a;--txt:#e9dcc4}
 body{margin:0;background:var(--bg);color:#f3eee9;font:15px/1.55 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:1040px;margin:0 auto;padding:16px}
 h1{font-size:19px;color:var(--gold);margin:0 0 4px}
 .note{color:#a89f97;font-size:13px;margin:0 0 10px}
 .bar{position:sticky;top:0;z-index:5;background:#0d0b0aee;backdrop-filter:blur(4px);
      border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:0 0 16px}
 .bar b{color:var(--gold)} .tally{font-size:13px;color:#cfc6bd;margin-top:6px}
 .tally span{display:inline-block;margin:0 12px 0 0}
 button{background:var(--gold);color:#1a1712;border:0;border-radius:7px;padding:7px 12px;
        font-weight:600;cursor:pointer;font-size:13px;margin-right:8px}
 button.ghost{background:#2a2521;color:#cfc6bd}
 .clip{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 16px}
 .cid{font:12px ui-monospace,Menlo,monospace;color:#8f8880;margin:0 0 8px}
 audio{width:100%;height:36px;margin:0 0 10px}
 .row{display:flex;gap:10px;align-items:flex-start;padding:8px;border-top:1px solid #2a2521;border-radius:8px}
 .row.best{background:#241f16;box-shadow:inset 3px 0 0 var(--gold)}
 .picks{display:flex;flex-direction:column;gap:6px;flex:0 0 auto;padding-top:2px;align-items:center;min-width:42px}
 .picks label{cursor:pointer;font-size:12px;user-select:none;display:flex;align-items:center;gap:3px;color:#a89f97}
 .picks input{cursor:pointer;margin:0}
 .m{flex:1}
 .mlabel{font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--gold);margin:0 0 3px}
 .mtext{font:16px/1.5 'Noto Sans Devanagari',serif;color:var(--txt);word-break:break-word}
 .mtext.empty{color:#a05a5a;font-style:italic}
 textarea{width:100%;box-sizing:border-box;margin-top:8px;background:#15120f;color:#e9dcc4;
          border:1px solid var(--line);border-radius:7px;padding:6px 8px;font:13px system-ui;resize:vertical}
 .done{outline:1px solid #3a5f3a}
</style></head><body><div class="wrap">
<h1>Hindi ASR A/B — pick the best transcriber for his voice</h1>
<p class="note">For each clip: play it, then ⭐ the single <b>best</b> model and ✓ any that are also
<b>acceptable</b>. Add a note if useful. Saves to this browser automatically. When done, hit
<b>Download review</b> and send me the file.</p>
<div class="bar">
  <button onclick="dl()">⬇ Download review</button>
  <button class="ghost" onclick="if(confirm('Clear all your picks/notes?')){localStorage.removeItem(KEY);location.reload()}">Clear all</button>
  <span id="prog"></span>
  <div class="tally" id="tally"></div>
</div>
"""

FOOT = """<script>
const KEY = "asr_ab_review_v1";
const MODELS = window.__MODELS__;
function load(){ try{return JSON.parse(localStorage.getItem(KEY))||{}}catch(e){return {}} }
function save(s){ localStorage.setItem(KEY, JSON.stringify(s)); }
let S = load();

function render(){
  document.querySelectorAll('.clip').forEach(card=>{
    const cid = card.dataset.clip; const rec = S[cid]||{};
    card.querySelectorAll('.best-radio').forEach(r=>{ r.checked = (rec.best===r.value); });
    card.querySelectorAll('.acc-check').forEach(c=>{ c.checked = (rec.acc||[]).includes(c.value); });
    const ta = card.querySelector('textarea'); if(ta) ta.value = rec.note||"";
    card.querySelectorAll('.row').forEach(row=>{
      row.classList.toggle('best', rec.best===row.dataset.model);
    });
    card.classList.toggle('done', !!rec.best);
  });
  updateBar();
}
function updateBar(){
  const clips = document.querySelectorAll('.clip').length;
  let reviewed=0; const counts={}; MODELS.forEach(m=>counts[m]=0);
  Object.values(S).forEach(r=>{ if(r.best){reviewed++; counts[r.best]=(counts[r.best]||0)+1;} });
  document.getElementById('prog').innerHTML = `<b>${reviewed}</b> / ${clips} clips reviewed`;
  document.getElementById('tally').innerHTML = '⭐ best-pick tally: ' +
    MODELS.map(m=>`<span>${m}: <b>${counts[m]||0}</b></span>`).join('');
}
function setBest(cid, model){ S[cid]=S[cid]||{}; S[cid].best=model; save(S); render(); }
function toggleAcc(cid, model, on){
  S[cid]=S[cid]||{}; const a=new Set(S[cid].acc||[]); on?a.add(model):a.delete(model);
  S[cid].acc=[...a]; save(S); updateBar();
}
function setNote(cid, v){ S[cid]=S[cid]||{}; S[cid].note=v; save(S); }
function dl(){
  const out = {reviewed_at:new Date().toISOString(), review:S};
  const b = new Blob([JSON.stringify(out,null,2)], {type:'application/json'});
  const a = document.createElement('a'); a.href=URL.createObjectURL(b);
  a.download='asr_ab_review.json'; a.click();
}
document.addEventListener('change', e=>{
  const el=e.target, card=el.closest('.clip'); if(!card) return; const cid=card.dataset.clip;
  if(el.classList.contains('best-radio')) setBest(cid, el.value);
  else if(el.classList.contains('acc-check')) toggleAcc(cid, el.value, el.checked);
});
document.addEventListener('input', e=>{
  if(e.target.tagName==='TEXTAREA'){ const c=e.target.closest('.clip'); if(c) setNote(c.dataset.clip, e.target.value); }
});
render();
</script></div></body></html>"""


def main():
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "voice_lab/asr_ab")
    rows = [json.loads(l) for l in (d / "asr_ab.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    models = list(rows[0]["texts"].keys())

    body = [HEAD]
    for i, r in enumerate(rows):
        cid = r["clip"]
        body.append(f'<div class="clip" data-clip="{html.escape(cid, quote=True)}">')
        body.append(f'<div class="cid">{html.escape(cid)}</div>')
        body.append(f'<audio controls preload="none" src="audio/{html.escape(Path(cid).name)}"></audio>')
        for m in models:
            txt = (r["texts"].get(m) or "").strip()
            mv = html.escape(m, quote=True)
            cell = html.escape(txt) if txt else '<span class="mtext empty">(empty — model produced nothing)</span>'
            cls = "mtext" if txt else ""
            body.append(f'<div class="row" data-model="{mv}">'
                        f'<div class="picks">'
                        f'<label title="best model for this clip"><input type="radio" name="best-{i}" class="best-radio" value="{mv}">⭐</label>'
                        f'<label title="also acceptable"><input type="checkbox" class="acc-check" value="{mv}">✓</label>'
                        f'</div>'
                        f'<div class="m"><div class="mlabel">{html.escape(m)}</div>'
                        f'<div class="{cls}">{cell}</div></div></div>')
        body.append('<textarea rows="1" placeholder="note for this clip (optional)…"></textarea>')
        body.append('</div>')
    foot = FOOT.replace("window.__MODELS__", json.dumps(models, ensure_ascii=False))
    body.append(foot)
    (d / "index.html").write_text("\n".join(body), encoding="utf-8")
    print(f"wrote {d/'index.html'} — interactive review over {len(rows)} clips × {len(models)} models")


if __name__ == "__main__":
    main()
