from __future__ import annotations

import sqlite3


def test_parse_structured_assessment_raw_json() -> None:
    from claimready.extract import parse_assessment_record

    record = {
        "id": 1,
        "patient_id": 1,
        "org_id": "ORG-101",
        "pcc_assessment_id": 20001,
        "assessment_type": "Weekly Wound Information Sheet",
        "status": "Complete",
        "assessment_date": "2026-05-10",
        "completion_date": "2026-05-10",
        "template_id": 5,
        "assessment_type_description": "Quarterly",
        "raw_json": "{\"wound_type\": \"pressure_ulcer\", \"stage\": 2, \"location\": \"Sacrum\", \"length_cm\": 3.2, \"width_cm\": 2.1, \"depth_cm\": 0.4, \"drainage_type\": \"serosanguineous\", \"drainage_amount\": \"moderate\"}",
        "sync_version": 1,
        "is_current": True,
    }

    candidate = parse_assessment_record(record, patient_external_id="FA-001")

    assert candidate.wound_type == "pressure_ulcer"
    assert candidate.pressure_ulcer_stage == "2"
    assert candidate.location == "Sacrum"
    assert candidate.length_cm == 3.2
    assert candidate.width_cm == 2.1
    assert candidate.depth_cm == 0.4
    assert candidate.drainage_amount == "moderate"


