"""
find_calm_ref.py — pick GGSM's calmest, most-intimate real clip to use as the VoxCPM reference prompt.

The reference clip is the #1 lever on mood: the clone inherits the prompt's register. We're currently
prompting with the Namabhasa *lecture* clip (ggs_l1_0112) — that's why "class tone" leaks in. This
ranks his 140 real clips on the calmness recipe (LOW pitch · NARROW range · QUIET · SLOW), z-scored
ACROSS clips (not within a sentence), with guards so the pick is still a good reference:
  - duration 4–12s (VoxCPM prompt sweet spot)
  - English-dominant text (prompt teaches English phonetics; transcript becomes prompt_text)
  - identity not an outlier-low (ECAPA to his centroid — the ref must clearly be him)

Output: a printed shortlist + voice_lab/calm_ref/ gallery so you make the final calm-vs-slow-lecture
call by ear. Run:  .venv/Scripts/python.exe scripts/find_calm_ref.py
"""
import json, re, shutil, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_graveness as bg          # feats() = f0/spread/loud/rate/dur
import gate_takes as gt               # ecapa_centroid()

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data/out/lecture1/final"
CLIPS = FINAL / "clips"
OUT = ROOT / "voice_lab" / "calm_ref"
AUD = OUT / "audio"
CUR_REF = "ggs_l1_0112"               # the lecture clip we want to replace
sys.stdout.reconfigure(encoding="utf-8")


def main():
    eng = set((ROOT / "data/english_words.txt").read_text(encoding="utf-8").split())
    tok = re.compile(r"[a-z']+")

    def ef(t):
        w = tok.findall(t.lower())
        return (sum(1 for x in w if x in eng) / len(w)) if w else 0.0

    rows = [json.loads(l) for l in (FINAL / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"[load] {len(rows)} real clips")
    print("[ecapa] building his identity centroid ...")
    embed, ref, ceil, cos = gt.ecapa_centroid()

    cand = []
    for r in rows:
        stem = Path(r["audio"]).stem
        p = CLIPS / Path(r["audio"]).name
        if not p.exists() or stem == CUR_REF:
            continue
        dur = float(r.get("duration", 0))
        if not (4.0 <= dur <= 12.0) or ef(r["text"]) < 0.85:      # good ref shape + English
            continue
        f = bg.feats(p)
        cand.append(dict(stem=stem, name=p.name, text=r["text"].strip(),
                         ecapa=round(cos(embed(p), ref), 3), **f))
    print(f"[filter] {len(cand)} clips pass (4–12s, English-dominant)")

    # z-score the calmness knobs ACROSS clips; identity guard = drop bottom-quartile "him"
    for k in ("f0", "spread", "loud", "rate"):
        v = np.array([c[k] for c in cand], float)
        mu, sd = v.mean(), (v.std() or 1.0)
        for c in cand:
            c[f"z_{k}"] = (c[k] - mu) / sd
    id_floor = float(np.percentile([c["ecapa"] for c in cand], 25))
    for c in cand:
        c["calm"] = round(-(c["z_f0"] + c["z_spread"] + c["z_loud"] + c["z_rate"]) / 4, 3)
        c["weak_id"] = c["ecapa"] < id_floor

    ranked = sorted(cand, key=lambda c: -c["calm"])
    strong = [c for c in ranked if not c["weak_id"]]

    print(f"\n=== CALMEST clips (higher = calmer; identity floor {id_floor:.2f}, his ceiling {ceil:.2f}) ===")
    print(f"{'rank':>4} {'clip':<14} {'calm':>6} {'pitch':>6} {'range':>6} {'loud':>6} {'rate':>5} {'ident':>6}  text")
    for i, c in enumerate(ranked[:15], 1):
        flag = "  ⚠weak-id" if c["weak_id"] else ""
        print(f"{i:>4} {c['stem']:<14} {c['calm']:+.2f} {c['f0']:6.0f} {c['spread']:6.0f} "
              f"{c['loud']:6.1f} {c['rate']:5.1f} {c['ecapa']:6.2f}  \"{c['text'][:44]}\"{flag}")
    top = strong[0]
    print(f"\n[pick] calmest strong-identity clip: {top['stem']}  (calm {top['calm']:+.2f}, ident {top['ecapa']:.2f})")
    print(f"       prompt_text -> \"{top['text']}\"")

    # gallery: top 12 strong-identity, calm-first, to audition calm-vs-slow-lecture by ear
    if OUT.exists():
        shutil.rmtree(OUT)
    AUD.mkdir(parents=True, exist_ok=True)
    gal = []
    for c in strong[:12]:
        shutil.copyfile(CLIPS / c["name"], AUD / c["name"])
        gal.append(dict(stem=c["stem"], wav=f"audio/{c['name']}", text=c["text"], calm=c["calm"],
                        f0=round(c["f0"]), spread=round(c["spread"]), loud=round(c["loud"], 1),
                        rate=round(c["rate"], 1), ecapa=c["ecapa"]))
    (OUT / "index.html").write_text(TEMPLATE.replace("/*__DATA__*/", json.dumps(gal, ensure_ascii=False)), encoding="utf-8")
    print(f"\nwrote {OUT/'index.html'}  — listen, pick the one that sounds calm & intimate (not slow-lecture)")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Calmest reference clip</title>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--g:#7c9cff;}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:900px;margin:0 auto;padding:22px 16px 80px}h1{font-size:20px;margin:0 0 4px}
 .sub{color:var(--mut);margin:0 0 16px;max-width:720px}
 .item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 10px}
 .item.top{border-color:var(--g)} .r{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
 .calm{font-weight:800;color:var(--g);font-size:16px;min-width:56px} .stem{color:var(--mut);font-size:12px}
 .txt{margin:6px 0 0;font-size:13.5px} .m{color:var(--mut);font-size:12px} audio{height:32px}
 .badge{font-size:10px;background:var(--g);color:#0f1115;border-radius:10px;padding:1px 7px;font-weight:800}
</style></head><body><div class="wrap">
 <h1>🌙 Calmest reference clip — pick the diary voice</h1>
 <p class="sub">His real clips ranked <b>calmest-first</b> (low pitch · narrow range · quiet · slow, across clips). The one you pick becomes the VoxCPM <b>reference prompt</b> — it biases every generated take toward that mood. <b>Listen for calm &amp; intimate</b> (a man alone at night), not slow-lecture. The meter narrows; your ear decides.</p>
 <div id="list"></div></div>
<script>
const D=/*__DATA__*/;
document.getElementById("list").innerHTML=D.map((c,i)=>`
 <div class="item${i===0?' top':''}">
  <div class="r"><span class="calm">${c.calm>=0?'+':''}${c.calm}</span>
   <audio controls preload="none" src="${c.wav}"></audio>
   <span class="stem">${c.stem}${i===0?' <span class="badge">calmest</span>':''}</span></div>
  <div class="txt">“${c.text}”</div>
  <div class="m">pitch ${c.f0}Hz · range ${c.spread} · loud ${c.loud}dB · rate ${c.rate}/s · identity ${c.ecapa}</div>
 </div>`).join("");
</script></body></html>
"""

if __name__ == "__main__":
    main()
