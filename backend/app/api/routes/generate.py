"""
Synthetic data generation routes.
Generation runs in a background thread so the API returns immediately.
"""
import json
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import DatasetRecord, GenerationRecord, get_db
from app.services.synthetic_generation import create_generation_record, run_generation

router = APIRouter()


# ── Start generation ──────────────────────────────────────────────────────────

@router.post("/generate")
def start_generation(body: dict, db: Session = Depends(get_db)):
    dataset_id = body.get("dataset_id")
    if not dataset_id:
        raise HTTPException(400, "dataset_id is required.")

    dataset = db.get(DatasetRecord, dataset_id)
    if not dataset:
        raise HTTPException(404, "Dataset not found.")
    if dataset.status != "preprocessed":
        raise HTTPException(400, "Dataset must be preprocessed before generation.")
    if not dataset.preprocessed_path:
        raise HTTPException(400, "No preprocessed file found. Run preprocessing first.")

    num_records = int(body.get("num_records", 1000))
    if num_records < 100:
        raise HTTPException(400, "num_records must be at least 100.")
    if num_records > 500000:
        raise HTTPException(400, "num_records must be at most 500,000.")

    model = body.get("model", "CTGAN").upper()
    if model not in ("CTGAN", "TVAE", "GAUSSIANCOPULA"):
        model = "CTGAN"

    epochs = int(body.get("epochs", settings.CTGAN_EPOCHS))
    epochs = max(10, min(epochs, 2000))

    cohort_raw = body.get("cohort")
    cohort_config = None
    if cohort_raw:
        # Validate percentages
        for key in ("older_patients_pct", "diabetic_pct"):
            val = cohort_raw.get(key)
            if val is not None:
                fval = float(val)
                if not (0 <= fval <= 100):
                    raise HTTPException(400, f"{key} must be between 0 and 100.")
        if cohort_raw.get("activity_distribution"):
            total = sum(float(v) for v in cohort_raw["activity_distribution"].values())
            if total <= 0:
                raise HTTPException(400, "activity_distribution values must sum > 0.")
        cohort_config = cohort_raw

    # ── New: generic dynamic cohort requirements ──────────────────────────────
    dynamic_requirements = body.get("requirements")
    if dynamic_requirements:
        # Validate each requirement generically
        for i, req in enumerate(dynamic_requirements):
            if not isinstance(req, dict):
                raise HTTPException(400, f"requirements[{i}] must be an object.")
            if not req.get("feature"):
                raise HTTPException(400, f"requirements[{i}].feature is required.")
            if not req.get("operator"):
                raise HTTPException(400, f"requirements[{i}].operator is required.")
            if req.get("value") is None:
                raise HTTPException(400, f"requirements[{i}].value is required.")
            tp = req.get("target_proportion")
            if tp is None:
                raise HTTPException(400, f"requirements[{i}].target_proportion is required.")
            if not (0.0 <= float(tp) <= 1.0):
                raise HTTPException(400,
                    f"requirements[{i}].target_proportion must be between 0 and 1 (got {tp}).")
        # Store requirements inside cohort_config so run_generation can access them
        if cohort_config is None:
            cohort_config = {}
        cohort_config["_dynamic_requirements"] = dynamic_requirements

    gen_record = create_generation_record(db, dataset_id, num_records, model, cohort_config)

    # Run in background thread (prototype approach; production would use a task queue)
    def _run():
        # Each thread gets its own DB session
        from app.database import SessionLocal
        thread_db = SessionLocal()
        try:
            run_generation(
                gen_id=gen_record.id,
                dataset_id=dataset_id,
                source_path=dataset.preprocessed_path,
                num_records=num_records,
                model_name=model,
                epochs=epochs,
                cohort_config=cohort_config,
                db=thread_db,
            )
        except Exception:
            pass  # errors are persisted to DB inside run_generation
        finally:
            thread_db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {
        "generation_id": gen_record.id,
        "dataset_id": dataset_id,
        "status": "pending",
        "num_requested": num_records,
        "model": model,
        "message": "Generation started. Poll /api/generation/{id}/status for progress.",
    }


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/generation/{generation_id}/status")
def generation_status(generation_id: str, db: Session = Depends(get_db)):
    record = db.get(GenerationRecord, generation_id)
    if not record:
        raise HTTPException(404, "Generation job not found.")

    cohort_results = {}
    if record.cohort_results:
        try:
            cohort_results = json.loads(record.cohort_results)
        except Exception:
            pass

    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "status": record.status,
        "progress": record.progress or 0,
        "progress_message": record.progress_message or "",
        "model_used": record.model_used,
        "num_requested": record.num_requested,
        "num_generated": record.num_generated,
        "generation_time_seconds": record.generation_time_seconds,
        "cohort_results": cohort_results,
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat(),
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


# ── Preview synthetic records ─────────────────────────────────────────────────

@router.get("/generation/{generation_id}/preview")
def preview_synthetic(
    generation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=500),
    search: Optional[str] = Query(None),
    sort_col: Optional[str] = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    record = db.get(GenerationRecord, generation_id)
    if not record:
        raise HTTPException(404, "Generation job not found.")
    if record.status != "done":
        raise HTTPException(400, f"Generation is not complete (status: {record.status}).")
    if not record.output_path:
        raise HTTPException(500, "Output file missing.")

    import pandas as pd
    try:
        df = pd.read_csv(record.output_path)
    except Exception as e:
        raise HTTPException(500, f"Could not read synthetic dataset: {e}")

    # Search filter across all string columns
    if search:
        mask = df.astype(str).apply(
            lambda col: col.str.contains(search, case=False, na=False)
        ).any(axis=1)
        df = df[mask]

    # Sort
    if sort_col and sort_col in df.columns:
        ascending = sort_dir.lower() != "desc"
        df = df.sort_values(sort_col, ascending=ascending)

    total = len(df)
    start = (page - 1) * page_size
    end = start + page_size
    page_df = df.iloc[start:end]

    # Convert NaN to None for JSON
    rows = page_df.where(page_df.notna(), other=None).to_dict(orient="records")

    return {
        "generation_id": generation_id,
        "columns": list(df.columns),
        "rows": rows,
        "total_rows": total,
        "page": page,
        "page_size": page_size,
    }


# ── List all generations for a dataset ───────────────────────────────────────

@router.get("/generations")
def list_generations(
    dataset_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(GenerationRecord)
    if dataset_id:
        query = query.filter(GenerationRecord.dataset_id == dataset_id)
    records = query.order_by(GenerationRecord.created_at.desc()).limit(20).all()

    return [
        {
            "id": r.id,
            "dataset_id": r.dataset_id,
            "status": r.status,
            "model_used": r.model_used,
            "num_requested": r.num_requested,
            "num_generated": r.num_generated,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]
