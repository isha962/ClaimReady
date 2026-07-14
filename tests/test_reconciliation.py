from __future__ import annotations

import contextlib
import io
import json
import sqlite3
from datetime import date

import pytest

from claimready.models import CoverageRecord, WoundCandidateRecord


CURRENT_STATE_TABLES = (
    "reconciled_wounds",
    "selected_field_evidence",
    "reconciliation_conflicts",
    "patient_routing",
    "wound_group_members",
)


def test_reconciliation_tables_exist(tmp_path) -> None:
    from claimready.db import Database

    database = Database(tmp_path / "claimready.sqlite3")
    database.initialize()

    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type = 'table'")
        }

    assert {
        "reconciliation_runs",
        "reconciled_wounds",
        "selected_field_evidence",
        "reconciliation_conflicts",
        "patient_routing",
        "wound_group_members",
    } <= tables


def test_reconciliation_prefers_structured_assessment_for_shared_fields(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:1:1",
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
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
        _candidate(
            candidate_key="progress_note:1:1",
            source_type="progress_note",
            source_record_id="1",
            source_date="2026-05-11T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="2",
            location="Sacrum",
            length_cm=3.1,
            width_cm=2.0,
            depth_cm=0.3,
            drainage_amount="light",
            extraction_method="narrative_note",
            source_excerpt="Sacral wound with stage II documentation and lighter drainage.",
            raw_source_text="Sacral wound with stage II documentation and lighter drainage.",
            confidence=0.70,
        ),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        row = connection.execute(
            """
            select wound_type, pressure_ulcer_stage, location, length_cm, width_cm, depth_cm, drainage_amount
            from reconciled_wounds
            where reconciliation_run_id = ?
            order by wound_key
            limit 1
            """,
            (result.reconciliation_run_id,),
        ).fetchone()

    assert row["pressure_ulcer_stage"] == "3"
    assert row["location"] == "Sacrum"
    assert row["drainage_amount"] == "moderate"


def test_lower_precedence_source_fills_missing_field(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:2:1",
            source_type="assessment",
            source_record_id="2",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="2",
            location="Sacrum",
            length_cm=4.2,
            width_cm=3.1,
            depth_cm=None,
            drainage_amount="light",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":2,"location":"Sacrum","length_cm":4.2,"width_cm":3.1,"depth_cm":null,"drainage_amount":"light"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":2,"location":"Sacrum","length_cm":4.2,"width_cm":3.1,"depth_cm":null,"drainage_amount":"light"}',
            confidence=0.95,
        ),
        _candidate(
            candidate_key="progress_note:2:1",
            source_type="progress_note",
            source_record_id="2",
            source_date="2026-05-12T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="2",
            location="Sacrum",
            length_cm=4.2,
            width_cm=3.1,
            depth_cm=1.5,
            drainage_amount="light",
            extraction_method="narrative_note",
            source_excerpt="Sacral wound, Meas 4.2x3.1x1.5cm, scant drainage, stage II pressure ulcer improving.",
            raw_source_text="Sacral wound, Meas 4.2x3.1x1.5cm, scant drainage, stage II pressure ulcer improving.",
            confidence=0.75,
        ),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        row = connection.execute(
            """
            select depth_cm
            from reconciled_wounds
            where reconciliation_run_id = ?
            order by wound_key
            limit 1
            """,
            (result.reconciliation_run_id,),
        ).fetchone()
        evidence_row = connection.execute(
            """
            select value_type
            from selected_field_evidence
            where reconciliation_run_id = ?
              and field_name = 'depth_cm'
            limit 1
            """,
            (result.reconciliation_run_id,),
        ).fetchone()

    assert row["depth_cm"] == 1.5
    assert evidence_row["value_type"] == "numeric"


