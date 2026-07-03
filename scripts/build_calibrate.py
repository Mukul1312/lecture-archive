"""
build_calibrate.py — Stage-0 ear-calibration probe. Turns the "is calm the right target?" question
into a measurable test: does S_breathy explain your ear beyond S_arousal?

What it does:
  1. Compute the decomposed feature vector over his 140 lecture-1 clips (HAVE prosody + NEW voice-quality),
     z-scored across the pool, into three provisional sub-scores:
        S_arousal (higher = calmer)   = -(z_f0 + z_rate + z_loud)/3
        S_breathy (higher = breathier) = (z_h1h2 - z_cpps - z_hnr)/3      # Garellek: tilt up + periodicity down
        S_gravity (higher = graver)    = -(z_f0 + z_spread)/2
  2. STRATIFY a ~36-clip labeling sample: a spread across the S_arousal range PLUS, within matched arousal,
     the extreme-breathy and extreme-modal clips — so arousal and breathiness are NOT collinear and your
     labels can separate them.
  3. Build a BLIND rating gallery (random order, no scores shown) where you rate each clip 1-5 on
     "private night-prayer <-> public lecture" + tags, and EXPORT labels.json.

Then scripts/score_calibrate.py regresses your labels on the sub-scores and reports whether adding
S_breathy improves the fit over arousal-alone (the go/no-go for engineering breathiness).

Features are cached to data/out/lecture1/calibrate/features.json (re-run instant; --recompute to refresh).
Run: .venv/Scripts/python.exe scripts/build_calibrate.py
"""
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_graveness import feats as prosody_feats     # f0, spread, loud, rate
from voice_quality import vq_feats                       # cpps, hnr, alpha_std, hammarberg, h1h2

CLIPS = ROOT / "data/out/lecture1/final/clips"
OUTD = ROOT / "data/out/lecture1/calibrate"
FEAT = OUTD / "features.json"
GAL = ROOT / "voice_lab" / "calibrate"
AUD = GAL / "audio"
N_LABEL = 36
FKEYS = ["f0", "spread", "loud", "rate", "cpps", "hnr", "alpha_std", "hammarberg", "h1h2"]


def compute_features(recompute=False):
    if FEAT.exists() and not recompute:
        return json.loads(FEAT.read_text(encoding="utf-8"))
    OUTD.mkdir(parents=True, exist_ok=True)
    rows = []
    names = sorted(p.stem for p in CLIPS.glob("*.wav"))
    for i, n in enumerate(names, 1):
        p = CLIPS / f"{n}.wav"
        g = prosody_feats(p)
        vq = vq_feats(p)
        rows.append(dict(clip=n, f0=g["f0"], spread=g["spread"], loud=g["loud"], rate=g["rate"],
                         cpps=vq["cpps"], hnr=vq["hnr"], alpha_std=vq["alpha_std"],
                         hammarberg=vq["hammarberg"], h1h2=vq["h1h2"]))
        if i % 20 == 0:
            print(f"  features {i}/{len(names)}", file=sys.stderr)
    FEAT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"cached features -> {FEAT}")
    return rows


def zscore(rows):
    """Add z_<feat> across the pool (NaN-safe: impute missing to the pool mean -> z=0)."""
    for k in FKEYS:
        v = np.array([r[k] for r in rows], dtype=float)
        m = np.nanmean(v)
        s = np.nanstd(v) or 1.0
        for r in rows:
            x = r[k]
            r[f"z_{k}"] = 0.0 if (x is None or not np.isfinite(x)) else (x - m) / s
    for r in rows:
        r["S_arousal"] = round(-(r["z_f0"] + r["z_rate"] + r["z_loud"]) / 3, 3)      # higher = calmer
        r["S_breathy"] = round((r["z_h1h2"] - r["z_cpps"] - r["z_hnr"]) / 3, 3)       # higher = breathier
        r["S_gravity"] = round(-(r["z_f0"] + r["z_spread"]) / 2, 3)                    # higher = graver
    return rows


