"""
Dataset upload, profiling, and preprocessing routes.
"""
import json
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.database import DatasetRecord, get_db
from app.services.data_processing import (
    classify_all_columns,
    create_dataset_record,
    detect_longitudinal_structure,
    load_file,
    preprocess_dataset,
    profile_dataset,
    save_preprocessed,
    save_upload,
)

router = APIRouter()

MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _build_upload_response(record: DatasetRecord, df) -> dict:
    """Build the standard upload/profile response including full privacy classification
    and longitudinal structure detection."""
    col_profiles   = profile_dataset(df)
    classification = classify_all_columns(df)
    longitudinal   = detect_longitudinal_structure(df, classification)
    direct_ids     = classification["direct_identifiers"]

    for cp in col_profiles:
        cp["is_sensitive"] = cp["name"] in direct_ids

    return {
        "id":          record.id,
        "filename":    record.original_filename,
        "num_rows":    record.num_rows,
        "num_columns": record.num_columns,
        "columns":     col_profiles,
        # Backward-compat field: direct identifiers only
        "sensitive_columns":     direct_ids,
        # Full structured classification (4-tier)
        "privacy_classification": classification,
        # Longitudinal structure detection
        "longitudinal_info": longitudinal,
        "status":     record.status,
        "created_at": record.created_at.isoformat(),
    }


# ── Upload ─────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(400, "Unsupported file type. Upload a .csv or .xlsx file.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Uploaded file is empty.")
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.")

    try:
        ds_id, saved_path = save_upload(content, filename)
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {e}")

    try:
        df = load_file(saved_path)
    except Exception as e:
        os.remove(saved_path)
        raise HTTPException(422, f"Could not parse file: {e}")

    if df.empty or len(df.columns) == 0:
        os.remove(saved_path)
        raise HTTPException(422, "File has no data.")

    if len(df) < 10:
        raise HTTPException(422, f"Dataset has only {len(df)} rows. Need at least 10.")

    record = create_dataset_record(db, ds_id, filename, saved_path, df)
    return _build_upload_response(record, df)


# ── Demo dataset ───────────────────────────────────────────────────────────────

@router.post("/upload-demo")
async def upload_demo(db: Session = Depends(get_db)):
    demo_path = os.path.join("data", "demo_patient_data.csv")
    if not os.path.exists(demo_path):
        raise HTTPException(404, "Demo dataset not found on server.")

    with open(demo_path, "rb") as f:
        content = f.read()

    ds_id, saved_path = save_upload(content, "demo_patient_data.csv")

    try:
        df = load_file(saved_path)
    except Exception as e:
        raise HTTPException(500, f"Could not parse demo file: {e}")

    record = create_dataset_record(db, ds_id, "demo_patient_data.csv", saved_path, df)
    resp = _build_upload_response(record, df)
    resp["is_demo"] = True
    return resp


# ── Profile ────────────────────────────────────────────────────────────────────

@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: str, db: Session = Depends(get_db)):
    record = db.get(DatasetRecord, dataset_id)
    if not record:
        raise HTTPException(404, "Dataset not found.")

    direct_ids = json.loads(record.sensitive_columns or "[]")
    col_types   = json.loads(record.column_types or "{}")
    missing     = json.loads(record.missing_counts or "{}")
    unique      = json.loads(record.unique_counts or "{}")

    upload_path = os.path.join(settings.UPLOAD_DIR, record.filename)
    col_profiles = []
    classification = {}
    longitudinal   = {}
    try:
        df = load_file(upload_path)
        col_profiles   = profile_dataset(df)
        classification = classify_all_columns(df)
        longitudinal   = detect_longitudinal_structure(df, classification)
        direct_ids     = classification["direct_identifiers"]
        for cp in col_profiles:
            cp["is_sensitive"] = cp["name"] in direct_ids
    except Exception:
        names = json.loads(record.column_names or "[]")
        for name in names:
            col_profiles.append({
                "name": name,
                "dtype": col_types.get(name, "unknown"),
                "missing_count": missing.get(name, 0),
                "missing_pct": 0,
                "unique_count": unique.get(name, 0),
                "sample_values": [],
                "is_sensitive": name in direct_ids,
            })

    return {
        "id":          record.id,
        "filename":    record.original_filename,
        "num_rows":    record.num_rows,
        "num_columns": record.num_columns,
        "columns":     col_profiles,
        "sensitive_columns":     direct_ids,
        "privacy_classification": classification,
        "longitudinal_info":     longitudinal,
        "approved_columns": json.loads(record.approved_columns or "[]"),
        "status": record.status,
        "preprocessing_summary": (
            json.loads(record.preprocessing_summary)
            if record.preprocessing_summary else {}
        ),
        "created_at": record.created_at.isoformat(),
    }


# ── Preprocess ─────────────────────────────────────────────────────────────────

@router.post("/{dataset_id}/preprocess")
def preprocess(
    dataset_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    record = db.get(DatasetRecord, dataset_id)
    if not record:
        raise HTTPException(404, "Dataset not found.")

    approved_columns = body.get("approved_columns", [])
    column_mapping   = body.get("column_mapping", {})

    if not approved_columns:
        raise HTTPException(400, "approved_columns must not be empty.")

    upload_path = os.path.join(settings.UPLOAD_DIR, record.filename)
    try:
        df = load_file(upload_path)
    except Exception as e:
        raise HTTPException(500, f"Could not load dataset: {e}")

    # Server-side safety: ensure neither direct identifiers nor longitudinal
    # linkage keys slip into the modeling columns, regardless of what the
    # frontend sent.  Both categories are excluded from modeling.
    classification = classify_all_columns(df)
    must_exclude = set(classification["excluded_from_modeling"])  # direct + linkage keys
    approved_columns = [c for c in approved_columns if c not in must_exclude]

    if not approved_columns:
        raise HTTPException(
            400,
            "No modeling columns remain after removing direct personal identifiers "
            "and linkage keys. Please review the column selection.",
        )

    missing_cols = [c for c in approved_columns if c not in df.columns]
    if missing_cols:
        raise HTTPException(400, f"Columns not found in dataset: {missing_cols}")

    try:
        cleaned_df, summary = preprocess_dataset(df, approved_columns, column_mapping)
    except Exception as e:
        raise HTTPException(500, f"Preprocessing failed: {e}")

    if len(cleaned_df) < 50:
        raise HTTPException(
            422,
            f"After preprocessing only {len(cleaned_df)} rows remain. "
            "Need at least 50 for synthetic generation.",
        )

    preprocessed_path = save_preprocessed(cleaned_df, dataset_id)

    record.approved_columns     = json.dumps(approved_columns)
    record.preprocessing_summary = json.dumps(summary)
    record.preprocessed_path    = preprocessed_path
    record.status               = "preprocessed"
    db.commit()

    removed_identifiers = sorted(must_exclude & set(df.columns))
    return {
        "dataset_id": dataset_id,
        "rows_before": summary["rows_before"],
        "rows_after":  summary["rows_after"],
        "missing_handled":   summary["missing_handled"],
        "duplicates_removed": summary["duplicates_removed"],
        "columns_excluded":  summary["columns_excluded"],
        "columns_included":  summary["columns_included"],
        "identifiers_removed": removed_identifiers,
        "status": "preprocessed",
    }
