from __future__ import annotations

import csv
import io
import json
import math
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Iterable

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .config import Settings
from .db import Database
from .api_models import (
    ApiErrorResponse,
    CoverageEvidence,
    DiagnosisItem,
    FacilityMetricsItem,
    FacilityMetricsResponse,
    PaginationMeta,
    PatientDetailResponse,
    PatientListItem,
    PatientListResponse,
    PipelineHealthResponse,
    PipelineRunItem,
    ReconciledWoundItem,
    ReconciliationConflictItem,
    RoutingDecisionItem,
    SelectedFieldEvidenceItem,
    SummaryResponse,
    WoundSummary,
)


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
DATABASE_ENV = "CLAIMREADY_DB_PATH"


def _get_database() -> Database:
    return Database(os.environ.get(DATABASE_ENV) or "claimready.sqlite3")


def create_app(database_path: str | None = None) -> FastAPI:
    settings = Settings(database_path=database_path or os.environ.get(DATABASE_ENV) or "claimready.sqlite3")
    app = FastAPI(title="ClaimReady API", version="1.0.0")
    app.state.database_path = settings.database_path

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_request, exc: HTTPException):  # type: ignore[override]
        return _json_error(exc.status_code, exc.detail or "Request failed")

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_request, exc: RequestValidationError):  # type: ignore[override]
        return _json_error(400, "Invalid request", detail=str(exc))

    @app.exception_handler(ValidationError)
    async def _pydantic_exception_handler(_request, exc: ValidationError):  # type: ignore[override]
        return _json_error(500, "Response validation failed", detail=str(exc))

    @app.exception_handler(Exception)
    async def _fallback_exception_handler(_request, exc: Exception):  # type: ignore[override]
        return _json_error(500, "Unexpected server error", detail=str(exc))

    @app.get("/api/summary", response_model=SummaryResponse)
    def get_summary(database: Database = Depends(_get_database)) -> SummaryResponse:
        with database.connect() as connection:
            return _build_summary(connection)

    @app.get("/api/patients", response_model=PatientListResponse)
    def get_patients(
        database: Database = Depends(_get_database),
        facility_id: int | None = None,
        route: str | None = None,
        wound_type: str | None = None,
        missing_field: str | None = None,
        conflict_status: str | None = None,
        minimum_readiness_score: float | None = Query(default=None, alias="minimum_readiness_score"),
        search: str | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        sort_by: str = Query(default="readiness_score"),
        sort_order: str = Query(default="desc"),
    ) -> PatientListResponse:
        with database.connect() as connection:
            return _list_patients(
                connection,
                facility_id=facility_id,
                route=route,
                wound_type=wound_type,
                missing_field=missing_field,
                conflict_status=conflict_status,
                minimum_readiness_score=minimum_readiness_score,
                search=search,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
            )

    @app.get("/api/patients/{patient_external_id}", response_model=PatientDetailResponse)
    def get_patient_detail(
        patient_external_id: str,
        database: Database = Depends(_get_database),
    ) -> PatientDetailResponse:
        with database.connect() as connection:
            detail = _get_patient_detail(connection, patient_external_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        return detail

    @app.get("/api/facilities", response_model=FacilityMetricsResponse)
    def get_facilities(database: Database = Depends(_get_database)) -> FacilityMetricsResponse:
        with database.connect() as connection:
            return FacilityMetricsResponse(items=_get_facility_metrics(connection))

    @app.get("/api/pipeline-health", response_model=PipelineHealthResponse)
    def get_pipeline_health(database: Database = Depends(_get_database)) -> PipelineHealthResponse:
        with database.connect() as connection:
            return _get_pipeline_health(connection)

    @app.get("/api/export/patients.csv")
    def export_patients_csv(database: Database = Depends(_get_database)) -> Response:
        with database.connect() as connection:
            rows = _export_patient_rows(connection)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else _patient_csv_headers())
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="claimready-patients.csv"'},
        )

    return app


app = create_app()


def _json_error(status_code: int, error: str, *, detail: str | None = None) -> Response:
    payload = ApiErrorResponse(error=error, detail=detail).model_dump()
    return Response(content=json.dumps(payload), status_code=status_code, media_type="application/json")


