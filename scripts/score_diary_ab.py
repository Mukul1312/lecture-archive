"""
score_diary_ab.py — read the A/B/C diary clips and answer: does the CALM reference / style instruction
make the batch CALMER while HOLDING identity? Pull the pod output to data/out/lecture1/diary_ab/ first.

Per clip {arm}__{label}__s{seed}.wav it measures identity (ECAPA cosine to his centroid) + the calmness
knobs (pitch/range/loud/rate). Graveness is z-scored WITHIN each sentence across arms+seeds, so the arms
compete fairly on the same words. Then per-ARM: mean identity + mean graveness.

Decision rule (matches the plan): the winning arm is the CALMEST (highest graveness) that still holds
ECAPA >= ~0.74. Also builds voice_lab/diary_ab/ to listen A vs B vs C side by side.

Run:  .venv/Scripts/python.exe scripts/score_diary_ab.py
"""
import json, re, shutil, sys
from collections import defaultdict
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_graveness as bg           # feats(): f0/spread/loud/rate/dur
import gate_takes as gt                # ecapa_centroid()

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/lecture1/diary_ab"
OUT = ROOT / "voice_lab" / "diary_ab"
AUD = OUT / "audio"
ARMS = {"A": "current (Ultimate, max-id ref 0081)", "B": "calm ref 0001 (no instruction)",
        "C": "calm ref 0001 + (calm...) instruction"}
sys.stdout.reconfigure(encoding="utf-8")


