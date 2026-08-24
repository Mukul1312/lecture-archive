"""
build_casting_site.py — deployable listening site for choosing the non-GGSM narrator.

Distinct from build_casting_gallery.py: that one is a local dev page (loose .wav, needs a server).
This produces a self-contained static site (compressed mp3, relative paths) for sharing with the
seniors who make the actual call — deployable to Vercel or openable from disk.

Design deliberately matches the EXISTING devotee-facing page (site/index.html): same aubergine/gold
palette, Georgia serif, om header, and the same pick-then-send-feedback interaction. Visual
continuity matters more here than novelty — the audience is the same devotees.

Writes to site-casting/ — never touches site/, which holds a tracked deliverable.

  .venv/Scripts/python.exe scripts/hi/build_casting_site.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HI = ROOT / "data/hi"
SRC = HI / "out_seeds"
OUT = ROOT / "site-casting"
AUDIO = OUT / "audio"
sys.stdout.reconfigure(encoding="utf-8")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Choosing the narrator's voice</title>
<style>
 :root{{--bg:#100d13;--card:#1c1720;--line:#312836;--ink:#f1ebf4;--mut:#a99fb3;--gold:#c9a24a;--v:#8f7ad6}}
 *{{box-sizing:border-box}}
 body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 Georgia,'Times New Roman',serif}}
 .wrap{{max-width:720px;margin:0 auto;padding:40px 20px 90px}}
 .top{{text-align:center;margin:0 0 22px}}
 .om{{color:var(--gold);font-size:15px;letter-spacing:.2em;margin:0 0 10px}}
 h1{{font-size:25px;line-height:1.3;margin:0 0 6px;font-weight:600}}
 .sub{{color:var(--mut);font-size:14px;margin:0}}
 .intro{{color:#d8c7a0;font-style:italic;font-size:15px;text-align:center;margin:18px auto 8px;max-width:600px}}
 .ask{{background:#17131c;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:22px 0 18px;
   text-align:center;font-size:15px;font-family:system-ui,Segoe UI,Roboto,sans-serif}}
 .ask b{{color:var(--gold)}}
 h2{{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--mut);margin:32px 0 12px;
   text-align:center;font-family:system-ui}}
 .passage{{background:#17131c;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:0 0 10px}}
 .passage .t{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);
   margin:0 0 6px;font-family:system-ui}}
 .passage p{{margin:0;font-size:15px;color:#d8c7a0}}
 .recs{{display:flex;flex-direction:column;gap:14px}}
 .rec{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}}
 .rec.on{{border-color:var(--gold)}}
 .rec .hd{{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:0 0 12px}}
 .rec .t{{font-size:13px;color:var(--gold);letter-spacing:.14em;text-transform:uppercase;margin:0;
   font-family:system-ui}}
 .rec .id{{font-size:11px;color:var(--mut);font-family:system-ui}}
 .lbl{{font-size:11px;color:var(--mut);font-family:system-ui;margin:0 0 4px;letter-spacing:.06em}}
 audio{{width:100%;height:40px;margin:0 0 10px}}
 audio:last-of-type{{margin-bottom:0}}
 .choose{{margin:30px 0 0;padding:18px;border:1px solid var(--line);border-radius:14px;background:#161219;
   font-family:system-ui,Segoe UI,Roboto,sans-serif}}
 .choose .q{{text-align:center;font-size:15px;margin:0 0 12px}}
 .opts{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin:0 0 12px}}
 .opt{{cursor:pointer;border:1px solid var(--line);background:#221b29;color:var(--ink);border-radius:30px;
   padding:9px 18px;font:14px system-ui}}
 .opt.on{{border-color:var(--gold);background:rgba(201,162,74,.16);color:#fff;font-weight:700}}
 .note{{width:100%;min-height:52px;margin:4px 0 12px;background:#0f0c13;border:1px solid var(--line);
   color:var(--ink);border-radius:10px;padding:9px 11px;font:14px system-ui;resize:vertical}}
 .send{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}}
 .send button{{cursor:pointer;border-radius:10px;padding:11px 18px;font:14px/1 system-ui;font-weight:700;
   border:1px solid var(--gold)}}
 .send .wa{{background:var(--gold);color:#100d13}}.send .cp{{background:transparent;color:var(--gold)}}
 .send button:disabled{{opacity:.4;cursor:not-allowed}}
 .hint{{text-align:center;color:var(--mut);font-size:12.5px;margin:11px 0 0}}
 .disc{{margin:38px 0 0;padding:16px 18px;border:1px solid var(--line);border-radius:12px;background:#17131c;
   color:var(--mut);font-size:13px;line-height:1.65;font-family:system-ui,Segoe UI,Roboto,sans-serif}}
 .disc b{{color:#c9b8cf}}
 .disc p{{margin:0 0 9px}}.disc p:last-child{{margin:0}}
 :focus-visible{{outline:2px solid var(--gold);outline-offset:2px}}
 @media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style></head><body>
<div class="wrap">

 <div class="top">
  <div class="om">॥ śrī śrī guru-gaurāṅgau jayataḥ ॥</div>
  <h1>Choosing the narrator's voice</h1>
  <p class="sub">For the Hindi diary &amp; teaching Shorts</p>
 </div>

 <p class="intro">Mahārāja's own voice will not be used for narration. These are candidate
 voices for the devotee who will read his words.</p>

 <div class="ask">Please listen to each voice and choose the one that sounds most
 <b>mature, sweet and prayerful</b> — a voice fit to carry his teachings.</div>

 <h2>The passages being read</h2>
 {passages}

 <h2>The voices</h2>
 <div class="recs">
{cards}
 </div>

 <div class="choose">
  <p class="q">Which voice should carry the teachings?</p>
  <div class="opts" id="opts">{opts}</div>
  <textarea class="note" id="note" placeholder="Any thoughts? (optional)"></textarea>
  <div class="send">
   <button class="wa" id="wa" disabled>Send on WhatsApp</button>
   <button class="cp" id="cp" disabled>Copy my choice</button>
  </div>
  <p class="hint" id="hint">Choose a voice above to continue.</p>
 </div>

 <div class="disc">
  <p><b>Please judge the voice, not the delivery.</b> These are plain readings. No emphasis or
  dramatic pauses have been added yet — that is a separate piece of work. Listen for the
  <b>timbre</b>: is this a voice you would want narrating every episode?</p>
  <p><b>Every voice here has been checked.</b> Each was measured against Mahārāja's recordings by
  two independent speaker-recognition systems and confirmed <b>not</b> to resemble his voice.</p>
  <p>Each voice is a different synthetic speaker. Whichever is chosen will be fixed permanently, so
  the narrator stays the same across the whole series.</p>
 </div>

</div>
<script>
 var sel=null;
 var opts=document.getElementById('opts');
 opts.addEventListener('click',function(e){{
   var b=e.target.closest('.opt'); if(!b) return;
   sel=b.dataset.v;
   [].forEach.call(opts.querySelectorAll('.opt'),function(o){{o.classList.toggle('on',o===b);}});
   [].forEach.call(document.querySelectorAll('.rec'),function(r){{
     r.classList.toggle('on', r.dataset.v===sel);}});
   document.getElementById('wa').disabled=false;
   document.getElementById('cp').disabled=false;
   document.getElementById('hint').textContent='Chosen: '+sel;
 }});
 function msg(){{
   var n=document.getElementById('note').value.trim();
   return 'Narrator voice — my choice: '+sel+(n?('\\nNotes: '+n):'');
 }}
 document.getElementById('wa').onclick=function(){{
   window.open('https://wa.me/?text='+encodeURIComponent(msg()),'_blank');
 }};
 document.getElementById('cp').onclick=function(){{
   navigator.clipboard.writeText(msg()).then(function(){{
     document.getElementById('hint').textContent='Copied — please paste it in your reply.';
   }});
 }};
</script>
</body></html>
"""


