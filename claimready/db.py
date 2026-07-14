from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import (
    AssessmentRecord,
    FieldConflictRecord,
    FieldEvidenceRecord,
    CoverageRecord,
    DiagnosisRecord,
    PatientRecord,
    ProgressNoteRecord,
    ReconciledWoundRecord,
    ReconciliationConflictRecord,
    ReconciliationRunRecord,
    RequestEvent,
    RoutingDecision,
    SyncResult,
    SyncWindow,
    SelectedFieldEvidenceRecord,
    WoundCandidateRecord,
    WoundGroupMemberRecord,
)


SCHEMA_STATEMENTS = (
    """
    create table if not exists patients (
        id integer primary key,
        facility_id integer not null,
        patient_id text not null unique,
        first_name text,
        last_name text,
        birth_date text,
        gender text,
        primary_payer_code text,
        last_modified_at text,
        is_new_admission integer not null default 0,
        raw_json text not null,
        synced_at text not null
    )
    """,
    """
    create table if not exists diagnoses (
        id integer primary key,
        patient_id text not null,
        icd10_code text,
        icd10_description text,
        clinical_status text,
        onset_date text,
        last_modified_at text,
        raw_json text not null,
        synced_at text not null
    )
    """,
    """
    create table if not exists coverage_records (
        id integer primary key,
        patient_id text not null,
        payer_name text,
        payer_code text,
        payer_type text,
        effective_from text,
        effective_to text,
        last_modified_at text,
        raw_json text not null,
        synced_at text not null
    )
    """,
    """
    create table if not exists progress_notes (
        id integer primary key,
        patient_id integer not null,
        org_id text,
        pcc_note_id integer,
        note_type text,
        effective_date text,
        note_text text,
        created_by text,
        note_label text,
        sync_version integer,
        is_current integer not null default 1,
        raw_json text not null,
        synced_at text not null
    )
    """,
    """
    create table if not exists assessments (
        id integer primary key,
        patient_id integer not null,
        org_id text,
        pcc_assessment_id integer,
        assessment_type text,
        status text,
        assessment_date text,
        completion_date text,
        template_id integer,
        assessment_type_description text,
        raw_json text,
        sync_version integer,
        is_current integer not null default 1,
        synced_at text not null
    )
    """,
    """
    create table if not exists wound_candidates (
        candidate_key text primary key,
        patient_internal_id integer not null,
        patient_external_id text,
        source_type text not null,
        source_record_id text not null,
        source_date text,
        wound_index integer not null,
        documentation_state text not null,
        wound_type text,
        pressure_ulcer_stage text,
        location text,
        length_cm real,
        width_cm real,
        depth_cm real,
        drainage_amount text,
        extraction_method text not null,
        confidence real not null,
        source_excerpt text,
        raw_source_text text,
        raw_source_json text,
        conflict_count integer not null default 0,
        synced_at text not null
    )
    """,
    """
    create table if not exists reconciliation_runs (
        id integer primary key autoincrement,
        started_at text not null,
        finished_at text,
        status text not null,
        evaluation_date text not null,
        patients_evaluated integer not null default 0,
        wounds_reconciled integer not null default 0,
        historical_conflicts integer not null default 0,
        resolved_conflicts integer not null default 0,
        unresolved_conflicts integer not null default 0,
        auto_accept_count integer not null default 0,
        flag_for_review_count integer not null default 0,
        reject_count integer not null default 0,
        error_message text
    )
    """,
    """
    create table if not exists reconciled_wounds (
        reconciliation_run_id integer not null,
        wound_key text not null,
        patient_internal_id integer not null,
        patient_external_id text,
        primary_candidate_key text,
        primary_source_type text,
        primary_source_record_id text,
        primary_source_date text,
        primary_source_excerpt text,
        wound_type text,
        pressure_ulcer_stage text,
        location text,
        length_cm real,
        width_cm real,
        depth_cm real,
        drainage_amount text,
        documentation_state text,
        is_active_wound integer not null default 0,
        is_primary_wound integer not null default 0,
        confidence real not null,
        selection_reason text not null,
        selected_at text not null,
        synced_at text not null,
        primary key (reconciliation_run_id, wound_key)
    )
    """,
    """
    create table if not exists selected_field_evidence (
        reconciliation_run_id integer not null,
        wound_key text not null,
        candidate_key text not null,
        field_name text not null,
        selected_value text,
        value_type text not null,
        source_type text not null,
        source_record_id text not null,
        source_date text,
        source_excerpt text,
        extraction_method text not null,
        confidence real not null,
        selection_reason text not null,
        alternative_values_json text not null,
        conflict_status text not null,
        precedence_rank integer not null,
        synced_at text not null,
        primary key (reconciliation_run_id, wound_key, field_name)
    )
    """,
    """
    create table if not exists reconciliation_conflicts (
        reconciliation_run_id integer not null,
        patient_internal_id integer not null,
        patient_external_id text,
        wound_key text not null,
        field_name text not null,
        conflict_type text not null,
        conflict_state text not null,
        selected_value text,
        alternative_values_json text not null,
        threshold_json text not null,
        source_records_json text not null,
        source_dates_json text not null,
        source_excerpts_json text not null,
        explanation text not null,
        synced_at text not null,
        primary key (reconciliation_run_id, wound_key, field_name, conflict_type, conflict_state)
    )
    """,
    """
    create table if not exists patient_routing (
        reconciliation_run_id integer not null,
        patient_internal_id integer not null,
        patient_external_id text,
        evaluation_date text not null,
        coverage_status text not null,
        coverage_record_id integer,
        coverage_record_snapshot_json text,
        active_part_b integer not null default 0,
        qualifying_wound_present integer not null default 0,
        primary_wound_key text,
        route text not null,
        explanation text not null,
        missing_fields_json text not null,
        conflicting_fields_json text not null,
        recommended_next_action text not null,
        readiness_score real not null,
        readiness_breakdown_json text not null,
        routing_reason_codes_json text not null,
        selected_at text not null,
        synced_at text not null,
        primary key (reconciliation_run_id, patient_internal_id)
    )
    """,
    """
    create table if not exists wound_group_members (
        reconciliation_run_id integer not null,
        wound_key text not null,
        candidate_key text not null,
        match_score real not null,
        match_reason text not null,
        synced_at text not null,
        primary key (reconciliation_run_id, wound_key, candidate_key)
    )
    """,
    """
    create table if not exists field_evidence (
        id integer primary key autoincrement,
        candidate_key text not null,
        field_name text not null,
        candidate_value text,
        normalized_value text,
        source_type text not null,
        source_record_id text not null,
        source_date text,
        source_excerpt text,
        extraction_method text not null,
        confidence real not null
    )
    """,
    """
    create table if not exists field_conflicts (
        id integer primary key autoincrement,
        candidate_key text not null,
        field_name text not null,
        conflicting_values_json text not null,
        source_type text not null,
        source_record_id text not null,
        source_date text,
        source_excerpt text,
        extraction_method text not null,
        confidence real not null
    )
    """,
    """
    create table if not exists sync_runs (
        id integer primary key autoincrement,
        started_at text not null,
        finished_at text,
        status text not null,
        mode text not null,
        facilities_json text not null,
        since_json text,
        request_count integer not null default 0,
        retry_count integer not null default 0,
        rate_limited_count integer not null default 0,
        failure_count integer not null default 0,
        total_latency_ms real not null default 0
    )
    """,
    """
    create table if not exists api_request_log (
        id integer primary key autoincrement,
        sync_run_id integer not null,
        recorded_at text not null,
        method text not null,
        url text not null,
        attempt integer not null,
        status_code integer,
        duration_ms real not null,
        retry_after real,
        wait_seconds real,
        outcome text not null,
        response_text text,
        error text
    )
    """,
    """
    create table if not exists failed_requests (
        id integer primary key autoincrement,
        sync_run_id integer not null,
        recorded_at text not null,
        method text not null,
        url text not null,
        attempt integer not null,
        status_code integer,
        retry_after real,
        wait_seconds real,
        response_text text,
        error text
    )
    """,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("begin immediate")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            self._ensure_column(connection, "api_request_log", "wait_seconds", "real")
            self._ensure_column(connection, "failed_requests", "wait_seconds", "real")
            self._migrate_reconciliation_current_state(connection)

    def start_sync_run(self, mode: str, facilities: list[int], since: SyncWindow | None) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                insert into sync_runs (
                    started_at, status, mode, facilities_json, since_json
                ) values (?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    "running",
                    mode,
                    _json_text(facilities),
                    _json_text(asdict(since)) if since else None,
                ),
            )
            return int(cursor.lastrowid)

    def finish_sync_run(self, sync_run_id: int, result: SyncResult, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                update sync_runs
                set finished_at = ?, status = ?, request_count = ?, retry_count = ?,
                    rate_limited_count = ?, failure_count = ?, total_latency_ms = ?
                where id = ?
                """,
                (
                    _now(),
                    status,
                    result.request_count,
                    result.retry_count,
                    result.rate_limited_count,
                    result.failure_count,
                    result.total_latency_ms,
                    sync_run_id,
                ),
            )

    def log_event(self, sync_run_id: int, event: RequestEvent) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into api_request_log (
                    sync_run_id, recorded_at, method, url, attempt, status_code,
                    duration_ms, retry_after, wait_seconds, outcome, response_text, error
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sync_run_id,
                    _now(),
                    event.method,
                    event.url,
                    event.attempt,
                    event.status_code,
                    event.duration_ms,
                    event.retry_after,
                    event.wait_seconds,
                    event.outcome,
                    event.response_text,
                    event.error,
                ),
            )

    def log_failed_request(self, sync_run_id: int, event: RequestEvent) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into failed_requests (
                    sync_run_id, recorded_at, method, url, attempt, status_code,
                    retry_after, wait_seconds, response_text, error
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sync_run_id,
                    _now(),
                    event.method,
                    event.url,
                    event.attempt,
                    event.status_code,
                    event.retry_after,
                    event.wait_seconds,
                    event.response_text,
                    event.error,
                ),
            )

    def upsert_patients(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into patients (
                    id, facility_id, patient_id, first_name, last_name, birth_date,
                    gender, primary_payer_code, last_modified_at, is_new_admission,
                    raw_json, synced_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    facility_id=excluded.facility_id,
                    patient_id=excluded.patient_id,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    birth_date=excluded.birth_date,
                    gender=excluded.gender,
                    primary_payer_code=excluded.primary_payer_code,
                    last_modified_at=excluded.last_modified_at,
                    is_new_admission=excluded.is_new_admission,
                    raw_json=excluded.raw_json,
                    synced_at=excluded.synced_at
                """,
                [
                    (
                        row["id"],
                        row["facility_id"],
                        row["patient_id"],
                        row.get("first_name"),
                        row.get("last_name"),
                        row.get("birth_date"),
                        row.get("gender"),
                        row.get("primary_payer_code"),
                        row.get("last_modified_at"),
                        int(bool(row.get("is_new_admission"))),
                        _json_text(row),
                        _now(),
                    )
                    for row in rows
                ],
            )

    def insert_diagnoses(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into diagnoses (
                    id, patient_id, icd10_code, icd10_description, clinical_status,
                    onset_date, last_modified_at, raw_json, synced_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    patient_id=excluded.patient_id,
                    icd10_code=excluded.icd10_code,
                    icd10_description=excluded.icd10_description,
                    clinical_status=excluded.clinical_status,
                    onset_date=excluded.onset_date,
                    last_modified_at=excluded.last_modified_at,
                    raw_json=excluded.raw_json,
                    synced_at=excluded.synced_at
                """,
                [
                    (
                        row.get("id"),
                        row.get("patient_id"),
                        row.get("icd10_code"),
                        row.get("icd10_description"),
                        row.get("clinical_status"),
                        row.get("onset_date"),
                        row.get("last_modified_at"),
                        _json_text(row),
                        _now(),
                    )
                    for row in rows
                ],
            )

    def insert_coverage_records(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into coverage_records (
                    id, patient_id, payer_name, payer_code, payer_type,
                    effective_from, effective_to, last_modified_at, raw_json, synced_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    patient_id=excluded.patient_id,
                    payer_name=excluded.payer_name,
                    payer_code=excluded.payer_code,
                    payer_type=excluded.payer_type,
                    effective_from=excluded.effective_from,
                    effective_to=excluded.effective_to,
                    last_modified_at=excluded.last_modified_at,
                    raw_json=excluded.raw_json,
                    synced_at=excluded.synced_at
                """,
                [
                    (
                        row.get("id"),
                        row.get("patient_id"),
                        row.get("payer_name"),
                        row.get("payer_code"),
                        row.get("payer_type"),
                        row.get("effective_from"),
                        row.get("effective_to"),
                        row.get("last_modified_at"),
                        _json_text(row),
                        _now(),
                    )
                    for row in rows
                ],
            )

    def insert_progress_notes(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into progress_notes (
                    id, patient_id, org_id, pcc_note_id, note_type, effective_date,
                    note_text, created_by, note_label, sync_version, is_current,
                    raw_json, synced_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    patient_id=excluded.patient_id,
                    org_id=excluded.org_id,
                    pcc_note_id=excluded.pcc_note_id,
                    note_type=excluded.note_type,
                    effective_date=excluded.effective_date,
                    note_text=excluded.note_text,
                    created_by=excluded.created_by,
                    note_label=excluded.note_label,
                    sync_version=excluded.sync_version,
                    is_current=excluded.is_current,
                    raw_json=excluded.raw_json,
                    synced_at=excluded.synced_at
                """,
                [
                    (
                        row.get("id"),
                        row.get("patient_id"),
                        row.get("org_id"),
                        row.get("pcc_note_id"),
                        row.get("note_type"),
                        row.get("effective_date"),
                        row.get("note_text"),
                        row.get("created_by"),
                        row.get("note_label"),
                        row.get("sync_version"),
                        int(bool(row.get("is_current"))),
                        _json_text(row),
                        _now(),
                    )
                    for row in rows
                ],
            )

    def insert_assessments(self, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into assessments (
                    id, patient_id, org_id, pcc_assessment_id, assessment_type, status,
                    assessment_date, completion_date, template_id,
                    assessment_type_description, raw_json, sync_version, is_current,
                    synced_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    patient_id=excluded.patient_id,
                    org_id=excluded.org_id,
                    pcc_assessment_id=excluded.pcc_assessment_id,
                    assessment_type=excluded.assessment_type,
                    status=excluded.status,
                    assessment_date=excluded.assessment_date,
                    completion_date=excluded.completion_date,
                    template_id=excluded.template_id,
                    assessment_type_description=excluded.assessment_type_description,
                    raw_json=excluded.raw_json,
                    sync_version=excluded.sync_version,
                    is_current=excluded.is_current,
                    synced_at=excluded.synced_at
                """,
                [
                    (
                        row.get("id"),
                        row.get("patient_id"),
                        row.get("org_id"),
                        row.get("pcc_assessment_id"),
                        row.get("assessment_type"),
                        row.get("status"),
                        row.get("assessment_date"),
                        row.get("completion_date"),
                        row.get("template_id"),
                        row.get("assessment_type_description"),
                        row.get("raw_json"),
                        row.get("sync_version"),
                        int(bool(row.get("is_current"))),
                        _now(),
                    )
                    for row in rows
                ],
            )

    def clear_wound_candidates(self) -> None:
        with self.connect() as connection:
            connection.execute("delete from field_conflicts")
            connection.execute("delete from field_evidence")
            connection.execute("delete from wound_candidates")

    def insert_wound_candidates(self, rows: Iterable[WoundCandidateRecord]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into wound_candidates (
                    candidate_key, patient_internal_id, patient_external_id, source_type,
                    source_record_id, source_date, wound_index, documentation_state,
                    wound_type, pressure_ulcer_stage, location, length_cm, width_cm,
                    depth_cm, drainage_amount, extraction_method, confidence,
                    source_excerpt, raw_source_text, raw_source_json, conflict_count,
                    synced_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(candidate_key) do update set
                    patient_internal_id=excluded.patient_internal_id,
                    patient_external_id=excluded.patient_external_id,
                    source_type=excluded.source_type,
                    source_record_id=excluded.source_record_id,
                    source_date=excluded.source_date,
                    wound_index=excluded.wound_index,
                    documentation_state=excluded.documentation_state,
                    wound_type=excluded.wound_type,
                    pressure_ulcer_stage=excluded.pressure_ulcer_stage,
                    location=excluded.location,
                    length_cm=excluded.length_cm,
                    width_cm=excluded.width_cm,
                    depth_cm=excluded.depth_cm,
                    drainage_amount=excluded.drainage_amount,
                    extraction_method=excluded.extraction_method,
                    confidence=excluded.confidence,
                    source_excerpt=excluded.source_excerpt,
                    raw_source_text=excluded.raw_source_text,
                    raw_source_json=excluded.raw_source_json,
                    conflict_count=excluded.conflict_count,
                    synced_at=excluded.synced_at
                """,
                [
                    (
                        row.candidate_key,
                        row.patient_internal_id,
                        row.patient_external_id,
                        row.source_type,
                        row.source_record_id,
                        row.source_date,
                        row.wound_index,
                        row.documentation_state,
                        row.wound_type,
                        row.pressure_ulcer_stage,
                        row.location,
                        row.length_cm,
                        row.width_cm,
                        row.depth_cm,
                        row.drainage_amount,
                        row.extraction_method,
                        row.confidence,
                        row.source_excerpt,
                        row.raw_source_text,
                        row.raw_source_json,
                        row.conflict_count,
                        _now(),
                    )
                    for row in rows
                ],
            )

    def insert_field_evidence(self, rows: Iterable[FieldEvidenceRecord]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into field_evidence (
                    candidate_key, field_name, candidate_value, normalized_value,
                    source_type, source_record_id, source_date, source_excerpt,
                    extraction_method, confidence
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.candidate_key,
                        row.field_name,
                        row.candidate_value,
                        row.normalized_value,
                        row.source_type,
                        row.source_record_id,
                        row.source_date,
                        row.source_excerpt,
                        row.extraction_method,
                        row.confidence,
                    )
                    for row in rows
                ],
            )

    def insert_field_conflicts(self, rows: Iterable[FieldConflictRecord]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into field_conflicts (
                    candidate_key, field_name, conflicting_values_json, source_type,
                    source_record_id, source_date, source_excerpt, extraction_method,
                    confidence
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.candidate_key,
                        row.field_name,
                        row.conflicting_values_json,
                        row.source_type,
                        row.source_record_id,
                        row.source_date,
                        row.source_excerpt,
                        row.extraction_method,
                        row.confidence,
                    )
                    for row in rows
                ],
            )

    def start_reconciliation_run(self, evaluation_date: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                insert into reconciliation_runs (
                    started_at, status, evaluation_date
                ) values (?, ?, ?)
                """,
                (_now(), "running", evaluation_date),
            )
            return int(cursor.lastrowid)

    def finish_reconciliation_run(
        self,
        run: ReconciliationRunRecord,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        statement = """
            update reconciliation_runs
            set finished_at = ?, status = ?, patients_evaluated = ?, wounds_reconciled = ?,
                historical_conflicts = ?, resolved_conflicts = ?, unresolved_conflicts = ?,
                auto_accept_count = ?, flag_for_review_count = ?, reject_count = ?,
                error_message = ?
            where id = ?
        """
        payload = (
            run.finished_at or _now(),
            run.status,
            run.patients_evaluated,
            run.wounds_reconciled,
            run.historical_conflicts,
            run.resolved_conflicts,
            run.unresolved_conflicts,
            run.auto_accept_count,
            run.flag_for_review_count,
            run.reject_count,
            run.error_message,
            run.id,
        )
        if connection is None:
            with self.connect() as connection:
                connection.execute(statement, payload)
            return
        connection.execute(statement, payload)

    def insert_wound_group_members(
        self,
        rows: Iterable[WoundGroupMemberRecord],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        statement = """
            insert into wound_group_members (
                reconciliation_run_id, wound_key, candidate_key, match_score,
                match_reason, synced_at
            ) values (?, ?, ?, ?, ?, ?)
            on conflict(wound_key, candidate_key) do update set
                reconciliation_run_id=excluded.reconciliation_run_id,
                match_score=excluded.match_score,
                match_reason=excluded.match_reason,
                synced_at=excluded.synced_at
        """
        payload = [
            (
                row.reconciliation_run_id,
                row.wound_key,
                row.candidate_key,
                row.match_score,
                row.match_reason,
                row.synced_at,
            )
            for row in rows
        ]
        if connection is None:
            with self.connect() as connection:
                connection.executemany(statement, payload)
            return
        connection.executemany(statement, payload)

    def upsert_reconciled_wounds(
        self,
        rows: Iterable[ReconciledWoundRecord],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        statement = """
            insert into reconciled_wounds (
                reconciliation_run_id, wound_key, patient_internal_id, patient_external_id,
                primary_candidate_key, primary_source_type, primary_source_record_id,
                primary_source_date, primary_source_excerpt, wound_type,
                pressure_ulcer_stage, location, length_cm, width_cm, depth_cm,
                drainage_amount, documentation_state, is_active_wound, is_primary_wound,
                confidence, selection_reason, selected_at, synced_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(wound_key) do update set
                reconciliation_run_id=excluded.reconciliation_run_id,
                patient_internal_id=excluded.patient_internal_id,
                patient_external_id=excluded.patient_external_id,
                primary_candidate_key=excluded.primary_candidate_key,
                primary_source_type=excluded.primary_source_type,
                primary_source_record_id=excluded.primary_source_record_id,
                primary_source_date=excluded.primary_source_date,
                primary_source_excerpt=excluded.primary_source_excerpt,
                wound_type=excluded.wound_type,
                pressure_ulcer_stage=excluded.pressure_ulcer_stage,
                location=excluded.location,
                length_cm=excluded.length_cm,
                width_cm=excluded.width_cm,
                depth_cm=excluded.depth_cm,
                drainage_amount=excluded.drainage_amount,
                documentation_state=excluded.documentation_state,
                is_active_wound=excluded.is_active_wound,
                is_primary_wound=excluded.is_primary_wound,
                confidence=excluded.confidence,
                selection_reason=excluded.selection_reason,
                selected_at=excluded.selected_at,
                synced_at=excluded.synced_at
        """
        payload = [
            (
                row.reconciliation_run_id,
                row.wound_key,
                row.patient_internal_id,
                row.patient_external_id,
                row.primary_candidate_key,
                row.primary_source_type,
                row.primary_source_record_id,
                row.primary_source_date,
                row.primary_source_excerpt,
                row.wound_type,
                row.pressure_ulcer_stage,
                row.location,
                row.length_cm,
                row.width_cm,
                row.depth_cm,
                row.drainage_amount,
                row.documentation_state,
                int(bool(row.is_active_wound)),
                int(bool(row.is_primary_wound)),
                row.confidence,
                row.selection_reason,
                row.selected_at,
                row.synced_at,
            )
            for row in rows
        ]
        if connection is None:
            with self.connect() as connection:
                connection.executemany(statement, payload)
            return
        connection.executemany(statement, payload)

    def upsert_selected_field_evidence(
        self,
        rows: Iterable[SelectedFieldEvidenceRecord],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        statement = """
            insert into selected_field_evidence (
                reconciliation_run_id, wound_key, candidate_key, field_name,
                selected_value, value_type, source_type, source_record_id,
                source_date, source_excerpt, extraction_method, confidence,
                selection_reason, alternative_values_json, conflict_status,
                precedence_rank, synced_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(wound_key, field_name) do update set
                reconciliation_run_id=excluded.reconciliation_run_id,
                candidate_key=excluded.candidate_key,
                selected_value=excluded.selected_value,
                value_type=excluded.value_type,
                source_type=excluded.source_type,
                source_record_id=excluded.source_record_id,
                source_date=excluded.source_date,
                source_excerpt=excluded.source_excerpt,
                extraction_method=excluded.extraction_method,
                confidence=excluded.confidence,
                selection_reason=excluded.selection_reason,
                alternative_values_json=excluded.alternative_values_json,
                conflict_status=excluded.conflict_status,
                precedence_rank=excluded.precedence_rank,
                synced_at=excluded.synced_at
        """
        payload = [
            (
                row.reconciliation_run_id,
                row.wound_key,
                row.candidate_key,
                row.field_name,
                row.selected_value,
                row.value_type,
                row.source_type,
                row.source_record_id,
                row.source_date,
                row.source_excerpt,
                row.extraction_method,
                row.confidence,
                row.selection_reason,
                row.alternative_values_json,
                row.conflict_status,
                row.precedence_rank,
                row.synced_at,
            )
            for row in rows
        ]
        if connection is None:
            with self.connect() as connection:
                connection.executemany(statement, payload)
            return
        connection.executemany(statement, payload)

    def upsert_reconciliation_conflicts(
        self,
        rows: Iterable[ReconciliationConflictRecord],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        statement = """
            insert into reconciliation_conflicts (
                reconciliation_run_id, patient_internal_id, patient_external_id,
                wound_key, field_name, conflict_type, conflict_state,
                selected_value, alternative_values_json, threshold_json,
                source_records_json, source_dates_json, source_excerpts_json,
                explanation, synced_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(wound_key, field_name, conflict_type) do update set
                reconciliation_run_id=excluded.reconciliation_run_id,
                patient_internal_id=excluded.patient_internal_id,
                patient_external_id=excluded.patient_external_id,
                conflict_state=excluded.conflict_state,
                selected_value=excluded.selected_value,
                alternative_values_json=excluded.alternative_values_json,
                threshold_json=excluded.threshold_json,
                source_records_json=excluded.source_records_json,
                source_dates_json=excluded.source_dates_json,
                source_excerpts_json=excluded.source_excerpts_json,
                explanation=excluded.explanation,
                synced_at=excluded.synced_at
        """
        payload = [
            (
                row.reconciliation_run_id,
                row.patient_internal_id,
                row.patient_external_id,
                row.wound_key,
                row.field_name,
                row.conflict_type,
                row.conflict_state,
                row.selected_value,
                row.alternative_values_json,
                row.threshold_json,
                row.source_records_json,
                row.source_dates_json,
                row.source_excerpts_json,
                row.explanation,
                row.synced_at,
            )
            for row in rows
        ]
        if connection is None:
            with self.connect() as connection:
                connection.executemany(statement, payload)
            return
        connection.executemany(statement, payload)

    def upsert_patient_routing(
        self,
        rows: Iterable[RoutingDecision],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        statement = """
            insert into patient_routing (
                reconciliation_run_id, patient_internal_id, patient_external_id,
                evaluation_date, coverage_status, coverage_record_id,
                coverage_record_snapshot_json, active_part_b,
                qualifying_wound_present, primary_wound_key, route,
                explanation, missing_fields_json, conflicting_fields_json,
                recommended_next_action, readiness_score, readiness_breakdown_json,
                routing_reason_codes_json, selected_at, synced_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(patient_internal_id) do update set
                reconciliation_run_id=excluded.reconciliation_run_id,
                patient_external_id=excluded.patient_external_id,
                evaluation_date=excluded.evaluation_date,
                coverage_status=excluded.coverage_status,
                coverage_record_id=excluded.coverage_record_id,
                coverage_record_snapshot_json=excluded.coverage_record_snapshot_json,
                active_part_b=excluded.active_part_b,
                qualifying_wound_present=excluded.qualifying_wound_present,
                primary_wound_key=excluded.primary_wound_key,
                route=excluded.route,
                explanation=excluded.explanation,
                missing_fields_json=excluded.missing_fields_json,
                conflicting_fields_json=excluded.conflicting_fields_json,
                recommended_next_action=excluded.recommended_next_action,
                readiness_score=excluded.readiness_score,
                readiness_breakdown_json=excluded.readiness_breakdown_json,
                routing_reason_codes_json=excluded.routing_reason_codes_json,
                selected_at=excluded.selected_at,
                synced_at=excluded.synced_at
        """
        payload = [
            (
                row.reconciliation_run_id,
                row.patient_internal_id,
                row.patient_external_id,
                row.evaluation_date,
                row.coverage_status,
                row.coverage_record_id,
                row.coverage_record_snapshot_json,
                int(bool(row.active_part_b)),
                int(bool(row.qualifying_wound_present)),
                row.primary_wound_key,
                row.route,
                row.explanation,
                row.missing_fields_json,
                row.conflicting_fields_json,
                row.recommended_next_action,
                row.readiness_score,
                row.readiness_breakdown_json,
                row.routing_reason_codes_json,
                row.selected_at,
                row.synced_at,
            )
            for row in rows
        ]
        if connection is None:
            with self.connect() as connection:
                connection.executemany(statement, payload)
            return
        connection.executemany(statement, payload)

    def clear_reconciliation_current_state(
        self,
        *,
        connection: sqlite3.Connection,
        patient_internal_ids: Iterable[int],
        wound_keys: Iterable[str],
    ) -> None:
        patient_ids = sorted({int(patient_id) for patient_id in patient_internal_ids})
        wound_key_list = sorted({str(wound_key) for wound_key in wound_keys})
        if patient_ids:
            placeholders = ",".join("?" for _ in patient_ids)
            existing_wound_keys = {
                str(row[0])
                for row in connection.execute(
                    f"select wound_key from reconciled_wounds where patient_internal_id in ({placeholders})",
                    patient_ids,
                )
            }
            wound_key_list = sorted(existing_wound_keys | set(wound_key_list))
        if patient_ids:
            placeholders = ",".join("?" for _ in patient_ids)
            connection.execute(
                f"delete from reconciled_wounds where patient_internal_id in ({placeholders})",
                patient_ids,
            )
            connection.execute(
                f"delete from reconciliation_conflicts where patient_internal_id in ({placeholders})",
                patient_ids,
            )
            connection.execute(
                f"delete from patient_routing where patient_internal_id in ({placeholders})",
                patient_ids,
            )
        if wound_key_list:
            placeholders = ",".join("?" for _ in wound_key_list)
            connection.execute(
                f"delete from wound_group_members where wound_key in ({placeholders})",
                wound_key_list,
            )
            connection.execute(
                f"delete from selected_field_evidence where wound_key in ({placeholders})",
                wound_key_list,
            )

    def _migrate_reconciliation_current_state(self, connection: sqlite3.Connection) -> None:
        dedupe_statements = (
            (
                "reconciled_wounds",
                "wound_key",
                "reconciliation_run_id desc, selected_at desc, synced_at desc, rowid desc",
            ),
            (
                "selected_field_evidence",
                "wound_key, field_name",
                "reconciliation_run_id desc, synced_at desc, rowid desc",
            ),
            (
                "reconciliation_conflicts",
                "wound_key, field_name, conflict_type",
                "reconciliation_run_id desc, synced_at desc, rowid desc",
            ),
            (
                "patient_routing",
                "patient_internal_id",
                "reconciliation_run_id desc, selected_at desc, synced_at desc, rowid desc",
            ),
            (
                "wound_group_members",
                "wound_key, candidate_key",
                "reconciliation_run_id desc, synced_at desc, rowid desc",
            ),
        )
        for table_name, partition_by, order_by in dedupe_statements:
            connection.execute(
                f"""
                delete from {table_name}
                where rowid in (
                    select rowid from (
                        select
                            rowid,
                            row_number() over (
                                partition by {partition_by}
                                order by {order_by}
                            ) as rn
                        from {table_name}
                    )
                    where rn > 1
                )
                """
            )
        connection.execute(
            """
            create unique index if not exists idx_reconciled_wounds_current
            on reconciled_wounds (wound_key)
            """
        )
        connection.execute(
            """
            create unique index if not exists idx_selected_field_evidence_current
            on selected_field_evidence (wound_key, field_name)
            """
        )
        connection.execute(
            """
            create unique index if not exists idx_reconciliation_conflicts_current
            on reconciliation_conflicts (wound_key, field_name, conflict_type)
            """
        )
        connection.execute(
            """
            create unique index if not exists idx_patient_routing_current
            on patient_routing (patient_internal_id)
            """
        )
        connection.execute(
            """
            create unique index if not exists idx_wound_group_members_current
            on wound_group_members (wound_key, candidate_key)
            """
        )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        existing_columns = {
            row[1]
            for row in connection.execute(f"pragma table_info({table_name})")
        }
        if column_name not in existing_columns:
            connection.execute(f"alter table {table_name} add column {column_name} {column_type}")
