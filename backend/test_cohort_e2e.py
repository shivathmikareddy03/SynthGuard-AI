"""
End-to-end cohort accuracy test.
Uploads demo dataset, generates with 3 requirements, verifies the
actual output CSV satisfies them.

Run: python test_cohort_e2e.py
"""
import sys, time, csv, io
sys.path.insert(0, ".")
import httpx
import pandas as pd

BASE   = "http://localhost:8000/api"
client = httpx.Client(base_url=BASE, timeout=60)

PASS = 0
FAIL = 0

def check(label, cond, detail=""):
    global PASS, FAIL
    sym = "PASS" if cond else "FAIL"
    sys.stdout.write(f"  {sym}  {label}" + (f"  [{detail}]" if detail else "") + "\n")
    if cond: PASS += 1
    else:    FAIL += 1

# ── 1. Upload + preprocess ────────────────────────────────────────────────────
sys.stdout.write("\n=== 1. Upload + Preprocess ===\n")
u = client.post("/dataset/upload-demo").json()
ds_id = u["id"]
cols  = [c["name"] for c in u["columns"] if not c["is_sensitive"]]
sys.stdout.write(f"Dataset: {ds_id[:12]}  columns: {cols}\n")

pp = client.post(f"/dataset/{ds_id}/preprocess",
    json={"approved_columns": cols, "column_mapping": {}}).json()
sys.stdout.write(f"Preprocessed: {pp['rows_after']} rows  cols: {pp['columns_included']}\n")
check("Preprocess OK", pp["rows_after"] > 0)

# ── 2. Cohort profile ─────────────────────────────────────────────────────────
sys.stdout.write("\n=== 2. Cohort Profile ===\n")
cp = client.get(f"/dataset/{ds_id}/cohort-profile").json()
profile = {c["name"]: c for c in cp["columns"]}
sys.stdout.write(f"Profile columns: {list(profile.keys())}\n")

# Verify Age is numerical and Diabetes is binary/boolean
age_col  = next((n for n in profile if "age"      in n.lower()), None)
diab_col = next((n for n in profile if "diabetes" in n.lower()), None)
act_col  = next((n for n in profile if "activity" in n.lower()), None)
sys.stdout.write(f"Age col: {age_col}  Diabetes col: {diab_col}  Activity col: {act_col}\n")
check("Age column found in profile",      age_col  is not None)
check("Diabetes column found in profile", diab_col is not None)
check("Activity column found in profile", act_col  is not None)

if not (age_col and diab_col and act_col):
    sys.stdout.write("Cannot proceed — required columns missing from profile.\n")
    sys.exit(1)

# Detect correct value for diabetic=True from actual profile
diab_prof = profile[diab_col]
sys.stdout.write(f"Diabetes profile: kind={diab_prof['kind']}  unique_values={diab_prof.get('unique_values')}\n")
true_val = "True"
if diab_prof.get("unique_values"):
    for v in diab_prof["unique_values"]:
        if v.lower() in ("true", "1", "yes"):
            true_val = v
            break
sys.stdout.write(f"Using diabetic value: '{true_val}'\n")

# Detect low-activity value
act_prof  = profile[act_col]
act_vals  = act_prof.get("unique_values", [])
low_val   = next((v for v in act_vals if v.lower() == "low"), act_vals[0] if act_vals else "Low")
sys.stdout.write(f"Using activity low value: '{low_val}'\n")

# ── 3. Generate with requirements ────────────────────────────────────────────
sys.stdout.write("\n=== 3. Generate (500 records, 50 epochs, 3 requirements) ===\n")

reqs = [
    {"feature": age_col,  "operator": "gte",   "value": 60,       "target_proportion": 0.40, "label": f"{age_col} >= 60"},
    {"feature": diab_col, "operator": "equal", "value": true_val, "target_proportion": 0.30, "label": f"{diab_col} = {true_val}"},
    {"feature": act_col,  "operator": "equal", "value": low_val,  "target_proportion": 0.35, "label": f"{act_col} = {low_val}"},
]
sys.stdout.write(f"Requirements sent:\n")
for r in reqs:
    sys.stdout.write(f"  {r['label']}  target={r['target_proportion']*100:.0f}%\n")

gen = client.post("/generate", json={
    "dataset_id":  ds_id,
    "num_records": 500,
    "model":       "CTGAN",
    "epochs":      50,
    "requirements": reqs,
}).json()
gen_id = gen["generation_id"]
sys.stdout.write(f"Generation ID: {gen_id[:12]}\n")
check("Generation accepted (got ID)", bool(gen_id))

