from __future__ import annotations

import csv
import io
import json
from datetime import date

from fastapi.testclient import TestClient

from claimready.api_models import (
    FacilityMetricsResponse,
    PatientDetailResponse,
    PatientListResponse,
    PipelineHealthResponse,
    SummaryResponse,
)
from claimready.models import RequestEvent, SyncResult, WoundCandidateRecord


def test_summary_endpoint_reports_database_metrics(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get("/api/summary")

    assert response.status_code == 200
    summary = SummaryResponse.model_validate(response.json())
    assert summary.total_patients == 3
    assert summary.active_medicare_part_b_count == 2
    assert summary.auto_accept_count == 1
    assert summary.flag_for_review_count == 1
    assert summary.reject_count == 1
    assert summary.claim_ready_rate == 0.3333
    assert summary.unresolved_conflict_count == 1
    assert summary.most_common_missing_field == "depth_cm"
    assert summary.latest_sync_time is not None
    assert summary.latest_reconciliation_time is not None
    assert summary.auto_accept_count + summary.flag_for_review_count + summary.reject_count == summary.total_patients
    assert summary.active_medicare_part_b_count <= summary.total_patients
    assert summary.auto_accept_count <= summary.total_patients
    assert summary.flag_for_review_count <= summary.total_patients
    assert summary.reject_count <= summary.total_patients
    assert 0 <= summary.claim_ready_rate <= 1


def test_patients_endpoint_supports_filters_search_sort_and_pagination(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get(
        "/api/patients",
        params={
            "facility_id": 101,
            "route": "flag_for_review",
            "wound_type": "pressure_ulcer",
            "missing_field": "depth_cm",
            "conflict_status": "unresolved_material",
            "minimum_readiness_score": 20,
            "search": "Fox",
            "sort_by": "patient_name",
            "sort_order": "asc",
        },
    )

    assert response.status_code == 200
    payload = PatientListResponse.model_validate(response.json())
    assert payload.pagination.total == 1
    assert len(payload.items) == 1
    item = payload.items[0]
    assert item.patient_external_id == "FB-001"
    assert item.facility_id == 101
    assert item.route == "flag_for_review"
    assert item.active_part_b is True
    assert item.primary_wound_summary is not None
    assert item.primary_wound_summary.wound_type == "pressure_ulcer"
    assert "depth_cm" in item.missing_fields
    assert "length_cm" in item.conflicting_fields
    assert "documentation_state" in item.conflicting_fields
    assert item.recommended_next_action == "Review documentation before release."
    assert item.conflict_count >= 1
    assert 0 <= item.readiness_score <= 100


def test_patients_endpoint_returns_current_state_rows_without_multiplication(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get("/api/patients", params={"page": 1, "page_size": 25, "sort_by": "patient_id"})

    assert response.status_code == 200
    payload = PatientListResponse.model_validate(response.json())
    assert payload.pagination.total == 3
    assert len(payload.items) == 3
    assert len({item.patient_internal_id for item in payload.items}) == 3
    assert len({item.patient_external_id for item in payload.items}) == 3
    assert sum(1 for item in payload.items if item.route == "auto_accept") == 1
    assert sum(1 for item in payload.items if item.route == "flag_for_review") == 1
    assert sum(1 for item in payload.items if item.route == "reject") == 1


def test_patients_endpoint_returns_paginated_rows(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get("/api/patients", params={"page": 1, "page_size": 2, "sort_by": "patient_id"})

    assert response.status_code == 200
    payload = PatientListResponse.model_validate(response.json())
    assert payload.pagination.total == 3
    assert payload.pagination.total_pages == 2
    assert len(payload.items) == 2


def test_patient_detail_endpoint_returns_traceable_audit_payload(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get("/api/patients/FB-001")

    assert response.status_code == 200
    payload = PatientDetailResponse.model_validate(response.json())
    assert payload.patient_external_id == "FB-001"
    assert payload.coverage_evidence
    assert payload.diagnoses
    assert payload.routing_decision is not None
    assert payload.primary_wound is not None
    assert payload.selected_field_evidence
    assert payload.conflicts
    assert payload.audit["coverage_records"]
    assert payload.audit["wound_candidates"]
    assert payload.audit["reconciliation_runs"]
    assert payload.audit["sync_runs"]
    assert payload.selected_field_evidence[0].value_type in {"text", "numeric"}
    assert len({(item.wound_key, item.field_name) for item in payload.selected_field_evidence}) == len(payload.selected_field_evidence)
    assert len({(item.wound_key, item.field_name, item.conflict_type) for item in payload.conflicts}) == len(payload.conflicts)


def test_facilities_endpoint_reports_facility_metrics(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get("/api/facilities")

    assert response.status_code == 200
    payload = FacilityMetricsResponse.model_validate(response.json())
    assert len(payload.items) == 2
    facility_101 = next(item for item in payload.items if item.facility_id == 101)
    assert facility_101.patient_count == 2
    assert facility_101.auto_accept_rate == 0.5
    assert facility_101.review_rate == 0.5
    assert facility_101.reject_rate == 0.0
    assert facility_101.conflict_count == 1
    assert facility_101.most_common_missing_fields[0] == "depth_cm"
    assert facility_101.wound_type_distribution[0]["wound_type"] == "pressure_ulcer"
    assert facility_101.auto_accept_rate + facility_101.review_rate + facility_101.reject_rate == 1.0
    assert facility_101.patient_count == facility_101.route_distribution["auto_accept"] + facility_101.route_distribution["flag_for_review"] + facility_101.route_distribution["reject"]
    assert facility_101.route_distribution["auto_accept"] + facility_101.route_distribution["flag_for_review"] + facility_101.route_distribution["reject"] == facility_101.patient_count


def test_fixture_database_summary_and_facility_metrics_are_current_state_safe(tmp_path, monkeypatch) -> None:
    client = _build_fixture_api_client(tmp_path, monkeypatch)

    summary_response = client.get("/api/summary")
    facilities_response = client.get("/api/facilities")
    patients_response = client.get("/api/patients", params={"page": 1, "page_size": 25, "sort_by": "patient_id"})

    summary = SummaryResponse.model_validate(summary_response.json())
    facilities = FacilityMetricsResponse.model_validate(facilities_response.json())
    patients = PatientListResponse.model_validate(patients_response.json())

    assert summary.total_patients == 6
    assert summary.active_medicare_part_b_count == 3
    assert summary.auto_accept_count == 3
    assert summary.flag_for_review_count == 0
    assert summary.reject_count == 3
    assert summary.claim_ready_rate == 0.5
    assert summary.unresolved_conflict_count == 0
    assert summary.auto_accept_count + summary.flag_for_review_count + summary.reject_count == summary.total_patients
    assert summary.active_medicare_part_b_count <= summary.total_patients
    assert summary.auto_accept_count <= summary.total_patients
    assert summary.flag_for_review_count <= summary.total_patients
    assert summary.reject_count <= summary.total_patients
    assert 0 <= summary.claim_ready_rate <= 1

    assert patients.pagination.total == 6
    assert len(patients.items) == 6
    assert len({item.patient_internal_id for item in patients.items}) == 6
    assert len({item.patient_external_id for item in patients.items}) == 6
    assert sum(1 for item in patients.items if item.route == "auto_accept") == 3
    assert sum(1 for item in patients.items if item.route == "flag_for_review") == 0
    assert sum(1 for item in patients.items if item.route == "reject") == 3
    assert all(0 <= item.readiness_score <= 100 for item in patients.items)
    assert all(item.conflict_count == 0 for item in patients.items if item.route == "auto_accept")

    for facility in facilities.items:
        assert facility.auto_accept_rate + facility.review_rate + facility.reject_rate == 1.0
        assert facility.route_distribution["auto_accept"] + facility.route_distribution["flag_for_review"] + facility.route_distribution["reject"] == facility.patient_count
        assert facility.conflict_count == 0


def test_fixture_patient_detail_uses_current_state_rows_without_duplicates(tmp_path, monkeypatch) -> None:
    client = _build_fixture_api_client(tmp_path, monkeypatch)

    response = client.get("/api/patients/FA-001")

    assert response.status_code == 200
    payload = PatientDetailResponse.model_validate(response.json())
    assert len(payload.selected_field_evidence) == len({(item.wound_key, item.field_name) for item in payload.selected_field_evidence})
    assert len(payload.conflicts) == len({(item.wound_key, item.field_name, item.conflict_type) for item in payload.conflicts})
    assert payload.routing_decision is not None
    assert payload.primary_wound is not None
    assert payload.selected_field_evidence


def test_pipeline_health_endpoint_returns_latest_runs_and_counts(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get("/api/pipeline-health")

    assert response.status_code == 200
    payload = PipelineHealthResponse.model_validate(response.json())
    assert payload.latest_sync_run is not None
    assert payload.latest_sync_run.status == "completed"
    assert payload.latest_sync_run.request_count == 6
    assert payload.latest_sync_run.retry_count == 2
    assert payload.latest_sync_run.rate_limited_count == 1
    assert payload.latest_sync_run.failure_count == 1
    assert payload.latest_reconciliation_run is not None
    assert payload.latest_reconciliation_run.status == "completed"
    assert payload.latest_reconciliation_run.patients_evaluated == 3
    assert payload.latest_reconciliation_run.wounds_reconciled == 3
    assert payload.latest_reconciliation_run.historical_conflicts == 1
    assert payload.latest_reconciliation_run.resolved_conflicts == 1
    assert payload.latest_reconciliation_run.unresolved_conflicts == 1
    assert payload.endpoint_failures
    assert payload.records_ingested["patients"] == 3
    assert payload.extraction_candidate_count == 4


def test_export_patients_csv_returns_current_state_rows(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    response = client.get("/api/export/patients.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    reader = csv.DictReader(io.StringIO(response.text))
    rows = list(reader)
    assert len(rows) == 3
    assert rows[0]["patient_external_id"] == "FA-001"
    assert "recommended_next_action" in rows[0]


def test_validation_errors_and_not_found_are_consistently_structured(tmp_path, monkeypatch) -> None:
    client, _database = _build_api_client(tmp_path, monkeypatch)

    validation_response = client.get("/api/patients", params={"page": 0})
    not_found_response = client.get("/api/patients/ZZ-404")

    assert validation_response.status_code == 400
    assert validation_response.json()["error"] == "Invalid request"
    assert not_found_response.status_code == 404
    assert not_found_response.json()["error"] == "Patient not found"


def _build_api_client(tmp_path, monkeypatch) -> tuple[TestClient, object]:
    from claimready.api import create_app
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    db_path = tmp_path / "claimready.sqlite3"
    monkeypatch.setenv("CLAIMREADY_DB_PATH", str(db_path))

    database = Database(db_path)
    database.initialize()
    _seed_database(database)
    _seed_sync_and_reconcile(database)

    return TestClient(create_app(str(db_path))), database


def _build_fixture_api_client(tmp_path, monkeypatch) -> TestClient:
    from claimready.api import create_app
    from claimready.cli import main as claimready_main

    db_path = tmp_path / "claimready-fixture.sqlite3"
    monkeypatch.setenv("CLAIMREADY_DB_PATH", str(db_path))

    exit_code = claimready_main(["--database", str(db_path), "--use-fixtures", "reconcile"])
    assert exit_code == 0

    return TestClient(create_app(str(db_path)))


def _seed_database(database) -> None:
    database.upsert_patients(
        [
            {
                "id": 1,
                "facility_id": 101,
                "patient_id": "FA-001",
                "first_name": "Agnes",
                "last_name": "Dunbar",
                "birth_date": "1942-05-04",
                "gender": "Female",
                "primary_payer_code": "MCB",
                "last_modified_at": "2026-05-17T19:13:00",
                "is_new_admission": True,
            },
            {
                "id": 2,
                "facility_id": 101,
                "patient_id": "FB-001",
                "first_name": "Beatrice",
                "last_name": "Fox",
                "birth_date": "1941-03-14",
                "gender": "Female",
                "primary_payer_code": "MCB",
                "last_modified_at": "2026-05-17T19:13:00",
                "is_new_admission": True,
            },
            {
                "id": 3,
                "facility_id": 202,
                "patient_id": "FC-001",
                "first_name": "Carla",
                "last_name": "West",
                "birth_date": "1944-11-22",
                "gender": "Female",
                "primary_payer_code": "HMO",
                "last_modified_at": "2026-05-17T19:13:00",
                "is_new_admission": False,
            },
        ]
    )
    database.insert_diagnoses(
        [
            {
                "id": 1,
                "patient_id": "FA-001",
                "icd10_code": "L89.153",
                "icd10_description": "Pressure ulcer of sacral region, stage 3",
                "clinical_status": "active",
                "onset_date": "2026-04-11",
                "last_modified_at": "2026-05-17T19:13:00",
            },
            {
                "id": 2,
                "patient_id": "FB-001",
                "icd10_code": "L89.623",
                "icd10_description": "Pressure ulcer of right heel, stage 3",
                "clinical_status": "active",
                "onset_date": "2026-04-18",
                "last_modified_at": "2026-05-17T19:13:00",
            },
        ]
    )
    database.insert_coverage_records(
        [
            {
                "id": 1,
                "patient_id": "FA-001",
                "payer_name": "Medicare Part B",
                "payer_code": "MCB",
                "payer_type": "Medicare B",
                "effective_from": "2020-01-01T00:00:00",
                "effective_to": None,
                "last_modified_at": "2026-05-17T19:13:00",
            },
            {
                "id": 2,
                "patient_id": "FB-001",
                "payer_name": "Medicare Part B",
                "payer_code": "MCB",
                "payer_type": "Medicare B",
                "effective_from": "2020-01-01T00:00:00",
                "effective_to": None,
                "last_modified_at": "2026-05-17T19:13:00",
            },
            {
                "id": 3,
                "patient_id": "FC-001",
                "payer_name": "Commercial HMO",
                "payer_code": "HMO",
                "payer_type": "HMO",
                "effective_from": "2020-01-01T00:00:00",
                "effective_to": None,
                "last_modified_at": "2026-05-17T19:13:00",
            },
        ]
    )
    database.insert_progress_notes(
        [
            {
                "id": 1,
                "patient_id": 1,
                "org_id": "ORG-1",
                "pcc_note_id": 1001,
                "note_type": "progress_note",
                "effective_date": "2026-05-11T09:00:00",
                "note_text": "Stage III sacral pressure ulcer with moderate drainage.",
                "created_by": "RN",
                "note_label": "SOAP",
                "sync_version": 1,
                "is_current": True,
            },
            {
                "id": 2,
                "patient_id": 2,
                "org_id": "ORG-1",
                "pcc_note_id": 1002,
                "note_type": "progress_note",
                "effective_date": "2026-05-11T10:00:00",
                "note_text": "Right heel wound measured 4.0 x 2.1 cm with moderate drainage.",
                "created_by": "RN",
                "note_label": "Narrative",
                "sync_version": 1,
                "is_current": True,
            },
        ]
    )
    database.insert_assessments(
        [
            {
                "id": 1,
                "patient_id": 1,
                "org_id": "ORG-1",
                "pcc_assessment_id": 2001,
                "assessment_type": "wound",
                "status": "complete",
                "assessment_date": "2026-05-10",
                "completion_date": "2026-05-10",
                "template_id": 501,
                "assessment_type_description": "Structured wound assessment",
                "raw_json": json.dumps(
                    {
                        "wound_type": "pressure_ulcer",
                        "stage": 3,
                        "location": "Sacrum",
                        "length_cm": 3.4,
                        "width_cm": 2.1,
                        "depth_cm": 0.5,
                        "drainage_amount": "moderate",
                    }
                ),
                "sync_version": 1,
                "is_current": True,
            },
            {
                "id": 2,
                "patient_id": 2,
                "org_id": "ORG-1",
                "pcc_assessment_id": 2002,
                "assessment_type": "wound",
                "status": "complete",
                "assessment_date": "2026-05-10",
                "completion_date": "2026-05-10",
                "template_id": 502,
                "assessment_type_description": "Structured wound assessment",
                "raw_json": json.dumps(
                    {
                        "wound_type": "pressure_ulcer",
                        "stage": 2,
                        "location": "Right Heel",
                        "length_cm": 4.0,
                        "width_cm": 2.0,
                        "depth_cm": None,
                        "drainage_amount": "moderate",
                    }
                ),
                "sync_version": 1,
                "is_current": True,
            },
            {
                "id": 3,
                "patient_id": 3,
                "org_id": "ORG-1",
                "pcc_assessment_id": 2003,
                "assessment_type": "wound",
                "status": "complete",
                "assessment_date": "2026-05-10",
                "completion_date": "2026-05-10",
                "template_id": 503,
                "assessment_type_description": "Structured wound assessment",
                "raw_json": json.dumps(
                    {
                        "wound_type": "diabetic_foot_ulcer",
                        "location": "Left Foot",
                        "length_cm": 2.1,
                        "width_cm": 1.3,
                        "depth_cm": 0.3,
                        "drainage_amount": "light",
                    }
                ),
                "sync_version": 1,
                "is_current": True,
            },
        ]
    )
    database.insert_wound_candidates(
        [
            _candidate(
                candidate_key="assessment:1:1",
                patient_internal_id=1,
                patient_external_id="FA-001",
                source_type="assessment",
                source_record_id="1",
                source_date="2026-05-10",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="3",
                location="Sacrum",
                length_cm=3.4,
                width_cm=2.1,
                depth_cm=0.5,
                drainage_amount="moderate",
                source_excerpt="Structured sacral assessment.",
                raw_source_json='{"wound_type":"pressure_ulcer"}',
            ),
            _candidate(
                candidate_key="progress_note:2:1",
                patient_internal_id=2,
                patient_external_id="FB-001",
                source_type="progress_note",
                source_record_id="2",
                source_date="2026-05-11T10:00:00",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="2",
                location="Right Heel",
                length_cm=4.3,
                width_cm=2.1,
                depth_cm=None,
                drainage_amount="moderate",
                extraction_method="narrative_note",
                source_excerpt="Right heel wound measured 4.3 x 2.1 cm with moderate drainage.",
                raw_source_text="Right heel wound measured 4.3 x 2.1 cm with moderate drainage.",
                confidence=0.7,
            ),
            _candidate(
                candidate_key="progress_note:2:2",
                patient_internal_id=2,
                patient_external_id="FB-001",
                source_type="progress_note",
                source_record_id="3",
                source_date="2026-05-11T11:00:00",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="2",
                location="Right Heel",
                length_cm=4.0,
                width_cm=2.1,
                depth_cm=None,
                drainage_amount="moderate",
                extraction_method="narrative_note",
                source_excerpt="Right heel wound measured 4.0 x 2.1 cm with moderate drainage.",
                raw_source_text="Right heel wound measured 4.0 x 2.1 cm with moderate drainage.",
                confidence=0.7,
            ),
            _candidate(
                candidate_key="assessment:3:1",
                patient_internal_id=3,
                patient_external_id="FC-001",
                source_type="assessment",
                source_record_id="3",
                source_date="2026-05-10",
                wound_type="diabetic_foot_ulcer",
                pressure_ulcer_stage=None,
                location="Left Foot",
                length_cm=2.1,
                width_cm=1.3,
                depth_cm=0.3,
                drainage_amount="light",
                source_excerpt="Left foot ulcer.",
                raw_source_json='{"wound_type":"diabetic_foot_ulcer"}',
            ),
        ]
    )


def _seed_sync_and_reconcile(database) -> None:
    from claimready.reconcile import reconcile_database

    sync_run_id = database.start_sync_run("fixture", [101, 202], None)
    database.log_event(
        sync_run_id,
        RequestEvent(
            method="GET",
            url="/pcc/patients?facility_id=101",
            attempt=1,
            status_code=200,
            duration_ms=12.5,
            outcome="success",
        ),
    )
    database.log_event(
        sync_run_id,
        RequestEvent(
            method="GET",
            url="/pcc/notes?facility_id=101",
            attempt=1,
            status_code=500,
            duration_ms=18.0,
            outcome="failed",
            response_text='{"detail":"notes unavailable"}',
            error="HTTP 500",
        ),
    )
    database.log_failed_request(
        sync_run_id,
        RequestEvent(
            method="GET",
            url="/pcc/notes?facility_id=101",
            attempt=1,
            status_code=500,
            duration_ms=18.0,
            outcome="failed",
            response_text='{"detail":"notes unavailable"}',
            error="HTTP 500",
        ),
    )
    database.finish_sync_run(
        sync_run_id,
        SyncResult(
            sync_run_id=sync_run_id,
            facilities_synced=[101, 202],
            request_count=6,
            retry_count=2,
            rate_limited_count=1,
            failure_count=1,
            total_latency_ms=123.4,
        ),
        status="completed",
    )
    reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))


def _candidate(
    *,
    candidate_key: str,
    patient_internal_id: int,
    patient_external_id: str,
    source_type: str,
    source_record_id: str,
    source_date: str,
    wound_type: str | None,
    pressure_ulcer_stage: str | None,
    location: str | None,
    length_cm: float | None,
    width_cm: float | None,
    depth_cm: float | None,
    drainage_amount: str | None,
    source_excerpt: str,
    raw_source_json: str | None = None,
    raw_source_text: str | None = None,
    documentation_state: str = "active",
    extraction_method: str = "assessment_raw_json",
    confidence: float = 0.95,
) -> WoundCandidateRecord:
    return WoundCandidateRecord(
        candidate_key=candidate_key,
        patient_internal_id=patient_internal_id,
        patient_external_id=patient_external_id,
        source_type=source_type,
        source_record_id=source_record_id,
        source_date=source_date,
        wound_index=1,
        documentation_state=documentation_state,
        wound_type=wound_type,
        pressure_ulcer_stage=pressure_ulcer_stage,
        location=location,
        length_cm=length_cm,
        width_cm=width_cm,
        depth_cm=depth_cm,
        drainage_amount=drainage_amount,
        extraction_method=extraction_method,
        confidence=confidence,
        source_excerpt=source_excerpt,
        raw_source_text=raw_source_text,
        raw_source_json=raw_source_json,
    )
