from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


TABLE_CASES = [
    ("patients", "id"),
    ("diagnoses", "id"),
    ("coverage_records", "id"),
    ("progress_notes", "id"),
    ("assessments", "id"),
]


@pytest.mark.parametrize("table_name, id_column", TABLE_CASES)
def test_fixture_sync_is_idempotent_for_each_source_table(tmp_path: Path, table_name: str, id_column: str) -> None:
    from claimready import cli

    db_path = tmp_path / f"{table_name}.sqlite3"

    assert cli.main(["--database", str(db_path), "--use-fixtures"]) == 0
    first_counts = _table_snapshot(db_path, table_name, id_column)
    first_sync_runs = _sync_run_count(db_path)

    assert cli.main(["--database", str(db_path), "--use-fixtures"]) == 0
    second_counts = _table_snapshot(db_path, table_name, id_column)
    second_sync_runs = _sync_run_count(db_path)

    assert first_counts == second_counts
    assert second_sync_runs == first_sync_runs + 1


def test_fixture_sync_updates_existing_row_instead_of_inserting_duplicate(tmp_path: Path, monkeypatch) -> None:
    from claimready import cli
    from claimready import fixtures

    db_path = tmp_path / "claimready.sqlite3"

    assert cli.main(["--database", str(db_path), "--use-fixtures"]) == 0

    monkeypatch.setitem(
        fixtures._DIAGNOSES_BY_PATIENT,
        "FA-001",
        [
            {
                **fixtures._DIAGNOSES_BY_PATIENT["FA-001"][0],
                "clinical_status": "resolved",
                "last_modified_at": "2026-06-01T00:00:00",
            }
        ],
    )

    assert cli.main(["--database", str(db_path), "--use-fixtures"]) == 0

    with sqlite3.connect(db_path) as connection:
        row_count = connection.execute("select count(*) from diagnoses where id = 1").fetchone()[0]
        status = connection.execute("select clinical_status from diagnoses where id = 1").fetchone()[0]
        last_modified_at = connection.execute("select last_modified_at from diagnoses where id = 1").fetchone()[0]

    assert row_count == 1
    assert status == "resolved"
    assert last_modified_at == "2026-06-01T00:00:00"


def test_required_patient_fetch_failure_marks_run_failed(tmp_path: Path, monkeypatch) -> None:
    from claimready import cli
    from claimready.client import RequestFailure

    async def fake_sync(*args, **kwargs):
        raise RequestFailure(
            "GET /pcc/patients?facility_id=101 failed with HTTP 500",
            method="GET",
            url="/pcc/patients?facility_id=101",
            status_code=500,
            attempts=5,
        )

    monkeypatch.setattr(cli, "sync_all_facilities", fake_sync)

    db_path = tmp_path / "failed.sqlite3"
    exit_code = cli.main(["--database", str(db_path)])

    assert exit_code == 1


def _table_snapshot(db_path: Path, table_name: str, id_column: str) -> tuple[int, int]:
    with sqlite3.connect(db_path) as connection:
        row_count = connection.execute(f"select count(*) from {table_name}").fetchone()[0]
        distinct_ids = connection.execute(
            f"select count(distinct {id_column}) from {table_name}"
        ).fetchone()[0]
    return row_count, distinct_ids


def _sync_run_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("select count(*) from sync_runs").fetchone()[0]