def test_recency_breaks_ties_within_same_precedence(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="progress_note:3:1",
            source_type="progress_note",
            source_record_id="3",
            source_date="2026-05-10T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="2",
            location="Sacrum",
            length_cm=3.0,
            width_cm=2.0,
            depth_cm=0.4,
            drainage_amount="moderate",
            extraction_method="narrative_note",
            source_excerpt="Sacral pressure ulcer stage II with moderate drainage.",
            raw_source_text="Sacral pressure ulcer stage II with moderate drainage.",
            confidence=0.70,
        ),
        _candidate(
            candidate_key="progress_note:4:1",
            source_type="progress_note",
            source_record_id="4",
            source_date="2026-05-12T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.0,
            width_cm=2.0,
            depth_cm=0.4,
            drainage_amount="moderate",
            extraction_method="narrative_note",
            source_excerpt="Sacral pressure ulcer stage III with moderate drainage.",
            raw_source_text="Sacral pressure ulcer stage III with moderate drainage.",
            confidence=0.70,
        ),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        stage = connection.execute(
            """
            select pressure_ulcer_stage
            from reconciled_wounds
            where reconciliation_run_id = ?
            order by wound_key
            limit 1
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]

    assert stage == "3"


@pytest.mark.parametrize(
    "delta_cm, expected_status",
    [
        (0.09, "historical"),
        (0.10, "historical"),
        (0.11, "unresolved_material"),
    ],
)
def test_numeric_measurement_tolerance_preserves_alternatives(tmp_path, delta_cm, expected_status) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:5:1",
            source_type="assessment",
            source_record_id="5",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="2",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":2,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":2,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
        _candidate(
            candidate_key="progress_note:5:1",
            source_type="progress_note",
            source_record_id="5",
            source_date="2026-05-11T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="2",
            location="Sacrum",
            length_cm=3.2 + delta_cm,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            extraction_method="narrative_note",
            source_excerpt=f"Sacral wound measured {3.2 + delta_cm:.2f} x 2.1 x 0.4 cm.",
            raw_source_text=f"Sacral wound measured {3.2 + delta_cm:.2f} x 2.1 x 0.4 cm.",
            confidence=0.70,
        ),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        conflict = connection.execute(
            """
            select conflict_state, alternative_values_json, threshold_json
            from reconciliation_conflicts
            where reconciliation_run_id = ?
              and field_name = 'length_cm'
            order by wound_key
            limit 1
            """,
            (result.reconciliation_run_id,),
        ).fetchone()

    assert conflict["conflict_state"] == expected_status
    assert json.loads(conflict["threshold_json"]) == {"numeric_tolerance_cm": 0.1}
    assert len(json.loads(conflict["alternative_values_json"])) == 2


def test_stage_conflict_persists_conflict_record(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:6:1",
            source_type="assessment",
            source_record_id="6",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="2",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":2,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":2,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
        _candidate(
            candidate_key="progress_note:6:1",
            source_type="progress_note",
            source_record_id="6",
            source_date="2026-05-11T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            extraction_method="narrative_note",
            source_excerpt="Sacral pressure ulcer stage III with identical measurements.",
            raw_source_text="Sacral pressure ulcer stage III with identical measurements.",
            confidence=0.70,
        ),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        conflict_row = connection.execute(
            """
            select conflict_type, conflict_state, selected_value
            from reconciliation_conflicts
            where reconciliation_run_id = ?
              and field_name = 'pressure_ulcer_stage'
            limit 1
            """,
            (result.reconciliation_run_id,),
        ).fetchone()

    assert conflict_row["conflict_type"] == "stage_disagreement"
    assert conflict_row["conflict_state"] in {"resolved", "unresolved_material"}
    assert conflict_row["selected_value"] == "2"


def test_healed_vs_active_conflict_is_visible(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:7:1",
            source_type="assessment",
            source_record_id="7",
            source_date="2026-05-09",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=2.8,
            width_cm=1.5,
            depth_cm=0.6,
            drainage_amount="moderate",
            documentation_state="healed",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":2.8,"width_cm":1.5,"depth_cm":0.6,"drainage_amount":"moderate","documentation_state":"healed"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":2.8,"width_cm":1.5,"depth_cm":0.6,"drainage_amount":"moderate","documentation_state":"healed"}',
            confidence=0.85,
        ),
        _candidate(
            candidate_key="progress_note:7:1",
            source_type="progress_note",
            source_record_id="7",
            source_date="2026-05-11T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=2.8,
            width_cm=1.5,
            depth_cm=0.6,
            drainage_amount="moderate",
            documentation_state="active",
            extraction_method="narrative_note",
            source_excerpt="Active sacral pressure ulcer stage III with moderate drainage.",
            raw_source_text="Active sacral pressure ulcer stage III with moderate drainage.",
            confidence=0.70,
        ),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        row = connection.execute(
            """
            select count(*) from reconciliation_conflicts
            where reconciliation_run_id = ?
              and field_name = 'documentation_state'
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]

    assert row >= 1


