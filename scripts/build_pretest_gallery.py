"""
build_pretest_gallery.py — audition the pronunciation pre-test, WITH emotion/graveness metrics AND notes.
For each test sentence it shows the spoken text, the tricky term(s) it stress-tests, and every seed-take
with: the audio (judge pronunciation by ear), its measured prosody (pitch, range, loudness, rate) + a
combined "graveness" score (low pitch · narrow range · quiet · slow, centred within the sentence), and a
NOTES box per take to flag generation problems. Takes are sorted gravest-first. Notes persist in the
browser and export via a "copy notes" button to send back.

Output -> voice_lab/pretest/  (servable). Run after pulling out_pretest -> data/out/lecture1/pretest/.
  .venv/Scripts/python.exe scripts/build_pretest_gallery.py
"""
import importlib.util
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/lecture1/pretest"
OUT = ROOT / "voice_lab" / "pretest"
AUD = OUT / "audio"

_spec = importlib.util.spec_from_file_location("bg", ROOT / "scripts" / "build_graveness.py")
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

TESTS = {
    "date":     ("May eighth, nineteen seventy five, Thursday.", "the spoken DATE (May 8th 1975 Thursday)"),
    "vow":      ("...except a little maha water with Tulasi.", "mahā-water, Tulasī"),
    "iskcon":   ("To open an ISKCON centre in Odisha.", "ISKCON, Odisha"),
    "prema":    ("...complete and uninterrupted Krishna prema.", "kṛṣṇa-prema"),
    "prasadam": ("He will not accept any Prasadam at night.", "Prasādam"),
    "lila":     ("But what an astonishing leela You are performing.", "līlā"),
    "sannyasi": ("...severe austerity in front of a sannyasi present here.", "sannyāsī"),
    "gopala":   ("Oh my Lord, Gopala! Please shower Your mercy.", "Gopāla"),
    "gauranga": ("...in the service of Sri Sri Guru and Gauranga. Hare Krishna.", "Śrī Śrī, Gaurānga, Hare Kṛṣṇa"),
}


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    AUD.mkdir(parents=True, exist_ok=True)
    pat = re.compile(r"(?P<label>\w+)__s(?P<seed>\d+)\.wav")

    rows = []
    for p in sorted(SRC.glob("*.wav")):
        m = pat.match(p.name)
        if not m or m["label"] not in TESTS:
            continue
        f = bg.feats(p)
        shutil.copyfile(p, AUD / p.name)
        rows.append(dict(label=m["label"], seed=int(m["seed"]), wav=f"audio/{p.name}", **f))

    for key in ("f0", "spread", "loud", "rate"):
        by_sent = defaultdict(list)
        for r in rows:
            by_sent[r["label"]].append(r[key])
        means = {s: float(np.mean(v)) for s, v in by_sent.items()}
        devs = [r[key] - means[r["label"]] for r in rows]
        sd = float(np.std(devs)) or 1.0
        for r, d in zip(rows, devs):
            r[f"z_{key}"] = d / sd
    for r in rows:
        r["grave"] = round(-(r["z_f0"] + r["z_spread"] + r["z_loud"] + r["z_rate"]) / 4, 3)

    groups = []
    for label, (text, terms) in TESTS.items():
        g = sorted([r for r in rows if r["label"] == label], key=lambda r: -r["grave"])
        groups.append(dict(text=text, terms=terms, takes=[
            dict(seed=r["seed"], wav=r["wav"], grave=r["grave"], f0=round(r["f0"]),
                 spread=round(r["spread"]), loud=round(r["loud"], 1), rate=round(r["rate"], 1)) for r in g]))
    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(groups, ensure_ascii=False))
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"wrote {OUT / 'index.html'}  ({sum(len(g['takes']) for g in groups)} takes, {len(groups)} sentences, graveness-ranked, notes enabled)")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pronunciation + emotion pre-test</title>
<style>
  :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--warn:#ffb84a;--g:#7c9cff;}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:980px;margin:0 auto;padding:22px 16px 96px}
  h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 16px;max-width:760px}
  .item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
  .term{font-size:12px;color:var(--warn);font-weight:700;margin:0 0 2px}.txt{margin:0 0 8px;font-size:13.5px}
  table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);font-size:12.5px;vertical-align:middle}
  th{color:var(--mut);font-weight:600}tr.top td{background:#16302a}
  .gv{font-weight:700;color:var(--g)} audio{width:170px;height:30px}
  input.note{width:100%;min-width:150px;background:#11141b;border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:4px 7px;font:inherit;font-size:12px}
  input.note.has{border-color:var(--warn)}
  .hint{font-size:11.5px;color:var(--mut)}
  .bar{position:fixed;left:0;right:0;bottom:0;background:#11141b;border-top:1px solid var(--line);padding:9px 16px;display:flex;gap:12px;align-items:center;justify-content:center}
  .bar button{cursor:pointer;border:1px solid var(--warn);background:var(--warn);color:#0f1115;border-radius:8px;padding:8px 16px;font:inherit;font-weight:800}
  .bar span{color:var(--mut);font-size:12.5px} #out{display:none;width:100%;max-width:980px;height:150px;margin:8px auto 0;background:#11141b;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px}
</style></head><body><div class="wrap">
  <h1>🗣️📉 Pre-test — pronunciation <span style="color:var(--mut)">+</span> emotion <span style="color:var(--mut)">+</span> notes</h1>
  <p class="sub">Each block: the tricky <b style="color:var(--warn)">term(s)</b> in a diary sentence, seed-takes ranked <b>gravest-first</b>. Listen for the term said <i>with dignity</i>; read the <b class="gv">graveness</b> + prosody for the <b>solemn</b> take; and <b style="color:var(--warn)">write any generation problems in the notes box</b> (glitch, mispronunciation, rushed, wrong stress…). Notes save automatically — hit <b>Copy notes</b> to send them to me. <span class="hint">graveness = low pitch · narrow range · quiet · slow.</span></p>
  <div id="list"></div>
</div>
<div class="bar"><button id="copy">Copy notes to send Claude</button><span id="cnt"></span></div>
<textarea id="out" readonly></textarea>
<script>
const DATA = /*__DATA__*/;
const LSKEY="pretest_notes_v1";
let notes = JSON.parse(localStorage.getItem(LSKEY)||"{}");
const esc=s=>s.replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;");
document.getElementById("list").innerHTML = DATA.map(g=>`
  <div class="item">
    <div class="term">▶ testing: ${g.terms}</div>
    <div class="txt">"${g.text}"</div>
    <table>
      <tr><th>#</th><th>seed</th><th>graveness</th><th>pitch</th><th>range</th><th>loud</th><th>rate</th><th>listen</th><th>your notes (flag problems)</th></tr>
      ${g.takes.map((t,i)=>`<tr class="${i===0?'top':''}">
        <td>${i+1}</td><td>${t.seed}</td>
        <td class="gv">${t.grave>=0?'+':''}${t.grave}</td>
        <td>${t.f0}</td><td>${t.spread}</td><td>${t.loud}</td><td>${t.rate}</td>
        <td><audio controls preload="none" src="${t.wav}"></audio></td>
        <td><input class="note${(notes[t.wav]||'').trim()?' has':''}" data-k="${t.wav}" data-term="${esc(g.terms)}" data-seed="${t.seed}" data-grave="${t.grave}" value="${esc(notes[t.wav]||'')}" placeholder="e.g. glitch on 'Tulasi', too fast…"></td>
      </tr>`).join("")}
    </table>
  </div>`).join("");
function count(){const n=Object.values(notes).filter(v=>(v||'').trim()).length;document.getElementById("cnt").textContent=n?`${n} note${n>1?'s':''} saved`:"no notes yet";}
document.querySelectorAll("input.note").forEach(inp=>inp.oninput=()=>{
  notes[inp.dataset.k]=inp.value;localStorage.setItem(LSKEY,JSON.stringify(notes));
  inp.classList.toggle("has",!!inp.value.trim());count();});
document.getElementById("copy").onclick=()=>{
  const lines=[];
  document.querySelectorAll("input.note").forEach(inp=>{const v=(inp.value||'').trim();
    if(v)lines.push(`[${inp.dataset.term}] seed ${inp.dataset.seed} (graveness ${inp.dataset.grave}): ${v}`);});
  const out=document.getElementById("out");out.style.display="block";
  out.value=lines.length?("Pre-test problems flagged:\n"+lines.join("\n")):"(no notes written yet)";
  out.select();document.execCommand("copy");
  document.getElementById("copy").textContent="✓ copied — paste to Claude";};
count();
</script></body></html>
"""

if __name__ == "__main__":
    main()
