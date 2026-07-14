from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx


FIXTURE_NOTICE = "Synthetic development data from ClaimReady fixtures"


_PATIENTS_BY_FACILITY: dict[int, list[dict[str, Any]]] = {
    101: [
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
            "patient_id": "FA-002",
            "first_name": "Leon",
            "last_name": "Dawson",
            "birth_date": "1943-02-25",
            "gender": "Male",
            "primary_payer_code": "HMO",
            "last_modified_at": "2026-05-15T12:24:00",
            "is_new_admission": False,
        },
    ],
    102: [
        {
            "id": 3,
            "facility_id": 102,
            "patient_id": "FB-001",
            "first_name": "Nora",
            "last_name": "Patel",
            "birth_date": "1945-02-13",
            "gender": "Female",
            "primary_payer_code": "MCB",
            "last_modified_at": "2026-05-14T10:00:00",
            "is_new_admission": False,
        },
        {
            "id": 4,
            "facility_id": 102,
            "patient_id": "FB-002",
            "first_name": "Luis",
            "last_name": "Gomez",
            "birth_date": "1939-09-29",
            "gender": "Male",
            "primary_payer_code": "MCA",
            "last_modified_at": "2026-05-13T09:00:00",
            "is_new_admission": False,
        },
    ],
    103: [
        {
            "id": 5,
            "facility_id": 103,
            "patient_id": "FC-001",
            "first_name": "Imani",
            "last_name": "Cole",
            "birth_date": "1941-08-11",
            "gender": "Female",
            "primary_payer_code": "MCB",
            "last_modified_at": "2026-05-18T15:00:00",
            "is_new_admission": True,
        },
        {
            "id": 6,
            "facility_id": 103,
            "patient_id": "FC-002",
            "first_name": "Ruth",
            "last_name": "Bell",
            "birth_date": "1944-01-20",
            "gender": "Female",
            "primary_payer_code": "HMO",
            "last_modified_at": "2026-05-16T08:30:00",
            "is_new_admission": False,
        },
    ],
}

_DIAGNOSES_BY_PATIENT: dict[str, list[dict[str, Any]]] = {
    "FA-001": [
        {
            "id": 1,
            "patient_id": "FA-001",
            "icd10_code": "L89.152",
            "icd10_description": "Pressure ulcer of sacral region, stage 2",
            "clinical_status": "active",
            "onset_date": "2026-04-10",
            "last_modified_at": "2026-05-17T19:13:00",
        }
    ],
    "FA-002": [
        {
            "id": 2,
            "patient_id": "FA-002",
            "icd10_code": "I87.2",
            "icd10_description": "Venous insufficiency",
            "clinical_status": "active",
            "onset_date": "2026-03-10",
            "last_modified_at": "2026-05-15T12:24:00",
        }
    ],
    "FB-001": [
        {
            "id": 3,
            "patient_id": "FB-001",
            "icd10_code": "E11.621",
            "icd10_description": "Type 2 diabetes mellitus with foot ulcer",
            "clinical_status": "active",
            "onset_date": "2026-04-12",
            "last_modified_at": "2026-05-14T10:00:00",
        }
    ],
    "FB-002": [
        {
            "id": 4,
            "patient_id": "FB-002",
            "icd10_code": "L97.429",
            "icd10_description": "Non-pressure chronic ulcer of left heel and midfoot",
            "clinical_status": "active",
            "onset_date": "2026-04-18",
            "last_modified_at": "2026-05-13T09:00:00",
        }
    ],
    "FC-001": [
        {
            "id": 5,
            "patient_id": "FC-001",
            "icd10_code": "L89.154",
            "icd10_description": "Pressure ulcer of sacral region, stage 4",
            "clinical_status": "active",
            "onset_date": "2026-04-22",
            "last_modified_at": "2026-05-18T15:00:00",
        }
    ],
    "FC-002": [
        {
            "id": 6,
            "patient_id": "FC-002",
            "icd10_code": "T81.89XA",
            "icd10_description": "Other complications of surgical and medical care",
            "clinical_status": "active",
            "onset_date": "2026-04-28",
            "last_modified_at": "2026-05-16T08:30:00",
        }
    ],
}

