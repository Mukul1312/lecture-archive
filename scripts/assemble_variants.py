"""
assemble_variants.py — build the full 8th-May diary in 4 cleaning TIERS and one combined devotee
A/B gallery, so devotees can choose their point on the noise<->identity frontier.

Only HIS lines differ between tiers; the 3rd-person narrator (chunks 1-3) is the SAME base-model take
in every tier, and every tier runs the identical funnel (duration + identity gate, then rank by
graveness + vocal-effort + NOISE-FLOOR). Each tier's full.wav is labelled with its MEASURED mean
output noise floor + ECAPA identity, so the choice is informed but the ear decides.

Pull the pod's /workspace/diary_var -> data/out/lecture1/diary_var/ first (noisy tier = the existing
data/out/lecture1/diary). Then:  .venv/Scripts/python.exe scripts/assemble_variants.py
"""
import json
import re
import shutil
import sys
from collections import defaultdict
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_graveness as bg
import gate_takes as gt
from assemble_diary import vocal_effort, noise_floor, GAP

ROOT = Path(__file__).resolve().parent.parent
SRC_NARR = ROOT / "data/out/lecture1/diary_narr"
CHUNKS = ROOT / "data/narration/diary_chunks_calm.txt"
VAR = ROOT / "data/out/lecture1/diary_var"
NARR = {1, 2, 3}
# equalize every tier to the SAME 24 seeds for a fair, max-quality A/B (all tiers regenerated to 24).
# (Narrator's 6 seeds are a subset, so it's unaffected.)
SEEDS_AB = {42, 123, 7, 2024, 99, 314, 777, 2025, 1, 11, 21, 55,
            88, 111, 222, 333, 444, 555, 666, 888, 999, 1234, 1976, 8848}
OUT = ROOT / "voice_lab" / "diary_variants"
AUD = OUT / "audio"
sys.stdout.reconfigure(encoding="utf-8")

TIERS = [  # (key, label, blurb, ggs-takes dir)   ordered most-him -> cleanest
    ("noisy",  "Untouched", "his voice as-is — most him, faint room tone", ROOT / "data/out/lecture1/diary"),
    ("hpf",    "Gentle high-pass", "identity-safe — rumble removed, him intact", VAR / "hpf"),
    ("zipenh", "ZipEnhancer", "cleaner — small identity shift", VAR / "zipenh"),
    ("redn",   "Full denoise", "cleanest — clearest identity shift", VAR / "redn"),
]
PAT = re.compile(r"(?P<ch>\d+)__s(?P<seed>\d+)\.wav")


def row(p, src, narr, embed, cos, ref):
    m = PAT.match(p.name)
    return dict(ch=int(m["ch"]), seed=int(m["seed"]), wav=p.name, dir=str(src), narr=narr,
                ecapa=round(cos(embed(p), ref), 3), **bg.feats(p), **vocal_effort(p), **noise_floor(p))


def funnel(rows):
    """Per chunk: duration + identity gate, then pick the calmest+quietest clean take."""
    ev = np.array([r["ecapa"] for r in rows if not r["narr"]])
    id_thr = max(0.55, float(ev.mean() - 1.4 * ev.std())) if ev.size else 0.55
    chunks = defaultdict(list)
    for r in rows:
        chunks[r["ch"]].append(r)
    picks = {}
    for ch, takes in chunks.items():
        med = float(np.median([t["dur"] for t in takes]))
        clean = [t for t in takes if 0.6 * med <= t["dur"] <= 1.35 * med
                 and (t["narr"] or t["ecapa"] >= id_thr)]
        pool = clean or takes
        # rank by graveness + vocal-effort ONLY. The noise bed is set by the TIER (reference cleaning),
        # ~uniform within a tier, so a within-tier noise term adds no signal and risks picking p10
        # silence-glitch outliers. noise_floor is still computed per take, but only for the TIER LABEL.
        for k in ("f0", "spread", "rate", "alpha", "peak"):
            v = np.array([t[k] for t in pool], float)
            mu, sd = v.mean(), (v.std() or 1.0)
            for t in pool:
                t[f"z_{k}"] = (t[k] - mu) / sd
        for t in pool:   # softest: low pitch/range, slow, low mean effort, low PEAK effort
            t["calm"] = -(t["z_f0"] + t["z_spread"] + 2.0 * t["z_rate"]
                          + 2.0 * t["z_alpha"] + 2.5 * t["z_peak"]) / 8.5
        picks[ch] = max(pool, key=lambda t: t["calm"])
    return picks, id_thr