def _build_summary(connection: sqlite3.Connection) -> SummaryResponse:
    total_patients = _scalar(connection, "select count(distinct id) from patients")
    active_part_b_count = _scalar(
        connection,
        """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
        select count(*)
        from current_patient_routing
        where active_part_b = 1
        """,
    )
    auto_accept_count = _scalar(
        connection,
        """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
        select count(*) from current_patient_routing where route = 'auto_accept'
        """,
    )
    flag_for_review_count = _scalar(
        connection,
        """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
        select count(*) from current_patient_routing where route = 'flag_for_review'
        """,
    )
    reject_count = _scalar(
        connection,
        """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
        select count(*) from current_patient_routing where route = 'reject'
        """,
    )
    claim_ready_rate = round(auto_accept_count / total_patients, 4) if total_patients else 0.0
    unresolved_conflict_count = _scalar(
        connection,
        """
        with current_reconciliation_conflicts as (
            select rc.*
            from reconciliation_conflicts rc
            join (
                select wound_key, field_name, conflict_type, max(reconciliation_run_id) as reconciliation_run_id
                from reconciliation_conflicts
                group by wound_key, field_name, conflict_type
            ) latest
              on latest.wound_key = rc.wound_key
             and latest.field_name = rc.field_name
             and latest.conflict_type = rc.conflict_type
             and latest.reconciliation_run_id = rc.reconciliation_run_id
        )
        select count(*) from current_reconciliation_conflicts where conflict_state = 'unresolved_material'
        """,
    )
    most_common_missing_field = _most_common_missing_field(connection)
    latest_sync_time = _parse_datetime(_scalar_text(connection, "select finished_at from sync_runs where finished_at is not null order by id desc limit 1"))
    latest_reconciliation_time = _parse_datetime(_scalar_text(connection, "select finished_at from reconciliation_runs where finished_at is not null order by id desc limit 1"))
    return SummaryResponse(
        total_patients=total_patients,
        active_medicare_part_b_count=active_part_b_count,
        auto_accept_count=auto_accept_count,
        flag_for_review_count=flag_for_review_count,
        reject_count=reject_count,
        claim_ready_rate=claim_ready_rate,
        unresolved_conflict_count=unresolved_conflict_count,
        most_common_missing_field=most_common_missing_field,
        latest_sync_time=latest_sync_time,
        latest_reconciliation_time=latest_reconciliation_time,
    )


def _list_patients(
    connection: sqlite3.Connection,
    *,
    facility_id: int | None,
    route: str | None,
    wound_type: str | None,
    missing_field: str | None,
    conflict_status: str | None,
    minimum_readiness_score: float | None,
    search: str | None,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
) -> PatientListResponse:
    current_routing_cte = """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
    """
    clauses = ["1 = 1"]
    params: list[Any] = []

    if facility_id is not None:
        clauses.append("p.facility_id = ?")
        params.append(facility_id)
    if route:
        clauses.append("pr.route = ?")
        params.append(route)
    if minimum_readiness_score is not None:
        clauses.append("coalesce(pr.readiness_score, 0) >= ?")
        params.append(minimum_readiness_score)
    if search:
        search_value = f"%{search.lower()}%"
        clauses.append(
            """
            (
                lower(p.patient_id) like ?
                or lower(coalesce(p.first_name, '') || ' ' || coalesce(p.last_name, '')) like ?
            )
            """
        )
        params.extend([search_value, search_value])
    if wound_type:
        clauses.append(
            """
            exists (
                select 1 from reconciled_wounds rw
                where rw.patient_internal_id = p.id and rw.wound_type = ?
            )
            """
        )
        params.append(wound_type)
    if missing_field:
        clauses.append(
            """
            exists (
                select 1 from json_each(coalesce(pr.missing_fields_json, '[]'))
                where json_each.value = ?
            )
            """
        )
        params.append(missing_field)
    if conflict_status:
        clauses.append(
            """
            exists (
                select 1
                from (
                    select rc.*
                    from reconciliation_conflicts rc
                    join (
                        select wound_key, field_name, conflict_type, max(reconciliation_run_id) as reconciliation_run_id
                        from reconciliation_conflicts
                        group by wound_key, field_name, conflict_type
                    ) latest
                      on latest.wound_key = rc.wound_key
                     and latest.field_name = rc.field_name
                     and latest.conflict_type = rc.conflict_type
                     and latest.reconciliation_run_id = rc.reconciliation_run_id
                ) rc
                where rc.patient_internal_id = p.id and rc.conflict_state = ?
            )
            """
        )
        params.append(conflict_status)

    sort_column = {
        "patient_id": "p.patient_id",
        "facility_id": "p.facility_id",
        "route": "coalesce(pr.route, 'reject')",
        "readiness_score": "coalesce(pr.readiness_score, 0)",
        "last_modified_at": "coalesce(pr.selected_at, p.last_modified_at, '')",
        "patient_name": "coalesce(p.last_name, '') || ', ' || coalesce(p.first_name, '')",
    }.get(sort_by, "coalesce(pr.readiness_score, 0)")
    sort_direction = "asc" if sort_order.lower() == "asc" else "desc"

    total = _scalar(
        connection,
        f"""
        {current_routing_cte}
        select count(*)
        from patients p
        left join current_patient_routing pr on pr.patient_internal_id = p.id
        where {" and ".join(clauses)}
        """,
        params,
    )

    offset = (page - 1) * page_size
    rows = connection.execute(
        f"""
        {current_routing_cte}
        select
            p.id as patient_internal_id,
            p.patient_id as patient_external_id,
            p.facility_id,
            p.first_name,
            p.last_name,
            pr.route,
            pr.readiness_score,
            pr.active_part_b,
            pr.primary_wound_key,
            pr.missing_fields_json,
            pr.conflicting_fields_json,
            pr.recommended_next_action,
            pr.readiness_breakdown_json,
            pr.routing_reason_codes_json,
            pr.coverage_status
        from patients p
        left join current_patient_routing pr on pr.patient_internal_id = p.id
        where {" and ".join(clauses)}
        order by {sort_column} {sort_direction}, p.patient_id asc
        limit ? offset ?
        """,
        [*params, page_size, offset],
    ).fetchall()

    wound_map = _primary_wound_map(connection, [int(row["patient_internal_id"]) for row in rows])
    conflict_counts = _conflict_counts(connection, [int(row["patient_internal_id"]) for row in rows])

    items: list[PatientListItem] = []
    for row in rows:
        patient_name = " ".join(part for part in [row["first_name"], row["last_name"]] if part) or row["patient_external_id"]
        primary_wound = wound_map.get(int(row["patient_internal_id"]))
        items.append(
            PatientListItem(
                patient_internal_id=int(row["patient_internal_id"]),
                patient_external_id=str(row["patient_external_id"]),
                patient_name=patient_name,
                facility_id=int(row["facility_id"]),
                facility_label=f"Facility {int(row['facility_id'])}",
                route=str(row["route"] or "reject"),
                readiness_score=float(row["readiness_score"] or 0),
                active_part_b=bool(row["active_part_b"]),
                primary_wound_summary=primary_wound,
                missing_fields=_json_list(row["missing_fields_json"]),
                conflicting_fields=_json_list(row["conflicting_fields_json"]),
                recommended_next_action=str(row["recommended_next_action"] or ""),
                conflict_count=conflict_counts.get(int(row["patient_internal_id"]), 0),
            )
        )

    return PatientListResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=max(1, math.ceil(total / page_size)) if total else 1,
        ),
    )


