export type Route = "auto_accept" | "flag_for_review" | "reject";

export type SummaryResponse = {
  total_patients: number;
  active_medicare_part_b_count: number;
  auto_accept_count: number;
  flag_for_review_count: number;
  reject_count: number;
  claim_ready_rate: number;
  unresolved_conflict_count: number;
  most_common_missing_field: string | null;
  latest_sync_time: string | null;
  latest_reconciliation_time: string | null;
};

export type PaginationMeta = {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export type WoundSummary = {
  wound_key: string;
  wound_type: string | null;
  pressure_ulcer_stage: string | null;
  location: string | null;
  length_cm: number | null;
  width_cm: number | null;
  depth_cm: number | null;
  drainage_amount: string | null;
  documentation_state: string | null;
  is_primary_wound: boolean;
};

export type PatientListItem = {
  patient_internal_id: number;
  patient_external_id: string;
  patient_name: string;
  facility_id: number;
  facility_label: string;
  route: Route;
  readiness_score: number;
  active_part_b: boolean;
  primary_wound_summary: WoundSummary | null;
  missing_fields: string[];
  conflicting_fields: string[];
  recommended_next_action: string;
  conflict_count: number;
};

export type PatientListResponse = {
  items: PatientListItem[];
  pagination: PaginationMeta;
};

export type CoverageEvidence = {
  id: number;
  patient_id: string;
  payer_name: string | null;
  payer_code: string | null;
  payer_type: string | null;
  effective_from: string | null;
  effective_to: string | null;
  last_modified_at: string | null;
  raw_json: Record<string, unknown> | null;
  is_active_part_b: boolean;
};

export type DiagnosisItem = {
  id: number;
  patient_id: string;
  icd10_code: string | null;
  icd10_description: string | null;
  clinical_status: string | null;
  onset_date: string | null;
  last_modified_at: string | null;
  raw_json: Record<string, unknown> | null;
};

export type SelectedFieldEvidenceItem = {
  candidate_key: string;
  wound_key: string;
  field_name: string;
  selected_value: string | null;
  value_type: string;
  source_type: string;
  source_record_id: string;
  source_date: string | null;
  source_excerpt: string | null;
  extraction_method: string;
  confidence: number;
  selection_reason: string;
  alternative_values_json: Array<Record<string, unknown>>;
  conflict_status: string;
  precedence_rank: number;
  synced_at: string | null;
};

export type ReconciliationConflictItem = {
  wound_key: string;
  field_name: string;
  conflict_type: string;
  conflict_state: string;
  selected_value: string | null;
  alternative_values_json: Array<Record<string, unknown>>;
  threshold_json: Record<string, unknown>;
  source_records_json: Array<Record<string, unknown>>;
  source_dates_json: string[];
  source_excerpts_json: string[];
  explanation: string;
  synced_at: string | null;
};

export type ReconciledWoundItem = {
  wound_key: string;
  patient_internal_id: number;
  patient_external_id: string;
  primary_candidate_key: string | null;
  primary_source_type: string | null;
  primary_source_record_id: string | null;
  primary_source_date: string | null;
  primary_source_excerpt: string | null;
  wound_type: string | null;
  pressure_ulcer_stage: string | null;
  location: string | null;
  length_cm: number | null;
  width_cm: number | null;
  depth_cm: number | null;
  drainage_amount: string | null;
  documentation_state: string | null;
  is_active_wound: boolean;
  is_primary_wound: boolean;
  confidence: number;
  selection_reason: string;
  selected_at: string | null;
  synced_at: string | null;
  selected_fields: SelectedFieldEvidenceItem[];
  conflicts: ReconciliationConflictItem[];
};

export type RoutingDecisionItem = {
  route: Route;
  coverage_status: string;
  active_part_b: boolean;
  qualifying_wound_present: boolean;
  primary_wound_key: string | null;
  explanation: string;
  missing_fields: string[];
  conflicting_fields: string[];
  recommended_next_action: string;
  readiness_score: number;
  readiness_breakdown_json: Record<string, unknown>;
  routing_reason_codes_json: string[];
  coverage_record_id: number | null;
  coverage_record_snapshot_json: Record<string, unknown> | null;
  selected_at: string | null;
  synced_at: string | null;
};

export type PatientDetailResponse = {
  patient_internal_id: number;
  patient_external_id: string;
  patient_name: string;
  facility_id: number;
  demographics: Record<string, unknown>;
  coverage_evidence: CoverageEvidence[];
  diagnoses: DiagnosisItem[];
  routing_decision: RoutingDecisionItem | null;
  explanation: string | null;
  primary_wound: ReconciledWoundItem | null;
  reconciled_wounds: ReconciledWoundItem[];
  selected_field_evidence: SelectedFieldEvidenceItem[];
  conflicts: ReconciliationConflictItem[];
  audit: Record<string, unknown>;
};

export type FacilityMetricsItem = {
  facility_id: number;
  facility_label: string;
  patient_count: number;
  auto_accept_rate: number;
  review_rate: number;
  reject_rate: number;
  most_common_missing_fields: string[];
  conflict_count: number;
  wound_type_distribution: Array<{ wound_type: string; count: number }>;
  route_distribution: Record<string, number>;
};

export type FacilityMetricsResponse = {
  items: FacilityMetricsItem[];
};

export type PipelineRunItem = {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  mode: string | null;
  evaluation_date: string | null;
  request_count: number;
  retry_count: number;
  rate_limited_count: number;
  failure_count: number;
  total_latency_ms: number;
  patients_evaluated: number;
  wounds_reconciled: number;
  historical_conflicts: number;
  resolved_conflicts: number;
  unresolved_conflicts: number;
  auto_accept_count: number;
  flag_for_review_count: number;
  reject_count: number;
};

export type PipelineHealthResponse = {
  latest_sync_run: PipelineRunItem | null;
  latest_reconciliation_run: PipelineRunItem | null;
  endpoint_failures: Array<{ url: string; status_code: number | null; count: number }>;
  records_ingested: Record<string, number>;
  extraction_candidate_count: number;
};

export type ApiErrorResponse = {
  error: string;
  detail?: string | null;
};