def test_multiple_coverage_records_select_active_part_b(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:17:1",
            source_type="assessment",
            source_record_id="17",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=10, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2019-01-01T00:00:00", effective_to="2020-01-01T00:00:00"),
        _coverage_record(id=11, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.auto_accept_count == 1
    with database.connect() as connection:
        row = connection.execute(
            """
            select coverage_record_id, coverage_record_snapshot_json
            from patient_routing
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()
    assert row["coverage_record_id"] == 11
    assert json.loads(row["coverage_record_snapshot_json"])["effective_to"] is None


def test_expired_part_b_rejects_patient(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:18:1",
            source_type="assessment",
            source_record_id="18",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=12, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2019-01-01T00:00:00", effective_to="2020-01-01T00:00:00"),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.reject_count == 1
    with database.connect() as connection:
        route = connection.execute(
            """
            select route
            from patient_routing
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]
    assert route == "reject"


def test_active_part_b_auto_accepts_complete_wound(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:8:1",
            source_type="assessment",
            source_record_id="8",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=1, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.auto_accept_count == 1
    with database.connect() as connection:
        route = connection.execute(
            """
            select route
            from patient_routing
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]
    assert route == "auto_accept"


def test_no_part_b_rejects_patient(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:9:1",
            source_type="assessment",
            source_record_id="9",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=2, patient_id="FA-001", payer_code="HMO", payer_type="HMO", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.reject_count == 1
    with database.connect() as connection:
        route = connection.execute(
            """
            select route
            from patient_routing
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]
    assert route == "reject"


def test_missing_depth_flags_for_review(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:10:1",
            source_type="assessment",
            source_record_id="10",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=None,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":null,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":null,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=3, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.flag_for_review_count == 1
    with database.connect() as connection:
        missing_fields = json.loads(
            connection.execute(
                """
                select missing_fields_json
                from patient_routing
                where reconciliation_run_id = ?
                """,
                (result.reconciliation_run_id,),
            ).fetchone()[0]
        )
    assert "depth_cm" in missing_fields


def test_pressure_ulcer_missing_stage_flags_for_review(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:11:1",
            source_type="assessment",
            source_record_id="11",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage=None,
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=4, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.flag_for_review_count == 1
    with database.connect() as connection:
        row = connection.execute(
            """
            select route, missing_fields_json
            from patient_routing
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()
    assert row["route"] == "flag_for_review"
    assert "pressure_ulcer_stage" in json.loads(row["missing_fields_json"])


def test_non_pressure_wound_without_stage_can_auto_accept(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:12:1",
            source_type="assessment",
            source_record_id="12",
            source_date="2026-05-10",
            wound_type="diabetic_foot_ulcer",
            pressure_ulcer_stage=None,
            location="Right Heel",
            length_cm=2.0,
            width_cm=1.4,
            depth_cm=0.3,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"diabetic_foot_ulcer","location":"Right Heel","length_cm":2.0,"width_cm":1.4,"depth_cm":0.3,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"diabetic_foot_ulcer","location":"Right Heel","length_cm":2.0,"width_cm":1.4,"depth_cm":0.3,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=5, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.auto_accept_count == 1


def test_ambiguous_primary_wound_routes_for_review(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="progress_note:13:1",
            source_type="progress_note",
            source_record_id="13",
            source_date="2026-05-10T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.0,
            width_cm=2.0,
            depth_cm=0.4,
            drainage_amount="moderate",
            extraction_method="narrative_note",
            source_excerpt="Sacral pressure ulcer stage III with moderate drainage.",
            raw_source_text="Sacral pressure ulcer stage III with moderate drainage.",
            confidence=0.70,
        ),
        _candidate(
            candidate_key="progress_note:13:2",
            source_type="progress_note",
            source_record_id="14",
            source_date="2026-05-10T09:00:00",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Right Heel",
            length_cm=3.0,
            width_cm=2.0,
            depth_cm=0.4,
            drainage_amount="moderate",
            extraction_method="narrative_note",
            source_excerpt="Right heel pressure ulcer stage III with moderate drainage.",
            raw_source_text="Right heel pressure ulcer stage III with moderate drainage.",
            confidence=0.70,
        ),
    ], coverage=[
        _coverage_record(id=6, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    assert result.flag_for_review_count == 1
    with database.connect() as connection:
        primary_wound_key = connection.execute(
            """
            select primary_wound_key
            from patient_routing
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]
        member_count = connection.execute(
            """
            select count(*)
            from wound_group_members
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]
    assert primary_wound_key is None
    assert member_count == 2


def test_reconciliation_explanation_is_deterministic(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:14:1",
            source_type="assessment",
            source_record_id="14",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=7, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    result = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        explanation = connection.execute(
            """
            select explanation
            from patient_routing
            where reconciliation_run_id = ?
            """,
            (result.reconciliation_run_id,),
        ).fetchone()[0]

    assert "Active Medicare Part B" in explanation
    assert "Stage 3" in explanation
    assert "No unresolved documentation conflicts" in explanation


def test_reconciliation_rerun_does_not_duplicate_within_run(tmp_path) -> None:
    from claimready.db import Database
    from claimready.reconcile import reconcile_database

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:15:1",
            source_type="assessment",
            source_record_id="15",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=8, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    first = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))
    with database.connect() as connection:
        first_counts = {
            table_name: connection.execute(f"select count(*) from {table_name}").fetchone()[0]
            for table_name in CURRENT_STATE_TABLES
        }
        first_snapshot = {
            table_name: _table_snapshot(connection, table_name)
            for table_name in CURRENT_STATE_TABLES
        }

    second = reconcile_database(database, evaluation_date=date.fromisoformat("2026-07-13"))

    with database.connect() as connection:
        second_counts = {
            table_name: connection.execute(f"select count(*) from {table_name}").fetchone()[0]
            for table_name in CURRENT_STATE_TABLES
        }
        second_snapshot = {
            table_name: _table_snapshot(connection, table_name)
            for table_name in CURRENT_STATE_TABLES
        }
        current_run_id = connection.execute(
            "select reconciliation_run_id from reconciled_wounds where wound_key = 'patient:1:wound:1'"
        ).fetchone()[0]
        run_rows = connection.execute("select count(*) from reconciliation_runs").fetchone()[0]

    assert first_counts == second_counts
    assert first_snapshot == second_snapshot
    assert current_run_id == second.reconciliation_run_id
    assert run_rows == 2


def test_reconcile_cli_patient_trace(tmp_path, capsys) -> None:
    from claimready.db import Database
    from claimready import cli

    database = _seed_database(tmp_path, candidates=[
        _candidate(
            candidate_key="assessment:16:1",
            source_type="assessment",
            source_record_id="16",
            source_date="2026-05-10",
            wound_type="pressure_ulcer",
            pressure_ulcer_stage="3",
            location="Sacrum",
            length_cm=3.2,
            width_cm=2.1,
            depth_cm=0.4,
            drainage_amount="moderate",
            source_excerpt='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            raw_source_json='{"wound_type":"pressure_ulcer","stage":3,"location":"Sacrum","length_cm":3.2,"width_cm":2.1,"depth_cm":0.4,"drainage_amount":"moderate"}',
            confidence=0.95,
        ),
    ], coverage=[
        _coverage_record(id=9, patient_id="FA-001", payer_code="MCB", payer_type="Medicare B", effective_from="2020-01-01T00:00:00", effective_to=None),
    ])

    exit_code = cli.main(["--database", str(database.path), "reconcile", "--patient", "FA-001"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Decision trace for FA-001" in captured.out
    assert "Recommended next action" in captured.out


def _seed_database(tmp_path, *, candidates: list[WoundCandidateRecord], coverage: list[dict[str, object]] | None = None) -> Database:
    from claimready.db import Database

    db_path = tmp_path / "claimready.sqlite3"
    database = Database(db_path)
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
        coverage
        or [
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
    database.insert_wound_candidates(candidates)
    return database


def _candidate(
    *,
    candidate_key: str,
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
        patient_internal_id=1,
        patient_external_id="FA-001",
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


def _coverage_record(
    *,
    id: int,
    patient_id: str,
    payer_code: str,
    payer_type: str,
    effective_from: str,
    effective_to: str | None,
) -> dict[str, object]:
    return {
        "id": id,
        "patient_id": patient_id,
        "payer_name": "Medicare Part B" if payer_code == "MCB" else "Commercial HMO",
        "payer_code": payer_code,
        "payer_type": payer_type,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "last_modified_at": "2026-05-17T19:13:00",
    }


def _table_snapshot(connection: sqlite3.Connection, table_name: str) -> list[str]:
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
    rows = []
    for row in connection.execute(f"select * from {table_name} order by {ordering[table_name]}"):
        payload = dict(row)
        for column in exclusions[table_name]:
            payload.pop(column, None)
        rows.append(json.dumps(payload, sort_keys=True))
    return rows