def _get_patient_detail(connection: sqlite3.Connection, patient_external_id: str) -> PatientDetailResponse | None:
    patient = connection.execute(
        """
        select id, facility_id, patient_id, first_name, last_name, birth_date, gender,
               primary_payer_code, last_modified_at, is_new_admission, raw_json, synced_at
        from patients
        where patient_id = ?
        """,
        (patient_external_id,),
    ).fetchone()
    if patient is None:
        return None

    patient_internal_id = int(patient["id"])
    full_name = " ".join(part for part in [patient["first_name"], patient["last_name"]] if part) or patient["patient_id"]
    routing_row = connection.execute(
        """
        select *
        from patient_routing
        where patient_internal_id = ?
        order by reconciliation_run_id desc
        limit 1
        """,
        (patient_internal_id,),
    ).fetchone()
    routing_decision = _routing_item(routing_row) if routing_row else None

    coverage_rows = connection.execute(
        "select * from coverage_records where patient_id = ? order by effective_from, id",
        (patient["patient_id"],),
    ).fetchall()
    diagnoses = connection.execute(
        "select * from diagnoses where patient_id = ? order by id",
        (patient["patient_id"],),
    ).fetchall()
    reconciled_wounds = connection.execute(
        """
        with current_reconciled_wounds as (
            select rw.*
            from reconciled_wounds rw
            join (
                select wound_key, max(reconciliation_run_id) as reconciliation_run_id
                from reconciled_wounds
                group by wound_key
            ) latest
              on latest.wound_key = rw.wound_key
             and latest.reconciliation_run_id = rw.reconciliation_run_id
        )
        select *
        from current_reconciled_wounds
        where patient_internal_id = ?
        order by wound_key
        """,
        (patient_internal_id,),
    ).fetchall()
    selected_evidence_rows = connection.execute(
        """
        with current_reconciled_wounds as (
            select rw.*
            from reconciled_wounds rw
            join (
                select wound_key, max(reconciliation_run_id) as reconciliation_run_id
                from reconciled_wounds
                group by wound_key
            ) latest
              on latest.wound_key = rw.wound_key
             and latest.reconciliation_run_id = rw.reconciliation_run_id
        ),
        current_selected_field_evidence as (
            select sfe.*
            from selected_field_evidence sfe
            join (
                select wound_key, field_name, max(reconciliation_run_id) as reconciliation_run_id
                from selected_field_evidence
                group by wound_key, field_name
            ) latest
              on latest.wound_key = sfe.wound_key
             and latest.field_name = sfe.field_name
             and latest.reconciliation_run_id = sfe.reconciliation_run_id
        )
        select sfe.*
        from current_selected_field_evidence sfe
        where sfe.wound_key in (select wound_key from current_reconciled_wounds where patient_internal_id = ?)
        order by sfe.wound_key, sfe.field_name
        """,
        (patient_internal_id,),
    ).fetchall()
    conflict_rows = connection.execute(
        """
        with current_reconciled_wounds as (
            select rw.*
            from reconciled_wounds rw
            join (
                select wound_key, max(reconciliation_run_id) as reconciliation_run_id
                from reconciled_wounds
                group by wound_key
            ) latest
              on latest.wound_key = rw.wound_key
             and latest.reconciliation_run_id = rw.reconciliation_run_id
        ),
        current_reconciliation_conflicts as (
            select rc.*
            from reconciliation_conflicts rc
            join (
                select wound_key, field_name, conflict_type, max(reconciliation_run_id) as reconciliation_run_id
                from reconciliation_conflicts
                group by wound_key, field_name, conflict_type
            ) latest
              on latest.wound_key = rc.wound_key
             and latest.field_name = rc.field_name
             and latest.conflict_type = rc.conflict_type
             and latest.reconciliation_run_id = rc.reconciliation_run_id
        )
        select *
        from current_reconciliation_conflicts
        where patient_internal_id = ?
        order by wound_key, field_name, conflict_type
        """,
        (patient_internal_id,),
    ).fetchall()

    wound_by_key = {str(row["wound_key"]): _wound_item(row) for row in reconciled_wounds}
    evidence_by_wound: dict[str, list[SelectedFieldEvidenceItem]] = defaultdict(list)
    for row in selected_evidence_rows:
        evidence_by_wound[str(row["wound_key"])].append(_selected_field_item(row))
    conflicts_by_wound: dict[str, list[ReconciliationConflictItem]] = defaultdict(list)
    for row in conflict_rows:
        conflicts_by_wound[str(row["wound_key"])].append(_conflict_item(row))

    wounds: list[ReconciledWoundItem] = []
    for wound_key, wound in wound_by_key.items():
        wound.selected_fields = evidence_by_wound.get(wound_key, [])
        wound.conflicts = conflicts_by_wound.get(wound_key, [])
        wounds.append(wound)

    primary_wound = next((wound for wound in wounds if wound.is_primary_wound), wounds[0] if wounds else None)

    audit = {
        "patients": [_row_to_dict(patient)],
        "coverage_records": [_row_to_dict(row) for row in coverage_rows],
        "diagnoses": [_row_to_dict(row) for row in diagnoses],
        "progress_notes": [_row_to_dict(row) for row in connection.execute("select * from progress_notes where patient_id = ? order by id", (patient_internal_id,)).fetchall()],
        "assessments": [_row_to_dict(row) for row in connection.execute("select * from assessments where patient_id = ? order by id", (patient_internal_id,)).fetchall()],
        "wound_candidates": [_row_to_dict(row) for row in connection.execute("select * from wound_candidates where patient_internal_id = ? order by candidate_key", (patient_internal_id,)).fetchall()],
        "sync_runs": [_row_to_dict(row) for row in connection.execute("select * from sync_runs order by id desc limit 5").fetchall()],
        "reconciliation_runs": [_row_to_dict(row) for row in connection.execute("select * from reconciliation_runs order by id desc limit 5").fetchall()],
    }

    return PatientDetailResponse(
        patient_internal_id=patient_internal_id,
        patient_external_id=str(patient["patient_id"]),
        patient_name=full_name,
        facility_id=int(patient["facility_id"]),
        demographics={
            "first_name": patient["first_name"],
            "last_name": patient["last_name"],
            "birth_date": patient["birth_date"],
            "gender": patient["gender"],
            "primary_payer_code": patient["primary_payer_code"],
            "is_new_admission": bool(patient["is_new_admission"]),
            "last_modified_at": _parse_datetime(patient["last_modified_at"]),
            "synced_at": _parse_datetime(patient["synced_at"]),
        },
        coverage_evidence=[_coverage_item(row) for row in coverage_rows],
        diagnoses=[_diagnosis_item(row) for row in diagnoses],
        routing_decision=routing_decision,
        explanation=routing_decision.explanation if routing_decision else None,
        primary_wound=primary_wound,
        reconciled_wounds=wounds,
        selected_field_evidence=[_selected_field_item(row) for row in selected_evidence_rows],
        conflicts=[_conflict_item(row) for row in conflict_rows],
        audit=audit,
    )


