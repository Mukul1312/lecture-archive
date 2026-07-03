"""
triage_lectures.py - Stage 1 lecture picker for taptajivanam.com/all-transcriptions.php

For EVERY lecture on the index it fetches the page (static HTML, urllib) and scores it on the
axes that decide whether it's good clone-training material -- WITHOUT downloading any audio:

  english_pct   fraction of transcript words in an English dictionary (high = English-dominant,
                low = verse/Sanskrit-dense -> fewer usable clips)
  discussion    ratio of NON-GGS speaker turns + question density (high = crowd Q&A / interview,
                low = solo class monologue -> cleaner single-speaker data)
  words / mins  transcript size + a rough minutes estimate from the MP3 byte size (HEAD request)
  has_audio     the <source>.mp3 exists
  transcript    the official transcript is present on the page

Output: data/lecture_triage.tsv (all rows) + a ranked shortlist to stdout. HTML is cached under
data/.triage_cache/ so re-runs are instant and we don't hammer the site.

Run:
  .venv/Scripts/python.exe scripts/triage_lectures.py            # all lectures
  .venv/Scripts/python.exe scripts/triage_lectures.py --limit 3  # quick parse test
"""
import argparse, html, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_lecture import P_RE, SOURCE_RE, slugify           # reuse the proven parsers
import classify_transliterate as ct

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://taptajivanam.com/"
INDEX = BASE + "all-transcriptions.php"
CACHE = ROOT / "data" / ".triage_cache"
UA = {"User-Agent": "Mozilla/5.0 (voice-clone data triage)"}
ENG = set((ROOT / "data" / "english_words.txt").read_text(encoding="utf-8").split())
# questioner/crowd labels that mark a Q&A / discussion (his OWN speech is usually unlabeled, so
# the robust signal is the ABSOLUTE count of these interjections, not a ratio against his turns).
OTHER_SPK = re.compile(r'(?:^|\n|\.|")\s*(Devotee|Devotees|Question|Questioner|Guest|Visitor|'
                       r'Interviewer|Audience|Boy|Child)\s*:', re.I)
GGS_SPK = re.compile(r'Gour\s+Govinda\s+Swami\s*:', re.I)


def fetch(url, cache_key=None, retries=3):
    if cache_key:
        cp = CACHE / cache_key
        if cp.exists():
            return cp.read_text(encoding="utf-8", errors="replace")
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
            if cache_key:
                CACHE.mkdir(parents=True, exist_ok=True)
                (CACHE / cache_key).write_text(raw, encoding="utf-8")
            return raw
        except Exception as e:
            if a == retries - 1:
                print(f"  !! fetch failed {url}: {e}")
                return ""
            time.sleep(1.0)


def head_bytes(url):
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n else 0
    except Exception:
        return 0


def strip_tags(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def lecture_rows():
    raw = fetch(INDEX, cache_key="index.html")
    seen, out = set(), []
    for href, txt in re.findall(r'<a[^>]+href="([^"]*view-archive\.php[^"]*)"[^>]*>(.*?)</a>', raw, re.I | re.S):
        if href in seen:
            continue
        seen.add(href)
        aid = re.search(r"a_id=(\d+)", href)
        out.append((href, strip_tags(txt), aid.group(1) if aid else "?"))
    return out


def analyze(href, title, aid):
    url = urllib.parse.urljoin(BASE, html.unescape(href))
    page = fetch(url, cache_key=f"a{aid}.html")
    paras = [strip_tags(p) for p in P_RE.findall(page)]          # strict (old template: dir=ltr+justify)
    if len([p for p in paras if len(p) > 40]) < 3:              # new template: justify without dir
        paras = [strip_tags(p) for p in
                 re.findall(r'<p style="text-align:\s*justify;?"[^>]*>(.*?)</p>', page, re.I | re.S)]
    paras = [p for p in paras if len(p) > 40]
    text = "\n".join(paras).strip()
    m = SOURCE_RE.search(page)                                  # non-empty static .mp3 src
    audio = urllib.parse.urljoin(BASE, m.group(1)) if m else ""
    js_audio = int(bool(re.search(r"<audio[^>]*>", page)) and not audio)   # JS-injected mp3 (needs firecrawl)
    # vocab: transliterate IAST->ASCII, then dictionary hit-rate
    toks = re.findall(r"[A-Za-z']+", ct.transliterate(text).lower())
    eng = sum(1 for t in toks if t in ENG)
    english_pct = eng / len(toks) if toks else 0.0
    # solo vs discussion: absolute questioner interjections, and their density per 1000 words
    other = len(OTHER_SPK.findall(text))
    disc = round(other / max(1.0, len(toks) / 1000.0), 2)      # questioner turns per 1k words
    qmarks = text.count("?")
    mb = head_bytes(audio) / 1e6 if audio else 0.0
    est_min = mb / (142_000 / 8 * 60 / 1e6) if mb else 0.0     # ~142 kbps mp3
    return {
        "aid": aid, "title": title, "words": len(toks), "english_pct": round(english_pct, 3),
        "discussion": round(disc, 3), "other_turns": other, "qmarks": qmarks,
        "audio_mb": round(mb, 1), "est_min": round(est_min, 1),
        "has_transcript": int(len(toks) > 200), "has_audio": int(bool(audio)),
        "js_audio": js_audio, "url": url,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    lects = lecture_rows()
    if args.limit:
        lects = lects[: args.limit]
    print(f"[index] {len(lects)} lectures\n")
    rows = []
    for i, (href, title, aid) in enumerate(lects, 1):
        r = analyze(href, title, aid)
        rows.append(r)
        aud = "AUD" if r["has_audio"] else ("JS " if r["js_audio"] else "---")
        print(f"{i:3d}/{len(lects)} [{aid:>4s}] eng {r['english_pct']*100:3.0f}%  "
              f"q{r['other_turns']:2d}  {r['est_min']:5.1f}min  "
              f"{aud} {'TXT' if r['has_transcript'] else '---'}  {title[:48]}")

    cols = ["aid", "title", "words", "english_pct", "discussion", "other_turns", "qmarks",
            "audio_mb", "est_min", "has_transcript", "has_audio", "js_audio", "url"]
    out = ROOT / "data" / "lecture_triage.tsv"
    with out.open("w", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r[c]) for c in cols) + "\n")
    print(f"\n[write] {out}")

    if len(rows) > 5:
        good = [r for r in rows if (r["has_audio"] or r["js_audio"]) and r["has_transcript"]
                and r["english_pct"] >= 0.80 and r["other_turns"] <= 3]
        good.sort(key=lambda r: (r["other_turns"], -r["english_pct"]))
        print(f"\n=== SHORTLIST (English-dominant solo classes, ≤3 questioner turns, {len(good)} of {len(rows)}) ===")
        for r in good[:20]:
            src = "static" if r["has_audio"] else "JS"
            print(f"  [{r['aid']:>4s}] eng {r['english_pct']*100:3.0f}%  q{r['other_turns']:2d}  "
                  f"{r['est_min']:5.1f}min  {src:>6s}  {r['title'][:48]}")


if __name__ == "__main__":
    main()
