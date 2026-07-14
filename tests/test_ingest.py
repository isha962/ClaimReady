import asyncio
import sqlite3

import httpx
import pytest


def test_sync_all_facilities_persists_rows_and_failed_requests(tmp_path) -> None:
    from claimready.client import PCCClient
    from claimready.db import Database
    from claimready.ingest import sync_all_facilities
    from claimready.client import RequestFailure

    def payload(request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path
        params = dict(url.params)

        if path == "/pcc/patients":
            return httpx.Response(
                200,
                json=[
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
                ],
            )
        if path == "/pcc/diagnoses":
            return httpx.Response(200, json=[{"id": 1, "patient_id": "FA-001", "clinical_status": "active"}])
        if path == "/pcc/coverage":
            return httpx.Response(200, json=[{"id": 1, "patient_id": "FA-001", "payer_code": "MCB"}])
        if path == "/pcc/notes":
            return httpx.Response(500, json={"detail": "notes unavailable"})
        if path == "/pcc/assessments":
            return httpx.Response(200, json=[{"id": 1, "patient_id": 1, "raw_json": "{}"}])
        raise AssertionError(f"unexpected path: {path} {params}")

    async def sleep(seconds: float) -> None:
        return None

    db_path = tmp_path / "claimready.sqlite3"
    database = Database(db_path)
    database.initialize()

    client = PCCClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(payload),
        sleep_fn=sleep,
        jitter_fn=lambda *_: 0.0,
        max_retries=1,
    )

    result = asyncio.run(sync_all_facilities(database=database, client=client, facilities=[101]))

    with sqlite3.connect(db_path) as connection:
        patient_count = connection.execute("select count(*) from patients").fetchone()[0]
        diagnosis_count = connection.execute("select count(*) from diagnoses").fetchone()[0]
        coverage_count = connection.execute("select count(*) from coverage_records").fetchone()[0]
        note_count = connection.execute("select count(*) from progress_notes").fetchone()[0]
        assessment_count = connection.execute("select count(*) from assessments").fetchone()[0]
        failed_count = connection.execute("select count(*) from failed_requests").fetchone()[0]
        sync_runs = connection.execute("select count(*) from sync_runs").fetchone()[0]
        api_requests = connection.execute("select count(*) from api_request_log").fetchone()[0]

    assert patient_count == 1
    assert diagnosis_count == 1
    assert coverage_count == 1
    assert note_count == 0
    assert assessment_count == 1
    assert failed_count == 1
    assert sync_runs == 1
    assert api_requests >= 5
    assert result.failure_count == 1


def test_sync_marks_run_failed_when_required_facility_fails(tmp_path) -> None:
    from claimready.client import PCCClient
    from claimready.client import RequestFailure
    from claimready.db import Database
    from claimready.ingest import sync_all_facilities

    def payload(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pcc/patients":
            return httpx.Response(500, json={"detail": "temporary failure"})
        raise AssertionError(f"unexpected path: {request.url.path}")

    async def sleep(seconds: float) -> None:
        return None

    db_path = tmp_path / "claimready.sqlite3"
    database = Database(db_path)
    database.initialize()

    client = PCCClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(payload),
        sleep_fn=sleep,
        jitter_fn=lambda *_: 0.0,
        max_retries=1,
    )

    with pytest.raises(RequestFailure):
        asyncio.run(sync_all_facilities(database=database, client=client, facilities=[101]))

    with sqlite3.connect(db_path) as connection:
        status = connection.execute("select status from sync_runs order by id desc limit 1").fetchone()[0]

    assert status == "failed"


def test_optional_endpoint_failure_keeps_run_completed(tmp_path) -> None:
    from claimready.client import PCCClient
    from claimready.db import Database
    from claimready.ingest import sync_all_facilities

    def payload(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/pcc/patients":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "facility_id": 101,
                        "patient_id": "FA-001",
                        "first_name": "Agnes",
                        "last_name": "Dunbar",
                        "primary_payer_code": "MCB",
                        "is_new_admission": True,
                    }
                ],
            )
        if path == "/pcc/notes":
            return httpx.Response(500, json={"detail": "notes unavailable"})
        return httpx.Response(200, json=[{"id": 1, "patient_id": "FA-001"}])

    async def sleep(seconds: float) -> None:
        return None

    db_path = tmp_path / "claimready.sqlite3"
    database = Database(db_path)
    database.initialize()

    client = PCCClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(payload),
        sleep_fn=sleep,
        jitter_fn=lambda *_: 0.0,
        max_retries=1,
    )

    result = asyncio.run(sync_all_facilities(database=database, client=client, facilities=[101]))

    assert result.failure_count == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select status, failure_count from sync_runs order by id desc limit 1"
        ).fetchone()

    assert row[0] == "completed"
    assert row[1] == 1