def _get_facility_metrics(connection: sqlite3.Connection) -> list[FacilityMetricsItem]:
    rows = connection.execute(
        """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
        select
            p.facility_id,
            count(distinct p.id) as patient_count,
            count(distinct case when pr.route = 'auto_accept' then p.id end) as auto_accept_count,
            count(distinct case when pr.route = 'flag_for_review' then p.id end) as review_count,
            count(distinct case when pr.route = 'reject' then p.id end) as reject_count,
            count(case when rc.conflict_state = 'unresolved_material' then 1 end) as conflict_count
        from patients p
        left join current_patient_routing pr on pr.patient_internal_id = p.id
        left join (
            select rc.*
            from reconciliation_conflicts rc
            join (
                select wound_key, field_name, conflict_type, max(reconciliation_run_id) as reconciliation_run_id
                from reconciliation_conflicts
                group by wound_key, field_name, conflict_type
            ) latest
              on latest.wound_key = rc.wound_key
             and latest.field_name = rc.field_name
             and latest.conflict_type = rc.conflict_type
             and latest.reconciliation_run_id = rc.reconciliation_run_id
        ) rc on rc.patient_internal_id = p.id
        group by p.facility_id
        order by p.facility_id
        """
    ).fetchall()

    items: list[FacilityMetricsItem] = []
    for row in rows:
        facility_id = int(row["facility_id"])
        patient_count = int(row["patient_count"])
        auto_accept_count = int(row["auto_accept_count"] or 0)
        review_count = int(row["review_count"] or 0)
        reject_count = int(row["reject_count"] or 0)
        conflict_count = int(row["conflict_count"] or 0)
        wound_type_distribution = _facility_wound_type_distribution(connection, facility_id)
        items.append(
            FacilityMetricsItem(
                facility_id=facility_id,
                facility_label=f"Facility {facility_id}",
                patient_count=patient_count,
                auto_accept_rate=round(auto_accept_count / patient_count, 4) if patient_count else 0.0,
                review_rate=round(review_count / patient_count, 4) if patient_count else 0.0,
                reject_rate=round(reject_count / patient_count, 4) if patient_count else 0.0,
                most_common_missing_fields=_facility_missing_fields(connection, facility_id),
                conflict_count=conflict_count,
                wound_type_distribution=wound_type_distribution,
                route_distribution={
                    "auto_accept": auto_accept_count,
                    "flag_for_review": review_count,
                    "reject": reject_count,
                },
            )
        )
    return items