def stratified_sample(rows, n=N_LABEL, seed=1337):
    """Sample a 3x3 (S_arousal tercile x S_breathy tercile) grid so breathiness is spread AT EACH
    arousal level -> the two dimensions decorrelate in the labeling set and your labels can separate
    their effects. (In his voice calm~breathy naturally co-vary, so this is deliberate.)"""
    rng = random.Random(seed)
    aq = np.quantile([r["S_arousal"] for r in rows], [1 / 3, 2 / 3])
    bq = np.quantile([r["S_breathy"] for r in rows], [1 / 3, 2 / 3])
    terc = lambda x, q: 0 if x < q[0] else (1 if x < q[1] else 2)
    cells = {}
    for r in rows:
        cells.setdefault((terc(r["S_arousal"], aq), terc(r["S_breathy"], bq)), []).append(r)
    print("  arousal x breathy 3x3 cell counts (a,b):",
          {f"{a}{b}": len(cells.get((a, b), [])) for a in range(3) for b in range(3)})
    per = max(1, round(n / 9))
    chosen, ids = [], set()
    for v in cells.values():
        vv = v[:]
        rng.shuffle(vv)
        for r in vv[:per]:
            chosen.append(r)
            ids.add(r["clip"])
    if len(chosen) < n:                     # backfill preferring off-diagonal (arousal & breathy disagree)
        rest = sorted((r for r in rows if r["clip"] not in ids),
                      key=lambda r: -abs(r["S_arousal"] - r["S_breathy"]))
        chosen += rest[:n - len(chosen)]
    rng.shuffle(chosen)                      # BLIND presentation order
    return chosen


def build_gallery(sample):
    if GAL.exists():
        shutil.rmtree(GAL)
    AUD.mkdir(parents=True, exist_ok=True)
    items = []
    for i, r in enumerate(sample, 1):
        src = CLIPS / f"{r['clip']}.wav"
        shutil.copyfile(src, AUD / f"c{i:02d}.wav")     # neutral display name (blind)
        items.append(dict(n=i, clip=r["clip"], url=f"audio/c{i:02d}.wav"))
    (GAL / "index.html").write_text(
        TEMPLATE.replace("/*__DATA__*/", json.dumps(items, ensure_ascii=False)), encoding="utf-8")
    print(f"wrote {GAL/'index.html'}  ({len(items)} clips to label)")


