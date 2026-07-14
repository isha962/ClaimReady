from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from claimready.models import WoundCandidateRecord


CURRENT_STATE_TABLES = (
    "reconciled_wounds",
    "selected_field_evidence",
    "reconciliation_conflicts",
    "patient_routing",
    "wound_group_members",
)


def test_full_pipeline_reconciliation_stays_idempotent(tmp_path) -> None:
    from claimready import cli

    db_path = tmp_path / "claimready.sqlite3"

    assert cli.main(["--database", str(db_path), "--use-fixtures", "extract"]) == 0
    assert cli.main(["--database", str(db_path), "reconcile"]) == 0
    first_snapshot = _current_state_snapshot(db_path)
    first_counts = _current_state_counts(db_path)

    assert cli.main(["--database", str(db_path), "reconcile"]) == 0
    second_snapshot = _current_state_snapshot(db_path)
    second_counts = _current_state_counts(db_path)

    assert first_counts == second_counts
    assert first_snapshot == second_snapshot
    for table_name, count in second_counts.items():
        assert count == _distinct_key_count(db_path, table_name)


def test_single_patient_reconciliation_is_idempotent_and_isolated(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_two_patient_database(tmp_path)

    first = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))
    with database.connect() as connection:
        fb_snapshot_before = _patient_snapshot(connection, "FB-001")

    database.insert_wound_candidates(
        [
            _candidate(
                candidate_key="assessment:fa:1",
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
                source_excerpt="Updated sacral assessment.",
                raw_source_json='{"wound_type":"pressure_ulcer"}',
                confidence=0.95,
            )
        ]
    )

    second = reconcile_database(
        database,
        evaluation_date=date.fromisoformat("2026-07-13"),
        patient_external_id="FA-001",
    )

    with database.connect() as connection:
        fb_snapshot_after = _patient_snapshot(connection, "FB-001")
        fa_rows = connection.execute(
            "select count(*) from patient_routing where patient_external_id = ?",
            ("FA-001",),
        ).fetchone()[0]
        fb_rows = connection.execute(
            "select count(*) from patient_routing where patient_external_id = ?",
            ("FB-001",),
        ).fetchone()[0]

    assert first.patients_evaluated == 2
    assert second.patients_evaluated == 1
    assert fb_snapshot_before == fb_snapshot_after
    assert fa_rows == 1
    assert fb_rows == 1


def test_resolved_conflicts_and_missing_fields_are_removed_on_rerun(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = Database(tmp_path / "claimready.sqlite3")
    database.initialize()
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
            }
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
            }
        ]
    )
    database.insert_wound_candidates(
        [
            _candidate(
                candidate_key="assessment:1",
                patient_internal_id=1,
                patient_external_id="FA-001",
                source_type="assessment",
                source_record_id="1",
                source_date="2026-05-10",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="2",
                location="Sacrum",
                length_cm=3.2,
                width_cm=2.1,
                depth_cm=0.4,
                drainage_amount="moderate",
                source_excerpt="Stage 2 sacral assessment.",
                raw_source_json='{"stage":2}',
            ),
            _candidate(
                candidate_key="progress_note:1",
                patient_internal_id=1,
                patient_external_id="FA-001",
                source_type="progress_note",
                source_record_id="2",
                source_date="2026-05-11T09:00:00",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="3",
                location="Sacrum",
                length_cm=3.2,
                width_cm=2.1,
                depth_cm=0.4,
                drainage_amount="moderate",
                source_excerpt="Stage 3 sacral note.",
                raw_source_text="Stage 3 sacral note.",
                extraction_method="narrative_note",
                confidence=0.7,
            ),
        ]
    )

    first = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        first_depth_rows = connection.execute(
            """
            select count(*)
            from selected_field_evidence
            where wound_key = ? and field_name = 'depth_cm'
            """,
            ("patient:1:wound:1",),
        ).fetchone()[0]
        first_conflicts = connection.execute(
            """
            select count(*)
            from reconciliation_conflicts
            where wound_key = ? and field_name = 'pressure_ulcer_stage'
            """,
            ("patient:1:wound:1",),
        ).fetchone()[0]

    database.insert_wound_candidates(
        [
            _candidate(
                candidate_key="assessment:1",
                patient_internal_id=1,
                patient_external_id="FA-001",
                source_type="assessment",
                source_record_id="1",
                source_date="2026-05-10",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="2",
                location="Sacrum",
                length_cm=3.2,
                width_cm=2.1,
                depth_cm=None,
                drainage_amount="moderate",
                source_excerpt="Stage 2 sacral assessment without depth.",
                raw_source_json='{"stage":2,"depth":null}',
            ),
            _candidate(
                candidate_key="progress_note:1",
                patient_internal_id=1,
                patient_external_id="FA-001",
                source_type="progress_note",
                source_record_id="2",
                source_date="2026-05-11T09:00:00",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="2",
                location="Sacrum",
                length_cm=3.2,
                width_cm=2.1,
                depth_cm=None,
                drainage_amount="moderate",
                source_excerpt="Stage 2 sacral note without depth.",
                raw_source_text="Stage 2 sacral note without depth.",
                extraction_method="narrative_note",
                confidence=0.7,
            ),
        ]
    )

    second = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        second_depth_rows = connection.execute(
            """
            select count(*)
            from selected_field_evidence
            where wound_key = ? and field_name = 'depth_cm'
            """,
            ("patient:1:wound:1",),
        ).fetchone()[0]
        second_conflicts = connection.execute(
            """
            select count(*)
            from reconciliation_conflicts
            where wound_key = ? and field_name = 'pressure_ulcer_stage'
            """,
            ("patient:1:wound:1",),
        ).fetchone()[0]

    assert first_depth_rows == 1
    assert first_conflicts >= 1
    assert second_depth_rows == 0
    assert second_conflicts == 0
    assert first.reconciliation_run_id != second.reconciliation_run_id