def _get_pipeline_health(connection: sqlite3.Connection) -> PipelineHealthResponse:
    latest_sync = connection.execute("select * from sync_runs order by id desc limit 1").fetchone()
    latest_reconcile = connection.execute("select * from reconciliation_runs order by id desc limit 1").fetchone()
    latest_sync_id = int(latest_sync["id"]) if latest_sync else None
    endpoint_failures: list[dict[str, Any]] = []
    if latest_sync_id is not None:
        endpoint_failures = [
            {"url": row["url"], "status_code": row["status_code"], "count": row["count"]}
            for row in connection.execute(
                """
                select url, status_code, count(*) as count
                from failed_requests
                where sync_run_id = ?
                group by url, status_code
                order by count(*) desc, url asc
                """,
                (latest_sync_id,),
            ).fetchall()
        ]
    return PipelineHealthResponse(
        latest_sync_run=_pipeline_run_item(latest_sync) if latest_sync else None,
        latest_reconciliation_run=_pipeline_run_item(latest_reconcile) if latest_reconcile else None,
        endpoint_failures=endpoint_failures,
        records_ingested={
            "patients": _scalar(connection, "select count(*) from patients"),
            "diagnoses": _scalar(connection, "select count(*) from diagnoses"),
            "coverage_records": _scalar(connection, "select count(*) from coverage_records"),
            "progress_notes": _scalar(connection, "select count(*) from progress_notes"),
            "assessments": _scalar(connection, "select count(*) from assessments"),
            "wound_candidates": _scalar(connection, "select count(*) from wound_candidates"),
        },
        extraction_candidate_count=_scalar(connection, "select count(*) from wound_candidates"),
    )


