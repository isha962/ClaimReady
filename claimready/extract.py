from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .db import Database
from .models import (
    AssessmentRecord,
    ExtractionResult,
    FieldConflictRecord,
    FieldEvidenceRecord,
    ProgressNoteRecord,
    WoundCandidateRecord,
)


SUPPORTED_WOUND_TYPES = {
    "pressure ulcer": "pressure_ulcer",
    "pressure injury": "pressure_ulcer",
    "diabetic foot ulcer": "diabetic_foot_ulcer",
    "diabetic ulcer": "diabetic_foot_ulcer",
    "venous stasis ulcer": "venous_stasis_ulcer",
    "venous ulcer": "venous_stasis_ulcer",
    "arterial ulcer": "arterial_ulcer",
    "surgical site infection": "surgical_site_infection",
    "ssi": "surgical_site_infection",
    "abscess": "abscess",
    "burn": "burn",
}

DRAINAGE_MAP = {
    "scant": "light",
    "minimal": "light",
    "small": "light",
    "light": "light",
    "moderate": "moderate",
    "heavy": "heavy",
    "copious": "heavy",
    "large": "heavy",
    "none": "none",
    "no drainage": "none",
    "dry": "none",
    "unknown": "unknown",
    "indeterminate": "unknown",
    "unable to assess": "unknown",
    "not assessed": "unknown",
    "not recorded": "unknown",
    "not specified": "unknown",
}

LOCATION_MAP = {
    "sacral": "Sacrum",
    "sacrum": "Sacrum",
    "right heel": "Right Heel",
    "left heel": "Left Heel",
    "coccyx": "Coccyx",
    "heel": "Heel",
    "foot": "Foot",
    "right foot": "Right Foot",
    "left foot": "Left Foot",
}

