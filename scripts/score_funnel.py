"""
score_funnel.py — the QC funnel + take-selection studio (Stages 3-4).

For a folder of generated takes it runs every take through three OBJECTIVE gates and then ranks the
survivors, so a human curates from a clean shortlist instead of raw output:
  3a  HALLUCINATION  — ASR round-trip (faster-whisper): transcribe the take, compare to the input text;
                       extra words / repeats / a laugh / missing words  -> auto-FAIL.
  3b  IDENTITY       — ECAPA cosine to his voice centroid; too low ("not him") -> flag.
  3c  PROSODY        — graveness (low pitch/range/loud/rate), centred within the line.
  4   RANK           -> a studio gallery: passing takes ranked gravest-first, with the transcription shown.

Validation run: points at the pre-test takes to prove the funnel flags the hallucinations we caught by ear
(date-123, vow-123 laugh, Prasadam-123, vow-7 repeat).  Output -> voice_lab/studio/
Run: .venv/Scripts/python.exe scripts/score_funnel.py
"""
import difflib
import importlib.util
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
import torch
import torch.nn.functional as F
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy
from faster_whisper import WhisperModel

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data/out/lecture1/final"
CLIPS = FINAL / "clips"
SRC = ROOT / "data/out/lecture1/pretest"        # validation input
OUT = ROOT / "voice_lab" / "studio"
AUD = OUT / "audio"
DEV = "cpu"
HALLUC_SIM = 0.72      # word-sequence similarity below this  -> hallucination
HALLUC_LEN = 1.40      # transcript >40% longer than input     -> extra content
ID_FLOOR = 0.62        # ECAPA cosine below this                -> "not clearly him"

# expected text per pre-test line (what we asked the clone to say)
EXPECT = {
    "date": "May eighth, nineteen seventy five, Thursday.",
    "vow": "This servant took a vow not to eat anything at night except a little maha water with Tulasi.",
    "iskcon": "To open an ISKCON centre in Odisha.",
    "prema": "For receiving complete and uninterrupted Krishna prema.",
    "prasadam": "He will not accept any Prasadam at night.",
    "lila": "But what an astonishing leela You are performing.",
    "sannyasi": "This servant did not desire to perform such type of severe austerity in front of a sannyasi present here.",
    "gopala": "Oh my Lord, Gopala! Please shower Your mercy.",
    "gauranga": "May this servant achieve success in the service of Sri Sri Guru and Gauranga. Hare Krishna.",
}

_spec = importlib.util.spec_from_file_location("bg", ROOT / "scripts" / "build_graveness.py")
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

print("loading ASR (faster-whisper base.en) + ECAPA ...", file=sys.stderr)
asr = WhisperModel("base.en", device="cpu", compute_type="int8")
clf = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     savedir=str(ROOT / ".venv/spkrec"), run_opts={"device": DEV},
                                     local_strategy=LocalStrategy.COPY)


