"""
prep_entries.py — turn data/diary/entries.md (the faithful diacritic source, role-tagged) into
narration-ready chunks, deterministically. This is the "make them ready for narration" step:

  1. parse each `## Entry N` block into its `### [NARRATOR]` / `### [GGS]` sections
  2. SPOKEN DATES  — replace every inline dd-mm-yy / dd-mm-yyyy with its spoken form
                     (the clone reads digits badly): 15-04-75 -> "April fifteenth, nineteen seventy five"
  3. LEXICON       — lexicon.normalize(): Gopāla->Gopaal, Kṛṣṇa->Krishna, strip residual diacritics
  4. chunk each paragraph at sentence ends (each well under VoxCPM's ~20s ceiling), tagged by role
  5. write, per entry:
        data/narration/entries/entryN.tsv          role<TAB>tts_text   (generation input)
        data/narration/entries/entryN.display.md   human/devotee transcript (diacritics kept)
     and one data/narration/entries/_review.md — the lexicon + spoken-date + chunk-length CHECK.

Role -> voice:  NARR = base VoxCPM2 (no LoRA) male narrator;  GGS = LoRA + calm ref (his clone).
Run: .venv/Scripts/python.exe scripts/prep_entries.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from lexicon import normalize, spoken_date, LEXICON   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SRC = ROOT / "data" / "diary" / "entries.md"
OUT = ROOT / "data" / "narration" / "entries"
OUT.mkdir(parents=True, exist_ok=True)

MAXLEN = 230           # chars; a calm slow read of ~230 chars stays under the ~20s autoregressive ceiling
DATE_RE = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2,4})\b")

# prayerful softening (house style, ear-approved on the 8th-May entry): "!" -> "…" (weight, not volume).
# Lowercase the word after "…" ONLY if it's a plain sentence-opener — never a deity name or reverential
# pronoun (You/Your/Lord stay capital). This joins "Oh Lord!" into its sentence: "Oh Lord… this servant…"
_OPENERS = {"as", "by", "what", "there", "may", "please", "but", "and", "now", "still", "otherwise",
            "if", "so", "oh", "today", "whenever", "because", "in", "for", "let", "this", "that",
            "unless", "especially", "when", "where", "why", "how", "then", "yet", "also", "again", "once"}


def soften(text):
    """GGS-only: '!' -> '…', joining short interjections into the following sentence's prosody."""
    def repl(m):
        w = m.group(1)
        return f"… {w[0].lower() + w[1:]}" if w.lower() in _OPENERS else f"… {w}"
    return re.sub(r"!\s+(\w+)", repl, text).replace("!", "…")


def sub_dates(text, log):
    """Replace inline digit dates with spoken form (no trailing '.', it's mid-sentence). Logs each."""
    def repl(m):
        dd, mm, yy = int(m[1]), int(m[2]), int(m[3])
        if yy < 100:
            yy += 1900
        phrase = spoken_date(dd, mm, yy).rstrip(".")
        log.append((m.group(0), phrase))
        return phrase
    return DATE_RE.sub(repl, text)


def split_sentences(p, soft):
    """Split a paragraph at sentence ends; further split any overlong sentence on ';' then ','.
    soft=True (GGS, post-soften): DON'T split on '…' — keep softened interjections joined to their
    sentence; split only on '.'/'?'. soft=False (narrator): split on '.'/'?'/'!' normally."""
    boundary = r"(?<=[.?])\s+" if soft else r"(?<=[.!?])\s+"
    out = []
    for s in re.split(boundary, p.strip()):
        s = s.strip()
        if not s:
            continue
        if len(s) <= MAXLEN:
            out.append(s)
            continue
        buf = ""
        for seg in re.split(r"(?<=[;,])\s+", s):        # break the long one at clause boundaries
            if buf and len(buf) + 1 + len(seg) > MAXLEN:
                out.append(buf)
                buf = seg
            else:
                buf = f"{buf} {seg}".strip()
        if buf:
            out.append(buf)
    return out


def parse(md):
    """entries.md -> [ {n, title, role, section, paras:[...]} ] in reading order."""
    buckets, n, title, role = [], None, None, None
    for ln in md.splitlines():
        m = re.match(r"##\s+Entry\s+(\d+)\s+—\s+(.*)", ln)
        if m:
            n, title, role = int(m[1]), m[2].strip(), None
            continue
        m = re.match(r"###\s+\[(NARRATOR|GGS)\]\s*(.*)", ln)
        if m:
            role = m[1]
            buckets.append({"n": n, "title": title, "role": role,
                            "section": m[2].strip() or role.lower(), "paras": []})
            continue
        if role is None:
            continue                                    # metadata / header lines before the first ###
        t = ln.strip()
        if not t or t.startswith(("-", ">", "#", "|", "*")):
            continue                                    # skip bullets, blockquotes, rules
        buckets[-1]["paras"].append(t)
    return buckets


