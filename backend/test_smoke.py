"""
Quick smoke test — verifies the backend services work without the full HTTP stack.
Run: python test_smoke.py
"""
import sys, os
sys.path.insert(0, ".")

print("=== SynthGen Backend Smoke Test ===\n")

# 1. Config
from app.config import settings
print(f"[1] Config OK  — CTGAN_EPOCHS={settings.CTGAN_EPOCHS}")

# 2. Database
from app.database import create_tables, SessionLocal
create_tables()
print("[2] DB tables created OK")

# 3. Data processing
from app.services.data_processing import (
    load_file, profile_dataset, detect_sensitive_columns, preprocess_dataset
)
demo_path = os.path.join("data", "demo_patient_data.csv")
df = load_file(demo_path)
print(f"[3] Demo data loaded: {len(df)} rows x {len(df.columns)} cols")

profile = profile_dataset(df)
print(f"    Profiled {len(profile)} columns")

sensitive = detect_sensitive_columns(df)
print(f"    Sensitive columns detected: {sensitive}")

approved = [c for c in df.columns if c not in sensitive]
cleaned, summary = preprocess_dataset(df, approved)
print(f"    After preprocess: {len(cleaned)} rows")
print(f"    Missing handled: {list(summary['missing_handled'].keys())}")
print(f"    Duplicates removed: {summary['duplicates_removed']}")

# 4. Validation service (no generation needed — compare demo data to itself)
import pandas as pd
from app.services.validation import numerical_column_stats, categorical_column_stats, correlation_stats

numeric_cols = cleaned.select_dtypes(include=["number"]).columns.tolist()
if numeric_cols:
    stat = numerical_column_stats(cleaned[numeric_cols[0]], cleaned[numeric_cols[0]])
    print(f"[4] Validation (self): {numeric_cols[0]} dist_similarity={stat.get('distribution_similarity')}%")
else:
    print("[4] Validation skipped (no numeric cols)")

# 5. Privacy service (self-compare — should give 100% exact duplicates)
from app.services.privacy import check_exact_duplicates
exact = check_exact_duplicates(cleaned, cleaned)
print(f"[5] Privacy (self exact duplicates): {exact} (expected {len(cleaned)})")

# 6. Export service
from app.services.export import export_csv, export_xlsx
csv_bytes = export_csv(cleaned)
xlsx_bytes = export_xlsx(cleaned)
print(f"[6] Export: CSV={len(csv_bytes)} bytes, XLSX={len(xlsx_bytes)} bytes")

print("\n=== All checks passed ✓ ===")
