import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any, List
from app.services.constraints_config import CONSTRAINTS

def _get_col(df: pd.DataFrame, possible_names: List[str]) -> str:
    """Find the first matching column name (case-insensitive)"""
    col_map = {c.lower(): c for c in df.columns}
    for n in possible_names:
        if n.lower() in col_map:
            return col_map[n.lower()]
    return None

def run_physiological_constraints(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    report = {
        "generated_records": len(df),
        "valid_records": 0,
        "rejected_records": 0,
        "warnings": 0,
        "violations_by_rule": {},
        "rejected_examples": [],
        "repaired_records": 0
    }
    
    if df.empty:
        return df, report

    reject_mask = pd.Series(False, index=df.index)
    warning_count_per_row = pd.Series(0, index=df.index)
    
    def log_violation(rule_name: str, mask: pd.Series, severity: str, action: str, reason_template: str, example_values: pd.DataFrame = None):
        if not mask.any():
            return
        
        count = int(mask.sum())
        report["violations_by_rule"][rule_name] = report.get("violations_by_rule", {}).get(rule_name, 0) + count
        
        if action == "reject":
            nonlocal reject_mask
            new_rejects = mask & ~reject_mask
            reject_mask = reject_mask | mask
            
            if new_rejects.any():
                example_idx = df[new_rejects].head(5).index
                for idx in example_idx:
                    if len(report["rejected_examples"]) < 5:
                        vals = example_values.loc[idx].to_dict() if example_values is not None else {}
                        reason = reason_template.format(**vals)
                        report["rejected_examples"].append({
                            "row_index": int(idx),
                            "violation": rule_name,
                            "reason": reason
                        })
                        
        elif action == "flag" or severity == "warning":
            nonlocal warning_count_per_row
            warning_count_per_row = warning_count_per_row.add(mask.astype(int))

    sys_col = _get_col(df, ["systolic_bp", "systolic", "bp_sys", "ap_hi"])
    dia_col = _get_col(df, ["diastolic_bp", "diastolic", "bp_dia", "ap_lo"])
    if sys_col and dia_col:
        mask = (df[sys_col] <= df[dia_col]) & df[sys_col].notna() & df[dia_col].notna()
        log_violation("Systolic BP <= Diastolic BP", mask, "critical", "reject", 
                      "Systolic BP ({sys}) must be greater than Diastolic BP ({dia}).",
                      df[[sys_col, dia_col]].rename(columns={sys_col: "sys", dia_col: "dia"}))
        mask_sys = ((df[sys_col] < CONSTRAINTS["blood_pressure"]["min_systolic"]) | 
                    (df[sys_col] > CONSTRAINTS["blood_pressure"]["max_systolic"])) & df[sys_col].notna()
        log_violation("Systolic BP out of bounds", mask_sys, "critical", "reject",
                      "Systolic BP ({sys}) is physically impossible.", df[[sys_col]].rename(columns={sys_col: "sys"}))
        mask_dia = ((df[dia_col] < CONSTRAINTS["blood_pressure"]["min_diastolic"]) | 
                    (df[dia_col] > CONSTRAINTS["blood_pressure"]["max_diastolic"])) & df[dia_col].notna()
        log_violation("Diastolic BP out of bounds", mask_dia, "critical", "reject",
                      "Diastolic BP ({dia}) is physically impossible.", df[[dia_col]].rename(columns={dia_col: "dia"}))

    hr_col = _get_col(df, ["heart_rate", "hr", "pulse"])
    if hr_col:
        mask_hr_imp = ((df[hr_col] <= 0) | (df[hr_col] > CONSTRAINTS["heart_rate"]["max"])) & df[hr_col].notna()
        log_violation("Heart Rate impossible", mask_hr_imp, "critical", "reject",
                      "Heart rate ({hr}) is impossible.", df[[hr_col]].rename(columns={hr_col: "hr"}))
        mask_hr_warn = ((df[hr_col] < CONSTRAINTS["heart_rate"]["warning_min"]) | 
                        (df[hr_col] > CONSTRAINTS["heart_rate"]["warning_max"])) & df[hr_col].notna() & ~mask_hr_imp
        log_violation("Heart Rate abnormal", mask_hr_warn, "warning", "flag",
                      "Heart rate ({hr}) is clinically unusual.", df[[hr_col]].rename(columns={hr_col: "hr"}))

    spo2_col = _get_col(df, ["spo2", "oxygen_saturation", "o2_sat"])
    if spo2_col:
        mask_spo2_imp = ((df[spo2_col] < 0) | (df[spo2_col] > 100)) & df[spo2_col].notna()
        log_violation("SpO2 outside 0-100", mask_spo2_imp, "critical", "reject",
                      "SpO2 ({spo2}) must be between 0 and 100.", df[[spo2_col]].rename(columns={spo2_col: "spo2"}))
        mask_spo2_warn = (df[spo2_col] < CONSTRAINTS["spo2"]["warning_min"]) & df[spo2_col].notna() & ~mask_spo2_imp
        log_violation("SpO2 critically low", mask_spo2_warn, "warning", "flag",
                      "SpO2 ({spo2}) is clinically very low.", df[[spo2_col]].rename(columns={spo2_col: "spo2"}))

    age_col = _get_col(df, ["age", "patient_age"])
    if age_col:
        mask_age = ((df[age_col] < 0) | (df[age_col] > CONSTRAINTS["age"]["max"])) & df[age_col].notna()
        log_violation("Age impossible", mask_age, "critical", "reject",
                      "Age ({age}) cannot be negative or extreme.", df[[age_col]].rename(columns={age_col: "age"}))

    bmi_col = _get_col(df, ["bmi", "body_mass_index"])
    height_col = _get_col(df, ["height", "height_cm"])
    weight_col = _get_col(df, ["weight", "weight_kg"])
    if height_col and weight_col and bmi_col:
        mask_hw = ((df[height_col] <= 0) | (df[weight_col] <= 0)) & df[height_col].notna() & df[weight_col].notna()
        log_violation("Negative/Zero Height or Weight", mask_hw, "critical", "reject",
                      "Height ({h}) and weight ({w}) must be positive.", df[[height_col, weight_col]].rename(columns={height_col: "h", weight_col: "w"}))
        valid_hw = df[height_col].notna() & df[weight_col].notna() & (df[height_col] > 0) & ~reject_mask
        expected_bmi = df.loc[valid_hw, weight_col] / ((df.loc[valid_hw, height_col] / 100) ** 2)
        diff = (df.loc[valid_hw, bmi_col] - expected_bmi).abs()
        repair_mask = valid_hw & (diff > 1.0)
        if repair_mask.any():
            df.loc[repair_mask, bmi_col] = expected_bmi[repair_mask]
            report["repaired_records"] += int(repair_mask.sum())
            report["violations_by_rule"]["Invalid BMI consistency (repaired)"] = int(repair_mask.sum())

    temp_col = _get_col(df, ["temperature", "temp"])
    if temp_col:
        mask_temp_imp = ((df[temp_col] < CONSTRAINTS["temperature"]["min"]) | 
                         (df[temp_col] > CONSTRAINTS["temperature"]["max"])) & df[temp_col].notna()
        log_violation("Temperature impossible", mask_temp_imp, "critical", "reject",
                      "Temperature ({temp}) is physically impossible.", df[[temp_col]].rename(columns={temp_col: "temp"}))
        mask_temp_warn = ((df[temp_col] < CONSTRAINTS["temperature"]["warning_min"]) | 
                          (df[temp_col] > CONSTRAINTS["temperature"]["warning_max"])) & df[temp_col].notna() & ~mask_temp_imp
        log_violation("Temperature abnormal", mask_temp_warn, "warning", "flag",
                      "Temperature ({temp}) is clinically unusual.", df[[temp_col]].rename(columns={temp_col: "temp"}))

    glu_col = _get_col(df, ["glucose", "blood_glucose", "gluc"])
    if glu_col:
        mask_glu_imp = ((df[glu_col] < CONSTRAINTS["blood_glucose"]["min"]) | 
                        (df[glu_col] > CONSTRAINTS["blood_glucose"]["max"])) & df[glu_col].notna()
        log_violation("Glucose impossible", mask_glu_imp, "critical", "reject",
                      "Glucose ({glu}) is physically impossible.", df[[glu_col]].rename(columns={glu_col: "glu"}))
        mask_glu_warn = ((df[glu_col] < CONSTRAINTS["blood_glucose"]["warning_min"]) | 
                         (df[glu_col] > CONSTRAINTS["blood_glucose"]["warning_max"])) & df[glu_col].notna() & ~mask_glu_imp
        log_violation("Glucose abnormal", mask_glu_warn, "warning", "flag",
                      "Glucose ({glu}) is clinically unusual.", df[[glu_col]].rename(columns={glu_col: "glu"}))

    for col in df.select_dtypes(include=[np.number]).columns:
        if col not in [sys_col, dia_col, hr_col, spo2_col, age_col, bmi_col, height_col, weight_col, temp_col, glu_col]:
            lower_col = col.lower()
            if any(x in lower_col for x in ["rate", "count", "amount", "level", "weight", "height", "mass"]):
                mask_neg = (df[col] < 0) & df[col].notna()
                log_violation(f"Negative {col}", mask_neg, "critical", "reject",
                              f"{col} ({{val}}) cannot be negative.", df[[col]].rename(columns={col: "val"}))

    valid_df = df[~reject_mask].copy()
    report["rejected_records"] = int(reject_mask.sum())
    report["valid_records"] = len(valid_df)
    report["warnings"] = int((warning_count_per_row[~reject_mask] > 0).sum())
    
    if report["generated_records"] > 0:
        report["rejection_rate"] = round(report["rejected_records"] / report["generated_records"] * 100, 2)
        report["warning_rate"] = round(report["warnings"] / report["generated_records"] * 100, 2)
    else:
        report["rejection_rate"] = 0.0
        report["warning_rate"] = 0.0
        
    return valid_df, report