def test_parse_labeled_note_extracts_all_fields() -> None:
    from claimready.extract import parse_progress_note_record

    record = {
        "id": 1,
        "patient_id": 1,
        "org_id": "ORG-101",
        "pcc_note_id": 10001,
        "note_type": "Wound (SPN)",
        "effective_date": "2026-05-10T09:00:00",
        "note_text": "Wound Assessment Note\nLocation: Sacrum\nWound Type: Pressure Ulcer, Stage 2\nLength: 3.2 cm  Width: 2.1 cm  Depth: 0.4 cm\nDrainage: Moderate serosanguineous",
        "created_by": "RN Smith",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    candidates = parse_progress_note_record(record, patient_external_id="FA-001")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.wound_type == "pressure_ulcer"
    assert candidate.pressure_ulcer_stage == "2"
    assert candidate.location == "Sacrum"
    assert candidate.length_cm == 3.2
    assert candidate.width_cm == 2.1
    assert candidate.depth_cm == 0.4
    assert candidate.drainage_amount == "moderate"


def test_parse_abbreviated_prose_measurements_and_roman_stage() -> None:
    from claimready.extract import parse_progress_note_record

    record = {
        "id": 2,
        "patient_id": 2,
        "org_id": "ORG-101",
        "pcc_note_id": 10002,
        "note_type": "Wound (SPN)",
        "effective_date": "2026-05-11T09:00:00",
        "note_text": "Sacral wound, Meas 4.2x3.1x1.5cm, scant drainage, stage II pressure ulcer improving.",
        "created_by": "LPN Jones",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    candidates = parse_progress_note_record(record, patient_external_id="FA-002")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.pressure_ulcer_stage == "2"
    assert candidate.length_cm == 4.2
    assert candidate.width_cm == 3.1
    assert candidate.depth_cm == 1.5
    assert candidate.drainage_amount == "light"


def test_parse_unknown_drainage_normalizes_to_unknown() -> None:
    from claimready.extract import parse_progress_note_record

    record = {
        "id": 9,
        "patient_id": 9,
        "org_id": "ORG-105",
        "pcc_note_id": 10009,
        "note_type": "Wound (SPN)",
        "effective_date": "2026-05-17T09:00:00",
        "note_text": "Pressure ulcer at sacrum, drainage indeterminate, measurements not recorded.",
        "created_by": "RN Stone",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    candidate = parse_progress_note_record(record, patient_external_id="FD-001")[0]

    assert candidate.drainage_amount == "unknown"


def test_parse_multiple_wounds_and_conflict_detection() -> None:
    from claimready.extract import parse_progress_note_record

    record = {
        "id": 4,
        "patient_id": 4,
        "org_id": "ORG-102",
        "pcc_note_id": 10004,
        "note_type": "Wound (SPN)",
        "effective_date": "2026-05-13T09:00:00",
        "note_text": "Multi-wound note: wound one left heel 1.0 x 0.5 x 0.2 cm moderate drainage; wound two coccyx 2.5 x 1.2 x 0.4 cm heavy drainage.",
        "created_by": "RN Lee",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    candidates = parse_progress_note_record(record, patient_external_id="FB-002")

    assert len(candidates) == 2
    assert {candidate.location for candidate in candidates} == {"Left Heel", "Coccyx"}


def test_parse_envive_narrative_finds_explicit_anatomical_location() -> None:
    from claimready.extract import parse_progress_note_record

    record = {
        "id": 10,
        "patient_id": 10,
        "org_id": "ORG-106",
        "pcc_note_id": 10010,
        "note_type": "Envive Narrative",
        "effective_date": "2026-05-18T09:00:00",
        "note_text": "Envive narrative synthetic development data: resident with diabetic foot ulcer to right heel, drainage moderate, wound measures 2.0 x 1.4 x 0.3 cm, surrounding tissue intact.",
        "created_by": "RN Rivera",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    candidate = parse_progress_note_record(record, patient_external_id="FD-002")[0]

    assert candidate.location == "Right Heel"
    assert candidate.wound_type == "diabetic_foot_ulcer"


def test_parse_negated_and_missing_fields_remain_null() -> None:
    from claimready.extract import parse_progress_note_record

    negated_record = {
        "id": 5,
        "patient_id": 5,
        "org_id": "ORG-103",
        "pcc_note_id": 10005,
        "note_type": "Wound (SPN)",
        "effective_date": "2026-05-14T09:00:00",
        "note_text": "No wound present today. Measurements not recorded.",
        "created_by": "RN Smith",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    candidates = parse_progress_note_record(negated_record, patient_external_id="FC-001")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.documentation_state == "negated"
    assert candidate.wound_type is None
    assert candidate.length_cm is None
    assert candidate.width_cm is None
    assert candidate.depth_cm is None


def test_parse_unstageable_and_healed_note_types() -> None:
    from claimready.extract import parse_progress_note_record

    unstageable_record = {
        "id": 7,
        "patient_id": 7,
        "org_id": "ORG-104",
        "pcc_note_id": 10007,
        "note_type": "Wound (SPN)",
        "effective_date": "2026-05-15T09:00:00",
        "note_text": "Sacral pressure ulcer, unstageable, 2.0 x 1.0 x 0.4 cm, light drainage.",
        "created_by": "RN Smith",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }
    healed_record = {
        "id": 8,
        "patient_id": 8,
        "org_id": "ORG-104",
        "pcc_note_id": 10008,
        "note_type": "Wound (SPN)",
        "effective_date": "2026-05-16T09:00:00",
        "note_text": "Resolved pressure ulcer, healed and closed, previously stage III at sacrum.",
        "created_by": "RN Smith",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    unstageable = parse_progress_note_record(unstageable_record, patient_external_id="FX-001")[0]
    healed = parse_progress_note_record(healed_record, patient_external_id="FX-002")[0]

    assert unstageable.pressure_ulcer_stage == "unstageable"
    assert healed.documentation_state == "healed"
    assert healed.pressure_ulcer_stage == "3"


def test_parse_conflicting_note_leaves_stage_null_and_records_conflict() -> None:
    from claimready.extract import parse_progress_note_record

    record = {
        "id": 6,
        "patient_id": 6,
        "org_id": "ORG-103",
        "pcc_note_id": 10006,
        "note_type": "Envive Narrative",
        "effective_date": "2026-05-15T09:00:00",
        "note_text": "Envive narrative synthetic development data with conflicting values: note describes stage 2 sacral pressure ulcer measuring 2.2 x 1.1 x 0.3 cm with light drainage, while another section says stage 3.",
        "created_by": "RN Smith",
        "note_label": None,
        "sync_version": 1,
        "is_current": True,
    }

    candidate = parse_progress_note_record(record, patient_external_id="FC-002")[0]

    assert candidate.pressure_ulcer_stage is None
    assert candidate.conflict_count >= 1
    assert candidate.field_conflicts


def test_fixture_extraction_persists_candidates_and_evidence(tmp_path) -> None:
    from claimready import cli
    from claimready.db import Database
    from claimready.extract import extract_wound_candidates

    db_path = tmp_path / "claimready.sqlite3"
    assert cli.main(["--database", str(db_path), "--use-fixtures"]) == 0

    database = Database(db_path)
    result = extract_wound_candidates(database)

    assert result.candidate_count > 0
    assert result.evidence_count >= result.candidate_count

    with sqlite3.connect(db_path) as connection:
        candidate_count = connection.execute("select count(*) from wound_candidates").fetchone()[0]
        evidence_count = connection.execute("select count(*) from field_evidence").fetchone()[0]
        conflict_count = connection.execute("select count(*) from field_conflicts").fetchone()[0]

    assert candidate_count == result.candidate_count
    assert evidence_count == result.evidence_count
    assert conflict_count >= 1


def test_extract_cli_reports_candidate_counts(tmp_path, capsys) -> None:
    from claimready import cli

    db_path = tmp_path / "claimready.sqlite3"
    assert cli.main(["--database", str(db_path), "--use-fixtures"]) == 0

    exit_code = cli.main(["--database", str(db_path), "extract"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Wound candidates:" in captured.out
    assert "Field evidence:" in captured.out
