"""
Synthetic data generation using SDV.
Primary model: CTGAN. Fallback: TVAE, then GaussianCopulaSynthesizer.
"""
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.database import GenerationRecord
from app.services.cohort import apply_cohort_requirements
from app.utils.ids import new_id

logger = logging.getLogger("sh405.generation")


def _load_sdv():
    try:
        from sdv.metadata import SingleTableMetadata
        from sdv.single_table import CTGANSynthesizer, TVAESynthesizer, GaussianCopulaSynthesizer
        return SingleTableMetadata, CTGANSynthesizer, TVAESynthesizer, GaussianCopulaSynthesizer
    except ImportError as e:
        raise RuntimeError(f"SDV is not installed: {e}")


def _build_metadata(df: pd.DataFrame):
    SingleTableMetadata, *_ = _load_sdv()
    metadata = SingleTableMetadata()
    metadata.detect_from_dataframe(df)
    return metadata


def _make_synthesizer(model_name: str, metadata, epochs: int):
    _, CTGANSynthesizer, TVAESynthesizer, GaussianCopulaSynthesizer = _load_sdv()
    model_name = model_name.upper()
    if model_name == "CTGAN":
        return CTGANSynthesizer(metadata, epochs=epochs, verbose=False), "CTGAN"
    elif model_name == "TVAE":
        return TVAESynthesizer(metadata, epochs=epochs), "TVAE"
    else:
        return GaussianCopulaSynthesizer(metadata), "GaussianCopula"


def _is_direct_identifier(col: str) -> bool:
    """
    Fast column-name check — returns True if this column is a direct personal
    identifier that must be stripped before any modeling.
    Mirrors _DIRECT_ID_EXACT + partial patterns from data_processing.py.
    """
    import re
    norm = col.lower()
    norm = re.sub(r"[^a-z0-9]+", "_", norm)
    norm = re.sub(r"_+", "_", norm).strip("_")

    _EXACT = {
        "name", "patient_name", "patientname", "full_name", "fullname",
        "first_name", "firstname", "last_name", "lastname",
        "patient_full_name", "patient_first_name", "patient_last_name",
        "aadhaar", "aadhaar_number", "ssn", "social_security_number",
        "social_security", "passport_number", "passport",
        "driver_license", "drivers_license", "driving_license", "license_number",
        "national_id", "nationalid",
        "medical_record_number", "mrn", "medical_record_no",
        "hospital_id", "hospitalid",
        "email", "email_address", "e_mail",
        "phone", "phone_number", "mobile", "mobile_number",
        "telephone", "telephone_number", "fax", "fax_number",
        "address", "home_address", "street_address", "postal_address",
        "street", "street_name",
        "credit_card", "creditcard", "bank_account", "bankaccount",
        "insurance_id", "insuranceid", "nhs_number", "nhs",
        "health_id", "healthid",
        "ip_address", "ip", "mac_address", "mac",
        "photo", "photo_url", "image", "face_image",
        "latitude", "longitude", "gps",
    }
    if norm in _EXACT:
        return True

    # Partial patterns: phone_number, fax_number, patient_name variants
    _PARTIAL = [
        r"_?number$",
        r"^patient_?name$",
        r"^patient_?identifier$",
    ]
    return any(re.search(p, norm) for p in _PARTIAL)


def _is_linkage_key(col: str) -> bool:
    """
    Fast column-name check (no data scanning) — returns True if this column
    is a longitudinal linkage key that must never enter CTGAN as a feature.
    Mirrors the exact same sets used in data_processing.classify_all_columns
    so behaviour is consistent with the privacy classifier.
    """
    import re
    norm = col.lower()
    norm = re.sub(r"[^a-z0-9]+", "_", norm)
    norm = re.sub(r"_+", "_", norm).strip("_")

    _EXACT = {
        "patient_id", "patientid", "patient_identifier", "patientidentifier",
        "patient_key", "patientkey",
        "subject_id", "subjectid", "subject_key", "subjectkey",
        "participant_id", "participantid", "participant_key", "participantkey",
        "person_id", "personid", "person_key", "personkey",
        "study_id", "studyid", "study_subject_id",
        "encounter_subject_id", "encounter_id", "encounterid",
        "case_id", "caseid", "case_number",
        "cohort_id", "cohortid",
        "member_id", "memberid",
        "client_id", "clientid",
        "respondent_id", "respondentid",
        "record_id", "recordid",
    }
    if norm in _EXACT:
        return True

    _PATTERNS = [
        r"^patient_?id$", r"^subject_?id$", r"^participant_?id$",
        r"^person_?id$",  r"^case_?id$",    r"^cohort_?id$",
        r"^encounter_?id$", r"^study_?id$", r"^member_?id$",
        r"^client_?id$",  r".*_key$",
    ]
    return any(re.search(p, norm) for p in _PATTERNS)


