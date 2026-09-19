"""
Cohort-profile endpoint.
Returns per-column metadata needed by the dynamic cohort builder UI.
No ML, no training — purely derived from the preprocessed CSV.
"""
import json
import os
from typing import List

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import DatasetRecord, get_db
from app.services.data_processing import (
    classify_all_columns,
    infer_column_type,
    load_file,
)

router = APIRouter()

# Ordinal keyword sets for lightweight detection
_ORDINAL_KEYWORDS = [
    {"low", "medium", "high"},
    {"low", "moderate", "high"},
    {"never", "sometimes", "often", "always"},
    {"none", "mild", "moderate", "severe"},
    {"poor", "fair", "good", "excellent"},
    {"strongly disagree", "disagree", "neutral", "agree", "strongly agree"},
    {"1", "2", "3", "4", "5"},
]

_ORDINAL_ORDER = {
    "low": 0, "moderate": 1, "medium": 1, "high": 2,
    "never": 0, "sometimes": 1, "often": 2, "always": 3,
    "none": 0, "mild": 1, "severe": 2,
    "poor": 0, "fair": 1, "good": 2, "excellent": 3,
    "strongly disagree": 0, "disagree": 1, "neutral": 2, "agree": 3, "strongly agree": 4,
}


def _safe(v):
    """Convert numpy scalars to plain Python for JSON serialisation."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return v


def _classify_col_kind(series: pd.Series, dtype_str: str) -> str:
    """
    Determine the UI-level kind for a column.
    Returns: 'numerical' | 'binary' | 'ordinal' | 'categorical'
    """
    if dtype_str in ("integer", "float"):
        return "numerical"

    n_unique = series.nunique(dropna=True)

    # Binary: exactly 2 unique non-null values
    if n_unique == 2:
        return "binary"

    # Ordinal check: unique values (lowercased) match a known ordinal set
    vals_lower = {str(v).lower().strip() for v in series.dropna().unique()}
    for known_set in _ORDINAL_KEYWORDS:
        if vals_lower == known_set or vals_lower.issubset(known_set):
            return "ordinal"

    return "categorical"


def profile_column_for_cohort(series: pd.Series, dtype_str: str) -> dict:
    """
    Build the per-column cohort metadata object.
    """
    kind = _classify_col_kind(series, dtype_str)
    result: dict = {
        "name": series.name,
        "dtype": dtype_str,
        "kind": kind,
    }

    if kind == "numerical":
        clean = pd.to_numeric(series, errors="coerce").dropna()
        result["min"]    = _safe(float(clean.min()))   if len(clean) else None
        result["max"]    = _safe(float(clean.max()))   if len(clean) else None
        result["mean"]   = _safe(float(clean.mean()))  if len(clean) else None
        result["unique_count"] = int(series.nunique(dropna=True))

    elif kind in ("binary", "categorical", "ordinal"):
        raw_vals = [str(v) for v in series.dropna().unique()]
        # Deduplicate, sort for stability
        unique_vals = sorted(set(raw_vals))
        result["unique_values"] = unique_vals
        result["unique_count"]  = len(unique_vals)

        if kind == "ordinal":
            # Attach suggested ordering where known
            ordered = sorted(
                unique_vals,
                key=lambda v: _ORDINAL_ORDER.get(v.lower().strip(), 999),
            )
            result["ordinal_order"] = ordered

    return result


def _get_modeling_df(record: DatasetRecord) -> pd.DataFrame:
    """
    Return the preprocessed (modeling) dataframe — the one CTGAN actually trains on.
    Falls back to the raw upload if preprocessed not available.
    """
    # Prefer the preprocessed file (already stripped of identifiers)
    if record.preprocessed_path and os.path.exists(record.preprocessed_path):
        return pd.read_csv(record.preprocessed_path)

    # Fallback: load raw and apply classification to strip identifiers
    upload_path = os.path.join(settings.UPLOAD_DIR, record.filename)
    df = load_file(upload_path)
    classification = classify_all_columns(df)
    exclude = set(classification["excluded_from_modeling"])
    return df[[c for c in df.columns if c not in exclude]]


@router.get("/{dataset_id}/cohort-profile")
def get_cohort_profile(dataset_id: str, db: Session = Depends(get_db)):
    """
    Return per-column metadata for every modeling column.
    Used by the dynamic cohort builder UI.
    """
    record = db.get(DatasetRecord, dataset_id)
    if not record:
        raise HTTPException(404, "Dataset not found.")

    try:
        df = _get_modeling_df(record)
    except Exception as e:
        raise HTTPException(500, f"Could not load dataset for cohort profiling: {e}")

    columns: List[dict] = []
    for col in df.columns:
        series = df[col]
        dtype_str = infer_column_type(series)
        try:
            col_meta = profile_column_for_cohort(series.rename(col), dtype_str)
            columns.append(col_meta)
        except Exception:
            # Never crash the whole profile because one column is unexpected
            columns.append({
                "name": col,
                "dtype": dtype_str,
                "kind": "categorical",
                "unique_count": int(series.nunique(dropna=True)),
                "unique_values": [str(v) for v in series.dropna().unique()[:50]],
            })

    return {
        "dataset_id": dataset_id,
        "columns": columns,
        "total_columns": len(columns),
    }
