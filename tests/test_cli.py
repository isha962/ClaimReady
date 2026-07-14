from __future__ import annotations

import contextlib
import io
import sqlite3

import pytest


def test_cli_reports_clean_failure_for_live_sync(monkeypatch, tmp_path) -> None:
    from claimready import cli
    from claimready.client import RequestFailure

    async def fake_run(*args, **kwargs):
        raise RequestFailure(
            "GET /pcc/patients?facility_id=101 failed with HTTP 500",
            method="GET",
            url="/pcc/patients?facility_id=101",
            status_code=500,
            attempts=5,
        )

    monkeypatch.setattr(cli, "sync_all_facilities", fake_run)

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = cli.main(["--database", str(tmp_path / "claimready.sqlite3")])

    assert exit_code == 1
    assert "Live PCC sync failed after retries." in stdout.getvalue()
    assert "Endpoint: /pcc/patients?facility_id=101" in stdout.getvalue()
    assert "Last status: HTTP 500" in stdout.getvalue()
    assert "The remote API appears unavailable. No successful sync was recorded." in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_cli_debug_mode_prints_traceback(monkeypatch, tmp_path, capsys) -> None:
    from claimready import cli
    from claimready.client import RequestFailure

    async def fake_run(*args, **kwargs):
        raise RequestFailure(
            "GET /pcc/patients?facility_id=101 failed with HTTP 500",
            method="GET",
            url="/pcc/patients?facility_id=101",
            status_code=500,
            attempts=5,
        )

    monkeypatch.setattr(cli, "sync_all_facilities", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--database", str(tmp_path / "claimready.sqlite3"), "--debug"])

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Traceback (most recent call last)" in captured.err


def test_fixture_mode_loads_synthetic_data(tmp_path) -> None:
    from claimready import cli

    db_path = tmp_path / "claimready.sqlite3"
    exit_code = cli.main(["--database", str(db_path), "--use-fixtures"])

    assert exit_code == 0

    with sqlite3.connect(db_path) as connection:
        patients = connection.execute("select count(*) from patients").fetchone()[0]
        notes = connection.execute("select count(*) from progress_notes").fetchone()[0]
        assessments = connection.execute("select count(*) from assessments").fetchone()[0]
        payer_codes = {
            row[0]
            for row in connection.execute("select distinct payer_code from coverage_records")
        }
        note_texts = [row[0] for row in connection.execute("select note_text from progress_notes")]
        raw_json_rows = [row[0] for row in connection.execute("select raw_json from assessments")]

    assert patients > 0
    assert notes > 0
    assert assessments > 0
    assert "MCB" in payer_codes
    assert any("Pressure Ulcer" in text for text in note_texts)
    assert any("Meas" in text for text in note_texts)
    assert any("Envive" in text or "resident" in text.lower() for text in note_texts)
    assert any("\"stage\"" in raw_json for raw_json in raw_json_rows)
    assert any("\"wound_type\"" in raw_json for raw_json in raw_json_rows)


def test_fixture_mode_uses_claimready_db_path_env(monkeypatch, tmp_path) -> None:
    from claimready import cli

    db_path = tmp_path / "env.sqlite3"
    monkeypatch.setenv("CLAIMREADY_DB_PATH", str(db_path))

    exit_code = cli.main(["--use-fixtures"])

    assert exit_code == 0
    assert db_path.exists()


def test_check_api_command_reports_statuses(capsys) -> None:
    from claimready import cli

    async def fake_probe(url: str):
        if url == "https://hackathon.prod.pulsefoundry.ai/":
            return ("reachable", 200)
        if url == "https://hackathon.prod.pulsefoundry.ai/health/":
            return ("redirected", 301)
        return ("server error", 500)

    cli._probe_url = fake_probe  # type: ignore[attr-defined]

    exit_code = cli.main(["check-api"])

    assert exit_code in (0, 1)
    captured = capsys.readouterr()
    assert "hackathon.prod.pulsefoundry.ai" in captured.out
    assert "reachable" in captured.out
    assert "redirected" in captured.out
    assert "server error" in captured.out