_COVERAGE_BY_PATIENT: dict[str, list[dict[str, Any]]] = {
    "FA-001": [
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
    ],
    "FA-002": [
        {
            "id": 2,
            "patient_id": "FA-002",
            "payer_name": "Commercial HMO",
            "payer_code": "HMO",
            "payer_type": "HMO",
            "effective_from": "2023-01-01T00:00:00",
            "effective_to": None,
            "last_modified_at": "2026-05-15T12:24:00",
        }
    ],
    "FB-001": [
        {
            "id": 3,
            "patient_id": "FB-001",
            "payer_name": "Medicare Part B",
            "payer_code": "MCB",
            "payer_type": "Medicare B",
            "effective_from": "2021-01-01T00:00:00",
            "effective_to": None,
            "last_modified_at": "2026-05-14T10:00:00",
        }
    ],
    "FB-002": [
        {
            "id": 4,
            "patient_id": "FB-002",
            "payer_name": "Medicare Part A",
            "payer_code": "MCA",
            "payer_type": "Medicare A",
            "effective_from": "2026-01-01T00:00:00",
            "effective_to": None,
            "last_modified_at": "2026-05-13T09:00:00",
        }
    ],
    "FC-001": [
        {
            "id": 5,
            "patient_id": "FC-001",
            "payer_name": "Medicare Part B",
            "payer_code": "MCB",
            "payer_type": "Medicare B",
            "effective_from": "2020-01-01T00:00:00",
            "effective_to": None,
            "last_modified_at": "2026-05-18T15:00:00",
        }
    ],
    "FC-002": [
        {
            "id": 6,
            "patient_id": "FC-002",
            "payer_name": "Managed Care",
            "payer_code": "HMO",
            "payer_type": "HMO",
            "effective_from": "2022-01-01T00:00:00",
            "effective_to": None,
            "last_modified_at": "2026-05-16T08:30:00",
        }
    ],
}