def _prepare_for_sdv(source_df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform the preprocessed DataFrame into the form SDV/CTGAN expects.

    Privacy pre-processing (steps 0a and 0b) runs first so that:
      - Direct personal identifiers (names, emails, MRNs …) are dropped.
      - Longitudinal linkage keys (patient_id …) are replaced with an internal
        integer pseudonym (timeline_id) and then also dropped before modeling.
        The mapping is used only for grouping within this call and is never
        persisted or returned.

    Remaining transforms:
      - datetime64 columns → <col>_ordinal (integer) + original dropped
      - object columns that parse as dates → ordinal integer
      - object columns that are numbers stored as strings → float
      - all-null columns dropped
    """
    df = source_df.copy()

    # ── 0a. Strip direct personal identifiers ────────────────────────────────
    # Names, emails, phones, MRNs, addresses etc. must never reach CTGAN.
    direct_id_cols = [c for c in df.columns if _is_direct_identifier(c)]
    if direct_id_cols:
        logger.info("Removing direct personal identifiers before SDV: %s", direct_id_cols)
        df = df.drop(columns=direct_id_cols)

    # ── 0b. Pseudonymize longitudinal linkage keys ────────────────────────────
    # Replace the original linkage-key values with a compact integer index so
    # that the grouping structure is preserved internally while the original IDs
    # are never seen by CTGAN.  The integer column is then also dropped before
    # training — CTGAN only sees the clinical features.
    linkage_cols = [c for c in df.columns if _is_linkage_key(c)]
    if linkage_cols:
        key_col = linkage_cols[0]  # use first detected key
        logger.info(
            "Pseudonymizing longitudinal linkage key '%s' before SDV (original values discarded)",
            key_col,
        )
        # Build integer mapping: original value → sequential integer
        unique_vals = df[key_col].dropna().unique()
        _mapping = {v: i + 1 for i, v in enumerate(unique_vals)}
        df["_timeline_id"] = df[key_col].map(_mapping)
        # Drop all linkage key columns — _timeline_id is internal only and also dropped
        df = df.drop(columns=linkage_cols + ["_timeline_id"])

    # ── 1. Convert existing datetime64 columns to ordinal ints ───────────────
    date_cols_to_drop = []
    for col in list(df.columns):
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col + "_ordinal"] = df[col].map(
                lambda x: int(x.toordinal()) if pd.notnull(x) else None
            )
            date_cols_to_drop.append(col)
    if date_cols_to_drop:
        df = df.drop(columns=date_cols_to_drop)

    # ── 2. Object columns that look like date strings → ordinal int ───────────
    for col in list(df.columns):
        if df[col].dtype == object:
            sample = df[col].dropna().head(20).astype(str)
            if len(sample) == 0:
                continue
            try:
                parsed = pd.to_datetime(sample, errors="coerce")
                if parsed.notna().mean() >= 0.9:
                    df[col] = pd.to_datetime(df[col], errors="coerce").map(
                        lambda x: int(x.toordinal()) if pd.notnull(x) else None
                    )
            except Exception:
                pass

    # ── 3. Object columns that are numbers stored as strings → float ──────────
    for col in list(df.columns):
        if df[col].dtype == object:
            coerced = pd.to_numeric(df[col], errors="coerce")
            if coerced.notna().mean() >= 0.9:
                df[col] = coerced

    # ── 4. Drop all-null columns ──────────────────────────────────────────────
    df = df.dropna(axis=1, how="all")

    return df


def run_generation(
    gen_id: str,
    dataset_id: str,
    source_path: str,
    num_records: int,
    model_name: str,
    epochs: int,
    cohort_config: Optional[Dict],
    db: Session,
    progress_callback: Optional[Callable[[int, str], None]] = None,
):
    """
    Full generation pipeline. Runs synchronously in a background thread.
    Updates GenerationRecord in the DB throughout.
    """
    def _progress(pct: int, msg: str):
        record = db.get(GenerationRecord, gen_id)
        if record:
            record.progress = pct
            record.progress_message = msg
            db.commit()
        if progress_callback:
            progress_callback(pct, msg)

    record = db.get(GenerationRecord, gen_id)
    if not record:
        return

    try:
        # ── 1. Load and transform source ──────────────────────────────────────
        _progress(5, "Loading preprocessed dataset…")
        raw_df = pd.read_csv(source_path)
        source_df = _prepare_for_sdv(raw_df)

        if len(source_df) < 50:
            raise ValueError(
                f"Dataset has only {len(source_df)} rows after preprocessing. "
                "Need at least 50 rows for reliable synthetic generation."
            )

        logger.info(
            "Generation %s: source=%d rows, %d cols after SDV prep. Columns: %s",
            gen_id[:8], len(source_df), len(source_df.columns), list(source_df.columns),
        )

        # ── 2. Save generation-ready source for validation ────────────────────
        # This ensures source and synthetic are in exactly the same dtype space.
        _progress(8, "Saving generation-ready source for validation…")
        source_for_val_path = os.path.join(
            settings.EXPORT_DIR, f"{gen_id}_source_for_validation.csv"
        )
        source_df.to_csv(source_for_val_path, index=False)

        # Store path so the validation route can find it
        record = db.get(GenerationRecord, gen_id)
        record.source_for_validation_path = source_for_val_path
        db.commit()

        # ── 3. Build SDV metadata ─────────────────────────────────────────────
        _progress(10, "Analyzing dataset structure…")
        metadata = _build_metadata(source_df)

        # ── 4. Train synthesizer ──────────────────────────────────────────────
        _progress(15, f"Training {model_name} synthesizer ({epochs} epochs)…")
        t_start = time.time()
        used_model = model_name

        try:
            synthesizer, used_model = _make_synthesizer(model_name, metadata, epochs)
            record = db.get(GenerationRecord, gen_id)
            record.status = "training"
            record.model_used = used_model
            db.commit()
            synthesizer.fit(source_df)

        except Exception as train_err:
            if model_name.upper() == "CTGAN":
                _progress(15, f"CTGAN failed ({train_err}). Falling back to TVAE…")
                try:
                    synthesizer, used_model = _make_synthesizer("TVAE", metadata, epochs)
                    record = db.get(GenerationRecord, gen_id)
                    record.model_used = "TVAE"
                    db.commit()
                    synthesizer.fit(source_df)
                except Exception as tvae_err:
                    _progress(15, f"TVAE failed ({tvae_err}). Falling back to GaussianCopula…")
                    synthesizer, used_model = _make_synthesizer("GaussianCopula", metadata, epochs)
                    record = db.get(GenerationRecord, gen_id)
                    record.model_used = "GaussianCopula"
                    db.commit()
                    synthesizer.fit(source_df)
            else:
                raise

        # ── 5. Generate pool ──────────────────────────────────────────────────
        _progress(60, f"Generating synthetic records (model: {used_model})…")
        record = db.get(GenerationRecord, gen_id)
        record.status = "generating"
        db.commit()

        pool_size = min(num_records * 3, max(num_records + 5000, 15000))
        synthetic_pool = synthesizer.sample(num_rows=pool_size)

        # ── 6. Cohort resampling ──────────────────────────────────────────────
        _progress(80, "Applying cohort requirements…")
        cohort_results = {}
        if cohort_config:
            synthetic_df, cohort_results = apply_cohort_requirements(
                synth_df=synthetic_pool,
                source_df=source_df,
                num_records=num_records,
                cohort_config=cohort_config,
            )
        else:
            synthetic_df = synthetic_pool.head(num_records)

        synthetic_df = synthetic_df.head(num_records).reset_index(drop=True)

        # ── 7. Add synt_id if a linkage key was in the source ───────────────
        # Detect whether the original preprocessed CSV had a linkage key.
        # If so, assign new SYN-XXXXXX values as the synt_id column.
        # synt_id is a synthetic/pseudonymous identifier — original IDs are
        # never reused and never appear in the output.
        try:
            original_cols = list(pd.read_csv(source_path, nrows=0).columns)
            had_linkage_key = any(_is_linkage_key(c) for c in original_cols)
        except Exception:
            had_linkage_key = False

        if had_linkage_key:
            synthetic_df.insert(
                0,
                "synt_id",
                [f"SYN-{i+1:06d}" for i in range(len(synthetic_df))],
            )
            logger.info(
                "Assigned synt_id (SYN-000001…SYN-%06d) to synthetic output",
                len(synthetic_df),
            )

        # ── 8. Save synthetic output ──────────────────────────────────────────
        _progress(90, "Saving synthetic dataset…")
        output_path = os.path.join(settings.EXPORT_DIR, f"{gen_id}_synthetic.csv")
        synthetic_df.to_csv(output_path, index=False)

        elapsed = time.time() - t_start

        # ── 9. Finalise record ────────────────────────────────────────────────
        record = db.get(GenerationRecord, gen_id)
        record.status = "done"
        record.progress = 100
        record.progress_message = "Generation complete"
        record.num_generated = len(synthetic_df)
        record.model_used = used_model
        record.output_path = output_path
        record.cohort_results = json.dumps(cohort_results)
        record.generation_time_seconds = round(elapsed, 2)
        record.completed_at = datetime.utcnow()
        db.commit()

        logger.info(
            "Generation %s complete: %d records in %.1fs (model=%s)",
            gen_id[:8], len(synthetic_df), elapsed, used_model,
        )

    except Exception as e:
        record = db.get(GenerationRecord, gen_id)
        if record:
            record.status = "error"
            record.error_message = str(e)
            record.progress_message = f"Error: {e}"
            db.commit()
        logger.error("Generation %s failed: %s", gen_id[:8], e)
        raise


def create_generation_record(
    db: Session,
    dataset_id: str,
    num_records: int,
    model: str,
    cohort_config: Optional[Dict],
) -> GenerationRecord:
    gen_id = new_id()
    record = GenerationRecord(
        id=gen_id,
        dataset_id=dataset_id,
        num_requested=num_records,
        model_used=model,
        cohort_config=json.dumps(cohort_config) if cohort_config else None,
        status="pending",
        progress=0,
        progress_message="Queued",
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
