"""
Post-generation cohort resampling.

Two public APIs:

1. apply_cohort_requirements(synth_df, source_df, num_records, cohort_config)
   ── Legacy interface kept for backward compatibility.
   ── Hard-coded field names (older_patients_pct, diabetic_pct, etc.)

2. apply_dynamic_cohort(synth_df, num_records, requirements)
   ── New dataset-driven interface.
   ── requirements is a list of:
      {
        "feature":           "<column_name>",
        "operator":          "greater_than|less_than|gte|lte|equal|between|in_values",
        "value":             <scalar or list>,
        "target_proportion": 0.0–1.0,
      }
   ── Works for any column / datatype — no hard-coded healthcare names.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("sh405.cohort")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _col_exists(df: pd.DataFrame, col: Optional[str]) -> Optional[str]:
    if col is None:
        return None
    if col in df.columns:
        return col
    lower_map = {c.lower(): c for c in df.columns}
    return lower_map.get(col.lower())


def _eval_condition(series: pd.Series, operator: str, value: Any) -> pd.Series:
    """
    Return a boolean mask for rows satisfying (series <operator> value).
    Handles numerical, boolean, and categorical/string columns.
    """
    op = operator.lower().strip()

    # Boolean columns: coerce to bool before comparison
    if pd.api.types.is_bool_dtype(series):
        bool_map = {"true": True, "false": False, "1": True, "0": False,
                    "yes": True, "no": False}
        if isinstance(value, str):
            target = bool_map.get(value.lower().strip(), value.lower() == "true")
        elif isinstance(value, (int, float)):
            target = bool(value)
        else:
            target = bool(value)
        if op in ("equal", "eq", "equals", "=", "=="):
            return series == target
        if op in ("not_equal", "ne", "!="):
            return series != target
        if op == "in_values":
            targets = [bool_map.get(str(v).lower().strip(), str(v).lower() == "true") for v in value]
            return series.isin(targets)
        # Fallback: treat True=1, False=0 for numeric operators
        series = series.astype(int)

    # Numeric coercion when column is numeric-like
    if pd.api.types.is_numeric_dtype(series):
        if op in ("greater_than", "gt"):
            return series > float(value)
        if op in ("less_than", "lt"):
            return series < float(value)
        if op in ("gte", "greater_than_or_equal", ">="):
            return series >= float(value)
        if op in ("lte", "less_than_or_equal", "<="):
            return series <= float(value)
        if op in ("equal", "eq", "equals", "=", "=="):
            return series == float(value)
        if op == "between":
            lo, hi = float(value[0]), float(value[1])
            return (series >= lo) & (series <= hi)
        if op in ("not_equal", "ne", "!="):
            return series != float(value)
        if op == "in_values":
            vals = [float(v) for v in value]
            return series.isin(vals)

    # Categorical / string comparison
    s_lower = series.astype(str).str.lower().str.strip()

    if op in ("equal", "eq", "equals", "=", "=="):
        return s_lower == str(value).lower().strip()
    if op in ("not_equal", "ne", "!="):
        return s_lower != str(value).lower().strip()
    if op == "in_values":
        vals = [str(v).lower().strip() for v in value]
        return s_lower.isin(vals)

    # For ordinal-like numeric comparisons on string columns — try numeric coerce
    try:
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().mean() >= 0.9:
            return _eval_condition(numeric, operator, value)
    except Exception:
        pass

    logger.warning("Unsupported operator '%s' for column dtype %s", operator, series.dtype)
    return pd.Series([False] * len(series), index=series.index)


def _measure_proportion(df: pd.DataFrame, feature: str, operator: str, value: Any) -> float:
    """Return the fraction (0–1) of rows in df satisfying the condition."""
    if feature not in df.columns or len(df) == 0:
        return 0.0
    mask = _eval_condition(df[feature], operator, value)
    return float(mask.sum()) / len(df)


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic cohort API  (new, dataset-driven)
# ─────────────────────────────────────────────────────────────────────────────

def apply_dynamic_cohort(
    synth_df: pd.DataFrame,
    num_records: int,
    requirements: List[Dict],
) -> Tuple[pd.DataFrame, List[Dict]]:
    """
    Resample `synth_df` to approximately satisfy all cohort requirements.

    Each requirement:
    {
        "feature":           str,          column name
        "operator":          str,          see _eval_condition
        "value":             any,          scalar or list
        "target_proportion": float,        0.0–1.0
        "label":             str optional  display label
    }

    Strategy: for each requirement, partition the pool into "satisfies" and
    "does not satisfy" strata; sample proportionally; combine; repeat for the
    next requirement on the combined result. Because requirements are applied
    sequentially the final proportions are approximations — they are measured
    from the actual output and reported honestly.

    Returns (result_df, report_list) where report_list mirrors requirements
    with "requested_pct", "generated_pct", "diff_pct", "status" fields added.
    """
    if not requirements:
        result = synth_df.sample(
            n=min(num_records, len(synth_df)), replace=True, random_state=42
        ).reset_index(drop=True)
        return result, []

    pool = synth_df.copy()
    rng  = np.random.default_rng(42)

    # Apply requirements one at a time, narrowing the pool progressively
    for req in requirements:
        feature  = req["feature"]
        operator = req["operator"]
        value    = req["value"]
        target_p = float(req["target_proportion"])   # 0–1

        if feature not in pool.columns:
            logger.warning("Cohort feature '%s' not in synthetic columns — skipping", feature)
            continue

        mask         = _eval_condition(pool[feature], operator, value)
        satisfying   = pool[mask]
        not_satisfying = pool[~mask]

        n_satisfy     = max(0, int(round(target_p * num_records)))
        n_not_satisfy = max(0, num_records - n_satisfy)

        frames = []
        if n_satisfy > 0:
            src = satisfying if len(satisfying) > 0 else pool
            frames.append(src.sample(n=n_satisfy, replace=True,
                                     random_state=int(rng.integers(0, 100000))))
        if n_not_satisfy > 0:
            src = not_satisfying if len(not_satisfying) > 0 else pool
            frames.append(src.sample(n=n_not_satisfy, replace=True,
                                     random_state=int(rng.integers(0, 100000))))

        if frames:
            pool = pd.concat(frames, ignore_index=True).sample(
                frac=1, random_state=42
            ).reset_index(drop=True)

    # Trim / pad to exact num_records
    if len(pool) > num_records:
        result = pool.sample(n=num_records, random_state=42).reset_index(drop=True)
    elif len(pool) < num_records:
        extra  = synth_df.sample(n=num_records - len(pool), replace=True, random_state=42)
        result = pd.concat([pool, extra], ignore_index=True).sample(
            frac=1, random_state=42
        ).reset_index(drop=True)
    else:
        result = pool

    # ── Measure actual proportions ────────────────────────────────────────────
    report = []
    for req in requirements:
        feature  = req["feature"]
        operator = req["operator"]
        value    = req["value"]
        target_p = float(req["target_proportion"])
        label    = req.get("label") or f"{feature} {operator} {value}"

        if feature not in result.columns:
            report.append({
                **req,
                "label":          label,
                "requested_pct":  round(target_p * 100, 2),
                "generated_pct":  None,
                "diff_pct":       None,
                "status":         "column_missing",
            })
            continue

        actual_p = _measure_proportion(result, feature, operator, value)
        diff     = round(abs(target_p - actual_p) * 100, 2)
        status   = "pass" if diff <= 5 else "warn"

        report.append({
            "feature":        feature,
            "operator":       operator,
            "value":          value,
            "label":          label,
            "requested_pct":  round(target_p * 100, 2),
            "generated_pct":  round(actual_p * 100, 2),
            "diff_pct":       diff,
            "status":         status,
        })

    return result.reset_index(drop=True), report


# ─────────────────────────────────────────────────────────────────────────────
# Legacy API  (kept intact for backward compatibility)
# ─────────────────────────────────────────────────────────────────────────────

def apply_cohort_requirements(
    synth_df: pd.DataFrame,
    source_df: pd.DataFrame,
    num_records: int,
    cohort_config: Dict,
) -> Tuple[pd.DataFrame, Dict]:
    """
    Legacy hard-coded cohort resampling.
    Translates the old config format into dynamic requirements and delegates.
    Preserved for backward compatibility with existing saved cohort_config records.
    """
    older_pct    = cohort_config.get("older_patients_pct")
    diabetic_pct = cohort_config.get("diabetic_pct")
    activity_dist = cohort_config.get("activity_distribution")
    age_col      = _col_exists(synth_df, cohort_config.get("age_column",      "Age"))
    diabetes_col = _col_exists(synth_df, cohort_config.get("diabetes_column", "Diabetes"))
    activity_col = _col_exists(synth_df, cohort_config.get("activity_column", "ActivityLevel"))

    # Build generic requirements from the legacy config
    requirements: List[Dict] = []

    if older_pct is not None and age_col is not None:
        requirements.append({
            "feature":           age_col,
            "operator":          "gte",
            "value":             60,
            "target_proportion": float(older_pct) / 100,
            "label":             f"{age_col} ≥ 60",
            "_legacy_key":       "older",
        })

    if diabetic_pct is not None and diabetes_col is not None:
        requirements.append({
            "feature":           diabetes_col,
            "operator":          "in_values",
            "value":             ["1", "true", "yes", "1.0"],
            "target_proportion": float(diabetic_pct) / 100,
            "label":             f"{diabetes_col} = diabetic",
            "_legacy_key":       "diabetic",
        })

    if activity_dist is not None and activity_col is not None:
        total_pct = sum(float(v) for v in activity_dist.values())
        if total_pct > 0:
            # Use the largest activity-level bucket as the resampling target
            max_cat = max(activity_dist, key=lambda k: float(activity_dist[k]))
            requirements.append({
                "feature":           activity_col,
                "operator":          "equal",
                "value":             max_cat,
                "target_proportion": float(activity_dist[max_cat]) / total_pct,
                "label":             f"{activity_col} = {max_cat}",
                "_legacy_key":       "activity",
            })

    if not requirements:
        df = synth_df.sample(n=min(num_records, len(synth_df)), replace=True, random_state=42)
        return df.reset_index(drop=True), {"note": "No cohort constraints applied"}

    result, report = apply_dynamic_cohort(synth_df, num_records, requirements)

    # Translate report back into the legacy result dict shape
    legacy_results: Dict = {}
    for item in report:
        key = item.get("_legacy_key")
        if key == "older":
            legacy_results["older_pct_requested"] = item["requested_pct"]
            legacy_results["older_pct_actual"]    = item.get("generated_pct")
            legacy_results["older_pct_diff"]      = item.get("diff_pct")
        elif key == "diabetic":
            legacy_results["diabetic_pct_requested"] = item["requested_pct"]
            legacy_results["diabetic_pct_actual"]    = item.get("generated_pct")
            legacy_results["diabetic_pct_diff"]      = item.get("diff_pct")
        elif key == "activity" and activity_dist is not None:
            legacy_results["activity_requested"] = activity_dist
            if activity_col and activity_col in result.columns:
                vc = result[activity_col].value_counts(normalize=True) * 100
                legacy_results["activity_actual"] = {
                    k: round(float(v), 2) for k, v in vc.to_dict().items()
                }

    return result, legacy_results
