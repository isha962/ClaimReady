from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SyncWindow:
    patients_since: str | None = None
    notes_since: str | None = None
    assessments_since: str | None = None


@dataclass(slots=True)
class SyncResult:
    sync_run_id: int
    facilities_synced: list[int]
    request_count: int
    retry_count: int
    rate_limited_count: int
    failure_count: int
    total_latency_ms: float = 0.0


@dataclass(slots=True)
class ClientStats:
    request_count: int = 0
    retry_count: int = 0
    rate_limited_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0


@dataclass(slots=True)
class RequestEvent:
    method: str
    url: str
    attempt: int
    status_code: int | None
    duration_ms: float
    outcome: str
    retry_after: float | None = None
    wait_seconds: float | None = None
    response_text: str | None = None
    error: str | None = None


@dataclass(slots=True)
class PatientRecord:
    id: int
    facility_id: int
    patient_id: str
    first_name: str | None
    last_name: str | None
    birth_date: str | None
    gender: str | None
    primary_payer_code: str | None
    last_modified_at: str | None
    is_new_admission: bool
    raw: dict[str, Any]


@dataclass(slots=True)
class DiagnosisRecord:
    id: int
    patient_id: str
    icd10_code: str | None
    icd10_description: str | None
    clinical_status: str | None
    onset_date: str | None
    last_modified_at: str | None
    raw: dict[str, Any]


@dataclass(slots=True)
class CoverageRecord:
    id: int
    patient_id: str
    payer_name: str | None
    payer_code: str | None
    payer_type: str | None
    effective_from: str | None
    effective_to: str | None
    last_modified_at: str | None
    raw: dict[str, Any]


@dataclass(slots=True)
class ProgressNoteRecord:
    id: int
    patient_id: int
    org_id: str | None
    pcc_note_id: int | None
    note_type: str | None
    effective_date: str | None
    note_text: str | None
    created_by: str | None
    note_label: str | None
    sync_version: int | None
    is_current: bool
    raw: dict[str, Any]


@dataclass(slots=True)
class AssessmentRecord:
    id: int
    patient_id: int
    org_id: str | None
    pcc_assessment_id: int | None
    assessment_type: str | None
    status: str | None
    assessment_date: str | None
    completion_date: str | None
    template_id: int | None
    assessment_type_description: str | None
    raw_json: str | None
    sync_version: int | None
    is_current: bool
    raw: dict[str, Any]


@dataclass(slots=True)
class FieldEvidenceRecord:
    candidate_key: str
    field_name: str
    candidate_value: str | None
    normalized_value: str | None
    source_type: str
    source_record_id: str
    source_date: str | None
    source_excerpt: str | None
    extraction_method: str
    confidence: float


@dataclass(slots=True)
class FieldConflictRecord:
    candidate_key: str
    field_name: str
    conflicting_values_json: str
    source_type: str
    source_record_id: str
    source_date: str | None
    source_excerpt: str | None
    extraction_method: str
    confidence: float


@dataclass(slots=True)
class WoundCandidateRecord:
    candidate_key: str
    patient_internal_id: int
    patient_external_id: str | None
    source_type: str
    source_record_id: str
    source_date: str | None
    wound_index: int
    documentation_state: str
    wound_type: str | None
    pressure_ulcer_stage: str | None
    location: str | None
    length_cm: float | None
    width_cm: float | None
    depth_cm: float | None
    drainage_amount: str | None
    extraction_method: str
    confidence: float
    source_excerpt: str | None
    raw_source_text: str | None
    raw_source_json: str | None
    conflict_count: int = 0
    field_evidence: list[FieldEvidenceRecord] = field(default_factory=list, repr=False)
    field_conflicts: list[FieldConflictRecord] = field(default_factory=list, repr=False)


@dataclass(slots=True)
class ExtractionResult:
    candidate_count: int
    evidence_count: int
    conflict_count: int
    source_counts: dict[str, int]


@dataclass(slots=True)
class ReconciliationRunRecord:
    id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    status: str = "running"
    evaluation_date: str | None = None
    patients_evaluated: int = 0
    wounds_reconciled: int = 0
    historical_conflicts: int = 0
    resolved_conflicts: int = 0
    unresolved_conflicts: int = 0
    auto_accept_count: int = 0
    flag_for_review_count: int = 0
    reject_count: int = 0
    error_message: str | None = None


@dataclass(slots=True)
class WoundGroupMemberRecord:
    reconciliation_run_id: int
    wound_key: str
    candidate_key: str
    match_score: float
    match_reason: str
    synced_at: str


@dataclass(slots=True)
class SelectedFieldEvidenceRecord:
    reconciliation_run_id: int
    wound_key: str
    candidate_key: str
    field_name: str
    selected_value: str | None
    value_type: str
    source_type: str
    source_record_id: str
    source_date: str | None
    source_excerpt: str | None
    extraction_method: str
    confidence: float
    selection_reason: str
    alternative_values_json: str
    conflict_status: str
    precedence_rank: int
    synced_at: str


@dataclass(slots=True)
class ReconciliationConflictRecord:
    reconciliation_run_id: int
    patient_internal_id: int
    patient_external_id: str | None
    wound_key: str
    field_name: str
    conflict_type: str
    conflict_state: str
    selected_value: str | None
    alternative_values_json: str
    threshold_json: str
    source_records_json: str
    source_dates_json: str
    source_excerpts_json: str
    explanation: str
    synced_at: str


@dataclass(slots=True)
class ReconciledWoundRecord:
    reconciliation_run_id: int
    wound_key: str
    patient_internal_id: int
    patient_external_id: str | None
    primary_candidate_key: str | None
    primary_source_type: str | None
    primary_source_record_id: str | None
    primary_source_date: str | None
    primary_source_excerpt: str | None
    wound_type: str | None
    pressure_ulcer_stage: str | None
    location: str | None
    length_cm: float | None
    width_cm: float | None
    depth_cm: float | None
    drainage_amount: str | None
    documentation_state: str | None
    is_active_wound: bool
    is_primary_wound: bool
    confidence: float
    selection_reason: str
    selected_at: str
    synced_at: str


@dataclass(slots=True)
class RoutingDecision:
    reconciliation_run_id: int
    patient_internal_id: int
    patient_external_id: str | None
    evaluation_date: str
    coverage_status: str
    coverage_record_id: int | None
    coverage_record_snapshot_json: str | None
    active_part_b: bool
    qualifying_wound_present: bool
    primary_wound_key: str | None
    route: str
    explanation: str
    missing_fields_json: str
    conflicting_fields_json: str
    recommended_next_action: str
    readiness_score: float
    readiness_breakdown_json: str
    routing_reason_codes_json: str
    selected_at: str
    synced_at: str


@dataclass(slots=True)
class ReconciliationResult:
    reconciliation_run_id: int
    patients_evaluated: int
    wounds_reconciled: int
    historical_conflicts: int
    resolved_conflicts: int
    unresolved_conflicts: int
    auto_accept_count: int
    flag_for_review_count: int
    reject_count: int
    decisions_by_patient: dict[str, RoutingDecision] = field(default_factory=dict)
    wounds_by_key: dict[str, ReconciledWoundRecord] = field(default_factory=dict)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    return value
