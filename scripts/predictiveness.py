import sys, csv
sys.stdout.reconfigure(encoding="utf-8")
from statistics import median
try:
    from scripts.repo_paths import data_root
except ModuleNotFoundError:
    from repo_paths import data_root

METRICS = data_root(__file__) / "out" / "lecture1" / "qa_asr_report.tsv"
CUT_IDS = {1,5,11,15,16,30,35,36,48,49,51,58,66,70,79,80,81,85,93,98,99,100,101,109,115,117,118,123,125}

rows = []
with open(METRICS, encoding="utf-8") as f:
    r = csv.DictReader(f, delimiter="\t")
    for row in r:
        clip = int(row["clip"])
        rec = {"clip": clip, "is_cut": clip in CUT_IDS}
        for m in ["dur","align_min","align_mean","cer_raw","cer_core","wer","sanskrit_load","lead","trail"]:
            rec[m] = float(row[m])
        rec["status"] = row["status"]
        rows.append(rec)

cuts = [r for r in rows if r["is_cut"]]
keeps = [r for r in rows if not r["is_cut"]]
print(f"total={len(rows)} cuts={len(cuts)} keeps={len(keeps)}")
# sanity: status FAIL should equal cut set?
fail_status = {r["clip"] for r in rows if r["status"]=="FAIL"}
print("status==FAIL set == CUT_IDS:", fail_status==CUT_IDS, "| FAIL count:", len(fail_status))

def pct(vals, p):
    s = sorted(vals)
    if not s: return float('nan')
    k = (len(s)-1)*p
    lo = int(k); hi = min(lo+1, len(s)-1)
    return s[lo] + (s[hi]-s[lo])*(k-lo)

METRIC_LIST = ["align_min","align_mean","cer_raw","cer_core","wer","sanskrit_load","lead","trail"]

print("\n=== PER-METRIC distributions (cut vs keep) ===")
print(f"{'metric':<14}{'cut_med':>9}{'cut_p10':>9}{'cut_p90':>9}{'keep_med':>9}{'keep_p10':>9}{'keep_p90':>9}")
stats = {}
for m in METRIC_LIST:
    cv = [r[m] for r in cuts]; kv = [r[m] for r in keeps]
    cmed, kmed = median(cv), median(kv)
    stats[m] = {"cut_med":cmed,"keep_med":kmed,
                "cut_p10":pct(cv,0.10),"cut_p90":pct(cv,0.90),
                "keep_p10":pct(kv,0.10),"keep_p90":pct(kv,0.90)}
    print(f"{m:<14}{cmed:>9.3f}{stats[m]['cut_p10']:>9.3f}{stats[m]['cut_p90']:>9.3f}"
          f"{kmed:>9.3f}{stats[m]['keep_p10']:>9.3f}{stats[m]['keep_p90']:>9.3f}")

# ---- single-threshold gate search ----
# For each metric, try direction (cut if value >= thr) and (cut if value <= thr).
# Evaluate over candidate thresholds = all observed values. Score = catch many cuts, flag few keeps.
def eval_gate(predicate):
    caught = sum(1 for r in cuts if predicate(r))
    flagged = sum(1 for r in keeps if predicate(r))
    return caught, flagged

print("\n=== SINGLE-THRESHOLD GATE search ===")
best = []
for m in METRIC_LIST:
    allvals = sorted(set(r[m] for r in rows))
    for direction in [">=", "<="]:
        for thr in allvals:
            if direction == ">=":
                pred = (lambda mm,t: (lambda r: r[mm] >= t))(m, thr)
            else:
                pred = (lambda mm,t: (lambda r: r[mm] <= t))(m, thr)
            caught, flagged = eval_gate(pred)
            best.append((m, direction, thr, caught, flagged))

# For reporting: for each metric+direction, find threshold maximizing caught - penalty*flagged,
# and also the "max catch with min flags" frontier. Let's pull, per metric, the threshold that
# catches the most cuts while flagging <= some keep budgets, plus best F-like tradeoff.
# Use objective: maximize caught, tie-break minimize flagged. Also compute a balanced one.
def summarize_metric(m):
    rowsm = [b for b in best if b[0]==m]
    # best catch-all-feasible: maximize (caught - flagged) then caught
    by_net = max(rowsm, key=lambda b: (b[3]-b[4], b[3], -b[4]))
    return by_net

print("\nPer-metric best single gate by (caught - keeps_flagged):")
print(f"{'metric':<14}{'dir':>4}{'thr':>10}{'caught/29':>11}{'keepsFlag/105':>15}")
single_best_overall = None
for m in METRIC_LIST:
    b = summarize_metric(m)
    print(f"{m:<14}{b[1]:>4}{b[2]:>10.3f}{b[3]:>9}/29{b[4]:>13}/105")
    net = b[3]-b[4]
    if single_best_overall is None or (net, b[3], -b[4]) > (single_best_overall[3]-single_best_overall[4], single_best_overall[3], -single_best_overall[4]):
        single_best_overall = b

print("\nBEST SINGLE GATE overall (max net = caught - flagged):")
print(single_best_overall)

# Also show, for the best metric, the full tradeoff frontier (caught vs flagged) by sweeping threshold
print("\nFrontier for align_min (cut if align_min <= thr):")
am = sorted(set(r["align_min"] for r in rows))
seen=set()
for thr in am:
    caught, flagged = eval_gate(lambda r,t=thr: r["align_min"] <= t)
    key=(caught,flagged)
    if key not in seen:
        seen.add(key)
