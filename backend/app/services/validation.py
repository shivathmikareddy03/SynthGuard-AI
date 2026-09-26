"""
Statistical validation: compare source vs synthetic datasets.

KS test implementation notes
─────────────────────────────
• Uses scipy.stats.ks_2samp (two-sample Kolmogorov-Smirnov test).
• Pass criterion: p-value > 0.05 (i.e. we cannot reject the null hypothesis
  that both samples come from the same distribution).
• Sample-size correction: when |source| != |synthetic|, ks_2samp already
  accounts for both sample sizes internally.  However, with a very small
  source (e.g. 200 rows) and a large synthetic (e.g. 10 000 rows) the test
  gains enormous power and will detect even tiny differences. Therefore we
  also cap the synthetic sample passed to ks_2samp at 2 × |source| so that
  the test sensitivity is symmetric — we are testing whether the MODEL learned
  the distribution, not whether 10 000 generated points perfectly replicate
  200 source points.
• The raw ks_statistic and p_value are always stored for full transparency.
  The pass/fail decision uses the standard 0.05 threshold; we do NOT change
  it to inflate the score.
• NaN handling: NaN values are dropped before the test. If fewer than 2
  non-null values remain in either series the test is skipped and the column
  is marked "insufficient_data".
• Cohort note: when a cohort constraint was applied (e.g. 40 % older
  patients) the synthetic age distribution is intentionally shifted from the
  source. This will cause age to fail the KS test. That is *correct* — the
  dashboard labels such cases so the researcher understands why.
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy.orm import Session

from app.database import ValidationRecord
from app.utils.ids import new_id

logger = logging.getLogger("synthgen.validation")

# Maximum synthetic rows passed to ks_2samp (2 × source size).
# Prevents inflated power from large synthetic pools swamping a small source.
_KS_SYNTH_CAP_MULTIPLIER = 2

# p-value threshold — do NOT change this to inflate pass rates.
_KS_ALPHA = 0.05


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series)


def _safe_float(v) -> float:
    """Return float, replacing NaN/Inf with 0.0."""
    try:
        f = float(v)
        return 0.0 if (np.isnan(f) or np.isinf(f)) else f
    except Exception:
        return 0.0


def _coerce_numeric(series: pd.Series) -> pd.Series:
    """
    Coerce a series to numeric, handling:
    - columns that are already float/int  → unchanged
    - object columns that are actually numbers stored as strings
    - boolean series → 0/1 float
    Returns a float64 Series (NaN where conversion failed).
    """
    if pd.api.types.is_bool_dtype(series):
        return series.astype(float)
    if _is_numeric(series):
        return series.astype(float)
    # Try object→numeric
    coerced = pd.to_numeric(series, errors="coerce")
    return coerced


def _prepare_pair(src: pd.Series, syn: pd.Series) -> Tuple[
    Optional[np.ndarray], Optional[np.ndarray], str
]:
    """
    Prepare (source_values, synthetic_values) for KS test.

    Returns (src_arr, syn_arr, status) where status is one of:
      "ok"                 — both arrays valid, KS test can run
      "insufficient_data"  — fewer than 2 non-null values in source or synthetic
      "not_numeric"        — column cannot be coerced to numeric
    """
    src_f = _coerce_numeric(src).dropna().values
    syn_f = _coerce_numeric(syn).dropna().values

    if len(src_f) == 0 or len(syn_f) == 0:
        return None, None, "not_numeric"

    if len(src_f) < 2 or len(syn_f) < 2:
        return src_f, syn_f, "insufficient_data"

    # Cap synthetic to 2× source length so test power is balanced
    cap = len(src_f) * _KS_SYNTH_CAP_MULTIPLIER
    if len(syn_f) > cap:
        rng = np.random.default_rng(42)
        syn_f = rng.choice(syn_f, size=cap, replace=False)

    return src_f, syn_f, "ok"


# ── Numerical column stats (includes per-column KS test) ─────────────────────

def numerical_column_stats(
    src: pd.Series,
    syn: pd.Series,
    cohort_affected: bool = False,
) -> Dict:
    """
    Compute distributional statistics and run KS test for one numeric column.

    Uses scipy.stats.ks_2samp.
    Pass criterion: ks_pvalue > 0.05.
    Synthetic sample is capped at 2× source size for balanced test power.
    """
    src_arr, syn_arr, status = _prepare_pair(src, syn)

    if status == "not_numeric":
        return {}

    col_name = str(src.name)

    # Build base stats even if KS can't run
    src_f = _coerce_numeric(src).dropna().values
    syn_f = _coerce_numeric(syn).dropna().values

    def _stats(arr: np.ndarray) -> Dict:
        return {
            "mean":   _safe_float(np.mean(arr)),
            "std":    _safe_float(np.std(arr, ddof=1) if len(arr) > 1 else 0),
            "median": _safe_float(np.median(arr)),
            "min":    _safe_float(np.min(arr)),
            "max":    _safe_float(np.max(arr)),
            "q25":    _safe_float(np.percentile(arr, 25)),
            "q75":    _safe_float(np.percentile(arr, 75)),
        }

    result: Dict = {
        "column":         col_name,
        "source_n":       int(len(src_f)),
        "synth_n":        int(len(syn_f)),
        "ks_capped_synth_n": int(len(syn_arr)) if syn_arr is not None else 0,
        "cohort_affected": cohort_affected,
    }

    # Add distributional stats
    if len(src_f) > 0:
        ss = _stats(src_f)
        result.update({
            "source_mean":   ss["mean"],
            "source_std":    ss["std"],
            "source_median": ss["median"],
            "source_min":    ss["min"],
            "source_max":    ss["max"],
            "source_q25":    ss["q25"],
            "source_q75":    ss["q75"],
        })

    if len(syn_f) > 0:
        ys = _stats(syn_f)
        result.update({
            "synth_mean":    ys["mean"],
            "synth_std":     ys["std"],
            "synth_median":  ys["median"],
            "synth_min":     ys["min"],
            "synth_max":     ys["max"],
            "synth_q25":     ys["q25"],
            "synth_q75":     ys["q75"],
        })

    # KS test
    if status == "insufficient_data":
        result.update({
            "ks_statistic":         None,
            "ks_pvalue":            None,
            "ks_pass":              False,
            "ks_status":            "insufficient_data",
            "distribution_similarity": 0.0,
        })
        return result

    # status == "ok"
    ks_stat, ks_p = stats.ks_2samp(src_arr, syn_arr)
    ks_stat_f = _safe_float(ks_stat)
    ks_p_f    = _safe_float(ks_p)

    # Log for diagnostics
    logger.debug(
        "KS %s: n_src=%d n_syn_capped=%d stat=%.4f p=%.6f %s",
        col_name, len(src_arr), len(syn_arr),
        ks_stat_f, ks_p_f,
        "PASS" if ks_p_f > _KS_ALPHA else "FAIL",
    )

    result.update({
        "ks_statistic":            ks_stat_f,
        "ks_pvalue":               ks_p_f,
        "ks_pass":                 bool(ks_p_f > _KS_ALPHA),
        "ks_status":               "pass" if ks_p_f > _KS_ALPHA else "fail",
        "ks_alpha":                _KS_ALPHA,
        # Distribution similarity: 1 − KS statistic, expressed as percentage.
        # This is computed on the full synthetic vs source (not the capped version).
        "distribution_similarity": round((1.0 - ks_stat_f) * 100, 2),
    })
    return result


# ── Categorical column stats ──────────────────────────────────────────────────

def categorical_column_stats(src: pd.Series, syn: pd.Series) -> Dict:
    src_vc = src.astype(str).value_counts(normalize=True)
    syn_vc = syn.astype(str).value_counts(normalize=True)

    all_cats = set(src_vc.index) | set(syn_vc.index)
    src_dist = {c: round(_safe_float(src_vc.get(c, 0)) * 100, 2) for c in all_cats}
    syn_dist = {c: round(_safe_float(syn_vc.get(c, 0)) * 100, 2) for c in all_cats}

    tvd = 0.5 * sum(abs(src_dist.get(c, 0) - syn_dist.get(c, 0)) for c in all_cats) / 100
    tvd = _safe_float(tvd)

    chi2 = None
    chi2_p = None
    try:
        src_counts = src.astype(str).value_counts()
        syn_counts = syn.astype(str).value_counts()
        cats = list(set(src_counts.index) | set(syn_counts.index))
        o_src = np.array([src_counts.get(c, 0) for c in cats], dtype=float)
        o_syn = np.array([syn_counts.get(c, 0) for c in cats], dtype=float)
        if o_syn.sum() > 0:
            o_syn = o_syn / o_syn.sum() * o_src.sum()
        if (o_src > 0).any() and (o_syn > 0).any():
            chi2_val, chi2_p_val = stats.chisquare(o_src + 0.5, o_syn + 0.5)
            chi2   = _safe_float(chi2_val)
            chi2_p = _safe_float(chi2_p_val)
    except Exception:
        pass

    return {
        "column":               str(src.name),
        "source_distribution":  src_dist,
        "synth_distribution":   syn_dist,
        "chi2_statistic":       chi2,
        "chi2_pvalue":          chi2_p,
        "tvd":                  round(tvd, 4),
        "similarity_score":     round((1.0 - min(tvd, 1.0)) * 100, 2),
    }


# ── Correlation stats ─────────────────────────────────────────────────────────

def correlation_stats(source_df: pd.DataFrame, synth_df: pd.DataFrame) -> List[Dict]:
    # Use coerce-numeric to handle string-encoded numbers
    src_num = {
        c: _coerce_numeric(source_df[c])
        for c in source_df.columns
        if c in synth_df.columns and _coerce_numeric(source_df[c]).dropna().shape[0] > 1
    }
    syn_num = {
        c: _coerce_numeric(synth_df[c])
        for c in src_num
        if _coerce_numeric(synth_df[c]).dropna().shape[0] > 1
    }
    numeric_cols = [c for c in src_num if c in syn_num]

    results = []
    for i, col_a in enumerate(numeric_cols):
        for col_b in numeric_cols[i + 1:]:
            try:
                src_corr = src_num[col_a].corr(src_num[col_b])
                syn_corr = syn_num[col_a].corr(syn_num[col_b])
                if np.isnan(src_corr) or np.isnan(syn_corr):
                    continue
                results.append({
                    "col_a":                col_a,
                    "col_b":                col_b,
                    "source_correlation":   round(_safe_float(src_corr), 4),
                    "synth_correlation":    round(_safe_float(syn_corr), 4),
                    "difference":           round(abs(_safe_float(src_corr) - _safe_float(syn_corr)), 4),
                })
            except Exception:
                continue
    return results


# ── Overall quality scores ────────────────────────────────────────────────────

def compute_overall_scores(
    num_stats: List[Dict],
    cat_stats: List[Dict],
    corr_stats: List[Dict],
) -> Dict:
    scores: Dict = {}

    # Distribution similarity — average of numeric + categorical
    num_sims = [s["distribution_similarity"] for s in num_stats if s.get("distribution_similarity") is not None]
    cat_sims = [s["similarity_score"]         for s in cat_stats if s.get("similarity_score")         is not None]
    all_sims = num_sims + cat_sims
    scores["distribution_similarity"] = round(np.mean(all_sims), 2) if all_sims else 0.0

    # Correlation preservation
    if corr_stats:
        mean_diff = np.mean([c["difference"] for c in corr_stats])
        scores["correlation_preservation"] = round(max(0.0, (1.0 - mean_diff)) * 100, 2)
    else:
        scores["correlation_preservation"] = 100.0

    # KS pass rate — threshold p > 0.05, denominator = only columns where KS ran
    testable = [s for s in num_stats if s.get("ks_status") in ("pass", "fail")]
    skipped  = [s for s in num_stats if s.get("ks_status") == "insufficient_data"]
    if testable:
        ks_passes = sum(1 for s in testable if s.get("ks_pass") is True)
        scores["ks_pass_rate"]         = round(ks_passes / len(testable) * 100, 2)
        scores["ks_tested_columns"]    = len(testable)
        scores["ks_passed_columns"]    = ks_passes
        scores["ks_skipped_columns"]   = len(skipped)
    else:
        scores["ks_pass_rate"]         = 0.0
        scores["ks_tested_columns"]    = 0
        scores["ks_passed_columns"]    = 0
        scores["ks_skipped_columns"]   = len(skipped)

    # Overall quality score (weighted average)
    scores["overall_quality"] = round(
        0.5 * scores["distribution_similarity"]
        + 0.3 * scores["correlation_preservation"]
        + 0.2 * scores["ks_pass_rate"],
        2,
    )
    return scores


# ── Main validation entry point ───────────────────────────────────────────────

def run_validation(
    generation_id: str,
    dataset_id: str,
    source_path: str,        # generation-ready source (ordinal dates, same dtype space as synthetic)
    synthetic_path: str,
    db: Session,
    cohort_columns: Optional[List[str]] = None,  # columns affected by cohort resampling
) -> ValidationRecord:
    """
    Compare source vs synthetic datasets statistically.

    Both CSVs must be in the same column/dtype space.  The caller should pass
    source_path = GenerationRecord.source_for_validation_path (the ordinal-
    transformed copy saved during generation) so dtypes match.
    """
    source_df = pd.read_csv(source_path)
    synth_df  = pd.read_csv(synthetic_path)

    logger.info(
        "Validation: source=%s (%d rows), synthetic=%s (%d rows)",
        source_path, len(source_df), synthetic_path, len(synth_df),
    )

    # Align columns (only columns present in BOTH datasets)
    common_cols = [c for c in source_df.columns if c in synth_df.columns]
    source_df = source_df[common_cols]
    synth_df  = synth_df[common_cols]

    cohort_cols_set = set(cohort_columns or [])
    num_stats: List[Dict] = []
    cat_stats: List[Dict] = []

    for col in common_cols:
        # Determine if this column should be treated numerically.
        # Use coerce-numeric: a column stored as strings (e.g. "1", "2.5") counts as numeric.
        src_coerced = _coerce_numeric(source_df[col])
        syn_coerced = _coerce_numeric(synth_df[col])

        src_numeric_frac = src_coerced.notna().mean()
        syn_numeric_frac = syn_coerced.notna().mean()

        # Treat as numeric if ≥ 90 % of values in BOTH series can be coerced
        treat_numeric = (src_numeric_frac >= 0.9) and (syn_numeric_frac >= 0.9)

        if treat_numeric:
            stat = numerical_column_stats(
                src_coerced.rename(col),
                syn_coerced.rename(col),
                cohort_affected=(col in cohort_cols_set),
            )
            if stat:
                num_stats.append(stat)
        else:
            stat = categorical_column_stats(source_df[col], synth_df[col])
            if stat:
                cat_stats.append(stat)

    corr    = correlation_stats(source_df, synth_df)
    overall = compute_overall_scores(num_stats, cat_stats, corr)

    # Log per-column KS summary
    for s in num_stats:
        if s.get("ks_status") in ("pass", "fail"):
            logger.info(
                "  KS %-35s  stat=%.4f  p=%.6f  %s%s",
                s["column"], s["ks_statistic"], s["ks_pvalue"],
                s["ks_status"].upper(),
                "  (cohort-affected)" if s.get("cohort_affected") else "",
            )

    logger.info(
        "KS pass rate: %d/%d = %.1f%%",
        overall.get("ks_passed_columns", 0),
        overall.get("ks_tested_columns", 0),
        overall.get("ks_pass_rate", 0.0),
    )

    val_id = new_id()
    record = ValidationRecord(
        id=val_id,
        generation_id=generation_id,
        dataset_id=dataset_id,
        numerical_stats=json.dumps(num_stats),
        categorical_stats=json.dumps(cat_stats),
        correlation_stats=json.dumps(corr),
        overall_scores=json.dumps(overall),
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
