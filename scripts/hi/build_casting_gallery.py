"""
build_casting_gallery.py — the listening page for choosing the non-GGSM narrator.

Why this exists: measurement can rule voices OUT (too close to GGSM, pitch too high for "mature
man") but cannot rule one IN. "Sweet and prayerful" is a judgement for project reviewers, so
this page presents only the candidates that PASSED screening and gets out of the way.

Each candidate is one SEED — measured to be what actually selects the speaker (same-seed/different-
description = 0.573 similarity; same-description/different-seed = 0.188, i.e. indistinguishable
from unrelated voices). Both diary passages are shown per voice so a candidate is judged on a short
prayerful line AND a longer narrative one.

  .venv/Scripts/python.exe scripts/hi/build_casting_gallery.py
  python -m http.server 8747 -d data/hi      ->  http://localhost:8747/casting_gallery.html
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HI = ROOT / "data/hi"
CLIPS = HI / "out_seeds"
SCREEN = HI / "_seed_screen.json"
OUT = HI / "casting_gallery.html"
PASSAGES = HI / "_audition_passages.json"
sys.stdout.reconfigure(encoding="utf-8")

CSS = """
:root{--bg:#faf9f7;--card:#fff;--ink:#1a1c20;--soft:#5b6069;--mute:#8a9099;--line:#e6e3de;
      --accent:#2f4b7c;--accent-bg:#eef2f8;--good:#2e7d5b}
@media(prefers-color-scheme:dark){:root{--bg:#131519;--card:#1b1e23;--ink:#ecebe8;--soft:#b2b7bf;
      --mute:#848a94;--line:#2c3038;--accent:#93b0dc;--accent-bg:#1d2430;--good:#6fbf97}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:60rem;margin:0 auto;padding:2.5rem 1.25rem 5rem}
h1{font-family:Georgia,serif;font-size:2rem;margin:0 0 .3rem}
.lede{color:var(--soft);margin:0 0 2rem;max-width:60ch}
.passage{background:var(--accent-bg);border-left:3px solid var(--accent);padding:.9rem 1.1rem;
         border-radius:2px;margin:0 0 2rem}
.passage p{margin:.2rem 0;font-size:.95rem}
.passage .lbl{font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);
              font-weight:600}
.grid{display:flex;flex-direction:column;gap:1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:1.1rem 1.25rem}
.card h2{font-family:Georgia,serif;font-size:1.15rem;margin:0 0 .15rem}
.meta{display:flex;flex-wrap:wrap;gap:.4rem 1.1rem;color:var(--mute);font-size:.82rem;
      margin-bottom:.85rem;font-variant-numeric:tabular-nums}
.meta b{color:var(--soft);font-weight:600}
.rows{display:flex;flex-direction:column;gap:.6rem}
.row{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}
.tag{font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);
     min-width:6.5rem;font-weight:600}
audio{flex:1;min-width:15rem;height:34px}
.pill{display:inline-block;font-size:.68rem;font-weight:650;padding:.1rem .45rem;border-radius:2px;
      background:var(--accent-bg);color:var(--accent)}
footer{margin-top:2.5rem;padding-top:1.2rem;border-top:1px solid var(--line);
       color:var(--mute);font-size:.82rem}
"""


def main():
    if not SCREEN.exists():
        sys.exit(f"missing {SCREEN} — run the seed screen first")
    screen = {s["voice"]: s for s in json.loads(SCREEN.read_text(encoding="utf-8"))}
    kept = [v for v, s in screen.items() if s["keep"]]
    if not kept:
        sys.exit("no candidates passed screening")

    passages = json.loads(PASSAGES.read_text(encoding="utf-8")) if PASSAGES.exists() else {}
    by_voice = defaultdict(dict)
    for p in sorted(CLIPS.glob("*.wav")):
        tag, seed, pid = p.stem.split("__")
        by_voice[f"{tag}__{seed}"][pid] = p.name

    # Lowest pitch first — closest to the "mature, grave" end of the brief.
    kept.sort(key=lambda v: screen[v]["f0"])

    h = [f"<style>{CSS}</style>", '<div class="wrap">']
    h.append("<h1>Choose the narrator</h1>")
    h.append('<p class="lede">Each card is one candidate voice. They all passed screening: '
             "confirmed <b>not</b> to resemble Gour Govinda Swami, and within a mature male pitch "
             "range. Which one is right is a judgement of the ear — listen for whether it sounds "
             "<i>sweet and prayerful</i>, and whether you could hear it narrate every episode.</p>")

    if passages:
        h.append('<div class="passage"><p class="lbl">The two passages (1975 diary)</p>')
        for pid, txt in passages.items():
            h.append(f"<p><b>{pid}</b> — {txt}</p>")
        h.append("</div>")

    h.append('<div class="grid">')
    for i, v in enumerate(kept, 1):
        s = screen[v]
        h.append('<div class="card">')
        h.append(f'<h2>Voice {i} <span class="pill">{v}</span></h2>')
        h.append(f'<div class="meta"><span><b>pitch</b> {s["f0"]:.0f} Hz</span>'
                 f'<span><b>similarity to GGSM</b> {s["ggsm"]:.3f} '
                 f'<span style="color:var(--good)">(his own level is 0.694 — far below)</span></span></div>')
        h.append('<div class="rows">')
        for pid in sorted(by_voice[v]):
            label = "short / prayerful" if pid == "p01" else "longer / narrative"
            h.append(f'<div class="row"><span class="tag">{label}</span>'
                     f'<audio controls preload="none" src="out_seeds/{by_voice[v][pid]}"></audio></div>')
        h.append("</div></div>")
    h.append("</div>")
    h.append(f'<footer>{len(kept)} candidates passed of {len(screen)} generated. '
             "Each candidate is a fixed seed — measured to be what selects the speaker. "
             "Whichever you choose gets frozen as a reference clip and cloned for every future "
             "episode, which is what keeps the narrator identical across the series.</footer>")
    h.append("</div>")

    OUT.write_text("\n".join(h), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(kept)} candidates)")
    print("serve:  python -m http.server 8747 -d data/hi")
    print("open :  http://localhost:8747/casting_gallery.html")


if __name__ == "__main__":
    main()