_NOTES_BY_PATIENT_ID: dict[int, list[dict[str, Any]]] = {
    1: [
        {
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
    ],
    2: [
        {
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
    ],
    3: [
        {
            "id": 3,
            "patient_id": 3,
            "org_id": "ORG-102",
            "pcc_note_id": 10003,
            "note_type": "Envive Narrative",
            "effective_date": "2026-05-12T09:00:00",
            "note_text": "Envive narrative synthetic development data: resident with diabetic foot ulcer to right heel, drainage moderate, wound measures 2.0 x 1.4 x 0.3 cm, surrounding tissue intact.",
            "created_by": "RN Lee",
            "note_label": None,
            "sync_version": 1,
            "is_current": True,
        }
    ],
    4: [
        {
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
    ],
    5: [
        {
            "id": 5,
            "patient_id": 5,
            "org_id": "ORG-103",
            "pcc_note_id": 10005,
            "note_type": "Wound (SPN)",
            "effective_date": "2026-05-14T09:00:00",
            "note_text": "Pressure injury documented at sacrum, drainage unknown, measurements not recorded in this note.",
            "created_by": "RN Smith",
            "note_label": None,
            "sync_version": 1,
            "is_current": True,
        }
    ],
    6: [
        {
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
    ],
}

_ASSESSMENTS_BY_PATIENT_ID: dict[int, list[dict[str, Any]]] = {
    1: [
        {
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
    ],
    2: [
        {
            "id": 2,
            "patient_id": 2,
            "org_id": "ORG-101",
            "pcc_assessment_id": 20002,
            "assessment_type": "Weekly Wound Information Sheet",
            "status": "Complete",
            "assessment_date": "2026-05-11",
            "completion_date": "2026-05-11",
            "template_id": 5,
            "assessment_type_description": "Quarterly",
            "raw_json": "{\"wound_type\": \"pressure_ulcer\", \"stage\": 2, \"location\": \"Sacrum\", \"length_cm\": 4.2, \"width_cm\": 3.1, \"depth_cm\": null, \"drainage_amount\": \"light\"}",
            "sync_version": 1,
            "is_current": True,
        }
    ],
    3: [
        {
            "id": 3,
            "patient_id": 3,
            "org_id": "ORG-102",
            "pcc_assessment_id": 20003,
            "assessment_type": "HP Skin & Wound",
            "status": "Complete",
            "assessment_date": "2026-05-12",
            "completion_date": "2026-05-12",
            "template_id": 6,
            "assessment_type_description": "Admissions",
            "raw_json": "{\"wound_type\": \"diabetic_foot_ulcer\", \"location\": \"Right Heel\", \"length_cm\": 2.0, \"width_cm\": 1.4, \"depth_cm\": 0.3, \"drainage_amount\": \"moderate\"}",
            "sync_version": 1,
            "is_current": True,
        }
    ],
    4: [
        {
            "id": 4,
            "patient_id": 4,
            "org_id": "ORG-102",
            "pcc_assessment_id": 20004,
            "assessment_type": "HP Skin & Wound",
            "status": "Complete",
            "assessment_date": "2026-05-13",
            "completion_date": "2026-05-13",
            "template_id": 6,
            "assessment_type_description": "Admissions",
            "raw_json": "{\"wound_type\": \"venous_stasis_ulcer\", \"location\": \"Left Heel\", \"length_cm\": 1.0, \"width_cm\": 0.5, \"depth_cm\": 0.2, \"drainage_amount\": \"heavy\"}",
            "sync_version": 1,
            "is_current": True,
        }
    ],
    5: [
        {
            "id": 5,
            "patient_id": 5,
            "org_id": "ORG-103",
            "pcc_assessment_id": 20005,
            "assessment_type": "Weekly Wound Information Sheet",
            "status": "Complete",
            "assessment_date": "2026-05-14",
            "completion_date": "2026-05-14",
            "template_id": 5,
            "assessment_type_description": "Quarterly",
            "raw_json": "{\"wound_type\": \"pressure_ulcer\", \"stage\": 4, \"location\": \"Sacrum\", \"length_cm\": 2.8, \"width_cm\": 1.5, \"depth_cm\": 0.6, \"drainage_amount\": \"moderate\"}",
            "sync_version": 1,
            "is_current": True,
        }
    ],
    6: [
        {
            "id": 6,
            "patient_id": 6,
            "org_id": "ORG-103",
            "pcc_assessment_id": 20006,
            "assessment_type": "Weekly Wound Information Sheet",
            "status": "Complete",
            "assessment_date": "2026-05-15",
            "completion_date": "2026-05-15",
            "template_id": 5,
            "assessment_type_description": "Quarterly",
            "raw_json": "{\"wound_type\": \"pressure_ulcer\", \"stage\": 3, \"location\": \"Sacrum\", \"length_cm\": 2.2, \"width_cm\": 1.1, \"depth_cm\": 0.3, \"drainage_amount\": \"light\"}",
            "sync_version": 1,
            "is_current": True,
        }
    ],
}


def build_fixture_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "fixture": True})
        if path == "/":
            return httpx.Response(200, json={"message": FIXTURE_NOTICE})
        if path == "/pcc/patients":
            facility_id = int(params["facility_id"])
            rows = list(_PATIENTS_BY_FACILITY[facility_id])
            since = params.get("since")
            if since:
                rows = [row for row in rows if row["last_modified_at"] >= since]
            return httpx.Response(200, json=rows)
        if path == "/pcc/diagnoses":
            return httpx.Response(200, json=list(_DIAGNOSES_BY_PATIENT[params["patient_id"]]))
        if path == "/pcc/coverage":
            return httpx.Response(200, json=list(_COVERAGE_BY_PATIENT[params["patient_id"]]))
        if path == "/pcc/notes":
            patient_id = int(params["patient_id"])
            rows = list(_NOTES_BY_PATIENT_ID[patient_id])
            since = params.get("since")
            if since:
                rows = [row for row in rows if row["effective_date"] >= since]
            return httpx.Response(200, json=rows)
        if path == "/pcc/assessments":
            patient_id = int(params["patient_id"])
            rows = list(_ASSESSMENTS_BY_PATIENT_ID[patient_id])
            since = params.get("since")
            if since:
                rows = [row for row in rows if row["assessment_date"] >= since]
            return httpx.Response(200, json=rows)
        return httpx.Response(404, json={"detail": f"unknown fixture path: {path}"})

    return httpx.MockTransport(handler)
