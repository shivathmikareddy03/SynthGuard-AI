// ── Dataset ───────────────────────────────────────────────────────────────────

export interface ColumnInfo {
  name: string
  dtype: string
  missing_count: number
  missing_pct: number
  unique_count: number
  sample_values: (string | number | boolean)[]
  is_sensitive: boolean
}

export interface PrivacyClassification {
  direct_identifiers: string[]
  longitudinal_linkage_keys: string[]
  temporal_columns: string[]
  quasi_identifiers: string[]
  sensitive_health_attributes: string[]
  clinical: string[]
  excluded_from_modeling: string[]   // direct_identifiers + longitudinal_linkage_keys
}

export interface LongitudinalInfo {
  is_longitudinal: boolean
  dataset_type: 'longitudinal' | 'cross_sectional' | 'unknown'
  linkage_key: string | null
  temporal_column: string | null
  unique_subjects: number
  total_observations: number
  avg_obs_per_subject: number
  max_obs_per_subject: number
  repeated_subjects: number
}

export interface DatasetProfile {
  id: string
  filename: string
  num_rows: number
  num_columns: number
  columns: ColumnInfo[]
  sensitive_columns: string[]              // direct identifiers only (backward compat)
  privacy_classification: PrivacyClassification
  longitudinal_info: LongitudinalInfo
  approved_columns: string[]
  preprocessing_summary?: PreprocessingResult
  status: 'uploaded' | 'preprocessed' | 'error'
  created_at: string
  is_demo?: boolean
}

export interface PreprocessingResult {
  dataset_id: string
  rows_before: number
  rows_after: number
  missing_handled: Record<string, number>
  duplicates_removed: number
  columns_excluded: string[]
  columns_included: string[]
  status: string
}

// ── Generation ───────────────────────────────────────────────────────────────

// ── Dynamic cohort types (new dataset-driven API) ─────────────────────────

export type CohortOperator =
  | 'greater_than' | 'gt'
  | 'less_than'    | 'lt'
  | 'gte' | 'greater_than_or_equal'
  | 'lte' | 'less_than_or_equal'
  | 'equal' | 'eq'
  | 'between'
  | 'in_values'
  | 'not_equal' | 'ne'

export type ColumnKind = 'numerical' | 'binary' | 'ordinal' | 'categorical'

export interface CohortColumnProfile {
  name: string
  dtype: string
  kind: ColumnKind
  // numerical
  min?: number | null
  max?: number | null
  mean?: number | null
  unique_count?: number
  // categorical / binary / ordinal
  unique_values?: string[]
  ordinal_order?: string[]
}

export interface CohortProfileResponse {
  dataset_id: string
  columns: CohortColumnProfile[]
  total_columns: number
}

export interface CohortRequirement {
  id: string            // client-side UUID for React keys
  feature: string
  operator: CohortOperator
  value: string | number | [number, number] | string[]
  target_proportion: number   // 0–1
  label?: string
}

export interface CohortRequirementResult {
  feature: string
  operator: string
  value: unknown
  label: string
  requested_pct: number
  generated_pct: number | null
  diff_pct: number | null
  status: 'pass' | 'warn' | 'column_missing'
}

export interface ValidationError {
  id: string
  message: string
}

// Legacy cohort config (kept for backward compatibility)
export interface CohortConfig {
  older_patients_pct?: number
  diabetic_pct?: number
  activity_distribution?: Record<string, number>
  age_column?: string
  diabetes_column?: string
  activity_column?: string
}

export interface GenerateRequest {
  dataset_id: string
  num_records: number
  model: 'CTGAN' | 'TVAE' | 'GAUSSIANCOPULA'
  epochs?: number
  cohort?: CohortConfig                // legacy
  requirements?: Omit<CohortRequirement, 'id'>[]  // new dynamic
}

export interface GenerationStatus {
  id: string
  dataset_id: string
  status: 'pending' | 'training' | 'generating' | 'done' | 'error'
  progress: number
  progress_message: string
  model_used: string | null
  num_requested: number
  num_generated: number | null
  generation_time_seconds: number | null
  cohort_results: Record<string, unknown> | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}

export interface PreviewResponse {
  generation_id: string
  columns: string[]
  rows: Record<string, unknown>[]
  total_rows: number
  page: number
  page_size: number
}

// ── Validation ───────────────────────────────────────────────────────────────

export interface NumericalColumnStats {
  column: string
  source_n: number
  synth_n: number
  ks_capped_synth_n: number
  source_mean: number
  synth_mean: number
  source_std: number
  synth_std: number
  source_median: number
  synth_median: number
  source_min: number
  synth_min: number
  source_max: number
  synth_max: number
  source_q25: number
  synth_q25: number
  source_q75: number
  synth_q75: number
  ks_statistic: number | null
  ks_pvalue: number | null
  ks_pass: boolean
  ks_status: 'pass' | 'fail' | 'insufficient_data' | 'not_numeric'
  ks_alpha: number
  cohort_affected: boolean
  distribution_similarity: number
}

export interface CategoricalColumnStats {
  column: string
  source_distribution: Record<string, number>
  synth_distribution: Record<string, number>
  chi2_statistic: number | null
  chi2_pvalue: number | null
  tvd: number
  similarity_score: number
}

export interface CorrelationStat {
  col_a: string
  col_b: string
  source_correlation: number
  synth_correlation: number
  difference: number
}

export interface ValidationReport {
  validation_id: string
  generation_id: string
  numerical_stats: NumericalColumnStats[]
  categorical_stats: CategoricalColumnStats[]
  correlation_stats: CorrelationStat[]
  overall_scores: {
    distribution_similarity: number
    correlation_preservation: number
    ks_pass_rate: number
    ks_passed_columns: number
    ks_tested_columns: number
    ks_skipped_columns: number
    overall_quality: number
  }
  created_at: string
}

// ── Privacy ───────────────────────────────────────────────────────────────────

export interface PrivacyReport {
  privacy_id: string
  generation_id: string
  exact_duplicates: number
  near_duplicates: number
  risk_level: 'Low' | 'Medium' | 'High'
  total_source_records: number
  total_synthetic_records: number
  duplicate_rate_pct: number
  near_duplicate_rate_pct: number
  details: {
    disclaimer: string
    exact_duplicate_rate_pct: number
    near_duplicate_rate_pct: number
    near_duplicate_threshold: number
    near_duplicate_sample_details: Array<{
      synth_idx: number
      nearest_source_idx: number
      distance: number
    }>
    total_source_records: number
    total_synthetic_records: number
    risk_interpretation: string
    note: string
  }
  created_at: string
}

// ── App state ─────────────────────────────────────────────────────────────────

export type WorkflowStep =
  | 'idle'
  | 'uploaded'
  | 'preprocessed'
  | 'generating'
  | 'done'

export interface AppState {
  dataset: DatasetProfile | null
  preprocessing: PreprocessingResult | null
  generation: GenerationStatus | null
  validation: ValidationReport | null
  privacy: PrivacyReport | null
  currentStep: WorkflowStep
}
