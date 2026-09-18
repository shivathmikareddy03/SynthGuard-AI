"""
Verify that datasets containing personal identifiers are:
  1. Accepted (not rejected)
  2. Classified correctly
  3. Preprocessed with identifiers stripped server-side
  4. Safe to feed into _prepare_for_sdv (no identifier columns reach CTGAN)

Run: python test_identifier_acceptance.py
"""
import sys, io, csv
sys.path.insert(0, ".")
import pandas as pd
import httpx

BASE = "http://localhost:8000/api"
client = httpx.Client(base_url=BASE, timeout=30)

PASS = 0
FAIL = 0

def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        sys.stdout.write("PASS  %s\n" % label)
        PASS += 1
    else:
        sys.stdout.write("FAIL  %s  %s\n" % (label, detail))
        FAIL += 1

# ── Build a dataset that contains real personal identifiers ──────────────────
rows = [
    ["Patient_ID","Patient_Name","Email","Phone","MRN",
     "visit_date","age","diabetes","systolic_bp","pain_score"],
]
# 10 rows minimum, 3 patients each with 3+ visits (longitudinal)
import random; random.seed(42)
for pid, pname, email, phone, mrn in [
    ("P001","John Doe","john@email.com","555-0001","MRN001"),
    ("P002","Jane Smith","jane@email.com","555-0002","MRN002"),
    ("P003","Bob Jones","bob@email.com","555-0003","MRN003"),
]:
    for i, date in enumerate(["2024-01-01","2024-02-01","2024-03-01","2024-04-01"]):
        rows.append([
            pid, pname, email, phone, mrn,
            date,
            random.randint(35,75),
            random.choice([True,False]),
            random.randint(110,160),
            round(random.uniform(0,8),1),
        ])

buf = io.StringIO()
csv.writer(buf).writerows(rows)
csv_bytes = buf.getvalue().encode()

sys.stdout.write("\n=== Dataset with personal identifiers ===\n")
sys.stdout.write("Columns: %s\n\n" % rows[0])

# ── 1. Upload — must be accepted, not rejected ────────────────────────────────
sys.stdout.write("--- Upload ---\n")
r = client.post("/dataset/upload",
    files={"file": ("patient_data_with_pii.csv", csv_bytes, "text/csv")})
check("Upload accepted (HTTP 200)", r.status_code == 200,
      f"got {r.status_code}: {r.text[:200]}")

if r.status_code != 200:
    sys.stdout.write("Cannot continue — upload was rejected\n"); sys.exit(1)

j = r.json()
ds_id = j["id"]
pc    = j["privacy_classification"]
lon   = j["longitudinal_info"]

# ── 2. Classification ─────────────────────────────────────────────────────────
sys.stdout.write("\n--- Classification ---\n")
sys.stdout.write("direct_identifiers:        %s\n" % pc["direct_identifiers"])
sys.stdout.write("longitudinal_linkage_keys: %s\n" % pc["longitudinal_linkage_keys"])
sys.stdout.write("temporal_columns:          %s\n" % pc["temporal_columns"])
sys.stdout.write("excluded_from_modeling:    %s\n" % pc["excluded_from_modeling"])
sys.stdout.write("longitudinal:              %s  type=%s\n" % (lon["is_longitudinal"], lon["dataset_type"]))

check("Patient_Name in direct_identifiers",   "Patient_Name" in pc["direct_identifiers"])
check("Email in direct_identifiers",          "Email" in pc["direct_identifiers"])
check("Phone in direct_identifiers",          "Phone" in pc["direct_identifiers"])
check("MRN in direct_identifiers",            "MRN" in pc["direct_identifiers"])
check("Patient_ID in longitudinal_linkage_keys", "Patient_ID" in pc["longitudinal_linkage_keys"])
check("Patient_ID NOT in direct_identifiers", "Patient_ID" not in pc["direct_identifiers"])
check("visit_date in temporal_columns",       "visit_date" in pc["temporal_columns"])
check("diabetes in sensitive_health",         "diabetes" in pc["sensitive_health_attributes"])
check("systolic_bp in sensitive_health",      "systolic_bp" in pc["sensitive_health_attributes"])
check("pain_score in sensitive_health",       "pain_score" in pc["sensitive_health_attributes"])
check("is_longitudinal = True",               lon["is_longitudinal"] is True)
check("unique_subjects = 3",                  lon["unique_subjects"] == 3)

# ── 3. Preprocess — identifiers removed server-side ──────────────────────────
sys.stdout.write("\n--- Preprocess ---\n")
all_cols = [c["name"] for c in j["columns"]]
# Send ALL columns including identifiers — server must strip them automatically
r2 = client.post(f"/dataset/{ds_id}/preprocess",
    json={"approved_columns": all_cols, "column_mapping": {}})
check("Preprocess accepted (HTTP 200)", r2.status_code == 200,
      f"got {r2.status_code}: {r2.text[:200]}")

if r2.status_code == 200:
    pp = r2.json()
    sys.stdout.write("columns_included: %s\n" % pp["columns_included"])
    sys.stdout.write("identifiers_removed: %s\n" % pp.get("identifiers_removed", "N/A"))
    pii_cols = {"Patient_Name","Email","Phone","MRN","Patient_ID"}
    leaked = pii_cols & set(pp["columns_included"])
    check("No PII columns in modeling columns",
          len(leaked) == 0, f"leaked: {leaked}")
    check("Patient_Name not in modeling columns",
          "Patient_Name" not in pp["columns_included"])
    check("Email not in modeling columns",
          "Email" not in pp["columns_included"])
    check("Patient_ID not in modeling columns",
          "Patient_ID" not in pp["columns_included"])
    check("Clinical columns retained (age, diabetes, systolic_bp)",
          all(c in pp["columns_included"] for c in ["age","diabetes","systolic_bp"]))

# ── 4. _prepare_for_sdv strips PII before CTGAN ──────────────────────────────
sys.stdout.write("\n--- _prepare_for_sdv internal check ---\n")
from app.services.synthetic_generation import _prepare_for_sdv

df_with_pii = pd.DataFrame({
    "Patient_Name": ["John","Jane","Bob"],
    "Email":        ["j@x.com","j2@x.com","b@x.com"],
    "Patient_ID":   ["P001","P002","P003"],
    "MRN":          ["M001","M002","M003"],
    "age":          [45,62,38],
    "diabetes":     [True,False,True],
    "systolic_bp":  [140,125,150],
})
sdv_df = _prepare_for_sdv(df_with_pii)
sys.stdout.write("SDV input columns: %s\n" % list(sdv_df.columns))

for pii_col in ["Patient_Name","Email","Patient_ID","MRN"]:
    check(f"{pii_col} stripped from CTGAN input",
          pii_col not in sdv_df.columns)
for keep in ["age","diabetes","systolic_bp"]:
    check(f"{keep} retained in CTGAN input",
          keep in sdv_df.columns)

sys.stdout.write("\n")
sys.stdout.write("="*50 + "\n")
sys.stdout.write("  %d passed,  %d failed\n" % (PASS, FAIL))
sys.stdout.write("  ALL PASSED\n" if FAIL == 0 else "  SOME FAILED\n")
sys.stdout.write("="*50 + "\n")
sys.exit(0 if FAIL == 0 else 1)