def _export_patient_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
        select
            p.patient_id,
            p.first_name,
            p.last_name,
            p.facility_id,
            pr.route,
            pr.readiness_score,
            pr.active_part_b,
            pr.primary_wound_key,
            pr.missing_fields_json,
            pr.conflicting_fields_json,
            pr.recommended_next_action,
            pr.readiness_breakdown_json,
            pr.routing_reason_codes_json
        from patients p
        left join current_patient_routing pr on pr.patient_internal_id = p.id
        order by p.facility_id, p.patient_id
        """
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "patient_external_id": row["patient_id"],
                "patient_name": " ".join(part for part in [row["first_name"], row["last_name"]] if part),
                "facility_id": row["facility_id"],
                "route": row["route"],
                "readiness_score": row["readiness_score"],
                "active_part_b": bool(row["active_part_b"]),
                "primary_wound_key": row["primary_wound_key"],
                "missing_fields": ", ".join(_json_list(row["missing_fields_json"])),
                "conflicting_fields": ", ".join(_json_list(row["conflicting_fields_json"])),
                "recommended_next_action": row["recommended_next_action"],
            }
        )
    return output


def _patient_csv_headers() -> list[str]:
    return [
        "patient_external_id",
        "patient_name",
        "facility_id",
        "route",
        "readiness_score",
        "active_part_b",
        "primary_wound_key",
        "missing_fields",
        "conflicting_fields",
        "recommended_next_action",
    ]


def _primary_wound_map(connection: sqlite3.Connection, patient_internal_ids: list[int]) -> dict[int, WoundSummary]:
    if not patient_internal_ids:
        return {}
    placeholders = ",".join("?" for _ in patient_internal_ids)
    rows = connection.execute(
        f"""
        with current_reconciled_wounds as (
            select rw.*
            from reconciled_wounds rw
            join (
                select wound_key, max(reconciliation_run_id) as reconciliation_run_id
                from reconciled_wounds
                group by wound_key
            ) latest
              on latest.wound_key = rw.wound_key
             and latest.reconciliation_run_id = rw.reconciliation_run_id
        )
        select *
        from current_reconciled_wounds
        where patient_internal_id in ({placeholders})
        order by patient_internal_id, is_primary_wound desc, wound_key
        """,
        patient_internal_ids,
    ).fetchall()
    result: dict[int, WoundSummary] = {}
    for row in rows:
        patient_internal_id = int(row["patient_internal_id"])
        if patient_internal_id not in result:
            result[patient_internal_id] = _wound_summary(row)
    return result


def _conflict_counts(connection: sqlite3.Connection, patient_internal_ids: list[int]) -> dict[int, int]:
    if not patient_internal_ids:
        return {}
    placeholders = ",".join("?" for _ in patient_internal_ids)
    rows = connection.execute(
        f"""
        with current_reconciliation_conflicts as (
            select rc.*
            from reconciliation_conflicts rc
            join (
                select wound_key, field_name, conflict_type, max(reconciliation_run_id) as reconciliation_run_id
                from reconciliation_conflicts
                group by wound_key, field_name, conflict_type
            ) latest
              on latest.wound_key = rc.wound_key
             and latest.field_name = rc.field_name
             and latest.conflict_type = rc.conflict_type
             and latest.reconciliation_run_id = rc.reconciliation_run_id
        )
        select patient_internal_id, count(*) as count
        from current_reconciliation_conflicts
        where conflict_state = 'unresolved_material'
          and patient_internal_id in ({placeholders})
        group by patient_internal_id
        """,
        patient_internal_ids,
    ).fetchall()
    return {int(row["patient_internal_id"]): int(row["count"]) for row in rows}


def _facility_missing_fields(connection: sqlite3.Connection, facility_id: int) -> list[str]:
    rows = connection.execute(
        """
        with current_patient_routing as (
            select pr.*
            from patient_routing pr
            join (
                select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                from patient_routing
                group by patient_internal_id
            ) latest
              on latest.patient_internal_id = pr.patient_internal_id
             and latest.reconciliation_run_id = pr.reconciliation_run_id
        )
        select pr.missing_fields_json
        from patients p
        left join current_patient_routing pr on pr.patient_internal_id = p.id
        where p.facility_id = ?
        """,
        (facility_id,),
    ).fetchall()
    counter = Counter()
    for row in rows:
        for field in _json_list(row["missing_fields_json"]):
            counter[field] += 1
    return [field for field, _count in counter.most_common(3)]


def _facility_wound_type_distribution(connection: sqlite3.Connection, facility_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        with current_reconciled_wounds as (
            select rw.*
            from reconciled_wounds rw
            join (
                select wound_key, max(reconciliation_run_id) as reconciliation_run_id
                from reconciled_wounds
                group by wound_key
            ) latest
              on latest.wound_key = rw.wound_key
             and latest.reconciliation_run_id = rw.reconciliation_run_id
        )
        select coalesce(rw.wound_type, 'unknown') as wound_type, count(*) as count
        from current_reconciled_wounds rw
        join patients p on p.id = rw.patient_internal_id
        where p.facility_id = ?
        group by coalesce(rw.wound_type, 'unknown')
        order by count(*) desc, wound_type asc
        """,
        (facility_id,),
    ).fetchall()
    return [{"wound_type": row["wound_type"], "count": int(row["count"])} for row in rows]


def _routing_item(row: sqlite3.Row | None) -> RoutingDecisionItem | None:
    if row is None:
        return None
    return RoutingDecisionItem(
        route=str(row["route"]),
        coverage_status=str(row["coverage_status"]),
        active_part_b=bool(row["active_part_b"]),
        qualifying_wound_present=bool(row["qualifying_wound_present"]),
        primary_wound_key=row["primary_wound_key"],
        explanation=str(row["explanation"]),
        missing_fields=_json_list(row["missing_fields_json"]),
        conflicting_fields=_json_list(row["conflicting_fields_json"]),
        recommended_next_action=str(row["recommended_next_action"]),
        readiness_score=float(row["readiness_score"]),
        readiness_breakdown_json=_json_object(row["readiness_breakdown_json"]),
        routing_reason_codes_json=_json_list(row["routing_reason_codes_json"]),
        coverage_record_id=row["coverage_record_id"],
        coverage_record_snapshot_json=_json_object(row["coverage_record_snapshot_json"]),
        selected_at=_parse_datetime(row["selected_at"]),
        synced_at=_parse_datetime(row["synced_at"]),
    )