def main():
    screen = json.loads((HI / "_seed_screen.json").read_text(encoding="utf-8"))
    kept = sorted([s for s in screen if s["keep"]], key=lambda s: s["f0"])
    if not kept:
        sys.exit("no kept candidates — run the seed screen first")
    passages = json.loads((HI / "_audition_passages.json").read_text(encoding="utf-8"))
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found — needed to compress audio for the web")

    if AUDIO.exists():
        shutil.rmtree(AUDIO)
    AUDIO.mkdir(parents=True)

    # Neutral public labels: seniors shouldn't have to parse "tender__s909".
    cards, opts = [], []
    for i, s in enumerate(kept, 1):
        name = f"Voice {i}"
        for pid in sorted(passages):
            src = SRC / f"{s['voice']}__{pid}.wav"
            if not src.exists():
                sys.exit(f"missing {src}")
            dst = AUDIO / f"voice{i}_{pid}.mp3"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                            "-ac", "1", "-b:a", "72k", str(dst)], check=True)
        players = "\n".join(
            f'   <p class="lbl">{"Short prayer" if pid == "p01" else "Longer passage"}</p>\n'
            f'   <audio controls preload="none" src="audio/voice{i}_{pid}.mp3"></audio>'
            for pid in sorted(passages))
        cards.append(
            f'  <div class="rec" data-v="{name}">\n'
            f'   <div class="hd"><p class="t">{name}</p></div>\n{players}\n  </div>')
        opts.append(f'<button class="opt" data-v="{name}">{name}</button>')

    pblocks = "\n".join(
        f' <div class="passage"><p class="t">{"Short prayer" if pid == "p01" else "Longer passage"}'
        f'</p><p>{txt}</p></div>' for pid, txt in sorted(passages.items()))

    (OUT / "index.html").write_text(
        PAGE.format(cards="\n".join(cards), opts="".join(opts), passages=pblocks),
        encoding="utf-8")
    total = sum(f.stat().st_size for f in AUDIO.iterdir())
    print(f"wrote {OUT.relative_to(ROOT)}/index.html  ·  {len(kept)} voices  ·  "
          f"audio {total/1e6:.1f} MB")
    print("preview :  python -m http.server 8750 -d site-casting")
    print("deploy  :  npm i -g vercel  &&  vercel deploy --prod site-casting")


if __name__ == "__main__":
    main()