# ── 4. Poll ───────────────────────────────────────────────────────────────────
sys.stdout.write("\n=== 4. Polling ===\n")
t0      = time.time()
timeout = 600
last_msg = ""
while True:
    s = client.get(f"/generation/{gen_id}/status").json()
    if s["progress_message"] != last_msg:
        sys.stdout.write(f"  [{int(time.time()-t0):3d}s] {s['progress']:3d}%  {s['progress_message']}\n")
        last_msg = s["progress_message"]
    if s["status"] == "done":
        sys.stdout.write(f"  Done in {time.time()-t0:.1f}s\n")
        break
    if s["status"] == "error":
        sys.stdout.write(f"  ERROR: {s['error_message']}\n")
        sys.exit(1)
    if time.time() - t0 > timeout:
        sys.stdout.write("  TIMEOUT\n"); sys.exit(1)
    time.sleep(3)

# ── 5. Check cohort_results in status response ─────────────────────────────
sys.stdout.write("\n=== 5. Cohort Results (from status response) ===\n")
cr = s.get("cohort_results", {})
sys.stdout.write(f"cohort_results keys: {list(cr.keys())}\n")
reqs_report = cr.get("requirements", [])
check("cohort_results.requirements exists", len(reqs_report) > 0,
      f"got keys: {list(cr.keys())}")

if reqs_report:
    for r in reqs_report:
        sys.stdout.write(f"  {r.get('label','?')}: req={r.get('requested_pct')}%  got={r.get('generated_pct')}%  diff={r.get('diff_pct')}pp  [{r.get('status')}]\n")
        check(f"{r.get('label')} generated_pct is not None", r.get("generated_pct") is not None)
        check(f"{r.get('label')} status is pass/warn (not column_missing)",
              r.get("status") in ("pass", "warn"),
              f"status={r.get('status')}")

# ── 6. Download CSV and measure actual proportions ───────────────────────────
sys.stdout.write("\n=== 6. Verify Actual Output CSV ===\n")
csv_bytes = client.get(f"/export/{gen_id}/csv").content
df = pd.read_csv(io.BytesIO(csv_bytes))
sys.stdout.write(f"Downloaded CSV: {len(df)} rows  cols: {list(df.columns)}\n")
check("CSV has correct row count", len(df) == 500, f"got {len(df)}")

# Measure actual proportions from the real CSV
def measure_pct(df, col, op, val):
    if col not in df.columns:
        return None
    s = df[col]
    if op == "gte":
        mask = pd.to_numeric(s, errors="coerce") >= float(val)
    elif op == "equal":
        mask = s.astype(str).str.lower().str.strip() == str(val).lower().strip()
    else:
        mask = pd.Series([False]*len(df))
    return round(mask.sum() / len(df) * 100, 2)

age_pct  = measure_pct(df, age_col,  "gte",   60)
diab_pct = measure_pct(df, diab_col, "equal", true_val)
act_pct  = measure_pct(df, act_col,  "equal", low_val)

sys.stdout.write(f"\nActual output proportions:\n")
sys.stdout.write(f"  {age_col} >= 60:      {age_pct}%   (requested 40%)\n")
sys.stdout.write(f"  {diab_col} = {true_val}: {diab_pct}%   (requested 30%)\n")
sys.stdout.write(f"  {act_col}  = {low_val}:   {act_pct}%   (requested 35%)\n")

check(f"{age_col} proportion in output > 0",  age_pct  is not None and age_pct  > 0)
check(f"{diab_col} proportion in output >= 0", diab_pct is not None and diab_pct >= 0)
check(f"{act_col} proportion in output > 0",  act_pct  is not None and act_pct  > 0)

# Tolerance: within 15pp (CTGAN with 50 epochs won't be perfect)
TOLERANCE = 15
check(f"{age_col} >= 60 within {TOLERANCE}pp of 40%",
      age_pct is not None and abs(age_pct - 40) <= TOLERANCE,
      f"got {age_pct}%")
check(f"{diab_col} within {TOLERANCE}pp of 30%",
      diab_pct is not None and abs(diab_pct - 30) <= TOLERANCE,
      f"got {diab_pct}%")
check(f"{act_col} within {TOLERANCE}pp of 35%",
      act_pct is not None and abs(act_pct - 35) <= TOLERANCE,
      f"got {act_pct}%")

# ── Summary ───────────────────────────────────────────────────────────────────
sys.stdout.write(f"\n{'='*50}\n")
sys.stdout.write(f"  {PASS} passed,  {FAIL} failed\n")
sys.stdout.write("  ALL PASSED\n" if FAIL == 0 else "  SOME FAILED\n")
sys.stdout.write("="*50 + "\n")
sys.exit(0 if FAIL == 0 else 1)