def _wound_item(row: sqlite3.Row) -> ReconciledWoundItem:
    return ReconciledWoundItem(
        wound_key=str(row["wound_key"]),
        patient_internal_id=int(row["patient_internal_id"]),
        patient_external_id=str(row["patient_external_id"]),
        primary_candidate_key=row["primary_candidate_key"],
        primary_source_type=row["primary_source_type"],
        primary_source_record_id=row["primary_source_record_id"],
        primary_source_date=_parse_datetime(row["primary_source_date"]),
        primary_source_excerpt=row["primary_source_excerpt"],
        wound_type=row["wound_type"],
        pressure_ulcer_stage=row["pressure_ulcer_stage"],
        location=row["location"],
        length_cm=row["length_cm"],
        width_cm=row["width_cm"],
        depth_cm=row["depth_cm"],
        drainage_amount=row["drainage_amount"],
        documentation_state=row["documentation_state"],
        is_active_wound=bool(row["is_active_wound"]),
        is_primary_wound=bool(row["is_primary_wound"]),
        confidence=float(row["confidence"]),
        selection_reason=str(row["selection_reason"]),
        selected_at=_parse_datetime(row["selected_at"]),
        synced_at=_parse_datetime(row["synced_at"]),
    )


def _wound_summary(row: sqlite3.Row) -> WoundSummary:
    return WoundSummary(
        wound_key=str(row["wound_key"]),
        wound_type=row["wound_type"],
        pressure_ulcer_stage=row["pressure_ulcer_stage"],
        location=row["location"],
        length_cm=row["length_cm"],
        width_cm=row["width_cm"],
        depth_cm=row["depth_cm"],
        drainage_amount=row["drainage_amount"],
        documentation_state=row["documentation_state"],
        is_primary_wound=bool(row["is_primary_wound"]),
    )


def _selected_field_item(row: sqlite3.Row) -> SelectedFieldEvidenceItem:
    return SelectedFieldEvidenceItem(
        candidate_key=str(row["candidate_key"]),
        wound_key=str(row["wound_key"]),
        field_name=str(row["field_name"]),
        selected_value=row["selected_value"],
        value_type=str(row["value_type"]),
        source_type=str(row["source_type"]),
        source_record_id=str(row["source_record_id"]),
        source_date=_parse_datetime(row["source_date"]),
        source_excerpt=row["source_excerpt"],
        extraction_method=str(row["extraction_method"]),
        confidence=float(row["confidence"]),
        selection_reason=str(row["selection_reason"]),
        alternative_values_json=_json_list_of_dicts(row["alternative_values_json"]),
        conflict_status=str(row["conflict_status"]),
        precedence_rank=int(row["precedence_rank"]),
        synced_at=_parse_datetime(row["synced_at"]),
    )


def _conflict_item(row: sqlite3.Row) -> ReconciliationConflictItem:
    return ReconciliationConflictItem(
        wound_key=str(row["wound_key"]),
        field_name=str(row["field_name"]),
        conflict_type=str(row["conflict_type"]),
        conflict_state=str(row["conflict_state"]),
        selected_value=row["selected_value"],
        alternative_values_json=_json_list_of_dicts(row["alternative_values_json"]),
        threshold_json=_json_object(row["threshold_json"]),
        source_records_json=_json_list_of_dicts(row["source_records_json"]),
        source_dates_json=_json_list(row["source_dates_json"]),
        source_excerpts_json=_json_list(row["source_excerpts_json"]),
        explanation=str(row["explanation"]),
        synced_at=_parse_datetime(row["synced_at"]),
    )


def _coverage_item(row: sqlite3.Row) -> CoverageEvidence:
    raw_json = _json_object(row["raw_json"])
    return CoverageEvidence(
        id=int(row["id"]),
        patient_id=str(row["patient_id"]),
        payer_name=row["payer_name"],
        payer_code=row["payer_code"],
        payer_type=row["payer_type"],
        effective_from=_parse_date(row["effective_from"]),
        effective_to=_parse_date(row["effective_to"]),
        last_modified_at=_parse_datetime(row["last_modified_at"]),
        raw_json=raw_json,
        is_active_part_b=_is_active_part_b(row),
    )


def _diagnosis_item(row: sqlite3.Row) -> DiagnosisItem:
    return DiagnosisItem(
        id=int(row["id"]),
        patient_id=str(row["patient_id"]),
        icd10_code=row["icd10_code"],
        icd10_description=row["icd10_description"],
        clinical_status=row["clinical_status"],
        onset_date=_parse_date(row["onset_date"]),
        last_modified_at=_parse_datetime(row["last_modified_at"]),
        raw_json=_json_object(row["raw_json"]),
    )