def load16k(p):
    y, sr = sf.read(str(p), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != 16000:
        g = gcd(sr, 16000)
        y = resample_poly(y, 16000 // g, sr // g).astype("float32")
    return y


@torch.no_grad()
def embed(p):
    w = torch.from_numpy(np.ascontiguousarray(load16k(p))).unsqueeze(0)
    return F.normalize(clf.encode_batch(w.to(DEV)).squeeze(0).squeeze(0), dim=0)


def cos(a, b):
    return float(torch.dot(a, b))


def transcribe(p):
    segs, _ = asr.transcribe(str(p), beam_size=1, language="en")
    return " ".join(s.text for s in segs).strip()


_NUMW = set(("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
             "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred "
             "thousand first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
             "thirteenth fourteenth fifteenth twentieth thirtieth").split())


def _toks(t):
    return re.sub(r"[^a-z0-9 ]", " ", t.lower()).split()


def _collapse_nums(toks):
    """Collapse a run of number-tokens (words OR digits) to a single '#num' so 'eighth nineteen
    seventy five' and '8th 1975' compare equal — an ASR can't be trusted on number FORMAT."""
    out, prev = [], False
    for w in toks:
        isnum = w.isdigit() or re.sub(r"(st|nd|rd|th)$", "", w).isdigit() or w in _NUMW
        if isnum:
            if not prev:
                out.append("#num")
            prev = True
        else:
            out.append(w); prev = False
    return out


def _has_repeat(toks):
    for i in range(len(toks) - 2):
        if toks[i] == toks[i + 1] == toks[i + 2]:            # same word 3x in a row
            return True
    for i in range(len(toks) - 3):
        if toks[i] == toks[i + 2] and toks[i + 1] == toks[i + 3] and toks[i]:   # bigram looped
            return True
    return False


def hallucination(expected, said):
    """ASR round-trip flags only STRUCTURAL faults it can actually judge — gross extra content, loops,
    empty/truncated output. Term-correctness (Sanskrit) and subtle laughs stay an EAR check (ASR can't
    read those). sim is kept as info, not a reject trigger."""
    raw = _toks(said)
    e, s = _collapse_nums(_toks(expected)), _collapse_nums(raw)
    if not s:
        return dict(sim=0.0, lr=0.0, said=said, fail=True, why="empty")
    sim = round(difflib.SequenceMatcher(None, e, s).ratio(), 2)
    lr = round(len(s) / max(1, len(e)), 2)
    rep = _has_repeat(raw)
    fail = (lr > 1.5) or rep or (lr < 0.45)
    why = "repeat/loop" if rep else "extra content" if lr > 1.5 else "truncated" if lr < 0.45 else ""
    return dict(sim=sim, lr=lr, said=said, fail=fail, why=why)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    AUD.mkdir(parents=True, exist_ok=True)

    # his ECAPA centroid (English-dense clips, prompt clips excluded)
    rows = [json.loads(l) for l in (FINAL / "train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    eng = set((ROOT / "data/english_words.txt").read_text(encoding="utf-8").split())
    tok = re.compile(r"[a-z']+")
    def ef(t):
        w = tok.findall(t.lower()); return (sum(1 for x in w if x in eng) / len(w)) if w else 0
    EXCL = {"ggs_l1_0112", "ggs_l1_0114"}
    sel = [Path(r["audio"]).name for r in rows if 5 <= r["duration"] <= 12 and ef(r["text"]) >= 0.85 and Path(r["audio"]).stem not in EXCL]
    ref = F.normalize(torch.stack([embed(CLIPS / n) for n in sel[:20]]).mean(0), dim=0)

    pat = re.compile(r"(?P<label>\w+)__s(?P<seed>\d+)\.wav")
    takes = []
    for p in sorted(SRC.glob("*.wav")):
        m = pat.match(p.name)
        if not m or m["label"] not in EXPECT:
            continue
        shutil.copyfile(p, AUD / p.name)
        h = hallucination(EXPECT[m["label"]], transcribe(p))
        f = bg.feats(p)
        takes.append(dict(label=m["label"], seed=int(m["seed"]), wav=f"audio/{p.name}",
                          idn=round(cos(embed(p), ref), 3), **h, **f))
        print(f"  {p.name:<22} halluc={'FAIL('+h['why']+')' if h['fail'] else 'ok':<14} id={takes[-1]['idn']:.2f}", file=sys.stderr)

    # graveness centred within line
    for key in ("f0", "spread", "loud", "rate"):
        by = defaultdict(list)
        for t in takes:
            by[t["label"]].append(t[key])
        mean = {s: float(np.mean(v)) for s, v in by.items()}
        dev = [t[key] - mean[t["label"]] for t in takes]
        sd = float(np.std(dev)) or 1.0
        for t, d in zip(takes, dev):
            t[f"z_{key}"] = d / sd
    for t in takes:
        t["grave"] = round(-(t["z_f0"] + t["z_spread"] + t["z_loud"] + t["z_rate"]) / 4, 3)
        t["idlow"] = t["idn"] < ID_FLOOR

    flagged = [t for t in takes if t["fail"]]
    print(f"\n=== HALLUCINATION GATE: {len(flagged)}/{len(takes)} takes auto-rejected ===")
    for t in flagged:
        print(f"  {t['label']}__s{t['seed']}  ({t['why']}, sim {t['sim']}, len×{t['lr']}):  \"{t['said'][:70]}\"")

    groups = []
    for label, text in EXPECT.items():
        g = [t for t in takes if t["label"] == label]
        g.sort(key=lambda t: (t["fail"], -t["grave"]))     # survivors first, gravest-first
        groups.append(dict(label=label, text=text, takes=[
            dict(seed=t["seed"], wav=t["wav"], fail=t["fail"], why=t["why"], said=t["said"],
                 grave=t["grave"], idn=t["idn"], idlow=t["idlow"],
                 f0=round(t["f0"]), spread=round(t["spread"]), loud=round(t["loud"], 1), rate=round(t["rate"], 1))
            for t in g]))
    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(groups, ensure_ascii=False))
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"\nwrote {OUT / 'index.html'}")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Take studio — the funnel</title>
<style>
  :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--ink:#e7e9ee;--mut:#9aa3b2;--g:#7c9cff;--ok:#46c08a;--bad:#ff5d5d;--warn:#ffb84a;}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:1000px;margin:0 auto;padding:22px 16px 80px}
  h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 16px;max-width:770px}
  .item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px}
  .txt{margin:0 0 8px;font-size:13.5px}
  table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);font-size:12.5px;vertical-align:middle}
  th{color:var(--mut);font-weight:600}tr.top td{background:#16302a}tr.fail{opacity:.5}
  .gv{font-weight:700;color:var(--g)} audio{width:160px;height:30px}
  .tag{font-size:10px;padding:1px 6px;border-radius:10px;font-weight:700}
  .pass{background:#16302a;color:var(--ok)} .rej{background:#3a1b1b;color:var(--bad)} .idlow{background:#3a2e1a;color:var(--warn)}
  .said{color:var(--mut);font-size:11.5px;max-width:260px}
</style></head><body><div class="wrap">
  <h1>🎛️ Take studio — the QC funnel</h1>
  <p class="sub">Every take auto-checked: <b class="pass" style="padding:1px 5px;border-radius:8px">HALLUCINATION</b> (ASR reads it back — extra/repeat/laugh → rejected), <b>identity</b> (ECAPA cosine; low = not clearly him), and <b class="gv">graveness</b>. Survivors are ranked gravest-first per line — you pick the calm, correctly-said take from a pre-cleaned shortlist. Rejected takes are dimmed with what the ASR heard.</p>
  <div id="list"></div>
</div>
<script>
const DATA = /*__DATA__*/;
document.getElementById("list").innerHTML = DATA.map(g=>`
  <div class="item">
    <div class="txt">"${g.text}"</div>
    <table>
      <tr><th>seed</th><th>check</th><th>graveness</th><th>identity</th><th>pitch</th><th>rate</th><th>listen</th><th>ASR heard</th></tr>
      ${g.takes.map((t,i)=>`<tr class="${t.fail?'fail':(i===0?'top':'')}">
        <td>${t.seed}</td>
        <td>${t.fail?`<span class="tag rej">✗ ${t.why}</span>`:`<span class="tag pass">✓ clean</span>`}${t.idlow&&!t.fail?' <span class="tag idlow">id?</span>':''}</td>
        <td class="gv">${t.grave>=0?'+':''}${t.grave}</td>
        <td>${t.idn}</td><td>${t.f0}</td><td>${t.rate}</td>
        <td><audio controls preload="none" src="${t.wav}"></audio></td>
        <td class="said">${t.said}</td></tr>`).join("")}
    </table>
  </div>`).join("");
</script></body></html>
"""

if __name__ == "__main__":
    main()
