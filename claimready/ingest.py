from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from .client import PCCClient, RequestFailure
from .db import Database
from .models import RequestEvent, SyncResult, SyncWindow
from .progress import ProgressReporter


@dataclass(slots=True)
class _PatientSyncResult:
    patient_id: str
    internal_id: int
    failures: list[RequestFailure]


class _DatabaseEventSink:
    def __init__(
        self,
        database: Database,
        sync_run_id: int,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.database = database
        self.sync_run_id = sync_run_id
        self.progress = progress

    def __call__(self, event: RequestEvent) -> None:
        self.database.log_event(self.sync_run_id, event)
        if event.outcome == "failure":
            self.database.log_failed_request(self.sync_run_id, event)
        if self.progress is not None:
            self.progress(event)


async def sync_all_facilities(
    *,
    database: Database,
    client: PCCClient,
    facilities: list[int],
    since: SyncWindow | None = None,
    mode: str = "full",
    progress: ProgressReporter | None = None,
) -> SyncResult:
    database.initialize()
    sync_run_id = database.start_sync_run(mode=mode, facilities=facilities, since=since)
    client.set_event_sink(_DatabaseEventSink(database, sync_run_id, progress))

    fatal_failure: RequestFailure | None = None

    try:
        for facility_id in facilities:
            if progress is not None:
                progress.facility_start(facility_id)
            patient_params: dict[str, Any] = {"facility_id": facility_id}
            if since and since.patients_since:
                patient_params["since"] = since.patients_since
            endpoint = "/pcc/patients"
            if progress is not None:
                progress.endpoint_start(facility_id, endpoint)
            try:
                patients = await client.get_json(endpoint, params=patient_params)
            except RequestFailure as exc:
                fatal_failure = exc
                break
            database.upsert_patients(patients)
            if progress is not None:
                progress.endpoint_success(facility_id, endpoint, len(patients))

            patient_tasks = [
                _sync_patient(
                    client=client,
                    patient=row,
                    database=database,
                    facility_id=facility_id,
                    since=since,
                    progress=progress,
                )
                for row in patients
            ]
            patient_results = await asyncio.gather(*patient_tasks, return_exceptions=True)
            for result in patient_results:
                if isinstance(result, Exception):
                    raise result
            if progress is not None:
                progress.facility_complete(facility_id)
    finally:
        had_failure = fatal_failure is not None
        stats = client.stats
        result = SyncResult(
            sync_run_id=sync_run_id,
            facilities_synced=facilities,
            request_count=stats.request_count,
            retry_count=stats.retry_count,
            rate_limited_count=stats.rate_limited_count,
            failure_count=stats.failure_count,
            total_latency_ms=stats.total_latency_ms,
        )
        database.finish_sync_run(sync_run_id, result, status="failed" if had_failure else "completed")

    if fatal_failure is not None:
        raise fatal_failure

    return SyncResult(
        sync_run_id=sync_run_id,
        facilities_synced=facilities,
        request_count=client.stats.request_count,
        retry_count=client.stats.retry_count,
        rate_limited_count=client.stats.rate_limited_count,
        failure_count=client.stats.failure_count,
        total_latency_ms=client.stats.total_latency_ms,
    )


async def _sync_patient(
    *,
    client: PCCClient,
    patient: dict[str, Any],
    database: Database,
    facility_id: int,
    since: SyncWindow | None,
    progress: ProgressReporter | None,
) -> _PatientSyncResult:
    internal_id = int(patient["id"])
    patient_id = str(patient["patient_id"])
    failures: list[RequestFailure] = []

    tasks = [
        _fetch_and_store(
            client=client,
            database=database,
            path="/pcc/diagnoses",
            params={"patient_id": patient_id},
            store=database.insert_diagnoses,
            patient_id=patient_id,
            facility_id=facility_id,
            progress=progress,
        ),
        _fetch_and_store(
            client=client,
            database=database,
            path="/pcc/coverage",
            params={"patient_id": patient_id},
            store=database.insert_coverage_records,
            patient_id=patient_id,
            facility_id=facility_id,
            progress=progress,
        ),
        _fetch_and_store(
            client=client,
            database=database,
            path="/pcc/notes",
            params=_patient_internal_params(internal_id, since.notes_since if since else None),
            store=database.insert_progress_notes,
            patient_id=patient_id,
            facility_id=facility_id,
            progress=progress,
        ),
        _fetch_and_store(
            client=client,
            database=database,
            path="/pcc/assessments",
            params=_patient_internal_params(internal_id, since.assessments_since if since else None),
            store=database.insert_assessments,
            patient_id=patient_id,
            facility_id=facility_id,
            progress=progress,
        ),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, RequestFailure):
            failures.append(result)
        elif isinstance(result, Exception):
            raise result

    return _PatientSyncResult(patient_id=patient_id, internal_id=internal_id, failures=failures)


async def _fetch_and_store(
    *,
    client: PCCClient,
    database: Database,
    path: str,
    params: dict[str, Any],
    store,
    patient_id: str,
    facility_id: int,
    progress: ProgressReporter | None,
) -> RequestFailure | None:
    if progress is not None:
        progress.endpoint_start(facility_id, path)
    try:
        payload = await client.get_json(path, params=params)
    except RequestFailure as exc:
        return exc

    if not isinstance(payload, list):
        raise ValueError(f"expected list payload from {path}")
    store(payload)
    if progress is not None:
        progress.endpoint_success(facility_id, path, len(payload))
    return None


def _patient_internal_params(patient_id: int, since: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"patient_id": patient_id}
    if since:
        params["since"] = since
    return params