NEGATED_RE = re.compile(r"\b(?:no|denies|without|negative for)\b.*\bwound\b|\bno open wounds?\b", re.IGNORECASE)
HEALED_RE = re.compile(r"\b(?:healed|resolved|closed|historical|previously)\b", re.IGNORECASE)
STAGE_RE = re.compile(r"\bstage\s*(?P<stage>(?:\d+|[ivx]+|unstageable))\b", re.IGNORECASE)
MEASUREMENT_RE = re.compile(
    r"(?:(?:meas(?:urements?)?\s*)?)"
    r"(?P<length>\d+(?:\.\d+)?)\s*[x×]\s*"
    r"(?P<width>\d+(?:\.\d+)?)\s*[x×]\s*"
    r"(?P<depth>\d+(?:\.\d+)?)\s*cm\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class _ValueMatch:
    field_name: str
    candidate_value: str | None
    normalized_value: str | None
    source_excerpt: str | None
    extraction_method: str
    confidence: float


def parse_assessment_record(record: dict[str, Any], *, patient_external_id: str | None) -> WoundCandidateRecord:
    parsed = _parse_assessment_values(record)
    source_record_id = str(record["id"])
    candidate_key = f"assessment:{source_record_id}:1"
    source_excerpt = record.get("raw_json")
    evidence = _build_evidence(
        candidate_key=candidate_key,
        source_type="assessment",
        source_record_id=source_record_id,
        source_date=record.get("assessment_date"),
        source_excerpt=source_excerpt,
        extraction_method="assessment_raw_json",
        confidence=0.95,
        parsed_values=parsed,
    )
    conflicts = _build_conflicts(
        candidate_key=candidate_key,
        source_type="assessment",
        source_record_id=source_record_id,
        source_date=record.get("assessment_date"),
        source_excerpt=source_excerpt,
        parsed_values=parsed,
    )
    return WoundCandidateRecord(
        candidate_key=candidate_key,
        patient_internal_id=int(record["patient_id"]),
        patient_external_id=patient_external_id,
        source_type="assessment",
        source_record_id=source_record_id,
        source_date=record.get("assessment_date"),
        wound_index=1,
        documentation_state=parsed.get("documentation_state", "active"),
        wound_type=parsed.get("wound_type"),
        pressure_ulcer_stage=parsed.get("pressure_ulcer_stage"),
        location=parsed.get("location"),
        length_cm=_to_float(parsed.get("length_cm")),
        width_cm=_to_float(parsed.get("width_cm")),
        depth_cm=_to_float(parsed.get("depth_cm")),
        drainage_amount=parsed.get("drainage_amount"),
        extraction_method="assessment_raw_json",
        confidence=0.95,
        source_excerpt=source_excerpt,
        raw_source_text=None,
        raw_source_json=record.get("raw_json"),
        conflict_count=len(conflicts),
        field_evidence=evidence,
        field_conflicts=conflicts,
    )


def parse_progress_note_record(record: dict[str, Any], *, patient_external_id: str | None) -> list[WoundCandidateRecord]:
    note_text = record.get("note_text") or ""
    sections = _split_note_sections(note_text)
    records: list[WoundCandidateRecord] = []
    for index, section in enumerate(sections, start=1):
        parsed = _parse_note_values(section)
        source_record_id = str(record["id"])
        candidate_key = f"progress_note:{source_record_id}:{index}"
        method = parsed.get("extraction_method", "structured_note_labels")
        confidence = parsed.get("confidence", 0.8)
        evidence = _build_evidence(
            candidate_key=candidate_key,
            source_type="progress_note",
            source_record_id=source_record_id,
            source_date=record.get("effective_date"),
            source_excerpt=section.strip(),
            extraction_method=method,
            confidence=confidence,
            parsed_values=parsed,
        )
        conflicts = _build_conflicts(
            candidate_key=candidate_key,
            source_type="progress_note",
            source_record_id=source_record_id,
            source_date=record.get("effective_date"),
            source_excerpt=section.strip(),
            parsed_values=parsed,
        )
        records.append(
            WoundCandidateRecord(
                candidate_key=candidate_key,
                patient_internal_id=int(record["patient_id"]),
                patient_external_id=patient_external_id,
                source_type="progress_note",
                source_record_id=source_record_id,
                source_date=record.get("effective_date"),
                wound_index=index,
                documentation_state=parsed.get("documentation_state", "active"),
                wound_type=parsed.get("wound_type"),
                pressure_ulcer_stage=parsed.get("pressure_ulcer_stage"),
                location=parsed.get("location"),
                length_cm=_to_float(parsed.get("length_cm")),
                width_cm=_to_float(parsed.get("width_cm")),
                depth_cm=_to_float(parsed.get("depth_cm")),
                drainage_amount=parsed.get("drainage_amount"),
                extraction_method=method,
                confidence=confidence,
                source_excerpt=section.strip(),
                raw_source_text=note_text,
                raw_source_json=None,
                conflict_count=len(conflicts),
                field_evidence=evidence,
                field_conflicts=conflicts,
            )
        )
    return records


def extract_wound_candidates(database: Database) -> ExtractionResult:
    database.initialize()
    database.clear_wound_candidates()

    candidates: list[WoundCandidateRecord] = []
    with database.connect() as connection:
        patients = {
            int(row["id"]): row["patient_id"]
            for row in connection.execute("select id, patient_id from patients")
        }
        for row in connection.execute("select * from assessments order by id"):
            candidates.append(
                parse_assessment_record(dict(row), patient_external_id=patients.get(int(row["patient_id"])))
            )
        for row in connection.execute("select * from progress_notes order by id"):
            candidates.extend(
                parse_progress_note_record(dict(row), patient_external_id=patients.get(int(row["patient_id"])))
            )

    field_evidence = [evidence for candidate in candidates for evidence in candidate.field_evidence]
    field_conflicts = [conflict for candidate in candidates for conflict in candidate.field_conflicts]

    database.insert_wound_candidates(candidates)
    database.insert_field_evidence(field_evidence)
    database.insert_field_conflicts(field_conflicts)

    source_counts = {
        "assessment": sum(1 for candidate in candidates if candidate.source_type == "assessment"),
        "progress_note": sum(1 for candidate in candidates if candidate.source_type == "progress_note"),
    }
    return ExtractionResult(
        candidate_count=len(candidates),
        evidence_count=len(field_evidence),
        conflict_count=len(field_conflicts),
        source_counts=source_counts,
    )


def _parse_assessment_values(record: dict[str, Any]) -> dict[str, Any]:
    raw_json = record.get("raw_json")
    try:
        payload = json.loads(raw_json) if raw_json else {}
    except json.JSONDecodeError:
        payload = {}
    return _parse_payload_values(
        payload,
        source_text=raw_json,
        extraction_method="assessment_raw_json",
        confidence=0.95,
        allow_conflict=False,
    )


def _parse_note_values(section: str) -> dict[str, Any]:
    values: dict[str, Any] = {
        "documentation_state": _detect_documentation_state(section),
    }
    label_values = _parse_labeled_fields(section)
    if label_values:
        values.update(label_values)

    values["confidence"] = 0.8
    values["extraction_method"] = "structured_note_labels"

    if values.get("documentation_state") == "negated":
        values.setdefault("wound_type", None)
        values.setdefault("pressure_ulcer_stage", None)
        values.setdefault("location", None)
        values.setdefault("length_cm", None)
        values.setdefault("width_cm", None)
        values.setdefault("depth_cm", None)
        values.setdefault("drainage_amount", None)
        return values

    measurements = _find_measurements(section)
    stage_matches = _find_stages(section)
    wound_type_matches = _find_wound_types(section)
    location_matches = _find_locations(section)
    drainage_matches = _find_drainage(section)

    for field_name, matches in (
        ("length_cm", [match[0] for match in measurements if match[0] is not None]),
        ("width_cm", [match[1] for match in measurements if match[1] is not None]),
        ("depth_cm", [match[2] for match in measurements if match[2] is not None]),
    ):
        values[field_name], conflicts = _resolve_numeric(values.get(field_name), matches)
        if conflicts:
            values[f"{field_name}_conflicts"] = conflicts

    values["wound_type"], wound_type_conflicts = _resolve_string(values.get("wound_type"), wound_type_matches)
    values["pressure_ulcer_stage"], stage_conflicts = _resolve_string(values.get("pressure_ulcer_stage"), stage_matches)
    values["location"], location_conflicts = _resolve_string(values.get("location"), location_matches)
    values["drainage_amount"], drainage_conflicts = _resolve_string(values.get("drainage_amount"), drainage_matches)
    if wound_type_conflicts:
        values["wound_type_conflicts"] = wound_type_conflicts
    if stage_conflicts:
        values["pressure_ulcer_stage_conflicts"] = stage_conflicts
    if location_conflicts:
        values["location_conflicts"] = location_conflicts
    if drainage_conflicts:
        values["drainage_amount_conflicts"] = drainage_conflicts
    return values


def _parse_payload_values(
    payload: dict[str, Any],
    *,
    source_text: str | None,
    extraction_method: str,
    confidence: float,
    allow_conflict: bool,
) -> dict[str, Any]:
    values = {
        "documentation_state": "active",
        "wound_type": _normalize_wound_type(str(payload.get("wound_type"))) if payload.get("wound_type") is not None else None,
        "pressure_ulcer_stage": _normalize_stage(payload.get("stage")),
        "location": _normalize_location(str(payload.get("location"))) if payload.get("location") is not None else None,
        "length_cm": _to_float(payload.get("length_cm")),
        "width_cm": _to_float(payload.get("width_cm")),
        "depth_cm": _to_float(payload.get("depth_cm")),
        "drainage_amount": _normalize_drainage(str(payload.get("drainage_amount"))) if payload.get("drainage_amount") is not None else None,
        "extraction_method": extraction_method,
        "confidence": confidence,
    }
    if allow_conflict and source_text:
        stage_matches = _find_stages(source_text)
        stage_unique = _unique(stage_matches)
        if len([match for match in stage_unique if match is not None]) > 1:
            values["pressure_ulcer_stage"] = None
            values["pressure_ulcer_stage_conflicts"] = stage_unique
        drainage_matches = _find_drainage(source_text)
        drainage_unique = _unique(drainage_matches)
        if len([match for match in drainage_unique if match is not None]) > 1:
            values["drainage_amount"] = None
            values["drainage_amount_conflicts"] = drainage_unique
    return values


def _build_evidence(
    *,
    candidate_key: str,
    source_type: str,
    source_record_id: str,
    source_date: str | None,
    source_excerpt: str | None,
    extraction_method: str,
    confidence: float,
    parsed_values: dict[str, Any],
) -> list[FieldEvidenceRecord]:
    evidence: list[FieldEvidenceRecord] = []
    for field_name in ("wound_type", "pressure_ulcer_stage", "location", "length_cm", "width_cm", "depth_cm", "drainage_amount", "documentation_state"):
        value = parsed_values.get(field_name)
        if value is None:
            continue
        evidence.append(
            FieldEvidenceRecord(
                candidate_key=candidate_key,
                field_name=field_name,
                candidate_value=_stringify(value),
                normalized_value=_stringify(value),
                source_type=source_type,
                source_record_id=source_record_id,
                source_date=source_date,
                source_excerpt=source_excerpt,
                extraction_method=extraction_method,
                confidence=confidence,
            )
        )

    return evidence


def _build_conflicts(
    *,
    candidate_key: str,
    source_type: str,
    source_record_id: str,
    source_date: str | None,
    source_excerpt: str | None,
    parsed_values: dict[str, Any],
) -> list[FieldConflictRecord]:
    conflicts: list[FieldConflictRecord] = []
    for field_name in ("pressure_ulcer_stage", "drainage_amount", "wound_type", "location", "length_cm", "width_cm", "depth_cm"):
        conflict_values = parsed_values.get(f"{field_name}_conflicts")
        if not conflict_values:
            continue
        conflicts.append(
            FieldConflictRecord(
                candidate_key=candidate_key,
                field_name=field_name,
                conflicting_values_json=json.dumps(conflict_values, sort_keys=True),
                source_type=source_type,
                source_record_id=source_record_id,
                source_date=source_date,
                source_excerpt=source_excerpt,
                extraction_method=parsed_values.get("extraction_method", "unknown"),
                confidence=0.5,
            )
        )
    return conflicts


def _parse_labeled_fields(section: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    location = _first_match(r"(?im)^\s*location\s*:\s*(?P<value>[^\n]+)", section)
    wound_type = _first_match(r"(?im)^\s*wound type\s*:\s*(?P<value>[^\n]+)", section)
    drainage = _first_match(r"(?im)^\s*drainage\s*:\s*(?P<value>[^\n]+)", section)
    length = _first_match(r"(?im)^\s*length\s*:\s*(?P<value>[\d.]+)\s*cm", section)
    width = _first_match(r"(?im)^\s*width\s*:\s*(?P<value>[\d.]+)\s*cm", section)
    depth = _first_match(r"(?im)^\s*depth\s*:\s*(?P<value>[\d.]+)\s*cm", section)

    if location:
        values["location"] = _normalize_location(location)
    if wound_type:
        values["wound_type"] = _normalize_wound_type(wound_type)
    if drainage:
        values["drainage_amount"] = _normalize_drainage(drainage)
    if length:
        values["length_cm"] = _to_float(length)
    if width:
        values["width_cm"] = _to_float(width)
    if depth:
        values["depth_cm"] = _to_float(depth)

    stage = _first_match(r"(?i)\bstage\s*(?P<value>(?:\d+|[ivx]+|unstageable))\b", section)
    if stage:
        values["pressure_ulcer_stage"] = _normalize_stage(stage)
    elif re.search(r"(?i)\bunstageable\b", section):
        values["pressure_ulcer_stage"] = "unstageable"
    if not values.get("wound_type"):
        if re.search(r"pressure\s+ulcer|pressure\s+injury", section, re.IGNORECASE):
            values["wound_type"] = "pressure_ulcer"
        elif re.search(r"diabetic\s+foot\s+ulcer|foot\s+ulcer", section, re.IGNORECASE):
            values["wound_type"] = "diabetic_foot_ulcer"
        elif re.search(r"venous\s+(?:stasis\s+)?ulcer", section, re.IGNORECASE):
            values["wound_type"] = "venous_stasis_ulcer"
        elif re.search(r"arterial\s+ulcer", section, re.IGNORECASE):
            values["wound_type"] = "arterial_ulcer"
        elif re.search(r"surgical\s+site\s+infection|ssi\b", section, re.IGNORECASE):
            values["wound_type"] = "surgical_site_infection"
        elif re.search(r"\babscess\b", section, re.IGNORECASE):
            values["wound_type"] = "abscess"
        elif re.search(r"\bburn\b", section, re.IGNORECASE):
            values["wound_type"] = "burn"

    return values


def _split_note_sections(note_text: str) -> list[str]:
    markers = list(
        re.finditer(r"(?i)\bwound\s+(?:one|two|1|2|first|second)\b", note_text)
    )
    if not markers:
        return [note_text]
    sections: list[str] = []
    for index, marker in enumerate(markers):
        start = marker.start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(note_text)
        sections.append(note_text[start:end].strip(" ;\n"))
    return sections


def _find_measurements(text: str) -> list[tuple[float | None, float | None, float | None]]:
    matches: list[tuple[float | None, float | None, float | None]] = []
    for match in MEASUREMENT_RE.finditer(text):
        matches.append(
            (
                _to_float(match.group("length")),
                _to_float(match.group("width")),
                _to_float(match.group("depth")),
            )
        )
    length = _first_match(r"(?i)\blength\s*:\s*([\d.]+)\s*cm", text)
    width = _first_match(r"(?i)\bwidth\s*:\s*([\d.]+)\s*cm", text)
    depth = _first_match(r"(?i)\bdepth\s*:\s*([\d.]+)\s*cm", text)
    if length or width or depth:
        matches.append((_to_float(length), _to_float(width), _to_float(depth)))
    return matches


def _find_stages(text: str) -> list[str]:
    stages: list[str] = []
    for match in STAGE_RE.finditer(text):
        normalized = _normalize_stage(match.group("stage"))
        if normalized is not None:
            stages.append(normalized)
    if re.search(r"\bunstageable\b", text, re.IGNORECASE):
        stages.append("unstageable")
    return stages


def _find_wound_types(text: str) -> list[str]:
    wound_types: list[str] = []
    for phrase, normalized in SUPPORTED_WOUND_TYPES.items():
        if re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE):
            wound_types.append(normalized)
    return wound_types


def _find_locations(text: str) -> list[str]:
    found: list[tuple[str, str]] = []
    lower_text = text.lower()
    for phrase, normalized in sorted(LOCATION_MAP.items(), key=lambda item: -len(item[0])):
        if phrase in lower_text:
            found.append((phrase, normalized))
    explicit = _first_match(r"(?i)\blocation\s*:\s*([^\n]+)", text)
    if explicit:
        normalized = _normalize_location(explicit)
        if normalized:
            found.append((explicit.lower(), normalized))

    if not found:
        return []

    selected: list[str] = []
    for phrase, normalized in found:
        if normalized in {"Heel", "Foot"}:
            if any(other_normalized in {"Left Heel", "Right Heel", "Left Foot", "Right Foot"} for _, other_normalized in found):
                continue
        if normalized == "Sacrum" and any(other_normalized == "Coccyx" for _, other_normalized in found):
            continue
        if normalized not in selected:
            selected.append(normalized)
    return selected


def _find_drainage(text: str) -> list[str]:
    drainage: list[str] = []
    lower = text.lower()
    for phrase, normalized in DRAINAGE_MAP.items():
        if phrase in lower:
            drainage.append(normalized)
    explicit = _first_match(r"(?i)\bdrainage\s*:\s*([^\n]+)", text)
    if explicit:
        normalized = _normalize_drainage(explicit)
        if normalized:
            drainage.append(normalized)
    return drainage


def _detect_documentation_state(text: str) -> str:
    lower = text.lower()
    if NEGATED_RE.search(text):
        return "negated"
    if "unstageable" in lower:
        return "active"
    if "healed" in lower:
        return "healed"
    if "resolved" in lower:
        return "resolved"
    if "closed" in lower:
        return "closed"
    if "historical" in lower or "previously" in lower:
        return "historical"
    return "active"


def _normalize_wound_type(value: str) -> str | None:
    lower = value.lower().replace("_", " ")
    for phrase, normalized in SUPPORTED_WOUND_TYPES.items():
        if phrase in lower:
            return normalized
    exact_map = {
        "pressure ulcer": "pressure_ulcer",
        "pressure injury": "pressure_ulcer",
        "diabetic foot ulcer": "diabetic_foot_ulcer",
        "diabetic ulcer": "diabetic_foot_ulcer",
        "venous stasis ulcer": "venous_stasis_ulcer",
        "venous ulcer": "venous_stasis_ulcer",
        "arterial ulcer": "arterial_ulcer",
        "surgical site infection": "surgical_site_infection",
        "ssi": "surgical_site_infection",
    }
    return exact_map.get(lower)


def _normalize_stage(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text == "unstageable":
        return "unstageable"
    if text.isdigit():
        return str(int(text))
    roman_map = {
        "i": "1",
        "ii": "2",
        "iii": "3",
        "iv": "4",
    }
    return roman_map.get(text)


def _normalize_drainage(value: str) -> str | None:
    lower = value.lower()
    for phrase, normalized in DRAINAGE_MAP.items():
        if phrase in lower:
            return normalized
    return "unknown"


def _normalize_location(value: str) -> str | None:
    lower = value.strip().lower()
    for phrase, normalized in LOCATION_MAP.items():
        if phrase in lower:
            return normalized
    if not lower:
        return None
    return value.strip().title()


def _resolve_string(existing: Any, matches: Iterable[str]) -> tuple[Any, list[Any]]:
    unique_matches = [match for match in _unique(matches) if match is not None]
    if len(unique_matches) > 1:
        return None, unique_matches
    if unique_matches:
        return unique_matches[0], []
    return existing, []


def _resolve_numeric(existing: Any, matches: Iterable[float | None]) -> tuple[Any, list[Any]]:
    unique_matches = [match for match in _unique(matches) if match is not None]
    if len(unique_matches) > 1:
        return None, unique_matches
    if unique_matches:
        return unique_matches[0], []
    return existing, []


def _unique(values: Iterable[Any]) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    if "value" in match.groupdict():
        return match.group("value").strip()
    return match.group(1).strip()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
    return str(value)
