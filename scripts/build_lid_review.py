"""
build_lid_review.py — interactive review of the MMS-LID ear-check samples.

Reads data/hi/lid_samples/<mms_lang>/*.wav (from cloud/export_lid_samples.py) and writes
data/hi/lid_samples/index.html as a labeling tool: per clip you mark what it TRULY is
(Hindi speech / Kirtana sung / Odia / English / Noise), add a note; it autosaves to the browser
and shows, per MMS label-group, the distribution of your true-calls (so "MMS=Nepali" turning out
to be "Hindi speech" is measured, not just asserted). Download button exports lid_review.json —
this is our small hand-labeled dev set + kirtana calibration data.

Runs locally (stdlib); reuses the already-pulled data/hi/lid_samples/ audio.
  python scripts/build_lid_review.py
"""
import html
import json
from pathlib import Path

BASE = Path("data/hi/lid_samples")
# MMS label -> (display, the question to answer)
GROUPS = [
    ("hin", "Hindi (MMS confident)", "Reference — this is what he sounds like when MMS is sure it's Hindi."),
    ("npi", "MMS said: Nepali", "He doesn't speak Nepali. Is this really him speaking HINDI? (the key test)"),
    ("guj", "MMS said: Gujarati", "Almost certainly accented Hindi mislabeled — confirm."),
    ("asm", "MMS said: Assamese", "Almost certainly accented Hindi mislabeled — confirm."),
    ("ben", "MMS said: Bengali", "Expect a MIX: some SUNG kirtana (drop) + some mislabeled Hindi speech."),
    ("ory", "MMS said: Odia", "Only 7 windows in all 116 min. Is even this Odia, or Hindi?"),
    ("eng", "MMS said: English", "Only 1 window total; his English is embedded in Hindi, not pure."),
]
TRUTH = ["Hindi speech", "Kirtana (sung)", "Odia speech", "English", "Noise/unclear"]