def main():
    rows = zscore(compute_features(recompute="--recompute" in sys.argv))
    sample = stratified_sample(rows)
    # honest read of the sample design: are arousal & breathy actually decorrelated in the sample?
    a = np.array([r["S_arousal"] for r in sample]); b = np.array([r["S_breathy"] for r in sample])
    corr = float(np.corrcoef(a, b)[0, 1]); vif = 1.0 / max(1e-6, 1 - corr ** 2)
    print(f"\nsample: {len(sample)} clips | S_arousal x S_breathy corr {corr:+.2f}  (VIF {vif:.1f}) "
          f"{'-> OK, effects are separable' if vif < 2.5 else '-> still collinear; interpret weights cautiously'}")
    build_gallery(sample)
    print("\nNEXT: open http://localhost:8000/calibrate/ , rate all clips, click Export -> save as")
    print("      data/out/lecture1/calibrate/labels.json , then run scripts/score_calibrate.py")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ear calibration — private prayer vs lecture</title>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--pick:#46c08a;--warn:#ff9d4a}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:780px;margin:0 auto;padding:20px 16px 120px}
 h1{font-size:19px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 14px}
 .clip{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
 .clip.done{border-color:var(--pick)}
 .hd{display:flex;gap:10px;align-items:center}.hd .n{color:var(--mut);font-family:ui-monospace,monospace;font-size:12px;width:32px}
 audio{flex:1;height:36px}
 .rate{display:flex;gap:6px;margin:10px 0 6px;align-items:center;flex-wrap:wrap}
 .rate .lab{font-size:12px;color:var(--mut);width:100%}
 .rate button{cursor:pointer;border:1px solid var(--line);background:#11141b;color:var(--ink);border-radius:8px;padding:6px 12px;font:inherit;font-weight:700}
 .rate button.on{background:var(--pick);color:#0f1115;border-color:var(--pick)}
 .tags{display:flex;gap:6px;flex-wrap:wrap}
 .tags button{cursor:pointer;border:1px solid var(--line);background:#11141b;color:var(--mut);border-radius:20px;padding:3px 10px;font:inherit;font-size:12px}
 .tags button.on{background:#2a3550;color:var(--ink);border-color:#5a7}
 .bar{position:fixed;left:0;right:0;bottom:0;background:#0c0e13;border-top:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;align-items:center;justify-content:center}
 .bar .prog{color:var(--mut);font-size:13px}.bar button{cursor:pointer;border:0;border-radius:8px;padding:8px 16px;font-weight:700}
 #exp{background:var(--pick);color:#0f1115}#exp:disabled{background:#2a2e38;color:var(--mut);cursor:not-allowed}
 .scale{font-size:11.5px;color:var(--mut)}
</style></head><body><div class="wrap">
 <h1>&#127911; Ear calibration &mdash; is it *prayer* or just *quiet*?</h1>
 <p class="sub">Rate each clip <b>blind</b> (no scores shown): does it sound like <b>GGS reading a private prayer in his diary at night</b> (5), or <b>preaching to a hall</b> (1)? Then tag what you hear. This teaches the machine which acoustic dimension your ear is actually using &mdash; especially whether <i>breathy/tender</i> matters beyond merely <i>quiet/slow</i>. Rate all, then <b>Export</b>.</p>
 <p class="scale"><b>1</b> = full public lecture &middot; <b>2</b> &middot; <b>3</b> = neutral/measured &middot; <b>4</b> &middot; <b>5</b> = intimate private prayer. Tags: <b>tender</b>, <b>hushed/breathy</b>, <b>flat/bored</b> (calm but hollow &mdash; the failure mode), <b>pressed/loud</b>.</p>
 <div id="list"></div>
</div>
<div class="bar"><span class="prog" id="prog"></span><button id="exp" disabled>Export labels.json</button></div>
<script>
const D=/*__DATA__*/;const L={};
const TAGS=["tender","hushed/breathy","flat/bored","pressed/loud"];
const list=document.getElementById("list"), prog=document.getElementById("prog"), exp=document.getElementById("exp");
function upd(){const done=Object.values(L).filter(x=>x.rating).length;
  prog.textContent=`${done} / ${D.length} rated`; exp.disabled=done<D.length;}
D.forEach(it=>{L[it.clip]={rating:0,tags:[]};
  const el=document.createElement("div");el.className="clip";el.id="cl"+it.n;
  el.innerHTML=`<div class="hd"><span class="n">#${it.n}</span><audio controls preload="none" src="${it.url}"></audio></div>
   <div class="rate"><span class="lab">lecture 1 &nbsp;&larr;&rarr;&nbsp; 5 private prayer</span>
     ${[1,2,3,4,5].map(v=>`<button data-r="${v}">${v}</button>`).join("")}</div>
   <div class="tags">${TAGS.map(t=>`<button data-t="${t}">${t}</button>`).join("")}</div>`;
  el.querySelectorAll("[data-r]").forEach(b=>b.onclick=()=>{
    L[it.clip].rating=+b.dataset.r; el.querySelectorAll("[data-r]").forEach(x=>x.classList.toggle("on",x===b));
    el.classList.add("done"); upd();});
  el.querySelectorAll("[data-t]").forEach(b=>b.onclick=()=>{
    const t=b.dataset.t, arr=L[it.clip].tags, i=arr.indexOf(t);
    if(i<0){arr.push(t);b.classList.add("on");}else{arr.splice(i,1);b.classList.remove("on");}});
  list.appendChild(el);});
upd();
exp.onclick=()=>{const blob=new Blob([JSON.stringify(L,null,1)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="labels.json";a.click();};
</script></body></html>
"""

if __name__ == "__main__":
    main()
