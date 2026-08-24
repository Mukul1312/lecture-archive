import sys, csv
sys.stdout.reconfigure(encoding="utf-8")
from statistics import median
try:
    from scripts.repo_paths import data_root
except ModuleNotFoundError:
    from repo_paths import data_root

METRICS = data_root(__file__) / "out" / "lecture1" / "qa_asr_report.tsv"
CUT_IDS = {1,5,11,15,16,30,35,36,48,49,51,58,66,70,79,80,81,85,93,98,99,100,101,109,115,117,118,123,125}

rows=[]
with open(METRICS, encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        clip=int(row["clip"]); rec={"clip":clip,"is_cut":clip in CUT_IDS,"reasons":row["reasons"]}
        for m in ["align_min","align_mean","cer_raw","cer_core","wer","sanskrit_load","lead","trail"]:
            rec[m]=float(row[m])
        rows.append(rec)
cuts=[r for r in rows if r["is_cut"]]; keeps=[r for r in rows if not r["is_cut"]]

# 1) Confirm circularity: every cut reason == high_cer_core, and cer_core>0.85 partitions exactly.
print("All cut reasons:", sorted(set(r["reasons"] for r in cuts)))
print("cuts with cer_core>0.85:", sum(r["cer_core"]>0.85 for r in cuts), "/29")
print("keeps with cer_core>0.85:", sum(r["cer_core"]>0.85 for r in keeps), "/105")
print("min cer_core among cuts:", min(r["cer_core"] for r in cuts))
print("max cer_core among keeps:", max(r["cer_core"] for r in keeps))

# 2) So evaluate OTHER metrics as if cer_core didn't exist. How well would each ALONE
#    have recovered the same 29 the cer_core gate found? This tells us which metric is an
#    INDEPENDENT detector vs which only looks good because it correlates with cer_core.
print("\n=== Non-CER metrics as standalone detectors of the same 29 ===")
def eval_gate(pred):
    return sum(1 for r in cuts if pred(r)), sum(1 for r in keeps if pred(r))
def best_dir_thr(m):
    allv=sorted(set(r[m] for r in rows)); best=None
    for d in (">=","<="):
        for t in allv:
            pred=(lambda mm,tt,dd:(lambda r: r[mm]>=tt if dd==">=" else r[mm]<=tt))(m,t,d)
            c,fl=eval_gate(pred); net=c-fl
            if best is None or (net,c,-fl)>(best[3]-best[4],best[3],-best[4]): best=(m,d,t,c,fl)
    return best
for m in ["align_min","align_mean","wer","sanskrit_load","lead","trail"]:
    b=best_dir_thr(m); print(f"  {m:<14} best {b[1]} {b[2]:>9.3f} -> caught {b[3]}/29, keepsFlagged {b[4]}/105")

# 3) abs(sanskrit_load) as a detector (big magnitude either sign = Sanskrit/transcript mismatch)
def best_abs(m):
    allv=sorted(set(abs(r[m]) for r in rows)); best=None
    for t in allv:
        pred=(lambda tt:(lambda r: abs(r[m])>=tt))(t)
        c,fl=eval_gate(pred); net=c-fl
        if best is None or (net,c,-fl)>(best[1]-best[2],best[1],-best[2]): best=(t,c,fl)
    return best
b=best_abs("sanskrit_load"); print(f"  abs(sanskrit_load) >= {b[0]:.3f} -> caught {b[1]}/29, keepsFlagged {b[2]}/105")

# 4) The suspected false-negative: clip 124 (kept, align_min -91.6). Where does it rank?
print("\n=== align_min ranking (most negative = worst alignment) ===")
ordered=sorted(rows, key=lambda r:r["align_min"])
for r in ordered[:12]:
    print(f"  clip {r['clip']:>3} align_min={r['align_min']:>9.3f} align_mean={r['align_mean']:>7.3f} "
          f"cer_core={r['cer_core']:>6.3f} {'CUT' if r['is_cut'] else 'KEEP'}")
# how many keeps are more extreme on align_min than the worst cut?
worst_cut_amin=min(r["align_min"] for r in cuts)
keeps_worse=[r for r in keeps if r["align_min"]<worst_cut_amin]
print(f"worst-cut align_min={worst_cut_amin:.3f}; keeps MORE negative than that: {[r['clip'] for r in keeps_worse]}")

# 5) Independent gate to surface false-negative SUSPECTS among keeps (NOT confirmed errors).
#    Use align_min, which is the pipeline's intended-but-OFF primary gate, independent of cer_core.
print("\n=== align_min as an INDEPENDENT suspect-surfacing gate on KEEPS ===")
for thr in [-50,-45,-40,-38,-35]:
    susp=[r["clip"] for r in keeps if r["align_min"]<=thr]
    cutscaught=sum(r["align_min"]<=thr for r in cuts)
    print(f"  align_min<={thr}: keeps flagged(suspects)={len(susp)} {susp} ; (also catches {cutscaught}/29 cuts)")

# 6) Correlation-ish: do non-cer metrics differ between cut and keep at all? medians + overlap
print("\n=== cut vs keep medians, and keep-side overlap into cut range ===")
for m in ["align_min","align_mean","wer","sanskrit_load"]:
    cv=[r[m] for r in cuts]; kv=[r[m] for r in keeps]
    print(f"  {m:<14} cut_med={median(cv):>8.3f} keep_med={median(kv):>8.3f}")