def _pipeline_run_item(row: sqlite3.Row) -> PipelineRunItem:
    return PipelineRunItem(
        id=int(row["id"]),
        started_at=_parse_datetime(row["started_at"]),
        finished_at=_parse_datetime(row["finished_at"]),
        status=str(row["status"]),
        mode=row["mode"] if "mode" in row.keys() else None,
        evaluation_date=_parse_date(row["evaluation_date"]) if "evaluation_date" in row.keys() and row["evaluation_date"] else None,
        request_count=int(row["request_count"]) if "request_count" in row.keys() and row["request_count"] is not None else 0,
        retry_count=int(row["retry_count"]) if "retry_count" in row.keys() and row["retry_count"] is not None else 0,
        rate_limited_count=int(row["rate_limited_count"]) if "rate_limited_count" in row.keys() and row["rate_limited_count"] is not None else 0,
        failure_count=int(row["failure_count"]) if "failure_count" in row.keys() and row["failure_count"] is not None else 0,
        total_latency_ms=float(row["total_latency_ms"]) if "total_latency_ms" in row.keys() and row["total_latency_ms"] is not None else 0.0,
        patients_evaluated=int(row["patients_evaluated"]) if "patients_evaluated" in row.keys() and row["patients_evaluated"] is not None else 0,
        wounds_reconciled=int(row["wounds_reconciled"]) if "wounds_reconciled" in row.keys() and row["wounds_reconciled"] is not None else 0,
        historical_conflicts=int(row["historical_conflicts"]) if "historical_conflicts" in row.keys() and row["historical_conflicts"] is not None else 0,
        resolved_conflicts=int(row["resolved_conflicts"]) if "resolved_conflicts" in row.keys() and row["resolved_conflicts"] is not None else 0,
        unresolved_conflicts=int(row["unresolved_conflicts"]) if "unresolved_conflicts" in row.keys() and row["unresolved_conflicts"] is not None else 0,
        auto_accept_count=int(row["auto_accept_count"]) if "auto_accept_count" in row.keys() and row["auto_accept_count"] is not None else 0,
        flag_for_review_count=int(row["flag_for_review_count"]) if "flag_for_review_count" in row.keys() and row["flag_for_review_count"] is not None else 0,
        reject_count=int(row["reject_count"]) if "reject_count" in row.keys() and row["reject_count"] is not None else 0,
    )


def _scalar(connection: sqlite3.Connection, sql: str, params: Iterable[Any] | None = None) -> int:
    row = connection.execute(sql, tuple(params or ())).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _scalar_text(connection: sqlite3.Connection, sql: str, params: Iterable[Any] | None = None) -> str | None:
    row = connection.execute(sql, tuple(params or ())).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def _json_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _json_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _json_object(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    try:
        parsed = json.loads(value)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _most_common_missing_field(connection: sqlite3.Connection) -> str | None:
    try:
        row = connection.execute(
            """
            with current_patient_routing as (
                select pr.*
                from patient_routing pr
                join (
                    select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                    from patient_routing
                    group by patient_internal_id
                ) latest
                  on latest.patient_internal_id = pr.patient_internal_id
                 and latest.reconciliation_run_id = pr.reconciliation_run_id
            )
            select json_each.value, count(distinct current_patient_routing.patient_internal_id) as count
            from current_patient_routing, json_each(current_patient_routing.missing_fields_json)
            group by json_each.value
            order by count desc, json_each.value asc
            limit 1
            """
        ).fetchone()
    except sqlite3.OperationalError:
        counts = Counter()
        for row in connection.execute(
            """
            with current_patient_routing as (
                select pr.*
                from patient_routing pr
                join (
                    select patient_internal_id, max(reconciliation_run_id) as reconciliation_run_id
                    from patient_routing
                    group by patient_internal_id
                ) latest
                  on latest.patient_internal_id = pr.patient_internal_id
                 and latest.reconciliation_run_id = pr.reconciliation_run_id
            )
            select missing_fields_json from current_patient_routing
            """
        ):
            for field in _json_list(row["missing_fields_json"]):
                counts[field] += 1
        return counts.most_common(1)[0][0] if counts else None
    return str(row[0]) if row else None


def _is_active_part_b(row: sqlite3.Row) -> bool:
    payer_code = str(row["payer_code"] or "")
    payer_type = str(row["payer_type"] or "")
    if payer_code != "MCB" and payer_type != "Medicare B":
        return False
    effective_from = _parse_date(row["effective_from"])
    effective_to = _parse_date(row["effective_to"])
    today = date.today()
    if effective_from and effective_from > today:
        return False
    if effective_to and effective_to < today:
        return False
    return True
