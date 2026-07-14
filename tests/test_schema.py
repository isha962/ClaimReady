from pathlib import Path
import sqlite3


def test_schema_creates_expected_tables(tmp_path: Path) -> None:
    from claimready.db import Database

    db_path = tmp_path / "claimready.sqlite3"
    database = Database(db_path)
    database.initialize()

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table' order by name"
            )
        }

    assert {
        "patients",
        "diagnoses",
        "coverage_records",
        "progress_notes",
        "assessments",
        "sync_runs",
        "api_request_log",
        "failed_requests",
    }.issubset(tables)