for thr in am:
    caught, flagged = eval_gate(lambda r,t=thr: r["align_min"] <= t)
    if caught in (5,10,15,20,25,29) :
        print(f"  thr<={thr:8.2f} -> caught {caught}/29, keepsFlagged {flagged}/105")

# ---- combined gate search (2-3 metrics, OR of single-threshold rules) ----
# Build candidate atomic rules (metric, dir, thr). To keep it tractable use quantile-based thresholds.
def candidate_thresholds(m):
    vals = sorted(set(r[m] for r in rows))
    # use cut-group informed thresholds plus deciles
    qs = [pct([r[m] for r in rows], p) for p in [0.5,0.6,0.7,0.75,0.8,0.85,0.9,0.95]]
    qsl = [pct([r[m] for r in rows], p) for p in [0.05,0.1,0.15,0.2,0.25,0.3,0.4]]
    cand = sorted(set(round(x,4) for x in qs+qsl))
    return cand

atoms = []
for m in METRIC_LIST:
    for thr in candidate_thresholds(m):
        for direction in [">=","<="]:
            pred = (lambda mm,t,d: (lambda r: r[mm] >= t if d==">=" else r[mm] <= t))(m,thr,direction)
            caught, flagged = eval_gate(pred)
            # keep only atoms that catch at least a few cuts and aren't trivially flagging everything
            if caught >= 3 and flagged <= 70:
                atoms.append((m,direction,thr,pred,caught,flagged))

print(f"\nNum candidate atoms: {len(atoms)}")

# Search 1-,2-,3-combinations using OR logic. Objective: maximize caught, then minimize flagged.
import itertools
def eval_or(preds):
    caught = sum(1 for r in cuts if any(p(r) for p in preds))
    flagged = sum(1 for r in keeps if any(p(r) for p in preds))
    return caught, flagged

best_combo = {1:None,2:None,3:None}
def better(a,b):
    # a,b are tuples (caught, flagged, label). higher caught, then lower flagged
    if b is None: return True
    if a[0]!=b[0]: return a[0]>b[0]
    return a[1]<b[1]

# limit atoms to distinct metric to encourage diverse combos; but allow same metric different thr too.
for combo in itertools.combinations(atoms, 1):
    preds=[c[3] for c in combo]
    caught,flagged=eval_or(preds)
    lbl=[(c[0],c[1],c[2]) for c in combo]
    if better((caught,flagged,lbl), best_combo[1]):
        best_combo[1]=(caught,flagged,lbl)

# For 2 and 3, prune atoms to a strong subset (top by caught-flagged) to keep tractable
atoms_sorted = sorted(atoms, key=lambda a:(a[4]-a[5]), reverse=True)[:40]
for combo in itertools.combinations(atoms_sorted, 2):
    if combo[0][0]==combo[1][0] and combo[0][1]==combo[1][1]:
        continue
    preds=[c[3] for c in combo]
    caught,flagged=eval_or(preds)
    lbl=[(c[0],c[1],c[2]) for c in combo]
    if better((caught,flagged,lbl), best_combo[2]):
        best_combo[2]=(caught,flagged,lbl)

for combo in itertools.combinations(atoms_sorted, 3):
    preds=[c[3] for c in combo]
    caught,flagged=eval_or(preds)
    lbl=[(c[0],c[1],c[2]) for c in combo]
    if better((caught,flagged,lbl), best_combo[3]):
        best_combo[3]=(caught,flagged,lbl)

print("\n=== BEST COMBINED (OR) GATES ===")
for k in [1,2,3]:
    print(f"{k}-rule: caught {best_combo[k][0]}/29, keepsFlagged {best_combo[k][1]}/105, rules={best_combo[k][2]}")

# Also test specific intuitive combos
print("\n=== INTUITIVE combos ===")
def show(label, pred):
    caught,flagged=eval_gate(pred)
    print(f"  {label}: caught {caught}/29, keepsFlagged {flagged}/105")

show("cer_core>=0.86", lambda r: r["cer_core"]>=0.86)
show("cer_core>=0.85", lambda r: r["cer_core"]>=0.85)
show("cer_core>=0.86 OR wer>=1.5", lambda r: r["cer_core"]>=0.86 or r["wer"]>=1.5)
show("cer_core>=0.86 OR abs(sanskrit_load)>=0.4", lambda r: r["cer_core"]>=0.86 or abs(r["sanskrit_load"])>=0.4)
show("cer_core>=0.86 OR align_min<=-40", lambda r: r["cer_core"]>=0.86 or r["align_min"]<=-40)
show("align_min<=-40", lambda r: r["align_min"]<=-40)

# CER distribution overlap check (Sanskrit bias)
print("\n=== CER overlap (are cut & keep cer distributions even different?) ===")
for m in ["cer_raw","cer_core","sanskrit_load"]:
    cv=sorted(r[m] for r in cuts); kv=sorted(r[m] for r in keeps)
    print(f"{m}: cut[min,med,max]=({min(cv):.3f},{median(cv):.3f},{max(cv):.3f}) "
          f"keep[min,med,max]=({min(kv):.3f},{median(kv):.3f},{max(kv):.3f})")

# how many keeps have cer_core >= cut median?
cm = median([r["cer_core"] for r in cuts])
keep_above = sum(1 for r in keeps if r["cer_core"]>=cm)
print(f"keeps with cer_core >= cut-median({cm:.3f}): {keep_above}/105")
