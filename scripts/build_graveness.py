"""
build_graveness.py — turn "seed 123 feels grave" into a measurement.

Research recipe for a grave/solemn tone (Scherer 2003; eGeMAPS): LOW mean pitch, NARROW pitch range,
LOW loudness, SLOW rate. This scores every pre-test take on those four prosodic knobs, centres each
feature WITHIN its sentence (so we compare the 5 seeds fairly, not different words), and ranks takes by
a combined "graveness" score. Then it checks whether seed 123 is systematically the gravest.

Output -> voice_lab/graveness/ (servable) + a printed per-seed summary.
Run: .venv/Scripts/python.exe scripts/build_graveness.py
"""
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import parselmouth

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/out/lecture1/pretest"
OUT = ROOT / "voice_lab" / "graveness"
AUD = OUT / "audio"

LABELS = {
    "date": "the spoken date", "vow": "mahā-water, Tulasī", "iskcon": "ISKCON, Odisha",
    "prema": "kṛṣṇa-prema", "prasadam": "Prasādam", "lila": "līlā",
    "sannyasi": "sannyāsī", "gopala": "Gopāla", "gauranga": "Śrī Śrī, Gaurāṅga, Hare Kṛṣṇa",
}


def feats(wav):
    snd = parselmouth.Sound(str(wav))
    dur = snd.get_total_duration()
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=75, pitch_ceiling=300)
    f0 = pitch.selected_array["frequency"]
    f0 = f0[f0 > 0]
    f0_med = float(np.median(f0)) if len(f0) else 0.0      # pitch height (robust)
    f0_spread = float(np.std(f0)) if len(f0) else 0.0      # pitch range
    inten = snd.to_intensity()
    xs, vals = inten.xs(), inten.values[0]
    ok = np.isfinite(vals)
    xs, vals = xs[ok], vals[ok]
    loud = float(np.mean(vals)) if len(vals) else 0.0      # loudness (dB)
    # rate proxy: syllable nuclei = intensity peaks above (peak-20 dB), min 120 ms apart
    thr = (vals.max() - 20) if len(vals) else 0.0
    peaks = []
    for i in range(1, len(vals) - 1):
        if vals[i] > vals[i - 1] and vals[i] >= vals[i + 1] and vals[i] > thr:
            if not peaks or (xs[i] - xs[peaks[-1]]) > 0.12:
                peaks.append(i)
    rate = (len(peaks) / dur) if dur > 0 else 0.0          # syllables/sec (approx)
    return dict(f0=f0_med, spread=f0_spread, loud=loud, rate=rate, dur=dur)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    AUD.mkdir(parents=True, exist_ok=True)

    pat = re.compile(r"(?P<label>\w+)__s(?P<seed>\d+)\.wav")
    rows = []
    for p in sorted(SRC.glob("*.wav")):
        m = pat.match(p.name)
        if not m:
            continue
        f = feats(p)
        shutil.copyfile(p, AUD / p.name)
        rows.append(dict(label=m["label"], seed=int(m["seed"]), wav=f"audio/{p.name}", **f))

    # centre each feature WITHIN its sentence (remove content confound), then z-scale globally
    for key in ("f0", "spread", "loud", "rate"):
        by_sent = defaultdict(list)
        for r in rows:
            by_sent[r["label"]].append(r[key])
        means = {s: float(np.mean(v)) for s, v in by_sent.items()}
        devs = [r[key] - means[r["label"]] for r in rows]
        sd = float(np.std(devs)) or 1.0
        for r, d in zip(rows, devs):
            r[f"z_{key}"] = d / sd
    # graveness = lower pitch + narrower range + quieter + slower  ->  higher score
    for r in rows:
        r["grave"] = round(-(r["z_f0"] + r["z_spread"] + r["z_loud"] + r["z_rate"]) / 4, 3)

    # per-seed average graveness (is seed 123 systematically gravest?)
    seed_g = defaultdict(list)
    for r in rows:
        seed_g[r["seed"]].append(r["grave"])
    seed_rank = sorted(((round(float(np.mean(v)), 3), s) for s, v in seed_g.items()), reverse=True)
    print("\n=== per-seed average graveness (higher = graver; centred within sentence) ===")
    for g, s in seed_rank:
        star = "  <-- your pick" if s == 123 else ""
        print(f"  seed {s:<5} {g:+.3f}{star}")
    won = sum(1 for lab in LABELS if (grp := [r for r in rows if r["label"] == lab])
              and max(grp, key=lambda r: r["grave"])["seed"] == 123)
    print(f"\nseed 123 is the gravest take in {won}/{len(LABELS)} sentences.")

    # group for the gallery, sorted gravest-first within each sentence
    groups = []
    for lab in LABELS:
        g = sorted([r for r in rows if r["label"] == lab], key=lambda r: -r["grave"])
        if g:
            groups.append(dict(label=lab, terms=LABELS[lab], takes=[
                dict(seed=r["seed"], wav=r["wav"], grave=r["grave"],
                     f0=round(r["f0"]), spread=round(r["spread"]), loud=round(r["loud"], 1),
                     rate=round(r["rate"], 1)) for r in g]))
    data = dict(groups=groups, seedRank=[{"seed": s, "grave": g} for g, s in seed_rank])
    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"\nwrote {OUT / 'index.html'}")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Graveness meter</title>