def main():
    md = SRC.read_text(encoding="utf-8")
    buckets = parse(md)
    entry_nums = sorted({b["n"] for b in buckets})

    date_log = []                                       # (raw, spoken) across the whole doc
    long_warn = []                                      # (entry, role, len, chunk) over MAXLEN
    gaps = []                                           # (entry, char, word) residual non-ASCII after normalize
    rows_by_entry = {n: [] for n in entry_nums}         # n -> [(role, section, disp, tts)]

    for b in buckets:
        is_ggs = b["role"] == "GGS"
        for para in b["paras"]:
            para = para.replace("[Haribol]", "Haribol")  # spoken exclamation, not a tag
            disp_para = sub_dates(para, date_log)
            if is_ggs:
                disp_para = soften(disp_para)             # prayerful "!"->"…" on his lines only
            for disp in split_sentences(disp_para, is_ggs):
                tts = normalize(disp)
                rows_by_entry[b["n"]].append((b["role"], b["section"], disp, tts))
                if len(tts) > MAXLEN:
                    long_warn.append((b["n"], b["role"], len(tts), tts))
                for ch in tts:
                    if ord(ch) > 127:
                        word = next((w for w in tts.split() if ch in w), ch)
                        gaps.append((b["n"], ch, word))

    # ---- write per-entry .tsv (generation) + .display.md (transcript) ----
    for n in entry_nums:
        rows = rows_by_entry[n]
        title = next(b["title"] for b in buckets if b["n"] == n)
        tsv = "\n".join(f"{r[0]}\t{r[3]}" for r in rows) + "\n"
        (OUT / f"entry{n}.tsv").write_text(tsv, encoding="utf-8")

        disp_md, cur = [f"# Entry {n} — {title}\n"], None
        for role, section, disp, _ in rows:
            head = f"[{role}] {section}"
            if head != cur:
                voice = "base-model male narrator — not his voice" if role == "NARRATOR" else "his clone, calm ref"
                disp_md.append(f"\n**{head}** _({voice})_")
                cur, idx = head, 0
            idx += 1
            disp_md.append(f"{idx}. {disp}")
        (OUT / f"entry{n}.display.md").write_text("\n".join(disp_md) + "\n", encoding="utf-8")

    # ---- lexicon coverage: which maintained terms actually fired (so the ear can confirm each) ----
    joined = " ".join(r[2] for rows in rows_by_entry.values() for r in rows)
    src_joined = " ".join(b_para for b in buckets for b_para in b["paras"])
    fired = sorted({k: LEXICON[k] for k in LEXICON if k in src_joined}.items(),
                   key=lambda kv: kv[0].lower())

    # ---- review report ----
    R = ["# Diary entries — narration-prep review", "",
         f"Source: `data/diary/entries.md` · generated by `scripts/prep_entries.py`", ""]
    R.append("## Chunk counts (→ GPU cost)")
    R.append("| Entry | NARR | GGS | title |")
    R.append("|---|---|---|---|")
    tot_n = tot_g = 0
    for n in entry_nums:
        rows = rows_by_entry[n]
        cn = sum(1 for r in rows if r[0] == "NARRATOR")
        cg = sum(1 for r in rows if r[0] == "GGS")
        tot_n += cn
        tot_g += cg
        R.append(f"| {n} | {cn} | {cg} | {next(b['title'] for b in buckets if b['n']==n)} |")
    R.append(f"| **all** | **{tot_n}** | **{tot_g}** | — |")
    R.append("")
    R.append(f"At 24 seeds/GGS-chunk + 6 seeds/NARR-chunk: "
             f"**{tot_g*24 + tot_n*6} generations** ({tot_g}×24 + {tot_n}×6).")
    R.append("")

    R.append("## Spoken-date conversions (check)")
    if date_log:
        seen = set()
        R.append("| in text | spoken as |")
        R.append("|---|---|")
        for raw, spoken in date_log:
            if raw not in seen:
                seen.add(raw)
                R.append(f"| `{raw}` | {spoken} |")
    else:
        R.append("_No inline digit-dates in any body (Entries 2–4 carry the date only in the header)._")
    R.append("")

    R.append("## Lexicon coverage (check)")
    R.append(f"**{len(fired)} maintained terms fired.** Confirm each is spelled how the clone should *say* it:")
    R.append("")
    R.append("| source term | spoken as |")
    R.append("|---|---|")
    for k, v in fired:
        R.append(f"| {k} | {v} |")
    R.append("")
    if gaps:
        R.append(f"### ⚠ Lexicon GAPS — {len(gaps)} residual non-ASCII (add to LEXICON):")
        seen = set()
        for n, ch, word in gaps:
            key = (ch, word)
            if key not in seen:
                seen.add(key)
                R.append(f"- entry {n}: `{ch}` in **{word}**")
    else:
        R.append("✅ **No residual non-ASCII** after normalize — every diacritic term is mapped.")
    R.append("")

    R.append("## Over-length chunks (>%d chars → >~20s risk)" % MAXLEN)
    if long_warn:
        for n, role, ln_, chunk in long_warn:
            R.append(f"- entry {n} [{role}] {ln_} chars: {chunk}")
    else:
        R.append("✅ Every chunk is within the length ceiling.")
    R.append("")

    (OUT / "_review.md").write_text("\n".join(R) + "\n", encoding="utf-8")

    # ---- stdout summary ----
    print(f"Parsed {len(entry_nums)} entries → {OUT.relative_to(ROOT)}")
    print(f"  chunks: NARR {tot_n} · GGS {tot_g}  (→ {tot_g*24 + tot_n*6} generations)")
    print(f"  spoken dates: {len({r for r,_ in date_log})} distinct")
    print(f"  lexicon terms fired: {len(fired)}")
    print(f"  lexicon gaps (residual non-ASCII): {len(gaps)}")
    print(f"  over-length chunks: {len(long_warn)}")
    print(f"\nReview → {(OUT/'_review.md').relative_to(ROOT)}")
    if gaps:
        print("  ⚠ GAPS:", ", ".join(sorted({f'{c}:{w}' for _, c, w in gaps})))


if __name__ == "__main__":
    main()