def load16k(p):
    y, s = sf.read(str(p), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    if s != 16000:
        g = gcd(s, 16000)
        y = resample_poly(y, 16000 // g, s // g).astype("float32")
    return y


def main():
    if not SRC.exists() or not list(SRC.glob("*.wav")):
        sys.exit(f"no clips in {SRC} — pull the pod's /workspace/out_diary_ab/ there first "
                 f"(scp -r ...:/workspace/out_diary_ab/ {SRC})")
    print("[ecapa] centroid ...")
    embed, ref, ceil, cos = gt.ecapa_centroid()      # embed() already resamples to 16k internally

    pat = re.compile(r"(?P<arm>[ABC])__(?P<label>\w+?)__s(?P<seed>\d+)\.wav")
    rows = []
    for p in sorted(SRC.glob("*.wav")):
        m = pat.match(p.name)
        if not m:
            continue
        f = bg.feats(p)
        rows.append(dict(arm=m["arm"], label=m["label"], seed=int(m["seed"]),
                         wav=p.name, ecapa=round(cos(embed(p), ref), 3), **f))
    print(f"[load] {len(rows)} clips · his ceiling {ceil:.3f}\n")

    # z-score calmness WITHIN each sentence (across arms+seeds) so arms compete on the same words
    for k in ("f0", "spread", "loud", "rate"):
        by = defaultdict(list)
        for r in rows:
            by[r["label"]].append(r[k])
        mean = {lab: float(np.mean(v)) for lab, v in by.items()}
        devs = [r[k] - mean[r["label"]] for r in rows]
        sd = float(np.std(devs)) or 1.0
        for r, d in zip(rows, devs):
            r[f"z_{k}"] = d / sd
    for r in rows:
        r["grave"] = -(r["z_f0"] + r["z_spread"] + r["z_loud"] + r["z_rate"]) / 4

    print(f"=== per-ARM: identity vs calmness (n={len(rows)//3 if rows else 0} lines x seeds each) ===")
    print(f"{'arm':<4} {'identity(ECAPA)':>16} {'graveness':>11} {'pitch':>6} {'loud':>6}  which")
    summary = {}
    for a in "ABC":
        g = [r for r in rows if r["arm"] == a]
        if not g:
            continue
        e = np.array([r["ecapa"] for r in g]); gr = np.array([r["grave"] for r in g])
        summary[a] = (e.mean(), gr.mean())
        print(f"{a:<4} {e.mean():6.3f}±{e.std():.3f}    {gr.mean():+8.3f}   "
              f"{np.mean([r['f0'] for r in g]):6.0f} {np.mean([r['loud'] for r in g]):6.1f}  {ARMS[a]}")

    if summary:
        ok = {a: (e, gr) for a, (e, gr) in summary.items() if e >= 0.74}
        print("\n=== VERDICT ===")
        if ok:
            win = max(ok, key=lambda a: ok[a][1])
            print(f"  Calmest arm holding ECAPA>=0.74: **{win}** ({ARMS[win]}) — "
                  f"graveness {summary[win][1]:+.3f}, identity {summary[win][0]:.3f}")
        else:
            print("  No arm holds ECAPA>=0.74 — identity dropped too far; reconsider reference/mode.")
        if "A" in summary and ("C" in summary or "B" in summary):
            best_new = max([a for a in ("B", "C") if a in summary], key=lambda a: summary[a][1])
            dG = summary[best_new][1] - summary["A"][1]
            dE = summary[best_new][0] - summary["A"][0]
            print(f"  {best_new} vs A: graveness {dG:+.3f} (calmer if +), identity {dE:+.3f} (cost if -). "
                  f"{'CALM REFERENCE WORKS' if dG > 0.15 and summary[best_new][0] >= 0.74 else 'inconclusive — judge by ear'}.")

    # gallery: A/B/C side by side per line
    if OUT.exists():
        shutil.rmtree(OUT)
    AUD.mkdir(parents=True, exist_ok=True)
    for r in rows:
        shutil.copyfile(SRC / r["wav"], AUD / r["wav"])
    groups = []
    for lab in sorted({r["label"] for r in rows}):
        takes = sorted([r for r in rows if r["label"] == lab], key=lambda r: (r["arm"], r["seed"]))
        groups.append(dict(label=lab, takes=[dict(arm=r["arm"], seed=r["seed"], wav=f"audio/{r['wav']}",
                     grave=round(r["grave"], 2), ecapa=r["ecapa"], f0=round(r["f0"]), loud=round(r["loud"], 1))
                     for r in takes]))
    (OUT / "index.html").write_text(TEMPLATE.replace("/*__DATA__*/", json.dumps(
        dict(arms=ARMS, groups=groups), ensure_ascii=False)), encoding="utf-8")
    print(f"\nwrote {OUT/'index.html'} — listen A vs B vs C per line (the ear is the final judge on calm-vs-class)")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Diary A/B/C — calm reference test</title>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--a:#e5675b;--b:#5cc8ff;--c:#7cff9c;}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:960px;margin:0 auto;padding:22px 16px 80px}h1{font-size:20px;margin:0 0 4px}
 .sub{color:var(--mut);margin:0 0 16px;max-width:760px}.item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
 .lab{font-size:12px;color:var(--mut);margin:0 0 8px;text-transform:uppercase;letter-spacing:.05em}
 table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);font-size:12.5px}
 th{color:var(--mut)} .A{color:var(--a)}.B{color:var(--b)}.C{color:var(--c)} audio{height:30px;width:190px} .g{font-weight:700}
</style></head><body><div class="wrap">
 <h1>🌙 Diary A/B/C — does the calm reference work?</h1>
 <p class="sub"><b class="A">A</b> current (Ultimate, max-id ref) · <b class="B">B</b> calm ref, no instruction · <b class="C">C</b> calm ref + "(calm…)" instruction. Listen per line: is B/C calmer & intimate <i>while still him</i>? graveness ↑ = calmer.</p>
 <div id="list"></div></div>
<script>
const D=/*__DATA__*/;
document.getElementById("list").innerHTML=D.groups.map(g=>`
 <div class="item"><div class="lab">${g.label}</div>
 <table><tr><th>arm</th><th>seed</th><th>graveness</th><th>pitch</th><th>loud</th><th>identity</th><th>listen</th></tr>
 ${g.takes.map(t=>`<tr><td class="${t.arm} g">${t.arm}</td><td>${t.seed}</td><td class="g">${t.grave>=0?'+':''}${t.grave}</td>
   <td>${t.f0}</td><td>${t.loud}</td><td>${t.ecapa}</td>
   <td><audio controls preload="none" src="${t.wav}"></audio></td></tr>`).join("")}
 </table></div>`).join("");
</script></body></html>
"""

if __name__ == "__main__":
    main()