def test_failed_reconciliation_rolls_back_current_state(tmp_path, monkeypatch) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_two_patient_database(tmp_path)
    successful = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))
    baseline_counts = _current_state_counts(database.path)

    def fail_on_routing(*args, **kwargs):
        raise RuntimeError("synthetic reconciliation failure")

    monkeypatch.setattr(Database, "upsert_patient_routing", fail_on_routing)

    with pytest.raises(RuntimeError):
        reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        failed_run = connection.execute(
            "select status, error_message from reconciliation_runs order by id desc limit 1"
        ).fetchone()

    assert failed_run["status"] == "failed"
    assert "synthetic reconciliation failure" in failed_run["error_message"]
    assert baseline_counts == _current_state_counts(database.path)


def _seed_two_patient_database(tmp_path):
    from claimready.db import Database

    database = Database(tmp_path / "claimready.sqlite3")
    database.initialize()
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
                "first_name": "Mona",
                "last_name": "Irwin",
                "birth_date": "1943-09-08",
                "gender": "Female",
                "primary_payer_code": "MCB",
                "last_modified_at": "2026-05-17T19:13:00",
                "is_new_admission": True,
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
        ]
    )
    database.insert_wound_candidates(
        [
            _candidate(
                candidate_key="assessment:fa:1",
                patient_internal_id=1,
                patient_external_id="FA-001",
                source_type="assessment",
                source_record_id="1",
                source_date="2026-05-10",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="3",
                location="Sacrum",
                length_cm=3.2,
                width_cm=2.1,
                depth_cm=0.4,
                drainage_amount="moderate",
                source_excerpt="FA wound",
                raw_source_json='{"patient":"FA-001"}',
            ),
            _candidate(
                candidate_key="assessment:fb:1",
                patient_internal_id=2,
                patient_external_id="FB-001",
                source_type="assessment",
                source_record_id="2",
                source_date="2026-05-10",
                wound_type="pressure_ulcer",
                pressure_ulcer_stage="2",
                location="Right Heel",
                length_cm=2.8,
                width_cm=1.5,
                depth_cm=0.3,
                drainage_amount="light",
                source_excerpt="FB wound",
                raw_source_json='{"patient":"FB-001"}',
            ),
        ]
    )
    return database


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


def _current_state_counts(db_path) -> dict[str, int]:
    with sqlite3.connect(db_path) as connection:
        return {
            table_name: connection.execute(f"select count(*) from {table_name}").fetchone()[0]
            for table_name in CURRENT_STATE_TABLES
        }


def _distinct_key_count(db_path, table_name: str) -> int:
    queries = {
        "reconciled_wounds": "select count(distinct wound_key) from reconciled_wounds",
        "selected_field_evidence": "select count(distinct wound_key || '|' || field_name) from selected_field_evidence",
        "reconciliation_conflicts": "select count(distinct wound_key || '|' || field_name || '|' || conflict_type) from reconciliation_conflicts",
        "patient_routing": "select count(distinct patient_internal_id) from patient_routing",
        "wound_group_members": "select count(distinct wound_key || '|' || candidate_key) from wound_group_members",
    }
    with sqlite3.connect(db_path) as connection:
        return connection.execute(queries[table_name]).fetchone()[0]


def _current_state_snapshot(db_path) -> dict[str, list[str]]:
    exclusions = {
        "reconciled_wounds": {"reconciliation_run_id", "selected_at", "synced_at"},
        "selected_field_evidence": {"reconciliation_run_id", "synced_at"},
        "reconciliation_conflicts": {"reconciliation_run_id", "synced_at"},
        "patient_routing": {"reconciliation_run_id", "selected_at", "synced_at"},
        "wound_group_members": {"reconciliation_run_id", "synced_at"},
    }
    ordering = {
        "reconciled_wounds": "wound_key",
        "selected_field_evidence": "wound_key, field_name",
        "reconciliation_conflicts": "wound_key, field_name, conflict_type",
        "patient_routing": "patient_internal_id",
        "wound_group_members": "wound_key, candidate_key",
    }
    snapshots: dict[str, list[str]] = {}
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        for table_name in CURRENT_STATE_TABLES:
            rows = []
            for row in connection.execute(f"select * from {table_name} order by {ordering[table_name]}"):
                payload = dict(row)
                for column in exclusions[table_name]:
                    payload.pop(column, None)
                rows.append(json.dumps(payload, sort_keys=True))
            snapshots[table_name] = rows
    return snapshots


def _patient_snapshot(connection: sqlite3.Connection, patient_id: str) -> list[str]:
    rows = []
    for row in connection.execute(
        """
        select patient_external_id, route, explanation, primary_wound_key, recommended_next_action
        from patient_routing
        where patient_external_id = ?
        order by patient_internal_id
        """,
        (patient_id,),
    ):
        rows.append(json.dumps(dict(row), sort_keys=True))
    return rows