<style>
  :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--g:#7c9cff;--pick:#ffb84a;}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:900px;margin:0 auto;padding:22px 16px 80px}
  h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 14px;max-width:720px}
  .sum{background:var(--card);border:1px solid var(--g);border-radius:12px;padding:12px 14px;margin:0 0 16px}
  .sum b{color:var(--ink)} .seedbar{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:13px}
  .seedbar .n{width:70px;color:var(--mut)} .seedbar .bar{height:12px;border-radius:3px;background:var(--g)}
  .seedbar.pick .n{color:var(--pick);font-weight:700}.seedbar.pick .bar{background:var(--pick)}
  .item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
  .term{font-size:12px;color:var(--mut);margin:0 0 8px} .term b{color:var(--ink)}
  table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);font-size:12.5px}
  th{color:var(--mut);font-weight:600} tr.top td{background:#16302a}
  tr.pick td{outline:1px solid var(--pick)} .badge{font-size:10px;background:var(--pick);color:#0f1115;border-radius:10px;padding:1px 6px;font-weight:700}
  .gv{font-weight:700} audio{width:170px;height:30px;vertical-align:middle}
</style></head><body><div class="wrap">
  <h1>📉 Graveness meter — measuring the mood, not guessing it</h1>
  <p class="sub">Each take scored on the research recipe for a solemn tone — <b>low pitch · narrow pitch-range · quiet · slow</b> — centred within each sentence so the 5 seeds compete fairly. Higher <b class="gv">graveness</b> = graver. Rows are sorted gravest-first; <span class="badge">123</span> is your pick.</p>
  <div class="sum" id="sum"></div>
  <div id="list"></div>
</div>
<script>
const DATA = /*__DATA__*/;
const maxg = Math.max(...DATA.seedRank.map(s=>Math.abs(s.grave)),0.3);
document.getElementById("sum").innerHTML = `<b>Which seed is gravest, on average?</b> (centred within sentence, so it's the seed's own tendency)`+
  DATA.seedRank.map(s=>{const w=Math.round((s.grave/maxg)*46+50);
    return `<div class="seedbar${s.seed===123?' pick':''}"><span class="n">seed ${s.seed}</span><span class="bar" style="width:${Math.max(6,w+ (s.grave<0?-40:0))}px"></span><span>${s.grave>=0?'+':''}${s.grave.toFixed(3)}</span></div>`;}).join("");
document.getElementById("list").innerHTML = DATA.groups.map(g=>`
  <div class="item">
    <div class="term">▶ ${g.label} · <b>${g.terms}</b></div>
    <table>
      <tr><th>#</th><th>seed</th><th>graveness</th><th>pitch Hz</th><th>range</th><th>loud dB</th><th>rate</th><th>listen</th></tr>
      ${g.takes.map((t,i)=>`<tr class="${i===0?'top':''} ${t.seed===123?'pick':''}">
        <td>${i+1}</td><td>${t.seed}${t.seed===123?' <span class="badge">pick</span>':''}</td>
        <td class="gv">${t.grave>=0?'+':''}${t.grave}</td>
        <td>${t.f0}</td><td>${t.spread}</td><td>${t.loud}</td><td>${t.rate}</td>
        <td><audio controls preload="none" src="${t.wav}"></audio></td></tr>`).join("")}
    </table>
  </div>`).join("");
</script></body></html>
"""

if __name__ == "__main__":
    main()
