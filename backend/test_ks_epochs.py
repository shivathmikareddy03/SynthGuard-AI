"""
Test KS pass rate across different epoch counts.
Generates with no cohort constraints to measure pure distribution fidelity.
Run: python test_ks_epochs.py
"""
import sys, time
sys.path.insert(0, ".")
import httpx
from scipy import stats
import numpy as np
import pandas as pd

BASE = "http://localhost:8000/api"
client = httpx.Client(base_url=BASE, timeout=30)

def upload_demo():
    r = client.post("/dataset/upload-demo")
    assert r.status_code == 200, r.text
    return r.json()["id"]

def preprocess(ds_id):
    r = client.get(f"/dataset/{ds_id}/profile")
    cols = [c["name"] for c in r.json()["columns"] if not c["is_sensitive"]]
    r2 = client.post(f"/dataset/{ds_id}/preprocess",
                     json={"approved_columns": cols, "column_mapping": {}})
    assert r2.status_code == 200, r2.text
    return r2.json()

def generate_and_validate(ds_id, epochs, num_records=2000):
    r = client.post("/generate", json={
        "dataset_id": ds_id,
        "num_records": num_records,
        "model": "CTGAN",
        "epochs": epochs,
        # No cohort — test pure distribution fidelity
    })
    assert r.status_code == 200, r.text
    gen_id = r.json()["generation_id"]
    print(f"  Generation started: {gen_id[:12]}  epochs={epochs}")

    # Poll
    t0 = time.time()
    while True:
        s = client.get(f"/generation/{gen_id}/status").json()
        if s["status"] == "done":
            print(f"  Done in {time.time()-t0:.0f}s")
            break
        if s["status"] == "error":
            print(f"  ERROR: {s['error_message']}")
            return None, None
        time.sleep(4)

    # Validate (force re-run)
    try:
        client.post(f"/validation/{gen_id}/rerun", timeout=60)
    except Exception:
        pass
    vr = client.post(f"/validation/{gen_id}", timeout=60)
    if vr.status_code != 200:
        vr = client.get(f"/validation/{gen_id}/report", timeout=60)
    val = vr.json()
    return s, val

def print_ks_table(val):
    num_stats = val.get("numerical_stats", [])
    scores = val.get("overall_scores", {})
    print(f"  KS pass rate: {scores.get('ks_pass_rate', '?')}%"
          f"  ({scores.get('ks_passed_columns','?')}/{scores.get('ks_tested_columns','?')} columns)")
    for s in num_stats:
        ks_s = s.get("ks_statistic")
        ks_p = s.get("ks_pvalue")
        status = s.get("ks_status", "?")
        n_src = s.get("source_n", "?")
        n_cap = s.get("ks_capped_synth_n", "?")
        cohort = " ← cohort-targeted" if s.get("cohort_affected") else ""
        print(f"    {s['column']:<35} n_src={str(n_src):<5} n_cap={str(n_cap):<5} "
              f"stat={ks_s:.4f if ks_s is not None else '?':>8}  "
              f"p={ks_p:.6f if ks_p is not None else '?':>10}  "
              f"{status.upper()}{cohort}")

print("\n===  KS Test Investigation — SynthGen  ===")
print("(no cohort constraints; testing pure distribution fidelity)\n")

ds_id = upload_demo()
print(f"Dataset: {ds_id[:12]}")
preprocess(ds_id)
print("Preprocessed OK\n")

for epochs in [300]:
    print(f"\n{'─'*60}")
    print(f"CTGAN epochs = {epochs}")
    gen_status, val = generate_and_validate(ds_id, epochs=epochs, num_records=2000)
    if val:
        print_ks_table(val)

print("\n=== Done ===")
