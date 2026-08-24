import sys, json, csv, re
sys.stdout.reconfigure(encoding="utf-8")
try:
    from scripts.repo_paths import data_root
except ModuleNotFoundError:
    from repo_paths import data_root

BASE = data_root(__file__) / "out" / "lecture1"
rows = []
with open(BASE / "qa_asr_report.tsv", encoding="utf-8") as f:
    for d in csv.DictReader(f, delimiter="\t"):
        for k in ("dur","align_min","align_mean","cer_raw","cer_core","wer","sanskrit_load","lead","trail"):
            d[k]=float(d[k])
        d["clip"]=int(d["clip"]); rows.append(d)
CUTS={1,5,11,15,16,30,35,36,48,49,51,58,66,70,79,80,81,85,93,98,99,100,101,109,115,117,118,123,125}
for d in rows: d["is_cut"]=d["clip"] in CUTS
text={}
with open(BASE / "train.jsonl",encoding="utf-8") as f:
    for i,l in enumerate(f,1): text[i]=json.loads(l)["text"]

# The decisive finding: cer_core has a CLEAN GAP. keeps max=0.849, cuts min=0.862.
# So cer_core<=0.85 is already perfect-precision on confirmed-bad.
# For a HIGH-PRECISION SCALING gate we want margin + catch false-neg suspects that were kept unheard.
# Strategy: keep cer_core as primary, ADD redundant guards that flag the worst unheard keeps.

def show(predicate, name):
    kept=[d for d in rows if predicate(d)]
    kc=[d for d in kept if d["is_cut"]]
    kk=[d for d in kept if not d["is_cut"]]
    print(f"{name}: kept={len(kept)} leak_cuts={len(kc)} {sorted(x['clip'] for x in kc)} yield_keeps={len(kk)}")
    return len(kk), sorted(d["clip"] for d in rows if not predicate(d) and not d["is_cut"])

# RECOMMENDED GATE: cer_core<=0.80 (one notch tighter than prod for margin)
#  + align_min>=-45 (catches clip124 broken, -91.6)
#  + |sanskrit_load|<=0.40 (verse text/audio sanskrit mismatch)
#  + 4.0<=dur<=20 (VoxCPM2 clip-length sanity)
print("=== RECOMMENDED TIERED GATE ===\n")

def auto_keep(d):
    return (d["cer_core"]<=0.80 and d["align_min"]>=-45.0
            and abs(d["sanskrit_load"])<=0.40 and 4.0<=d["dur"]<=20.0)
yk, susp = show(auto_keep, "AUTO-KEEP (cer_core<=.80 & align_min>=-45 & |sload|<=.40 & 4<=dur<=20)")
print(f"  false-neg SUSPECTS to spot-check ({len(susp)}): {susp}")

# How many of those suspects are 'borderline' (close to gate) vs deep?
print("\n=== suspect breakdown (why each KEEP was dropped) ===")
for cid in susp:
    d=next(x for x in rows if x["clip"]==cid)
    why=[]
    if d["cer_core"]>0.80: why.append(f"cer_core={d['cer_core']:.2f}")
    if d["align_min"]<-45: why.append(f"align_min={d['align_min']:.1f}")
    if abs(d["sanskrit_load"])>0.40: why.append(f"sload={d['sanskrit_load']:.2f}")
    if not (4.0<=d["dur"]<=20.0): why.append(f"dur={d['dur']:.1f}")
    print(f"  clip {cid:3d}: {', '.join(why)}")

# Also report a STRICTER variant for if we want even fewer/cleaner
print("\n=== STRICT variant (cer_core<=0.70) ===")
def strict(d):
    return (d["cer_core"]<=0.70 and d["align_min"]>=-40.0
            and abs(d["sanskrit_load"])<=0.30 and 4.0<=d["dur"]<=18.0)
yk2, susp2 = show(strict, "STRICT")

# ---- PROJECTION across 10 lectures ----
print("\n\n=== YIELD PROJECTION ===")
clips_per_lec = 134  # lecture1 actual
# lecture1 confirmed-bad rate among ALL = 29/134 = 21.6%
# recommended gate auto-keep yield on lecture1:
print(f"lecture1: {clips_per_lec} clips, gate auto-keeps {yk} ({100*yk/clips_per_lec:.0f}%)")
# assume similar distribution; project
per_lec_yield = yk/clips_per_lec
total_clips = clips_per_lec*10
proj_keep = per_lec_yield*total_clips
print(f"per-lecture auto-keep yield: ~{yk} clips ({100*per_lec_yield:.0f}%)")
print(f"10 lectures: ~{total_clips} raw clips -> ~{proj_keep:.0f} auto-kept clean clips")
print(f"need 150 => surplus factor {proj_keep/150:.1f}x")
# we only need 150; so we can be even more selective OR stop after a few lectures
need=150
lec_needed = need/yk
print(f"lectures needed to reach 150 at this yield: {lec_needed:.1f}")

# ---- MANUAL REVIEW REDUCTION ----
print("\n=== MANUAL REVIEW REDUCTION ===")
print(f"OLD (full manual pass): listen to all {clips_per_lec} clips/lecture = {clips_per_lec*10} clips over 10 lectures")
print(f"NEW: trust auto-keep ({yk}/lec), spot-check only the suspects ({len(susp)}/lec)")
print(f"  spot-check load: {len(susp)} clips/lec * 10 = {len(susp)*10} clips total (vs {clips_per_lec*10})")
print(f"  reduction: {100*(1-(len(susp)*10)/(clips_per_lec*10)):.0f}% fewer clips to listen to")
print(f"  (auto-keep set NOT listened; trusted by gate)")
