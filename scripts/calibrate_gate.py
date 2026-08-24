import sys, json, csv, re
sys.stdout.reconfigure(encoding="utf-8")
try:
    from scripts.repo_paths import data_root
except ModuleNotFoundError:
    from repo_paths import data_root

BASE = data_root(__file__) / "out" / "lecture1"
REPORT = BASE / "qa_asr_report.tsv"
MANIFEST = BASE / "train.jsonl"

# ---- load metrics ----
rows = []
with open(REPORT, encoding="utf-8") as f:
    r = csv.DictReader(f, delimiter="\t")
    for d in r:
        for k in ("dur","align_min","align_mean","cer_raw","cer_core","wer","sanskrit_load","lead","trail"):
            d[k] = float(d[k])
        d["clip"] = int(d["clip"])
        rows.append(d)

CUTS = {1,5,11,15,16,30,35,36,48,49,51,58,66,70,79,80,81,85,93,98,99,100,101,109,115,117,118,123,125}
for d in rows:
    d["is_cut"] = d["clip"] in CUTS

cuts = [d for d in rows if d["is_cut"]]
keeps = [d for d in rows if not d["is_cut"]]
N = len(rows)
print(f"total={N} cuts={len(cuts)} keeps={len(keeps)}")

# ---- load manifest text ----
text_by_idx = {}
with open(MANIFEST, encoding="utf-8") as f:
    for i, line in enumerate(f, start=1):
        j = json.loads(line)
        text_by_idx[i] = j["text"]

# ---- distribution summary: cuts vs keeps for each metric ----
def stats(vals):
    vals = sorted(vals)
    n = len(vals)
    def pct(p):
        return vals[min(n-1, int(p*n))]
    return dict(min=vals[0], p10=pct(0.10), p25=pct(0.25), med=pct(0.5),
               p75=pct(0.75), p90=pct(0.90), max=vals[-1])

print("\n=== metric distributions (cuts vs keeps) ===")
for m in ("align_min","align_mean","cer_raw","cer_core","wer","sanskrit_load","dur","lead","trail"):
    sc = stats([d[m] for d in cuts])
    sk = stats([d[m] for d in keeps])
    print(f"\n{m}")
    print(f"  CUTS : min={sc['min']:.3f} p10={sc['p10']:.3f} p25={sc['p25']:.3f} med={sc['med']:.3f} p75={sc['p75']:.3f} p90={sc['p90']:.3f} max={sc['max']:.3f}")
    print(f"  KEEPS: min={sk['min']:.3f} p10={sk['p10']:.3f} p25={sk['p25']:.3f} med={sk['med']:.3f} p75={sk['p75']:.3f} p90={sk['p90']:.3f} max={sk['max']:.3f}")

# ---- how well does a single threshold isolate cuts? ----
# We want HIGH PRECISION KEEP gate => among auto-kept, few/no confirmed cuts.
# Evaluate candidate gates: a clip is AUTO-KEPT if it passes ALL conditions.

def eval_gate(name, predicate):
    kept = [d for d in rows if predicate(d)]
    kept_cuts = [d for d in kept if d["is_cut"]]
    kept_keeps = [d for d in kept if not d["is_cut"]]
    dropped = [d for d in rows if not predicate(d)]
    dropped_cuts = [d for d in dropped if d["is_cut"]]
    dropped_keeps = [d for d in dropped if not d["is_cut"]]
    print(f"\n--- GATE: {name} ---")
    print(f"  auto-kept       : {len(kept):3d}  (of {N})")
    print(f"  cuts leaking in : {len(kept_cuts):3d}  <-- contamination (want 0)   ids={sorted(d['clip'] for d in kept_cuts)}")
    print(f"  keeps retained  : {len(kept_keeps):3d}  (yield)")
    print(f"  cuts caught     : {len(dropped_cuts):3d}/29  ({100*len(dropped_cuts)/29:.0f}% of confirmed-bad dropped)")
    print(f"  keeps also dropped (false-neg SUSPECTS to re-listen): {len(dropped_keeps):3d}   ids={sorted(d['clip'] for d in dropped_keeps)}")
    return dict(kept=len(kept), kept_cuts=len(kept_cuts), kept_keeps=len(kept_keeps),
                caught=len(dropped_cuts), susp=len(dropped_keeps),
                susp_ids=sorted(d['clip'] for d in dropped_keeps),
                leak_ids=sorted(d['clip'] for d in kept_cuts))

# Baseline: current production gate is cer_core based (status column). Re-derive.
print("\n\n############ BASELINE: current cer_core gate (status) ############")
# infer current threshold: all FAIL are high_cer_core; find boundary
pass_core = max(d["cer_core"] for d in rows if d["status"]=="PASS")
fail_core = min(d["cer_core"] for d in rows if d["status"]=="FAIL")
print(f"current PASS max cer_core={pass_core:.3f}, FAIL min cer_core={fail_core:.3f}")

