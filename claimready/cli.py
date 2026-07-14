from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from datetime import date, datetime, timezone

import httpx

from .client import PCCClient, RequestFailure
from .config import Settings
from .db import Database
from .fixtures import FIXTURE_NOTICE, build_fixture_transport
from .extract import extract_wound_candidates
from .reconcile import format_patient_trace, reconcile_database
from .ingest import sync_all_facilities
from .progress import ProgressReporter


API_CHECK_URLS = [
    "https://hackathon.prod.pulsefoundry.ai/",
    "https://hackathon.prod.pulsefoundry.ai/health/",
    "https://hackathon.prod.pulsefoundry.ai/pcc/patients?facility_id=101",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimready")
    parser.add_argument("--database", default=None)
    parser.add_argument("--facility", action="append", type=int, dest="facilities")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--use-fixtures", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("check-api", help="Probe the live API without syncing data")
    subparsers.add_parser("extract", help="Extract wound candidates from source data")
    reconcile_parser = subparsers.add_parser("reconcile", help="Reconcile wound candidates into routing decisions")
    reconcile_parser.add_argument("--patient", default=None)
    reconcile_parser.add_argument("--evaluation-date", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-api":
        return asyncio.run(_run_api_check(debug=args.debug))
    if args.command == "extract":
        return _run_extract(args)
    if args.command == "reconcile":
        return _run_reconcile(args)

    return _run_sync(args)


def _run_sync(args: argparse.Namespace) -> int:
    facilities = args.facilities or [101, 102, 103]
    database_path = args.database or os.environ.get("CLAIMREADY_DB_PATH") or "claimready.sqlite3"
    settings = Settings(database_path=database_path)
    database = Database(settings.database_path)
    progress = ProgressReporter(stream=sys.stdout)

    async def run() -> None:
        progress.write(FIXTURE_NOTICE if args.use_fixtures else "Connecting to live PCC API")
        transport = build_fixture_transport() if args.use_fixtures else None
        async with PCCClient(
            base_url=settings.base_url,
            max_retries=settings.max_retries,
            concurrency_limit=settings.max_concurrency,
            transport=transport,
        ) as client:
            await sync_all_facilities(
                database=database,
                client=client,
                facilities=facilities,
                progress=progress,
            )

    try:
        asyncio.run(run())
        return 0
    except RequestFailure as exc:
        return _handle_sync_failure(exc, debug=args.debug)
    except Exception as exc:  # pragma: no cover - safety net for unexpected errors
        return _handle_unexpected_failure(exc, debug=args.debug)


def _handle_sync_failure(exc: RequestFailure, *, debug: bool) -> int:
    if debug:
        traceback.print_exception(exc, file=sys.stderr)
        raise SystemExit(1)

    print("Live PCC sync failed after retries.")
    print(f"Endpoint: {exc.url}")
    if exc.status_code is None:
        print("Last status: network failure")
    else:
        print(f"Last status: HTTP {exc.status_code}")
    print("The remote API appears unavailable. No successful sync was recorded.")
    return 1


def _handle_unexpected_failure(exc: Exception, *, debug: bool) -> int:
    if debug:
        traceback.print_exception(exc, file=sys.stderr)
        raise SystemExit(1)
    print(f"ClaimReady failed: {exc}")
    return 1


def _run_extract(args: argparse.Namespace) -> int:
    database_path = args.database or os.environ.get("CLAIMREADY_DB_PATH") or "claimready.sqlite3"
    settings = Settings(database_path=database_path)
    database = Database(settings.database_path)

    if args.use_fixtures:
        sync_exit = _run_sync(args)
        if sync_exit != 0:
            return sync_exit

    result = extract_wound_candidates(database)
    print(f"Wound candidates: {result.candidate_count}")
    print(f"Field evidence: {result.evidence_count}")
    print(f"Field conflicts: {result.conflict_count}")
    print(f"Assessments parsed: {result.source_counts.get('assessment', 0)}")
    print(f"Progress notes parsed: {result.source_counts.get('progress_note', 0)}")
    return 0


def _run_reconcile(args: argparse.Namespace) -> int:
    database_path = args.database or os.environ.get("CLAIMREADY_DB_PATH") or "claimready.sqlite3"
    settings = Settings(database_path=database_path)
    database = Database(settings.database_path)

    if args.use_fixtures:
        sync_exit = _run_sync(args)
        if sync_exit != 0:
            return sync_exit
        extract_result = extract_wound_candidates(database)
        if extract_result.candidate_count == 0:
            print("No wound candidates were extracted from fixture data.")
            return 1

    evaluation_date = _parse_evaluation_date(args.evaluation_date)
    result = reconcile_database(
        database,
        evaluation_date=evaluation_date,
        patient_external_id=args.patient,
    )

    print(f"Patients evaluated: {result.patients_evaluated}")
    print(f"Wounds reconciled: {result.wounds_reconciled}")
    print(f"Resolved conflicts: {result.resolved_conflicts}")
    print(f"Unresolved conflicts: {result.unresolved_conflicts}")
    print(f"Auto accept: {result.auto_accept_count}")
    print(f"Review: {result.flag_for_review_count}")
    print(f"Reject: {result.reject_count}")

    if args.patient:
        decision = result.decisions_by_patient.get(args.patient)
        if decision is None:
            print(f"Patient {args.patient} was not found in the reconciliation results.")
            return 1
        wounds = [wound for wound in result.wounds_by_key.values() if wound.patient_external_id == args.patient]
        with database.connect() as connection:
            conflicts = [
                _row_to_conflict(dict(row))
                for row in connection.execute(
                    """
                    select *
                    from reconciliation_conflicts
                    where reconciliation_run_id = ?
                      and patient_external_id = ?
                    order by wound_key, field_name
                    """,
                    (result.reconciliation_run_id, args.patient),
                )
            ]
        for line in format_patient_trace(decision, wounds, conflicts):
            print(line)

    return 0


async def _run_api_check(*, debug: bool) -> int:
    progress = ProgressReporter(stream=sys.stdout)
    any_unhealthy = False

    for url in API_CHECK_URLS:
        try:
            classification, status_code = await _probe_url(url)
        except Exception as exc:  # pragma: no cover - defensive
            if debug:
                traceback.print_exception(exc, file=sys.stderr)
                raise SystemExit(1)
            classification = "network failure"
            status_code = None
        progress.api_check_result(url, classification, status_code)
        if classification in {"rate limited", "server error", "network failure"}:
            any_unhealthy = True

    return 1 if any_unhealthy else 0


async def _probe_url(url: str) -> tuple[str, int | None]:
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        try:
            response = await client.get(url)
        except httpx.RequestError:
            return ("network failure", None)

    status = response.status_code
    if 200 <= status < 300:
        return ("reachable", status)
    if 300 <= status < 400:
        return ("redirected", status)
    if status == 429:
        return ("rate limited", status)
    if status >= 500:
        return ("server error", status)
    return ("reachable", status)


def _parse_evaluation_date(value: str | None):
    if not value:
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(value)


def _row_to_conflict(row: dict[str, object]):
    from .models import ReconciliationConflictRecord

    return ReconciliationConflictRecord(
        reconciliation_run_id=int(row["reconciliation_run_id"]),
        patient_internal_id=int(row["patient_internal_id"]),
        patient_external_id=row["patient_external_id"],
        wound_key=str(row["wound_key"]),
        field_name=str(row["field_name"]),
        conflict_type=str(row["conflict_type"]),
        conflict_state=str(row["conflict_state"]),
        selected_value=row["selected_value"],
        alternative_values_json=str(row["alternative_values_json"]),
        threshold_json=str(row["threshold_json"]),
        source_records_json=str(row["source_records_json"]),
        source_dates_json=str(row["source_dates_json"]),
        source_excerpts_json=str(row["source_excerpts_json"]),
        explanation=str(row["explanation"]),
        synced_at=str(row["synced_at"]),
    )
