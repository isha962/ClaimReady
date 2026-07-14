from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PaginationMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    page_size: int
    total: int
    total_pages: int


class WoundSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wound_key: str
    wound_type: str | None = None
    pressure_ulcer_stage: str | None = None
    location: str | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    depth_cm: float | None = None
    drainage_amount: str | None = None
    documentation_state: str | None = None
    is_primary_wound: bool = False


class PatientListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_internal_id: int
    patient_external_id: str
    patient_name: str
    facility_id: int
    facility_label: str
    route: Literal["auto_accept", "flag_for_review", "reject"]
    readiness_score: float
    active_part_b: bool
    primary_wound_summary: WoundSummary | None = None
    missing_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    recommended_next_action: str
    conflict_count: int


class PatientListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PatientListItem]
    pagination: PaginationMeta


class SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_patients: int
    active_medicare_part_b_count: int
    auto_accept_count: int
    flag_for_review_count: int
    reject_count: int
    claim_ready_rate: float
    unresolved_conflict_count: int
    most_common_missing_field: str | None = None
    latest_sync_time: datetime | None = None
    latest_reconciliation_time: datetime | None = None


class CoverageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    patient_id: str
    payer_name: str | None = None
    payer_code: str | None = None
    payer_type: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    last_modified_at: datetime | None = None
    raw_json: dict[str, Any] | None = None
    is_active_part_b: bool = False


class DiagnosisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    patient_id: str
    icd10_code: str | None = None
    icd10_description: str | None = None
    clinical_status: str | None = None
    onset_date: date | None = None
    last_modified_at: datetime | None = None
    raw_json: dict[str, Any] | None = None


class SelectedFieldEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_key: str
    wound_key: str
    field_name: str
    selected_value: str | None = None
    value_type: str
    source_type: str
    source_record_id: str
    source_date: datetime | None = None
    source_excerpt: str | None = None
    extraction_method: str
    confidence: float
    selection_reason: str
    alternative_values_json: list[dict[str, Any]]
    conflict_status: str
    precedence_rank: int
    synced_at: datetime | None = None


class ReconciliationConflictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wound_key: str
    field_name: str
    conflict_type: str
    conflict_state: str
    selected_value: str | None = None
    alternative_values_json: list[dict[str, Any]]
    threshold_json: dict[str, Any]
    source_records_json: list[dict[str, Any]]
    source_dates_json: list[str]
    source_excerpts_json: list[str]
    explanation: str
    synced_at: datetime | None = None


class ReconciledWoundItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wound_key: str
    patient_internal_id: int
    patient_external_id: str
    primary_candidate_key: str | None = None
    primary_source_type: str | None = None
    primary_source_record_id: str | None = None
    primary_source_date: datetime | None = None
    primary_source_excerpt: str | None = None
    wound_type: str | None = None
    pressure_ulcer_stage: str | None = None
    location: str | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    depth_cm: float | None = None
    drainage_amount: str | None = None
    documentation_state: str | None = None
    is_active_wound: bool
    is_primary_wound: bool
    confidence: float
    selection_reason: str
    selected_at: datetime | None = None
    synced_at: datetime | None = None
    selected_fields: list[SelectedFieldEvidenceItem] = Field(default_factory=list)
    conflicts: list[ReconciliationConflictItem] = Field(default_factory=list)


class RoutingDecisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: Literal["auto_accept", "flag_for_review", "reject"]
    coverage_status: str
    active_part_b: bool
    qualifying_wound_present: bool
    primary_wound_key: str | None = None
    explanation: str
    missing_fields: list[str]
    conflicting_fields: list[str]
    recommended_next_action: str
    readiness_score: float
    readiness_breakdown_json: dict[str, Any]
    routing_reason_codes_json: list[str]
    coverage_record_id: int | None = None
    coverage_record_snapshot_json: dict[str, Any] | None = None
    selected_at: datetime | None = None
    synced_at: datetime | None = None


class PatientDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_internal_id: int
    patient_external_id: str
    patient_name: str
    facility_id: int
    demographics: dict[str, Any]
    coverage_evidence: list[CoverageEvidence]
    diagnoses: list[DiagnosisItem]
    routing_decision: RoutingDecisionItem | None = None
    explanation: str | None = None
    primary_wound: ReconciledWoundItem | None = None
    reconciled_wounds: list[ReconciledWoundItem]
    selected_field_evidence: list[SelectedFieldEvidenceItem]
    conflicts: list[ReconciliationConflictItem]
    audit: dict[str, Any]


class FacilityMetricsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_id: int
    facility_label: str
    patient_count: int
    auto_accept_rate: float
    review_rate: float
    reject_rate: float
    most_common_missing_fields: list[str]
    conflict_count: int
    wound_type_distribution: list[dict[str, Any]]
    route_distribution: dict[str, int]


class FacilityMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FacilityMetricsItem]


class PipelineRunItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str
    mode: str | None = None
    evaluation_date: date | None = None
    request_count: int = 0
    retry_count: int = 0
    rate_limited_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    patients_evaluated: int = 0
    wounds_reconciled: int = 0
    historical_conflicts: int = 0
    resolved_conflicts: int = 0
    unresolved_conflicts: int = 0
    auto_accept_count: int = 0
    flag_for_review_count: int = 0
    reject_count: int = 0


class PipelineHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest_sync_run: PipelineRunItem | None = None
    latest_reconciliation_run: PipelineRunItem | None = None
    endpoint_failures: list[dict[str, Any]]
    records_ingested: dict[str, int]
    extraction_candidate_count: int


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str
    detail: str | None = None