# ---- verse/sanskrit/second-voice heuristics from text ----
# Detect verse-heavy / sanskrit transliteration: lots of diacritic-ish tokens, hyphenated transliteration, IAST markers.
IAST = re.compile(r"[āīūṛṝḷḹṅñṭḍṇśṣṁṃḥ]", re.I)
def sanskrit_token_ratio(text):
    toks = re.findall(r"[A-Za-zāīūṛṝḷḹṅñṭḍṇśṣṁṃḥ'\-]+", text)
    if not toks: return 0.0
    # transliteration markers: contains apostrophe (avagraha), or known verse words, or IAST diacritics, or hyphen-compound
    verse_hits = 0
    for t in toks:
        if IAST.search(t) or "'" in t:
            verse_hits += 1
    return verse_hits/len(toks)

def hyphen_compound_ratio(text):
    toks = re.findall(r"[A-Za-z'\-]+", text)
    if not toks: return 0.0
    return sum(1 for t in toks if "-" in t)/len(toks)

print("\n=== text-based verse signal (sanskrit token ratio) cuts vs keeps ===")
for d in rows:
    d["str"] = sanskrit_token_ratio(text_by_idx[d["clip"]])
    d["hyr"] = hyphen_compound_ratio(text_by_idx[d["clip"]])
sc = stats([d["str"] for d in cuts]); sk = stats([d["str"] for d in keeps])
print(f"  CUTS str : med={sc['med']:.3f} p75={sc['p75']:.3f} max={sc['max']:.3f}")
print(f"  KEEPS str: med={sk['med']:.3f} p75={sk['p75']:.3f} max={sk['max']:.3f}")

# ---- CANDIDATE GATES ----
print("\n\n############ CANDIDATE GATES ############")

# G0: just current cer_core (<=0.85 keep) -- reproduce production
eval_gate("cer_core<=0.85 (current prod)", lambda d: d["cer_core"]<=0.85)

# G1: tighten cer_core only
for t in (0.80,0.75,0.70,0.65,0.60,0.55):
    eval_gate(f"cer_core<={t}", lambda d,t=t: d["cer_core"]<=t)

# G2: align_min floor only
for t in (-45,-40,-35,-32,-30,-28,-25):
    eval_gate(f"align_min>={t}", lambda d,t=t: d["align_min"]>=t)

# G3: sanskrit_load (abs) -- |sanskrit_load| large = text/audio sanskrit mismatch
for t in (0.5,0.4,0.3,0.25,0.2):
    eval_gate(f"|sanskrit_load|<={t}", lambda d,t=t: abs(d["sanskrit_load"])<=t)

# G-COMBO A: high-precision multi-condition
def gA(d):
    return (d["cer_core"]<=0.70 and d["align_mean"]>=-12.0 and abs(d["sanskrit_load"])<=0.30
            and d["dur"]>=4.0 and d["dur"]<=22.0)
eval_gate("COMBO-A cer_core<=.70 & align_mean>=-12 & |sload|<=.30 & 4<=dur<=22", gA)

def gB(d):
    return (d["cer_core"]<=0.65 and d["align_mean"]>=-11.0 and abs(d["sanskrit_load"])<=0.25
            and d["dur"]>=4.0 and d["dur"]<=20.0 and d["lead"]<=0.5 and d["trail"]<=0.5)
eval_gate("COMBO-B cer_core<=.65 & align_mean>=-11 & |sload|<=.25 & 4<=dur<=20 & lead/trail<=.5", gB)

def gC(d):
    return (d["cer_core"]<=0.60 and d["align_mean"]>=-10.0 and abs(d["sanskrit_load"])<=0.20
            and d["dur"]>=4.0 and d["dur"]<=20.0 and d["lead"]<=0.4 and d["trail"]<=0.4)
eval_gate("COMBO-C cer_core<=.60 & align_mean>=-10 & |sload|<=.20 & 4<=dur<=20 & lead/trail<=.4", gC)

# G-COMBO that catches ALL cuts (precision=100% on cuts) while maximizing keeps retained
def gD(d):
    return (d["cer_core"]<=0.85 and abs(d["sanskrit_load"])<=0.40 and d["align_min"]>=-32.0)
eval_gate("COMBO-D cer_core<=.85 & |sload|<=.40 & align_min>=-32", gD)

# check clip 65 (clean reference) and clip 124 (suspected broken keep)
print("\n=== reference clips ===")
for cid in (65,124):
    d = next(x for x in rows if x["clip"]==cid)
    print(f"  clip {cid}: align_min={d['align_min']:.1f} align_mean={d['align_mean']:.2f} cer_core={d['cer_core']:.3f} sload={d['sanskrit_load']:.3f} dur={d['dur']:.1f} lead={d['lead']} trail={d['trail']} status={d['status']}")
