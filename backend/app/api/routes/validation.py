"""
Statistical validation routes.
"""
import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import DatasetRecord, GenerationRecord, ValidationRecord, get_db
from app.services.validation import run_validation

router = APIRouter()
logger = logging.getLogger("synthgen.routes.validation")


def _resolve_source_path(gen_record: GenerationRecord, dataset: DatasetRecord) -> str:
    """
    Return the correct source CSV path for validation.

    Prefer source_for_validation_path (the generation-ready, ordinal-encoded copy)
    so that source and synthetic are in the same dtype/scale space.
    Fall back to the raw preprocessed CSV only when the generation-ready copy
    doesn't exist (e.g. for generations created before this fix).
    """
    val_path = getattr(gen_record, "source_for_validation_path", None)
    if val_path and os.path.exists(val_path):
        logger.info("Using generation-ready source for validation: %s", val_path)
        return val_path

    # Fallback: raw preprocessed CSV
    if dataset.preprocessed_path and os.path.exists(dataset.preprocessed_path):
        logger.warning(
            "source_for_validation_path not found; falling back to preprocessed CSV. "
            "Re-run generation to get accurate KS results."
        )
        return dataset.preprocessed_path

    raise HTTPException(500, "Source CSV not found. Re-run preprocessing and generation.")


def _cohort_columns(gen_record: GenerationRecord) -> List[str]:
    """Extract the column names that were targeted by cohort constraints."""
    cols = []
    if not gen_record.cohort_config:
        return cols
    try:
        cfg = json.loads(gen_record.cohort_config)
        for key in ("age_column", "diabetes_column", "activity_column"):
            v = cfg.get(key)
            if v:
                cols.append(v)
    except Exception:
        pass
    return cols


@router.post("/{generation_id}")
def trigger_validation(generation_id: str, db: Session = Depends(get_db)):
    gen_record = db.get(GenerationRecord, generation_id)
    if not gen_record:
        raise HTTPException(404, "Generation job not found.")
    if gen_record.status != "done":
        raise HTTPException(400, f"Generation must be complete before validation (status: {gen_record.status}).")

    # Return existing if already computed
    existing = (
        db.query(ValidationRecord)
        .filter(ValidationRecord.generation_id == generation_id)
        .first()
    )
    if existing:
        return _format_validation(existing)

    dataset = db.get(DatasetRecord, gen_record.dataset_id)
    if not dataset:
        raise HTTPException(400, "Source dataset record not found.")

    source_path = _resolve_source_path(gen_record, dataset)

    if not os.path.exists(gen_record.output_path or ""):
        raise HTTPException(500, "Synthetic output file missing from disk.")

    cohort_cols = _cohort_columns(gen_record)

    try:
        val_record = run_validation(
            generation_id=generation_id,
            dataset_id=gen_record.dataset_id,
            source_path=source_path,
            synthetic_path=gen_record.output_path,
            db=db,
            cohort_columns=cohort_cols,
        )
    except Exception as e:
        raise HTTPException(500, f"Validation failed: {e}")

    return _format_validation(val_record)


@router.post("/{generation_id}/rerun")
def rerun_validation(generation_id: str, db: Session = Depends(get_db)):
    """Force re-run validation even if a previous result exists."""
    gen_record = db.get(GenerationRecord, generation_id)
    if not gen_record:
        raise HTTPException(404, "Generation job not found.")
    if gen_record.status != "done":
        raise HTTPException(400, f"Generation must be complete (status: {gen_record.status}).")

    # Delete existing validation record
    existing = (
        db.query(ValidationRecord)
        .filter(ValidationRecord.generation_id == generation_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()

    dataset = db.get(DatasetRecord, gen_record.dataset_id)
    if not dataset:
        raise HTTPException(400, "Source dataset record not found.")

    source_path  = _resolve_source_path(gen_record, dataset)
    cohort_cols  = _cohort_columns(gen_record)

    try:
        val_record = run_validation(
            generation_id=generation_id,
            dataset_id=gen_record.dataset_id,
            source_path=source_path,
            synthetic_path=gen_record.output_path,
            db=db,
            cohort_columns=cohort_cols,
        )
    except Exception as e:
        raise HTTPException(500, f"Validation failed: {e}")

    return _format_validation(val_record)


@router.get("/{generation_id}/report")
def get_validation_report(generation_id: str, db: Session = Depends(get_db)):
    val_record = (
        db.query(ValidationRecord)
        .filter(ValidationRecord.generation_id == generation_id)
        .first()
    )
    if not val_record:
        raise HTTPException(404, "Validation report not found. Run validation first.")
    return _format_validation(val_record)


def _format_validation(record: ValidationRecord) -> dict:
    return {
        "validation_id":     record.id,
        "generation_id":     record.generation_id,
        "numerical_stats":   json.loads(record.numerical_stats   or "[]"),
        "categorical_stats": json.loads(record.categorical_stats or "[]"),
        "correlation_stats": json.loads(record.correlation_stats or "[]"),
        "overall_scores":    json.loads(record.overall_scores    or "{}"),
        "created_at":        record.created_at.isoformat(),
    }