HEAD = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>MMS-LID ear-check — label it</title>
<style>
 :root{--gold:#c9a24a;--line:#332e2a}
 body{margin:0;background:#12100f;color:#f3eee9;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .w{max-width:900px;margin:0 auto;padding:16px}
 h1{font-size:19px;color:var(--gold);margin:0 0 4px}.note{color:#a89f97;font-size:13px;margin:0 0 10px}
 .bar{position:sticky;top:0;z-index:5;background:#0d0b0aee;backdrop-filter:blur(4px);border:1px solid var(--line);
      border-radius:10px;padding:10px 12px;margin:0 0 16px}
 button{background:var(--gold);color:#1a1712;border:0;border-radius:7px;padding:7px 12px;font-weight:600;cursor:pointer;margin-right:8px}
 button.ghost{background:#2a2521;color:#cfc6bd}
 .tally{font-size:12px;color:#cfc6bd;margin-top:8px}.tally div{margin:2px 0}
 .tally b{color:var(--gold)}
 h2{font-size:15px;color:var(--gold);margin:22px 0 2px;border-top:1px solid var(--line);padding-top:14px}
 .q{color:#d8c7a0;font-size:13px;margin:0 0 10px}
 .clip{background:#1d1a18;border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:0 0 10px}
 .cid{font:11px ui-monospace,Menlo,monospace;color:#8f8880;margin:0 0 6px}
 audio{width:100%;height:34px;margin:0 0 8px}
 .opts{display:flex;flex-wrap:wrap;gap:6px}
 .opts label{cursor:pointer;font-size:13px;background:#15120f;border:1px solid var(--line);border-radius:6px;
             padding:4px 9px;user-select:none;display:flex;align-items:center;gap:5px}
 .opts label.on{background:#241f16;border-color:var(--gold);color:var(--gold)}
 textarea{width:100%;box-sizing:border-box;margin-top:8px;background:#15120f;color:#e9dcc4;border:1px solid var(--line);
          border-radius:7px;padding:5px 8px;font:13px system-ui;resize:vertical}
 .done{outline:1px solid #3a5f3a}
</style></head><body><div class="w">
<h1>MMS-LID ear-check — what is each clip really?</h1>
<p class="note">MMS-LID called only 34% of his speech "Hindi" and scattered the rest. For each clip, tick
<b>every</b> label that applies (a clip can be Hindi + embedded English, or Hindi with a bit of kirtana at the edge).
Watch the tally: if "Nepali/Gujarati/Assamese" fill up with <b>Hindi speech</b>, that proves no language-ID can
filter his accent. Autosaves here; hit <b>Download</b> when done.</p>
<div class="bar"><button onclick="dl()">⬇ Download labels</button>
<button class="ghost" onclick="if(confirm('Clear all?')){localStorage.removeItem(KEY);location.reload()}">Clear</button>
<span id="prog"></span><div class="tally" id="tally"></div></div>
"""
FOOT = """<script>
const KEY="lid_review_v1", TRUTH=%TRUTH%, GROUPS=%GROUPS%;
function load(){try{return JSON.parse(localStorage.getItem(KEY))||{}}catch(e){return{}}}
let S=load();
function save(){localStorage.setItem(KEY,JSON.stringify(S))}
function truths(id){return (S[id]&&S[id].truth)||[]}         // multi-select: an array of labels
function render(){
  document.querySelectorAll('.clip').forEach(c=>{
    const id=c.dataset.clip, t=truths(id);
    c.querySelectorAll('.opts label').forEach(l=>l.classList.toggle('on', t.includes(l.dataset.v)));
    const ta=c.querySelector('textarea'); if(ta) ta.value=(S[id]&&S[id].note)||"";
    c.classList.toggle('done', t.length>0);
  });
  updateBar();
}
function updateBar(){
  const clips=document.querySelectorAll('.clip').length;
  let done=Object.values(S).filter(r=>r.truth&&r.truth.length).length;
  document.getElementById('prog').innerHTML=`<b>${done}</b> / ${clips} labeled`;
  let html='';
  GROUPS.forEach(([g,disp])=>{
    const ids=[...document.querySelectorAll(`.clip[data-mms="${g}"]`)].map(c=>c.dataset.clip);
    if(!ids.length) return;
    const cnt={}; ids.forEach(id=>truths(id).forEach(t=>cnt[t]=(cnt[t]||0)+1));   // a clip counts for each tag
    const parts=Object.entries(cnt).map(([k,v])=>`${k}: <b>${v}</b>`).join(' · ')||'—';
    html+=`<div>${disp}: ${parts}</div>`;
  });
  document.getElementById('tally').innerHTML=html;
}
document.addEventListener('click',e=>{
  const l=e.target.closest('.opts label'); if(!l) return;
  const c=l.closest('.clip'), id=c.dataset.clip, v=l.dataset.v;
  S[id]=S[id]||{}; S[id].mms=c.dataset.mms;
  const set=new Set(S[id].truth||[]); set.has(v)?set.delete(v):set.add(v);   // toggle membership
  S[id].truth=[...set]; save(); render();
});
document.addEventListener('input',e=>{
  if(e.target.tagName==='TEXTAREA'){const c=e.target.closest('.clip'); S[c.dataset.clip]=S[c.dataset.clip]||{};
    S[c.dataset.clip].note=e.target.value; S[c.dataset.clip].mms=c.dataset.mms; save();}
});
function dl(){const b=new Blob([JSON.stringify({at:new Date().toISOString(),labels:S},null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='lid_review.json';a.click();}
render();
</script></div></body></html>"""


def main():
    body = [HEAD]
    idx = 0
    for g, disp, q in GROUPS:
        d = BASE / g
        if not d.exists():
            continue
        clips = sorted(d.glob("*.wav"))
        if not clips:
            continue
        body.append(f'<h2>{html.escape(disp)}</h2><div class="q">{html.escape(q)}</div>')
        for c in clips:
            cid = f"{g}/{c.name}"
            opts = "".join(
                f'<label data-v="{html.escape(t, quote=True)}">{html.escape(t)}</label>' for t in TRUTH)
            body.append(
                f'<div class="clip" data-mms="{g}" data-clip="{html.escape(cid, quote=True)}">'
                f'<div class="cid">{html.escape(c.name)}</div>'
                f'<audio controls preload="none" src="{g}/{html.escape(c.name)}"></audio>'
                f'<div class="opts">{opts}</div>'
                f'<textarea rows="1" placeholder="note (optional)…"></textarea></div>')
            idx += 1
    foot = (FOOT.replace("%TRUTH%", json.dumps(TRUTH))
                .replace("%GROUPS%", json.dumps([[g, disp] for g, disp, _ in GROUPS])))
    body.append(foot)
    (BASE / "index.html").write_text("\n".join(body), encoding="utf-8")
    print(f"wrote {BASE/'index.html'} — interactive over {idx} clips")


if __name__ == "__main__":
    main()