def stitch(picks, path):
    order = sorted(picks)
    sr0 = sf.info(str(Path(picks[order[0]]["dir"]) / picks[order[0]]["wav"])).samplerate
    sil = np.zeros(int(GAP * sr0), dtype="float32")
    segs = []
    for ch in order:
        y, sr = sf.read(str(Path(picks[ch]["dir"]) / picks[ch]["wav"]), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        if sr != sr0:
            g = gcd(sr, sr0)
            y = resample_poly(y, sr0 // g, sr // g).astype("float32")
        segs.append(y)
        segs.append(sil)
    full = np.concatenate(segs[:-1])
    sf.write(str(path), full, sr0)
    return len(full) / sr0 / 60


def main():
    for _, _, _, d in TIERS:
        if not d.exists() or not list(d.glob("*.wav")):
            sys.exit(f"missing tier takes: {d} — pull the pod's /workspace/diary_var there first")
    texts = [l.strip() for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    AUD.mkdir(exist_ok=True)

    print("[ecapa] centroid ...")
    embed, ref, ceil, cos = gt.ecapa_centroid()

    # narrator takes (shared across every tier — his lines are what differ)
    narr_rows = [row(p, SRC_NARR, True, embed, cos, ref) for p in sorted(SRC_NARR.glob("*.wav"))
                 if int(PAT.match(p.name)["ch"]) in NARR and int(PAT.match(p.name)["seed"]) in SEEDS_AB]
    print(f"[narr] {len(narr_rows)} shared narrator takes")

    tiers, gal_picks = [], {}
    for key, label, blurb, gdir in TIERS:
        rows = list(narr_rows) + [row(p, gdir, False, embed, cos, ref)
                                  for p in sorted(gdir.glob("*.wav"))
                                  if int(PAT.match(p.name)["ch"]) not in NARR
                                  and int(PAT.match(p.name)["seed"]) in SEEDS_AB]
        picks, id_thr = funnel(rows)
        dur = stitch(picks, OUT / f"full_{key}.wav")
        # TIER LABEL = robust POPULATION mean over ALL of his takes in this tier (not the funnel picks,
        # which are a tiny high-variance sample) — this matches the causal ref A/B and is monotonic.
        ggs_all = [r for r in rows if not r["narr"]]
        tno = float(np.mean([t["nfloor"] for t in ggs_all]))
        tid = float(np.mean([t["ecapa"] for t in ggs_all]))
        tiers.append(dict(key=key, label=label, blurb=blurb, dur=round(dur, 2),
                          noise=round(tno, 1), id=round(tid, 3), n=len(ggs_all)))
        gal_picks[key] = picks
        # copy each tier's picked take for the per-chunk comparison (tier-prefixed to avoid collisions)
        for ch, t in picks.items():
            dst = f"{key}__{t['wav']}"
            shutil.copyfile(Path(t["dir"]) / t["wav"], AUD / dst)
        print(f"[{key:7s}] {dur:.2f} min · noise {tno:6.1f} dBFS · id {tid:.3f} · gate {id_thr:.2f}")

    base = next(t for t in tiers if t["key"] == "noisy")
    for t in tiers:
        t["dnoise"] = round(t["noise"] - base["noise"], 1)
        t["did"] = round(t["id"] - base["id"], 3)

    order = sorted(gal_picks["noisy"])
    groups = [dict(ch=ch, text=texts[ch - 1] if ch - 1 < len(texts) else "", narr=(ch in NARR),
                   takes=[dict(key=k, wav=f"audio/{k}__{gal_picks[k][ch]['wav']}") for k, *_ in TIERS])
              for ch in order]
    data = dict(ceil=round(ceil, 3), tiers=tiers, groups=groups)
    (OUT / "index.html").write_text(TEMPLATE.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False)),
                                    encoding="utf-8")
    print(f"\n[gallery] {OUT / 'index.html'}")
    print("  tiers (most-him -> cleanest):")
    for t in tiers:
        print(f"    {t['label']:18s} noise {t['noise']:6.1f} ({t['dnoise']:+.1f}) · id {t['id']:.3f} ({t['did']:+.3f})")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Diary — cleaning tiers (choose)</title>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--acc:#7cff9c;--note:#ffd479;--warn:#ff9c7c}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:820px;margin:0 auto;padding:22px 18px 120px}h1{font-size:22px;margin:0 0 2px}
 .sub{color:var(--mut);font-size:13px}
 .tier{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 15px;margin:0 0 12px}
 .tier.rec{border-color:var(--acc)}
 .tier h3{margin:0 0 2px;font-size:16px}.tier .blurb{color:var(--mut);font-size:13px;margin-bottom:6px}
 .badge{display:inline-block;font-size:11.5px;color:var(--mut);border:1px solid var(--line);border-radius:20px;padding:1px 9px;margin:0 4px 4px 0}
 .badge b{color:var(--ink)} .good{color:var(--acc)} .bad{color:var(--warn)}
 .tier audio{width:100%;height:40px;margin-top:6px}
 .cmp{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:16px 0 12px}
 details summary{cursor:pointer;color:var(--mut);font-size:13px}
 .row{margin:8px 0;border-top:1px solid var(--line);padding-top:8px}.row .t{font-size:13.5px;color:#fff;margin-bottom:3px}
 .mini{display:flex;align-items:center;gap:8px;margin:3px 0}.mini .k{width:120px;font-size:11.5px;color:var(--mut)}.mini audio{flex:1;height:28px}
 label.nl{display:block;font-size:11px;color:var(--mut);margin:9px 0 3px}
 .note{width:100%;min-height:40px;background:#0f141b;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:7px 9px;font:13px/1.5 system-ui;resize:vertical}
 .note:focus{border-color:var(--note);outline:none}.note.noted{border-color:var(--note)}
 .pickrow{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
 .pick{cursor:pointer;border:1px solid var(--line);background:#0f141b;color:var(--ink);border-radius:20px;padding:5px 13px;font:13px system-ui}
 .pick.on{border-color:var(--acc);background:rgba(124,255,156,.12);color:#fff;font-weight:700}
 .bar{position:fixed;left:0;right:0;bottom:0;background:#11141b;border-top:1px solid var(--line);padding:11px 16px;display:flex;gap:12px;justify-content:center;align-items:center}
 .bar button{cursor:pointer;border:1px solid var(--acc);background:var(--acc);color:#0f1115;border-radius:8px;padding:9px 16px;font:inherit;font-weight:800}
 #out{display:none;width:100%;max-width:820px;height:120px;margin:8px auto 0;background:#11141b;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:8px;font:12.5px ui-monospace,monospace}
</style></head><body><div class="wrap">
<h1>🌙 The diary — choose the cleaning</h1>
<p class="sub">Same words, same narrator — only <b>his</b> voice differs. Listen to each full Short and pick the one that best honours his voice. Top = most him; down = progressively cleaner. Numbers are measured (noise floor + identity); trust your ear.</p>
<div id="tiers"></div>
<div class="cmp"><b>Which do you prefer?</b>
<div class="pickrow" id="picks"></div>
<label class="nl">📝 Why (optional)</label><textarea class="note" data-k="_why" placeholder="what you heard — noise, warmth, which felt most like him…"></textarea></div>
<details class="cmp"><summary>▸ Hear the same line in all tiers (per-chunk A/B)</summary><div id="rows"></div></details>
</div>
<div class="bar"><span id="cnt" class="sub"></span><button id="copy">Copy choice + notes</button></div>
<textarea id="out" readonly></textarea>
<script>
const D=/*__DATA__*/, LN="diary_var_notes", LC="diary_var_choice";
let nt=JSON.parse(localStorage.getItem(LN)||"{}"), choice=localStorage.getItem(LC)||"";
const dd=(v)=>v>0?`<span class="bad">+${v}</span>`:`<span class="good">${v}</span>`;
document.getElementById("tiers").innerHTML=D.tiers.map((t,i)=>`<div class="tier${t.key==='hpf'?' rec':''}">
 <h3>${String.fromCharCode(65+i)}. ${t.label} ${t.key==='hpf'?'· <span class="good">identity-safe</span>':''}</h3>
 <div class="blurb">${t.blurb}</div>
 <span class="badge">noise <b>${t.noise} dBFS</b> ${t.key==='noisy'?'':`(${dd(t.dnoise)} dB)`}</span>
 <span class="badge">identity <b>${t.id}</b> ${t.key==='noisy'?'':`(${dd(t.did)})`}</span>
 <span class="badge">${t.dur} min</span>
 <audio controls preload="none" src="full_${t.key}.wav"></audio></div>`).join("");
document.getElementById("rows").innerHTML=D.groups.map(g=>`<div class="row"><div class="t">${g.ch}. "${g.text}"${g.narr?' <span class="sub">(narrator — same in all)</span>':''}</div>
 ${g.narr?`<div class="mini"><span class="k">narrator</span><audio controls preload="none" src="${g.takes[0].wav}"></audio></div>`
   :g.takes.map(t=>`<div class="mini"><span class="k">${t.key}</span><audio controls preload="none" src="${t.wav}"></audio></div>`).join("")}
 </div>`).join("");
document.getElementById("picks").innerHTML=D.tiers.map((t,i)=>`<span class="pick" data-k="${t.key}">${String.fromCharCode(65+i)}. ${t.label}</span>`).join("");
function paint(){document.querySelectorAll(".pick").forEach(el=>el.classList.toggle("on",el.dataset.k===choice));
  document.getElementById("cnt").textContent=(choice?`choice: ${choice}`:"no choice yet")+` · ${Object.keys(nt).length} note(s)`;}
document.querySelectorAll(".pick").forEach(el=>el.onclick=()=>{choice=el.dataset.k;localStorage.setItem(LC,choice);paint();});
document.querySelectorAll(".note").forEach(el=>{const k=el.dataset.k;if(nt[k])el.value=nt[k];el.classList.toggle("noted",!!nt[k]);
  el.oninput=()=>{const v=el.value.trim();if(v)nt[k]=v;else delete nt[k];localStorage.setItem(LN,JSON.stringify(nt));el.classList.toggle("noted",!!v);paint();};});
document.getElementById("copy").onclick=()=>{const o=document.getElementById("out");o.style.display="block";
  let s="Diary cleaning-tier choice\n\nCHOICE: "+(choice||"(none)")+"\n\nNOTES:\n";
  const ks=Object.keys(nt); s+=ks.length?ks.map(k=>`[${k}] ${nt[k]}`).join("\n"):"(none)";
  o.value=s;o.select();document.execCommand("copy");document.getElementById("copy").textContent="✓ copied";};
paint();
</script></body></html>
"""


if __name__ == "__main__":
    main()
